# utils/Notes.py

"""心理咨询 / 学业指导的带日期会话笔记。

和长期记忆完全分开：
- 记忆回答“这个人是谁、我们经历过什么”
- 笔记只记录“这一次聊了什么、结果如何”

每次新的浏览器会话生成一条笔记；同一会话内继续聊天会更新同一条。
"""

import html
import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from utils.storage import save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTES_PATH = Path(
    os.getenv("NOTES_PATH") or (_PROJECT_ROOT / "data" / "session_notes.json")
)
_LOCK = threading.RLock()

_KIND_LABELS = {
    "psychologist": "心理咨询",
    "mentor": "学业指导",
}

_NOTE_PROMPT = """You write private dated session notes for the user.

KIND
__KIND__

DATE
__DATE__

SESSION TRANSCRIPT
__TRANSCRIPT__

CURRENT NOTE FOR THIS SESSION (may be empty)
__EXISTING__

TASK
Update the note for THIS session only. Use only the transcript; do not invent facts and do not use any long-term memory.

RULES
- 心理咨询：summary 记录用户这次带来的问题、情绪状态和这次的结果；details 记录关键观察、讨论了什么、用了什么方法；next 给 1-3 条具体建议。
- 学业指导：summary 记录这次的主题和主要结论；details 记录给出的建议和理由；next 给 1-3 条具体下一步。
- Simplified Chinese, third person ("用户..."), concise.
- summary <= 150 Chinese characters.
- details: 2-5 items, each <= 60 characters.
- next: 1-3 items, each <= 60 characters.
- No diagnosis or medical claims beyond what was discussed.
- No markdown tables or headings.

Output JSON only:
{"summary": "...", "details": ["..."], "next": ["..."]}
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clean_list(value, limit: int) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[\n；;]+", value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = []
    cleaned: list[str] = []
    for item in items:
        text = _one_line(item).strip("-• ").strip()
        if text and text not in cleaned:
            cleaned.append(text[:80])
    return cleaned[:limit]


def _load_all() -> dict:
    if not NOTES_PATH.exists():
        return {}
    try:
        data = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    notes = data.get("notes", {}) if isinstance(data, dict) else {}
    return notes if isinstance(notes, dict) else {}


def _save_all(notes: dict) -> None:
    save_json(NOTES_PATH, {"version": 1, "notes": notes})


def load_notes(kind: str) -> list[dict]:
    with _LOCK:
        raw = _load_all().get(kind) or {}
    result = []
    if isinstance(raw, dict):
        for note_id, note in raw.items():
            if not isinstance(note, dict):
                continue
            result.append(
                {
                    "id": str(note.get("id") or note_id),
                    "date": _one_line(note.get("date")),
                    "summary": _one_line(note.get("summary")),
                    "details": _clean_list(note.get("details"), 5),
                    "next": _clean_list(note.get("next"), 3),
                    "created_at": str(note.get("created_at") or ""),
                    "updated_at": str(note.get("updated_at") or ""),
                }
            )
    result.sort(key=lambda item: (item["date"], item["updated_at"]), reverse=True)
    return result


def _transcript(messages, limit: int = 20) -> str:
    lines = []
    for message in messages[-limit:]:
        role = "用户" if message.get("role") == "user" else "咨询师/导师"
        content = _one_line(message.get("content"))[:500]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(empty)"


def _existing_text(notes: list[dict], note_id: str) -> str:
    for note in notes:
        if note["id"] != note_id:
            continue
        parts = []
        if note["summary"]:
            parts.append(f"summary: {note['summary']}")
        if note["details"]:
            parts.append("details:\n" + "\n".join(f"- {x}" for x in note["details"]))
        if note["next"]:
            parts.append("next:\n" + "\n".join(f"- {x}" for x in note["next"]))
        return "\n".join(parts)
    return "(empty)"


def update_session_note(
    kind: str,
    note_id: str,
    note_date: str,
    messages,
    assistant_label: str = "",
) -> dict | None:
    """生成或更新当前会话的笔记；失败时保留已有笔记。"""
    if not note_id:
        return None

    existing_notes = load_notes(kind)
    prompt = (
        _NOTE_PROMPT.replace("__KIND__", _KIND_LABELS.get(kind, kind))
        .replace("__DATE__", note_date or datetime.now().strftime("%Y-%m-%d"))
        .replace("__TRANSCRIPT__", _transcript(messages))
        .replace("__EXISTING__", _existing_text(existing_notes, note_id))
    )

    try:
        from utils.llm import call_llm_json

        data = call_llm_json(
            prompt, temperature=0.2, num_predict=700, fallback={}, timeout=45
        )
    except Exception:
        logger.exception("生成会话笔记失败")
        return None

    if not isinstance(data, dict) or not data:
        return None

    summary = _one_line(data.get("summary"))[:200]
    details = _clean_list(data.get("details"), 5)
    next_steps = _clean_list(data.get("next"), 3)
    if not summary and not details and not next_steps:
        return None

    old = next((note for note in existing_notes if note["id"] == note_id), None)
    created_at = old["created_at"] if old and old["created_at"] else _now()
    note = {
        "id": note_id,
        "date": note_date or datetime.now().strftime("%Y-%m-%d"),
        "summary": summary,
        "details": details,
        "next": next_steps,
        "created_at": created_at,
        "updated_at": _now(),
    }

    with _LOCK:
        all_notes = _load_all()
        bucket = all_notes.get(kind)
        if not isinstance(bucket, dict):
            bucket = {}
            all_notes[kind] = bucket
        bucket[note_id] = {key: value for key, value in note.items() if key != "id"}
        _save_all(all_notes)
    return note


def _note_body_html(note: dict, kind: str) -> str:
    parts = []
    if note["summary"]:
        parts.append(f"<p>{html.escape(note['summary'])}</p>")
    if note["details"]:
        items = "".join(f"<li>{html.escape(item)}</li>" for item in note["details"])
        parts.append(f"<ul>{items}</ul>")
    if note["next"]:
        label = "建议" if kind == "psychologist" else "下一步"
        joined = "；".join(html.escape(item) for item in note["next"])
        parts.append(f"<p><b>{label}：</b>{joined}</p>")
    return "".join(parts) or "<p>（无内容）</p>"


def render_notes_sidebar(kind: str, title: str) -> None:
    """在侧边栏显示历史会话笔记；只有点开某个日期才显示内容。"""
    import streamlit as st

    notes = load_notes(kind)
    with st.sidebar:
        with st.expander(title, expanded=False):
            if not notes:
                st.caption("聊完一轮会自动生成一条带日期的记录。")
                return

            st.markdown(
                "<style>"
                "details.session-note{margin:.25rem 0;}"
                "details.session-note>summary{cursor:pointer;font-weight:600;}"
                "details.session-note[open]>summary{margin-bottom:.35rem;}"
                "</style>",
                unsafe_allow_html=True,
            )
            for note in notes:
                body = _note_body_html(note, kind)
                date = html.escape(note["date"] or "未标日期")
                st.markdown(
                    f"<details class='session-note'><summary>{date}</summary>{body}</details>",
                    unsafe_allow_html=True,
                )

