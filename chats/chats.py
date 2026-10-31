# chats/chats.py

import streamlit as st
import copy
import hashlib
from utils import ChatHistory, ExamState, HelpMemory, HelpSession, Part2Card
from utils.asr import transcribe_upload
from utils.Chat import (
    PART3_TOPICS,
    examiner_greeting,
    generate_question_set,
    get_chat_answer,
)
from utils.config import describe_llm
from utils.Notebook import render_jotting_sidebar
from utils.tts import existing_audio, speak

st.set_page_config(page_title="和考官对话", page_icon=":material/chat:", layout="wide")

# 重新开始后，控件 key 必须在下一次 rerun、控件实例化前清掉。
if st.session_state.pop("exam_reset_controls", False):
    for _key in ("exam_part_choice", "exam_use_part2_card", "exam_part3_topic"):
        st.session_state.pop(_key, None)

_state = ExamState.load()
_cue_card = Part2Card.get()


def _generate_questions(part: str, *, topic: str, use_card: bool, recent: list[str]) -> dict:
    return generate_question_set(
        part,
        topic=topic,
        use_card=use_card,
        cue_card=str(_cue_card or ""),
        recent=recent,
    )


with st.sidebar:
    st.subheader("🎙️ 考试设置")
    _part_labels = ["Part 1", "Part 3"]
    _selected_label = (
        "Part 3" if _state.get("selected_part") == ExamState.PART3 else "Part 1"
    )
    _part_choice = st.radio(
        "练习部分",
        _part_labels,
        index=_part_labels.index(_selected_label),
        horizontal=True,
        key="exam_part_choice",
    )
    _chosen_part = ExamState.PART3 if _part_choice == "Part 3" else ExamState.PART1
    if _chosen_part != _state.get("selected_part"):
        ExamState.set_selected_part(_state, _chosen_part)
        ExamState.save(_state)

    if _part_choice == "Part 3":
        _use_card = st.checkbox(
            "参考 Part 2 题卡",
            value=bool(_state.get("use_part2_card", True)),
            disabled=not bool(_cue_card),
            key="exam_use_part2_card",
        )
        _topic_options = ["随机话题"] + PART3_TOPICS
        _saved_topic = _state.get("part3_topic") or "随机话题"
        _topic_index = (
            _topic_options.index(_saved_topic)
            if _saved_topic in _topic_options
            else 0
        )
        _topic = st.selectbox(
            "Part 3 话题",
            _topic_options,
            index=_topic_index,
            disabled=bool(_use_card and _cue_card),
            key="exam_part3_topic",
        )
        _state["use_part2_card"] = bool(_use_card)
        _state["part3_topic"] = _topic
        ExamState.save(_state)

    st.caption(ExamState.status_text(_state))
    st.divider()
    st.subheader("🆘 老师帮帮我！")
    st.caption("老师会进考场旁听，只给引导式提示。")
    if st.button(
        "进入帮助会话", key="exam_help_start", use_container_width=True
    ):
        HelpSession.start("exam")
        st.switch_page(st.session_state["page_help"])
    st.divider()
    last_question = next(
        (
            message.get("content", "")
            for message in reversed(st.session_state.get("messages") or [])
            if message.get("role") == "assistant"
        ),
        "",
    )
    render_jotting_sidebar(
        "严肃话题",
        "chat",
        "考官或参考回答里的好表达，随时存。",
        scene=last_question,
    )

if "edit_mode" not in st.session_state: st.session_state.edit_mode = False
if "edit_index" not in st.session_state: st.session_state.edit_index = -1
if "input_buffer" not in st.session_state: st.session_state.input_buffer = ""
if "messages" not in st.session_state:
    st.session_state["messages"] = ChatHistory.load("exam")

