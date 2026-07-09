"""
Tests for i18n / bilingual support (zh/en).

Covers:
  1. lang default "zh" when omitted from create_session
  2. Illegal lang value falls back to "zh"
  3. EN member prompt contains "Conclusion:" instruction
  4. EN conclusion extracted from "Conclusion:" line
  5. Both markers (【結論】 and Conclusion:) extracted regardless of lang
  6. EN chair prompt has four English section headers + zero brand names in member sections
  7. redact_model_names en token is [an AI] not [某AI]
  8. Mock end-to-end EN round: conclusion non-None, chair_summary non-empty
  9. public_view exposes lang field
 10. Server POST /api/parliament accepts lang field and stores it
"""
import json
import os
import re
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapters
import anonymizer
import parliament


# ── shared config ─────────────────────────────────────────────────────────────

_THREE_CFG = {
    "members": [
        {"id": "claude",  "model_display": "Claude",   "adapter": "claude", "color": "#e07830", "emblem": "star"},
        {"id": "codex",   "model_display": "ChatGPT",  "adapter": "codex",  "color": "#10b8a0", "emblem": "knot"},
        {"id": "gemini",  "model_display": "Gemini",   "adapter": "gemini", "color": "#8060e8", "emblem": "quad"},
    ],
    "member_system_prompt": "You are a committee member.",
    "chair_system_prompt": "You are the chair.",
}


def _run_session(lang="zh", response_text=None):
    """Run a session with all members returning response_text."""
    def mock_adapter(name, prompt, model_arg=None):
        return adapters._run_mock(name, prompt)

    adapters.set_mock_mode(True)
    try:
        session = parliament.create_session("Should AI be regulated?", _THREE_CFG, lang=lang)
        lock = threading.Lock()
        parliament.run_session(session, lock)
    finally:
        adapters.set_mock_mode(False)
    return session


# ── Test 1: lang default ──────────────────────────────────────────────────────

class TestLangDefault(unittest.TestCase):

    def test_lang_default_is_zh(self):
        session = parliament.create_session("test", _THREE_CFG)
        self.assertEqual(session.get("lang"), "zh")

    def test_lang_explicit_zh(self):
        session = parliament.create_session("test", _THREE_CFG, lang="zh")
        self.assertEqual(session.get("lang"), "zh")

    def test_lang_explicit_en(self):
        session = parliament.create_session("test", _THREE_CFG, lang="en")
        self.assertEqual(session.get("lang"), "en")


# ── Test 2: illegal lang value ────────────────────────────────────────────────

class TestLangFallback(unittest.TestCase):

    def test_illegal_lang_falls_back_to_zh(self):
        session = parliament.create_session("test", _THREE_CFG, lang="fr")
        self.assertEqual(session.get("lang"), "zh",
            "Non-en/zh lang must normalise to zh")

    def test_empty_lang_falls_back_to_zh(self):
        session = parliament.create_session("test", _THREE_CFG, lang="")
        self.assertEqual(session.get("lang"), "zh")


# ── Test 3: EN member prompt has Conclusion instruction ───────────────────────

class TestEnMemberPrompt(unittest.TestCase):

    def _capture_prompts(self, lang):
        prompts = []
        def mock_adapter(name, prompt, model_arg=None):
            prompts.append((name, prompt))
            return True, f"Body.\nConclusion: Test conclusion."

        with patch.object(adapters, "run_adapter", side_effect=mock_adapter):
            session = parliament.create_session("Test question", _THREE_CFG, lang=lang)
            lock = threading.Lock()
            parliament.run_session(session, lock)
        return prompts

    def test_en_member_prompt_contains_conclusion_instruction(self):
        prompts = self._capture_prompts("en")
        member_prompts = [(n, p) for n, p in prompts if n != "claude"]
        self.assertGreater(len(member_prompts), 0)
        for name, p in member_prompts:
            self.assertIn("Conclusion:", p,
                f"EN member prompt for {name} should contain 'Conclusion:' instruction")

    def test_en_member_prompt_contains_member_label(self):
        prompts = self._capture_prompts("en")
        member_prompts = [(n, p) for n, p in prompts if n != "claude"]
        for name, p in member_prompts:
            self.assertRegex(p, r"Member [A-Z]",
                f"EN prompt for {name} should use 'Member X' label")

    def test_zh_member_prompt_contains_zh_conclusion_instruction(self):
        prompts = self._capture_prompts("zh")
        member_prompts = [(n, p) for n, p in prompts if n != "claude"]
        for name, p in member_prompts:
            self.assertIn("【結論】", p,
                f"ZH member prompt for {name} should contain 【結論】 instruction")


