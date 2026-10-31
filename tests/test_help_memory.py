"""求助会话的临时记忆：只在帮助页里累计，结束求助时进「考试过程」再清空。"""

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

from utils import HelpMemory, Memory, TeacherMemory  # noqa: E402


class HelpMemoryTest(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = _TMP_ROOT / f"helpmem-{uuid.uuid4().hex[:8]}"
        self.root.mkdir()
        self.memory_patch = mock.patch.object(
            Memory, "MEMORY_PATH", self.root / "memories.json"
        )
        self.teacher_patch = mock.patch.object(
            TeacherMemory, "MEMORY_PATH", self.root / "teacher_memory.json"
        )
        self.memory_patch.start()
        self.teacher_patch.start()

    def tearDown(self):
        self.memory_patch.stop()
        self.teacher_patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _seed(self, source: str, text: str) -> None:
        Memory.remember(HelpMemory.key(source), text)

    def test_memory_text_is_marked_as_session_context(self):
        self._seed("exam", "名字题只说了短语，没成句")
        text = HelpMemory.memory_text("exam")
        self.assertIn("THIS HELP SESSION", text)
        self.assertIn("名字题只说了短语", text)
        self.assertNotIn("PERMANENT FACTS", text)

    def test_sources_do_not_share_memory(self):
        self._seed("exam", "考官对话里的问题")
        self.assertTrue(HelpMemory.memory_text("exam"))
        self.assertFalse(HelpMemory.memory_text("part2"))

    def test_finish_writes_exam_note_then_clears(self):
        self._seed("exam", "名字题只说了短语，没成句")
        self.assertTrue(HelpMemory.finish("exam"))

        notes = TeacherMemory.load_memory()["exam_notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["source"], "模拟考试求助")
        self.assertIn("名字题只说了短语", notes[0]["summary"])
        self.assertFalse(HelpMemory.memory_text("exam"))

    def test_finish_without_memory_writes_nothing(self):
        self.assertFalse(HelpMemory.finish("exam"))
        self.assertEqual(TeacherMemory.load_memory()["exam_notes"], [])

    def test_same_day_same_source_updates_instead_of_duplicating(self):
        TeacherMemory.remember_exam_session("模拟考试求助", "第一版摘要")
        TeacherMemory.remember_exam_session("模拟考试求助", "第二版摘要")
        notes = TeacherMemory.load_memory()["exam_notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["summary"], "第二版摘要")

    def test_exam_note_shows_up_in_teacher_memory_text(self):
        TeacherMemory.remember_exam_session("考官对话", "Part 1 名字题只给短语")
        text = TeacherMemory.memory_text()
        self.assertIn("EXAM-SESSION PROBLEMS", text)
        self.assertIn("Part 1 名字题只给短语", text)


if __name__ == "__main__":
    unittest.main()
