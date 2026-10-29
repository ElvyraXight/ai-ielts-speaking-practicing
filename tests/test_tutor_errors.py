import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import TutorErrors, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"errors-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TutorErrorsTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.path = self.root / "tutor_errors.json"
        self.patches = [
            mock.patch.object(TutorErrors, "ERRORS_PATH", self.path),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_similar_errors_merge_and_count(self):
        TutorErrors.add_errors(["which 从句动词单复数"])
        TutorErrors.add_errors(["which 从句动词单复数"])
        items = TutorErrors.items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["count"], 2)

    def test_items_sorted_by_familiarity(self):
        TutorErrors.add_errors(["弱错误"])
        TutorErrors.add_errors(["常见错误", "常见错误", "常见错误"])
        items = TutorErrors.items()
        self.assertEqual(items[0]["text"], "常见错误")
        self.assertEqual(items[0]["count"], 3)

    def test_remove_and_consume(self):
        TutorErrors.add_errors(["错误 A", "错误 B"])
        self.assertTrue(TutorErrors.remove("错误 A"))
        self.assertNotIn("错误 A", [item["text"] for item in TutorErrors.items()])
        target = TutorErrors.consume("错误 B")
        self.assertEqual(target["text"], "错误 B")
        self.assertEqual(TutorErrors.items(), [])

    def test_cap_keeps_most_familiar(self):
        stamp = "2026-10-29 00:00:00"
        items = [
            {
                "text": f"错误 {index}",
                "count": 2 if index < 50 else 1,
                "first": stamp,
                "last": stamp,
            }
            for index in range(60)
        ]
        TutorErrors._save_unlocked(items)
        self.assertEqual(len(TutorErrors.items()), 50)
        self.assertTrue(all(item["count"] == 2 for item in TutorErrors.items()))


if __name__ == "__main__":
    unittest.main()
