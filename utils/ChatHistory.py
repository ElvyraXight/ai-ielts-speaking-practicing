# utils/ChatHistory.py

"""每个聊天页独立的本地聊天记录。

不是浏览器缓存：消息写到 data/chat_history.json，刷新/关浏览器后还能读回来。
每个页面一个 key（tutor / free_talk / catgirl / friend / psychologist / mentor / exam），
互不覆盖；每页最多保留最近 300 条。
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = Path(
    os.getenv("CHAT_HISTORY_PATH")
    or (_PROJECT_ROOT / "data" / "chat_history.json")
)
_LOCK = threading.RLock()

_MAX_MESSAGES = 300
_MAX_TEXT = 20000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_messages(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    result = []
    for message in raw[-_MAX_MESSAGES:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role not in ("user", "assistant"):
            continue
        try:
            clean = json.loads(json.dumps(message, ensure_ascii=False))
        except (TypeError, ValueError):
            continue
        content = clean.get("content")
        if content is not None:
            clean["content"] = str(content)[:_MAX_TEXT]
        result.append(clean)
    return result


def _load_all() -> dict:
    data = load_json(HISTORY_PATH, {})
    if not isinstance(data, dict):
        return {}
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        return {}
    return sessions


def load(key: str) -> list[dict]:
    with _LOCK:
        session = _load_all().get(str(key or "").strip())
        if not isinstance(session, dict):
            return []
        return _clean_messages(session.get("messages"))


def save(key: str, messages) -> None:
    key = str(key or "").strip()
    if not key:
        return
    clean = _clean_messages(messages)
    with _LOCK:
        sessions = _load_all()
        old = sessions.get(key) or {}
        if old.get("messages") == clean:
            return
        sessions[key] = {**old, "messages": clean, "updated_at": _now()}
        save_json(HISTORY_PATH, {"version": 1, "sessions": sessions})


def clear(key: str) -> None:
    key = str(key or "").strip()
    if not key:
        return
    with _LOCK:
        sessions = _load_all()
        old = sessions.get(key) or {}
        sessions[key] = {**old, "messages": [], "updated_at": _now()}
        save_json(HISTORY_PATH, {"version": 1, "sessions": sessions})


def load_meta(key: str) -> dict:
    with _LOCK:
        session = _load_all().get(str(key or "").strip())
        if not isinstance(session, dict):
            return {}
        meta = session.get("meta")
        return dict(meta) if isinstance(meta, dict) else {}


def save_meta(key: str, meta: dict) -> None:
    key = str(key or "").strip()
    if not key or not isinstance(meta, dict):
        return
    clean = json.loads(json.dumps(meta, ensure_ascii=False))
    with _LOCK:
        sessions = _load_all()
        old = sessions.get(key) or {}
        if old.get("meta") == clean:
            return
        sessions[key] = {**old, "meta": clean, "updated_at": _now()}
        save_json(HISTORY_PATH, {"version": 1, "sessions": sessions})


def update_meta(key: str, meta: dict) -> None:
    """只更新给定字段，保留同一会话已有的 meta（人设、专业方向等）。

    save_meta 是整份替换（HelpSession 用它清空临时会话）；页面想加一个
    自己的字段时用这个，避免被其它模块的 update_meta 覆盖。
    """
    key = str(key or "").strip()
    if not key or not isinstance(meta, dict):
        return
    clean = json.loads(json.dumps(meta, ensure_ascii=False))
    with _LOCK:
        sessions = _load_all()
        old = sessions.get(key) or {}
        current = old.get("meta") if isinstance(old.get("meta"), dict) else {}
        merged = {**current, **clean}
        if merged == current:
            return
        sessions[key] = {**old, "meta": merged, "updated_at": _now()}
        save_json(HISTORY_PATH, {"version": 1, "sessions": sessions})


def render_restart_button(
    key: str,
    on_restart,
    label: str = "🔄 重新开始聊天",
    title: str = "重新开始聊天",
    message: str = "确认清空当前聊天记录？",
) -> None:
    """侧边栏底部按钮：点击后弹窗确认，确认后清空当前页记录并重置页面状态。

    `message` 由各页面传入，说明清空的到底是哪一段聊天 / 考试进度。
    """
    import streamlit as st

    open_key = f"chat_restart_confirm_{key}"

    @st.dialog(title)
    def _confirm_dialog() -> None:
        st.write(message)
        left, right = st.columns(2)
        if left.button(
            "确认重新开始",
            key=f"chat_restart_yes_{key}",
            use_container_width=True,
        ):
            clear(key)
            on_restart()
            st.session_state.pop(open_key, None)
            st.rerun()
        if right.button(
            "取消",
            key=f"chat_restart_no_{key}",
            use_container_width=True,
        ):
            st.session_state.pop(open_key, None)
            st.rerun()

    with st.sidebar:
        st.divider()
        if st.button(label, key=f"chat_restart_{key}", use_container_width=True):
            st.session_state[open_key] = True
            st.rerun()

    if st.session_state.get(open_key):
        _confirm_dialog()


__all__ = [
    "clear",
    "load",
    "load_meta",
    "render_restart_button",
    "save",
    "save_meta",
    "update_meta",
]
