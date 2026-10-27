# utils/WordAtlas.py

"""内置词库与背单词逻辑。

词库来自 Word Atlas（https://github.com/designfuchen/word-atlas），
CC BY 4.0，见 assets/word-atlas-LICENSE.txt。7,298 个雅思词条，
含音标、中英释义、两条例句、搭配、词族、近反义和用法提示。

这里只放数据与调度，界面在 chats/Words.py：
- 今日队列 = 到期复习 + 新词（按 datasets 的学习顺序）
- 三种主动回忆：看词选义 / 看义选词 / 例句填空拼写
- 评分后按 SM-2 的简化规则排下一次复习
"""

import json
import logging
import os
import random
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.storage import save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORDS_PATH = Path(
    os.getenv("WORD_ATLAS_PATH") or (_PROJECT_ROOT / "assets" / "word-atlas.json")
)
PROGRESS_PATH = Path(
    os.getenv("WORD_PROGRESS_PATH") or (_PROJECT_ROOT / "data" / "word_progress.json")
)

_LOCK = threading.RLock()
_WORDS = None
_BY_ID = {}

DEFAULT_NEW_PER_DAY = 10
MAX_QUEUE = 60
_CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
_TOPICS = {
    "education": "教育",
    "work": "工作",
    "technology": "科技",
    "science": "科学",
    "environment": "环境",
    "health": "健康",
    "society": "社会",
    "government": "政府",
    "economy": "经济",
    "media": "媒体",
    "arts": "艺术",
    "travel": "旅行",
    "city": "城市",
    "nature": "自然",
    "daily": "日常",
    "emotion": "情绪",
    "thinking": "思维",
    "sport": "运动",
    "history": "历史",
}


