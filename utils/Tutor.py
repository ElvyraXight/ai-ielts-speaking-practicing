# utils/Tutor.py

"""对话式雅思口语老师。

模型统一走 utils/config.py 的 provider 配置，所以 Part 2 用哪个模型，
这个老师就用哪个模型。
"""

import re

from utils.llm import as_text, call_llm_json

_TUTOR_PROMPT = """You are a warm, precise IELTS Speaking tutor for a Chinese learner.

TEACHER'S LONG-TERM MEMORY OF THIS STUDENT (from earlier lessons; may be incomplete)
__MEMORY__

PREP LIST (the teacher's lesson-prep notebook; points the student chose to practise)
__PREP__

THIS LESSON'S PLAN (prepared before the lesson; teach these in order)
__PLAN__

CONTEXT
__CONTEXT__

CONVERSATION SO FAR
__HISTORY__

STUDENT'S NEW MESSAGE
__MESSAGE__

RULES
- Explain in Simplified Chinese; keep every English example sentence in English.
- Be concise: at most 170 words. Plain lines starting with "- " are fine.
- If the student asks you to check or improve an answer:
  1) start with 2-3 corrections in the exact form: 原句「...」→ 改为「...」（中文原因）;
  2) then give ONE improved version of the whole answer at Band 7+;
  3) keep the student's own facts (places, people, events). Never invent a new city, person or trip.
- If the student asks for expressions or sentence patterns: give 2-3 natural spoken options, each with a short Chinese note.
- WHENEVER your reply points out a concrete error in the student's English, also list
  0-2 short repeatable pattern labels in new_issues (<= 18 Chinese characters), never a
  full sentence or a one-off example. These go into the student's 待整理知识点 list; the
  student decides whether to add them to the prep book. Use [] if you point out no error.
- Never invent errors. If a sentence is already correct, say so and offer one small upgrade.
- If the student only says thanks / ok / understood, reply with one short natural line
  (e.g. 不客气，随时来) and do not repeat the previous correction or evaluation.
- Do NOT end every reply with a question. Most replies should end with a concrete
  suggestion, example, or short instruction. Ask at most ONE question, and only when you
  genuinely need the answer to continue; never add a question just to keep the student talking.
- No headings, no tables, no markdown code fences.
- Use 「」 around quoted English sentences, never double quotes.
- This is a TEXT-ONLY chat: you cannot hear the student's voice or audio. Never ask
  them to speak, read aloud, repeat aloud, or record; never comment on pronunciation,
  stress, intonation, speed, accent, or how something sounds. If you want a retry,
  ask them to TYPE the sentence.
- If the student asks for pronunciation help, say this chat is text-only: you can
  check wording and grammar, but not pronunciation.

USING THE MEMORY
- Use LEVEL to choose how complex your English and explanations are.
- Use STYLE and WEAK to catch the mistakes this student actually repeats.
- Use WORKS to teach the way that has helped them before.
- NOTES are things the student explicitly asked you to remember; respect them.
- If the newest message explicitly asks you to remember something, acknowledge it in one
  short line (e.g. 记住了), then answer normally.
- Never recite the memory, never say "according to my memory"; if it conflicts with the
  current message, trust the current message.

USING THE PREP LIST
- When choosing what to practise, take the points from this list first. If the list is
  non-empty, do not invent a different weak point.
- Build the question around the student's own words, notebook and expressions, not generic topics.
- Retired points are already excluded; do not bring them back unless the student asks.

USING THE PLAN
- This lesson's plan is the goal, not a menu. Keep it in mind, but start the conversation
  normally; do not open with a drill just because a plan exists.
- If the student is greeting you, making small talk, or asking a question, answer normally.
  Do not turn that message into a drill; wait for them to ask/agree to practise.
- When the student asks to practise, agrees to practise, or gives an answer that needs
  coaching, begin with the first pending point.
- Do not re-teach points marked done.
- Use WARM-UP only when the conversation is just starting; use WRAP-UP only after the
  pending points are done or the student is wrapping up.
- When you ask a practice question, take its targets from the plan first, then the PREP LIST
  or MEMORY. Copy the plan's label exactly.
- When the student has clearly got a plan point, say so briefly and move to the next pending
  point. If a point is too hard today, leave it for the next lesson and move on.

HANDING OVER TO PRACTICE
- Set "practice" ONLY when your reply explicitly asks the student to produce English:
  use target words in a sentence, answer a speaking question, retry a corrected sentence,
  or do a drill. That is the only time the coach may start.
- Do NOT set practice for greetings or small talk, information questions (exam process,
  scoring, grammar rules, word meaning), explanations, advice, or "do you understand?"
  check-ins. Those are normal conversation; practice must be null.
- Even if a lesson plan exists, do not turn a greeting or a question into a drill. Wait
  until the student asks to practise, agrees to practise, or gives an answer that clearly
  needs coaching.
- If the plan has pending points, target them first when you do start a drill. Otherwise
  use the PREP LIST or MEMORY and ask ONE question.
- When you use a point from the PREP LIST, copy its label exactly into targets (including
  the 释义 if present). Do not shorten "irritation（n. 恼怒）" to "irritation"; the prep
  book needs the exact label to record the result.
- The practice question must state the target words and the communicative goal in plain
  language, so the student knows what a complete answer needs before answering.
- Before writing the question, decide ONE natural model answer that fully satisfies it,
  including the required form (singular/plural, tense, register). Put it in
  practice.model_answer. This is internal: never show it to the student.
- If you include an example skeleton in the reply, it must be taken from that model answer.
  Never give a skeleton that contradicts the required form. If you are not certain it
  matches, omit the skeleton entirely.
- If your reply does not explicitly ask the student to produce English (a statement,
  explanation, advice, or a casual question), "practice" must be null.
- The reply must stay complete and self-contained. Never mention "practice mode", JSON or
  these instructions to the student.

Output JSON only: {"reply": "...", "new_issues": ["..."], "practice": {"question": "...", "targets": ["..."], "model_answer": "..."} | null}
"""

