# utils/Notebook.py

"""单词 / 词组笔记本的数据层。

- 数据保存在 data/notebook.json，写入是原子的。
- 新增时如果没填中文意思 / 标签 / 分组，会自动调用模型补全：
  词性前缀、一词多义、雅思分类标签、语义分组。
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from utils.storage import save_json

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_PATH = Path(
    os.getenv("NOTEBOOK_PATH") or (_PROJECT_ROOT / "data" / "notebook.json")
)
_LOCK = threading.RLock()

_TAG_TAXONOMY = [
    "教育", "工作", "科技", "环境", "健康", "社会", "文化", "媒体",
    "旅行", "人物", "情绪", "描述", "生活", "观点", "口语", "写作",
    "Part 2", "Part 3",
]

_ENRICH_PROMPT = """You are an IELTS vocabulary notebook assistant.

WORD / PHRASE
__TERM__

MEANING ALREADY PROVIDED (keep exactly if not empty)
__MEANING__

REQUIRED SENSES (if not "(none)", return exactly these, in order)
__REQUIRED__

MANUAL EXAMPLE (if not "(none)")
__EXAMPLE__

EXISTING GROUPS (reuse one if the meaning is closely related)
__GROUPS__

EXISTING TAGS (reuse when appropriate)
__TAGS__

Return JSON:
{"senses": [{"pos": "n.", "meaning": "氛围", "example": "The cafe has a relaxed vibe."}], "tags": ["..."], "group": "..."}

SENSE RULES
- If REQUIRED SENSES is not "(none)", return exactly one sense for each item, in the same order, with the same pos and meaning. Do not add, remove, merge, or reorder senses.
- If MEANING ALREADY PROVIDED is empty, identify 1-3 common senses per part of speech. Omit rare or technical senses.
- pos: n. v. a. ad. phr. etc.
- meaning: Chinese gloss only, no part-of-speech prefix, concise, like class notes.
- Every sense's meaning must be ONE short gloss. Do not put "/", "；" or ";" inside a single sense.
- Do not use near-synonyms as separate senses. "开心的/高兴的" is one sense.
- "特征" and "特点" are near-synonyms: return ONE sense, e.g. n. 特征. "优点" and "缺点" are opposites: keep both.
- Before output, compare every pair of glosses under the same part of speech. Merge paraphrases; keep opposites and genuinely different concepts.
- Every sense must have exactly one example.
- example: one natural IELTS-level English sentence, roughly 8-20 words, clearly showing THIS sense. No Chinese translation, no brackets, no label.
- If MANUAL EXAMPLE is not "(none)": assign it verbatim to the sense it actually illustrates, and generate examples for all other senses. Never change the manual sentence. If it does not fit any sense, attach it to the closest one.
- MANUAL EXAMPLE may contain multiple lines. Treat one line as one example; when the number of lines matches the number of senses, assign them in order.
- If MEANING ALREADY PROVIDED contains "/" senses, keep each "/" gloss as a separate sense and give each its own example.

TAG RULES
- Choose 1-3 tags from this IELTS taxonomy: __TAXONOMY__
- Reuse an existing tag when it fits.

GROUP RULES
- A short Chinese semantic cluster, 2-6 characters.
- Prefer one of these standard groups when it fits: 积极情绪, 消极情绪, 态度表达, 人物性格, 学习动作, 工作职场, 科技产品, 环境问题, 旅行经历, 日常场所, 日常物品, 饮食健康, 媒体娱乐, 社会现象, 时间频率, 程度描述, 因果关系.
- NEVER use 程度描述 as a default or fallback. Use it ONLY when the dominant meaning is degree or intensity (e.g. substantial, constant).
- Do NOT use 程度描述 for readiness, atmosphere, time, objects, actions, people, emotions or places.
- Choose the most precise group. If unsure, create a new 2-6 character group instead of using 程度描述.
- Only reuse an EXISTING GROUP if the new meaning is a near-synonym or the same narrow situation.
- If no existing or standard group fits, create a new concise group. Avoid "其他" unless nothing fits.
- The group must describe the meaning, not the part of speech or a broad tag.
- Examples: all set -> 状态描述; vibe -> 氛围感受; timeless / back then -> 时间频率; substantial / constant -> 程度描述.

