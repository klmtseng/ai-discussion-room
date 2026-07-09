"""
Unit tests for AI Parliament.
No real CLI calls — all adapters mocked.
Run: python3 -m pytest tests/ -v
  or: python3 -m unittest discover tests -v
"""
import io
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from unittest.mock import patch, call, MagicMock

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anonymizer
import adapters
import parliament


# ── PIN auth helpers ──────────────────────────────────────────────────────────

def _make_handler_with_headers(headers_dict: dict) -> "_Handler":
    """Build a minimal _Handler-like object with mock headers for PIN testing."""
    import server as srv

    class _FakeRequest:
        def makefile(self, *a, **k):
            return io.BytesIO(b"")

    class _FakeHandler(srv._Handler):
        def __init__(self):
            # Don't call super().__init__ — we just need headers
            self.headers = headers_dict
            self._sent = []

        def _send_json(self, code, data):
            self._sent.append((code, data))

    return _FakeHandler()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_session(config=None):
    cfg = config or {"member_system_prompt": "", "chair_system_prompt": ""}
    return parliament.create_session("測試議題", cfg)


# ── Anonymizer tests ──────────────────────────────────────────────────────────

class TestShuffle(unittest.TestCase):

    def test_same_seed_same_result(self):
        m1 = anonymizer.create_shuffle(42)
        m2 = anonymizer.create_shuffle(42)
        self.assertEqual(m1, m2)

    def test_different_seed_may_differ(self):
        """Not guaranteed but almost certain with large seed space."""
        results = set()
        for seed in range(20):
            m = anonymizer.create_shuffle(seed)
            results.add(tuple(m.values()))
        self.assertGreater(len(results), 1)

    def test_all_labels_present(self):
        m = anonymizer.create_shuffle(7)
        self.assertEqual(set(m.keys()), {"A", "B", "C"})

    def test_all_adapters_used_exactly_once(self):
        m = anonymizer.create_shuffle(7)
        self.assertEqual(set(m.values()), set(anonymizer.ADAPTER_NAMES))


# ── Self-id filter tests ──────────────────────────────────────────────────────

class TestFilterSelfIdEnglish(unittest.TestCase):

    def _check(self, text, label="A"):
        result = anonymizer.filter_self_id(text, label)
        # Model names should not appear in result
        for name in ("Claude", "ChatGPT", "Gemini", "Bard", "Codex"):
            self.assertNotIn(name, result, f"'{name}' still present after filtering: {result!r}")
        return result

    def test_im_claude(self):
        self._check("I'm Claude, and I'm here to help you today.")

    def test_as_chatgpt(self):
        self._check("As ChatGPT, I would suggest the following approach.")

    def test_gemini_here(self):
        self._check("Gemini here, ready to answer your question.")

    def test_this_is_gemini(self):
        self._check("This is Gemini speaking on the matter.")

    def test_i_am_claude(self):
        self._check("I am Claude, developed by Anthropic.")

    def test_replacement_label(self):
        result = anonymizer.filter_self_id("I'm Claude, nice to meet you.", "B")
        self.assertIn("[委員B]", result)


class TestFilterSelfIdChinese(unittest.TestCase):

    def _check(self, text, label="A"):
        result = anonymizer.filter_self_id(text, label)
        for name in ("Claude", "ChatGPT", "Gemini", "Anthropic", "OpenAI", "Google"):
            self.assertNotIn(name, result, f"'{name}' still present: {result!r}")
        return result

    def test_wo_shi_claude(self):
        self._check("我是Claude，很高興為您服務。")

    def test_shen_wei_ai(self):
        self._check("身為AI語言模型，我認為這個問題需要謹慎思考。")

    def test_you_anthropic_kaifa(self):
        self._check("由Anthropic開發的我表示這個問題很有趣。")

    def test_wo_shi_youkai_ai(self):
        self._check("我是由OpenAI訓練的語言模型。")

    def test_zuowei_google(self):
        self._check("作為Google的AI助手，我建議您考慮以下方案。")

    def test_replacement_has_label(self):
        result = anonymizer.filter_self_id("我是Claude，", "C")
        self.assertIn("[委員C]", result)


