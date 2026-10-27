# utils/LongNotes.py

"""按日期归档的长文本笔记：语法知识、范文、阅读摘录等。"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LONG_NOTES_PATH = Path(
    os.getenv("LONG_NOTES_PATH") or (_PROJECT_ROOT / "data" / "long_notes.json")
)
_LOCK = threading.RLock()

_TITLE_PROMPT = """You write short Chinese titles for personal study notes.

Read the note below and give it a concise, descriptive title.

RULES
- Simplified Chinese, at most 18 characters.
- No quotation marks, no numbering, no trailing colon.
- Capture the main topic, not just the first sentence.
- If the note is an English essay or grammar explanation, the title should still be Chinese.

Output JSON only:
{"title": "..."}

NOTE:
__CONTENT__
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_title(value) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = title.strip('"“”\'`')
    title = re.sub(r"^标题[:：]\s*", "", title)
    title = title.strip("-•# ").strip()
    return title[:40]


def _fallback_title(content: str) -> str:
    text = re.sub(r"[#*`>_\-]+", " ", content or "").strip()
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return (first[:24] or "未命名笔记")


def _normalize_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return date.today().isoformat()


def _as_date(value):
    try:
        return datetime.strptime(_normalize_date(value), "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def generate_title(content: str) -> str:
    """根据正文生成一个简短中文标题；失败时退回正文首行。"""
    prompt = _TITLE_PROMPT.replace("__CONTENT__", (content or "")[:4000])
    try:
        from utils.llm import call_llm_json

        data = call_llm_json(
            prompt, temperature=0.2, num_predict=80, fallback={}, timeout=30
        )
        title = _clean_title(data.get("title")) if isinstance(data, dict) else ""
    except Exception:
        logger.exception("生成长文本标题失败")
        title = ""
    return title or _fallback_title(content)


def _load_raw() -> list[dict]:
    if not LONG_NOTES_PATH.exists():
        return []
    try:
        data = json.loads(LONG_NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries", []) if isinstance(data, dict) else []
    return entries if isinstance(entries, list) else []


def _save_raw(entries: list[dict]) -> None:
    LONG_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"version": 1, "entries": entries}, ensure_ascii=False, indent=2
    )
    tmp = LONG_NOTES_PATH.with_name(LONG_NOTES_PATH.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, LONG_NOTES_PATH)


def load_notes() -> list[dict]:
    with _LOCK:
        raw = _load_raw()
    notes: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        title = _clean_title(item.get("title")) or _fallback_title(content)
        notes.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex[:12]),
                "date": _normalize_date(item.get("date")),
                "title": title,
                "content": content,
                "created_at": str(item.get("created_at") or _now()),
                "updated_at": str(item.get("updated_at") or item.get("created_at") or _now()),
            }
        )
    notes.sort(
        key=lambda note: (note["date"], note["created_at"], note["updated_at"]),
        reverse=True,
    )
    return notes