# ── Test 4: EN conclusion extracted from "Conclusion:" line ──────────────────

class TestEnConclusionExtraction(unittest.TestCase):

    def _run_with_text(self, response_text, lang="en"):
        with patch.object(adapters, "run_adapter", return_value=(True, response_text)):
            session = parliament.create_session("Test?", _THREE_CFG, lang=lang)
            lock = threading.Lock()
            parliament.run_session(session, lock)
        return session

    def test_conclusion_extracted_from_en_marker(self):
        session = self._run_with_text("Body text.\nConclusion: AI should be carefully regulated.", lang="en")
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"], f"EN Conclusion: marker not extracted for {label}")
            self.assertIn("regulated", m["conclusion"])

    def test_conclusion_case_insensitive(self):
        session = self._run_with_text("Body.\nCONCLUSION: Upper-case marker works.", lang="en")
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"], f"Case-insensitive 'CONCLUSION:' not extracted for {label}")


# ── Test 5: both markers extracted regardless of lang ─────────────────────────

class TestBothMarkersExtracted(unittest.TestCase):

    def _run_single(self, response_text, lang):
        with patch.object(adapters, "run_adapter", return_value=(True, response_text)):
            session = parliament.create_session("test", _THREE_CFG, lang=lang)
            lock = threading.Lock()
            parliament.run_session(session, lock)
        return session

    def test_zh_marker_extracted_in_en_session(self):
        """User might write in Chinese even in EN UI session."""
        text = "Some body.\n【結論】此議題需要謹慎處理。"
        session = self._run_single(text, lang="en")
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"],
                f"【結論】 marker should be extracted even in en session for {label}")

    def test_en_marker_extracted_in_zh_session(self):
        """User might write in English even in ZH UI session."""
        text = "Some body.\nConclusion: This topic requires careful handling."
        session = self._run_single(text, lang="zh")
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"],
                f"Conclusion: marker should be extracted even in zh session for {label}")


# ── Test 6: EN chair prompt has four English sections + zero brands ───────────

class TestEnChairPrompt(unittest.TestCase):

    BRANDS = ["Claude", "ChatGPT", "Gemini", "GPT-4", "Anthropic", "OpenAI", "Google"]

    def _build(self, **kwargs):
        defaults = dict(
            question="Should AI be regulated?",
            anon_responses={"A": "Response A.", "B": "Response B.", "C": "Response C."},
            member_statuses={"A": "done", "B": "done", "C": "done"},
            chair_system="",
            lang="en",
        )
        defaults.update(kwargs)
        return anonymizer.build_chair_prompt(**defaults)

    def test_en_chair_prompt_has_english_section_headers(self):
        prompt = self._build()
        self.assertIn("1. Consensus", prompt)
        self.assertIn("2. Divergences", prompt)
        self.assertIn("3. Minority Report", prompt)
        self.assertIn("4. Chair's Synthesis", prompt)

    def test_en_chair_prompt_no_chinese_section_headers(self):
        prompt = self._build()
        self.assertNotIn("共識點", prompt)
        self.assertNotIn("分歧點", prompt)
        self.assertNotIn("少數派報告", prompt)
        self.assertNotIn("綜合結論", prompt)

    def test_en_chair_prompt_member_sections_no_brand_names(self):
        prompt = self._build()
        # Extract only member response sections (before footer)
        lines = prompt.splitlines()
        section_lines = []
        in_section = False
        for line in lines:
            if "[Member " in line:
                in_section = True
            if "Please output" in line:
                break
            if in_section:
                section_lines.append(line)
        section = "\n".join(section_lines)
        for brand in self.BRANDS:
            self.assertNotIn(brand, section,
                f"Brand '{brand}' leaked in EN chair member sections")

    def test_en_chair_prompt_uses_member_label_not_zh_label(self):
        prompt = self._build()
        self.assertIn("Member A", prompt)
        self.assertIn("Member B", prompt)
        self.assertNotIn("委員A", prompt)
        self.assertNotIn("委員B", prompt)

    def test_en_chair_prompt_unanimous_fallback(self):
        prompt = self._build()
        self.assertIn("unanimous", prompt)

    def test_en_chair_prompt_no_consensus_option(self):
        prompt = self._build()
        self.assertIn("no consensus", prompt)


# ── Test 7: redact_model_names lang token ─────────────────────────────────────

