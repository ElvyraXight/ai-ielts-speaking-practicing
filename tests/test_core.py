"""核心逻辑的回归测试（只用标准库，不依赖 pytest）。

跑法：python -m unittest discover -s tests -v
覆盖三块最容易"悄悄坏掉"的逻辑：落盘备份策略、Part 2 题卡/纠错清洗、背单词排期。
"""

import json
import shutil
import sys
import time
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import Memory as memory  # noqa: E402
from utils import Part2, WordAtlas, config, conversation, storage  # noqa: E402

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


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
        self.assertTrue(memory.delete_fact("catgirl", "用户养了一只猫"))
        self.assertEqual(memory.load_memory("catgirl")["facts"], [])

    def test_llm_failure_keeps_old_memory(self):
        self._run({"new_facts": ["用户住在杭州"]})
        with mock.patch.object(memory, "call_llm_json", side_effect=RuntimeError("boom")):
            memory.update_memory("catgirl", "你好", "你好呀", "猫娘")
        texts = [fact["text"] for fact in memory.load_memory("catgirl")["facts"]]
        self.assertEqual(texts, ["用户住在杭州"])


if __name__ == "__main__":
    unittest.main()
