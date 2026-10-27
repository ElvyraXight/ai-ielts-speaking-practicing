# utils/llm.py

"""全站共享的 LLM 客户端。

 provider 配置在 utils/Part2.py 里统一解析（config/.env / .env.local）：
   LLM_PROVIDER=auto      配了 DEEPSEEK_API_KEY 就用 DeepSeek，否则用 Ollama
   LLM_PROVIDER=deepseek  强制 DeepSeek（需要 Key）
   LLM_PROVIDER=ollama    强制本地 Ollama
"""

from utils.Part2 import _as_text, _call_llm, describe_llm


def call_llm_json(
    prompt: str,
    *,
    temperature: float = 0.7,
    num_predict: int = 800,
    fallback=None,
    timeout: float | None = None,
) -> dict:
    """让模型返回一个 JSON 对象；失败时返回 fallback。"""
    return _call_llm(
        prompt,
        temperature=temperature,
        num_predict=num_predict,
        fallback=fallback,
        timeout=timeout,
    )


as_text = _as_text

__all__ = ["call_llm_json", "describe_llm", "as_text"]
