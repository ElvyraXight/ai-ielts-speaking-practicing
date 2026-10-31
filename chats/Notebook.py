# chats/Notebook.py

import json

import streamlit as st

from utils import NotebookSync
from utils.Expressions import render_expressions
from utils.LongNotes import render_long_notes
from utils.Notebook import (
    add_entry,
    backfill_entries,
    delete_entry,
    load_entries,
    order_by_relevance,
    record_review,
    refresh_entry_examples,
    review_due_count,
    review_entries,
    search_entries,
    stats,
    update_entry,
)
from utils.WordAtlas import check_answer, make_question

st.set_page_config(page_title="我的笔记本", page_icon="📓", layout="wide")

st.title("📓 我的笔记本")
st.caption(
    "单词 / 词组会自动补全词性、标签和每个义项的例句；表达库记录「想表达的意思 → 地道说法」，"
    "用中文提示做产出复习；仓库便签条按日期归档，标题可留空由 AI 生成。"
)

if st.session_state.get("nb_mode") in ("长文本", "长文本笔记"):
    st.session_state["nb_mode"] = "仓库"

notebook_mode = st.segmented_control(
    "笔记类型",
    ["单词 / 词组", "表达", "仓库"],
    default="单词 / 词组",
    key="nb_mode",
    label_visibility="collapsed",
) or "单词 / 词组"

if notebook_mode == "仓库":
    render_long_notes()
    st.stop()

if notebook_mode == "表达":
    render_expressions()
    st.stop()


# ================= 单词复习（和背单词同一套逻辑） =================
def _entry_as_word(entry: dict) -> dict:
    senses = []
    for sense in entry.get("senses") or []:
        zh = str(sense.get("zh") or sense.get("meaning") or "").strip()
        if not zh:
            continue
        senses.append(
            {
                "pos": sense.get("pos") or "",
                "zh": zh,
                "example": sense.get("example") or "",
            }
        )
    if not senses:
        senses = [
            {
                "pos": "",
                "zh": entry.get("meaning") or "",
                "example": entry.get("example") or "",
            }
        ]
    examples = [
        {"en": sense.get("example") or "", "zh": ""}
        for sense in senses
        if sense.get("example")
    ]
    if not examples and entry.get("example"):
        examples = [{"en": entry["example"], "zh": ""}]
    return {
        "id": entry["id"],
        "w": entry["term"],
        "senses": senses,
        "ex": examples,
        "cefr": None,
    }


def _render_word_entry(entry: dict) -> None:
    st.markdown(f"### {entry['term']}")
    if entry.get("meaning"):
        st.markdown(entry["meaning"])
    for sense in entry.get("senses") or []:
        if sense.get("example"):
            st.caption(sense["example"])
    st.caption(
        f"标签：{'、'.join(entry.get('tags') or []) or '—'}"
        f" ｜ 来源：{entry.get('source') or '—'}"
    )


def _reset_word_review(queue: list[str]) -> None:
    st.session_state.nb_rv_queue = queue
    st.session_state.nb_rv_pos = 0
    st.session_state.nb_rv_question = None
    st.session_state.nb_rv_answered = False
    st.session_state.nb_rv_given = ""
    st.session_state.nb_rv_correct = False
    st.session_state.nb_rv_finished = False


def _advance_word_review(grade: str | None = None) -> None:
    queue = st.session_state.get("nb_rv_queue") or []
    pos = st.session_state.get("nb_rv_pos", 0)
    if grade and pos < len(queue):
        record_review(queue[pos], grade)
    st.session_state.nb_rv_pos = pos + 1
    st.session_state.nb_rv_question = None
    st.session_state.nb_rv_answered = False
    st.session_state.nb_rv_given = ""
    st.session_state.nb_rv_correct = False
    if pos + 1 >= len(queue):
        st.session_state.nb_rv_finished = True
    st.rerun()


