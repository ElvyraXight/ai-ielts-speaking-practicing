"""雅思口语评分口径：必须真的出现在每一个评价/建议 prompt 里。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from utils import Chat, HelpCoach, IeltsRubric, Part2, Tutor  # noqa: E402


class RubricContentTest(unittest.TestCase):
    def test_each_part_has_length_and_good_bad_examples(self):
        for name in ("PART1", "PART2", "PART3"):
            block = getattr(IeltsRubric, name)
            with self.subTest(part=name):
                self.assertIn("Length:", block)
                self.assertIn("Good:", block)
                self.assertIn("Bad:", block)

    def test_for_part_selects_the_right_block(self):
        self.assertIn("PART 2", IeltsRubric.for_part("part2"))
        self.assertNotIn("PART 1", IeltsRubric.for_part("part2"))
        self.assertNotIn("INTRODUCTION", IeltsRubric.for_part("part2"))
        self.assertIn("PART 1", IeltsRubric.for_part("exam"))
        self.assertIn("PART 3", IeltsRubric.for_part("exam"))
        # 选 Part 3 时开场介绍照样在，所以 Part 3 入口也要带 INTRO
        self.assertIn("INTRODUCTION", IeltsRubric.for_part("part3"))

    def test_introduction_is_its_own_block_not_part1(self):
        """开场问名字不是 Part 1：一句话足够，不许要求细节。"""
        intro = IeltsRubric.INTRO
        self.assertIn("this is NOT Part 1", intro)
        self.assertIn("You can call me Elvira.", intro)
        self.assertIn("Detail is NOT required", intro)
        self.assertIn("never call a complete", intro)
        self.assertIn("before Part 3", intro)
        self.assertIn("introduction/identity (before any part) = 1 sentence", IeltsRubric.CROSS)
        self.assertNotIn("this is NOT Part 1", IeltsRubric.PART1)


class RubricInjectionTest(unittest.TestCase):
    def test_exam_feedback_prompt_contains_standard(self):
        with mock.patch.object(Chat, "call_llm_json", return_value={}) as fake:
            Chat.ask_feedback_agent("I go there last year.", "Where did you go?")
        prompt = fake.call_args.args[0]
        self.assertIn("IELTS SPEAKING STANDARD", prompt)
        self.assertIn("WHAT EXAMINERS REWARD", prompt)
        self.assertIn("Part 1", prompt)

    def test_part2_feedback_prompt_contains_standard(self):
        prompt = Part2._answer_prompt(
            Part2._FEEDBACK_PROMPT, "Describe a trip.", "Last year I go to Japan."
        )
        self.assertIn("IELTS SPEAKING PART 2 STANDARD", prompt)
        self.assertIn("Cover EVERY bullet point", prompt)
        self.assertNotIn("__RUBRIC__", prompt)

    def test_tutor_coach_prompt_contains_standard(self):
        with mock.patch.object(Tutor, "call_llm_json", return_value={}) as fake:
            Tutor.coach_practice_answer(
                "Describe your morning.",
                [{"label": "rally", "kind": "word"}],
                "I usually get up at seven.",
            )
        prompt = fake.call_args.args[0]
        self.assertIn("WHAT EXAMINERS REWARD", prompt)
        self.assertIn("PART 2", prompt)

    def test_help_hint_prompt_contains_standard(self):
        with mock.patch.object(HelpCoach, "call_llm_json", return_value={}) as fake:
            HelpCoach.advise(
                source="exam",
                context_text="Part 1",
                transcript="Examiner: ...",
                student_message="这题怎么答",
            )
        prompt = fake.call_args.args[0]
        self.assertIn("IELTS SPEAKING STANDARD", prompt)
        self.assertIn("PART 3", prompt)


if __name__ == "__main__":
    unittest.main()