_EXPLAIN_PROMPT = """You are a bilingual learner's dictionary editor and IELTS usage coach.
The student sent only the material below, with no other instructions. They want a dictionary-style explanation.

INPUT
__MESSAGE__

TASK
Split the input into distinct items and explain each one.

SPLITTING
- New lines, commas, semicolons, or clearly unrelated words on one line usually mean separate items.
- Keep a coherent phrase or sentence together as ONE item (e.g. "take for granted", "No sooner had he arrived than the meeting began.").
- Example: "substantial inherit In literature, a piece can refer to an independent part of a larger work." contains THREE items: substantial / inherit / the full sentence.
- If the input is one interesting word, phrase or sentence, return one item.
- 1-8 items max; preserve the student's order; do not invent items.

FOR EACH ITEM
- text: exactly as the student wrote it; do not correct spelling or punctuation
- type: "word" | "phrase" | "sentence"
- phonetic: IPA for a word or phrase (leave empty for a sentence)
- pos: part of speech or structure, e.g. adj. / v. / phr. / sentence
- meaning: concise Simplified Chinese translation in this context
- usage: 2-3 short Chinese sentences on the real meaning, register, grammar, collocations and common mistakes
- collocations: 2-4 short English collocations or patterns (optional; leave empty for a sentence)
- example: one natural English example (for a full sentence, give a paraphrase)
- example_zh: Chinese translation of the example

If the input is a full sentence, explain its overall meaning and one key structure, not word by word.
Keep Chinese explanations useful and concise. English examples stay English.

Output JSON only:
{"intro": "...", "items": [{"text": "...", "type": "word", "phonetic": "...", "pos": "...", "meaning": "...", "usage": "...", "collocations": ["..."], "example": "...", "example_zh": "..."}]}
"""

_ASK_PREFIX = re.compile(
    r"^\s*(please\s+)?(explain|tell me|what|how|why|translate|correct|improve|rewrite|check|give me|can you|could you|show me|i want|i need|help me|teach me|write|make)\b",
    re.I,
)