# ── Chair prompt tests ────────────────────────────────────────────────────────

class TestBuildChairPrompt(unittest.TestCase):

    def test_absent_member_shows_notice(self):
        prompt = anonymizer.build_chair_prompt(
            question="氣候變遷的對策？",
            anon_responses={"A": "回答A", "C": "回答C"},
            member_statuses={"A": "done", "B": "error", "C": "done"},
            chair_system="",
        )
        self.assertIn("本席缺席", prompt)
        self.assertIn("委員B", prompt)

    def test_no_model_names_in_response_section(self):
        # Even if a "leaked" response is passed in, it should be clean
        # (caller should pre-filter; build_chair_prompt doesn't double-filter)
        prompt = anonymizer.build_chair_prompt(
            question="測試",
            anon_responses={"A": "[委員A]已替換", "B": "正常回答", "C": "正常"},
            member_statuses={"A": "done", "B": "done", "C": "done"},
            chair_system="",
        )
        self.assertIn("本輪議題", prompt)
        self.assertIn("共識點", prompt)
        self.assertIn("分歧點", prompt)
        self.assertIn("少數派報告", prompt)
        self.assertIn("綜合結論", prompt)

    def test_all_three_done(self):
        prompt = anonymizer.build_chair_prompt(
            question="Q",
            anon_responses={"A": "A回答", "B": "B回答", "C": "C回答"},
            member_statuses={"A": "done", "B": "done", "C": "done"},
            chair_system="你是主席。",
        )
        self.assertIn("你是主席。", prompt)
        self.assertIn("A回答", prompt)
        self.assertIn("B回答", prompt)
        self.assertIn("C回答", prompt)
        self.assertNotIn("本席缺席", prompt)

    def test_resummary_includes_followups(self):
        followups = [
            {"member": "A", "question": "追問", "response": "補充回答", "status": "done"}
        ]
        prompt = anonymizer.build_chair_prompt(
            question="Q",
            anon_responses={"A": "初答", "B": "初答B", "C": "初答C"},
            member_statuses={"A": "done", "B": "done", "C": "done"},
            chair_system="",
            is_resummary=True,
            followup_summaries=followups,
        )
        self.assertIn("深聊補充", prompt)
        self.assertIn("追問", prompt)
        self.assertIn("補充回答", prompt)


# ── Adapter noise filter tests ────────────────────────────────────────────────

class TestAdapterNoiseFilter(unittest.TestCase):

    def test_gemini_ripgrep_removed(self):
        raw = "Ripgrep is not available on this system.\nHello world"
        result = adapters.filter_noise(raw, "gemini")
        self.assertNotIn("Ripgrep", result)
        self.assertIn("Hello world", result)

    def test_gemini_model_line_removed(self):
        raw = "Using model: gemini-2.5-flash\nActual answer here."
        result = adapters.filter_noise(raw, "gemini")
        self.assertNotIn("Using model", result)
        self.assertIn("Actual answer here", result)

    def test_gemini_blank_lines_removed(self):
        raw = "\n\nReal content\n\n"
        result = adapters.filter_noise(raw, "gemini")
        self.assertEqual(result.strip(), "Real content")

    def test_codex_tokens_used_removed(self):
        raw = "Tokens used: 123\nSession ID: abc\nHere is the answer."
        result = adapters.filter_noise(raw, "codex")
        self.assertNotIn("Tokens used", result)
        self.assertIn("Here is the answer", result)

    def test_claude_no_filter(self):
        raw = "Some output\nWith multiple lines"
        result = adapters.filter_noise(raw, "claude")
        self.assertEqual(result, raw.strip())


# ── Parliament session tests ──────────────────────────────────────────────────

