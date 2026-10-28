# utils/Entertainment.py

"""娱乐角色对话（闲聊 / 猫娘 / 心理咨询 / 学业导师）。

角色永远用英文生成；用户说中文时再把回复翻译成中文。
长期记忆与"诊疗笔记 / 指导记录"由 utils/Memory.py、utils/Notes.py 负责，
这里只在每轮结束后各触发一次，且失败不影响这一轮对话。
"""

import logging
import re

import langid

from utils.conversation import format_history
from utils.llm import call_llm_json
from utils.Memory import memory_text, update_memory
from utils.Notes import update_session_note
from utils.tts import VOICE_US_FEMALE, speak

logger = logging.getLogger(__name__)


def is_chinese(text: str) -> bool:
    """判断这句话是中文还是英文；langid 失败时按汉字比例兜底。"""
    if not text:
        return False
    try:
        lang, _ = langid.classify(text)
        return lang == "zh"
    except Exception:
        logger.debug("langid 判定失败，改用汉字比例", exc_info=True)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))
        return chinese_chars > len(text) * 0.2


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


def ask_entertainment_agent(user_message, history_str, persona, memory=""):
    prompt = f"""
You are playing a specific role: "{persona}"

LONG-TERM MEMORY ABOUT THIS USER (from previous sessions; may be incomplete)
{memory or "(none)"}

Here is the conversation history:
{history_str}

=== CRITICAL RULES ===
1. You MUST always reply in ENGLISH ONLY, regardless of what language the user speaks.
2. React naturally to what they said.
3. Use the long-term memory naturally when it fits. Never say "according to my memory" or list the facts.
4. Facts under PERMANENT FACTS were repeated or stressed by the user. Treat them as established truth: never contradict them, never ask about them again, and never act surprised by them.
5. If the user repeats something you already know, acknowledge it briefly and move the conversation forward instead of asking the same question again.
6. If the memory conflicts with what the user says now, trust the new message.
7. Output ONLY valid JSON: {{"reply": "Your response here."}}
"""
    data = call_llm_json(prompt, temperature=0.7, num_predict=400, fallback={})
    return clean_ai_text(str(data.get("reply") or "")) or "I'm here for you."


def translate_to_chinese(english_text):
    """用户说中文时，把英文回复翻译成中文。"""
    prompt = f"""
Translate the following English text into simplified Chinese.
Keep the tone and emotion perfectly intact.
Output ONLY valid JSON: {{"translation": "Your Chinese translation here."}}

Text: "{english_text}"
"""
    data = call_llm_json(prompt, temperature=0.1, num_predict=500, fallback={})
    return str(data.get("translation") or english_text).strip()


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

    reply_text_en = ask_entertainment_agent(message, history_str, persona, memory)
    final_reply = translate_to_chinese(reply_text_en) if is_chinese(message) else reply_text_en

    if memory_key:
        try:
            update_memory(memory_key, message, final_reply, memory_label)
        except Exception:
            logger.warning("更新长期记忆失败（%s）", memory_key, exc_info=True)

    # 心理咨询 / 学业指导：更新本次会话的带日期笔记（与记忆独立）
    if note_kind and note_id:
        try:
            update_session_note(
                note_kind,
                note_id,
                note_date or "",
                list(history) + [{"role": "assistant", "content": final_reply}],
            )
        except Exception:
            logger.warning("更新会话笔记失败（%s）", note_kind, exc_info=True)

    bot_data = {
        "reply": final_reply,
        "correction": "娱乐模式，已关闭语法纠错。",
        "suggestion": "在这里，做真实的自己就好。",
        "model_answer": "专注对话交流。",
    }
    return bot_data, speak(final_reply, voice=chosen_voice)


__all__ = ["get_entertainment_answer", "is_chinese"]
