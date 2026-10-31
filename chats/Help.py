# chats/Help.py

"""考场旁的临时老师会话：只在学生主动求助时打开，不推进考试。

Part 2 和考官对话各一份互不干扰的临时聊天。长期记忆（学习档案 / 关于你）
只读不写；这一场求助里说过什么，由 `HelpMemory` 这台临时记忆负责，
结束帮助时「毕业」写进学习档案的「考试过程」，然后清空。
"""

import streamlit as st

from utils import ChatHistory, ExamState, HelpMemory, HelpSession, Memory, Part2Card, TeacherMemory
from utils.config import current_selection, describe_llm
from utils.HelpCoach import advise, one_hint, preset_model_answer
from utils.Notebook import render_jotting_sidebar
from utils.TutorLead import compose

st.set_page_config(
    page_title="老师帮帮我！",
    page_icon=":material/support_agent:",
    layout="wide",
)

source = str(HelpSession.context().get("source") or "")
source_label = "讲个故事" if source == "part2" else "考官对话"


def _exam_context() -> tuple[str, str, str]:
    state = ExamState.load()
    messages = ChatHistory.load("exam")
    part = ExamState.PART_LABELS.get(state.get("active_part"), "Part 1")
    question = next(
        (
            str(message.get("content") or "")
            for message in reversed(messages)
            if message.get("role") == "assistant"
        ),
        "",
    )
    lines = []
    for message in messages:
        role = "Examiner" if message.get("role") == "assistant" else "Candidate"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:800]}")
    transcript = "\n".join(lines)[-8000:] or "(还没有考试对话)"
    index = int(state.get("index") or 0)
    question_lines = []
    for item_index, item in enumerate(state.get("questions") or [], 1):
        mark = "已问" if item_index <= index else "未问"
        question_lines.append(
            f"{item_index}. [{mark}] {item.get('question') or ''}"
        )
    context = (
        f"考试：雅思口语模拟（{ExamState.status_text(state)}）\n"
        f"当前部分：{part}\n"
        f"当前问题：{question or '(还没有题目)'}\n"
        "本轮题目：\n"
        + ("\n".join(question_lines) or "(还没有生成题目)")
    )
    return context, transcript, question


def _part2_answer() -> str:
    """「讲个故事」页里学生当前的答案。

    答案本身只活在那一页的 session_state（`part2_input`）；但那是 widget 键，
    换页后的下一次运行会被 Streamlit 清掉，所以 Part 2 页每轮把内容抄进普通键
    `part2_answer`，这里优先读它，读不到再退回 widget 键（同一轮内）。
    刷新 / 重开软件后两边都空，不额外落盘。
    """
    value = st.session_state.get("part2_answer")
    if value is None:
        value = st.session_state.get("part2_input")
    return str(value or "").strip()


def _part2_context() -> tuple[str, str, str]:
    cue = Part2Card.get()
    answer = _part2_answer()
    context = "考试：雅思口语 Part 2\n" f"题卡：\n{cue or '(还没有题卡)'}"
    context += f"\n\n你的答案：\n{answer}" if answer else "\n\n你的答案：（还没有写）"
    transcript = f"Cue card: {cue}" if cue else ""
    # 给后台教练的转写里也带上答案：没有它，老师只能看见题卡，
    # 会反复要求学生把答案贴进聊天框。
    if answer:
        transcript += f"\n\nStudent's current answer:\n{answer}"
    return context, transcript, cue


if not source:
    st.title("🆘 老师帮帮我！")
    st.info("请从「和考官对话」或「讲个故事」页面的侧边栏进入。")
    col1, col2 = st.columns(2)
    if col1.button("去和考官对话", use_container_width=True):
        st.switch_page(st.session_state["page_chat"])
    if col2.button("去讲个故事", use_container_width=True):
        st.switch_page(st.session_state["page_part2"])
    st.stop()

context_text, test_transcript, current_question = (
    _part2_context() if source == "part2" else _exam_context()
)
part2_answer = _part2_answer() if source == "part2" else ""
display_context = context_text
if source == "exam":
    display_context = context_text.split("\n本轮题目：", 1)[0]
messages = HelpSession.messages()


