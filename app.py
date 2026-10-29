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
    ]),
    ("娱乐", [
        ("chats/ChatFriend.py", "日常闲聊", ":material/forum:", "page_chatfriend", False),
        ("chats/CatGirl.py", "猫娘小屋", ":material/pets:", "page_catgirl", False),
        ("chats/Psychologist.py", "心理咨询", ":material/psychology:", "page_psychologist", False),
        ("chats/Mentor.py", "学业导师", ":material/school:", "page_mentor", False),
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


def _save_word(term: str, meaning: str, note: str = "") -> None:
    from utils.Notebook import add_entry

    add_entry(
        term=term,
        meaning=meaning,
        note=note,
        source="随手查",
        enrich=False,
    )
    st.toast("已存入单词表")


def _save_expression(intent: str, natural: str) -> None:
    from utils.Expressions import add_expression

    add_expression(intent=intent, natural=natural, source="随手查")
    st.toast("已存入表达库")


def _save_buttons(prefix: str, kind: str, word: tuple, sentence: tuple) -> None:
    """word → 单词表；sentence → 表达库；phrase 两个按钮都給。"""
    if kind == "word":
        if st.button("存单词表", key=f"{prefix}_word", use_container_width=True):
            _save_word(*word)
        return
    if kind == "sentence":
        if st.button("存表达库", key=f"{prefix}_expr", use_container_width=True):
            _save_expression(*sentence)
        return
    left, right = st.columns(2)
    if left.button(
        "单词表", key=f"{prefix}_pw", use_container_width=True, help="按词组存入单词表"
    ):
        _save_word(*word)
    if right.button(
        "表达库", key=f"{prefix}_pe", use_container_width=True, help="按表达存入表达库"
    ):
        _save_expression(*sentence)


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
        st.markdown(f"**直译**　{result.get('translation') or '（无）'}")
        options = result.get("options") or []
        if options:
            st.divider()
        for index, option in enumerate(options):
            text_col, action_col = st.columns([4, 2], vertical_alignment="center")
            with text_col:
                st.markdown(f"**{option['en']}**")
                if option.get("zh"):
                    st.caption(option["zh"])
                if option.get("note"):
                    st.caption(option["note"])
            with action_col:
                _save_buttons(
                    prefix=f"ql_opt_{index}",
                    kind=option.get("type") or "phrase",
                    word=(
                        option["en"],
                        option.get("zh") or option.get("note") or "",
                        option.get("note") or "",
                    ),
                    sentence=(result["source"], option["en"]),
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
        else:
            translation = str(result.get("translation") or "")
            translation = translation.replace("\r\n", "\n").replace("\n", "  \n")
            st.markdown(translation or "（没拿到翻译）")
            if (
                result.get("source_type") in ("word", "phrase")
                and result.get("example")
            ):
                st.markdown(f"**例句**　{result['example']}")
                if result.get("example_zh"):
                    st.caption(result["example_zh"])
        if result.get("translation"):
            _save_buttons(
                prefix="ql_en",
                kind=result.get("source_type") or "phrase",
                word=(result["source"], result["translation"], ""),
                sentence=(result["translation"], result["source"]),
            )


with st.sidebar:
    # 背景音音量常驻在侧边栏最上面，任何页面都能调。
    render_volume()
    st.divider()
    # 和 AI 老师页同一种输入框：箭头在框内，Enter 直接发。
    if query := st.chat_input(
        "英文→中文 / 中文→英文说法",
        key="quick_query",
        max_chars=500,
    ):
        with st.spinner("查一下…"):
            st.session_state["quick_result"] = QuickLookup.lookup(query)
        _quick_dialog()

# 非主页页面顶部放一个「← 工作台」的页面链接，和侧边栏导航同一种控件
if pg.url_path != dashboard.url_path:
    st.page_link(
        dashboard,
        label="工作台",
        icon=":material/arrow_back:",
        help="回到工作台",
    )

pg.run()