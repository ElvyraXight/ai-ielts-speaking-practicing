# chats/Tutor.py

import asyncio

import streamlit as st

from utils.config import describe_llm
from utils.Expressions import render_expression_capture
from utils.LearnerProfile import build_profile, counts
from utils.Notebook import render_quick_add
from utils.tts import existing_audio, new_audio_path, synthesize
from utils.Tutor import ask_tutor, explain_vocabulary, is_bare_lookup

st.set_page_config(page_title="AI 雅思老师", page_icon="🧑‍🏫", layout="wide")

# 侧边栏的分隔线：Streamlit 默认的块间距是 1rem，<hr> 自己还带一段浏览器 margin，
# 两段叠在一起就忽宽忽窄。这里把块间距统一成 0.55rem，再把 hr / 标题的 margin 归零，
# 让每条分隔线上下都是同样的距离。只作用在本页侧边栏。
st.markdown(
    """
<style>
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.55rem !important;
}
[data-testid="stSidebar"] hr {
    margin: 0.15rem 0 !important;
    border-color: rgba(128, 128, 128, 0.22) !important;
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 {
    margin: 0 !important;
    padding: 0 !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    margin: 0 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🧑‍🏫 AI 雅思老师")
st.caption(f"🤖 当前模型：{describe_llm()}")

GREETING = {
    "role": "assistant",
    "content": (
        "你好，我是你的雅思口语老师。你可以：\n"
        "- 贴一段答案，让我指出问题并改成 Band 7+\n"
        "- 直接发单词、词组或句子，让我逐条讲解并生成发音\n"
        "- 问我某道题怎么展开、怎么说更自然\n"
        "- 让我根据你当前的题卡追问你\n\n"
        "我会参考你的背单词进度和笔记本里存的词句来出练习。想从哪儿开始？"
    ),
}

if "tutor_messages" not in st.session_state:
    st.session_state.tutor_messages = [GREETING]

cue_card = st.session_state.get("part2_cue_card", "")
student_answer = st.session_state.get("part2_input", "")

with st.sidebar:
    st.subheader("📚 老师能看到的学习档案")
    share_profile = st.toggle(
        "让老师参考背单词 / 笔记本",
        value=True,
        key="tutor_use_profile",
        help="关掉后，老师只能看到这次对话和你贴的内容。",
    )
    info = counts()
    st.caption(
        f"单词 {info['learned']} 个（到期 {info['due']}）· "
        f"笔记 {info['notes']} 条 · 表达 {info['expressions']} 条"
    )
    profile = ""
    if share_profile:
        profile = build_profile()
        with st.expander("预览老师看到的内容"):
            st.code(profile or "（还没有可参考的数据）", language="text")
    st.divider()

with st.sidebar:
    st.subheader("📎 带上当前 Part 2 练习")
    use_card = st.checkbox(
        "使用当前题卡", value=bool(cue_card), disabled=not bool(cue_card)
    )
    use_answer = st.checkbox(
        "使用我刚才的故事", value=bool(student_answer), disabled=not bool(student_answer)
    )
    if cue_card:
        st.text_area("当前题卡", cue_card, height=150, disabled=True)
    if not cue_card:
        st.caption("还没有题卡？先去「讲个故事」抽一张。")
    st.divider()
    render_quick_add("AI 老师", "tutor")
    render_expression_capture("AI 老师", "tutor", scene=cue_card)
    st.divider()
    if st.button("🧹 清空对话", use_container_width=True):
        st.session_state.tutor_messages = [GREETING]
        st.session_state.pop("tutor_audio_request", None)
        st.rerun()

context_card = cue_card if use_card else ""
context_answer = student_answer if use_answer else ""


def _attach_item_audio(items: list[dict]) -> None:
    """给每个条目并行生成发音；单条失败不影响整条回复。"""

    async def _one(item: dict) -> None:
        text = str(item.get("text") or "").strip()
        if not text:
            item["audio"] = None
            return
        path = new_audio_path("tutor_item")
        try:
            await asyncio.wait_for(synthesize(text, path), timeout=10)
            item["audio"] = existing_audio(path)
        except Exception:
            item["audio"] = None

    async def _all() -> None:
        await asyncio.gather(*(_one(item) for item in items))

    asyncio.run(_all())


def _send(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    history = list(st.session_state.tutor_messages)
    st.session_state.tutor_messages.append({"role": "user", "content": text})

    if is_bare_lookup(text):
        with st.spinner("老师正在逐条讲解并生成发音..."):
            try:
                data = explain_vocabulary(text)
            except Exception:
                data = {"items": []}
            items = data.get("items") or []
            if items:
                _attach_item_audio(items)
                st.session_state.tutor_messages.append(
                    {
                        "role": "assistant",
                        "content": data.get("intro") or "我按条给你拆开讲：",
                        "items": items,
                    }
                )
                return

    with st.spinner("老师正在思考..."):
        reply = ask_tutor(
            text, history, context_card, context_answer, profile=profile
        )
    st.session_state.tutor_messages.append({"role": "assistant", "content": reply})


with st.sidebar:
    if st.button(
        "📚 按我的进度安排练习",
        key="tutor_plan",
        use_container_width=True,
        help="让老师用你到期的词和笔记本里的表达出一组练习。",
    ):
        _send(
            "请根据我的学习档案安排今天 10 分钟的练习：先用我最近记的词和表达出 3 个口语问题，"
            "再给我一个 Part 2 开头任务；每个问题只问一句，等我回答。"
        )
        st.rerun()


for idx, msg in enumerate(st.session_state.tutor_messages):
    with st.chat_message(msg["role"]):
        if msg.get("items"):
            st.caption("📖 词典讲解")
            if msg.get("content"):
                st.markdown(msg["content"])
            type_labels = {"word": "单词", "phrase": "词组", "sentence": "句子"}
            for j, item in enumerate(msg["items"]):
                head_col, btn_col = st.columns([8, 1])
                label = type_labels.get(item.get("type"), "")
                heading = f"**{item['text']}**"
                if label:
                    heading += f" · {label}"
                if item.get("phonetic"):
                    heading += f" /{item['phonetic']}/"
                head_col.markdown(heading)
                audio_path = item.get("audio")
                if audio_path:
                    if btn_col.button(
                        "🔊",
                        key=f"tutor_audio_{idx}_{j}",
                        help="听发音",
                        use_container_width=True,
                    ):
                        st.session_state.tutor_audio_request = f"{idx}:{j}"
                        st.rerun()
                if item.get("pos"):
                    st.caption(item["pos"])
                if item.get("meaning"):
                    st.write(item["meaning"])
                if item.get("usage"):
                    st.caption(item["usage"])
                if item.get("collocations"):
                    st.caption("搭配：" + "；".join(item["collocations"]))
                if item.get("example"):
                    example = f"**例：** {item['example']}"
                    if item.get("example_zh"):
                        example += f"（{item['example_zh']}）"
                    st.markdown(example)
                if not audio_path:
                    st.caption("发音生成失败，可稍后再试。")
                if (
                    audio_path
                    and st.session_state.get("tutor_audio_request")
                    == f"{idx}:{j}"
                ):
                    st.audio(audio_path, autoplay=True)
                    st.session_state.tutor_audio_request = ""
                st.divider()
        else:
            st.markdown(msg["content"])

if prompt := st.chat_input("问老师任何雅思口语问题…"):
    _send(prompt)
    st.rerun()
