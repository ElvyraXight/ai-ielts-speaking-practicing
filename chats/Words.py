# chats/Words.py

"""背单词页：今日计划 + 词卡 + 三种主动回忆。

词库来自 Word Atlas（CC BY 4.0），见 assets/word-atlas-LICENSE.txt。
数据逻辑都在 utils/WordAtlas.py，这里只负责界面和会话状态。
"""

import asyncio
import os

import streamlit as st

from utils.Part2 import generate_audio
from utils.WordAtlas import (
    apply_review,
    build_queue,
    cefr_options,
    check_answer,
    load_progress,
    load_words,
    make_question,
    next_due,
    set_new_per_day,
    stats,
    topic_label,
    topic_options,
    word_by_id,
)

st.set_page_config(page_title="背单词 · Word Atlas", page_icon="📚", layout="wide")

st.title("📚 背单词")
st.caption(
    "词库来自 Word Atlas（7,298 个雅思词条，CC BY 4.0）：先认，再回忆，最后拼写。"
)

progress = load_progress()
counts = stats(progress)

# ================= 侧边栏 =================
with st.sidebar:
    st.subheader("今日设置")
    new_per_day = st.slider(
        "每天新词",
        5,
        30,
        int(progress["settings"]["new_per_day"]),
        1,
        help="只影响还没学过的词；到期复习不受这个数字限制。",
    )
    if new_per_day != int(progress["settings"]["new_per_day"]):
        set_new_per_day(new_per_day)
        st.rerun()

    levels = st.multiselect(
        "CEFR 难度", cefr_options(), default=[], placeholder="全部难度"
    )
    topics = st.multiselect(
        "话题",
        list(topic_options()),
        default=[],
        format_func=topic_label,
        placeholder="全部话题",
    )

    st.divider()
    st.caption(
        f"已学 {counts['learned']} ｜ 待复习 {counts['due']} ｜ "
        f"今日 {counts['new_today']} 新 / {counts['review_today']} 复习"
    )
    st.caption("进度保存在 data/word_progress.json")
    st.caption(
        "[词库 Word Atlas](https://github.com/designfuchen/word-atlas) · CC BY 4.0"
    )


# ================= 状态 =================
def _reset_session(queue: list[str]) -> None:
    st.session_state.wa_queue = queue
    st.session_state.wa_pos = 0
    st.session_state.wa_question = None
    st.session_state.wa_answered = False
    st.session_state.wa_correct = False
    st.session_state.wa_given = ""
    st.session_state.wa_finished = False
    st.session_state.wa_correct_total = 0


def _advance(grade: str | None = None) -> None:
    queue = st.session_state.get("wa_queue") or []
    pos = st.session_state.get("wa_pos", 0)
    if grade and pos < len(queue):
        apply_review(queue[pos], grade)
    st.session_state.wa_pos = pos + 1
    st.session_state.wa_question = None
    st.session_state.wa_answered = False
    st.session_state.wa_correct = False
    st.session_state.wa_given = ""
    if pos + 1 >= len(queue):
        st.session_state.wa_finished = True
    st.rerun()


def _play_word(word: dict) -> None:
    path = f"audio_records/wa_{word['id']}.mp3"
    if not os.path.exists(path):
        try:
            asyncio.run(generate_audio(word["w"], path))
        except Exception:
            st.warning("发音生成失败（edge-tts 需要联网）")
            return
    st.audio(path, autoplay=True)


def _render_word_card(word: dict, *, show_word: bool = True) -> None:
    if show_word:
        st.markdown(f"### {word['w']}")
    st.caption(
        f"{word.get('uk') or ''} ｜ {word.get('us') or ''} ｜ "
        f"{word.get('cefr') or ''} · {topic_label(word.get('topic') or '')}"
    )
    for sense in word.get("senses") or []:
        pos = sense.get("pos") or ""
        zh = sense.get("zh") or ""
        st.markdown(f"**{pos} {zh}**".strip())
        if sense.get("en"):
            st.caption(sense["en"])

    for example in word.get("ex") or []:
        st.markdown(f"> {example.get('en', '')}")
        if example.get("zh"):
            st.caption(example["zh"])

    if word.get("col"):
        pairs = []
        for item in word["col"]:
            english, _, chinese = str(item).partition("｜")
            pairs.append(f"{english}（{chinese}）" if chinese else english)
        st.markdown("**搭配**：" + "；".join(pairs))

    extras = []
    if word.get("fam"):
        extras.append("词族：" + "、".join(word["fam"]))
    if word.get("syn"):
        extras.append("近义：" + "、".join(word["syn"]))
    if word.get("ant"):
        extras.append("反义：" + "、".join(word["ant"]))
    if extras:
        st.caption(" ｜ ".join(extras))

    if word.get("tip"):
        st.info(f"💡 {word['tip']}")
    if word.get("note"):
        st.caption(f"注意：{word['note']}")


