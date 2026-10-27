import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(page_title="AI 个人助理中心", page_icon="🎓", layout="wide")

# 页面定义
dashboard = st.Page("course/dashboard.py", title="入口", icon=":material/dashboard:", default=True)
chat = st.Page("chats/chats.py", title="严肃话题", icon=":material/chat:")
freetalk = st.Page("chats/FreeTalk.py", title="自由聊天", icon=":material/coffee:")
part2_page = st.Page("chats/Part2.py", title="讲个故事", icon=":material/book:")
tutor = st.Page("chats/Tutor.py", title="AI 老师", icon=":material/smart_toy:")
notebook = st.Page("chats/Notebook.py", title="笔记本", icon=":material/menu_book:")
catgirl = st.Page("chats/CatGirl.py", title="猫娘小屋", icon=":material/pets:")
psychologist = st.Page("chats/Psychologist.py", title="心理咨询", icon=":material/psychology:")
mentor = st.Page("chats/Mentor.py", title="学业导师", icon=":material/school:")

# 存入 session_state，供 dashboard 跳转
st.session_state["page_chat"] = chat
st.session_state["page_freetalk"] = freetalk
st.session_state["page_part2"] = part2_page
st.session_state["page_tutor"] = tutor
st.session_state["page_notebook"] = notebook
st.session_state["page_catgirl"] = catgirl
st.session_state["page_psychologist"] = psychologist
st.session_state["page_mentor"] = mentor

# 配置导航
pg = st.navigation(
    {
        "主页": [dashboard],
        "练习": [chat, freetalk, part2_page],
        "工具": [tutor, notebook],
        "娱乐": [catgirl, psychologist, mentor],
    }
)
pg.run()