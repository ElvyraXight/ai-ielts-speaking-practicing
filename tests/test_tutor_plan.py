import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import PrepBook, TutorPlan, TutorProgress, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"plan-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TutorPlanTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(TutorPlan, "PLAN_PATH", self.root / "tutor_plan.json"),
            mock.patch.object(PrepBook, "PREP_PATH", self.root / "prep_book.json"),
            mock.patch.object(
                TutorProgress, "PROGRESS_PATH", self.root / "tutor_progress.json"
            ),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
            mock.patch.object(
                PrepBook,
                "sync_candidates",
                return_value={"added": 0, "total": 0},
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _prep(self, labels):
        items = []
        for index, label in enumerate(labels):
            items.append(
                {
                    "source_key": f"user:{label}",
                    "label": label,
                    "kind": "word",
                    "source": "user_request",
                    "added_at": f"2026-10-29 00:00:{index:02d}.000000",
                }
            )
        PrepBook._save_unlocked(items, {item["source_key"] for item in items})

    def _create(self, previous=None, manual=False):
        with mock.patch.object(TutorPlan, "call_llm_json", return_value={}):
            return TutorPlan.create_plan(previous=previous, manual=manual)

    def test_selects_oldest_first_then_newest(self):
        self._prep(["a", "b", "c", "d", "e"])
        plan = self._create()
        self.assertEqual([point["label"] for point in plan["points"]], ["a", "e", "d"])

    def test_quota_excludes_last_and_limits_older_plans(self):
        self._prep(["a", "b", "c", "d", "e", "f"])
        previous = {
            "version": 2,
            "lesson_id": "old",
            "points": [],
            "status": "done",
            "last_auto_plan_date": "2026-10-28",
            "history": [
                {
                    "lesson_id": "p1",
                    "created_at": "2026-10-20",
                    "source_keys": ["user:a", "user:b"],
                    "status": "done",
                },
                {
                    "lesson_id": "p2",
                    "created_at": "2026-10-21",
                    "source_keys": ["user:c"],
                    "status": "done",
                },
                {
                    "lesson_id": "p3",
                    "created_at": "2026-10-22",
                    "source_keys": ["user:d"],
                    "status": "done",
                },
            ],
        }
        plan = self._create(previous=previous)
        labels = [point["label"] for point in plan["points"]]
        self.assertEqual(labels, ["a", "f", "e"])
        self.assertNotIn("d", labels)
        self.assertNotIn("c", labels)

    def test_same_day_done_plan_is_not_regenerated(self):
        self._prep(["a"])
        plan = self._create()
        plan = TutorPlan.mark_mastered([p["label"] for p in plan["points"]])
        self.assertTrue(TutorPlan.is_done(plan))
        with mock.patch.object(TutorPlan, "call_llm_json") as fake:
            again = TutorPlan.ensure_plan()
        self.assertEqual(again["lesson_id"], plan["lesson_id"])
        fake.assert_not_called()

    def test_done_plan_is_regenerated_on_new_day(self):
        self._prep(["a"])
        plan = self._create()
        plan = TutorPlan.mark_mastered([p["label"] for p in plan["points"]])
        plan["last_auto_plan_date"] = "2026-10-28"
        storage.save_json(TutorPlan.PLAN_PATH, plan)
        PrepBook.add_user_point("z")
        with mock.patch.object(TutorPlan, "call_llm_json", return_value={}):
            again = TutorPlan.ensure_plan()
        self.assertNotEqual(again["lesson_id"], plan["lesson_id"])
        self.assertEqual([p["label"] for p in again["points"]], ["z"])

    def test_done_plan_not_replaced_when_only_last_plan_points_remain(self):
        self._prep(["a"])
        plan = self._create()
        plan = TutorPlan.mark_mastered(["a"])
        plan["last_auto_plan_date"] = "2026-10-28"
        storage.save_json(TutorPlan.PLAN_PATH, plan)
        again = TutorPlan.ensure_plan()
        self.assertEqual(again["lesson_id"], plan["lesson_id"])
        self.assertEqual([p["label"] for p in again["points"]], ["a"])

    def test_incomplete_plan_is_never_updated(self):
        self._prep(["a"])
        plan = self._create()
        with mock.patch.object(TutorPlan, "call_llm_json") as fake:
            again = TutorPlan.ensure_plan()
        self.assertEqual(again["lesson_id"], plan["lesson_id"])
        fake.assert_not_called()

    def test_empty_prep_creates_empty_plan_without_retry(self):
        with mock.patch.object(TutorPlan, "call_llm_json") as fake:
            plan = TutorPlan.ensure_plan()
        self.assertTrue(TutorPlan.is_empty(plan))
        self.assertFalse(TutorPlan.can_train(plan))
        fake.assert_not_called()

    def test_user_points_cap_at_ten_and_reopen_done_plan(self):
        plan, created = TutorPlan.add_user_point("p1")
        self.assertTrue(created)
        self.assertEqual(len(plan["points"]), 1)
        plan = TutorPlan.mark_mastered(["p1"])
        self.assertTrue(TutorPlan.is_done(plan))
        for index in range(2, 11):
            plan, created = TutorPlan.add_user_point(f"p{index}")
            self.assertTrue(created)
        self.assertEqual(len(plan["points"]), 10)
        self.assertFalse(TutorPlan.is_done(plan))
        plan, created = TutorPlan.add_user_point("p11")
        self.assertFalse(created)
        self.assertEqual(len(plan["points"]), 10)

    def test_second_completion_removes_prep_item(self):
        self._prep(["a"])
        plan = {
            "version": 2,
            "lesson_id": "current",
            "goal": "",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": "user:a",
                    "label": "a",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "auto",
                }
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [
                {
                    "lesson_id": "old",
                    "created_at": "",
                    "source_keys": ["user:a"],
                    "status": "done",
                },
                {
                    "lesson_id": "current",
                    "created_at": "",
                    "source_keys": ["user:a"],
                    "status": "active",
                },
            ],
        }
        TutorPlan._save_unlocked(plan)
        TutorPlan.mark_mastered(["a"])
        self.assertIsNone(PrepBook.find_exact("a"))

    def test_mark_mastered_updates_history(self):
        self._prep(["a"])
        plan = self._create()
        plan = TutorPlan.mark_mastered(["a"])
        record = plan["history"][-1]
        self.assertEqual(record["lesson_id"], plan["lesson_id"])
        self.assertEqual(record["status"], "done")
        self.assertTrue(TutorPlan.is_done(plan))
        self.assertEqual(TutorProgress.today_count(), 1)


if __name__ == "__main__":
    unittest.main()