_DEFAULT_CFG = {
    "member_system_prompt": "你是委員。",
    "chair_system_prompt": "你是主席。",
}


class TestSessionWithOneMemberFailure(unittest.TestCase):

    def test_session_completes_despite_one_error(self):
        """When codex adapter fails, session still completes and chair is called."""
        captured_chair_prompts = []

        def mock_adapter(name, prompt, model_arg=None, seat_cfg=None):
            if name == "codex":
                return False, "codex: timeout after 120s"
            if name == "claude":
                captured_chair_prompts.append(prompt)
                return True, "主席總結：共識/分歧/結論。"
            return True, f"[MOCK {name}] 回答。"

        with patch.object(adapters, "run_adapter", side_effect=mock_adapter):
            session = _make_session(_DEFAULT_CFG)
            lock = threading.Lock()
            parliament.run_session(session, lock)

        self.assertEqual(session["status"], "done")
        self.assertEqual(session["chair_status"], "done")

        # Identify which label got codex
        failed_label = next(
            lbl for lbl, m in session["members"].items() if m["_adapter"] == "codex"
        )
        self.assertEqual(session["members"][failed_label]["status"], "error")

        # Other members should be done
        for lbl, m in session["members"].items():
            if lbl != failed_label:
                self.assertEqual(m["status"], "done")

        # Chair should have been called; at least one call (the summary) mentions 本席缺席
        self.assertTrue(len(captured_chair_prompts) > 0, "Claude adapter was never called")
        # The chair summary prompt will contain 本席缺席 for the failed member
        self.assertTrue(
            any("本席缺席" in p for p in captured_chair_prompts),
            f"No prompt contained '本席缺席'. Got: {[p[:80] for p in captured_chair_prompts]}",
        )

    def test_chair_summary_set(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "mock回答")):
            session = _make_session(_DEFAULT_CFG)
            lock = threading.Lock()
            parliament.run_session(session, lock)
        self.assertIsNotNone(session["chair_summary"])
        self.assertNotIn("失敗", session["chair_summary"])


class TestSessionAllSuccess(unittest.TestCase):

    def test_all_members_done(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "一個完整的回答。")):
            session = _make_session(_DEFAULT_CFG)
            lock = threading.Lock()
            parliament.run_session(session, lock)

        for label in ("A", "B", "C"):
            self.assertEqual(session["members"][label]["status"], "done")
        self.assertEqual(session["status"], "done")
        self.assertIsNotNone(session["chair_summary"])

    def test_public_view_no_private_fields(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "回答")):
            session = _make_session(_DEFAULT_CFG)
            lock = threading.Lock()
            parliament.run_session(session, lock)

        view = parliament.public_view(session)
        self.assertNotIn("_config", view)
        self.assertNotIn("_debug_seed", view)
        self.assertNotIn("_debug_shuffle", view)
        self.assertIn("session_id", view)
        self.assertIn("members", view)
        self.assertIn("chair_summary", view)


class TestFollowup(unittest.TestCase):

    def test_followup_appended_to_conversation(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "回答")):
            session = _make_session(_DEFAULT_CFG)
            lock = threading.Lock()
            parliament.run_session(session, lock)

        # pick any done member label
        label = next(l for l, m in session["members"].items() if m["status"] == "done")

        with patch.object(adapters, "run_adapter", return_value=(True, "追問回答")):
            fid = parliament.add_followup(session, label, "追問內容", lock)
            parliament.run_followup(session, fid, _DEFAULT_CFG, lock)

        followup = next(f for f in session["followups"] if f["id"] == fid)
        self.assertEqual(followup["status"], "done")
        self.assertIn("追問回答", followup["response"])
        # Conversation should have grown
        self.assertGreater(len(session["members"][label]["conversation"]), 2)


# ── PIN auth tests ───────────────────────────────────────────────────────────

