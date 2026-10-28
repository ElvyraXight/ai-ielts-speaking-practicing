# utils/llm.py

"""LLM 调用层：Ollama 与 DeepSeek 两套后端，统一 JSON 模式、重试和用量记录。

provider 配置在 utils/config.py，这里只负责"把 prompt 发出去、把 JSON 拿回来"。
调用失败时返回 {"_fallback": fallback}（fallback 为 None 时返回空 dict），
由各功能模块决定怎么兜底——这个约定别改，页面里在用。
"""

import json
import logging
import re
import time
from collections import deque

import requests

from utils.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_TIMEOUT,
    OLLAMA_MODEL,
    OLLAMA_URL,
    current_selection,
)

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# 这些状态码值得再试一次；400/401/403 之类重试也没用，只会白等。
_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# 最近几次 DeepSeek 调用的真实 token 用量（用于估算费用/排查）
_USAGE_LOG: deque = deque(maxlen=100)


def usage_log() -> list[dict]:
    return list(_USAGE_LOG)


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
    # 双语字段（reply + reply_zh）被截断时，只保留第一个字段的值，
    # 别把 '", "reply_zh": "..."' 这段残渣塞进正文。
    value = re.split(r'"\s*,\s*"[A-Za-z_]+"\s*:', value)[0]
    value = re.sub(r'"\s*\}\s*$', "", value).strip()
    value = value.rstrip('"').rstrip("}").rstrip().rstrip('"')
    try:
        value = json.loads('"' + value + '"')
    except Exception:
        value = value.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    return {key: value.strip()} if value.strip() else {}


def _retry_delay(response, attempt: int) -> float:
    """优先听服务端的 Retry-After，其次 1s / 2s 退避，最多等 10 秒。"""
    if response is not None:
        try:
            hinted = float(response.headers.get("Retry-After", ""))
            if hinted >= 0:
                return min(hinted, 10.0)
        except (TypeError, ValueError):
            pass
    return 1.0 if attempt == 0 else 2.0


def as_text(value) -> str:
    """模型偶尔把字段返回成嵌套 dict/list，这里统一摊平成可读文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(as_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(as_text(v) for v in value)
    return str(value)


def _call_ollama(
    prompt: str,
    *,
    temperature: float,
    num_predict: int,
    fallback=None,
    timeout: float | None = None,
    model: str | None = None,
) -> dict:
    """统一封装 Ollama 调用：JSON 模式、重试一次、解析失败返回 fallback。"""
    payload = {
        "model": model or OLLAMA_MODEL,
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
            resp = requests.post(
                OLLAMA_URL, json=payload, timeout=timeout or LLM_TIMEOUT
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Ollama HTTP %s：%s", resp.status_code, (resp.text or "")[:200]
                )
                if attempt == 0 and resp.status_code in _RETRY_STATUS:
                    time.sleep(_retry_delay(resp, attempt))
                    continue
                break
            raw = resp.json().get("response", "")
            return _safe_json_loads(raw)
        except requests.RequestException as exc:
            logger.warning("Ollama 请求失败（第 %d 次）：%s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(_retry_delay(None, attempt))
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
    timeout: float | None = None,
    model: str | None = None,
) -> dict:
    """调用 DeepSeek 官方 API（OpenAI 兼容的 /chat/completions + JSON 模式）。"""
    if not DEEPSEEK_API_KEY:
        logger.error("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek")
        return {"_fallback": fallback} if fallback is not None else {}

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    payload = {
        "model": model or DEEPSEEK_MODEL,
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
            resp = requests.post(
                url, json=payload, headers=headers, timeout=timeout or LLM_TIMEOUT
            )
            if resp.status_code >= 400:
                logger.warning(
                    "DeepSeek HTTP %s：%s", resp.status_code, (resp.text or "")[:200]
                )
                # 429/5xx 值得重试；Key 错了、额度没了之类重试也没用。
                if attempt == 0 and resp.status_code in _RETRY_STATUS:
                    time.sleep(_retry_delay(resp, attempt))
                    continue
                break
            body = resp.json()
            usage = body.get("usage") or {}
            if usage:
                _USAGE_LOG.append(
                    {
                        "model": model or DEEPSEEK_MODEL,
                        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                        "completion_tokens": int(usage.get("completion_tokens") or 0),
                        "cache_hit": int(usage.get("prompt_cache_hit_tokens") or 0),
                        "cache_miss": int(usage.get("prompt_cache_miss_tokens") or 0),
                    }
                )
            raw = ((body.get("choices") or [{}])[0].get("message") or {}).get(
                "content", ""
            )
            return _safe_json_loads(raw)
        except requests.RequestException as exc:
            logger.warning("DeepSeek 请求失败（第 %d 次）：%s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(_retry_delay(None, attempt))
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


def call_llm(
    prompt: str,
    *,
    temperature: float,
    num_predict: int,
    fallback=None,
    timeout: float | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """按当前选择（或显式传入）的 provider/model 分发。

    **在后台线程里调用时一定要显式传 provider 和 model。** Streamlit 的
    session_state 只属于发起脚本运行的主线程；工作线程里读到的是空值，
    于是一次"切到 Ollama"的对话可能悄悄还在用 DeepSeek 计费。
    两个都传齐时这里连 session_state 都不会碰。
    """
    if provider is None or model is None:
        selected_provider, selected_model = current_selection()
        provider = provider or selected_provider
        if not model:
            model = (
                selected_model
                if provider == selected_provider
                else (OLLAMA_MODEL if provider == "ollama" else DEEPSEEK_MODEL)
            )
    provider = str(provider).lower()

    if provider == "deepseek" and DEEPSEEK_API_KEY:
        return _call_deepseek(
            prompt,
            temperature=temperature,
            num_predict=num_predict,
            fallback=fallback,
            timeout=timeout,
            model=model,
        )
    if provider == "deepseek":
        logger.warning("DeepSeek 未配置 Key，回退到 Ollama")
        provider = "ollama"
        model = OLLAMA_MODEL
    return _call_ollama(
        prompt,
        temperature=temperature,
        num_predict=num_predict,
        fallback=fallback,
        timeout=timeout,
        model=model,
    )


def call_llm_json(
    prompt: str,
    *,
    temperature: float = 0.7,
    num_predict: int = 800,
    fallback=None,
    timeout: float | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """让模型返回一个 JSON 对象；失败时返回 fallback。"""
    return call_llm(
        prompt,
        temperature=temperature,
        num_predict=num_predict,
        fallback=fallback,
        timeout=timeout,
        provider=provider,
        model=model,
    )


__all__ = ["as_text", "call_llm", "call_llm_json", "usage_log"]
