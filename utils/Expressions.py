# utils/Expressions.py

"""表达库：积累「想表达的意思 → 地道说法」的配对。

和单词笔记本的区别：
- 单词表解决「不认识这个词」；
- 表达库解决「这个意思我不会用英语说」，记的是意图和说法，不是词条。

复习方式也不同：只给中文意图，让你把英文产出出来，再对答案。
说不出来就等于没学会，这才是表达能力的检验标准。

数据保存在 data/expressions.json（已 gitignore），每次写入自动留快照。
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.storage import save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPRESSIONS_PATH = Path(
    os.getenv("EXPRESSIONS_PATH") or (_PROJECT_ROOT / "data" / "expressions.json")
)
_LOCK = threading.RLock()

_REVIEW_LIMIT = 20
_MASTERED_DAYS = 21


# ----------------------------- 基础工具 -----------------------------
def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _scene_hint(text, limit: int = 80) -> str:
    """把上下文压成一行场景（用于追问、人设这类单行文本）。"""
    line = next(
        (part.strip() for part in str(text or "").splitlines() if part.strip()), ""
    )
    line = re.sub(r"^[-*#>+\s]+", "", line)
    if len(line) <= limit:
        return line
    cut = line[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return (cut or line[:limit]) + "…"


def _clean_scene(text, limit: int = 600) -> str:
    """保留换行的场景文本：Part 2 的完整题卡要连 You should say 一起存。"""
    lines = [
        re.sub(r"\s+", " ", part).strip()
        for part in str(text or "").replace("\r\n", "\n").split("\n")
    ]
    lines = [line for line in lines if line]
    return "\n".join(lines)[:limit].strip()


def _scene_display(scene: str) -> str:
    """把多行场景转成 Markdown 硬换行，卡片里才不会挤成一行。"""
    return "  \n".join(line for line in str(scene or "").splitlines() if line.strip())


def _today() -> date:
    return date.today()


def _review_defaults() -> dict:
    return {
        "due": _today().isoformat(),
        "interval": 0,
        "streak": 0,
        "lapses": 0,
        "last": "",
    }


def _normalize(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    intent = _one_line(raw.get("intent"))
    natural = _one_line(raw.get("natural"))
    if not intent or not natural:
        return None
    review = raw.get("review") if isinstance(raw.get("review"), dict) else {}
    due = str(review.get("due") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        due = _today().isoformat()
    try:
        interval = max(0, int(review.get("interval") or 0))
        streak = max(0, int(review.get("streak") or 0))
        lapses = max(0, int(review.get("lapses") or 0))
    except (TypeError, ValueError):
        interval = streak = lapses = 0
    created = str(raw.get("created_at") or _stamp())
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:12]),
        "intent": intent,
        "natural": natural,
        "mine": _one_line(raw.get("mine")),
        "scene": _clean_scene(raw.get("scene")),
        "source": _one_line(raw.get("source")),
        "created_at": created,
        "updated_at": str(raw.get("updated_at") or created),
        "review": {
            "due": due,
            "interval": interval,
            "streak": streak,
            "lapses": lapses,
            "last": str(review.get("last") or ""),
        },
    }


# ----------------------------- 读写 -----------------------------
def _load_unlocked() -> list[dict]:
    if not EXPRESSIONS_PATH.exists():
        return []
    try:
        data = json.loads(EXPRESSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("entries", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        entry = _normalize(item)
        if entry:
            entries.append(entry)
    return entries


def _save_unlocked(entries: list[dict]) -> None:
    save_json(EXPRESSIONS_PATH, {"version": 1, "entries": entries})


def load_expressions() -> list[dict]:
    with _LOCK:
        return _load_unlocked()


def add_expression(
    intent: str,
    natural: str,
    mine: str = "",
    scene: str = "",
    source: str = "",
) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "intent": _one_line(intent),
        "natural": _one_line(natural),
        "mine": _one_line(mine),
        "scene": _clean_scene(scene),
        "source": _one_line(source),
        "created_at": _stamp(),
        "updated_at": _stamp(),
        "review": _review_defaults(),
    }
    with _LOCK:
        entries = _load_unlocked()
        entries.insert(0, entry)
        _save_unlocked(entries)
    return entry


def update_expression(entry_id: str, **fields) -> dict | None:
    allowed = {"intent", "natural", "mine", "scene"}
    with _LOCK:
        entries = _load_unlocked()
        for entry in entries:
            if entry["id"] != entry_id:
                continue
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "scene":
                    entry["scene"] = _clean_scene(value)
                    continue
                text = _one_line(value)
                if text or key == "mine":
                    entry[key] = text
            if not entry["intent"] or not entry["natural"]:
                return None
            entry["updated_at"] = _stamp()
            _save_unlocked(entries)
            return entry
    return None


def delete_expression(entry_id: str) -> bool:
    with _LOCK:
        entries = _load_unlocked()
        remaining = [entry for entry in entries if entry["id"] != entry_id]
        if len(remaining) == len(entries):
            return False
        _save_unlocked(remaining)
        return True


def review_expression(entry_id: str, grade: str) -> dict | None:
    """grade: again（没印象）/ hard（差一点）/ good（说对了）。

    简单的间隔重复：说对了就把间隔按 1 → 3 → 7 → 14 → 30 拉长，
    差一点明天再来，没印象当天算到期、随时可以再练。
    """
    with _LOCK:
        entries = _load_unlocked()
        for entry in entries:
            if entry["id"] != entry_id:
                continue
            review = entry["review"]
            today = _today()
            if grade == "good":
                review["streak"] += 1
                if review["streak"] == 1:
                    interval = 1
                elif review["streak"] == 2:
                    interval = 3
                elif review["streak"] == 3:
                    interval = 7
                else:
                    interval = min(120, max(7, int(review["interval"]) * 2))
                review["interval"] = interval
                review["due"] = (today + timedelta(days=interval)).isoformat()
            elif grade == "hard":
                review["streak"] = 0
                review["interval"] = 1
                review["due"] = (today + timedelta(days=1)).isoformat()
            else:
                review["streak"] = 0
                review["lapses"] += 1
                review["due"] = today.isoformat()
            review["last"] = today.isoformat()
            entry["updated_at"] = _stamp()
            _save_unlocked(entries)
            return entry
    return None


def stats(entries: list[dict] | None = None) -> dict:
    entries = load_expressions() if entries is None else entries
    today = _today().isoformat()
    return {
        "total": len(entries),
        "due": sum(1 for entry in entries if entry["review"]["due"] <= today),
        "mastered": sum(
            1 for entry in entries if entry["review"]["interval"] >= _MASTERED_DAYS
        ),
        "fresh": sum(
            1
            for entry in entries
            if not entry["review"]["last"] and entry["review"]["streak"] == 0
        ),
    }


def due_entries(entries: list[dict] | None = None, limit: int = _REVIEW_LIMIT) -> list[dict]:
    entries = load_expressions() if entries is None else entries
    today = _today().isoformat()
    due = [entry for entry in entries if entry["review"]["due"] <= today]
    due.sort(key=lambda entry: (entry["review"]["due"], entry["created_at"]))
    return due[:limit]


def next_due(entries: list[dict] | None = None) -> str:
    entries = load_expressions() if entries is None else entries
    today = _today().isoformat()
    future = [entry["review"]["due"] for entry in entries if entry["review"]["due"] > today]
    return min(future) if future else ""


# ----------------------------- 侧边栏快速记录 -----------------------------
def render_expression_capture(
    source: str, key_prefix: str, scene: str = "", scene_full: bool = False
) -> None:
    """练习页侧边栏的「记下这句」：不调用模型。

    场景（当前题目 / 人设 / 上一句追问）由页面自动传入，不要求手填；
    scene_full=True 时保留完整文本（Part 2 题卡连 You should say 一起存）。
    """
    import streamlit as st

    scene_value = _clean_scene(scene) if scene_full else _scene_hint(scene)
    with st.expander("🗣️ 记下这句", expanded=False):
        st.caption("记「想表达的意思 → 地道说法」，不是记单词。")
        if scene_value:
            lines = scene_value.splitlines()
            extra = f"（完整题卡，{len(lines)} 行）" if len(lines) > 1 else ""
            st.caption(f"场景自动记录：{lines[0]}{extra}")
        with st.form(f"exp_quick_{key_prefix}", clear_on_submit=True):
            intent = st.text_input(
                "想表达什么（中文）*",
                key=f"{key_prefix}_exp_intent",
                placeholder="e.g. 我想说「这事我一时半会儿说不清」",
            )
            natural = st.text_area(
                "地道说法（英文）*",
                key=f"{key_prefix}_exp_natural",
                height=80,
                placeholder="e.g. It's hard to put into words right now.",
            )
            mine = st.text_input(
                "我当时的说法（可选）",
                key=f"{key_prefix}_exp_mine",
                placeholder="e.g. I can't say it clear now.",
            )
            if st.form_submit_button("存入表达库", use_container_width=True):
                if not intent.strip() or not natural.strip():
                    st.warning("中文意图和地道说法都要填")
                else:
                    entry = add_expression(
                        intent,
                        natural,
                        mine=mine,
                        scene=scene_value,
                        source=source,
                    )
                    st.success(f"已记下：{entry['intent']}")
                    st.toast("🗣️ 已存入表达库")


# ----------------------------- 表达库页面 -----------------------------
def _review_flow(entries: list[dict]) -> None:
    import streamlit as st

    by_id = {entry["id"]: entry for entry in entries}
    ids = [entry_id for entry_id in st.session_state.get("exp_ids", []) if entry_id in by_id]
    pos = st.session_state.get("exp_pos", 0)

    if not ids or pos >= len(ids):
        due = due_entries(entries)
        if not due:
            hint = next_due(entries)
            st.caption(
                f"今天没有到期的表达。下一次复习：{hint}" if hint else "还没有表达，先记一句。"
            )
            return
        if ids:
            st.success("这一轮复习完成。")
        st.caption("只看中文，把英文说出来或打出来，然后对答案；说不出来就选「没印象」。")
        if st.button(f"开始复习（{len(due)} 条）", type="primary", use_container_width=True):
            st.session_state.exp_ids = [entry["id"] for entry in due]
            st.session_state.exp_pos = 0
            st.session_state.exp_revealed = False
            st.rerun()
        return

    entry = by_id[ids[pos]]
    st.progress(pos / len(ids), text=f"第 {pos + 1} / {len(ids)} 张")
    st.markdown(f"### {entry['intent']}")
    if entry.get("scene"):
        st.caption(f"场景：{_scene_display(entry['scene'])}")

    st.text_input(
        "用英文说出来（写完再对答案）",
        key=f"exp_answer_{entry['id']}",
        placeholder="Type your English here…",
    )

    def _advance(grade: str | None = None) -> None:
        if grade:
            review_expression(entry["id"], grade)
        st.session_state.exp_pos = pos + 1
        st.session_state.exp_revealed = False
        st.rerun()

    if not st.session_state.get("exp_revealed"):
        if st.button("显示地道说法", key=f"exp_show_{entry['id']}", use_container_width=True):
            st.session_state.exp_revealed = True
            st.rerun()
        return

    st.success(entry["natural"])
    if entry.get("mine"):
        st.caption(f"你当时说的是：{entry['mine']}")

    col1, col2, col3 = st.columns(3)
    if col1.button("😵 没印象", key=f"exp_again_{entry['id']}", use_container_width=True):
        _advance("again")
    if col2.button("🤔 差一点", key=f"exp_hard_{entry['id']}", use_container_width=True):
        _advance("hard")
    if col3.button(
        "✅ 说对了", key=f"exp_good_{entry['id']}", type="primary", use_container_width=True
    ):
        _advance("good")


def _render_entry(entry: dict) -> None:
    import streamlit as st

    editing = st.session_state.get("exp_edit_id") == entry["id"]
    deleting = st.session_state.get("exp_delete_id") == entry["id"]
    with st.expander(entry["intent"], expanded=editing or deleting):
        if deleting:
            st.warning("确定要删除这条表达吗？")
            st.caption(f"地道说法：{entry['natural']}")
            yes, no = st.columns(2)
            if yes.button(
                "确认删除",
                type="primary",
                key=f"exp_del_yes_{entry['id']}",
                use_container_width=True,
            ):
                delete_expression(entry["id"])
                st.session_state.exp_delete_id = None
                st.session_state.exp_edit_id = None
                st.session_state.exp_flash = "已删除一条表达"
                st.rerun()
            if no.button(
                "取消", key=f"exp_del_no_{entry['id']}", use_container_width=True
            ):
                st.session_state.exp_delete_id = None
                st.rerun()
            return

        if editing:
            with st.form(f"exp_edit_{entry['id']}"):
                intent = st.text_area(
                    "想表达什么（中文）",
                    value=entry["intent"],
                    key=f"exp_ei_{entry['id']}",
                    height=70,
                )
                natural = st.text_area(
                    "地道说法（英文）",
                    value=entry["natural"],
                    key=f"exp_en_{entry['id']}",
                    height=80,
                )
                mine = st.text_input(
                    "我当时的说法", value=entry["mine"], key=f"exp_em_{entry['id']}"
                )
                if st.form_submit_button("保存修改", use_container_width=True):
                    if not intent.strip() or not natural.strip():
                        st.warning("中文意图和地道说法不能为空")
                    else:
                        update_expression(
                            entry["id"],
                            intent=intent,
                            natural=natural,
                            mine=mine,
                        )
                        st.session_state.exp_edit_id = None
                        st.session_state.exp_flash = "已保存修改"
                        st.rerun()
            if st.button("取消修改", key=f"exp_cancel_{entry['id']}", use_container_width=True):
                st.session_state.exp_edit_id = None
                st.rerun()
            return

        st.markdown(f"**{entry['natural']}**")
        if entry["mine"]:
            st.caption(f"你当时说的是：{entry['mine']}")
        if entry["scene"]:
            st.caption(f"场景：{_scene_display(entry['scene'])}")
        st.caption(f"来源：{entry['source'] or '—'}")
        review = entry["review"]
        st.caption(
            f"复习：下次 {review['due']}"
            f" ｜ 间隔 {review['interval']} 天"
            f" ｜ 连胜 {review['streak']}"
            f" ｜ 遗忘 {review['lapses']} 次"
        )
        edit_col, del_col = st.columns(2)
        if edit_col.button(
            "✏️ 修改", key=f"exp_edit_btn_{entry['id']}", use_container_width=True
        ):
            st.session_state.exp_edit_id = entry["id"]
            st.session_state.exp_delete_id = None
            st.rerun()
        if del_col.button(
            "🗑 删除", key=f"exp_del_btn_{entry['id']}", use_container_width=True
        ):
            st.session_state.exp_edit_id = None
            st.session_state.exp_delete_id = entry["id"]
            st.rerun()


def render_expressions() -> None:
    """「笔记本 → 表达」这个 tab 的全部内容。"""
    import streamlit as st

    entries = load_expressions()
    counts = stats(entries)

    if st.session_state.get("exp_flash"):
        st.success(st.session_state.exp_flash)
        st.session_state.exp_flash = ""

    col1, col2, col3 = st.columns(3)
    col1.metric("待复习", counts["due"])
    col2.metric("总条数", counts["total"])
    col3.metric("已掌握", counts["mastered"])

    st.caption(
        "记的是「想表达的意思 → 地道说法」。复习时只给中文，你先把英文说出来，再对答案。"
    )

    with st.expander("➕ 记一句", expanded=(counts["total"] == 0)):
        with st.form("exp_add_form", clear_on_submit=True):
            intent = st.text_input(
                "想表达什么（中文）*",
                key="exp_add_intent",
                placeholder="e.g. 我想说「这事我一时半会儿说不清」",
            )
            natural = st.text_area(
                "地道说法（英文）*",
                key="exp_add_natural",
                height=80,
                placeholder="e.g. It's hard to put into words right now.",
            )
            mine = st.text_input(
                "我当时的说法（可选）",
                key="exp_add_mine",
                placeholder="e.g. I can't say it clear now.",
            )
            if st.form_submit_button("保存到表达库", type="primary", use_container_width=True):
                if not intent.strip() or not natural.strip():
                    st.warning("中文意图和地道说法都要填")
                else:
                    add_expression(intent, natural, mine=mine, source="手动添加")
                    st.session_state.exp_flash = "已加入表达库"
                    st.rerun()

    with st.container(border=True):
        st.subheader("🎯 产出复习")
        _review_flow(entries)

    st.divider()

    query = st.text_input(
        "🔍 搜索", placeholder="中文意图、英文说法或场景", key="exp_query"
    )
    sort_by = st.selectbox(
        "排序",
        ["到期优先", "最近添加"],
        key="exp_sort",
    )

    visible = entries
    if query.strip():
        keyword = query.strip().lower()
        visible = [
            entry
            for entry in visible
            if keyword
            in " ".join(
                [
                    entry["intent"],
                    entry["natural"],
                    entry["mine"],
                    entry["scene"],
                ]
            ).lower()
        ]
    if sort_by == "最近添加":
        visible = sorted(visible, key=lambda entry: entry["created_at"], reverse=True)
    else:
        visible = sorted(visible, key=lambda entry: entry["review"]["due"])

    st.markdown(f"**🗣️ 全部表达（{len(visible)}）**")
    if not entries:
        st.info("还没有表达。点上面的「记一句」，或在练习页侧边栏的「🗣️ 记下这句」随手存。")
    elif not visible:
        st.info("没有匹配的表达，换个关键词试试。")
    else:
        for entry in visible:
            _render_entry(entry)

    with st.sidebar:
        st.subheader("🗣️ 表达库")
        st.caption(f"共 {len(entries)} 条 ｜ 待复习 {counts['due']}")
        st.download_button(
            "⬇️ 导出 JSON",
            data=json.dumps(
                {"version": 1, "entries": entries}, ensure_ascii=False, indent=2
            ),
            file_name="expressions.json",
            mime="application/json",
            use_container_width=True,
        )
        st.caption("数据文件：data/expressions.json")


__all__ = [
    "add_expression",
    "delete_expression",
    "due_entries",
    "load_expressions",
    "next_due",
    "render_expression_capture",
    "render_expressions",
    "review_expression",
    "stats",
    "update_expression",
]
