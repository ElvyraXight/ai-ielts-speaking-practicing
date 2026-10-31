import shutil
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import LearnerProfile, PrepBook, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"prepbook-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class PrepBookTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.path = self.root / "prep_book.json"
        self.patches = [
            mock.patch.object(PrepBook, "PREP_PATH", self.path),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
            mock.patch.object(
                LearnerProfile,
                "weak_words",
                return_value=["- irritation（n. 恼怒）· 复习 3 次"],
            ),
            mock.patch.object(
                LearnerProfile,
                "notebook_lines",
                return_value=[
                    "- irritation — n. 恼怒 · 情绪",
                    "- take for granted — phr. 认为理所当然 · 口语",
                ],
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_sync_dedupes_same_word_from_two_sources(self):
        result = PrepBook.sync_candidates()
        self.assertEqual(result["added"], 2)
        items = PrepBook.candidates()
        labels = [item["label"] for item in items]
        self.assertEqual(len(items), 2)
        self.assertEqual(sum("irritation" in label for label in labels), 1)
        self.assertIn("word:irritation", PrepBook._load_unlocked()[1])
        self.assertTrue(
            any("take for granted" in label for label in labels)
        )

    def test_sync_is_idempotent(self):
        PrepBook.sync_candidates()
        result = PrepBook.sync_candidates()
        self.assertEqual(result["added"], 0)
        self.assertEqual(len(PrepBook.candidates()), 2)

    def test_sync_updates_changed_notebook_label(self):
        PrepBook.sync_candidates()
        with mock.patch.object(
            LearnerProfile,
            "notebook_lines",
            return_value=["- take for granted — phr. 认为理所应当 · 口语"],
        ):
            result = PrepBook.sync_candidates()
        self.assertEqual(result["updated"], 1)
        item = PrepBook.find_exact("take for granted")
        self.assertIn("认为理所应当", item["label"])
        self.assertNotIn("认为理所当然", item["label"])

    def test_sync_removes_deleted_notebook_item_but_keeps_weak_word(self):
        PrepBook.sync_candidates()
        with mock.patch.object(
            LearnerProfile, "notebook_lines", return_value=[]
        ):
            result = PrepBook.sync_candidates()
        self.assertGreaterEqual(result["removed"], 1)
        self.assertIsNone(PrepBook.find_exact("take for granted"))
        self.assertIsNotNone(PrepBook.find_exact("irritation"))

    def test_expression_items_are_removed(self):
        PrepBook._save_unlocked(
            [
                {
                    "source_key": "expression:想表达「foo」→ bar",
                    "label": "想表达「foo」→ bar",
                    "kind": "phrase",
                    "source": "expression",
                    "added_at": "2026-10-01 00:00:00.000000",
                }
            ],
            {"expression:想表达「foo」→ bar"},
        )
        result = PrepBook.sync_candidates()
        self.assertEqual(result["removed"], 1)
        self.assertIsNone(PrepBook.get("expression:想表达「foo」→ bar"))
        self.assertNotIn(
            "expression:想表达「foo」→ bar", PrepBook._load_unlocked()[1]
        )

    def test_find_exact_ignores_gloss_but_not_other_word(self):
        PrepBook.sync_candidates()
        self.assertIsNotNone(PrepBook.find_exact("irritation"))
        self.assertIsNotNone(PrepBook.find_exact("irritation（n. 恼怒）"))
        self.assertIsNone(PrepBook.find_exact("irritate"))

    def test_add_user_point_and_duplicate(self):
        item, created = PrepBook.add_user_point("which 从句")
        self.assertTrue(created)
        self.assertEqual(item["kind"], "phrase")
        again, created = PrepBook.add_user_point("which 从句")
        self.assertFalse(created)
        self.assertEqual(again["source_key"], item["source_key"])
        self.assertEqual(len(PrepBook.candidates()), 1)

    def test_remove_item_prevents_resync(self):
        PrepBook.sync_candidates()
        item = PrepBook.find_exact("irritation")
        self.assertTrue(PrepBook.remove_item(item["source_key"]))
        PrepBook.sync_candidates()
        self.assertIsNone(PrepBook.find_exact("irritation"))

    def test_candidates_are_newest_first(self):
        _, first = PrepBook.add_user_point("alpha")
        _, second = PrepBook.add_user_point("beta")
        self.assertTrue(first)
        self.assertTrue(second)
        labels = [item["label"] for item in PrepBook.candidates()]
        self.assertEqual(labels, ["beta", "alpha"])

    def _fill(self, count=200):
        items = []
        base = datetime(2026, 10, 1)
        for index in range(count):
            items.append(
                {
                    "source_key": f"user_request:p{index}",
                    "label": f"p{index}",
                    "kind": "word",
                    "source": "user_request",
                    "added_at": (
                        base + timedelta(seconds=index)
                    ).strftime("%Y-%m-%d %H:%M:%S.%f"),
                }
            )
        PrepBook._save_unlocked(items, {item["source_key"] for item in items})

    def test_fifo_evicts_oldest(self):
        self._fill()
        PrepBook.add_user_point("new")
        items = PrepBook.candidates()
        self.assertEqual(len(items), 200)
        self.assertNotIn("p0", [item["label"] for item in items])
        self.assertIn("new", [item["label"] for item in items])

    def test_fifo_skips_protected_keys(self):
        self._fill()
        PrepBook.add_user_point("new", protected_keys={"user_request:p0"})
        items = PrepBook.candidates()
        labels = [item["label"] for item in items]
        self.assertIn("p0", labels)
        self.assertNotIn("p1", labels)

    def test_item_has_no_old_scheduling_fields(self):
        PrepBook.sync_candidates()
        item = PrepBook.find_exact("irritation")
        self.assertEqual(
            set(item),
            {"source_key", "label", "kind", "source", "added_at"},
        )


if __name__ == "__main__":
    unittest.main()
