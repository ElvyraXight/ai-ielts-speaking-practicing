# utils/Memory.py

"""娱乐角色（闲聊 / 猫娘 / 心理咨询 / 学业导师）的跨会话长期记忆。

数据结构（data/memories.json，v2）：

    {
      "version": 2,
      "personas": {
        "catgirl": {
          "summary": "对这个用户的简短画像",
          "facts": [
            {"text": "...", "count": 2,
             "first": "2026-10-01 21:03:11", "last": "2026-10-28 23:40:02",
             "permanent": false}
          ],
          "updated_at": "..."
        }
      }
    }

三条规则：

1. **事实只增不减。** 模型只回答"这轮新增了什么 / 哪条又被提到 / 哪条要固化"，
   合并由本地完成。以前是让模型重写整份清单，它某次少写一条，那条就真没了。
2. **反复提到就固化。** 同一条事实被提到 `_PERMANENT_AT` 次自动变永久；
   用户在话里明确强调（"记住…"、"别再忘"、"我说过很多次"）时，
   这一轮提取到的事实立刻固化。
3. **永久记忆不淡忘、不挤占。** 非永久事实 60 天没再提且只提过一次会被清掉；
   永久事实永远保留，注入 prompt 时单独成段，并明确要求"不要问第二遍"。

角色之间互相独立：猫娘不会知道你和咨询师聊过什么。
"""

import difflib
import hashlib
import logging
import os
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.llm import call_llm_json
from utils.storage import load_json, save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = Path(
    os.getenv("MEMORY_PATH") or (_PROJECT_ROOT / "data" / "memories.json")
)
_LOCK = threading.RLock()

_MAX_FACTS = 14          # 每个角色最多存多少条（含永久）
_MAX_PERMANENT = 10      # 永久事实上限
_MAX_SUMMARY = 300
_MAX_FACT_CHARS = 60
_PERMANENT_AT = 3        # 同一条被提到 3 次 -> 永久
_DECAY_DAYS = 60         # 非永久 + 只提过一次 + 这么久没提 -> 淡忘
_SIMILARITY = 0.72

