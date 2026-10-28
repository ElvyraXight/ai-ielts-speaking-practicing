# utils/TeacherMemory.py

"""AI 老师的长期记忆：一个会随课更新的“学生模型”。

不是聊天记录，也不是单词表，而是老师对学生稳定特征的判断：

- level: 当前水平（CEFR / 雅思区间 + 一句依据）
- style: 表达习惯（句长、时态、用词、填充词……）
- strengths: 已经稳的东西
- weaknesses: 反复出现、还没解决的问题（带出现次数和最近时间）
- methods: 对这个学生有效的讲法/练法
- recent: 最近几次课练了什么、下次先抓什么

练习结束后用一次轻量 LLM 调用更新，合并与去重都在本地完成；
数据在 data/teacher_memory.json（已 gitignore），每轮注入老师 prompt。
"""

import difflib
import json
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

_MAX_STYLE = 6
_MAX_STRENGTHS = 8
_MAX_WEAKNESSES = 10
_MAX_METHODS = 6
_MAX_NOTES = 8
_MAX_RECENT = 5
_MAX_TEXT = 80
_SIMILARITY = 0.78


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
        "notes": [],
        "recent": [],
        "updated_at": "",
    }


def _clean_fact(raw) -> dict | None:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    text = _one_line(raw.get("text"))
    if not text:
        return None
    stamp = _now()
    return {
        "text": text,
        "count": max(1, int(raw.get("count") or 1)),
        "first": str(raw.get("first") or stamp),
        "last": str(raw.get("last") or stamp),
    }


def _clean_list(value, limit: int) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for raw in value:
        fact = _clean_fact(raw)
        if fact and fact["text"] not in {item["text"] for item in result}:
            result.append(fact)
    return result[:limit]


def _normalise(raw) -> dict:
    memory = _empty()
    if not isinstance(raw, dict):
        return memory
    level = raw.get("level") if isinstance(raw.get("level"), dict) else {}
    memory["level"] = {
        "band": _one_line(level.get("band"), 20),
        "note": _one_line(level.get("note"), _MAX_TEXT),
        "updated": str(level.get("updated") or ""),
    }
    memory["style"] = _clean_list(raw.get("style"), _MAX_STYLE)
    memory["strengths"] = _clean_list(raw.get("strengths"), _MAX_STRENGTHS)
    memory["weaknesses"] = _clean_list(raw.get("weaknesses"), _MAX_WEAKNESSES)
    memory["methods"] = _clean_list(raw.get("methods"), _MAX_METHODS)
    memory["notes"] = _clean_list(raw.get("notes"), _MAX_NOTES)
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


def _merge_facts(items: list[dict], additions, limit: int) -> list[dict]:
    texts = []
    if isinstance(additions, str):
        texts = [additions]
    elif isinstance(additions, list):
        texts = [as_text(item) for item in additions]
    stamp = _now()
    for raw in texts:
        text = _one_line(raw)
        if not text:
            continue
        existing = next((item for item in items if _similar(item["text"], text)), None)
        if existing:
            existing["count"] += 1
            existing["last"] = stamp
        else:
            items.append(
                {"text": text, "count": 1, "first": stamp, "last": stamp}
            )
    items.sort(key=lambda item: (item["last"], item["count"]), reverse=True)
    return items[:limit]