# ----------------------------- 词库 -----------------------------
def load_words() -> list[dict]:
    """加载整份词库（只读，进程内缓存）。"""
    global _WORDS
    if _WORDS is not None:
        return _WORDS
    with _LOCK:
        if _WORDS is not None:
            return _WORDS
        try:
            data = json.loads(WORDS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("词库读取失败：%s", WORDS_PATH)
            data = []
        words = [word for word in data if isinstance(word, dict) and word.get("w")]
        _BY_ID.clear()
        for word in words:
            _BY_ID[str(word.get("id") or word["w"]).lower()] = word
        _WORDS = words
        logger.info("词库加载完毕：%d 个词条", len(words))
    return _WORDS


def word_by_id(word_id: str) -> dict | None:
    load_words()
    return _BY_ID.get(str(word_id).lower())


def cefr_options() -> list[str]:
    return list(_CEFR_ORDER)


def topic_options() -> dict[str, str]:
    return dict(_TOPICS)


def topic_label(topic: str) -> str:
    return _TOPICS.get(str(topic), str(topic))


# ----------------------------- 进度 -----------------------------
def _today() -> date:
    return date.today()


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_progress() -> dict:
    return {
        "version": 1,
        "words": {},
        "daily": {},
        "settings": {"new_per_day": DEFAULT_NEW_PER_DAY},
    }


def load_progress() -> dict:
    with _LOCK:
        if not PROGRESS_PATH.exists():
            return _default_progress()
        try:
            data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("进度文件损坏，按空进度处理：%s", PROGRESS_PATH)
            return _default_progress()
    if not isinstance(data, dict):
        return _default_progress()
    data.setdefault("words", {})
    data.setdefault("daily", {})
    settings = data.setdefault("settings", {})
    if not isinstance(settings, dict):
        data["settings"] = settings = {}
    if not isinstance(settings.get("new_per_day"), int):
        settings["new_per_day"] = DEFAULT_NEW_PER_DAY
    return data


def save_progress(progress: dict) -> None:
    with _LOCK:
        save_json(PROGRESS_PATH, progress)


def today_counts(progress: dict | None = None) -> dict:
    progress = load_progress() if progress is None else progress
    today = _today().isoformat()
    record = progress.get("daily", {}).get(today) or {}
    return {
        "new": int(record.get("new") or 0),
        "review": int(record.get("review") or 0),
    }


def stats(progress: dict | None = None) -> dict:
    progress = load_progress() if progress is None else progress
    today = _today().isoformat()
    records = progress.get("words", {})
    due = sum(
        1
        for record in records.values()
        if str(record.get("due") or "") <= today
    )
    learning = sum(1 for record in records.values() if record.get("reps", 0) < 3)
    mastered = sum(1 for record in records.values() if record.get("reps", 0) >= 3)
    counts = today_counts(progress)
    return {
        "learned": len(records),
        "due": due,
        "learning": learning,
        "mastered": mastered,
        "new_today": counts["new"],
        "review_today": counts["review"],
    }


def _filtered_words(words: list[dict], cefr: list[str], topics: list[str]) -> list[dict]:
    selected_cefr = set(cefr or _CEFR_ORDER)
    selected_topics = set(topics or _TOPICS)
    return [
        word
        for word in words
        if word.get("cefr") in selected_cefr and word.get("topic") in selected_topics
    ]


def build_queue(
    *,
    cefr: list[str] | None = None,
    topics: list[str] | None = None,
    new_limit: int | None = None,
    max_size: int = MAX_QUEUE,
) -> list[str]:
    """到期复习优先，再补今天还剩的新词额度。"""
    words = load_words()
    progress = load_progress()
    today = _today().isoformat()
    limit = new_limit if new_limit is not None else progress["settings"]["new_per_day"]

    due: list[str] = []
    for word_id, record in progress["words"].items():
        if str(record.get("due") or "") <= today and word_id in _BY_ID:
            due.append(word_id)
    due.sort(key=lambda wid: (str(progress["words"][wid].get("due") or ""), wid))

    quota = max(0, int(limit) - today_counts(progress)["new"])
    pool = _filtered_words(words, cefr or [], topics or [])
    new: list[str] = []
    if quota:
        for word in pool:
            word_id = str(word["id"]).lower()
            if word_id not in progress["words"]:
                new.append(word_id)
                if len(new) >= quota:
                    break

    queue = due + new
    return queue[:max_size]


def next_due(progress: dict | None = None) -> str:
    progress = load_progress() if progress is None else progress
    today = _today().isoformat()
    future = [
        str(record.get("due"))
        for record in progress.get("words", {}).values()
        if str(record.get("due") or "") > today
    ]
    return min(future) if future else ""


# ----------------------------- 题目 -----------------------------
def _pick_distractors(word: dict, pool: list[dict], key: str, count: int = 3) -> list[str]:
    correct = _option_value(word, key)
    candidates: list[str] = []
    same_level = [item for item in pool if item.get("cefr") == word.get("cefr")]
    for item in same_level + pool:
        value = _option_value(item, key)
        if item is word or not value or value == correct or value in candidates:
            continue
        candidates.append(value)
        if len(candidates) >= count:
            break
    return candidates


def _option_value(word: dict, key: str) -> str:
    if key == "w":
        return str(word.get("w") or "")
    senses = word.get("senses") or []
    if not senses:
        return ""
    return str(senses[0].get("zh") or "")


def _cloze_sentence(word: dict) -> str:
    target = str(word.get("w") or "")
    for example in word.get("ex") or []:
        sentence = str(example.get("en") or "")
        pattern = re.compile(rf"\b{re.escape(target)}\b", re.IGNORECASE)
        if pattern.search(sentence):
            return pattern.sub("____", sentence, count=1)
    return ""


def mode_for(reps: int) -> str:
    if reps <= 0:
        return "meaning"
    if reps == 1:
        return "recall"
    return "spell"


def make_question(word: dict, pool: list[dict], reps: int = 0, rng=None) -> dict:
    """生成一道题；选项在生成时就固定下来，重跑页面不会变。"""
    rng = rng or random
    mode = mode_for(reps)
    question = {
        "word_id": str(word["id"]).lower(),
        "mode": mode,
        "answer": "",
        "options": [],
        "prompt": "",
        "cloze": "",
    }

    if mode == "meaning":
        question["prompt"] = word["w"]
        question["answer"] = _option_value(word, "zh")
        distractors = _pick_distractors(word, pool, "zh")
        options = [question["answer"], *distractors]
        rng.shuffle(options)
        question["options"] = options
    elif mode == "recall":
        question["prompt"] = _option_value(word, "zh")
        question["answer"] = word["w"]
        distractors = _pick_distractors(word, pool, "w")
        options = [word["w"], *distractors]
        rng.shuffle(options)
        question["options"] = options
    else:
        question["prompt"] = _option_value(word, "zh")
        question["answer"] = word["w"]
        question["cloze"] = _cloze_sentence(word)

    return question


def _norm_answer(text: str) -> str:
    text = str(text or "").strip().lower()
    return re.sub(r"[\s\-'’]", "", text)


def check_answer(question: dict, answer: str) -> bool:
    if question.get("mode") == "spell":
        return _norm_answer(answer) == _norm_answer(question.get("answer", ""))
    return str(answer or "").strip() == str(question.get("answer", "")).strip()


# ----------------------------- 评分与排期 -----------------------------
def apply_review(word_id: str, grade: str) -> dict:
    """grade: again / hard / good / easy。返回更新后的记录。"""
    progress = load_progress()
    today = _today()
    record = progress["words"].get(word_id)
    is_new = record is None
    if record is None:
        record = {
            "reps": 0,
            "interval": 0,
            "ease": 2.5,
            "lapses": 0,
            "due": today.isoformat(),
            "last": "",
            "added": _now_stamp(),
        }

    reps = int(record.get("reps") or 0)
    interval = int(record.get("interval") or 0)
    ease = float(record.get("ease") or 2.5)

    if grade == "again":
        reps = 0
        interval = 0
        ease = max(1.3, ease - 0.2)
        record["lapses"] = int(record.get("lapses") or 0) + 1
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

    record["reps"] = reps
    record["interval"] = min(180, max(0, interval))
    record["ease"] = round(ease, 2)
    record["due"] = due.isoformat()
    record["last"] = today.isoformat()
    progress["words"][word_id] = record

    day = today.isoformat()
    daily = progress.setdefault("daily", {}).setdefault(day, {"new": 0, "review": 0})
    if is_new:
        daily["new"] = int(daily.get("new") or 0) + 1
    else:
        daily["review"] = int(daily.get("review") or 0) + 1

    save_progress(progress)
    return record


def set_new_per_day(value: int) -> None:
    progress = load_progress()
    progress["settings"]["new_per_day"] = max(1, min(50, int(value)))
    save_progress(progress)


__all__ = [
    "apply_review",
    "build_queue",
    "cefr_options",
    "check_answer",
    "load_progress",
    "load_words",
    "make_question",
    "next_due",
    "set_new_per_day",
    "stats",
    "today_counts",
    "topic_options",
    "topic_label",
    "word_by_id",
]
