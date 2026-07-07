"""
Anonymization layer for AI Parliament.

Two jobs:
  1. create_shuffle(seed) → random {label: adapter} mapping reproducible per seed.
  2. filter_self_id(text, label) → strip/replace AI self-identification phrases.
  3. build_chair_prompt(…) → construct chair input with zero model names.
"""
import random
import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Shuffle
# ---------------------------------------------------------------------------

ADAPTER_NAMES = ["claude", "codex", "gemini"]
LABELS = ["A", "B", "C"]


def create_shuffle(seed: int) -> Dict[str, str]:
    """
    Returns {label: adapter_name} mapping for one session round.
    Same seed always produces the same mapping (deterministic for debug).
    """
    rng = random.Random(seed)
    adapters = ADAPTER_NAMES[:]
    rng.shuffle(adapters)
    return dict(zip(LABELS, adapters))


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
]


def filter_self_id(text: str, label: str) -> str:
    """Replace self-identification phrases with [委員{label}]."""
    replacement = f"[委員{label}]"
    for pattern in _SELF_ID_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Chair prompt builder
# ---------------------------------------------------------------------------

def build_chair_prompt(
    question: str,
    anon_responses: Dict[str, str],
    member_statuses: Dict[str, str],
    chair_system: str,
    is_resummary: bool = False,
    followup_summaries: Optional[List[dict]] = None,
) -> str:
    """
    Build the chair prompt. Guarantees zero AI model names in member sections.

    anon_responses: {label: already-filtered response text}
    member_statuses: {label: "done"|"error"|"running"}
    """
    parts: List[str] = []

    if chair_system:
        parts.append(chair_system)
        parts.append("")

    if is_resummary:
        parts.append(f"本輪議題（再總結）：{question}")
        parts.append("")
        parts.append("以下為三位委員的初始回答及後續深聊補充，請重新總結：")
    else:
        parts.append(f"本輪議題：{question}")
        parts.append("")
        parts.append("以下為三位匿名委員的回答，請進行分析：")

    parts.append("")

    for label in LABELS:
        status = member_statuses.get(label, "error")
        if status == "done":
            resp = anon_responses.get(label, "(無內容)")
            parts.append(f"【委員{label}】")
            parts.append(resp)
        else:
            parts.append(f"【委員{label}】（本席缺席）")
        parts.append("")

    if is_resummary and followup_summaries:
        parts.append("── 深聊補充 ──")
        parts.append("")
        for fs in followup_summaries:
            label = fs.get("member", "?")
            q = fs.get("question", "")
            a = fs.get("response", "")
            if a:
                parts.append(f"委員{label} 被追問：{q}")
                parts.append(f"委員{label} 補充：{filter_self_id(a, label)}")
                parts.append("")

    parts.append("請輸出以下三部分：")
    parts.append("1. 共識點（三方一致或高度相近的觀點）")
    parts.append("2. 分歧點（觀點有明顯差異或矛盾之處）")
    parts.append("3. 綜合結論（主席裁量的整合意見）")
    parts.append("")
    parts.append(
        "重要：回答中嚴禁出現 Claude、ChatGPT、Gemini、Bard、Codex、"
        "Anthropic、OpenAI、Google 等品牌名稱；請一律稱「委員A/B/C」。"
    )

    return "\n".join(parts)
