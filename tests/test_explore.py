"""
Tests for exploration mode (explore.py + server /api/explore/encounter).
Run: python3 -m pytest tests/test_explore.py -v
"""
import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapters
import explore


# ── Config helpers ────────────────────────────────────────────────────────────

_CFG = {
    "members": [
        {"id": "claude", "model_display": "Claude",   "adapter": "claude", "color": "#e07830", "emblem": "star"},
        {"id": "codex",  "model_display": "ChatGPT",  "adapter": "codex",  "color": "#10b8a0", "emblem": "knot"},
        {"id": "gemini", "model_display": "Gemini",   "adapter": "gemini", "color": "#8060e8", "emblem": "quad"},
    ],
    "member_system_prompt": "你是委員。",
    "chair_system_prompt":  "你是主席。",
    "exploration": {
        "enabled": True,
        "cooldown_seconds": 120,
        "max_exchanges_per_hour": 10,
    },
}

_CFG_TIGHT = dict(_CFG, exploration={
    "enabled": True,
    "cooldown_seconds": 5,
    "max_exchanges_per_hour": 2,
})

_CFG_DISABLED = dict(_CFG, exploration={"enabled": False})


def _fresh_throttle(cooldown=1, max_ph=10):
    """Return a fresh ExploreThrottle for unit tests."""
    return explore.ExploreThrottle(cooldown_seconds=cooldown, max_per_hour=max_ph)


# ── Unit: throttle logic ──────────────────────────────────────────────────────

class TestExploreThrottleCooldown(unittest.TestCase):

    def test_first_call_passes(self):
        t = _fresh_throttle(cooldown=60)
        ok, wait = t.check()
        self.assertTrue(ok)
        self.assertIsNone(wait)

    def test_immediate_second_call_blocked(self):
        t = _fresh_throttle(cooldown=60)
        t.check()              # first — consumes slot
        ok, wait = t.check()  # immediate second
        self.assertFalse(ok)
        self.assertIsNotNone(wait)
        self.assertGreater(wait, 0)

    def test_wait_seconds_reported_correctly(self):
        t = _fresh_throttle(cooldown=30)
        t.check()
        ok, wait = t.check()
        self.assertFalse(ok)
        self.assertLessEqual(wait, 31)   # should be ≤ cooldown + 1
        self.assertGreater(wait, 0)

    def test_hourly_cap_blocks_after_limit(self):
        t = _fresh_throttle(cooldown=0, max_ph=2)
        # Burn through cap
        ok1, _ = t.check()
        ok2, _ = t.check()
        ok3, wait3 = t.check()
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertFalse(ok3)
        # wait3 is None when hourly cap is the limiting factor
        self.assertIsNone(wait3)

    def test_429_payload_has_wait_seconds_for_cooldown(self):
        """Verify the throttle returns wait_seconds (not None) for cooldown block."""
        t = _fresh_throttle(cooldown=120)
        t.check()
        ok, wait = t.check()
        self.assertFalse(ok)
        self.assertIsNotNone(wait)


# ── Unit: encounter normal flow ───────────────────────────────────────────────

class TestEncounterNormalFlow(unittest.TestCase):

    def setUp(self):
        explore.reset_throttle()   # ensure fresh state

    def test_encounter_returns_exchange_list(self):
        """Mock adapters: encounter should return 3 turns."""
        with patch.object(adapters, "run_adapter", return_value=(True, "測試回應")):
            ok, result = explore.run_encounter("A", "B", _CFG_TIGHT)
        self.assertTrue(ok)
        self.assertIn("exchange", result)
        self.assertIn("topic", result)
        self.assertIsInstance(result["exchange"], list)

    def test_encounter_turn_count_at_most_3(self):
        """Turn count must never exceed MAX_TURNS=3."""
        with patch.object(adapters, "run_adapter", return_value=(True, "一句話")):
            ok, result = explore.run_encounter("A", "B", _CFG_TIGHT)
        self.assertTrue(ok)
        self.assertLessEqual(len(result["exchange"]), explore.MAX_TURNS)

    def test_encounter_exchange_has_label_and_text(self):
        with patch.object(adapters, "run_adapter", return_value=(True, "回應")):
            ok, result = explore.run_encounter("A", "B", _CFG_TIGHT)
        self.assertTrue(ok)
        for turn in result["exchange"]:
            self.assertIn("label", turn)
            self.assertIn("text", turn)

    def test_encounter_alternates_a_b_a(self):
        """Labels must alternate A → B → A for a 3-turn exchange."""
        with patch.object(adapters, "run_adapter", return_value=(True, "回應")):
            ok, result = explore.run_encounter("A", "B", _CFG_TIGHT)
        self.assertTrue(ok)
        labels = [t["label"] for t in result["exchange"]]
        self.assertEqual(labels, ["A", "B", "A"])


