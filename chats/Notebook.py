# chats/Notebook.py

import json
import random

import streamlit as st

from utils.Notebook import (
    add_entry,
    delete_entry,
    load_entries,
    search_entries,
    stats,
    update_entry,
)

st.set_page_config(page_title="我的笔记本", page_icon="📓", layout="wide")

st.title("📓 单词与词组笔记本")
st.caption("遇到好词好句随手存；支持搜索、修改、删除和随机复习。")

if st.session_state.get("nb_flash"):
    st.success(st.session_state.nb_flash)
    st.session_state.nb_flash = ""

entries = load_entries()
counts = stats(entries)

col1, col2, col3, col4 = st.columns(4)
col1.metric("总条目", counts["total"])
col2.metric("近 7 天新增", counts["week"])
col3.metric("标签数", counts["tags"])
col4.metric("有例句", counts["with_example"])

with st.expander("➕ 新增一条", expanded=(counts["total"] == 0)):
    with st.form("nb_add_form", clear_on_submit=True):
        term = st.text_input(
            "单词 / 词组 *",
            key="nb_add_term",
            placeholder="e.g. take ... for granted",
        )
        meaning = st.text_input("中文意思 / 解释", key="nb_add_meaning")
        example = st.text_area("例句", key="nb_add_example", height=90)
        note = st.text_area("备注 / 搭配 / 易错点", key="nb_add_note", height=80)
        col_tag, col_source = st.columns(2)
        tags = col_tag.text_input(
            "标签（逗号分隔）", key="nb_add_tags", placeholder="Part2, 环境"
        )
        source = col_source.selectbox(
            "来源",
            ["手动添加", "讲个故事", "AI 老师", "严肃话题", "自由聊天", "其他"],
            key="nb_add_source",
        )
        if st.form_submit_button(
            "保存到笔记本", type="primary", use_container_width=True
        ):
            if not term.strip():
                st.warning("单词 / 词组不能为空")
            else:
                add_entry(
                    term,
                    meaning=meaning,
                    example=example,
                    note=note,
                    tags=tags,
                    source=source,
                )
                st.session_state.nb_flash = f"已保存：{term.strip()}"
                st.rerun()

st.divider()

col_query, col_sort, col_tag = st.columns([2.4, 1, 1.4])
query = col_query.text_input(
    "🔍 搜索", placeholder="单词、意思、例句、备注或标签", key="nb_query"
)
sort_by = col_sort.selectbox(
    "排序", ["最近更新", "最近添加", "字母顺序"], key="nb_sort"
)
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
else:
    filtered.sort(key=lambda entry: entry["term"].lower())

st.subheader(f"📚 全部笔记（{len(filtered)}）")

if not entries:
    st.info(
        "还没有笔记。点上面的「新增一条」，或在练习页面侧边栏的「➕ 加入笔记本」里随手保存。"
    )
elif not filtered:
    st.info("没有匹配的笔记，换个关键词或标签试试。")

for entry in filtered:
    header = entry["term"]
    if entry["meaning"]:
        header += f" — {entry['meaning']}"
    with st.expander(header):
        if entry["example"]:
            st.markdown(f"**例句：** {entry['example']}")
        if entry["note"]:
            st.markdown(f"**备注：** {entry['note']}")
        st.caption(
            f"来源：{entry['source'] or '—'} ｜ 添加：{entry['created_at']} ｜ 更新：{entry['updated_at']}"
        )

        with st.form(f"nb_edit_{entry['id']}"):
            edit_col1, edit_col2 = st.columns(2)
            new_term = edit_col1.text_input(
                "单词 / 词组", value=entry["term"], key=f"nb_et_{entry['id']}"
            )
            new_meaning = edit_col2.text_input(
                "中文意思", value=entry["meaning"], key=f"nb_em_{entry['id']}"
            )
            new_example = st.text_area(
                "例句", value=entry["example"], key=f"nb_ee_{entry['id']}", height=80
            )
            new_note = st.text_area(
                "备注", value=entry["note"], key=f"nb_en_{entry['id']}", height=70
            )
            edit_col3, edit_col4 = st.columns(2)
            new_tags = edit_col3.text_input(
                "标签", value=", ".join(entry["tags"]), key=f"nb_eg_{entry['id']}"
            )
            new_source = edit_col4.text_input(
                "来源", value=entry["source"], key=f"nb_es_{entry['id']}"
            )
            if st.form_submit_button("保存修改", use_container_width=True):
                if not new_term.strip():
                    st.warning("单词 / 词组不能为空")
                else:
                    update_entry(
                        entry["id"],
                        term=new_term,
                        meaning=new_meaning,
                        example=new_example,
                        note=new_note,
                        tags=new_tags,
                        source=new_source,
                    )
                    st.session_state.nb_flash = f"已更新：{new_term.strip()}"
                    st.rerun()

        confirm = st.checkbox("确认删除这条", key=f"nb_delok_{entry['id']}")
        if st.button("🗑 删除", key=f"nb_del_{entry['id']}", disabled=not confirm):
            delete_entry(entry["id"])
            st.session_state.nb_flash = f"已删除：{entry['term']}"
            if st.session_state.get("nb_review_id") == entry["id"]:
                st.session_state.pop("nb_review_id", None)
            st.rerun()

st.divider()
st.subheader("🎴 随机复习")

if entries:
    ids = {entry["id"] for entry in entries}
    if st.session_state.get("nb_review_id") not in ids:
        st.session_state.nb_review_id = random.choice(entries)["id"]
        st.session_state.nb_reveal = False
    current = next(
        entry for entry in entries if entry["id"] == st.session_state.nb_review_id
    )
    st.markdown(f"### {current['term']}")
    if st.button("显示意思 / 例句", key="nb_reveal_btn"):
        st.session_state.nb_reveal = True
    if st.session_state.get("nb_reveal"):
        st.write(current["meaning"] or "（还没有写意思）")
        if current["example"]:
            st.caption(current["example"])
    if st.button("换一个", key="nb_next_btn"):
        st.session_state.nb_review_id = random.choice(entries)["id"]
        st.session_state.nb_reveal = False
        st.rerun()
else:
    st.caption("有笔记之后，这里会随机抽一条考你。")

with st.sidebar:
    st.subheader("📓 笔记本")
    st.caption(f"共 {len(entries)} 条")
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
