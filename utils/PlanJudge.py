# utils/PlanJudge.py

"""独立的“计划点完成裁判”。

它不负责教，也不看陪练内部的状态；只看：

- 老师当前这条可见回复；
- 老师上一条可见回复；
- 当前计划里还没打勾的点。

判定规则：
- 老师开始问下一个点 → 上一个点通过；
- 老师让大家做一个综合练习，明确用到多个点 → 这些点通过；
- 只是“不错/很好”但还在改同一个点 → 不打勾。
"""

import logging
import re

from utils.llm import call_llm_json

logger = logging.getLogger(__name__)

_KEYWORDS = (
    "可以了",
    "可以",
    "行了",
    "过了",
    "过关",
    "过关了",
    "这条过",
    "这个点过",
    "完成",
    "没问题",
    "用对",
    "说对",
    "到位",
    "达标",
    "掌握",
    "通过",
    "不用改",
    "不用再改",
    "就这样",
    "算过",
    "收尾",
    "下一个",
    "接下来",
    "换一个",
    "换个点",
    "再试一个",
    "下一题",
    "综合",
    "一起用",
    "都用上",
    "组合",
    "连起来",
    "完整回答",
    "good",
    "correct",
    "done",
    "complete",
    "perfect",
    "that's it",
    "you've got it",
    "no need to change",
    "nailed it",
    "next",
)


_ALL_DONE_RE = re.compile(
    r"(都过关|都过啦|全部过关|三个表达都|三个点都|全部完成|都完成了|今天.*完成"
    r"|all done|all (?:points|expressions).*(?:done|complete)"
    r"|everything.*(?:done|complete))",
    re.IGNORECASE,
)


def needs_review(teacher_message: str) -> bool:
    text = str(teacher_message or "").casefold()
    return any(keyword.casefold() in text for keyword in _KEYWORDS)


def _format_points(points) -> str:
    lines = []
    for index, point in enumerate(points or [], 1):
        key = str(point.get("source_key") or "").strip()
        label = str(point.get("label") or "").strip()
        if key and label:
            lines.append(f"{index}. {key} — {label}")
    return "\n".join(lines) or "(none)"


def _point_terms(source_key: str, label: str) -> list[str]:
    raw = str(source_key or "").strip()
    kind, _, target = raw.partition(":")
    if not target:
        target = raw
    if kind == "expression":
        for arrow in ("→", "->"):
            if arrow in target:
                target = target.rsplit(arrow, 1)[1]
    label_text = re.split(r"[（(]", str(label or ""), maxsplit=1)[0]
    terms = []
    for term in (target, label_text):
        term = term.strip().strip("\"'“”‘’「」")
        if len(term) >= 2 and term.casefold() not in {t.casefold() for t in terms}:
            terms.append(term)
    return terms


def _word_pattern(term: str) -> str:
    return rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])"


def has_student_evidence(
    source_key: str, label: str, student_message: str
) -> bool:
    """学生这条消息里是否真的用了这个点（含常见词形变化）。"""
    text = str(student_message or "").casefold()
    if not text:
        return False
    for term in _point_terms(source_key, label):
        lowered = term.casefold()
        if re.search(_word_pattern(lowered), text):
            return True
        if re.fullmatch(r"[a-z][a-z' -]*", lowered):
            stem = re.sub(
                r"(ation|ition|tion|sion|ion|ing|ed|es|s)$", "", lowered
            )
            if len(stem) >= 4 and re.search(
                rf"(?<![A-Za-z]){re.escape(stem)}", text
            ):
                return True
    return False


