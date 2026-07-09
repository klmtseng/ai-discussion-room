"""
Core orchestration for AI Discussion Room.
Manages sessions, member calls (parallel), chair summaries, and followups.
All state lives in-memory (dict). Thread-safe via a caller-supplied lock.

Upgrade 2: public_view() includes model_display per label (from shuffle resolution).
           Chair prompt NEVER receives model_display — enforced here.
Upgrade 3: N-member support driven by config["members"] array.
"""
import random
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import adapters
import anonymizer


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def create_session(question: str, config: dict, lang: str = "zh") -> dict:
    # Normalise lang: only "en" is accepted; anything else falls back to "zh"
    if lang not in ("zh", "en"):
        lang = "zh"
    members_cfg = anonymizer.members_from_config(config)
    # Build id→member dict for O(1) lookups — avoids adapter-keyed collisions when
    # two seats share the same adapter (e.g. Gemini Flash + Gemini Pro).
    id_to_member = {m["id"]: m for m in members_cfg}
    member_ids = [m["id"] for m in members_cfg]
    seed = random.randint(0, 2**31 - 1)
    shuffle_map = anonymizer.create_shuffle(seed, member_ids)  # {label → member_id}
    label_meta = anonymizer.resolve_label_meta(shuffle_map, config)  # {label → {model_display, color, emblem}}
    return {
        "id": str(uuid.uuid4())[:8],
        "question": question,
        "lang": lang,
        "status": "running",
        "created_at": time.time(),
        "_debug_seed": seed,
        "_debug_shuffle": shuffle_map,   # label → member_id (debug only, never sent to chair)
        "_label_meta": label_meta,       # label → {model_display, color, emblem} (public view only)
        "members": {
            label: {
                "status": "running",
                "response": None,
                "error": None,
                "conclusion": None,       # deterministic extraction; None until done
                "_member_id": member_id,
                "_adapter": id_to_member[member_id]["adapter"],
                "_model_arg": id_to_member[member_id].get("model_arg"),
                "conversation": [],       # [{role, content}, …]
            }
            for label, member_id in shuffle_map.items()
        },
        "chair_status": "pending",
        "chair_summary": None,
        "followups": [],                  # [{id, member, question, response, status}]
        "_config": config,
    }


# ---------------------------------------------------------------------------
# Public view (strips private fields for JSON response)
# ---------------------------------------------------------------------------

def public_view(session: dict) -> dict:
    label_meta = session.get("_label_meta", {})
    return {
        "session_id": session["id"],
        "question": session["question"],
        "lang": session.get("lang", "zh"),
        "status": session["status"],
        "chair_status": session["chair_status"],
        "members": {
            label: {
                "status": m["status"],
                "response": m.get("response"),
                "error": m.get("error"),
                "conclusion": m.get("conclusion"),  # deterministic; None = not provided
                "conversation_turns": len(m.get("conversation", [])) // 2,
                # Upgrade 2: expose model_display in public view (NOT in chair prompt)
                "model_display": label_meta.get(label, {}).get("model_display", ""),
                "color": label_meta.get(label, {}).get("color", "#888888"),
                "emblem": label_meta.get(label, {}).get("emblem", "dot"),
            }
            for label, m in session["members"].items()
        },
        "chair_summary": session.get("chair_summary"),
        "followups": [
            {
                "id": f["id"],
                "member": f["member"],
                "question": f["question"],
                "response": f.get("response"),
                "status": f["status"],
            }
            for f in session.get("followups", [])
        ],
    }


# ---------------------------------------------------------------------------
# Session runner (called in a daemon thread)
# ---------------------------------------------------------------------------

