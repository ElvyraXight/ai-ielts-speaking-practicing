# chats/Tutor.py

import asyncio
import logging
import re
import threading
import uuid

import streamlit as st

from utils import ChatHistory, Memory, PrepBook, TeacherMemory, TutorErrors, TutorLead, TutorPlan
from utils import PlanJudge
from utils.config import current_selection, describe_llm
from utils.Notebook import render_quick_add
from utils.tts import existing_audio, new_audio_path, synthesize
from utils.Tutor import (
    ask_practice_question,
    ask_tutor_turn,
    coach_practice_answer,
    explain_vocabulary,
    is_bare_lookup,
    should_pause_coaching,
)

logger = logging.getLogger(__name__)

st.set_page_config(page_title="雅思口语老师", page_icon="👩‍🏫", layout="wide")

st.title("👩‍🏫 雅思口语老师")
st.caption(f"🤖 当前模型：{describe_llm()}")
st.caption("文字对话，老师听不到声音")

if "tutor_practice_stage" not in st.session_state:
    saved_training = ChatHistory.load_meta("tutor").get("training") or {}
    if saved_training.get("stage") in ("answer", "coaching"):
        st.session_state["tutor_practice"] = saved_training.get("point") or []
        st.session_state["tutor_practice_question"] = saved_training.get("question", "")
        st.session_state["tutor_practice_model"] = saved_training.get("model", "")
        st.session_state["tutor_practice_stage"] = saved_training["stage"]
        st.session_state["tutor_practice_focus"] = saved_training.get("focus", "")
        st.session_state["tutor_practice_checklist"] = saved_training.get("checklist") or []
        st.session_state["tutor_practice_turns"] = saved_training.get("turns", 0)
        st.session_state["tutor_practice_lesson"] = saved_training.get("lesson", "")

if st.session_state.get("tutor_practice_stage"):
    st.caption("训练中")


def _prepare_plan(force: bool = False) -> dict:
    provider, model = current_selection()
    with st.spinner("老师正在看备课本，准备这次课..."):
        return TutorPlan.ensure_plan(
            memory=TeacherMemory.memory_text(),
            force=force,
            provider=provider,
            model=model,
        )


if "tutor_plan" not in st.session_state:
    try:
        st.session_state["tutor_plan"] = _prepare_plan()
    except Exception:
        logger.exception("准备本次课计划失败")
        st.session_state["tutor_plan"] = TutorPlan.load_plan()

plan = st.session_state["tutor_plan"]
plan_keys = {
    point.get("source_key") for point in plan.get("points") or [] if point.get("source_key")
}
if "tutor_last_points" not in st.session_state:
    tracking_meta = ChatHistory.load_meta("tutor")
    if tracking_meta.get("plan_lesson") == str(plan.get("lesson_id") or ""):
        st.session_state["tutor_last_points"] = tracking_meta.get("plan_last_points") or []
    else:
        st.session_state["tutor_last_points"] = []
elif ChatHistory.load_meta("tutor").get("plan_lesson") not in (
    "",
    str(plan.get("lesson_id") or ""),
):
    st.session_state["tutor_last_points"] = []

try:
    PrepBook.sync_candidates(protected_keys=plan_keys)
except Exception:
    logger.exception("同步备课本失败")


