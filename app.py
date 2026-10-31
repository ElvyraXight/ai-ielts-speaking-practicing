import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from utils import QuickLookup
from utils.Ambient import load_state as load_ambient_state, render_player, render_volume
from utils.config import current_selection, load_saved_selection, save_selection

# 让 utils.* 的 logger.info 真正打出来（默认只有 WARNING 以上可见）。
# 输出到启动 App 的终端；日志级别可用 LOG_LEVEL=DEBUG 调低门槛。
_LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()
_utils_logger = logging.getLogger("utils")
if not _utils_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    _utils_logger.addHandler(_handler)
_utils_logger.setLevel(_LOG_LEVEL)
_utils_logger.propagate = False

st.set_page_config(page_title="工作台", page_icon="🎓", layout="wide")

# 默认主按钮颜色：浅蓝紫（与严肃话题发送键一致），不再使用大红色
st.markdown(
    """
<style>
button[kind="primary"],
button[kind="primaryFormSubmit"],
div.stFormSubmitButton > button {
    background-color: #E6E6FA !important;
    color: #4B0082 !important;
    border: 1px solid #D8BFD8 !important;
}
button[kind="primary"]:hover,
button[kind="primaryFormSubmit"]:hover,
div.stFormSubmitButton > button:hover {
    background-color: #D8BFD8 !important;
    color: #4B0082 !important;
}
button[kind="segmented_control"] {
    color: #4B0082 !important;
    border-color: #D8BFD8 !important;
}
button[kind="segmented_control"]:hover {
    background-color: #F3EAF7 !important;
}
button[kind="segmented_controlActive"] {
    background-color: #E6E6FA !important;
    color: #4B0082 !important;
    border-color: #D8BFD8 !important;
}
button[kind="segmented_controlActive"]:hover {
    background-color: #D8BFD8 !important;
    color: #4B0082 !important;
}
/* 侧边栏标题区（收起箭头那一行）的下边距默认偏大，导致最上面的
   背景音音量块比页面里的普通区块多出一截空；收窄到和小标题间距一致。 */
[data-testid="stSidebarHeader"] {
    margin-bottom: 0.4rem !important;
}
/* 随手查发送按钮：2.5rem 见方，图标居中。 */
.st-key-quick_lookup_send_box button {
    width: 2.5rem !important;
    min-width: 2.5rem !important;
    max-width: 2.5rem !important;
    height: 2.5rem !important;
    min-height: 2.5rem !important;
    padding: 0 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    line-height: 1 !important;
    font-size: 1.15rem !important;
}
/* 随手查输入框不显示 Streamlit 自带的 "Press Enter to submit form • 0/500"。 */
.st-key-quick_query_text [data-testid="InputInstructions"] {
    display: none !important;
}
/* 工作台也保留和子页面一样高的返回槽位，但主页不显示按钮。 */
.st-key-sidebar_back_home {
    visibility: hidden;
}
/* 去掉页面大标题后，Streamlit 默认 6rem 的顶部留白显得太空；
   收到刚好避开右上角工具栏的高度。 */
[data-testid="stMainBlockContainer"] {
    padding-top: 4rem !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# 背景音：控制在首页右上角，播放器挂在父页面，切换页面不会中断
_ambient = load_ambient_state()
render_player(_ambient["track"], _ambient["volume"])

# 模型选择：优先继续用上次手动选的；没有才跟随 .env。
if "llm_choice" not in st.session_state:
    _choice = load_saved_selection() or current_selection()
    st.session_state["llm_choice"] = _choice
    save_selection(*_choice)

# 页面定义：标题 / 图标 / session_state 键 / 所属分组都写在一处。
# 以前 st.Page 和侧边栏 page_link 各列一遍，加一个页面要改两处、忘一处就少入口。
PAGE_TABLE = [
    ("", [
        ("course/dashboard.py", "主页", ":material/dashboard:", "page_dashboard", True),
    ]),
    ("练习", [
        ("chats/chats.py", "严肃话题", ":material/chat:", "page_chat", False),
        ("chats/FreeTalk.py", "自由聊天", ":material/coffee:", "page_freetalk", False),
        ("chats/Part2.py", "讲个故事", ":material/book:", "page_part2", False),
        ("chats/Words.py", "背单词", ":material/translate:", "page_words", False),
    ]),
    ("工具", [
        ("chats/Tutor.py", "雅思老师", ":material/co_present:", "page_tutor", False),
        ("chats/Notebook.py", "笔记本", ":material/menu_book:", "page_notebook", False),
        ("chats/Research.py", "查资料", ":material/search:", "page_research", False),
    ]),
    ("娱乐", [
        ("chats/ChatFriend.py", "日常闲聊", ":material/forum:", "page_chatfriend", False),
        ("chats/CatGirl.py", "猫娘小屋", ":material/pets:", "page_catgirl", False),
        ("chats/Psychologist.py", "心理咨询", ":material/psychology:", "page_psychologist", False),
        ("chats/Mentor.py", "学业导师", ":material/school:", "page_mentor", False),
    ]),
    ("隐藏", [
        ("chats/Help.py", "老师帮帮我", ":material/support_agent:", "page_help", False),
    ]),
]

pages: dict[str, st.Page] = {}
navigation: dict[str, list[st.Page]] = {}
for group, items in PAGE_TABLE:
    group_pages: list[st.Page] = []
    for path, title, icon, state_key, is_default in items:
        page = st.Page(path, title=title, icon=icon, default=is_default)
        pages[title] = page
        st.session_state[state_key] = page
        group_pages.append(page)
    navigation[group] = group_pages

dashboard = pages["主页"]

# 配置导航：页面仍由 st.navigation 注册，但侧边栏不再列入口；
# 换页面靠工作台首页的卡片，回工作台靠每页顶部的「← 工作台」。
pg = st.navigation(navigation, position="hidden")


def _save_word(
    term: str,
    meaning: str = "",
    note: str = "",
    analysis: dict | None = None,
    analyze: bool = False,
) -> None:
    """英文词/词组优先复用查询时的分析；中文选项没分析过，保存时补一次。"""
    from utils.Notebook import add_entry

    if analysis is not None:
        add_entry(
            term=term,
            meaning=meaning,
            note=note,
            source="随手查",
            analysis=analysis,
        )
    elif analyze:
        with st.spinner("正在分析这个说法..."):
            add_entry(term=term, meaning=meaning, note=note, source="随手查")
    else:
        # 查询时模型没给出分析（比如英文兜底翻译），只存已经看到的内容。
        add_entry(
            term=term,
            meaning=meaning,
            note=note,
            source="随手查",
            enrich=False,
        )


def _save_expression(intent: str, natural: str) -> None:
    from utils.Expressions import add_expression

    add_expression(intent=intent, natural=natural, source="随手查")


def _quick_saved(key: str) -> bool:
    return bool((st.session_state.get("quick_saved") or {}).get(key))


def _mark_quick_saved(key: str) -> None:
    saved = dict(st.session_state.get("quick_saved") or {})
    saved[key] = True
    st.session_state["quick_saved"] = saved
    st.rerun(scope="fragment")


def _save_button(key: str, label: str, save, help_text: str = "") -> None:
    """保存成功后就地禁用这颗按钮，避免连点重复写入。"""
    saved = _quick_saved(key)
    clicked = st.button(
        "已存入" if saved else label,
        key=key,
        disabled=saved,
        use_container_width=True,
        help=help_text,
    )
    if clicked and not saved:
        save()
        _mark_quick_saved(key)


def _save_buttons(
    prefix: str,
    mode: str,
    word: tuple,
    sentence: tuple,
    word_analysis: dict | None = None,
    analyze_word: bool = False,
) -> None:
    """word → 单词表；sentence → 表达库；both 两个按钮都給。"""
    if mode == "word":
        _save_button(
            f"{prefix}_word",
            "存单词表",
            lambda: _save_word(*word, analysis=word_analysis, analyze=analyze_word),
        )
        return
    if mode == "sentence":
        _save_button(
            f"{prefix}_expr",
            "存表达库",
            lambda: _save_expression(*sentence),
        )
        return
    left, right = st.columns(2)
    with left:
        _save_button(
            f"{prefix}_pw",
            "存单词表",
            lambda: _save_word(*word, analysis=word_analysis, analyze=analyze_word),
            "按词组存入单词表",
        )
    with right:
        _save_button(
            f"{prefix}_pe",
            "存表达库",
            lambda: _save_expression(*sentence),
            "按表达存入表达库",
        )


@st.dialog("随手查", width="large")
def _quick_dialog() -> None:
    """英文→中文翻译 / 中文→几个英文说法；结果只在内存里，不落盘。"""
    result = st.session_state.get("quick_result") or {}
    if result.get("error") and not result.get("translation") and not result.get("options"):
        st.warning(result["error"])
        return
    if not result:
        st.write("先在上面输入点内容。")
        return

    st.caption(result.get("source", ""))
    if result.get("mode") == "cn":
        direct = str(result.get("translation") or "").strip()
        direct_col, direct_action_col = st.columns([4, 2], vertical_alignment="center")
        with direct_col:
            st.markdown(f"**直译**　{direct or '（无）'}")
        with direct_action_col:
            if direct:
                _save_buttons(
                    prefix="ql_cn_direct",
                    mode=QuickLookup.save_mode(direct),
                    word=(direct, result["source"], ""),
                    sentence=(result["source"], direct),
                    analyze_word=True,
                )
        options = result.get("options") or []
        if options:
            st.divider()
        for index, option in enumerate(options):
            intent = QuickLookup.strip_pos(option.get("zh") or "")
            mode = option.get("save_mode") or "both"
            if not intent:
                # 没有中文释义就不硬拿用户输入当意图，避免存进一句不对应的话。
                mode = "" if mode == "sentence" else "word"
            text_col, action_col = st.columns([4, 2], vertical_alignment="center")
            with text_col:
                st.markdown(f"**{option['en']}**")
                if intent:
                    st.caption(intent)
                if option.get("note"):
                    st.caption(option["note"])
                if not intent:
                    st.caption("没有中文释义，暂不能存表达库")
            with action_col:
                if mode:
                    _save_buttons(
                        prefix=f"ql_opt_{index}",
                        mode=mode,
                        word=(option["en"], intent, ""),
                        sentence=(intent, option["en"]),
                        analyze_word=True,
                    )
    else:
        senses = result.get("senses") or []
        if senses:
            for index, sense in enumerate(senses):
                pos = str(sense.get("pos") or "").strip()
                meaning = str(sense.get("meaning") or "").strip()
                heading = f"{pos} {meaning}".strip()
                if heading:
                    st.markdown(f"**{heading}**")
                if sense.get("example"):
                    st.markdown(sense["example"])
                if sense.get("example_zh"):
                    st.caption(sense["example_zh"])
                if index < len(senses) - 1:
                    st.write("")
            if result.get("example_zh_error"):
                st.caption("⚠️ 例句中文没翻译出来，可以再查一次。")
        else:
            translation = str(result.get("translation") or "")
            translation = translation.replace("\r\n", "\n").replace("\n", "  \n")
            st.markdown(translation or "（没拿到翻译）")
            if (
                result.get("save_mode") in ("word", "both")
                and result.get("example")
            ):
                st.markdown(f"**例句**　{result['example']}")
                if result.get("example_zh"):
                    st.caption(result["example_zh"])
                elif result.get("example_zh_error"):
                    st.caption("⚠️ 例句中文没翻译出来，可以再查一次。")
        if result.get("translation"):
            _save_buttons(
                prefix="ql_en",
                mode=result.get("save_mode") or "both",
                word=(result["source"], "", ""),
                sentence=(QuickLookup.strip_pos(result["translation"]), result["source"]),
                word_analysis=result.get("analysis"),
            )


with st.sidebar:
    # 三个固定槽位：返回工作台 / 音量 / 随手查。
    # 主页隐藏返回按钮但保留槽位，保证三块在所有页面位置一致。
    back_key = (
        "sidebar_back_home"
        if pg.url_path == dashboard.url_path
        else "sidebar_back_sub"
    )
    with st.container(key=back_key):
        st.page_link(
            dashboard,
            label="工作台",
            icon=":material/arrow_back:",
            help="回到工作台",
        )
    st.markdown('<div style="height:0.35rem"></div>', unsafe_allow_html=True)
    # 背景音音量常驻在侧边栏最上面，任何页面都能调。
    render_volume()
    st.markdown('<div style="height:0.55rem"></div>', unsafe_allow_html=True)
    # 和 AI 老师页同一种输入体验：Enter 直接查，但固定单行，不随内容长高。
    with st.form("quick_lookup_form", clear_on_submit=True, border=False):
        with st.container(
            horizontal=True,
            vertical_alignment="bottom",
            gap="small",
            wrap=False,
        ):
            query = st.text_input(
                "随手查",
                placeholder="英文→中文 / 中文→英文说法",
                key="quick_query_text",
                max_chars=500,
                label_visibility="collapsed",
                width="stretch",
            )
            with st.container(key="quick_lookup_send_box", width="content"):
                submitted = st.form_submit_button(
                    "🔍", help="随手查", width=40
                )
    if submitted and query.strip():
        st.session_state["quick_saved"] = {}
        cache = st.session_state.get("quick_cache") or {}
        st.session_state["quick_cache"] = cache
        with st.spinner("查一下…"):
            st.session_state["quick_result"] = QuickLookup.lookup_cached(query, cache)
        _quick_dialog()
    elif submitted:
        st.warning("先输入要查的单词或句子")

# 页面内容；「← 工作台」已固定在侧边栏顶部。
pg.run()