# utils/Tutor.py

"""对话式雅思口语老师。

复用 utils/Part2.py 里的模型配置（Ollama / DeepSeek API），
所以 Part 2 用哪个模型，这个老师就用哪个模型。
"""

import re

from utils.Part2 import _as_text, _call_llm

_TUTOR_PROMPT = """You are a warm, precise IELTS Speaking tutor for a Chinese learner.

CONTEXT
__CONTEXT__

CONVERSATION SO FAR
__HISTORY__

STUDENT'S NEW MESSAGE
__MESSAGE__

RULES
- Explain in Simplified Chinese; keep every English example sentence in English.
- Be concise: at most 170 words. Plain lines starting with "- " are fine.
- If the student asks you to check or improve an answer:
  1) start with 2-3 corrections in the exact form: 原句「...」→ 改为「...」（中文原因）;
  2) then give ONE improved version of the whole answer at Band 7+;
  3) keep the student's own facts (places, people, events). Never invent a new city, person or trip.
- If the student asks for expressions or sentence patterns: give 2-3 natural spoken options, each with a short Chinese note.
- Never invent errors. If a sentence is already correct, say so and offer one small upgrade.
- End with ONE short follow-up question that keeps the student speaking.
- No headings, no tables, no markdown code fences.
- Use 「」 around quoted English sentences, never double quotes.

Output JSON only: {"reply": "..."}
"""


def _build_history(messages, limit: int = 10) -> str:
    lines = []
    for msg in messages[-limit:]:
        content = re.sub(r"\s+", " ", str(msg.get("content", ""))).strip()[:700]
        if not content:
            continue
        role = "Tutor" if msg.get("role") == "assistant" else "Student"
        lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(no previous messages)"


def ask_tutor(message: str, history, cue_card: str = "", student_answer: str = "") -> str:
    """根据上下文回答学生；模型统一走 Part 2 的 provider 配置。"""
    context_parts = []
    if (cue_card or "").strip():
        context_parts.append("Current Part 2 cue card:\n" + cue_card.strip())
    if (student_answer or "").strip():
        context_parts.append(
            "The student's current Part 2 answer:\n" + student_answer.strip()[:2000]
        )

    prompt = (
        _TUTOR_PROMPT.replace("__CONTEXT__", "\n\n".join(context_parts) or "(none)")
        .replace("__HISTORY__", _build_history(history))
        .replace("__MESSAGE__", (message or "").strip() or "(empty)")
    )
    data = _call_llm(prompt, temperature=0.7, num_predict=700, fallback="")
    reply = _as_text(data.get("reply") or data.get("_fallback") or "").strip()
    return reply or "（老师这边暂时没接上，再问一次试试？）"
