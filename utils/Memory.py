# utils/Memory.py

"""娱乐角色（猫娘 / 心理咨询师 / 学业导师）的跨会话长期记忆。

每个角色一份记忆，保存在 data/memories.json：
- summary: 对这个用户的简短画像
- facts: 重要事实 / 共同经历

聊天本身仍然每次从开场白开始；这里只保存“值得记住”的内容。
"""

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
MEMORY_PATH = Path(
    os.getenv("MEMORY_PATH") or (_PROJECT_ROOT / "data" / "memories.json")
)
_LOCK = threading.RLock()

_MAX_FACTS = 8
_MAX_SUMMARY = 300


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clean_facts(facts) -> list[str]:
    if isinstance(facts, str):
        items = re.split(r"[\n；;]+", facts)
    elif isinstance(facts, (list, tuple)):
        items = list(facts)
    else:
        items = []
    cleaned: list[str] = []
    for item in items:
        fact = _one_line(item).strip("-• ").strip()
        if fact and fact not in cleaned:
            cleaned.append(fact[:50])
    return cleaned[:_MAX_FACTS]


def _load_all() -> dict:
    if not MEMORY_PATH.exists():
        return {}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    personas = data.get("personas", {}) if isinstance(data, dict) else {}
    return personas if isinstance(personas, dict) else {}


def _save_all(personas: dict) -> None:
    save_json(MEMORY_PATH, {"version": 1, "personas": personas})


def load_memory(key: str) -> dict:
    with _LOCK:
        raw = _load_all().get(key) or {}
    return {
        "summary": _one_line(raw.get("summary"))[:_MAX_SUMMARY],
        "facts": _clean_facts(raw.get("facts")),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def memory_text(key: str) -> str:
    memory = load_memory(key)
    if not memory["summary"] and not memory["facts"]:
        return ""
    parts = [memory["summary"]] if memory["summary"] else []
    if memory["facts"]:
        parts.append("要点：" + "；".join(memory["facts"]))
    return "\n".join(parts)


def clear_memory(key: str) -> None:
    with _LOCK:
        personas = _load_all()
        if key in personas:
            personas.pop(key)
            _save_all(personas)


def update_memory(
    key: str,
    user_message: str,
    assistant_reply: str,
    persona_label: str = "",
) -> dict:
    """把这一轮对话合并进长期记忆；失败时保留旧记忆。"""
    old = load_memory(key)
    prompt = f"""You maintain the long-term memory of a roleplay companion.

PERSONA
{persona_label or key}

CURRENT MEMORY
Summary: {old['summary'] or '(empty)'}
Facts:
{chr(10).join('- ' + fact for fact in old['facts']) or '(empty)'}

NEW EXCHANGE
User: {user_message}
Companion: {assistant_reply}

TASK
Update the memory about the user across sessions.

KEEP
- stable facts: name, city, job/school, relationships, preferences, recurring goals or problems
- important shared experiences, promises, ongoing topics

DROP
- small talk and one-off details
- details not mentioned for a long time unless they are important
- sensitive one-off details unless clearly important

STYLE
- Simplified Chinese, third person ("用户...")
- summary: at most 200 Chinese characters
- facts: at most 8 short items, each at most 30 characters
- If nothing important remains, facts may be an empty list

Output JSON only:
{{"summary": "...", "facts": ["...", "..."]}}
"""
    try:
        from utils.llm import call_llm_json

        data = call_llm_json(
            prompt, temperature=0.2, num_predict=600, fallback={}, timeout=45
        )
    except Exception:
        logger.exception("更新角色记忆失败")
        return old

    if not isinstance(data, dict) or not data:
        return old

    new_summary = _one_line(data.get("summary"))[:_MAX_SUMMARY]
    raw_facts = data.get("facts")
    if raw_facts is None:
        new_facts = old["facts"]
    else:
        new_facts = _clean_facts(raw_facts)

    if not new_summary and not new_facts:
        return old

    summary = new_summary or old["summary"]
    facts = new_facts if raw_facts is not None else old["facts"]

    with _LOCK:
        personas = _load_all()
        personas[key] = {
            "summary": summary,
            "facts": facts,
            "updated_at": _now(),
        }
        _save_all(personas)
    return {"summary": summary, "facts": facts, "updated_at": _now()}


def render_memory_sidebar(key: str) -> None:
    """侧边栏里默认收起的记忆区，点开才显示内容和清空。"""
    import streamlit as st

    memory = load_memory(key)
    with st.sidebar:
        with st.expander("记忆", expanded=False):
            if memory["summary"]:
                st.caption(memory["summary"])
            for fact in memory["facts"]:
                st.caption(f"- {fact}")
            if not memory["summary"] and not memory["facts"]:
                st.caption("聊几次后，这里会记住关于你的重要信息。")
            st.caption("只保留重要内容；很久不提的细节会慢慢淡忘。")
            if st.button("清空这个角色的记忆", key=f"mem_clear_{key}"):
                clear_memory(key)
                st.rerun()
