# utils/Tutor.py

"""对话式雅思口语老师。

复用 utils/Part2.py 里的模型配置（Ollama / DeepSeek API），
所以 Part 2 用哪个模型，这个老师就用哪个模型。
"""

import re

from utils.Part2 import _as_text, _call_llm
from utils.llm import call_llm_json

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

_EXPLAIN_PROMPT = """The student sent only the material below, with no other instructions. They want you to explain it.

INPUT
__MESSAGE__

TASK
Split the input into distinct items and explain each one.

SPLITTING
- New lines, commas, semicolons, or clearly unrelated words on one line usually mean separate items.
- Keep a coherent phrase or sentence together as ONE item (e.g. "take for granted", "No sooner had he arrived than the meeting began.").
- If the input is one interesting word, phrase or sentence, return one item.
- 1-8 items max; preserve the student's order; do not invent items.

FOR EACH ITEM
- text: exactly as the student wrote it; do not correct spelling or punctuation
- type: "word" | "phrase" | "sentence"
- meaning: concise Simplified Chinese meaning in this context
- usage: one short Chinese note on grammar, register or collocation (optional)
- example: one natural English example (optional; for a full sentence, give a short paraphrase or a note on its structure instead)
- example_zh: Chinese translation of the example (optional)

If the input is a full sentence, explain its overall meaning and one key structure, not word by word.
Keep Chinese explanations concise. English examples stay English.

Output JSON only:
{"intro": "...", "items": [{"text": "...", "type": "word", "meaning": "...", "usage": "...", "example": "...", "example_zh": "..."}]}
"""

_ASK_PREFIX = re.compile(
    r"^\s*(please\s+)?(explain|tell me|what|how|why|translate|correct|improve|rewrite|check|give me|can you|could you|show me)\b",
    re.I,
)


def _build_history(messages, limit: int = 10) -> str:
    lines = []
    for msg in messages[-limit:]:
        content = re.sub(r"\s+", " ", str(msg.get("content", ""))).strip()[:700]
        items = msg.get("items") or []
        if items:
            item_lines = []
            for item in items[:8]:
                text = str(item.get("text") or "").strip()
                meaning = str(item.get("meaning") or "").strip()
                if text:
                    item_lines.append(f"{text} — {meaning}".strip(" —"))
            if item_lines:
                content = (content + "\n" + "\n".join(item_lines)).strip()
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


def is_bare_lookup(message: str) -> bool:
    """没有其它说明、只发英文单词 / 词组 / 句子时，走逐条讲解模式。"""
    text = (message or "").strip()
    if not text or len(text) > 1200:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    if "?" in text:
        return False
    if _ASK_PREFIX.match(text):
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _infer_type(text: str) -> str:
    words = len(re.findall(r"[A-Za-z']+", text))
    if re.search(r"[.!?]$", text) and words > 2:
        return "sentence"
    if " " in text.strip():
        return "phrase"
    return "word"


def explain_vocabulary(message: str) -> dict:
    """把一段只有英文的输入拆成条目，逐条讲解。"""
    prompt = _EXPLAIN_PROMPT.replace("__MESSAGE__", (message or "").strip()[:1200])
    data = call_llm_json(
        prompt, temperature=0.3, num_predict=1000, fallback={}, timeout=90
    )
    if not isinstance(data, dict):
        return {"intro": "", "items": []}

    items: list[dict] = []
    seen: set[str] = set()
    raw_items = data.get("items")
    if not isinstance(raw_items, (list, tuple)):
        raw_items = []

    for raw in raw_items[:8]:
        if not isinstance(raw, dict):
            continue
        text = _as_text(raw.get("text") or "").strip().strip('"“”')
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)

        item_type = str(raw.get("type") or "").strip().lower()
        if item_type not in ("word", "phrase", "sentence"):
            item_type = _infer_type(text)

        item = {
            "text": text[:300],
            "type": item_type,
            "meaning": _as_text(raw.get("meaning") or "").strip()[:500],
            "usage": _as_text(raw.get("usage") or "").strip()[:500],
            "example": _as_text(raw.get("example") or "").strip()[:500],
            "example_zh": _as_text(raw.get("example_zh") or "").strip()[:500],
        }
        items.append(item)

    intro = _as_text(data.get("intro") or "").strip()[:500]
    return {"intro": intro or "我按条给你拆开讲：", "items": items}