def _render_question(question: dict, word: dict, pos: int, total: int) -> None:
    wid = question["word_id"]
    mode = question["mode"]
    st.progress(pos / total if total else 0.0, text=f"第 {pos + 1} / {total} 个")

    if mode == "meaning":
        st.markdown(f"## {word['w']}")
        st.caption(f"{word.get('uk') or ''} ｜ 选一个正确的意思")
        choice = st.radio(
            "选择意思",
            question["options"],
            index=None,
            key=f"wa_opt_{wid}_{pos}",
            label_visibility="collapsed",
        )
        if st.button(
            "提交", key=f"wa_submit_{wid}_{pos}", type="primary", use_container_width=True
        ):
            if not choice:
                st.warning("先选一个再提交")
            else:
                st.session_state.wa_answered = True
                st.session_state.wa_given = choice
                st.session_state.wa_correct = check_answer(question, choice)
                st.rerun()
        return

    if mode == "recall":
        st.markdown(f"## {question['prompt']}")
        st.caption("哪一个英文单词对应这个意思？")
        choice = st.radio(
            "选择单词",
            question["options"],
            index=None,
            key=f"wa_opt_{wid}_{pos}",
            label_visibility="collapsed",
        )
        if st.button(
            "提交", key=f"wa_submit_{wid}_{pos}", type="primary", use_container_width=True
        ):
            if not choice:
                st.warning("先选一个再提交")
            else:
                st.session_state.wa_answered = True
                st.session_state.wa_given = choice
                st.session_state.wa_correct = check_answer(question, choice)
                st.rerun()
        return

    # spell
    st.markdown(f"## {question['prompt']}")
    if question.get("cloze"):
        st.markdown(f"> {question['cloze']}")
        st.caption("把空格补成完整的单词")
    else:
        st.caption("写出对应的英文单词")
    typed = st.text_input(
        "拼写", key=f"wa_text_{wid}_{pos}", placeholder="type the word…"
    )
    if st.button(
        "提交", key=f"wa_submit_{wid}_{pos}", type="primary", use_container_width=True
    ):
        if not typed.strip():
            st.warning("先写一个答案")
        else:
            st.session_state.wa_answered = True
            st.session_state.wa_given = typed
            st.session_state.wa_correct = check_answer(question, typed)
            st.rerun()


# ================= 主界面 =================
finished = st.session_state.get("wa_finished", False)
queue = st.session_state.get("wa_queue") or []

if not queue and not finished:
    remaining = max(0, int(progress["settings"]["new_per_day"]) - counts["new_today"])
    st.markdown(
        f"**今天：{counts['due']} 个到期复习，还可学 {remaining} 个新词。**"
    )
    if st.button("开始学习", type="primary", use_container_width=True):
        new_queue = build_queue(cefr=levels, topics=topics)
        if not new_queue:
            st.warning("没有可学的词：今天的额度用完了，或筛选条件下没有词。")
        else:
            _reset_session(new_queue)
            st.rerun()
    hint = next_due()
    if hint:
        st.caption(f"下一次有词到期：{hint}")
    st.caption("先看词选意思，再看着中文回忆，最后用例句填空拼写；答完给自己打分决定下次时间。")
    st.stop()

if finished:
    st.success("这一轮完成了。")
    col1, col2, col3 = st.columns(3)
    col1.metric("今日新词", counts["new_today"])
    col2.metric("今日复习", counts["review_today"])
    col3.metric("累计已学", counts["learned"])
    if st.button("再来一轮", type="primary", use_container_width=True):
        _reset_session(build_queue(cefr=levels, topics=topics))
        st.rerun()
    hint = next_due()
    if hint:
        st.caption(f"下一次有词到期：{hint}")
    st.stop()

pos = int(st.session_state.get("wa_pos", 0))
wid = queue[pos]
word = word_by_id(wid)
if word is None:
    _advance()
    st.stop()

question = st.session_state.get("wa_question")
if not question or question.get("word_id") != wid:
    record = progress["words"].get(wid) or {}
    question = make_question(word, load_words(), int(record.get("reps") or 0))
    st.session_state.wa_question = question

if not st.session_state.get("wa_answered"):
    _render_question(question, word, pos, len(queue))
else:
    if st.session_state.get("wa_correct"):
        st.success(f"✅ 答对了：{question['answer']}")
    else:
        st.error(
            f"❌ 正确答案：{question['answer']}"
            f"（你写的是 {st.session_state.get('wa_given') or '空'}）"
        )
    _render_word_card(word, show_word=True)
    if st.button("🔊 听发音", key=f"wa_tts_{wid}_{pos}", use_container_width=True):
        _play_word(word)

    st.markdown("**这个词你记得怎么样？**")
    again, hard, good, easy = st.columns(4)
    if again.button("😵 忘了", key=f"wa_rate_again_{wid}_{pos}", use_container_width=True):
        _advance("again")
    if hard.button("🤔 模糊", key=f"wa_rate_hard_{wid}_{pos}", use_container_width=True):
        _advance("hard")
    if good.button("✅ 记得", key=f"wa_rate_good_{wid}_{pos}", use_container_width=True):
        _advance("good")
    if easy.button("🚀 太简单", key=f"wa_rate_easy_{wid}_{pos}", use_container_width=True):
        _advance("easy")
