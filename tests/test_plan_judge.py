import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import PlanJudge  # noqa: E402


class PlanJudgeTest(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"source_key": "word:a", "label": "a"},
            {"source_key": "word:b", "label": "b"},
        ]

    def test_keyword_prefilter(self):
        self.assertTrue(PlanJudge.needs_review("好，这个点可以了。"))
        self.assertTrue(PlanJudge.needs_review("接下来看下一个点。"))
        self.assertFalse(PlanJudge.needs_review("再改一下，补一个结果。"))

    def test_no_keyword_does_not_call_model(self):
        with mock.patch.object(PlanJudge, "call_llm_json") as fake:
            result = PlanJudge.judge("继续改。", "上一句。", self.points)
        self.assertEqual(result["completed"], [])
        fake.assert_not_called()

    def test_only_pending_source_keys_are_accepted(self):
        payload = {
            "completed": [
                {"source_key": "word:a", "evidence": "老师换到下一个点"},
                {"source_key": "word:not-in-plan", "evidence": "假的"},
                {"source_key": "word:a", "evidence": "重复"},
            ],
            "reason": "换点了",
        }
        with mock.patch.object(PlanJudge, "call_llm_json", return_value=payload):
            result = PlanJudge.judge(
                "接下来我们看 b。",
                "刚才 a 再来一次。",
                self.points,
                current_target=self.points[0],
            )
        self.assertEqual(
            [item["source_key"] for item in result["completed"]], ["word:a"]
        )

    def test_prompt_contains_both_teacher_messages(self):
        captured = {}

        def fake(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"completed": [], "reason": ""}

        with mock.patch.object(PlanJudge, "call_llm_json", side_effect=fake):
            PlanJudge.judge(
                "接下来我们看下一个点。",
                "上一句还在改 a。",
                self.points,
                current_target=self.points[0],
            )
        self.assertIn("上一句还在改 a", captured["prompt"])
        self.assertIn("接下来我们看下一个点", captured["prompt"])
        self.assertIn("word:a", captured["prompt"])

    def test_force_conversation_uses_whole_chat(self):
        captured = {}

        def fake(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "completed": [{"source_key": "word:b", "evidence": "老师后来换到 b"}],
                "reason": "整场检查",
            }

        messages = [
            {"role": "assistant", "content": "先练 a。"},
            {"role": "user", "content": "a 的答案。"},
            {"role": "assistant", "content": "这个点可以了，接下来看 b。"},
        ]
        with mock.patch.object(PlanJudge, "call_llm_json", side_effect=fake):
            result = PlanJudge.judge_conversation(messages, self.points)
        self.assertIn("先练 a", captured["prompt"])
        self.assertIn("接下来看 b", captured["prompt"])
        self.assertEqual(result["completed"][0]["source_key"], "word:b")


    def test_force_conversation_all_done_phrase_falls_back_to_all_points(self):
        messages = [
            {"role": "assistant", "content": "三个表达都过关了，今天的内容都完成了。"},
        ]
        with mock.patch.object(
            PlanJudge,
            "call_llm_json",
            return_value={"completed": [], "reason": "模型漏判"},
        ):
            result = PlanJudge.judge_conversation(messages, self.points)
        self.assertEqual(
            {item["source_key"] for item in result["completed"]},
            {"word:a", "word:b"},
        )

    def test_message_judge_returns_active_and_switch_completion(self):
        payload = {
            "active_source_keys": ["word:b"],
            "completed": [{"source_key": "word:a", "evidence": "换到 b"}],
            "reason": "切换点",
        }
        with mock.patch.object(PlanJudge, "call_llm_json", return_value=payload):
            result = PlanJudge.judge_message(
                "接着练 b。",
                "先练 a。",
                self.points,
                user_message="I had to tug it downstairs.",
                last_points=["word:a"],
            )
        self.assertEqual(result["active_source_keys"], ["word:b"])
        self.assertEqual(result["completed"][0]["source_key"], "word:a")


if __name__ == "__main__":
    unittest.main()