# 这些短回复是“说话”，不是查词。以前只有 2-5 个词、没有句号时一律进
# 词典讲解，于是 "sounds good" / "I think so" 也会弹出一张词卡。
_CHAT_REPLIES = {
    "ok",
    "okay",
    "sure",
    "yes",
    "yeah",
    "yep",
    "no",
    "nope",
    "thanks",
    "thank you",
    "thank you very much",
    "got it",
    "i see",
    "i think so",
    "i don't think so",
    "i guess so",
    "i hope so",
    "i'm not sure",
    "not sure",
    "not really",
    "sounds good",
    "sound good",
    "sounds great",
    "sounds nice",
    "sounds interesting",
    "me too",
    "same here",
    "no problem",
    "no worries",
    "never mind",
    "of course",
    "fair enough",
    "good idea",
    "that's great",
    "that's good",
    "that's nice",
    "that's interesting",
    "maybe",
    "alright",
    "all right",
    "good",
    "great",
    "cool",
    "nice",
    "well done",
    "that makes sense",
    "makes sense",
    "i agree",
    "i disagree",
    "i'm fine",
    "i'm good",
    "pretty good",
    "not bad",
    "so-so",
    "so so",
    "see you",
    "good morning",
    "good night",
    "how are you",
    "what's up",
    "whats up",
}
_SUBJECT_RE = re.compile(
    r"^(i|i'm|i've|i'd|i'll|you|you're|we|we're|they|he|she|it)\b",
    re.I,
)

# 训练中遇到这些，说明学生不是在答题，而是在问规则/流程/词义或想停。
_COACH_HELP_RE = re.compile(
    r"(怎么改|怎么写|怎么说|怎么用|不会|不知道|这句|这样|对吗|行吗|可以吗|"
    r"对不对|是不是|再说一遍|没听清|重复|为什么用)",
    re.I,
)
_META_TOPIC_RE = re.compile(
    r"(考试|流程|评分|分数|规则|几个部分|多长时间|多少分|band|part\s*[123]|"
    r"雅思|区别|意思|含义|用法)",
    re.I,
)
_STOP_RE = re.compile(
    r"(不练了|先不练|不想练|休息一下|待会再|换个话题|说点别的|stop practice)",
    re.I,
)


def should_pause_coaching(text: str) -> bool:
    """训练中遇到“问流程 / 问区别 / 不想练”时，先退回普通对话。

    英文回答即使带问号也不在这里拦，交给陪练 prompt 判断；只处理中文的
    元问题，避免把“口语考试流程是什么”当成一次答题。
    """
    value = str(text or "").strip()
    if not value or not re.search(r"[\u4e00-\u9fff]", value):
        return False
    if _STOP_RE.search(value):
        return True
    if _COACH_HELP_RE.search(value):
        return False
    if re.search(r"[?？]", value):
        return True
    return bool(_META_TOPIC_RE.search(value))


_GREETING_RE = re.compile(
    r"^(你好|您好|hi|hello|hey|早上好|上午好|下午好|晚上好|在吗)"
    r"[呀啊哈呢哦哟]?[!！。,.，\s]*$",
    re.I,
)
_THANKS_RE = re.compile(
    r"^(谢谢|谢了|感谢|thanks|thank you)[!！。,.，\s]*$", re.I
)
_PRACTICE_REQUEST_RE = re.compile(
    r"(陪我练|开始练|练一下|练一句|练一段|考我|出题|来一句|说一句|"
    r"practice with me|start practice|drill me)",
    re.I,
)
_QUESTION_WORD_RE = re.compile(
    r"(什么|怎么|怎样|为什么|如何|哪|多少|是否|能不能|可不可以|有没有|"
    r"流程|区别|意思|含义|用法|规则|评分)",
    re.I,
)


def should_start_practice(message: str) -> bool:
    """老师返回 practice 时，判断这条用户消息是否真的适合开始训练。

    欢迎语、感谢、普通问题（流程 / 评分 / 词义 / 区别）不开始训练；
    明确说“陪我练 / 考我 / 练一句”则放行。
    """
    value = str(message or "").strip()
    if not value:
        return False
    if _STOP_RE.search(value):
        return False
    if _PRACTICE_REQUEST_RE.search(value):
        return True
    if _GREETING_RE.match(value) or _THANKS_RE.match(value):
        return False
    if re.search(r"[?？]", value):
        return False
    if re.search(r"[\u4e00-\u9fff]", value) and _QUESTION_WORD_RE.search(value):
        return False
    return True

