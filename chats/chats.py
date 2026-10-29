# chats/chats.py

import streamlit as st
import hashlib
from utils import ChatHistory
from utils.asr import transcribe_upload
from utils.Chat import get_chat_answer
from utils.config import describe_llm
from utils.Notebook import render_quick_add
from utils.tts import existing_audio

st.set_page_config(page_title="AI 雅思模拟考", page_icon=":material/chat:", layout="wide")

with st.sidebar:
    st.subheader("📓 随手记")
    st.caption("考官或参考回答里的好表达，随时存。")
    last_question = next(
        (
            message.get("content", "")
            for message in reversed(st.session_state.get("messages") or [])
            if message.get("role") == "assistant"
        ),
        "",
    )
    render_quick_add("严肃话题", "chat", scene=last_question)

if "edit_mode" not in st.session_state: st.session_state.edit_mode = False
if "edit_index" not in st.session_state: st.session_state.edit_index = -1
if "input_buffer" not in st.session_state: st.session_state.input_buffer = ""
if "messages" not in st.session_state:
    st.session_state["messages"] = ChatHistory.load("exam")

def send_exam_message():
    user_input = st.session_state.input_buffer.strip()
    if not user_input: return
    st.session_state.input_buffer = ""
    
    if st.session_state.edit_mode:
        st.session_state.messages = st.session_state.messages[:st.session_state.edit_index]
        st.session_state.edit_mode = False
        
    st.session_state.messages.append({"role": "user", "content": user_input})
    ChatHistory.save("exam", st.session_state.messages)
    
    with st.spinner("🧠 考官正在思考..."):
        bot_data, audio_file = get_chat_answer(user_input, st.session_state.messages)
        
    st.session_state.messages.append({
        "role": "assistant", "content": bot_data.get("reply", ""), "audio": audio_file,
        "correction": bot_data.get("correction", ""), "suggestion": bot_data.get("suggestion", ""), "model_answer": bot_data.get("model_answer", "")
    })
    ChatHistory.save("exam", st.session_state.messages)

chat_container = st.container(height=600)
with chat_container:
    st.title("🎙️ AI 雅思口语全真模拟")
    st.caption(f"🤖 当前模型：{describe_llm()}")
    st.caption("🔊 最新一条考官回复会自动播放；旧消息可点播放器重听。")
        
    if not st.session_state["messages"]:
        with st.spinner("🎙️ 考官正在准备入场..."):
            intro_data, intro_audio = get_chat_answer("", [])
        st.session_state["messages"] = [{
            "role": "assistant", 
            "content": intro_data.get("reply", "Hello! Could you tell me your full name?"), 
            "audio": intro_audio,
            "correction": "", "suggestion": "", "model_answer": ""
        }]
        ChatHistory.save("exam", st.session_state["messages"])
        
    latest_audio = next(
        (
            audio
            for m in reversed(st.session_state.messages)
            if (audio := existing_audio(m.get("audio")))
        ),
        None,
    )

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            col1, col2 = st.columns([9, 1])
            with col1:
                st.write(msg["content"])
                audio = existing_audio(msg.get("audio"))
                if audio:
                    autoplay = (
                        audio == latest_audio
                        and st.session_state.get("chat_autoplayed_audio") != audio
                    )
                    if autoplay:
                        st.session_state.chat_autoplayed_audio = audio
                    st.audio(audio, autoplay=autoplay)
            with col2:
                if msg["role"] == "user":
                    if st.button("✏️", key=f"edit_btn_{i}", help="修改这句话"):
                        st.session_state.edit_mode = True
                        st.session_state.edit_index = i
                        st.session_state.input_buffer = msg["content"]
                        st.rerun()

    if st.session_state.edit_mode:
        st.info(f"✏️ 正在修改你的回答。")
        if st.button("❌ 取消修改"):
            st.session_state.edit_mode = False
            st.session_state.input_buffer = ""
            st.rerun()

if audio := st.audio_input(
    "🎤 点击麦克风开始录音",
    key="exam_audio",
    help="需要允许浏览器麦克风权限；若持续报错，请改用文字输入。",
):
    audio_bytes = audio.getvalue()
    audio_id = hashlib.md5(audio_bytes).hexdigest()

    if "last_audio_id" not in st.session_state:
        st.session_state.last_audio_id = None
    if audio_id != st.session_state.last_audio_id:
        st.session_state.last_audio_id = audio_id
        with st.spinner("🎧 考官正在听..."):
            user_text = transcribe_upload(audio)

        if user_text and user_text.strip():
            # 先放进输入框让用户确认，避免录音组件收尾时自动发送导致重复
            st.session_state.input_buffer = user_text
            st.toast("🎧 已转成文字，确认后点发送")
            st.rerun()
        else:
            st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

st.caption("语音会先转成文字，确认后再点发送。")

with st.container():
    st.text_area(
        "输入你的回答:",
        key="input_buffer",
        height=80,
        label_visibility="collapsed",
    )
    # on_click 在控件实例化前执行，可安全清空输入框；
    # text_area 不再绑定 on_change，避免一次点击发送两遍。
    st.button(
        "发送 🚀",
        key="send_exam",
        on_click=send_exam_message,
        shortcut="Ctrl+Enter",
        use_container_width=True,
        type="primary",
    )

st.divider()
st.subheader("📝 实时纠错与地道表达")
last_ai_msg = next((msg for msg in reversed(st.session_state.messages) if msg["role"] == "assistant" and "correction" in msg), None)

if last_ai_msg:
    col1, col2, col3 = st.columns(3)
    with col1: st.error(f"**📌 语法纠错**\n\n{last_ai_msg['correction']}")
    with col2: st.success(f"**🌟 基于你的回答润色**\n\n{last_ai_msg['suggestion']}")
    with col3: st.info(f"**🏆 考官满分参考**\n\n{last_ai_msg.get('model_answer', 'N/A')}")
else:
    st.info("开始对话后，这里会显示你的专属学习笔记。")


def _restart_exam() -> None:
    st.session_state.pop("messages", None)
    st.session_state.edit_mode = False
    st.session_state.edit_index = -1
    st.session_state.input_buffer = ""
    st.session_state.pop("last_audio_id", None)
    st.session_state.pop("chat_autoplayed_audio", None)


ChatHistory.render_restart_button("exam", _restart_exam)