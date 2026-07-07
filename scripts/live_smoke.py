#!/usr/bin/env python3
"""
Live integration smoke test — calls real CLIs (uses your subscription).

By default tests gemini and codex only (fastest + cheapest).
Add --all to include claude.

Usage:
  python3 scripts/live_smoke.py
  python3 scripts/live_smoke.py --all
"""
import os
import sys
import time

# Path to project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import adapters  # noqa: E402

# Make sure mock mode is off
adapters.set_mock_mode(False)

QUESTION = "用一句話回答：1加1等於多少？"
TIMEOUT = 120


def _run(name: str) -> bool:
    print(f"\n{'='*50}")
    print(f"[{name.upper()}] 提問：{QUESTION}")
    print(f"{'='*50}")
    t0 = time.time()
    success, text = adapters.run_adapter(name, QUESTION)
    elapsed = time.time() - t0
    print(f"成功：{success}  耗時：{elapsed:.1f}s")
    print(f"回覆（前300字）：\n{text[:300]}")
    if not success:
        print(f"[FAIL] {name}: {text}")
    return success


def main():
    run_all = "--all" in sys.argv
    tests = ["gemini", "codex"]
    if run_all:
        tests.append("claude")
    else:
        print("(claude 測試已跳過；加 --all 可一併測試)")

    passed = []
    failed = []

    for name in tests:
        try:
            ok = _run(name)
            (passed if ok else failed).append(name)
        except Exception as e:
            print(f"[EXCEPTION] {name}: {e}")
            failed.append(name)

    print(f"\n{'='*50}")
    print(f"通過：{passed}")
    print(f"失敗：{failed}")
    print(f"{'='*50}")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