def _render_word_review() -> None:
    entries = load_entries()
    if not entries:
        st.info("词库是空的。切到「单词表」先加几个词。")
        return

    due = review_due_count()
    queue = st.session_state.get("nb_rv_queue") or []
    finished = st.session_state.get("nb_rv_finished", False)

    if not queue and not finished:
        st.markdown(f"**今天待复习 {due} 个，词库共 {len(entries)} 个。**")
        st.caption(
            "先看词选义，再看着中文回忆，最后用例句填空拼写；"
            "答完自评，按词光的间隔逻辑排下一次。"
        )
        if st.button(
            f"开始复习（{due}）",
            type="primary",
            use_container_width=True,
            key="nb_rv_start",
            disabled=due == 0,
        ):
            _reset_word_review([entry["id"] for entry in review_entries(30)])
            st.rerun()
        if due == 0:
            st.success("今天没有到期的词。")
        return

    if finished or st.session_state.get("nb_rv_pos", 0) >= len(queue):
        st.success("这一轮复习完成。")
        if st.button(
            "再来一轮",
            type="primary",
            use_container_width=True,
            key="nb_rv_again",
        ):
            _reset_word_review([entry["id"] for entry in review_entries(30)])
            st.rerun()
        return

    pos = st.session_state.get("nb_rv_pos", 0)
    entry = next((item for item in entries if item["id"] == queue[pos]), None)
    if entry is None:
        _advance_word_review()
        return

    question = st.session_state.get("nb_rv_question")
    if not question or question.get("word_id") != entry["id"]:
        pool = [_entry_as_word(item) for item in entries]
        question = make_question(
            _entry_as_word(entry), pool, int(entry["review"].get("reps") or 0)
        )
        st.session_state.nb_rv_question = question

    st.progress(pos / len(queue), text=f"第 {pos + 1} / {len(queue)} 个")
    if st.session_state.get("nb_rv_answered"):
        _render_word_review_result(entry, question)
        return

    mode = question["mode"]

    if mode in {"meaning", "recall"}:
        if mode == "meaning":
            st.markdown(f"## {entry['term']}")
            st.caption("选一个正确的意思")
            label = "选择意思"
        else:
            st.markdown(f"## {question['prompt']}")
            st.caption("哪一个英文对应这个意思？")
            label = "选择单词"
        choice = st.radio(
            label,
            question["options"],
            index=None,
            key=f"nb_rv_opt_{entry['id']}_{pos}",
            label_visibility="collapsed",
        )
        if st.button(
            "提交",
            key=f"nb_rv_submit_{entry['id']}_{pos}",
            type="primary",
            use_container_width=True,
        ):
            if not choice:
                st.warning("先选一个再提交")
            else:
                st.session_state.nb_rv_answered = True
                st.session_state.nb_rv_given = choice
                st.session_state.nb_rv_correct = check_answer(question, choice)
                st.rerun()
        return

    st.markdown(f"## {question['prompt']}")
    if question.get("cloze"):
        st.markdown(f"> {question['cloze']}")
        st.caption("把空格补成完整的单词")
    else:
        st.caption("写出对应的英文单词")
    with st.form(key=f"nb_rv_form_{entry['id']}_{pos}"):
        typed = st.text_input(
            "拼写",
            key=f"nb_rv_text_{entry['id']}_{pos}",
            placeholder="type the word…",
        )
        submitted = st.form_submit_button(
            "提交",
            key=f"nb_rv_submit_{entry['id']}_{pos}",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not typed.strip():
            st.warning("先写一个答案")
        else:
            st.session_state.nb_rv_answered = True
            st.session_state.nb_rv_given = typed
            st.session_state.nb_rv_correct = check_answer(question, typed)
            st.rerun()


def _render_word_review_result(entry: dict, question: dict) -> None:
    if st.session_state.get("nb_rv_correct"):
        st.success(f"✅ 答对了：{question['answer']}")
    else:
        st.error(
            f"❌ 正确答案：{question['answer']}"
            f"（你写的是 {st.session_state.get('nb_rv_given') or '空'}）"
        )
    _render_word_entry(entry)

    st.markdown("**这个词你记得怎么样？**")
    again, hard, good, easy = st.columns(4)
    if again.button(
        "😵 忘了", key=f"nb_rv_again_btn_{entry['id']}", use_container_width=True
    ):
        _advance_word_review("again")
    if hard.button(
        "🤔 模糊", key=f"nb_rv_hard_btn_{entry['id']}", use_container_width=True
    ):
        _advance_word_review("hard")
    if good.button(
        "✅ 记得", key=f"nb_rv_good_btn_{entry['id']}", use_container_width=True
    ):
        _advance_word_review("good")
    if easy.button(
        "🚀 太简单", key=f"nb_rv_easy_btn_{entry['id']}", use_container_width=True
    ):
        _advance_word_review("easy")

if st.session_state.get("nb_flash"):
    st.success(st.session_state.nb_flash)
    st.session_state.nb_flash = ""

entries = load_entries()

word_view = st.segmented_control(
    "单词视图",
    ["复习", "单词表"],
    default="复习",
    key="nb_word_view",
    label_visibility="collapsed",
) or "复习"

if word_view == "复习":
    _render_word_review()
    st.stop()

counts = stats(entries)

col1, col2, col3, col4 = st.columns(4)
col1.metric("总条目", counts["total"])
col2.metric("近 7 天新增", counts["week"])
col3.metric("标签数", counts["tags"])
col4.metric("有例句", counts["with_example"])

with st.expander("➕ 新增一条", expanded=(counts["total"] == 0)):
    st.caption("只填单词 / 词组和例句；意思、词性和标签会自动补全。")
    with st.form("nb_add_form", clear_on_submit=True):
        term = st.text_input(
            "单词 / 词组 *",
            key="nb_add_term",
            placeholder="e.g. take ... for granted",
        )
        example = st.text_area(
            "例句（可选，每行一个，按义项顺序）", key="nb_add_example", height=90
        )
        if st.form_submit_button(
            "保存到笔记本", type="primary", use_container_width=True
        ):
            if not term.strip():
                st.warning("单词 / 词组不能为空")
            else:
                with st.spinner("正在补全翻译 / 标签 / 例句..."):
                    entry = add_entry(
                        term,
                        example=example,
                        source="手动添加",
                    )
                st.session_state.nb_flash = (
                    f"已保存：{entry['term']} ｜ {entry['meaning'] or '待补充'}"
                )
                st.rerun()

st.divider()

col_query, col_sort, col_tag = st.columns([2.4, 1, 1.4])
query = col_query.text_input(
    "🔍 搜索", placeholder="单词、意思、例句或标签", key="nb_query"
)
sort_options = ["语义相关", "最近添加", "最近更新", "字母顺序"]
if st.session_state.get("nb_sort") not in sort_options:
    st.session_state.nb_sort = "语义相关"
sort_by = col_sort.selectbox("排序", sort_options, key="nb_sort")
all_tags = sorted({tag for entry in entries for tag in entry["tags"]})
tag_filter = col_tag.multiselect("标签筛选", all_tags, key="nb_tag_filter")

filtered = search_entries(entries, query)
if tag_filter:
    filtered = [
        entry for entry in filtered if any(tag in entry["tags"] for tag in tag_filter)
    ]
if sort_by == "最近更新":
    filtered.sort(key=lambda entry: entry["updated_at"], reverse=True)
elif sort_by == "最近添加":
    filtered.sort(key=lambda entry: entry["created_at"], reverse=True)
elif sort_by == "字母顺序":
    filtered.sort(key=lambda entry: entry["term"].lower())
else:
    filtered = order_by_relevance(filtered)

st.markdown(f"**📚 全部笔记（{len(filtered)}）**")


def render_entry(entry: dict) -> None:
    editing = st.session_state.get("nb_edit_entry_id") == entry["id"]
    deleting = st.session_state.get("nb_delete_entry_id") == entry["id"]
    focused = st.session_state.get("nb_focus_entry") == entry["id"]
    with st.expander(entry["term"], expanded=editing or deleting or focused):
        if deleting:
            st.warning(f"确定要删除「{entry['term']}」吗？")
            if entry["meaning"]:
                st.caption(entry["meaning"])
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button(
                "确认删除",
                type="primary",
                key=f"nb_del_yes_{entry['id']}",
                use_container_width=True,
            ):
                old_term, old_meaning = entry["term"], entry["meaning"]
                delete_entry(entry["id"])
                NotebookSync.after_notebook_delete(old_term, old_meaning)
                st.session_state.nb_edit_entry_id = None
                st.session_state.nb_delete_entry_id = None
                if st.session_state.get("nb_focus_entry") == entry["id"]:
                    st.session_state.pop("nb_focus_entry", None)
                st.session_state.nb_flash = f"已删除：{entry['term']}"
                st.rerun()
            if cancel_col.button(
                "取消删除",
                key=f"nb_del_no_{entry['id']}",
                use_container_width=True,
            ):
                st.session_state.nb_delete_entry_id = None
                st.session_state.nb_focus_entry = entry["id"]
                st.rerun()
        elif editing:
            current_examples = [
                sense["example"]
                for sense in entry.get("senses", [])
                if sense.get("example")
            ] or ([entry["example"]] if entry["example"] else [])
            with st.form(f"nb_edit_{entry['id']}"):
                edit_col1, edit_col2 = st.columns(2)
                new_term = edit_col1.text_input(
                    "单词 / 词组", value=entry["term"], key=f"nb_et_{entry['id']}"
                )
                new_meaning = edit_col2.text_input(
                    "中文意思 / 词性", value=entry["meaning"], key=f"nb_em_{entry['id']}"
                )
                new_example = st.text_area(
                    "例句（每行一个，按义项顺序）",
                    value="\n".join(current_examples),
                    key=f"nb_ee_{entry['id']}",
                    height=100,
                )
                new_tags = st.text_input(
                    "标签", value=", ".join(entry["tags"]), key=f"nb_etags_{entry['id']}"
                )
                if st.form_submit_button("保存修改", use_container_width=True):
                    if not new_term.strip():
                        st.warning("单词 / 词组不能为空")
                    else:
                        manual_lines = [
                            line.strip()
                            for line in new_example.splitlines()
                            if line.strip()
                        ]
                        old_term, old_meaning = entry["term"], entry["meaning"]
                        meaning_changed = new_meaning.strip() != entry["meaning"]
                        examples_changed = manual_lines != current_examples
                        update_entry(
                            entry["id"],
                            term=new_term,
                            meaning=new_meaning,
                            example=manual_lines[0] if manual_lines else "",
                            tags=new_tags,
                        )
                        if meaning_changed or examples_changed:
                            with st.spinner("正在为每个意思补全例句..."):
                                refresh_entry_examples(
                                    entry["id"], manual_examples=manual_lines
                                )
                        NotebookSync.after_notebook_edit(
                            old_term,
                            old_meaning,
                            new_term.strip(),
                            new_meaning.strip(),
                        )
                        st.session_state.nb_edit_entry_id = None
                        st.session_state.nb_delete_entry_id = None
                        st.session_state.nb_focus_entry = entry["id"]
                        st.session_state.nb_flash = f"已更新：{new_term.strip()}"
                        st.rerun()
            if st.button(
                "取消修改",
                key=f"nb_cancel_{entry['id']}",
                use_container_width=True,
            ):
                st.session_state.nb_edit_entry_id = None
                st.session_state.nb_delete_entry_id = None
                st.session_state.nb_focus_entry = entry["id"]
                st.rerun()
        else:
            senses = entry.get("senses") or []
            if senses:
                for sense in senses:
                    pos = sense.get("pos") or ""
                    gloss = sense.get("meaning") or ""
                    heading = f"{pos} {gloss}".strip()
                    if heading:
                        st.markdown(f"**{heading}**")
                    if sense.get("example"):
                        st.caption(sense["example"])
            else:
                if entry["meaning"]:
                    st.markdown(entry["meaning"])
                if entry["example"]:
                    st.caption(entry["example"])
            st.caption(
                f"标签：{'、'.join(entry['tags']) or '—'}"
                f" ｜ 来源：{entry['source'] or '—'}"
            )
            info_col, edit_col, del_col = st.columns([7, 0.9, 0.9])
            info_col.caption(f"添加：{entry['created_at']} ｜ 更新：{entry['updated_at']}")
            if edit_col.button(
                "✏️ 修改",
                key=f"nb_edit_btn_{entry['id']}",
                use_container_width=True,
            ):
                st.session_state.nb_edit_entry_id = entry["id"]
                st.session_state.nb_delete_entry_id = None
                st.session_state.nb_focus_entry = entry["id"]
                st.rerun()

            if del_col.button(
                "🗑 删除",
                key=f"nb_del_{entry['id']}",
                use_container_width=True,
            ):
                st.session_state.nb_edit_entry_id = None
                st.session_state.nb_delete_entry_id = entry["id"]
                st.session_state.nb_focus_entry = entry["id"]
                st.rerun()


if not entries:
    st.info(
        "还没有笔记。点上面的「新增一条」，或在练习页面侧边栏的「➕ 加入笔记本」里随手保存。"
    )
elif not filtered:
    st.info("没有匹配的笔记，换个关键词或标签试试。")
else:
    for entry in filtered:
        render_entry(entry)

with st.sidebar:
    st.subheader("📓 笔记本")
    st.caption(f"共 {len(entries)} 条")
    if st.button("🪄 补全缺失的翻译 / 词性 / 标签 / 例句", use_container_width=True):
        with st.spinner("正在整理旧笔记..."):
            touched = backfill_entries()
        st.session_state.nb_flash = (
            f"已补全 {touched} 条" if touched else "没有需要补全的笔记"
        )
        st.rerun()
    st.download_button(
        "⬇️ 导出 JSON",
        data=json.dumps(
            {"version": 1, "entries": entries}, ensure_ascii=False, indent=2
        ),
        file_name="notebook.json",
        mime="application/json",
        use_container_width=True,
    )
    st.caption("数据文件：data/notebook.json")
