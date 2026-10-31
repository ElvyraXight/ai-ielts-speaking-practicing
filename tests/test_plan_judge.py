import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import PlanJudge  # noqa: E402


class PlanJudgeTest(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"source_key": "word:alpha", "label": "alpha"},
            {"source_key": "word:beta", "label": "beta"},
        ]

    def test_keyword_prefilter(self):
        self.assertTrue(PlanJudge.needs_review("Good, done."))
        self.assertTrue(PlanJudge.needs_review("Next point."))
        self.assertFalse(PlanJudge.needs_review("Try again with a detail."))

    def test_no_keyword_does_not_call_model(self):
        with mock.patch.object(PlanJudge, "call_llm_json") as fake:
            result = PlanJudge.judge("Keep revising.", "Previous.", self.points)
        self.assertEqual(result["completed"], [])
        fake.assert_not_called()

    def test_only_pending_source_keys_are_accepted(self):
        payload = {
            "completed": [
                {"source_key": "word:alpha", "evidence": "moved on"},
                {"source_key": "word:not-in-plan", "evidence": "fake"},
                {"source_key": "word:alpha", "evidence": "duplicate"},
            ],
            "reason": "switch",
        }
        with mock.patch.object(PlanJudge, "call_llm_json", return_value=payload):
            result = PlanJudge.judge(
                "Next, we look at beta.",
                "Try alpha again.",
                self.points,
                current_target=self.points[0],
            )
        self.assertEqual(
            [item["source_key"] for item in result["completed"]], ["word:alpha"]
        )

    def test_prompt_contains_both_teacher_messages(self):
        captured = {}

        def fake(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"completed": [], "reason": ""}

        with mock.patch.object(PlanJudge, "call_llm_json", side_effect=fake):
            PlanJudge.judge(
                "Let us move to the next point.",
                "Previous message still correcting alpha.",
                self.points,
                current_target=self.points[0],
            )
        self.assertIn("Previous message still correcting alpha", captured["prompt"])
        self.assertIn("Let us move to the next point", captured["prompt"])
        self.assertIn("word:alpha", captured["prompt"])

    def test_force_conversation_uses_whole_chat(self):
        captured = {}

        def fake(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "completed": [
                    {"source_key": "word:beta", "evidence": "teacher moved on"}
                ],
                "reason": "whole chat",
            }

        messages = [
            {"role": "assistant", "content": "Practice alpha first."},
            {"role": "user", "content": "I used alpha and beta."},
            {"role": "assistant", "content": "Alpha is done. Next beta."},
        ]
        with mock.patch.object(PlanJudge, "call_llm_json", side_effect=fake):
            result = PlanJudge.judge_conversation(messages, self.points)
        self.assertIn("Practice alpha first", captured["prompt"])
        self.assertIn("Next beta", captured["prompt"])
        self.assertEqual(result["completed"][0]["source_key"], "word:beta")

    def test_force_conversation_all_done_phrase_requires_student_evidence(self):
        messages = [
            {"role": "assistant", "content": "All done for today."},
            {"role": "user", "content": "I used alpha and beta."},
        ]
        with mock.patch.object(
            PlanJudge,
            "call_llm_json",
            return_value={"completed": [], "reason": "model missed"},
        ):
            result = PlanJudge.judge_conversation(messages, self.points)
        self.assertEqual(
            {item["source_key"] for item in result["completed"]},
            {"word:alpha", "word:beta"},
        )

    def test_force_conversation_all_done_without_evidence_is_ignored(self):
        messages = [
            {"role": "assistant", "content": "All done for today."},
        ]
        with mock.patch.object(
            PlanJudge,
            "call_llm_json",
            return_value={"completed": [], "reason": "model missed"},
        ):
            result = PlanJudge.judge_conversation(messages, self.points)
        self.assertEqual(result["completed"], [])

    def test_message_judge_returns_active_and_switch_completion(self):
        payload = {
            "active_source_keys": ["word:beta"],
            "completed": [{"source_key": "word:alpha", "evidence": "moved to beta"}],
            "reason": "switch",
        }
        with mock.patch.object(PlanJudge, "call_llm_json", return_value=payload):
            result = PlanJudge.judge_message(
                "Now practice beta.",
                "Practice alpha.",
                self.points,
                user_message="I used alpha in my answer.",
                last_points=["word:alpha"],
            )
        self.assertEqual(result["active_source_keys"], ["word:beta"])
        self.assertEqual(result["completed"][0]["source_key"], "word:alpha")

    def test_message_judge_ignores_teacher_only_acceptance(self):
        payload = {
            "active_source_keys": ["word:beta"],
            "completed": [{"source_key": "word:alpha", "evidence": "teacher accepted"}],
            "reason": "switch",
        }
        with mock.patch.object(PlanJudge, "call_llm_json", return_value=payload):
            result = PlanJudge.judge_message(
                "Now practice beta.",
                "Practice alpha.",
                self.points,
                user_message="I talked about something else.",
                last_points=["word:alpha"],
            )
        self.assertEqual(result["completed"], [])


if __name__ == "__main__":
    unittest.main()
