import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import TeacherMemory, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"teacher-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TeacherMemoryTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.path = self.root / "teacher_memory.json"
        self.patches = [
            mock.patch.object(TeacherMemory, "MEMORY_PATH", self.path),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _update(self, payload):
        with mock.patch.object(
            TeacherMemory, "call_llm_json", return_value=payload
        ):
            return TeacherMemory.update_from_lesson(
                question="Q", answer="A", feedback="F"
            )

    def test_update_builds_profile(self):
        memory = self._update(
            {
                "level": {"band": "5.5-6.0", "note": "复杂句少"},
                "style_add": ["句子偏短"],
                "strength_add": ["观点清楚"],
                "weakness_add": ["时态混用"],
                "method_add": ["对比句有效"],
                "session_summary": "练了 downside",
                "next_focus": "过去时",
            }
        )
        self.assertEqual(memory["level"]["band"], "5.5-6.0")
        self.assertEqual([item["text"] for item in memory["style"]], ["句子偏短"])
        self.assertEqual(
            [item["text"] for item in memory["weaknesses"]], ["时态混用"]
        )
        self.assertEqual(len(memory["recent"]), 1)
        self.assertIn("5.5-6.0", TeacherMemory.memory_text(memory))

    def test_similar_facts_merge_and_count(self):
        self._update({"weakness_add": ["时态混用"], "style_add": ["句子偏短"]})
        memory = self._update(
            {"weakness_add": ["时态容易混"], "style_add": ["句子偏短"]}
        )
        self.assertEqual(len(memory["weaknesses"]), 1)
        self.assertEqual(memory["weaknesses"][0]["count"], 2)
        self.assertEqual(memory["style"][0]["count"], 2)
        self.assertIn("2 次", TeacherMemory.memory_text(memory))

    def test_empty_update_keeps_memory(self):
        self._update({"weakness_add": ["时态混用"]})
        memory = self._update({})
        self.assertEqual(len(memory["weaknesses"]), 1)

    def test_level_only_updates_when_given(self):
        self._update({"level": {"band": "6.0", "note": "稳定"}})
        memory = self._update({"level": None})
        self.assertEqual(memory["level"]["band"], "6.0")

    def test_clear(self):
        self._update({"weakness_add": ["时态混用"]})
        TeacherMemory.clear_memory()
        self.assertEqual(TeacherMemory.memory_text(), "")


if __name__ == "__main__":
    unittest.main()
