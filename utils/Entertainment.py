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

from utils.config import current_selection
from utils.conversation import format_history
from utils.llm import call_llm_json
from utils.Memory import memory_text, update_memory
from utils.Notes import update_session_note
from utils.tts import VOICE_US_FEMALE, speak

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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


def ask_entertainment_agent(user_message, history_str, persona, memory="", bilingual=False):
    """返回 (英文回复, 给用户看的回复)；bilingual 时一次调用同时拿到中文。

    中文翻译缺失时退回英文原回复，不再追加一次翻译请求——
    宁可这一轮没翻，也不让用户多等一次往返。
    """
    translation_rule = (
        '7. The user wrote in Chinese. Also provide "reply_zh": a faithful, '
        "natural Simplified Chinese translation of the same reply. "
        "Translate only; do not add advice, notes or extra sentences."
        if bilingual
        else ""
    )
    shape = (
        '{"reply": "Your English response here.", "reply_zh": "同一句英文的中文翻译"}'
        if bilingual
        else '{"reply": "Your response here."}'
    )
    prompt = f"""
You are playing a specific role: "{persona}"

LONG-TERM MEMORY ABOUT THIS USER (from previous sessions; may be incomplete)
{memory or "(none)"}

Here is the conversation history:
{history_str}

=== CRITICAL RULES ===
1. You MUST always write "reply" in ENGLISH ONLY, regardless of what language the user speaks.
2. React naturally to what they said.
3. Use the long-term memory naturally when it fits. Never say "according to my memory" or list the facts.
4. Facts under PERMANENT FACTS were repeated or stressed by the user. Treat them as established truth: never contradict them, never ask about them again, and never act surprised by them.
5. If the user repeats something you already know, acknowledge it briefly and move the conversation forward instead of asking the same question again.
6. If the memory conflicts with what the user says now, trust the new message.
{translation_rule}
Output ONLY valid JSON: {shape}
"""
    data = call_llm_json(
        prompt, temperature=0.7, num_predict=900 if bilingual else 400, fallback={}
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
        greeting = clean_ai_text(str(data.get("reply") or "")) or "Hello."
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

    reply_en, final_reply = ask_entertainment_agent(
        message, history_str, persona, memory, bilingual=bilingual
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

    # 心理咨询 / 学业指导：更新本次会话的带日期笔记（与记忆独立）
    if note_kind and note_id:
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
