# utils/LearnerProfile.py

"""给 AI 老师看的"学习档案"。

只读、限量、不写文件：
- 背单词：已学 / 待复习 / 今天的量，加上最该复习的几个词（按遗忘次数和到期排）；
- 笔记本：最近的单词、词组条目；
- 表达库：最近攒下的「想表达的意思 → 地道说法」。

内容会随每轮对话发给模型，所以这里做了上限和截断，避免把整本笔记塞进 prompt。
Part 2 的回答内容不在里面——那部分不落盘。
"""

from datetime import date

from utils.Expressions import load_expressions, stats as expression_stats
from utils.Notebook import load_entries
from utils.WordAtlas import (
    load_progress,
    stats as word_stats,
    target_plan,
    word_by_id,
)

_MAX_WORDS = 8
_MAX_NOTES = 6
_MAX_EXPRESSIONS = 6
_MAX_MEANING = 40


def _one_line(text, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


def _first_sense(word: dict) -> str:
    for sense in word.get("senses") or []:
        meaning = _one_line(sense.get("zh"), _MAX_MEANING)
        if meaning:
            pos = _one_line(sense.get("pos"), 8)
            return f"{pos} {meaning}".strip()
    return ""


def weak_words(limit: int = _MAX_WORDS) -> list[str]:
    """最该复习的词：遗忘多、复习次数少、已经到期的优先。"""
    progress = load_progress()
    today = date.today().isoformat()
    scored = []
    for word_id, record in (progress.get("words") or {}).items():
        word = word_by_id(word_id)
        if not word:
            continue
        reps = int(record.get("reps") or 0)
        lapses = int(record.get("lapses") or 0)
        due = str(record.get("due") or "")
        score = lapses * 3 + max(0, 3 - reps) + (1 if due <= today else 0)
        scored.append((score, due, word, reps, lapses))
    scored.sort(key=lambda item: (-item[0], item[1]))

    lines = []
    for _score, _due, word, reps, lapses in scored[:limit]:
        meaning = _first_sense(word)
        detail = f"复习 {reps} 次"
        if lapses:
            detail += f" / 遗忘 {lapses} 次"
        lines.append(f"- {word.get('w', '')}（{meaning}）· {detail}")
    return lines


def notebook_lines(limit: int = _MAX_NOTES) -> list[str]:
    entries = load_entries()
    entries = sorted(entries, key=lambda item: str(item.get("created_at") or ""), reverse=True)
    lines = []
    for entry in entries[:limit]:
        term = _one_line(entry.get("term"), 60)
        if not term:
            continue
        meaning = _one_line(entry.get("meaning"), _MAX_MEANING)
        tags = "、".join(str(tag) for tag in (entry.get("tags") or [])[:3])
        suffix = f" · {'（' + tags + '）' if tags else ''}"
        lines.append(f"- {term} — {meaning}{suffix}".strip())
    return lines


def expression_lines(limit: int = _MAX_EXPRESSIONS) -> list[str]:
    entries = load_expressions()
    entries = sorted(entries, key=lambda item: str(item.get("created_at") or ""), reverse=True)
    lines = []
    for entry in entries[:limit]:
        intent = _one_line(entry.get("intent"), 60)
        natural = _one_line(entry.get("natural"), 80)
        if intent and natural:
            lines.append(f"- 想表达「{intent}」→ {natural}")
    return lines


def counts() -> dict:
    """侧边栏展示用的数量，不触发任何模型调用。"""
    words = word_stats(load_progress())
    expressions = expression_stats()
    return {
        "learned": words["learned"],
        "due": words["due"],
        "notes": len(load_entries()),
        "expressions": expressions["total"],
        "expression_due": expressions["due"],
    }


def build_profile() -> str:
    """拼成交给模型的文本；完全没有数据时返回空串。"""
    words = word_stats(load_progress())
    plan = target_plan()
    blocks = []

    if words["learned"] or words["new_today"] or words["review_today"]:
        head = (
            f"- 已学 {words['learned']} 个词，待复习 {words['due']} 个；"
            f"今天新学 {words['new_today']}、复习 {words['review_today']}"
        )
        if plan.get("target"):
            head += f"；目标日期 {plan['target']}，每天约 {plan.get('per_day', 0)} 个"
        lines = weak_words()
        if lines:
            head += "\n- 最该复习：" + "；".join(
                line.lstrip("- ").split(" · ")[0] for line in lines[: _MAX_WORDS]
            )
        blocks.append("VOCABULARY\n" + head)

    notes = notebook_lines()
    if notes:
        blocks.append(
            "NOTEBOOK (words and phrases the student saved; reuse them in examples when natural)\n"
            + "\n".join(notes)
        )

    expressions = expression_lines()
    if expressions:
        blocks.append(
            "EXPRESSIONS (intent -> natural phrasing the student wants to own)\n"
            + "\n".join(expressions)
        )

    return "\n\n".join(blocks)


__all__ = ["build_profile", "counts", "expression_lines", "notebook_lines", "weak_words"]
