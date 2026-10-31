"""Part 2 题卡落盘：刷新/重启后复用，只有主动换题才更新。"""

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

from utils import Part2Card  # noqa: E402


class Part2CardTest(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = _TMP_ROOT / f"p2card-{uuid.uuid4().hex[:8]}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.patchers = [
            mock.patch.object(Part2Card, "CARD_PATH", self.root / "part2_card.json"),
            mock.patch.object(Part2Card, "_session_get", return_value=""),
            mock.patch.object(Part2Card, "_session_set"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_save_and_load(self):
        card = "Describe a piece of technology you use every day."
        Part2Card.save(card)
        self.assertEqual(Part2Card.load(), card)

    def test_answer_is_saved_with_the_card(self):
        Part2Card.save("Card A")
        Part2Card.save_answer("My story")
        self.assertEqual(Part2Card.load_answer(), "My story")
        self.assertEqual(Part2Card.load(), "Card A")

    def test_new_card_keeps_the_answer_until_it_is_cleared(self):
        Part2Card.save("Card A")
        Part2Card.save_answer("My story")
        Part2Card.save("Card B")
        self.assertEqual(Part2Card.load_answer(), "My story")
        Part2Card.save_answer("")
        self.assertEqual(Part2Card.load_answer(), "")
        self.assertEqual(Part2Card.load(), "Card B")

    def test_get_or_create_reuses_saved_card(self):
        Part2Card.save("Saved card")
        calls = []

        def generator():
            calls.append(1)
            return "New card"

        self.assertEqual(Part2Card.get_or_create(generator), "Saved card")
        self.assertEqual(calls, [])

    def test_get_or_create_generates_and_saves(self):
        self.assertEqual(Part2Card.get_or_create(lambda: "New card"), "New card")
        self.assertEqual(Part2Card.load(), "New card")

    def test_session_card_is_persisted(self):
        with mock.patch.object(
            Part2Card, "_session_get", return_value="Session card"
        ):
            self.assertEqual(
                Part2Card.get_or_create(lambda: "New card"), "Session card"
            )
        self.assertEqual(Part2Card.load(), "Session card")