# 用户明确要求"记住"的说法，命中就立刻固化这一轮的事实。
_STRESS_RE = re.compile(
    r"(记住|记牢|记一下|记下|别忘了|不要忘|不能忘|别再忘|我说过|跟你说过|和你讲过|"
    r"强调过|反复说|很重要|最重要|永久|永远记住|"
    r"remember (this|that)|don'?t forget|never forget|i told you|i'?ve told you|"
    r"keep (this )?in mind|it'?s important)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return date.today()


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _parse_day(stamp: str) -> date | None:
    try:
        return datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _normalise(text: str) -> str:
    """比较用：去掉标点空白，只留文字和数字。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def _similar(a: str, b: str) -> bool:
    """两条事实是不是同一件事（措辞可能不同）。"""
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= _SIMILARITY


def _new_fact(
    text,
    *,
    stamp: str = "",
    count: int | None = None,
    permanent: bool = False,
    first: str = "",
    last: str = "",
) -> dict | None:
    text = _one_line(text).strip("-• ").strip()[:_MAX_FACT_CHARS]
    if not text:
        return None
    stamp = stamp or _now()
    try:
        count_value = 1 if count is None else int(count)
    except (TypeError, ValueError):
        count_value = 1
    return {
        "text": text,
        "count": max(0, count_value),
        "first": first or stamp,
        "last": last or stamp,
        "permanent": bool(permanent),
    }


def _normalise_persona(raw) -> dict:
    """兼容 v1（facts 是字符串列表）：老数据先按永久处理，侧边栏可以取消。"""
    if not isinstance(raw, dict):
        return {"summary": "", "facts": [], "updated_at": ""}
    stamp = str(raw.get("updated_at") or "") or _now()
    facts: list[dict] = []
    for item in raw.get("facts") or []:
        if isinstance(item, str):
            fact = _new_fact(item, stamp=stamp, permanent=True)
        elif isinstance(item, dict):
            fact = _new_fact(
                item.get("text") or "",
                stamp=stamp,
                count=item.get("count"),
                permanent=item.get("permanent") or False,
                first=str(item.get("first") or ""),
                last=str(item.get("last") or ""),
            )
        else:
            fact = None
        if fact and not fact["permanent"] and fact["count"] >= _PERMANENT_AT:
            # 旧数据里取消永久后可能还留着 3 次以上的计数；按“重新计数”处理。
            fact["count"] = 0
        if fact and not any(_similar(fact["text"], old["text"]) for old in facts):
            facts.append(fact)
    return {
        "summary": _one_line(raw.get("summary"))[:_MAX_SUMMARY],
        "facts": facts,
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _load_all() -> dict:
    data = load_json(MEMORY_PATH, {})
    personas = data.get("personas", {}) if isinstance(data, dict) else {}
    if not isinstance(personas, dict):
        return {}
    return {key: _normalise_persona(raw) for key, raw in personas.items()}


def _save_all(personas: dict) -> None:
    save_json(MEMORY_PATH, {"version": 2, "personas": personas})


def load_memory(key: str) -> dict:
    with _LOCK:
        return _load_all().get(key) or {"summary": "", "facts": [], "updated_at": ""}


def memory_text(key: str) -> str:
    """拼进 prompt 的记忆文本：永久事实单独一段，放在最前面。"""
    memory = load_memory(key)
    permanent = [fact for fact in memory["facts"] if fact["permanent"]]
    others = [fact for fact in memory["facts"] if not fact["permanent"]]
    if not memory["summary"] and not memory["facts"]:
        return ""

    blocks = []
    if permanent:
        blocks.append(
            "PERMANENT FACTS — the user has repeated or stressed these. "
            "Never forget them, never contradict them, never ask about them again:\n"
            + "\n".join(f"- {fact['text']}" for fact in permanent)
        )
    if memory["summary"]:
        blocks.append("SUMMARY OF THIS USER:\n" + memory["summary"])
    if others:
        blocks.append(
            "OTHER KNOWN FACTS (less certain, mention only when relevant):\n"
            + "\n".join(f"- {fact['text']}" for fact in others)
        )
    return "\n\n".join(blocks)


def clear_memory(key: str) -> None:
    with _LOCK:
        personas = _load_all()
        if key in personas:
            personas.pop(key)
            _save_all(personas)


def _index_list(value, size: int) -> list[int]:
    """模型返回的 1-based 序号列表 -> 去重的 0-based 下标。"""
    if not isinstance(value, (list, tuple)):
        return []
    result: list[int] = []
    for item in value:
        try:
            index = int(item) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < size and index not in result:
            result.append(index)
    return result


def _clean_list(value, limit: int) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\n；;]+", value)
    if not isinstance(value, (list, tuple)):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _one_line(item).strip("-• ").strip()[:_MAX_FACT_CHARS]
        if text and not any(_similar(text, old) for old in cleaned):
            cleaned.append(text)
    return cleaned[:limit]


def _prune(facts: list[dict]) -> list[dict]:
    """淡忘非永久事实，再按"永久优先 + 提到次数"截断。"""
    cutoff = _today() - timedelta(days=_DECAY_DAYS)
    kept = []
    for fact in facts:
        if fact["permanent"]:
            kept.append(fact)
            continue
        last = _parse_day(fact["last"])
        if fact["count"] <= 1 and last and last < cutoff:
            continue
        kept.append(fact)

    permanent = [fact for fact in kept if fact["permanent"]][:_MAX_PERMANENT]
    others = [fact for fact in kept if not fact["permanent"]]
    others.sort(key=lambda fact: (fact["count"], fact["last"]), reverse=True)
    return permanent + others[: max(0, _MAX_FACTS - len(permanent))]


def _merge(
    facts: list[dict],
    *,
    new_texts: list[str],
    repeated_texts: list[str],
    permanent_texts: list[str],
    stress: bool,
) -> list[dict]:
    """把这一轮的变化合并进**当前**记忆。

    模型返回的是 prompt 里的编号，这里先换回事实原文、再按相似度匹配，
    而不是直接拿编号当下标：后台更新和侧边栏的钉/删可能同时发生，
    编号一旦错位就会改到别人的记忆上。
    """
    stamp = _now()
    facts = [dict(fact) for fact in facts]

    def find(text: str) -> dict | None:
        return next((fact for fact in facts if _similar(fact["text"], text)), None)

    for text in repeated_texts:
        match = find(text)
        if match:
            match["count"] += 1
            match["last"] = stamp
            if stress:
                match["permanent"] = True
    for text in permanent_texts:
        match = find(text)
        if match:
            match["permanent"] = True
            match["count"] = max(match["count"], _PERMANENT_AT)

    for text in new_texts:
        match = find(text)
        if match:
            match["count"] += 1
            match["last"] = stamp
            if stress:
                match["permanent"] = True
            continue
        fact = _new_fact(text, stamp=stamp, permanent=stress)
        if fact:
            facts.append(fact)

    for fact in facts:
        if fact["count"] >= _PERMANENT_AT:
            fact["permanent"] = True

    return _prune(facts)


_MEMORY_PROMPT = """You maintain the long-term memory of a roleplay companion.

PERSONA
{label}

CURRENT MEMORY
Summary: {summary}
Numbered facts:
{facts}

NEW EXCHANGE
User: {user}
Companion: {reply}

TASK
Only report what CHANGED. The app merges your answer into the stored memory,
so you never need to repeat facts that are already listed.

- summary: rewrite the short profile of this user with the new exchange folded in,
  at most 200 Chinese characters, third person ("用户…"). Keep it stable.
- new_facts: facts first learned in THIS exchange that are NOT already in the numbered
  list. Max 3, Simplified Chinese, third person, each at most 30 characters.
  Stable things only: identity, city, job/school, relationships, preferences,
  recurring goals or problems. [] if nothing new.
- repeated: numbers of the listed facts the user clearly mentioned AGAIN in this
  message. [] if unsure — do not guess.
- permanent: numbers of listed facts that must never be forgotten (name, city,
  job/school, family, core identity) or that the user stressed. [] if none.
- stress: true only if the user explicitly asked to remember something or stressed
  that it matters ("记住", "别再忘", "我说过很多次", "always remember", "don't forget").

Output JSON only:
{{"summary": "...", "new_facts": ["..."], "repeated": [1], "permanent": [2], "stress": false}}
"""


def update_memory(
    key: str,
    user_message: str,
    assistant_reply: str,
    persona_label: str = "",
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """把这一轮对话合并进长期记忆；失败时保留旧记忆，绝不整份覆盖。

    调用方现在在后台线程里跑它，所以 provider/model 必须显式传进来；
    线程里读不到 Streamlit 的 session_state。
    """
    old = load_memory(key)
    numbered = "\n".join(
        f"{index + 1}. {fact['text']}" + (" [PERMANENT]" if fact["permanent"] else "")
        for index, fact in enumerate(old["facts"])
    ) or "(empty)"
    prompt = _MEMORY_PROMPT.format(
        label=persona_label or key,
        summary=old["summary"] or "(empty)",
        facts=numbered,
        user=(user_message or "").strip()[:1500],
        reply=(assistant_reply or "").strip()[:1500],
    )

    try:
        data = call_llm_json(
            prompt,
            temperature=0.2,
            num_predict=600,
            fallback={},
            timeout=45,
            provider=provider,
            model=model,
        )
    except Exception:
        logger.exception("更新角色记忆失败（%s）", key)
        return old

    if not isinstance(data, dict) or not data:
        return old

    # 编号 -> 原文：merge 时按原文匹配当前记忆，避免编号错位。
    snapshot = old["facts"]
    repeated_texts = [
        snapshot[index]["text"]
        for index in _index_list(data.get("repeated"), len(snapshot))
    ]
    permanent_texts = [
        snapshot[index]["text"]
        for index in _index_list(data.get("permanent"), len(snapshot))
    ]
    new_texts = _clean_list(data.get("new_facts"), limit=3)
    stress = bool(data.get("stress")) or bool(_STRESS_RE.search(user_message or ""))
    summary = _one_line(data.get("summary"))[:_MAX_SUMMARY] or old["summary"]

    if not new_texts and not repeated_texts and not permanent_texts and not summary:
        return old

    # 只在真正的读-改-写上锁，LLM 调用不占锁：后台线程和侧边栏手动操作
    # 因此不会互相覆盖，也不会把界面卡住。
    with _LOCK:
        personas = _load_all()
        current = personas.get(key) or {"summary": "", "facts": [], "updated_at": ""}
        merged = _merge(
            current["facts"],
            new_texts=new_texts,
            repeated_texts=repeated_texts,
            permanent_texts=permanent_texts,
            stress=stress,
        )
        summary = summary or current["summary"]
        if not merged and not summary:
            return old
        updated = {"summary": summary, "facts": merged, "updated_at": _now()}
        personas[key] = updated
        _save_all(personas)
    return updated


def remember(key: str, text: str, permanent: bool = True) -> bool:
    """直接写入一条用户明确要求记住的事实，不调用模型。"""
    text = _one_line(text).strip("-• ").strip()[:_MAX_FACT_CHARS]
    if not text:
        return False
    with _LOCK:
        personas = _load_all()
        current = personas.get(key) or {"summary": "", "facts": [], "updated_at": ""}
        merged = _merge(
            current["facts"],
            new_texts=[text],
            repeated_texts=[],
            permanent_texts=[],
            stress=bool(permanent),
        )
        personas[key] = {
            "summary": current["summary"],
            "facts": merged,
            "updated_at": _now(),
        }
        _save_all(personas)
    return True


def set_permanent(key: str, text: str, permanent: bool = True) -> bool:
    """手动把一个事实钉成永久 / 取消永久。"""
    with _LOCK:
        personas = _load_all()
        persona = personas.get(key)
        if not persona:
            return False
        for fact in persona["facts"]:
            if _similar(fact["text"], text):
                fact["permanent"] = bool(permanent)
                if permanent:
                    fact["count"] = max(fact["count"], _PERMANENT_AT)
                else:
                    # 取消永久记忆后，重新按“被提到几次”从头算。
                    fact["count"] = 0
                persona["updated_at"] = _now()
                _save_all(personas)
                return True
    return False


def delete_fact(key: str, text: str) -> bool:
    with _LOCK:
        personas = _load_all()
        persona = personas.get(key)
        if not persona:
            return False
        before = len(persona["facts"])
        persona["facts"] = [
            fact for fact in persona["facts"] if not _similar(fact["text"], text)
        ]
        if len(persona["facts"]) == before:
            return False
        persona["updated_at"] = _now()
        _save_all(personas)
        return True


def _pin_button_css(key: str) -> str:
    """把记忆里的 📌 固定成小方块。

    用容器的 key 限定作用范围（Streamlit 会给带 key 的容器加 st-key-<key>
    类名），这样侧边栏里其它按钮不会被一起改小。
    """
    container = f"memory_facts_{key}"
    selectors = ", ".join(
        f".st-key-{name} button"
        for name in (container, container.replace("_", "-"))
    )
    return (
        "<style>"
        f"{selectors}{{"
        "width:1.95rem !important;min-width:1.95rem !important;"
        "height:1.95rem !important;min-height:1.95rem !important;"
        "padding:0 !important;border-radius:.5rem;font-size:.95rem;line-height:1;"
        "display:inline-flex;align-items:center;justify-content:center;"
        "}"
        "</style>"
    )


def _fact_row(key: str, fact: dict, *, permanent: bool) -> None:
    import streamlit as st

    label = ("📌 " if permanent else "· ") + fact["text"]
    text_col, action_col = st.columns([6, 1], vertical_alignment="center")
    text_col.caption(label)
    digest = hashlib.md5(fact["text"].encode("utf-8")).hexdigest()[:8]
    if permanent:
        if action_col.button(
            "🔓",
            key=f"mem_pin_{key}_{digest}",
            help="取消永久记忆",
        ):
            set_permanent(key, fact["text"], permanent=False)
            st.rerun()
    else:
        if action_col.button(
            "🗑",
            key=f"mem_delete_{key}_{digest}",
            help="删除这条记忆",
        ):
            delete_fact(key, fact["text"])
            st.rerun()


def render_memory_sidebar(key: str, title: str = "记忆") -> None:
    """侧边栏里默认收起的记忆区：永久和临时分开；临时记忆可直接删除。

    「清空{title}」会删掉这一份记忆的全部内容，所以和「重新开始聊天」一样
    先弹确认框：点按钮只打开弹窗，确认后才真正清空。
    """
    import streamlit as st

    confirm_key = f"mem_clear_confirm_{key}"

    @st.dialog(f"清空{title}")
    def _confirm_clear() -> None:
        st.write(f"确认清空「{title}」里的全部内容？清空后无法恢复。")
        left, right = st.columns(2)
        if left.button(
            "确认清空",
            key=f"mem_clear_yes_{key}",
            use_container_width=True,
        ):
            clear_memory(key)
            st.session_state.pop(confirm_key, None)
            st.rerun()
        if right.button(
            "取消",
            key=f"mem_clear_no_{key}",
            use_container_width=True,
        ):
            st.session_state.pop(confirm_key, None)
            st.rerun()

    memory = load_memory(key)
    permanent = [fact for fact in memory["facts"] if fact["permanent"]]
    others = [fact for fact in memory["facts"] if not fact["permanent"]]

    with st.sidebar:
        st.markdown(_pin_button_css(key), unsafe_allow_html=True)
        with st.expander(
            title,
            expanded=False,
            key=f"memory_expander_{key}",
        ):
            if not memory["facts"]:
                st.caption("聊几次后，这里会记住关于你的重要信息。")
            with st.container(key=f"memory_facts_{key}"):
                for fact in permanent:
                    _fact_row(key, fact, permanent=True)
                if permanent and others:
                    st.divider()
                for fact in others:
                    _fact_row(key, fact, permanent=False)

            st.caption(
                "同一件事提到 3 次会自动变成永久记忆；说「记住……」会立即固化。"
                "很久不提、只提过一次的普通记忆会淡忘。"
            )
            if st.button(f"清空{title}", key=f"mem_clear_{key}"):
                st.session_state[confirm_key] = True
                st.rerun()

    if st.session_state.get(confirm_key):
        _confirm_clear()


__all__ = [
    "clear_memory",
    "delete_fact",
    "load_memory",
    "memory_text",
    "remember",
    "render_memory_sidebar",
    "set_permanent",
    "update_memory",
]
