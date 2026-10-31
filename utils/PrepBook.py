# utils/PrepBook.py

"""备课本：课计划的唯一候选池。

只保存“可以拿来练的点”，不再保存错题排期（errors / streak / due）。
数据在 data/prep_book.json：

    {
      "version": 1,
      "items": [
        {"source_key": "word:irritation", "label": "irritation（n. 恼怒）",
         "kind": "word", "source": "weak_word",
         "added_at": "2026-10-29 08:45:00.123456"}
      ],
      "seen": ["word:irritation"]
    }

规则：
- 候选只来自弱词、笔记本、用户手动加入；表达库不进备课本；
- 同一个词从两个来源来也只留一条；
- 不做模糊/语义去重；
- 上限 200，满了删 added_at 最久远的；当前计划里的点不删；
- 用户明确要练的点可以手动加入，也算 seen；
- 待整理知识点不在这里，由单独的模块管理。
"""

import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREP_PATH = Path(
    os.getenv("PREP_BOOK_PATH") or (_PROJECT_ROOT / "data" / "prep_book.json")
)
_LOCK = threading.RLock()

_MAX_ITEMS = 200
_MAX_LABEL = 120
_KIND_WORD = "word"
_KIND_PHRASE = "phrase"
# expression 只用于识别旧数据，同步时会被清掉；新候选不再来自表达库。
_SOURCES = ("weak_word", "notebook", "expression", "user_request")


def _now() -> str:
    # 带微秒，保证同一秒内加入的条目也有稳定先后顺序。
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _one_line(text, limit: int = _MAX_LABEL) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _label_key(label: str) -> str:
    value = _one_line(label)
    value = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", value).strip()
    value = re.sub(r"[。.!！?？,，;；:：]+$", "", value).strip()
    return value.casefold()


def _strip_list_marker(text: str) -> str:
    return _one_line(text).lstrip("- ").strip()


def _english_word(label: str) -> str:
    """取标签里的英文头词，用于判断是不是同一个单词。"""
    value = _strip_list_marker(label)
    value = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", value).strip()
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    return words[0].casefold() if words else ""


def _infer_kind(label: str) -> str:
    value = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", _strip_list_marker(label))
    if re.search(r"[\u4e00-\u9fff]", value):
        return _KIND_PHRASE
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", value)
    return _KIND_WORD if len(words) == 1 else _KIND_PHRASE


def _word_source_key(label: str) -> str:
    word = _english_word(label)
    return f"word:{word}" if word else ""


def _source_key_for(label: str, kind: str, source: str) -> str:
    if source == "expression":
        return "expression:" + _label_key(label)
    if kind == _KIND_WORD:
        key = _word_source_key(label)
        if key:
            return key
    return f"{source}:{_label_key(label)}"


def item_from_notebook(term: str, meaning: str) -> dict:
    """笔记本条目在备课本里的标签 / key；编辑和删除时用它对齐。"""
    from utils.LearnerProfile import notebook_label

    label = notebook_label(term, meaning)
    if not label:
        return {}
    kind = _infer_kind(label)
    return {
        "source_key": _source_key_for(label, kind, "notebook"),
        "label": label,
        "kind": kind,
        "source": "notebook",
    }