def run_session(session: dict, lock: threading.Lock) -> None:
    """Run all member calls in parallel, then trigger chair summary."""
    labels = list(session["members"].keys())
    try:
        threads = [
            threading.Thread(target=_run_member, args=(session, label, lock), daemon=True)
            for label in labels
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        run_summary(session, session["_config"], lock, is_resummary=False)
    except Exception as exc:
        with lock:
            session["status"] = "error"
            session["chair_status"] = "error"
            _lang = session.get("lang", "zh")
            session["chair_summary"] = f"(System error: {exc})" if _lang == "en" else f"(系統錯誤: {exc})"


def _run_member(session: dict, label: str, lock: threading.Lock) -> None:
    member_slot = session["members"][label]
    adapter_name = member_slot["_adapter"]
    member_id = member_slot["_member_id"]
    config = session["_config"]
    question = session["question"]
    lang = session.get("lang", "zh")
    is_en = lang == "en"
    member_system = config.get("member_system_prompt", "")

    # Per-member system prompt override — look up by member id (not adapter) so
    # two seats sharing the same adapter get their own overrides independently.
    members_cfg = anonymizer.members_from_config(config)
    member_override = next(
        (m.get("system_prompt", "") for m in members_cfg if m["id"] == member_id),
        ""
    )
    effective_system = member_override or member_system

    if is_en:
        _conclusion_instruction = (
            "\n\n(Format requirement: the last line of your answer MUST start with "
            "\"Conclusion: \" followed by a single sentence ≤40 words summarising your position.)"
        )
        if effective_system:
            # The user-supplied system prompt may be written in another language
            # (e.g. Chinese) and would otherwise steer the answer's language —
            # in EN mode the language directive must win explicitly.
            prompt = (
                f"{effective_system}{_conclusion_instruction}\n\n"
                f"Respond in English regardless of the language used above.\n"
                f"Your label for this round is Member {label}.\n\nQuestion: {question}"
            )
        else:
            prompt = (
                f"You are Member {label}. Answer the following question. "
                f"Do not reveal which AI model or brand you are."
                f"{_conclusion_instruction}\n\n"
                f"Question: {question}"
            )
    else:
        _conclusion_instruction = (
            "\n\n（格式要求：回答的最後一行必須以【結論】開頭，用一句話（≤40字）總結你的立場。）"
        )
        if effective_system:
            prompt = (
                f"{effective_system}{_conclusion_instruction}\n\n"
                f"你的本輪代號是委員{label}。\n\n問題：{question}"
            )
        else:
            prompt = (
                f"你是委員{label}。請回答以下問題，不要提及你是哪個AI模型或品牌。"
                f"{_conclusion_instruction}\n\n"
                f"問題：{question}"
            )

    try:
        # For openai-compat seats, pass the full member config so the adapter
        # can read base_url, model, and api_key_env.
        seat_cfg = next(
            (m for m in members_cfg if m["id"] == member_id), {}
        ) if adapter_name == "openai-compat" else None
        success, text = adapters.run_adapter(
            adapter_name, prompt,
            model_arg=session["members"][label].get("_model_arg"),
            seat_cfg=seat_cfg,
        )
    except Exception as exc:
        success, text = False, str(exc)

    # Deterministic conclusion extraction:
    # Try both markers (regardless of lang — user may use Chinese UI but write English, or vice versa).
    # Priority: last line starting with 【結論】 OR line-start "Conclusion:" (case-insensitive).
    conclusion: Optional[str] = None
    if success and text:
        for line in reversed(text.splitlines()):
            stripped = line.strip()
            if stripped.startswith("【結論】"):
                raw_conclusion = stripped[len("【結論】"):].strip()
                conclusion = anonymizer.filter_self_id(raw_conclusion, label, lang=lang) if raw_conclusion else None
                break
            if re.match(r"^Conclusion:\s*", stripped, re.IGNORECASE):
                raw_conclusion = re.sub(r"^Conclusion:\s*", "", stripped, flags=re.IGNORECASE).strip()
                conclusion = anonymizer.filter_self_id(raw_conclusion, label, lang=lang) if raw_conclusion else None
                break

    with lock:
        if success and text:
            session["members"][label]["status"] = "done"
            session["members"][label]["response"] = text
            session["members"][label]["conclusion"] = conclusion
            session["members"][label]["conversation"] = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": text},
            ]
        else:
            session["members"][label]["status"] = "error"
            session["members"][label]["error"] = text or "no response"
            session["members"][label]["conclusion"] = None


# ---------------------------------------------------------------------------
# Chair summary (initial + re-summary after followups)
# ---------------------------------------------------------------------------

