import shutil
import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import ChatHistory, Chat, ExamState, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"exam-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ExamStateTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(
                ChatHistory, "HISTORY_PATH", self.root / "chat_history.json"
            ),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _generator(self, part, *, topic, use_card, recent):
        size = 8 if part == "part1" else 6
        return {
            "topics": [topic],
            "questions": [
                {"topic": topic, "question": f"{part} question {i}"}
                for i in range(size)
            ],
        }

    def test_greeting_uses_time_and_fixed_male_name(self):
        morning = Chat.examiner_greeting(datetime(2026, 10, 30, 9, 0))
        afternoon = Chat.examiner_greeting(datetime(2026, 10, 30, 15, 0))
        self.assertIn("Good morning", morning)
        self.assertIn("Good afternoon", afternoon)
        self.assertIn("Daniel", morning)
        self.assertIn("full name", morning)
        self.assertNotIn("Sarah", morning)

    def test_prelude_status(self):
        state = ExamState.default_state()
        self.assertIn("开场确认", ExamState.status_text(state))
        state["prelude_step"] = 2
        self.assertIn("Part 1", ExamState.status_text(state))

    def test_part3_prelude_uses_part3_transition(self):
        state = ExamState.default_state()
        state["active_part"] = "part3"
        self.assertIn("Part 3", ExamState.status_text(state))
        self.assertIn("abstract", ExamState.prelude_transition("part3"))
        self.assertIn("first part", ExamState.prelude_transition("part1"))

    def test_part1_cycle_then_switches_to_pending_part3(self):
        state = ExamState.default_state()
        state["active_part"] = "part1"
        state["questions"] = [
            {"topic": "t", "question": f"q{i}"} for i in range(8)
        ]
        state["index"] = 7
        ExamState.set_selected_part(state, "part3")
        self.assertEqual(state["pending_part"], "part3")

        question = ExamState.take_next_question(state, self._generator)
        self.assertEqual(question["question"], "q7")
        self.assertEqual(state["active_part"], "part1")
        self.assertEqual(state["pending_part"], "part3")

        question = ExamState.take_next_question(state, self._generator)
        self.assertEqual(state["active_part"], "part3")
        self.assertEqual(state["pending_part"], "")
        self.assertEqual(state["questions"][0]["question"], "part3 question 0")

    def test_recent_questions_are_capped(self):
        state = ExamState.default_state()
        state["questions"] = [{"topic": "t", "question": "q"}]
        state["index"] = 0
        for i in range(20):
            state["recent"] = (state["recent"] + [f"old {i}"])[-12:]
        ExamState.take_next_question(state, self._generator)
        self.assertEqual(len(state["recent"]), 12)
        self.assertEqual(state["recent"][-1], "q")

    def test_state_round_trips(self):
        state = ExamState.default_state()
        state["selected_part"] = "part3"
        state["part3_topic"] = "科技"
        state["use_part2_card"] = False
        ExamState.save(state)
        loaded = ExamState.load()
        self.assertEqual(loaded["selected_part"], "part3")
        self.assertEqual(loaded["part3_topic"], "科技")
        self.assertFalse(loaded["use_part2_card"])

    def test_rewind_uses_message_snapshot(self):
        """编辑旧消息时优先恢复那条消息旁边的状态快照。"""
        questions = [
            {"topic": "t", "question": "part3 question 0"},
            {"topic": "t", "question": "part3 question 1"},
        ]
        current = ExamState.default_state()
        current["prelude_step"] = 2
        current["index"] = 2
        current["questions"] = questions
        ExamState.save(current)

        snapshot = ExamState.default_state()
        snapshot["prelude_step"] = 2
        snapshot["index"] = 1
        snapshot["questions"] = questions
        restored = ExamState.rewind_to(
            [
                {
                    "role": "assistant",
                    "content": "Good afternoon. Your full name?",
                    "exam_state": ExamState.default_state(),
                },
                {"role": "user", "content": "Elvira"},
                {
                    "role": "assistant",
                    "content": "Great. part3 question 0",
                    "exam_state": snapshot,
                },
            ]
        )
        self.assertEqual(restored["index"], 1)
        self.assertEqual(ExamState.load()["index"], 1)

    def test_rewind_without_snapshot_restores_prelude(self):
        """老记录没有快照时，按剩余用户消息把开场步骤退回去。"""
        state = ExamState.default_state()
        state["prelude_step"] = 2
        state["index"] = 2
        state["questions"] = [{"topic": "t", "question": "part3 question 0"}]
        ExamState.save(state)
        restored = ExamState.rewind_to([{"role": "assistant", "content": "greeting"}])
        self.assertEqual(restored["prelude_step"], 0)
        self.assertEqual(restored["index"], 0)

    def test_rewind_without_snapshot_counts_asked_questions(self):
        """老记录里还能看到题目时，按题目在列表里的位置还原题号。"""
        state = ExamState.default_state()
        state["prelude_step"] = 2
        state["index"] = 2
        state["questions"] = [
            {"topic": "t", "question": f"part3 question {i}"} for i in range(3)
        ]
        ExamState.save(state)
        restored = ExamState.rewind_to(
            [
                {"role": "assistant", "content": "Good afternoon. Your full name?"},
                {"role": "user", "content": "Elvira"},
                {"role": "assistant", "content": "What would you like me to call you?"},
                {"role": "user", "content": "Elvira is fine."},
                {"role": "assistant", "content": "Great. part3 question 0"},
            ]
        )
        self.assertEqual(restored["prelude_step"], 2)
        self.assertEqual(restored["index"], 1)


if __name__ == "__main__":
    unittest.main()
