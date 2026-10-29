# utils/TutorPlan.py

"""本次课计划：只从备课本候选池里选点。

规则（按用户确认的版本）：

- 自动计划最多 3 个点；用户明确要练的点可以追加，最多 10 个；
- 按备课本 added_at 从新到旧选；
- 最近三个计划：上个计划最多 0 个、上上个最多 1 个、上上上个最多 2 个；
- 一个点只按最近一次出现算配额；
- 不做高相关判断；
- 计划里所有点打勾后才完成；0 点计划是空状态；
- 每天第一次打开老师页，如果计划完成且备课本有点，自动重新备课；
- 0 点/备课本为空不自动重试。
"""

import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from utils import PrepBook, TutorProgress
from utils.llm import call_llm_json
from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = Path(
    os.getenv("TUTOR_PLAN_PATH") or (_PROJECT_ROOT / "data" / "tutor_plan.json")
)
_LOCK = threading.RLock()

_MAX_AUTO_POINTS = 3
_MAX_POINTS = 10
_MAX_HISTORY = 10
_MAX_LABEL = 120


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().date().isoformat()


def _one_line(text, limit: int = _MAX_LABEL) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _label_key(label: str) -> str:
    value = _one_line(label)
    value = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", value).strip()
    value = re.sub(r"[。.!！?？,，;；:：]+$", "", value).strip()
    return value.casefold()


def _empty() -> dict:
    return {
        "version": 2,
        "lesson_id": "",
        "goal": "",
        "warmup": "",
        "wrapup": "",
        "points": [],
        "status": "empty",
        "created_at": "",
        "updated_at": "",
        "last_auto_plan_date": "",
        "history": [],
    }


def _normalise_point(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    label = _one_line(raw.get("label"))
    if not label:
        return None
    status = str(raw.get("status") or "pending").strip().lower()
    if status not in ("pending", "mastered"):
        status = "pending"
    source_key = _one_line(raw.get("source_key"), 160) or "plan:" + _label_key(label)
    return {
        "source_key": source_key,
        "label": label,
        "kind": _one_line(raw.get("kind"), 20) or "phrase",
        "source": _one_line(raw.get("source"), 20) or "prep",
        "task": _one_line(raw.get("task"), 300),
        "criterion": _one_line(raw.get("criterion"), 160),
        "status": status,
        "mastered_at": str(raw.get("mastered_at") or ""),
        "added_by": str(raw.get("added_by") or "auto"),
    }


def _normalise_history(raw) -> list[dict]:
    result = []
    if not isinstance(raw, list):
        return result
    for item in raw[-_MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "lesson_id": str(item.get("lesson_id") or ""),
                "created_at": str(item.get("created_at") or ""),
                "goal": _one_line(item.get("goal"), 160),
                "source_keys": [
                    str(key)
                    for key in (item.get("source_keys") or [])
                    if str(key).strip()
                ],
                "status": "done" if item.get("status") == "done" else "active",
            }
        )
    return result


def _normalise(raw) -> dict:
    plan = _empty()
    if not isinstance(raw, dict):
        return plan
    plan["lesson_id"] = str(raw.get("lesson_id") or "")
    plan["goal"] = _one_line(raw.get("goal"), 160)
    plan["warmup"] = _one_line(raw.get("warmup"), 200)
    plan["wrapup"] = _one_line(raw.get("wrapup"), 200)
    plan["created_at"] = str(raw.get("created_at") or "")
    plan["updated_at"] = str(raw.get("updated_at") or "")
    plan["last_auto_plan_date"] = str(raw.get("last_auto_plan_date") or "")
    plan["history"] = _normalise_history(raw.get("history"))

    points = []
    for item in (raw.get("points") or [])[:_MAX_POINTS]:
        point = _normalise_point(item)
        if point and not any(
            point["source_key"].casefold() == old["source_key"].casefold()
            for old in points
        ):
            points.append(point)
    plan["points"] = points
    if not points:
        plan["status"] = "empty"
    elif all(point["status"] == "mastered" for point in points):
        plan["status"] = "done"
    else:
        plan["status"] = "active"
    return plan


def _load_unlocked() -> dict:
    return _normalise(load_json(PLAN_PATH, {}))


def load_plan() -> dict:
    with _LOCK:
        return _load_unlocked()


