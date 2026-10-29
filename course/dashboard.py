from datetime import date

import streamlit as st

from utils.Ambient import render_picker as render_ambient_picker
from utils.config import (
    DEEPSEEK_API_KEY,
    OLLAMA_MODEL,
    current_selection,
    deepseek_model_choices,
    list_ollama_models,
    save_selection,
)
from utils.Expressions import load_expressions, stats as expression_stats
from utils.Notebook import load_entries
from utils.TutorPlan import is_done as tutor_plan_done
from utils.TutorPlan import load_plan as load_tutor_plan
from utils.TutorProgress import backfill_plan, today_count as tutor_today_count
from utils.WordAtlas import (
    load_progress as load_word_progress,
    stats as word_stats,
)

# 「今天」这一块的排版：标题、说明、两行打卡项的层级和行距。
# 只作用于这个容器（st.container(key="today_block")），不影响页面其他区域。
st.markdown(
    """
<style>
.st-key-today_block .today-title {
    font-size: 3rem;
    font-weight: 650;
    letter-spacing: 0.01em;
    line-height: 1.1;
}
.st-key-today_block .today-sub {
    font-size: 0.92rem;
    opacity: 0.62;
    line-height: 1.75;
    margin-top: 0.5rem;
    margin-bottom: 0.2rem;
}
.st-key-today_block .today-row {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.6rem;
}
.st-key-today_block .today-name {
    font-size: 1.18rem;
    font-weight: 650;
    line-height: 1.4;
}
.st-key-today_block .today-meta {
    font-size: 1rem;
    opacity: 0.85;
    line-height: 1.4;
}
.st-key-today_block [data-testid="stCaptionContainer"] p {
    font-size: 0.86rem;
    line-height: 1.7;
    margin-top: 0.3rem;
}
</style>
""",
    unsafe_allow_html=True,
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
    save_selection(*options[selected])


# 页面顶部不再放大标题，模型和背景音横排放在右上角，各自固定宽度。
with st.container(
    horizontal=True,
    horizontal_alignment="right",
    vertical_alignment="bottom",
    gap="small",
):
    with st.container(width=280):
        render_model_switcher()
    with st.container(width=170):
        render_ambient_picker()

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
tutor_plan = load_tutor_plan()
backfill_plan(tutor_plan)
tutor_points = tutor_plan.get("points") or []
tutor_done = bool(tutor_points) and tutor_plan_done(tutor_plan)
tutor_done_today = tutor_done and any(
    str(point.get("mastered_at") or "").startswith(notebook_today)
    for point in tutor_points
)
tutor_pending = sum(
    1 for point in tutor_points if point.get("status") != "mastered"
)
tutor_today_done = tutor_today_count()

with st.container(key="today_block", gap="medium"):
    st.markdown('<div class="today-title">今天</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="today-sub">打卡项：背今天的单词、复习到期的表达、完成课程计划。</div>',
        unsafe_allow_html=True,
    )

    word_col, word_btn_col = st.columns([3.4, 2.6])
    with word_col:
        if word_counts["due"] or new_quota:
            word_meta = (
                f"复习 {word_counts['due']} 个 · 新词 {new_quota} 个"
            )
        else:
            word_meta = "✅ 今天已完成"
        st.markdown(
            '<div class="today-row">'
            '<span class="today-name">📚 背单词</span>'
            f'<span class="today-meta">{word_meta}</span>'
            "</div>",
            unsafe_allow_html=True,
        )
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
            exp_meta = f"到期 {exp_stats['due']} 条"
        else:
            exp_meta = "✅ 今天没有到期"
        st.markdown(
            '<div class="today-row">'
            '<span class="today-name">🗣️ 表达复习</span>'
            f'<span class="today-meta">{exp_meta}</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption("只看中文意图，先把英文说出来")
    with exp_btn_col:
        with st.container(
            horizontal=True, horizontal_alignment="right", width="stretch"
        ):
            if st.button("去复习", key="today_review", width=112):
                st.session_state["nb_mode"] = "表达"
                st.switch_page(st.session_state["page_notebook"])

    tutor_col, tutor_btn_col = st.columns([3.4, 2.6])
    with tutor_col:
        if not tutor_points:
            tutor_meta = (
                f"今日已完成 {tutor_today_done} 个"
                if tutor_today_done
                else "还没有课程计划"
            )
        elif tutor_done_today:
            tutor_meta = "✅ 今天已完成"
        elif tutor_done:
            tutor_meta = "计划已完成，去更新"
        else:
            tutor_meta = f"待完成 {tutor_pending} 个"
        st.markdown(
            '<div class="today-row">'
            '<span class="today-name">📋 课程计划</span>'
            f'<span class="today-meta">{tutor_meta}</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        if tutor_points:
            done_count = len(tutor_points) - tutor_pending
            progress = f"本课计划已完成 {done_count}/{len(tutor_points)} 个点"
            if tutor_today_done:
                progress += f"，今日累计完成 {tutor_today_done} 个点"
            st.caption(progress)
            if tutor_done and not tutor_done_today:
                st.caption("去老师页会自动备下一课")
        else:
            if tutor_today_done:
                st.caption(
                    f"今日累计完成 {tutor_today_done} 个点（重新备课也保留）"
                )
            else:
                st.caption("去和老师备一节课，或者直接说「我想练」")
    with tutor_btn_col:
        with st.container(
            horizontal=True, horizontal_alignment="right", width="stretch"
        ):
            if st.button("去上课", key="today_tutor", width=112):
                st.switch_page(st.session_state["page_tutor"])

    if (
        not word_counts["due"]
        and not new_quota
        and not exp_stats["due"]
        and tutor_done_today
    ):
        st.success("今天的背诵、复习和课程计划都完成了，明天见。")

# 今天和下面的卡片之间多留一截，避免两块贴在一起。
st.markdown('<div style="height:1.5rem"></div>', unsafe_allow_html=True)

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
    st.write("雅思老师随时聊；笔记本记单词、表达和仓库便签条。")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "👩‍🏫 雅思老师",
            key="tutor_btn",
            use_container_width=True,
        ):
            st.switch_page(st.session_state["page_tutor"])
    with col2:
        if st.button(
            "📓 笔记本",
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
