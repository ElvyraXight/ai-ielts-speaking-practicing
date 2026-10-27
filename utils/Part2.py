# utils/Part2.py

"""IELTS Speaking Part 2 模块。

对外接口（chats/Part2.py 依赖）：
    generate_cue_card()                      -> str
    evaluate_part2_story(user_story, card)   -> dict
    transcribe_audio(audio_file)             -> str
    generate_audio(text, output_file)        -> None

设计要点：
1. 题卡只调用一次大模型：一次性输出 topic + 4 个 bullet，再用本地校验兜底，
   不合格就重试一次，仍不合格则从内置标准题库中随机抽取（保证永远是"常规雅思题"）。
2. 题卡严格贴合官方样式：Describe ... / You should say: / 四条小点。
3. 点评、改写答案、参考范文三个 Agent 都会拿到考生原文，避免"凭空点评"。
"""

import asyncio
import json
import logging
import os
import random
import re
import tempfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import edge_tts
import requests
import whisper

try:
    from dotenv import dotenv_values
except ImportError:  # python-dotenv 可选；没有就用系统环境变量
    dotenv_values = None

logger = logging.getLogger(__name__)

# ----------------------------- 配置 -----------------------------
# 先读 config/.env 与 config/.env.local（后者可放密钥，已在 .gitignore 中）
_ENV_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
_ORIGINAL_ENV_KEYS = {key for key, value in os.environ.items() if value}


def _load_env_file(path: str, *, override: bool = False) -> None:
    """读取 .env 文件；空值不生效，系统环境变量优先级最高。"""
    if dotenv_values is None or not os.path.exists(path):
        return
    try:
        values = dotenv_values(path)
    except Exception:
        return
    for key, value in values.items():
        if not value or key in _ORIGINAL_ENV_KEYS:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value


_load_env_file(os.path.join(_ENV_DIR, ".env"))
_load_env_file(os.path.join(_ENV_DIR, ".env.local"), override=True)

