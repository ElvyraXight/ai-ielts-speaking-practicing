# utils/Notebook.py

"""单词 / 词组笔记本的数据层。

- 数据保存在 data/notebook.json，写入是原子的。
- 新增时如果没填中文意思 / 标签 / 分组，会自动调用模型补全：
  词性前缀、一词多义、雅思分类标签、语义分组。
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_PATH = Path(
    os.getenv("NOTEBOOK_PATH") or (_PROJECT_ROOT / "data" / "notebook.json")
)
_LOCK = threading.RLock()

_TAG_TAXONOMY = [
    "教育", "工作", "科技", "环境", "健康", "社会", "文化", "媒体",
    "旅行", "人物", "情绪", "描述", "生活", "观点", "口语", "写作",
    "Part 2", "Part 3",
]

_ENRICH_PROMPT = """You are an IELTS vocabulary notebook assistant.

WORD / PHRASE
__TERM__

MEANING ALREADY PROVIDED (keep it unchanged if not empty)
__MEANING__

EXISTING GROUPS (reuse one if the meaning is closely related)
__GROUPS__

EXISTING TAGS (reuse when appropriate)
__TAGS__

Return JSON:
{"meaning": "...", "tags": ["..."], "group": "..."}

MEANING RULES
- Chinese, concise, like class notes; no examples, no English definitions, no brackets.
- Prefix each part of speech: n. v. a. ad. phr. etc.
- Separate different parts of speech with "；".
- Within one part of speech, separate clearly different common senses with "/" (usually 1-3; omit rare or technical senses).
- Near-synonyms count as ONE sense: write only the most common, e.g. 开心的 (not 开心的/高兴的).
- SELF-CHECK EVERY "/": if the two Chinese glosses are close synonyms or paraphrases, delete all but the most common one.
  Correct: a. 开心的 ｜ a. 一丝不苟的 ｜ n. 银行/河岸 ｜ n. 光/灯
  Wrong: a. 开心的/高兴的 ｜ a. 一丝不苟的/极仔细的
- Only use "/" when the senses are clearly different concepts, not paraphrases.
- If the word is a phrase, use "phr." and give its most common meaning.
- If MEANING ALREADY PROVIDED is not empty, return it exactly.

TAG RULES
- Choose 1-3 tags from this IELTS taxonomy: __TAXONOMY__
- Reuse an existing tag when it fits.

GROUP RULES
- A short Chinese semantic cluster, 2-6 characters.
- Prefer one of these standard groups when it fits: 积极情绪, 消极情绪, 态度表达, 人物性格, 学习动作, 工作职场, 科技产品, 环境问题, 旅行经历, 日常场所, 日常物品, 饮食健康, 媒体娱乐, 社会现象, 时间频率, 程度描述, 因果关系.
- Only reuse an EXISTING GROUP if the new meaning is a near-synonym or the same narrow situation (e.g. happy / delighted -> 积极情绪). Do NOT reuse a group just because the word is also common.
- If no existing or standard group fits, create a new concise group. Avoid "其他" unless nothing fits.
- The group must describe the meaning, not the part of speech or a broad tag.
- Examples: light -> 日常物品 or 光线照明; take ... for granted -> 态度表达; bank -> 日常场所.

Output JSON only.
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, (list, tuple)):
        items = list(tags)
    else:
        items = re.split(r"[,，;；]+", str(tags or ""))
    cleaned: list[str] = []
    for item in items:
        tag = _one_line(item)
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _normalize(raw: dict) -> dict:
    created = str(raw.get("created_at") or _now())
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:12]),
        "term": _one_line(raw.get("term")),
        "meaning": _one_line(raw.get("meaning")),
        "example": str(raw.get("example", "")).strip(),
        "note": str(raw.get("note", "")).strip(),
        "tags": _clean_tags(raw.get("tags", [])),
        "group": _one_line(raw.get("group"))[:12],
        "source": _one_line(raw.get("source")),
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


def _enrich(term: str, meaning: str = "", entries=None) -> dict:
    """调用模型补全意思 / 标签 / 语义分组；失败时返回空值。"""
    entries = entries or []
    groups: list[str] = []
    seen_tags: list[str] = []
    for entry in reversed(entries):
        group = entry.get("group") or ""
        if group and group not in groups:
            groups.append(group)
        for tag in entry.get("tags", []):
            if tag not in seen_tags:
                seen_tags.append(tag)

    prompt = (
        _ENRICH_PROMPT.replace("__TERM__", term)
        .replace("__MEANING__", meaning or "(none)")
        .replace("__GROUPS__", "、".join(groups[:25]) or "(none)")
        .replace("__TAGS__", "、".join(seen_tags[:30]) or "(none)")
        .replace("__TAXONOMY__", "、".join(_TAG_TAXONOMY))
    )

    try:
        from utils.llm import call_llm_json

        data = call_llm_json(
            prompt, temperature=0.2, num_predict=700, fallback={}, timeout=30
        )
    except Exception:
        logger.exception("笔记本自动补全失败")
        data = {}

    generated_meaning = _one_line(data.get("meaning"))
    generated_tags = _clean_tags(data.get("tags"))
    group = _one_line(data.get("group"))[:12]
    if meaning.strip():
        generated_meaning = meaning.strip()
    return {"meaning": generated_meaning, "tags": generated_tags, "group": group}


