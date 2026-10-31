# utils/HelpMemory.py

"""求助会话的临时记忆：考场上打开「老师帮帮我」时，这一场到底聊过什么。

为什么需要它：帮助页以前对长期记忆只读不写，每轮都从零开始理解学生的问题，
于是同一个毛病会被反复指出来（“Part 1 只给短语太短”说三遍），也不记得
刚才已经给过什么提示。

做法和训练期临时记忆（`TrainingMemory`）同构：

- 用记忆引擎的一个隐藏 persona 存，不出现在任何侧栏，也不写进「关于你」；
- 每轮把（学生私问, 老师提示）交给后台模型，模型只报告增量，本地合并；
- 读完把段落标题换成 "THIS HELP SESSION"，避免模型当成永久事实；
- 一场求助结束时「毕业」：把摘要写进英语学习档案的「考试过程」，
  然后清空——和训练记忆写进「课堂成果」再销毁是一回事。

两个来源（考官对话 / 讲个故事）各有各的键，互不污染。
"""

from __future__ import annotations

import logging
import threading

from utils import Memory

logger = logging.getLogger(__name__)

_KEYS = {"exam": "help_exam", "part2": "help_part2"}
_LABELS = {"exam": "模拟考试求助", "part2": "Part 2 求助"}


def _source(value: str) -> str:
    """把来源归一到 exam / part2；未知来源按 exam 处理。"""
    return "part2" if str(value or "").strip().lower() == "part2" else "exam"


def key(source: str = "exam") -> str:
    return _KEYS[_source(source)]


def label(source: str = "exam") -> str:
    return _LABELS[_source(source)]


def memory_text(source: str = "exam") -> str:
    """给模型看的这一场求助的记录；语气上明确是临时上下文。"""
    text = Memory.memory_text(key(source))
    if not text:
        return ""
    return (
        text.replace(
            "PERMANENT FACTS — the user has repeated or stressed these. "
            "Never forget them, never contradict them, never ask about them again:",
            "THIS HELP SESSION — ALREADY SAID OR ALREADY FIXED:",
        )
        .replace("SUMMARY OF THIS USER:", "HELP SESSION SUMMARY:")
        .replace(
            "OTHER KNOWN FACTS (less certain, mention only when relevant):",
            "OTHER NOTES FROM THIS HELP SESSION (mention only when relevant):",
        )
    )


def update(
    source: str,
    student_message: str,
    hint: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """同步更新；页面里用 update_async。"""
    Memory.update_memory(
        key(source),
        student_message,
        hint,
        label(source),
        provider=provider,
        model=model,
    )


def update_async(
    source: str,
    student_message: str,
    hint: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    threading.Thread(
        target=update,
        args=(source, student_message, hint),
        kwargs={"provider": provider, "model": model},
        daemon=True,
    ).start()


def clear(source: str = "exam") -> None:
    Memory.clear_memory(key(source))


def finish(source: str = "exam") -> bool:
    """一场求助结束：把摘要写进学习档案的「考试过程」，再清掉临时记忆。"""
    src = _source(source)
    memory = Memory.load_memory(key(src))
    summary = str(memory.get("summary") or "").strip()
    if not summary:
        facts = [
            str(fact.get("text") or "").strip()
            for fact in (memory.get("facts") or [])
            if str(fact.get("text") or "").strip()
        ]
        summary = "；".join(facts[:3])
    wrote = False
    if summary:
        from utils import TeacherMemory

        try:
            TeacherMemory.remember_exam_session(
                source_label=_LABELS[src],
                summary=summary,
            )
            wrote = True
        except Exception:
            logger.exception("写入考试过程记录失败")
    clear(src)
    return wrote


__all__ = [
    "clear",
    "finish",
    "key",
    "label",
    "memory_text",
    "update",
    "update_async",
]
