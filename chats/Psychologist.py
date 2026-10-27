import streamlit as st
import os
import hashlib
from utils.Entertainment import get_entertainment_answer, transcribe_audio
from utils.llm import describe_llm
from utils.Memory import render_memory_sidebar

st.set_page_config(page_title="温润心理咨询师", page_icon="🕊️", layout="wide")
render_memory_sidebar("psychologist", "咨询师的记忆")
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

# 温润且极专业的心理咨询师人设
PSY_PERSONA = """
You are Dr. Lin, a highly professional psychological counselor with a Ph.D. in Clinical Psychology and 15 years of experience. 

=== YOUR VIBE (PERSONALITY) ===
- Your tone is extremely warm, gentle, and soothing—like soft cotton. You provide a completely safe, non-judgmental space.
- You make the user feel heard and validated before anything else. You often use phrases like "I hear you," "It makes complete sense that you feel this way," or "Take your time."
- You speak slowly and thoughtfully. You never rush the user or immediately jump to solutions.

=== YOUR PROFESSIONAL TOOLKIT ===
- Despite your gentle tone, you are highly analytical. You use professional frameworks (like CBT, Humanistic therapy, or Somatic grounding) seamlessly.
- When the user is anxious, you gently guide them with grounding exercises (e.g., deep breathing).
- When the user has irrational thoughts (like "I'm a total failure"), you gently point out the cognitive distortion (e.g., "It sounds like your mind is playing an 'all-or-nothing' trick on you.") and help them reframe it.
- Use the Socratic method: ask gentle, open-ended questions to help them discover their own strengths.

=== CRITICAL RULES ===
1. Speak in the SAME language the user uses (Chinese or English). If Chinese, use a very warm and poetic but professional tone.
2. NEVER give superficial advice like "Just relax" or "Don't be sad". Validate first, then intervene.
3. Always end your response with a gentle, supportive question that invites deeper reflection.
"""

# 初始化状态
if "psy_edit_mode" not in st.session_state: st.session_state.psy_edit_mode = False
if "psy_edit_index" not in st.session_state: st.session_state.psy_edit_index = -1
if "psy_input_buffer" not in st.session_state: st.session_state.psy_input_buffer = ""

def send_psy_message():
    user_input = st.session_state.psy_input_buffer.strip()
    if not user_input: return
    st.session_state.psy_input_buffer = ""
    
    if st.session_state.psy_edit_mode:
        st.session_state["psy_messages"] = st.session_state["psy_messages"][:st.session_state.psy_edit_index]
        st.session_state.psy_edit_mode = False
        
    st.session_state["psy_messages"].append({"role": "user", "content": user_input})
    
    with st.spinner("咨询师正在温柔地倾听..."):
        bot_data, audio_file = get_entertainment_answer(
            user_input,
            st.session_state["psy_messages"],
            PSY_PERSONA,
            memory_key="psychologist",
            memory_label="心理咨询师",
        )
        
    st.session_state["psy_messages"].append({
        "role": "assistant", "content": bot_data.get("reply", ""), "audio": audio_file,
        "correction": bot_data.get("correction", ""), "suggestion": bot_data.get("suggestion", ""), "model_answer": bot_data.get("model_answer", "")
    })

chat_container = st.container(height=600)
with chat_container:
    st.title("🕊️ 心理咨询室")
    st.caption(f"🤖 当前模型：{describe_llm()}")
    
    if "psy_messages" not in st.session_state:
        with st.spinner("咨询师正在整理沙发..."):
            intro_data, intro_audio = get_entertainment_answer(
                "",
                [],
                PSY_PERSONA,
                memory_key="psychologist",
                memory_label="心理咨询师",
            )
        st.session_state["psy_messages"] = [{
            "role": "assistant", "content": intro_data.get("reply", "你好，我是林医生。请坐，今天想聊点什么？"), "audio": intro_audio,
            "correction": "", "suggestion": "", "model_answer": ""
        }]
        
    for i, msg in enumerate(st.session_state["psy_messages"]):
        with st.chat_message(msg["role"]):
            col1, col2 = st.columns([9, 1])
            with col1:
                st.write(msg["content"])
                if msg.get("audio") and os.path.exists(msg["audio"]): st.audio(msg["audio"])
            with col2:
                if msg["role"] == "user":
                    if st.button("✏️", key=f"psy_edit_{i}"):
                        st.session_state.psy_edit_mode = True
                        st.session_state.psy_edit_index = i
                        st.session_state.psy_input_buffer = msg["content"]
                        st.rerun()

if audio := st.audio_input(
    "🎤 点击麦克风说话",
    key="psy_audio",
    help="需要允许浏览器麦克风权限；若持续报错，请改用文字输入。",
):
    audio_bytes = audio.getvalue()
    audio_id = hashlib.md5(audio_bytes).hexdigest()
    if "psy_last_audio_id" not in st.session_state:
        st.session_state.psy_last_audio_id = None
    if audio_id != st.session_state.psy_last_audio_id:
        st.session_state.psy_last_audio_id = audio_id
        with st.spinner("正在倾听..."):
            user_text = transcribe_audio(audio)
        if user_text and user_text.strip() != "":
            st.session_state.psy_input_buffer = user_text
            st.toast("🎧 已转成文字，确认后点发送")
            st.rerun()

st.caption("语音会先转成文字，确认后再点发送。")

with st.container():
    st.text_area(
        "输入你想说的话:",
        key="psy_input_buffer",
        height=80,
        label_visibility="collapsed",
    )
    st.button(
        "发送 🚀",
        on_click=send_psy_message,
        use_container_width=True,
        type="primary",
    )