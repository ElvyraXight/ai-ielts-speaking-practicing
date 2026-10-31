"""核心逻辑的回归测试（只用标准库，不依赖 pytest）。

跑法：python -m unittest discover -s tests -v
覆盖最容易"悄悄坏掉"的逻辑：落盘备份 / 读取、LLM 解析与重试、
Part 2 题卡与纠错清洗、背单词排期、角色记忆、语音文件清理。
"""

import json
import os
import shutil
import sys
import time
import unittest
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import Entertainment as entertainment  # noqa: E402
from utils import LearnerProfile as learner_profile  # noqa: E402
from utils import Memory as memory  # noqa: E402
from utils import Notes as notes  # noqa: E402
from utils import Part2, WordAtlas, config, conversation, llm, storage, tts  # noqa: E402
from utils import Expressions  # noqa: E402
from utils import Notebook  # noqa: E402
from utils import PlanJudge  # noqa: E402
from utils import QuickLookup as quick_lookup  # noqa: E402
from utils import Tutor as tutor_mod  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def setUpModule() -> None:
    # 上次异常退出可能留下临时目录（Windows 上偶尔还删不掉），先尽量清一次。
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_tmp_dir() -> Path:
    """在仓库内建临时目录：系统临时目录在 Windows 沙箱下可能写不进去。"""
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TMP_ROOT / f"case-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self.backup_dir = self.root / "backups"
        self.patches = [
            mock.patch.object(storage, "BACKUP_DIR", self.backup_dir),
            mock.patch.object(storage, "CORRUPT_DIR", self.backup_dir / "corrupt"),
        ]
        for patcher in self.patches:
            patcher.start()
        self.path = self.root / "data" / "notes.json"

    def tearDown(self):
        for patcher in self.patches:
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _backups(self, stem="notes"):
        return sorted(self.backup_dir.glob(f"{stem}-*.json"))

    def test_first_write_creates_no_backup(self):
        storage.save_json(self.path, {"v": 1})
        self.assertEqual(self._backups(), [])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"v": 1})

    def test_backup_keeps_one_file_per_day(self):
        storage.save_json(self.path, {"v": 1})
        storage.save_json(self.path, {"v": 2})
        storage.save_json(self.path, {"v": 3})

        backups = self._backups()
        self.assertEqual(len(backups), 1, "同一天应该只有一份快照")
        self.assertEqual(backups[0].name, f"notes-{time.strftime('%Y%m%d')}.json")
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), {"v": 1})

    def test_identical_content_is_not_rewritten(self):
        storage.save_json(self.path, {"v": 1})
        before = self.path.stat().st_mtime_ns
        storage.save_json(self.path, {"v": 1})
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_corrupt_file_is_quarantined(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ this is not json", encoding="utf-8")

        storage.save_json(self.path, {"v": 1})

        quarantined = list((self.backup_dir / "corrupt").glob("notes-*.json"))
        self.assertEqual(len(quarantined), 1)
        self.assertIn("not json", quarantined[0].read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"v": 1})

    def test_old_backups_are_pruned(self):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        old_day = (date.today() - timedelta(days=storage.MAX_BACKUP_DAYS + 1)).strftime("%Y%m%d")
        recent_day = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
        (self.backup_dir / f"notes-{old_day}.json").write_text("{}", encoding="utf-8")
        (self.backup_dir / f"notes-{recent_day}.json").write_text("{}", encoding="utf-8")

        storage._prune("notes")

        names = [p.name for p in self._backups()]
        self.assertNotIn(f"notes-{old_day}.json", names)
        self.assertIn(f"notes-{recent_day}.json", names)


class CueCardTest(unittest.TestCase):
    def test_parse_card_normalises_bullets(self):
        topic, points = Part2._parse_card(
            {
                "topic": "describe a place you like",
                "points": [
                    "Where it is",
                    "How often you go there",
                    "what you usually do there (e.g. reading)",
                    "explain why you like it",
                ],
            }
        )
        self.assertTrue(topic.startswith("Describe"))
        self.assertEqual(len(points), 4)
        self.assertEqual(points[2], "what you usually do there")
        self.assertTrue(points[3].startswith("and explain "))

    def test_points_as_string_are_split(self):
        _, points = Part2._parse_card(
            {
                "topic": "Describe a skill",
                "points": "what it is\nhow you learned it\nwhat was hard\nand explain why",
            }
        )
        self.assertEqual(len(points), 4)

    def test_topic_rejects_first_person_and_chinese(self):
        self.assertIsNotNone(Part2._topic_problem("Describe my hometown"))
        self.assertIsNotNone(Part2._topic_problem("Describe 一条街"))
        self.assertIsNone(Part2._topic_problem("Describe a place you often visit"))

    def test_recent_topic_detection(self):
        recent = ["Describe a place you often visit in your city"]
        self.assertTrue(
            Part2._topic_is_recent("Describe a place you often visit in your city", recent)
        )
        self.assertFalse(Part2._topic_is_recent("Describe a skill you learned", recent))

    def test_fabricated_correction_is_dropped(self):
        story = "I went there last year and I see many beautiful flowers."
        feedback = "\n".join(
            [
                "- 原句「I see many beautiful flowers.」→ 改为「I saw many beautiful flowers.」（叙述过去的事用过去时）",
                "- 原句「I visited a big museum.」→ 改为「I visited a huge museum.」（用词）",
            ]
        )
        cleaned = Part2._filter_fabricated_corrections(feedback, story)
        self.assertIn("beautiful flowers", cleaned)
        self.assertNotIn("museum", cleaned)

    def test_false_tense_fix_is_dropped(self):
        """把 every weekend 这类习惯句改成过去时，是模型常见的误判。"""
        story = "I go there every weekend with my friend."
        feedback = "- 原句「I go there every weekend.」→ 改为「I went there every weekend.」（时态）"
        self.assertEqual(Part2._filter_fabricated_corrections(feedback, story), "")

    def test_clean_answer_strips_chinese_and_template_tokens(self):
        raw = "The answer starts here and 继续 continues. <|im_start|>user"
        cleaned = Part2._clean_answer(raw)
        self.assertNotIn("<|", cleaned)
        self.assertNotIn("中文", cleaned)
        self.assertNotIn("继续", cleaned)
        self.assertIn("The answer starts here", cleaned)


class SchedulingTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()
        self._patch = mock.patch.object(
            WordAtlas, "PROGRESS_PATH", self.root / "word_progress.json"
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_first_good_answer_schedules_tomorrow(self):
        record = WordAtlas.apply_review("word-1", "good")
        self.assertEqual(record["reps"], 1)
        self.assertEqual(record["interval"], 1)
        self.assertEqual(record["due"], (date.today() + timedelta(days=1)).isoformat())

    def test_second_good_answer_moves_to_three_days(self):
        WordAtlas.apply_review("word-1", "good")
        record = WordAtlas.apply_review("word-1", "good")
        self.assertEqual(record["reps"], 2)
        self.assertEqual(record["interval"], 3)

    def test_forgetting_resets_the_word(self):
        WordAtlas.apply_review("word-1", "good")
        WordAtlas.apply_review("word-1", "good")
        record = WordAtlas.apply_review("word-1", "again")
        self.assertEqual(record["reps"], 0)
        self.assertEqual(record["lapses"], 1)
        self.assertEqual(record["due"], date.today().isoformat())

    def test_daily_counters(self):
        WordAtlas.apply_review("word-1", "good")
        WordAtlas.apply_review("word-2", "good")
        WordAtlas.apply_review("word-1", "good")
        counts = WordAtlas.today_counts()
        self.assertEqual(counts["new"], 2)
        self.assertEqual(counts["review"], 1)

    def test_spelling_comparison_ignores_spaces_and_case(self):
        question = {"mode": "spell", "answer": "well-being"}
        self.assertTrue(WordAtlas.check_answer(question, "Well Being"))
        self.assertFalse(WordAtlas.check_answer(question, "wellbeingx"))

    def test_modes_follow_reps(self):
        self.assertEqual(WordAtlas.mode_for(0), "meaning")
        self.assertEqual(WordAtlas.mode_for(1), "recall")
        self.assertEqual(WordAtlas.mode_for(5), "spell")


class ExamPlanTest(unittest.TestCase):
    """考试计划：分数 → CEFR 范围、剩余天数 → 每日新词。"""

    def setUp(self):
        self.root = _make_tmp_dir()
        self.progress_path = self.root / "word_progress.json"
        self._patches = [
            mock.patch.object(WordAtlas, "PROGRESS_PATH", self.progress_path),
            mock.patch.object(storage, "BACKUP_DIR", self.root / "backups"),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _progress(self, **settings) -> dict:
        base = {
            "version": 1,
            "words": {},
            "daily": {},
            "settings": {
                "new_per_day": 10,
                "start_cefr": "A1",
                "topics": [],
                "exam_date": "",
                "target_band": 7.5,
                "auto_plan": False,
            },
        }
        base["settings"].update(settings)
        return base

    def test_seven_point_five_maps_to_b2_c1(self):
        self.assertEqual(WordAtlas.band_range(7.5), ("B2", "C1"))
        self.assertEqual(WordAtlas.band_range(7.4), ("B2", "C1"))
        self.assertEqual(WordAtlas.band_range(6.0), ("B1", "B2"))
        self.assertEqual(WordAtlas.band_label(8.0), "C1–C2")

    def test_plan_counts_and_per_day(self):
        target = (date.today() + timedelta(days=242)).isoformat()
        plan = WordAtlas.exam_plan(progress=self._progress(exam_date=target))
        self.assertTrue(plan["set"])
        self.assertEqual(plan["range"], "B2–C1")
        self.assertEqual(plan["total"], 3735)
        self.assertEqual(plan["days"], 242)
        self.assertEqual(plan["review_days"], 7)
        self.assertEqual(plan["per_day"], 16)

    def test_learned_words_in_range_are_subtracted(self):
        word = next(w for w in WordAtlas.load_words() if w.get("cefr") == "B2")
        progress = self._progress(
            exam_date=(date.today() + timedelta(days=242)).isoformat()
        )
        progress["words"][str(word["id"]).lower()] = {"reps": 1}
        plan = WordAtlas.exam_plan(progress=progress)
        self.assertEqual(plan["learned"], 1)
        self.assertEqual(plan["remaining"], 3734)

    def test_last_week_only_review(self):
        progress = self._progress(
            exam_date=(date.today() + timedelta(days=5)).isoformat()
        )
        plan = WordAtlas.exam_plan(progress=progress)
        self.assertEqual(plan["days"], 5)
        self.assertEqual(plan["per_day"], 0)

    def test_auto_plan_drives_daily_limit(self):
        target = (date.today() + timedelta(days=242)).isoformat()
        self.assertEqual(
            WordAtlas.daily_limit(self._progress(exam_date=target, auto_plan=True)),
            16,
        )
        self.assertEqual(
            WordAtlas.daily_limit(
                self._progress(exam_date=target, auto_plan=False, new_per_day=30)
            ),
            30,
        )
        self.assertEqual(
            WordAtlas.daily_limit(
                self._progress(exam_date="", auto_plan=True, new_per_day=25)
            ),
            25,
        )

    def test_update_settings_clamps_and_validates(self):
        WordAtlas.update_settings(
            target_band=7.3, exam_date="2027-06-30", auto_plan=True
        )
        settings = WordAtlas.load_progress()["settings"]
        self.assertEqual(settings["target_band"], 7.5)
        self.assertEqual(settings["exam_date"], "2027-06-30")
        self.assertTrue(settings["auto_plan"])

        WordAtlas.update_settings(exam_date="not-a-date", target_band=4.2)
        settings = WordAtlas.load_progress()["settings"]
        self.assertEqual(settings["exam_date"], "")
        self.assertEqual(settings["target_band"], 4.0)

    def test_legacy_target_date_becomes_exam_date(self):
        self.progress_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "words": {},
                    "daily": {},
                    "settings": {
                        "target_date": "2027-06-30",
                        "new_per_day": 10,
                        "start_cefr": "A1",
                        "topics": [],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        settings = WordAtlas.load_progress()["settings"]
        self.assertEqual(settings["exam_date"], "2027-06-30")
        self.assertEqual(settings["target_band"], WordAtlas.DEFAULT_BAND)


class ConfigTest(unittest.TestCase):
    def test_provider_resolution(self):
        with mock.patch.object(config, "DEEPSEEK_API_KEY", ""):
            self.assertEqual(config._resolve_provider("auto"), "ollama")
            self.assertEqual(config._resolve_provider("deepseek"), "ollama")
            self.assertEqual(config._resolve_provider("nonsense"), "ollama")
        with mock.patch.object(config, "DEEPSEEK_API_KEY", "sk-test"):
            self.assertEqual(config._resolve_provider("auto"), "deepseek")
            self.assertEqual(config._resolve_provider("ollama"), "ollama")

    def test_ollama_base_url(self):
        with mock.patch.object(config, "OLLAMA_URL", "http://127.0.0.1:9999/api/generate"):
            self.assertEqual(config.ollama_base_url(), "http://127.0.0.1:9999")

    def test_deepseek_choices_are_unique(self):
        choices = config.deepseek_model_choices()
        self.assertEqual(len(choices), len(set(choices)))
        self.assertIn(config.DEEPSEEK_MODEL, choices)

    def test_model_choice_persists(self):
        root = _make_tmp_dir()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        path = root / "model_choice.json"
        with mock.patch.object(config, "MODEL_CHOICE_PATH", path), mock.patch.object(
            config, "DEEPSEEK_API_KEY", "sk-test"
        ):
            config.save_selection("deepseek", "deepseek-chat")
            self.assertEqual(
                config.load_saved_selection(), ("deepseek", "deepseek-chat")
            )
        with mock.patch.object(config, "MODEL_CHOICE_PATH", path), mock.patch.object(
            config, "DEEPSEEK_API_KEY", ""
        ):
            self.assertIsNone(config.load_saved_selection())


class HistoryTest(unittest.TestCase):
    def test_labels_and_limit(self):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "how are you"},
        ]
        text = conversation.format_history(
            history, limit=2, assistant_label="Examiner", user_label="Candidate"
        )
        self.assertEqual(text, "Examiner: hello\nCandidate: how are you")


class MemoryTest(unittest.TestCase):
    """娱乐角色的长期记忆：只增不减、反复提到就固化、永久不淡忘。"""

    def setUp(self):
        self.root = _make_tmp_dir()
        self._patch = mock.patch.object(
            memory, "MEMORY_PATH", self.root / "memories.json"
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, payload, message="今天好累", reply="辛苦了"):
        with mock.patch.object(memory, "call_llm_json", return_value=payload):
            return memory.update_memory("catgirl", message, reply, "猫娘")

    def test_new_fact_is_saved(self):
        self._run({"summary": "用户最近很累", "new_facts": ["用户在准备考试"]})
        data = memory.load_memory("catgirl")
        self.assertEqual([f["text"] for f in data["facts"]], ["用户在准备考试"])
        self.assertFalse(data["facts"][0]["permanent"])
        self.assertEqual(data["summary"], "用户最近很累")

    def test_repeated_fact_becomes_permanent_after_three_turns(self):
        payload = {"new_facts": ["用户养了一只叫团子的猫"]}
        for _ in range(3):
            self._run(payload)
        fact = memory.load_memory("catgirl")["facts"][0]
        self.assertEqual(fact["count"], 3)
        self.assertTrue(fact["permanent"])

    def test_explicit_stress_pins_fact_immediately(self):
        self._run(
            {"new_facts": ["用户对猫毛过敏"]},
            message="记住，我对猫毛过敏，别再问了",
        )
        self.assertTrue(memory.load_memory("catgirl")["facts"][0]["permanent"])

    def test_direct_remember_writes_personal_fact(self):
        self.assertTrue(memory.remember("tutor", "老师叫Vicente"))
        facts = memory.load_memory("tutor")["facts"]
        self.assertEqual([fact["text"] for fact in facts], ["老师叫Vicente"])
        self.assertTrue(facts[0]["permanent"])

    def test_repeated_index_bumps_count(self):
        self._run({"new_facts": ["用户住在杭州"]})
        self._run({"repeated": [1]})
        fact = memory.load_memory("catgirl")["facts"][0]
        self.assertEqual(fact["count"], 2)
        self.assertEqual(fact["text"], "用户住在杭州")

    def test_v1_string_facts_become_permanent(self):
        path = self.root / "memories.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "personas": {
                        "catgirl": {"summary": "旧画像", "facts": ["用户喜欢猫", "用户是学生"]}
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        data = memory.load_memory("catgirl")
        self.assertEqual(len(data["facts"]), 2)
        self.assertTrue(all(fact["permanent"] for fact in data["facts"]))
        self.assertEqual(data["summary"], "旧画像")

    def test_stale_one_off_fact_decays_but_permanent_survives(self):
        old = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        path = self.root / "memories.json"
        path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "personas": {
                        "catgirl": {
                            "summary": "",
                            "facts": [
                                {"text": "用户去年去过冰岛", "count": 1, "first": old, "last": old, "permanent": False},
                                {"text": "用户的名字是阿岚", "count": 1, "first": old, "last": old, "permanent": True},
                                {"text": "用户喜欢雨天", "count": 2, "first": old, "last": old, "permanent": False},
                            ],
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._run({"summary": "用户最近在准备考试"})
        texts = [fact["text"] for fact in memory.load_memory("catgirl")["facts"]]
        self.assertNotIn("用户去年去过冰岛", texts)
        self.assertIn("用户的名字是阿岚", texts)
        self.assertIn("用户喜欢雨天", texts)

    def test_memory_text_puts_permanent_first(self):
        self._run(
            {"new_facts": ["用户住在杭州"], "stress": True},
            message="记住我住在杭州",
        )
        self._run({"new_facts": ["用户喜欢咖啡"]})
        text = memory.memory_text("catgirl")
        self.assertIn("PERMANENT FACTS", text)
        self.assertLess(text.index("PERMANENT FACTS"), text.index("用户喜欢咖啡"))

    def test_pin_and_delete(self):
        self._run({"new_facts": ["用户养了一只猫"]})
        self.assertTrue(memory.set_permanent("catgirl", "用户养了一只猫", True))
        self.assertTrue(memory.load_memory("catgirl")["facts"][0]["permanent"])
        self.assertTrue(memory.set_permanent("catgirl", "用户养了一只猫", False))
        self.assertFalse(memory.load_memory("catgirl")["facts"][0]["permanent"])
        self.assertEqual(memory.load_memory("catgirl")["facts"][0]["count"], 0)
        self.assertTrue(memory.delete_fact("catgirl", "用户养了一只猫"))
        self.assertEqual(memory.load_memory("catgirl")["facts"], [])

    def test_legacy_unpinned_count_is_reset_on_load(self):
        memory._save_all(
            {
                "catgirl": {
                    "summary": "",
                    "facts": [
                        {
                            "text": "用户喜欢猫",
                            "count": 3,
                            "permanent": False,
                            "first": "2026-01-01 00:00:00",
                            "last": "2026-10-01 00:00:00",
                        }
                    ],
                    "updated_at": "",
                }
            }
        )
        fact = memory.load_memory("catgirl")["facts"][0]
        self.assertFalse(fact["permanent"])
        self.assertEqual(fact["count"], 0)

    def test_llm_failure_keeps_old_memory(self):
        self._run({"new_facts": ["用户住在杭州"]})
        with mock.patch.object(memory, "call_llm_json", side_effect=RuntimeError("boom")):
            memory.update_memory("catgirl", "你好", "你好呀", "猫娘")
        texts = [fact["text"] for fact in memory.load_memory("catgirl")["facts"]]
        self.assertEqual(texts, ["用户住在杭州"])

    def test_provider_and_model_are_forwarded(self):
        with mock.patch.object(
            memory, "call_llm_json", return_value={"new_facts": ["用户喜欢猫"]}
        ) as call:
            memory.update_memory(
                "catgirl",
                "hi",
                "hello",
                "猫娘",
                provider="ollama",
                model="qwen2.5:7b",
            )
        self.assertEqual(call.call_args.kwargs["provider"], "ollama")
        self.assertEqual(call.call_args.kwargs["model"], "qwen2.5:7b")

    def test_merge_matches_repeats_by_text_not_index(self):
        stamp = memory._now()
        facts = [memory._new_fact("用户住在杭州", stamp=stamp)]
        merged = memory._merge(
            facts,
            new_texts=[],
            repeated_texts=["用户住在杭州"],
            permanent_texts=[],
            stress=True,
        )
        self.assertEqual(merged[0]["count"], 2)
        self.assertTrue(merged[0]["permanent"])


class LoadJsonTest(unittest.TestCase):
    """统一读取入口：坏文件不能让页面崩，也不能悄悄丢数据。"""

    def setUp(self):
        self.root = _make_tmp_dir()
        self.path = self.root / "data.json"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_missing_file_returns_default(self):
        self.assertEqual(storage.load_json(self.path, {"a": 1}), {"a": 1})
        self.assertIsNone(storage.load_json(self.path))

    def test_corrupt_file_returns_default(self):
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(storage.load_json(self.path, []), [])

    def test_valid_file_round_trips(self):
        self.path.write_text('{"v": 2}', encoding="utf-8")
        self.assertEqual(storage.load_json(self.path, {}), {"v": 2})


class LLMParseTest(unittest.TestCase):
    """全站都依赖"模型返回畸形 JSON 时还能救回来"这个约定。"""

    def test_markdown_fence_is_stripped(self):
        self.assertEqual(llm._safe_json_loads('```json\n{"a": 1}\n```'), {"a": 1})

    def test_json_inside_chatter_is_found(self):
        self.assertEqual(llm._safe_json_loads('好的：\n{"a": 2}\n希望有帮助'), {"a": 2})

    def test_non_object_root_is_rejected(self):
        with self.assertRaises(ValueError):
            llm._safe_json_loads("[1, 2, 3]")

    def test_truncated_json_is_salvaged(self):
        salvaged = llm._salvage_partial_json('{"correction": "I went to the park and')
        self.assertEqual(salvaged, {"correction": "I went to the park and"})

    def test_retry_delay_prefers_server_hint_and_caps(self):
        response = mock.Mock(headers={"Retry-After": "3"})
        self.assertEqual(llm._retry_delay(response, 0), 3.0)
        response = mock.Mock(headers={"Retry-After": "999"})
        self.assertEqual(llm._retry_delay(response, 0), 10.0)
        self.assertEqual(llm._retry_delay(None, 1), 2.0)


class LLMRetryTest(unittest.TestCase):
    """429/5xx 才重试，401/400 立刻放弃；失败仍走 {_fallback: ...} 约定。"""

    def _ok(self, content='{"reply": "hi"}', usage=None):
        response = mock.Mock()
        response.status_code = 200
        response.headers = {}
        response.text = ""
        response.json.return_value = {
            "choices": [{"message": {"content": content}}],
            "usage": usage or {},
        }
        return response

    def _error(self, status, headers=None):
        response = mock.Mock()
        response.status_code = status
        response.headers = headers or {}
        response.text = "error"
        return response

    def _call(self, responses):
        with mock.patch.object(llm, "DEEPSEEK_API_KEY", "sk-test"), mock.patch.object(
            llm.requests, "post", side_effect=responses
        ) as post, mock.patch.object(llm.time, "sleep") as sleep:
            data = llm.call_llm(
                "prompt",
                temperature=0.1,
                num_predict=10,
                provider="deepseek",
                model="deepseek-flash",
            )
        return data, post, sleep

    def test_rate_limit_is_retried_then_succeeds(self):
        data, post, sleep = self._call(
            [self._error(429, {"Retry-After": "0"}), self._ok()]
        )
        self.assertEqual(data, {"reply": "hi"})
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_auth_error_is_not_retried(self):
        data, post, _ = self._call([self._error(401)])
        self.assertEqual(data, {})
        self.assertEqual(post.call_count, 1)

    def test_server_error_returns_empty_dict_without_fallback(self):
        data, post, sleep = self._call([self._error(503), self._error(503)])
        self.assertEqual(data, {})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_fallback_payload_is_returned_on_failure(self):
        with mock.patch.object(llm, "DEEPSEEK_API_KEY", "sk-test"), mock.patch.object(
            llm.requests, "post", side_effect=[self._error(401)]
        ):
            data = llm.call_llm(
                "prompt",
                temperature=0.1,
                num_predict=10,
                fallback={"correction": "兜底"},
                provider="deepseek",
                model="deepseek-flash",
            )
        self.assertEqual(data, {"_fallback": {"correction": "兜底"}})

    def test_token_usage_is_recorded(self):
        llm._USAGE_LOG.clear()
        data, _, _ = self._call(
            [
                self._ok(
                    usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "prompt_cache_hit_tokens": 4,
                    }
                )
            ]
        )
        self.assertEqual(data, {"reply": "hi"})
        entry = llm.usage_log()[-1]
        self.assertEqual(entry["prompt_tokens"], 10)
        self.assertEqual(entry["completion_tokens"], 5)
        self.assertEqual(entry["cache_hit"], 4)

    def test_worker_call_never_touches_session_state(self):
        """后台线程必须靠显式 provider/model；碰 session_state 就会拿到空值。"""
        with mock.patch.object(llm, "current_selection") as selection, mock.patch.object(
            llm, "DEEPSEEK_API_KEY", "sk-test"
        ), mock.patch.object(llm.requests, "post", return_value=self._ok()):
            data = llm.call_llm(
                "prompt",
                temperature=0.1,
                num_predict=10,
                provider="deepseek",
                model="deepseek-flash",
            )
        selection.assert_not_called()
        self.assertEqual(data, {"reply": "hi"})


class ThreadModelSelectionTest(unittest.TestCase):
    """Part 2 / 自由聊天：并发的模型调用必须沿用主线程选中的模型。"""

    def test_part2_passes_selection_into_workers(self):
        with mock.patch.object(
            Part2, "current_selection", return_value=("ollama", "qwen2.5:7b")
        ), mock.patch.object(
            Part2,
            "ask_feedback_agent",
            return_value={"correction": "原文 → 改为…", "suggestion": ""},
        ) as feedback, mock.patch.object(
            Part2, "ask_model_agent", return_value="model answer"
        ) as model, mock.patch.object(
            Part2, "ask_upgrade_agent", return_value="revised"
        ) as upgrade:
            result = Part2.evaluate_part2_story("I went there yesterday.", "Describe a place")

        self.assertEqual(result["model_answer"], "model answer")
        self.assertEqual(feedback.call_args.kwargs["provider"], "ollama")
        self.assertEqual(feedback.call_args.kwargs["model"], "qwen2.5:7b")
        self.assertEqual(model.call_args.kwargs["provider"], "ollama")
        self.assertEqual(model.call_args.kwargs["model"], "qwen2.5:7b")
        self.assertEqual(upgrade.call_args.kwargs["provider"], "ollama")
        self.assertEqual(upgrade.call_args.kwargs["model"], "qwen2.5:7b")

    def test_freetalk_passes_selection_into_workers(self):
        from utils import FreeTalk as freetalk

        with mock.patch.object(
            freetalk, "current_selection", return_value=("ollama", "qwen2.5:7b")
        ), mock.patch.object(
            freetalk, "ask_friend_agent", return_value="Hey!"
        ) as friend, mock.patch.object(
            freetalk,
            "ask_feedback_agent",
            return_value={"correction": "", "suggestion": "", "model_answer": ""},
        ) as feedback, mock.patch.object(
            freetalk, "speak", return_value=None
        ):
            freetalk.get_freetalk_answer(
                "hello", [{"role": "user", "content": "hello"}], "persona"
            )

        self.assertEqual(friend.call_args.kwargs["provider"], "ollama")
        self.assertEqual(friend.call_args.kwargs["model"], "qwen2.5:7b")
        self.assertEqual(feedback.call_args.kwargs["provider"], "ollama")
        self.assertEqual(feedback.call_args.kwargs["model"], "qwen2.5:7b")


class AudioFilesTest(unittest.TestCase):
    """语音文件保留今天和昨天、空文件不交给播放器、失败不留残片。"""

    def setUp(self):
        self.root = _make_tmp_dir()
        self.audio = self.root / "audio"
        self.audio.mkdir()
        self.patches = [
            mock.patch.object(tts, "AUDIO_DIR", self.audio),
            mock.patch.object(tts, "_PRUNE_DAY", None),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in self.patches:
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _file_days_ago(self, name: str, days: int) -> Path:
        path = self.audio / name
        path.write_bytes(b"x")
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def _old_file(self, name: str) -> Path:
        return self._file_days_ago(name, 3)

    def test_prune_keeps_today_and_yesterday(self):
        older = self._file_days_ago("older.mp3", 2)
        yesterday = self._file_days_ago("yesterday.mp3", 1)
        today = self._file_days_ago("today.mp3", 0)

        self.assertEqual(tts._prune_old_audio(), 1)
        self.assertFalse(older.exists())
        self.assertTrue(yesterday.exists())
        self.assertTrue(today.exists())

    def test_prune_runs_once_per_process_day(self):
        tts._prune_old_audio()
        old = self._old_file("late.mp3")
        self.assertEqual(tts._prune_old_audio(), 0)
        self.assertTrue(old.exists())

    def test_existing_audio_rejects_empty_and_missing(self):
        empty = self.audio / "empty.mp3"
        empty.write_bytes(b"")
        self.assertIsNone(tts.existing_audio(str(empty)))
        self.assertIsNone(tts.existing_audio(str(self.audio / "missing.mp3")))
        self.assertIsNone(tts.existing_audio(None))

        good = self.audio / "good.mp3"
        good.write_bytes(b"abc")
        self.assertEqual(tts.existing_audio(str(good)), str(good))

    def test_failed_synthesis_removes_partial_file(self):
        target = self.audio / "partial.mp3"
        target.write_bytes(b"half")
        with mock.patch.object(
            tts.asyncio, "run", side_effect=RuntimeError("boom")
        ), mock.patch.object(tts, "new_audio_path", return_value=str(target)):
            self.assertIsNone(tts.speak("hello"))
        self.assertFalse(target.exists())


class LearnerProfileTest(unittest.TestCase):
    """交给 AI 老师的学习档案：有数据就带上下文，没数据就留空。"""

    def setUp(self):
        self.patches = [
            mock.patch.object(
                learner_profile,
                "load_progress",
                return_value={"words": {"abandon": {"reps": 1, "lapses": 2, "due": "2026-01-01"}}},
            ),
            mock.patch.object(
                learner_profile,
                "word_stats",
                return_value={"learned": 12, "due": 4, "new_today": 5, "review_today": 3},
            ),
            mock.patch.object(learner_profile, "target_plan", return_value={}),
            mock.patch.object(
                learner_profile,
                "word_by_id",
                side_effect=lambda word_id: {
                    "w": "abandon",
                    "senses": [{"pos": "v.", "zh": "放弃"}],
                }
                if word_id == "abandon"
                else None,
            ),
            mock.patch.object(
                learner_profile,
                "load_entries",
                return_value=[
                    {
                        "term": "take for granted",
                        "meaning": "phr. 认为理所当然",
                        "tags": ["口语"],
                        "created_at": "2026-10-28 10:00:00",
                    }
                ],
            ),
            mock.patch.object(
                learner_profile,
                "load_expressions",
                return_value=[
                    {
                        "intent": "我完全理解",
                        "natural": "I totally get it",
                        "created_at": "2026-10-28 11:00:00",
                    }
                ],
            ),
            mock.patch.object(
                learner_profile, "expression_stats", return_value={"total": 1, "due": 1}
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in self.patches:
            patcher.stop()

    def test_profile_contains_progress_words_and_expressions(self):
        text = learner_profile.build_profile()
        self.assertIn("待复习 4", text)
        self.assertIn("abandon", text)
        self.assertIn("take for granted", text)
        self.assertIn("I totally get it", text)

    def test_counts_match_the_data(self):
        info = learner_profile.counts()
        self.assertEqual(info, {
            "learned": 12,
            "due": 4,
            "notes": 1,
            "expressions": 1,
            "expression_due": 1,
        })


class TutorProfileTest(unittest.TestCase):
    """学习档案不再注入老师 prompt；备课本是唯一的数据通道。"""

    def _ask(self, profile: str):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {"reply": "ok"}

        with mock.patch.object(tutor_mod, "call_llm_json", side_effect=fake_llm):
            reply = tutor_mod.ask_tutor("帮我安排练习", [], profile=profile)
        return reply, captured.get("prompt", "")

    def test_profile_is_not_injected(self):
        reply, prompt = self._ask("VOCABULARY\n- 已学 12 个词")
        self.assertEqual(reply, "ok")
        self.assertNotIn("已学 12 个词", prompt)
        self.assertNotIn("LEARNER PROFILE", prompt)
        self.assertNotIn("__PROFILE__", prompt)

    def test_empty_profile_marks_none(self):
        _, prompt = self._ask("")
        self.assertIn("(none)", prompt)


class PracticePromptTest(unittest.TestCase):
    """出题和评估的 prompt 里要带上练习点，评估结果要归一化。"""

    def test_question_prompt_contains_targets(self):
        captured = {}

        def fake_llm(prompt, **_kwargs):
            captured["prompt"] = prompt
            return {
                "question": "Tell me about a trip.",
                "model_answer": "Last year I took a trip to the coast.",
            }

        targets = [{"label": "abandon（放弃）", "kind": "word", "strength": 1}]
        with mock.patch.object(tutor_mod, "call_llm_json", side_effect=fake_llm):
            asked = tutor_mod.ask_practice_question(targets, profile="")
        self.assertEqual(asked["question"], "Tell me about a trip.")
        self.assertEqual(
            asked["model_answer"], "Last year I took a trip to the coast."
        )
        self.assertIn("abandon（放弃）", captured["prompt"])
        self.assertIn("model_answer", captured["prompt"])

    def test_practice_question_wrapper_accepts_plain_string(self):
        targets = [{"label": "abandon（放弃）"}]
        with mock.patch.object(
            tutor_mod, "call_llm_json", return_value="Tell me about a trip."
        ):
            asked = tutor_mod.ask_practice_question(targets)
        self.assertEqual(asked["question"], "Tell me about a trip.")
        self.assertEqual(asked["model_answer"], "")

    def test_assessment_is_normalised(self):
        payload = {
            "assessments": [
                {"index": 1, "result": "GOOD", "note": "不错"},
                {"index": 2, "result": "nonsense"},
            ],
            "new_issues": "漏冠词；时态混用",
            "feedback": "总体不错。",
        }
        with mock.patch.object(tutor_mod, "call_llm_json", return_value=payload):
            data = tutor_mod.assess_practice_answer("Q", "A", [{"label": "X"}])
        self.assertEqual(len(data["assessments"]), 1)
        self.assertEqual(data["assessments"][0]["result"], "good")
        self.assertEqual(data["new_issues"], ["漏冠词", "时态混用"])


class VocabularyLookupTest(unittest.TestCase):
    """查词前先确认是正常英语；表情符号走闲聊，拼写错误先反问。"""

    def test_emoticon_is_casual_chat_not_lookup(self):
        payload = {"needs_clarification": True, "kind": "not_english"}
        with mock.patch.object(
            tutor_mod, "call_llm_json", return_value=payload
        ) as fake:
            data = tutor_mod.explain_vocabulary("qwq")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["clarify"], "")
        self.assertEqual(data["clarify_kind"], "not_english")
        prompt = fake.call_args.args[0]
        self.assertIn("STEP 0", prompt)
        self.assertIn("kaomoji", prompt)

    def test_misspelling_asks_before_explaining(self):
        payload = {
            "needs_clarification": True,
            "kind": "misspelling",
            "question": "你是想问 personal 吗？",
            "suggestions": ["personal"],
        }
        with mock.patch.object(tutor_mod, "call_llm_json", return_value=payload):
            data = tutor_mod.explain_vocabulary("personnal")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["clarify_kind"], "misspelling")
        self.assertIn("personal", data["clarify"])

    def test_confirmation_without_question_names_the_suggestions(self):
        payload = {"needs_clarification": True, "suggestions": ["personal"]}
        with mock.patch.object(tutor_mod, "call_llm_json", return_value=payload):
            data = tutor_mod.explain_vocabulary("personnal")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["clarify_kind"], "misspelling")
        self.assertIn("personal", data["clarify"])

    def test_real_word_still_gets_explained(self):
        payload = {
            "intro": "好。",
            "items": [{"text": "abandon", "type": "word", "meaning": "放弃"}],
        }
        with mock.patch.object(tutor_mod, "call_llm_json", return_value=payload):
            data = tutor_mod.explain_vocabulary("abandon")
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["clarify"], "")
        self.assertEqual(data["clarify_kind"], "")


class QuickLookupTest(unittest.TestCase):
    """随手查：判中英文、清洗返回、失败兜底。"""

    def test_language_detection(self):
        self.assertTrue(quick_lookup.is_chinese("这个用英语怎么说"))
        self.assertTrue(quick_lookup.is_chinese("I'm fine 谢谢"))
        self.assertFalse(quick_lookup.is_chinese("I'm fine, thanks"))

    def test_type_inference(self):
        self.assertEqual(quick_lookup._infer_type("hello"), "word")
        self.assertEqual(quick_lookup._infer_type("take off"), "phrase")
        self.assertEqual(quick_lookup._infer_type("I went home."), "sentence")

    def test_save_mode(self):
        self.assertEqual(quick_lookup.save_mode("hello"), "word")
        self.assertEqual(quick_lookup.save_mode("well-known"), "word")
        self.assertEqual(quick_lookup.save_mode("  hello  "), "word")
        self.assertEqual(quick_lookup.save_mode("take off"), "both")
        self.assertEqual(quick_lookup.save_mode("I went home"), "both")
        self.assertEqual(quick_lookup.save_mode("Hello."), "sentence")
        self.assertEqual(quick_lookup.save_mode("How are you?"), "sentence")
        self.assertEqual(quick_lookup.save_mode("Wait!"), "sentence")

    def test_strip_pos(self):
        self.assertEqual(quick_lookup.strip_pos("phr. 跑过来蹭脸颊"), "跑过来蹭脸颊")
        self.assertEqual(quick_lookup.strip_pos("n. 书；v. 预订"), "书；预订")
        self.assertEqual(quick_lookup.strip_pos("adj. 开心的/高兴的"), "开心的/高兴的")
        self.assertEqual(quick_lookup.strip_pos("书；预订"), "书；预订")

    def test_english_input_returns_translation(self):
        with mock.patch.object(
            quick_lookup,
            "call_llm_json",
            return_value={
                "translation": "你好",
                "type": "word",
                "example": "She said hello to everyone.",
                "example_zh": "她向所有人打了招呼。",
            },
        ), mock.patch("utils.Notebook.analyze_term", return_value={}):
            result = quick_lookup.lookup("hello")
        self.assertEqual(result["mode"], "en")
        self.assertEqual(result["translation"], "你好")
        self.assertEqual(result["source_type"], "word")
        self.assertEqual(result["save_mode"], "word")
        self.assertEqual(result["example"], "She said hello to everyone.")
        self.assertEqual(result["example_zh"], "她向所有人打了招呼。")
        self.assertEqual(result["options"], [])

    def test_sentence_query_only_translates(self):
        with mock.patch("utils.Notebook.analyze_term") as analyze, mock.patch.object(
            quick_lookup,
            "call_llm_json",
            return_value={
                "translation": "我回家了。",
                "type": "sentence",
                "example": "",
                "example_zh": "",
            },
        ):
            result = quick_lookup.lookup("I went home.")
        analyze.assert_not_called()
        self.assertEqual(result["save_mode"], "sentence")
        self.assertEqual(result["translation"], "我回家了。")
        self.assertFalse(result["example_zh_error"])

    def test_phrase_query_uses_notebook_senses(self):
        meta = {
            "senses": [
                {"pos": "v.", "meaning": "起飞", "example": "The plane took off."},
                {"pos": "v.", "meaning": "脱下", "example": "He took off his coat."},
            ],
            "meaning": "v. 起飞；脱下",
            "example": "The plane took off.",
            "tags": ["旅行"],
            "group": "旅行经历",
        }
        with mock.patch(
            "utils.Notebook.analyze_term", return_value=meta
        ) as analyze, mock.patch.object(
            quick_lookup, "_translate_examples", return_value=["飞机起飞了。", "他脱下了外套。"]
        ):
            result = quick_lookup.lookup("take off")
        analyze.assert_called_once_with("take off")
        self.assertEqual(result["save_mode"], "both")
        self.assertEqual(len(result["senses"]), 2)

    def test_chinese_options_get_save_mode(self):
        payload = {
            "translation": "Understood.",
            "options": [
                {"en": "understood", "zh": "明白了", "type": "sentence", "note": ""},
                {"en": "I totally get it.", "zh": "我完全理解", "type": "phrase", "note": ""},
                {"en": "fair enough", "zh": "有道理", "type": "phrase", "note": ""},
            ],
        }
        with mock.patch.object(quick_lookup, "call_llm_json", return_value=payload):
            result = quick_lookup.lookup("我明白了")
        modes = {option["en"]: option["save_mode"] for option in result["options"]}
        self.assertEqual(modes["understood"], "word")
        self.assertEqual(modes["I totally get it."], "sentence")
        self.assertEqual(modes["fair enough"], "both")

    def test_english_word_uses_notebook_senses(self):
        meta = {
            "senses": [
                {"pos": "n.", "meaning": "书", "example": "I read a book."},
                {"pos": "v.", "meaning": "预订", "example": "I booked a table."},
            ],
            "meaning": "n. 书；v. 预订",
            "example": "I read a book.",
            "tags": ["教育", "生活"],
            "group": "日常物品",
        }
        with mock.patch(
            "utils.Notebook.analyze_term", return_value=meta
        ), mock.patch.object(
            quick_lookup,
            "_translate_examples",
            return_value=["我读了一本书。", "我订了一张两人桌。"],
        ):
            result = quick_lookup.lookup("book")
        self.assertEqual(result["translation"], "n. 书；v. 预订")
        self.assertEqual(result["save_mode"], "word")
        self.assertEqual(len(result["senses"]), 2)
        self.assertEqual(result["senses"][0]["example_zh"], "我读了一本书。")
        self.assertEqual(result["senses"][1]["example_zh"], "我订了一张两人桌。")
        # 查询时的标签 / 分组也要跟着结果走，保存时直接复用。
        self.assertEqual(result["analysis"]["tags"], ["教育", "生活"])
        self.assertEqual(result["analysis"]["group"], "日常物品")

    def test_example_zh_failure_is_marked(self):
        meta = {
            "senses": [{"pos": "n.", "meaning": "书", "example": "I read a book."}],
            "meaning": "n. 书",
            "example": "I read a book.",
        }
        with mock.patch(
            "utils.Notebook.analyze_term", return_value=meta
        ), mock.patch.object(quick_lookup, "_translate_examples", return_value=[""]):
            result = quick_lookup.lookup("book")
        self.assertTrue(result["example_zh_error"])
        self.assertEqual(result["senses"][0]["example_zh"], "")

    def test_fallback_translation_marks_missing_example_zh(self):
        with mock.patch.object(
            quick_lookup,
            "call_llm_json",
            return_value={
                "translation": "你好",
                "type": "word",
                "example": "Hello there.",
                "example_zh": "",
            },
        ), mock.patch("utils.Notebook.analyze_term", return_value={}):
            result = quick_lookup.lookup("hello")
        self.assertTrue(result["example_zh_error"])

    def test_example_zh_failure_is_not_cached(self):
        cache = {}
        failed = {
            "translation": "n. 书",
            "options": [],
            "error": "",
            "example_zh_error": True,
        }
        with mock.patch.object(
            quick_lookup, "lookup", return_value=failed
        ) as lookup:
            quick_lookup.lookup_cached("book", cache)
            quick_lookup.lookup_cached("book", cache)
        self.assertEqual(lookup.call_count, 2)

    def test_chinese_input_cleans_options(self):
        payload = {
            "translation": "I completely understand.",
            "options": [
                {"en": "I totally get it.", "zh": "我完全理解", "type": "sentence", "note": "口语"},
                {"en": "I totally get it.", "zh": "重复的", "type": "sentence", "note": ""},
                "That makes sense to me.",
                {"en": "  ", "zh": "空的", "type": "word", "note": ""},
                {"en": "I see where you're coming from.", "zh": "我理解你的处境", "type": "phrase", "note": "更委婉"},
                {"en": "Fair enough.", "zh": "有道理", "type": "phrase", "note": "简短"},
                {"en": "Understood.", "zh": "明白", "type": "word", "note": "超出上限"},
            ],
        }
        with mock.patch.object(quick_lookup, "call_llm_json", return_value=payload):
            result = quick_lookup.lookup("我完全理解")
        self.assertEqual(result["mode"], "cn")
        texts = [option["en"] for option in result["options"]]
        self.assertEqual(texts[0], "I totally get it.")
        self.assertEqual(len(texts), 5)
        self.assertEqual(len(texts), len(set(texts)))
        self.assertEqual(result["options"][0]["type"], "sentence")
        self.assertEqual(result["options"][0]["zh"], "我完全理解")

    def test_empty_and_failure(self):
        self.assertEqual(quick_lookup.lookup("   ")["error"], "先输入点内容")
        with mock.patch.object(
            quick_lookup, "call_llm_json", return_value={}
        ), mock.patch("utils.Notebook.analyze_term", return_value={}):
            result = quick_lookup.lookup("hello")
        self.assertEqual(result["translation"], "")
        self.assertTrue(result["error"])

    def test_lookup_cached_reuses_success_only(self):
        cache = {}
        success = {"translation": "你好", "options": [], "error": ""}
        with mock.patch.object(
            quick_lookup, "lookup", return_value=success
        ) as lookup:
            first = quick_lookup.lookup_cached(" Hello ", cache)
            second = quick_lookup.lookup_cached("hello", cache)
        self.assertIs(first, second)
        self.assertEqual(lookup.call_count, 1)

        failed = {"translation": "", "options": [], "error": "没接上"}
        with mock.patch.object(
            quick_lookup, "lookup", return_value=failed
        ) as lookup:
            quick_lookup.lookup_cached("missing", cache)
            quick_lookup.lookup_cached("missing", cache)
        self.assertEqual(lookup.call_count, 2, "失败结果不能进缓存")


class NotebookAnalysisReuseTest(unittest.TestCase):
    """随手查保存：直接落查询时的分析，不能再调一次模型。"""

    def setUp(self):
        self.root = _make_tmp_dir()
        self.patcher = mock.patch.object(
            Notebook, "NOTEBOOK_PATH", self.root / "notebook.json"
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_add_entry_reuses_analysis(self):
        analysis = {
            "senses": [
                {"pos": "n.", "meaning": "书", "example": "I read a book."},
                {"pos": "v.", "meaning": "预订", "example": "I booked a table."},
            ],
            "meaning": "n. 书；v. 预订",
            "tags": ["教育", "生活"],
            "group": "日常物品",
        }
        with mock.patch.object(Notebook, "_enrich") as enrich:
            entry = Notebook.add_entry("book", source="随手查", analysis=analysis)
            enrich.assert_not_called()

        self.assertEqual(entry["term"], "book")
        self.assertEqual(entry["meaning"], "n. 书；v. 预订")
        self.assertEqual(
            [sense["meaning"] for sense in entry["senses"]], ["书", "预订"]
        )
        self.assertEqual(entry["example"], "I read a book.")
        self.assertEqual(entry["tags"], ["教育", "生活"])
        self.assertEqual(entry["group"], "日常物品")


class ExpressionMineRemovalTest(unittest.TestCase):
    """表达库不再保存“我当时的说法”。"""

    def setUp(self):
        self.root = _make_tmp_dir()
        self.path = self.root / "expressions.json"
        self.patcher = mock.patch.object(Expressions, "EXPRESSIONS_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_new_expression_has_no_mine(self):
        entry = Expressions.add_expression("我能听清", "I can hear you very clearly")
        self.assertNotIn("mine", entry)
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("mine", stored["entries"][0])

    def test_legacy_mine_is_dropped_on_load(self):
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        {
                            "id": "legacy",
                            "intent": "我能听清",
                            "natural": "I can hear you very clearly",
                            "mine": "It's perfectly clear.",
                            "scene": "",
                            "source": "严肃话题",
                            "created_at": "2026-10-20 10:00:00",
                            "updated_at": "2026-10-20 10:00:00",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        entries = Expressions.load_expressions()
        self.assertEqual(len(entries), 1)
        self.assertNotIn("mine", entries[0])


class PlanJudgeEvidenceTest(unittest.TestCase):
    def test_student_evidence_accepts_inflections(self):
        self.assertTrue(
            PlanJudge.has_student_evidence(
                "word:irritation", "irritation（n. 恼怒）", "I felt irritated."
            )
        )
        self.assertTrue(
            PlanJudge.has_student_evidence(
                "word:rally", "rally（n. 集会）", "A rally took shape."
            )
        )

    def test_student_evidence_rejects_teacher_only_mention(self):
        self.assertFalse(
            PlanJudge.has_student_evidence(
                "word:irritation", "irritation（n. 恼怒）", "I talked about rally."
            )
        )

    def test_judge_message_requires_student_evidence(self):
        pending = [{"source_key": "word:irritation", "label": "irritation（n. 恼怒）"}]
        payload = {
            "active_source_keys": ["word:irritation"],
            "completed": [
                {"source_key": "word:irritation", "evidence": "老师说可以收了"}
            ],
            "reason": "老师接受了",
        }
        with mock.patch.object(
            PlanJudge, "call_llm_json", return_value=payload
        ):
            result = PlanJudge.judge_message(
                "用上 irritation 说说烦心事",
                "rally 那段可以收了",
                pending,
                user_message="I talked about rally.",
            )
        self.assertEqual(result["completed"], [])

    def test_force_check_requires_student_evidence(self):
        messages = [
            {"role": "assistant", "content": "用上 irritation 说说烦心事"},
            {"role": "user", "content": "I talked about rally."},
        ]
        pending = [{"source_key": "word:irritation", "label": "irritation（n. 恼怒）"}]
        payload = {
            "completed": [
                {"source_key": "word:irritation", "evidence": "老师说可以收了"}
            ],
            "reason": "老师接受了",
        }
        with mock.patch.object(
            PlanJudge, "call_llm_json", return_value=payload
        ):
            result = PlanJudge.judge_conversation(messages, pending)
        self.assertEqual(result["completed"], [])


class EntertainmentTest(unittest.TestCase):
    """中文回复只走一次调用；后台记忆拿到显式的 provider/model。"""

    def test_is_chinese(self):
        self.assertTrue(entertainment.is_chinese("我今天很累"))
        self.assertTrue(entertainment.is_chinese("I'm fine 谢谢"))
        self.assertFalse(entertainment.is_chinese("ok, sure"))
        self.assertFalse(entertainment.is_chinese(""))

    def test_bilingual_reply_uses_one_call(self):
        with mock.patch.object(
            entertainment,
            "call_llm_json",
            return_value={"reply": "Hey", "reply_zh": "嘿"},
        ) as call:
            english, final = entertainment.ask_entertainment_agent(
                "你好", "User: hi", "persona", bilingual=True
            )
        self.assertEqual(call.call_count, 1)
        self.assertEqual(english, "Hey")
        self.assertEqual(final, "嘿")
        self.assertIn("reply_zh", call.call_args.args[0])
        self.assertIn("not a literal translation", call.call_args.args[0])

    def test_english_reply_does_not_ask_for_translation(self):
        with mock.patch.object(
            entertainment, "call_llm_json", return_value={"reply": "Hey"}
        ) as call:
            english, final = entertainment.ask_entertainment_agent(
                "hello", "User: hi", "persona", bilingual=False
            )
        self.assertNotIn("reply_zh", call.call_args.args[0])
        self.assertEqual((english, final), ("Hey", "Hey"))

    def test_rewrite_zh_restates_instead_of_translating(self):
        with mock.patch.object(
            entertainment,
            "call_llm_json",
            return_value={"reply": "Hey", "reply_zh": "嘿"},
        ) as call:
            entertainment.ask_entertainment_agent(
                "你好", "User: hi", "persona", bilingual=True, rewrite_zh=True
            )
        prompt = call.call_args.args[0]
        self.assertIn("Do NOT translate", prompt)
        self.assertIn("as if Chinese were the language", prompt)
        self.assertIn("the way people talk", prompt)
        self.assertNotIn("Simplified Chinese version of the same reply", prompt)

    def test_answer_forwards_rewrite_zh(self):
        with mock.patch.object(
            entertainment, "ask_entertainment_agent", return_value=("en", "zh")
        ) as agent, mock.patch.object(
            entertainment, "memory_text", return_value=""
        ), mock.patch.object(
            entertainment, "speak", return_value=None
        ), mock.patch.object(
            entertainment, "current_selection", return_value=("p", "m")
        ):
            entertainment.get_entertainment_answer(
                "你好", [], "persona", rewrite_zh=True
            )
        self.assertTrue(agent.call_args.kwargs["rewrite_zh"])

    def test_missing_translation_falls_back_to_english(self):
        with mock.patch.object(
            entertainment, "call_llm_json", return_value={"reply": "Hey"}
        ):
            _, final = entertainment.ask_entertainment_agent(
                "你好", "", "persona", bilingual=True
            )
        self.assertEqual(final, "Hey")

    def test_background_jobs_get_explicit_model(self):
        history = [{"role": "user", "content": "hi"}]
        with mock.patch.object(
            entertainment, "call_llm_json", return_value={"reply": "Hello"}
        ), mock.patch.object(
            entertainment, "memory_text", return_value=""
        ), mock.patch.object(
            entertainment, "current_selection", return_value=("ollama", "qwen2.5:7b")
        ), mock.patch.object(
            entertainment, "speak", return_value=None
        ), mock.patch.object(
            entertainment, "_run_in_background"
        ) as background:
            entertainment.get_entertainment_answer(
                "hello", history, "persona", memory_key="catgirl", memory_label="猫娘"
            )
        self.assertEqual(background.call_count, 1)
        self.assertEqual(background.call_args.kwargs["provider"], "ollama")
        self.assertEqual(background.call_args.kwargs["model"], "qwen2.5:7b")


    def test_intro_failure_uses_persona_fallback_and_speaks_it(self):
        with mock.patch.object(
            entertainment, "call_llm_json", return_value={}
        ), mock.patch.object(
            entertainment, "speak", return_value="voice.mp3"
        ) as speak:
            data, audio = entertainment.get_entertainment_answer(
                "", [], "persona", intro_fallback="Sit down, let's begin."
            )
        self.assertEqual(data["reply"], "Sit down, let's begin.")
        self.assertEqual(audio, "voice.mp3")
        self.assertEqual(speak.call_args.args[0], "Sit down, let's begin.")

    def test_intro_failure_without_fallback_is_empty(self):
        with mock.patch.object(
            entertainment, "call_llm_json", return_value={}
        ), mock.patch.object(entertainment, "speak") as speak:
            data, audio = entertainment.get_entertainment_answer("", [], "persona")
        self.assertEqual(data["reply"], "")
        self.assertIsNone(audio)
        speak.assert_not_called()


class ChatPageSpecTest(unittest.TestCase):
    def test_role_pages_restate_chinese_by_default(self):
        from utils.ChatPage import ChatPageSpec

        spec = ChatPageSpec(
            prefix="x",
            page_title="t",
            page_icon="i",
            heading="h",
            persona="p",
            voice="v",
            memory_key="k",
            memory_label="l",
            intro_fallback="f",
            spinner_intro="a",
            spinner_send="b",
        )
        self.assertTrue(spec.rewrite_zh)


class NotesTest(unittest.TestCase):
    def setUp(self):
        self.root = _make_tmp_dir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_transcript_is_trimmed(self):
        messages = [{"role": "user", "content": "x" * 1000} for _ in range(20)]
        lines = notes._transcript(messages).splitlines()
        self.assertEqual(len(lines), 12)
        self.assertLessEqual(len(lines[0]), 400)

    def test_note_requires_more_than_three_user_turns(self):
        self.assertFalse(notes.note_ready([]))
        self.assertFalse(
            notes.note_ready(
                [
                    {"role": "assistant", "content": "你好。"},
                    {"role": "user", "content": "第一句"},
                    {"role": "assistant", "content": "嗯。"},
                    {"role": "user", "content": "第二句"},
                ]
            )
        )
        # 3 条以内不写，第 4 条起才生成。
        self.assertFalse(
            notes.note_ready(
                [{"role": "user", "content": f"第{i}句"} for i in range(1, 4)]
            )
        )
        self.assertTrue(
            notes.note_ready(
                [{"role": "user", "content": f"第{i}句"} for i in range(1, 5)]
            )
        )

    def test_note_body_does_not_join_with_double_punctuation(self):
        body = notes._note_body_html(
            {
                "summary": "这次聊了论文。",
                "details": [],
                "next": ["先做 A。", "再做 B；", "最后 C"],
            },
            "mentor",
        )
        self.assertNotIn("。；", body)
        self.assertNotIn("；；", body)
        self.assertIn("先做 A；再做 B；最后 C。", body)

    def test_delete_note_removes_only_that_record(self):
        with mock.patch.object(
            notes, "NOTES_PATH", self.root / "session_notes.json"
        ):
            notes._save_all(
                {
                    "psychologist": {
                        "a": {"date": "2026-10-01", "summary": "A"},
                        "b": {"date": "2026-10-02", "summary": "B"},
                    }
                }
            )
            self.assertTrue(notes.delete_note("psychologist", "a"))
            self.assertFalse(notes.delete_note("psychologist", "a"))
            self.assertEqual(
                [note["id"] for note in notes.load_notes("psychologist")], ["b"]
            )

    def test_provider_is_forwarded(self):
        with mock.patch.object(
            notes, "NOTES_PATH", self.root / "session_notes.json"
        ), mock.patch.object(
            llm, "call_llm_json", return_value={"summary": "聊了考试"}
        ) as call:
            note = notes.update_session_note(
                "mentor",
                "n1",
                "2026-10-28",
                [{"role": "user", "content": "hi"}],
                provider="ollama",
                model="qwen2.5:7b",
            )
        self.assertIsNotNone(note)
        self.assertEqual(call.call_args.kwargs["provider"], "ollama")
        self.assertEqual(call.call_args.kwargs["model"], "qwen2.5:7b")


if __name__ == "__main__":
    unittest.main()