def judge(
    teacher_message: str,
    previous_teacher_message: str,
    pending_points,
    *,
    current_target: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """返回 {"completed": [{"source_key": "...", "evidence": "..."}], "reason": "..."}。"""
    if not needs_review(teacher_message):
        return {"completed": [], "reason": "no review keyword"}

    pending = [
        point
        for point in (pending_points or [])
        if isinstance(point, dict) and str(point.get("source_key") or "").strip()
    ]
    if not pending:
        return {"completed": [], "reason": "no pending points"}

    target = ""
    if isinstance(current_target, dict):
        target = (
            f"{current_target.get('source_key') or ''} — "
            f"{current_target.get('label') or ''}"
        )
    prompt = f"""You are a strict completion judge for an IELTS lesson plan.
You do not teach. You only decide which pending plan points the teacher has
clearly accepted as complete in the CURRENT message.

PENDING PLAN POINTS
{_format_points(pending)}

CURRENT TARGET
{target or "(none)"}

PREVIOUS TEACHER MESSAGE
{str(previous_teacher_message or "").strip() or "(none)"}

CURRENT TEACHER MESSAGE (visible to the student)
{str(teacher_message or "").strip()}

RULES
- If the CURRENT message moves on to a different/next point, the CURRENT TARGET
  is complete, even if the teacher does not say "done".
- If the CURRENT message starts an integrated practice that explicitly uses
  several pending points, mark ALL those explicitly used points complete.
- If the CURRENT message is still correcting the same point or asking for another
  attempt, mark nothing.
- A generic "不错/很好/good" is NOT completion unless the message clearly accepts
  this attempt as finished.
- Only mark source_keys from PENDING PLAN POINTS. Never invent a point.
- Use the previous teacher message only as context; do not mark from it alone.
- Output JSON only:
  {{"completed": [{{"source_key": "...", "evidence": "short Chinese reason"}}],
   "reason": "short Chinese reason"}}
"""
    try:
        data = call_llm_json(
            prompt,
            temperature=0.1,
            num_predict=350,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("计划完成裁判调用失败")
        return {"completed": [], "reason": "judge error"}
    if not isinstance(data, dict):
        return {"completed": [], "reason": "bad judge output"}

    valid = {str(point["source_key"]).casefold() for point in pending}
    completed = []
    for raw in data.get("completed") or []:
        if isinstance(raw, str):
            raw = {"source_key": raw}
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("source_key") or "").strip()
        if not key or key.casefold() not in valid:
            continue
        if any(item["source_key"].casefold() == key.casefold() for item in completed):
            continue
        completed.append(
            {
                "source_key": key,
                "evidence": str(raw.get("evidence") or "")[:160],
            }
        )
    return {
        "completed": completed,
        "reason": str(data.get("reason") or "")[:160],
    }


def _format_conversation(messages, limit: int = 120, chars: int = 500) -> str:
    lines = []
    for message in list(messages or [])[-limit:]:
        if not isinstance(message, dict):
            continue
        role = "Tutor" if message.get("role") == "assistant" else "Student"
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if content:
            lines.append(f"{role}: {content[:chars]}")
    return "\n".join(lines) or "(no conversation)"


def judge_conversation(
    messages,
    pending_points,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """强制检查整场聊天，返回已完成的计划点。"""
    pending = [
        point
        for point in (pending_points or [])
        if isinstance(point, dict) and str(point.get("source_key") or "").strip()
    ]
    if not pending:
        return {"completed": [], "reason": "no pending points"}
    conversation_text = _format_conversation(messages)
    student_text = "\n".join(
        re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        for message in (messages or [])
        if isinstance(message, dict) and message.get("role") == "user"
    )
    prompt = f"""You are a strict completion judge for an IELTS lesson plan.
Read the WHOLE conversation and decide which pending plan points the teacher
has clearly accepted as complete at some point.

PENDING PLAN POINTS
{_format_points(pending)}

CONVERSATION
{conversation_text}

RULES
- A point is complete if the teacher explicitly accepts it ("过关了/可以了/
  完成/没有要改的"), moves on to a different point, or includes it in an
  integrated practice that uses it.
- If the teacher explicitly says all points passed ("三个表达都过关了 /
  今天的内容都完成了"), mark ALL pending points that were covered in that block.
- Later asking for another round, a new example or a small polish does NOT revoke
  an earlier clear acceptance. Only an explicit "这个点还没过/还不算完成" revokes it.
- Generic praise ("不错/很好/good") is not completion if the teacher is still
  correcting or asking for another attempt.
- Only mark source_keys from PENDING PLAN POINTS. Never invent a point.
- Output JSON only:
  {{"completed": [{{"source_key": "...", "evidence": "short Chinese reason"}}],
   "reason": "short Chinese reason"}}
"""
    try:
        data = call_llm_json(
            prompt,
            temperature=0.1,
            num_predict=500,
            fallback={},
            timeout=60,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("整场聊天完成裁判调用失败")
        return {"completed": [], "reason": "judge error"}
    if not isinstance(data, dict):
        data = {}

    valid = {str(point["source_key"]).casefold() for point in pending}
    by_key = {
        str(point["source_key"]).casefold(): point for point in pending
    }
    completed = []
    for raw in data.get("completed") or []:
        if isinstance(raw, str):
            raw = {"source_key": raw}
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("source_key") or "").strip()
        if not key or key.casefold() not in valid:
            continue
        point = by_key.get(key.casefold()) or {}
        if not has_student_evidence(key, point.get("label") or "", student_text):
            continue
        if any(item["source_key"].casefold() == key.casefold() for item in completed):
            continue
        completed.append(
            {
                "source_key": key,
                "evidence": str(raw.get("evidence") or "")[:160],
            }
        )
    # 老师明确说过“全部过关/都完成了”，但模型还是漏判时，强制兜底。
    # 兜底也必须有学生实际使用证据，不能只凭老师一句话。
    if not completed and _ALL_DONE_RE.search(conversation_text):
        completed = [
            {
                "source_key": point["source_key"],
                "evidence": "老师明确说全部/几个表达都过关了",
            }
            for point in pending
            if has_student_evidence(
                point["source_key"], point.get("label") or "", student_text
            )
        ]
    return {
        "completed": completed,
        "reason": str(data.get("reason") or "")[:160],
    }


def judge_message(
    teacher_message: str,
    previous_teacher_message: str,
    pending_points,
    *,
    user_message: str = "",
    last_points=None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """每条老师消息都调用：识别当前在练的点，并判断是否切换。"""
    pending = [
        point
        for point in (pending_points or [])
        if isinstance(point, dict) and str(point.get("source_key") or "").strip()
    ]
    if not pending:
        return {"active_source_keys": [], "completed": [], "reason": "no pending points"}
    last_keys = [
        str(key).strip()
        for key in (last_points or [])
        if str(key).strip()
    ]
    prompt = f"""You are tracking an IELTS lesson plan during a conversation.

PENDING PLAN POINTS
{_format_points(pending)}

LAST TRAINING POINT(S)
{chr(10).join(last_keys) or "(none)"}

PREVIOUS TEACHER MESSAGE
{str(previous_teacher_message or "").strip() or "(none)"}

STUDENT MESSAGE BETWEEN THE TWO TEACHER MESSAGES
{str(user_message or "").strip() or "(none)"}

CURRENT TEACHER MESSAGE
{str(teacher_message or "").strip()}

TASK
1. active_source_keys: which pending points is the CURRENT message currently
   training or asking the student to use? Use source_keys only. [] if the message
   is not training a point.
2. completed: which points are clearly finished.
   - If active_source_keys moves to a different point from LAST TRAINING POINT(S),
     mark the last point complete ONLY IF the student message actually addresses
     the point asked in PREVIOUS TEACHER MESSAGE. If the student changed topic,
     asked something unrelated, or did not answer that point, do not mark it.
   - If the current message explicitly accepts a point as finished, mark it.
   - If the current message asks an integrated practice using several pending
     points, mark all those points complete.
   - If the message is still correcting the same point or asking another attempt,
     mark nothing.
   - Never mark a point outside PENDING PLAN POINTS.
Output JSON only:
{{"active_source_keys": ["..."], "completed": [{{"source_key": "...", "evidence": "短中文原因"}}], "reason": "短中文原因"}}
"""
    try:
        data = call_llm_json(
            prompt,
            temperature=0.1,
            num_predict=450,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("逐条消息计划裁判调用失败")
        return {"active_source_keys": [], "completed": [], "reason": "judge error"}
    if not isinstance(data, dict):
        data = {}
    valid = {str(point["source_key"]).casefold() for point in pending}
    by_key = {
        str(point["source_key"]).casefold(): point for point in pending
    }
    active = []
    for raw in data.get("active_source_keys") or []:
        key = str(raw or "").strip()
        if key.casefold() in valid and key.casefold() not in {
            item.casefold() for item in active
        }:
            active.append(key)
    completed = []
    for raw in data.get("completed") or []:
        if isinstance(raw, str):
            raw = {"source_key": raw}
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("source_key") or "").strip()
        if key.casefold() not in valid:
            continue
        point = by_key.get(key.casefold()) or {}
        if not has_student_evidence(key, point.get("label") or "", user_message):
            continue
        if any(item["source_key"].casefold() == key.casefold() for item in completed):
            continue
        completed.append(
            {
                "source_key": key,
                "evidence": str(raw.get("evidence") or "")[:160],
            }
        )
    return {
        "active_source_keys": active,
        "completed": completed,
        "reason": str(data.get("reason") or "")[:160],
    }


__all__ = [
    "has_student_evidence",
    "judge",
    "judge_conversation",
    "judge_message",
    "needs_review",
]