Output JSON only.
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _split_examples(value) -> list[str]:
    """例句可以一行一条；换行是分隔符，不把一句话从中间拆开。"""
    if isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = str(value or "").splitlines()
    examples: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in examples:
            examples.append(text)
    return examples


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, (list, tuple)):
        items = list(tags)
    else:
        items = re.split(r"[,，;；]+", str(tags or ""))
    cleaned: list[str] = []
    for item in items:
        tag = _one_line(item)
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


_POS_RE = re.compile(
    r"^\s*(n|v|a|ad|adv|adj|prep|conj|pron|phr|num|int)\.\s*", re.I
)
_POS_CANON = {"adj": "a", "adv": "ad"}


def parse_meaning(meaning: str) -> list[dict]:
    """把 "n. 银行/河岸；v. 存储" 拆成逐条义项。"""
    senses: list[dict] = []
    for chunk in re.split(r"[；;]", _one_line(meaning)):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _POS_RE.match(chunk)
        if match:
            raw_pos = match.group(1).lower()
            pos = _POS_CANON.get(raw_pos, raw_pos) + "."
            body = chunk[match.end() :]
        else:
            pos = ""
            body = chunk
        for gloss in re.split(r"[/／]", body):
            gloss = _one_line(gloss)
            if gloss:
                senses.append({"pos": pos, "meaning": gloss, "example": ""})
    return senses


def format_meaning(senses: list[dict]) -> str:
    groups: list[list] = []
    for sense in senses:
        pos = _one_line(sense.get("pos"))
        gloss = _one_line(sense.get("meaning"))
        if not gloss:
            continue
        if groups and groups[-1][0] == pos:
            groups[-1][1].append(gloss)
        else:
            groups.append([pos, [gloss]])
    parts = []
    for pos, glosses in groups:
        body = "/".join(glosses)
        parts.append(f"{pos} {body}".strip())
    return "；".join(parts)


def _clean_senses(raw, required=None, manual_examples=None) -> list[dict]:
    cleaned: list[dict] = []
    if isinstance(raw, (list, tuple)):
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            pos = _one_line(item.get("pos")).lower().rstrip(".")
            pos = _POS_CANON.get(pos, pos)
            if pos:
                pos += "."
            gloss = _one_line(item.get("meaning"))
            if not gloss:
                continue
            match = _POS_RE.match(gloss)
            if match:
                if not pos:
                    raw_pos = match.group(1).lower()
                    pos = _POS_CANON.get(raw_pos, raw_pos) + "."
                gloss = _one_line(gloss[match.end() :])
            if not gloss:
                continue
            gloss = (
                gloss.replace("；", "、")
                .replace(";", "、")
                .replace("/", "、")
                .replace("／", "、")
            )
            cleaned.append(
                {
                    "pos": pos,
                    "meaning": gloss,
                    "example": str(item.get("example") or "").strip(),
                }
            )

    if required:
        aligned = []
        for index, sense in enumerate(required):
            example = cleaned[index]["example"] if index < len(cleaned) else ""
            aligned.append(
                {
                    "pos": sense["pos"],
                    "meaning": sense["meaning"],
                    "example": example,
                }
            )
        cleaned = aligned

    last_pos = ""
    for sense in cleaned:
        if sense["pos"]:
            last_pos = sense["pos"]
        elif last_pos:
            sense["pos"] = last_pos

    manual_examples = (
        [manual_examples]
        if isinstance(manual_examples, str)
        else list(manual_examples or [])
    )
    manual = [str(item or "").strip() for item in manual_examples if str(item or "").strip()]
    if manual and cleaned:
        if len(manual) == len(cleaned):
            for sense, example in zip(cleaned, manual):
                sense["example"] = example
        elif len(manual) == 1:
            if not any(
                manual[0] in sense["example"]
                for sense in cleaned
                if sense["example"]
            ):
                target = next(
                    (sense for sense in cleaned if not sense["example"]), cleaned[0]
                )
                target["example"] = manual[0]
        else:
            for sense, example in zip(cleaned, manual):
                if not sense["example"]:
                    sense["example"] = example

    deduped: list[dict] = []
    for sense in cleaned:
        same = next(
            (
                item
                for item in deduped
                if item["pos"] == sense["pos"]
                and item["meaning"] == sense["meaning"]
            ),
            None,
        )
        if same is None:
            deduped.append(sense)
        elif not same.get("example") and sense.get("example"):
            same["example"] = sense["example"]

    return deduped[:8]


