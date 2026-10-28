# utils/Practice.py

"""老师的备课本：哪些点最该练、错得多不多、下次什么时候再练。

数据在 data/practice.json（已 gitignore）：

    {"version": 1, "items": [
        {"label": "abandon（v. 放弃）", "kind": "word",
         "errors": 3, "streak": 1, "interval": 2, "due": "2026-10-30",
         "attempts": 4, "hits": 1, "last": "...", "last_result": "good",
         "note": "搭配不熟", "created": "..."}
    ]}

规则：
- 错得多（errors 高）优先练；答对后间隔变长、优先级下降。
- 错过的点要连续 2 次答对，才按“错得少”对待、开始明显降频。
- 连续 3 次用得好，就从备课本和 practice.json 里删除。
- 删除后如果再练到、并且答错，会当新的问题重新入库。
"""

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.LearnerProfile import expression_lines, notebook_lines, weak_words
from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRACTICE_PATH = Path(
    os.getenv("PRACTICE_PATH") or (_PROJECT_ROOT / "data" / "practice.json")
)

_LOCK = threading.RLock()
_MAX_ITEMS = 60
_SEED_LIMIT = 10
_COOLDOWN_DAYS = 3
_MASTERED_COOLDOWN_DAYS = 10
_MASTERED_STRENGTH = 4
_MAX_STRENGTH = 5
_MAX_LABEL = 80
_HIGH_ERROR = 2
_RETIRE_STREAK = 3
_MAX_INTERVAL = 30


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return date.today()


def _parse_day(stamp: str) -> date | None:
    try:
        return datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _one_line(text, limit: int = _MAX_LABEL) -> str:
    return " ".join(str(text or "").split())[:limit]


def _load() -> list[dict]:
    data = load_json(PRACTICE_PATH, {})
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    cleaned = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        label = _one_line(raw.get("label"))
        if not label or raw.get("retired"):
            continue
        attempts = max(0, int(raw.get("attempts") or 0))
        hits = max(0, int(raw.get("hits") or 0))
        errors = raw.get("errors")
        if not isinstance(errors, int):
            errors = max(0, attempts - hits)
        last = str(raw.get("last") or "")
        interval = max(1, int(raw.get("interval") or 1))
        due = str(raw.get("due") or "")
        if not due:
            last_day = _parse_day(last)
            due = (
                (last_day + timedelta(days=interval)).isoformat()
                if last_day
                else _today().isoformat()
            )
        cleaned.append(
            {
                "label": label,
                "kind": str(raw.get("kind") or "issue")[:20],
                "strength": max(0, min(_MAX_STRENGTH, int(raw.get("strength") or 0))),
                "errors": max(0, errors),
                "streak": max(0, int(raw.get("streak") or 0)),
                "interval": interval,
                "due": due,
                "attempts": attempts,
                "hits": hits,
                "last": last,
                "last_result": str(raw.get("last_result") or ""),
                "note": _one_line(raw.get("note"), 80),
                "created": str(raw.get("created") or ""),
            }
        )
    return cleaned


def _save(items: list[dict]) -> None:
    save_json(PRACTICE_PATH, {"version": 1, "items": items[:_MAX_ITEMS]})


def _find(items: list[dict], label: str) -> dict | None:
    key = _one_line(label).lower()
    for item in items:
        if item["label"].lower() == key:
            return item
    return None


def _new_item(label: str, kind: str = "issue", note: str = "") -> dict:
    return {
        "label": _one_line(label),
        "kind": kind,
        "strength": 1 if kind in ("word", "phrase") else 0,
        "errors": 0,
        "streak": 0,
        "interval": 1,
        "due": _today().isoformat(),
        "attempts": 0,
        "hits": 0,
        "last": "",
        "last_result": "",
        "note": _one_line(note, 80),
        "created": _now(),
    }


def _seed(items: list[dict]) -> list[dict]:
    """用最近要复习的词和表达库补几条初始练习点。"""
    existing = {item["label"].lower() for item in items}
    seeds: list[tuple[str, str]] = []

    for line in weak_words(limit=_SEED_LIMIT):
        # 形如 "- abandon（v. 放弃）· 复习 2 次"，只取词和释义那一段。
        text = line.lstrip("- ").split("·")[0].strip()
        if text:
            seeds.append((text, "word"))
    for line in expression_lines(limit=_SEED_LIMIT):
        text = line.lstrip("- ").strip()
        if text:
            seeds.append((text, "phrase"))
    for line in notebook_lines(limit=_SEED_LIMIT):
        text = line.lstrip("- ").strip()
        if text:
            seeds.append((text, "phrase"))

    for label, kind in seeds:
        key = label.lower()
        if key in existing:
            continue
        items.append(_new_item(label, kind))
        existing.add(key)
        if len(items) >= _MAX_ITEMS:
            break
    return items


