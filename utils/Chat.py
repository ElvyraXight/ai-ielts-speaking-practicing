# utils/Chat.py

"""全真模拟：考官提问 + 即时反馈。

一轮对话两次并行调用：一次生成考官回应与追问，一次生成语法/润色/范文。
音频统一走 utils/tts.py，历史格式化统一走 utils/conversation.py。
"""

import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from difflib import SequenceMatcher

from utils.conversation import format_history
from utils.IeltsRubric import EXAM as IELTS_STANDARD
from utils.llm import call_llm_json
from utils.tts import speak

EXAMINER_NAME = "Daniel"


def examiner_greeting(now: datetime | None = None) -> str:
    """真实考试式的开场：按中午 12 点区分 morning / afternoon。"""
    current = now or datetime.now()
    greeting = "Good morning" if current.hour < 12 else "Good afternoon"
    return (
        f"{greeting}. My name is {EXAMINER_NAME}. "
        "Can you tell me your full name, please?"
    )

PART3_TOPICS = [
    "教育",
    "科技",
    "环境",
    "社会",
    "工作",
    "媒体",
    "城市",
    "家庭",
    "文化",
    "健康",
]

_PART1_FALLBACK = [
    ("Work or study", "Do you work or are you a student?"),
    ("Work or study", "What do you like most about it?"),
    ("Work or study", "What would you like to change about it?"),
    ("Work or study", "How do you usually spend your breaks?"),
    ("Home", "Do you live in a house or an apartment?"),
    ("Home", "What is your favourite room in your home?"),
    ("Home", "How has your home changed since you were a child?"),
    ("Home", "What would you like to improve about your home?"),
]

_PART3_FALLBACK = [
    ("Education", "How has education changed in your country over the past few decades?"),
    ("Education", "Do you think exams are a fair way to measure ability?"),
    ("Education", "What role should schools play in preparing people for work?"),
    ("Education", "Should practical skills be taught alongside academic subjects?"),
    ("Education", "How might technology change the way people learn?"),
    ("Education", "What is the most important quality of a good teacher today?"),
]

_BACKUP_GREETING = "Hello, welcome to your IELTS speaking test. Let's begin. Could you tell me your full name?"
_BACKUP_QUESTIONS = [
    "How has the internet changed the way people build friendships?",
    "Do you think modern cities are designed well for human well-being?",
    "Can you describe a time when you had to learn something completely new?",
    "What are the pros and cons of working from home?",
]


def _too_similar(question: str, previous: list[str]) -> bool:
    value = re.sub(r"\s+", " ", str(question or "")).strip().casefold()
    if not value:
        return True
    for old in previous:
        old_value = re.sub(r"\s+", " ", str(old or "")).strip().casefold()
        if not old_value:
            continue
        if SequenceMatcher(None, value, old_value).ratio() >= 0.72:
            return True
    return False


def _clean_generated(raw, part: str, recent: list[str]) -> list[dict]:
    questions = []
    seen = list(recent)
    for item in raw or []:
        if isinstance(item, str):
            item = {"question": item, "topic": ""}
        if not isinstance(item, dict):
            continue
        question = re.sub(r"\s+", " ", str(item.get("question") or "")).strip()
        if not question:
            continue
        if _too_similar(question, seen):
            continue
        topic = str(item.get("topic") or "").strip()
        questions.append({"topic": topic, "question": question})
        seen.append(question)
        if len(questions) >= (8 if part == "part1" else 6):
            break
    return questions


