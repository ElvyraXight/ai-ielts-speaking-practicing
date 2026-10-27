import requests
import streamlit as st

from utils.Expressions import due_entries, load_expressions, stats as expression_stats
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

# ================= 0. 今天 =================
expressions = load_expressions()
exp_stats = expression_stats(expressions)
today_due = due_entries(expressions, limit=3)

with st.container(border=True):
    st.subheader("🧠 今天")
    col1, col2, col3 = st.columns(3)
    col1.metric("待复习表达", exp_stats["due"])
    col2.metric("表达库", exp_stats["total"])
    col3.metric("已掌握", exp_stats["mastered"])

    if today_due:
        st.caption("今天先把这 3 句用出去：")
        for entry in today_due:
            st.markdown(f"- **{entry['intent']}** → {entry['natural']}")
    elif exp_stats["total"]:
        st.caption("今天没有到期的表达。练完随手记一句，明天再来。")
    else:
        st.caption("表达库还是空的。练完在侧边栏「🗣️ 记下这句」存一句试试。")

    last_scene = next(
        (entry["scene"] for entry in expressions if entry["scene"]), ""
    )
    if last_scene:
        st.caption(f"最近记录的场景：{last_scene.splitlines()[0]}")

    review_col, practice_col = st.columns(2)
    if review_col.button("🎯 去复习", key="today_review", use_container_width=True):
        st.session_state["nb_mode"] = "表达"
        st.switch_page(st.session_state["page_notebook"])
    if practice_col.button(
        "🃏 去练一个 Part 2", key="today_part2", use_container_width=True
    ):
        st.switch_page(st.session_state["page_part2"])

# ================= 1. 练习 =================
with st.container(border=True):
    st.subheader("🎯 练习")
    st.write("针对性训练雅思口语的不同环节，积少成多。")
    st.markdown(
        "<hr style='margin-top: 5px; margin-bottom: 15px;'/>",
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🧠 严肃话题", key="part3_btn", use_container_width=True):
            st.switch_page(st.session_state["page_chat"])
    with col2:
        if st.button("☕ 自由聊天", key="part1_btn", use_container_width=True):
            st.switch_page(st.session_state["page_freetalk"])
    with col3:
        if st.button("🃏 讲个故事", key="part2_btn", use_container_width=True):
            st.switch_page(st.session_state["page_part2"])
    with col4:
        if st.button("📚 背单词", key="words_btn", use_container_width=True):
            st.switch_page(st.session_state["page_words"])

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
