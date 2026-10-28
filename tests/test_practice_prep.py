import shutil
import sys
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import Practice, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"prep-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class PrepBookTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(Practice, "PRACTICE_PATH", self.root / "practice.json"),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
            mock.patch.object(Practice, "weak_words", return_value=[]),
            mock.patch.object(Practice, "expression_lines", return_value=[]),
            mock.patch.object(Practice, "notebook_lines", return_value=[]),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _item(label, errors=0, streak=0, interval=1):
        return {
            "label": label,
            "kind": "issue",
            "strength": 1,
            "errors": errors,
            "streak": streak,
            "interval": interval,
            "due": date.today().isoformat(),
            "retired": False,
            "attempts": 0,
            "hits": 0,
            "last": "",
            "last_result": "",
            "note": "",
            "created": "",
        }

    def _apply(self, label, result):
        Practice.apply_results(
            [{"label": label, "kind": "issue"}],
            [{"index": 1, "result": result}],
            [],
        )

    def _target(self):
        return next(item for item in Practice._load() if item["label"] == "点")

    def test_high_error_needs_two_good_before_interval_grows(self):
        Practice._save([self._item("点", errors=3)])
        self._apply("点", "good")
        first = self._target()
        self.assertEqual(first["streak"], 1)
        self.assertEqual(first["interval"], 2)
        self.assertNotIn("retired", first)

        self._apply("点", "good")
        second = self._target()
        self.assertEqual(second["streak"], 2)
        self.assertEqual(second["interval"], 4)
        self.assertNotIn("retired", second)

        self._apply("点", "good")
        labels = [item["label"] for item in Practice._load()]
        self.assertNotIn("点", labels)

    def test_low_error_deletes_after_three_good(self):
        Practice._save([self._item("点", errors=0)])
        for _ in range(3):
            self._apply("点", "good")
        self.assertNotIn("点", [item["label"] for item in Practice._load()])
        self.assertNotIn("点", [item["label"] for item in Practice.prep_points(6)])

    def test_weak_resets_streak_and_comes_back(self):
        Practice._save([self._item("点", errors=0, streak=2, interval=7)])
        self._apply("点", "weak")
        item = self._target()
        self.assertEqual(item["streak"], 0)
        self.assertEqual(item["errors"], 1)
        self.assertEqual(item["interval"], 1)
        self.assertNotIn("retired", item)
        self.assertEqual(Practice.prep_points(6)[0]["label"], "点")

    def test_high_error_first(self):
        Practice._save(
            [
                self._item("低错误", errors=1),
                self._item("高错误", errors=5),
                self._item("没错", errors=0),
            ]
        )
        labels = [item["label"] for item in Practice.prep_points(6)]
        self.assertEqual(labels[:2], ["高错误", "低错误"])
        self.assertNotIn("没错", labels[:2])

    def test_prep_text_shows_counts(self):
        Practice._save([self._item("点", errors=4, streak=1, interval=2)])
        text = Practice.prep_text(6)
        self.assertIn("点", text)
        self.assertIn("错 4", text)
        self.assertIn("连对 1", text)

    def test_seen_labels_are_not_seeded_twice(self):
        Practice._save([self._item("老面孔", errors=1)])
        Practice._save([])
        with mock.patch.object(
            Practice, "weak_words", return_value=["- 老面孔"]
        ):
            Practice._seed([])
        self.assertNotIn("老面孔", [item["label"] for item in Practice.prep_points(6)])
        self.assertNotIn("老面孔", [item["label"] for item in Practice._load()])


if __name__ == "__main__":
    unittest.main()
