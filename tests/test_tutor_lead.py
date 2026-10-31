import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import TutorLead  # noqa: E402

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

    def test_coach_reply_caps_corrections_at_four(self):
        with mock.patch.object(
            TutorLead, "call_llm_json", return_value={"reply": "好，改这几处。"}
        ) as fake:
            TutorLead.compose(
                kind="coach",
                message="I go there last year.",
                transcript="Student: I go there last year.",
                draft="改三处：时态、冠词、介词。",
            )
        prompt = fake.call_args.args[0]
        self.assertIn("at most FOUR correction points", prompt)
        self.assertIn("intended meaning", prompt)
        self.assertIn("If STUDENT JUST SAID is in Chinese", prompt)

    def test_training_memory_is_injected(self):
        with mock.patch.object(
            TutorLead, "call_llm_json", return_value={"reply": "好"}
        ) as fake:
            TutorLead.compose(
                kind="coach",
                message="I gave it a tug.",
                transcript="Student: I gave it a tug.",
                draft="brief",
                training_memory="TEMP TRAINING MEMORY",
            )
        prompt = fake.call_args.args[0]
        self.assertIn("TEMPORARY SESSION MEMORY", prompt)
        self.assertIn("TEMP TRAINING MEMORY", prompt)

    def test_plan_done_does_not_send_plan_or_mention_it(self):
        with mock.patch.object(
            TutorLead, "call_llm_json", return_value={"reply": "好"}
        ) as fake:
            TutorLead.compose(
                kind="tutor",
                message="你好",
                transcript="Student: 你好",
                draft="reply",
                plan="SECRET PLAN",
                plan_done=True,
            )
        prompt = fake.call_args.args[0]
        self.assertNotIn("SECRET PLAN", prompt)
        self.assertIn("never mention the lesson plan", prompt)

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
        captured = {}

        def fake_llm(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"reply": "好。", "keep_practice": True}

        with mock.patch.object(TutorLead, "call_llm_json", side_effect=fake_llm):
            TutorLead.compose(
                kind="tutor",
                message="你好呀",
                transcript="Student: 你好呀",
                draft="你好。",
                plan="GOAL: 练 irritation",
                student_memory="WEAK: which 从句",
                personal_memory="上次聊过考试流程。",
                no_drill=True,
            )
        prompt = captured["prompt"]
        self.assertIn("YOUR MEMORY OF EARLIER CONVERSATIONS", prompt)
        self.assertIn("上次聊过考试流程", prompt)
        self.assertIn("GOAL: 练 irritation", prompt)
        self.assertIn("WEAK: which 从句", prompt)
        self.assertIn("do NOT start a drill", prompt)
        self.assertIn("TEXT-ONLY", prompt)
        self.assertIn("cannot hear audio", prompt)

    def test_bullet_markers_are_removed_from_reply(self):
        draft = "可以说「He's my personal tutor.」"
        with mock.patch.object(
            TutorLead,
            "call_llm_json",
            return_value={
                "reply": (
                    "可以用这几句：\n"
                    "- 「He's my personal tutor.」——最直接\n"
                    "- 「This is Vicente, my tutor.」——介绍人时用"
                ),
                "summary": "",
                "keep_practice": True,
            },
        ):
            result = TutorLead.compose(
                kind="tutor",
                message="怎么介绍",
                transcript="Student: 怎么介绍",
                draft=draft,
            )
        self.assertNotIn("\n- ", result["reply"])
        self.assertIn("「He's my personal tutor.」", result["reply"])
        self.assertIn("「This is Vicente, my tutor.」", result["reply"])

    def test_bullet_markers_are_removed_from_fallback_draft(self):
        draft = "可以用这两句：\n- 「A」\n- 「B」"
        with mock.patch.object(TutorLead, "call_llm_json", return_value={}):
            result = TutorLead.compose(
                kind="tutor", message="x", transcript="", draft=draft
            )
        self.assertEqual(result["reply"], "可以用这两句：\n「A」\n「B」")

    def test_prompt_forbids_bullet_lists(self):
        captured = {}

        def fake_llm(prompt, **kwargs):
            captured["prompt"] = prompt
            return {"reply": "好。", "summary": "", "keep_practice": True}

        with mock.patch.object(TutorLead, "call_llm_json", side_effect=fake_llm):
            TutorLead.compose(kind="tutor", message="你好", transcript="", draft="你好。")
        self.assertIn("Never use bullet points", captured["prompt"])

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