def _save_unlocked(plan: dict) -> dict:
    plan["updated_at"] = _now()
    if not plan.get("points"):
        plan["status"] = "empty"
    elif all(point.get("status") == "mastered" for point in plan["points"]):
        plan["status"] = "done"
        # 完成当天不再自动重开；下一次“每天第一次打开”才更新。
        plan["last_auto_plan_date"] = _today()
    else:
        plan["status"] = "active"
    save_json(PLAN_PATH, plan)
    return plan


def is_empty(plan: dict) -> bool:
    return not (plan.get("points") or [])


def is_done(plan: dict) -> bool:
    points = plan.get("points") or []
    return bool(points) and all(point.get("status") == "mastered" for point in points)


def can_train(plan: dict) -> bool:
    return any(point.get("status") != "mastered" for point in plan.get("points") or [])


def pending_points(plan: dict) -> list[dict]:
    return [p for p in (plan.get("points") or []) if p.get("status") != "mastered"]


def _sync_history_entry(plan: dict) -> None:
    """把当前计划的点/状态同步进 history 的对应记录。"""
    if not plan.get("points"):
        return
    key = plan.get("lesson_id")
    history = plan.setdefault("history", [])
    entry = next((item for item in history if item.get("lesson_id") == key), None)
    record = {
        "lesson_id": key,
        "created_at": plan.get("created_at") or _now(),
        "goal": plan.get("goal") or "",
        "source_keys": [point["source_key"] for point in plan["points"]],
        "status": "done" if is_done(plan) else "active",
    }
    if entry:
        entry.update(record)
    else:
        history.append(record)
    plan["history"] = history[-_MAX_HISTORY:]


def _recent_plan_keys(history: list[dict]) -> list[set[str]]:
    """最近三个计划的 source_key 集合，最近的在前。"""
    result = []
    for record in reversed((history or [])[-3:]):
        result.append({str(key).casefold() for key in record.get("source_keys") or []})
    return result


def _select_points(history: list[dict]) -> list[dict]:
    """第一个点取备课本里最早加入的；第二个起按最新的取。"""
    items = PrepBook.candidates()
    recent = _recent_plan_keys(history)
    used = [0, 0, 0]  # 上上个、上上上个、更早（占位）
    selected = []
    selected_keys = set()

    def take(item: dict) -> bool:
        key = item["source_key"].casefold()
        last_index = 0
        for index, keys in enumerate(recent, start=1):
            if key in keys:
                last_index = index
                break
        if last_index == 1:
            return False
        if last_index == 2 and used[0] >= 1:
            return False
        if last_index == 3 and used[1] >= 2:
            return False
        if last_index == 2:
            used[0] += 1
        elif last_index == 3:
            used[1] += 1
        selected.append(item)
        selected_keys.add(key)
        return True

    # 第一个点：从加入备课本最早的开始找第一个符合配额的。
    for item in sorted(items, key=lambda item: item.get("added_at", "")):
        if take(item):
            break
        if len(selected) >= _MAX_AUTO_POINTS:
            break

    # 第二个点起：恢复从新到旧。
    if len(selected) < _MAX_AUTO_POINTS:
        for item in items:
            if item["source_key"].casefold() in selected_keys:
                continue
            if take(item) and len(selected) >= _MAX_AUTO_POINTS:
                break
    return selected


def _fallback_tasks(points: list[dict]) -> list[dict]:
    result = []
    for point in points:
        label = point["label"]
        result.append(
            {
                "source_key": point["source_key"],
                "task": f"Tell me about a real situation where you could use {label}.",
                "criterion": f"自然地用上 {label}，并补一个具体细节。",
            }
        )
    return result


