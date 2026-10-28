# utils/asr.py

"""全站共享的语音识别。

优先用 faster-whisper（CTranslate2 实现，CPU 上比 openai-whisper 快不少）；
没装或模型加载失败时自动回退到 openai-whisper，不会因为换后端把语音功能弄坏。

以前 Chat / FreeTalk / Entertainment 三个模块各自在 import 时 load 一次，
Part2 又懒加载一份，同一个进程里最多驻留四份模型。现在统一走这里：
第一次真正转写时才加载，全站只有一份。

模型大小可以用环境变量覆盖：WHISPER_MODEL=tiny|base|small|medium
默认 base；如果项目里有 models/faster-whisper-base 就优先用它（离线可用）。
计算精度：WHISPER_COMPUTE_TYPE=int8|float32（默认 int8）
"""

import logging
import os
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCAL_MODEL = _PROJECT_ROOT / "models" / "faster-whisper-base"
_REQUESTED = (os.getenv("WHISPER_MODEL") or "base").strip() or "base"
# 默认 base 且本地已有模型时，直接用本地目录，省掉首次下载
_MODEL_SOURCE = str(_LOCAL_MODEL) if _REQUESTED == "base" and _LOCAL_MODEL.exists() else _REQUESTED
_COMPUTE_TYPE = (os.getenv("WHISPER_COMPUTE_TYPE") or "int8").strip() or "int8"
_MODEL = None
_BACKEND = ""
_LOCK = threading.Lock()


def _load_model():
    """加载模型；faster-whisper 优先，失败回退 openai-whisper。"""
    global _BACKEND
    try:
        from faster_whisper import WhisperModel

        logger.info(
            "正在加载 faster-whisper（%s, %s）...", _MODEL_SOURCE, _COMPUTE_TYPE
        )
        model = WhisperModel(_MODEL_SOURCE, device="cpu", compute_type=_COMPUTE_TYPE)
        _BACKEND = "faster-whisper"
    except Exception:
        logger.warning("faster-whisper 不可用，回退到 openai-whisper", exc_info=True)
        import whisper

        logger.info("正在加载 openai-whisper（%s）...", _REQUESTED)
        model = whisper.load_model(_REQUESTED)
        _BACKEND = "openai-whisper"
    logger.info("语音识别模型加载完毕：%s（%s）", _BACKEND, _MODEL_SOURCE)
    return model


def get_model():
    """按需加载并返回唯一的识别模型实例。"""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _LOCK:
        if _MODEL is None:
            _MODEL = _load_model()
    return _MODEL


def transcribe_file(path: str, language: str = "en") -> str:
    """转写一个音频文件，返回纯文本；失败由调用方决定怎么兜底。"""
    model = get_model()
    if _BACKEND == "faster-whisper":
        segments, _info = model.transcribe(
            path, language=language, vad_filter=True, beam_size=5
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
    return str(model.transcribe(path, language=language).get("text") or "").strip()


def transcribe_upload(audio_file) -> str:
    """转写 Streamlit 的录音/上传对象；失败返回空串并记日志。

    以前这段代码在四个模块里各抄一遍，其中三个还把临时 wav 写到当前工作目录，
    换一个启动目录就会在别处留下垃圾文件。这里统一用系统临时目录。
    """
    if audio_file is None:
        return ""
    suffix = ".wav"
    name = str(getattr(audio_file, "name", "") or "")
    if "." in name:
        suffix = "." + name.rsplit(".", 1)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_file.getbuffer())
        tmp_path = tmp.name
    try:
        return transcribe_file(tmp_path)
    except Exception:
        logger.exception("语音转写失败：%s", getattr(audio_file, "name", "audio"))
        return ""
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


__all__ = ["get_model", "transcribe_file", "transcribe_upload"]