def _lead_speak(
    kind: str,
    message: str,
    draft: str,
    *,
    practice: dict | None = None,
    no_drill: bool = False,
    plan_done: bool = False,
    update_summary: bool = False,
) -> dict:
    """所有学生可见的话都先经过主模型；失败时退回后台 brief。"""
    provider, model = current_selection()
    try:
        return TutorLead.compose(
            kind=kind,
            message=message,
            transcript=TutorLead.transcript_text(st.session_state.tutor_messages),
            draft=draft,
            plan=TutorPlan.plan_text(st.session_state.get("tutor_plan") or plan),
            student_memory=TeacherMemory.memory_text(),
            personal_memory=Memory.memory_text("tutor"),
            practice=practice,
            no_drill=no_drill,
            plan_done=plan_done,
            update_summary=update_summary,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("主模型表达失败")
        return {"reply": draft, "keep_practice": True}


def _remember_personal(user_message: str, reply: str) -> None:
    provider, model = current_selection()

    def run() -> None:
        try:
            Memory.update_memory(
                "tutor",
                user_message,
                reply,
                "雅思口语老师",
                provider=provider,
                model=model,
            )
        except Exception:
            logger.exception("更新「关于你」记忆失败")

    threading.Thread(target=run, daemon=True).start()


GREETING_VERSION = 5
GREETING = {
    "role": "assistant",
    "content": (
        "来啦，我在。今天想聊什么就说，不想聊就随便说两句英文，"
        "我听听你最近的状态。"
    ),
}


def _save_tutor_chat() -> None:
    ChatHistory.save("tutor", st.session_state.get("tutor_messages") or [])


def _save_training_meta() -> None:
    meta = ChatHistory.load_meta("tutor")
    stage = st.session_state.get("tutor_practice_stage")
    if stage in ("answer", "coaching"):
        meta["training"] = {
            "point": st.session_state.get("tutor_practice") or [],
            "question": st.session_state.get("tutor_practice_question", ""),
            "model": st.session_state.get("tutor_practice_model", ""),
            "stage": stage,
            "focus": st.session_state.get("tutor_practice_focus", ""),
            "checklist": st.session_state.get("tutor_practice_checklist") or [],
            "turns": st.session_state.get("tutor_practice_turns", 0),
            "lesson": st.session_state.get("tutor_practice_lesson", ""),
        }
    else:
        meta.pop("training", None)
    ChatHistory.save_meta("tutor", meta)


if "tutor_messages" not in st.session_state:
    restored = ChatHistory.load("tutor")
    if restored:
        st.session_state.tutor_messages = restored
        st.session_state["tutor_greeting_version"] = GREETING_VERSION
    else:
        greeting = dict(GREETING)
        provider, model = current_selection()
        try:
            with st.spinner("老师正在想怎么开口..."):
                lead = TutorLead.compose(
                    kind="greeting",
                    message="",
                    transcript="",
                    draft=GREETING["content"],
                    plan=TutorPlan.plan_text(plan),
                    student_memory=TeacherMemory.memory_text(),
                    personal_memory=Memory.memory_text("tutor"),
                    no_drill=True,
                    update_summary=False,
                    provider=provider,
                    model=model,
                )
            if lead.get("reply"):
                greeting["content"] = lead["reply"]
        except Exception:
            logger.exception("开场白生成失败")
        st.session_state.tutor_messages = [greeting]
        st.session_state["tutor_greeting_version"] = GREETING_VERSION
        _save_tutor_chat()
elif st.session_state.get("tutor_greeting_version") != GREETING_VERSION:
    if st.session_state.tutor_messages and st.session_state.tutor_messages[0].get(
        "role"
    ) == "assistant":
        st.session_state.tutor_messages[0] = GREETING
        _save_tutor_chat()
    st.session_state["tutor_greeting_version"] = GREETING_VERSION

cue_card = st.session_state.get("part2_cue_card", "")
student_answer = st.session_state.get("part2_input", "")


def _rule(bottom: str = "0.35rem") -> None:
    st.markdown(
        "<hr style='margin:0.35rem 0 "
        f"{bottom};border:none;border-top:1px solid rgba(128,128,128,0.22)'>",
        unsafe_allow_html=True,
    )


def _queue_user_point(text: str) -> None:
    label = re.sub(r"\s+", " ", str(text or "")).strip()
    if not label:
        return
    existing = PrepBook.find_exact(label)
    st.session_state["tutor_pending_label"] = existing["label"] if existing else label
    st.session_state["tutor_pending_original"] = label
    st.session_state["tutor_pending_existing"] = bool(existing)
    st.toast("在侧边栏「➕ 我想练」里确认一下")
    st.rerun()


def _pending_card() -> None:
    label = st.session_state.get("tutor_pending_label")
    if not label:
        return
    st.caption("确认加入备课本")
    edited = st.text_input(
        "概括成",
        value=label,
        key=f"tutor_pending_edit_{abs(hash(label))}",
    )
    existing = bool(st.session_state.get("tutor_pending_existing"))
    st.caption(
        "备课本里已有这个条目，可以直接加入当前课程计划。"
        if existing
        else "确认后加入备课本，同时加入当前计划。"
    )
    left, right = st.columns(2)
    add_label = "加入课程计划" if existing else "加入备课本和计划"
    if left.button(add_label, key="tutor_pending_add", use_container_width=True):
        value = (edited or "").strip()
        if not value:
            st.warning("先写一个概括。")
            return
        if existing:
            item = PrepBook.find_exact(label) or PrepBook.find_exact(value)
            if not item:
                st.warning("备课本里的这个条目找不到了，请重新输入。")
                return
        else:
            item, _created = PrepBook.add_user_point(
                value, protected_keys=plan_keys
            )
        updated, added = TutorPlan.add_user_point(
            item["label"],
            source_key=item["source_key"],
            kind=item["kind"],
        )
        st.session_state["tutor_plan"] = updated
        st.session_state.pop("tutor_pending_label", None)
        st.session_state.pop("tutor_pending_original", None)
        st.session_state.pop("tutor_pending_existing", None)
        if not added:
            current = TutorPlan.load_plan()
            already = any(
                str(point.get("source_key") or "").casefold()
                == str(item.get("source_key") or "").casefold()
                for point in current.get("points") or []
            )
            if already:
                st.toast("这个点已经在当前计划里")
            elif len(current.get("points") or []) >= 10:
                st.toast("计划已满 10 个点，没有加入")
            else:
                st.toast("没有加入计划")
        else:
            st.toast("已加入课程计划" if existing else "已加入备课本和计划")
        st.rerun()
    if right.button("取消", key="tutor_pending_cancel", use_container_width=True):
        st.session_state.pop("tutor_pending_label", None)
        st.session_state.pop("tutor_pending_original", None)
        st.session_state.pop("tutor_pending_existing", None)
        st.rerun()


def _clear_coaching() -> None:
    for key in (
        "tutor_practice",
        "tutor_practice_question",
        "tutor_practice_model",
        "tutor_practice_stage",
        "tutor_practice_focus",
        "tutor_practice_checklist",
        "tutor_practice_turns",
        "tutor_practice_lesson",
    ):
        st.session_state.pop(key, None)
    _save_training_meta()


def _force_check_plan() -> None:
    """手动强制裁判检查本场全部聊天，补齐可能漏掉的计划点。"""
    plan_now = st.session_state.get("tutor_plan") or plan
    pending = TutorPlan.pending_points(plan_now)
    if not pending:
        st.toast("本课计划已经全部完成")
        return
    provider, model = current_selection()
    try:
        with st.spinner("正在检查本场聊天..."):
            data = PlanJudge.judge_conversation(
                st.session_state.get("tutor_messages") or [],
                pending,
                provider=provider,
                model=model,
            )
    except Exception:
        logger.exception("强制检查计划失败")
        st.toast("检查失败，请稍后再试")
        return
    completed = data.get("completed") or []
    if not completed:
        st.toast("没有检测到新的已完成点")
        return
    updated = plan_now
    count = 0
    for item in completed:
        key = item.get("source_key") if isinstance(item, dict) else ""
        if not key:
            continue
        updated = TutorPlan.mark_point(key)
        count += 1
    if not count:
        st.toast("没有检测到新的已完成点")
        return
    st.session_state["tutor_plan"] = updated
    st.toast(f"✅ 检测到 {count} 个已完成点")
    if TutorPlan.is_done(updated):
        _clear_coaching()
        st.toast("🎉 本课计划已完成")
    st.rerun()


def _start_coaching_direct(point: dict, question: str, reply: str, model_answer: str = "") -> None:
    st.session_state["tutor_practice"] = [point]
    st.session_state["tutor_practice_question"] = question
    st.session_state["tutor_practice_model"] = model_answer[:500]
    st.session_state["tutor_practice_stage"] = "answer"
    st.session_state["tutor_practice_focus"] = ""
    st.session_state["tutor_practice_checklist"] = []
    st.session_state["tutor_practice_turns"] = 0
    st.session_state["tutor_practice_lesson"] = uuid.uuid4().hex[:8]
    previous_teacher = next(
        (
            str(message.get("content") or "")
            for message in reversed(st.session_state.tutor_messages)
            if message.get("role") == "assistant"
        ),
        "",
    )
    st.session_state.tutor_messages.append({"role": "assistant", "content": reply})
    _save_tutor_chat()
    _save_training_meta()
    if _track_plan_message(reply, previous_teacher):
        _clear_coaching()


def _begin_training(point: dict) -> None:
    if not TutorPlan.can_train(st.session_state.get("tutor_plan") or plan):
        st.toast("计划里没有未完成的点了")
        return
    try:
        question = ask_practice_question(
            [{"label": point["label"], "kind": point.get("kind", "phrase")}],
            memory=TeacherMemory.memory_text(),
        )
    except Exception:
        logger.exception("训练模型出题失败")
        st.toast("训练模型暂时没接上")
        return
    draft = f"好，我们练这个：{question}"
    lead = _lead_speak(
        "tutor",
        "我想练这个",
        draft,
        practice={
            "question": question,
            "targets": [point["label"]],
            "model_answer": "",
        },
        plan_done=False,
    )
    if lead.get("keep_practice") is False:
        st.session_state.tutor_messages.append(
            {"role": "assistant", "content": lead.get("reply") or draft}
        )
        _save_tutor_chat()
        st.rerun()
    _start_coaching_direct(
        point,
        question,
        lead.get("reply") or draft,
    )
    st.rerun()


with st.sidebar:
    plan_points = plan.get("points") or []
    if plan_points:
        done_count = sum(1 for item in plan_points if item.get("status") == "mastered")
        with st.expander(
            f"📋 本课计划（{done_count}/{len(plan_points)}）", expanded=False
        ):
            for item in plan_points:
                mark = "✅" if item.get("status") == "mastered" else "○"
                st.caption(f"{mark} {item['label']}")
            if TutorPlan.pending_points(plan):
                if st.button(
                    "🔍 强制检测是否完成",
                    key="tutor_force_check",
                    use_container_width=True,
                ):
                    _force_check_plan()
            if TutorPlan.is_done(plan):
                st.caption("本课已完成；每天第一次打开时会自动更新。")
                if st.button("更新计划", key="tutor_replan", use_container_width=True):
                    provider, model = current_selection()
                    try:
                        with st.spinner("重新备课..."):
                            new_plan = TutorPlan.create_plan(
                                memory=TeacherMemory.memory_text(),
                                previous=plan,
                                manual=True,
                                provider=provider,
                                model=model,
                            )
                    except Exception:
                        logger.exception("重新备课失败")
                        st.toast("重新备课失败，保留原计划")
                    else:
                        st.session_state["tutor_plan"] = new_plan
                        st.rerun()
    else:
        st.caption("📋 还没有本课计划：在下面「我想练」里加一个点。")
        if PrepBook.candidates(protected_keys=plan_keys) and st.button(
            "从备课本生成计划", key="tutor_make_plan", use_container_width=True
        ):
            provider, model = current_selection()
            try:
                with st.spinner("备课..."):
                    new_plan = TutorPlan.create_plan(
                        memory=TeacherMemory.memory_text(),
                        previous=plan,
                        manual=True,
                        provider=provider,
                        model=model,
                    )
            except Exception:
                logger.exception("生成计划失败")
                st.toast("生成计划失败")
            else:
                st.session_state["tutor_plan"] = new_plan
                st.rerun()

    with st.expander("➕ 我想练", expanded=False):
        want = st.text_input("想练什么", key="tutor_want_input")
        if st.button("准备加入", key="tutor_want_ready", use_container_width=True):
            _queue_user_point(want)
        _pending_card()

    prep_items = PrepBook.candidates(protected_keys=plan_keys)
    with st.expander(f"📚 备课本（{len(prep_items)}）", expanded=False):
        if not prep_items:
            st.caption("备课本为空：弱词、笔记本、表达会慢慢进来。")
        else:
            with st.container(height=260):
                for item in prep_items:
                    st.caption(f"- {item['label']} · {item['source']}")

    errors = TutorErrors.items()
    with st.expander(
        f"🩹 待整理知识点（{len(errors)}）",
        expanded=False,
        key="tutor_errors_expander",
    ):
        if not errors:
            st.caption("还没有待整理知识点。")
        else:
            with st.container(height=260):
                for error in errors:
                    st.caption(f"- {error['text']}（{error['count']} 次）")
                    left, right = st.columns(2)
                    if left.button(
                        "加入备课本",
                        key=f"err_add_{abs(hash(error['text']))}",
                        use_container_width=True,
                    ):
                        item, _ = PrepBook.add_user_point(
                            error["text"], protected_keys=plan_keys
                        )
                        TutorErrors.remove(error["text"])
                        st.toast(f"已加入备课本：{item['label']}")
                        st.rerun()
                    if right.button(
                        "删除",
                        key=f"err_del_{abs(hash(error['text']))}",
                        use_container_width=True,
                    ):
                        TutorErrors.remove(error["text"])
                        st.rerun()

    TeacherMemory.render_sidebar("英语学习档案")
    Memory.render_memory_sidebar("tutor", "关于你")

    _rule()
    st.subheader("📎 带上当前 Part 2 练习")
    use_card = st.checkbox(
        "使用当前题卡", value=bool(cue_card), disabled=not bool(cue_card)
    )
    use_answer = st.checkbox(
        "使用我刚才的故事", value=bool(student_answer), disabled=not bool(student_answer)
    )
    if cue_card:
        st.text_area("当前题卡", cue_card, height=150, disabled=True)
    if not cue_card:
        st.caption("还没有题卡？先去「讲个故事」抽一张。")
    _rule()
    st.subheader("📓 随手记")
    st.caption("练习里碰到的好词好句，顺手存下来。")
    render_quick_add("AI 老师", "tutor", scene=cue_card)

context_card = cue_card if use_card else ""
context_answer = student_answer if use_answer else ""


def _attach_item_audio(items: list[dict]) -> None:
    async def _one(item: dict) -> None:
        text = str(item.get("text") or "").strip()
        if not text:
            item["audio"] = None
            return
        path = new_audio_path("tutor_item")
        try:
            await asyncio.wait_for(synthesize(text, path), timeout=10)
            item["audio"] = existing_audio(path)
        except Exception:
            item["audio"] = None

    async def _all() -> None:
        await asyncio.gather(*(_one(item) for item in items))

    asyncio.run(_all())


def _remember_explicit(text: str) -> bool:
    """用户说“记住……”时，按内容分到「英语学习档案」或「关于你」。"""
    raw = re.sub(
        r"^\s*(?:请|麻烦)?(?:记住|别忘了|别忘记|remember)\s*[:：]?\s*",
        "",
        str(text or ""),
        flags=re.I,
    ).strip(" ，。,.!！")
    if not raw:
        return False

    english = re.search(
        r"雅思|口语|写作|听力|阅读|单词|词汇|语法|时态|从句|冠词|介词|"
        r"发音|重音|语调|流利|分数|band|表达|用词|句型|句式|错误|弱点|"
        r"练法|学习|考试|答案|句子",
        raw,
        re.I,
    )
    if english:
        TeacherMemory.add_note(text)
        st.toast("🧠 已写入英语学习档案")
        return True

    fact = re.sub(r"^(?:你|自己)(?:叫|的名字是|名字叫)", "老师叫", raw)
    fact = re.sub(r"^我(?:叫|的名字是|名字叫)", "用户叫", fact)
    fact = re.sub(r"^我", "用户", fact)
    fact = re.sub(r"^你", "老师", fact)
    if Memory.remember("tutor", fact, permanent=True):
        st.toast("💬 已写入关于你")
        return True
    return False


_TRAIN_INTENT_RE = re.compile(
    r"^\s*(?:(?:我|我们)\s*)?(?:"
    r"我想练|想练|要练|开始练|开始训练|继续练|再练|陪我练|考我|"
    r"练一下|练一会|练会儿|练一轮|练练|训练吧|上课吧|开始吧"
    r")\s*[:：]?\s*(.*)$",
    re.I,
)
_TRAIN_INTENT_HINT_RE = re.compile(
    r"(?:练|训练|上课).{0,16}(?:吧|吗|呗|一轮|一会|会儿|开始|继续|再)|"
    r"(?:开始|继续|再).{0,12}(?:练|训练|上课)",
    re.I,
)
_TRAIN_YES_RE = re.compile(
    r"^\s*(?:(?:那|我们就|我们|就|好)\s*)?"
    r"(?:开始|开始吧|好|好的|可以|行|嗯|来吧|练吧|确认|yes|ok|start)",
    re.I,
)


def _training_request(text: str) -> str | None:
    """返回用户点名的内容；只有“想开始”但没点名时返回空串；不是意图返回 None。"""
    match = _TRAIN_INTENT_RE.match(text)
    requested = (match.group(1) if match else "").strip()
    if not match and _TRAIN_INTENT_HINT_RE.search(text):
        requested = ""
    elif not match:
        return None
    requested = requested.strip("吧 吗 呗 呀 啊 哦 ！!。.，, ")
    requested = re.sub(
        r"^(?:一轮|一会|会儿|一下|练|训练|上课)\s*", "", requested
    ).strip()
    if requested in {"", "吧", "吗", "呗", "呀", "啊", "哦"}:
        requested = ""
    return requested


def _find_pending_point(text: str, pending: list[dict]) -> dict | None:
    value = str(text or "").strip().casefold()
    if not value:
        return None
    for point in pending:
        label = str(point.get("label") or "").casefold()
        key = str(point.get("source_key") or "").casefold()
        if value in label or value == key or (key and key in value):
            return point
    return None


def _point_phrases(point: dict) -> list[str]:
    label = str(point.get("label") or "")
    parts = []
    if "→" in label:
        parts.append(label.rsplit("→", 1)[-1])
    parts.extend(re.findall(r"[A-Za-z][A-Za-z'’\- ]{3,}", label))
    key = str(point.get("source_key") or "")
    if ":" in key:
        parts.append(key.split(":", 1)[1])
    result = []
    for part in parts:
        value = part.strip(" .。！!？?，,;；:：\"'「」")
        if len(value) >= 4:
            result.append(value)
    return result


def _find_point_in_text(text: str, pending: list[dict]) -> dict | None:
    value = str(text or "").casefold()
    for point in pending:
        for phrase in _point_phrases(point):
            if phrase.casefold() in value:
                return point
    return None


_TARGET_SWITCH_RE = re.compile(
    r"(?:start|begin|let'?s|today|with|练|换|先|用|就练|我们说)",
    re.I,
)


def _handle_training_intent(text: str) -> bool:
    requested = _training_request(text)
    if requested is None:
        return False
    pending = TutorPlan.pending_points(st.session_state.get("tutor_plan") or plan)
    if not pending:
        if requested:
            _queue_user_point(requested)
        else:
            st.session_state.tutor_messages.append(
                {
                    "role": "assistant",
                    "content": "本课计划里还没有可练的点；先在侧边栏「➕ 我想练」里加一个。",
                }
            )
            _save_tutor_chat()
            st.rerun()
        return True
    point = _find_pending_point(requested, pending) if requested else pending[0]
    if not point:
        _queue_user_point(requested)
        return True
    _begin_training(point)
    return True


def _send(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    history = list(st.session_state.tutor_messages)
    st.session_state.tutor_messages.append({"role": "user", "content": text})
    _save_tutor_chat()

    if st.session_state.get("tutor_practice_stage") and _TRAIN_YES_RE.match(text):
        draft = "已经开始了，直接把上面的问题用英文完整打出来就行。"
        lead = _lead_speak("tutor", text, draft, no_drill=True)
        st.session_state.tutor_messages.append(
            {"role": "assistant", "content": lead.get("reply") or draft}
        )
        _save_tutor_chat()
        st.rerun()
    if st.session_state.get("tutor_practice_stage") and _TARGET_SWITCH_RE.search(text):
        pending = TutorPlan.pending_points(
            st.session_state.get("tutor_plan") or plan
        )
        point = _find_point_in_text(text, pending)
        current = (st.session_state.get("tutor_practice") or [{}])[0]
        if point and point.get("source_key") != current.get("source_key"):
            _begin_training(point)
            return
    if _handle_training_intent(text):
        return

    paused = False
    if st.session_state.get("tutor_practice_stage"):
        if should_pause_coaching(text):
            _clear_coaching()
            paused = True
        else:
            _coach_practice(text, st.session_state.get("tutor_practice") or [])
            return

    remembered = False
    if TeacherMemory.looks_like_remember(text):
        remembered = _remember_explicit(text)

    if not remembered and is_bare_lookup(text):
        with st.spinner("老师正在逐条讲解并生成发音..."):
            try:
                data = explain_vocabulary(text)
            except Exception:
                data = {"items": []}
            items = data.get("items") or []
            if items:
                intro = data.get("intro") or "我按条给你拆开讲："
                lead = _lead_speak(
                    "dictionary", text, intro, no_drill=True, update_summary=False
                )
                intro = lead.get("reply") or intro
                _attach_item_audio(items)
                st.session_state.tutor_messages.append(
                    {"role": "assistant", "content": intro, "items": items}
                )
                _save_tutor_chat()
                _remember_personal(text, intro)
                return

    plan_ready = TutorPlan.can_train(st.session_state.get("tutor_plan") or plan)
    try:
        with st.spinner("老师正在思考..."):
            turn = ask_tutor_turn(
                text,
                history,
                context_card,
                context_answer,
                memory=TeacherMemory.memory_text(),
                plan=TutorPlan.plan_text(st.session_state.get("tutor_plan") or plan),
                paused=paused,
                no_drill=True,
                plan_done=not plan_ready,
            )
    except Exception:
        logger.exception("老师回合失败")
        st.session_state.tutor_messages.append(
            {"role": "assistant", "content": "（老师这边暂时没接上，再发一次试试？）"}
        )
        _save_tutor_chat()
        return

    reply = turn.get("reply") or "（老师这边暂时没接上，再问一次试试？）"
    try:
        TutorErrors.add_errors(turn.get("new_issues") or [])
    except Exception:
        logger.exception("记录聊天中指出的错误失败")
    lead = _lead_speak(
        "tutor",
        text,
        reply,
        no_drill=True,
        plan_done=not plan_ready,
    )
    reply = lead.get("reply") or reply
    previous_teacher = next(
        (
            str(message.get("content") or "")
            for message in reversed(st.session_state.tutor_messages)
            if message.get("role") == "assistant"
        ),
        "",
    )
    st.session_state.tutor_messages.append({"role": "assistant", "content": reply})
    _save_tutor_chat()
    _track_plan_message(reply, previous_teacher, text)
    _remember_personal(text, reply)


def _remember_lesson(
    question: str,
    answer: str,
    feedback: str,
    targets: list[dict],
    usage,
    lesson_id: str,
    final: bool,
    focus: str,
    status: str,
    checklist,
    provider: str,
    model: str,
) -> None:
    try:
        TeacherMemory.update_from_lesson(
            question=question,
            answer=answer,
            feedback=feedback,
            targets="\n".join(str(item.get("label") or "") for item in targets),
            results="\n".join(
                f"{item.get('index')}.{item.get('result')}"
                for item in (usage or [])
            ),
            lesson_id=lesson_id,
            followup=not final,
            focus=focus,
            status=status,
            checklist=checklist,
            final=final,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("后台更新英语学习档案失败")


def _save_plan_tracking(last_points: list[str]) -> None:
    meta = ChatHistory.load_meta("tutor")
    meta["plan_last_points"] = list(last_points or [])
    meta["plan_lesson"] = str(plan.get("lesson_id") or "")
    ChatHistory.save_meta("tutor", meta)


def _track_plan_message(
    teacher_message: str,
    previous_teacher_message: str,
    user_message: str = "",
) -> bool:
    """每条老师消息都检查：当前练哪个点，切换点就把上一个点打勾。"""
    plan_now = st.session_state.get("tutor_plan") or plan
    pending = TutorPlan.pending_points(plan_now)
    if not pending:
        return False
    last_points = [
        str(key).strip()
        for key in (st.session_state.get("tutor_last_points") or [])
        if str(key).strip()
    ]
    provider, model = current_selection()
    try:
        data = PlanJudge.judge_message(
            teacher_message,
            previous_teacher_message,
            pending,
            user_message=user_message,
            last_points=last_points,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("逐条消息计划裁判失败")
        return False
    pending_keys = {
        str(point.get("source_key") or "").casefold() for point in pending
    }
    active = [
        str(key).strip()
        for key in (data.get("active_source_keys") or [])
        if str(key).strip().casefold() in pending_keys
    ]
    completed = []
    for item in data.get("completed") or []:
        key = item.get("source_key") if isinstance(item, dict) else ""
        if key and str(key).casefold() in pending_keys:
            completed.append(str(key))
    seen = set()
    marked = False
    updated = plan_now
    for key in completed:
        if key.casefold() in seen:
            continue
        seen.add(key.casefold())
        updated = TutorPlan.mark_point(key)
        marked = True
    if active:
        last_points = active
        st.session_state["tutor_last_points"] = last_points
        _save_plan_tracking(last_points)
    if not marked:
        return False
    st.session_state["tutor_plan"] = updated
    st.toast("✅ 计划点已完成")
    remaining = TutorPlan.pending_points(updated)
    if not remaining:
        st.toast("🎉 本课计划已完成")
        return True
    # 实时进入训练：刚完成一个点、还有剩余点时，直接切到下一个点。
    if not st.session_state.get("tutor_practice_stage"):
        next_point = next(
            (
                point
                for point in remaining
                if str(point.get("source_key") or "").casefold()
                in {str(key).casefold() for key in active}
            ),
            remaining[0],
        )
        if active:
            st.session_state["tutor_practice"] = [next_point]
            st.session_state["tutor_practice_question"] = teacher_message
            st.session_state["tutor_practice_model"] = ""
            st.session_state["tutor_practice_stage"] = "answer"
            st.session_state["tutor_practice_focus"] = ""
            st.session_state["tutor_practice_checklist"] = []
            st.session_state["tutor_practice_turns"] = 0
            st.session_state["tutor_practice_lesson"] = uuid.uuid4().hex[:8]
            _save_training_meta()
            st.toast("▶️ 已进入训练")
        else:
            _begin_training(next_point)
    return False


def _coach_practice(answer: str, targets: list[dict]) -> None:
    question = st.session_state.get("tutor_practice_question", "")
    stage = st.session_state.get("tutor_practice_stage", "answer")
    focus = st.session_state.get("tutor_practice_focus", "")
    checklist = st.session_state.get("tutor_practice_checklist") or []
    first_turn = stage == "answer"
    provider, model = current_selection()
    current_plan = st.session_state.get("tutor_plan") or plan

    recent = st.session_state.tutor_messages[:-1][-8:]
    history = "\n".join(
        f"{'Tutor' if msg.get('role') == 'assistant' else 'Student'}: "
        f"{str(msg.get('content') or '')[:700]}"
        for msg in recent
    )

    try:
        with st.spinner("老师正在看你的回答..."):
            data = coach_practice_answer(
                question,
                targets,
                answer,
                history=history,
                focus=focus,
                checklist=checklist,
                first_turn=first_turn,
                status="teaching" if first_turn else stage,
                model_answer=st.session_state.get("tutor_practice_model", ""),
                memory=TeacherMemory.memory_text(),
                plan=TutorPlan.plan_text(current_plan),
            )
    except Exception:
        logger.exception("陪练回合失败")
        st.session_state.tutor_messages.append(
            {"role": "assistant", "content": "（老师这边暂时没接上，把刚才那句再发一次试试？）"}
        )
        _save_tutor_chat()
        return

    try:
        TutorErrors.add_errors(data.get("new_issues") or [])
    except Exception:
        logger.exception("记录待整理知识点失败")

    mastered = data.get("status") == "mastered"
    checklist_out = data.get("checklist", checklist)
    if not isinstance(checklist_out, list):
        checklist_out = checklist

    st.session_state["tutor_practice_stage"] = "mastered" if mastered else "coaching"
    st.session_state["tutor_practice_focus"] = data.get("focus") or focus
    st.session_state["tutor_practice_checklist"] = checklist_out
    st.session_state["tutor_practice_turns"] = (
        int(st.session_state.get("tutor_practice_turns") or 0) + 1
    )
    _save_training_meta()

    feedback = data.get("feedback") or "（这次没接上，把刚才那句再说一遍试试？）"
    previous_teacher = next(
        (
            str(message.get("content") or "")
            for message in reversed(st.session_state.tutor_messages)
            if message.get("role") == "assistant"
        ),
        "",
    )
    lead = _lead_speak("coach", answer, feedback)
    feedback = lead.get("reply") or feedback
    st.session_state.tutor_messages.append(
        {"role": "assistant", "content": feedback}
    )
    _save_tutor_chat()
    judge_done = _track_plan_message(feedback, previous_teacher, answer)
    _remember_personal(answer, feedback)

    final = mastered or not checklist_out or judge_done
    if targets and (first_turn or final):
        threading.Thread(
            target=_remember_lesson,
            args=(
                question,
                answer,
                feedback,
                targets,
                data.get("usage"),
                st.session_state.get("tutor_practice_lesson", ""),
                final,
                data.get("focus") or focus,
                data.get("status") or "teaching",
                checklist_out,
                provider,
                model,
            ),
            daemon=True,
        ).start()

    if judge_done or data.get("reason") == "stopped":
        _clear_coaching()


for idx, msg in enumerate(st.session_state.tutor_messages):
    with st.chat_message(msg["role"]):
        if msg.get("items"):
            st.caption("📖 词典讲解")
            if msg.get("content"):
                st.markdown(msg["content"])
            type_labels = {"word": "单词", "phrase": "词组", "sentence": "句子"}
            for j, item in enumerate(msg["items"]):
                head_col, btn_col = st.columns([8, 1])
                label = type_labels.get(item.get("type"), "")
                heading = f"**{item['text']}**"
                if label:
                    heading += f" · {label}"
                if item.get("phonetic"):
                    heading += f" /{item['phonetic']}/"
                head_col.markdown(heading)
                audio_path = item.get("audio")
                if audio_path:
                    if btn_col.button(
                        "🔊",
                        key=f"tutor_audio_{idx}_{j}",
                        help="听发音",
                        use_container_width=True,
                    ):
                        st.session_state.tutor_audio_request = f"{idx}:{j}"
                        st.rerun()
                if item.get("pos"):
                    st.caption(item["pos"])
                if item.get("meaning"):
                    st.write(item["meaning"])
                if item.get("usage"):
                    st.caption(item["usage"])
                if item.get("collocations"):
                    st.caption("搭配：" + "；".join(item["collocations"]))
                if item.get("example"):
                    example = f"**例：** {item['example']}"
                    if item.get("example_zh"):
                        example += f"（{item['example_zh']}）"
                    st.markdown(example)
                if not audio_path:
                    st.caption("发音生成失败，可稍后再试。")
                if (
                    audio_path
                    and st.session_state.get("tutor_audio_request") == f"{idx}:{j}"
                ):
                    st.audio(audio_path, autoplay=True)
                    st.session_state.tutor_audio_request = ""
                st.divider()
        else:
            st.markdown(msg["content"])

if st.session_state.get("tutor_practice_stage"):
    _input_placeholder = "把你这句英文完整打出来，老师在等你的回答…"
else:
    _input_placeholder = "问老师任何雅思口语问题…"

if prompt := st.chat_input(_input_placeholder):
    _send(prompt)
    st.rerun()


def _restart_tutor_chat() -> None:
    st.session_state.pop("tutor_messages", None)
    st.session_state.pop("tutor_greeting_version", None)
    st.session_state.pop("tutor_audio_request", None)
    for key in (
        "tutor_pending_label",
        "tutor_pending_original",
        "tutor_pending_existing",
        "tutor_last_points",
    ):
        st.session_state.pop(key, None)
    _clear_coaching()
    meta = ChatHistory.load_meta("tutor")
    meta.pop("plan_last_points", None)
    meta.pop("plan_lesson", None)
    ChatHistory.save_meta("tutor", meta)


ChatHistory.render_restart_button("tutor", _restart_tutor_chat)
