import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import TutorLead, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"lead-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TutorLeadTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.path = self.root / "tutor_dialogue.json"
        self.patches = [
            mock.patch.object(TutorLead, "MEMORY_PATH", self.path),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _compose(self, payload, draft="今天想练什么？", **kwargs):
        with mock.patch.object(
            TutorLead, "call_llm_json", return_value=payload
        ) as fake:
            result = TutorLead.compose(
                kind="tutor",
                message="你好呀",
                transcript="Student: 你好呀",
                draft=draft,
                **kwargs,
            )
        return result, fake

    def test_compose_saves_summary_and_reply(self):
        result, fake = self._compose(
            {
                "reply": "先不急着练，今天想聊点什么？",
                "summary": "学生在准备雅思，先聊了流程。",
                "keep_practice": False,
            }
        )
        self.assertEqual(result["reply"], "先不急着练，今天想聊点什么？")
        self.assertFalse(result["keep_practice"])
        memory = TutorLead.load_memory()
        self.assertEqual(memory["summary"], "学生在准备雅思，先聊了流程。")
        self.assertIn("学生在准备雅思", TutorLead.memory_text())
        self.assertTrue(fake.called)

    def test_quotes_missing_falls_back_to_draft(self):
        draft = "原句「I go」→ 改为「I went」（过去时）"
        result, _ = self._compose(
            {
                "reply": "过去时要注意一下。",
                "summary": "讲了时态。",
                "keep_practice": True,
            },
            draft=draft,
        )
        self.assertEqual(result["reply"], draft)

    def test_quotes_preserved_uses_lead_reply(self):
        draft = "原句「I go」→ 改为「I went」（过去时）"
        result, _ = self._compose(
            {
                "reply": "这里把「I go」改成「I went」更自然（过去时）。",
                "summary": "讲了时态。",
                "keep_practice": True,
            },
            draft=draft,
        )
        self.assertIn("更自然", result["reply"])

    def test_empty_llm_falls_back_to_draft(self):
        result, _ = self._compose({})
        self.assertEqual(result["reply"], "今天想练什么？")
        self.assertTrue(result["keep_practice"])

    def test_dictionary_does_not_overwrite_conversation_memory(self):
        TutorLead.save_summary("旧摘要")
        with mock.patch.object(
            TutorLead,
            "call_llm_json",
            return_value={"reply": "这几个词我分开讲。", "summary": "新摘要"},
        ):
            TutorLead.compose(
                kind="dictionary",
                message="abandon",
                transcript="Student: abandon",
                draft="我按条给你拆开讲：",
                update_summary=False,
            )
        self.assertEqual(TutorLead.load_memory()["summary"], "旧摘要")

    def test_transcript_includes_dictionary_items(self):
        text = TutorLead.transcript_text(
            [
                {"role": "user", "content": "abandon"},
                {
                    "role": "assistant",
                    "content": "我按条讲：",
                    "items": [{"text": "abandon", "meaning": "放弃"}],
                },
            ]
        )
        self.assertIn("Student: abandon", text)
        self.assertIn("Teacher: 我按条讲", text)
        self.assertIn("abandon — 放弃", text)

    def test_prompt_contains_memory_plan_and_no_drill_note(self):
        TutorLead.save_summary("上次聊过考试流程。")
        captured = {}

        def fake_llm(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"reply": "好。", "summary": "继续聊。", "keep_practice": True}

        with mock.patch.object(TutorLead, "call_llm_json", side_effect=fake_llm):
            TutorLead.compose(
                kind="tutor",
                message="你好呀",
                transcript="Student: 你好呀",
                draft="你好。",
                plan="GOAL: 练 irritation",
                student_memory="WEAK: which 从句",
                no_drill=True,
            )
        prompt = captured["prompt"]
        self.assertIn("CONVERSATION MEMORY", prompt)
        self.assertIn("上次聊过考试流程", prompt)
        self.assertIn("GOAL: 练 irritation", prompt)
        self.assertIn("WEAK: which 从句", prompt)
        self.assertIn("do NOT start a drill", prompt)
        self.assertIn("TEXT-ONLY", prompt)
        self.assertIn("cannot hear audio", prompt)

    def test_practice_text_contains_targets(self):
        captured = {}

        def fake_llm(prompt, **kwargs):
            captured["prompt"] = prompt
            return {
                "reply": "用 irritation 说一句。",
                "summary": "练 irritation。",
                "keep_practice": True,
            }

        with mock.patch.object(TutorLead, "call_llm_json", side_effect=fake_llm):
            TutorLead.compose(
                kind="tutor",
                message="开始练",
                transcript="Student: 开始练",
                draft="用 irritation 说一句。",
                practice={
                    "question": "用 irritation 说一句。",
                    "targets": ["irritation"],
                },
            )
        self.assertIn("PRACTICE ATTACHED", captured["prompt"])
        self.assertIn("Targets: irritation", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
