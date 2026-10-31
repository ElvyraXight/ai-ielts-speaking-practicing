# utils/HelpCoach.py

"""临时帮助会话的后台专家：只给建议，不直接对学生说话。"""

from __future__ import annotations

import logging
import re

from utils.IeltsRubric import for_part
from utils.llm import call_llm_json

logger = logging.getLogger(__name__)

_PRESET_ANSWER_PROMPT = """You are an IELTS Speaking examiner-coach preparing PRIVATE reference material for one question.
The student never sees this text; it is the fixed standard every later hint must follow.

CURRENT TEST CONTEXT
{context}

RECENT TEST CONVERSATION
{transcript}

ABOUT THIS STUDENT
{memory}

IELTS SPEAKING STANDARD — the reference answer must satisfy this
{rubric}

TASK
Write ONE model answer this student could give to the CURRENT question. Natural spoken
English, 2-4 sentences, Band 7-8, using this student's own details when the conversation
shows them. Answer the current question only; no explanations, no Chinese, no lists.

Output JSON only: {{"answer": "..."}}
"""


def preset_model_answer(
    *,
    context_text: str,
    transcript: str,
    memory: str = "",
    part: str = "",
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """为当前题目生成一份固定的参考回答（学生看不到，只用来定标准）。"""
    prompt = _PRESET_ANSWER_PROMPT.format(
        context=context_text or "(none)",
        transcript=transcript or "(no test conversation yet)",
        memory=memory or "(none)",
        rubric=for_part(part),
    )
    try:
        data = call_llm_json(
            prompt,
            temperature=0.4,
            num_predict=300,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("生成参考回答失败")
        return ""
    if not isinstance(data, dict):
        return ""
    answer = re.sub(r"[\u4e00-\u9fa5]+", " ", str(data.get("answer") or ""))
    answer = re.sub(r"\s+", " ", answer).strip().strip('"').strip()
    return answer[:600]


def one_hint(text: str, limit: int = 260) -> str:
    """只保留一段、最多约 260 字的提示，避免一次灌多条建议。"""
    value = str(text or "").strip()
    if not value:
        return ""
    paragraph = value.split("\n\n")[0].strip()
    if len(paragraph) <= limit:
        return paragraph
    cut = paragraph[:limit]
    boundary = max(
        cut.rfind("。"),
        cut.rfind("！"),
        cut.rfind("？"),
        cut.rfind(". "),
        cut.rfind("; "),
    )
    if boundary >= 60:
        cut = cut[: boundary + 1]
    return cut.rstrip("，,；;。.!！?？ ") + "…"


def advise(
    *,
    source: str,
    context_text: str,
    transcript: str,
    student_message: str,
    student_answer: str = "",
    model_answer: str = "",
    session_memory: str = "",
    help_history: str = "",
    repeated_attempt: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    part = "Part 2" if source == "part2" else "Part 1 / Part 3 考官对话"
    if source == "part2":
        if student_answer:
            attempt = (
                "The student's Part 2 answer above (STUDENT'S CURRENT PART 2 ANSWER). "
                "Their help-chat message is the question, not the answer."
            )
        else:
            attempt = (
                "No Part 2 answer yet — they have not written one on the 讲个故事 page. "
                "Help with the cue card, or ask for one short version first."
            )
    else:
        attempt = "The newest Student line in HELP-CHAT SO FAR."
    prompt = f"""You are a private IELTS Speaking examiner-coach sitting beside the
student during a mock speaking test. The examiner cannot hear you.

CURRENT TEST CONTEXT
{context_text or "(none)"}

RECENT TEST CONVERSATION
{transcript or "(no test conversation yet)"}

STUDENT'S CURRENT PART 2 ANSWER — the answer they want help with (empty outside Part 2)
{student_answer or "(none)"}

STUDENT'S PRIVATE QUESTION
{student_message}

HELP-CHAT SO FAR (verbatim; the last Student line is the newest attempt)
{help_history or "(this is the first question)"}

REPEATED ATTEMPT
{"yes — the student just sent the same sentence again" if repeated_attempt else "no"}

CURRENT ATTEMPT TO JUDGE
{attempt}

PRESET REFERENCE ANSWER FOR THIS QUESTION (fixed internal standard; the student never sees this text)
{(model_answer or "").strip() or "(none)"}

IELTS SPEAKING STANDARD — judge the candidate's attempt and aim the hint at this
{for_part("part2" if source == "part2" else "part1")}

WHAT YOU ALREADY TOLD THEM IN THIS HELP SESSION
{session_memory or "(nothing yet)"}

YOUR ROLE
- The student is in {part}; help with exactly what they are stuck on.
- Use IELTS Speaking assessment rules: task response, coherence, lexical resource,
  grammatical range and accuracy, and natural spoken delivery.
- Give ONE guided hint at a time — never the finished answer, never the whole reference
  answer, and never a list of everything.
- Base every hint on the PRESET REFERENCE ANSWER. Its wording and its requirements are the
  standard for this question: do not suggest one version and then reverse it in a later
  turn. Same question, same target.
- Use the reference to name the specific gap: say which part is missing or wrong, and what
  to change (meaning, structure, connector, word class), or offer an A/B choice. Give a
  fragment at most, never the whole reference sentence.
- In Part 2, when STUDENT'S CURRENT PART 2 ANSWER is present, work from its actual wording:
  point at the tense, connector or word that needs work. Never ask the student to paste the
  answer into the chat — you already have it.
- Judge CURRENT ATTEMPT TO JUDGE as the current attempt; the test context is background only.
  Compare it literally (including punctuation and spacing) with your previous hint and with
  the reference answer.
- If the change you asked for is already in the current attempt, do not ask for it again:
  say it is done and stop.
- The reference answer is one good version, not a script. Accept any equally natural
  wording; never ask the student to copy its punctuation or phrasing.
- If REPEATED ATTEMPT is yes: do not rephrase the same hint. If the sentence is acceptable,
  confirm it and stop; otherwise point at one different, concrete element.
- Do not ask the student to retype a sentence that already matches the reference. If their
  latest attempt is already fine, say it is fine and stop; do not invent a new requirement.
- Never repeat a hint that is already in WHAT YOU ALREADY TOLD THEM. If the student asks the
  same thing again, give the NEXT step (or say plainly that this point was already settled
  and ask them to say the whole sentence once), instead of rephrasing the same advice.
- First understand what the student is trying to say. If their intended meaning is
  unclear, ask one short clarifying question instead of guessing.
- If their English expresses a different meaning, point out the meaning gap before
  correcting grammar.
- Keep explanations in Simplified Chinese; English examples stay English.
- If there is a real repeatable issue, also return up to 2 short Chinese labels for it.

Output JSON only:
{{"hint": "...", "issues": ["..."], "reason": "short Chinese reason"}}
"""
    try:
        data = call_llm_json(
            prompt,
            temperature=0.3,
            num_predict=700,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("帮助会话专家建议失败")
        return {"hint": "", "issues": [], "reason": "error"}
    if not isinstance(data, dict):
        data = {}
    hint = str(data.get("hint") or "").strip()[:1200]
    issues = [
        str(item).strip()[:40]
        for item in (data.get("issues") or [])
        if str(item).strip()
    ][:2]
    return {
        "hint": hint,
        "issues": issues,
        "reason": str(data.get("reason") or "")[:160],
    }


__all__ = ["advise", "one_hint", "preset_model_answer"]
