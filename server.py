#!/usr/bin/env python3
"""
AI Parliament — HTTP Server
Python 3 stdlib only. Zero third-party dependencies.

Usage:
  python3 server.py            # real CLI mode
  python3 server.py --mock     # mock mode (no real CLI calls, for testing)
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# Must set mock mode BEFORE importing modules that read adapters._MOCK_MODE at import time
if "--mock" in sys.argv:
    os.environ["AI_PARLIAMENT_MOCK"] = "1"

import adapters  # noqa: E402  (mock env set above)
import parliament  # noqa: E402

PORT = 8930

_sessions: dict = {}
_sessions_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_config_cache: dict | None = None

def _load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ("config.json", "config.example.json"):
        path = os.path.join(base, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _config_cache = json.load(f)
            return _config_cache
    _config_cache = {}
    return _config_cache


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # silence access log
        pass

    # -- helpers --

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: str, content_type: str) -> None:
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)

    def _read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return None

    def _parts(self) -> list[str]:
        return [p for p in urlparse(self.path).path.split("/") if p]

    def _get_session(self, session_id: str) -> dict | None:
        with _sessions_lock:
            return _sessions.get(session_id)

    # -- OPTIONS (CORS pre-flight) --

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # -- GET --

    def do_GET(self) -> None:
        parts = self._parts()

        # Serve static UI
        if not parts or parts == ["index.html"]:
            base = os.path.dirname(os.path.abspath(__file__))
            self._send_file(os.path.join(base, "static", "index.html"), "text/html; charset=utf-8")
            return

        # GET /api/parliament/{id}
        if len(parts) == 3 and parts[:2] == ["api", "parliament"]:
            session = self._get_session(parts[2])
            if session is None:
                self._send_json(404, {"error": "session not found"})
                return
            self._send_json(200, parliament.public_view(session))
            return

        self.send_error(404)

    # -- POST --

    def do_POST(self) -> None:
        parts = self._parts()
        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        # POST /api/parliament  — start new session
        if parts == ["api", "parliament"]:
            question = (data.get("question") or "").strip()
            if not question:
                self._send_json(400, {"error": "question required"})
                return
            config = _load_config()
            session = parliament.create_session(question, config)
            with _sessions_lock:
                _sessions[session["id"]] = session
            t = threading.Thread(
                target=parliament.run_session,
                args=(session, _sessions_lock),
                daemon=True,
            )
            t.start()
            self._send_json(202, {"session_id": session["id"], "status": "running"})
            return

        # POST /api/parliament/{id}/followup
        if len(parts) == 4 and parts[:2] == ["api", "parliament"] and parts[3] == "followup":
            session = self._get_session(parts[2])
            if session is None:
                self._send_json(404, {"error": "session not found"})
                return
            member = data.get("member", "")
            question = (data.get("question") or "").strip()
            if member not in ("A", "B", "C") or not question:
                self._send_json(400, {"error": "member (A/B/C) and question required"})
                return
            config = _load_config()
            fid = parliament.add_followup(session, member, question, _sessions_lock)
            t = threading.Thread(
                target=parliament.run_followup,
                args=(session, fid, config, _sessions_lock),
                daemon=True,
            )
            t.start()
            self._send_json(202, {"followup_id": fid, "status": "running"})
            return

        # POST /api/parliament/{id}/summarize  — re-summarize after followups
        if len(parts) == 4 and parts[:2] == ["api", "parliament"] and parts[3] == "summarize":
            session = self._get_session(parts[2])
            if session is None:
                self._send_json(404, {"error": "session not found"})
                return
            config = _load_config()
            with _sessions_lock:
                session["chair_status"] = "pending"
                session["status"] = "running"
            t = threading.Thread(
                target=parliament.run_summary,
                args=(session, config, _sessions_lock, True),
                daemon=True,
            )
            t.start()
            self._send_json(202, {"status": "running"})
            return

        self.send_error(404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mock_tag = " [MOCK 模式]" if "--mock" in sys.argv else ""
    print(f"AI 眾議院啟動{mock_tag} → http://localhost:{PORT}")
    server = HTTPServer(("", PORT), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已關閉。")
