import requests
import streamlit as st

from utils.Part2 import DEEPSEEK_API_KEY, current_selection, describe_llm


@st.cache_data(ttl=60, show_spinner=False)
def _ollama_models() -> list[str]:
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        response.raise_for_status()
        names = [
            item.get("name")
            for item in response.json().get("models", [])
            if item.get("name")
        ]
        return sorted(dict.fromkeys(names)) or ["qwen2.5:7b"]
    except Exception:
        return ["qwen2.5:7b", "deepseek-coder-v2:latest"]


def render_model_switcher() -> None:
    options: dict[str, tuple[str, str]] = {}
    if DEEPSEEK_API_KEY:
        options["DeepSeek · deepseek-flash"] = ("deepseek", "deepseek-flash")
        options["DeepSeek · deepseek-v4-pro"] = ("deepseek", "deepseek-v4-pro")
    for name in _ollama_models():
        options[f"Ollama · {name}"] = ("ollama", name)

    if not options:
        st.caption("没有可用模型")
        return

    current = current_selection()
    saved = st.session_state.get("llm_model_choice")
    labels = list(options)
    if saved in labels:
        current_label = saved
    else:
        current_label = next(
            (label for label, value in options.items() if value == current), None
        )
        if current_label is None:
            label = (
                f"DeepSeek · {current[1]}"
                if current[0] == "deepseek"
                else f"Ollama · {current[1]}"
            )
            options = {label: current, **options}
            labels = list(options)
            current_label = label

    if st.session_state.get("llm_model_choice") not in labels:
        st.session_state.llm_model_choice = current_label

    selected = st.selectbox("模型", labels, key="llm_model_choice")
    st.session_state["llm_choice"] = options[selected]
    if options[selected][0] == "deepseek":
        st.caption("在线 DeepSeek")
    else:
        st.caption("本地 Ollama")


head_left, head_right = st.columns([3, 2])
with head_left:
    st.title("AI 个人助理中心")
with head_right:
    render_model_switcher()
st.caption(f"🤖 当前模型：{describe_llm()}")
st.write("")

# ================= 1. 练习 =================
with st.container(border=True):
    st.subheader("🎯 练习")
    st.write("针对性训练雅思口语的不同环节，积少成多。")
    st.markdown(
        "<hr style='margin-top: 5px; margin-bottom: 15px;'/>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🧠 严肃话题", key="part3_btn", use_container_width=True):
            st.switch_page(st.session_state["page_chat"])
    with col2:
        if st.button("☕ 自由聊天", key="part1_btn", use_container_width=True):
            st.switch_page(st.session_state["page_freetalk"])
    with col3:
        if st.button("🃏 讲个故事", key="part2_btn", use_container_width=True):
            st.switch_page(st.session_state["page_part2"])

# ================= 2. 工具 =================
st.write("")
with st.container(border=True):
    st.subheader("🧰 工具")
    st.write("AI 老师随时答疑；笔记本记单词、长文本。")
    st.markdown(
        "<hr style='margin-top: 5px; margin-bottom: 15px;'/>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "🧑‍🏫 AI 老师（贴答案、随时提问）",
            key="tutor_btn",
            use_container_width=True,
        ):
            st.switch_page(st.session_state["page_tutor"])
    with col2:
        if st.button(
            "📓 笔记本（单词 / 长文本）",
            key="notebook_btn",
            use_container_width=True,
        ):
            st.switch_page(st.session_state["page_notebook"])

# ================= 3. 娱乐 =================
st.write("")
with st.container(border=True):
    st.subheader("🧘 娱乐")
    st.write("在这里放下防备，随时找人倾诉、求助或闲聊。")
    st.markdown(
        "<hr style='margin-top: 5px; margin-bottom: 15px;'/>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🎩 AI闲聊", key="chatfriend_btn", use_container_width=True):
            st.switch_page(st.session_state["page_chatfriend"])
    with col2:
        if st.button("🐱 找猫娘", key="catgirl_btn", use_container_width=True):
            st.switch_page(st.session_state["page_catgirl"])

    col3, col4 = st.columns(2)
    with col3:
        if st.button("🛋️ 心理咨询", key="psychologist_btn", use_container_width=True):
            st.switch_page(st.session_state["page_psychologist"])
    with col4:
        if st.button("🎓 学业导师", key="mentor_btn", use_container_width=True):
            st.switch_page(st.session_state["page_mentor"])
