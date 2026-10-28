"""页面冒烟测试：用 Streamlit 官方 AppTest 真正把每个页面跑一遍。

单元测试管的是数据层，但"页面还能不能打开"是另一回事——比如模板改错一个
字段名、共用组件少传一个参数，只有真正渲染才会暴露。这里不点任何会花钱的
按钮，只验证：每个页面能渲染、没有异常、发一条消息能走通。
"""

import contextlib
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

try:  # 没装 streamlit 的旧环境就跳过，不让核心测试跟着挂
    from streamlit.testing.v1 import AppTest
except Exception:  # pragma: no cover - 依赖缺失时的降级
    AppTest = None

from utils import (  # noqa: E402
    Ambient,
    Expressions,
    LongNotes,
    Memory,
    Notebook,
    Notes,
    WordAtlas,
    config,
    tts,
)

PAGES = [
    "app.py",
    "course/dashboard.py",
    "chats/chats.py",
    "chats/FreeTalk.py",
    "chats/Part2.py",
    "chats/Words.py",
    "chats/Tutor.py",
    "chats/Notebook.py",
    "chats/ChatFriend.py",
    "chats/CatGirl.py",
    "chats/Psychologist.py",
    "chats/Mentor.py",
]


def _fake_answer(*_args, **_kwargs):
    return (
        {
            "reply": "Hello there.",
            "correction": "",
            "suggestion": "",
            "model_answer": "",
        },
        None,
    )


@unittest.skipUnless(AppTest is not None, "需要 streamlit.testing.v1.AppTest")
class PageSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _TMP_ROOT / f"pages-{uuid.uuid4().hex[:8]}"
        cls.root.mkdir(parents=True, exist_ok=True)
        cls.stack = contextlib.ExitStack()
        patches = [
            # 所有落盘都改到临时目录，绝不动真实的 data/
            mock.patch.object(Memory, "MEMORY_PATH", cls.root / "memories.json"),
            mock.patch.object(Notes, "NOTES_PATH", cls.root / "session_notes.json"),
            mock.patch.object(Notebook, "NOTEBOOK_PATH", cls.root / "notebook.json"),
            mock.patch.object(
                Expressions, "EXPRESSIONS_PATH", cls.root / "expressions.json"
            ),
            mock.patch.object(
                LongNotes, "LONG_NOTES_PATH", cls.root / "long_notes.json"
            ),
            mock.patch.object(
                WordAtlas, "PROGRESS_PATH", cls.root / "word_progress.json"
            ),
            mock.patch.object(Ambient, "STATE_PATH", cls.root / "ambient.json"),
            mock.patch.object(tts, "AUDIO_DIR", cls.root / "audio"),
            # 不联网：模型列表和所有对话都走假数据
            mock.patch.object(config, "list_ollama_models", return_value=[]),
            mock.patch(
                "utils.ChatPage.get_entertainment_answer", side_effect=_fake_answer
            ),
            mock.patch("utils.Chat.get_chat_answer", side_effect=_fake_answer),
            mock.patch("utils.FreeTalk.get_freetalk_answer", side_effect=_fake_answer),
            mock.patch(
                "utils.Part2.generate_cue_card",
                return_value=(
                    "Describe a place you like\n\nYou should say:\n"
                    "- where it is\n- how often you go there"
                ),
            ),
        ]
        for patch in patches:
            cls.stack.enter_context(patch)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def _run_page(self, path: str):
        app = AppTest.from_file(str(_ROOT / path), default_timeout=60)
        app.run()
        self.assertFalse(
            app.exception, f"{path} 渲染时报错：{[str(e) for e in app.exception]}"
        )
        return app

    def test_every_page_renders(self):
        for path in PAGES:
            with self.subTest(page=path):
                self._run_page(path)

    def test_entertainment_page_send_flow(self):
        app = self._run_page("chats/CatGirl.py")
        self.assertEqual(len(app.session_state["cat_messages"]), 1)  # 开场白

        app.text_area(key="cat_input_buffer").set_value("hello there").run()
        app.button(key="send_cat").click().run()

        self.assertFalse(
            app.exception, f"发送消息时报错：{[str(e) for e in app.exception]}"
        )
        messages = app.session_state["cat_messages"]
        self.assertEqual(len(messages), 3)  # 开场白 + 用户 + 回复
        self.assertEqual(messages[1]["content"], "hello there")
        self.assertEqual(messages[2]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
