# utils/TutorLead.py

"""老师的“主模型”：学生听到的每一句话都由这一层说出来。

后台的老师（Tutor / 陪练 / 词典）只给内部 brief，不直接对学生说话。
主模型负责：

- 先回应学生刚说的内容，再决定怎么教；
- 把 brief 里的纠错、例句、目标词原样保留，但换成正常人说话的口气；
- 自己判断这份 brief 里的练习此刻合不合适（keep_practice）；
- 维护一整场对话的滚动记忆，跨会话继续用（data/tutor_dialogue.json）。

它是“表达层”，不负责出题、判分、记账；那些仍然由后台模块完成。
"""

import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from utils.llm import as_text, call_llm_json
from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = Path(
    os.getenv("TUTOR_DIALOGUE_PATH")
    or (_PROJECT_ROOT / "data" / "tutor_dialogue.json")
)
_LOCK = threading.RLock()

_MAX_SUMMARY = 800
_MAX_TRANSCRIPT = 20000
_MAX_DRAFT = 2200


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text, limit: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def load_memory() -> dict:
    with _LOCK:
        data = load_json(MEMORY_PATH, {})
    if not isinstance(data, dict):
        return {"version": 1, "summary": "", "updated_at": ""}
    return {
        "version": 1,
        "summary": _one_line(data.get("summary"), _MAX_SUMMARY),
        "updated_at": str(data.get("updated_at") or ""),
    }


def memory_text() -> str:
    summary = load_memory().get("summary") or ""
    return ("CONVERSATION MEMORY:\n" + summary) if summary else ""


def save_summary(summary: str) -> dict:
    memory = load_memory()
    value = _one_line(summary, _MAX_SUMMARY)
    if not value or value == memory.get("summary"):
        return memory
    memory["summary"] = value
    memory["updated_at"] = _now()
    with _LOCK:
        save_json(MEMORY_PATH, memory)
    return memory


def clear_memory() -> None:
    with _LOCK:
        save_json(MEMORY_PATH, {"version": 1, "summary": "", "updated_at": _now()})


def transcript_text(messages, limit: int = _MAX_TRANSCRIPT) -> str:
    """把整场对话压成给主模型看的文本；词典卡只留词和释义。"""
    lines = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        items = message.get("items") or []
        if items:
            item_lines = []
            for item in items[:8]:
                text = str(item.get("text") or "").strip()
                meaning = str(item.get("meaning") or "").strip()
                if text:
                    item_lines.append(f"{text} — {meaning}".strip(" —"))
            if item_lines:
                content = (content + " " + " / ".join(item_lines)).strip()
        if not content:
            continue
        role = "Teacher" if message.get("role") == "assistant" else "Student"
        lines.append(f"{role}: {content[:900]}")
    text = "\n".join(lines)
    if len(text) > limit:
        text = "[earlier conversation omitted]\n" + text[-limit:]
    return text


def _quotes_preserved(draft: str, reply: str) -> bool:
    """brief 里的「原句」/「改句」必须原样出现，避免主模型把纠错改坏。"""
    quotes = re.findall(r"「[^」]{1,200}」", draft or "")
    if not quotes:
        return True
    return all(quote in (reply or "") for quote in quotes)


def _keep_practice(raw) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() not in ("false", "0", "no", "否")
    return raw is not False


def _practice_text(practice: dict | None) -> str:
    if not isinstance(practice, dict):
        return "(none)"
    question = _one_line(practice.get("question"), 500)
    targets = [
        _one_line(item, 80)
        for item in (practice.get("targets") or [])
        if _one_line(item, 80)
    ]
    if not question:
        return "(none)"
    return question + ("\nTargets: " + " / ".join(targets) if targets else "")


