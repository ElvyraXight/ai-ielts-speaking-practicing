# utils/Part2Card.py

"""Part 2 题卡与答案草稿的本地持久化：刷新页面、重开软件后仍是同一张卡、同一份答案。

session_state 只活在一个浏览器会话里；题卡和答案草稿另外落一份到
data/part2_card.json，页面启动时先读文件，只有文件也没有时才重新生成。
答案跟着题卡走：主动「换一道题」才清空。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from utils.storage import load_json, save_json

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CARD_PATH = Path(
    os.getenv("PART2_CARD_PATH")
    or (_PROJECT_ROOT / "data" / "part2_card.json")
)
SESSION_KEY = "part2_cue_card"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _session_get() -> str:
    try:
        import streamlit as st

        return str(st.session_state.get(SESSION_KEY) or "").strip()
    except Exception:
        return ""


def _session_set(value: str) -> None:
    try:
        import streamlit as st

        st.session_state[SESSION_KEY] = value
    except Exception:
        pass


def _load_data() -> dict:
    data = load_json(CARD_PATH, {})
    return dict(data) if isinstance(data, dict) else {}


def load() -> str:
    return str(_load_data().get("cue_card") or "").strip()


def save(cue_card: str) -> str:
    value = str(cue_card or "").strip()
    if not value:
        return ""
    data = _load_data()
    data.update({"version": 1, "cue_card": value, "updated_at": _now()})
    save_json(CARD_PATH, data)
    _session_set(value)
    return value


def load_answer() -> str:
    """学生写过的答案草稿；没有就返回空串。"""
    return str(_load_data().get("answer") or "")


def save_answer(answer: str) -> None:
    """保存答案草稿；空字符串表示清空（例如主动「换一道题」）。"""
    data = _load_data()
    data["version"] = 1
    data["answer"] = str(answer or "")
    data["answer_updated_at"] = _now()
    save_json(CARD_PATH, data)


def get() -> str:
    """当前题卡：优先本次会话，其次磁盘；读到磁盘后同步回 session。"""
    current = _session_get()
    if current:
        return current
    value = load()
    if value:
        _session_set(value)
    return value


def get_or_create(generator) -> str:
    """优先复用已有题卡；只有会话和磁盘都没有时才生成并落盘。"""
    current = get()
    if current:
        if load() != current:
            save(current)
        return current
    generated = str(generator() or "").strip()
    if generated:
        save(generated)
    return generated


__all__ = [
    "CARD_PATH",
    "get",
    "get_or_create",
    "load",
    "load_answer",
    "save",
    "save_answer",
]
