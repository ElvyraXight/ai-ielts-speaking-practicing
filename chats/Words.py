# chats/Words.py

"""背单词页：目标计划 + 今日学习 + 复习巩固 + 已背过的词。

词库来自 Word Atlas（CC BY 4.0），见 assets/word-atlas-LICENSE.txt。
数据逻辑都在 utils/WordAtlas.py，这里只负责界面和会话状态。
"""

from datetime import date, timedelta

import streamlit as st

from utils.tts import cached_audio_path, existing_audio, speak
from utils.WordAtlas import (
    apply_review,
    build_drill_queue,
    build_queue,
    build_review_queue,
    cefr_options,
    check_answer,
    forget_word,
    load_progress,
    load_words,
    make_question,
    next_due,
    stats,
    target_plan,
    topic_label,
    topic_options,
    update_settings,
    word_by_id,
)

st.set_page_config(page_title="背单词 · Word Atlas", page_icon="📚", layout="wide")

st.title("📚 背单词")
st.caption(
    "词库来自 Word Atlas（7,298 个雅思词条，CC BY 4.0）：先认，再回忆，最后拼写。"
)

progress = load_progress()
settings = progress["settings"]
counts = stats(progress)


# ================= 侧边栏：目标与范围 =================
def _saved_target() -> date:
    try:
        saved = date.fromisoformat(settings["target_date"])
        if saved > date.today():
            return saved
    except (TypeError, ValueError):
        pass
    return date.today() + timedelta(days=180)


with st.sidebar:
    st.subheader("目标")

    use_target = st.checkbox(
        "按目标日期规划",
        value=bool(settings["target_date"]),
        key="wa_use_target",
        help="打开后按目标日期反推每天要学多少新词。",
    )
    if use_target:
        target = st.date_input(
            "目标日期",
            value=_saved_target(),
            min_value=date.today(),
            key="wa_target",
        )
        if str(target) != settings["target_date"]:
            update_settings(target_date=str(target))
            settings["target_date"] = str(target)
    else:
        target = None
        if settings["target_date"]:
            update_settings(target_date="")
            settings["target_date"] = ""

    start_cefr = st.selectbox(
        "起始难度",
        cefr_options(),
        index=cefr_options().index(settings["start_cefr"]),
        key="wa_start_cefr",
        help="只学这一级和更难的词，会记住你的选择。",
    )
    if start_cefr != settings["start_cefr"]:
        update_settings(start_cefr=start_cefr)
        settings["start_cefr"] = start_cefr

    topics = st.multiselect(
        "话题",
        list(topic_options()),
        default=settings["topics"],
        format_func=topic_label,
        placeholder="全部话题",
        key="wa_topics",
    )
    if topics != settings["topics"]:
        update_settings(topics=topics)
        settings["topics"] = topics

    plan = (
        target_plan(start_cefr=start_cefr, topics=topics, target_date=str(target))
        if target
        else None
    )
    if plan:
        st.caption(
            f"剩余 **{plan['remaining']}** 词 · **{plan['days']}** 天 · "
            f"每天 **{plan['per_day']}** 个"
        )
        if plan["per_day"] > 50:
            st.caption("目标偏紧：每天需要超过 50 个，建议把日期放宽。")
        if st.button("按目标设定每日新词", use_container_width=True):
            update_settings(new_per_day=max(1, min(50, plan["per_day"])))
            st.rerun()

    st.divider()
    new_per_day = st.slider(
        "每日新词",
        5,
        50,
        int(settings["new_per_day"]),
        1,
        help="只影响新词；到期复习不受这个数字限制。",
    )
    if new_per_day != int(settings["new_per_day"]):
        update_settings(new_per_day=new_per_day)
        settings["new_per_day"] = new_per_day

    st.divider()
    st.caption(
        f"已学 {counts['learned']} ｜ 待复习 {counts['due']} ｜ "
        f"今日 {counts['new_today']} 新 / {counts['review_today']} 复习"
    )
    st.caption("进度保存在 data/word_progress.json")
    st.caption(
        "[词库 Word Atlas](https://github.com/designfuchen/word-atlas) · CC BY 4.0"
    )


