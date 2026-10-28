# utils/tts.py

"""语音合成：统一 edge-tts 的调用方式、音频目录和文件命名。

以前 Chat / FreeTalk / Entertainment / Part2 各有一份 generate_audio，
音色默认值还不一样；页面里也各自 asyncio.run 一次。现在只留这一份：
失败只记日志并返回 None，由页面决定要不要提示，不再静默吞掉。
"""

import asyncio
import logging
import uuid
from pathlib import Path

import edge_tts

from utils.config import AUDIO_DIR

logger = logging.getLogger(__name__)

VOICE_UK_MALE = "en-GB-RyanNeural"
VOICE_UK_MALE_DEEP = "en-GB-ThomasNeural"
VOICE_US_FEMALE = "en-US-AriaNeural"
# 英音童声：比成人女声更"娇小"，猫娘用这个
VOICE_UK_GIRL = "en-GB-MaisieNeural"
DEFAULT_VOICE = VOICE_UK_MALE


def ensure_audio_dir() -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return AUDIO_DIR


def new_audio_path(prefix: str = "ai_voice", suffix: str = ".mp3") -> str:
    """生成一个新的音频文件路径（不创建文件）。"""
    ensure_audio_dir()
    return str(AUDIO_DIR / f"{prefix}_{uuid.uuid4().hex[:8]}{suffix}")


def cached_audio_path(name: str) -> str:
    """可复用的固定文件名，例如单词发音 wa_<id>.mp3。"""
    ensure_audio_dir()
    return str(AUDIO_DIR / name)


async def synthesize(text: str, output_file: str, voice: str | None = None) -> str:
    """异步合成一段语音；文本为空时抛 ValueError。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text for TTS")
    communicate = edge_tts.Communicate(text, voice or DEFAULT_VOICE)
    await communicate.save(output_file)
    return output_file


def speak(
    text: str,
    *,
    prefix: str = "ai_voice",
    voice: str | None = None,
    output_file: str | None = None,
) -> str | None:
    """同步合成一段语音，返回文件路径；失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    path = output_file or new_audio_path(prefix)
    try:
        asyncio.run(synthesize(text, path, voice=voice))
    except Exception:
        logger.warning("语音生成失败：%s", text[:60], exc_info=True)
        return None
    return path


__all__ = [
    "AUDIO_DIR",
    "DEFAULT_VOICE",
    "VOICE_UK_MALE",
    "VOICE_UK_MALE_DEEP",
    "VOICE_UK_GIRL",
    "VOICE_US_FEMALE",
    "cached_audio_path",
    "ensure_audio_dir",
    "new_audio_path",
    "speak",
    "synthesize",
]
