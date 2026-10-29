# utils/config.py

"""全站配置：.env 读取、模型选择、Ollama 探测。

这一层原来长在 utils/Part2.py 里，于是"全站共享的配置"反而要从一个
功能模块 import，任何页面想调模型都被 Part 2 的题库和 prompt 牵连。
现在它只依赖标准库和 requests，不 import 任何 utils 模块。

环境变量优先级：系统环境变量 > config/.env.local > config/.env。
"""

import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_CHOICE_PATH = Path(
    os.getenv("MODEL_CHOICE_PATH")
    or (PROJECT_ROOT / "data" / "model_choice.json")
)
ENV_DIR = PROJECT_ROOT / "config"

try:
    from dotenv import dotenv_values
except ImportError:  # python-dotenv 可选；没有就只用系统环境变量
    dotenv_values = None

_ORIGINAL_ENV_KEYS = {key for key, value in os.environ.items() if value}


def _load_env_file(path: Path, *, override: bool = False) -> None:
    """读取 .env 文件；空值不生效，系统环境变量优先级最高。"""
    if dotenv_values is None or not path.exists():
        return
    try:
        values = dotenv_values(path)
    except Exception:
        logger.warning("读取 %s 失败，忽略该文件", path.name, exc_info=True)
        return
    for key, value in values.items():
        if not value or key in _ORIGINAL_ENV_KEYS:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value


_load_env_file(ENV_DIR / ".env")
_load_env_file(ENV_DIR / ".env.local", override=True)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _abs_path(value: str, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b")
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = (
    _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    or "https://api.deepseek.com"
)
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-flash") or "deepseek-flash"
# 下拉框里可选的两个档位；.env 里换了模型也会排在最前面。
DEEPSEEK_CHOICES = ("deepseek-flash", "deepseek-v4-pro")
LLM_TIMEOUT = float(_env("LLM_TIMEOUT") or _env("OLLAMA_TIMEOUT") or "180")
AUDIO_DIR = _abs_path(_env("AUDIO_DIR"), PROJECT_ROOT / "audio_records")


def _resolve_provider(raw: str) -> str:
    """auto / ollama / deepseek -> 实际使用的 provider。"""
    provider = (raw or "auto").lower()
    if provider == "auto":
        return "deepseek" if DEEPSEEK_API_KEY else "ollama"
    if provider not in ("ollama", "deepseek"):
        logger.warning("未知的 LLM_PROVIDER=%s，回退到 ollama", raw)
        return "ollama"
    if provider == "deepseek" and not DEEPSEEK_API_KEY:
        logger.warning("LLM_PROVIDER=deepseek 但缺少 DEEPSEEK_API_KEY，回退到 Ollama")
        return "ollama"
    return provider


LLM_PROVIDER = _resolve_provider(_env("LLM_PROVIDER", "auto"))


def load_saved_selection() -> tuple[str, str] | None:
    """读取上次手动选择的模型；没有/坏了就返回 None。"""
    try:
        data = json.loads(MODEL_CHOICE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    provider = str(data.get("provider") or "").strip().lower()
    model = str(data.get("model") or "").strip()
    if provider not in ("deepseek", "ollama") or not model:
        return None
    if provider == "deepseek" and not DEEPSEEK_API_KEY:
        return None
    return provider, model


def save_selection(provider: str, model: str) -> None:
    """记住上次使用的模型，下次启动继续用。"""
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    if provider not in ("deepseek", "ollama") or not model:
        return
    payload = json.dumps(
        {"version": 1, "provider": provider, "model": model},
        ensure_ascii=False,
        indent=2,
    )
    try:
        MODEL_CHOICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = MODEL_CHOICE_PATH.with_name(MODEL_CHOICE_PATH.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, MODEL_CHOICE_PATH)
    except OSError:
        logger.exception("保存模型选择失败")


def current_selection() -> tuple[str, str]:
    """当前使用的 (provider, model)：优先主页手动选择，否则用 .env 默认值。"""
    try:
        import streamlit as st

        choice = st.session_state.get("llm_choice")
        if isinstance(choice, (tuple, list)) and len(choice) == 2:
            provider = str(choice[0]).strip().lower()
            model = str(choice[1]).strip()
            if provider in ("deepseek", "ollama") and model:
                if provider == "deepseek" and not DEEPSEEK_API_KEY:
                    return "ollama", OLLAMA_MODEL
                return provider, model
    except Exception:
        pass
    if LLM_PROVIDER == "deepseek" and DEEPSEEK_API_KEY:
        return "deepseek", DEEPSEEK_MODEL
    return "ollama", OLLAMA_MODEL


def describe_llm() -> str:
    """给页面显示的当前模型。"""
    provider, model = current_selection()
    if provider == "deepseek":
        return f"DeepSeek · {model}"
    return f"Ollama · {model}"


def deepseek_model_choices() -> list[str]:
    """DeepSeek 下拉选项：.env 里配置的模型排第一，其余档位去重追加。"""
    choices = [DEEPSEEK_MODEL]
    choices.extend(name for name in DEEPSEEK_CHOICES if name not in choices)
    return choices


def ollama_base_url() -> str:
    """从 OLLAMA_URL 反推服务地址，用于 /api/tags 探测。"""
    base = OLLAMA_URL.split("/api/", 1)[0].rstrip("/")
    return base or "http://localhost:11434"


def list_ollama_models(timeout: float = 1.5) -> list[str]:
    """本机已安装的 Ollama 模型；服务没起时返回空列表。"""
    try:
        response = requests.get(f"{ollama_base_url()}/api/tags", timeout=timeout)
        response.raise_for_status()
        names = [
            str(item.get("name"))
            for item in response.json().get("models", [])
            if item.get("name")
        ]
    except Exception:
        logger.info("Ollama 不可用（%s），下拉框只显示 DeepSeek", ollama_base_url())
        return []
    return sorted(dict.fromkeys(names))


__all__ = [
    "AUDIO_DIR",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_CHOICES",
    "DEEPSEEK_MODEL",
    "LLM_PROVIDER",
    "MODEL_CHOICE_PATH",
    "LLM_TIMEOUT",
    "OLLAMA_MODEL",
    "OLLAMA_URL",
    "PROJECT_ROOT",
    "current_selection",
    "deepseek_model_choices",
    "describe_llm",
    "list_ollama_models",
    "load_saved_selection",
    "ollama_base_url",
    "save_selection",
]
