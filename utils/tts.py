# utils/tts.py

"""语音合成：统一 edge-tts 的调用方式、音频目录和文件命名。

以前 Chat / FreeTalk / Entertainment / Part2 各有一份 generate_audio，
音色默认值还不一样；页面里也各自 asyncio.run 一次。现在只留这一份：
失败只记日志并返回 None，由页面决定要不要提示，不再静默吞掉。

音频目录按天清理：每段语音都会生成一个新文件，长期用下来只增不减；
清理放在这里而不是启动脚本里，这样不管从快捷方式、start.bat 还是
命令行启动都生效。保留今天和昨天，前天及更早的删掉——这样跨午夜的
会话里还能回听昨天的内容。
"""

import asyncio
import logging
import os
import threading
import uuid
from datetime import date, timedelta
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

# 保留今天 + 昨天；前天及更早的音频会被清掉。
_KEEP_DAYS = 1
_PRUNE_LOCK = threading.Lock()
_PRUNE_DAY: date | None = None


def _prune_old_audio(today: date | None = None) -> int:
    """删掉前天及更早生成的 mp3；每个进程每天只扫一次目录。"""
    global _PRUNE_DAY
    today = today or date.today()
    if _PRUNE_DAY == today:
        return 0

    cutoff = today - timedelta(days=_KEEP_DAYS)
    removed = 0
    with _PRUNE_LOCK:
        if _PRUNE_DAY == today:
            return 0
        try:
            for path in AUDIO_DIR.glob("*.mp3"):
                try:
                    if date.fromtimestamp(path.stat().st_mtime) < cutoff:
                        path.unlink()
                        removed += 1
                except OSError:
                    continue
        except OSError:
            logger.warning("清理旧语音失败，跳过", exc_info=True)
        _PRUNE_DAY = today

    if removed:
        logger.info("已清理 %d 个旧语音文件（保留今天和昨天）", removed)
    return removed


def ensure_audio_dir() -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_audio()
    return AUDIO_DIR


def new_audio_path(prefix: str = "ai_voice", suffix: str = ".mp3") -> str:
    """生成一个新的音频文件路径（不创建文件）。"""
    ensure_audio_dir()
    return str(AUDIO_DIR / f"{prefix}_{uuid.uuid4().hex[:8]}{suffix}")


def cached_audio_path(name: str) -> str:
    """可复用的固定文件名，例如单词发音 wa_<id>.mp3。"""
    ensure_audio_dir()
    return str(AUDIO_DIR / name)


def existing_audio(path: str | None) -> str | None:
    """页面渲染播放器前统一走这里：不存在或 0 字节的文件不交给 st.audio。"""
    if not path:
        return None
    try:
        candidate = Path(path)
        if candidate.is_file() and candidate.stat().st_size > 0:
            return str(candidate)
    except OSError:
        logger.debug("检查音频文件失败：%s", path, exc_info=True)
    return None


async def synthesize(text: str, output_file: str, voice: str | None = None) -> str:
    """异步合成一段语音；文本为空时抛 ValueError。

    先写 .part 再改名：中途断网只会留下临时文件，不会留下一个
    0 字节的 mp3 让页面渲染出坏播放器。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text for TTS")
    temp_file = f"{output_file}.part"
    try:
        communicate = edge_tts.Communicate(text, voice or DEFAULT_VOICE)
        await communicate.save(temp_file)
        os.replace(temp_file, output_file)
    finally:
        try:
            os.remove(temp_file)
        except OSError:
            pass
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
        Path(path).unlink(missing_ok=True)
        return None
    # edge-tts 偶尔"成功"但没写出内容；空文件不如不给。
    return existing_audio(path)


__all__ = [
    "AUDIO_DIR",
    "DEFAULT_VOICE",
    "VOICE_UK_MALE",
    "VOICE_UK_MALE_DEEP",
    "VOICE_UK_GIRL",
    "VOICE_US_FEMALE",
    "cached_audio_path",
    "ensure_audio_dir",
    "existing_audio",
    "new_audio_path",
    "speak",
    "synthesize",
]