def _cooling(item: dict) -> bool:
    """上次答好的点进入冷却期，避免刚巩固完又抽到。"""
    if item.get("last_result") != "good":
        return False
    last = _parse_day(item.get("last"))
    if not last:
        return False
    age = (_today() - last).days
    threshold = (
        _MASTERED_COOLDOWN_DAYS
        if item.get("strength", 0) >= _MASTERED_STRENGTH
        else _COOLDOWN_DAYS
    )
    return age < threshold


def pick_targets(limit: int = 3) -> list[dict]:
    """挑出最该练的几个点；不会抽到刚刚练好的。"""
    with _LOCK:
        items = _load()
        if len(items) < limit:
            items = _seed(items)

        pool = [item for item in items if not _cooling(item)]
        if not pool:
            # 全都刚练好：退而求其次，练最不熟的那个，而不是不练。
            pool = list(items)
        pool.sort(key=lambda item: (item["strength"], item["last"] or ""))
        chosen = pool[:limit]
        _save(items)

    return [
        {"label": item["label"], "kind": item["kind"], "strength": item["strength"]}
        for item in chosen
    ]


def apply_results(
    targets: list[dict], assessments, new_issues
) -> None:
    """把这一轮的评估写回备课本：错得多往前排，连续答对降频/退场。"""
    with _LOCK:
        items = _load()

        for raw in assessments or []:
            if not isinstance(raw, dict):
                continue
            try:
                index = int(raw.get("index", 0)) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(targets):
                continue
            label = targets[index].get("label", "")
            item = _find(items, label)
            if item is None:
                item = _new_item(label, targets[index].get("kind", "issue"))
                items.append(item)

            result = str(raw.get("result") or "").lower()
            if result == "good":
                item["hits"] += 1
                item["streak"] += 1
                item["strength"] = min(_MAX_STRENGTH, item["strength"] + 1)
                if item["errors"] >= _HIGH_ERROR and item["streak"] < 2:
                    # 错得多的点，连续 2 次答对前仍保持较高频率
                    item["interval"] = 2
                else:
                    item["interval"] = min(
                        _MAX_INTERVAL, max(3, item["interval"] * 2)
                    )
                if item["streak"] >= _RETIRE_STREAK:
                    items.remove(item)
                    logger.info("已练好，移出备课本：%s", item["label"])
                    continue
            else:
                item["errors"] += 1
                item["streak"] = 0
                item["interval"] = 1
                if result == "weak":
                    item["strength"] = max(0, item["strength"] - 1)

            item["attempts"] += 1
            item["last"] = _now()
            item["last_result"] = result or "partial"
            item["due"] = (
                _today() + timedelta(days=item["interval"])
            ).isoformat()
            note = _one_line(raw.get("note"), 80)
            if note:
                item["note"] = note

        for issue in (new_issues or [])[:2]:
            label = _one_line(issue)
            if not label or _find(items, label):
                continue
            item = _new_item(label, "issue", note="练习中新暴露")
            item["errors"] = 1
            item["due"] = _today().isoformat()
            items.append(item)
            logger.info("新增练习重点：%s", label)

        _save(items)


def prep_points(limit: int = 6) -> list[dict]:
    """备课本：未练好的点里，错得多、到期、连对少的排前面。"""
    items = _load()
    active = [item for item in items if not item.get("retired")]
    if len(active) < limit:
        items = _seed(items)
        active = [item for item in items if not item.get("retired")]

    today = _today().isoformat()
    active.sort(
        key=lambda item: (
            item["due"] > today,
            -item["errors"],
            item["streak"],
            item["due"],
            item["last"],
        )
    )
    # 清理旧版本留下的 retired 记录：写回时只剩当前有效点
    _save(items)
    return active[:limit]


def prep_text(limit: int = 6) -> str:
    """给老师 prompt 的备课本摘要。"""
    points = prep_points(limit)
    if not points:
        return ""
    today = _today().isoformat()
    lines = []
    for item in points:
        when = "今天" if item["due"] <= today else item["due"]
        lines.append(
            f"- {item['label']}（错 {item['errors']} · 连对 {item['streak']} · {when}）"
        )
    return "\n".join(lines)


def weakest(limit: int = 6) -> list[dict]:
    """侧边栏展示用：最不熟的几条。"""
    items = _load()
    if len(items) < limit:
        items = _seed(items)
        _save(items)
    items.sort(key=lambda item: (item["strength"], item["last"] or ""))
    return items[:limit]


def summary() -> dict:
    items = _load()
    cooling = sum(1 for item in items if _cooling(item))
    return {
        "total": len(items),
        "weak": sum(1 for item in items if item["strength"] <= 1),
        "cooling": cooling,
    }


__all__ = [
    "apply_results",
    "pick_targets",
    "prep_points",
    "prep_text",
    "summary",
    "weakest",
]
