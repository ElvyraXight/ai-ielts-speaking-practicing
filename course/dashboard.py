from datetime import date

import streamlit as st

from utils.Ambient import render_picker as render_ambient_picker
from utils.config import (
    DEEPSEEK_API_KEY,
    OLLAMA_MODEL,
    current_selection,
    deepseek_model_choices,
    list_ollama_models,
)
from utils.Expressions import load_expressions, stats as expression_stats
from utils.Notebook import load_entries
from utils.WordAtlas import (
    load_progress as load_word_progress,
    stats as word_stats,
)


@st.cache_data(ttl=60, show_spinner=False)
def _ollama_models() -> list[str]:
    """本机 Ollama 模型列表；服务没起时至少保留配置里的默认模型。"""
    return list_ollama_models() or [OLLAMA_MODEL]


def render_model_switcher() -> None:
    options: dict[str, tuple[str, str]] = {}
    if DEEPSEEK_API_KEY:
        for name in deepseek_model_choices():
            options[f"DeepSeek · {name}"] = ("deepseek", name)
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


head_left, head_right = st.columns([3, 2])
with head_left:
    st.title("工作台")
with head_right:
    # 背景音跟模型选择同一种控件，直接排在它下面。
    render_model_switcher()
    render_ambient_picker()
st.write("")

# ================= 0. 今天 =================
expressions = load_expressions()
exp_stats = expression_stats(expressions)
word_progress = load_word_progress()
word_counts = word_stats(word_progress)
new_quota = max(
    0, int(word_progress["settings"]["new_per_day"]) - word_counts["new_today"]
)
notebook_entries = load_entries()
notebook_today = date.today().isoformat()
notebook_word_due = sum(
    1 for entry in notebook_entries if entry["review"]["due"] <= notebook_today
)
# 小字和「今日已学 / 复习」对齐：显示今天已经巩固完的条数，而不是待巩固数。
notebook_word_done = sum(
    1
    for entry in notebook_entries
    if str(entry["review"].get("last") or "").startswith(notebook_today)
)

with st.container(border=True):
    st.subheader("🧠 今天")
    st.caption("打卡项：背今天的单词、复习到期的表达。")

    word_col, word_btn_col = st.columns([3.4, 2.6])
    with word_col:
        if word_counts["due"] or new_quota:
            st.markdown(
                f"**📚 背单词**　复习 {word_counts['due']} 个 · "
                f"新词 {new_quota} 个"
            )
        else:
            st.markdown("**📚 背单词**　✅ 今天已完成")
        st.caption(
            f"今日已学 {word_counts['new_today']} 个新词，"
            f"复习 {word_counts['review_today']} 个，"
            f"巩固单词/词组 {notebook_word_done} 个"
        )
    with word_btn_col:
        with st.container(
            horizontal=True, horizontal_alignment="right", width="stretch"
        ):
            if st.button("去背单词", key="today_words", width=112):
                st.switch_page(st.session_state["page_words"])
            if st.button(
                "去巩固单词/词组",
                key="today_drill",
                width=170,
                disabled=notebook_word_due == 0,
            ):
                # 巩固的是笔记本「单词 / 词组」里的条目，落到它的复习视图。
                st.session_state["nb_mode"] = "单词 / 词组"
                st.session_state["nb_word_view"] = "复习"
                st.switch_page(st.session_state["page_notebook"])

    exp_col, exp_btn_col = st.columns([3.4, 2.6])
    with exp_col:
        if exp_stats["due"]:
            st.markdown(f"**🗣️ 表达复习**　到期 {exp_stats['due']} 条")
        else:
            st.markdown("**🗣️ 表达复习**　✅ 今天没有到期")
        st.caption("只看中文意图，先把英文说出来")
    with exp_btn_col:
        with st.container(
            horizontal=True, horizontal_alignment="right", width="stretch"
        ):
            if st.button("去复习", key="today_review", width=112):
                st.session_state["nb_mode"] = "表达"
                st.switch_page(st.session_state["page_notebook"])

    if not word_counts["due"] and not new_quota and not exp_stats["due"]:
        st.success("今天的背诵和复习都完成了，明天见。")

# ================= 1. 练习 =================
with st.container(border=True):
    st.subheader("🎯 练习")
    st.write("针对性训练雅思口语的不同环节，积少成多。")

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
    st.write("AI 老师随时答疑；笔记本记单词、表达和长文本。")

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
            "📓 笔记本（单词 / 表达 / 长文本）",
            key="notebook_btn",
            use_container_width=True,
        ):
            st.switch_page(st.session_state["page_notebook"])

# ================= 3. 娱乐 =================
st.write("")
with st.container(border=True):
    st.subheader("🧘 娱乐")
    st.write("在这里放下防备，随时找人倾诉、求助或闲聊。")

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
