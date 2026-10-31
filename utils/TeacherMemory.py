# utils/TeacherMemory.py

"""AI 老师的长期记忆：一个会随课更新的“学生模型”。

不是聊天记录，也不是单词表，而是老师对学生稳定特征的判断：

- level: 当前水平（CEFR / 雅思区间 + 一句依据）
- style: 表达习惯（句长、时态、用词、填充词……）
- strengths: 已经稳的东西
- weaknesses: 反复出现、还没解决的问题（带出现次数和最近时间）
- methods: 对这个学生有效的讲法/练法
- outcomes: 课堂成果（训练临时记忆销毁前留下的“这次练成了什么”）
- recent: 最近几次课练了什么、下次先抓什么

学生明确说「记住……」的内容不在这里，统一写进「关于你」（`Memory` 的 tutor
persona），本文件只管“老师对学生的稳定判断”。

练习**开始和结束**各用一次轻量 LLM 调用更新（中间重说不重复调用），
合并与去重都在本地完成；数据在 data/teacher_memory.json（已 gitignore），
每轮注入老师 prompt。稳定特征只收“会跨答案复现的模式”，一句里的具体
错误留在 recent 摘要里，避免学生模型被同一句话的细节填满。
"""

import difflib
import logging
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path

from utils.llm import call_llm_json, as_text
from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = Path(
    os.getenv("TEACHER_MEMORY_PATH")
    or (_PROJECT_ROOT / "data" / "teacher_memory.json")
)
_LOCK = threading.RLock()

_MAX_STYLE = 5
_MAX_STRENGTHS = 5
_MAX_WEAKNESSES = 5
_MAX_METHODS = 4
_MAX_OUTCOMES = 6
_MAX_RECENT = 4
_MAX_EXAM_NOTES = 12
_MAX_TEXT = 80
_SIMILARITY = 0.78

