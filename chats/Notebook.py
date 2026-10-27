# chats/Notebook.py

import json
import random

import streamlit as st

from utils.LongNotes import render_long_notes
from utils.Notebook import (
    add_entry,
    backfill_entries,
    delete_entry,
    load_entries,
    search_entries,
    stats,
    update_entry,
)

st.set_page_config(page_title="我的笔记本", page_icon="📓", layout="wide")

st.title("📓 我的笔记本")
st.caption(
    "单词 / 词组会自动补全词性、标签和分组；长文本笔记按日期归档，标题可留空由 AI 生成。"
)

notebook_mode = st.segmented_control(
    "笔记类型",
    ["单词 / 词组", "长文本笔记"],
    default="单词 / 词组",
    key="nb_mode",
    label_visibility="collapsed",
) or "单词 / 词组"

if notebook_mode == "长文本笔记":
    render_long_notes()
    st.stop()

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
    st.caption("只填单词 / 词组和例句；意思、词性、标签、分组会自动补全。")
    with st.form("nb_add_form", clear_on_submit=True):
        term = st.text_input(
            "单词 / 词组 *",
            key="nb_add_term",
            placeholder="e.g. take ... for granted",
        )
        example = st.text_area("例句（可选）", key="nb_add_example", height=90)
        if st.form_submit_button(
            "保存到笔记本", type="primary", use_container_width=True
        ):
            if not term.strip():
                st.warning("单词 / 词组不能为空")
            else:
                with st.spinner("正在补全翻译 / 标签 / 分组..."):
                    entry = add_entry(
                        term,
                        example=example,
                        source="手动添加",
                    )
                st.session_state.nb_flash = (
                    f"已保存：{entry['term']} ｜ {entry['meaning'] or '待补充'}"
                    f" ｜ 分组：{entry['group']}"
                )
                st.rerun()

with st.expander("🎴 随机复习", expanded=False):
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
        if st.button("换一个", key="nb_next_btn", disabled=len(entries) < 2):
            others = [entry for entry in entries if entry["id"] != current["id"]]
            st.session_state.nb_review_id = random.choice(others)["id"]
            st.session_state.nb_reveal = False
            st.rerun()
        if len(entries) < 2:
            st.caption("至少要有两条笔记，才能换到不同的一条。")
    else:
        st.caption("有笔记之后，这里会随机抽一条考你。")

st.divider()

col_query, col_sort, col_tag = st.columns([2.4, 1, 1.4])
query = col_query.text_input(
    "🔍 搜索", placeholder="单词、意思、例句、备注、分组或标签", key="nb_query"
)
sort_by = col_sort.selectbox(
    "排序", ["相关分组", "最近添加", "最近更新", "字母顺序"], key="nb_sort"
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
    filtered = list(reversed(filtered))
elif sort_by == "字母顺序":
    filtered.sort(key=lambda entry: entry["term"].lower())
# "相关分组" 保持文件中的添加顺序，渲染时倒序（新的在前）

st.markdown(f"**📚 全部笔记（{len(filtered)}）**")


def render_entry(entry: dict) -> None:
    with st.expander(entry["term"]):
        editing = st.session_state.get("nb_edit_entry_id") == entry["id"]

        if editing:
            with st.form(f"nb_edit_{entry['id']}"):
                edit_col1, edit_col2 = st.columns(2)
                new_term = edit_col1.text_input(
                    "单词 / 词组", value=entry["term"], key=f"nb_et_{entry['id']}"
                )
                new_meaning = edit_col2.text_input(
                    "中文意思 / 词性", value=entry["meaning"], key=f"nb_em_{entry['id']}"
                )
                new_example = st.text_area(
                    "例句", value=entry["example"], key=f"nb_ee_{entry['id']}", height=80
                )
                edit_col3, edit_col4 = st.columns(2)
                new_tags = edit_col3.text_input(
                    "标签", value=", ".join(entry["tags"]), key=f"nb_etags_{entry['id']}"
                )
                new_group = edit_col4.text_input(
                    "分组", value=entry["group"], key=f"nb_egroup_{entry['id']}"
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
                            tags=new_tags,
                            group=new_group,
                        )
                        st.session_state.nb_edit_entry_id = None
                        st.session_state.nb_flash = f"已更新：{new_term.strip()}"
                        st.rerun()
            if st.button(
                "取消修改",
                key=f"nb_cancel_{entry['id']}",
                use_container_width=True,
            ):
                st.session_state.nb_edit_entry_id = None
                st.rerun()
        else:
            if entry["meaning"]:
                st.markdown(f"**翻译：** {entry['meaning']}")
            if entry["example"]:
                st.markdown(f"**例句：** {entry['example']}")
            st.caption(
                f"分组：{entry['group'] or '未分组'} ｜ 标签：{'、'.join(entry['tags']) or '—'}"
                f" ｜ 来源：{entry['source'] or '—'}"
            )
            st.caption(f"添加：{entry['created_at']} ｜ 更新：{entry['updated_at']}")

            if st.button(
                "✏️ 修改",
                key=f"nb_edit_btn_{entry['id']}",
                use_container_width=True,
            ):
                st.session_state.nb_edit_entry_id = entry["id"]
                st.rerun()

            confirm = st.checkbox("确认删除这条", key=f"nb_delok_{entry['id']}")
            if st.button(
                "🗑 删除",
                key=f"nb_del_{entry['id']}",
                disabled=not confirm,
            ):
                delete_entry(entry["id"])
                st.session_state.nb_edit_entry_id = None
                st.session_state.nb_flash = f"已删除：{entry['term']}"
                if st.session_state.get("nb_review_id") == entry["id"]:
                    st.session_state.pop("nb_review_id", None)
                st.rerun()


if not entries:
    st.info(
        "还没有笔记。点上面的「新增一条」，或在练习页面侧边栏的「➕ 加入笔记本」里随手保存。"
    )
elif not filtered:
    st.info("没有匹配的笔记，换个关键词或标签试试。")
elif sort_by == "相关分组":
    grouped: dict[str, list[dict]] = {}
    for entry in reversed(filtered):
        grouped.setdefault(entry["group"] or "未分组", []).append(entry)
    for group, items in grouped.items():
        st.markdown(f"**{group}** · {len(items)} 条")
        group_tags = sorted({tag for item in items for tag in item["tags"]})
        if group_tags:
            st.caption("　".join(group_tags))
        for entry in items:
            render_entry(entry)
else:
    for entry in filtered:
        render_entry(entry)

with st.sidebar:
    st.subheader("📓 笔记本")
    st.caption(f"共 {len(entries)} 条")
    if st.button("🪄 补全缺失的翻译 / 标签 / 分组", use_container_width=True):
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