_PRACTICE_ASK_PROMPT = """You are an IELTS Speaking tutor writing ONE practice question.

TARGET POINTS (what this student most needs to practise)
__TARGETS__

LEARNER PROFILE
__PROFILE__

STUDENT MEMORY
__MEMORY__

TASK
Write ONE natural IELTS Speaking question (one or two sentences, English) that would
make this student produce ALL of the target points in a single answer. Weave them into
a question about a real topic; it must sound like an examiner or a conversation, not a
grammar drill.

RULES
- Match the level in STUDENT MEMORY; if it is empty, keep the question straightforward.
- Do not mention the targets, and never use the words "target", "practise" or "point".
- Do not give an example answer.
- The question must be answerable in 3-5 sentences.
- Output JSON only: {"question": "..."}
"""

_PRACTICE_ASSESS_PROMPT = """You are an IELTS Speaking tutor reviewing one practice answer.

PRACTICE QUESTION
__QUESTION__

TARGET POINTS
__TARGETS__

STUDENT'S ANSWER
__ANSWER__

TASK
1. For each target (numbered), judge whether the student used it correctly and naturally:
   "good", "partial" or "weak". Avoiding it entirely is "weak".
2. new_issues: up to 2 NEW problems visible in this answer that are NOT in the target
   list (grammar, word choice, tense). Short Chinese labels, e.g. "第三人称单数漏 -s".
3. feedback: 2-3 short Chinese lines — what worked, the single most important fix, and
   one natural English phrase they could reuse. Quote English in 「」.

RULES
- Judge only what is in the answer; never invent errors.
- No headings, no tables, no markdown, no follow-up question.
- Output JSON only:
{"assessments": [{"index": 1, "result": "good", "note": "中文短评"}], "new_issues": ["..."], "feedback": "..."}
"""


def _format_targets(targets) -> str:
    labels = [
        str(target.get("label") or "").strip()
        for target in targets or []
        if str(target.get("label") or "").strip()
    ]
    return "\n".join(f"{index + 1}. {label}" for index, label in enumerate(labels)) or "(none)"


def ask_practice_question(targets, profile: str = "", memory: str = "") -> str:
    """按 2-3 个练习点出一道口语题。"""
    if not targets:
        return ""
    prompt = (
        _PRACTICE_ASK_PROMPT.replace("__TARGETS__", _format_targets(targets))
        .replace("__PROFILE__", (profile or "").strip() or "(none)")
        .replace("__MEMORY__", (memory or "").strip() or "(none)")
    )
    data = call_llm_json(prompt, temperature=0.7, num_predict=220, fallback={})
    question = as_text(data.get("question") or "").strip().strip('"').strip()
    return question or "Tell me about something you did recently that you found difficult."


def assess_practice_answer(question: str, answer: str, targets) -> dict:
    """评估一次练习回答：每个练习点练得怎样、有没有新问题、给一段反馈。"""
    prompt = (
        _PRACTICE_ASSESS_PROMPT.replace("__QUESTION__", (question or "").strip() or "(none)")
        .replace("__TARGETS__", _format_targets(targets))
        .replace("__ANSWER__", (answer or "").strip()[:2000] or "(empty)")
    )
    data = call_llm_json(prompt, temperature=0.2, num_predict=700, fallback={})
    if not isinstance(data, dict):
        return {"assessments": [], "new_issues": [], "feedback": ""}

    assessments = []
    raw_assessments = data.get("assessments")
    if isinstance(raw_assessments, list):
        for raw in raw_assessments:
            if not isinstance(raw, dict):
                continue
            try:
                index = int(raw.get("index", 0))
            except (TypeError, ValueError):
                continue
            result = str(raw.get("result") or "").strip().lower()
            if index < 1 or result not in ("good", "partial", "weak"):
                continue
            assessments.append(
                {
                    "index": index,
                    "result": result,
                    "note": as_text(raw.get("note") or "").strip()[:80],
                }
            )

    issues = data.get("new_issues")
    if isinstance(issues, str):
        issues = re.split(r"[\n；;]+", issues)
    new_issues = []
    if isinstance(issues, list):
        for issue in issues[:2]:
            text = as_text(issue).strip()[:60]
            if text:
                new_issues.append(text)

    return {
        "assessments": assessments,
        "new_issues": new_issues,
        "feedback": as_text(data.get("feedback") or "").strip()[:800],
    }