def _apply_update(memory: dict, data: dict, lesson_id: str = "") -> dict:
    level = data.get("level") if isinstance(data.get("level"), dict) else None
    if level:
        band = _one_line(level.get("band"), 20)
        note = _one_line(level.get("note"), _MAX_TEXT)
        if band or note:
            memory["level"] = {
                "band": band or memory["level"].get("band", ""),
                "note": note or memory["level"].get("note", ""),
                "updated": _now(),
            }

    memory["style"] = _merge_facts(
        memory["style"], data.get("style_add"), _MAX_STYLE
    )
    memory["strengths"] = _merge_facts(
        memory["strengths"], data.get("strength_add"), _MAX_STRENGTHS
    )
    memory["weaknesses"] = _merge_facts(
        memory["weaknesses"], data.get("weakness_add"), _MAX_WEAKNESSES
    )
    memory["methods"] = _merge_facts(
        memory["methods"], data.get("method_add"), _MAX_METHODS
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


def memory_text(memory: dict | None = None) -> str:
    """给 prompt 用的紧凑文本；没有记忆时返回空串。"""
    memory = load_memory() if memory is None else memory
    level = memory.get("level") or {}
    lines = []

    if level.get("band") or level.get("note"):
        parts = [part for part in (level.get("band"), level.get("note")) if part]
        lines.append("LEVEL: " + " — ".join(parts))

    def block(title: str, items: list[dict], with_count: bool = False) -> None:
        if not items:
            return
        parts = []
        for item in items:
            text = item["text"]
            if with_count and item["count"] > 1:
                text += f"（{item['count']} 次）"
            parts.append(text)
        lines.append(f"{title}: " + "；".join(parts))

    block("STYLE", memory.get("style") or [])
    block("SOLID", memory.get("strengths") or [])
    block("WEAK", memory.get("weaknesses") or [], with_count=True)
    block("WORKS", memory.get("methods") or [], with_count=True)
    block("NOTES (student asked me to remember)", memory.get("notes") or [])

    recent = memory.get("recent") or []
    if recent:
        lines.append("RECENT: " + "；".join(
            f"{item['date']} {item['summary']}".strip() for item in recent[:3]
        ))
        next_focus = next((item["next"] for item in recent if item["next"]), "")
        if next_focus:
            lines.append("NEXT: " + next_focus)
    return "\n".join(lines)


def _update_prompt(memory: dict, lesson: dict) -> str:
    return f"""You maintain a teacher's long-term memory of one IELTS student.
Model the student, not the conversation. Keep only stable, useful observations.

CURRENT MEMORY
{memory_text(memory) or "(empty)"}

NEW LESSON
Question: {lesson.get('question', '')}
Student answer: {lesson.get('answer', '')}
Teacher feedback: {lesson.get('feedback', '')}
Target points: {lesson.get('targets', '')}
Results: {lesson.get('results', '')}
Follow-up turn: {lesson.get('followup', 'no')}
Current focus: {lesson.get('focus', '')}
Lesson status: {lesson.get('status', '')}
Checklist: {lesson.get('checklist', '')}

UPDATE RULES
- level: estimate CEFR / IELTS band only when the lesson gives real evidence; be conservative, use a range such as "5.5-6.0"; note = one short Chinese sentence of evidence. Return null if unsure.
- style_add: 0-2 short Chinese observations about how this student expresses (sentence length, tense, vocabulary habits, fillers). Only stable patterns.
- strength_add: 0-2 things that now look solid.
- weakness_add: 0-2 recurring problems or expressions still shaky. Name the pattern, not the whole sentence.
- method_add: 0-1 what worked or did not work in your teaching (e.g. "对比句比讲规则有效").
- session_summary: one short Chinese line about what was practised and what changed.
- next_focus: one short Chinese line for the next lesson.
- If this is a follow-up turn, only record what changed in this turn; session_summary must describe the whole lesson so far and will replace the previous summary for the same lesson, not add a new one.
- No transcript, no long quotes, each item <= 60 Chinese characters, no invented facts.
- If nothing stable, return empty arrays.

Output JSON only:
{{"level": {{"band": "", "note": ""}} | null, "style_add": [], "strength_add": [], "weakness_add": [], "method_add": [], "session_summary": "", "next_focus": ""}}
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
) -> dict:
    """练习的每一轮结束后更新学生模型；失败时保留旧记忆。"""
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
            "followup": "yes" if followup else "no",
            "focus": (focus or "")[:100],
            "status": (status or "")[:20],
            "checklist": (checklist or "")[:500],
        },
    )
    try:
        data = call_llm_json(
            prompt, temperature=0.2, num_predict=800, fallback={}, timeout=45
        )
    except Exception:
        logger.exception("更新老师记忆失败")
        return current
    if not isinstance(data, dict) or not data:
        return current

    with _LOCK:
        memory = _load_unlocked()
        memory = _apply_update(memory, data, lesson_id)
        _save_unlocked(memory)
    return memory


def add_note(text: str) -> dict:
    """用户明确说“记住……”时直接写入，不额外调用模型。"""
    note = _one_line(text, 120)
    if not note:
        return load_memory()
    with _LOCK:
        memory = _load_unlocked()
        memory["notes"] = _merge_facts(
            memory.get("notes") or [], [note], _MAX_NOTES
        )
        _save_unlocked(memory)
        return memory


_REMEMBER_RE = re.compile(
    r"(记住|记牢|记一下|记下|别忘了|不要忘|不能忘|别再忘|我说过|跟你说过|"
    r"和你讲过|强调过|很重要|remember (this|that)|don'?t forget|never forget|"
    r"i told you|i'?ve told you|keep (this )?in mind)",
    re.IGNORECASE,
)


def looks_like_remember(text: str) -> bool:
    return bool(_REMEMBER_RE.search(str(text or "")))


def render_sidebar() -> None:
    import streamlit as st

    memory = load_memory()
    with st.sidebar.expander("🧠 老师的记忆", expanded=False):
        if not memory_text(memory):
            st.caption("还没有形成记忆。练几次之后，这里会出现你的水平、表达特点、薄弱点和有效练法。")
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
            ("你说要记住的", "notes"),
        ):
            items = memory.get(key) or []
            if items:
                st.caption(f"**{title}**")
                for item in items:
                    suffix = (
                        f"（{item['count']} 次）"
                        if key in ("weaknesses", "methods") and item["count"] > 1
                        else ""
                    )
                    st.caption(f"- {item['text']}{suffix}")
        recent = memory.get("recent") or []
        if recent:
            st.caption("**最近**")
            for item in recent[:3]:
                text = f"- {item['date']} {item['summary']}".strip()
                if item.get("next"):
                    text += f"（下次：{item['next']}）"
                st.caption(text)
        if st.button("清空老师的记忆", key="teacher_memory_clear"):
            clear_memory()
            st.rerun()


__all__ = [
    "add_note",
    "clear_memory",
    "load_memory",
    "looks_like_remember",
    "memory_text",
    "render_sidebar",
    "update_from_lesson",
]