def _fill_missing_examples(
    term: str, senses: list[dict], manual_example: str = ""
) -> list[dict]:
    """第一遍漏掉例句时，针对缺失义项再补；保证每个义项都有例句。"""
    for _ in range(2):
        missing = [sense for sense in senses if not sense.get("example")]
        if not missing:
            break

        numbered = "\n".join(
            f"{index + 1}. {sense['pos']} {sense['meaning']}".strip()
            for index, sense in enumerate(missing)
        )
        prompt = f"""You write IELTS-level example sentences.

WORD / PHRASE: {term}

SENSES THAT STILL NEED EXAMPLES (treat each as distinct; do not merge or skip)
{numbered}

MANUAL EXAMPLE: {manual_example or "(none)"}

Write ONE natural English sentence for each listed sense, 8-20 words, clearly showing that exact meaning.
If MANUAL EXAMPLE fits one of these senses, use it verbatim there.
No Chinese translation. Every listed sense needs one example.
Output JSON only:
{{"examples": ["...", "..."]}}
"""
        try:
            from utils.llm import call_llm_json

            data = call_llm_json(
                prompt, temperature=0.3, num_predict=1000, fallback={}, timeout=45
            )
        except Exception:
            logger.exception("补全义项例句失败")
            data = {}

        examples = data.get("examples") if isinstance(data, dict) else None
        if isinstance(examples, (list, tuple)):
            for sense, example in zip(missing, examples):
                value = _one_line(example)
                if value and not sense.get("example"):
                    sense["example"] = value

    # 最后一招：逐义项单独要例句，避免模型把两个义项当成同一个。
    other_glosses = "、".join(
        sense["meaning"] for sense in senses if sense.get("meaning")
    )
    for sense in senses:
        if sense.get("example"):
            continue
        prompt = f"""You write one IELTS-level example sentence.

WORD / PHRASE: {term}
TARGET SENSE: {sense['pos']} {sense['meaning']}
OTHER SENSES (do not use): {other_glosses or "(none)"}

Write ONE natural English sentence, 8-20 words, where "{term}" is used in the TARGET SENSE,
not in any other sense. Do not translate. Output JSON only:
{{"example": "..."}}
"""
        try:
            from utils.llm import call_llm_json

            data = call_llm_json(
                prompt, temperature=0.3, num_predict=200, fallback={}, timeout=30
            )
        except Exception:
            data = {}
        example = _one_line(data.get("example")) if isinstance(data, dict) else ""
        if example:
            sense["example"] = example
    return senses


def _coalesce_empty_senses(senses: list[dict]) -> list[dict]:
    """极端情况下仍缺例句时，把同词性的空义项合并到前一个义项。"""
    merged: list[dict] = []
    for sense in senses:
        if (
            not sense.get("example")
            and merged
            and merged[-1].get("pos") == sense.get("pos")
        ):
            merged[-1]["meaning"] = (
                merged[-1]["meaning"].rstrip("/") + "/" + sense["meaning"]
            )
        else:
            merged.append(sense)
    return merged


def _normalize(raw: dict) -> dict:
    created = str(raw.get("created_at") or _now())
    meaning = _one_line(raw.get("meaning"))
    example = str(raw.get("example", "")).strip()
    required = parse_meaning(meaning)
    raw_senses = raw.get("senses")
    if raw_senses:
        senses = _clean_senses(raw_senses, required=None, manual_examples=None)
    else:
        senses = _clean_senses(
            None,
            required=required or None,
            manual_examples=[example] if example else [],
        )
    if not senses and required:
        senses = required
        if example and len(senses) == 1:
            senses[0]["example"] = example
    if senses and (not meaning or len(required) != len(senses)):
        meaning = format_meaning(senses)
    if not example and senses:
        example = next(
            (sense["example"] for sense in senses if sense["example"]), ""
        )
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:12]),
        "term": _one_line(raw.get("term")),
        "meaning": meaning,
        "senses": senses,
        "example": example,
        "note": str(raw.get("note", "")).strip(),
        "tags": _clean_tags(raw.get("tags", [])),
        "group": _one_line(raw.get("group"))[:12],
        "source": _one_line(raw.get("source")),
        "created_at": created,
        "updated_at": str(raw.get("updated_at") or created),
    }


def _load_unlocked() -> list[dict]:
    if not NOTEBOOK_PATH.exists():
        return []
    try:
        data = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("entries", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("term", "")).strip():
            entries.append(_normalize(item))
    return entries


def _save_unlocked(entries: list[dict]) -> None:
    save_json(NOTEBOOK_PATH, {"version": 1, "entries": entries})


