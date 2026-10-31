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

    def test_chat_new_issues_are_returned(self):
        payload = {
            "reply": "这里用 which 从句时动词要跟先行词一致。",
            "new_issues": ["which 从句动词单复数"],
            "practice": None,
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            turn = tutor.ask_tutor_turn("检查这句话", [])
        self.assertEqual(turn["new_issues"], ["which 从句动词单复数"])

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

    def test_short_chat_replies_are_not_dictionary_lookups(self):
        for text in (
            "ok",
            "thanks",
            "sounds good",
            "I think so",
            "not really",
            "me too",
            "how are you",
        ):
            with self.subTest(text=text):
                self.assertFalse(tutor.is_bare_lookup(text))

    def test_meta_questions_pause_coaching(self):
        for text in (
            "口语考试的流程是什么样的",
            "雅思评分标准是什么",
            "which 和 that 的区别",
            "这个单词什么意思",
            "我不想练了",
            "换个话题",
        ):
            with self.subTest(text=text):
                self.assertTrue(tutor.should_pause_coaching(text))

    def test_answer_or_help_request_does_not_pause_coaching(self):
        for text in (
            "怎么改",
            "这句对吗？",
            "我不知道",
            "请再说一遍",
            "I went to the park.",
            "The errand irritated me.",
        ):
            with self.subTest(text=text):
                self.assertFalse(tutor.should_pause_coaching(text))

    def test_should_start_practice_only_when_appropriate(self):
        for text in (
            "你好呀",
            "谢谢",
            "口语考试的流程是什么样的",
            "雅思评分标准是什么",
            "which 和 that 的区别",
            "这个单词什么意思",
            "我不想练了",
        ):
            with self.subTest(text=text):
                self.assertFalse(tutor.should_start_practice(text))

        for text in (
            "陪我练 irritation",
            "能考我一个句子吗",
            "I went to the park.",
            "好的",
        ):
            with self.subTest(text=text):
                self.assertTrue(tutor.should_start_practice(text))

    def test_paused_tutor_turn_never_returns_practice(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "reply": "口语考试分三部分。",
                "practice": {
                    "question": "用 irritation 说一句。",
                    "targets": ["irritation"],
                },
            }

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            turn = tutor.ask_tutor_turn("口语考试的流程是什么样的", [], paused=True)
        self.assertIsNone(turn["practice"])
        self.assertIn("paused a practice sentence", captured["prompt"])

    def test_no_drill_turn_ignores_practice(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "reply": "你好呀，今天想聊什么？",
                "practice": {
                    "question": "用 irritation 说一句。",
                    "targets": ["irritation"],
                },
            }

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            turn = tutor.ask_tutor_turn("你好呀", [], no_drill=True)
        self.assertIsNone(turn["practice"])
        self.assertIn("greeting", captured["prompt"])

    def test_casual_coach_turn_ends_immediately(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "feedback": "这句挺自然，可以把 good 换成 doing well。",
                "focus": "",
                "status": "teaching",
                "checklist": ["不该留下的点"],
                "usage": [],
                "new_issues": [],
            }

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            data = tutor.coach_practice_answer(
                "How are you?", [], "I'm good.", first_turn=True
            )
        self.assertIn("CASUAL ANSWER", captured["prompt"])
        self.assertEqual(data["status"], "mastered")
        self.assertEqual(data["reason"], "stopped")
        self.assertEqual(data["checklist"], [])
        self.assertEqual(data["focus"], "")

    def test_coach_prompt_checks_intended_meaning(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "feedback": "ok",
                "status": "teaching",
                "checklist": [],
                "usage": [],
                "new_issues": [],
            }

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.coach_practice_answer(
                "What annoyed you?",
                [{"label": "irritation"}],
                "It made me feel disappointed.",
            )
        self.assertIn("MEANING FIRST", captured["prompt"])
        self.assertIn("clarifying question", captured["prompt"])
        self.assertIn("Do not cap", captured["prompt"])
        self.assertIn("preserve the student's intended meaning", captured["prompt"])
        self.assertIn(
            "If STUDENT'S LATEST MESSAGE is in Chinese", captured["prompt"]
        )

    def test_mastered_without_reason_is_treated_as_stopped(self):
        payload = {
            "feedback": "ok",
            "status": "mastered",
            "checklist": [],
            "usage": [],
            "new_issues": [],
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            data = tutor.coach_practice_answer(
                "Q",
                [{"label": "irritation"}],
                "A",
                model_answer="The errand caused irritation.",
            )
        self.assertEqual(data["reason"], "stopped")

    def test_criteria_met_is_forwarded(self):
        payload = {
            "feedback": "ok",
            "status": "mastered",
            "reason": "criteria_met",
            "checklist": [],
            "usage": [],
            "new_issues": [],
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            data = tutor.coach_practice_answer(
                "Q",
                [{"label": "irritation"}],
                "A",
                model_answer="The errand caused irritation.",
            )
        self.assertEqual(data["reason"], "criteria_met")

    def test_mastered_with_all_good_usage_infers_criteria_met(self):
        payload = {
            "feedback": "ok",
            "status": "mastered",
            "checklist": [],
            "usage": [{"index": 1, "result": "good", "note": "用对了"}],
            "new_issues": [],
        }
        with mock.patch.object(tutor, "call_llm_json", return_value=payload):
            data = tutor.coach_practice_answer(
                "Q",
                [{"label": "irritation"}],
                "A",
                model_answer="The errand caused irritation.",
            )
        self.assertEqual(data["reason"], "criteria_met")

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

    def test_coach_is_told_about_repeated_attempt_and_literal_check(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "feedback": "ok",
                "status": "mastered",
                "checklist": [],
                "usage": [],
                "new_issues": [],
            }

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.coach_practice_answer(
                "Q", [], "A", repeated_attempt=True
            )
        prompt = captured["prompt"]
        self.assertIn("REPEATED ATTEMPT", prompt)
        self.assertIn("the student just sent the same answer again", prompt)
        # 已经改好的地方不许再要，参考答案不是模板。
        self.assertIn("already in the latest attempt", prompt)
        self.assertIn("never ask the student to copy its punctuation", prompt)

    def test_lesson_plan_is_injected_into_tutor_and_coach_prompts(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"reply": "ok", "practice": None}

        plan = "GOAL: 练 irritation\n1. [pending] irritation — 最近到期"
        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.ask_tutor_turn("x", [], plan=plan)
        self.assertIn("THIS LESSON'S PLAN", captured["prompt"])
        self.assertIn("GOAL: 练 irritation", captured["prompt"])

        with mock.patch.object(
            tutor,
            "call_llm_json",
            return_value={
                "feedback": "ok",
                "status": "teaching",
                "checklist": [],
                "usage": [],
                "new_issues": [],
            },
        ) as coach_llm:
            tutor.coach_practice_answer(
                "Q", [{"label": "irritation"}], "A", plan=plan
            )
        prompt = coach_llm.call_args.args[0]
        self.assertIn("THIS LESSON'S PLAN", prompt)
        self.assertIn("GOAL: 练 irritation", prompt)

    def test_prompts_forbid_audio_judgements(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"reply": "ok", "practice": None}

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.ask_tutor_turn("x", [])
        self.assertIn("TEXT-ONLY", captured["prompt"])
        self.assertIn("cannot hear", captured["prompt"])
        self.assertIn("If the student's message is in Chinese", captured["prompt"])
        self.assertIn("Do not open with", captured["prompt"])
        self.assertIn("TEMPORARY TRAINING MEMORY", captured["prompt"])

        with mock.patch.object(
            tutor,
            "call_llm_json",
            return_value={
                "feedback": "ok",
                "status": "teaching",
                "checklist": [],
                "usage": [],
                "new_issues": [],
            },
        ) as coach_llm:
            tutor.coach_practice_answer("Q", [{"label": "x"}], "A")
        self.assertIn("TEXT-ONLY", coach_llm.call_args.args[0])

    def test_coach_prompt_injects_training_memory(self):
        payload = {
            "feedback": "ok",
            "status": "teaching",
            "checklist": [],
            "usage": [],
            "new_issues": [],
        }
        with mock.patch.object(
            tutor, "call_llm_json", return_value=payload
        ) as fake:
            tutor.coach_practice_answer(
                "Q", [], "A", training_memory="TEMP TRAINING MEMORY"
            )
        prompt = fake.call_args.args[0]
        self.assertIn("TEMPORARY TRAINING MEMORY", prompt)
        self.assertIn("TEMP TRAINING MEMORY", prompt)

    def test_plan_done_prompt_hides_plan_and_forbids_mentions(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"reply": "ok", "practice": None}

        with mock.patch.object(tutor, "call_llm_json", side_effect=fake_llm):
            tutor.ask_tutor_turn(
                "你好",
                [],
                plan="GOAL: 练 irritation",
                plan_done=True,
            )
        prompt = captured["prompt"]
        self.assertNotIn("GOAL: 练 irritation", prompt)
        self.assertIn("Never mention the lesson plan", prompt)
        self.assertIn("If THIS LESSON'S PLAN is", prompt)


if __name__ == "__main__":
    unittest.main()
