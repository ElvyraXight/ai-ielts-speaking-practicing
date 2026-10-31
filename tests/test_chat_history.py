import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import ChatHistory, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    path = _TMP_ROOT / f"chat-history-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ChatHistoryTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patches = [
            mock.patch.object(ChatHistory, "HISTORY_PATH", self.root / "chat_history.json"),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_save_and_load(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "audio": "a.wav"},
        ]
        ChatHistory.save("tutor", messages)
        self.assertEqual(ChatHistory.load("tutor"), messages)

    def test_sessions_are_independent(self):
        ChatHistory.save("tutor", [{"role": "user", "content": "tutor"}])
        ChatHistory.save("catgirl", [{"role": "user", "content": "cat"}])
        self.assertEqual(ChatHistory.load("tutor")[0]["content"], "tutor")
        self.assertEqual(ChatHistory.load("catgirl")[0]["content"], "cat")

    def test_clear_only_current_session(self):
        ChatHistory.save("tutor", [{"role": "user", "content": "tutor"}])
        ChatHistory.save("catgirl", [{"role": "user", "content": "cat"}])
        ChatHistory.clear("tutor")
        self.assertEqual(ChatHistory.load("tutor"), [])
        self.assertEqual(ChatHistory.load("catgirl")[0]["content"], "cat")

    def test_caps_at_300_from_the_end(self):
        messages = [
            {"role": "user", "content": f"m{index}"} for index in range(305)
        ]
        ChatHistory.save("tutor", messages)
        loaded = ChatHistory.load("tutor")
        self.assertEqual(len(loaded), 300)
        self.assertEqual(loaded[0]["content"], "m5")
        self.assertEqual(loaded[-1]["content"], "m304")

    def test_invalid_entries_are_dropped(self):
        ChatHistory.save(
            "tutor",
            [
                {"role": "system", "content": "no"},
                {"role": "user", "content": "yes"},
                "bad",
            ],
        )
        self.assertEqual(ChatHistory.load("tutor"), [{"role": "user", "content": "yes"}])

    def test_meta_survives_message_save_and_clear(self):
        ChatHistory.save_meta(
            "psychologist", {"session_id": "abc", "session_date": "2026-10-29"}
        )
        ChatHistory.save("psychologist", [{"role": "user", "content": "hi"}])
        self.assertEqual(
            ChatHistory.load_meta("psychologist")["session_id"], "abc"
        )
        ChatHistory.clear("psychologist")
        self.assertEqual(ChatHistory.load("psychologist"), [])
        self.assertEqual(
            ChatHistory.load_meta("psychologist")["session_id"], "abc"
        )
        ChatHistory.save_meta("psychologist", {"session_id": "new"})
        self.assertEqual(ChatHistory.load_meta("psychologist")["session_id"], "new")


    def test_update_meta_merges_without_dropping_other_keys(self):
        ChatHistory.save_meta(
            "mentor", {"session_id": "abc", "session_date": "2026-10-29"}
        )
        ChatHistory.update_meta("mentor", {"major": "计算机科学"})
        self.assertEqual(
            ChatHistory.load_meta("mentor")["major"], "计算机科学"
        )

        ChatHistory.update_meta("mentor", {"session_id": "new"})
        meta = ChatHistory.load_meta("mentor")
        self.assertEqual(meta["session_id"], "new")
        self.assertEqual(meta["session_date"], "2026-10-29")
        self.assertEqual(meta["major"], "计算机科学")

    def test_save_meta_still_replaces_the_whole_block(self):
        ChatHistory.save_meta("help_exam", {"source": "exam"})
        ChatHistory.save_meta("help_exam", {})
        self.assertEqual(ChatHistory.load_meta("help_exam"), {})


if __name__ == "__main__":
    unittest.main()
