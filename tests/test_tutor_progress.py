import shutil
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import TutorProgress, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"progress-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TutorProgressTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(
                TutorProgress, "PROGRESS_PATH", self.root / "tutor_progress.json"
            ),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_same_plan_point_counts_once(self):
        today = date.today().isoformat()
        TutorProgress.record("lesson", "word:a", "a", f"{today} 10:00:00")
        TutorProgress.record("lesson", "word:a", "a", f"{today} 10:05:00")
        self.assertEqual(TutorProgress.today_count(), 1)

    def test_replanned_same_point_counts_again(self):
        today = date.today().isoformat()
        TutorProgress.record("lesson-1", "word:a", "a", f"{today} 10:00:00")
        TutorProgress.record("lesson-2", "word:a", "a", f"{today} 11:00:00")
        self.assertEqual(TutorProgress.today_count(), 2)

    def test_backfill_current_plan(self):
        plan = {
            "lesson_id": "lesson",
            "points": [
                {
                    "source_key": "word:a",
                    "label": "a",
                    "status": "mastered",
                    "mastered_at": "2026-10-29 10:00:00",
                },
                {
                    "source_key": "word:b",
                    "label": "b",
                    "status": "pending",
                    "mastered_at": "",
                },
            ],
        }
        self.assertEqual(TutorProgress.backfill_plan(plan), 1)
        self.assertEqual(TutorProgress.backfill_plan(plan), 0)
        self.assertEqual(len(TutorProgress.day_points("2026-10-29")), 1)

    def test_old_day_does_not_count_today(self):
        TutorProgress.record("lesson", "word:a", "a", "2026-10-28 10:00:00")
        self.assertEqual(TutorProgress.today_count(), 0)
        self.assertEqual(len(TutorProgress.day_points("2026-10-28")), 1)


if __name__ == "__main__":
    unittest.main()
