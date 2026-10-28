# utils/FreeTalk.py

"""自由聊天：可自定义人设，回复附带语法、润色和地道表达建议。"""

from concurrent.futures import ThreadPoolExecutor

from utils.config import current_selection
from utils.conversation import format_history
from utils.llm import call_llm_json
from utils.tts import VOICE_US_FEMALE, speak


def ask_friend_agent(user_message, history_str, persona, *, provider=None, model=None):
    prompt = f"""
You are a friendly, outgoing native English speaker.
Your persona: {persona}

History:
{history_str}

Respond naturally in ENGLISH ONLY. Keep it short and conversational (1-3 sentences).
Do NOT correct grammar.
Output ONLY valid JSON: {{"reply": "Your casual response."}}
"""
    data = call_llm_json(
        prompt,
        temperature=0.7,
        num_predict=300,
        fallback={},
        provider=provider,
        model=model,
    )
    return str(data.get("reply") or "That's interesting! What happened next?").strip()


def ask_feedback_agent(user_message, *, provider=None, model=None):
    """一个调用完成：语法纠错 + 润色 + 地道表达。"""
    prompt = f"""You are an IELTS speaking coach reviewing one short answer.

CANDIDATE SAID
{user_message}

TASKS
1. correction: 1-3 REAL grammar issues. Quote the exact phrase with 「」, give the corrected English, then a short Chinese note. If it is correct, write 语法基本正确.
2. suggestion: a more natural Band 7 spoken version of what they said. Keep the same meaning and a similar length.
3. model_answer: 1-2 idiomatic or slang expressions that could replace a bland phrase here, each with a short Chinese note.

RULES
- Quoted/corrected English stays in English; explanations in Simplified Chinese.
- No headings, no markdown tables, no code fences.
- Use 「」 around quoted English phrases, never double quotes.
- Output JSON only: {{"correction": "...", "suggestion": "...", "model_answer": "..."}}
"""
    data = call_llm_json(
        prompt,
        temperature=0.5,
        num_predict=1200,
        fallback={},
        provider=provider,
        model=model,
    )
    return {
        "correction": str(data.get("correction") or "Excellent! No obvious errors.").strip(),
        "suggestion": str(data.get("suggestion") or "").strip(),
        "model_answer": str(data.get("model_answer") or "N/A").strip(),
    }


def get_freetalk_answer(message, history, persona):
    """返回 (bot_data, 音频路径或 None)。空 message 表示开场白。"""
    if not message or len(message.strip()) < 2:
        first_q = "Hey there! How's your day going?"
        return {
            "reply": first_q,
            "correction": "",
            "suggestion": "",
            "model_answer": "",
        }, speak(first_q, voice=VOICE_US_FEMALE)

    history_str = format_history(
        history, limit=10, assistant_label="Friend", user_label="User"
    )
    # 线程里读不到 session_state，模型选择必须在主线程先定下来。
    provider, model = current_selection()

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_friend = executor.submit(
            ask_friend_agent, message, history_str, persona, provider=provider, model=model
        )
        future_feedback = executor.submit(
            ask_feedback_agent, message, provider=provider, model=model
        )

        reply_text = future_friend.result()
        feedback = future_feedback.result()

    bot_data = {
        "reply": reply_text,
        "correction": feedback["correction"],
        "suggestion": feedback["suggestion"] or message,
        "model_answer": feedback["model_answer"],
    }
    return bot_data, speak(reply_text, voice=VOICE_US_FEMALE)


__all__ = ["get_freetalk_answer"]
