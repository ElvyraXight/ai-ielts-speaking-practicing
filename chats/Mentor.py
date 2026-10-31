# chats/Mentor.py

"""学业导师：人设 + 页面骨架，流程在 utils/ChatPage.py。

专业方向由侧边栏输入，存在聊天记录的 `meta.major` 里；刷新、重启应用后
还在，默认「电子信息工程」。导师的其它要求（严谨直接、同一语言、论文结构、
最后追问）对所有专业都一样，只是把「电子信息工程」换成用户填的领域。

告诉模型的专业名会先翻成英文（`meta.major_en`）再拼进人设：中文专业名混在
英文提示词里，模型容易跑偏。翻译结果不像正常专业名（空、乱码、掺中文）时，
退回默认英文专业名。
"""

import re

import streamlit as st

from utils import ChatHistory
from utils.ChatPage import ChatPageSpec, render_chat_page
from utils.llm import call_llm_json
from utils.tts import VOICE_UK_MALE_DEEP

DEFAULT_MAJOR = "电子信息工程"
DEFAULT_MAJOR_EN = "Electronic Information Engineering"
MAJOR_KEY = "major"
MAJOR_EN_KEY = "major_en"
MAJOR_EN_SOURCE_KEY = "major_en_source"
_MAJOR_FAILED_KEY = "mentor_major_en_failed"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_TRANSLATE_PROMPT = """You name a university major or field of study in natural English.

The input may be written in Chinese. Return the English name the way a professor would
say it in a normal sentence — a real field name, not a word-by-word gloss.
Examples: 电子信息工程 -> Electronic Information Engineering; 计算机科学 -> Computer Science.
If the input is not a real field of study, or cannot be understood, return "".

MAJOR: __MAJOR__

Output JSON only: {"major_en": "..."}
"""


def current_major() -> str:
    """上次保存的专业；没保存过（或空）就用默认的电子信息工程。"""
    value = str(ChatHistory.load_meta("mentor").get(MAJOR_KEY) or "").strip()
    return value or DEFAULT_MAJOR


def _clean_major_en(text) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value.strip('"“”').strip(" .")


def _valid_major_en(text) -> bool:
    """翻译结果像不像一个正常的英文专业名；不像就交给默认值。"""
    value = _clean_major_en(text)
    if not value or len(value) > 60:
        return False
    if _CJK_RE.search(value):
        return False
    if not re.search(r"[A-Za-z]", value):
        return False
    # 正常专业名至少有一个元音；乱码串一般没有。
    if not re.search(r"[aeiouyAEIOUY]", value):
        return False
    # 只允许英文、数字和少量专业名里常见的标点。
    if re.search(r"[^A-Za-z0-9&,\-.'()/ ]", value):
        return False
    if value.casefold() in {"none", "null", "n/a"}:
        return False
    if len(value.split()) > 8:
        return False
    return True


def english_major(major: str) -> str:
    """给模型看的英文专业名；翻得不像人话就退回默认英文名。"""
    value = str(major or "").strip() or DEFAULT_MAJOR
    if value == DEFAULT_MAJOR:
        return DEFAULT_MAJOR_EN
    if not _CJK_RE.search(value):
        # 已经是英文（或其它拉丁字母）时不用再翻。
        return value if _valid_major_en(value) else DEFAULT_MAJOR_EN
    if st.session_state.get(_MAJOR_FAILED_KEY) == value:
        return DEFAULT_MAJOR_EN
    translated = ""
    try:
        data = call_llm_json(
            _TRANSLATE_PROMPT.replace("__MAJOR__", value[:200]),
            temperature=0.2,
            num_predict=60,
            fallback={},
            timeout=20,
        )
        if isinstance(data, dict):
            translated = _clean_major_en(data.get("major_en") or "")
    except Exception:
        translated = ""
    if not _valid_major_en(translated):
        # 这一轮别再反复调模型；换专业或重开 App 再试。
        st.session_state[_MAJOR_FAILED_KEY] = value
        return DEFAULT_MAJOR_EN
    return translated


