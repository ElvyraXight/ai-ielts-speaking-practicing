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
    daily_limit,
    exam_plan,
    forget_word,
    load_progress,
    load_words,
    make_question,
    next_due,
    stats,
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


# ================= 侧边栏：考试计划与范围 =================
def _open_plan_dialog() -> None:
    """把当前计划放进取值状态，再打开设置对话框。"""
    st.session_state["wa_plan_open"] = True
    st.session_state["wa_plan_band"] = float(settings["target_band"])
    st.session_state["wa_plan_auto"] = bool(settings["auto_plan"])
    try:
        saved = date.fromisoformat(settings["exam_date"])
    except (TypeError, ValueError):
        saved = date.today() + timedelta(days=180)
    # 考试日期已过时 date_input 会低于 min_value，往后放一天。
    st.session_state["wa_plan_date"] = max(saved, date.today())
    st.rerun()


def _close_plan_dialog() -> None:
    st.session_state.pop("wa_plan_open", None)
    st.rerun()


def _clear_plan_date() -> None:
    """按钮回调里清空日期：回调先于控件实例化，才能改 widget state。"""
    st.session_state["wa_plan_date"] = None


@st.dialog("设置考试计划", width="large")
def _plan_dialog() -> None:
    """复刻 Word Atlas 的考试计划：日期 + 目标分数 + 自动排每日新词。"""
    st.caption("按考试日期安排每日新词，考前预留复习时间。")
    today = date.today()
    pending_date = st.session_state.get("wa_plan_date")
    if isinstance(pending_date, date) and pending_date < today:
        st.session_state["wa_plan_date"] = today
    date_col, clear_col = st.columns([2, 1], vertical_alignment="bottom")
    with date_col:
        exam_date = st.date_input(
            "考试日期",
            value=st.session_state.get("wa_plan_date"),
            min_value=today,
            key="wa_plan_date",
            format="YYYY/MM/DD",
        )
        st.caption("日期未定可以留空。")
    with clear_col:
        st.button(
            "暂不设置",
            key="wa_plan_no_date",
            on_click=_clear_plan_date,
            use_container_width=True,
        )

    st.divider()
    st.markdown("**目标分数**")
    st.caption("用于推荐学习范围，可随时调整。")
    band = float(st.session_state.get("wa_plan_band") or settings["target_band"])
    minus_col, band_col, plus_col = st.columns([1, 2, 1], vertical_alignment="center")
    with minus_col:
        if st.button("−", key="wa_band_down", use_container_width=True):
            st.session_state["wa_plan_band"] = max(4.0, band - 0.5)
            st.rerun()
    with band_col:
        st.markdown(
            "<div style='text-align:center;font-size:1.7rem;font-weight:600'>"
            f"{band:g}</div>",
            unsafe_allow_html=True,
        )
    with plus_col:
        if st.button("＋", key="wa_band_up", use_container_width=True):
            st.session_state["wa_plan_band"] = min(9.0, band + 0.5)
            st.rerun()

    st.divider()
    auto = st.toggle(
        "自动安排每日新词",
        key="wa_plan_auto",
        help="自动计划按考试日期调整每日新词。",
    )
    st.caption("自动计划按考试日期调整每日新词。")

    date_text = str(exam_date) if exam_date else ""
    plan = exam_plan(band=band, exam_date=date_text)
    if plan["set"]:
        advice = (
            f"目标 {band:g} 分，参考范围是 **{plan['range']}** 的 "
            f"{plan['total']:,} 个词，已学 {plan['learned']} 个。"
        )
        if plan["remaining"] == 0:
            advice += "这个范围已经学完，最后几天专心复习即可。"
        elif plan["days"] <= plan["review_days"]:
            advice += (
                f"还剩 {plan['days']} 天，已进入复习期："
                f"最后 {plan['review_days']} 天只复习，不再排新词。"
            )
        else:
            advice += (
                f"还剩 {plan['days']} 天，最后 {plan['review_days']} 天只复习，"
                f"算下来每天约 **{plan['per_day']}** 个新词。"
            )
            if plan["per_day"] > 50:
                advice += "目标偏紧：自动模式每天最多排 50 个，建议把日期放宽。"
    else:
        advice = (
            f"目标 {band:g} 分，参考范围是 **{plan['range']}** 的 "
            f"{plan['total']:,} 个词，已学 {plan['learned']} 个。"
            "设置考试日期后可以算出每天要学几个。"
        )
    st.info(advice)
    st.caption("这是本产品的选词建议，不是官方分数要求，也不代表达到目标分数。")

    st.divider()
    cancel_col, save_col = st.columns(2)
    if cancel_col.button("取消", key="wa_plan_cancel", use_container_width=True):
        _close_plan_dialog()
    if save_col.button(
        "保存", key="wa_plan_save", type="primary", use_container_width=True
    ):
        update_settings(
            exam_date=str(exam_date) if exam_date else "",
            target_band=band,
            auto_plan=auto,
        )
        st.session_state.pop("wa_plan_open", None)
        st.toast("考试计划已保存")
        st.rerun()