def run_summary(
    session: dict,
    config: dict,
    lock: threading.Lock,
    is_resummary: bool = False,
) -> None:
    with lock:
        session["chair_status"] = "running"
        question = session["question"]
        lang = session.get("lang", "zh")
        labels = list(session["members"].keys())
        members_snap: Dict[str, Any] = {
            label: {"status": m["status"], "response": m.get("response")}
            for label, m in session["members"].items()
        }
        followups_snap = [f for f in session.get("followups", []) if f["status"] == "done"]

    # Build anonymized responses — model_display NEVER enters the chair prompt
    anon: Dict[str, str] = {}
    statuses: Dict[str, str] = {}
    for label, m in members_snap.items():
        statuses[label] = m["status"]
        if m["status"] == "done" and m["response"]:
            anon[label] = anonymizer.filter_self_id(m["response"], label, lang=lang)

    chair_system = config.get("chair_system_prompt", "")
    # Custom seats (config-defined) get their display/adapter names redacted too
    members_cfg = anonymizer.members_from_config(config)
    extra_brands = [m.get("model_display", "") for m in members_cfg] + \
                   [m.get("adapter", "") for m in members_cfg]
    prompt = anonymizer.build_chair_prompt(
        question=question,
        anon_responses=anon,
        member_statuses=statuses,
        chair_system=chair_system,
        is_resummary=is_resummary,
        followup_summaries=followups_snap if is_resummary else None,
        labels=labels,
        extra_brands=extra_brands,
        lang=lang,
    )

    try:
        success, text = adapters.run_adapter("claude", prompt)
    except Exception as exc:
        success, text = False, str(exc)

    with lock:
        _lang = session.get("lang", "zh")
        session["chair_summary"] = text if success else (
            f"(Chair summary failed: {text})" if _lang == "en" else f"(主席總結失敗: {text})"
        )
        session["chair_status"] = "done"
        session["status"] = "done"


# ---------------------------------------------------------------------------
# Followup management
# ---------------------------------------------------------------------------

def add_followup(
    session: dict,
    member: str,
    question: str,
    lock: threading.Lock,
) -> str:
    fid = str(uuid.uuid4())[:8]
    followup = {
        "id": fid,
        "member": member,
        "question": question,
        "response": None,
        "status": "running",
    }
    with lock:
        session["followups"].append(followup)
    return fid


def run_followup(
    session: dict,
    followup_id: str,
    config: dict,
    lock: threading.Lock,
) -> None:
    with lock:
        followup = next((f for f in session["followups"] if f["id"] == followup_id), None)
        if followup is None:
            return
        member = followup["member"]
        member_slot = session["members"][member]
        adapter_name = member_slot["_adapter"]
        member_id = member_slot["_member_id"]
        fq = followup["question"]
        conv = list(member_slot["conversation"])
        lang = session.get("lang", "zh")

    is_en = lang == "en"
    member_system = config.get("member_system_prompt", "")

    # Per-member system prompt override — look up by member id (not adapter).
    members_cfg = anonymizer.members_from_config(config)
    member_override = next(
        (m.get("system_prompt", "") for m in members_cfg if m["id"] == member_id),
        ""
    )
    effective_system = member_override or member_system

    # Reconstruct full conversation history in prompt
    history_parts = []
    for turn in conv:
        if is_en:
            role_label = "User" if turn["role"] == "user" else f"Member {member}"
            history_parts.append(f"{role_label}: {turn['content']}")
        else:
            role_label = "用戶" if turn["role"] == "user" else f"委員{member}"
            history_parts.append(f"{role_label}：{turn['content']}")

    if history_parts:
        if is_en:
            prompt = (
                f"{effective_system}\n\n"
                f"You are Member {member}. Below is your previous conversation:\n\n"
                + "\n\n".join(history_parts)
                + f"\n\nFollow-up question: {fq}\n\nPlease continue. Do not reveal your AI brand."
            )
        else:
            prompt = (
                f"{effective_system}\n\n"
                f"你是委員{member}，以下是你之前的對話記錄：\n\n"
                + "\n\n".join(history_parts)
                + f"\n\n用戶追問：{fq}\n\n請繼續回答。不要透露你是哪個AI品牌。"
            )
    else:
        if is_en:
            prompt = (
                f"{effective_system}\n\nYou are Member {member}.\n\n"
                f"Question: {fq}\n\nDo not reveal your AI brand."
            )
        else:
            prompt = (
                f"{effective_system}\n\n你是委員{member}。\n\n"
                f"問題：{fq}\n\n不要透露你是哪個AI品牌。"
            )

    try:
        # For openai-compat seats, pass the full member config.
        seat_cfg_fu = next(
            (m for m in members_cfg if m["id"] == member_id), {}
        ) if adapter_name == "openai-compat" else None
        success, text = adapters.run_adapter(
            adapter_name, prompt,
            model_arg=session["members"][member].get("_model_arg"),
            seat_cfg=seat_cfg_fu,
        )
    except Exception as exc:
        success, text = False, str(exc)

    cleaned = anonymizer.filter_self_id(text, member, lang=lang)

    with lock:
        followup["response"] = cleaned if success else (
            f"(Error: {text})" if is_en else f"(錯誤: {text})"
        )
        followup["status"] = "done" if success else "error"
        if success:
            session["members"][member]["conversation"].extend([
                {"role": "user", "content": fq},
                {"role": "assistant", "content": text},
            ])
