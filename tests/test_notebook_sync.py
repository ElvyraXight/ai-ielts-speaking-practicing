"""笔记本删/改后，备课本和当前课计划一起对齐。"""

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

from utils import (  # noqa: E402
    LearnerProfile,
    Notebook,
    NotebookSync,
    PrepBook,
    TutorPlan,
    storage,
)


class NotebookSyncTest(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = _TMP_ROOT / f"nbsync-{uuid.uuid4().hex[:8]}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(Notebook, "NOTEBOOK_PATH", self.root / "notebook.json"),
            mock.patch.object(PrepBook, "PREP_PATH", self.root / "prep_book.json"),
            mock.patch.object(TutorPlan, "PLAN_PATH", self.root / "tutor_plan.json"),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
            mock.patch.object(LearnerProfile, "weak_words", return_value=[]),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _add(self, term, meaning):
        return Notebook.add_entry(term, meaning=meaning, enrich=False)

    def _plan_with_point(self, source_key, label):
        plan = TutorPlan.load_plan()
        plan["lesson_id"] = "lesson-1"
        plan["created_at"] = "2026-10-31 00:00:00"
        plan["goal"] = "test"
        plan["points"] = [
            {
                "source_key": source_key,
                "label": label,
                "kind": "word",
                "source": "prep",
                "task": "elicit",
                "criterion": "ok",
                "status": "pending",
                "mastered_at": "",
                "added_by": "auto",
            }
        ]
        TutorPlan._save_unlocked(plan)

    def test_delete_removes_prep_and_plan_point(self):
        entry = self._add("book", "n. 书")
        PrepBook.sync_candidates()
        self._plan_with_point("word:book", "book（n. 书）")

        Notebook.delete_entry(entry["id"])
        with mock.patch.object(NotebookSync, "_sync_training") as training:
            NotebookSync.after_notebook_delete("book", "n. 书")

        self.assertIsNone(PrepBook.get("word:book"))
        self.assertEqual(TutorPlan.load_plan()["points"], [])
        training.assert_called_once()

    def test_meaning_change_updates_labels_but_keeps_task(self):
        entry = self._add("book", "n. 书")
        PrepBook.sync_candidates()
        self._plan_with_point("word:book", "book（n. 书）")

        Notebook.update_entry(entry["id"], meaning="n. 书本")
        NotebookSync.after_notebook_edit("book", "n. 书", "book", "n. 书本")

        item = PrepBook.get("word:book")
        self.assertIn("书本", item["label"])
        point = TutorPlan.load_plan()["points"][0]
        self.assertIn("书本", point["label"])
        self.assertEqual(point["task"], "elicit")

    def test_term_change_rekeys_prep_and_plan(self):
        entry = self._add("book", "n. 书")
        PrepBook.sync_candidates()
        self._plan_with_point("word:book", "book（n. 书）")

        Notebook.update_entry(entry["id"], term="booklet", meaning="n. 小册子")
        NotebookSync.after_notebook_edit("book", "n. 书", "booklet", "n. 小册子")

        self.assertIsNone(PrepBook.get("word:book"))
        self.assertIsNotNone(PrepBook.get("word:booklet"))
        point = TutorPlan.load_plan()["points"][0]
        self.assertEqual(point["source_key"], "word:booklet")
        self.assertEqual(point["task"], "")

    def test_delete_keeps_item_when_weak_word_still_has_it(self):
        with mock.patch.object(
            LearnerProfile,
            "weak_words",
            return_value=["- irritation（n. 恼怒）· 复习 3 次"],
        ):
            entry = self._add("irritation", "n. 恼怒")
            PrepBook.sync_candidates()
            self._plan_with_point("word:irritation", "irritation（n. 恼怒）")

            Notebook.delete_entry(entry["id"])
            NotebookSync.after_notebook_delete("irritation", "n. 恼怒")

            self.assertIsNotNone(PrepBook.get("word:irritation"))
            self.assertEqual(len(TutorPlan.load_plan()["points"]), 1)