def prompt_major() -> str:
    """拼人设用的专业名：优先复用翻译好的英文，专业换了才重新翻。"""
    major = current_major()
    meta = ChatHistory.load_meta("mentor")
    cached = _clean_major_en(meta.get(MAJOR_EN_KEY) or "")
    if (
        str(meta.get(MAJOR_EN_SOURCE_KEY) or "").strip() == major
        and _valid_major_en(cached)
    ):
        return cached
    translated = english_major(major)
    if st.session_state.get(_MAJOR_FAILED_KEY) != major and _valid_major_en(
        translated
    ):
        ChatHistory.update_meta(
            "mentor",
            {MAJOR_EN_KEY: translated, MAJOR_EN_SOURCE_KEY: major},
        )
    return translated


def build_persona(major: str) -> str:
    """把专业填进同一份导师要求，风格和规则不随专业变化。"""
    return f"""
You are Professor Chen, a tenured professor and expert mentor in {major}, with decades of experience in both academia and industry.

=== YOUR EXPERTISE ===
1. {major}: You know its core theory, methods, tools and real-world practice deeply, and you can explain them from undergraduate basics to research level.
2. Academic Writing: You are an expert in writing and reviewing papers in {major}. You know exactly how to structure an Abstract, craft a compelling Introduction, write a rigorous Methodology, and present Results and Discussions effectively.

=== YOUR VIBE (PERSONALITY) ===
- You are strict, logical, and direct. You do NOT sugarcoat things, but you are also patient and deeply care about the student's growth.
- You hate vague explanations. If the student uses buzzwords without understanding the underlying principles, you will immediately call it out and ask them to explain it simply.
- When explaining complex concepts, you use intuitive analogies, diagrams (described in text), and step-by-step logic.

=== CRITICAL RULES ===
1. Speak in the SAME language the user speaks (Chinese or English). 
2. When asked about academic writing, provide concrete structural advice (e.g., "Your abstract is too long. Cut the background and focus on your contribution and the 5% performance improvement.").
3. When asked about a problem in {major}, break down the reasoning process logically (clarify the goal -> list the assumptions -> check each step -> verify the result).
4. Always push the student to think deeper by asking a probing academic question at the end.
"""


def _major_selector() -> None:
    """侧边栏最上面的专业选择（搜索框正下方），保存方式和自由聊天的人设一致。"""
    with st.sidebar:
        st.subheader("🎓 选择专业")
        major = st.text_input(
            "输入专业方向：",
            value=current_major(),
            key="mentor_major_input",
            placeholder=DEFAULT_MAJOR,
        )
        ChatHistory.update_meta(
            "mentor", {MAJOR_KEY: str(major or "").strip() or DEFAULT_MAJOR}
        )
        # 和「自由聊天」的人设按钮同一套逻辑：保存新专业 → 清空聊天记录 →
        # 清空输入框 → 重开对话，让新专业立刻生效。
        if st.button(
            "🔄 修改专业并重启对话",
            key="mentor_apply_major",
            use_container_width=True,
        ):
            ChatHistory.update_meta(
                "mentor", {MAJOR_KEY: str(major or "").strip() or DEFAULT_MAJOR}
            )
            ChatHistory.clear("mentor")
            st.session_state.pop("mentor_messages", None)
            st.session_state["mentor_input_buffer"] = ""
            st.rerun()


MENTOR_PAGE = ChatPageSpec(
    prefix="mentor",
    page_title="学业导师",
    page_icon="🎓",
    heading="🎓 专业指导",
    persona=build_persona(prompt_major()),
    voice=VOICE_UK_MALE_DEEP,
    memory_key="mentor",
    memory_label="学业导师",
    note_kind="mentor",
    note_expander="指导记录",
    intro_fallback="You're late. Sit down and tell me exactly where your paper stands right now — no vague answers.",
    spinner_intro="导师正在查阅文献...",
    spinner_send="陈教授正在推演逻辑...",
    sidebar_top=_major_selector,
)

render_chat_page(MENTOR_PAGE)
