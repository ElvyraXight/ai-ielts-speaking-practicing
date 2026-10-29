# utils/TutorErrors.py

"""待整理知识点：陪练或聊天指出、但还没决定要不要加入备课本的内容。

像猫娘记忆一样只做“记住”和“合并”，不做自动加入：

- 同一个/相似错误合并，count +1；
- 按次数、最近出现排序，最熟悉的在前；
- 上限 50，超出时丢最不熟悉/最久远的；
- 用户选择“加入备课本”或“删除”后，从列表移除；
- 不做 summary，也不碰备课本（由页面调用 PrepBook）。
"""

import difflib
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ERRORS_PATH = Path(
    os.getenv("TUTOR_ERRORS_PATH")
    or (_PROJECT_ROOT / "data" / "tutor_errors.json")
)
_LOCK = threading.RLock()

_MAX_ITEMS = 50
_MAX_TEXT = 120
_SIMILARITY = 0.72


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:_MAX_TEXT]


def _normalise(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def _similar(a: str, b: str) -> bool:
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return False
    if na == nb or (len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na)):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= _SIMILARITY


def _load_unlocked() -> list[dict]:
    data = load_json(ERRORS_PATH, {})
    raw_items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        return []
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        text = _one_line(raw.get("text"))
        if not text:
            continue
        stamp = _now()
        items.append(
            {
                "text": text,
                "count": max(1, int(raw.get("count") or 1)),
                "first": str(raw.get("first") or stamp),
                "last": str(raw.get("last") or stamp),
            }
        )
    return items


def _save_unlocked(items: list[dict]) -> None:
    items = sorted(items, key=lambda item: (item["count"], item["last"]), reverse=True)
    save_json(ERRORS_PATH, {"version": 1, "items": items[:_MAX_ITEMS]})


def add_errors(values) -> int:
    """写入一批错误；相似错误合并并增加次数。返回新增/命中的条数。"""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return 0
    added = 0
    with _LOCK:
        items = _load_unlocked()
        stamp = _now()
        for raw in values:
            text = _one_line(raw)
            if not text:
                continue
            existing = next(
                (item for item in items if _similar(item["text"], text)), None
            )
            if existing:
                existing["count"] += 1
                existing["last"] = stamp
            else:
                items.append(
                    {"text": text, "count": 1, "first": stamp, "last": stamp}
                )
            added += 1
        _save_unlocked(items)
    return added


def items() -> list[dict]:
    """按最熟悉（次数、最近）排序。"""
    with _LOCK:
        return sorted(
            _load_unlocked(),
            key=lambda item: (item["count"], item["last"]),
            reverse=True,
        )


def remove(text: str) -> bool:
    with _LOCK:
        items = _load_unlocked()
        value = _one_line(text)
        before = len(items)
        items = [item for item in items if not _similar(item["text"], value)]
        if len(items) == before:
            return False
        _save_unlocked(items)
        return True


def consume(text: str) -> dict | None:
    """加入备课本前调用：取出并删除这条错误。"""
    target = next(
        (item for item in items() if _similar(item["text"], _one_line(text))), None
    )
    if not target:
        return None
    remove(target["text"])
    return target


def clear() -> None:
    with _LOCK:
        save_json(ERRORS_PATH, {"version": 1, "items": []})


__all__ = ["add_errors", "clear", "consume", "items", "remove"]
