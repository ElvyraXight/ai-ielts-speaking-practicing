# utils/SRS.py

"""共用的间隔重复排期。

背单词和笔记本复习都用这一套，避免两处逻辑漂移：
- 忘了：当天重来，reps 归零，lapses +1
- 模糊：间隔 ×1.2，至少 1 天
- 记得：0→1 天，1→3 天，之后 ×ease
- 太简单：间隔 ×ease×1.3，至少 2 天，ease 上调
间隔上限 180 天，ease 限制在 1.3–3.0。
"""

from datetime import date, timedelta


def default_record(today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "due": today.isoformat(),
        "interval": 0,
        "reps": 0,
        "ease": 2.5,
        "lapses": 0,
        "last": "",
    }


def schedule(record: dict | None, grade: str, today: date | None = None) -> dict:
    """返回更新后的复习记录；record 里的其它字段会保留。"""
    today = today or date.today()
    result = dict(record or default_record(today))
    reps = int(result.get("reps") or 0)
    interval = int(result.get("interval") or 0)
    ease = float(result.get("ease") or 2.5)
    lapses = int(result.get("lapses") or 0)

    if grade == "again":
        reps = 0
        interval = 0
        ease = max(1.3, ease - 0.2)
        lapses += 1
        due = today
    elif grade == "hard":
        reps += 1
        interval = max(1, round((interval or 1) * 1.2))
        ease = max(1.3, ease - 0.05)
        due = today + timedelta(days=interval)
    elif grade == "easy":
        reps += 1
        interval = max(2, round((interval or 1) * ease * 1.3))
        ease = min(3.0, ease + 0.15)
        due = today + timedelta(days=interval)
    else:  # good
        if reps <= 0:
            interval = 1
        elif reps == 1:
            interval = 3
        else:
            interval = max(1, round(interval * ease))
        reps += 1
        due = today + timedelta(days=interval)

    result["reps"] = reps
    result["interval"] = min(180, max(0, interval))
    result["ease"] = round(ease, 2)
    result["lapses"] = lapses
    result["due"] = due.isoformat()
    result["last"] = today.isoformat()
    return result


__all__ = ["default_record", "schedule"]
