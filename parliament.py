"""
Core orchestration for AI Parliament.
Manages sessions, member calls (parallel), chair summaries, and followups.
All state lives in-memory (dict). Thread-safe via a caller-supplied lock.

Upgrade 2: public_view() includes model_display per label (from shuffle resolution).
           Chair prompt NEVER receives model_display — enforced here.
Upgrade 3: N-member support driven by config["members"] array.
"""
import random
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import adapters
import anonymizer


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def create_session(question: str, config: dict) -> dict:
    members_cfg = anonymizer.members_from_config(config)
    adapter_names = [m["adapter"] for m in members_cfg]
    seed = random.randint(0, 2**31 - 1)
    shuffle_map = anonymizer.create_shuffle(seed, adapter_names)  # {label → adapter_name}
    label_meta = anonymizer.resolve_label_meta(shuffle_map, config)  # {label → {model_display, color, emblem}}
    return {
        "id": str(uuid.uuid4())[:8],
        "question": question,
        "status": "running",
        "created_at": time.time(),
        "_debug_seed": seed,
        "_debug_shuffle": shuffle_map,   # label → adapter (debug only, never sent to chair)
        "_label_meta": label_meta,       # label → {model_display, color, emblem} (public view only)
        "members": {
            label: {
                "status": "running",
                "response": None,
                "error": None,
                "_adapter": adapter_name,
                "conversation": [],       # [{role, content}, …]
            }
            for label, adapter_name in shuffle_map.items()
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
        "status": session["status"],
        "chair_status": session["chair_status"],
        "members": {
            label: {
                "status": m["status"],
                "response": m.get("response"),
                "error": m.get("error"),
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
            session["chair_summary"] = f"(系統錯誤: {exc})"


def _run_member(session: dict, label: str, lock: threading.Lock) -> None:
    adapter_name = session["members"][label]["_adapter"]
    config = session["_config"]
    question = session["question"]
    member_system = config.get("member_system_prompt", "")

    # Per-member system prompt override from config
    members_cfg = anonymizer.members_from_config(config)
    member_override = next(
        (m.get("system_prompt", "") for m in members_cfg if m["adapter"] == adapter_name),
        ""
    )
    effective_system = member_override or member_system

    if effective_system:
        prompt = f"{effective_system}\n\n你的本輪代號是委員{label}。\n\n問題：{question}"
    else:
        prompt = (
            f"你是委員{label}。請回答以下問題，不要提及你是哪個AI模型或品牌。\n\n"
            f"問題：{question}"
        )

    try:
        success, text = adapters.run_adapter(adapter_name, prompt)
    except Exception as exc:
        success, text = False, str(exc)

    with lock:
        if success and text:
            session["members"][label]["status"] = "done"
            session["members"][label]["response"] = text
            session["members"][label]["conversation"] = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": text},
            ]
        else:
            session["members"][label]["status"] = "error"
            session["members"][label]["error"] = text or "no response"


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
            anon[label] = anonymizer.filter_self_id(m["response"], label)

    chair_system = config.get("chair_system_prompt", "")
    prompt = anonymizer.build_chair_prompt(
        question=question,
        anon_responses=anon,
        member_statuses=statuses,
        chair_system=chair_system,
        is_resummary=is_resummary,
        followup_summaries=followups_snap if is_resummary else None,
        labels=labels,
    )

    try:
        success, text = adapters.run_adapter("claude", prompt)
    except Exception as exc:
        success, text = False, str(exc)

    with lock:
        session["chair_summary"] = text if success else f"(主席總結失敗: {text})"
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
        adapter_name = session["members"][member]["_adapter"]
        fq = followup["question"]
        conv = list(session["members"][member]["conversation"])

    member_system = config.get("member_system_prompt", "")

    # Per-member system prompt override
    members_cfg = anonymizer.members_from_config(config)
    member_override = next(
        (m.get("system_prompt", "") for m in members_cfg if m["adapter"] == adapter_name),
        ""
    )
    effective_system = member_override or member_system

    # Reconstruct full conversation history in prompt
    history_parts = []
    for i, turn in enumerate(conv):
        role_label = "用戶" if turn["role"] == "user" else f"委員{member}"
        history_parts.append(f"{role_label}：{turn['content']}")

    if history_parts:
        prompt = (
            f"{effective_system}\n\n"
            f"你是委員{member}，以下是你之前的對話記錄：\n\n"
            + "\n\n".join(history_parts)
            + f"\n\n用戶追問：{fq}\n\n請繼續回答。不要透露你是哪個AI品牌。"
        )
    else:
        prompt = (
            f"{effective_system}\n\n你是委員{member}。\n\n"
            f"問題：{fq}\n\n不要透露你是哪個AI品牌。"
        )

    try:
        success, text = adapters.run_adapter(adapter_name, prompt)
    except Exception as exc:
        success, text = False, str(exc)

    cleaned = anonymizer.filter_self_id(text, member)

    with lock:
        followup["response"] = cleaned if success else f"(錯誤: {text})"
        followup["status"] = "done" if success else "error"
        if success:
            session["members"][member]["conversation"].extend([
                {"role": "user", "content": fq},
                {"role": "assistant", "content": text},
            ])