# ── Unit: encounter throttle integration ─────────────────────────────────────

class TestEncounterThrottle(unittest.TestCase):

    def setUp(self):
        explore.reset_throttle()

    def test_second_encounter_immediately_returns_throttle_error(self):
        """Second call right after first should return wait_seconds in result."""
        with patch.object(adapters, "run_adapter", return_value=(True, "回應")):
            ok1, res1 = explore.run_encounter("A", "B", _CFG)
            ok2, res2 = explore.run_encounter("A", "B", _CFG)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertIn("wait_seconds", res2)
        self.assertTrue(res2.get("throttled"))

    def test_disabled_exploration_returns_error(self):
        ok, result = explore.run_encounter("A", "B", _CFG_DISABLED)
        self.assertFalse(ok)
        self.assertIn("error", result)


# ── Integration: server HTTP endpoint ────────────────────────────────────────

class TestServerExploreEndpoint(unittest.TestCase):
    """HTTP-level tests via embedded test server."""

    def setUp(self):
        import http.server
        import server as srv
        self._srv_mod = srv
        srv._config_cache = _CFG_TIGHT   # tight cooldown = 5 s
        explore.reset_throttle()

        self._server = http.server.HTTPServer(("127.0.0.1", 0), srv._Handler)
        self._port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._server.shutdown()
        import server as srv
        srv._config_cache = None
        explore.reset_throttle()

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

    def test_encounter_no_pin_returns_401(self):
        status, body = self._post("/api/explore/encounter", {"a": "A", "b": "B"})
        self.assertEqual(status, 401)

    def test_encounter_first_call_200(self):
        pin = self._srv_mod._PIN
        with patch.object(adapters, "run_adapter", return_value=(True, "mock回應")):
            status, body = self._post(
                "/api/explore/encounter", {"a": "A", "b": "B"}, pin=pin
            )
        self.assertEqual(status, 200)
        self.assertIn("exchange", body)
        self.assertIn("topic", body)

    def test_encounter_second_immediate_429(self):
        pin = self._srv_mod._PIN
        with patch.object(adapters, "run_adapter", return_value=(True, "mock回應")):
            s1, _ = self._post("/api/explore/encounter", {"a": "A", "b": "B"}, pin=pin)
            s2, body2 = self._post("/api/explore/encounter", {"a": "A", "b": "B"}, pin=pin)
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 429)
        self.assertIn("wait_seconds", body2)

    def test_encounter_missing_labels_returns_400(self):
        pin = self._srv_mod._PIN
        status, _ = self._post("/api/explore/encounter", {"a": "A"}, pin=pin)
        self.assertEqual(status, 400)

    def test_encounter_same_label_returns_400(self):
        pin = self._srv_mod._PIN
        status, _ = self._post("/api/explore/encounter", {"a": "A", "b": "A"}, pin=pin)
        self.assertEqual(status, 400)


# ── Config: exploration block read correctly ──────────────────────────────────

class TestExploreConfig(unittest.TestCase):

    def setUp(self):
        explore.reset_throttle()

    def test_default_cooldown_120(self):
        """No exploration key → default 120s cooldown."""
        cfg_no_exp = {k: v for k, v in _CFG.items() if k != "exploration"}
        t = explore.get_throttle(cfg_no_exp)
        self.assertEqual(t._cooldown, 120)

    def test_config_cooldown_respected(self):
        cfg = dict(_CFG, exploration={"enabled": True, "cooldown_seconds": 300, "max_exchanges_per_hour": 5})
        t = explore.get_throttle(cfg)
        self.assertEqual(t._cooldown, 300)
        self.assertEqual(t._max_per_hour, 5)

    def test_example_config_has_exploration_block(self):
        """config.example.json must have exploration key with required fields."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "config.example.json")
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertIn("exploration", cfg)
        exp = cfg["exploration"]
        self.assertIn("enabled", exp)
        self.assertIn("cooldown_seconds", exp)
        self.assertIn("max_exchanges_per_hour", exp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
