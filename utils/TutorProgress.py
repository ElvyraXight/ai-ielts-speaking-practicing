# utils/TutorProgress.py

"""每天完成过的课程点，独立于“当前计划”。

这样即使今天重新备过课、换过计划，今天完成的总数也不会被覆盖。
记录粒度：一个 lesson_id + source_key 只记一次。
"""

import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path

from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = Path(
    os.getenv("TUTOR_PROGRESS_PATH")
    or (_PROJECT_ROOT / "data" / "tutor_progress.json")
)
_LOCK = threading.RLock()

_MAX_DAYS = 400


def _today() -> str:
    return date.today().isoformat()


def _clean_day(day: str) -> str:
    try:
        return datetime.strptime(str(day)[:10], "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return _today()


def _load_all() -> dict:
    data = load_json(PROGRESS_PATH, {})
    if not isinstance(data, dict):
        return {}
    days = data.get("days")
    if not isinstance(days, dict):
        return {}
    result = {}
    for day, payload in days.items():
        if not isinstance(payload, dict):
            continue
        points = []
        for point in payload.get("points") or []:
            if not isinstance(point, dict):
                continue
            lesson_id = str(point.get("lesson_id") or "").strip()
            source_key = str(point.get("source_key") or "").strip()
            if not source_key:
                continue
            points.append(
                {
                    "lesson_id": lesson_id,
                    "source_key": source_key,
                    "label": str(point.get("label") or "")[:120],
                    "at": str(point.get("at") or ""),
                }
            )
        result[_clean_day(day)] = {"points": points}
    return result


def _event_key(point: dict) -> str:
    return f"{point.get('lesson_id') or ''}::{point.get('source_key') or ''}"


def record(
    lesson_id: str,
    source_key: str,
    label: str = "",
    at: str = "",
    *,
    day: str = "",
) -> bool:
    """记录一个已完成的点；同一课同一点重复调用不会重复计数。"""
    lesson_id = str(lesson_id or "").strip()
    source_key = str(source_key or "").strip()
    if not source_key:
        return False
    stamp = str(at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    day_key = _clean_day(day or stamp[:10] or _today())
    point = {
        "lesson_id": lesson_id,
        "source_key": source_key,
        "label": str(label or "")[:120],
        "at": stamp,
    }
    with _LOCK:
        days = _load_all()
        bucket = days.setdefault(day_key, {"points": []})
        key = _event_key(point)
        if any(_event_key(old) == key for old in bucket["points"]):
            return False
        bucket["points"].append(point)
        # 只保留最近 400 天，避免文件无限变大。
        for old_day in sorted(days)[:-_MAX_DAYS]:
            days.pop(old_day, None)
        save_json(PROGRESS_PATH, {"version": 1, "days": days})
    return True


def backfill_plan(plan: dict) -> int:
    """把当前计划里已经打勾、但还没进进度表的点补进来。"""
    if not isinstance(plan, dict):
        return 0
    lesson_id = str(plan.get("lesson_id") or "")
    added = 0
    for point in plan.get("points") or []:
        if not isinstance(point, dict) or point.get("status") != "mastered":
            continue
        mastered_at = str(point.get("mastered_at") or "")
        if record(
            lesson_id,
            str(point.get("source_key") or ""),
            str(point.get("label") or ""),
            mastered_at,
        ):
            added += 1
    return added


def day_points(day: str = "") -> list[dict]:
    key = _clean_day(day or _today())
    with _LOCK:
        return list((_load_all().get(key) or {}).get("points") or [])


def today_count() -> int:
    return len(day_points())


def total_count() -> int:
    with _LOCK:
        return sum(len((bucket or {}).get("points") or []) for bucket in _load_all().values())


__all__ = ["backfill_plan", "day_points", "record", "today_count", "total_count"]
