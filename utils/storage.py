# utils/storage.py

"""JSON 落盘：原子写 + 按天快照 + 坏文件隔离。

笔记本、长文本、角色记忆、咨询记录都是"只此一份"的个人数据，
这里的三条规则都是为"别把数据弄丢"服务的：

1. 原子写：先写 .tmp 再 os.replace，断电不会留下半个文件。
2. 按天快照：每个文件每天的第一份旧内容存到 data/backups/<stem>-YYYYMMDD.json，
   保留最近 MAX_BACKUP_DAYS 天。原来按"最近 20 份"保留，但 word_progress
   每答一个词就写一次，20 份只覆盖几分钟，等于没有备份。
3. 坏文件隔离：写入前发现现有文件已经不是合法 JSON，先把它复制到
   data/backups/corrupt/ 再覆盖，原始内容不会因为"解析失败 → 当成空数据 →
   保存"这条链路彻底消失。

恢复：把 data/backups/ 里想要的那份复制回 data/ 下的原名即可。
"""

import json
import logging
import os
import re
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or (_PROJECT_ROOT / "data" / "backups"))
CORRUPT_DIR = BACKUP_DIR / "corrupt"
MAX_BACKUP_DAYS = 30


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _quarantine(path: Path) -> None:
    """把损坏的文件另存一份，避免接下来的写入把它覆盖掉。"""
    try:
        CORRUPT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = CORRUPT_DIR / f"{path.stem}-{stamp}.json"
        index = 1
        while target.exists():
            target = CORRUPT_DIR / f"{path.stem}-{stamp}-{index}.json"
            index += 1
        shutil.copy2(path, target)
        logger.error(
            "检测到损坏的 %s，已另存为 %s，请检查后从备份恢复",
            path.name,
            target.name,
        )
    except OSError:
        logger.warning("隔离损坏文件 %s 失败", path.name, exc_info=True)


def _backup(path: Path, text: str) -> None:
    """每天只留第一份快照，避免高频写入把历史挤掉。"""
    day = time.strftime("%Y%m%d")
    target = BACKUP_DIR / f"{path.stem}-{day}.json"
    if target.exists():
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        _prune(path.stem)
    except OSError:
        logger.warning("备份 %s 失败", path.name, exc_info=True)


def _prune(stem: str) -> None:
    """删掉超过 MAX_BACKUP_DAYS 天的快照。"""
    cutoff = date.today() - timedelta(days=MAX_BACKUP_DAYS)
    pattern = re.compile(rf"^{re.escape(stem)}-(\d{{8}})")
    try:
        candidates = list(BACKUP_DIR.glob(f"{stem}-*.json"))
    except OSError:
        return
    for file in candidates:
        match = pattern.match(file.name)
        if not match:
            continue
        try:
            day = date(int(match.group(1)[:4]), int(match.group(1)[4:6]), int(match.group(1)[6:]))
        except ValueError:
            continue
        if day < cutoff:
            try:
                file.unlink()
            except OSError:
                pass


def save_json(path, data) -> None:
    """原子写入 JSON；内容没变就不写，覆盖前保留当天的旧版本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    existing = None
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
    if existing == payload:
        return
    if existing is not None:
        if _is_json(existing):
            _backup(path, existing)
        else:
            _quarantine(path)

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


__all__ = ["BACKUP_DIR", "MAX_BACKUP_DAYS", "save_json"]
