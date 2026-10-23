#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线测试 TranslationNotes 解析和冲突判定。"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import translation_notes_sync as T  # noqa: E402


SAMPLE = """return {
items = {
  ['Lighter'] = {
    literal = '打火机',
    rationale = '采用最常见称呼。',
    alternatives = {'点火器', '火机'},
    status = '已确认',
    confirmed = '2026-09-22',
    discussion = '[[Help talk:翻译说明#Lighter]]',
    history = {'旧译名：火机'},
  },
},
entities = {
  ['Drone'] = {
    display = '空壳',
    literal = '无人飞行器',
    rationale = '结合外观和群体行为。',
    alternatives = {'无人飞行器'},
    status = '已确认',
    confirmed = '2026-09-22',
    discussion = '',
    history = {},
  },
},
}"""


class TranslationNotesTest(unittest.TestCase):
    def test_parse_notes(self) -> None:
        notes = T.parse_notes_module(SAMPLE)
        self.assertEqual([note.key for note in notes], ["Lighter", "Drone"])
        self.assertEqual(notes[0].alternatives, ("点火器", "火机"))
        self.assertEqual(notes[1].display, "空壳")

    def test_payload(self) -> None:
        notes = T.parse_notes_module(SAMPLE)
        payload = T.note_payload(notes[0])
        self.assertEqual(payload["reason"], "采用最常见称呼。")
        self.assertIn("字面含义：打火机", payload["note"])
        self.assertIn("历史记录：旧译名：火机", payload["note"])

    def test_initial_empty_external_is_synced(self) -> None:
        plan = T.plan_row({"reason": "x", "confirmed": "", "note": ""},
                          {"reason": "", "confirmed": "", "note": ""}, None)
        self.assertEqual(plan["status"], T.STATUS_SYNCED)
        self.assertTrue(plan["write"])

    def test_initial_external_difference_is_conflict(self) -> None:
        plan = T.plan_row({"reason": "x", "confirmed": "", "note": ""},
                          {"reason": "y", "confirmed": "", "note": ""}, None)
        self.assertEqual(plan["status"], T.STATUS_CONFLICT)
        self.assertFalse(plan["write"])

    def test_wiki_change_pushes(self) -> None:
        previous = {
            "wiki_hash": T.payload_hash({"reason": "old", "confirmed": "", "note": ""}),
            "external_hash": T.payload_hash({"reason": "old", "confirmed": "", "note": ""}),
            "conflict": False,
        }
        plan = T.plan_row({"reason": "new", "confirmed": "", "note": ""},
                          {"reason": "old", "confirmed": "", "note": ""}, previous)
        self.assertEqual(plan["status"], T.STATUS_SYNCED)
        self.assertTrue(plan["write"])

    def test_external_change_marks_conflict(self) -> None:
        previous = {
            "wiki_hash": T.payload_hash({"reason": "old", "confirmed": "", "note": ""}),
            "external_hash": T.payload_hash({"reason": "old", "confirmed": "", "note": ""}),
            "conflict": False,
        }
        plan = T.plan_row({"reason": "old", "confirmed": "", "note": ""},
                          {"reason": "external", "confirmed": "", "note": ""},
                          previous)
        self.assertEqual(plan["status"], T.STATUS_CONFLICT)
        self.assertFalse(plan["write"])


if __name__ == "__main__":
    unittest.main()
