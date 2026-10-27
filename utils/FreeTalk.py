# utils/FreeTalk.py

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import edge_tts

from utils.asr import get_whisper_model
from utils.llm import call_llm_json

AUDIO_DIR = "audio_records"
os.makedirs(AUDIO_DIR, exist_ok=True)


def transcribe_audio(audio_file):
    if audio_file is None:
        return ""
    temp_filename = f"temp_{uuid.uuid4().hex[:6]}.wav"
    with open(temp_filename, "wb") as f:
        f.write(audio_file.getbuffer())
    try:
        result = get_whisper_model().transcribe(temp_filename, language="en")
        text = result["text"].strip()
    except Exception as e:
        text = f"识别失败: {e}"
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
    return text


async def generate_audio(text, output_file):
    voice = "en-US-AriaNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)


def build_history_string(history, limit: int = 10) -> str:
    res = ""
    for msg in history[-limit:]:
        role = "Friend" if msg["role"] == "assistant" else "User"
        res += f"{role}: {msg['content']}\n"
    return res


def ask_friend_agent(user_message, history_str, persona):
    system_prompt = f"""
You are a friendly, outgoing native English speaker.
Your persona: {persona}

History:
{history_str}

Respond naturally in ENGLISH ONLY. Keep it short and conversational (1-3 sentences).
Do NOT correct grammar.
Output ONLY valid JSON: {{"reply": "Your casual response."}}
"""
    data = call_llm_json(system_prompt, temperature=0.7, num_predict=300, fallback={})
    return str(data.get("reply") or "That's interesting! What happened next?").strip()


def ask_feedback_agent(user_message):
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
    data = call_llm_json(prompt, temperature=0.5, num_predict=1200, fallback={})
    return {
        "correction": str(data.get("correction") or "Excellent! No obvious errors.").strip(),
        "suggestion": str(data.get("suggestion") or "").strip(),
        "model_answer": str(data.get("model_answer") or "N/A").strip(),
    }


def get_freetalk_answer(message, history, persona):
    if not message or len(message.strip()) < 2:
        first_q = "Hey there! How's your day going?"
        audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
        try:
            asyncio.run(generate_audio(first_q, audio_filename))
        except Exception:
            audio_filename = None
        return {"reply": first_q, "correction": "", "suggestion": "", "model_answer": ""}, audio_filename

    history_str = build_history_string(history)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_friend = executor.submit(ask_friend_agent, message, history_str, persona)
        future_feedback = executor.submit(ask_feedback_agent, message)

        reply_text = future_friend.result()
        feedback = future_feedback.result()

    bot_data = {
        "reply": reply_text,
        "correction": feedback["correction"],
        "suggestion": feedback["suggestion"] or message,
        "model_answer": feedback["model_answer"],
    }

    audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
    try:
        asyncio.run(generate_audio(bot_data["reply"], audio_filename))
    except Exception:
        audio_filename = None

    return bot_data, audio_filename
