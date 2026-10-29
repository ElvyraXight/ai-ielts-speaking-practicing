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

    def _update(self, payload, **kwargs):
        with mock.patch.object(
            TeacherMemory, "call_llm_json", return_value=payload
        ):
            return TeacherMemory.update_from_lesson(
                question="Q", answer="A", feedback="F", **kwargs
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

    def test_followup_updates_same_recent_lesson(self):
        self._update({"session_summary": "第一轮"}, lesson_id="L1")
        memory = self._update(
            {"session_summary": "第二轮"}, lesson_id="L1", followup=True
        )
        self.assertEqual(len(memory["recent"]), 1)
        self.assertEqual(memory["recent"][0]["summary"], "第二轮")

    def test_remember_note_is_saved_and_deduped(self):
        text = "记住我下个月要考雅思"
        self.assertTrue(TeacherMemory.looks_like_remember(text))
        self.assertFalse(TeacherMemory.looks_like_remember("今天天气不错"))
        self.assertFalse(TeacherMemory.looks_like_remember("这个表达很重要吗？"))
        TeacherMemory.add_note(text)
        TeacherMemory.add_note(text)
        memory = TeacherMemory.load_memory()
        self.assertEqual(len(memory["notes"]), 1)
        self.assertIn("NOTES", TeacherMemory.memory_text(memory))
        self.assertNotIn("记住", memory["notes"][0]["text"])

    def test_user_note_with_meta_word_is_kept(self):
        TeacherMemory.add_note("记住我说话前习惯先列清单")
        memory = TeacherMemory.load_memory()
        self.assertEqual(len(memory["notes"]), 1)
        self.assertIn("清单", memory["notes"][0]["text"])

    def test_start_phase_does_not_write_stable_traits(self):
        memory = self._update(
            {
                "style_add": ["句子偏短"],
                "strength_add": ["which 从句已加 -s"],
                "weakness_add": ["which 从句动词单复数"],
                "method_add": ["对比句有效"],
                "session_summary": "练了一句",
            },
            final=False,
        )
        self.assertEqual(memory["style"], [])
        self.assertEqual(memory["strengths"], [])
        self.assertEqual(memory["weaknesses"], [])
        self.assertEqual(len(memory["methods"]), 1)
        self.assertEqual(len(memory["recent"]), 1)

    def test_final_phase_writes_pattern_level_traits(self):
        memory = self._update(
            {
                "strength_add": ["which 从句已加 -s"],
                "weakness_add": ["which 从句动词单复数"],
                "method_add": ["对比句有效"],
                "session_summary": "练了一句",
            },
            final=True,
        )
        self.assertEqual([item["text"] for item in memory["strengths"]], ["which 从句已加 -s"])
        self.assertEqual(
            [item["text"] for item in memory["weaknesses"]],
            ["which 从句动词单复数"],
        )

    def test_resolved_weakness_is_removed(self):
        self._update({"weakness_add": ["which 从句动词单复数"]})
        memory = self._update(
            {"resolved": ["which 从句动词单复数"], "session_summary": "已改对"}
        )
        self.assertEqual(memory["weaknesses"], [])

    def test_new_strength_replaces_contradictory_weakness(self):
        self._update({"weakness_add": ["which 从句动词单复数"]})
        memory = self._update({"strength_add": ["which 从句动词单复数"]})
        self.assertEqual(memory["weaknesses"], [])
        self.assertEqual(
            [item["text"] for item in memory["strengths"]],
            ["which 从句动词单复数"],
        )

    def test_meta_checklist_language_is_not_saved(self):
        memory = self._update(
            {"strength_add": ["清单该项过关"], "weakness_add": ["还剩 2 项"]}
        )
        self.assertEqual(memory["strengths"], [])
        self.assertEqual(memory["weaknesses"], [])

    def test_specific_sentence_facts_are_not_saved_as_traits(self):
        memory = self._update(
            {
                "strength_add": ["which irritated me 之后没有结果"],
                "weakness_add": ["errand 被写成复数 errands"],
                "style_add": ["句子偏短"],
                "method_add": ["对比句有效"],
            }
        )
        self.assertEqual(memory["strengths"], [])
        self.assertEqual(memory["weaknesses"], [])
        self.assertEqual([item["text"] for item in memory["style"]], ["句子偏短"])
        self.assertEqual([item["text"] for item in memory["methods"]], ["对比句有效"])

    def test_specific_level_note_is_cleared_on_load(self):
        self._update(
            {"level": {"band": "5.5-6.0", "note": "irritation 和 which 都对了"}}
        )
        memory = TeacherMemory.load_memory()
        self.assertEqual(memory["level"]["band"], "5.5-6.0")
        self.assertEqual(memory["level"]["note"], "")

    def test_provider_and_model_are_forwarded_to_background_call(self):
        captured = {}

        def fake_llm(prompt, **kwargs):
            captured.update(kwargs)
            return {"session_summary": "练了一句"}

        with mock.patch.object(
            TeacherMemory, "call_llm_json", side_effect=fake_llm
        ):
            TeacherMemory.update_from_lesson(
                question="Q",
                answer="A",
                feedback="F",
                final=True,
                provider="ollama",
                model="qwen2.5:7b",
            )
        self.assertEqual(captured["provider"], "ollama")
        self.assertEqual(captured["model"], "qwen2.5:7b")


if __name__ == "__main__":
    unittest.main()
