# utils/TrainingMemory.py

"""训练期临时记忆：训练/提到计划点时读取，训练结束或更新计划后清除。

用 Memory 引擎的一个隐藏 persona 存，不显示在侧边栏，也不写进「关于你」。
练习时学生经常反复说同一句话，这些内容只在这节课当上下文用，不进入长期
记忆；销毁前把这次练成的成果交给 TeacherMemory 记进「课堂成果」。
"""

from __future__ import annotations

import logging
import threading

from utils import ChatHistory, Memory

logger = logging.getLogger(__name__)

KEY = "tutor_training"
LABEL = "雅思口语训练"
META_KEY = "training_memory_lesson"


def memory_text() -> str:
    text = Memory.memory_text(KEY)
    # 换掉长期记忆的语气，避免主模型把训练期内容当成永久事实。
    return (
        text.replace(
            "PERMANENT FACTS — the user has repeated or stressed these. "
            "Never forget them, never contradict them, never ask about them again:",
            "TRAINING FACTS:",
        )
        .replace("SUMMARY OF THIS USER:", "TRAINING SUMMARY:")
        .replace(
            "OTHER KNOWN FACTS (less certain, mention only when relevant):",
            "OTHER TRAINING NOTES (less certain, mention only when relevant):",
        )
    )


def update(
    message: str,
    reply: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """同步更新；调用方需要后台时用 update_async。"""
    Memory.update_memory(
        KEY,
        message,
        reply,
        LABEL,
        provider=provider,
        model=model,
    )


def update_async(
    message: str,
    reply: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    threading.Thread(
        target=update,
        args=(message, reply),
        kwargs={"provider": provider, "model": model},
        daemon=True,
    ).start()


def clear() -> None:
    Memory.clear_memory(KEY)


def _remember_impression(lesson_id: str = "") -> None:
    """销毁前把这次训练的成果写进「英语学习档案」的课堂成果。

    以前这里会往「关于你」塞一条印象；训练内容不该进个人记忆，改成写进
    老师档案的课堂成果，计划换了也能看到上一节课练成了什么。
    """
    from utils import TeacherMemory

    memory = Memory.load_memory(KEY)
    text = str(memory.get("summary") or "").strip()
    if not text:
        facts = memory.get("facts") or []
        text = "；".join(
            str(fact.get("text") or "").strip()
            for fact in facts[:2]
            if str(fact.get("text") or "").strip()
        )
    if not text:
        return
    TeacherMemory.remember_outcome(text, lesson_id)


def ensure_lesson(lesson_id: str) -> bool:
    """计划换了就留一点成果并清空；同一份计划继续沿用。返回是否清空过。"""
    value = str(lesson_id or "")
    meta = ChatHistory.load_meta("tutor")
    current = str(meta.get(META_KEY) or "")
    changed = current != value
    if changed:
        _remember_impression(current)
        clear()
    meta[META_KEY] = value
    ChatHistory.save_meta("tutor", meta)
    return changed


__all__ = [
    "KEY",
    "clear",
    "ensure_lesson",
    "memory_text",
    "update",
    "update_async",
]