def _write_plan_content(
    points: list[dict], memory: str, provider=None, model=None
) -> dict:
    lines = "\n".join(
        f"{index + 1}. {point['label']} — {point['source_key']}"
        for index, point in enumerate(points)
    )
    prompt = f"""You are an IELTS Speaking teacher writing ONE short lesson around points
that have ALREADY been selected. Do not add or remove points.

SELECTED POINTS
{lines}

STUDENT MEMORY
{memory.strip() or "(none)"}

TASK
Write a natural lesson frame for these exact points:
- goal: one short Chinese line;
- warmup: one casual English question;
- for each selected point: the same source_key, one English elicitation question/task,
  and one short Chinese success criterion;
- wrapup: one short English production task.

Output JSON only:
{{"goal": "...", "warmup": "...",
 "points": [{{"source_key": "...", "task": "...", "criterion": "..."}}],
 "wrapup": "..."}}
"""
    try:
        data = call_llm_json(
            prompt,
            temperature=0.5,
            num_predict=900,
            fallback={},
            timeout=60,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("写课计划内容失败")
        data = {}
    if not isinstance(data, dict):
        data = {}

    by_key = {}
    for raw in data.get("points") or []:
        if isinstance(raw, dict):
            key = str(raw.get("source_key") or "").casefold()
            if key:
                by_key[key] = raw
    fallback = {item["source_key"]: item for item in _fallback_tasks(points)}
    enriched = []
    for point in points:
        raw = by_key.get(point["source_key"].casefold()) or {}
        fallback_item = fallback.get(point["source_key"], {})
        enriched.append(
            {
                **point,
                "task": _one_line(raw.get("task"), 300)
                or fallback_item.get("task", ""),
                "criterion": _one_line(raw.get("criterion"), 160)
                or fallback_item.get("criterion", ""),
            }
        )
    return {
        "goal": _one_line(
            data.get("goal") or "把备课本里的点用进一次完整回答。", 160
        ),
        "warmup": _one_line(
            data.get("warmup") or "How has your day been so far?", 200
        ),
        "wrapup": _one_line(
            data.get("wrapup") or "用今天练的点，完整回答一次 Part 1 问题。",
            200,
        ),
        "points": enriched,
    }


def create_plan(
    material: str = "",
    memory: str = "",
    prep: str = "",
    previous: dict | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    manual: bool = False,
) -> dict:
    """生成新计划：只从备课本选点；没有可选项就保存 0 点空状态。"""
    current = _normalise(previous) if previous else load_plan()
    if current.get("points") and not is_done(current):
        # 未完成不能更新；手动也不行。
        return current
    if current.get("points") and is_done(current):
        if current.get("last_auto_plan_date") == _today() and not manual:
            return current

    try:
        PrepBook.sync_candidates(
            protected_keys={
                point["source_key"] for point in current.get("points") or []
            }
        )
    except Exception:
        logger.exception("同步备课本候选失败")

    selected = _select_points(current.get("history") or [])
    if not selected:
        # 备课本里只剩上个计划的点（配额 0）时，不要用空计划覆盖已完成计划。
        if current.get("points"):
            return current
        empty = _empty()
        empty["last_auto_plan_date"] = _today()
        empty["created_at"] = _now()
        empty["updated_at"] = _now()
        _save_unlocked(empty)
        return empty

    content = _write_plan_content(
        selected, memory=memory, provider=provider, model=model
    )
    lesson_id = uuid.uuid4().hex[:8]
    points = []
    for item, content_point in zip(selected, content["points"]):
        points.append(
            {
                "source_key": item["source_key"],
                "label": item["label"],
                "kind": item["kind"],
                "source": item.get("source", "prep"),
                "task": content_point.get("task", ""),
                "criterion": content_point.get("criterion", ""),
                "status": "pending",
                "mastered_at": "",
                "added_by": "auto",
            }
        )
    plan = {
        "version": 2,
        "lesson_id": lesson_id,
        "goal": content["goal"],
        "warmup": content["warmup"],
        "wrapup": content["wrapup"],
        "points": points,
        "status": "active",
        "created_at": _now(),
        "updated_at": _now(),
        "last_auto_plan_date": _today(),
        "history": list(current.get("history") or [])[-_MAX_HISTORY:],
    }
    _sync_history_entry(plan)
    return _save_unlocked(plan)


def ensure_plan(
    material: str = "",
    memory: str = "",
    prep: str = "",
    *,
    force: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """每天第一次打开时调用：未完成保持不变；完成且备课本有点才自动更新。"""
    current = load_plan()
    if current.get("points") and not is_done(current):
        return current
    if force:
        return create_plan(
            material,
            memory,
            prep,
            previous=current,
            provider=provider,
            model=model,
            manual=True,
        )
    if not current.get("points"):
        return current
    if current.get("last_auto_plan_date") == _today():
        return current
    try:
        PrepBook.sync_candidates()
    except Exception:
        logger.exception("同步备课本失败")
    if not PrepBook.candidates():
        return current
    return create_plan(
        material,
        memory,
        prep,
        previous=current,
        provider=provider,
        model=model,
        manual=False,
    )


def _retire_completed(plan: dict) -> None:
    """一个点第二次进入计划并完成 → 从备课本删除（seen 保留）。"""
    history = plan.get("history") or []
    for point in plan.get("points") or []:
        if point.get("status") != "mastered":
            continue
        key = point["source_key"]
        appearances = sum(
            1
            for record in history
            if key in {str(item) for item in record.get("source_keys") or []}
        )
        if appearances >= 2:
            try:
                PrepBook.remove_item(key)
            except Exception:
                logger.exception("退休备课本条目失败：%s", key)


def add_user_point(
    label: str,
    *,
    source_key: str = "",
    kind: str = "",
    task: str = "",
    criterion: str = "",
) -> tuple[dict, bool]:
    """用户明确要练的点：追加进当前计划，最多 10 个；重复则返回已有。"""
    label = _one_line(label)
    if not label:
        return load_plan(), False
    with _LOCK:
        plan = _load_unlocked()
        key = _one_line(source_key, 160) or "user:" + _label_key(label)
        points = plan.get("points") or []
        if any(
            point["source_key"].casefold() == key.casefold()
            or _label_key(point["label"]) == _label_key(label)
            for point in points
        ):
            return plan, False
        if len(points) >= _MAX_POINTS:
            return plan, False
        if not points:
            plan["lesson_id"] = uuid.uuid4().hex[:8]
            plan["created_at"] = _now()
            plan["goal"] = plan.get("goal") or "按你的要求临时加练"
        points.append(
            {
                "source_key": key,
                "label": label,
                "kind": kind or "phrase",
                "source": "user_request",
                "task": task,
                "criterion": criterion,
                "status": "pending",
                "mastered_at": "",
                "added_by": "user",
            }
        )
        plan["points"] = points
        plan["status"] = "active"
        _sync_history_entry(plan)
        return _save_unlocked(plan), True


def mark_point(source_key: str, mastered: bool = True) -> dict:
    key = str(source_key or "").casefold()
    with _LOCK:
        plan = _load_unlocked()
        for point in plan.get("points") or []:
            if point["source_key"].casefold() == key:
                point["status"] = "mastered" if mastered else "pending"
                point["mastered_at"] = _now() if mastered else ""
                if mastered:
                    TutorProgress.record(
                        plan.get("lesson_id") or "",
                        point["source_key"],
                        point.get("label") or "",
                        point["mastered_at"],
                    )
                break
        _sync_history_entry(plan)
        _retire_completed(plan)
        return _save_unlocked(plan)


def mark_mastered(labels) -> dict:
    if isinstance(labels, str):
        labels = [labels]
    keys = {_label_key(label) for label in (labels or []) if str(label).strip()}
    with _LOCK:
        plan = _load_unlocked()
        changed = False
        for point in plan.get("points") or []:
            if point.get("status") == "mastered":
                continue
            if (
                point["source_key"].casefold() in {str(label).casefold() for label in labels or []}
                or _label_key(point["label"]) in keys
            ):
                point["status"] = "mastered"
                point["mastered_at"] = _now()
                TutorProgress.record(
                    plan.get("lesson_id") or "",
                    point["source_key"],
                    point.get("label") or "",
                    point["mastered_at"],
                )
                changed = True
        if changed:
            _sync_history_entry(plan)
            _retire_completed(plan)
            return _save_unlocked(plan)
        return plan


def plan_text(plan: dict | None = None) -> str:
    plan = load_plan() if plan is None else plan
    points = plan.get("points") or []
    if not points:
        return ""
    lines = []
    if plan.get("goal"):
        lines.append("GOAL: " + plan["goal"])
    if plan.get("warmup"):
        lines.append("WARM-UP: " + plan["warmup"])
    for index, point in enumerate(points, 1):
        mark = "done" if point.get("status") == "mastered" else "pending"
        lines.append(f"{index}. [{mark}] {point['label']}")
        if point.get("task"):
            lines.append(f"   elicit: {point['task']}")
        if point.get("criterion"):
            lines.append(f"   success: {point['criterion']}")
    if plan.get("wrapup"):
        lines.append("WRAP-UP: " + plan["wrapup"])
    return "\n".join(lines)


__all__ = [
    "add_user_point",
    "can_train",
    "create_plan",
    "ensure_plan",
    "is_done",
    "is_empty",
    "load_plan",
    "mark_mastered",
    "mark_point",
    "pending_points",
    "plan_text",
]