_PRACTICE_COACH_PROMPT = """You are a patient IELTS Speaking teacher coaching one student through ONE practice answer. You are not an examiner: never give the next exam question.

PRACTICE QUESTION
__QUESTION__

POINTS THE STUDENT WAS ASKED TO USE
__TARGETS__

MODEL ANSWER (internal reference; never reveal or quote)
__MODEL__

STUDENT MEMORY
__MEMORY__

PREP LIST (points the teacher is preparing from)
__PREP__

THIS LESSON'S PLAN (the larger goal; this practice answer is one step in it)
__PLAN__

CONVERSATION SO FAR
__HISTORY__

STUDENT'S LATEST MESSAGE
__MESSAGE__

CURRENT FOCUS
__FOCUS__

CRITERIA (internal tracking only; never mention this list)
__CHECKLIST__

FIRST TURN: __FIRST__
CURRENT STATUS: __STATUS__

HOW TO TEACH (this turn only)
- CASUAL ANSWER: if POINTS and MODEL ANSWER are both (none), this is not a drill. In 2–3 Chinese lines, name one thing that worked and give one natural upgrade. Do not invent criteria, do not ask the student to rebuild the sentence, set status "mastered", checklist [] and usage []. This keeps ordinary conversation from turning into a hidden exam.
- FIRST TURN is yes (drill only): in 1–2 Chinese sentences, name one real strength. Then state the COMPLETE requirement for a good version in one short list of 2–4 concrete criteria, covering the assigned points and the main visible gap. This is the only time you list them all; afterwards never re-list them or narrate progress.
- Make the criteria consistent with the PRACTICE QUESTION and MODEL ANSWER. If the question's example or skeleton contradicts the model answer, follow the model answer and do not penalise the student for the contradiction.
- If THIS LESSON'S PLAN gives a success criterion for the current target, use that criterion; do not add requirements that belong to other plan points.
- Never reveal or quote the MODEL ANSWER; use it only to judge completeness and choose hints. Accept any equally natural wording.
- Never say 清单 / checklist / 划掉 / 还剩几项 / 第几项 / 两项过了. The criteria are for you, not for the student.
- Then work on the biggest gap. Every turn must say HOW to change it — what meaning, structure, connector, word class or constraint to use — not only what is wrong. Never give the exact finished phrase.
- GUIDE, DO NOT DICTATE. Never hand the student a complete corrected sentence and ask them to repeat it. Give a fragment, an A/B choice, or a rule instead. Do not show a full model sentence even after several attempts.
- For a missing result or nuance, build it in order: fix the cause clause, then ask for the result with which, then ask for the short comment (e.g. with a dash). Do not skip to the finished sentence.
- If the student says 怎么改 / 不会 / 不知道, or gives no attempt, do NOT repeat the previous evaluation. Narrow the hint: an A/B choice, the first few words, or the rule.
- When the student produces part of the sentence, keep their words and ask for the missing piece; do not overwrite it with your polished version.
- TEXT-ONLY: the student types; you cannot hear audio. Never ask them to say/read aloud, repeat aloud, record, or comment on pronunciation, stress, intonation, speed or accent. End with a TYPED production step ("把整句再打一遍"), not "说一遍".
- End with ONE small production step about this sentence (a prompt or a sentence-level question), not a new topic question and no small talk.
- FIRST TURN is no: check only the latest attempt against the criteria. If a criterion is met, confirm it in a short clause and move to the next gap; if not, say what is missing and the method to fix it. Do not re-list the criteria.
- Do not add new criteria later unless the student introduces a new error; the requirement stays the one stated at the start.
- If the student is no longer working on the sentence (says thanks, wants to stop, changes topic, or just chats), stop coaching: answer them naturally and set status "mastered". Do not re-evaluate or repeat the previous feedback.
- Stay on the SAME answer. Do not change topic and do not ask for a new answer.
- When every criterion is met, set status "mastered" and say the answer is solid. Do not ask another question; stop.
- reason: "criteria_met" only when every criterion is actually met; "stopped" when the student disengages, changes topic, or just chats; "teaching" otherwise. This is for the coaching flow only; plan completion is checked separately.
- new_issues: 0–1 repeatable pattern labels (<= 18 Chinese characters), never a full sentence or a concrete example. These go into the student's "待整理知识点" list; the student decides whether to add them to the prep book, so "which 从句动词单复数" is useful and "which irritated me 之后没有结果" is not. [] if only this sentence is affected.
- Simplified Chinese for explanations; English examples stay English. At most 160 words. No headings, tables or markdown.

Output JSON only:
{"feedback": "...", "focus": "...", "status": "teaching"|"mastered", "reason": "criteria_met"|"stopped"|"teaching", "checklist": ["..."], "usage": [{"index": 1, "result": "good"|"partial"|"weak", "note": "中文短评"}], "new_issues": ["..."]}
"""