class TestRedactLangToken(unittest.TestCase):

    def test_zh_token_is_mouai(self):
        out = anonymizer.redact_model_names("Claude and Gemini disagree", lang="zh")
        self.assertIn("[某AI]", out)
        self.assertNotIn("[an AI]", out)

    def test_en_token_is_an_ai(self):
        out = anonymizer.redact_model_names("Claude and Gemini disagree", lang="en")
        self.assertIn("[an AI]", out)
        self.assertNotIn("[某AI]", out)


# ── Test 8: mock EN end-to-end ────────────────────────────────────────────────

class TestMockEnEndToEnd(unittest.TestCase):

    def test_en_round_conclusion_non_none(self):
        session = _run_session(lang="en")
        for label, m in session["members"].items():
            self.assertIsNotNone(m["conclusion"],
                f"EN mock adapter should produce non-None conclusion for {label}")

    def test_en_round_chair_summary_non_empty(self):
        session = _run_session(lang="en")
        self.assertIsNotNone(session.get("chair_summary"))
        self.assertNotEqual(session["chair_summary"], "")

    def test_en_round_public_view_lang_is_en(self):
        session = _run_session(lang="en")
        view = parliament.public_view(session)
        self.assertEqual(view.get("lang"), "en")


# ── Test 9: public_view exposes lang ─────────────────────────────────────────

class TestPublicViewLang(unittest.TestCase):

    def test_zh_session_public_view_lang_zh(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "回答\n【結論】立場。")):
            session = parliament.create_session("test", _THREE_CFG, lang="zh")
            lock = threading.Lock()
            parliament.run_session(session, lock)
        view = parliament.public_view(session)
        self.assertEqual(view.get("lang"), "zh")

    def test_en_session_public_view_lang_en(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "Body.\nConclusion: Position.")):
            session = parliament.create_session("test", _THREE_CFG, lang="en")
            lock = threading.Lock()
            parliament.run_session(session, lock)
        view = parliament.public_view(session)
        self.assertEqual(view.get("lang"), "en")


# ── Test 10: server POST /api/parliament stores lang ─────────────────────────

class TestServerLangField(unittest.TestCase):

    def setUp(self):
        import http.server
        import server as srv
        self._srv_mod = srv
        srv._config_cache = _THREE_CFG
        self._server = http.server.HTTPServer(("127.0.0.1", 0), srv._Handler)
        self._port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._server.shutdown()
        import server as srv
        srv._config_cache = None

    def _post(self, path, body, pin=None):
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self._port}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if pin is not None:
            req.add_header("X-Parliament-Pin", pin)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _get(self, path, pin=None):
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self._port}{path}"
        req = urllib.request.Request(url)
        if pin is not None:
            req.add_header("X-Parliament-Pin", pin)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_post_with_lang_en_session_has_lang_en(self):
        pin = self._srv_mod._PIN
        with patch.object(adapters, "run_adapter", return_value=(True, "Body.\nConclusion: OK.")):
            status, body = self._post("/api/parliament", {"question": "test", "lang": "en"}, pin=pin)
        self.assertEqual(status, 202)
        session_id = body["session_id"]
        import time
        for _ in range(30):
            s, d = self._get(f"/api/parliament/{session_id}", pin=pin)
            if s == 200 and d.get("status") == "done":
                break
            time.sleep(0.1)
        self.assertEqual(d.get("lang"), "en")

    def test_post_without_lang_defaults_to_zh(self):
        pin = self._srv_mod._PIN
        with patch.object(adapters, "run_adapter", return_value=(True, "回答。\n【結論】立場。")):
            status, body = self._post("/api/parliament", {"question": "test"}, pin=pin)
        self.assertEqual(status, 202)
        session_id = body["session_id"]
        import time
        for _ in range(30):
            s, d = self._get(f"/api/parliament/{session_id}", pin=pin)
            if s == 200 and d.get("status") == "done":
                break
            time.sleep(0.1)
        self.assertEqual(d.get("lang"), "zh")

    def test_post_with_illegal_lang_defaults_to_zh(self):
        pin = self._srv_mod._PIN
        with patch.object(adapters, "run_adapter", return_value=(True, "回答。\n【結論】立場。")):
            status, body = self._post("/api/parliament", {"question": "test", "lang": "de"}, pin=pin)
        self.assertEqual(status, 202)
        session_id = body["session_id"]
        import time
        for _ in range(30):
            s, d = self._get(f"/api/parliament/{session_id}", pin=pin)
            if s == 200 and d.get("status") == "done":
                break
            time.sleep(0.1)
        self.assertEqual(d.get("lang"), "zh")


if __name__ == "__main__":
    unittest.main(verbosity=2)