with st.sidebar:
    st.subheader("🆘 老师帮帮我！")
    st.caption(f"正在旁听：{source_label}")
    st.caption("只给引导式提示，不替你答完整题。")
    target = st.session_state.get(
        "page_part2" if source == "part2" else "page_chat"
    )
    if st.button("返回考试", key="help_back", use_container_width=True):
        if target:
            st.switch_page(target)
    if st.button("结束帮助", key="help_end", use_container_width=True):
        # 这场求助到此为止：摘要进「考试过程」，临时记忆销毁，再清聊天。
        HelpMemory.finish(source)
        HelpSession.clear(source)
        if target:
            st.switch_page(target)
        st.rerun()
    st.divider()
    render_jotting_sidebar(
        "老师帮帮我",
        f"help_{source}",
        "好词好句，随时存。",
        scene=current_question,
    )

st.title("🆘 老师帮帮我！")
st.caption("老师能看到当前考试、题目和你的答案；直接说你不懂的地方。")
st.caption(f"🤖 当前模型：{describe_llm()}")

with st.expander("当前情况", expanded=False):
    st.markdown(display_context.replace("\n", "  \n"))

if not messages:
    st.info("你还没有问老师。直接发第一条消息就行。")

for message in messages:
    with st.chat_message(message.get("role", "assistant")):
        st.markdown(message.get("content", ""))

if prompt := st.chat_input("问老师：这题怎么答 / 我这句话哪里不对…"):
    messages.append({"role": "user", "content": prompt})
    HelpSession.save_messages(messages)
    with st.chat_message("user"):
        st.markdown(prompt)

    provider, model = current_selection()

    # 同一道题只生成一次参考回答：之后的提示都围绕它，标准不再变。
    # 换题（考试进入下一题 / Part 2 换题卡）时自动重新生成。
    saved_answer = HelpSession.preset_answer()
    if not (
        saved_answer.get("answer")
        and str(saved_answer.get("question") or "") == current_question
    ):
        with st.spinner("老师正在准备参考回答…"):
            answer_text = preset_model_answer(
                context_text=context_text,
                transcript=test_transcript,
                memory=TeacherMemory.memory_text(),
                part=source,
                provider=provider,
                model=model,
            )
        if answer_text:
            HelpSession.save_preset_answer(current_question, answer_text)
            saved_answer = {
                "question": current_question,
                "answer": answer_text,
            }
    preset_answer = str(saved_answer.get("answer") or "")

    # 把这场求助的原文一起给后台教练：否则它看不到上一轮自己说过什么，
    # 也不知道学生已经按建议改过（截图里"逗号早就加了还在要求加"就是这种）。
    help_history = "\n".join(
        f"{'Student' if item.get('role') == 'user' else 'Teacher'}: "
        f"{str(item.get('content') or '')[:500]}"
        for item in messages[-6:]
    )
    previous_user = next(
        (
            str(item.get("content") or "").strip()
            for item in reversed(messages[:-1])
            if item.get("role") == "user"
        ),
        "",
    )
    repeated_attempt = bool(previous_user) and previous_user == prompt.strip()

    with st.spinner("老师正在看你的考试…"):
        advice = advise(
            source=source,
            context_text=context_text,
            transcript=test_transcript,
            student_message=prompt,
            student_answer=part2_answer,
            model_answer=preset_answer,
            session_memory=HelpMemory.memory_text(source),
            help_history=help_history,
            repeated_attempt=repeated_attempt,
            provider=provider,
            model=model,
        )
    draft = one_hint(
        advice.get("hint") or "老师这边没接上，能再说一次你卡住的地方吗？"
    )
    lead = compose(
        kind="help",
        message=prompt,
        transcript="\n".join(
            f"{item.get('role')}: {item.get('content')}" for item in messages[-8:]
        ),
        draft=draft,
        plan=context_text,
        # 长期记忆只读；这一场求助自己的记录走 HelpMemory（临时，结束即毕业）。
        student_memory=TeacherMemory.memory_text(),
        personal_memory=Memory.memory_text("tutor"),
        training_memory=HelpMemory.memory_text(source),
        no_drill=True,
        provider=provider,
        model=model,
    )
    reply = one_hint(lead.get("reply") or draft)
    messages.append({"role": "assistant", "content": reply})
    HelpSession.save_messages(messages)
    # 后台把这一轮并进临时记忆：下一轮就不再重复同一条提示。
    HelpMemory.update_async(source, prompt, reply, provider=provider, model=model)
    with st.chat_message("assistant"):
        st.markdown(reply)
