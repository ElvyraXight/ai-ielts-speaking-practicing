# utils/Chat.py

"""全真模拟：考官提问 + 即时反馈。

一轮对话两次并行调用：一次生成考官回应与追问，一次生成语法/润色/范文。
音频统一走 utils/tts.py，历史格式化统一走 utils/conversation.py。
"""

import random
import re
from concurrent.futures import ThreadPoolExecutor

from utils.conversation import format_history
from utils.llm import call_llm_json
from utils.tts import speak

_BACKUP_GREETING = "Hello, welcome to your IELTS speaking test. Let's begin. Could you tell me your full name?"
_BACKUP_QUESTIONS = [
    "How has the internet changed the way people build friendships?",
    "Do you think modern cities are designed well for human well-being?",
    "Can you describe a time when you had to learn something completely new?",
    "What are the pros and cons of working from home?",
]


def ask_examiner_agent(user_answer, history_str):
    """一个调用完成：回应上一句 + 追问下一题。"""
    prompt = f"""You are a professional IELTS Speaking examiner.

CONVERSATION SO FAR
{history_str}

CANDIDATE JUST SAID
{user_answer}

INSTRUCTION
Acknowledge the candidate's answer in one short sentence, then ask ONE next question.

RULES
- The next question must be specific and non-generic: ask about a detail, a reason, a comparison, a change over time, or a social/technological angle.
- NEVER ask about hometown, weather, hobbies, favourite colour or favourite food.
- Keep the whole reply under 45 words. Do not correct grammar. Do not answer for the candidate.
- Output JSON only: {{"reply": "your acknowledgement + question"}}
"""
    data = call_llm_json(prompt, temperature=0.6, num_predict=300, fallback={})
    reply = str(data.get("reply") or "").strip()
    if not reply:
        reply = random.choice(_BACKUP_QUESTIONS)
    return reply


def ask_feedback_agent(user_message, last_question):
    """一个调用完成：语法纠错 + 润色 + Band 8 参考。"""
    prompt = f"""You are an IELTS Speaking teacher reviewing one answer.

EXAMINER'S QUESTION
{last_question or "(the examiner's last question)"}

CANDIDATE'S ANSWER
{user_message}

TASKS
1. correction: 1-3 REAL grammar or word-choice issues. Quote the exact phrase with 「」, give the corrected English sentence, then a short Chinese note. If the answer is correct, write 语法基本正确.
2. suggestion: improve the candidate's answer into natural Band 7 spoken English. Keep their ideas and roughly the same length, slightly more detailed.
3. model_answer: a Band 8-9 answer to the examiner's question, 100-150 words, English only, natural spoken style.

RULES
- All quoted and corrected sentences must be English; explanations in Simplified Chinese.
- No headings, no markdown tables, no code fences.
- Use 「」 around quoted English phrases, never double quotes.
- Output JSON only: {{"correction": "...", "suggestion": "...", "model_answer": "..."}}
"""
    data = call_llm_json(prompt, temperature=0.5, num_predict=1400, fallback={})
    correction = str(data.get("correction") or "Excellent! No obvious errors.").strip()
    suggestion = str(data.get("suggestion") or "").strip()
    model_answer = str(data.get("model_answer") or "").strip()
    model_answer = re.sub(r"[\u4e00-\u9fa5]+", " ", model_answer).strip()
    return {
        "correction": correction,
        "suggestion": suggestion,
        "model_answer": model_answer,
    }


def get_chat_answer(message, history=None):
    """返回 (bot_data, 音频路径或 None)。空 message 表示开场白。"""
    history = history or []

    if not message or len(message.strip()) < 2:
        intro_prompt = """
        You are an IELTS Speaking examiner. Generate a natural, varied greeting to start the test.
        Do NOT always say "Good morning". Sometimes just say "Hello", sometimes ask "Can you hear me clearly?", or introduce yourself with a different name.
        Keep it under 20 words.
        Output ONLY valid JSON: {"reply": "Your greeting here."}
        """
        data = call_llm_json(intro_prompt, temperature=0.9, num_predict=120, fallback={})
        first_q = str(data.get("reply") or "").strip() or _BACKUP_GREETING
        first_q = re.sub(r"<[^>]*>", "", first_q).strip()
        return {
            "reply": first_q,
            "correction": "",
            "suggestion": "",
            "model_answer": "",
        }, speak(first_q)

    last_question = history[-2].get("content", "") if len(history) >= 2 else ""
    history_str = format_history(
        history, limit=6, assistant_label="Examiner", user_label="Candidate"
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_examiner = executor.submit(ask_examiner_agent, message, history_str)
        future_feedback = executor.submit(ask_feedback_agent, message, last_question)

        reply_text = future_examiner.result()
        feedback = future_feedback.result()

    bot_data = {
        "reply": reply_text,
        "correction": feedback["correction"],
        "suggestion": feedback["suggestion"] or message,
        "model_answer": feedback["model_answer"] or "Failed to generate model answer.",
    }
    return bot_data, speak(reply_text)


__all__ = ["get_chat_answer"]
