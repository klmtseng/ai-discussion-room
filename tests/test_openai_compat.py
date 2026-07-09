"""
Tests for the openai-compat adapter and server-side validation.

All HTTP interactions use a local threading.HTTPServer — no real external API calls.
Run: python3 -m pytest tests/test_openai_compat.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapters


# ---------------------------------------------------------------------------
# Tiny fake OpenAI-compat HTTP server for unit testing
# ---------------------------------------------------------------------------

def _make_fake_server(handler_class):
    """Spin up a local HTTP server on a random port; return (server, port)."""
    srv = HTTPServer(("127.0.0.1", 0), handler_class)
    port = srv.socket.getsockname()[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


class _OkHandler(BaseHTTPRequestHandler):
    """Returns a valid chat completion with content 'HELLO'."""
    def log_message(self, *_): pass
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "HELLO"}}]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _AuthEchoHandler(BaseHTTPRequestHandler):
    """Echoes the Authorization header in the response content."""
    def log_message(self, *_): pass
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        auth = self.headers.get("Authorization", "(none)")
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": auth}}]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Http401Handler(BaseHTTPRequestHandler):
    """Returns HTTP 401."""
    def log_message(self, *_): pass
    def do_POST(self):
        body = b'{"error":"unauthorized"}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Http500Handler(BaseHTTPRequestHandler):
    """Returns HTTP 500."""
    def log_message(self, *_): pass
    def do_POST(self):
        body = b'{"error":"server error"}'
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _BadJsonHandler(BaseHTTPRequestHandler):
    """Returns HTTP 200 with invalid JSON."""
    def log_message(self, *_): pass
    def do_POST(self):
        body = b'NOT JSON AT ALL {'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------

class TestOpenAICompatAdapterSuccess(unittest.TestCase):

    def setUp(self):
        self._srv, self._port = _make_fake_server(_OkHandler)

    def tearDown(self):
        self._srv.shutdown()

    def test_success_parse(self):
        ok, text = adapters._run_openai_compat("hello", {
            "base_url": f"http://127.0.0.1:{self._port}/v1",
            "model": "test-model",
        })
        self.assertTrue(ok)
        self.assertEqual(text, "HELLO")


class TestOpenAICompatAuth(unittest.TestCase):
    """Verify Authorization header behaviour."""

    def setUp(self):
        self._srv, self._port = _make_fake_server(_AuthEchoHandler)

    def tearDown(self):
        self._srv.shutdown()

    def test_no_api_key_env_sends_no_auth_header(self):
        """When api_key_env is absent, no Authorization header should be sent."""
        ok, text = adapters._run_openai_compat("hi", {
            "base_url": f"http://127.0.0.1:{self._port}/v1",
            "model": "llama3",
        })
        self.assertTrue(ok)
        self.assertEqual(text, "(none)")

    def test_api_key_env_empty_env_var_sends_no_auth_header(self):
        """When api_key_env is set but the env var is empty, no header should be sent."""
        env_name = "_TEST_COMPAT_KEY_EMPTY_"
        old = os.environ.pop(env_name, None)
        try:
            ok, text = adapters._run_openai_compat("hi", {
                "base_url": f"http://127.0.0.1:{self._port}/v1",
                "model": "llama3",
                "api_key_env": env_name,
            })
            self.assertTrue(ok)
            self.assertEqual(text, "(none)")
        finally:
            if old is not None:
                os.environ[env_name] = old

    def test_api_key_env_set_sends_bearer_header(self):
        """When api_key_env points to a populated env var, Bearer token must be sent."""
        env_name = "_TEST_COMPAT_KEY_LIVE_"
        os.environ[env_name] = "sk-test-secret"
        try:
            ok, text = adapters._run_openai_compat("hi", {
                "base_url": f"http://127.0.0.1:{self._port}/v1",
                "model": "llama3",
                "api_key_env": env_name,
            })
            self.assertTrue(ok)
            self.assertEqual(text, "Bearer sk-test-secret")
        finally:
            del os.environ[env_name]


class TestOpenAICompatHttpErrors(unittest.TestCase):

    def _run_with_handler(self, handler_class, cfg_extra=None):
        srv, port = _make_fake_server(handler_class)
        try:
            cfg = {"base_url": f"http://127.0.0.1:{port}/v1", "model": "m", **(cfg_extra or {})}
            return adapters._run_openai_compat("hi", cfg)
        finally:
            srv.shutdown()

    def test_http_401_returns_false_with_status(self):
        ok, text = self._run_with_handler(_Http401Handler)
        self.assertFalse(ok)
        self.assertIn("401", text)

    def test_http_500_returns_false_with_status(self):
        ok, text = self._run_with_handler(_Http500Handler)
        self.assertFalse(ok)
        self.assertIn("500", text)

    def test_bad_json_returns_false(self):
        ok, text = self._run_with_handler(_BadJsonHandler)
        self.assertFalse(ok)
        # Should mention format issue, not crash
        self.assertIn("openai-compat", text)

    def test_timeout_returns_false(self):
        """A port that refuses connections gives a URLError (connection refused)."""
        # Use a port we know nothing is listening on; use a small timeout via monkeypatching
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead_port = s.getsockname()[1]
        # dead_port is now freed — nothing listening
        orig_timeout = adapters.ADAPTERS["openai-compat"]["timeout"]
        adapters.ADAPTERS["openai-compat"]["timeout"] = 2
        try:
            ok, text = adapters._run_openai_compat("hi", {
                "base_url": f"http://127.0.0.1:{dead_port}/v1",
                "model": "m",
            })
            self.assertFalse(ok)
        finally:
            adapters.ADAPTERS["openai-compat"]["timeout"] = orig_timeout

    def test_missing_base_url_returns_false(self):
        ok, text = adapters._run_openai_compat("hi", {"model": "m"})
        self.assertFalse(ok)
        self.assertIn("base_url", text)

    def test_missing_model_returns_false(self):
        ok, text = adapters._run_openai_compat("hi", {"base_url": "http://localhost/v1"})
        self.assertFalse(ok)
        self.assertIn("model", text)


# ---------------------------------------------------------------------------
# run_adapter dispatch
# ---------------------------------------------------------------------------

class TestRunAdapterDispatch(unittest.TestCase):

    def setUp(self):
        self._srv, self._port = _make_fake_server(_OkHandler)

    def tearDown(self):
        self._srv.shutdown()

    def test_run_adapter_dispatches_openai_compat(self):
        seat_cfg = {
            "base_url": f"http://127.0.0.1:{self._port}/v1",
            "model": "test-model",
        }
        ok, text = adapters.run_adapter("openai-compat", "hi", seat_cfg=seat_cfg)
        self.assertTrue(ok)
        self.assertEqual(text, "HELLO")

    def test_run_adapter_mock_mode_ignores_compat(self):
        """Mock mode must return mock response regardless of seat_cfg."""
        orig = adapters._MOCK_MODE
        adapters._MOCK_MODE = True
        try:
            ok, text = adapters.run_adapter("openai-compat", "test question?", seat_cfg={})
            self.assertTrue(ok)
            self.assertIn("MOCK", text)
        finally:
            adapters._MOCK_MODE = orig

    def test_run_adapter_unknown_returns_false(self):
        ok, text = adapters.run_adapter("unknown-xyz", "hi")
        self.assertFalse(ok)
        self.assertIn("Unknown", text)


# ---------------------------------------------------------------------------
# Server PUT validation for openai-compat
# ---------------------------------------------------------------------------

class TestServerValidationOpenAICompat(unittest.TestCase):
    """Use the server._validate_members function directly."""

    def setUp(self):
        import server as srv
        self._validate = srv._validate_members

    def _two_seats(self, extra):
        """Return minimal 2-seat list with the extra dict as second seat."""
        return [
            {"id": "base", "model_display": "Base", "adapter": "claude"},
            extra,
        ]

    def test_valid_compat_seat_no_api_key(self):
        seats = self._two_seats({
            "id": "ollama",
            "model_display": "Ollama Llama",
            "adapter": "openai-compat",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
        })
        errors = self._validate(seats)
        self.assertEqual(errors, [])

    def test_valid_compat_seat_with_api_key_env(self):
        seats = self._two_seats({
            "id": "ds",
            "model_display": "DeepSeek",
            "adapter": "openai-compat",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key_env": "DEEPSEEK_API_KEY",
        })
        errors = self._validate(seats)
        self.assertEqual(errors, [])

    def test_missing_base_url_rejected(self):
        seats = self._two_seats({
            "id": "bad",
            "model_display": "Bad",
            "adapter": "openai-compat",
            "model": "llama3",
        })
        errors = self._validate(seats)
        self.assertTrue(any("base_url" in e for e in errors))

    def test_invalid_base_url_rejected(self):
        seats = self._two_seats({
            "id": "bad",
            "model_display": "Bad",
            "adapter": "openai-compat",
            "base_url": "ftp://not-http",
            "model": "llama3",
        })
        errors = self._validate(seats)
        self.assertTrue(any("base_url" in e for e in errors))

    def test_missing_model_rejected(self):
        seats = self._two_seats({
            "id": "bad",
            "model_display": "Bad",
            "adapter": "openai-compat",
            "base_url": "http://localhost/v1",
        })
        errors = self._validate(seats)
        self.assertTrue(any("model" in e for e in errors))

    def test_invalid_api_key_env_rejected(self):
        seats = self._two_seats({
            "id": "bad",
            "model_display": "Bad",
            "adapter": "openai-compat",
            "base_url": "http://localhost/v1",
            "model": "m",
            "api_key_env": "bad env name!",
        })
        errors = self._validate(seats)
        self.assertTrue(any("api_key_env" in e for e in errors))

    def test_valid_api_key_env_accepted(self):
        seats = self._two_seats({
            "id": "ok",
            "model_display": "OK",
            "adapter": "openai-compat",
            "base_url": "https://api.example.com/v1",
            "model": "some-model",
            "api_key_env": "SOME_API_KEY_123",
        })
        errors = self._validate(seats)
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Server test endpoint for openai-compat (via HTTP)
# ---------------------------------------------------------------------------

class TestServerTestEndpointCompat(unittest.TestCase):
    """Spin up a real parliament server + a fake compat endpoint."""

    def setUp(self):
        import server as srv
        import http.server as _hs

        self._srv_mod = srv

        # Temp config with 2 seats
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump({
            "members": [
                {"id": "claude", "model_display": "Claude", "adapter": "claude"},
                {"id": "codex",  "model_display": "ChatGPT", "adapter": "codex"},
            ]
        }, self._tmp)
        self._tmp.close()

        self._orig_override = srv._CONFIG_PATH_OVERRIDE
        srv._CONFIG_PATH_OVERRIDE = self._tmp.name
        srv._config_cache = None
        srv._test_cooldown_until = 0.0

        self._parliament_srv = _hs.HTTPServer(("127.0.0.1", 0), srv._Handler)
        self._parliament_port = self._parliament_srv.socket.getsockname()[1]
        t = threading.Thread(target=self._parliament_srv.serve_forever, daemon=True)
        t.start()

        # Fake compat endpoint
        self._compat_srv, self._compat_port = _make_fake_server(_OkHandler)

    def tearDown(self):
        self._parliament_srv.shutdown()
        self._compat_srv.shutdown()
        import server as srv
        srv._CONFIG_PATH_OVERRIDE = self._orig_override
        srv._config_cache = None
        srv._test_cooldown_until = 0.0
        os.unlink(self._tmp.name)

    def _req(self, method, path, body=None):
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self._parliament_port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Parliament-Pin", self._srv_mod._PIN)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {}

    def test_test_openai_compat_real_fake_endpoint(self):
        """POST /api/config/members/test with openai-compat pointing at our fake server."""
        status, body = self._req("POST", "/api/config/members/test", {
            "adapter": "openai-compat",
            "base_url": f"http://127.0.0.1:{self._compat_port}/v1",
            "model": "llama3",
        })
        self.assertEqual(status, 200)
        self.assertIn("ok", body)
        self.assertIn("latency_ms", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
