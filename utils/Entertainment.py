# utils/Entertainment.py

"""娱乐角色对话（闲聊 / 猫娘 / 心理咨询 / 学业导师）。

角色永远用英文生成；用户说中文时，翻译和回复在**同一次调用**里拿回来
（以前是回复完再发一次翻译请求，多一倍延迟和多一倍 token）。

长期记忆与"诊疗笔记 / 指导记录"由 utils/Memory.py、utils/Notes.py 负责。
它们都在后台线程里跑：等你看到回复和语音时，记忆已经在写了。
后台线程一定要显式带 provider/model —— Streamlit 的 session_state 只属于
主线程，线程里读不到，否则"切到 Ollama"的设置会在这里被悄悄忽略。
"""

import logging
import re
import threading
from difflib import SequenceMatcher

from utils.config import current_selection
from utils.conversation import format_history
from utils.llm import call_llm_json
from utils.Memory import memory_text, update_memory
from utils.Notes import note_ready, update_session_note
from utils.tts import VOICE_US_FEMALE, speak

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PUNCT_RE = re.compile(r"[\s，。！？、~～…；：,.!?;:\"'“”‘’()（）\[\]【】]+")
_REPEAT_RATIO = 0.72


def _too_similar(reply: str, previous: str) -> bool:
    """这一条回复是不是在重复上一句（整段照抄，或者换词不换意思）。"""
    left = _PUNCT_RE.sub("", str(reply or "")).lower()
    right = _PUNCT_RE.sub("", str(previous or "")).lower()
    if not left or not right:
        return False
    if left == right:
        return True
    # 共同前缀很长，基本就是同一句话开头抄下来的
    prefix = 0
    for a, b in zip(left, right):
        if a != b:
            break
        prefix += 1
    if prefix >= 24 and prefix >= min(len(left), len(right)) * 0.5:
        return True
    return SequenceMatcher(None, left, right).ratio() >= _REPEAT_RATIO


def is_chinese(text: str) -> bool:
    """消息里有没有汉字。

    以前用 langid 判语言，"ok"、"sure" 这种短句偶尔会被判成中文，
    于是白跑一次整段翻译。作文场景里"有汉字就是要中文回复"足够准。
    """
    return bool(_CJK_RE.search(text or ""))


def clean_ai_text(text: str) -> str:
    """去掉模型偶尔带出来的模板 token、JSON 残渣和包裹引号。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"<\|[^|]*\|>", "", text)
    for stop_word in ("<|im_start|>", "<tool_call>", "user:", "assistant:"):
        if stop_word in text:
            text = text.split(stop_word)[0]
    return text.strip().strip('"').strip("'").strip("}").strip("{").strip()


_ZH_TRANSLATION_RULE = (
    '7. The user wrote in Chinese. Also provide "reply_zh": a natural, spoken '
    "Simplified Chinese version of the same reply — not a literal translation. "
    "Keep the meaning, warmth and any question, but rewrite it so it sounds like a "
    "native Chinese speaker in this role. Avoid translationese: no English word order, "
    "no calques like '一部分的你', no excessive dashes or long nested clauses; split "
    "long English sentences into short Chinese ones. "
    "Translate only; do not add advice, notes or extra sentences."
)

# 角色聊天：中文不是「翻译英文」，而是先用中文把同一段话重新说一遍。
_ZH_REWRITE_RULE = (
    '7. The user wrote in Chinese. Do NOT translate your English reply word by word. '
    'First understand what you actually mean to say, then write "reply_zh": say the same '
    "thing again in natural, spoken Simplified Chinese, as if Chinese were the language you "
    "had originally spoken to this person — one person talking, not a translator at work. "
    "Write it the way people talk, not the way people write: short spoken sentences, "
    "everyday words, 语气词 like 嗯/其实/就是 are fine, sentence fragments are fine. "
    "No written-Chinese narration, no literary or clinical wording, and never restate the "
    "person's situation back at them like a report. "
    "Keep the same meaning, warmth and question; no added advice or extra sentences."
)


def ask_entertainment_agent(
    user_message,
    history_str,
    persona,
    memory="",
    bilingual=False,
    rewrite_zh=False,
    avoid="",
    temperature=0.7,
    retry_note="",
):
    """返回 (英文回复, 给用户看的回复)；bilingual 时一次调用同时拿到中文。

    中文翻译缺失时退回英文原回复，不再追加一次翻译请求——
    宁可这一轮没翻，也不让用户多等一次往返。
    """
    if not bilingual:
        translation_rule = ""
    elif rewrite_zh:
        translation_rule = _ZH_REWRITE_RULE
    else:
        translation_rule = _ZH_TRANSLATION_RULE
    shape = (
        '{"reply": "Your English response here.", "reply_zh": "..."}'
        if bilingual
        else '{"reply": "Your response here."}'
    )
    prompt = f"""
You are playing a specific role: "{persona}"

LONG-TERM MEMORY ABOUT THIS USER (from previous sessions; may be incomplete)
{memory or "(none)"}

Here is the conversation history:
{history_str}

THE USER JUST SAID (respond to this, not to earlier turns)
{user_message}

YOUR PREVIOUS REPLY (do NOT repeat it, do NOT paraphrase it, do NOT continue it)
{avoid or "(none)"}

