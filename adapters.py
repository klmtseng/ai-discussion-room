"""
CLI Adapters for AI Parliament.
To add a provider, add a new key to ADAPTERS and implement a _run_<name> function.

Mock mode: set MOCK_MODE = True (via adapters.set_mock_mode(True)) or
           export AI_PARLIAMENT_MOCK=1 before starting the server.
"""
import os
import re
import subprocess
import tempfile
import time
from typing import Tuple


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ADAPTERS: dict = {
    "claude": {
        "label": "Claude",
        "timeout": 120,
    },
    "codex": {
        "label": "ChatGPT (Codex)",
        "timeout": 120,
    },
    "gemini": {
        "label": "Gemini",
        "timeout": 120,
    },
}

_MOCK_MODE: bool = os.environ.get("AI_PARLIAMENT_MOCK", "").lower() in ("1", "true", "yes")


def set_mock_mode(enabled: bool) -> None:
    global _MOCK_MODE
    _MOCK_MODE = enabled


# ---------------------------------------------------------------------------
# Noise filter patterns (applied line-by-line before returning output)
# ---------------------------------------------------------------------------

_NOISE: dict = {
    "gemini": [
        re.compile(r"^Ripgrep is not available", re.IGNORECASE),
        re.compile(r"^Using model:", re.IGNORECASE),
        re.compile(r"^Loaded \d+ tool", re.IGNORECASE),
        re.compile(r"^\s*$"),
    ],
    "codex": [
        # fallback when --output-last-message is unavailable or empty
        re.compile(r"^(Tokens used|Session ID|Running|Executing|\$\s|>\s)"),
        re.compile(r"^\s*$"),
    ],
    "claude": [],
}


def filter_noise(text: str, adapter_name: str) -> str:
    """Strip known noise lines from CLI output. Public for testing."""
    patterns = _NOISE.get(adapter_name, [])
    if not patterns:
        return text.strip()
    lines = text.splitlines()
    clean = [ln for ln in lines if not any(p.search(ln) for p in patterns)]
    return "\n".join(clean).strip()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_adapter(name: str, prompt: str, model_arg: str = None) -> Tuple[bool, str]:
    """
    Run CLI adapter `name` with `prompt`.
    model_arg (optional, from the member's config entry) selects a specific
    model within the CLI: gemini `-m`, claude `--model`. Codex ignores it.
    Returns (success: bool, text: str).
    On failure text is a human-readable error description (no stack trace).
    """
    if _MOCK_MODE:
        return _run_mock(name, prompt)
    if name == "claude" or name.startswith("claude"):
        return _run_claude(prompt, model_arg)
    if name == "codex":
        return _run_codex(prompt)
    if name == "gemini" or name.startswith("gemini"):
        return _run_gemini(prompt, model_arg)
    return False, f"Unknown adapter: {name}"


# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------

def _run_mock(name: str, prompt: str) -> Tuple[bool, str]:
    time.sleep(0.3)  # simulate latency
    short = prompt[:60].replace("\n", " ")
    responses = {
        "claude": (
            f"[MOCK Claude] 關於「{short}」：這是一個值得深思的問題。我認為需要從多個角度來分析。\n"
            f"【結論】此議題需要多角度評估，建議審慎權衡利弊。"
        ),
        "codex": (
            f"[MOCK Codex] 針對「{short}」：從技術角度來看，有幾個關鍵點值得注意。\n"
            f"【結論】從技術視角看，關鍵在於找到可操作的具體解方。"
        ),
        "gemini": (
            f"[MOCK Gemini] 就「{short}」而言：根據現有資訊，可以從以下幾個維度思考。\n"
            f"【結論】綜合多維度分析，此問題有清晰的邏輯路徑可循。"
        ),
        # Extra mock adapters for N-member tests
        "gemini-pro": (
            f"[MOCK Gemini Pro] 關於「{short}」：從高層次分析，有幾個值得注意的面向。\n"
            f"【結論】高層次分析顯示此議題需要結構性的解決方案。"
        ),
        "claude-extra": (
            f"[MOCK Claude-2] 針對「{short}」：從另一個角度補充，這個問題有多個層面。\n"
            f"【結論】補充視角顯示問題多層面，整合觀點不可或缺。"
        ),
    }
    default_resp = (
        f"[MOCK {name}] 已收到問題。\n"
        f"【結論】已收到議題，立場待進一步釐清。"
    )
    return True, responses.get(name, default_resp)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def _run_claude(prompt: str, model_arg: str = None) -> Tuple[bool, str]:
    cmd = [
        "claude", "-p", prompt,
        "--disallowedTools", "Bash,Edit,Write,WebFetch,Read,TodoWrite,TodoRead",
    ]
    if model_arg:
        cmd += ["--model", model_arg]
    timeout = ADAPTERS["claude"]["timeout"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = r.stdout.strip()
        if r.returncode != 0 and not text:
            return False, f"claude rc={r.returncode}: {r.stderr[:300]}"
        return bool(text), text or f"(no output rc={r.returncode})"
    except subprocess.TimeoutExpired:
        return False, "claude: timeout after 120s"
    except FileNotFoundError:
        return False, "claude: CLI not found — install Claude Code"


# ---------------------------------------------------------------------------
# Codex (ChatGPT / OpenAI)
# ---------------------------------------------------------------------------

def _run_codex(prompt: str) -> Tuple[bool, str]:
    timeout = ADAPTERS["codex"]["timeout"]
    # Create a temp file for --output-last-message (clean final answer)
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="ap_codex_"
    )
    tmpfile = tf.name
    tf.close()

    cmd = [
        "codex", "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox", "read-only",
        "--output-last-message", tmpfile,
        "--",  # defence-in-depth: never let a dash-leading prompt parse as a flag
        prompt,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        # Prefer clean file output
        try:
            with open(tmpfile) as f:
                file_text = f.read().strip()
        except OSError:
            file_text = ""

        if file_text:
            return True, file_text

        # Fallback: filter noise from stdout
        stdout_text = filter_noise(r.stdout, "codex")
        if stdout_text:
            return True, stdout_text

        return False, f"codex: no output (rc={r.returncode}) stderr={r.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return False, "codex: timeout after 120s"
    except FileNotFoundError:
        return False, "codex: CLI not found — install OpenAI Codex CLI and authenticate"
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _run_gemini(prompt: str, model_arg: str = None) -> Tuple[bool, str]:
    timeout = ADAPTERS["gemini"]["timeout"]
    env = {**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"}
    cmd = ["gemini", "-p", prompt, "-m", model_arg or "gemini-2.5-flash"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        text = filter_noise(r.stdout, "gemini")
        if r.returncode != 0 and not text:
            return False, f"gemini rc={r.returncode}: {r.stderr[:300]}"
        return bool(text), text or f"(no output rc={r.returncode})"
    except subprocess.TimeoutExpired:
        return False, "gemini: timeout after 120s"
    except FileNotFoundError:
        return False, "gemini: CLI not found — install Gemini CLI"
