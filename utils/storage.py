# utils/storage.py

"""JSON 落盘：原子写 + 写前快照。

笔记本、长文本、角色记忆、咨询记录都是"只此一份"的个人数据。
原来只有 tmp + os.replace，能防写一半，但防不住"写成了合法 JSON 的错内容"
（比如解析失败后返回空列表、再保存就覆盖）。现在每次写入前把旧版本复制到
data/backups/，每个文件保留最近 MAX_BACKUPS 份。

恢复：把 data/backups/ 里想要的那份复制回 data/ 下的原名即可。
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = Path(os.getenv("BACKUP_DIR") or (_PROJECT_ROOT / "data" / "backups"))
MAX_BACKUPS = 20


def _backup(path: Path) -> None:
    """把现有文件复制一份快照；内容不是合法 JSON 就不备份，免得挤掉好的旧版本。"""
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("%s 当前内容无法解析，跳过备份", path.name)
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = BACKUP_DIR / f"{path.stem}-{stamp}.json"
        index = 1
        while target.exists():
            target = BACKUP_DIR / f"{path.stem}-{stamp}-{index}.json"
            index += 1
        shutil.copy2(path, target)
        _prune(path.stem)
    except OSError:
        logger.warning("备份 %s 失败", path.name, exc_info=True)


def _prune(stem: str) -> None:
    try:
        files = sorted(BACKUP_DIR.glob(f"{stem}-*.json"), key=lambda item: item.name)
    except OSError:
        return
    for old in files[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def save_json(path, data) -> None:
    """原子写入 JSON，并在覆盖前保留一份旧版本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    if path.exists():
        _backup(path)
    os.replace(tmp, path)
