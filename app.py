import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from utils.Ambient import load_state as load_ambient_state, render_player
from utils.config import current_selection

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
</style>
""",
    unsafe_allow_html=True,
)

# 背景音：控制在首页右上角，播放器挂在父页面，切换页面不会中断
_ambient = load_ambient_state()
render_player(_ambient["track"], _ambient["volume"])

# 模型选择默认跟随 .env；直接打开子页面（收藏链接/刷新）时也能拿到可用的 provider
if "llm_choice" not in st.session_state:
    st.session_state["llm_choice"] = current_selection()

# 页面定义
dashboard = st.Page("course/dashboard.py", title="主页", icon=":material/dashboard:", default=True)
chat = st.Page("chats/chats.py", title="严肃话题", icon=":material/chat:")
freetalk = st.Page("chats/FreeTalk.py", title="自由聊天", icon=":material/coffee:")
part2_page = st.Page("chats/Part2.py", title="讲个故事", icon=":material/book:")
words_page = st.Page("chats/Words.py", title="背单词", icon=":material/translate:")
tutor = st.Page("chats/Tutor.py", title="AI 老师", icon=":material/smart_toy:")
notebook = st.Page("chats/Notebook.py", title="笔记本", icon=":material/menu_book:")
chatfriend = st.Page("chats/ChatFriend.py", title="日常闲聊", icon=":material/forum:")
catgirl = st.Page("chats/CatGirl.py", title="猫娘小屋", icon=":material/pets:")
psychologist = st.Page("chats/Psychologist.py", title="心理咨询", icon=":material/psychology:")
mentor = st.Page("chats/Mentor.py", title="学业导师", icon=":material/school:")

# 存入 session_state，供 dashboard 跳转
st.session_state["page_chat"] = chat
st.session_state["page_freetalk"] = freetalk
st.session_state["page_part2"] = part2_page
st.session_state["page_words"] = words_page
st.session_state["page_tutor"] = tutor
st.session_state["page_notebook"] = notebook
st.session_state["page_chatfriend"] = chatfriend
st.session_state["page_catgirl"] = catgirl
st.session_state["page_psychologist"] = psychologist
st.session_state["page_mentor"] = mentor

# 配置导航
pg = st.navigation(
    {
        "": [dashboard],
        "练习": [chat, freetalk, part2_page, words_page],
        "工具": [tutor, notebook],
        "娱乐": [chatfriend, catgirl, psychologist, mentor],
    }
)
pg.run()