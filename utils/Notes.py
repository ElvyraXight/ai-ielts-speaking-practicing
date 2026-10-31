# utils/Notes.py

"""心理咨询 / 学业指导的带日期会话笔记。

和长期记忆完全分开：
- 记忆回答“这个人是谁、我们经历过什么”
- 笔记只记录“这一次聊了什么、结果如何”

每次新的浏览器会话生成一条笔记；同一会话内继续聊天会更新同一条。
"""

import html
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from utils.storage import load_json, save_json

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


_MIN_NOTE_TURNS = 4


def note_ready(messages) -> bool:
    """会话笔记只保留聊过 3 条以上的会话。

    只寒暄一两句、或刚好 3 条的短会话不值得生成诊疗 / 指导笔记；
    页面「重新开始聊天」的确认弹窗也用同一个判断来提示用户。
    """
    return (
        sum(
            1
            for message in messages or []
            if isinstance(message, dict) and message.get("role") == "user"
        )
        >= _MIN_NOTE_TURNS
    )


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
    data = load_json(NOTES_PATH, {})
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


def _transcript(messages, limit: int = 12, per_message: int = 350) -> str:
    """只取最近几条、每条截断：笔记要的是这次聊了什么，不是逐字全文。

    原来带 20 条、每条 500 字，一轮就把 1 万字符塞进 prompt；
    现在每轮少花约一半输入 token，信息量对"这次聊了什么"足够。
    """
    lines = []
    for message in messages[-limit:]:
        role = "用户" if message.get("role") == "user" else "咨询师/导师"
        content = _one_line(message.get("content"))[:per_message]
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


_NOTE_LOCKS: dict[str, threading.Lock] = {}
_LATEST_REQUESTS: dict[str, tuple] = {}
_REQUESTS_GUARD = threading.Lock()


def _lock_for(note_id: str) -> threading.Lock:
    with _REQUESTS_GUARD:
        return _NOTE_LOCKS.setdefault(note_id, threading.Lock())


