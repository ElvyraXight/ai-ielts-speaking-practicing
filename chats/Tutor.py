# chats/Tutor.py

import asyncio
import threading
import uuid

import streamlit as st

from utils import Practice
from utils import TeacherMemory
from utils.config import describe_llm
from utils.LearnerProfile import build_profile, counts
from utils.Notebook import render_quick_add
from utils.tts import existing_audio, new_audio_path, synthesize
from utils.Tutor import (
    ask_tutor_turn,
    coach_practice_answer,
    explain_vocabulary,
    is_bare_lookup,
)

st.set_page_config(page_title="雅思口语老师", page_icon="👩‍🏫", layout="wide")

st.title("👩‍🏫 雅思口语老师")
st.caption(f"当前模型：{describe_llm()}")


GREETING_VERSION = 4
GREETING = {
    "role": "assistant",
    "content": (
        "来啦，我在。今天想聊什么就说，不想聊就随便说两句英文，"
        "我听听你最近的状态。"
    ),
}

if "tutor_messages" not in st.session_state:
    st.session_state.tutor_messages = [GREETING]
    st.session_state["tutor_greeting_version"] = GREETING_VERSION
elif st.session_state.get("tutor_greeting_version") != GREETING_VERSION:
    # 升级后把旧的功能菜单开场白换掉，不动后面的对话
    if st.session_state.tutor_messages and st.session_state.tutor_messages[0].get(
        "role"
    ) == "assistant":
        st.session_state.tutor_messages[0] = GREETING
    st.session_state["tutor_greeting_version"] = GREETING_VERSION

cue_card = st.session_state.get("part2_cue_card", "")
student_answer = st.session_state.get("part2_input", "")
teacher_memory = TeacherMemory.memory_text()
prep = Practice.prep_text(6)


def _rule(bottom: str = "0.35rem") -> None:
    """侧边栏的统一分隔线；bottom 控制下半段留白。"""
    st.markdown(
        "<hr style='margin:0.35rem 0 "
        f"{bottom};border:none;border-top:1px solid rgba(128,128,128,0.22)'>",
        unsafe_allow_html=True,
    )


with st.sidebar:
    st.subheader("📚 老师能看到的学习档案")
    share_profile = st.toggle(
        "让老师参考背单词 / 笔记本",
        value=True,
        key="tutor_use_profile",
        help="关掉后，老师只能看到这次对话和你贴的内容。",
    )
    info = counts()
    st.caption(
        f"单词 {info['learned']} 个（到期 {info['due']}）· "
        f"笔记 {info['notes']} 条 · 表达 {info['expressions']} 条"
    )
    profile = ""
    if share_profile:
        profile = build_profile()
        with st.expander("预览老师看到的内容"):
            st.code(profile or "（还没有可参考的数据）", language="text")
    TeacherMemory.render_sidebar()
    prep_points = Practice.prep_points(6)
    if prep_points:
        with st.expander(f"📒 备课本（{len(prep_points)}）"):
            st.caption("老师会优先从这几条备课：错得多、到期、连对少的先练。")
            for item in prep_points:
                st.caption(
                    f"- {item['label']} · 错 {item['errors']} · "
                    f"连对 {item['streak']} · {item['due']}"
                )
    _rule()

with st.sidebar:
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
    """给每个条目并行生成发音；单条失败不影响整条回复。"""

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