def load_entries() -> list[dict]:
    with _LOCK:
        return _load_unlocked()


def _enrich(
    term: str, meaning: str = "", entries=None, example: str = ""
) -> dict:
    """调用模型补全逐义项翻译 / 例句 / 标签 / 语义分组。"""
    entries = entries or []
    groups: list[str] = []
    seen_tags: list[str] = []
    for entry in reversed(entries):
        group = entry.get("group") or ""
        if group and group not in groups:
            groups.append(group)
        for tag in entry.get("tags", []):
            if tag not in seen_tags:
                seen_tags.append(tag)

    required = parse_meaning(meaning)
    manual_examples = _split_examples(example)
    prompt = (
        _ENRICH_PROMPT.replace("__TERM__", term)
        .replace("__MEANING__", meaning or "(none)")
        .replace(
            "__REQUIRED__",
            json.dumps(required, ensure_ascii=False) if required else "(none)",
        )
        .replace(
            "__EXAMPLE__",
            "\n".join(manual_examples) if manual_examples else "(none)",
        )
        .replace("__GROUPS__", "、".join(groups[:25]) or "(none)")
        .replace("__TAGS__", "、".join(seen_tags[:30]) or "(none)")
        .replace("__TAXONOMY__", "、".join(_TAG_TAXONOMY))
    )

    try:
        from utils.llm import call_llm_json

        data = call_llm_json(
            prompt, temperature=0.2, num_predict=1600, fallback={}, timeout=45
        )
    except Exception:
        logger.exception("笔记本自动补全失败")
        data = {}

    senses = _clean_senses(
        data.get("senses"),
        required=required or None,
        manual_examples=manual_examples,
    )
    if senses and any(not sense.get("example") for sense in senses):
        senses = _fill_missing_examples(
            term, senses, "\n".join(manual_examples)
        )
    if senses and any(not sense.get("example") for sense in senses):
        senses = _coalesce_empty_senses(senses)
    if not senses and required:
        senses = required
        for sense, manual in zip(senses, manual_examples):
            sense["example"] = manual
        if manual_examples and not senses[0]["example"]:
            senses[0]["example"] = manual_examples[0]

    generated_meaning = meaning.strip() or format_meaning(senses)
    generated_example = (
        manual_examples[0] if manual_examples else next(
            (sense["example"] for sense in senses if sense["example"]), ""
        )
    )
    generated_tags = _clean_tags(data.get("tags"))
    group = _one_line(data.get("group"))[:12]
    return {
        "senses": senses,
        "meaning": generated_meaning,
        "example": generated_example,
        "tags": generated_tags,
        "group": group,
    }


def add_entry(
    term: str,
    meaning: str = "",
    example: str = "",
    note: str = "",
    tags="",
    source: str = "",
    group: str = "",
) -> dict:
    term = _one_line(term)
    if not term:
        raise ValueError("term is empty")

    meaning = _one_line(meaning)
    example = str(example or "").strip()
    group = _one_line(group)
    tags_list = _clean_tags(tags)

    entries = load_entries()
    meta = _enrich(term, meaning, entries, example)
    meaning = meaning or meta["meaning"]
    senses = meta["senses"] or parse_meaning(meaning)
    if senses and (not meaning or len(parse_meaning(meaning)) != len(senses)):
        meaning = format_meaning(senses)
    tags_list = tags_list or meta["tags"]
    group = group or meta["group"]
    manual_examples = _split_examples(example)
    example = manual_examples[0] if manual_examples else meta["example"]

    entry = _normalize(
        {
            "term": term,
            "meaning": meaning,
            "senses": senses,
            "example": example,
            "note": note,
            "tags": tags_list or ["未分类"],
            "group": group or "未分组",
            "source": source,
        }
    )
    with _LOCK:
        entries = _load_unlocked()
        entries.append(entry)
        _save_unlocked(entries)
    return entry


def update_entry(entry_id: str, **fields) -> dict | None:
    allowed = {"term", "meaning", "example", "note", "tags", "source", "group"}
    with _LOCK:
        entries = _load_unlocked()
        for entry in entries:
            if entry["id"] != entry_id:
                continue
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "tags":
                    entry[key] = _clean_tags(value) or ["未分类"]
                elif key == "term":
                    cleaned = _one_line(value)
                    if not cleaned:
                        raise ValueError("term is empty")
                    entry[key] = cleaned
                elif key == "group":
                    entry[key] = _one_line(value)[:12] or "未分组"
                elif key == "meaning":
                    entry[key] = _one_line(value)
                else:
                    entry[key] = str(value or "").strip()
            entry["updated_at"] = _now()
            _save_unlocked(entries)
            return entry
    return None


