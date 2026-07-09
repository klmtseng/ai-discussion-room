# AI 眾議院 (AI Parliament)

The only multi-LLM deliberation chamber that runs on your existing
Claude / ChatGPT / Gemini **subscriptions** (zero API cost, bring-your-own-subscription)
and lets you walk around a pixel JRPG parliament while the members deliberate.

Ask one question, get answers from all members simultaneously, then a chair AI
synthesises consensus, disagreements, and a conclusion — with the members
**structurally anonymised** to the chair (no brand token can reach it), so the
synthesis can't play favourites. No API keys, no vendor lock-in. MIT.

Related projects for comparison: [karpathy/llm-council](https://github.com/karpathy/llm-council)
(OpenRouter API, tab UI), [the-ai-counsel](https://github.com/jacob-bd/the-ai-counsel)
(API keys, debate rounds), [PolyGPT](https://github.com/ncvgl/polygpt) (web-login
side-by-side, no synthesis), [agent-office](https://github.com/harishkotra/agent-office)
(pixel office, agents only talk to each other).

> **ToS Warning**: This tool calls your personal CLI subscriptions locally.
> Do NOT deploy this as a public service. Each user must supply their own authenticated CLIs.

---

## Prerequisites — Three CLIs, self-authenticated

### 1. Claude (Anthropic)
```bash
npm install -g @anthropic-ai/claude-code
claude login   # browser OAuth flow
claude -p "hello"  # verify
```

### 2. ChatGPT / Codex (OpenAI)
```bash
npm install -g @openai/codex
codex login    # browser OAuth flow
codex exec --skip-git-repo-check "hello"  # verify
```

### 3. Gemini (Google — free API key, not personal OAuth)
Google discontinued personal OAuth for the Gemini CLI.
Use the free Gemini API key instead:

```bash
npm install -g @google/gemini-cli
# Create ~/.gemini/.env with:
#   GEMINI_API_KEY=<your key from aistudio.google.com>
GEMINI_CLI_TRUST_WORKSPACE=true gemini -p "hello" -m gemini-2.5-flash  # verify
```

---

## Installation

```bash
git clone <repo>
cd ai-parliament
cp config.example.json config.json   # optional: customise system prompts
python3 server.py
```
Open http://localhost:8930

---

## Anonymisation Mechanism

Each round, members A / B / C / … are assigned to the configured AIs in a random
order (seed stored for debug, never sent to chair). Three layers, weakest to strongest:

1. **Prompt layer** (best-effort): members are instructed not to reveal their identity.
2. **Self-ID filter** (best-effort): regex patterns rewrite self-identification phrases
   (e.g., "I'm Claude", "我是ChatGPT", "made by Anthropic") to `[委員X]`, in English and
   Chinese. A blocklist can always be phrased around — it is a backstop, not a guarantee.
3. **Hard brand redaction at the chair choke point** (structural guarantee): every
   member-derived string entering the chair prompt (answers, follow-up Q&A) passes
   `redact_model_names()`, which removes ALL occurrences of model/vendor brand tokens
   regardless of phrasing. The chair structurally cannot receive a brand name in
   member text. (The shared user question is not redacted — it carries no
   attribution signal. Writing style itself may still hint at a model; no filter
   can remove that.)

The UI shows YOU which member is which AI — anonymity is only against the chair.
Note: idle desks before a round show members in config order; labels are reshuffled
per round, so the A/B/C mapping is only meaningful once a round is running.

---

## Asset Credits & Licenses

All pixel art is CC0 (Kenney packs); the engine is Phaser 3 (MIT).
Full per-file attribution: [`static/assets/CREDITS.md`](static/assets/CREDITS.md).

---

## Configuration (`config.json`)

Copy from `config.example.json` and edit system prompts per role.
`config.json` is gitignored — no credentials, no personal data in the repo.

### Upgrading to N members (config-driven)

The `members` array in `config.json` controls how many AI seats are available.
Labels A, B, C, D, … are assigned automatically by position count.

**Example: adding a 4th seat (Gemini 2.5 Pro)**

```json
{
  "members": [
    {"id": "claude", "model_display": "Claude", "adapter": "claude",
     "color": "#e07830", "emblem": "star", "system_prompt": ""},
    {"id": "codex", "model_display": "ChatGPT", "adapter": "codex",
     "color": "#10b8a0", "emblem": "knot", "system_prompt": ""},
    {"id": "gemini", "model_display": "Gemini 2.5 Flash", "adapter": "gemini",
     "model_arg": "gemini-2.5-flash", "color": "#8060e8", "emblem": "quad", "system_prompt": ""},
    {"id": "gemini-pro", "model_display": "Gemini 2.5 Pro", "adapter": "gemini",
     "model_arg": "gemini-2.5-pro", "color": "#4040c0", "emblem": "quad", "system_prompt": ""}
  ]
}
```

> **Note on Gemini 2.5 Pro free tier**: `gemini -m gemini-2.5-pro` uses the free API key.
> The free tier allows ~50 requests/day. Each parliament session = 1 member call per seat.
> (`claude --model` flag confirmed via `claude --help`: use `--model <alias>` for Claude Code.)

**Example: adding a second Claude personality**

```json
{"id": "claude-critic", "model_display": "Claude (批判者)", "adapter": "claude",
 "color": "#c05020", "emblem": "star",
 "system_prompt": "你是一位嚴格的批判者委員。對每個問題都找出潛在風險和反例。"}
```

The `adapter` key maps to the CLI runner (`claude`, `codex`, `gemini`).
The `model_display` and `emblem`/`color` fields are for the public UI only —
they are never sent to the chair AI to preserve anonymisation.

---

## Running Tests

```bash
# Unit tests (no real CLI calls)
python3 -m pytest tests/ -v
# or
python3 -m unittest discover tests -v

# Live integration (uses real CLIs — burns subscription)
python3 scripts/live_smoke.py           # gemini + codex
python3 scripts/live_smoke.py --all     # all three including claude
```

---

## Mock Mode (for testing without CLI calls)

```bash
python3 server.py --mock
```
All CLI calls return instant stub responses. Useful for verifying the full API flow.

---

## 探索模式 (Explore Mode)

Click the **「探索」** button (top-right HUD) to activate free-roam mode.

**Gameplay**: AI members leave their desks and wander the chamber. When two members become adjacent (Manhattan distance = 1), they hold a short 3-turn conversation on a light topic (last debate question or a casual prompt). Speech bubbles appear above each speaker for ~4 seconds. Click a member during explore mode to read the full exchange in the bottom sheet.

**Auto-off**: Explore mode closes automatically after **30 minutes** (countdown shown next to button). Starting a new debate question also closes it and returns members to their desks.

### Quota cost warning

Each encounter = **3 CLI calls** (one per dialogue turn). Under the default throttle:
- Cooldown between encounters: **120 seconds** (global, all pairs share the clock)
- Hourly cap: **10 encounters per hour** → max ~30 CLI calls/hour

Adjusting in `config.json`:

```json
{
  "exploration": {
    "enabled": true,
    "cooldown_seconds": 120,
    "max_exchanges_per_hour": 10
  }
}
```

Set `"enabled": false` to disable the endpoint entirely. Lower `max_exchanges_per_hour` for lighter quota usage. The server returns HTTP 429 with `wait_seconds` when throttled — the frontend will not retry until the cooldown expires.

---

## API

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/api/parliament` | POST | `{"question": "…"}` | Start a new session |
| `/api/parliament/{id}` | GET | — | Poll session state |
| `/api/parliament/{id}/followup` | POST | `{"member": "A", "question": "…"}` | Deep-dive with one member |
| `/api/parliament/{id}/summarize` | POST | — | Re-summarise after followups |

Poll every 2 seconds until `status === "done"`.
