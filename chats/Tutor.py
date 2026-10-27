# chats/Tutor.py

import streamlit as st

from utils.Part2 import describe_llm
from utils.Notebook import render_quick_add
from utils.Tutor import ask_tutor

st.set_page_config(page_title="AI 雅思老师", page_icon="🧑‍🏫", layout="wide")

# 与 Part 2 页面保持一致的浅蓝紫按钮
st.markdown("""
<style>
div.stButton > button[kind="primary"] {
    background-color: #E6E6FA !important;
    color: #4B0082 !important;
    border: 1px solid #D8BFD8 !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #D8BFD8 !important;
    color: #4B0082 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🧑‍🏫 AI 雅思老师")
st.caption("把答案贴给我，我帮你改；也可以问任何 Part 2 / Part 3 问题。")
st.caption(f"🤖 当前模型：{describe_llm()}")

GREETING = {
    "role": "assistant",
    "content": (
        "你好，我是你的雅思口语老师。你可以：\n"
        "- 贴一段答案，让我指出问题并改成 Band 7+\n"
        "- 问我某道题怎么展开、怎么说更自然\n"
        "- 让我根据你当前的题卡追问你\n\n"
        "想从哪儿开始？"
    ),
}

if "tutor_messages" not in st.session_state:
    st.session_state.tutor_messages = [GREETING]

cue_card = st.session_state.get("part2_cue_card", "")
student_answer = st.session_state.get("part2_input", "")

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
    st.divider()
    render_quick_add("AI 老师", "tutor")
    st.divider()
    if st.button("🧹 清空对话", use_container_width=True):
        st.session_state.tutor_messages = [GREETING]
        st.rerun()

context_card = cue_card if use_card else ""
context_answer = student_answer if use_answer else ""


def _send(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    history = list(st.session_state.tutor_messages)
    st.session_state.tutor_messages.append({"role": "user", "content": text})
    with st.spinner("老师正在思考..."):
        reply = ask_tutor(text, history, context_card, context_answer)
    st.session_state.tutor_messages.append({"role": "assistant", "content": reply})


for msg in st.session_state.tutor_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if len(st.session_state.tutor_messages) <= 1:
    st.markdown("**可以这样开始：**")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("3 个自然的 Part 2 开头", use_container_width=True):
            _send(
                "给我 3 个自然的 Part 2 开头句，主题是「描述一个对你很重要的地方」，"
                "每个用一句中文说明适合什么题。"
            )
            st.rerun()
    with col2:
        if st.button("说不满两分钟怎么办", use_container_width=True):
            _send(
                "Part 2 总是说不满两分钟，给我一个能撑满 1 分半到 2 分钟的内容结构，并配一个例子。"
            )
            st.rerun()
    with col3:
        if st.button("根据题卡追问我", use_container_width=True):
            _send(
                "根据我当前的 Part 2 题卡，像考官一样连续追问我 3 个 Part 3 问题，一次只问一个。"
            )
            st.rerun()

if prompt := st.chat_input("问老师任何雅思口语问题…"):
    _send(prompt)
    st.rerun()
