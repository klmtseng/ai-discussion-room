"""
Tests for seat management endpoints (GET/PUT /api/config/members, POST test, cache invalidation).
Run: python3 -m pytest tests/test_seat_management.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapters


_THREE_CFG = {
    "members": [
        {"id": "claude", "model_display": "Claude",           "adapter": "claude", "color": "#e07830", "emblem": "star", "model_arg": None, "system_prompt": ""},
        {"id": "codex",  "model_display": "ChatGPT",          "adapter": "codex",  "color": "#10b8a0", "emblem": "knot", "model_arg": None, "system_prompt": ""},
        {"id": "gemini", "model_display": "Gemini 2.5 Flash", "adapter": "gemini", "color": "#8060e8", "emblem": "quad", "model_arg": "gemini-2.5-flash", "system_prompt": ""},
    ],
    "member_system_prompt": "你是委員。",
    "chair_system_prompt":  "你是主席。",
    "exploration": {"enabled": True, "cooldown_seconds": 120, "max_exchanges_per_hour": 10},
}

_FOUR_MEMBERS = [
    {"id": "claude", "model_display": "Claude",           "adapter": "claude", "color": "#e07830", "emblem": "star"},
    {"id": "codex",  "model_display": "ChatGPT",          "adapter": "codex",  "color": "#10b8a0", "emblem": "knot"},
    {"id": "gemini", "model_display": "Gemini 2.5 Flash", "adapter": "gemini", "color": "#8060e8", "emblem": "quad"},
    {"id": "gemini-pro", "model_display": "Gemini Pro",   "adapter": "gemini", "color": "#30c850", "emblem": "dot", "model_arg": "gemini-pro"},
]


class SeatManagementBase(unittest.TestCase):
    """Spin up a real HTTP server backed by a temp config file."""

    def setUp(self):
        import server as srv
        import http.server as _hs

        self._srv_mod = srv
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(_THREE_CFG, self._tmp)
        self._tmp.close()
        self._tmp_path = self._tmp.name

        # Patch server to use temp config path
        self._orig_override = srv._CONFIG_PATH_OVERRIDE
        srv._CONFIG_PATH_OVERRIDE = self._tmp_path
        srv._config_cache = None  # reset

        # Reset test-connection throttle
        srv._test_cooldown_until = 0.0

        self._server = _hs.HTTPServer(("127.0.0.1", 0), srv._Handler)
        self._port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._server.shutdown()
        import server as srv
        srv._CONFIG_PATH_OVERRIDE = self._orig_override
        srv._config_cache = None
        os.unlink(self._tmp_path)

    def _req(self, method, path, body=None, pin=None):
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self._port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if pin is not None:
            req.add_header("X-Parliament-Pin", pin)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {}

    @property
    def pin(self):
        return self._srv_mod._PIN


# ── GET /api/config/members — PIN lock ───────────────────────────────────────

class TestGetMembersPinLock(SeatManagementBase):

    def test_get_no_pin_returns_401(self):
        status, _ = self._req("GET", "/api/config/members")
        self.assertEqual(status, 401)

    def test_get_wrong_pin_returns_401(self):
        status, _ = self._req("GET", "/api/config/members", pin="000000")
        self.assertEqual(status, 401)

    def test_get_correct_pin_returns_200(self):
        status, body = self._req("GET", "/api/config/members", pin=self.pin)
        self.assertEqual(status, 200)
        self.assertIn("members", body)

    def test_get_returns_full_members_with_system_prompt(self):
        status, body = self._req("GET", "/api/config/members", pin=self.pin)
        self.assertEqual(status, 200)
        members = body["members"]
        self.assertEqual(len(members), 3)
        # Must include private/management fields (unlike /api/config)
        for m in members:
            self.assertIn("adapter", m)
            self.assertIn("id", m)

    def test_get_includes_system_prompt_field(self):
        status, body = self._req("GET", "/api/config/members", pin=self.pin)
        members = body["members"]
        # system_prompt present (may be empty string)
        for m in members:
            self.assertIn("system_prompt", m)


# ── PUT /api/config/members — PIN lock ───────────────────────────────────────

class TestPutMembersPinLock(SeatManagementBase):

    def test_put_no_pin_returns_401(self):
        status, _ = self._req("PUT", "/api/config/members", body={"members": _FOUR_MEMBERS})
        self.assertEqual(status, 401)

    def test_put_wrong_pin_returns_401(self):
        status, _ = self._req("PUT", "/api/config/members", body={"members": _FOUR_MEMBERS}, pin="000000")
        self.assertEqual(status, 401)


# ── PUT /api/config/members — validation ─────────────────────────────────────

class TestPutMembersValidation(SeatManagementBase):

    def test_put_too_few_seats_returns_400(self):
        status, body = self._req("PUT", "/api/config/members",
            body={"members": [_FOUR_MEMBERS[0]]}, pin=self.pin)
        self.assertEqual(status, 400)
        self.assertIn("errors", body)

    def test_put_too_many_seats_returns_400(self):
        seven = [
            {"id": f"m{i}", "model_display": f"M{i}", "adapter": "claude"}
            for i in range(7)
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": seven}, pin=self.pin)
        self.assertEqual(status, 400)
        self.assertIn("errors", body)

    def test_put_duplicate_id_returns_400(self):
        bad = [
            {"id": "claude", "model_display": "C1", "adapter": "claude"},
            {"id": "claude", "model_display": "C2", "adapter": "codex"},
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": bad}, pin=self.pin)
        self.assertEqual(status, 400)
        errs = " ".join(body.get("errors", []))
        self.assertIn("duplicate", errs)

    def test_put_invalid_id_pattern_returns_400(self):
        bad = [
            {"id": "UPPER_CASE!", "model_display": "Bad", "adapter": "claude"},
            {"id": "ok-seat", "model_display": "Good", "adapter": "codex"},
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": bad}, pin=self.pin)
        self.assertEqual(status, 400)
        errs = " ".join(body.get("errors", []))
        self.assertIn("id", errs)

    def test_put_invalid_adapter_returns_400(self):
        bad = [
            {"id": "x", "model_display": "X", "adapter": "unknown-vendor"},
            {"id": "y", "model_display": "Y", "adapter": "claude"},
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": bad}, pin=self.pin)
        self.assertEqual(status, 400)
        errs = " ".join(body.get("errors", []))
        self.assertIn("adapter", errs)

    def test_put_invalid_color_returns_400(self):
        bad = [
            {"id": "x", "model_display": "X", "adapter": "claude", "color": "red"},
            {"id": "y", "model_display": "Y", "adapter": "codex"},
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": bad}, pin=self.pin)
        self.assertEqual(status, 400)
        errs = " ".join(body.get("errors", []))
        self.assertIn("color", errs)

    def test_put_gemini_prefixed_adapter_accepted(self):
        members = [
            {"id": "a", "model_display": "Gemini Pro", "adapter": "gemini-pro"},
            {"id": "b", "model_display": "Claude",     "adapter": "claude"},
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": members}, pin=self.pin)
        self.assertEqual(status, 200)

    def test_put_claude_prefixed_adapter_accepted(self):
        members = [
            {"id": "a", "model_display": "Claude Haiku", "adapter": "claude-haiku"},
            {"id": "b", "model_display": "Codex",        "adapter": "codex"},
        ]
        status, body = self._req("PUT", "/api/config/members",
            body={"members": members}, pin=self.pin)
        self.assertEqual(status, 200)


# ── PUT /api/config/members — persistence & cache invalidation ───────────────

class TestPutMembersPersistence(SeatManagementBase):

    def test_put_writes_to_config_file(self):
        status, body = self._req("PUT", "/api/config/members",
            body={"members": _FOUR_MEMBERS}, pin=self.pin)
        self.assertEqual(status, 200)
        with open(self._tmp_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(len(on_disk["members"]), 4)

    def test_put_preserves_other_config_keys(self):
        """Updating members must not destroy chair_system_prompt / exploration / etc."""
        status, _ = self._req("PUT", "/api/config/members",
            body={"members": _FOUR_MEMBERS}, pin=self.pin)
        self.assertEqual(status, 200)
        with open(self._tmp_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertIn("chair_system_prompt", on_disk)
        self.assertIn("member_system_prompt", on_disk)
        self.assertIn("exploration", on_disk)
        self.assertEqual(on_disk["chair_system_prompt"], _THREE_CFG["chair_system_prompt"])

    def test_put_cache_invalidated_get_config_sees_new_members(self):
        """After PUT, GET /api/config must show new member count."""
        status, _ = self._req("PUT", "/api/config/members",
            body={"members": _FOUR_MEMBERS}, pin=self.pin)
        self.assertEqual(status, 200)
        # GET /api/config returns display-only members (label, color, emblem)
        status2, body2 = self._req("GET", "/api/config", pin=self.pin)
        self.assertEqual(status2, 200)
        self.assertEqual(len(body2["members"]), 4)

    def test_put_cache_invalidated_new_session_uses_new_members(self):
        """PUT members → new parliament session must use the new member list."""
        import parliament, anonymizer
        status, _ = self._req("PUT", "/api/config/members",
            body={"members": _FOUR_MEMBERS}, pin=self.pin)
        self.assertEqual(status, 200)

        import server as srv
        fresh_cfg = srv._load_config()
        session = parliament.create_session("test", fresh_cfg)
        self.assertEqual(len(session["members"]), 4)

    def test_existing_session_not_affected_by_put(self):
        """A session created before PUT retains its original members snapshot."""
        import parliament, anonymizer
        import server as srv
        original_cfg = srv._load_config()
        import copy
        original_cfg_copy = copy.deepcopy(original_cfg)
        session = parliament.create_session("test", original_cfg_copy)
        original_labels = set(session["members"].keys())
        self.assertEqual(len(original_labels), 3)  # 3-seat session

        # Now PUT 4 members
        self._req("PUT", "/api/config/members",
            body={"members": _FOUR_MEMBERS}, pin=self.pin)

        # Original session is untouched (it captured config at creation time)
        self.assertEqual(set(session["members"].keys()), original_labels)


# ── POST /api/config/members/test — mock mode ────────────────────────────────

class TestMemberTestEndpoint(SeatManagementBase):

    def test_test_mock_returns_ok(self):
        import server as srv
        orig_mock = adapters._MOCK_MODE
        adapters._MOCK_MODE = True
        try:
            status, body = self._req(
                "POST", "/api/config/members/test",
                body={"adapter": "claude", "model_arg": None},
                pin=self.pin,
            )
            self.assertEqual(status, 200)
            self.assertIn("ok", body)
            self.assertIn("latency_ms", body)
            self.assertIn("snippet", body)
        finally:
            adapters._MOCK_MODE = orig_mock

    def test_test_throttle_returns_429(self):
        import server as srv
        orig_mock = adapters._MOCK_MODE
        adapters._MOCK_MODE = True
        # Force cooldown active
        srv._test_cooldown_until = time.time() + 60
        try:
            status, body = self._req(
                "POST", "/api/config/members/test",
                body={"adapter": "claude"},
                pin=self.pin,
            )
            self.assertEqual(status, 429)
            self.assertIn("wait_seconds", body)
        finally:
            adapters._MOCK_MODE = orig_mock
            srv._test_cooldown_until = 0.0

    def test_test_no_pin_returns_401(self):
        status, _ = self._req("POST", "/api/config/members/test",
            body={"adapter": "claude"})
        self.assertEqual(status, 401)

    def test_test_unknown_adapter_returns_400(self):
        import server as srv
        srv._test_cooldown_until = 0.0
        status, body = self._req("POST", "/api/config/members/test",
            body={"adapter": "unknown-xyz"}, pin=self.pin)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