def _send(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    history = list(st.session_state.tutor_messages)
    st.session_state.tutor_messages.append({"role": "user", "content": text})

    if st.session_state.get("tutor_practice_stage"):
        _coach_practice(text, st.session_state.get("tutor_practice") or [])
        return

    remembered = False
    if TeacherMemory.looks_like_remember(text):
        TeacherMemory.add_note(text)
        remembered = True
        st.toast("🧠 已写入老师的长期记忆")

    if not remembered and is_bare_lookup(text):
        with st.spinner("老师正在逐条讲解并生成发音..."):
            try:
                data = explain_vocabulary(text)
            except Exception:
                data = {"items": []}
            items = data.get("items") or []
            if items:
                _attach_item_audio(items)
                st.session_state.tutor_messages.append(
                    {
                        "role": "assistant",
                        "content": data.get("intro") or "我按条给你拆开讲：",
                        "items": items,
                    }
                )
                return

    with st.spinner("老师正在思考..."):
        turn = ask_tutor_turn(
            text,
            history,
            context_card,
            context_answer,
            profile=profile,
            memory=TeacherMemory.memory_text(),
            prep=prep,
        )
    reply = turn.get("reply") or "（老师这边暂时没接上，再问一次试试？）"
    st.session_state.tutor_messages.append({"role": "assistant", "content": reply})
    if turn.get("practice"):
        _start_coaching(turn["practice"])


def _start_coaching(practice: dict) -> None:
    """老师刚问完问题：记下题目，下一次回复按“回答”来陪练。"""
    question = str(practice.get("question") or "").strip()
    if not question:
        return
    labels = [
        str(item).strip()[:60]
        for item in (practice.get("targets") or [])
        if str(item).strip()
    ][:3]
    targets = [
        {"label": label, "kind": "phrase", "strength": 1} for label in labels
    ]
    st.session_state["tutor_practice"] = targets
    st.session_state["tutor_practice_question"] = question
    st.session_state["tutor_practice_stage"] = "answer"
    st.session_state["tutor_practice_focus"] = ""
    st.session_state["tutor_practice_checklist"] = []
    st.session_state["tutor_practice_turns"] = 0
    st.session_state["tutor_practice_lesson"] = uuid.uuid4().hex[:8]


def _clear_coaching() -> None:
    for key in (
        "tutor_practice",
        "tutor_practice_question",
        "tutor_practice_stage",
        "tutor_practice_focus",
        "tutor_practice_checklist",
        "tutor_practice_turns",
        "tutor_practice_lesson",
    ):
        st.session_state.pop(key, None)


def _remember_lesson(
    question: str,
    answer: str,
    feedback: str,
    targets: list[dict],
    usage,
    lesson_id: str,
    first_turn: bool,
    focus: str,
    status: str,
    checklist,
) -> None:
    """后台更新老师的学生模型；失败不影响这次对话。"""
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
            followup=not first_turn,
            focus=focus,
            status=status,
            checklist=checklist,
        )
    except Exception:
        pass


def _coach_practice(answer: str, targets: list[dict]) -> None:
    """一个教学回合：先评价，再挑一个点讲解，不自动出下一题。"""
    question = st.session_state.get("tutor_practice_question", "")
    stage = st.session_state.get("tutor_practice_stage", "answer")
    focus = st.session_state.get("tutor_practice_focus", "")
    checklist = st.session_state.get("tutor_practice_checklist") or []
    first_turn = stage == "answer"

    recent = st.session_state.tutor_messages[:-1][-8:]
    history = "\n".join(
        f"{'Tutor' if msg.get('role') == 'assistant' else 'Student'}: "
        f"{str(msg.get('content') or '')[:700]}"
        for msg in recent
    )

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
            profile=profile,
            memory=teacher_memory,
            prep=prep,
        )

    if first_turn:
        Practice.apply_results(
            targets, data.get("usage"), data.get("new_issues")
        )

    st.session_state["tutor_practice_stage"] = (
        "mastered" if data.get("status") == "mastered" else "coaching"
    )
    st.session_state["tutor_practice_focus"] = data.get("focus") or focus
    st.session_state["tutor_practice_checklist"] = data.get(
        "checklist", checklist
    )
    st.session_state["tutor_practice_turns"] = (
        int(st.session_state.get("tutor_practice_turns") or 0) + 1
    )

    feedback = data.get("feedback") or "（这次没接上，把刚才那句再说一遍试试？）"
    st.session_state.tutor_messages.append(
        {"role": "assistant", "content": feedback}
    )

    threading.Thread(
        target=_remember_lesson,
        args=(
            question,
            answer,
            feedback,
            targets,
            data.get("usage"),
            st.session_state.get("tutor_practice_lesson", ""),
            first_turn,
            data.get("focus") or focus,
            data.get("status") or "teaching",
            data.get("checklist") or checklist,
        ),
        daemon=True,
    ).start()

    if data.get("status") == "mastered" or not (data.get("checklist") or []):
        # 这一句的薄弱点已经解决，回到普通对话；下一条消息不再被当成练习
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
                    and st.session_state.get("tutor_audio_request")
                    == f"{idx}:{j}"
                ):
                    st.audio(audio_path, autoplay=True)
                    st.session_state.tutor_audio_request = ""
                st.divider()
        else:
            st.markdown(msg["content"])

if prompt := st.chat_input("问老师任何雅思口语问题…"):
    _send(prompt)
    st.rerun()