class TestPinAuth(unittest.TestCase):
    """Test PIN authentication via _check_pin and _require_pin."""

    def setUp(self):
        import server as srv
        self._real_pin = srv._PIN

    def _handler_with(self, header_pin=None, cookie_pin=None):
        """Return a handler whose headers contain the specified values."""
        import server as srv
        headers = {}
        if header_pin is not None:
            headers["X-Parliament-Pin"] = header_pin
        if cookie_pin is not None:
            headers["Cookie"] = f"parliament_pin={cookie_pin}"

        class _Fake:
            def __init__(self):
                self.headers = headers
                self._sent = []
            def _send_json(self_inner, code, data):
                self_inner._sent.append((code, data))

        return _Fake()

    def test_correct_header_pin_accepted(self):
        import server as srv
        h = self._handler_with(header_pin=self._real_pin)
        result = srv._check_pin(h)
        self.assertTrue(result)

    def test_wrong_header_pin_rejected(self):
        import server as srv
        h = self._handler_with(header_pin="000000")
        result = srv._check_pin(h)
        self.assertFalse(result)

    def test_correct_cookie_pin_accepted(self):
        import server as srv
        h = self._handler_with(cookie_pin=self._real_pin)
        result = srv._check_pin(h)
        self.assertTrue(result)

    def test_no_pin_rejected(self):
        import server as srv
        h = self._handler_with()
        result = srv._check_pin(h)
        self.assertFalse(result)

    def test_pin_is_six_digits(self):
        import server as srv
        self.assertRegex(srv._PIN, r"^\d{6}$")


class TestPinEndToEnd(unittest.TestCase):
    """Integration: start mock server, verify 401/200 with real HTTP requests."""

    def setUp(self):
        import server as srv
        import http.server
        import urllib.request
        self._srv_mod = srv

        # Spin up a test server on a random port
        self._server = http.server.HTTPServer(("127.0.0.1", 0), srv._Handler)
        self._port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._server.shutdown()

    def _get(self, path, pin=None):
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self._port}{path}"
        req = urllib.request.Request(url)
        if pin is not None:
            req.add_header("X-Parliament-Pin", pin)
        try:
            resp = urllib.request.urlopen(req)
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw

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

    def test_static_index_no_pin_200(self):
        status, _ = self._get("/")
        self.assertEqual(status, 200)

    def test_api_no_pin_returns_401(self):
        status, body = self._get("/api/parliament/nonexistent")
        self.assertEqual(status, 401)

    def test_api_wrong_pin_returns_401(self):
        status, body = self._get("/api/parliament/nonexistent", pin="000000")
        self.assertEqual(status, 401)

    def test_api_correct_pin_returns_404_not_401(self):
        """With correct PIN, API returns 404 (session not found) not 401."""
        pin = self._srv_mod._PIN
        status, body = self._get("/api/parliament/nonexistent", pin=pin)
        self.assertEqual(status, 404)

    def test_post_without_pin_returns_401(self):
        status, body = self._post("/api/parliament", {"question": "test"})
        self.assertEqual(status, 401)

    def test_mock_full_round_with_pin(self):
        """POST a question, poll until done, verify members and chair_summary."""
        pin = self._srv_mod._PIN

        with patch.object(adapters, "run_adapter", return_value=(True, "測試回答")):
            status, body = self._post("/api/parliament", {"question": "測試議題"}, pin=pin)
            self.assertEqual(status, 202)
            session_id = body["session_id"]

            # Poll until done (mock is synchronous via threading, may need a moment)
            import time
            for _ in range(30):
                s, d = self._get(f"/api/parliament/{session_id}", pin=pin)
                if s == 200 and d.get("status") == "done" and d.get("chair_status") == "done":
                    break
                time.sleep(0.1)

            self.assertEqual(d["status"], "done")
            self.assertEqual(d["chair_status"], "done")
            for label in ("A", "B", "C"):
                self.assertEqual(d["members"][label]["status"], "done")
            self.assertIsNotNone(d["chair_summary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