def refresh_entry_examples(
    entry_id: str, manual_examples=None
) -> dict | None:
    """按当前意思重新生成/补齐逐义项例句；手动例句会被保留并归位。"""
    entries = load_entries()
    entry = next((item for item in entries if item["id"] == entry_id), None)
    if entry is None:
        return None
    if manual_examples is None:
        manual_examples = [
            sense["example"]
            for sense in entry.get("senses", [])
            if sense.get("example")
        ] or _split_examples(entry["example"])
    manual_examples = _split_examples(manual_examples)
    others = [item for item in entries if item["id"] != entry_id]
    meta = _enrich(
        entry["term"],
        entry["meaning"],
        others,
        "\n".join(manual_examples),
    )
    if not meta["senses"]:
        return entry
    entry["senses"] = meta["senses"]
    if not entry["meaning"]:
        entry["meaning"] = meta["meaning"]
    entry["example"] = (
        manual_examples[0] if manual_examples else meta["example"]
    )
    entry["updated_at"] = _now()
    with _LOCK:
        _save_unlocked(entries)
    return entry


def backfill_entries() -> int:
    """给旧笔记补全翻译 / 例句 / 标签 / 分组，返回处理的条数。"""

    def needs_examples(entry: dict) -> bool:
        senses = entry.get("senses") or []
        return not senses or any(not sense.get("example") for sense in senses)

    entries = load_entries()
    pending = [
        entry
        for entry in entries
        if not entry["meaning"]
        or not entry["tags"]
        or entry["tags"] == ["未分类"]
        or not entry["group"]
        or entry["group"] == "未分组"
        or needs_examples(entry)
    ]
    if not pending:
        return 0

    touched = 0
    for entry in pending:
        others = [item for item in entries if item is not entry]
        current_examples = [
            sense["example"]
            for sense in entry.get("senses", [])
            if sense.get("example")
        ] or _split_examples(entry["example"])
        meta = _enrich(
            entry["term"],
            entry["meaning"],
            others,
            "\n".join(current_examples),
        )
        changed = False
        if meta["senses"]:
            entry["senses"] = meta["senses"]
            changed = True
        if not entry["meaning"] and meta["meaning"]:
            entry["meaning"] = meta["meaning"]
            changed = True
        if not entry["example"] and meta["example"]:
            entry["example"] = meta["example"]
            changed = True
        if (not entry["tags"] or entry["tags"] == ["未分类"]) and meta["tags"]:
            entry["tags"] = meta["tags"]
            changed = True
        if (not entry["group"] or entry["group"] == "未分组") and meta["group"]:
            entry["group"] = meta["group"]
            changed = True
        if changed:
            entry["updated_at"] = _now()
            touched += 1

    if touched:
        with _LOCK:
            _save_unlocked(entries)
    return touched


def delete_entry(entry_id: str) -> bool:
    with _LOCK:
        entries = _load_unlocked()
        kept = [entry for entry in entries if entry["id"] != entry_id]
        if len(kept) == len(entries):
            return False
        _save_unlocked(kept)
        return True


def stats(entries: list[dict] | None = None) -> dict:
    entries = load_entries() if entries is None else entries
    week_ago = datetime.now().timestamp() - 7 * 24 * 3600
    week_count = 0
    for entry in entries:
        try:
            if datetime.strptime(entry["created_at"], "%Y-%m-%d %H:%M:%S").timestamp() >= week_ago:
                week_count += 1
        except ValueError:
            pass
    return {
        "total": len(entries),
        "week": week_count,
        "tags": len({tag for entry in entries for tag in entry["tags"]}),
        "with_example": sum(
            1
            for entry in entries
            if entry["example"]
            or any(sense.get("example") for sense in entry.get("senses", []))
        ),
    }


