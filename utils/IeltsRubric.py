# utils/IeltsRubric.py

"""雅思口语「什么样的答案算好」的统一口径。

这些文字会被拼进所有需要评价答案的 prompt：严肃话题的三栏反馈、讲个故事的
评估与范文、老师的陪练点评、老师帮帮我的提示，以及参考回答的生成。

集中在一处，是为了避免每个 prompt 各写一套长度要求——以前 Part 1 有的地方写
"2-4 句"，有的地方又暗示越长越好，模型就会给出互相矛盾的反馈。

**开场介绍不是 Part 1。** 名字、怎么称呼、ID 核对这些发生在任何分段开始之前；
这个 App 允许直接从 Part 3 开始，那时开场照样先走一遍。所以它单独成段（INTRO），
标准只有一条：一句完整、礼貌的话，不需要额外细节。
"""

from __future__ import annotations

INTRO = """IELTS SPEAKING — THE INTRODUCTION (this is NOT Part 1)
The introduction happens at the start of every test, before whichever part the candidate
practises — before Part 1, and also before Part 3 when the candidate starts from Part 3.
Typical questions: greeting, "What's your full name?", "What would you like me to call you?",
"Can I see your ID please?", "Where are you from?"
- Requirement: ONE short, complete, polite sentence. Detail is NOT required here.
- Good: "You can call me Elvira."
- Good: "My full name is Elvira Yang, but Elvira is fine."
- Good: "I'm from Chengdu, in the southwest of China." — one orientation clause is plenty.
- Bad: "Elvira." — a fragment is too abrupt; answer with a sentence.
- Bad: "Well, my name has quite an interesting history, because my grandmother..." — over-answering the introduction.
- Judging rule: never ask for reasons, feelings or extra detail here, and never call a complete
  short sentence "too short". Do not apply Part 1 topic rules to these questions, and do not
  apply this rule to Part 1 topic questions."""

PART1 = """IELTS SPEAKING PART 1 — TOPIC QUESTIONS (home, work, study, hobbies, music, food, weather, transport, daily routine)
- Length: 2-3 sentences, about 20-30 seconds, roughly 25-45 words.
- Shape: a direct answer, then ONE specific reason, example or detail.
- Good: "I usually walk to work, about twenty minutes. It's the only exercise I get, and I like the streets before the city wakes up."
- Good (a "no" answer still gets developed): "Not really — I tried once but I'm hopeless at it. My friends still tease me about it."
- Bad: "Yes." or "I like music." — no development, so Fluency and Coherence fails.
- Bad: "Music is a controversial issue. There are many advantages and disadvantages." — essay or memorised register.
- Bad: answering a different question, or just repeating the question back as the answer.
- Bad: a Part 3 style abstract argument squeezed into a Part 1 slot.
- Bad: bolting two extra layers of meaning onto a question that only needed one detail."""

PART2 = """IELTS SPEAKING PART 2 (LONG TURN) — WHAT A GOOD ANSWER LOOKS LIKE
- Length: 1.5-2 minutes, about 180-250 words. Under 1 minute is clearly under-length; past 2.5 minutes the examiner cuts you off.
- Shape: set the scene (what / when / where / who, in past tenses), then 2-3 concrete details or one small story with a turning point, then how you felt and why it mattered (a present feeling is natural), then one short closing reflection.
- Cover EVERY bullet point on the card. The final "explain why..." bullet is the one candidates forget.
- Good: one specific event, real people and places, sensory detail, clean past tenses, one moment that changed something.
- Bad: a list of general facts with no story ("I often go to the park. Parks are good for people.").
- Bad: tense drift — narrating a past event in the present tense; or no answer to the last bullet.
- Bad: a memorised opening ("Today I would like to talk about...") that spends twenty seconds and says nothing.
- Bad: reading the cue card back as sentences instead of answering it."""

PART3 = """IELTS SPEAKING PART 3 — WHAT A GOOD ANSWER LOOKS LIKE
- Length: 30-60 seconds, 4-6 sentences, about 60-100 words. One sentence is not enough.
- Shape: a position, then a reason, then an example or a comparison (different people, places or times), then optionally a concession ("although...") or a return to the question.
- Good: "In general yes, though it depends on the city. In big cities people are busier, so families eat together less. My cousin in Shanghai, for instance... Overall I'd say..."
- Good: compare two groups or two eras, then say which side you are on and why.
- Bad: only a personal anecdote ("my friend did this once") with no general point.
- Bad: absolute claims with no nuance, or four undeveloped ideas in a row.
- Bad: restating the question in different words instead of answering it."""

CROSS = """WHAT EXAMINERS REWARD AND WHAT THEY PENALISE
- Length is judged per question type, never by one global number:
  introduction/identity (before any part) = 1 sentence; Part 1 topic = 2-3 sentences;
  Part 3 = 4-6 sentences; Part 2 = 1.5-2 minutes.
  Never apply one type's length to another, and never upgrade a complete short answer just to make it longer.
- Rewarded: a direct answer developed with something concrete; natural spoken linking (actually, to be honest, the thing is) used sparingly; range used accurately; simple grammar with very few errors.
- Penalised: memorised language that does not fit the question (this alone can cap the score around Band 5.5-6); ignoring part of the question; one-clause answers with no development; repeated basic errors (tense, articles, subject-verb agreement) that make the listener work; long answers that drift off topic.
- Judge an answer against the part it was given in: never demand Part 3 depth in Part 1, and never accept Part 1 brevity in Part 3.
- Never comment on pronunciation, accent, stress or speed. There is no audio; only text."""

EXAM = "\n\n".join((INTRO, PART1, PART3, CROSS))
ALL = "\n\n".join((INTRO, PART1, PART2, PART3, CROSS))


def for_part(part: str) -> str:
    """按分段取口径。

    - part2：长回合，只有 PART2 + 通用规则（Part 2 没有开场介绍）。
    - 其余（Part 1 / Part 3 / 未知）：开场介绍 + Part 1 + Part 3 + 通用规则，
      因为这个 App 的考官页可以在 Part 1 和 Part 3 之间切换，而且选 Part 3 时
      开头仍然要走身份介绍。
    """
    if str(part or "").strip().lower() in ("part2", "part 2", "p2"):
        return "\n\n".join((PART2, CROSS))
    return EXAM


__all__ = ["ALL", "CROSS", "EXAM", "INTRO", "PART1", "PART2", "PART3", "for_part"]
