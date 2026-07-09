"""
Tests for Feature 4 (2026-07-09):
  - Conclusion extraction (deterministic, no LLM fallback)
  - Minority report (chair prompt four-section format)
  - public_view conclusion exposure
  - conclusion self-id filtering
  - mock end-to-end conclusion flow
"""
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapters
import anonymizer
import parliament


# ── helpers ──────────────────────────────────────────────────────────────────

_THREE_CFG = {
    "members": [
        {"id": "claude",  "model_display": "Claude",   "adapter": "claude", "color": "#e07830", "emblem": "star"},
        {"id": "codex",   "model_display": "ChatGPT",  "adapter": "codex",  "color": "#10b8a0", "emblem": "knot"},
        {"id": "gemini",  "model_display": "Gemini",   "adapter": "gemini", "color": "#8060e8", "emblem": "quad"},
    ],
    "member_system_prompt": "你是委員。",
    "chair_system_prompt": "你是主席。",
}


def _run_session_mock(response_text):
    """Run a session where all members return response_text."""
    with patch.object(adapters, "run_adapter", return_value=(True, response_text)):
        session = parliament.create_session("測試議題", _THREE_CFG)
        lock = threading.Lock()
        parliament.run_session(session, lock)
    return session


# ── Test 1: extraction with 【結論】 present ────────────────────────────────

class TestConclusionExtraction(unittest.TestCase):

    def test_conclusion_extracted_from_last_conclusion_line(self):
        """Conclusion is extracted from the last 【結論】 line."""
        text = "正文段落。\n詳細說明。\n【結論】此議題應審慎評估。"
        session = _run_session_mock(text)
        for label, m in session["members"].items():
            self.assertEqual(m["status"], "done")
            self.assertIsNotNone(m["conclusion"], f"conclusion should not be None for {label}")
            self.assertIn("審慎評估", m["conclusion"])

    def test_conclusion_none_when_format_absent(self):
        """Conclusion is None when response has no 【結論】 line — no LLM fallback."""
        text = "這是一個沒有結論行的回答。整段都是正文。"
        session = _run_session_mock(text)
        for label, m in session["members"].items():
            self.assertIsNone(m["conclusion"], f"conclusion must be None (no 【結論】) for {label}")

    def test_multiple_conclusion_lines_takes_last(self):
        """If multiple 【結論】 lines exist, the last one wins."""
        text = "【結論】第一個結論不應採用。\n後面還有更多內容。\n【結論】最後這個才是正確結論。"
        session = _run_session_mock(text)
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"])
            self.assertIn("最後這個才是正確結論", m["conclusion"])
            self.assertNotIn("第一個結論", m["conclusion"])

    def test_conclusion_in_public_view(self):
        """public_view exposes conclusion field for each member."""
        text = "正文。\n【結論】公開視圖應可見此結論。"
        session = _run_session_mock(text)
        view = parliament.public_view(session)
        for label, mdata in view["members"].items():
            self.assertIn("conclusion", mdata, f"label {label} missing conclusion in public_view")
            self.assertIsNotNone(mdata["conclusion"])
            self.assertIn("公開視圖應可見此結論", mdata["conclusion"])

    def test_conclusion_none_in_public_view_when_absent(self):
        """public_view shows conclusion=None when format not followed."""
        text = "只有正文，沒有結論行。"
        session = _run_session_mock(text)
        view = parliament.public_view(session)
        for label, mdata in view["members"].items():
            self.assertIn("conclusion", mdata)
            self.assertIsNone(mdata["conclusion"])


# ── Test 2: conclusion self-id filter ────────────────────────────────────────

class TestConclusionSelfIdFilter(unittest.TestCase):

    def test_self_id_in_conclusion_is_filtered(self):
        """Brand names in the extracted conclusion are filtered by filter_self_id."""
        text = "正文段落。\n【結論】我是Claude，認為此議題應從多角度審視。"
        session = _run_session_mock(text)
        for label, m in session["members"].items():
            if m["conclusion"] is not None:
                self.assertNotIn("Claude", m["conclusion"],
                    f"brand 'Claude' leaked in conclusion for {label}: {m['conclusion']!r}")

    def test_clean_conclusion_unchanged(self):
        """Conclusion without brand names passes through unchanged."""
        text = "正文。\n【結論】此議題需要跨部門協作才能有效解決。"
        session = _run_session_mock(text)
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"])
            self.assertIn("跨部門協作", m["conclusion"])


# ── Test 3: mock end-to-end conclusion non-empty ─────────────────────────────

class TestMockEndToEndConclusion(unittest.TestCase):

    def test_mock_adapter_responses_have_conclusion(self):
        """Mock adapters include 【結論】 so end-to-end conclusion is non-None."""
        adapters.set_mock_mode(True)
        try:
            session = parliament.create_session("AI 應用的倫理邊界？", _THREE_CFG)
            lock = threading.Lock()
            parliament.run_session(session, lock)
            for label, m in session["members"].items():
                self.assertIsNotNone(
                    m["conclusion"],
                    f"mock adapter for {label} should produce non-None conclusion"
                )
        finally:
            adapters.set_mock_mode(False)


# ── Test 4: chair prompt four-section format ──────────────────────────────────

class TestChairPromptFourSections(unittest.TestCase):

    def _build_prompt(self, **kwargs):
        defaults = dict(
            question="測試議題",
            anon_responses={"A": "A回答", "B": "B回答", "C": "C回答"},
            member_statuses={"A": "done", "B": "done", "C": "done"},
            chair_system="",
        )
        defaults.update(kwargs)
        return anonymizer.build_chair_prompt(**defaults)

    def test_chair_prompt_has_four_sections(self):
        prompt = self._build_prompt()
        self.assertIn("1. 共識點", prompt)
        self.assertIn("2. 分歧點", prompt)
        self.assertIn("3. 少數派報告", prompt)
        self.assertIn("4. 綜合結論", prompt)

    def test_minority_report_section_instruction_present(self):
        prompt = self._build_prompt()
        self.assertIn("少數派報告", prompt)
        self.assertIn("未收斂", prompt)

    def test_minority_report_unanimous_fallback_instruction(self):
        """Prompt includes 'no minority when unanimous' instruction."""
        prompt = self._build_prompt()
        self.assertIn("全體一致", prompt)

    def test_chair_prompt_no_consensus_allowed(self):
        """Prompt explicitly allows chair to declare no consensus."""
        prompt = self._build_prompt()
        self.assertIn("無共識", prompt)

    def test_chair_prompt_resummary_also_has_four_sections(self):
        followups = [{"member": "A", "question": "追問", "response": "補充回答", "status": "done"}]
        prompt = anonymizer.build_chair_prompt(
            question="Q",
            anon_responses={"A": "初答", "B": "初答B", "C": "初答C"},
            member_statuses={"A": "done", "B": "done", "C": "done"},
            chair_system="",
            is_resummary=True,
            followup_summaries=followups,
        )
        self.assertIn("少數派報告", prompt)
        self.assertIn("4. 綜合結論", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
