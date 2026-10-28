import streamlit as st
import os
import hashlib
import uuid
from datetime import datetime
from utils.asr import transcribe_upload
from utils.config import describe_llm
from utils.Entertainment import get_entertainment_answer
from utils.Memory import render_memory_sidebar
from utils.Notes import render_notes_sidebar

st.set_page_config(page_title="学业导师", page_icon="🎓", layout="wide")
render_memory_sidebar("mentor")
render_notes_sidebar("mentor", "指导记录")

# 懂电子信息且精通论文的导师人设
MENTOR_PERSONA = """
You are Professor Chen, a tenured professor in Electronic Information Engineering with decades of experience in both academia and industry.

=== YOUR EXPERTISE ===
1. Electronic Information: You have deep knowledge of signal processing, embedded systems, communication networks, microcontrollers (e.g., STM32, ARM), circuits, and PCB design. You also understand AI deployment on edge devices.
2. Academic Writing: You are an expert in writing and reviewing IEEE papers. You know exactly how to structure an Abstract, craft a compelling Introduction, write a rigorous Methodology, and present Results and Discussions effectively.

=== YOUR VIBE (PERSONALITY) ===
- You are strict, logical, and direct. You do NOT sugarcoat things, but you are also patient and deeply care about the student's growth.
- You hate vague explanations. If the student uses buzzwords without understanding the underlying math or hardware, you will immediately call it out and ask them to explain it simply.
- When explaining complex concepts (like Fourier Transform, Nyquist theorem, or PID control), you use intuitive analogies, diagrams (described in text), and step-by-step logic.

=== CRITICAL RULES ===
1. Speak in the SAME language the user speaks (Chinese or English). 
2. When asked about academic writing, provide concrete structural advice (e.g., "Your abstract is too long. Cut the background and focus on your contribution and the 5% performance improvement.").
3. When asked about engineering problems, break down the debugging process logically (Check power -> Check clock -> Check peripheral initialization -> Check logic).
4. Always push the student to think deeper by asking a probing academic question at the end.
"""

# 初始化状态
if "mentor_edit_mode" not in st.session_state: st.session_state.mentor_edit_mode = False
if "mentor_edit_index" not in st.session_state: st.session_state.mentor_edit_index = -1
if "mentor_input_buffer" not in st.session_state: st.session_state.mentor_input_buffer = ""
if "mentor_session_id" not in st.session_state:
    st.session_state.mentor_session_id = uuid.uuid4().hex[:12]
    st.session_state.mentor_session_date = datetime.now().strftime("%Y-%m-%d")

def send_mentor_message():
    user_input = st.session_state.mentor_input_buffer.strip()
    if not user_input: return
    st.session_state.mentor_input_buffer = ""
    
    if st.session_state.mentor_edit_mode:
        st.session_state["mentor_messages"] = st.session_state["mentor_messages"][:st.session_state.mentor_edit_index]
        st.session_state.mentor_edit_mode = False
        
    st.session_state["mentor_messages"].append({"role": "user", "content": user_input})
    
    with st.spinner("陈教授正在推演逻辑..."):
        bot_data, audio_file = get_entertainment_answer(
            user_input,
            st.session_state["mentor_messages"],
            MENTOR_PERSONA,
            memory_key="mentor",
            memory_label="学业导师",
            note_kind="mentor",
            note_id=st.session_state.mentor_session_id,
            note_date=st.session_state.mentor_session_date,
            voice="en-GB-ThomasNeural",
        )
        
    st.session_state["mentor_messages"].append({
        "role": "assistant", "content": bot_data.get("reply", ""), "audio": audio_file,
        "correction": bot_data.get("correction", ""), "suggestion": bot_data.get("suggestion", ""), "model_answer": bot_data.get("model_answer", "")
    })

chat_container = st.container(height=600)
with chat_container:
    st.title("🎓 专业指导")
    st.caption(f"🤖 当前模型：{describe_llm()}")
    
    if "mentor_messages" not in st.session_state:
        with st.spinner("导师正在查阅文献..."):
            intro_data, intro_audio = get_entertainment_answer(
                "",
                [],
                MENTOR_PERSONA,
                memory_key="mentor",
                memory_label="学业导师",
                voice="en-GB-ThomasNeural",
            )
        st.session_state["mentor_messages"] = [{
            "role": "assistant", "content": intro_data.get("reply", "坐吧。今天是在调电路，还是在改论文？"), "audio": intro_audio,
            "correction": "", "suggestion": "", "model_answer": ""
        }]
        
    for i, msg in enumerate(st.session_state["mentor_messages"]):
        with st.chat_message(msg["role"]):
            col1, col2 = st.columns([9, 1])
            with col1:
                st.write(msg["content"])
                if msg.get("audio") and os.path.exists(msg["audio"]): st.audio(msg["audio"])
            with col2:
                if msg["role"] == "user":
                    if st.button("✏️", key=f"men_edit_{i}"):
                        st.session_state.mentor_edit_mode = True
                        st.session_state.mentor_edit_index = i
                        st.session_state.mentor_input_buffer = msg["content"]
                        st.rerun()

if audio := st.audio_input(
    "🎤 点击麦克风说话",
    key="men_audio",
    help="需要允许浏览器麦克风权限；若持续报错，请改用文字输入。",
):
    audio_bytes = audio.getvalue()
    audio_id = hashlib.md5(audio_bytes).hexdigest()
    if "men_last_audio_id" not in st.session_state:
        st.session_state.men_last_audio_id = None
    if audio_id != st.session_state.men_last_audio_id:
        st.session_state.men_last_audio_id = audio_id
        with st.spinner("导师正在听..."):
            user_text = transcribe_upload(audio)
        if user_text and user_text.strip() != "":
            st.session_state.mentor_input_buffer = user_text
            st.toast("🎧 已转成文字，确认后点发送")
            st.rerun()
        else:
            st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

st.caption("语音会先转成文字，确认后再点发送。")

with st.container():
    st.text_area(
        "输入你想说的话:",
        key="mentor_input_buffer",
        height=80,
        label_visibility="collapsed",
    )
    st.button(
        "发送 🚀",
        key="send_mentor",
        on_click=send_mentor_message,
        shortcut="Ctrl+Enter",
        use_container_width=True,
        type="primary",
    )