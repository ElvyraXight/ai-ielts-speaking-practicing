"""帮助会话的后台教练：固定参考回答 + 围绕它给提示。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from utils import HelpCoach  # noqa: E402


class HelpCoachTest(unittest.TestCase):
    def test_preset_answer_is_cleaned_english(self):
        with mock.patch.object(
            HelpCoach,
            "call_llm_json",
            return_value={"answer": '  "My full name is Elvira Yang."  '},
        ):
            answer = HelpCoach.preset_model_answer(
                context_text="Q: What's your full name?",
                transcript="",
            )
        self.assertEqual(answer, "My full name is Elvira Yang.")

    def test_preset_answer_drops_chinese(self):
        with mock.patch.object(
            HelpCoach,
            "call_llm_json",
            return_value={"answer": "直接说：My full name is Elvira Yang."},
        ):
            answer = HelpCoach.preset_model_answer(context_text="Q", transcript="")
        self.assertNotIn("直接说", answer)
        self.assertIn("My full name is Elvira Yang.", answer)

    def test_advise_uses_the_fixed_reference_answer(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"hint": "先接 full name", "issues": []}

        with mock.patch.object(HelpCoach, "call_llm_json", side_effect=fake_llm):
            HelpCoach.advise(
                source="exam",
                context_text="Q: What's your full name?",
                transcript="",
                student_message="这题怎么答",
                model_answer="My full name is Elvira Yang.",
                help_history="Student: 这题怎么答\nTeacher: 先说 My full name is...",
                repeated_attempt=True,
            )

        prompt = captured["prompt"]
        self.assertIn("PRESET REFERENCE ANSWER", prompt)
        self.assertIn("My full name is Elvira Yang.", prompt)
        # 同题同标准，不许来回改口，也不许一直要求复述。
        self.assertIn("reverse it", prompt)
        self.assertIn("retype", prompt)
        self.assertIn("never the whole reference", prompt)
        # 必须看到上一轮说过什么、学生已经改到了哪一步。
        self.assertIn("HELP-CHAT SO FAR", prompt)
        self.assertIn("Student: 这题怎么答", prompt)
        self.assertIn("the student just sent the same sentence again", prompt)
        self.assertIn("CURRENT ATTEMPT TO JUDGE", prompt)
        self.assertIn("The newest Student line", prompt)

    def test_advise_reads_the_part2_answer(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"hint": "把 went 改成 go", "issues": []}

        with mock.patch.object(HelpCoach, "call_llm_json", side_effect=fake_llm):
            HelpCoach.advise(
                source="part2",
                context_text="考试：雅思口语 Part 2\n题卡：Describe a place",
                transcript="Cue card: Describe a place",
                student_message="这句话哪里不对",
                student_answer="Last week I go to a park near my home.",
            )

        prompt = captured["prompt"]
        # 老师要直接看到学生写的答案，而不是只看到题卡。
        self.assertIn("Last week I go to a park near my home.", prompt)
        self.assertIn("STUDENT'S CURRENT PART 2 ANSWER", prompt)
        self.assertIn(
            "Their help-chat message is the question, not the answer.", prompt
        )
        self.assertIn("Never ask the student to paste the", prompt)

    def test_advise_part2_without_answer_asks_for_one(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"hint": "", "issues": []}

        with mock.patch.object(HelpCoach, "call_llm_json", side_effect=fake_llm):
            HelpCoach.advise(
                source="part2",
                context_text="考试：雅思口语 Part 2",
                transcript="",
                student_message="怎么答",
            )

        prompt = captured["prompt"]
        self.assertIn("No Part 2 answer yet", prompt)
        self.assertNotIn("The newest Student line", prompt)


if __name__ == "__main__":
    unittest.main()