# ================= 通用 =================
def _play_word(word: dict) -> None:
    path = cached_audio_path(f"wa_{word['id']}.mp3")
    audio = existing_audio(path)
    if not audio:
        # 0 字节的旧缓存也当没缓存，重新合成。
        audio = existing_audio(speak(word["w"], output_file=path))
    if not audio:
        st.warning("发音生成失败（edge-tts 需要联网）")
        return
    st.audio(audio, autoplay=True)


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


def _queue_for(mode: str) -> list[str]:
    if mode == "review":
        return build_review_queue()
    if mode == "drill":
        return build_drill_queue(10)
    return build_queue()


def _reset_session(queue: list[str], mode: str) -> None:
    st.session_state.wa_queue = queue
    st.session_state.wa_mode = mode
    st.session_state.wa_pos = 0
    st.session_state.wa_question = None
    st.session_state.wa_answered = False
    st.session_state.wa_correct = False
    st.session_state.wa_given = ""
    st.session_state.wa_finished = False


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


def _render_question(question: dict, word: dict, pos: int, total: int) -> None:
    wid = question["word_id"]
    mode = question["mode"]
    st.progress(pos / total if total else 0.0, text=f"第 {pos + 1} / {total} 个")

    if mode in {"meaning", "recall"}:
        if mode == "meaning":
            st.markdown(f"## {word['w']}")
            st.caption(f"{word.get('uk') or ''} ｜ 选一个正确的意思")
            label = "选择意思"
        else:
            st.markdown(f"## {question['prompt']}")
            st.caption("哪一个英文单词对应这个意思？")
            label = "选择单词"
        choice = st.radio(
            label,
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

    st.markdown(f"## {question['prompt']}")
    if question.get("cloze"):
        st.markdown(f"> {question['cloze']}")
        st.caption("把空格补成完整的单词")
    else:
        st.caption("写出对应的英文单词")
    with st.form(key=f"wa_form_{wid}_{pos}"):
        typed = st.text_input(
            "拼写", key=f"wa_text_{wid}_{pos}", placeholder="type the word…"
        )
        submitted = st.form_submit_button(
            "提交",
            key=f"wa_submit_{wid}_{pos}",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not typed.strip():
            st.warning("先写一个答案")
        else:
            st.session_state.wa_answered = True
            st.session_state.wa_given = typed
            st.session_state.wa_correct = check_answer(question, typed)
            st.rerun()


# ================= 已背过的词 =================
def _render_learned() -> None:
    records = {
        word_id: record
        for word_id, record in progress["words"].items()
        if word_by_id(word_id) is not None
    }
    learning = sum(1 for record in records.values() if int(record.get("reps") or 0) < 3)
    mastered = sum(1 for record in records.values() if int(record.get("reps") or 0) >= 3)

    st.markdown(f"### 已背过 {len(records)} 个")
    col1, col2, col3 = st.columns(3)
    col1.metric("学习中", learning)
    col2.metric("已掌握", mastered)
    col3.metric("今天复习", counts["review_today"])

    if not records:
        st.info("还没有背过的词。切回「今日学习」开始第一组吧。")
        return

    query = st.text_input("🔍 搜索", placeholder="单词或中文意思", key="wa_learned_query")
    status = st.selectbox(
        "状态", ["全部", "学习中", "已掌握"], key="wa_learned_status"
    )

    rows = []
    for word_id, record in records.items():
        word = word_by_id(word_id) or {}
        reps = int(record.get("reps") or 0)
        if status == "学习中" and reps >= 3:
            continue
        if status == "已掌握" and reps < 3:
            continue
        haystack = " ".join(
            [str(word.get("w") or "")]
            + [str(sense.get("zh") or "") for sense in word.get("senses") or []]
        ).lower()
        if query.strip() and query.strip().lower() not in haystack:
            continue
        rows.append((str(record.get("last") or ""), word_id, word, record))

    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    st.caption(f"匹配 {len(rows)} 个" + ("，只显示最近复习的 100 个" if len(rows) > 100 else ""))

    for _, word_id, word, record in rows[:100]:
        first_zh = ""
        if word.get("senses"):
            first_zh = str(word["senses"][0].get("zh") or "")
        title = f"{word.get('w')}　{first_zh}"
        with st.expander(title, expanded=False):
            st.caption(
                f"复习 {int(record.get('reps') or 0)} 次 ｜ "
                f"间隔 {int(record.get('interval') or 0)} 天 ｜ "
                f"下次 {record.get('due') or '—'} ｜ "
                f"遗忘 {int(record.get('lapses') or 0)} 次"
            )
            _render_word_card(word)
            if st.button("🔊 听发音", key=f"wa_tts_learned_{word_id}"):
                _play_word(word)
            if st.button(
                "移出已背过（清空这个词的记录）",
                key=f"wa_forget_{word_id}",
                use_container_width=True,
            ):
                forget_word(word_id)
                st.rerun()


# ================= 视图切换 =================
view = st.segmented_control(
    "视图",
    ["今日学习", "已背过"],
    default="今日学习",
    key="wa_view",
    label_visibility="collapsed",
) or "今日学习"

if view == "已背过":
    _render_learned()
    st.stop()


# ================= 今日学习 =================
finished = st.session_state.get("wa_finished", False)
queue = st.session_state.get("wa_queue") or []

if not queue and not finished:
    remaining = max(0, int(settings["new_per_day"]) - counts["new_today"])
    st.markdown(
        f"**今天：{counts['due']} 个到期复习，还可学 {remaining} 个新词。**"
    )
    st.caption(
        f"范围：{start_cefr} 及以上"
        + (f" · {len(topics)} 个话题" if topics else " · 全部话题")
    )

    learn_col, review_col, drill_col = st.columns(3)
    if learn_col.button(
        "开始今日学习", type="primary", use_container_width=True, key="wa_start_daily"
    ):
        new_queue = build_queue()
        if not new_queue:
            st.warning("没有可学的词：今天的额度用完了，或筛选条件下没有词。")
        else:
            _reset_session(new_queue, "daily")
            st.rerun()

    if review_col.button(
        f"只复习到期（{counts['due']}）",
        use_container_width=True,
        key="wa_start_review",
        disabled=counts["due"] == 0,
    ):
        new_queue = build_review_queue()
        if new_queue:
            _reset_session(new_queue, "review")
            st.rerun()

    if drill_col.button(
        "巩固已学（10 个）",
        use_container_width=True,
        key="wa_start_drill",
        disabled=counts["learned"] == 0,
    ):
        new_queue = build_drill_queue(10)
        if new_queue:
            _reset_session(new_queue, "drill")
            st.rerun()

    hint = next_due()
    if hint:
        st.caption(f"下一次有词到期：{hint}")
    st.caption(
        "复习只练到期的词；巩固会从学过的词里挑最薄弱的 10 个，打乱顺序。"
    )
    st.stop()

if finished:
    mode_desc = {
        "daily": "今日学习",
        "review": "到期复习",
        "drill": "巩固练习",
    }.get(st.session_state.get("wa_mode", "daily"), "学习")
    st.success(f"{mode_desc}这一轮完成了。")
    col1, col2, col3 = st.columns(3)
    col1.metric("今日新词", counts["new_today"])
    col2.metric("今日复习", counts["review_today"])
    col3.metric("累计已学", counts["learned"])
    if st.button("再来一轮", type="primary", use_container_width=True):
        mode = st.session_state.get("wa_mode", "daily")
        new_queue = _queue_for(mode)
        if new_queue:
            _reset_session(new_queue, mode)
            st.rerun()
        else:
            st.info("这个模式暂时没有要练的词了。")
    hint = next_due()
    if hint:
        st.caption(f"下一次有词到期：{hint}")
    st.stop()

pos = int(st.session_state.get("wa_pos", 0))
if pos >= len(queue):
    st.session_state.wa_finished = True
    st.rerun()

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
