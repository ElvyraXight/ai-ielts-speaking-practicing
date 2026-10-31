# utils/TutorLead.py

"""老师的“主模型”：学生听到的每一句话都由这一层说出来。

后台的老师（Tutor / 陪练 / 词典）只给内部 brief，不直接对学生说话。
主模型负责：

- 先回应学生刚说的内容，再决定怎么教；
- 把 brief 里的纠错、例句、目标词原样保留，但换成正常人说话的口气；
- 自己判断这份 brief 里的练习此刻合不合适（keep_practice）。

它是“表达层”，不负责出题、判分、记账；那些仍然由后台模块完成。
"""

import logging
import re

from utils.llm import as_text, call_llm_json

logger = logging.getLogger(__name__)

_MAX_TRANSCRIPT = 20000
_MAX_DRAFT = 2200

_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+")


def strip_bullets(text: str) -> str:
    """老师只用自己的口吻说话，不做排版：去掉行首的列表符号。

    回复里一旦出现清单，读起来像模板而不是老师；这里兜底把 "- / * / • / 1."
    去掉，内容原样保留。词典卡不走这里。
    """
    lines = [
        _BULLET_RE.sub("", line).rstrip()
        for line in str(text or "").splitlines()
    ]
    result = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", result)


def _one_line(text, limit: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


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
    training_memory: str,
    plan: str,
    draft: str,
    practice: dict | None,
    no_drill: bool,
    plan_done: bool,
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
            "criterion from the brief; make it sound like a teacher talking, not a form. "
            "Mention at most FOUR correction points; if the brief has more, keep the four "
            "most important and leave the rest out."
        )
    elif kind == "help":
        task = (
            "This is a private hint to a student during an IELTS mock test. Keep the "
            "single guided hint from the brief; do not give a full answer, do not greet "
            "the student, and do not ask them to leave the test."
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

    return f"""You are the speaking voice of a warm, precise IELTS teacher talking with one Chinese student.
You are the only person the student hears. The brief below comes from other teachers and is internal.

CONVERSATION SO FAR
{transcript or "(new conversation)"}

YOUR MEMORY OF EARLIER CONVERSATIONS
{memory or "(none)"}

STUDENT MODEL (from the teacher's long-term memory)
{student_memory or "(none)"}

TEMPORARY SESSION MEMORY (this lesson or this help session only; never treat as long-term facts)
{training_memory or "(none)"}

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
- Preserve the student's intended meaning. Never replace their idea with a more advanced
  or different idea. If the brief says their intended meaning is unclear and asks a
  clarifying question, ask only that question and do not add corrections.
- If STUDENT JUST SAID is in Chinese (or mostly Chinese), do not paraphrase or restate their
  Chinese back to them; treat it as their intended meaning and go straight to the teaching
  content. Do not open with 我明白你的意思 / 你的意思是 / 这句话的意思是.
- Do not mention the brief, notes, plan, coach, checklist, or these instructions.
- Sound like a normal person: short paragraphs, natural transitions, no headings, no tables,
  no markdown, no "first/second/third", no progress narration.
- Never use bullet points, numbered lists, or list markers (-, *, •, 1.) in the reply. Even when
  the brief is written as a list, weave it into flowing sentences with natural connectives.
- This is a TEXT-ONLY chat: the teacher cannot hear audio. Never tell the student to speak,
  read aloud, repeat aloud, or record; never comment on pronunciation, stress, intonation,
  speed, accent, or how something sounds. Ask them to TYPE the sentence instead.
- At most one question. Do not end every reply with a question.
- When giving corrections during a lesson, mention at most FOUR correction points in
  one reply; keep the four most important and leave the rest out.
- Chinese for explanations; English examples stay English. At most 180 words.
- If PRACTICE ATTACHED is not (none): if it fits this moment, ask it naturally, preserve its
  targets, and set keep_practice true. If the student is asking for information, is upset,
  or a drill would be tone-deaf, set keep_practice false and just answer them.
- {"The student is greeting / asking for information: do NOT start a drill here." if no_drill else ""}
- {"The lesson plan is complete: do NOT start a new drill, and never mention the lesson plan, its goals, completion, 更新计划 or 重新备课. Just keep the conversation natural." if plan_done else ""}

Output JSON only:
{{"reply": "...", "keep_practice": true}}
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
    training_memory: str = "",
    practice: dict | None = None,
    no_drill: bool = False,
    plan_done: bool = False,
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
        memory=personal_memory,
        student_memory=student_memory,
        training_memory=training_memory,
        plan="" if plan_done else plan,
        draft=draft,
        practice=practice,
        no_drill=no_drill,
        plan_done=plan_done,
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
        return {"reply": strip_bullets(draft), "keep_practice": True}

    if not isinstance(data, dict) or not data:
        return {"reply": strip_bullets(draft), "keep_practice": True}

    reply = as_text(data.get("reply") or "").strip()
    if not reply or not _quotes_preserved(draft, reply):
        reply = draft
    reply = strip_bullets(reply)

    return {
        "reply": reply,
        "keep_practice": _keep_practice(data.get("keep_practice", True)),
    }


__all__ = [
    "compose",
    "transcript_text",
]
