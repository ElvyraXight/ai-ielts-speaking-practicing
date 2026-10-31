# utils/ExamState.py

"""雅思考官练习的状态机。

只负责“考到第几题、这一轮什么时候结束、下一轮练 Part 1 还是 Part 3”；
题目内容由 utils.Chat.generate_question_set 生成。
"""

from __future__ import annotations

from utils import ChatHistory

PART1 = "part1"
PART3 = "part3"
PART_LABELS = {PART1: "Part 1", PART3: "Part 3"}
PART1_SIZE = 8
PART3_SIZE = 6
RECENT_LIMIT = 12
META_KEY = "exam_state"


def default_state() -> dict:
    return {
        "selected_part": PART1,
        "active_part": PART1,
        "pending_part": "",
        "prelude_step": 0,
        "index": 0,
        "questions": [],
        "topics": [],
        "part3_topic": "随机话题",
        "use_part2_card": True,
        "recent": [],
    }


def _normalise(raw) -> dict:
    state = default_state()
    if not isinstance(raw, dict):
        return state
    if raw.get("selected_part") in (PART1, PART3):
        state["selected_part"] = raw["selected_part"]
    if raw.get("active_part") in (PART1, PART3):
        state["active_part"] = raw["active_part"]
    if raw.get("pending_part") in (PART1, PART3):
        state["pending_part"] = raw["pending_part"]
    if "prelude_step" in raw:
        try:
            state["prelude_step"] = max(0, min(2, int(raw.get("prelude_step") or 0)))
        except (TypeError, ValueError):
            state["prelude_step"] = 0
    elif raw.get("questions") or int(raw.get("index") or 0) > 0:
        # 旧状态没有开场步骤：已经进入题目，就视为开场已完成。
        state["prelude_step"] = 2
    try:
        state["index"] = max(0, int(raw.get("index") or 0))
    except (TypeError, ValueError):
        state["index"] = 0
    questions = []
    for item in raw.get("questions") or []:
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            questions.append(
                {
                    "topic": str(item.get("topic") or "").strip(),
                    "question": str(item.get("question") or "").strip(),
                }
            )
    state["questions"] = questions
    state["topics"] = [str(t).strip() for t in (raw.get("topics") or []) if str(t).strip()]
    state["part3_topic"] = str(raw.get("part3_topic") or "随机话题").strip()
    state["use_part2_card"] = bool(raw.get("use_part2_card", True))
    state["recent"] = [
        str(q).strip() for q in (raw.get("recent") or []) if str(q).strip()
    ][-RECENT_LIMIT:]
    return state


def load() -> dict:
    return _normalise(ChatHistory.load_meta("exam").get(META_KEY))


def save(state: dict) -> None:
    meta = ChatHistory.load_meta("exam")
    meta[META_KEY] = _normalise(state)
    ChatHistory.save_meta("exam", meta)


def reset() -> dict:
    state = default_state()
    save(state)
    return state


def rewind_to(messages: list[dict]) -> dict:
    """编辑旧消息后，把考试状态回退到「这些消息之后」。

    新消息生成回复时会把当时的 ExamState 快照写进 `exam_state`；优先用快照。
    老记录没有快照，就按剩余用户消息数还原来开场步骤，再按已出现的题目还原题号。
    """
    prefix = [item for item in messages or [] if isinstance(item, dict)]
    snapshot = next(
        (
            item.get("exam_state")
            for item in reversed(prefix)
            if isinstance(item.get("exam_state"), dict)
        ),
        None,
    )
    if snapshot:
        state = _normalise(snapshot)
        save(state)
        return state

    state = load()
    user_count = sum(1 for item in prefix if item.get("role") == "user")
    state["prelude_step"] = min(2, user_count)
    if state["prelude_step"] < 2:
        state["index"] = 0
    else:
        questions = state.get("questions") or []
        matched = []
        for item in prefix:
            if item.get("role") != "assistant":
                continue
            content = str(item.get("content") or "")
            for position, question in enumerate(questions):
                text = str(question.get("question") or "")
                if text and text in content:
                    matched.append(position)
        if matched:
            state["index"] = max(matched) + 1
        else:
            state["index"] = max(0, min(user_count - 2, len(questions)))
    save(state)
    return state


def round_size(part: str) -> int:
    return PART1_SIZE if part == PART1 else PART3_SIZE


def set_selected_part(state: dict, part: str) -> None:
    part = part if part in (PART1, PART3) else PART1
    state["selected_part"] = part
    if not state.get("questions"):
        state["active_part"] = part
        state["pending_part"] = ""
    elif part == state.get("active_part"):
        state["pending_part"] = ""
    else:
        state["pending_part"] = part


def _start_cycle(state: dict, generator) -> bool:
    part = state.get("pending_part") or state.get("active_part") or PART1
    if part not in (PART1, PART3):
        part = PART1
    payload = generator(
        part,
        topic=state.get("part3_topic") or "随机话题",
        use_card=bool(state.get("use_part2_card")),
        recent=list(state.get("recent") or []),
    )
    questions = []
    for item in (payload or {}).get("questions") or []:
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            questions.append(
                {
                    "topic": str(item.get("topic") or "").strip(),
                    "question": str(item.get("question") or "").strip(),
                }
            )
    if not questions:
        return False
    state["active_part"] = part
    state["pending_part"] = ""
    state["questions"] = questions[: round_size(part)]
    state["topics"] = [
        str(t).strip() for t in (payload or {}).get("topics") or [] if str(t).strip()
    ]
    state["index"] = 0
    return True


def take_next_question(state: dict, generator) -> dict | None:
    """取下一题并推进状态；一轮结束会自动开新一轮或切到待切换的 Part。"""
    questions = state.get("questions") or []
    if not questions or state.get("index", 0) >= len(questions):
        if not _start_cycle(state, generator):
            return None
        questions = state.get("questions") or []
    index = int(state.get("index") or 0)
    if index >= len(questions):
        return None
    item = dict(questions[index])
    state["index"] = index + 1
    recent = list(state.get("recent") or [])
    recent.append(item["question"])
    state["recent"] = recent[-RECENT_LIMIT:]
    return item


def prelude_transition(part: str) -> str:
    if part == PART3:
        return (
            "Thank you. Now, in this part, I'd like to discuss some more "
            "abstract questions with you."
        )
    return (
        "Thank you. Now, in this first part, I'd like to ask you "
        "some questions about yourself."
    )


def status_text(state: dict) -> str:
    if int(state.get("prelude_step") or 0) < 2:
        target = PART_LABELS.get(state.get("active_part"), "Part 1")
        return f"当前：开场确认（全名 → 称呼 → {target}）"
    part = PART_LABELS.get(state.get("active_part"), "Part 1")
    total = round_size(state.get("active_part") or PART1)
    index = min(int(state.get("index") or 0), total)
    text = f"当前：{part} · 第 {index}/{total} 题"
    pending = state.get("pending_part")
    if pending and pending != state.get("active_part"):
        text += f"；本轮结束后切到 {PART_LABELS[pending]}"
    return text


__all__ = [
    "PART1",
    "PART3",
    "PART1_SIZE",
    "PART3_SIZE",
    "PART_LABELS",
    "default_state",
    "load",
    "prelude_transition",
    "reset",
    "rewind_to",
    "round_size",
    "save",
    "set_selected_part",
    "status_text",
    "take_next_question",
]
