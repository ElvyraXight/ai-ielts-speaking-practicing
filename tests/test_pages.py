"""页面冒烟测试：用 Streamlit 官方 AppTest 真正把每个页面跑一遍。

单元测试管的是数据层，但"页面还能不能打开"是另一回事——比如模板改错一个
字段名、共用组件少传一个参数，只有真正渲染才会暴露。这里不点任何会花钱的
按钮，只验证：每个页面能渲染、没有异常、发一条消息能走通。
"""

import contextlib
import json
import shutil
import sys
import unittest
import uuid
from datetime import date
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

    def test_memory_sidebar_keeps_only_pin_button(self):
        Memory.MEMORY_PATH.write_text(
            json.dumps(
                {
                    "version": 2,
                    "personas": {
                        "catgirl": {
                            "summary": "",
                            "facts": [
                                {
                                    "text": "用户住在杭州",
                                    "count": 1,
                                    "first": "2026-10-28 10:00:00",
                                    "last": "2026-10-28 10:00:00",
                                    "permanent": False,
                                }
                            ],
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.addCleanup(lambda: Memory.MEMORY_PATH.unlink(missing_ok=True))

        app = self._run_page("chats/CatGirl.py")
        labels = [button.label for button in app.button]
        self.assertIn("📌", labels)
        self.assertNotIn("🗑", labels)

        # 小方块按钮的 CSS 注入到了页面里（用容器 key 限定范围）
        styles = " ".join(str(m.value or "") for m in app.markdown)
        self.assertIn("st-key-memory_facts_catgirl", styles)
        self.assertIn("1.95rem", styles)

    def test_notes_sidebar_renders_dates(self):
        Notes.NOTES_PATH.write_text(
            json.dumps(
                {
                    "version": 1,
                    "notes": {
                        "psychologist": {
                            "n1": {
                                "date": "2026-10-28",
                                "summary": "聊了考试压力",
                                "details": ["讨论了复习计划"],
                                "next": ["早点睡"],
                                "created_at": "2026-10-28 10:00:00",
                                "updated_at": "2026-10-28 10:00:00",
                            }
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.addCleanup(lambda: Notes.NOTES_PATH.unlink(missing_ok=True))

        app = self._run_page("chats/Psychologist.py")
        styles = " ".join(str(m.value or "") for m in app.markdown)
        self.assertIn("details.session-note>summary", styles)
        self.assertIn("padding:.28rem", styles)
        self.assertIn("<details class='session-note'", styles)

    def test_expressions_tab_uses_word_layout(self):
        Expressions.EXPRESSIONS_PATH.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        {
                            "id": "e1",
                            "intent": "我想说这事一时半会儿说不清",
                            "natural": "It's hard to put into words right now.",
                            "mine": "I can't say it clear now.",
                            "scene": "",
                            "source": "手动添加",
                            "created_at": "2026-10-20 10:00:00",
                            "updated_at": "2026-10-20 10:00:00",
                            "review": {
                                "due": "2026-10-20",
                                "interval": 0,
                                "streak": 0,
                                "lapses": 0,
                                "last": "",
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.addCleanup(lambda: Expressions.EXPRESSIONS_PATH.unlink(missing_ok=True))

        app = AppTest.from_file(str(_ROOT / "chats/Notebook.py"), default_timeout=60)
        app.session_state["nb_mode"] = "表达"
        app.run()

        self.assertFalse(
            app.exception, f"表达 tab 渲染报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(
            app.segmented_control(key="nb_mode").options,
            ["单词 / 词组", "表达", "长文本笔记"],
        )

        # 和「单词 / 词组」一样：复习 / 表达表两个视图，列表里有修改、删除和时间行。
        app.segmented_control(key="exp_view").set_value("表达表").run()
        self.assertFalse(
            app.exception, f"表达表渲染报错：{[str(e) for e in app.exception]}"
        )
        labels = [button.label for button in app.button]
        self.assertIn("✏️ 修改", labels)
        self.assertIn("🗑 删除", labels)
        self.assertTrue(
            any("全部表达" in str(m.value or "") for m in app.markdown)
        )
        self.assertTrue(
            any("添加：" in str(c.value or "") for c in app.caption)
        )

    def test_today_has_drill_shortcut(self):
        app = self._run_page("course/dashboard.py")
        labels = [button.label for button in app.button]
        self.assertIn("去背单词", labels)
        self.assertIn("去巩固单词/词组", labels)
        self.assertTrue(
            any("巩固单词/词组" in str(c.value or "") for c in app.caption)
        )
        # 背景音和模型一样是下拉框（没有图标）
        self.assertIn("背景音", [s.label for s in app.selectbox])
        # 板块说明和入口按钮之间不再有横线
        self.assertFalse(
            any("<hr" in str(m.value or "") for m in app.markdown)
        )

    def test_sidebar_volume_and_no_model_caption(self):
        app = self._run_page("app.py")
        # 音量常驻侧边栏最上面，任何页面都能调
        self.assertIn("背景音音量", [s.label for s in app.sidebar.slider])
        # 工作台不再显示「当前模型」那行灰色小字
        self.assertFalse(
            any("当前模型" in str(c.value or "") for c in app.caption)
        )

    def test_back_to_dashboard_link(self):
        app = self._run_page("app.py")
        # 工作台上没有「返回工作台」的链接
        self.assertNotIn("工作台", [link.label for link in app.page_link])

        app.switch_page("chats/Tutor.py").run()
        self.assertFalse(
            app.exception, f"切到子页面时报错：{[str(e) for e in app.exception]}"
        )
        # 子页面顶部是「← 工作台」的页面链接，不再有 🏠 按钮
        self.assertIn("工作台", [link.label for link in app.page_link])
        self.assertFalse(any(button.label == "🏠" for button in app.button))

    def test_tutor_page_has_no_intro_text_or_starters(self):
        app = self._run_page("chats/Tutor.py")
        self.assertFalse(
            any("把答案贴给我" in str(c.value or "") for c in app.caption)
        )
        self.assertFalse(
            any("可以这样开始" in str(m.value or "") for m in app.markdown)
        )
        labels = [button.label for button in app.button]
        self.assertNotIn("3 个自然的 Part 2 开头", labels)
        self.assertNotIn("说不满两分钟怎么办", labels)
        self.assertNotIn("根据题卡追问我", labels)

    def test_quick_add_includes_expression_mode(self):
        app = self._run_page("chats/Tutor.py")
        control = app.segmented_control(key="tutor_nb_type")
        # 和笔记本页一致：单词 → 表达 → 长文本
        self.assertEqual(
            control.options, ["单词 / 词组", "表达", "长文本笔记"]
        )

        control.set_value("表达").run()
        self.assertFalse(
            app.exception, f"表达表单报错：{[str(e) for e in app.exception]}"
        )
        self.assertIn("想表达什么（中文）*", [t.label for t in app.text_input])
        self.assertIn("地道说法（英文）*", [t.label for t in app.text_area])

    def test_today_drill_shows_reviewed_today(self):
        today = date.today().isoformat()

        def entry(entry_id: str, due: str, last: str) -> dict:
            return {
                "id": entry_id,
                "term": f"phrase {entry_id}",
                "meaning": "v. 测试",
                "senses": [{"pos": "v.", "meaning": "测试", "example": "A test sentence."}],
                "example": "A test sentence.",
                "tags": ["口语"],
                "created_at": "2026-10-01 10:00:00",
                "updated_at": "2026-10-01 10:00:00",
                "review": {
                    "due": due,
                    "interval": 1,
                    "streak": 0,
                    "lapses": 0,
                    "last": last,
                },
            }

        Notebook.NOTEBOOK_PATH.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        entry("n1", "2026-10-01", ""),        # 还没巩固，仍在队列里
                        entry("n2", "2099-01-01", today),     # 今天巩固过
                        entry("n3", "2099-01-01", today),     # 今天巩固过
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.addCleanup(lambda: Notebook.NOTEBOOK_PATH.unlink(missing_ok=True))

        app = self._run_page("course/dashboard.py")
        # 小字显示今天已经巩固完的条数（2），而不是待巩固的条数（1）
        self.assertTrue(
            any("巩固单词/词组 2 个" in str(c.value or "") for c in app.caption)
        )
        self.assertFalse(app.button(key="today_drill").disabled)


if __name__ == "__main__":
    unittest.main()
