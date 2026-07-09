"""
Anonymization layer for AI Parliament.

Two jobs:
  1. create_shuffle(seed, adapter_names) → random {label: adapter_name} mapping.
  2. filter_self_id(text, label) → strip/replace AI self-identification phrases.
  3. build_chair_prompt(…) → construct chair input with zero model names.

Upgrade 2: public_model_display_map(config) — returns {label: model_display}
  for use in public_view only; NEVER passed to chair prompt.
Upgrade 3: N-member support — labels generated as A,B,C,D… from member count.
"""
import random
import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------

import string

def _make_labels(n: int) -> List[str]:
    """Generate n labels: A, B, C, … Z, AA, AB, …"""
    labels = []
    for i in range(n):
        if i < 26:
            labels.append(string.ascii_uppercase[i])
        else:
            labels.append(string.ascii_uppercase[i // 26 - 1] + string.ascii_uppercase[i % 26])
    return labels


# ---------------------------------------------------------------------------
# Shuffle
# ---------------------------------------------------------------------------

# Legacy constants — kept for backward compat and tests that import them directly
ADAPTER_NAMES = ["claude", "codex", "gemini"]
LABELS = ["A", "B", "C"]


def create_shuffle(seed: int, adapter_names: Optional[List[str]] = None) -> Dict[str, str]:
    """
    Returns {label: adapter_name} mapping for one session round.
    Same seed always produces the same mapping (deterministic for debug).
    adapter_names defaults to the legacy 3-adapter list for backward compat.
    """
    if adapter_names is None:
        adapter_names = ADAPTER_NAMES[:]
    labels = _make_labels(len(adapter_names))
    rng = random.Random(seed)
    adapters_copy = adapter_names[:]
    rng.shuffle(adapters_copy)
    return dict(zip(labels, adapters_copy))


# ---------------------------------------------------------------------------
# Config helpers (Upgrade 2 & 3)
# ---------------------------------------------------------------------------

def members_from_config(config: dict) -> List[dict]:
    """Return the members list from config, or a legacy default for old configs."""
    members = config.get("members")
    if members and isinstance(members, list) and len(members) > 0:
        return members
    # Legacy: no members array — use built-in defaults
    return [
        {"id": "claude", "model_display": "Claude", "adapter": "claude", "color": "#e07830", "emblem": "star"},
        {"id": "codex",  "model_display": "ChatGPT", "adapter": "codex",  "color": "#10b8a0", "emblem": "knot"},
        {"id": "gemini", "model_display": "Gemini",  "adapter": "gemini", "color": "#8060e8", "emblem": "quad"},
    ]


def public_model_display_map(config: dict) -> Dict[str, str]:
    """
    Return {label: model_display} for use in public view JSON ONLY.
    Labels are A, B, C, … assigned in config order (not shuffle order — intentionally;
    shuffle is internal and labels are the only public identity).
    NOTE: This map MUST NEVER be passed to the chair prompt.
    """
    members = members_from_config(config)
    labels = _make_labels(len(members))
    # We return label→model_display in CONFIG order (not shuffle order).
    # The shuffle maps label→adapter internally, but the user-facing model_display
    # is assigned per-label AFTER shuffle is resolved in parliament.py.
    return {}  # populated per-session by parliament.py, not here


def resolve_label_display(shuffle_map: Dict[str, str], config: dict) -> Dict[str, str]:
    """
    Given shuffle_map = {label: adapter_id} and config, return {label: model_display}.
    This is the post-shuffle mapping: label A might map to Claude in one session,
    ChatGPT in another. model_display follows the actual adapter, not config order.
    """
    members = members_from_config(config)
    adapter_to_display = {m["adapter"]: m.get("model_display", m["adapter"]) for m in members}
    return {label: adapter_to_display.get(adapter, adapter) for label, adapter in shuffle_map.items()}


def resolve_label_meta(shuffle_map: Dict[str, str], config: dict) -> Dict[str, dict]:
    """
    Return {label: {model_display, color, emblem}} following shuffle.
    Safe to send to public view; NEVER to chair.
    """
    members = members_from_config(config)
    adapter_meta = {m["adapter"]: {
        "model_display": m.get("model_display", m["adapter"]),
        "color": m.get("color", "#888888"),
        "emblem": m.get("emblem", "dot"),
    } for m in members}
    return {label: adapter_meta.get(adapter, {"model_display": adapter, "color": "#888888", "emblem": "dot"})
            for label, adapter in shuffle_map.items()}


# ---------------------------------------------------------------------------
# Self-identification filter
# ---------------------------------------------------------------------------

# Patterns that reveal which AI model is speaking.
# Each is replaced with f"[委員{label}]".
_SELF_ID_PATTERNS: List[re.Pattern] = [
    # English — direct name announcement
    re.compile(
        r"\b(I'?m|I am|This is|As|Hi,?\s*I'?m|Hello,?\s*I'?m)\s+"
        r"(Claude|ChatGPT|GPT-?4?o?|Gemini|Bard|Codex)\b",
        re.IGNORECASE,
    ),
    # English — name + role verb
    re.compile(
        r"\b(Claude|ChatGPT|GPT-?4?o?|Gemini|Bard|Codex)\s+"
        r"(here|speaking|says?|responds?|answering)\b",
        re.IGNORECASE,
    ),
    # English — "As Claude / As an AI by OpenAI"
    re.compile(
        r"\bAs\s+an?\s+(Claude|ChatGPT|GPT-?4?o?|Gemini|Bard|Codex)\b",
        re.IGNORECASE,
    ),
    # English — "I'm an AI made by Anthropic"
    re.compile(
        r"\bI'?m\s+an?\s+(AI|language model|LLM)\s+(made|created|built|developed)\s+by\s+"
        r"(Anthropic|OpenAI|Google)\b",
        re.IGNORECASE,
    ),
    # English — "Anthropic's Claude / OpenAI's model"
    re.compile(
        r"\b(Anthropic|OpenAI|Google DeepMind|Google)\s*'?s\s+"
        r"(Claude|ChatGPT|Gemini|AI|model|assistant)\b",
        re.IGNORECASE,
    ),
    # Chinese — 我是Claude/ChatGPT/Gemini
    re.compile(
        r"我是\s*(Claude|ChatGPT|Gemini|GPT|Bard|Codex|AI助手|語言模型)[，。,！!]?",
        re.IGNORECASE,
    ),
    # Chinese — Claude在此/回答/表示
    re.compile(
        r"(Claude|ChatGPT|Gemini|Bard|Codex)\s*(在此|回答|回覆|表示|認為|說)",
        re.IGNORECASE,
    ),
    # Chinese — 身為AI/語言模型/Claude
    re.compile(
        r"身為\s*(Claude|ChatGPT|Gemini|Bard|Codex|AI|語言模型|大型語言模型)",
        re.IGNORECASE,
    ),
    # Chinese — 作為Anthropic/OpenAI/Google的AI
    re.compile(
        r"作為\s*(Anthropic|OpenAI|Google)\s*(的)?\s*(AI|助手|模型|系統)",
        re.IGNORECASE,
    ),
    # Chinese — 由Anthropic/OpenAI/Google開發
    re.compile(
        r"由\s*(Anthropic|OpenAI|Google)\s*(開發|製造|訓練|設計)",
        re.IGNORECASE,
    ),
    # Chinese — 我是由…訓練的
    re.compile(
        r"我是由\s*(Anthropic|OpenAI|Google)\s*(訓練|開發|製造)",
        re.IGNORECASE,
    ),
    # --- hardening (validity-audit 2026-07-08): mid-sentence self-reference ---
    # English — "(made|trained|...) by Anthropic/OpenAI/Google" anywhere
    re.compile(
        r"\b(made|created|built|developed|trained|designed)\s+by\s+"
        r"(Anthropic|OpenAI|Google(\s+DeepMind)?)\b",
        re.IGNORECASE,
    ),
    # English — "Anthropic/OpenAI/Google trained/made me"
    re.compile(
        r"\b(Anthropic|OpenAI|Google(\s+DeepMind)?)\s+"
        r"(trained|made|created|built|developed)\s+me\b",
        re.IGNORECASE,
    ),
    # Both — model name + 模型/助手/系統 suffix (residual after 我是由… match)
    re.compile(
        r"(Claude|ChatGPT|Gemini|Bard|Codex|GPT[-\w.]*)\s*(模型|助手|系統)",
        re.IGNORECASE,
    ),
    # Chinese — 作為/身為 + 廠商的 + 模型名
    re.compile(
        r"(作為|身為|做為)\s*(Anthropic|OpenAI|Google)?\s*(的)?\s*"
        r"(Claude|ChatGPT|Gemini|Bard|Codex|GPT[-\w.]*)",
        re.IGNORECASE,
    ),
    # Chinese — (OpenAI|...)(訓練|開發)了?我
    re.compile(
        r"(Anthropic|OpenAI|Google)\s*(訓練|開發|製造|創造)(了)?我",
        re.IGNORECASE,
    ),
    # Both — "GPT-4 級別的我 / Claude-level me"
    re.compile(
        r"(Claude|ChatGPT|Gemini|GPT[-\w.]*)\s*(級別|等級)?的我",
        re.IGNORECASE,
    ),
    # Self-referring product URLs
    re.compile(
        r"\b(claude\.ai|chat\.openai\.com|chatgpt\.com|gemini\.google\.com)\b",
        re.IGNORECASE,
    ),
]


def filter_self_id(text: str, label: str, lang: str = "zh") -> str:
    """Replace self-identification phrases with [委員{label}] (zh) or [Member {label}] (en)."""
    replacement = f"[Member {label}]" if lang == "en" else f"[委員{label}]"
    for pattern in _SELF_ID_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Chair prompt builder
# ---------------------------------------------------------------------------

# Hard backstop for chair-bound text (VA cold review 2026-07-08, P2-1):
# filter_self_id is a best-effort blocklist and WILL miss novel phrasings
# ("This response comes from Gemini", "My name is Claude", …). For the chair,
# attribution safety beats content fidelity, so every occurrence of a model /
# vendor brand in member-derived text is redacted at this single choke point.
# The user-visible response text is NOT redacted (users see who is who anyway).
_BRAND_RE = re.compile(
    # Bare "Google" IS included (VA hot review P1-1): "my developer is Google"
    # is the most natural Gemini self-attribution. In chair-bound text,
    # attribution safety beats content fidelity — a neutral mention of
    # Google-the-company being redacted is acceptable collateral.
    r"\b(Claude|ChatGPT|GPT[-\w.]*|Gemini|Bard|Codex|Copilot|"
    r"Anthropic|OpenAI|Google(\s+DeepMind)?|DeepMind|Meta|xAI|Grok|"
    r"Mistral|Llama|DeepSeek|Qwen)\b",
    re.IGNORECASE,
)


def redact_model_names(text: str, extra_brands: Optional[List[str]] = None, lang: str = "zh") -> str:
    """
    Replace every model/vendor brand token with [某AI] (zh) or [an AI] (en).
    Chair-bound text only.

    extra_brands: brand strings derived from the runtime config (each member's
    model_display and adapter id), so custom seats added via config are
    redacted too even if absent from the static list (VA hot review P2-1).
    """
    token = "[an AI]" if lang == "en" else "[某AI]"
    text = _BRAND_RE.sub(token, text)
    for brand in extra_brands or []:
        for t in re.split(r"[\s/_-]+", str(brand)):
            if len(t) >= 3 and not t.isdigit():
                text = re.sub(rf"(?i)\b{re.escape(t)}\b", token, text)
    return text


def build_chair_prompt(
    question: str,
    anon_responses: Dict[str, str],
    member_statuses: Dict[str, str],
    chair_system: str,
    is_resummary: bool = False,
    followup_summaries: Optional[List[dict]] = None,
    labels: Optional[List[str]] = None,
    extra_brands: Optional[List[str]] = None,
    lang: str = "zh",
) -> str:
    """
    Build the chair prompt. Member sections are pre-filtered by filter_self_id
    (best-effort) and then hard-redacted by redact_model_names at this choke
    point, so the assembled prompt structurally contains no brand tokens in
    member-derived text. The main question is user-authored and shared by all
    members (no attribution signal), so it is intentionally NOT redacted.

    anon_responses: {label: already-filtered response text}
    member_statuses: {label: "done"|"error"|"running"}
    labels: ordered list of labels; defaults to LABELS (A,B,C) for backward compat.
    """
    if labels is None:
        # Use member_statuses keys (includes absent members); fall back to anon_responses keys
        labels = list(member_statuses.keys()) or list(anon_responses.keys()) or LABELS

    n = len(labels)
    is_en = lang == "en"

    if is_en:
        label_list = "/".join(f"Member {l}" for l in labels)
    else:
        label_list = "/".join(f"委員{l}" for l in labels)

    parts: List[str] = []

    if chair_system:
        parts.append(chair_system)
        parts.append("")

    if is_en:
        if is_resummary:
            parts.append(f"Agenda item (re-summary): {question}")
            parts.append("")
            parts.append(f"Below are the {n} members' initial responses and follow-up exchanges. Please re-summarise:")
        else:
            parts.append(f"Agenda item: {question}")
            parts.append("")
            parts.append(f"Below are {n} anonymous members' responses. Please analyse:")
    else:
        if is_resummary:
            parts.append(f"本輪議題（再總結）：{question}")
            parts.append("")
            parts.append(f"以下為{n}位委員的初始回答及後續深聊補充，請重新總結：")
        else:
            parts.append(f"本輪議題：{question}")
            parts.append("")
            parts.append(f"以下為{n}位匿名委員的回答，請進行分析：")

    parts.append("")

    for label in labels:
        status = member_statuses.get(label, "error")
        member_tag = f"[Member {label}]" if is_en else f"【委員{label}】"
        absent_note = f"(absent this session)" if is_en else "（本席缺席）"
        if status == "done":
            resp = redact_model_names(anon_responses.get(label, "(no content)" if is_en else "(無內容)"), extra_brands, lang=lang)
            parts.append(member_tag)
            parts.append(resp)
        else:
            parts.append(f"{member_tag}{absent_note}")
        parts.append("")

    if is_resummary and followup_summaries:
        parts.append("── Follow-up exchanges ──" if is_en else "── 深聊補充 ──")
        parts.append("")
        for fs in followup_summaries:
            label = fs.get("member", "?")
            q = fs.get("question", "")
            a = fs.get("response", "")
            if a:
                if is_en:
                    parts.append(f"Member {label} was asked: {redact_model_names(q, extra_brands, lang=lang)}")
                    parts.append(f"Member {label} replied: {redact_model_names(filter_self_id(a, label, lang=lang), extra_brands, lang=lang)}")
                else:
                    parts.append(f"委員{label} 被追問：{redact_model_names(q, extra_brands, lang=lang)}")
                    parts.append(f"委員{label} 補充：{redact_model_names(filter_self_id(a, label, lang=lang), extra_brands, lang=lang)}")
                parts.append("")

    if is_en:
        parts.append("Please output the following four sections:")
        parts.append("1. Consensus (points where all members substantially agree)")
        parts.append("2. Divergences (points of clear disagreement or contradiction)")
        parts.append(
            "3. Minority Report (per unresolved aspect: which member dissents and their "
            "strongest argument in one sentence; write \"None — unanimous\" if all agree)"
        )
        parts.append(
            "4. Chair's Synthesis (the chair's integrative conclusion; if no substantial "
            "consensus exists, you may declare \"no consensus\" and stop after the Minority Report "
            "rather than forcing a compromise)"
        )
        parts.append("")
        parts.append(
            "Important: do NOT include any AI brand names (Claude, ChatGPT, Gemini, Bard, Codex, "
            "Anthropic, OpenAI, Google, etc.) anywhere in your response; "
            "refer to members only as " + label_list + "."
        )
    else:
        parts.append("請輸出以下四部分：")
        parts.append("1. 共識點（各委員一致或高度相近的觀點）")
        parts.append("2. 分歧點（觀點有明顯差異或矛盾之處）")
        parts.append(
            "3. 少數派報告（針對每個未收斂的面向：哪位委員持異議，及其最強論據，一句話；"
            "若全體一致，此節寫「無——全體一致」）"
        )
        parts.append(
            "4. 綜合結論（主席裁量的整合意見；若實質共識不存在，"
            "允許明說「本題無共識」並止於少數派報告，不強行折衷）"
        )
        parts.append("")
        parts.append(
            "重要：回答中嚴禁出現 Claude、ChatGPT、Gemini、Bard、Codex、"
            "Anthropic、OpenAI、Google 等品牌名稱；請一律稱「" + label_list + "」。"
        )

    return "\n".join(parts)
