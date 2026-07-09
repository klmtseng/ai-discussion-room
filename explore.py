"""
Exploration mode logic for AI Discussion Room.
Manages roaming-encounter throttle (deterministic layer) and LLM turn generation.

Architecture principle: all throttle/counting is in this module (deterministic),
LLM calls happen only after passing throttle checks.
"""
import threading
import time
from typing import Optional, Tuple, List

import adapters
import anonymizer


# ---------------------------------------------------------------------------
# Default casual topics (used when no recent parliament question exists)
# ---------------------------------------------------------------------------

_CASUAL_TOPICS: List[str] = [
    "今天答得順嗎？",
    "你覺得主席公正嗎？",
    "這個會議室的空氣怎麼樣？",
    "你最近思考哪些有趣的問題？",
    "身為委員，你對彼此有什麼好奇的？",
    "今天的議題讓你學到什麼？",
    "如果可以改進議事方式，你會怎麼做？",
    "休息時間你通常在想什麼？",
    "你認為AI之間能建立真正的共識嗎？",
    "你有沒有什麼觀點想在正式議事外分享？",
]

_topic_index: int = 0
_topic_lock = threading.Lock()


def _next_casual_topic() -> str:
    global _topic_index
    with _topic_lock:
        topic = _CASUAL_TOPICS[_topic_index % len(_CASUAL_TOPICS)]
        _topic_index += 1
    return topic


# ---------------------------------------------------------------------------
# Rate-limit / throttle state
# ---------------------------------------------------------------------------

class ExploreThrottle:
    """
    All counting is deterministic — no LLM involved.
    Thread-safe via internal lock.
    """

    def __init__(self, cooldown_seconds: int = 120, max_per_hour: int = 10):
        self._lock = threading.Lock()
        self._cooldown = cooldown_seconds
        self._max_per_hour = max_per_hour
        self._last_ts: float = 0.0          # epoch of last successful encounter
        self._hour_bucket: float = 0.0      # start of current hour bucket (epoch)
        self._hour_count: int = 0           # encounters in current bucket

    def check(self) -> Tuple[bool, Optional[int]]:
        """
        Returns (ok, wait_seconds).
        ok=True  → caller may proceed; the counter is incremented atomically.
        ok=False → rate limited; wait_seconds is seconds until cooldown expires
                   OR None if hourly cap is the limit.
        """
        now = time.time()
        with self._lock:
            # Cooldown check
            elapsed = now - self._last_ts
            if elapsed < self._cooldown:
                wait = int(self._cooldown - elapsed) + 1
                return False, wait
            # Hourly cap check — reset bucket if > 1 hour old
            if now - self._hour_bucket > 3600:
                self._hour_bucket = now
                self._hour_count = 0
            if self._hour_count >= self._max_per_hour:
                return False, None   # hourly cap; tell client to wait
            # All clear — consume slot
            self._last_ts = now
            self._hour_count += 1
            return True, None


# ---------------------------------------------------------------------------
# Module-level throttle singleton
# ---------------------------------------------------------------------------

_throttle: Optional[ExploreThrottle] = None
_throttle_lock = threading.Lock()


def get_throttle(config: dict) -> ExploreThrottle:
    global _throttle
    with _throttle_lock:
        if _throttle is None:
            exp_cfg = config.get("exploration", {})
            cooldown = int(exp_cfg.get("cooldown_seconds", 120))
            max_ph = int(exp_cfg.get("max_exchanges_per_hour", 10))
            _throttle = ExploreThrottle(cooldown_seconds=cooldown, max_per_hour=max_ph)
        return _throttle


def reset_throttle():
    """For testing only: reset the module-level singleton."""
    global _throttle
    with _throttle_lock:
        _throttle = None


# ---------------------------------------------------------------------------
# Encounter: 3-turn dialogue
# ---------------------------------------------------------------------------

MAX_TURNS = 3   # hard-wired ceiling; must not be exceeded


