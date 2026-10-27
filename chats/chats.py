# chats/chats.py

import streamlit as st
import os
import hashlib
from utils.Chat import get_chat_anwser, transcribe_audio
from utils.Notebook import render_quick_add
from utils.llm import describe_llm

st.set_page_config(page_title="AI 雅思模拟考", page_icon=":material/chat:", layout="wide")
# 注入 CSS 改变按钮颜色
st.markdown("""
<style>
/* 修改 Primary 按钮（发送键）的颜色为浅蓝紫 */
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

AUDIO_DIR = "audio_records"
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR)

with st.sidebar:
    st.subheader("📓 随手记")
    st.caption("考官或参考回答里的好表达，随时存。")
    render_quick_add("严肃话题", "chat")

if 'message_count' not in st.session_state: st.session_state.message_count = 0
if "edit_mode" not in st.session_state: st.session_state.edit_mode = False
if "edit_index" not in st.session_state: st.session_state.edit_index = -1
if "input_buffer" not in st.session_state: st.session_state.input_buffer = ""

def send_exam_message():
    user_input = st.session_state.input_buffer.strip()
    if not user_input: return
    st.session_state.input_buffer = ""
    
    if st.session_state.edit_mode:
        st.session_state.messages = st.session_state.messages[:st.session_state.edit_index]
        st.session_state.edit_mode = False
        
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    with st.spinner("🧠 考官正在思考..."):
        bot_data, audio_file = get_chat_anwser(user_input, st.session_state.message_count, st.session_state.messages)
        
    st.session_state.messages.append({
        "role": "assistant", "content": bot_data.get("reply", ""), "audio": audio_file,
        "correction": bot_data.get("correction", ""), "suggestion": bot_data.get("suggestion", ""), "model_answer": bot_data.get("model_answer", "")
    })
    st.session_state.message_count += 1

chat_container = st.container(height=600)
with chat_container:
    st.title("🎙️ AI 雅思口语全真模拟")
    st.caption(f"🤖 当前模型：{describe_llm()}")
        
    if "messages" not in st.session_state:
        with st.spinner("🎙️ 考官正在准备入场..."):
            intro_data, intro_audio = get_chat_anwser("", 0, [])
        st.session_state["messages"] = [{
            "role": "assistant", 
            "content": intro_data.get("reply", "Hello! Could you tell me your full name?"), 
            "audio": intro_audio,
            "correction": "", "suggestion": "", "model_answer": ""
        }]
        
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            col1, col2 = st.columns([9, 1])
            with col1:
                st.write(msg["content"])
                if msg.get("audio") and os.path.exists(msg["audio"]):
                    st.audio(msg["audio"], autoplay=False)
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
            
    if audio := st.audio_input("🎤 点击麦克风开始录音"):
        audio_bytes = audio.getvalue()
        audio_id = hashlib.md5(audio_bytes).hexdigest()
        
        if "last_audio_id" not in st.session_state: st.session_state.last_audio_id = None
        if audio_id != st.session_state.last_audio_id:
            st.session_state.last_audio_id = audio_id
            with st.spinner("🎧 考官正在听..."):
                user_text = transcribe_audio(audio)
            
            if user_text and user_text.strip() != "":
                st.session_state.input_buffer = user_text
                send_exam_message() 
                st.rerun()

with st.container():
    st.text_area("输入你的回答:", key="input_buffer", height=80, label_visibility="collapsed", on_change=send_exam_message)
    if st.button("发送 🚀", on_click=send_exam_message, use_container_width=True, type="primary"):
        st.rerun()

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