import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import Tutor as tutor  # noqa: E402


class TutorTurnTest(unittest.TestCase):
    def test_practice_object_is_returned(self):
        payload = {
            "reply": "先试一句：用 trait 和 inherit 说说你从家人身上继承的特点？",
            "practice": {
                "question": "用 trait 和 inherit 说说你从家人身上继承的特点。",
                "targets": ["trait", "inherit"],
                "model_answer": "One trait I inherited from my mum is patience.",
            },
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            turn = tutor.ask_tutor_turn("教我表达", [])
        self.assertIn("trait", turn["reply"])
        self.assertEqual(turn["practice"]["targets"], ["trait", "inherit"])
        self.assertIn("继承", turn["practice"]["question"])
        self.assertIn("inherited", turn["practice"]["model_answer"])

    def test_practice_without_question_is_ignored(self):
        payload = {
            "reply": "好的。",
            "practice": {"targets": ["trait"]},
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            turn = tutor.ask_tutor_turn("x", [])
        self.assertIsNone(turn["practice"])

    def test_legacy_ask_tutor_returns_text(self):
        payload = {"reply": "可以直接说：...", "practice": None}
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            reply = tutor.ask_tutor("x", [])
        self.assertEqual(reply, "可以直接说：...")

    def test_full_sentences_are_not_dictionary_lookups(self):
        self.assertTrue(tutor.is_bare_lookup("abandon"))
        self.assertTrue(tutor.is_bare_lookup("on the verge of"))
        self.assertFalse(
            tutor.is_bare_lookup("I inherited patience from my mum.")
        )
        self.assertFalse(tutor.is_bare_lookup("I went hiking."))

    def test_prep_list_is_injected_into_the_prompt(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"reply": "ok", "practice": None}

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.ask_tutor_turn("x", [], prep="- abandon（错 3 · 连对 0）")
        self.assertIn("PREP LIST", captured["prompt"])
        self.assertIn("abandon", captured["prompt"])

    def test_model_answer_is_injected_into_coach_prompt(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "feedback": "ok",
                "focus": "",
                "status": "teaching",
                "checklist": [],
                "usage": [],
                "new_issues": [],
            }

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.coach_practice_answer(
                "Q",
                [],
                "A",
                model_answer="The constant errand built my irritation.",
            )
        self.assertIn("MODEL ANSWER", captured["prompt"])
        self.assertIn("constant errand", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
