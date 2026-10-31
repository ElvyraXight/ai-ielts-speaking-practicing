"""帮助会话：Part 2 和考官对话各一份临时聊天，互不干扰。"""

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

from utils import ChatHistory, HelpSession  # noqa: E402


class HelpSessionTest(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = _TMP_ROOT / f"help-{uuid.uuid4().hex[:8]}"
        self.root.mkdir()
        self.patcher = mock.patch.object(
            ChatHistory, "HISTORY_PATH", self.root / "chat_history.json"
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_exam_and_part2_sessions_are_separate(self):
        HelpSession.start("exam")
        HelpSession.save_messages([{"role": "user", "content": "考试里的问题"}])

        HelpSession.start("part2")
        HelpSession.save_messages([{"role": "user", "content": "题卡里的问题"}])
        self.assertEqual(HelpSession.messages()[0]["content"], "题卡里的问题")

        HelpSession.start("exam")
        self.assertEqual(HelpSession.messages()[0]["content"], "考试里的问题")
        self.assertEqual(HelpSession.context()["source"], "exam")

    def test_clear_only_clears_one_session(self):
        HelpSession.start("exam")
        HelpSession.save_messages([{"role": "user", "content": "考试里的问题"}])
        HelpSession.start("part2")
        HelpSession.save_messages([{"role": "user", "content": "题卡里的问题"}])

        HelpSession.clear("exam")
        HelpSession.start("part2")
        self.assertEqual(HelpSession.messages()[0]["content"], "题卡里的问题")

        HelpSession.start("exam")
        self.assertEqual(HelpSession.messages(), [])
        self.assertEqual(ChatHistory.load("help_exam"), [])

    def test_preset_answer_is_per_session_and_cleared(self):
        HelpSession.start("exam")
        HelpSession.save_preset_answer(
            "What's your full name?", "My full name is Elvira Yang."
        )
        self.assertEqual(
            HelpSession.preset_answer()["answer"], "My full name is Elvira Yang."
        )

        HelpSession.start("part2")
        self.assertEqual(HelpSession.preset_answer(), {})

        HelpSession.start("exam")
        self.assertEqual(
            HelpSession.preset_answer()["question"], "What's your full name?"
        )
        HelpSession.clear("exam")
        HelpSession.start("exam")
        self.assertEqual(HelpSession.preset_answer(), {})

    def test_legacy_help_session_migrates_to_its_source(self):
        ChatHistory.save("help", [{"role": "user", "content": "旧会话"}])
        ChatHistory.save_meta(
            "help",
            {
                "help_context": {
                    "source": "exam",
                    "started_at": "2026-10-30 10:00:00",
                }
            },
        )

        HelpSession.start("exam")
        self.assertEqual(HelpSession.messages()[0]["content"], "旧会话")
        self.assertEqual(ChatHistory.load("help"), [])