def _clean_item(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    label = _one_line(raw.get("label"))
    if not label:
        return None
    kind = str(raw.get("kind") or _infer_kind(label)).strip().lower()
    if kind not in (_KIND_WORD, _KIND_PHRASE):
        kind = _infer_kind(label)
    source = str(raw.get("source") or "user_request").strip().lower()
    if source not in _SOURCES:
        source = "user_request"
    source_key = _one_line(raw.get("source_key"), 160) or _source_key_for(
        label, kind, source
    )
    if not source_key:
        return None
    return {
        "source_key": source_key,
        "label": label,
        "kind": kind,
        "source": source,
        "added_at": str(raw.get("added_at") or _now()),
    }


def _empty() -> dict:
    return {"version": 1, "items": [], "seen": []}


def _load_raw() -> dict:
    data = load_json(PREP_PATH, {})
    return data if isinstance(data, dict) else {}


def _load_unlocked() -> tuple[list[dict], set[str]]:
    data = _load_raw()
    items: list[dict] = []
    seen: set[str] = set()
    raw_seen = data.get("seen")
    if isinstance(raw_seen, list):
        for key in raw_seen:
            value = _one_line(key, 160)
            if value:
                seen.add(value.casefold())

    raw_items = data.get("items")
    if isinstance(raw_items, list):
        for raw in raw_items:
            item = _clean_item(raw)
            if not item:
                continue
            key = item["source_key"].casefold()
            if key in {old["source_key"].casefold() for old in items}:
                continue
            items.append(item)
            seen.add(key)
    return items, seen


def _save_unlocked(items: list[dict], seen: set[str]) -> None:
    save_json(
        PREP_PATH,
        {
            "version": 1,
            "items": items[:_MAX_ITEMS],
            "seen": sorted(seen),
        },
    )


def _evict(items: list[dict], protected_keys: set[str]) -> list[dict]:
    """超过上限时删 added_at 最久远的；当前计划里的点不动。"""
    protected = {str(key).casefold() for key in (protected_keys or set())}
    while len(items) > _MAX_ITEMS:
        candidates = [
            item
            for item in items
            if item["source_key"].casefold() not in protected
        ]
        if not candidates:
            break
        oldest = min(candidates, key=lambda item: item["added_at"])
        items.remove(oldest)
        logger.info("备课本已满，移除最久远的条目：%s", oldest["label"])
    return items


def _append_item(
    items: list[dict],
    seen: set[str],
    *,
    label: str,
    kind: str,
    source: str,
    source_key: str = "",
    added_at: str = "",
    protected_keys: set[str] | None = None,
    skip_seen: bool = True,
) -> tuple[dict | None, bool]:
    label = _one_line(label)
    if not label:
        raise ValueError("empty label")
    key = _one_line(source_key, 160) or _source_key_for(label, kind, source)
    key_cf = key.casefold()
    existing = next(
        (item for item in items if item["source_key"].casefold() == key_cf), None
    )
    if existing:
        seen.add(key_cf)
        return existing, False
    if skip_seen and key_cf in seen:
        return None, False
    item = {
        "source_key": key,
        "label": label,
        "kind": kind,
        "source": source,
        "added_at": added_at or _now(),
    }
    items.append(item)
    seen.add(key_cf)
    _evict(items, protected_keys or set())
    return item, True


def _upsert_item(
    items: list[dict],
    seen: set[str],
    *,
    label: str,
    kind: str,
    source: str,
    source_key: str = "",
    protected_keys: set[str] | None = None,
) -> tuple[dict | None, bool, bool]:
    """新增或更新：同一个 key 的标签变了就改标签，不制造重复条目。"""
    label = _one_line(label)
    if not label:
        return None, False, False
    key = _one_line(source_key, 160) or _source_key_for(label, kind, source)
    key_cf = key.casefold()
    existing = next(
        (item for item in items if item["source_key"].casefold() == key_cf), None
    )
    if existing is not None:
        changed = existing.get("source") == source and (
            existing.get("label") != label or existing.get("kind") != kind
        )
        if changed:
            existing["label"] = label
            existing["kind"] = kind
        seen.add(key_cf)
        return existing, False, changed
    if key_cf in seen:
        return None, False, False
    item = {
        "source_key": key,
        "label": label,
        "kind": kind,
        "source": source,
        "added_at": _now(),
    }
    items.append(item)
    seen.add(key_cf)
    _evict(items, protected_keys or set())
    return item, True, False


def _weak_items() -> list[tuple[str, str, str]]:
    """返回 [(source_key, label, kind)]；用现有 weak_words 的格式。"""
    from utils.LearnerProfile import weak_words

    result = []
    for line in weak_words(limit=_MAX_ITEMS):
        raw = _strip_list_marker(line)
        if not raw:
            continue
        label = raw.split("·", 1)[0].strip()
        if not label:
            continue
        key = _word_source_key(label)
        if key:
            result.append((key, label, _KIND_WORD))
    return result


def _notebook_items() -> list[tuple[str, str, str]]:
    from utils.LearnerProfile import notebook_lines

    result = []
    for line in notebook_lines(limit=_MAX_ITEMS):
        raw = _strip_list_marker(line)
        if not raw:
            continue
        raw = raw.split("·", 1)[0].strip()
        term, _, meaning = raw.partition(" — ")
        term = term.strip()
        meaning = meaning.strip()
        if not term:
            continue
        item = item_from_notebook(term, meaning)
        if not item:
            continue
        result.append((item["source_key"], item["label"], item["kind"]))
    return result


def sync_candidates(protected_keys: set[str] | None = None) -> dict:
    """把弱词、笔记本同步进备课本，并清掉已经不存在的自动来源。

    - 同一个 key 还在：标签变了就更新（比如笔记本里改了中文意思）；
    - 来源真的没了：移除条目，并把 key 从 seen 里放出来，以后重新添加还能进来；
    - 同一个词还在弱词/另一个来源里：保留，不误删；
    - 读取某个来源失败时，不清那个来源的旧条目；
    - 表达库不再进备课本，旧版本加进来的 expression 条目会在这里移除。
    """
    with _LOCK:
        items, seen = _load_unlocked()
        rows_by_source: dict[str, list[tuple[str, str, str]]] = {}
        current_keys: set[str] = set()
        failed: set[str] = set()
        for source, getter in (
            ("weak_word", _weak_items),
            ("notebook", _notebook_items),
        ):
            try:
                rows = getter()
            except Exception:
                logger.exception("读取备课本来源失败：%s", getter.__name__)
                failed.add(source)
                continue
            rows_by_source[source] = rows
            for source_key, _label, _kind in rows:
                current_keys.add(source_key.casefold())

        added = updated = removed = 0
        for source, rows in rows_by_source.items():
            for source_key, label, kind in rows:
                _, created, changed = _upsert_item(
                    items,
                    seen,
                    label=label,
                    kind=kind,
                    source=source,
                    source_key=source_key,
                    protected_keys=protected_keys,
                )
                added += int(created)
                updated += int(changed)

        stale = [
            item
            for item in items
            if item.get("source") in ("weak_word", "notebook", "expression")
            and item.get("source") not in failed
            and item["source_key"].casefold() not in current_keys
        ]
        for item in stale:
            items.remove(item)
            removed += 1
            key_cf = item["source_key"].casefold()
            if key_cf not in current_keys:
                seen.discard(key_cf)

        _save_unlocked(items, seen)
        return {
            "added": added,
            "updated": updated,
            "removed": removed,
            "total": len(items),
        }


def candidates(protected_keys: set[str] | None = None) -> list[dict]:
    """全部 active 条目，按 added_at 从新到旧。"""
    with _LOCK:
        items, seen = _load_unlocked()
        items = _evict(items, protected_keys or set())
        _save_unlocked(items, seen)
        return [
            dict(item)
            for item in sorted(items, key=lambda item: item["added_at"], reverse=True)
        ]


def get(source_key: str) -> dict | None:
    key = str(source_key or "").casefold()
    return next(
        (dict(item) for item in candidates() if item["source_key"].casefold() == key),
        None,
    )


def find_exact(label: str) -> dict | None:
    key = _label_key(label)
    if not key:
        return None
    return next(
        (dict(item) for item in candidates() if _label_key(item["label"]) == key),
        None,
    )


def add_user_point(
    label: str,
    kind: str = "",
    *,
    protected_keys: set[str] | None = None,
) -> tuple[dict, bool]:
    """用户明确要练的点：加入备课本；完全一样则返回已有条目。"""
    with _LOCK:
        items, seen = _load_unlocked()
        key = _source_key_for(label, kind or _infer_kind(label), "user_request")
        item, created = _append_item(
            items,
            seen,
            label=label,
            kind=kind or _infer_kind(label),
            source="user_request",
            source_key=key,
            protected_keys=protected_keys,
            skip_seen=False,
        )
        _save_unlocked(items, seen)
        return dict(item or {}), created


def remove_item(source_key: str) -> bool:
    key = str(source_key or "").casefold()
    with _LOCK:
        items, seen = _load_unlocked()
        before = len(items)
        items = [item for item in items if item["source_key"].casefold() != key]
        if len(items) == before:
            return False
        seen.add(key)
        _save_unlocked(items, seen)
        return True


__all__ = [
    "add_user_point",
    "candidates",
    "find_exact",
    "get",
    "remove_item",
    "sync_candidates",
]
