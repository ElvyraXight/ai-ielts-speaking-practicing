import hashlib
import os

import streamlit as st

from utils.asr import transcribe_upload
from utils.config import describe_llm
from utils.Entertainment import get_entertainment_answer
from utils.Memory import render_memory_sidebar

st.set_page_config(page_title="AI闲聊", page_icon="🎩", layout="wide")
render_memory_sidebar("companion")

# 温柔、绅士、风趣、知识渊博的聊天对象
CHAT_PERSONA = """
You are "AI闲聊", a warm, gentlemanly, witty and deeply knowledgeable conversational partner.

Your style:
1. Gentle and polite. Never condescending, never judgmental, never mocking.
2. Dry, light humour. Playful, but never at the user's expense.
3. Well-read in literature, history, science, philosophy, films and everyday life.
   You enjoy connecting ideas and offering a relevant anecdote, book or fact —
   but briefly, and only when it fits.
4. Curious. Ask one thoughtful follow-up question at the end, not a list of questions.
5. Concise. At most 2-4 short paragraphs. Do not lecture or dump information.
6. If the user seems vulnerable or tired, soften the humour and respond with care.
7. Never mention being an AI, having a memory, or keeping notes. Just talk like a person.
8. Reply in English. (The app translates to Chinese when the user writes Chinese.)
"""

# 初始化状态
if "friend_edit_mode" not in st.session_state:
    st.session_state.friend_edit_mode = False
if "friend_edit_index" not in st.session_state:
    st.session_state.friend_edit_index = -1
if "friend_input_buffer" not in st.session_state:
    st.session_state.friend_input_buffer = ""


def send_friend_message():
    user_input = st.session_state.friend_input_buffer.strip()
    if not user_input:
        return
    st.session_state.friend_input_buffer = ""

    if st.session_state.friend_edit_mode:
        st.session_state["friend_messages"] = st.session_state["friend_messages"][
            : st.session_state.friend_edit_index
        ]
        st.session_state.friend_edit_mode = False

    st.session_state["friend_messages"].append(
        {"role": "user", "content": user_input}
    )

    with st.spinner("AI 正在斟酌措辞..."):
        bot_data, audio_file = get_entertainment_answer(
            user_input,
            st.session_state["friend_messages"],
            CHAT_PERSONA,
            memory_key="companion",
            memory_label="AI闲聊",
            voice="en-GB-RyanNeural",
        )

    st.session_state["friend_messages"].append(
        {
            "role": "assistant",
            "content": bot_data.get("reply", ""),
            "audio": audio_file,
            "correction": bot_data.get("correction", ""),
            "suggestion": bot_data.get("suggestion", ""),
            "model_answer": bot_data.get("model_answer", ""),
        }
    )


chat_container = st.container(height=600)
with chat_container:
    st.title("🎩 AI闲聊")
    st.caption("温柔、绅士、风趣，也读过很多书。")
    st.caption(f"🤖 当前模型：{describe_llm()}")

    if "friend_messages" not in st.session_state:
        with st.spinner("AI 正在整理衣襟..."):
            intro_data, intro_audio = get_entertainment_answer(
                "",
                [],
                CHAT_PERSONA,
                memory_key="companion",
                memory_label="AI闲聊",
                voice="en-GB-RyanNeural",
            )
        st.session_state["friend_messages"] = [
            {
                "role": "assistant",
                "content": intro_data.get(
                    "reply",
                    "Good evening. Come in, take your time — what has been on your mind lately?",
                ),
                "audio": intro_audio,
                "correction": "",
                "suggestion": "",
                "model_answer": "",
            }
        ]

    for i, msg in enumerate(st.session_state["friend_messages"]):
        with st.chat_message(msg["role"]):
            col1, col2 = st.columns([9, 1])
            with col1:
                st.write(msg["content"])
                if msg.get("audio") and os.path.exists(msg["audio"]):
                    st.audio(msg["audio"])
            with col2:
                if msg["role"] == "user":
                    if st.button("✏️", key=f"friend_edit_{i}"):
                        st.session_state.friend_edit_mode = True
                        st.session_state.friend_edit_index = i
                        st.session_state.friend_input_buffer = msg["content"]
                        st.rerun()

if audio := st.audio_input(
    "🎤 点击麦克风说话",
    key="friend_audio",
    help="需要允许浏览器麦克风权限；若持续报错，请改用文字输入。",
):
    audio_bytes = audio.getvalue()
    audio_id = hashlib.md5(audio_bytes).hexdigest()
    if "friend_last_audio_id" not in st.session_state:
        st.session_state.friend_last_audio_id = None
    if audio_id != st.session_state.friend_last_audio_id:
        st.session_state.friend_last_audio_id = audio_id
        with st.spinner("正在听..."):
            user_text = transcribe_upload(audio)
        if user_text and user_text.strip() != "":
            st.session_state.friend_input_buffer = user_text
            st.toast("🎧 已转成文字，确认后点发送")
            st.rerun()
        else:
            st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

st.caption("语音会先转成文字，确认后再点发送。")

with st.container():
    st.text_area(
        "输入你想说的话:",
        key="friend_input_buffer",
        height=80,
        label_visibility="collapsed",
    )
    st.button(
        "发送 🚀",
        key="send_friend",
        on_click=send_friend_message,
        shortcut="Ctrl+Enter",
        use_container_width=True,
        type="primary",
    )
