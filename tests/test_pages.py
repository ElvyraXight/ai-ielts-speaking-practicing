"""页面冒烟测试：用 Streamlit 官方 AppTest 真正把每个页面跑一遍。

单元测试管的是数据层，但"页面还能不能打开"是另一回事——比如模板改错一个
字段名、共用组件少传一个参数，只有真正渲染才会暴露。这里不点任何会花钱的
按钮，只验证：每个页面能渲染、没有异常、发一条消息能走通。
"""

import contextlib
import json
import shutil
import sys
import time
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
    ChatHistory,
    PlanJudge,
    PrepBook,
    TeacherMemory,
    TutorErrors,
    TutorLead,
    TutorPlan,
    TutorProgress,
    WordAtlas,
    config,
    storage,
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
            mock.patch.object(storage, "BACKUP_DIR", cls.root / "backups"),
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
            mock.patch.object(
                PrepBook, "PREP_PATH", cls.root / "prep_book.json"
            ),
            mock.patch.object(
                TutorErrors, "ERRORS_PATH", cls.root / "tutor_errors.json"
            ),
            mock.patch.object(
                ChatHistory, "HISTORY_PATH", cls.root / "chat_history.json"
            ),
            mock.patch.object(
                config, "MODEL_CHOICE_PATH", cls.root / "model_choice.json"
            ),
            mock.patch.object(
                TeacherMemory, "MEMORY_PATH", cls.root / "teacher_memory.json"
            ),
            mock.patch.object(
                TutorPlan, "PLAN_PATH", cls.root / "tutor_plan.json"
            ),
            mock.patch.object(
                TutorProgress,
                "PROGRESS_PATH",
                cls.root / "tutor_progress.json",
            ),
            mock.patch.object(TutorLead, "MEMORY_PATH", cls.root / "tutor_dialogue.json"),
            mock.patch.object(Memory, "update_memory", return_value={}),
            mock.patch.object(
                PlanJudge,
                "judge_message",
                return_value={
                    "active_source_keys": [],
                    "completed": [],
                    "reason": "",
                },
            ),
            mock.patch.object(
                TutorLead,
                "compose",
                side_effect=lambda **kwargs: {
                    "reply": kwargs.get("draft", ""),
                    "keep_practice": True,
                },
            ),
            mock.patch.object(
                TutorPlan,
                "call_llm_json",
                return_value={
                    "goal": "练一个最近到期的词",
                    "warmup": "How has your day been?",
                    "points": [
                        {
                            "label": "irritation",
                            "kind": "word",
                            "why": "最近遗忘过一次",
                            "task": "Tell me about something that irritated you.",
                            "criterion": "用对 irritation 并说清原因。",
                        }
                    ],
                    "wrapup": "再完整说一遍。",
                },
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

    def setUp(self):
        for path in (
            TutorPlan.PLAN_PATH,
            TutorProgress.PROGRESS_PATH,
            PrepBook.PREP_PATH,
            TutorErrors.ERRORS_PATH,
            ChatHistory.HISTORY_PATH,
            config.MODEL_CHOICE_PATH,
            TeacherMemory.MEMORY_PATH,
            TutorLead.MEMORY_PATH,
            Memory.MEMORY_PATH,
        ):
            for attempt in range(3):
                try:
                    Path(path).unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt == 2:
                        break
                    time.sleep(0.05)

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
            ["单词 / 词组", "表达", "仓库"],
        )

        # 和「单词 / 词组」一样：复习 / 表达库两个视图，列表里有修改、删除和时间行。
        app.segmented_control(key="exp_view").set_value("表达库").run()
        self.assertFalse(
            app.exception, f"表达库渲染报错：{[str(e) for e in app.exception]}"
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
        self.assertIn("去上课", labels)
        self.assertTrue(
            any("个单词或词组" in str(c.value or "") for c in app.caption)
        )
        self.assertTrue(
            any("课程计划" in str(m.value or "") for m in app.markdown),
            [str(m.value or "") for m in app.markdown],
        )
        # 背景音和模型一样是下拉框（没有图标）
        self.assertIn("背景音", [s.label for s in app.selectbox])
        # 板块说明和入口按钮之间不再有横线
        self.assertFalse(
            any("<hr" in str(m.value or "") for m in app.markdown)
        )

    def test_today_shows_completed_tutor_plan(self):
        plan, _ = TutorPlan.add_user_point("a")
        TutorPlan.mark_mastered(["a"])
        app = self._run_page("course/dashboard.py")
        texts = [str(m.value or "") for m in app.markdown]
        self.assertTrue(any("✅ 今天已完成" in text for text in texts), texts)

    def test_today_shows_daily_tutor_point_total(self):
        TutorProgress.record("old-lesson", "word:a", "a")
        app = self._run_page("course/dashboard.py")
        texts = [str(c.value or "") for c in app.caption]
        self.assertTrue(
            any("今日累计完成 1 个点" in text for text in texts), texts
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

    def test_tutor_shows_one_line_hint_while_coaching(self):
        app = self._run_page("chats/Tutor.py")
        self.assertFalse(
            any("训练中" in str(c.value or "") for c in app.caption)
        )

        app.session_state["tutor_practice_stage"] = "answer"
        app.session_state["tutor_practice_question"] = "Tell me about your day."
        app.run()
        self.assertFalse(
            app.exception, f"训练提示渲染报错：{[str(e) for e in app.exception]}"
        )
        captions = [str(c.value or "") for c in app.caption]
        self.assertIn("训练中", captions)

    def test_tutor_page_says_text_only(self):
        app = self._run_page("chats/Tutor.py")
        captions = [str(c.value or "") for c in app.caption]
        self.assertTrue(
            any("文字对话" in text and "听不到声音" in text for text in captions),
            captions,
        )

    def test_tutor_sidebar_explains_empty_prep_book(self):
        app = self._run_page("chats/Tutor.py")
        captions = [str(c.value or "") for c in app.caption]
        self.assertTrue(
            any("备课本为空" in text for text in captions),
            captions,
        )

    def test_tutor_sidebar_shows_plan_and_memories(self):
        app = self._run_page("chats/Tutor.py")
        expanders = [str(e.label or "") for e in app.expander]
        self.assertTrue(
            any("备课本" in label for label in expanders),
            expanders,
        )
        self.assertTrue(
            any("英语学习档案" in label for label in expanders),
            expanders,
        )
        self.assertTrue(
            any("关于你" in label for label in expanders),
            expanders,
        )
        captions = [str(c.value or "") for c in app.caption]
        self.assertTrue(any("还没有本课计划" in text for text in captions), captions)

    def test_entertainment_page_has_sticky_note_form(self):
        app = self._run_page("chats/CatGirl.py")
        expanders = [str(item.label or "") for item in app.expander]
        self.assertTrue(any("📝 写便签" in label for label in expanders), expanders)

    def test_tutor_sidebar_has_warehouse_panel(self):
        app = self._run_page("chats/Tutor.py")
        expanders = [str(item.label or "") for item in app.expander]
        self.assertTrue(any("📦 仓库" in label for label in expanders), expanders)

    def test_tutor_want_enter_opens_confirmation(self):
        app = self._run_page("chats/Tutor.py")
        app.text_input(key="tutor_want_input").set_value("irritation").run()
        self.assertEqual(
            app.session_state.get("tutor_pending_label"), "irritation"
        )

    def test_tutor_pending_enter_adds_to_plan(self):
        app = self._run_page("chats/Tutor.py")
        app.text_input(key="tutor_want_input").set_value("irritation").run()
        pending_input = next(
            item for item in app.text_input if item.label == "概括成"
        )
        pending_input.set_value("irritation").run()
        app.form_submit_button(key="tutor_pending_add").click().run()
        labels = [
            point["label"]
            for point in app.session_state["tutor_plan"].get("points", [])
        ]
        self.assertIn("irritation", labels)

    def test_tutor_user_want_card_adds_to_prep_and_plan(self):
        app = self._run_page("chats/Tutor.py")
        app.text_input(key="tutor_want_input").set_value("irritation").run()
        app.button(key="tutor_want_ready").click().run()
        self.assertFalse(
            app.exception, f"准备加点报错：{[str(e) for e in app.exception]}"
        )
        app.form_submit_button(key="tutor_pending_add").click().run()
        self.assertFalse(
            app.exception, f"加入备课本报错：{[str(e) for e in app.exception]}"
        )
        labels = [
            point["label"]
            for point in app.session_state["tutor_plan"].get("points", [])
        ]
        self.assertIn("irritation", labels)
        self.assertIsNotNone(PrepBook.find_exact("irritation"))

    def test_tutor_existing_prep_point_can_join_plan_directly(self):
        item, _ = PrepBook.add_user_point("all set")
        app = self._run_page("chats/Tutor.py")
        app.text_input(key="tutor_want_input").set_value("all set").run()
        app.button(key="tutor_want_ready").click().run()
        labels = [button.label for button in app.form_submit_button]
        self.assertIn("加入课程计划", labels)
        app.form_submit_button(key="tutor_pending_add").click().run()
        plan_keys = {
            point["source_key"]
            for point in app.session_state["tutor_plan"].get("points", [])
        }
        self.assertIn(item["source_key"], plan_keys)

    def test_tutor_start_training_flow(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 2,
            "lesson_id": "test",
            "goal": "练 irritation",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": "user:irritation",
                    "label": "irritation",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                }
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        with mock.patch(
            "utils.Tutor.ask_practice_question",
            return_value="Tell me about something that irritated you.",
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "好，我们练这个：Tell me about something that irritated you.",
                "keep_practice": True,
            },
        ):
            app.run()
            app.chat_input[0].set_value("我们再稍微练会吧").run()
            self.assertEqual(app.session_state.get("tutor_practice_stage"), "answer")
            self.assertNotIn("tutor_training_confirm", app.session_state)
        self.assertFalse(
            app.exception, f"开始训练报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "answer")
        self.assertIn(
            "irritated", app.session_state["tutor_messages"][-1]["content"]
        )
        app.chat_input[0].set_value("开始").run()
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "answer")
        self.assertIn(
            "已经开始了", app.session_state["tutor_messages"][-1]["content"]
        )

    def test_tutor_judge_marks_plan_point_without_coach_criteria(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 2,
            "lesson_id": "judge-lesson",
            "goal": "练 a b",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": "user:a",
                    "label": "a",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                },
                {
                    "source_key": "user:b",
                    "label": "b",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                },
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        with mock.patch(
            "utils.Tutor.ask_practice_question",
            return_value="Tell me about a.",
        ), mock.patch(
            "utils.Tutor.coach_practice_answer",
            return_value={
                "feedback": "这个点可以了，接下来看下一个。",
                "focus": "",
                "status": "teaching",
                "reason": "teaching",
                "checklist": ["a 用对"],
                "usage": [],
                "new_issues": [],
            },
        ), mock.patch(
            "utils.PlanJudge.judge_message",
            return_value={
                "completed": [{"source_key": "user:a", "evidence": "换下一个点"}],
                "reason": "换点了",
            },
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "这个点可以了，接下来看下一个。",
                "keep_practice": True,
            },
        ):
            app.run()
            app.chat_input[0].set_value("我想练").run()
            app.chat_input[0].set_value("开始").run()
            app.chat_input[0].set_value("A short answer.").run()
        points = {
            point["source_key"]: point["status"]
            for point in app.session_state["tutor_plan"]["points"]
        }
        self.assertEqual(points["user:a"], "mastered")
        self.assertEqual(points["user:b"], "pending")

    def test_tutor_judge_auto_ends_when_all_points_done(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 2,
            "lesson_id": "judge-done",
            "goal": "练 a",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": "user:a",
                    "label": "a",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                }
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        with mock.patch(
            "utils.Tutor.ask_practice_question",
            return_value="Tell me about a.",
        ), mock.patch(
            "utils.Tutor.coach_practice_answer",
            return_value={
                "feedback": "这个点可以了，收尾。",
                "focus": "",
                "status": "teaching",
                "reason": "teaching",
                "checklist": ["a 用对"],
                "usage": [],
                "new_issues": [],
            },
        ), mock.patch(
            "utils.PlanJudge.judge_message",
            return_value={
                "completed": [{"source_key": "user:a", "evidence": "可以了"}],
                "reason": "完成",
            },
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "这个点可以了，收尾。",
                "keep_practice": True,
            },
        ):
            app.run()
            app.chat_input[0].set_value("我想练").run()
            app.chat_input[0].set_value("开始").run()
            app.chat_input[0].set_value("A short answer.").run()
        self.assertIsNone(app.session_state.get("tutor_practice_stage"))
        self.assertTrue(
            TutorPlan.is_done(app.session_state["tutor_plan"])
        )

    def test_tutor_training_state_is_restored_after_refresh(self):
        ChatHistory.save(
            "tutor",
            [
                {"role": "assistant", "content": "Tell me about a."},
            ],
        )
        ChatHistory.save_meta(
            "tutor",
            {
                "training": {
                    "point": [
                        {
                            "source_key": "user:a",
                            "label": "a",
                            "kind": "word",
                        }
                    ],
                    "question": "Tell me about a.",
                    "model": "",
                    "stage": "answer",
                    "focus": "",
                    "checklist": [],
                    "turns": 0,
                    "lesson": "test",
                }
            },
        )
        app = self._run_page("chats/Tutor.py")
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "answer")
        self.assertEqual(
            app.session_state.get("tutor_practice_question"), "Tell me about a."
        )

    def test_tutor_can_switch_to_another_plan_point_during_training(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 2,
            "lesson_id": "switch-lesson",
            "goal": "切换目标",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": "user:success",
                    "label": "想表达「我会像她一样成功。」→ I will be as successful as she is.",
                    "kind": "phrase",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                },
                {
                    "source_key": "user:hear",
                    "label": "想表达「我能听清」→ I can hear you very clearly",
                    "kind": "phrase",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                },
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        questions = iter(["Q1", "Q2"])
        with mock.patch(
            "utils.Tutor.ask_practice_question",
            side_effect=lambda *_args, **_kwargs: next(questions),
        ), mock.patch(
            "utils.TutorLead.compose",
            side_effect=lambda **kwargs: {
                "reply": kwargs.get("draft", ""),
                "keep_practice": True,
            },
        ):
            app.run()
            app.chat_input[0].set_value("我想练").run()
            app.chat_input[0].set_value("开始").run()
            app.chat_input[0].set_value(
                "let's start with I can hear you very clearly today."
            ).run()
        target = (app.session_state.get("tutor_practice") or [{}])[0]
        self.assertIn("I can hear you very clearly", target.get("label", ""))

    def test_tutor_force_check_scans_whole_chat(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 2,
            "lesson_id": "force-check",
            "goal": "检查",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": "user:a",
                    "label": "a",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                },
                {
                    "source_key": "user:b",
                    "label": "b",
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                },
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        ChatHistory.save(
            "tutor",
            [
                {"role": "assistant", "content": "先练 a。"},
                {"role": "user", "content": "a 的答案。"},
                {"role": "assistant", "content": "这个点可以了。"},
            ],
        )
        with mock.patch(
            "utils.PlanJudge.judge_conversation",
            return_value={
                "completed": [{"source_key": "user:a", "evidence": "可以了"}],
                "reason": "整场检查",
            },
        ):
            app.run()
            app.button(key="tutor_force_check").click().run()
        points = {
            point["source_key"]: point["status"]
            for point in app.session_state["tutor_plan"]["points"]
        }
        self.assertEqual(points["user:a"], "mastered")
        self.assertEqual(points["user:b"], "pending")

    def test_tutor_normal_chat_marks_previous_point_when_teacher_switches(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 2,
            "lesson_id": "chat-track",
            "goal": "tug lullaby downside",
            "warmup": "",
            "wrapup": "",
            "points": [
                {
                    "source_key": f"user:{word}",
                    "label": word,
                    "kind": "word",
                    "source": "user_request",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "user",
                }
                for word in ("tug", "lullaby", "downside")
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        replies = iter(
            [
                "好，那就从 tug 开始。用 tug 说一句完整的话。",
                "这句写得自然。接着练 lullaby。用 lullaby 说一句。",
            ]
        )
        judge_results = iter(
            [
                {"active_source_keys": ["user:tug"], "completed": [], "reason": ""},
                {
                    "active_source_keys": ["user:lullaby"],
                    "completed": [
                        {"source_key": "user:tug", "evidence": "学生回答了 tug"}
                    ],
                    "reason": "",
                },
            ]
        )
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            side_effect=lambda *_args, **_kwargs: {
                "reply": next(replies),
                "practice": None,
                "new_issues": [],
            },
        ), mock.patch(
            "utils.PlanJudge.judge_message",
            side_effect=lambda *_args, **_kwargs: next(judge_results),
        ), mock.patch(
            "utils.TutorLead.compose",
            side_effect=lambda **kwargs: {
                "reply": kwargs.get("draft", ""),
                "keep_practice": True,
            },
        ):
            app.run()
            app.chat_input[0].set_value("行啊").run()
            app.chat_input[0].set_value(
                "I had to tug my electric piano downstairs myself."
            ).run()
        points = {
            point["source_key"]: point["status"]
            for point in app.session_state["tutor_plan"]["points"]
        }
        self.assertEqual(points["user:tug"], "mastered")
        self.assertEqual(points["user:lullaby"], "pending")
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "answer")
        self.assertIn(
            "lullaby",
            (app.session_state.get("tutor_practice") or [{}])[0].get("label", ""),
        )

    def test_tutor_greeting_is_spoken_by_lead_and_does_not_start_training(self):
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={"reply": "你好呀，今天想聊什么？", "practice": None},
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "主模型：你好呀，今天想聊什么？",
                "keep_practice": True,
            },
        ):
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("你好呀").run()

        self.assertFalse(
            app.exception, f"发送问候报错：{[str(e) for e in app.exception]}"
        )
        messages = app.session_state["tutor_messages"]
        self.assertEqual(messages[-1]["content"], "主模型：你好呀，今天想聊什么？")
        self.assertFalse(app.session_state.get("tutor_practice_stage"))

    def test_generic_chat_history_is_restored(self):
        ChatHistory.save(
            "catgirl",
            [{"role": "assistant", "content": "这是上次没说完的话。"}],
        )
        app = self._run_page("chats/CatGirl.py")
        texts = [str(item.value or "") for item in app.markdown]
        self.assertTrue(any("上次没说完" in text for text in texts), texts)

    def test_freetalk_and_exam_history_are_restored(self):
        ChatHistory.save(
            "free_talk",
            [{"role": "assistant", "content": "上次自由聊天的话。"}],
        )
        ChatHistory.save(
            "exam",
            [{"role": "assistant", "content": "上次考官的话。"}],
        )
        free_app = self._run_page("chats/FreeTalk.py")
        free_texts = [str(item.value or "") for item in free_app.markdown]
        self.assertTrue(any("上次自由聊天" in text for text in free_texts), free_texts)
        exam_app = self._run_page("chats/chats.py")
        exam_texts = [str(item.value or "") for item in exam_app.markdown]
        self.assertTrue(any("上次考官" in text for text in exam_texts), exam_texts)

    def test_tutor_chat_history_survives_new_session(self):
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={"reply": "你好呀。", "practice": None, "new_issues": []},
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={"reply": "你好呀。", "keep_practice": True},
        ):
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("你好").run()
            app = self._run_page("chats/Tutor.py")
        contents = [
            str(message.get("content") or "")
            for message in app.session_state["tutor_messages"]
        ]
        self.assertIn("你好", contents)
        self.assertTrue(any("你好呀" in text for text in contents))

    def test_tutor_restart_clears_only_the_chat(self):
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={"reply": "你好呀。", "practice": None, "new_issues": []},
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={"reply": "你好呀。", "keep_practice": True},
        ):
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("你好").run()
            app.button(key="chat_restart_tutor").click().run()
            app.button(key="chat_restart_yes_tutor").click().run()
        contents = [
            str(message.get("content") or "")
            for message in app.session_state["tutor_messages"]
        ]
        self.assertNotIn("你好", contents)
        self.assertEqual(len(contents), 1)

    def test_psychologist_note_session_is_restored(self):
        ChatHistory.save(
            "psychologist",
            [{"role": "assistant", "content": "上次咨询的话。"}],
        )
        ChatHistory.save_meta(
            "psychologist",
            {"session_id": "abc123", "session_date": "2026-10-29"},
        )
        app = self._run_page("chats/Psychologist.py")
        self.assertEqual(app.session_state["psy_session_id"], "abc123")
        self.assertEqual(app.session_state["psy_session_date"], "2026-10-29")

    def test_freetalk_persona_is_restored(self):
        ChatHistory.save(
            "free_talk",
            [{"role": "assistant", "content": "上次自由聊天的话。"}],
        )
        ChatHistory.save_meta("free_talk", {"persona": "A patient IELTS tutor."})
        app = self._run_page("chats/FreeTalk.py")
        values = [str(item.value or "") for item in app.text_area]
        self.assertTrue(any("A patient IELTS tutor." in value for value in values), values)

    def test_tutor_remember_name_goes_to_about_you(self):
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={"reply": "记住了，我叫 Vicente。", "practice": None},
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "记住了，我叫 Vicente。",
                "keep_practice": True,
            },
        ):
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("记住自己叫Vicente").run()
        self.assertFalse(
            app.exception, f"记住名字报错：{[str(e) for e in app.exception]}"
        )
        facts = [fact["text"] for fact in Memory.load_memory("tutor")["facts"]]
        self.assertTrue(any("Vicente" in fact for fact in facts), facts)
        notes = TeacherMemory.load_memory()["notes"]
        self.assertFalse(any("Vicente" in note for note in notes), notes)

    def test_tutor_chat_errors_go_to_pending_list(self):
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={
                "reply": "这里 which 从句的动词要跟先行词一致。",
                "practice": None,
                "new_issues": ["which 从句动词单复数"],
            },
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "这里 which 从句的动词要跟先行词一致。",
                "keep_practice": True,
            },
        ):
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("I met a girl which lives next door.").run()
        self.assertFalse(
            app.exception, f"聊天错误记录报错：{[str(e) for e in app.exception]}"
        )
        self.assertIn(
            "which 从句动词单复数",
            [item["text"] for item in TutorErrors.items()],
        )

    def test_completed_plan_cannot_start_training(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_plan"] = {
            "version": 1,
            "lesson_id": "done",
            "goal": "已完成",
            "points": [
                {
                    "label": "irritation",
                    "kind": "word",
                    "why": "",
                    "task": "",
                    "criterion": "",
                    "status": "mastered",
                    "mastered_at": "2026-10-29 04:00:00",
                }
            ],
            "status": "done",
            "created_at": "",
            "updated_at": "",
        }
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={
                "reply": "好，我们用 irritation 练一句。",
                "practice": {
                    "question": "用 irritation 说一句。",
                    "targets": ["irritation"],
                    "model_answer": "The noise caused me irritation.",
                },
            },
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={
                "reply": "好，我们用 irritation 练一句。",
                "keep_practice": True,
            },
        ):
            app.chat_input[0].set_value("开始练").run()

        self.assertFalse(
            app.exception, f"已完成计划报错：{[str(e) for e in app.exception]}"
        )
        self.assertFalse(app.session_state.get("tutor_practice_stage"))

    def test_quick_add_includes_expression_mode(self):
        app = self._run_page("chats/Tutor.py")
        control = app.segmented_control(key="tutor_nb_type")
        # 和笔记本页一致：单词 → 表达 → 仓库
        self.assertEqual(
            control.options, ["单词 / 词组", "表达", "仓库"]
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
            any("巩固 2 个单词或词组" in str(c.value or "") for c in app.caption)
        )
        self.assertFalse(app.button(key="today_drill").disabled)


if __name__ == "__main__":
    unittest.main()