=== CRITICAL RULES ===
1. You MUST always write "reply" in ENGLISH ONLY, regardless of what language the user speaks.
2. React naturally to what they said.
3. Use the long-term memory naturally when it fits. Never say "according to my memory" or list the facts.
4. Facts under PERMANENT FACTS were repeated or stressed by the user. Treat them as established truth: never contradict them, never ask about them again, and never act surprised by them.
5. If the user repeats something you already know, acknowledge it briefly and move the conversation forward instead of asking the same question again.
6. Your reply must move the scene forward: say or do something NEW. Never copy a sentence from your previous reply, and never restate the same idea in different words.
7. If the user already answered your last question (a mood, a yes/no, "just looking"), never ask it again — acknowledge their answer and move one step further, with a NEW question or a new action (personas that must end on a question should ask a different, deeper one).
8. If the memory conflicts with what the user says now, trust the new message.
{retry_note}
{translation_rule}
Output ONLY valid JSON: {shape}
"""
    data = call_llm_json(
        prompt,
        temperature=temperature,
        num_predict=900 if bilingual else 400,
        fallback={},
    )
    reply = clean_ai_text(str(data.get("reply") or "")) or "I'm here for you."
    if not bilingual:
        return reply, reply

    translated = clean_ai_text(str(data.get("reply_zh") or ""))
    if not translated or '"reply_zh"' in translated:
        logger.warning("双语回复里没有可用的 reply_zh，退回英文原文")
        return reply, reply
    return reply, translated


def _run_in_background(label: str, func, *args, **kwargs) -> None:
    """把记忆 / 笔记的写入丢到后台；失败只记日志，绝不影响这一轮对话。"""

    def runner():
        try:
            func(*args, **kwargs)
        except Exception:
            logger.warning("%s失败", label, exc_info=True)

    threading.Thread(target=runner, name=f"bg-{label}", daemon=True).start()


def get_entertainment_answer(
    message,
    history,
    persona,
    memory_key=None,
    memory_label="",
    note_kind=None,
    note_id=None,
    note_date=None,
    voice=None,
    rewrite_zh=False,
    intro_fallback="",
):
    """返回 (bot_data, 音频路径或 None)。空 message 表示开场白。"""
    memory = memory_text(memory_key) if memory_key else ""
    chosen_voice = voice or VOICE_US_FEMALE

    if not message or len(message.strip()) < 2:
        intro_prompt = f"""
        Persona: {persona}

        LONG-TERM MEMORY ABOUT THIS USER (from previous sessions; may be incomplete)
        {memory or "(none)"}

        Greet the user naturally as this persona in English.
        If the memory has something worth acknowledging, you may briefly hint at it,
        but do not dump the memory or say "according to my memory".
        Facts marked PERMANENT are established; do not ask about them again.
        Output ONLY valid JSON: {{"reply": "Your greeting here."}}
        """
        data = call_llm_json(intro_prompt, temperature=0.7, num_predict=200, fallback={})
        # 生成失败时用页面预置的人设开场白，而不是一句 Hello.；兜底句同样合成语音。
        greeting = clean_ai_text(str(data.get("reply") or "")) or intro_fallback
        if not greeting:
            return {
                "reply": "",
                "correction": "专注当前角色",
                "suggestion": "自然表达即可",
                "model_answer": "祝你聊得开心",
            }, None
        return {
            "reply": greeting,
            "correction": "专注当前角色",
            "suggestion": "自然表达即可",
            "model_answer": "祝你聊得开心",
        }, speak(greeting, voice=chosen_voice)

    history_str = format_history(
        history, limit=10, assistant_label="AI", user_label="User"
    )
    bilingual = is_chinese(message)

    # 主线程里取一次模型选择，显式传给后台线程；后台线程读不到 session_state。
    provider, model = current_selection()

    previous_reply = next(
        (
            str(message_item.get("content") or "").strip()
            for message_item in reversed(list(history or []))
            if message_item.get("role") == "assistant"
            and str(message_item.get("content") or "").strip()
        ),
        "",
    )

    reply_en, final_reply = ask_entertainment_agent(
        message,
        history_str,
        persona,
        memory,
        bilingual=bilingual,
        rewrite_zh=rewrite_zh,
        avoid=previous_reply,
    )

    # 第二次兜底：模型把上一句原样说了一遍，就明确要求换一种说法重写一次。
    if previous_reply and _too_similar(final_reply, previous_reply):
        logger.info("角色回复与上一条过于相似，要求重写一次")
        reply_en, final_reply = ask_entertainment_agent(
            message,
            history_str,
            persona,
            memory,
            bilingual=bilingual,
            rewrite_zh=rewrite_zh,
            avoid=previous_reply,
            temperature=0.95,
            retry_note=(
                "IMPORTANT: your last attempt repeated your previous reply almost word for "
                "word. That is not acceptable. Answer the user's new message with a "
                "clearly different reaction, a different action and different wording."
            ),
        )

    if memory_key:
        _run_in_background(
            "更新长期记忆",
            update_memory,
            memory_key,
            message,
            final_reply,
            memory_label,
            provider=provider,
            model=model,
        )

    # 心理咨询 / 学业指导：更新本次会话的带日期笔记（与记忆独立）。
    # 用户没聊满 3 条的短会话不写，避免留下没内容的记录。
    if note_kind and note_id and note_ready(history):
        _run_in_background(
            "更新会话笔记",
            update_session_note,
            note_kind,
            note_id,
            note_date or "",
            list(history) + [{"role": "assistant", "content": final_reply}],
            provider=provider,
            model=model,
        )

    bot_data = {
        "reply": final_reply,
        "correction": "娱乐模式，已关闭语法纠错。",
        "suggestion": "在这里，做真实的自己就好。",
        "model_answer": "专注对话交流。",
    }
    return bot_data, speak(final_reply, voice=chosen_voice)


__all__ = ["get_entertainment_answer", "is_chinese"]