# LLM_PROVIDER: auto / ollama / deepseek
# auto = 配了 DEEPSEEK_API_KEY 就用 DeepSeek，否则用本地 Ollama
LLM_PROVIDER = (os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY", "") or "").strip()
DEEPSEEK_BASE_URL = (
    (os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com") or "").strip().rstrip("/")
    or "https://api.deepseek.com"
)
DEEPSEEK_MODEL = (
    (os.getenv("DEEPSEEK_MODEL", "deepseek-flash") or "").strip() or "deepseek-flash"
)
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT") or os.getenv("OLLAMA_TIMEOUT") or "180")
AUDIO_DIR = os.getenv("AUDIO_DIR", "audio_records")
TTS_VOICE = "en-GB-RyanNeural"

if LLM_PROVIDER == "auto":
    LLM_PROVIDER = "deepseek" if DEEPSEEK_API_KEY else "ollama"
elif LLM_PROVIDER not in ("ollama", "deepseek"):
    logger.warning("未知的 LLM_PROVIDER=%s，使用 ollama", LLM_PROVIDER)
    LLM_PROVIDER = "ollama"

if LLM_PROVIDER == "deepseek" and not DEEPSEEK_API_KEY:
    logger.warning("LLM_PROVIDER=deepseek 但缺少 DEEPSEEK_API_KEY，回退到 Ollama")
    LLM_PROVIDER = "ollama"


def describe_llm() -> str:
    """给页面显示当前使用的模型。"""
    if LLM_PROVIDER == "deepseek":
        return f"DeepSeek · {DEEPSEEK_MODEL}"
    return f"Ollama · {OLLAMA_MODEL}"


logger.info("Part 2 当前模型：%s", describe_llm())

# 最近几次 DeepSeek 调用的真实 token 用量（用于估算费用/排查）
_USAGE_LOG: deque = deque(maxlen=100)


def usage_log() -> list[dict]:
    return list(_USAGE_LOG)


os.makedirs(AUDIO_DIR, exist_ok=True)

# ----------------------------- 延迟加载 Whisper -----------------------------
_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        logger.info("正在加载语音识别模型(Part 2)...")
        _whisper_model = whisper.load_model("base")
        logger.info("加载完毕！")
    return _whisper_model

# ----------------------------- 通用工具 -----------------------------
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_FIRST_PERSON_RE = re.compile(
    r"\b(?:i|me|my|mine|we|us|our|ours|i'm|i've|i'd|we're|we've)\b", re.IGNORECASE
)
_EXAMPLE_RE = re.compile(r"\b(?:e\.g\.|for example|such as)\b", re.IGNORECASE)
_WH_START_RE = re.compile(r"^(?:what|who|whom|whose|where|when|why|how|whether)\b", re.IGNORECASE)
_HABIT_RE = re.compile(
    r"\b(?:every|each|usually|often|always|sometimes|whenever|normally|rarely|on weekends?)\b",
    re.IGNORECASE,
)
_PAST_RE = re.compile(
    r"\b(?:was|were|went|did|had|took|saw|ate|made|got|felt|came|said|told|knew|"
    r"thought|found|gave|left|kept|met|ran|sat|stood|wrote|heard|held|brought|bought|"
    r"caught|taught|began|became|visited|walked|stayed|enjoyed|played|watched|studied|"
    r"travelled|traveled|decided|managed)\b",
    re.IGNORECASE,
)


def _norm_punct(text: str) -> str:
    """统一引号/撇号，避免中文输入法样式标点混进题卡或 TTS。"""
    return (
        str(text)
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2026", "...")
        .replace("\u00a0", " ")
    )


def _safe_json_loads(text: str) -> dict:
    """容错解析 LLM 返回的 JSON，剥离 markdown 围栏并取第一个 {...}。"""
    if not text:
        raise ValueError("empty response")
    text = _JSON_FENCE_RE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found: {text[:200]}")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON root is not an object")
    return data


def _salvage_partial_json(raw: str) -> dict:
    """模型输出被截断或引号没转义时，尽量把字段值抠出来，而不是整条丢弃。"""
    match = re.search(r'"([A-Za-z_]+)"\s*:\s*"(.*)', raw or "", re.S)
    if not match:
        return {}
    key, value = match.group(1), match.group(2).rstrip()
    value = re.sub(r'"\s*\}\s*$', "", value).strip()
    value = value.rstrip('"').rstrip("}").rstrip().rstrip('"')
    try:
        value = json.loads('"' + value + '"')
    except Exception:
        value = value.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    return {key: value.strip()} if value.strip() else {}


def _as_text(value) -> str:
    """模型偶尔把字段返回成嵌套 dict/list，这里统一摊平成可读文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_as_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_as_text(v) for v in value)
    return str(value)


def _call_ollama(
    prompt: str,
    *,
    temperature: float,
    num_predict: int,
    fallback=None,
) -> dict:
    """统一封装 Ollama 调用：JSON 模式、重试一次、解析失败返回 fallback。"""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "num_ctx": 4096,
            "num_predict": num_predict,
        },
    }
    for attempt in range(2):
        raw = ""
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            return _safe_json_loads(raw)
        except requests.RequestException as exc:
            logger.warning("Ollama 请求失败（第 %d 次）：%s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(1.0)
                continue
        except (ValueError, KeyError) as exc:
            logger.warning("Ollama 返回内容无法解析：%s", exc)
            salvaged = _salvage_partial_json(raw)
            if salvaged:
                logger.info("已从截断/异常 JSON 中抢救出字段：%s", list(salvaged))
                return salvaged
            break
    logger.error("Ollama 调用最终失败，返回 fallback")
    return {"_fallback": fallback} if fallback is not None else {}


def _call_deepseek(
    prompt: str,
    *,
    temperature: float,
    num_predict: int,
    fallback=None,
) -> dict:
    """调用 DeepSeek 官方 API（OpenAI 兼容的 /chat/completions + JSON 模式）。"""
    if not DEEPSEEK_API_KEY:
        logger.error("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek")
        return {"_fallback": fallback} if fallback is not None else {}

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are an IELTS Speaking assistant. Reply with ONE valid json object only, no markdown, no extra text.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": num_predict,
        "response_format": {"type": "json_object"},
        # 本 App 要的是快速、便宜的结构化输出；关闭默认开启的 thinking，
        # 否则每次调用会额外生成大量推理 token，费用和延迟都会明显上升。
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(2):
        raw = ""
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
            if resp.status_code >= 400:
                logger.warning(
                    "DeepSeek HTTP %s：%s", resp.status_code, (resp.text or "")[:200]
                )
            resp.raise_for_status()
            body = resp.json()
            usage = body.get("usage") or {}
            if usage:
                _USAGE_LOG.append(
                    {
                        "model": DEEPSEEK_MODEL,
                        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                        "completion_tokens": int(usage.get("completion_tokens") or 0),
                        "cache_hit": int(usage.get("prompt_cache_hit_tokens") or 0),
                        "cache_miss": int(usage.get("prompt_cache_miss_tokens") or 0),
                    }
                )
            raw = ((body.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            return _safe_json_loads(raw)
        except requests.RequestException as exc:
            logger.warning("DeepSeek 请求失败（第 %d 次）：%s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(1.0)
                continue
        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            logger.warning("DeepSeek 返回内容无法解析：%s", exc)
            salvaged = _salvage_partial_json(raw)
            if salvaged:
                logger.info("已从截断/异常 JSON 中抢救出字段：%s", list(salvaged))
                return salvaged
            break
    logger.error("DeepSeek 调用最终失败，返回 fallback")
    return {"_fallback": fallback} if fallback is not None else {}


def _call_llm(
    prompt: str,
    *,
    temperature: float,
    num_predict: int,
    fallback=None,
) -> dict:
    """按 LLM_PROVIDER 分发到 Ollama 或 DeepSeek。"""
    if LLM_PROVIDER == "deepseek":
        return _call_deepseek(
            prompt, temperature=temperature, num_predict=num_predict, fallback=fallback
        )
    return _call_ollama(
        prompt, temperature=temperature, num_predict=num_predict, fallback=fallback
    )

# ----------------------------- 语音 -----------------------------
def transcribe_audio(audio_file) -> str:
    if audio_file is None:
        return ""
    model = get_whisper_model()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_file.getbuffer())
        tmp_path = tmp.name
    try:
        result = model.transcribe(tmp_path, language="en")
        return result["text"].strip()
    except Exception:
        logger.exception("转写失败")
        return ""
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

async def generate_audio(text: str, output_file: str) -> None:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text for TTS")
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(output_file)

# =====================================================================
# 题卡生成
# =====================================================================
_CUE_CARD_PROMPT = """You are a certified IELTS Speaking examiner with 15 years of experience writing Part 2 cue cards.

TASK
Write ONE authentic IELTS Speaking Part 2 cue card about familiar, everyday life, then exactly FOUR bullet points for it.

TOPIC LINE
- Begin with "Describe" and use ONE noun phrase (7-16 words). The topic must be a person, place, object, event, experience, activity or piece of media that any adult candidate can talk about for two minutes.
- Add a natural qualifier: a relative clause (who / that / where), a time reference ("a time when ..."), or a specific situation ("an occasion when ...").
- Do NOT rely on the adjectives "favourite", "interesting" or "important".
- No full stop, no question mark, no Chinese characters.

FOUR BULLET POINTS, in this exact order
1. Identity: what / who / where / when it is (e.g. "what it is", "who this person is", "where it is")
2. Background: how the candidate knows it or does it (e.g. "how you know about it", "when you went there", "how often you do it")
3. Concrete detail: what you did there, what happened that day, or what makes it special. This point MUST begin with "what".
4. Reason, feeling or impact, beginning with "and explain" (e.g. "and explain why you enjoyed it", "and explain how you felt about it")

RULES FOR THE BULLETS
- Point 1 and point 2 must begin with what / who / where / when / how. Point 3 must begin with the word "what". Never begin a point with "one specific ...", "a ..." or a bare noun.
- 4-12 words each, all lowercase, no full stop, no question mark.
- Address the candidate: use "you" and "your". NEVER use "I", "me", "my", "we" or "our".
- No answers, no examples, no "e.g.", no "such as", no slashes, no options, no hints.
- All four points must be different and must belong to the same topic.
- Point 4 must not repeat or rephrase point 3.

VARIETY
- Do not reuse or paraphrase any of these recent topics: __AVOID__
- Rotate the category. If the recent topics are mostly about places, choose a person, object, event, activity or piece of media this time; never produce several place topics in a row.

STYLE EXAMPLES (copy this exact style)
{"topic": "Describe a skill you learned that took a long time to master", "points": ["what the skill is", "when and how you started learning it", "what the most difficult part was", "and explain why you wanted to learn it"]}
{"topic": "Describe a time when you helped a stranger", "points": ["who the person was", "where and when this happened", "what you did to help", "and explain how you felt afterwards"]}

OUTPUT
Return JSON only, exactly in this shape:
{"topic": "Describe ...", "points": ["...", "...", "...", "and explain ..."]}
"""

# 兜底题库：全部是标准雅思 Part 2 题，保证任何情况下都能出一张正常的题卡。
_FALLBACK_CARDS = [
    (
        "Describe a place you like to spend time in",
        ["where it is", "how often you go there", "what you usually do there", "and explain why you like it"],
    ),
    (
        "Describe a person who has influenced you",
        ["who this person is", "how you know this person", "what this person is like", "and explain how they influenced you"],
    ),
    (
        "Describe a time when you helped someone",
        ["who the person was", "where and when it happened", "what you did to help", "and explain how you felt afterwards"],
    ),
    (
        "Describe a skill you learned that took a long time to master",
        ["what the skill is", "when and how you started learning it", "what the most difficult part was", "and explain why you wanted to learn it"],
    ),
    (
        "Describe an important decision you made",
        ["what the decision was", "when and why you made it", "what the result was", "and explain why it was important to you"],
    ),
    (
        "Describe a memorable journey you made",
        ["where you went", "how you travelled there", "what happened during the journey", "and explain why it was memorable"],
    ),
    (
        "Describe a piece of technology you use every day",
        ["what it is", "when you started using it", "what you use it for", "and explain why it is useful to you"],
    ),
    (
        "Describe a book or film that left a strong impression on you",
        ["what it is", "when you first read or watched it", "what it was about", "and explain why it impressed you"],
    ),
    (
        "Describe a public place in your city that you often visit",
        ["where it is", "how often you go there", "what you do there", "and explain why you enjoy going there"],
    ),
    (
        "Describe a traditional festival in your country",
        ["what the festival is", "when it is celebrated", "what people usually do during it", "and explain why it is important to you"],
    ),
    (
        "Describe a shop or market you like to go to",
        ["where it is", "how often you go there", "what you buy there", "and explain why you like it"],
    ),
    (
        "Describe an object you have kept for a long time",
        ["what it is", "when and where you got it", "what it means to you", "and explain how you feel about it"],
    ),
]

# 避免连续抽到相同的题（进程内记忆最近 6 个话题）
_RECENT_TOPICS: deque[str] = deque(maxlen=6)


def _clean_topic(text: str) -> str:
    t = _norm_punct(text or "").strip()
    t = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", t)
    t = re.sub(r"^(?:topic|task)\s*[:\-]\s*", "", t, flags=re.IGNORECASE)
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip().strip('"').strip("'").strip()
    if not t.lower().startswith("describe"):
        match = re.search(r"\bdescribe\b.*", t, flags=re.IGNORECASE)
        if match:
            t = match.group(0)
    t = t.rstrip(" .")
    if t.lower().startswith("describe"):
        t = "Describe" + t[len("describe") :]
    return t


def _clean_bullet(text: str) -> str:
    """把模型输出的小点清理成官方样式：小写、无编号、无例句、无斜杠。"""
    t = _norm_punct(text or "").strip()
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", t)
    t = re.sub(r"\s*\((?:e\.g\.|for example)[^)]*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[,;]?\s*(?:e\.g\.|for example|such as)\b.*$", "", t, flags=re.IGNORECASE)
    t = t.replace(" / ", " and ").replace("/", " and ")
    t = re.sub(r"\s+", " ", t).strip().strip('"').strip("'").strip()
    t = t.rstrip(" .;,")
    if not t:
        return ""
    # 官方题卡的小点一律小写开头（第四条由 _normalise_point4 统一成 "and explain ..."）
    return t[0].lower() + t[1:]


def _normalise_point4(text: str) -> str:
    """第四条统一成 'and explain ...'，且绝不出现 why 重复。"""
    t = _clean_bullet(text)
    if not t:
        return ""
    low = t.lower()
    if low.startswith("and explain"):
        rest = t[len("and explain") :]
    elif low.startswith("explain"):
        rest = t[len("explain") :]
    elif low.startswith("and "):
        rest = t[3:]
    else:
        rest = t
    rest = rest.lstrip(" :,-").strip()
    rest = re.sub(r"^why\s+why\b", "why", rest, flags=re.IGNORECASE)
    if not re.match(r"^(?:why|how|what|whether)\b", rest, flags=re.IGNORECASE):
        rest = f"why {rest}"
    return f"and explain {rest}".strip()


def _topic_is_recent(topic: str, recent: list[str]) -> bool:
    """和最近几道题太像（或只换了几个词）就判定为重复。"""
    current = set(_norm_for_match(topic).split())
    if not current:
        return False
    for old in recent:
        previous = set(_norm_for_match(old).split())
        if not previous:
            continue
        overlap = len(current & previous) / len(current | previous)
        if overlap >= 0.75:
            return True
    return False


def _topic_problem(topic: str) -> Optional[str]:
    if not topic:
        return "空话题"
    if not topic.lower().startswith("describe "):
        return "不是 Describe 开头"
    words = topic.split()
    if not 5 <= len(words) <= 28:
        return f"话题长度异常({len(words)}词)"
    if _FIRST_PERSON_RE.search(topic):
        return "话题里有第一人称"
    if "/" in topic or _EXAMPLE_RE.search(topic):
        return "话题里有斜杠或举例"
    if "?" in topic or _CJK_RE.search(topic):
        return "话题里有问号或中文"
    return None


def _bullet_problem(bullet: str, index: int) -> Optional[str]:
    if not bullet:
        return "空小点"
    words = bullet.split()
    if not 3 <= len(words) <= 14:
        return f"小点长度异常({len(words)}词)"
    if index == 2 and not bullet.lower().startswith("what"):
        return "第3点不是 what 开头"
    if index < 2 and not _WH_START_RE.match(bullet):
        return "小点不是 wh- 从句开头"
    if _FIRST_PERSON_RE.search(bullet):
        return "小点里有第一人称"
    if "/" in bullet:
        return "小点里有斜杠"
    if "?" in bullet:
        return "小点里有问号"
    if _EXAMPLE_RE.search(bullet):
        return "小点里有举例"
    if _CJK_RE.search(bullet):
        return "小点里有中文"
    return None


def _parse_card(data: dict) -> tuple[Optional[str], list[str]]:
    if not isinstance(data, dict):
        return None, []
    topic = _clean_topic(str(data.get("topic", "")))
    raw = data.get("points")
    if isinstance(raw, str):
        raw = re.split(r"\s*(?:\n|;|\|)\s*", raw)
    if not isinstance(raw, list):
        raw = [data.get(f"point{i}") for i in range(1, 5)]
    points = [_clean_bullet(str(p)) for p in raw if p]
    points = [p for p in points if p]
    if len(points) < 4:
        return None, []
    points = points[:4]
    points[3] = _normalise_point4(points[3])
    return topic, points


def _format_card(topic: str, points: list[str]) -> str:
    lines = [topic, "You should say:"]
    lines.extend(f"- {p}" for p in points[:3])
    lines.append(f"- {points[3]}")
    return "\n".join(lines)


def _pick_fallback_card(recent: list[str]) -> tuple[str, list[str]]:
    fresh = [c for c in _FALLBACK_CARDS if c[0] not in recent]
    return random.choice(fresh or _FALLBACK_CARDS)


def generate_cue_card() -> str:
    """生成一张标准的 IELTS Part 2 题卡；本地校验 + 重试 + 内置题库兜底。"""
    avoid = " | ".join(list(_RECENT_TOPICS)[-5:]) or "none"
    prompt = _CUE_CARD_PROMPT.replace("__AVOID__", avoid)

    for attempt in range(2):
        data = _call_llm(
            prompt,
            temperature=0.7 if attempt == 0 else 0.4,
            num_predict=400,
        )
        topic, points = _parse_card(data)
        if not topic:
            logger.warning("题卡解析失败（第 %d 次），原始输出：%s", attempt + 1, data)
            continue
        problems = [_topic_problem(topic)] + [
            _bullet_problem(p, i) for i, p in enumerate(points)
        ]
        if _topic_is_recent(topic, list(_RECENT_TOPICS)):
            problems.append("与最近题目重复")
        problems = [p for p in problems if p]
        if not problems:
            _RECENT_TOPICS.append(topic)
            return _format_card(topic, points)
        logger.warning("题卡校验未通过（第 %d 次）：%s | %s", attempt + 1, problems, _format_card(topic, points))

    recent = list(_RECENT_TOPICS)
    topic, points = _pick_fallback_card(recent)
    _RECENT_TOPICS.append(topic)
    logger.info("使用内置标准题库兜底：%s", topic)
    return _format_card(topic, points)

# =====================================================================
# 点评 / 改写 / 范文 Prompt
# =====================================================================
if LLM_PROVIDER == "deepseek":
    _FAIL_HINT = "请检查 DEEPSEEK_API_KEY、账户余额与网络后重试"
else:
    _FAIL_HINT = "请确认 Ollama 服务已启动后重试"

_CORRECTION_FALLBACK = f"（暂时无法生成点评，{_FAIL_HINT}）"
_REVISION_FALLBACK = f"（暂时无法生成改写答案，{_FAIL_HINT}）"
_MODEL_FALLBACK = f"（暂时无法生成参考范文，{_FAIL_HINT}）"

_GRAMMAR_PROMPT = """You are a patient, precise IELTS Speaking teacher giving feedback on a Part 2 long turn.

CUE CARD
__CUE_CARD__

CANDIDATE'S ANSWER (word for word)
__ANSWER__

Write the feedback in SIMPLIFIED CHINESE, but keep every English sentence you quote or correct in English.

IMPORTANT OUTPUT RULE
- Inside the feedback text use the corner brackets 「」 around quoted English sentences, and NEVER use double quotes (") inside the text. The correction must be one plain text string, not nested JSON.

Cover these three points in this order:
1. 时态与语法 — pick 2-4 sentences that really appear in the answer and write each one in EXACTLY this pattern:
   - 原句「I go there with my friend.」→ 改为「I went there with my friend.」（描述过去的事，用一般过去时）
   Copy the original sentence word for word from the answer above; if you cannot find an exact sentence, do not write a correction line.
   The part after 改为 MUST be the corrected ENGLISH sentence. NEVER translate into Chinese and never put Chinese after 改为.
   Only correct clear grammatical errors (tense, subject-verb agreement, articles, plurals, prepositions, word order). If the sentence is grammatically correct, skip it — even if you would word it differently. Do NOT suggest style preferences such as adding "would", and do NOT swap synonyms ("go back" → "go there" is NOT an error).
   Never change present simple to past simple unless the sentence has a clear past time marker (last year, yesterday, in 2019, when I was a child).
   TENSE EXAMPLES
   - 原句「I go there every weekend.」→ correct as it is, so write NO correction for it.
   - 原句「I still go back whenever I'm free.」→ correct as it is, so write NO correction for it.
   - 原句「I go there last summer.」→ 改为「I went there last summer.」（last summer 是过去时间）
   Choose at most 3 of the clearest errors. If you cannot find a clear error, do not invent one.
2. 题目覆盖 — name which of the four bullet points were not answered, or answered too briefly. Judge coverage ONLY against the four bullet points on the card; never ask for details the card does not require (names, numbers, exact dates, and so on). Write this line in complete Chinese, do not mix English words into it.
3. 一句话总评 — an estimated IELTS band for this answer and the single most important thing to fix.

FORMAT
- Every correction line must literally contain both labels: 原句 and 改为.
- Start every line with "- "; keep each line short (Chinese explanation under 40 characters).
- Use at most 6 lines in total.
- Do not rewrite the whole answer here.
- No headings, no preamble, no "Here is".
- If there are no real grammar errors, write one line saying 语法基本正确 and focus on the coverage point instead. Only write 语法基本正确 when you have not listed any correction above; never write it together with a correction.

Output JSON only: {"correction": "..."}
"""

_REVISE_PROMPT = """You are an IELTS Speaking examiner and a careful editor.

CUE CARD
__CUE_CARD__

CANDIDATE'S ORIGINAL ANSWER (word for word)
__ANSWER__

Rewrite the candidate's SAME story as a Band 7 spoken answer of 150-220 words.

RULES
- Keep the candidate's people, places, events and opinions. Do NOT invent a different story.
- Do not add new events, festivals, places, people, pets or objects that the original does not mention. You may add natural linking words and feelings, but no new facts.
- Fix every grammar, tense and word-order error. Use past tenses for past events and present tenses for present feelings.
- Write four short paragraphs, one for each bullet point of the cue card, about 40-55 words each. This must add up to 150-220 words; count the words before answering.
- If the original is short, expand it by describing the SAME details more fully: what you saw, heard, felt and how it ended.
- Spoken English only: contractions, short clear sentences, natural linkers (so, but, to be honest, in the end, what I mean is).
- No headings, no bullet points, no Chinese characters, no quotation marks, no stage directions, no introduction such as "Here is".
- Output the answer text only. Do not continue the conversation, do not answer as a second speaker.

Output JSON only: {"revised_answer": "..."}
"""

_FEEDBACK_PROMPT = """You are a patient, precise IELTS Speaking teacher reviewing one Part 2 answer.

CUE CARD
__CUE_CARD__

CANDIDATE'S ANSWER (word for word)
__ANSWER__

TASK 1 — correction
Write the feedback in Simplified Chinese; keep every quoted or corrected English sentence in English.
- Use 「」 around quoted English, never double quotes.
- Pick 2-4 sentences that really appear above. For each: 原句「...」→ 改为「...」（short Chinese reason）.
- Copy the original sentence exactly; if you cannot find one, skip it.
- Only clear grammar errors (tense, subject-verb agreement, articles, plurals, prepositions, word order). No style preferences and no synonym swaps. A present-tense habit stays present.
- Then add: 题目覆盖 (which of the four bullet points are missing or too brief, in complete Chinese) and 一句话总评 (estimated band + the single most important fix).
- At most 6 lines. If there are no real errors, write 语法基本正确.
- Put each correction on its own line starting with "- "; use real line breaks, do not merge several corrections into one paragraph.
Put this text in "correction".

TASK 2 — revised answer
Rewrite the candidate's SAME story as a Band 7 spoken answer of 170-210 words.
- It MUST be at least 160 words. If you finish early, keep developing the same details; do not return a short version.
- Keep the candidate's facts; do not add new events, places, people, pets or objects.
- Fix grammar and tense; use four short paragraphs (one per bullet point), about 40-55 words each.
- Spoken English, contractions, natural linkers; no headings, no bullet points, no Chinese, no quotation marks.
Put this text in "revised_answer".

Output JSON only:
{"correction": "...", "revised_answer": "..."}
"""

_EXPAND_PROMPT = """You are an IELTS Speaking examiner editing a Band 7 answer.

CUE CARD
__CUE_CARD__

CANDIDATE'S ORIGINAL ANSWER
__ANSWER__

DRAFT ANSWER (too short)
__DRAFT__

Expand the draft to 170-200 words WITHOUT adding new events, places or people.

RULES
- Keep every event and opinion already in the draft, in the same order.
- Make each of the four bullet points longer (about 45 words each): add what you saw, heard and felt, plus natural spoken fillers.
- Do not invent a different story and do not add a new trip, festival, person, pet or object.
- Spoken English only, contractions, short sentences, no headings, no bullet points, no Chinese, no quotation marks.
- Output the full expanded answer only.

Output JSON only: {"revised_answer": "..."}
"""

_MODEL_ANSWER_PROMPT = """You are a Band 8.5 IELTS Speaking candidate who sounds natural, not memorised.

CUE CARD
__CUE_CARD__

Give a complete Part 2 long turn (about two minutes, 200-240 words) answering this cue card.

RULES
- Cover all four bullet points in order and move smoothly from one to the next; do not read the card aloud.
- Mix tenses naturally: past simple / past continuous for the story, present perfect for experience, present simple for current feelings.
- Use spoken English: contractions, short sentences, natural fillers (well, actually, to be honest, you know), and one or two less common expressions used correctly.
- Use fillers sparingly: at most three in the whole answer, and never repeat "you know" more than once.
- Include one concrete detail (a name, a time, a place) so it sounds like a real memory.
- End with a short personal reflection, not a summary paragraph.
- Write at least 200 words. Keep every detail consistent with the rest of the answer.
- No headings, no bullet points, no Chinese, no stage directions, no "Hello everyone", no quotation marks.
- Output the answer text only: one JSON string, no template tokens, no second speaker, no questions to the examiner.

Output JSON only: {"model_answer": "..."}
"""


def _clean_answer(text: str) -> str:
    """清理范文/改写答案：去模板 token、去标题、去引号、去中文，保证可直接朗读。"""
    t = _norm_punct(text or "").strip()
    # 模型偶尔会"接着聊天"，把 <|im_start|>user ... / <tool_call> 之类的内容也塞进 JSON 字符串
    t = re.split(r"<\|[^>]{0,40}\|>|</?(?:tool_call|function_call|tool_response)>", t, flags=re.IGNORECASE)[0]
    t = re.split(r"\n\s*(?:user|assistant|system)\s*:", t, flags=re.IGNORECASE)[0]
    t = re.sub(r"<\|[^>]{0,40}\|>|</?(?:tool_call|function_call|tool_response)>", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*(?:sure|certainly|of course)[,.!\s]+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*(?:here(?:'s| is)[^\n]{0,60}?:)\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*(?:model answer|answer)\s*:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\[[^\]]{0,60}\]", "", t)
    t = t.replace("**", "").replace("__", "")
    t = _CJK_RE.sub(" ", t)
    t = re.sub(r"[，。！？；：、（）【】《》“”‘’]", " ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip().strip('"').strip("'").strip()
    # 去掉结尾残留的 JSON 符号
    return re.sub(r"[\s{}\[\]]+$", "", t).strip()


def _norm_for_match(text: str) -> str:
    t = _norm_punct(text or "").lower()
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_false_tense_fix(quote: str, corrected: str) -> bool:
    """原句是 every day / whenever 这类习惯表达时，把它改成过去时通常是被误判的。"""
    if not quote or not corrected:
        return False
    if not _HABIT_RE.search(quote) or _PAST_RE.search(quote):
        return False
    return bool(_PAST_RE.search(corrected))


def _filter_fabricated_corrections(feedback: str, story: str) -> str:
    """丢掉模型"编造"的原句，以及把一般现在时习惯句误改成过去时的伪纠错。"""
    story_norm = _norm_for_match(story)
    kept: list[str] = []
    for line in (feedback or "").splitlines():
        if "→" not in line and "改为" not in line:
            kept.append(line)
            continue
        match = re.search(r"原句\s*[:：]?\s*[「\"“](.+?)[」\"”]", line)
        quote = match.group(1) if match else ""
        if not quote:
            before = re.split(r"→|改为", line)[0]
            before = re.sub(r"^[\s\-*•]*原句\s*[:：]?\s*", "", before).strip()
            quote = before.strip('「」"“” ')
        quote_norm = _norm_for_match(quote)
        if not quote_norm or quote_norm not in story_norm:
            logger.info("丢弃疑似杜撰的纠错句：%s", quote)
            continue
        corrected_match = re.search(r"改为\s*[:：]?\s*[「\"“](.+?)[」\"”]", line)
        corrected = corrected_match.group(1) if corrected_match else ""
        if _is_false_tense_fix(quote, corrected):
            logger.info("丢弃把一般现在时误改为过去时的纠错：%s", quote)
            continue
        kept.append(line)
    kept_text = "\n".join(kept).strip()
    # 已经列出修改，就不要再说"语法基本正确"，避免自相矛盾
    if re.search(r"改为|→", kept_text):
        kept_text = "\n".join(
            line
            for line in kept_text.splitlines()
            if not re.search(r"语法基本正确|无明显语法错误|没有明显的语法错误", line)
        ).strip()
    return kept_text


def _answer_prompt(template: str, cue_card: str, user_story: str) -> str:
    return (
        template.replace("__CUE_CARD__", cue_card.strip() or "(not available)")
        .replace("__ANSWER__", user_story.strip() or "(empty)")
    )


def ask_feedback_agent(user_story: str, cue_card: str) -> dict:
    """一个调用同时产出语法点评与 Band 7 改写，省掉重复的题卡/原文输入。"""
    prompt = _answer_prompt(_FEEDBACK_PROMPT, cue_card, user_story)
    data = _call_llm(prompt, temperature=0.4, num_predict=1600, fallback={})
    correction = _as_text(data.get("correction") or "").strip()
    if len(correction) < 10 or correction.startswith("{") or '"correction"' in correction:
        correction = ""
    correction = _filter_fabricated_corrections(correction, user_story)
    revised = _clean_answer(_as_text(data.get("revised_answer") or ""))
    if revised and len(revised.split()) < 140:
        longer = _expand_revision(revised, user_story, cue_card)
        if len(longer.split()) > len(revised.split()):
            revised = longer
    return {"correction": correction, "suggestion": revised}


def ask_grammar_agent(user_story: str, cue_card: str) -> str:
    prompt = _answer_prompt(_GRAMMAR_PROMPT, cue_card, user_story)
    data = _call_llm(prompt, temperature=0.1, num_predict=700, fallback=_CORRECTION_FALLBACK)
    text = _as_text(data.get("correction") or data.get("_fallback") or "").strip()
    if len(text) < 10 or text.startswith("{") or '"correction"' in text:
        text = ""
    text = _filter_fabricated_corrections(text, user_story)
    return text or _CORRECTION_FALLBACK


def _expand_revision(draft: str, user_story: str, cue_card: str) -> str:
    """改写结果过短时补一次扩写，保证是完整的 Part 2 长回答。"""
    prompt = (
        _EXPAND_PROMPT.replace("__CUE_CARD__", cue_card.strip() or "(not available)")
        .replace("__ANSWER__", user_story.strip() or "(empty)")
        .replace("__DRAFT__", draft)
    )
    data = _call_llm(prompt, temperature=0.4, num_predict=1400, fallback="")
    return _clean_answer(_as_text(data.get("revised_answer") or ""))


def ask_upgrade_agent(user_story: str, cue_card: str) -> str:
    """在考生原故事基础上改写出一版 Band 7 答案（过短会自动扩写一次）。"""
    prompt = _answer_prompt(_REVISE_PROMPT, cue_card, user_story)
    data = _call_llm(prompt, temperature=0.4, num_predict=1400, fallback=_REVISION_FALLBACK)
    text = _clean_answer(_as_text(data.get("revised_answer") or data.get("suggestion") or ""))
    if text and len(text.split()) < 140:
        longer = _expand_revision(text, user_story, cue_card)
        if len(longer.split()) > len(text.split()):
            text = longer
    return text or str(data.get("_fallback") or _REVISION_FALLBACK)


def ask_model_agent(cue_card: str) -> str:
    prompt = _MODEL_ANSWER_PROMPT.replace("__CUE_CARD__", cue_card.strip() or "(not available)")
    data = _call_llm(prompt, temperature=0.6, num_predict=1800, fallback=_MODEL_FALLBACK)
    text = _clean_answer(_as_text(data.get("model_answer") or ""))
    return text or str(data.get("_fallback") or _MODEL_FALLBACK)

# =====================================================================
# 主调用函数（并行处理）
# =====================================================================
def evaluate_part2_story(user_story: str, cue_card: str) -> dict:
    story = (user_story or "").strip()
    card = (cue_card or "").strip()

    if not story:
        return {
            "correction": "（还没有输入答案，先讲一段再来看看反馈吧）",
            "suggestion": "",
            "model_answer": ask_model_agent(card),
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_feedback = executor.submit(ask_feedback_agent, story, card)
        f_model = executor.submit(ask_model_agent, card)

        feedback = f_feedback.result()
        correction = feedback["correction"] or ask_grammar_agent(story, card)
        suggestion = feedback["suggestion"] or ask_upgrade_agent(story, card)
        model_answer = f_model.result()

    return {
        "correction": correction,
        "suggestion": suggestion,
        "model_answer": model_answer,
    }
