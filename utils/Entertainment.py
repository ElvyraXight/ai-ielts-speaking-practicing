# utils/Entertainment.py

import whisper
import os
import uuid
import edge_tts
import asyncio
import re
import langid  # 用于判断你说的是中文还是英文

from utils.llm import call_llm_json
from utils.Memory import memory_text, update_memory
from utils.Notes import update_session_note

print("正在加载语音识别模型(娱乐模块)...")
whisper_model = whisper.load_model("base")
print("模型加载完毕！")

AUDIO_DIR = "audio_records"
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR)

# 判断文本是中文还是英文
def is_chinese(text):
    if not text:
        return False
    try:
        lang, _ = langid.classify(text)
        return lang == "zh"
    except:
        # 兜底：通过中文字符比例判断
        zh_chars = len(re.findall(r'[\u4e00-\u9fa5]', text))
        return zh_chars > len(text) * 0.2

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
        role = "AI" if msg["role"] == "assistant" else "User"
        res += f"{role}: {msg['content']}\n"
    return res

# 文本清洗（只用英文的规则了）
def clean_ai_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'\{[^}]*\}', '', text)
    text = re.sub(r'<\|[^|]*\|>', '', text)
    stop_words = ["<|im_start|>", "<tool_call>", "user:", "assistant:"]
    for word in stop_words:
        if word in text:
            text = text.split(word)[0]
    return text.strip().strip('"').strip("'").strip("}").strip("{").strip()

# AI 生成核心逻辑（固定说英文）
def ask_entertainment_agent(user_message, history_str, persona, memory=""):
    system_prompt = f"""
You are playing a specific role: "{persona}"

LONG-TERM MEMORY ABOUT THIS USER (from previous sessions; may be incomplete)
{memory or "(none)"}

Here is the conversation history:
{history_str}

=== CRITICAL RULES ===
1. You MUST always reply in ENGLISH ONLY, regardless of what language the user speaks.
2. React naturally to what they said.
3. Use the long-term memory naturally when it fits. Never say "according to my memory" or list the facts.
4. If the memory conflicts with what the user says now, trust the new message.
5. Output ONLY valid JSON: {{"reply": "Your response here."}}
"""
    data = call_llm_json(system_prompt, temperature=0.7, num_predict=400, fallback={})
    raw_reply = str(data.get("reply") or "")
    return clean_ai_text(raw_reply) or "I'm here for you."

# 翻译 Agent（如果用户说了中文，就把英文翻译成中文）
def translate_to_chinese(english_text):
    prompt = f"""
Translate the following English text into simplified Chinese.
Keep the tone and emotion perfectly intact.
Output ONLY valid JSON: {{"translation": "Your Chinese translation here."}}

Text: "{english_text}"
"""
    data = call_llm_json(prompt, temperature=0.1, num_predict=500, fallback={})
    return str(data.get("translation") or english_text).strip()

# 对外的主调用函数
def get_entertainment_answer(
    message,
    history,
    persona,
    memory_key=None,
    memory_label="",
    note_kind=None,
    note_id=None,
    note_date=None,
):
    memory = memory_text(memory_key) if memory_key else ""

    # 开场白默认用英文（或者中文人设用中文，这里统一用英文生成）
    if not message or len(message.strip()) < 2:
        system_prompt = f"""
        Persona: {persona}

        LONG-TERM MEMORY ABOUT THIS USER (from previous sessions; may be incomplete)
        {memory or "(none)"}

        Greet the user naturally as this persona in English.
        If the memory has something worth acknowledging, you may briefly hint at it,
        but do not dump the memory or say "according to my memory".
        Output ONLY valid JSON: {{"reply": "Your greeting here."}}
        """
        data = call_llm_json(system_prompt, temperature=0.7, num_predict=200, fallback={})
        first_q = clean_ai_text(str(data.get("reply") or "")) or "Hello."
            
        audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
        try: asyncio.run(generate_audio(first_q, audio_filename))
        except: audio_filename = None
        
        return {"reply": first_q, "correction": "专注当前角色", "suggestion": "自然表达即可", "model_answer": "祝你聊得开心"}, audio_filename

    # 正常对话流程
    history_str = build_history_string(history)
    
    # 1. 让主 AI 强制用英文回复
    reply_text_en = ask_entertainment_agent(message, history_str, persona, memory)

    # 2. 判断用户这句话是不是中文
    final_reply = reply_text_en
    if is_chinese(message):
        # 如果用户说了中文，调用翻译 AI
        final_reply = translate_to_chinese(reply_text_en)

    # 3. 把这一轮里值得记住的内容合并进长期记忆
    if memory_key:
        try:
            update_memory(memory_key, message, final_reply, memory_label)
        except Exception:
            pass

    # 4. 心理咨询 / 学业指导：更新本次会话的带日期笔记（与记忆独立）
    if note_kind and note_id:
        try:
            update_session_note(
                note_kind,
                note_id,
                note_date or "",
                list(history) + [{"role": "assistant", "content": final_reply}],
            )
        except Exception:
            pass

    bot_data = {
        "reply": final_reply,
        "correction": "娱乐模式，已关闭语法纠错。",
        "suggestion": "在这里，做真实的自己就好。",
        "model_answer": "专注对话交流。"
    }
    
    audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
    try: asyncio.run(generate_audio(final_reply, audio_filename))
    except: audio_filename = None

    return bot_data, audio_filename