def add_entry(
    term: str,
    meaning: str = "",
    example: str = "",
    note: str = "",
    tags="",
    source: str = "",
    group: str = "",
) -> dict:
    term = _one_line(term)
    if not term:
        raise ValueError("term is empty")

    meaning = _one_line(meaning)
    group = _one_line(group)
    tags_list = _clean_tags(tags)

    if not meaning or not tags_list or not group:
        entries = load_entries()
        meta = _enrich(term, meaning, entries)
        meaning = meaning or meta["meaning"]
        tags_list = tags_list or meta["tags"]
        group = group or meta["group"]

    entry = _normalize(
        {
            "term": term,
            "meaning": meaning,
            "example": example,
            "note": note,
            "tags": tags_list or ["未分类"],
            "group": group or "未分组",
            "source": source,
        }
    )
    with _LOCK:
        entries = _load_unlocked()
        entries.append(entry)
        _save_unlocked(entries)
    return entry


def update_entry(entry_id: str, **fields) -> dict | None:
    allowed = {"term", "meaning", "example", "note", "tags", "source", "group"}
    with _LOCK:
        entries = _load_unlocked()
        for entry in entries:
            if entry["id"] != entry_id:
                continue
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "tags":
                    entry[key] = _clean_tags(value) or ["未分类"]
                elif key == "term":
                    cleaned = _one_line(value)
                    if not cleaned:
                        raise ValueError("term is empty")
                    entry[key] = cleaned
                elif key == "group":
                    entry[key] = _one_line(value)[:12] or "未分组"
                elif key == "meaning":
                    entry[key] = _one_line(value)
                else:
                    entry[key] = str(value or "").strip()
            entry["updated_at"] = _now()
            _save_unlocked(entries)
            return entry
    return None


def backfill_entries() -> int:
    """给旧笔记补全缺失的意思 / 标签 / 分组，返回处理的条数。"""
    entries = load_entries()
    pending = [
        entry
        for entry in entries
        if not entry["meaning"]
        or not entry["tags"]
        or entry["tags"] == ["未分类"]
        or not entry["group"]
        or entry["group"] == "未分组"
    ]
    if not pending:
        return 0

    touched = 0
    for entry in pending:
        others = [item for item in entries if item is not entry]
        meta = _enrich(entry["term"], entry["meaning"], others)
        changed = False
        if not entry["meaning"] and meta["meaning"]:
            entry["meaning"] = meta["meaning"]
            changed = True
        if (not entry["tags"] or entry["tags"] == ["未分类"]) and meta["tags"]:
            entry["tags"] = meta["tags"]
            changed = True
        if (not entry["group"] or entry["group"] == "未分组") and meta["group"]:
            entry["group"] = meta["group"]
            changed = True
        if changed:
            entry["updated_at"] = _now()
            touched += 1

    if touched:
        with _LOCK:
            _save_unlocked(entries)
    return touched


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
                entry["group"],
                " ".join(entry["tags"]),
            ]
        ).lower()
        if query in haystack:
            result.append(entry)
    return result


def render_quick_add(source: str, key_prefix: str) -> None:
    """侧边栏快速收藏：不填意思/标签时自动补全。"""
    import streamlit as st

    with st.expander("➕ 加入笔记本", expanded=False):
        with st.form(f"nb_quick_{key_prefix}", clear_on_submit=True):
            term = st.text_input(
                "单词 / 词组",
                key=f"{key_prefix}_nb_term",
                placeholder="e.g. take ... for granted",
            )
            meaning = st.text_input("中文意思（留空自动生成）", key=f"{key_prefix}_nb_meaning")
            example = st.text_area("例句（可选）", key=f"{key_prefix}_nb_example", height=70)
            tags = st.text_input("标签（留空自动分类）", key=f"{key_prefix}_nb_tags")
            submitted = st.form_submit_button("保存到笔记本", use_container_width=True)
            if submitted:
                if not term.strip():
                    st.warning("先填一个单词或词组")
                else:
                    with st.spinner("正在补全翻译 / 标签 / 分组..."):
                        entry = add_entry(
                            term,
                            meaning=meaning,
                            example=example,
                            tags=tags,
                            source=source,
                        )
                    st.success(
                        f"已保存：{entry['term']} ｜ {entry['meaning'] or '待补充'}"
                        f" ｜ 分组：{entry['group']}"
                    )
                    st.toast(f"📓 已加入笔记本：{entry['term']}")
