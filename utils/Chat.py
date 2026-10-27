# utils/Chat.py

import whisper
import os
import uuid
import edge_tts
import asyncio
import random
import re
from concurrent.futures import ThreadPoolExecutor

from utils.llm import call_llm_json

print("正在加载语音识别模型，请稍候...")
whisper_model = whisper.load_model("base")
print("模型加载完毕！")

# =====================================================================
# 1. 基础工具函数
# =====================================================================
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
    voice = "en-GB-RyanNeural" 
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

# =====================================================================
# 2. 话题导演 Agent
# =====================================================================
def ask_topic_director_agent(context_history):
    system_prompt = f"""
You are an expert IELTS topic director. 
Based on the conversation history, generate THREE highly specific, interesting, and challenging questions for the examiner.

=== STRICT RULES ===
1. NEVER suggest generic topics like "hometown", "weather", "hobbies".
2. Dig deeper into tiny details they mentioned. Pivot to social or technological issues if boring.

=== CONVERSATION HISTORY ===
{context_history}

=== OUTPUT FORMAT ===
Output ONLY valid JSON, no markdown:
{{"questions": ["Question 1", "Question 2", "Question 3"]}}
"""
    banned_words = ["hometown", "weather", "favorite color", "favorite food", "do you like"]
    valid_questions = []

    data = call_llm_json(system_prompt, temperature=0.9, num_predict=400, fallback={})
    questions = data.get("questions") if isinstance(data, dict) else None
    if isinstance(questions, list):
        for q in questions:
            if isinstance(q, str) and q.strip() and not any(word in q.lower() for word in banned_words):
                valid_questions.append(q.strip())
        
    backup_questions = [
        "How has the internet changed the way people build friendships?",
        "Do you think modern cities are designed well for human well-being?",
        "Can you describe a time when you had to learn something completely new?",
        "What are the pros and cons of working from home?"
    ]
    return random.choice(valid_questions) if valid_questions else random.choice(backup_questions)

# =====================================================================
# 3. 考官 Agent 
# =====================================================================
def ask_examiner_agent(user_answer, suggested_question, counter):
    if counter == 0:
        rule = "Start the test. Say hello and ask the candidate to introduce themselves."
    else:
        rule = f'Acknowledge their answer naturally. Then, ask this EXACT question: "{suggested_question}"'

    system_prompt = f"""
You are a professional IELTS Speaking examiner.
{rule}
NEVER correct grammar. Keep your reply under 40 words.
Output ONLY valid JSON: {{"reply": "Your acknowledgement + the question."}}
"""
    prompt = f"{system_prompt}\n\nCandidate just said: {user_answer}\nExaminer Output:"
    data = call_llm_json(prompt, temperature=0.5, num_predict=200, fallback={})
    reply_text = str(data.get("reply") or "").strip() if isinstance(data, dict) else ""
    if not reply_text or "hometown" in reply_text.lower():
        return suggested_question
    return reply_text

# =====================================================================
# 4. 语法老师
# =====================================================================
def ask_grammar_agent(user_message):
    system_prompt = """
You are an IELTS grammar teacher.
Analyze the CANDIDATE'S answer for spoken grammar errors.
IGNORE capitalization and punctuation.
If perfect, output exactly: "Excellent! No obvious errors."
Output ONLY valid JSON: {"correction": "Your text here"}
"""
    prompt = f"{system_prompt}\n\nCandidate: {user_message}\nGrammar Output:"
    data = call_llm_json(prompt, temperature=0.1, num_predict=400, fallback={})
    return str(data.get("correction") or "Excellent! No obvious errors.").strip()

# =====================================================================
# 5. 内容教练
# =====================================================================
def ask_content_coach_agent(user_message):
    system_prompt = """
You are an IELTS Band 8 content coach.
Provide a native-level model answer based on the candidate's answer. 
Keep roughly the SAME length as their answer, slightly more detailed.
Output ONLY valid JSON: {"suggestion": "Your text here"}
"""
    prompt = f"{system_prompt}\n\nCandidate: {user_message}\nCoach Output:"
    data = call_llm_json(prompt, temperature=0.7, num_predict=500, fallback={})
    return str(data.get("suggestion") or "").strip()

# =====================================================================
# 6. 满分老师
# =====================================================================
def ask_model_answer_agent(last_question):
    if not last_question: return "N/A"
    system_prompt = f"""
You are a real human candidate taking the IELTS exam. You are from China.
The examiner just asked: "{last_question}"
Provide a PERFECT, natural-sounding response (Band 8-9 level).
YOU MUST SPEAK 100% IN ENGLISH. Absolutely NO Chinese characters allowed.
Output ONLY valid JSON: {{"model_answer": "Your English response here."}}
"""
    data = call_llm_json(system_prompt, temperature=0.6, num_predict=600, fallback={})
    answer = str(data.get("model_answer") or "").strip()
    if re.search(r'[\u4e00-\u9fa5]', answer):
        answer = re.sub(r'[\u4e00-\u9fa5]+', ' ', answer).strip()
    return answer or "I'm sorry, I couldn't generate a response at this moment."

# =====================================================================
# 7. 主调用函数 (动态生成开场白，五线并行)
# =====================================================================
def get_chat_anwser(message, counter, history=[]):
    # 【核心改动：如果是开场白，动态生成】
    if not message or len(message.strip()) < 2:
        intro_prompt = """
        You are an IELTS Speaking examiner. Generate a natural, varied greeting to start the test.
        Do NOT always say "Good morning". Sometimes just say "Hello", sometimes ask "Can you hear me clearly?", or introduce yourself with a different name.
        Keep it under 20 words.
        Output ONLY valid JSON: {"reply": "Your greeting here."}
        """
        data = call_llm_json(
            intro_prompt, temperature=0.9, num_predict=120, fallback={}
        )
        first_q = str(data.get("reply") or "").strip()
        if not first_q:
            first_q = "Hello, welcome to your IELTS speaking test. Let's begin."
        # 清洗可能产生的奇怪符号
        first_q = re.sub(r'<[^>]*>', '', first_q).strip()
            
        audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
        try: asyncio.run(generate_audio(first_q, audio_filename))
        except: audio_filename = None
        return {"reply": first_q, "correction": "", "suggestion": "", "model_answer": ""}, audio_filename

    last_question = history[-2]["content"] if len(history) >= 2 else ""
    context_str = "".join([f"{'Examiner' if m['role']=='assistant' else 'Candidate'}: {m['content']}\n" for m in history[-4:]])
    context_str += f"Candidate: {message}\n"

    suggested_q = ask_topic_director_agent(context_str)

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_examiner = executor.submit(ask_examiner_agent, message, suggested_q, counter)
        future_grammar = executor.submit(ask_grammar_agent, message)
        future_coach = executor.submit(ask_content_coach_agent, message)
        future_model = executor.submit(ask_model_answer_agent, last_question)
        
        reply_text = future_examiner.result()
        correction_text = future_grammar.result()
        suggestion_text = future_coach.result()
        model_answer_text = future_model.result()

    bot_data = {
        "reply": reply_text, "correction": correction_text, "suggestion": suggestion_text, "model_answer": model_answer_text
    }

    if not bot_data["suggestion"]: bot_data["suggestion"] = message
    if not bot_data["model_answer"]: bot_data["model_answer"] = "Failed to generate model answer."

    audio_filename = f"audio_records/ai_voice_{uuid.uuid4().hex[:6]}.mp3"
    try: asyncio.run(generate_audio(bot_data["reply"], audio_filename))
    except: audio_filename = None

    return bot_data, audio_filename