def send_exam_message(user_input: str = ""):
    user_input = str(user_input or st.session_state.get("input_buffer", "")).strip()
    if not user_input: return

    if st.session_state.edit_mode:
        prefix = st.session_state.messages[: st.session_state.edit_index]
        ExamState.rewind_to(prefix)
        st.session_state.messages = prefix
        st.session_state.edit_mode = False
    st.session_state.messages.append({"role": "user", "content": user_input})
    ChatHistory.save("exam", st.session_state.messages)

    state = ExamState.load()
    prelude_step = int(state.get("prelude_step") or 0)
    if prelude_step < 2:
        if prelude_step == 0:
            state["prelude_step"] = 1
            ExamState.save(state)
            reply = "Thank you. What would you like me to call you?"
        else:
            next_item = ExamState.take_next_question(state, _generate_questions)
            state["prelude_step"] = 2
            ExamState.save(state)
            reply = ExamState.prelude_transition(state.get("active_part") or "")
            if next_item:
                reply += " " + next_item["question"]
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "audio": speak(reply),
                "correction": "",
                "suggestion": "",
                "model_answer": "",
                "exam_state": copy.deepcopy(state),
            }
        )
        ChatHistory.save("exam", st.session_state.messages)
        return

    next_item = ExamState.take_next_question(state, _generate_questions)
    ExamState.save(state)
    next_question = (next_item or {}).get("question", "")
    with st.spinner("🧠 考官正在思考..."):
        bot_data, audio_file = get_chat_answer(
            user_input,
            st.session_state.messages,
            next_question=next_question,
        )
        
    st.session_state.messages.append({
        "role": "assistant", "content": bot_data.get("reply", ""), "audio": audio_file,
        "correction": bot_data.get("correction", ""), "suggestion": bot_data.get("suggestion", ""), "model_answer": bot_data.get("model_answer", ""),
        "exam_state": copy.deepcopy(state),
    })
    ChatHistory.save("exam", st.session_state.messages)

chat_container = st.container(height=600)
with chat_container:
    st.title("🎙️ 和考官对话")
    st.caption(f"🤖 当前模型：{describe_llm()}")
    st.caption("🔊 最新一条考官回复会自动播放；旧消息可点播放器重听。")
        
    if not st.session_state["messages"]:
        greeting_text = examiner_greeting()
        st.session_state["messages"] = [{
            "role": "assistant",
            "content": greeting_text,
            "audio": speak(greeting_text),
            "correction": "", "suggestion": "", "model_answer": "",
            "exam_state": copy.deepcopy(ExamState.load()),
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
            st.toast("🎧 已转成文字，确认后点「提交并获取反馈」")
            st.rerun()
        else:
            st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

st.caption("语音会先转成文字，确认后再点「提交并获取反馈」。")

# 重新开始按钮在页面末尾触发，此时输入框已经实例化，不能直接改它的 key；
# 先记一个标记，等下一次 rerun、输入框创建前再清空。
if st.session_state.pop("exam_reset_input", False):
    st.session_state["input_buffer"] = ""

# 输入区样式对齐「讲个故事」：多行输入框 + 通栏主色提交按钮。
with st.container():
    st.text_area(
        "输入你的回答 (支持语音转文字后修改):",
        key="input_buffer",
        height=150,
    )
    if st.button(
        "提交并获取反馈",
        key="exam_submit",
        shortcut="Ctrl+Enter",
        use_container_width=True,
        type="primary",
    ):
        prompt = st.session_state.get("input_buffer", "").strip()
        if prompt:
            st.session_state["exam_reset_input"] = True
            send_exam_message(prompt)
            st.rerun()

st.divider()
st.subheader("📝 实时纠错与地道表达")
last_ai_msg = next((msg for msg in reversed(st.session_state.messages) if msg["role"] == "assistant" and "correction" in msg), None)

if last_ai_msg:
    col1, col2, col3 = st.columns(3)
    with col1: st.error(f"**📌 语法纠错**\n\n{last_ai_msg['correction']}")
    with col2: st.success(f"**🌟 表达润色**\n\n{last_ai_msg['suggestion']}")
    with col3: st.info(f"**🏆 高分参考**\n\n{last_ai_msg.get('model_answer', 'N/A')}")
else:
    st.info("开始对话后，这里会显示你的专属学习笔记。")


def _restart_exam() -> None:
    st.session_state.pop("messages", None)
    st.session_state.edit_mode = False
    st.session_state.edit_index = -1
    st.session_state["exam_reset_input"] = True
    st.session_state.pop("last_audio_id", None)
    st.session_state.pop("chat_autoplayed_audio", None)
    st.session_state["exam_reset_controls"] = True
    ExamState.reset()
    HelpMemory.finish("exam")
    HelpSession.clear("exam")


ChatHistory.render_restart_button(
    "exam",
    _restart_exam,
    label="🔄 重新开始考试",
    title="重新开始考试",
    message="确认清空这场模拟考试记录并重置考试进度？",
)