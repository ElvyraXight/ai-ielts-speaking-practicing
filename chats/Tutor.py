# chats/Tutor.py

import asyncio
import re

import streamlit as st

from utils import Practice
from utils.config import describe_llm
from utils.LearnerProfile import build_profile, counts
from utils.Notebook import render_quick_add
from utils.tts import existing_audio, new_audio_path, synthesize
from utils.Tutor import (
    ask_practice_question,
    ask_tutor,
    coach_practice_answer,
    explain_vocabulary,
    is_bare_lookup,
)

_NEXT_QUESTION_RE = re.compile(
    r"(下一题|下一个问题|再来一题|换个题|换一题|next question|another question)",
    re.I,
)
_START_PRACTICE_RE = re.compile(
    r"(陪我练|陪我练习|安排练习|按我的进度安排练习|开始练习|练一练|"
    r"来一题|给我一题|出个题|practice with me|start practice)",
    re.I,
)
_EXIT_PRACTICE_RE = re.compile(
    r"(先不练了|不练了|结束练习|退出练习|stop practice)", re.I
)

st.set_page_config(page_title="AI 雅思老师", page_icon="🧑‍🏫", layout="wide")

st.title("🧑‍🏫 AI 雅思老师")
st.caption(f"🤖 当前模型：{describe_llm()}")

GREETING = {
    "role": "assistant",
    "content": (
        "你好，我是你的雅思口语老师。你可以：\n"
        "- 贴一段答案，让我指出问题并改成 Band 7+\n"
        "- 直接发单词、词组或句子，让我逐条讲解并生成发音\n"
        "- 问我某道题怎么展开、怎么说更自然\n"
        "- 想让我按你的进度陪你练，直接说「陪我练」\n\n"
        "我会参考你的背单词进度和笔记本里存的词句来出练习。想从哪儿开始？"
    ),
}

if "tutor_messages" not in st.session_state:
    st.session_state.tutor_messages = [GREETING]

cue_card = st.session_state.get("part2_cue_card", "")
student_answer = st.session_state.get("part2_input", "")


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
    weak_points = Practice.weakest(6)
    if weak_points:
        with st.expander(f"🎯 练习重点（{len(weak_points)}）"):
            for item in weak_points:
                st.caption(f"- {item['label']} · 熟练度 {item['strength']}/5")
    if st.session_state.get("tutor_practice"):
        st.caption("🎯 练习中：直接回复就是答案")
        focus = st.session_state.get("tutor_practice_focus")
        if focus:
            st.caption(f"当前在练：{focus}")
        checklist = st.session_state.get("tutor_practice_checklist") or []
        if checklist:
            st.caption(f"还要巩固 {len(checklist)} 个表达")
        st.caption("想换一题就说「下一题」；想暂停就说「先不练了」。")
    else:
        st.caption("想按进度练，直接说「陪我练」。")
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

    targets = st.session_state.get("tutor_practice")
    if targets:
        if _NEXT_QUESTION_RE.search(text) or _START_PRACTICE_RE.search(text):
            _start_practice()
            return
        if _EXIT_PRACTICE_RE.search(text):
            _stop_practice()
            return
        _coach_practice(text, targets)
        return

    if _START_PRACTICE_RE.search(text):
        _start_practice()
        return

    if is_bare_lookup(text):
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
        reply = ask_tutor(
            text, history, context_card, context_answer, profile=profile
        )
    st.session_state.tutor_messages.append({"role": "assistant", "content": reply})


def _start_practice() -> None:
    """挑 2-3 个最该练的点，出一道题，并把要用的点列给学生。"""
    targets = Practice.pick_targets(3)
    if not targets:
        st.session_state.tutor_messages.append(
            {
                "role": "assistant",
                "content": "还没有可练的素材：先去背几个词，或在笔记本里存几条表达，我再按你的弱项出题。",
            }
        )
        return
    with st.spinner("老师正在挑最该练的点..."):
        question = ask_practice_question(targets, profile)
    st.session_state["tutor_practice"] = targets
    st.session_state["tutor_practice_question"] = question
    st.session_state["tutor_practice_stage"] = "answer"
    st.session_state["tutor_practice_focus"] = ""
    st.session_state["tutor_practice_checklist"] = []
    st.session_state["tutor_practice_turns"] = 0

    points = "\n".join(
        f"{index}. {target['label']}" for index, target in enumerate(targets, 1)
    )
    content = f"这题请用上：\n{points}\n\n{question}"
    st.session_state.tutor_messages.append({"role": "assistant", "content": content})


def _stop_practice() -> None:
    for key in (
        "tutor_practice",
        "tutor_practice_question",
        "tutor_practice_stage",
        "tutor_practice_focus",
        "tutor_practice_checklist",
        "tutor_practice_turns",
    ):
        st.session_state.pop(key, None)
    st.session_state.tutor_messages.append(
        {
            "role": "assistant",
            "content": "好，先不练了。想继续时直接说「陪我练」。",
        }
    )


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
