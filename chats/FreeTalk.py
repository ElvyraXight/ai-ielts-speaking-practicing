# chats/FreeTalk.py

import streamlit as st
import os
import hashlib
from utils.asr import transcribe_upload
from utils.config import describe_llm
from utils.Expressions import render_expression_capture
from utils.FreeTalk import get_freetalk_answer
from utils.Notebook import render_quick_add

st.set_page_config(page_title="AI 自由聊天室", page_icon="☕", layout="wide")

with st.sidebar:
    st.subheader("🎭 自定义聊天对象")
    persona_input = st.text_area(
        "输入对方的身份或性格：",
        value="A friendly American college student who loves sports and music. Uses casual slang.",
        height=150
    )
    if st.button("🔄 应用人设并重启对话", use_container_width=True):
        st.session_state.pop("free_messages", None)
        st.session_state.free_input_buffer = ""
        st.rerun()
    st.divider()
    st.subheader("📓 随手记")
    render_quick_add("自由聊天", "freetalk")
    render_expression_capture("自由聊天", "freetalk", scene=persona_input)

# ================= 初始化状态 =================
if "free_edit_mode" not in st.session_state:
    st.session_state.free_edit_mode = False
if "free_edit_index" not in st.session_state:
    st.session_state.free_edit_index = -1
if "free_input_buffer" not in st.session_state:
    st.session_state.free_input_buffer = ""

# ================= 定义发送逻辑 =================
def send_free_message():
    user_input = st.session_state.free_input_buffer.strip()
    if not user_input:
        return
        
    st.session_state.free_input_buffer = ""
    
    if st.session_state.free_edit_mode:
        st.session_state["free_messages"] = st.session_state["free_messages"][:st.session_state.free_edit_index]
        st.session_state.free_edit_mode = False
        
    st.session_state["free_messages"].append({"role": "user", "content": user_input})
    
    with st.spinner("🧠 朋友正在思考..."):
        bot_data, audio_file = get_freetalk_answer(user_input, st.session_state["free_messages"], persona_input)
        
    st.session_state["free_messages"].append({
        "role": "assistant", "content": bot_data.get("reply", ""), "audio": audio_file,
        "correction": bot_data.get("correction", ""), "suggestion": bot_data.get("suggestion", ""), "model_answer": bot_data.get("model_answer", "")
    })

chat_container = st.container(height=600)
with chat_container:
    st.title("☕  和外国朋友聊聊天")
    st.caption(f"🤖 当前模型：{describe_llm()}")
    st.caption("🔊 最新一条朋友回复会自动播放；旧消息可点播放器重听。")
        
    if "free_messages" not in st.session_state:
        with st.spinner("☕ 朋友正在准备..."):
            intro_data, intro_audio = get_freetalk_answer("", [], persona_input)
        st.session_state["free_messages"] = [{
            "role": "assistant", "content": intro_data.get("reply", "Hey there!"), "audio": intro_audio,
            "correction": "", "suggestion": "", "model_answer": ""
        }]
        
    latest_audio = next(
        (
            m.get("audio")
            for m in reversed(st.session_state["free_messages"])
            if m.get("audio") and os.path.exists(m["audio"])
        ),
        None,
    )

    for i, msg in enumerate(st.session_state["free_messages"]):
        with st.chat_message(msg["role"]):
            col1, col2 = st.columns([9, 1])
            with col1:
                st.write(msg["content"])
                if msg.get("audio") and os.path.exists(msg["audio"]):
                    autoplay = (
                        msg["audio"] == latest_audio
                        and st.session_state.get("free_autoplayed_audio") != latest_audio
                    )
                    if autoplay:
                        st.session_state.free_autoplayed_audio = latest_audio
                    st.audio(msg["audio"], autoplay=autoplay)
            with col2:
                if msg["role"] == "user":
                    if st.button("✏️", key=f"free_edit_btn_{i}", help="修改这句话"):
                        st.session_state.free_edit_mode = True
                        st.session_state.free_edit_index = i
                        st.session_state.free_input_buffer = msg["content"]
                        st.rerun()

    if st.session_state.free_edit_mode:
        st.info("✏️ 正在修改你的发言。")
        if st.button("❌ 取消修改", key="free_cancel_edit"):
            st.session_state.free_edit_mode = False
            st.session_state.free_input_buffer = ""
            st.rerun()

if audio := st.audio_input(
    "🎤 点击麦克风说话",
    key="freetalk_audio",
    help="需要允许浏览器麦克风权限；若持续报错，请改用文字输入。",
):
    audio_bytes = audio.getvalue()
    audio_id = hashlib.md5(audio_bytes).hexdigest()

    if "free_last_audio_id" not in st.session_state:
        st.session_state.free_last_audio_id = None

    if audio_id != st.session_state.free_last_audio_id:
        st.session_state.free_last_audio_id = audio_id
        with st.spinner("🎧 朋友正在听..."):
            user_text = transcribe_upload(audio)

        if user_text and user_text.strip():
            # 只把识别结果放进输入框，让用户确认/修改后再发送；
            # 避免录音组件还在收尾时触发发送和 rerun。
            st.session_state.free_input_buffer = user_text
            st.toast("🎧 已转成文字，确认后点发送")
            st.rerun()
        else:
            st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

with st.expander("麦克风一直报错？改上传录音"):
    uploaded = st.file_uploader(
        "选择一段录音",
        type=["wav", "mp3", "m4a", "webm"],
        key="free_audio_upload",
    )
    if uploaded is not None:
        upload_id = hashlib.md5(uploaded.getvalue()).hexdigest()
        if st.session_state.get("free_audio_upload_id") != upload_id:
            st.session_state.free_audio_upload_id = upload_id
            with st.spinner("🎧 正在识别录音..."):
                uploaded_text = transcribe_upload(uploaded)
            if uploaded_text and uploaded_text.strip():
                st.session_state.free_input_buffer = uploaded_text
                st.toast("🎧 已转成文字，确认后点发送")
                st.rerun()

st.caption("语音会先转成文字，确认后再点发送。")

# ================= 模拟底部输入框 =================
with st.container():
    st.text_area(
        "输入你想说的话:",
        key="free_input_buffer",
        height=80,
        label_visibility="collapsed",
    )
    # 只用 on_click 回调发送：它在控件实例化前执行，能安全清空输入框；
    # 不再给 text_area 加 on_change，避免一次点击触发两次发送。
    st.button(
        "发送 🚀",
        key="send_freetalk",
        on_click=send_free_message,
        shortcut="Ctrl+Enter",
        use_container_width=True,
        type="primary",
    )

st.divider()
st.subheader("📝 聊天反馈与地道表达")
last_ai_msg = next((msg for msg in reversed(st.session_state["free_messages"]) if msg["role"] == "assistant" and "correction" in msg), None)

if last_ai_msg:
    col1, col2, col3 = st.columns(3)
    with col1: st.error(f"**📌 语法纠错**\n\n{last_ai_msg['correction']}")
    with col2: st.success(f"**🌟 表达润色**\n\n{last_ai_msg['suggestion']}")
    with col3: st.info(f"**🤙 地道俚语/高级表达**\n\n{last_ai_msg.get('model_answer', 'N/A')}")
else:
    st.info("随便说点什么吧，朋友会给你反馈的！")