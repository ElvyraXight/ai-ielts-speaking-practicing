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
            },
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            turn = tutor.ask_tutor_turn("教我表达", [])
        self.assertIn("trait", turn["reply"])
        self.assertEqual(turn["practice"]["targets"], ["trait", "inherit"])
        self.assertIn("继承", turn["practice"]["question"])

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


if __name__ == "__main__":
    unittest.main()
