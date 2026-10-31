"""娱乐角色：不要把上一条回复原样再说一遍。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from utils import Entertainment  # noqa: E402


class SimilarityTest(unittest.TestCase):
    def test_identical_text_is_similar(self):
        self.assertTrue(Entertainment._too_similar("你好呀，主人", "你好呀，主人"))

    def test_long_shared_opening_is_similar(self):
        previous = "哦~！我也想你了，主人！绒绒好开心每天早上都能陪在你身边，昨晚睡得好吗？"
        current = "哦~！我也想你了，主人！绒绒好开心每天早上都能陪在你身边，让我看看床单吧。"
        self.assertTrue(Entertainment._too_similar(current, previous))

    def test_different_reply_is_not_similar(self):
        self.assertFalse(
            Entertainment._too_similar("外面下雨了，出门记得带伞。", "今天想吃什么，我去做。")
        )

    def test_empty_input_is_not_similar(self):
        self.assertFalse(Entertainment._too_similar("", "有内容"))
        self.assertFalse(Entertainment._too_similar("有内容", ""))


class DuplicateRewriteTest(unittest.TestCase):
    def _call(self, replies):
        history = [
            {"role": "user", "content": "想你啦"},
            {"role": "assistant", "content": "哦~！我也想你了，主人！"},
        ]
        with mock.patch.object(
            Entertainment, "ask_entertainment_agent", side_effect=replies
        ) as fake, mock.patch.object(
            Entertainment, "speak", return_value=None
        ), mock.patch.object(
            Entertainment, "current_selection", return_value=("deepseek", "deepseek-flash")
        ), mock.patch.object(
            Entertainment, "memory_text", return_value=""
        ):
            data, _ = Entertainment.get_entertainment_answer(
                "嗯嗯", history, "persona text", memory_key=None
            )
        return data, fake

    def test_duplicate_reply_triggers_one_rewrite(self):
        data, fake = self._call(
            [
                ("dup", "哦~！我也想你了，主人！"),
                ("new", "那你要先陪我去买条鱼。"),
            ]
        )
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(data["reply"], "那你要先陪我去买条鱼。")
        retry_kwargs = fake.call_args_list[1].kwargs
        self.assertIn("repeated your previous reply", retry_kwargs["retry_note"])
        self.assertGreater(retry_kwargs["temperature"], 0.7)

    def test_distinct_reply_does_not_retry(self):
        data, fake = self._call([("a", "外面下雨了，记得带伞。")])
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(data["reply"], "外面下雨了，记得带伞。")

    def test_prompt_tells_model_not_to_repeat(self):
        with mock.patch.object(
            Entertainment, "call_llm_json", return_value={"reply": "hi"}
        ) as fake:
            Entertainment.ask_entertainment_agent(
                "嗯嗯", "User: 想你啦", "persona text", avoid="哦~！我也想你了"
            )
        prompt = fake.call_args.args[0]
        self.assertIn("YOUR PREVIOUS REPLY", prompt)
        self.assertIn("do NOT repeat it", prompt)
        self.assertIn("THE USER JUST SAID", prompt)


if __name__ == "__main__":
    unittest.main()