def add_note(content: str, title: str = "", note_date=None) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("内容不能为空")
    title = _clean_title(title) or generate_title(content)
    note = {
        "id": uuid.uuid4().hex[:12],
        "date": _normalize_date(note_date),
        "title": title,
        "content": content,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _LOCK:
        entries = _load_raw()
        entries.append(note)
        _save_raw(entries)
    return note


def update_note(
    note_id: str, content: str, title: str = "", note_date=None
) -> dict | None:
    content = (content or "").strip()
    if not content:
        raise ValueError("内容不能为空")
    title = _clean_title(title) or generate_title(content)

    with _LOCK:
        entries = _load_raw()
        for index, note in enumerate(entries):
            if str(note.get("id")) != str(note_id):
                continue
            updated = {
                "id": str(note.get("id")),
                "date": _normalize_date(note_date),
                "title": title,
                "content": content,
                "created_at": str(note.get("created_at") or _now()),
                "updated_at": _now(),
            }
            entries[index] = updated
            _save_raw(entries)
            return updated
    return None


def delete_note(note_id: str) -> bool:
    with _LOCK:
        entries = _load_raw()
        remaining = [n for n in entries if str(n.get("id")) != str(note_id)]
        if len(remaining) == len(entries):
            return False
        _save_raw(remaining)
    return True


def group_by_date(notes: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for note in notes:
        groups.setdefault(note["date"] or "未标日期", []).append(note)
    return groups


def render_long_notes() -> None:
    """长文本笔记的完整界面：新增、按日期分组、编辑、删除。"""
    import streamlit as st

    notes = load_notes()

    if st.session_state.get("ln_flash"):
        st.success(st.session_state.ln_flash)
        st.session_state.ln_flash = ""

    st.subheader("📝 长文本笔记")
    st.caption("语法知识、范文、阅读摘录；按日期归档，标题留空会自动生成。")

    with st.expander("➕ 新增长文本", expanded=not notes):
        with st.form("ln_add_form", clear_on_submit=True):
            content = st.text_area(
                "内容",
                height=320,
                key="ln_add_content",
                placeholder="把大段语法知识、范文、阅读笔记贴在这里……",
            )
            col_title, col_date = st.columns([3, 1])
            title = col_title.text_input(
                "标题（留空自动生成）", key="ln_add_title"
            )
            note_date = col_date.date_input(
                "日期", value=date.today(), key="ln_add_date"
            )
            if st.form_submit_button(
                "保存笔记", type="primary", use_container_width=True
            ):
                if not content.strip():
                    st.warning("内容不能为空")
                else:
                    with st.spinner(
                        "正在保存..." if title.strip() else "正在生成标题并保存..."
                    ):
                        note = add_note(content, title, note_date)
                    st.session_state.ln_flash = (
                        f"已保存：{note['title']}（{note['date']}）"
                    )
                    st.rerun()

    if not notes:
        st.info("还没有长文本笔记。点上面的「新增长文本」，粘贴语法知识或范文即可。")
    else:
        for day, day_notes in group_by_date(notes).items():
            st.markdown(f"**{day}**")
            for note in day_notes:
                with st.expander(note["title"] or "未命名笔记"):
                    st.markdown(note["content"])
                    st.caption(
                        f"日期：{note['date']} ｜ 更新：{note['updated_at']}"
                    )

                    with st.form(f"ln_edit_{note['id']}"):
                        new_content = st.text_area(
                            "内容",
                            value=note["content"],
                            height=320,
                            key=f"ln_ec_{note['id']}",
                        )
                        edit_col1, edit_col2 = st.columns([3, 1])
                        new_title = edit_col1.text_input(
                            "标题（留空自动生成）",
                            value=note["title"],
                            key=f"ln_et_{note['id']}",
                        )
                        new_date = edit_col2.date_input(
                            "日期",
                            value=_as_date(note["date"]),
                            key=f"ln_ed_{note['id']}",
                        )
                        if st.form_submit_button(
                            "保存修改", use_container_width=True
                        ):
                            if not new_content.strip():
                                st.warning("内容不能为空")
                            else:
                                with st.spinner(
                                    "正在保存..."
                                    if new_title.strip()
                                    else "正在生成标题并保存..."
                                ):
                                    update_note(
                                        note["id"],
                                        new_content,
                                        new_title,
                                        new_date,
                                    )
                                st.session_state.ln_flash = (
                                    f"已更新：{note['date']}"
                                )
                                st.rerun()

                    confirm = st.checkbox(
                        "确认删除这条", key=f"ln_delok_{note['id']}"
                    )
                    if st.button(
                        "🗑 删除",
                        key=f"ln_del_{note['id']}",
                        disabled=not confirm,
                    ):
                        delete_note(note["id"])
                        st.session_state.ln_flash = f"已删除：{note['title']}"
                        st.rerun()

    with st.sidebar:
        st.subheader("📝 长文本笔记")
        st.caption(f"共 {len(notes)} 条")
        st.download_button(
            "⬇️ 导出长文本 JSON",
            data=json.dumps(
                {"version": 1, "entries": notes}, ensure_ascii=False, indent=2
            ),
            file_name="long_notes.json",
            mime="application/json",
            use_container_width=True,
        )
        st.caption("数据文件：data/long_notes.json")
