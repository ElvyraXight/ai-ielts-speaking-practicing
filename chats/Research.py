# chats/Research.py

"""查资料：最普通的对话式 AI，没有记忆、语音、计划等额外功能。"""

import streamlit as st

from utils import ChatHistory
from utils.config import current_selection, describe_llm
from utils.conversation import format_history
from utils.llm import call_llm_json
from utils.Notebook import render_jotting_sidebar

st.set_page_config(page_title="查资料", page_icon="🔎", layout="wide")

KEY = "research"

with st.sidebar:
    render_jotting_sidebar("查资料", KEY, "查到的表达或知识点，随时存。")

st.title("🔎 查资料")
st.caption(f"🤖 当前模型：{describe_llm()}")
st.caption("普通对话 AI：直接问，按你的语言回答。")

if "research_messages" not in st.session_state:
    st.session_state["research_messages"] = ChatHistory.load(KEY)
messages = st.session_state["research_messages"]

if not messages:
    st.info("想查什么？直接发第一条消息。")

for message in messages:
    with st.chat_message(message.get("role", "assistant")):
        st.markdown(message.get("content", ""))

if prompt := st.chat_input("想问什么？"):
    messages.append({"role": "user", "content": prompt})
    ChatHistory.save(KEY, messages)
    with st.chat_message("user"):
        st.markdown(prompt)

    history = format_history(
        messages[:-1], limit=12, assistant_label="Assistant", user_label="User"
    )
    llm_prompt = f"""You are a helpful, accurate general assistant.
Answer in the same language as the user. Be direct and concise.
If you do not know something, say so; never pretend to have looked it up.

CONVERSATION SO FAR
{history or "(none)"}

USER
{prompt}

Output JSON only: {{"reply": "..."}}"""

    provider, model = current_selection()
    try:
        with st.spinner("查一下…"):
            data = call_llm_json(
                llm_prompt,
                temperature=0.5,
                num_predict=900,
                fallback={},
                timeout=60,
                provider=provider,
                model=model,
            )
    except Exception:
        data = {}

    reply = str((data or {}).get("reply") or "").strip() or "没接上，再试一次。"
    messages.append({"role": "assistant", "content": reply})
    ChatHistory.save(KEY, messages)
    with st.chat_message("assistant"):
        st.markdown(reply)


def _restart_research() -> None:
    st.session_state.pop("research_messages", None)


ChatHistory.render_restart_button(
    KEY,
    _restart_research,
    message="确认清空查资料的对话记录？",
)
