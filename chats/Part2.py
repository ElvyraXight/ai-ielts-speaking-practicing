# chats/Part2.py

import hashlib

import streamlit as st

from utils.asr import transcribe_upload
from utils import HelpMemory, HelpSession, Part2Card
from utils.config import describe_llm
from utils.Notebook import render_jotting_sidebar
from utils.Part2 import evaluate_part2_story, generate_cue_card
from utils.tts import existing_audio, speak

st.set_page_config(page_title="Part 2 讲故事", page_icon="🃏", layout="wide")

st.title("🃏 Part 2: 讲个小故事")
st.caption("你将获得一张 Cue Card。请准备1分钟，然后开始讲述一个 1.5-2 分钟的故事。你可以对着麦克风说，也可以直接打字。")
st.caption(f"🤖 当前模型：{describe_llm()}")

# 题卡落盘：刷新 / 重开软件后还是同一张，只有主动「换一道题」才变。
cue_card = Part2Card.get()
if cue_card:
    cue_card = Part2Card.get_or_create(generate_cue_card)
else:
    with st.spinner("正在为你抽取 Cue Card..."):
        cue_card = Part2Card.get_or_create(generate_cue_card)

# ================= 初始化状态 =================
# 先恢复答案草稿：下面的侧栏按钮要把当前输入抄给帮助页，别让 widget 键的清空
# 把落盘的草稿又覆盖掉。
if "part2_evaluation" not in st.session_state:
    st.session_state.part2_evaluation = None
saved_answer = Part2Card.load_answer()
if "part2_input" not in st.session_state:
    st.session_state.part2_input = saved_answer
elif not str(st.session_state.get("part2_input") or "").strip() and saved_answer:
    # 从别的页面回来时 widget 键会被 Streamlit 清掉，用落盘的草稿恢复。
    st.session_state.part2_input = saved_answer
if "part2_answer" not in st.session_state:
    st.session_state.part2_answer = ""

with st.sidebar:
    st.subheader("🆘 老师帮帮我！")
    st.caption("老师会看当前题卡和你的答案，只给引导式提示。")
    if st.button(
        "进入帮助会话", key="p2_help_start", use_container_width=True
    ):
        # 帮助页是下一次脚本运行，`part2_input` 这个 widget 键在那一轮就会被
        # Streamlit 清掉；先把答案抄进普通键并落盘，老师才看得到、回来也还在。
        answer_now = str(st.session_state.get("part2_input") or "").strip()
        st.session_state["part2_answer"] = answer_now
        Part2Card.save_answer(answer_now)
        HelpSession.start("part2")
        st.switch_page(st.session_state["page_help"])
    st.divider()
    render_jotting_sidebar(
        "讲个故事",
        "p2",
        "遇到好词好句，先存进笔记本。",
        scene=cue_card,
        scene_full=True,
    )

# ================= 展示 Cue Card =================
# 题卡是纯文本，转成 Markdown 硬换行，避免 Streamlit 把同一行挤成一段
card_markdown = cue_card.replace("\n", "  \n")
st.info(f"**📌 你的题目：**\n\n{card_markdown}")

if st.button("🔄 换一道题", use_container_width=False):
    with st.spinner("AI 正在构思新题目..."):
        cue_card = Part2Card.save(generate_cue_card())
    st.session_state.part2_evaluation = None
    st.session_state.part2_input = ""
    st.session_state.part2_answer = ""
    Part2Card.save_answer("")
    HelpMemory.finish("part2")
    HelpSession.clear("part2")
    st.rerun()

st.divider()

# ================= 用户输入区 =================
st.subheader("🎙️ 你的故事")
if audio := st.audio_input("点击麦克风开始讲故事 (会自动转成文字)"):
    audio_bytes = audio.getvalue()
    audio_id = hashlib.md5(audio_bytes).hexdigest()
    if "p2_last_audio_id" not in st.session_state: st.session_state.p2_last_audio_id = None
    if audio_id != st.session_state.p2_last_audio_id:
        st.session_state.p2_last_audio_id = audio_id
        with st.spinner("🎧 正在识别你的语音..."):
            user_text = transcribe_upload(audio)
            if user_text:
                # 把语音识别的内容追加到输入框
                st.session_state.part2_input += f" {user_text}"
                Part2Card.save_answer(st.session_state.part2_input)
            else:
                st.toast("🎧 没有识别出内容，请再说一次或改用文字输入")

def _save_draft():
    """把输入框里的答案草稿落盘；刷新、重开软件后还能读回来。"""
    Part2Card.save_answer(st.session_state.get("part2_input") or "")


def submit_story():
    user_story = st.session_state.part2_input.strip()
    if not user_story: return
    with st.spinner("老师正在详细分析你的故事（语法纠错、改写答案与参考范文）..."):
        st.session_state.part2_evaluation = evaluate_part2_story(user_story, cue_card)

with st.container():
    # 绑定 key 到 session_state，方便语音输入往里塞字
    st.text_area(
        "输入你的故事 (支持语音转文字后修改):",
        key="part2_input",
        height=150,
        on_change=_save_draft,
    )
    # widget 键在跨页那一轮会被清掉，这里同步一份普通键给「老师帮帮我」；
    # 草稿本身已经由 on_change / 语音转写写进 data/part2_card.json。
    st.session_state["part2_answer"] = st.session_state["part2_input"].strip()
    # on_click 回调在控件实例化前执行，本身就会触发一次完整重跑，不需要再 st.rerun()
    st.button(
        "提交并获取反馈",
        key="submit_part2",
        on_click=submit_story,
        shortcut="Ctrl+Enter",
        use_container_width=True,
        type="primary",
    )

# ================= 反馈展示区 =================
if st.session_state.part2_evaluation:
    st.divider()
    st.subheader("📝 老师的深度拆解")
    
    eval_data = st.session_state.part2_evaluation
    
    col1, col2 = st.columns(2)
    with col1:
        st.error(f"**📌 语法与时态纠错**\n\n{eval_data.get('correction') or '（暂无）'}")
    with col2:
        revised = eval_data.get("suggestion") or "（暂无）"
        st.success(f"**🌟 修改后的答案 (Band 7+)**\n\n{revised}")
        
    # 满分口语范文框
    model_answer = eval_data.get("model_answer") or ""
    st.info(f"**🏆 参考范文 (Band 8+ 口语长回答)**\n\n{model_answer or '（暂无）'}")
    
    # 语音播放功能（仅在范文正常生成时显示，避免朗读失败提示）
    if model_answer and not model_answer.startswith("（"):
        if st.button("🔊 听一听这份高分参考", use_container_width=True):
            with st.spinner("正在生成语音..."):
                audio_path = existing_audio(speak(model_answer, prefix="p2_model"))
            if audio_path:
                st.audio(audio_path, autoplay=True)
            else:
                st.warning("语音生成失败，请检查网络后重试。")