def generate_question_set(
    part: str,
    *,
    topic: str = "随机话题",
    use_card: bool = False,
    cue_card: str = "",
    recent: list[str] | None = None,
) -> dict:
    """生成一轮固定题量：Part 1 两话题×4 题，Part 3 一话题×6 题。"""
    part = "part3" if str(part).lower() in ("part3", "part 3") else "part1"
    recent = [str(q).strip() for q in (recent or []) if str(q).strip()][-12:]
    recent_block = "\n".join(f"- {q}" for q in recent) or "(none)"
    if part == "part1":
        count = 8
        prompt = f"""You are an IELTS Speaking examiner building a fixed Part 1 question set.

RECENTLY ASKED QUESTIONS (do not repeat or closely paraphrase any of them)
{recent_block}

TASK
- Choose TWO familiar everyday topics suitable for IELTS Part 1.
- Write FOUR short, personal, concrete questions for each topic (8 total).
- Within each topic, move from a simple question to a more detailed one.
- Do not ask about hometown, weather, hobbies, favourite colour or favourite food.
- Every question must be answerable naturally in 2-4 sentences.
- Avoid any question that is semantically close to the recent list.

Output JSON only:
{{"topics": ["topic 1", "topic 2"], "questions": [{{"topic": "topic 1", "question": "..."}}]}}
"""
    else:
        chosen = str(topic or "").strip()
        if not chosen or chosen == "随机话题":
            chosen = random.choice(PART3_TOPICS)
        card_block = (
            f"\nPART 2 CUE CARD TO BASE THE DISCUSSION ON\n{cue_card.strip()}\n"
            if use_card and cue_card.strip()
            else ""
        )
        count = 6
        prompt = f"""You are an IELTS Speaking examiner building a fixed Part 3 question set.

PART 3 TOPIC
{chosen}
{card_block}
RECENTLY ASKED QUESTIONS (do not repeat or closely paraphrase any of them)
{recent_block}

TASK
- Write SIX discussion questions on this abstract topic (6 total).
- Move from description to analysis, evaluation, comparison and future implications.
- Do not ask simple personal questions; require reasons, examples or opinions.
- Never ask about hometown, weather, hobbies, favourite colour or favourite food.
- Avoid any question that is semantically close to the recent list.

Output JSON only:
{{"topics": ["{chosen}"], "questions": [{{"topic": "{chosen}", "question": "..."}}]}}
"""

    data = {}
    for _attempt in range(2):
        data = call_llm_json(
            prompt,
            temperature=0.7,
            num_predict=1800,
            fallback={},
            timeout=60,
        )
        questions = _clean_generated(data.get("questions"), part, recent)
        if len(questions) >= count:
            return {
                "topics": [
                    str(t).strip()
                    for t in (data.get("topics") or [])
                    if str(t).strip()
                ],
                "questions": questions[:count],
            }
        # 第二次追加更严格的提醒
        prompt += "\nReturn EXACTLY the requested number of questions, no explanations."

    fallback = _PART1_FALLBACK if part == "part1" else _PART3_FALLBACK
    questions = _clean_generated(
        [{"topic": t, "question": q} for t, q in fallback], part, recent
    )
    if len(questions) < count:
        questions = [{"topic": t, "question": q} for t, q in fallback][:count]
    return {
        "topics": sorted({item["topic"] for item in questions if item["topic"]}),
        "questions": questions[:count],
    }


def ask_examiner_agent(user_answer, history_str, next_question: str = ""):
    """一个调用完成：回应上一句 + 追问下一题。"""
    fixed = str(next_question or "").strip()
    fixed_block = (
        f"\nNEXT QUESTION TO ASK (use it exactly, do not replace or rewrite it)\n{fixed}\n"
        if fixed
        else ""
    )
    prompt = f"""You are a professional IELTS Speaking examiner.

CONVERSATION SO FAR
{history_str}

CANDIDATE JUST SAID
{user_answer}
{fixed_block}
INSTRUCTION
Acknowledge the candidate's answer in one short sentence, then ask ONE next question.
{'Ask exactly the NEXT QUESTION above. Do not change its wording or ask a different question.' if fixed else ''}

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
2. suggestion: based on the corrections above, rewrite the candidate's answer into natural Band 7 spoken English. Apply every correction; keep the intended meaning, tone and roughly the same length. Do not add new ideas.
3. model_answer: a high-scoring answer to the examiner's question, English only, natural spoken style, following the length and shape required for that part below. Do not pad to a fixed word count and do not write an essay. Answer at Band 8-9 level with natural spoken grammar, vocabulary and linking.

IELTS SPEAKING STANDARD — judge the answer, the rewrite and the model answer against this
{IELTS_STANDARD}

RULES
- First infer the candidate's intended meaning from the answer and the examiner's question. Treat that intended meaning as fixed.
- If the wording actually expresses a different meaning, correct the meaning first: briefly say what it currently means, what they likely meant, then give the correction.
- Every correction and suggestion must preserve the candidate's intended meaning, tone and details. Do not upgrade, soften or add ideas they did not intend.
- If the intended meaning is genuinely unclear, do not guess and do not correct grammar. Put ONE short Chinese clarifying question in "correction", and leave "suggestion" and "model_answer" empty.
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


def get_chat_answer(message, history=None, next_question: str = ""):
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
        future_examiner = executor.submit(
            ask_examiner_agent, message, history_str, next_question
        )
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


__all__ = [
    "EXAMINER_NAME",
    "PART3_TOPICS",
    "examiner_greeting",
    "generate_question_set",
    "get_chat_answer",
]