def _prompt(
    *,
    kind: str,
    message: str,
    transcript: str,
    memory: str,
    student_memory: str,
    plan: str,
    draft: str,
    practice: dict | None,
    no_drill: bool,
    plan_done: bool,
    update_summary: bool,
) -> str:
    practice_block = _practice_text(practice)
    if kind == "greeting":
        task = (
            "This is the opening line of a new lesson. Greet the student naturally like a "
            "real teacher; do not start a drill or list features."
        )
    elif kind == "coach":
        task = (
            "This is feedback on one practice answer. Keep every correction and every "
            "criterion from the brief; make it sound like a teacher talking, not a form."
        )
    elif kind == "dictionary":
        task = (
            "This is a dictionary lookup. Write ONE short natural lead-in; do not list "
            "the definitions because the cards below your message already show them."
        )
    else:
        task = (
            "This is a normal tutoring turn. Answer what the student just said, then use "
            "the brief only as much as the moment needs."
        )

    summary_rule = (
        "Also update your rolling memory: one short Chinese paragraph (<=150 characters) "
        "covering what this conversation is about, what the student wants, what happened, "
        "and what is unresolved. It is your continuity across sessions, not a lesson log."
        if update_summary
        else 'Return "summary": ""; do not change the stored conversation memory.'
    )

    return f"""You are the speaking voice of a warm, precise IELTS teacher talking with one Chinese student.
You are the only person the student hears. The brief below comes from other teachers and is internal.

CONVERSATION SO FAR
{transcript or "(new conversation)"}

YOUR MEMORY OF EARLIER CONVERSATIONS
{memory or "(none)"}

STUDENT MODEL (from the teacher's long-term memory)
{student_memory or "(none)"}

THIS LESSON
{plan or "(none)"}

STUDENT JUST SAID
{message or "(empty)"}

EXPERT BRIEF (internal advice; never mention, quote, or expose it)
{draft[:_MAX_DRAFT] or "(none)"}

PRACTICE ATTACHED
{practice_block}

TASK
{task}

RULES
- Respond to the student's actual message first. If they ask a question, answer it. If they
  are greeting or chatting, chat back before teaching. Never ignore what they said.
- Keep every correction, quoted English phrase, example, target word and fact from the
  brief exactly. Do not add new errors, new teaching points, or new facts.
- Do not mention the brief, notes, plan, coach, checklist, or these instructions.
- Sound like a normal person: short paragraphs, natural transitions, no headings, no tables,
  no markdown, no "first/second/third", no progress narration.
- This is a TEXT-ONLY chat: the teacher cannot hear audio. Never tell the student to speak,
  read aloud, repeat aloud, or record; never comment on pronunciation, stress, intonation,
  speed, accent, or how something sounds. Ask them to TYPE the sentence instead.
- At most one question. Do not end every reply with a question.
- Chinese for explanations; English examples stay English. At most 180 words.
- If PRACTICE ATTACHED is not (none): if it fits this moment, ask it naturally, preserve its
  targets, and set keep_practice true. If the student is asking for information, is upset,
  or a drill would be tone-deaf, set keep_practice false and just answer them.
- {"The student is greeting / asking for information: do NOT start a drill here." if no_drill else ""}
- {"The current lesson plan is complete: do NOT start a new drill. If the student asks to practise, explain that this lesson's goals are done and a new plan will be prepared on the next start (or they can click 重新备课)." if plan_done else ""}
- {summary_rule}

Output JSON only:
{{"reply": "...", "summary": "...", "keep_practice": true}}
"""


def compose(
    *,
    kind: str,
    message: str,
    transcript: str,
    draft: str,
    plan: str = "",
    student_memory: str = "",
    personal_memory: str = "",
    practice: dict | None = None,
    no_drill: bool = False,
    plan_done: bool = False,
    update_summary: bool = True,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """让主模型把 brief 说成一句正常人会说的话；失败时原样返回 brief。"""
    draft = str(draft or "").strip()
    if not draft:
        return {"reply": "", "keep_practice": True}

    prompt = _prompt(
        kind=kind,
        message=message,
        transcript=transcript,
        memory=personal_memory or memory_text(),
        student_memory=student_memory,
        plan=plan,
        draft=draft,
        practice=practice,
        no_drill=no_drill,
        plan_done=plan_done,
        update_summary=update_summary,
    )
    try:
        data = call_llm_json(
            prompt,
            temperature=0.7,
            num_predict=700,
            fallback={},
            timeout=60,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("主模型表达失败")
        return {"reply": draft, "keep_practice": True}

    if not isinstance(data, dict) or not data:
        return {"reply": draft, "keep_practice": True}

    reply = as_text(data.get("reply") or "").strip()
    if not reply or not _quotes_preserved(draft, reply):
        reply = draft

    if update_summary:
        summary = _one_line(data.get("summary"), _MAX_SUMMARY)
        if summary:
            try:
                save_summary(summary)
            except Exception:
                logger.exception("保存对话记忆失败")

    return {
        "reply": reply,
        "keep_practice": _keep_practice(data.get("keep_practice", True)),
    }


__all__ = [
    "clear_memory",
    "compose",
    "load_memory",
    "memory_text",
    "save_summary",
    "transcript_text",
]
