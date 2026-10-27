# utils/Notebook.py

"""单词 / 词组笔记本的数据层。

数据保存在项目根目录的 data/notebook.json，写入是原子的；
每次修改后立即落盘，重启 App 不会丢。
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_PATH = Path(
    os.getenv("NOTEBOOK_PATH") or (_PROJECT_ROOT / "data" / "notebook.json")
)
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, (list, tuple)):
        items = list(tags)
    else:
        items = re.split(r"[,，;；]+", str(tags or ""))
    cleaned: list[str] = []
    for item in items:
        tag = str(item).strip()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _normalize(raw: dict) -> dict:
    created = str(raw.get("created_at") or _now())
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:12]),
        "term": str(raw.get("term", "")).strip(),
        "meaning": str(raw.get("meaning", "")).strip(),
        "example": str(raw.get("example", "")).strip(),
        "note": str(raw.get("note", "")).strip(),
        "tags": _clean_tags(raw.get("tags", [])),
        "source": str(raw.get("source", "")).strip(),
        "created_at": created,
        "updated_at": str(raw.get("updated_at") or created),
    }


def _load_unlocked() -> list[dict]:
    if not NOTEBOOK_PATH.exists():
        return []
    try:
        data = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("entries", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("term", "")).strip():
            entries.append(_normalize(item))
    return entries


def _save_unlocked(entries: list[dict]) -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"version": 1, "entries": entries}, ensure_ascii=False, indent=2
    )
    tmp = NOTEBOOK_PATH.with_name(NOTEBOOK_PATH.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, NOTEBOOK_PATH)


def load_entries() -> list[dict]:
    with _LOCK:
        return _load_unlocked()


def add_entry(
    term: str,
    meaning: str = "",
    example: str = "",
    note: str = "",
    tags="",
    source: str = "",
) -> dict:
    term = str(term or "").strip()
    if not term:
        raise ValueError("term is empty")
    entry = _normalize(
        {
            "term": term,
            "meaning": meaning,
            "example": example,
            "note": note,
            "tags": tags,
            "source": source,
        }
    )
    with _LOCK:
        entries = _load_unlocked()
        entries.append(entry)
        _save_unlocked(entries)
    return entry


def update_entry(entry_id: str, **fields) -> dict | None:
    allowed = {"term", "meaning", "example", "note", "tags", "source"}
    with _LOCK:
        entries = _load_unlocked()
        for entry in entries:
            if entry["id"] != entry_id:
                continue
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "tags":
                    entry[key] = _clean_tags(value)
                elif key == "term":
                    cleaned = str(value or "").strip()
                    if not cleaned:
                        raise ValueError("term is empty")
                    entry[key] = cleaned
                else:
                    entry[key] = str(value or "").strip()
            entry["updated_at"] = _now()
            _save_unlocked(entries)
            return entry
    return None


def delete_entry(entry_id: str) -> bool:
    with _LOCK:
        entries = _load_unlocked()
        kept = [entry for entry in entries if entry["id"] != entry_id]
        if len(kept) == len(entries):
            return False
        _save_unlocked(kept)
        return True


def stats(entries: list[dict] | None = None) -> dict:
    entries = load_entries() if entries is None else entries
    week_ago = datetime.now().timestamp() - 7 * 24 * 3600
    week_count = 0
    for entry in entries:
        try:
            if datetime.strptime(entry["created_at"], "%Y-%m-%d %H:%M:%S").timestamp() >= week_ago:
                week_count += 1
        except ValueError:
            pass
    return {
        "total": len(entries),
        "week": week_count,
        "tags": len({tag for entry in entries for tag in entry["tags"]}),
        "with_example": sum(1 for entry in entries if entry["example"]),
    }


def search_entries(entries: list[dict], query: str) -> list[dict]:
    query = (query or "").strip().lower()
    if not query:
        return entries
    result = []
    for entry in entries:
        haystack = " ".join(
            [
                entry["term"],
                entry["meaning"],
                entry["example"],
                entry["note"],
                " ".join(entry["tags"]),
            ]
        ).lower()
        if query in haystack:
            result.append(entry)
    return result


def render_quick_add(source: str, key_prefix: str) -> None:
    """侧边栏快速收藏：单词 + 意思 + 例句，直接写入笔记本。"""
    import streamlit as st

    with st.expander("➕ 加入笔记本", expanded=False):
        with st.form(f"nb_quick_{key_prefix}", clear_on_submit=True):
            term = st.text_input(
                "单词 / 词组",
                key=f"{key_prefix}_nb_term",
                placeholder="e.g. take ... for granted",
            )
            meaning = st.text_input("中文意思", key=f"{key_prefix}_nb_meaning")
            example = st.text_area("例句（可选）", key=f"{key_prefix}_nb_example", height=70)
            tags = st.text_input("标签（可选，逗号分隔）", key=f"{key_prefix}_nb_tags")
            submitted = st.form_submit_button("保存到笔记本", use_container_width=True)
            if submitted:
                if not term.strip():
                    st.warning("先填一个单词或词组")
                else:
                    add_entry(
                        term,
                        meaning=meaning,
                        example=example,
                        tags=tags,
                        source=source,
                    )
                    st.success(f"已保存：{term.strip()}")
                    st.toast(f"📓 已加入笔记本：{term.strip()}")
