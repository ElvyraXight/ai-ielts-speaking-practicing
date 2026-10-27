import streamlit as st

from utils.llm import describe_llm

st.title("AI 个人助理中心")
st.caption(f"🤖 当前模型：{describe_llm()}")
st.write("") 

# ================= 上半部分：练习模式 =================
with st.container(border=True):
    st.subheader("🎯IELTS Training")
    st.write("针对性训练雅思口语的不同环节，积少成多。")
    st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px;'/>", unsafe_allow_html=True)
    
    # 并排三个按钮
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🧠 严肃话题", key="part3_btn", use_container_width=True):
            st.switch_page(st.session_state["page_chat"])
    with col2:
        if st.button("☕ 日常闲聊", key="part1_btn", use_container_width=True):
            st.switch_page(st.session_state["page_freetalk"])
    with col3:
        if st.button("🃏 讲个故事", key="part2_btn", use_container_width=True):
            st.switch_page(st.session_state["page_part2"])

    st.write("")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🧑‍🏫 AI 老师（贴答案、随时提问）", key="tutor_btn", use_container_width=True):
            st.switch_page(st.session_state["page_tutor"])
    with col_b:
        if st.button("📓 单词 / 词组笔记本", key="notebook_btn", use_container_width=True):
            st.switch_page(st.session_state["page_notebook"])

# ================= 下半部分：娱乐模式 =================
st.write("")
with st.container(border=True):
    st.subheader("🧘‍♀️ Personal Hut")
    st.write("在这里放下防备，随时找人倾诉、求助或闲聊。")
    st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px;'/>", unsafe_allow_html=True)
    
    # 在框内并排三个按钮
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🐱 找猫娘", key="catgirl_btn", use_container_width=True):
            st.switch_page(st.session_state["page_catgirl"])
    with col2:
        if st.button("🛋️ 心理咨询", key="psychologist_btn", use_container_width=True):
            st.switch_page(st.session_state["page_psychologist"])
    with col3:
        if st.button("🎓 学业导师", key="mentor_btn", use_container_width=True):
            st.switch_page(st.session_state["page_mentor"])