def update_session_note(
    kind: str,
    note_id: str,
    note_date: str,
    messages,
    assistant_label: str = "",
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict | None:
    """生成或更新当前会话的笔记；失败时保留已有笔记。

    每轮对话都会触发一次，但同一会话只允许一个更新在跑：跑的时候又来了
    新的一轮，就只记下"最新的那份"，等当前这次结束再补一遍。这样既不会
    排起长队，也不会用旧转录覆盖新笔记。provider/model 由主线程传进来，
    后台线程读不到 Streamlit 的 session_state。
    """
    if not note_id:
        return None

    request = (kind, note_date, list(messages), assistant_label, provider, model)
    with _REQUESTS_GUARD:
        _LATEST_REQUESTS[note_id] = request

    lock = _lock_for(note_id)
    if not lock.acquire(blocking=False):
        logger.info("笔记正在更新，这一轮并进下一次：%s", note_id)
        return None

    note = None
    try:
        while True:
            with _REQUESTS_GUARD:
                current = _LATEST_REQUESTS.get(note_id)
            if current is None:
                return note
            kind, note_date, messages, assistant_label, provider, model = current
            note = _write_note(
                kind,
                note_id,
                note_date,
                messages,
                assistant_label=assistant_label,
                provider=provider,
                model=model,
            )
            with _REQUESTS_GUARD:
                if _LATEST_REQUESTS.get(note_id) is current:
                    _LATEST_REQUESTS.pop(note_id, None)
                    return note
    finally:
        lock.release()


def _write_note(
    kind: str,
    note_id: str,
    note_date: str,
    messages,
    *,
    assistant_label: str = "",
    provider: str | None = None,
    model: str | None = None,
) -> dict | None:
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
            prompt,
            temperature=0.2,
            num_predict=700,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
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


def delete_note(kind: str, note_id: str) -> bool:
    """删除一条诊疗 / 指导记录；删掉后不可恢复。"""
    note_id = str(note_id or "").strip()
    if not note_id:
        return False
    with _LOCK:
        all_notes = _load_all()
        bucket = all_notes.get(kind)
        if not isinstance(bucket, dict) or note_id not in bucket:
            return False
        bucket.pop(note_id, None)
        if not bucket:
            all_notes.pop(kind, None)
        _save_all(all_notes)
        return True


def _note_body_html(note: dict, kind: str) -> str:
    parts = []
    if note["summary"]:
        parts.append(f"<p>{html.escape(note['summary'])}</p>")
    if note["details"]:
        items = "".join(f"<li>{html.escape(item)}</li>" for item in note["details"])
        parts.append(f"<ul>{items}</ul>")
    if note["next"]:
        label = "建议" if kind == "psychologist" else "下一步"
        items = [
            re.sub(r"[。！？；;，,、\s]+$", "", str(item).strip())
            for item in note["next"]
        ]
        joined = "；".join(html.escape(item) for item in items if item)
        parts.append(f"<p><b>{label}：</b>{joined + '。' if joined else ''}</p>")
    return "".join(parts) or "<p>（无内容）</p>"


def render_details_sidebar(
    title: str,
    entries: list[dict],
    empty_text: str,
    actions: Callable[[], None] | None = None,
) -> None:
    """诊疗笔记/仓库共用的侧边栏折叠记录格式；`actions` 是展开后的额外按钮。"""
    import streamlit as st

    with st.sidebar:
        with st.expander(title, expanded=False):
            if not entries:
                st.caption(empty_text)
                return

            st.markdown(
                "<style>"
                "details.session-note{margin:.12rem 0;}"
                "details.session-note>summary{"
                "cursor:pointer;font-weight:600;font-size:.86rem;"
                "padding:.28rem .1rem;line-height:1.45;"
                "}"
                "details.session-note>summary::marker{font-size:1em;}"
                "details.session-note>summary::-webkit-details-marker{font-size:1em;}"
                "details.session-note[open]>summary{"
                "margin-bottom:.3rem;padding-bottom:.2rem;"
                "}"
                "</style>",
                unsafe_allow_html=True,
            )
            for entry in entries:
                label = html.escape(str(entry.get("label") or "未标日期"))
                body = entry.get("body") or "<p>（无内容）</p>"
                st.markdown(
                    f"<details class='session-note'><summary>{label}</summary>{body}</details>",
                    unsafe_allow_html=True,
                )
            st.markdown("<div style='height:.4rem'></div>", unsafe_allow_html=True)
            if actions:
                actions()


def render_notes_sidebar(kind: str, title: str, exclude_id: str = "") -> None:
    """在侧边栏显示历史会话笔记；当前这次对话的笔记结束前不显示。

    记录多了以后需要能删：折叠框底部「🗑 删除记录…」打开管理弹窗，
    勾选要删的记录后统一确认，避免一条条点、也避免误删。
    """
    import streamlit as st

    notes = [note for note in load_notes(kind) if note["id"] != exclude_id]
    manage_key = f"note_manage_open_{kind}"
    pending_key = f"note_delete_pending_{kind}"

    def _manage_button() -> None:
        if st.button(
            "🗑 删除记录…",
            key=f"note_manage_btn_{kind}",
            use_container_width=True,
        ):
            st.session_state[manage_key] = True
            st.rerun()

    entries = [
        {
            "label": note["date"] or "未标日期",
            "body": _note_body_html(note, kind),
        }
        for note in notes
    ]
    render_details_sidebar(
        title,
        entries,
        "这次对话结束后，这里会显示带日期的记录。",
        actions=_manage_button,
    )

    @st.dialog(f"管理{title}")
    def _manage_dialog() -> None:
        pending_id = st.session_state.get(pending_key)
        pending = next((note for note in notes if note["id"] == pending_id), None)
        if pending:
            st.warning(
                f"确认删除「{pending['date'] or '未标日期'}」这条{title}？"
                "删除后不可恢复。"
            )
            if pending["summary"]:
                st.caption(pending["summary"])
            left, right = st.columns(2)
            if left.button(
                "确认删除",
                key=f"note_del_yes_{kind}",
                type="primary",
                use_container_width=True,
            ):
                delete_note(kind, pending["id"])
                st.session_state.pop(pending_key, None)
                st.rerun()
            if right.button(
                "取消",
                key=f"note_del_no_{kind}",
                use_container_width=True,
            ):
                st.session_state.pop(pending_key, None)
                st.rerun()
            return

        if not notes:
            st.caption("没有可删除的记录。")
        for note in notes:
            st.markdown(f"**{note['date'] or '未标日期'}**")
            if note["summary"]:
                st.caption(note["summary"])
            if st.button(
                "🗑 删除",
                key=f"note_del_{kind}_{note['id']}",
                use_container_width=True,
            ):
                st.session_state[pending_key] = note["id"]
                st.rerun()
            st.divider()
        if st.button(
            "关闭",
            key=f"note_manage_close_{kind}",
            use_container_width=True,
        ):
            st.session_state.pop(manage_key, None)
            st.rerun()

    if st.session_state.get(manage_key):
        _manage_dialog()

