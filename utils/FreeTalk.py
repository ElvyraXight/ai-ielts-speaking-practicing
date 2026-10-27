# utils/FreeTalk.py

import whisper
import os
import uuid
import edge_tts
import asyncio
from concurrent.futures import ThreadPoolExecutor

from utils.llm import call_llm_json

print("正在加载语音识别模型，请稍候...")
whisper_model = whisper.load_model("base")
print("模型加载完毕！")

AUDIO_DIR = "audio_records"
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR)

def transcribe_audio(audio_file):
    if audio_file is None:
        return ""
    temp_filename = f"temp_{uuid.uuid4().hex[:6]}.wav"
    with open(temp_filename, "wb") as f:
        f.write(audio_file.getbuffer())
    try:
        result = whisper_model.transcribe(temp_filename, language="en")
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

def build_history_string(history):
    res = ""
    for msg in history[-10:]:
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


def ask_grammar_agent(user_message):
    prompt = (
        "Rephrase to sound native. Output ONLY JSON: "
        '{"correction": "text"}\nUser: ' + user_message
    )
    data = call_llm_json(prompt, temperature=0.1, num_predict=300, fallback={})
    return str(data.get("correction") or "Excellent! No obvious errors.").strip()


def ask_polish_agent(user_message):
    prompt = (
        "Replace repetitive or overly general words with more specific, idiomatic "
        "expressions that fit spoken English, prioritizing natural collocations, and "
        "avoid stuffing in formal written or obscure vocabulary. Use simple sentences "
        "as the foundation, naturally incorporating a small number of subordinate "
        "clauses, complex sentences, or tense structures to demonstrate variety; do not "
        "deliberately lengthen sentences — prioritize accuracy over complexity. "
        'Output ONLY JSON: {"suggestion": "text"}\nUser: ' + user_message
    )
    data = call_llm_json(prompt, temperature=0.5, num_predict=500, fallback={})
    return str(data.get("suggestion") or user_message).strip()


def ask_slang_agent(user_message):
    prompt = (
        "Upgrade the wording with natural, idiomatic expressions. "
        'Output ONLY JSON: {"model_answer": "text"}\nUser: ' + user_message
    )
    data = call_llm_json(prompt, temperature=0.7, num_predict=300, fallback={})
    return str(data.get("model_answer") or "N/A").strip()

def get_freetalk_answer(message, history, persona):
    if not message or len(message.strip()) < 2:
        first_q = "Hey there! How's your day going?"
        audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
        try: asyncio.run(generate_audio(first_q, audio_filename))
        except: audio_filename = None
        return {"reply": first_q, "correction": "", "suggestion": "", "model_answer": ""}, audio_filename

    history_str = build_history_string(history)

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_friend = executor.submit(ask_friend_agent, message, history_str, persona)
        future_grammar = executor.submit(ask_grammar_agent, message)
        future_polish = executor.submit(ask_polish_agent, message)
        future_slang = executor.submit(ask_slang_agent, message)
        
        reply_text = future_friend.result()
        correction_text = future_grammar.result()
        suggestion_text = future_polish.result()
        slang_text = future_slang.result()

    bot_data = {
        "reply": reply_text, "correction": correction_text, "suggestion": suggestion_text, "model_answer": slang_text
    }
    
    audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
    try: asyncio.run(generate_audio(bot_data["reply"], audio_filename))
    except: audio_filename = None

    return bot_data, audio_filename