with st.sidebar:
    st.subheader("🎯 考试计划")
    plan = exam_plan()
    if plan["set"]:
        st.caption(f"{plan['target']} · 目标 {plan['band']:g} 分（{plan['range']}）")
        if plan["remaining"] == 0:
            st.caption("范围已经学完，接下来只复习。")
        elif plan["days"] <= plan["review_days"]:
            st.caption(f"还剩 {plan['days']} 天 · 进入考前复习期，不再排新词")
        else:
            st.caption(
                f"还剩 {plan['days']} 天 · 最后 {plan['review_days']} 天只复习 · "
                f"每天约 {plan['per_day']} 个"
                + ("（上限 50）" if plan["per_day"] > 50 else "")
            )
    else:
        st.caption("还没设置考试日期；每日新词按手动值。")
    if st.button("📅 设置考试计划", key="wa_open_plan", use_container_width=True):
        _open_plan_dialog()

    st.divider()
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

    st.divider()
    if settings["auto_plan"] and plan["set"]:
        st.caption(f"每日新词：自动 **{daily_limit()}** 个（按考试计划）")
        st.caption("想手动调整，就在考试计划里关掉「自动安排每日新词」。")
    else:
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
        if settings["auto_plan"]:
            st.caption("自动计划需要先设置考试日期，当前按手动值。")

    st.divider()
    st.caption(
        f"已学 {counts['learned']} ｜ 待复习 {counts['due']} ｜ "
        f"今日 {counts['new_today']} 新 / {counts['review_today']} 复习"
    )
    st.caption("进度保存在 data/word_progress.json")
    st.caption(
        "[词库与考试计划参考 Word Atlas]"
        "(https://github.com/designfuchen/word-atlas) · "
        "词库 CC BY 4.0 · 代码 MIT"
    )
    with st.expander("⚖️ 版权与致谢", expanded=False):
        st.markdown(
            "- 词库 `assets/word-atlas.json`：[Word Atlas]"
            "(https://github.com/designfuchen/word-atlas)，CC BY 4.0。\n"
            "- 本页「考试计划」的分数区间、最后 7 天只复习、每日新词换算法"
            "参考该项目的考试计划。\n"
            "- 背景音播放器 `utils/Ambient.py` 移植自其 `src/lib/sound.ts`（MIT）。\n"
            "- 完整声明见仓库根目录 `THIRD_PARTY_NOTICES.md`。"
        )

if st.session_state.get("wa_plan_open"):
    _plan_dialog()


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
        heading = f"{pos} {zh}".strip()
        if heading:
            st.markdown(f"**{heading}**")
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
    remaining = max(0, daily_limit() - counts["new_today"])
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