def coach_practice_answer(
    question: str,
    targets,
    latest: str,
    *,
    history: str = "",
    focus: str = "",
    checklist: list[str] | None = None,
    first_turn: bool = True,
    status: str = "teaching",
    profile: str = "",
    memory: str = "",
    prep: str = "",
    plan: str = "",
    model_answer: str = "",
) -> dict:
    """一次教学回合：评价 + 选一个薄弱点 + 讲解 + 巩固指令。

    不生成下一道题；checklist 保存这轮还要巩固的表达。
    """
    prompt = (
        _PRACTICE_COACH_PROMPT.replace(
            "__QUESTION__", (question or "").strip() or "(none)"
        )
        .replace("__TARGETS__", _format_targets(targets))
        .replace("__MODEL__", (model_answer or "").strip()[:500] or "(none)")
        .replace("__MEMORY__", (memory or "").strip() or "(none)")
        .replace("__PREP__", (prep or "").strip() or "(empty)")
        .replace("__PLAN__", (plan or "").strip() or "(none)")
        .replace("__HISTORY__", (history or "").strip() or "(no previous messages)")
        .replace("__MESSAGE__", (latest or "").strip()[:2000] or "(empty)")
        .replace("__FOCUS__", (focus or "").strip() or "(not set yet)")
        .replace(
            "__CHECKLIST__",
            "\n".join(f"- {item}" for item in (checklist or [])) or "(empty)",
        )
        .replace("__FIRST__", "yes" if first_turn else "no")
        .replace("__STATUS__", status or "teaching")
    )
    data = call_llm_json(prompt, temperature=0.5, num_predict=900, fallback={})
    if not isinstance(data, dict):
        data = {}

    usage = []
    raw_usage = data.get("usage")
    if isinstance(raw_usage, list):
        for raw in raw_usage:
            if not isinstance(raw, dict):
                continue
            try:
                index = int(raw.get("index", 0))
            except (TypeError, ValueError):
                continue
            result = str(raw.get("result") or "").strip().lower()
            if not 1 <= index <= len(targets or []) or result not in (
                "good",
                "partial",
                "weak",
            ):
                continue
            usage.append(
                {
                    "index": index,
                    "result": result,
                    "note": as_text(raw.get("note") or "").strip()[:80],
                }
            )

    issues = data.get("new_issues")
    if isinstance(issues, str):
        issues = re.split(r"[\n；;]+", issues)
    new_issues = []
    if isinstance(issues, list):
        for issue in issues[:2]:
            text = as_text(issue).strip()[:60]
            if text:
                new_issues.append(text)

    raw_checklist = data.get("checklist")
    if isinstance(raw_checklist, list):
        checklist_out = []
        for item in raw_checklist[:4]:
            text = as_text(item).strip()[:60]
            if text and text not in checklist_out:
                checklist_out.append(text)
    else:
        checklist_out = [str(item)[:60] for item in (checklist or [])][:4]

    next_status = str(data.get("status") or "").strip().lower()
    if next_status not in ("teaching", "mastered"):
        next_status = "mastered" if status == "mastered" else "teaching"

    next_focus = as_text(data.get("focus") or "").strip()[:80]
    if not next_focus:
        next_focus = focus or (checklist_out[0] if checklist_out else "")

    # 没有指定练习点、也没有标准答案，说明这只是一次普通问答：给一句
    # 反馈就结束，不要把它拖成“必须改到全对”的隐藏练习。
    if not targets and not (model_answer or "").strip():
        next_status = "mastered"
        checklist_out = []
        next_focus = ""

    if not checklist_out and next_focus and next_status != "mastered":
        checklist_out = [next_focus]

    reason = str(data.get("reason") or "").strip().lower()
    if reason not in ("criteria_met", "stopped", "teaching"):
        reason = "teaching"
    if next_status == "mastered" and reason == "teaching":
        # 模型只说 mastered 没说原因时：所有目标点都 good 且没有剩余标准，
        # 才按“真的做到”处理；否则按“停下来”处理，不拿它去勾计划。
        usage_good = bool(targets) and bool(usage) and all(
            item["result"] == "good" for item in usage
        )
        reason = (
            "criteria_met" if usage_good and not checklist_out else "stopped"
        )
    if next_status != "mastered":
        reason = "teaching"

    return {
        "feedback": as_text(data.get("feedback") or "").strip()[:1200],
        "focus": next_focus,
        "status": next_status,
        "reason": reason,
        "checklist": checklist_out,
        "usage": usage,
        "new_issues": new_issues,
    }