def order_by_relevance(entries: list[dict]) -> list[dict]:
    """按语义相近程度排序，不显示分组；相关的词相邻，新的优先。"""
    if len(entries) < 2:
        return list(entries)

    stop_chars = set("的了是有在和与及之其")

    def features(entry: dict) -> set[str]:
        tokens: set[str] = set()
        glosses = [
            sense.get("meaning", "")
            for sense in entry.get("senses", [])
            if sense.get("meaning")
        ] or [entry.get("meaning", "")]
        for gloss in glosses:
            chars = [
                char
                for char in gloss
                if "\u4e00" <= char <= "\u9fff" and char not in stop_chars
            ]
            tokens.update(chars)
            for index in range(len(gloss) - 1):
                pair = gloss[index : index + 2]
                if all("\u4e00" <= char <= "\u9fff" for char in pair):
                    tokens.add(pair)
        tokens.update(f"tag:{tag}" for tag in entry.get("tags", []))
        if entry.get("group"):
            tokens.add(f"group:{entry['group']}")
        tokens.update(
            f"en:{word}"
            for word in re.findall(r"[a-z]+", entry.get("term", "").lower())
            if len(word) > 1
        )
        return tokens

    feature_cache = {entry["id"]: features(entry) for entry in entries}

    def similarity(left: dict, right: dict) -> float:
        a = feature_cache[left["id"]]
        b = feature_cache[right["id"]]
        if not a or not b:
            return 0.0
        base = len(a & b) / len(a | b)
        if left.get("group") and left.get("group") == right.get("group"):
            base += 0.25
        return base

    remaining = sorted(
        entries, key=lambda entry: entry.get("created_at", ""), reverse=True
    )
    ordered = [remaining.pop(0)]
    while remaining:
        window = ordered[-3:]

        def score(candidate: dict):
            best = max(similarity(candidate, item) for item in window)
            return (round(best, 4), candidate.get("created_at", ""))

        best = max(remaining, key=score)
        remaining.remove(best)
        ordered.append(best)
    return ordered


def search_entries(entries: list[dict], query: str) -> list[dict]:
    query = (query or "").strip().lower()
    if not query:
        return entries
    result = []
    for entry in entries:
        haystack = " ".join(
            [
                entry["term"],
                entry["meaning"],
                entry["example"],
                " ".join(
                    f"{sense.get('pos', '')} {sense.get('meaning', '')} {sense.get('example', '')}"
                    for sense in entry.get("senses", [])
                ),
                entry["group"],
                " ".join(entry["tags"]),
            ]
        ).lower()
        if query in haystack:
            result.append(entry)
    return result


def render_quick_add(source: str, key_prefix: str) -> None:
    """侧边栏快速收藏：可选单词 / 词组，或长文本笔记。"""
    import streamlit as st

    from utils.LongNotes import add_note

    with st.expander("➕ 加入笔记本", expanded=False):
        note_type = st.segmented_control(
            "添加到",
            ["单词 / 词组", "长文本"],
            default="单词 / 词组",
            key=f"{key_prefix}_nb_type",
        ) or "单词 / 词组"

        if note_type == "长文本":
            with st.form(f"nb_quick_long_{key_prefix}", clear_on_submit=True):
                content = st.text_area(
                    "长文本内容",
                    key=f"{key_prefix}_ln_content",
                    height=180,
                    placeholder="语法知识、范文、阅读摘录……",
                )
                title = st.text_input(
                    "标题（留空自动生成）", key=f"{key_prefix}_ln_title"
                )
                submitted = st.form_submit_button(
                    "保存长文本", use_container_width=True
                )
                if submitted:
                    if not content.strip():
                        st.warning("先粘贴一些长文本内容")
                    else:
                        with st.spinner(
                            "正在保存..."
                            if title.strip()
                            else "正在生成标题并保存..."
                        ):
                            note = add_note(content, title)
                        st.success(
                            f"已保存长文本：{note['title']}（{note['date']}）"
                        )
                        st.toast(f"📝 已加入长文本：{note['title']}")
            return

        with st.form(f"nb_quick_{key_prefix}", clear_on_submit=True):
            term = st.text_input(
                "单词 / 词组",
                key=f"{key_prefix}_nb_term",
                placeholder="e.g. take ... for granted",
            )
            example = st.text_area(
                "例句（可选，每行一个，按义项顺序）",
                key=f"{key_prefix}_nb_example",
                height=90,
            )
            submitted = st.form_submit_button("保存到笔记本", use_container_width=True)
            if submitted:
                if not term.strip():
                    st.warning("先填一个单词或词组")
                else:
                    with st.spinner("正在补全翻译 / 标签 / 例句..."):
                        entry = add_entry(
                            term,
                            example=example,
                            source=source,
                        )
                    st.success(
                        f"已保存：{entry['term']} ｜ {entry['meaning'] or '待补充'}"
                    )
                    st.toast(f"📓 已加入笔记本：{entry['term']}")
