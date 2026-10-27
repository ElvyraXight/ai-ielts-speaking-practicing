# utils/asr.py

"""全站共享的 Whisper 语音识别模型。

以前 Chat / FreeTalk / Entertainment 三个模块各自在 import 时 load 一次，
Part2 又懒加载一份，同一个进程里最多驻留四份 base 模型（每份一百多 MB），
切页面还会卡十几秒。现在统一走这里：第一次真正转写时才加载，全站只有一份。

模型大小可以用环境变量覆盖：WHISPER_MODEL=tiny|base|small|medium
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

_MODEL_NAME = (os.getenv("WHISPER_MODEL") or "base").strip() or "base"
_MODEL = None
_LOCK = threading.Lock()


def get_whisper_model():
    """按需加载并返回唯一的 Whisper 模型实例。"""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _LOCK:
        if _MODEL is None:
            import whisper  # 延迟导入：不转写就不加载 torch

            logger.info("正在加载语音识别模型（%s，首次使用）...", _MODEL_NAME)
            _MODEL = whisper.load_model(_MODEL_NAME)
            logger.info("语音识别模型加载完毕")
    return _MODEL
