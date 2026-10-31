# utils/NotebookSync.py

"""笔记本删 / 改之后，把备课本和当前课计划一起对齐。

- 备课本：删掉的自动条目移除，改过的标签更新；同一个词如果还在弱词里就保留。
- 课计划：计划里同一个点跟着改名；词条被删且备课本里也没有了，就把计划点移除。
- 正在训练的点：改名时同步新标签；被移除时结束这次训练，避免继续练旧词。
- 表达库不再进备课本，所以这里不处理表达库。
"""

from __future__ import annotations

import logging

from utils import ChatHistory, PrepBook, TutorPlan

logger = logging.getLogger(__name__)

_TRAINING_KEYS = (
    "tutor_practice",
    "tutor_practice_question",
    "tutor_practice_model",
    "tutor_practice_stage",
    "tutor_practice_focus",
    "tutor_practice_checklist",
    "tutor_practice_turns",
    "tutor_practice_lesson",
)


def _publish_plan(plan: dict) -> None:
    try:
        import streamlit as st

        if "tutor_plan" in st.session_state:
            st.session_state["tutor_plan"] = plan
    except Exception:
        pass


def _sync_training(old_key: str, new_key: str, label: str) -> None:
    try:
        import streamlit as st
    except Exception:
        return
    stage = st.session_state.get("tutor_practice_stage")
    practice = st.session_state.get("tutor_practice") or []
    point = practice[0] if practice and isinstance(practice[0], dict) else None
    if not stage or not point:
        return
    if str(point.get("source_key") or "").casefold() != old_key.casefold():
        return

    meta = ChatHistory.load_meta("tutor")
    if new_key:
        point["source_key"] = new_key
        point["label"] = label
        st.session_state["tutor_practice"] = [point]
        training = meta.get("training")
        if isinstance(training, dict):
            training["point"] = [point]
            meta["training"] = training
            ChatHistory.save_meta("tutor", meta)
        return

    for key in _TRAINING_KEYS:
        st.session_state.pop(key, None)
    meta.pop("training", None)
    ChatHistory.save_meta("tutor", meta)


def _sync(old_item: dict | None, new_item: dict | None) -> None:
    PrepBook.sync_candidates()
    old_key = str((old_item or {}).get("source_key") or "")
    if not old_key:
        return
    new_key = str((new_item or {}).get("source_key") or "")
    old_exists = PrepBook.get(old_key) is not None

    if new_key and new_key.casefold() == old_key.casefold():
        item = PrepBook.get(new_key) or new_item or {}
        label = str(item.get("label") or (old_item or {}).get("label") or "")
        plan = TutorPlan.rename_point(
            old_key, new_key, label, clear_task=False
        )
        _publish_plan(plan)
        _sync_training(old_key, new_key, label)
        return

    if new_key:
        if old_exists:
            # 旧词还在弱词或其他来源里：旧计划点仍然有效，不硬改成新词。
            return
        item = PrepBook.get(new_key) or new_item or {}
        label = str(item.get("label") or "")
        plan = TutorPlan.rename_point(
            old_key, new_key, label, clear_task=True
        )
        _publish_plan(plan)
        _sync_training(old_key, new_key, label)
        return

    if not old_exists:
        plan = TutorPlan.remove_point(old_key)
        _publish_plan(plan)
        _sync_training(old_key, "", "")


def _run(old_item: dict | None, new_item: dict | None) -> None:
    try:
        _sync(old_item, new_item)
    except Exception:
        logger.exception("笔记本变更后同步备课本失败")


def after_notebook_delete(term: str, meaning: str) -> None:
    _run(PrepBook.item_from_notebook(term, meaning), None)


def after_notebook_edit(
    old_term: str,
    old_meaning: str,
    new_term: str,
    new_meaning: str,
) -> None:
    _run(
        PrepBook.item_from_notebook(old_term, old_meaning),
        PrepBook.item_from_notebook(new_term, new_meaning),
    )


__all__ = ["after_notebook_delete", "after_notebook_edit"]
