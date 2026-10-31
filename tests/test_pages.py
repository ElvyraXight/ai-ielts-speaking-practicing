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
from datetime import date, timedelta
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
    HelpSession,
    Part2Card,
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
    "chats/Research.py",
    "chats/Help.py",
    "chats/ChatFriend.py",
    "chats/CatGirl.py",
    "chats/Psychologist.py",
    "chats/Mentor.py",
]

# 有「📓 随手记」的练习页：结构统一为「➕ 加入笔记本」+「📦 仓库」。
JOTTING_PAGES = [
    "chats/chats.py",
    "chats/FreeTalk.py",
    "chats/Part2.py",
    "chats/Tutor.py",
    "chats/Research.py",
    "chats/Help.py",
]

# 四个角色聊天页保留自己的「📝 写便签」，不并进随手记。
STICKY_NOTE_PAGES = [
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
            mock.patch.object(Part2Card, "CARD_PATH", cls.root / "part2_card.json"),
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
            Memory.MEMORY_PATH,
            Part2Card.CARD_PATH,
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

    def test_teacher_sidebar_hides_learning_profile(self):
        """「英语学习档案」面板已隐藏：数据照写，但侧栏不再渲染。"""
        TeacherMemory.remember_outcome("把 which 从句说顺了", "L1")
        self.addCleanup(TeacherMemory.clear_memory)

        app = self._run_page("chats/Tutor.py")
        texts = " ".join(str(c.value or "") for c in app.caption)
        self.assertNotIn("课堂成果", texts)
        self.assertNotIn("把 which 从句说顺了", texts)

    def test_mentor_major_is_saved_and_used(self):
        with mock.patch(
            "utils.ChatPage.get_entertainment_answer", side_effect=_fake_answer
        ) as answer, mock.patch(
            "utils.llm.call_llm_json",
            return_value={"major_en": "Computer Science"},
        ):
            app = self._run_page("chats/Mentor.py")
            app.text_input(key="mentor_major_input").set_value("计算机科学").run()
            app.chat_input[0].set_value("帮我看看这篇论文的结构").run()

        self.assertFalse(
            app.exception, f"学业导师发送报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(ChatHistory.load_meta("mentor").get("major"), "计算机科学")
        personas = [str(call.args[2]) for call in answer.call_args_list]
        self.assertTrue(personas)
        self.assertIn("Computer Science", personas[-1])
        self.assertNotIn("计算机科学", personas[-1])

    def test_mentor_major_survives_app_restart(self):
        with mock.patch(
            "utils.ChatPage.get_entertainment_answer", side_effect=_fake_answer
        ), mock.patch(
            "utils.llm.call_llm_json",
            return_value={"major_en": "Computer Science"},
        ):
            app = self._run_page("chats/Mentor.py")
            app.text_input(key="mentor_major_input").set_value("计算机科学").run()

            again = AppTest.from_file(
                str(_ROOT / "chats/Mentor.py"), default_timeout=60
            )
            again.run()
        self.assertFalse(again.exception)
        self.assertEqual(
            again.text_input(key="mentor_major_input").value, "计算机科学"
        )
        self.assertEqual(
            ChatHistory.load_meta("mentor").get("major_en"), "Computer Science"
        )

    def test_mentor_untranslatable_major_falls_back_to_default(self):
        """翻译结果不像正常专业名时，用默认英文专业名。"""
        with mock.patch(
            "utils.ChatPage.get_entertainment_answer", side_effect=_fake_answer
        ) as answer, mock.patch(
            "utils.llm.call_llm_json", return_value={"major_en": "xqz??"}
        ):
            app = self._run_page("chats/Mentor.py")
            app.text_input(key="mentor_major_input").set_value("量子玄学").run()
            app.chat_input[0].set_value("帮我看论文结构").run()

        self.assertFalse(
            app.exception, f"兜底报错：{[str(e) for e in app.exception]}"
        )
        personas = [
            str(call.args[2]) for call in answer.call_args_list if len(call.args) > 2
        ]
        self.assertTrue(personas)
        self.assertIn("Electronic Information Engineering", personas[-1])
        self.assertNotIn("xqz", personas[-1])

    def test_mentor_apply_major_restarts_chat(self):
        """「修改专业并重启对话」跟自由聊天的人设按钮同一套逻辑。"""
        ChatHistory.save(
            "mentor", [{"role": "assistant", "content": "旧的专业对话。"}]
        )
        with mock.patch(
            "utils.ChatPage.get_entertainment_answer", side_effect=_fake_answer
        ) as answer, mock.patch(
            "utils.llm.call_llm_json",
            return_value={"major_en": "Computer Science"},
        ):
            app = self._run_page("chats/Mentor.py")
            app.text_input(key="mentor_major_input").set_value("计算机科学").run()
            app.button(key="mentor_apply_major").click().run()

        self.assertFalse(
            app.exception, f"修改专业报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(ChatHistory.load_meta("mentor").get("major"), "计算机科学")
        contents = [
            str(message.get("content") or "")
            for message in app.session_state["mentor_messages"]
        ]
        self.assertFalse(any("旧的专业对话" in text for text in contents), contents)
        self.assertEqual(len(contents), 1)  # 只剩重启后的新开场白
        self.assertFalse(app.session_state["mentor_input_buffer"])
        personas = [
            str(call.args[2]) for call in answer.call_args_list if len(call.args) > 2
        ]
        self.assertTrue(personas)
        self.assertIn("Computer Science", personas[-1])

    def test_freetalk_persona_survives_app_restart(self):
        app = self._run_page("chats/FreeTalk.py")
        app.text_area(key="free_persona_input").set_value("A grumpy pirate").run()
        self.assertEqual(
            ChatHistory.load_meta("free_talk").get("persona"), "A grumpy pirate"
        )

        again = AppTest.from_file(str(_ROOT / "chats/FreeTalk.py"), default_timeout=60)
        again.run()
        self.assertFalse(again.exception)
        self.assertEqual(
            again.text_area(key="free_persona_input").value, "A grumpy pirate"
        )

    def test_words_exam_plan_dialog_saves(self):
        target = date.today() + timedelta(days=242)
        app = self._run_page("chats/Words.py")
        app.session_state["wa_plan_open"] = True
        app.session_state["wa_plan_band"] = 7.5
        app.session_state["wa_plan_auto"] = True
        app.session_state["wa_plan_date"] = target
        app.run()
        self.assertFalse(
            app.exception, f"考试计划对话框报错：{[str(e) for e in app.exception]}"
        )

        # 目标分数 stepper 和「暂不设置」都要能在对话框里安全重跑。
        app.button(key="wa_band_up").click().run()
        self.assertEqual(app.session_state["wa_plan_band"], 8.0)
        app.button(key="wa_band_down").click().run()
        self.assertEqual(app.session_state["wa_plan_band"], 7.5)

        app.button(key="wa_plan_save").click().run()
        settings = WordAtlas.load_progress()["settings"]
        self.assertEqual(settings["target_band"], 7.5)
        self.assertEqual(settings["exam_date"], target.isoformat())
        self.assertTrue(settings["auto_plan"])
        self.assertEqual(WordAtlas.daily_limit(), 16)

    def test_words_exam_plan_clear_date(self):
        app = self._run_page("chats/Words.py")
        app.session_state["wa_plan_open"] = True
        app.session_state["wa_plan_band"] = 7.5
        app.session_state["wa_plan_auto"] = False
        app.session_state["wa_plan_date"] = date.today() + timedelta(days=100)
        app.run()

        app.button(key="wa_plan_no_date").click().run()
        self.assertFalse(
            app.exception, f"暂不设置日期报错：{[str(e) for e in app.exception]}"
        )
        self.assertIsNone(app.session_state["wa_plan_date"])

        app.button(key="wa_plan_save").click().run()
        settings = WordAtlas.load_progress()["settings"]
        self.assertEqual(settings["exam_date"], "")
        self.assertFalse(settings["auto_plan"])

    def test_words_exam_plan_cancel_closes_dialog(self):
        app = self._run_page("chats/Words.py")
        app.session_state["wa_plan_open"] = True
        app.session_state["wa_plan_date"] = date.today() + timedelta(days=30)
        app.run()

        app.button(key="wa_plan_cancel").click().run()
        self.assertFalse(
            app.exception, f"取消考试计划报错：{[str(e) for e in app.exception]}"
        )
        self.assertFalse(app.session_state.get("wa_plan_open"))

    def test_chat_pages_share_the_jotting_module(self):
        """每个练习页侧栏都是同一套「📓 随手记」：加入笔记本 + 仓库。"""
        for path in JOTTING_PAGES:
            with self.subTest(page=path):
                if path == "chats/Help.py":
                    # 帮助页只有从考试页进入才有侧栏（source 为空时提前返回）。
                    HelpSession.start("exam")
                    self.addCleanup(lambda: HelpSession.clear("exam"))
                app = self._run_page(path)
                labels = [str(e.label or "") for e in app.expander]
                self.assertIn("➕ 加入笔记本", labels)
                self.assertIn("📦 仓库", labels)

    def test_roleplay_pages_keep_the_sticky_note_form(self):
        """猫娘 / 闲聊 / 咨询 / 导师页保留「📝 写便签」，不换成随手记。"""
        for path in STICKY_NOTE_PAGES:
            with self.subTest(page=path):
                app = self._run_page(path)
                labels = [str(e.label or "") for e in app.expander]
                self.assertIn("📝 写便签", labels)
                self.assertNotIn("➕ 加入笔记本", labels)

    def test_help_page_uses_memory_without_saving(self):
        HelpSession.start("exam")
        self.addCleanup(lambda: HelpSession.clear("exam"))
        with mock.patch(
            "utils.HelpCoach.advise", return_value={"hint": "先讲一个品质"}
        ) as advise, mock.patch(
            "utils.HelpCoach.preset_model_answer",
            return_value="My full name is Elvira Yang.",
        ) as preset, mock.patch(
            "utils.TutorLead.compose", return_value={"reply": "老师回复"}
        ) as compose, mock.patch(
            "utils.TeacherMemory.memory_text", return_value="STUDENT MEMORY"
        ), mock.patch(
            "utils.Memory.memory_text", return_value="ABOUT YOU"
        ), mock.patch(
            "utils.TeacherMemory.update_from_lesson"
        ) as update_student, mock.patch(
            "utils.Memory.update_memory"
        ) as update_personal, mock.patch(
            "utils.HelpMemory.update_async"
        ) as session_update:
            app = self._run_page("chats/Help.py")
            self.assertNotIn(
                "本题已使用帮助", " ".join(c.value for c in app.caption)
            )
            self.assertIn("返回考试", [button.label for button in app.button])
            self.assertIn("结束帮助", [button.label for button in app.button])

            app.chat_input[0].set_value("这题怎么答").run()
            self.assertFalse(
                app.exception, f"帮助页发送报错：{[str(e) for e in app.exception]}"
            )
            kwargs = compose.call_args.kwargs
            self.assertEqual(kwargs["student_memory"], "STUDENT MEMORY")
            self.assertEqual(kwargs["personal_memory"], "ABOUT YOU")
            # 长期记忆仍然只读；这一场求助的临时记忆由 HelpMemory 负责。
            update_student.assert_not_called()
            update_personal.assert_not_called()
            self.assertEqual(session_update.call_args.args[0], "exam")
            self.assertEqual(session_update.call_args.args[1], "这题怎么答")
            self.assertIn("session_memory", advise.call_args.kwargs)
            self.assertEqual(HelpSession.messages()[0]["content"], "这题怎么答")

            # 同一道题只生成一次参考回答，并传给后台教练。
            self.assertEqual(preset.call_count, 1)
            self.assertEqual(
                advise.call_args.kwargs["model_answer"],
                "My full name is Elvira Yang.",
            )
            # 要把这场求助的原文给教练，才不会再让你重复已经改好的地方。
            self.assertIn(
                "Student: 这题怎么答", advise.call_args.kwargs["help_history"]
            )
            self.assertFalse(advise.call_args.kwargs["repeated_attempt"])

            app.chat_input[0].set_value("这题怎么答").run()
            self.assertEqual(preset.call_count, 1)  # 已缓存，不重新生成
            self.assertTrue(advise.call_args.kwargs["repeated_attempt"])

    def test_help_page_from_part2_sees_the_student_answer(self):
        """从「讲个故事」求助时，老师要带着学生已写的答案，而不是只看到题卡。"""
        Part2Card.save("Describe a place you like")
        HelpSession.start("part2")
        self.addCleanup(lambda: HelpSession.clear("part2"))
        answer = "Last week I go to a park near my home. It is very quiet."
        with mock.patch(
            "utils.HelpCoach.advise", return_value={"hint": "先改时态"}
        ) as advise, mock.patch(
            "utils.HelpCoach.preset_model_answer", return_value="A model answer."
        ), mock.patch(
            "utils.TutorLead.compose", return_value={"reply": "老师回复"}
        ), mock.patch(
            "utils.HelpMemory.update_async"
        ):
            app = AppTest.from_file(str(_ROOT / "chats/Help.py"), default_timeout=60)
            app.session_state["part2_answer"] = answer
            app.run()
            self.assertFalse(
                app.exception, f"帮助页渲染报错：{[str(e) for e in app.exception]}"
            )

            # 「当前情况」里学生能看到自己的答案，老师也确实拿到了。
            texts = " ".join(str(item.value or "") for item in app.markdown)
            self.assertIn("你的答案", texts)
            self.assertIn(answer, texts)

            app.chat_input[0].set_value("这句话哪里不对").run()
            self.assertFalse(
                app.exception, f"帮助页发送报错：{[str(e) for e in app.exception]}"
            )
            self.assertEqual(advise.call_args.kwargs["student_answer"], answer)
            self.assertIn(answer, advise.call_args.kwargs["transcript"])

    def test_part2_page_keeps_a_copy_of_the_answer_for_the_help_page(self):
        """`part2_input` 是 widget 键、换页会被清掉；页面要留一份普通键。"""
        app = self._run_page("chats/Part2.py")
        app.text_area(key="part2_input").set_value(
            "Last week I went to a park near my home."
        ).run()
        self.assertEqual(
            app.session_state["part2_answer"],
            "Last week I went to a park near my home.",
        )
        # 同一份草稿也落盘了，刷新 / 重开软件后还能读回来。
        self.assertEqual(
            Part2Card.load_answer(),
            "Last week I went to a park near my home.",
        )

    def test_part2_page_restores_the_answer_draft(self):
        """答案草稿落盘：重进页面（等价于换页 / 刷新 / 重开）时输入框自动恢复。"""
        Part2Card.save("Describe a place you like")
        Part2Card.save_answer("Last week I went to a park near my home.")
        app = self._run_page("chats/Part2.py")
        self.assertEqual(
            app.text_area(key="part2_input").value,
            "Last week I went to a park near my home.",
        )
        self.assertEqual(
            app.session_state["part2_answer"],
            "Last week I went to a park near my home.",
        )

    def test_entertainment_page_send_flow(self):
        app = self._run_page("chats/CatGirl.py")
        self.assertEqual(len(app.session_state["cat_messages"]), 1)  # 开场白

        app.chat_input[0].set_value("hello there").run()

        self.assertFalse(
            app.exception, f"发送消息时报错：{[str(e) for e in app.exception]}"
        )
        messages = app.session_state["cat_messages"]
        self.assertEqual(len(messages), 3)  # 开场白 + 用户 + 回复
        self.assertEqual(messages[1]["content"], "hello there")
        self.assertEqual(messages[2]["role"], "assistant")

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

        # 取消删除 / 取消修改后这一条要保持展开，不能自己折叠回去。
        app.button(key="exp_del_btn_e1").click().run()
        app.button(key="exp_del_no_e1").click().run()
        self.assertEqual(app.session_state.get("exp_focus_entry"), "e1")

        app.button(key="exp_edit_btn_e1").click().run()
        app.button(key="exp_cancel_e1").click().run()
        self.assertEqual(app.session_state.get("exp_focus_entry"), "e1")

    def test_tutor_plan_shows_training_status_while_coaching(self):
        app = self._run_page("chats/Tutor.py")
        self.assertFalse(
            any("训练中" in str(e.label or "") for e in app.expander)
        )

        app.session_state["tutor_practice_stage"] = "answer"
        app.session_state["tutor_practice_question"] = "Tell me about your day."
        app.session_state["tutor_plan"] = {
            "points": [
                {
                    "source_key": "plan:test",
                    "label": "test point",
                    "kind": "phrase",
                    "source": "prep",
                    "status": "pending",
                    "added_by": "auto",
                }
            ]
        }
        app.run()
        self.assertFalse(
            app.exception, f"训练提示渲染报错：{[str(e) for e in app.exception]}"
        )
        labels = [str(e.label or "") for e in app.expander]
        self.assertTrue(any("本课计划（训练中）" in label for label in labels))

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
            return_value={
                "question": "Tell me about something that irritated you.",
                "model_answer": "The constant errand built my irritation.",
            },
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
            # 出题时一起生成的标准答案要留给教练做参照。
            self.assertEqual(
                app.session_state.get("tutor_practice_model"),
                "The constant errand built my irritation.",
            )
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
        ), mock.patch("utils.Memory.update_memory") as update_memory:
            app.run()
            app.chat_input[0].set_value("我想练").run()
            app.chat_input[0].set_value("开始").run()
            app.chat_input[0].set_value("A short answer.").run()
            time.sleep(0.1)
            self.assertFalse(
                any(
                    call.args and call.args[0] == "tutor"
                    for call in update_memory.call_args_list
                ),
                "训练不应写「关于你」",
            )
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

    def test_tutor_mastered_training_state_is_restored_after_refresh(self):
        ChatHistory.save("tutor", [{"role": "assistant", "content": "Done."}])
        ChatHistory.save_meta(
            "tutor",
            {
                "training": {
                    "point": [{"source_key": "user:a", "label": "a", "kind": "word"}],
                    "question": "Tell me about a.",
                    "model": "",
                    "stage": "mastered",
                    "focus": "",
                    "checklist": [],
                    "turns": 1,
                    "lesson": "test",
                }
            },
        )
        app = self._run_page("chats/Tutor.py")
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "mastered")

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
                "I had to carry my electric piano downstairs myself."
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

    def test_exam_restart_does_not_get_stuck_on_confirmation(self):
        app = self._run_page("chats/chats.py")
        app.button(key="chat_restart_exam").click().run()
        # 弹窗文案要说明这次清空的是模拟考试记录和进度。
        dialog_text = " ".join(str(item.value or "") for item in app.markdown)
        self.assertIn("确认清空这场模拟考试记录并重置考试进度？", dialog_text)
        app.button(key="chat_restart_yes_exam").click().run()
        self.assertFalse(
            app.exception, f"重新开始报错：{[str(e) for e in app.exception]}"
        )
        self.assertFalse(app.session_state.get("chat_restart_confirm_exam"))

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

    def test_exam_input_matches_story_style_and_submits(self):
        """严肃话题输入区跟「讲个故事」一致：多行输入框 + 通栏提交按钮。"""
        app = self._run_page("chats/chats.py")
        self.assertEqual(app.button(key="exam_submit").label, "提交并获取反馈")

        app.text_area(key="input_buffer").set_value("My name is Lin.").run()
        app.button(key="exam_submit").click().run()

        self.assertFalse(
            app.exception, f"严肃话题提交报错：{[str(e) for e in app.exception]}"
        )
        contents = [
            str(message.get("content") or "")
            for message in app.session_state["messages"]
        ]
        self.assertIn("My name is Lin.", contents)
        self.assertEqual(app.session_state["input_buffer"], "")

    def test_freetalk_input_matches_story_style_and_submits(self):
        """自由聊天输入区同样对齐「讲个故事」，提交后清空输入框。"""
        app = self._run_page("chats/FreeTalk.py")
        self.assertEqual(app.button(key="free_submit").label, "提交并获取反馈")

        app.text_area(key="free_input_buffer").set_value("Hi, how's it going?").run()
        app.button(key="free_submit").click().run()

        self.assertFalse(
            app.exception, f"自由聊天提交报错：{[str(e) for e in app.exception]}"
        )
        contents = [
            str(message.get("content") or "")
            for message in app.session_state["free_messages"]
        ]
        self.assertIn("Hi, how's it going?", contents)
        self.assertEqual(app.session_state["free_input_buffer"], "")

    def test_tutor_non_word_lookup_goes_to_casual_chat(self):
        """qwq 这类表情符号不是查词：不弹词典，直接走闲聊。"""
        with mock.patch(
            "utils.Tutor.explain_vocabulary",
            return_value={
                "intro": "",
                "items": [],
                "clarify": "",
                "clarify_kind": "not_english",
            },
        ), mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={
                "reply": "哈哈，qwq 是委屈的表情吧。",
                "practice": None,
                "new_issues": [],
            },
        ) as turn:
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("qwq").run()

        self.assertFalse(
            app.exception, f"闲聊报错：{[str(e) for e in app.exception]}"
        )
        messages = app.session_state["tutor_messages"]
        self.assertEqual(messages[-1]["content"], "哈哈，qwq 是委屈的表情吧。")
        self.assertTrue(turn.called)
        self.assertFalse(any(message.get("items") for message in messages))

    def test_tutor_misspelling_asks_before_dictionary(self):
        with mock.patch(
            "utils.Tutor.explain_vocabulary",
            return_value={
                "intro": "",
                "items": [],
                "clarify": "「personnal」看着不像正常英语，你是想问 personal 吗？",
                "clarify_kind": "misspelling",
            },
        ), mock.patch("utils.Tutor.ask_tutor_turn") as turn:
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value("personnal").run()

        self.assertFalse(
            app.exception, f"反问报错：{[str(e) for e in app.exception]}"
        )
        self.assertIn(
            "personal", app.session_state["tutor_messages"][-1]["content"]
        )
        turn.assert_not_called()

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

    def test_research_chat_send(self):
        with mock.patch(
            "utils.llm.call_llm_json", return_value={"reply": "这是回答。"}
        ):
            app = self._run_page("chats/Research.py")
            app.chat_input[0].set_value("什么是抽样？").run()

        self.assertFalse(
            app.exception, f"查资料发送报错：{[str(e) for e in app.exception]}"
        )
        messages = app.session_state["research_messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "什么是抽样？")
        self.assertEqual(messages[1]["content"], "这是回答。")

    def test_research_page_shows_warehouse_sidebar(self):
        """查资料页和其他练习页一样，侧边栏要有只读的「📦 仓库」入口。"""
        app = self._run_page("chats/Research.py")

        self.assertFalse(
            app.exception, f"查资料侧边栏报错：{[str(e) for e in app.exception]}"
        )
        self.assertIn("📦 仓库", [str(e.label or "") for e in app.expander])

    def test_research_restart_clears_history(self):
        ChatHistory.save("research", [{"role": "user", "content": "旧问题"}])
        app = self._run_page("chats/Research.py")
        app.button(key="chat_restart_research").click().run()
        app.button(key="chat_restart_yes_research").click().run()

        self.assertFalse(
            app.exception, f"查资料重启报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(ChatHistory.load("research"), [])
        self.assertEqual(list(app.session_state["research_messages"]), [])

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

    def test_psychologist_restart_warns_short_note(self):
        """对话不足 3 条时，确认弹窗要说明不会保存诊疗笔记。"""
        ChatHistory.save(
            "psychologist",
            [
                {"role": "assistant", "content": "你好，我是林医生。"},
                {"role": "user", "content": "最近有点累。"},
                {"role": "assistant", "content": "听起来不容易。"},
            ],
        )
        app = self._run_page("chats/Psychologist.py")
        app.button(key="chat_restart_psychologist").click().run()
        texts = " ".join(str(item.value or "") for item in app.markdown)
        self.assertIn("不会保存诊疗笔记", texts)
        app.button(key="chat_restart_no_psychologist").click().run()

    def test_psychologist_restart_deletes_short_session_note(self):
        """3 条以内的会话即使之前写过笔记，重新开始时也要真删掉。"""
        ChatHistory.save(
            "psychologist",
            [
                {"role": "assistant", "content": "你好。"},
                {"role": "user", "content": "第一句"},
                {"role": "assistant", "content": "嗯。"},
                {"role": "user", "content": "第二句"},
            ],
        )
        ChatHistory.save_meta(
            "psychologist", {"session_id": "short1", "session_date": "2026-10-30"}
        )
        Notes._save_all(
            {
                "psychologist": {
                    "short1": {
                        "date": "2026-10-30",
                        "summary": "旧的一条短笔记",
                        "details": [],
                        "next": [],
                        "created_at": "2026-10-30 10:00:00",
                        "updated_at": "2026-10-30 10:00:00",
                    }
                }
            }
        )
        app = self._run_page("chats/Psychologist.py")
        app.button(key="chat_restart_psychologist").click().run()
        app.button(key="chat_restart_yes_psychologist").click().run()
        self.assertEqual(Notes.load_notes("psychologist"), [])

    def test_psychologist_restart_keeps_note_after_four_turns(self):
        """聊过 3 条（第 4 次往来）之后，重新开始不应删掉已有笔记。"""
        ChatHistory.save(
            "psychologist",
            [
                {"role": "assistant", "content": "你好。"},
                {"role": "user", "content": "第一句"},
                {"role": "assistant", "content": "嗯。"},
                {"role": "user", "content": "第二句"},
                {"role": "assistant", "content": "嗯嗯。"},
                {"role": "user", "content": "第三句"},
                {"role": "assistant", "content": "嗯嗯嗯。"},
                {"role": "user", "content": "第四句"},
            ],
        )
        ChatHistory.save_meta(
            "psychologist", {"session_id": "long1", "session_date": "2026-10-30"}
        )
        Notes._save_all(
            {
                "psychologist": {
                    "long1": {
                        "date": "2026-10-30",
                        "summary": "一条够长的笔记",
                        "details": [],
                        "next": ["先休息"],
                        "created_at": "2026-10-30 10:00:00",
                        "updated_at": "2026-10-30 10:00:00",
                    }
                }
            }
        )
        app = self._run_page("chats/Psychologist.py")
        app.button(key="chat_restart_psychologist").click().run()
        app.button(key="chat_restart_yes_psychologist").click().run()
        self.assertEqual(len(Notes.load_notes("psychologist")), 1)

    def test_mentor_restart_no_short_note_warning_after_four_turns(self):
        """聊过 3 条（第 4 条起）后，弹窗不再提示不会保存指导记录。"""
        ChatHistory.save(
            "mentor",
            [
                {"role": "assistant", "content": "坐吧。"},
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "答一"},
                {"role": "user", "content": "第二问"},
                {"role": "assistant", "content": "答二"},
                {"role": "user", "content": "第三问"},
                {"role": "assistant", "content": "答三"},
                {"role": "user", "content": "第四问"},
            ],
        )
        app = self._run_page("chats/Mentor.py")
        app.button(key="chat_restart_mentor").click().run()
        texts = " ".join(str(item.value or "") for item in app.markdown)
        self.assertNotIn("不会保存指导记录", texts)

    def test_psychologist_can_delete_a_note(self):
        """侧边栏「删除记录…」能删掉选中的诊疗笔记，且不影响其他记录。"""
        Notes._save_all(
            {
                "psychologist": {
                    "old1": {
                        "date": "2026-10-01",
                        "summary": "OLD ONE",
                        "details": [],
                        "next": [],
                        "created_at": "2026-10-01 10:00:00",
                        "updated_at": "2026-10-01 10:00:00",
                    },
                    "old2": {
                        "date": "2026-10-02",
                        "summary": "OLD TWO",
                        "details": [],
                        "next": [],
                        "created_at": "2026-10-02 10:00:00",
                        "updated_at": "2026-10-02 10:00:00",
                    },
                }
            }
        )
        ChatHistory.save_meta(
            "psychologist", {"session_id": "current", "session_date": "2026-10-31"}
        )
        ChatHistory.save(
            "psychologist", [{"role": "assistant", "content": "你好，我是林医生。"}]
        )
        app = self._run_page("chats/Psychologist.py")
        app.button(key="note_manage_btn_psychologist").click().run()
        app.button(key="note_del_psychologist_old1").click().run()
        app.button(key="note_del_yes_psychologist").click().run()

        self.assertFalse(
            app.exception, f"删除诊疗笔记报错：{[str(e) for e in app.exception]}"
        )
        ids = [note["id"] for note in Notes.load_notes("psychologist")]
        self.assertNotIn("old1", ids)
        self.assertIn("old2", ids)

    def test_psychologist_note_date_uses_last_message_date(self):
        app = self._run_page("chats/Psychologist.py")
        app.session_state["psy_session_date"] = "2026-10-29"
        with mock.patch(
            "utils.ChatPage.get_entertainment_answer",
            return_value=(
                {
                    "reply": "嗯，我在听。",
                    "correction": "",
                    "suggestion": "",
                    "model_answer": "",
                },
                None,
            ),
        ) as answer:
            app.chat_input[0].set_value("最近有点累").run()

        expected = date.today().isoformat()
        self.assertEqual(answer.call_args.kwargs.get("note_date"), expected)
        self.assertEqual(app.session_state["psy_session_date"], expected)

    def test_psychologist_current_note_hidden_until_restart(self):
        Notes._save_all(
            {
                "psychologist": {
                    "current": {
                        "date": "2026-10-31",
                        "summary": "CURRENT NOTE",
                        "details": [],
                        "next": [],
                        "created_at": "2026-10-31 10:00:00",
                        "updated_at": "2026-10-31 10:00:00",
                    },
                    "prev": {
                        "date": "2026-10-30",
                        "summary": "PREVIOUS NOTE",
                        "details": [],
                        "next": [],
                        "created_at": "2026-10-30 10:00:00",
                        "updated_at": "2026-10-30 10:00:00",
                    },
                }
            }
        )
        ChatHistory.save_meta(
            "psychologist",
            {"session_id": "current", "session_date": "2026-10-31"},
        )
        # 聊过 3 条以上，重启时才不会按「短会话」把这条笔记删掉。
        ChatHistory.save(
            "psychologist",
            [
                {"role": "assistant", "content": "你好。"},
                {"role": "user", "content": "第一句"},
                {"role": "assistant", "content": "嗯。"},
                {"role": "user", "content": "第二句"},
                {"role": "assistant", "content": "嗯嗯。"},
                {"role": "user", "content": "第三句"},
                {"role": "assistant", "content": "嗯嗯嗯。"},
                {"role": "user", "content": "第四句"},
            ],
        )
        app = self._run_page("chats/Psychologist.py")
        texts = " ".join(str(item.value or "") for item in app.markdown)
        self.assertIn("PREVIOUS NOTE", texts)
        self.assertNotIn("CURRENT NOTE", texts)

        restart = next(
            button for button in app.button if "重新开始聊天" in button.label
        )
        restart.click().run()
        confirm = next(
            button for button in app.button if "确认重新开始" in button.label
        )
        confirm.click().run()
        texts = " ".join(str(item.value or "") for item in app.markdown)
        self.assertIn("CURRENT NOTE", texts)

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
        self.assertNotIn("notes", TeacherMemory.load_memory())

    def test_tutor_remember_learning_fact_also_goes_to_about_you(self):
        """学习类的「记住…」也不再进学习档案，统一进「关于你」。"""
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={"reply": "记住了。", "practice": None},
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={"reply": "记住了。", "keep_practice": True},
        ):
            app = self._run_page("chats/Tutor.py")
            app.chat_input[0].set_value(
                "记住我最容易错的语法是从句单复数"
            ).run()
        self.assertFalse(
            app.exception, f"记住语法报错：{[str(e) for e in app.exception]}"
        )
        facts = [fact["text"] for fact in Memory.load_memory("tutor")["facts"]]
        self.assertTrue(any("从句" in fact for fact in facts), facts)
        self.assertNotIn("notes", TeacherMemory.load_memory())

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

    def test_tutor_plan_related_answer_coaches_directly(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_practice_stage"] = ""
        app.session_state["tutor_plan"] = {
            "version": 1,
            "lesson_id": "related",
            "goal": "练 tug",
            "points": [
                {
                    "source_key": "word:tug",
                    "label": "tug（n. 拉力）",
                    "kind": "word",
                    "source": "prep",
                    "task": "Tell me about a time you gave something a tug.",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "auto",
                }
            ],
            "status": "active",
            "created_at": "",
            "updated_at": "",
            "last_auto_plan_date": "",
            "history": [],
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        answer = "I gave the rope a hard tug to pull it free."
        with mock.patch(
            "utils.Tutor.coach_practice_answer",
            return_value={
                "feedback": "这个点可以了。",
                "focus": "",
                "status": "mastered",
                "reason": "criteria_met",
                "checklist": [],
                "usage": [],
                "new_issues": [],
            },
        ) as coach, mock.patch(
            "utils.TutorLead.compose",
            return_value={"reply": "这个点可以了。", "keep_practice": True},
        ), mock.patch(
            "utils.PlanJudge.judge_message",
            return_value={"completed": [], "reason": ""},
        ), mock.patch(
            "utils.TeacherMemory.update_from_lesson", return_value={}
        ), mock.patch(
            "utils.TrainingMemory.memory_text", return_value="TEMP MEMORY"
        ), mock.patch(
            "utils.TrainingMemory.update_async"
        ) as update_temp:
            app.run()
            app.chat_input[0].set_value(answer).run()

        self.assertFalse(
            app.exception, f"计划相关回答报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "mastered")
        self.assertEqual(
            app.session_state["tutor_practice"][0]["source_key"], "word:tug"
        )
        coach.assert_called_once()
        self.assertEqual(coach.call_args.args[2], answer)
        self.assertEqual(
            coach.call_args.kwargs.get("training_memory"), "TEMP MEMORY"
        )
        update_temp.assert_called_once()
        self.assertEqual(update_temp.call_args.args[0], answer)

    def test_tutor_plan_related_question_asks_training_question(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_practice_stage"] = ""
        app.session_state["tutor_plan"] = {
            "version": 1,
            "lesson_id": "related",
            "goal": "练 irritation",
            "points": [
                {
                    "source_key": "word:irritation",
                    "label": "irritation（n. 恼怒）",
                    "kind": "word",
                    "source": "prep",
                    "task": "",
                    "criterion": "",
                    "status": "pending",
                    "mastered_at": "",
                    "added_by": "auto",
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
            return_value="Tell me about a time you felt irritation.",
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={"reply": "好，我们练这个。", "keep_practice": True},
        ):
            app.run()
            app.chat_input[0].set_value("irritation 怎么用？").run()

        self.assertFalse(
            app.exception, f"计划相关提问报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(app.session_state.get("tutor_practice_stage"), "answer")

    def test_completed_plan_related_answer_does_not_start_training(self):
        app = self._run_page("chats/Tutor.py")
        app.session_state["tutor_practice_stage"] = ""
        app.session_state["tutor_plan"] = {
            "version": 1,
            "lesson_id": "done",
            "goal": "已完成",
            "points": [
                {
                    "source_key": "word:irritation",
                    "label": "irritation（n. 恼怒）",
                    "kind": "word",
                    "source": "prep",
                    "task": "",
                    "criterion": "",
                    "status": "mastered",
                    "mastered_at": "2026-10-29 04:00:00",
                    "added_by": "auto",
                }
            ],
            "status": "done",
            "created_at": "",
            "updated_at": "",
        }
        TutorPlan._save_unlocked(app.session_state["tutor_plan"])
        with mock.patch(
            "utils.Tutor.ask_tutor_turn",
            return_value={"reply": "好。", "practice": None},
        ) as ask_turn, mock.patch(
            "utils.TrainingMemory.memory_text", return_value="TEMP MEMORY"
        ), mock.patch(
            "utils.TutorLead.compose",
            return_value={"reply": "好。", "keep_practice": True},
        ):
            app.run()
            app.chat_input[0].set_value(
                "I felt irritation when my package was left on the top shelf."
            ).run()

        self.assertFalse(
            app.exception, f"已完成计划报错：{[str(e) for e in app.exception]}"
        )
        self.assertFalse(app.session_state.get("tutor_practice_stage"))
        self.assertEqual(
            ask_turn.call_args.kwargs.get("training_memory"), "TEMP MEMORY"
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

    def test_memory_clear_needs_confirmation(self):
        """「清空记忆」和「重新开始」一样：先弹确认框，确认后才真删。"""
        Memory._save_all(
            {
                "catgirl": {
                    "summary": "",
                    "facts": ["喜欢蓝色"],
                    "updated_at": "",
                }
            }
        )
        self.addCleanup(lambda: Memory.clear_memory("catgirl"))
        app = self._run_page("chats/CatGirl.py")

        app.button(key="mem_clear_catgirl").click().run()
        self.assertFalse(
            app.exception,
            f"打开清空记忆确认框报错：{[str(e) for e in app.exception]}",
        )
        dialog_text = " ".join(str(item.value or "") for item in app.markdown)
        self.assertIn("确认清空「记忆」里的全部内容？清空后无法恢复。", dialog_text)
        # 只是打开确认框，还没真删。
        self.assertTrue(Memory.load_memory("catgirl")["facts"])

        app.button(key="mem_clear_no_catgirl").click().run()
        self.assertTrue(Memory.load_memory("catgirl")["facts"])

        app.button(key="mem_clear_catgirl").click().run()
        app.button(key="mem_clear_yes_catgirl").click().run()
        self.assertFalse(
            app.exception, f"确认清空记忆报错：{[str(e) for e in app.exception]}"
        )
        self.assertEqual(Memory.load_memory("catgirl")["facts"], [])

if __name__ == "__main__":
    unittest.main()