def run_encounter(
    label_a: str,
    label_b: str,
    config: dict,
    recent_question: Optional[str] = None,
) -> Tuple[bool, dict]:
    """
    Generate a 3-turn exchange between label_a and label_b.
    Returns (ok, result_dict).

    result_dict on success: {exchange: [{label, text}, ...], topic: str}
    result_dict on failure: {error: str}
    """
    exp_cfg = config.get("exploration", {})
    if not exp_cfg.get("enabled", True):
        return False, {"error": "exploration disabled"}

    throttle = get_throttle(config)
    ok, wait = throttle.check()
    if not ok:
        if wait is not None:
            return False, {"wait_seconds": wait, "throttled": True}
        else:
            return False, {"hourly_cap": True, "throttled": True}

    # Topic selection
    topic = recent_question if recent_question else _next_casual_topic()

    # Retrieve member system_prompt for each participant
    members_cfg = anonymizer.members_from_config(config)
    member_system = config.get("member_system_prompt", "")

    def _get_system(adapter_name: str) -> str:
        override = next(
            (m.get("system_prompt", "") for m in members_cfg if m.get("adapter") == adapter_name),
            ""
        )
        return override or member_system

    # Resolve adapter names from config by label (we receive label strings from client)
    # For exploration, label→adapter isn't session-bound; we use config order as proxy.
    # Since labels (A, B, C…) are session-specific, we receive the label strings and
    # look them up in the config members list by position.
    labels_in_order = [chr(ord('A') + i) for i in range(len(members_cfg))]
    def _adapter_for_label(label: str) -> str:
        try:
            idx = labels_in_order.index(label)
            return members_cfg[idx]["adapter"]
        except (ValueError, IndexError, KeyError):
            return "claude"  # fallback

    adapter_a = _adapter_for_label(label_a)
    adapter_b = _adapter_for_label(label_b)
    sys_a = _get_system(adapter_a)
    sys_b = _get_system(adapter_b)
    model_a = next((m.get("model_arg") for m in members_cfg if m.get("adapter") == adapter_a), None)
    model_b = next((m.get("model_arg") for m in members_cfg if m.get("adapter") == adapter_b), None)

    exchange = []
    turn_count = 0
    context_text = ""   # running dialogue for B's reply

    # Turn 1: A opens (1-2 sentences)
    if turn_count >= MAX_TURNS:
        return True, {"exchange": exchange, "topic": topic}

    prompt_a1 = (
        f"{sys_a}\n\n"
        f"你的本輪代號是委員{label_a}。\n"
        f"你在會議室休息時間遇到了委員{label_b}。\n"
        f"話題背景：「{topic}」\n"
        f"請用1-2句輕鬆自然的中文說一句開場白。不要超過40個字。"
        f"嚴禁說出你是哪個AI品牌或模型。"
    )
    try:
        ok_a, text_a = adapters.run_adapter(adapter_a, prompt_a1, model_arg=model_a)
    except Exception as e:
        ok_a, text_a = False, str(e)

    if not ok_a:
        return False, {"error": f"adapter_a failed: {text_a[:100]}"}

    text_a = anonymizer.filter_self_id(text_a.strip(), label_a)
    exchange.append({"label": label_a, "text": text_a})
    context_text = f"委員{label_a}說：{text_a}"
    turn_count += 1

    # Turn 2: B replies to A
    if turn_count >= MAX_TURNS:
        return True, {"exchange": exchange, "topic": topic}

    prompt_b = (
        f"{sys_b}\n\n"
        f"你的本輪代號是委員{label_b}。\n"
        f"場景：會議室休息時間，話題背景：「{topic}」\n"
        f"{context_text}\n"
        f"請用1-2句自然的中文回應委員{label_a}。不要超過40個字。"
        f"嚴禁說出你是哪個AI品牌或模型。"
    )
    try:
        ok_b, text_b = adapters.run_adapter(adapter_b, prompt_b, model_arg=model_b)
    except Exception as e:
        ok_b, text_b = False, str(e)

    if not ok_b:
        return False, {"error": f"adapter_b failed: {text_b[:100]}"}

    text_b = anonymizer.filter_self_id(text_b.strip(), label_b)
    exchange.append({"label": label_b, "text": text_b})
    context_text += f"\n委員{label_b}說：{text_b}"
    turn_count += 1

    # Turn 3: A replies back
    if turn_count >= MAX_TURNS:
        return True, {"exchange": exchange, "topic": topic}

    prompt_a2 = (
        f"{sys_a}\n\n"
        f"你的本輪代號是委員{label_a}。\n"
        f"場景：會議室休息時間，話題背景：「{topic}」\n"
        f"{context_text}\n"
        f"請用1句話自然回應。不要超過30個字。"
        f"嚴禁說出你是哪個AI品牌或模型。"
    )
    try:
        ok_a2, text_a2 = adapters.run_adapter(adapter_a, prompt_a2, model_arg=model_a)
    except Exception as e:
        ok_a2, text_a2 = False, str(e)

    if ok_a2:
        text_a2 = anonymizer.filter_self_id(text_a2.strip(), label_a)
        exchange.append({"label": label_a, "text": text_a2})
        turn_count += 1

    return True, {"exchange": exchange, "topic": topic}
