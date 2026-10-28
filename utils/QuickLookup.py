# utils/QuickLookup.py

"""全站侧边栏的「随手查」：英文→中文翻译，中文→几个可用的英文说法。

一次调用完成，不落盘；结果由页面决定怎么展示。输入超过 500 字会被截断，
避免误贴长文把 token 烧掉。

每条结果都带 type（word / phrase / sentence）：单词进单词表、句子进表达库，
词组由页面给两个按钮让用户选。
"""

import logging
import re

from utils.llm import as_text, call_llm_json

logger = logging.getLogger(__name__)

_MAX_INPUT = 500
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z']+")
_TYPES = ("word", "phrase", "sentence")

_TRANSLATE_PROMPT = """You are a precise bilingual dictionary.

ENGLISH INPUT
__TEXT__

Translate it into natural Simplified Chinese.
- Keep the original tone and register.
- If it is an idiom or slang, give the idiomatic meaning; add a short literal gloss in
  parentheses only when the literal meaning is clearly different.
- If it is a single word, give the most common meaning(s), separated by /.
- No explanations, no pinyin, no English.

Also classify the input as "word", "phrase" or "sentence".

Output JSON only: {"translation": "...", "type": "word|phrase|sentence"}
"""

_OPTIONS_PROMPT = """You are an IELTS speaking coach helping a Chinese learner express an idea in English.

CHINESE INPUT
__TEXT__

TASK
1. translation: one faithful, natural English translation of the input.
2. options: 3-5 alternative expressions a fluent speaker might actually use. Mix short
   phrases and full sentences when useful.

FOR EACH OPTION
- en: the expression itself
- zh: a short Simplified Chinese meaning (for a word or phrase) or translation
- type: "word", "phrase" or "sentence"
- note: at most one short Chinese line about register or nuance (may be empty)

RULES
- Do not repeat the translation verbatim in options.
- Keep everything speakable: no headings, no markdown.
- If the input is already a fixed Chinese phrase with no good equivalent, say so in
  the note of one option.

Output JSON only:
{"translation": "...", "options": [{"en": "...", "zh": "...", "type": "word", "note": "..."}]}
"""


def is_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _infer_type(text: str) -> str:
    words = _WORD_RE.findall(text or "")
    if len(words) <= 1:
        return "word"
    if re.search(r"[.!?]\s*$", (text or "").strip()) and len(words) >= 3:
        return "sentence"
    if len(words) >= 6:
        return "sentence"
    return "phrase"


def _type_or_infer(value, text: str) -> str:
    value = str(value or "").strip().lower()
    return value if value in _TYPES else _infer_type(text)


def _clean_options(raw) -> list[dict]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    options: list[dict] = []
    seen: set[str] = set()
    for item in raw[:10]:
        if isinstance(item, str):
            en, zh, note, kind = item, "", "", ""
        elif isinstance(item, dict):
            en = as_text(item.get("en") or item.get("text") or "")
            zh = as_text(item.get("zh") or item.get("meaning") or "")
            note = as_text(item.get("note") or "")
            kind = item.get("type") or ""
        else:
            continue
        en = " ".join(en.split()).strip(" \"'")
        if not en:
            continue
        key = en.casefold()
        if key in seen:
            continue
        seen.add(key)
        options.append(
            {
                "en": en[:200],
                "zh": " ".join(zh.split())[:120],
                "note": " ".join(note.split())[:100],
                "type": _type_or_infer(kind, en),
            }
        )
    return options[:5]


def lookup(text: str) -> dict:
    """返回 {mode, source, source_type, translation, options, error}。"""
    source = " ".join(str(text or "").split())[:_MAX_INPUT]
    result = {
        "mode": "cn" if is_chinese(source) else "en",
        "source": source,
        "source_type": _infer_type(source),
        "translation": "",
        "options": [],
        "error": "",
    }
    if not source:
        result["error"] = "先输入点内容"
        return result

    if result["mode"] == "en":
        prompt = _TRANSLATE_PROMPT.replace("__TEXT__", source)
        data = call_llm_json(
            prompt, temperature=0.2, num_predict=300, fallback={}, timeout=45
        )
        result["translation"] = as_text(data.get("translation") or "").strip()[:500]
        result["source_type"] = _type_or_infer(data.get("type"), source)
    else:
        prompt = _OPTIONS_PROMPT.replace("__TEXT__", source)
        data = call_llm_json(
            prompt, temperature=0.4, num_predict=800, fallback={}, timeout=60
        )
        result["translation"] = as_text(data.get("translation") or "").strip()[:500]
        result["options"] = _clean_options(data.get("options"))

    if not result["translation"] and not result["options"]:
        logger.warning("随手查没有返回内容：%s", source[:40])
        result["error"] = "没接上，再试一次"
    return result


__all__ = ["is_chinese", "lookup"]