# 这些是老师内部流程词，不该写进学生模型。
_META_RE = re.compile(
    r"(清单|checklist|划掉|还剩\s*\d*\s*项|第\s*\d+\s*项|该项过关|这一项过了)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return date.today().isoformat()


def _one_line(text, limit: int = _MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _empty() -> dict:
    return {
        "version": 1,
        "level": {"band": "", "note": "", "updated": ""},
        "style": [],
        "strengths": [],
        "weaknesses": [],
        "methods": [],
        "outcomes": [],
        "recent": [],
        "exam_notes": [],
        "updated_at": "",
    }


def _clean_fact(
    raw, *, drop_meta: bool = True, drop_specific: bool = False
) -> dict | None:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    text = _one_line(raw.get("text"))
    if not text or (drop_meta and _META_RE.search(text)):
        return None
    # 稳定特征只收模式；带两个以上英文实词的多半是某一句的具体内容
    # （“which irritated me…”“errand 被写成 errands”），留在 recent 就够。
    if drop_specific and len(re.findall(r"[A-Za-z]{2,}", text)) >= 2:
        return None
    stamp = _now()
    return {
        "text": text,
        "count": max(1, int(raw.get("count") or 1)),
        "first": str(raw.get("first") or stamp),
        "last": str(raw.get("last") or stamp),
    }


def _clean_list(
    value, limit: int, *, drop_meta: bool = True, drop_specific: bool = False
) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for raw in value:
        fact = _clean_fact(raw, drop_meta=drop_meta, drop_specific=drop_specific)
        if fact and fact["text"] not in {item["text"] for item in result}:
            result.append(fact)
    return result[:limit]


def _normalise(raw) -> dict:
    memory = _empty()
    if not isinstance(raw, dict):
        return memory
    level = raw.get("level") if isinstance(raw.get("level"), dict) else {}
    level_note = _one_line(level.get("note"), 40)
    if len(re.findall(r"[A-Za-z]{2,}", level_note)) >= 2:
        # 旧数据里的“依据”常是某一句的具体例子，不是水平判断。
        level_note = ""
    memory["level"] = {
        "band": _one_line(level.get("band"), 20),
        "note": level_note,
        "updated": str(level.get("updated") or ""),
    }
    memory["style"] = _clean_list(raw.get("style"), _MAX_STYLE, drop_specific=True)
    memory["strengths"] = _clean_list(
        raw.get("strengths"), _MAX_STRENGTHS, drop_specific=True
    )
    memory["weaknesses"] = _clean_list(
        raw.get("weaknesses"), _MAX_WEAKNESSES, drop_specific=True
    )
    memory["methods"] = _clean_list(
        raw.get("methods"), _MAX_METHODS, drop_specific=True
    )
    outcomes = raw.get("outcomes") if isinstance(raw.get("outcomes"), list) else []
    memory["outcomes"] = [
        {
            "text": _one_line(item.get("text"), 120),
            "date": str(item.get("date") or ""),
            "lesson": str(item.get("lesson") or ""),
        }
        for item in outcomes[:_MAX_OUTCOMES]
        if isinstance(item, dict) and _one_line(item.get("text"), 120)
    ]
    recent = raw.get("recent") if isinstance(raw.get("recent"), list) else []
    memory["recent"] = [
        {
            "date": str(item.get("date") or ""),
            "summary": _one_line(item.get("summary"), 120),
            "next": _one_line(item.get("next"), 80),
            "lesson": str(item.get("lesson") or ""),
        }
        for item in recent[: _MAX_RECENT]
        if isinstance(item, dict) and (item.get("summary") or item.get("next"))
    ]
    exam_notes = raw.get("exam_notes") if isinstance(raw.get("exam_notes"), list) else []
    memory["exam_notes"] = [
        {
            "date": str(item.get("date") or ""),
            "source": _one_line(item.get("source"), 20),
            "summary": _one_line(item.get("summary"), 160),
        }
        for item in exam_notes[: _MAX_EXAM_NOTES]
        if isinstance(item, dict) and _one_line(item.get("summary"), 160)
    ]
    for key in ("style", "strengths", "weaknesses", "methods"):
        memory[key] = _dedupe(memory[key])
    _reconcile(memory)
    memory["updated_at"] = str(raw.get("updated_at") or "")
    return memory


def _load_unlocked() -> dict:
    return _normalise(load_json(MEMORY_PATH, {}))


def load_memory() -> dict:
    with _LOCK:
        return _load_unlocked()


def _save_unlocked(memory: dict) -> None:
    memory["updated_at"] = _now()
    save_json(MEMORY_PATH, memory)


def clear_memory() -> None:
    with _LOCK:
        save_json(MEMORY_PATH, _empty())


def _normalise_text(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def _similar(a: str, b: str) -> bool:
    na, nb = _normalise_text(a), _normalise_text(b)
    if not na or not nb:
        return False
    if na == nb or (len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na)):
        return True
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    # 中文短标签差一两个字很常见（“时态混用”/“时态容易混”），
    # 短串用更松的阈值，长句仍按 0.78。
    if len(na) <= 20 and len(nb) <= 20:
        return ratio >= 0.62
    return ratio >= _SIMILARITY


def _same_pattern(a: str, b: str) -> bool:
    """判断两条记忆是否在说同一个模式；比 _similar 更严，用于跨列表消歧。"""
    na, nb = _normalise_text(a), _normalise_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 6 and len(nb) >= 6 and (na in nb or nb in na):
        return True
    # “which 从句动词已加 -s” / “which 从句动词仍用复数”前缀相同，
    # 只是“已/仍”不同；共享足够长的前缀就按同一模式处理。
    if len(os.path.commonprefix([na, nb])) >= 8:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.82


def _dedupe(items: list[dict]) -> list[dict]:
    """读入时合并近义条目，保留较高计数和最新时间，避免旧数据越看越乱。"""
    result: list[dict] = []
    for item in items:
        existing = next((x for x in result if _similar(x["text"], item["text"])), None)
        if existing is None:
            result.append(item)
            continue
        existing["count"] = max(existing["count"], item["count"])
        if item.get("first") and (
            not existing.get("first") or item["first"] < existing["first"]
        ):
            existing["first"] = item["first"]
        if item.get("last") and (
            not existing.get("last") or item["last"] > existing["last"]
        ):
            existing["last"] = item["last"]
    result.sort(
        key=lambda item: (item.get("last", ""), item.get("count", 1)),
        reverse=True,
    )
    return result


def _merge_facts(
    items: list[dict],
    additions,
    limit: int,
    max_new: int | None = None,
    *,
    drop_meta: bool = True,
    drop_specific: bool = False,
) -> list[dict]:
    texts = []
    if isinstance(additions, str):
        texts = [additions]
    elif isinstance(additions, list):
        texts = [as_text(item) for item in additions]
    stamp = _now()
    added = 0
    for raw in texts:
        text = _one_line(raw)
        if not text or (drop_meta and _META_RE.search(text)):
            continue
        if drop_specific and len(re.findall(r"[A-Za-z]{2,}", text)) >= 2:
            continue
        existing = next((item for item in items if _similar(item["text"], text)), None)
        if existing:
            existing["count"] += 1
            existing["last"] = stamp
            continue
        if max_new is not None and added >= max_new:
            continue
        items.append(
            {"text": text, "count": 1, "first": stamp, "last": stamp}
        )
        added += 1
    items.sort(key=lambda item: (item["last"], item["count"]), reverse=True)
    return items[:limit]


def _apply_update(
    memory: dict, data: dict, lesson_id: str = "", *, traits: bool = True
) -> dict:
    """合并一次更新。

    traits=False 时只写“最近练了什么 / 有效练法”，不把这一轮的句子级
    观察塞进 STYLE / SOLID / WEAK。稳定特征只在课的开始和结束时判断，
    否则一节课的 6 次重说会把学生模型填满同一句话的细节。
    """
    if traits:
        level = data.get("level") if isinstance(data.get("level"), dict) else None
        if level:
            band = _one_line(level.get("band"), 20)
            note = _one_line(level.get("note"), 40)
            if band or note:
                memory["level"] = {
                    "band": band or memory["level"].get("band", ""),
                    "note": note or memory["level"].get("note", ""),
                    "updated": _now(),
                }

        memory["style"] = _merge_facts(
            memory["style"],
            data.get("style_add"),
            _MAX_STYLE,
            max_new=1,
            drop_specific=True,
        )
        memory["strengths"] = _merge_facts(
            memory["strengths"],
            data.get("strength_add"),
            _MAX_STRENGTHS,
            max_new=1,
            drop_specific=True,
        )
        memory["weaknesses"] = _merge_facts(
            memory["weaknesses"],
            data.get("weakness_add"),
            _MAX_WEAKNESSES,
            max_new=1,
            drop_specific=True,
        )

        resolved = data.get("resolved")
        if isinstance(resolved, str):
            resolved = [resolved]
        if isinstance(resolved, list):
            for text in resolved:
                value = _one_line(text)
                if value:
                    memory["weaknesses"] = [
                        item
                        for item in memory["weaknesses"]
                        if not _same_pattern(item["text"], value)
                    ]

        _reconcile(memory)

    memory["methods"] = _merge_facts(
        memory["methods"],
        data.get("method_add"),
        _MAX_METHODS,
        max_new=1,
        drop_specific=True,
    )

    summary = _one_line(data.get("session_summary"), 120)
    next_focus = _one_line(data.get("next_focus"), 80)
    if summary or next_focus:
        existing = None
        if lesson_id:
            existing = next(
                (
                    item
                    for item in memory["recent"]
                    if item.get("lesson") == lesson_id
                ),
                None,
            )
        if existing:
            existing["summary"] = summary or existing.get("summary", "")
            existing["next"] = next_focus or existing.get("next", "")
            existing["date"] = _today()
        else:
            memory["recent"].insert(
                0,
                {
                    "date": _today(),
                    "summary": summary,
                    "next": next_focus,
                    "lesson": lesson_id,
                },
            )
        memory["recent"] = memory["recent"][: _MAX_RECENT]
    return memory


def _reconcile(memory: dict) -> None:
    """同一条模式同时出现在 SOLID 和 WEAK 时，只保留更新的那条。"""
    for strength in list(memory["strengths"]):
        for weakness in list(memory["weaknesses"]):
            if not _same_pattern(strength["text"], weakness["text"]):
                continue
            if strength.get("last", "") >= weakness.get("last", ""):
                memory["weaknesses"].remove(weakness)
            else:
                memory["strengths"].remove(strength)
            break


def memory_text(memory: dict | None = None) -> str:
    """给 prompt 用的紧凑文本；没有记忆时返回空串。"""
    memory = load_memory() if memory is None else memory
    level = memory.get("level") or {}
    lines = []

    if level.get("band") or level.get("note"):
        parts = [part for part in (level.get("band"), level.get("note")) if part]
        lines.append("LEVEL: " + " — ".join(parts))

    def block(
        title: str, items: list[dict], with_count: bool = False, limit: int = 5
    ) -> None:
        if not items:
            return
        parts = []
        for item in items[:limit]:
            text = item["text"]
            if with_count and item["count"] > 1:
                text += f"（{item['count']} 次）"
            parts.append(text)
        lines.append(f"{title}: " + "；".join(parts))

    block("STYLE", memory.get("style") or [], limit=4)
    block("SOLID", memory.get("strengths") or [], limit=5)
    block("WEAK", memory.get("weaknesses") or [], with_count=True, limit=5)
    block("WORKS", memory.get("methods") or [], with_count=True, limit=3)

    recent = memory.get("recent") or []
    if recent:
        lines.append("RECENT: " + "；".join(
            f"{item['date']} {item['summary']}".strip() for item in recent[:1]
        ))
        next_focus = next((item["next"] for item in recent if item["next"]), "")
        if next_focus:
            lines.append("NEXT: " + next_focus)

    outcomes = memory.get("outcomes") or []
    if outcomes:
        lines.append(
            "CLASS OUTCOMES: "
            + "；".join(
                f"{item['date']} {item['text']}".strip() for item in outcomes[:3]
            )
        )

    exam_notes = memory.get("exam_notes") or []
    if exam_notes:
        lines.append(
            "EXAM-SESSION PROBLEMS: "
            + "；".join(
                f"{item['date']} {item['source']} {item['summary']}".strip()
                for item in exam_notes[:3]
            )
        )
    return "\n".join(lines)


def _update_prompt(memory: dict, lesson: dict) -> str:
    return f"""You maintain a teacher's long-term memory of one IELTS student.
Model the student, not the conversation. Keep only stable, useful patterns.

CURRENT MEMORY
{memory_text(memory) or "(empty)"}

NEW LESSON
Question: {lesson.get('question', '')}
Student answer: {lesson.get('answer', '')}
Teacher feedback: {lesson.get('feedback', '')}
Target points: {lesson.get('targets', '')}
Results: {lesson.get('results', '')}
Current focus: {lesson.get('focus', '')}
Lesson status: {lesson.get('status', '')}
Criteria: {lesson.get('checklist', '')}

UPDATE TYPE: {lesson.get('phase', 'final')} (start = lesson just began; final = this lesson is finished)

UPDATE RULES
- This is a student model, not a lesson log. STYLE / SOLID / WEAK are only for patterns
  likely to repeat across different answers. Specific words, mistakes or examples from
  this one sentence belong in session_summary, never in those lists.
- If UPDATE TYPE is start: return empty style_add / strength_add / weakness_add and
  level null. Only session_summary, next_focus and method_add are useful at this point.
- level: only on final, and only with real evidence. Use a conservative range such as
  "5.5-6.0"; note is one general Chinese sentence (<= 40 chars), no sentence-specific
  evidence. Return null if unsure.
- style_add: 0-1 stable way this student expresses (sentence length, tense habit,
  vocabulary habits, fillers), <= 30 Chinese chars. Pattern, not content.
- strength_add: 0-1 thing that now looks solid across answers. Never "this sentence
  passed" or a reference to the checklist.
- weakness_add: 0-1 recurring pattern, not the whole sentence. Good examples:
  "which 从句动词单复数" / "原因状语从句缺结果"; bad examples:
  "which irritated me 之后没有具体结果，因果链断了" / "errand 被写成复数".
  <= 30 Chinese chars.
- resolved: exact WEAK text from CURRENT MEMORY that this lesson proves is fixed;
  [] if none. Do not invent resolutions.
- method_add: 0-1 what worked or did not work in your teaching (e.g. "对比句比讲规则有效").
- session_summary: one short Chinese line about what was practised and whether it
  improved. No quotes, no checklist narration.
- next_focus: one short pattern to work on next, not the full sentence.
- Never mention 清单 / checklist / 划掉 / 还剩几项 / 第几项 / 过关.
- No transcript, no long quotes, no invented facts.
- If nothing stable, return empty arrays.

Output JSON only:
{{"level": {{"band": "", "note": ""}} | null, "style_add": [], "strength_add": [], "weakness_add": [], "method_add": [], "resolved": [], "session_summary": "", "next_focus": ""}}
"""


def update_from_lesson(
    *,
    question: str,
    answer: str,
    feedback: str,
    targets: str = "",
    results: str = "",
    lesson_id: str = "",
    followup: bool = False,
    focus: str = "",
    status: str = "",
    checklist="",
    final: bool = True,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """更新学生模型；失败时保留旧记忆。

    final=False 用于一次练习的第一轮：只更新“最近练了什么 / 有效练法”，
    稳定特征留到这一轮结束时再判断。provider/model 由主线程传入，因为
    这个函数通常在后台线程里跑，读不到 Streamlit 的 session_state。
    """
    if isinstance(checklist, list):
        checklist = "；".join(str(item) for item in checklist)
    current = load_memory()
    prompt = _update_prompt(
        current,
        {
            "question": (question or "")[:800],
            "answer": (answer or "")[:1600],
            "feedback": (feedback or "")[:1200],
            "targets": (targets or "")[:500],
            "results": (results or "")[:500],
            "focus": (focus or "")[:100],
            "status": (status or "")[:20],
            "checklist": (checklist or "")[:500],
            "phase": "final" if final else "start",
        },
    )
    try:
        data = call_llm_json(
            prompt,
            temperature=0.2,
            num_predict=800,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("更新老师记忆失败")
        return current
    if not isinstance(data, dict) or not data:
        return current

    with _LOCK:
        memory = _load_unlocked()
        memory = _apply_update(memory, data, lesson_id, traits=final)
        _save_unlocked(memory)
    return memory


def remember_outcome(summary: str, lesson_id: str = "") -> dict:
    """把一次课的成果写进「课堂成果」。

    训练期的临时记忆（TrainingMemory）在计划更新时会被销毁；销毁前用它
    留下的摘要调用这里。同一课只保留一条，重复调用以最新内容为准。
    """
    text = _one_line(summary, 120)
    if not text:
        return load_memory()
    lesson = str(lesson_id or "")
    with _LOCK:
        memory = _load_unlocked()
        existing = None
        if lesson:
            existing = next(
                (
                    item
                    for item in memory["outcomes"]
                    if item.get("lesson") == lesson
                ),
                None,
            )
        elif memory["outcomes"]:
            first = memory["outcomes"][0]
            if not first.get("lesson") and first["text"] == text:
                existing = first
        if existing is None:
            memory["outcomes"].insert(
                0, {"text": text, "date": _today(), "lesson": lesson}
            )
            memory["outcomes"] = memory["outcomes"][:_MAX_OUTCOMES]
        else:
            existing["text"] = text
            existing["date"] = _today()
        _save_unlocked(memory)
        return memory


_REMEMBER_RE = re.compile(
    r"(记住|记牢|记一下|记下|别忘了|不要忘|不能忘|别再忘|我说过|跟你说过|"
    r"和你讲过|强调过|remember (this|that)|don'?t forget|never forget|"
    r"i told you|i'?ve told you|keep (this )?in mind)",
    re.IGNORECASE,
)


def remember_exam_session(source_label: str, summary: str) -> dict:
    """把一场求助里反复出现的考试问题记进「考试过程」。

    和「课堂成果」并列：那边记“这节课练成了什么”，这边记“考试里卡在哪”。
    由 HelpMemory.finish() 在求助结束时调用，写完整场摘要后临时记忆即被清空。
    同一天同一来源的重复写入以最新内容为准，不叠加刷屏。
    """
    text = _one_line(summary, 160)
    if not text:
        return load_memory()
    source = _one_line(source_label, 20)
    with _LOCK:
        memory = _load_unlocked()
        today = _today()
        existing = next(
            (
                item
                for item in memory["exam_notes"]
                if item.get("date") == today and item.get("source") == source
            ),
            None,
        )
        if existing is None:
            memory["exam_notes"].insert(
                0, {"date": today, "source": source, "summary": text}
            )
            memory["exam_notes"] = memory["exam_notes"][:_MAX_EXAM_NOTES]
        else:
            existing["summary"] = text
        _save_unlocked(memory)
        return memory


def looks_like_remember(text: str) -> bool:
    return bool(_REMEMBER_RE.search(str(text or "")))


def render_sidebar(title: str = "老师的记忆") -> None:
    import streamlit as st

    memory = load_memory()
    with st.sidebar.expander(f"🧠 {title}", expanded=False):
        if not memory_text(memory):
            st.caption("还没有形成记忆。练几次之后，这里会出现你的水平、表达特点、薄弱点、有效练法和课堂成果。")
            return
        level = memory.get("level") or {}
        if level.get("band") or level.get("note"):
            st.markdown(
                f"**水平**：{level.get('band') or '—'}"
                + (f" — {level['note']}" if level.get("note") else "")
            )
        for title, key in (
            ("表达特点", "style"),
            ("已掌握", "strengths"),
            ("待巩固", "weaknesses"),
            ("有效练法", "methods"),
            ("课堂成果", "outcomes"),
        ):
            items = memory.get(key) or []
            if items:
                st.caption(f"**{title}**")
                for item in items:
                    text = item["text"]
                    if key == "outcomes" and item.get("date"):
                        text = f"{item['date']}｜{text}"
                    suffix = (
                        f"（{item['count']} 次）"
                        if key in ("weaknesses", "methods") and item["count"] > 1
                        else ""
                    )
                    st.caption(f"- {text}{suffix}")
        exam_notes = memory.get("exam_notes") or []
        if exam_notes:
            st.caption("**考试过程**")
            for item in exam_notes:
                st.caption(f"- {item['date']}｜{item['source']}｜{item['summary']}")


__all__ = [
    "clear_memory",
    "load_memory",
    "looks_like_remember",
    "memory_text",
    "remember_exam_session",
    "remember_outcome",
    "render_sidebar",
    "update_from_lesson",
]