def _build_history(messages, limit: int = 10) -> str:
    lines = []
    for msg in messages[-limit:]:
        content = re.sub(r"\s+", " ", str(msg.get("content", ""))).strip()[:700]
        items = msg.get("items") or []
        if items:
            item_lines = []
            for item in items[:8]:
                text = str(item.get("text") or "").strip()
                meaning = str(item.get("meaning") or "").strip()
                if text:
                    item_lines.append(f"{text} — {meaning}".strip(" —"))
            if item_lines:
                content = (content + "\n" + "\n".join(item_lines)).strip()
        if not content:
            continue
        role = "Tutor" if msg.get("role") == "assistant" else "Student"
        lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(no previous messages)"


def _parse_practice(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    question = as_text(raw.get("question") or "").strip()[:500]
    if not question:
        return None
    targets = []
    raw_targets = raw.get("targets")
    if not isinstance(raw_targets, list):
        raw_targets = []
    for item in raw_targets:
        text = as_text(item).strip()[:60]
        if text and text not in targets:
            targets.append(text)
    model_answer = as_text(raw.get("model_answer") or "").strip()[:500]
    return {
        "question": question,
        "targets": targets[:3],
        "model_answer": model_answer,
    }


def _clean_new_issues(raw, limit: int = 2) -> list[str]:
    issues = raw
    if isinstance(issues, str):
        issues = re.split(r"[\n；;]+", issues)
    result = []
    if isinstance(issues, list):
        for issue in issues[:limit]:
            text = as_text(issue).strip()[:60]
            if text and text not in result:
                result.append(text)
    return result


def ask_tutor_turn(
    message: str,
    history,
    cue_card: str = "",
    student_answer: str = "",
    profile: str = "",
    memory: str = "",
    prep: str = "",
    plan: str = "",
    paused: bool = False,
    no_drill: bool = False,
    plan_done: bool = False,
) -> dict:
    """老师的一轮回复；如果她开始出练习，practice 里带题目和要用的点。"""
    context_parts = []
    if (cue_card or "").strip():
        context_parts.append("Current Part 2 cue card:\n" + cue_card.strip())
    if (student_answer or "").strip():
        context_parts.append(
            "The student's current Part 2 answer:\n" + student_answer.strip()[:2000]
        )
    if paused:
        context_parts.append(
            "The student just paused a practice sentence to ask a question. "
            "Answer their question first. Do not start a new drill or ask them to "
            "produce English in this reply."
        )
    if no_drill and not paused:
        context_parts.append(
            "The student is greeting, small-talking, or asking for information. "
            "Answer normally. Do not start a drill, do not ask them to produce "
            "English, and do not set practice in this reply."
        )
    if plan_done:
        context_parts.append(
            "The current lesson plan is complete. Do not start a new drill. If the "
            "student asks to practise, tell them this lesson's goals are done and a "
            "new plan will be prepared on the next start (or they can click 更新计划)."
        )

    prompt = (
        _TUTOR_PROMPT.replace("__MEMORY__", (memory or "").strip() or "(none)")
        .replace("__PREP__", (prep or "").strip() or "(empty)")
        .replace("__PLAN__", (plan or "").strip() or "(none)")
        .replace("__CONTEXT__", "\n\n".join(context_parts) or "(none)")
        .replace("__HISTORY__", _build_history(history))
        .replace("__MESSAGE__", (message or "").strip() or "(empty)")
    )
    data = call_llm_json(prompt, temperature=0.7, num_predict=700, fallback="")
    reply = as_text(data.get("reply") or data.get("_fallback") or "").strip()
    practice = _parse_practice(data.get("practice"))
    if paused or no_drill or plan_done:
        # 学生只是问问题 / 打招呼 / 刚暂停 / 这课目标已完成，不要拖回训练。
        practice = None
    return {
        "reply": reply or "（老师这边暂时没接上，再问一次试试？）",
        "practice": practice,
        "new_issues": _clean_new_issues(data.get("new_issues")),
    }


def ask_tutor(
    message: str,
    history,
    cue_card: str = "",
    student_answer: str = "",
    profile: str = "",
    memory: str = "",
    prep: str = "",
    plan: str = "",
    paused: bool = False,
    no_drill: bool = False,
    plan_done: bool = False,
) -> str:
    """兼容旧调用：只返回文字回复。"""
    return ask_tutor_turn(
        message,
        history,
        cue_card,
        student_answer,
        profile=profile,
        memory=memory,
        prep=prep,
        plan=plan,
        paused=paused,
        no_drill=no_drill,
        plan_done=plan_done,
    )["reply"]


def is_bare_lookup(message: str) -> bool:
    """没有其它说明、只发英文单词 / 词组 / 句子时，走逐条讲解模式。"""
    text = (message or "").strip().replace("’", "'").replace("‘", "'")
    if not text or len(text) > 1200:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    if "?" in text:
        return False
    if _ASK_PREFIX.match(text):
        return False
    normalized = re.sub(r"[^a-z' ]+", " ", text.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized in _CHAT_REPLIES:
        return False
    # 以 I / you / we / they 开头、没有问号的短句是回答，不是词条。
    if _SUBJECT_RE.match(text):
        return False
    words = re.findall(r"[A-Za-z']+", text)
    # 完整句子是“说话”，不是查词；只有单词/短语才自动切词典。
    if len(words) >= 2 and text.rstrip().endswith((".", "!", "?")):
        return False
    if len(words) >= 6:
        return False
    return bool(re.search(r"[A-Za-z]", text))


def _infer_type(text: str) -> str:
    words = len(re.findall(r"[A-Za-z']+", text))
    if re.search(r"[.!?]$", text) and words > 2:
        return "sentence"
    if " " in text.strip():
        return "phrase"
    return "word"


def explain_vocabulary(message: str) -> dict:
    """把一段只有英文的输入拆成条目，逐条讲解。"""
    prompt = _EXPLAIN_PROMPT.replace("__MESSAGE__", (message or "").strip()[:1200])
    data = call_llm_json(
        prompt, temperature=0.3, num_predict=1000, fallback={}, timeout=90
    )
    if not isinstance(data, dict):
        return {"intro": "", "items": []}

    items: list[dict] = []
    seen: set[str] = set()
    raw_items = data.get("items")
    if not isinstance(raw_items, (list, tuple)):
        raw_items = []

    for raw in raw_items[:8]:
        if not isinstance(raw, dict):
            continue
        text = as_text(raw.get("text") or "").strip().strip('"“”')
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)

        item_type = str(raw.get("type") or "").strip().lower()
        if item_type not in ("word", "phrase", "sentence"):
            item_type = _infer_type(text)

        raw_collocations = raw.get("collocations")
        if isinstance(raw_collocations, str):
            raw_collocations = re.split(r"[\n；;,，]+", raw_collocations)
        if not isinstance(raw_collocations, (list, tuple)):
            raw_collocations = []
        collocations = []
        for collocation in raw_collocations:
            value = as_text(collocation).strip()
            if value and value not in collocations:
                collocations.append(value[:80])

        item = {
            "text": text[:300],
            "type": item_type,
            "phonetic": as_text(raw.get("phonetic") or "").strip()[:100],
            "pos": as_text(raw.get("pos") or "").strip()[:50],
            "meaning": as_text(raw.get("meaning") or "").strip()[:500],
            "usage": as_text(raw.get("usage") or "").strip()[:800],
            "collocations": collocations[:4],
            "example": as_text(raw.get("example") or "").strip()[:500],
            "example_zh": as_text(raw.get("example_zh") or "").strip()[:500],
        }
        items.append(item)

    intro = as_text(data.get("intro") or "").strip()[:500]
    return {"intro": intro or "我按条给你拆开讲：", "items": items}


__all__ = [
    "ask_practice_question",
    "ask_tutor",
    "ask_tutor_turn",
    "assess_practice_answer",
    "coach_practice_answer",
    "explain_vocabulary",
    "is_bare_lookup",
    "should_pause_coaching",
    "should_start_practice",
]
