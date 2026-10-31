"""训练期临时记忆：独立存储、计划切换时清空。"""

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

from utils import ChatHistory, Memory, TeacherMemory, TrainingMemory, storage  # noqa: E402


class TrainingMemoryTest(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = _TMP_ROOT / f"training-memory-{uuid.uuid4().hex[:8]}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(Memory, "MEMORY_PATH", self.root / "memories.json"),
            mock.patch.object(
                TeacherMemory, "MEMORY_PATH", self.root / "teacher_memory.json"
            ),
            mock.patch.object(
                ChatHistory, "HISTORY_PATH", self.root / "chat_history.json"
            ),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_update_reads_back_and_lesson_switch_clears(self):
        TrainingMemory.ensure_lesson("lesson-1")
        with mock.patch.object(
            Memory,
            "call_llm_json",
            return_value={
                "summary": "训练上下文",
                "new_facts": ["用户喜欢虚拟主播"],
            },
        ):
            TrainingMemory.update("I like a VTuber.", "Nice.")

        self.assertTrue(TrainingMemory.memory_text())
        self.assertIn("虚拟主播", TrainingMemory.memory_text())

        # 同一份计划再进入训练不会清空。
        TrainingMemory.ensure_lesson("lesson-1")
        self.assertTrue(TrainingMemory.memory_text())

        TrainingMemory.ensure_lesson("lesson-2")
        self.assertFalse(TrainingMemory.memory_text())
        self.assertEqual(TrainingMemory.memory_text(), "")

        # 成果进「英语学习档案 → 课堂成果」，不再往「关于你」写任何东西。
        tutor = Memory.load_memory("tutor")
        self.assertEqual(tutor["facts"], [])
        outcomes = TeacherMemory.load_memory()["outcomes"]
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["lesson"], "lesson-1")
        self.assertIn("训练上下文", outcomes[0]["text"])
        self.assertIn("CLASS OUTCOMES", TeacherMemory.memory_text())

    def test_clear_removes_hidden_persona(self):
        TrainingMemory.ensure_lesson("lesson-1")
        with mock.patch.object(
            Memory,
            "call_llm_json",
            return_value={"summary": "训练上下文", "new_facts": ["用户练过 tug"]},
        ):
            TrainingMemory.update("I gave it a tug.", "Good.")
        TrainingMemory.clear()
        self.assertFalse(TrainingMemory.memory_text())
