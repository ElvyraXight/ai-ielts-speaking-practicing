# utils/HelpSession.py

"""考场旁的临时老师会话。

Part 2 和考官对话各有一份互不干扰的临时聊天：

- 进入帮助不会清掉另一份；
- 结束帮助 / 重新开始考试 / Part 2 换题时，只清当前这一份；
- 临时聊天不写入任何长期记忆（TeacherMemory / Memory / TutorLead 摘要）。
"""

from __future__ import annotations

from datetime import datetime

from utils import ChatHistory

SOURCES = ("exam", "part2")
_CHAT_KEYS = {"exam": "help_exam", "part2": "help_part2"}
_LEGACY_KEY = "help"
_ACTIVE_KEY = "help_active"
META_KEY = "help_context"
PRESET_KEY = "preset_answer"


def _normalise_source(value) -> str:
    return "part2" if str(value) == "part2" else "exam"


def _chat_key(source: str) -> str:
    return _CHAT_KEYS[_normalise_source(source)]


def _session_source() -> str:
    try:
        import streamlit as st

        value = str(st.session_state.get("help_source") or "")
    except Exception:
        return ""
    return value if value in SOURCES else ""


def active_source() -> str:
    value = _session_source()
    if value:
        return value
    value = str(ChatHistory.load_meta(_ACTIVE_KEY).get("source") or "")
    return value if value in SOURCES else ""


def context(source: str = "") -> dict:
    src = _normalise_source(source) if source else active_source()
    if not src:
        return {}
    raw = ChatHistory.load_meta(_chat_key(src)).get(META_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def active() -> bool:
    return bool(context().get("source"))


def messages() -> list[dict]:
    src = active_source()
    return ChatHistory.load(_chat_key(src)) if src else []


def save_messages(items) -> None:
    src = active_source()
    if src:
        ChatHistory.save(_chat_key(src), items)


def preset_answer() -> dict:
    """当前会话为当前题目保存的固定参考回答：{"question": ..., "answer": ...}。"""
    src = active_source()
    if not src:
        return {}
    raw = ChatHistory.load_meta(_chat_key(src)).get(PRESET_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def save_preset_answer(question: str, answer: str) -> None:
    src = active_source()
    if not src:
        return
    key = _chat_key(src)
    meta = ChatHistory.load_meta(key)
    meta[PRESET_KEY] = {
        "question": str(question or ""),
        "answer": str(answer or ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    ChatHistory.save_meta(key, meta)


def _migrate_legacy() -> None:
    """旧版只有一份 help 会话；按它记录的来源搬到对应会话里。"""
    meta = ChatHistory.load_meta(_LEGACY_KEY)
    ctx = meta.get(META_KEY)
    source = str(ctx.get("source") or "") if isinstance(ctx, dict) else ""
    if source not in SOURCES:
        return
    key = _chat_key(source)
    if ChatHistory.load(key) or ChatHistory.load_meta(key).get(META_KEY):
        return
    ChatHistory.save(key, ChatHistory.load(_LEGACY_KEY))
    ChatHistory.save_meta(key, meta)
    ChatHistory.clear(_LEGACY_KEY)
    meta.pop(META_KEY, None)
    ChatHistory.save_meta(_LEGACY_KEY, meta)


def start(source: str) -> dict:
    src = _normalise_source(source)
    try:
        import streamlit as st

        st.session_state["help_source"] = src
    except Exception:
        pass
    ChatHistory.save_meta(_ACTIVE_KEY, {"source": src})
    _migrate_legacy()
    key = _chat_key(src)
    meta = ChatHistory.load_meta(key)
    if not isinstance(meta.get(META_KEY), dict):
        meta[META_KEY] = {
            "source": src,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        ChatHistory.save_meta(key, meta)
    return context(src)


def clear(source: str = "") -> None:
    src = _normalise_source(source) if source else active_source()
    if not src:
        return
    key = _chat_key(src)
    ChatHistory.clear(key)
    meta = ChatHistory.load_meta(key)
    meta.pop(META_KEY, None)
    meta.pop(PRESET_KEY, None)
    ChatHistory.save_meta(key, meta)
    if active_source() == src:
        try:
            import streamlit as st

            st.session_state.pop("help_source", None)
        except Exception:
            pass
        ChatHistory.save_meta(_ACTIVE_KEY, {})


__all__ = [
    "active",
    "active_source",
    "clear",
    "context",
    "messages",
    "preset_answer",
    "save_messages",
    "save_preset_answer",
    "start",
]
