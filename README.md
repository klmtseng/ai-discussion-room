# AI 討論室 (AI Discussion Room)

The only multi-LLM deliberation chamber that runs on your existing
Claude / ChatGPT / Gemini **subscriptions** (zero API cost, bring-your-own-subscription)
and lets you walk around a pixel JRPG parliament while the members deliberate.

Ask one question, get answers from all members simultaneously, then a chair AI
synthesises consensus, disagreements, and a conclusion — with the members
**structurally anonymised** to the chair (no brand token can reach it), so the
synthesis can't play favourites. No API keys, no vendor lock-in. MIT.

## Credits & Lineage

This project was inspired by a Chinese-language social media post showcasing an
"AI 眾議院" (AI House of Representatives) build — three AIs answering in parallel
with an anonymised chair synthesis. The original post is no longer traceable;
**if you are the original author, please open an issue and we will credit you
properly.** The council-with-anonymised-chairman concept traces back to
[karpathy/llm-council](https://github.com/karpathy/llm-council) (Nov 2025).
This implementation (subscription-CLI BYOS, structural brand redaction, pixel
chamber, exploration mode, minority report) was built independently.

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
cd ai-discussion-room
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

## Seat Management (in-browser UI)

You can add, edit, and delete AI seats without touching any config file.

### How to open

Click the **⚙** button in the top-right HUD (next to the Explore button). A bottom sheet opens with one card per seat.

### Actions per seat card

| Button | What it does |
|--------|-------------|
| **Test** | Fires a one-sentence probe ("Reply with exactly: SEAT_OK") at the adapter. Shows latency on success, error snippet on failure. **60-second global cooldown** across all Test clicks (prevents burning quota on rapid taps). |
| **Edit** | Opens an inline form: Display Name, ID, Adapter, Model Arg, Color (8 presets), Emblem (6 options), System Prompt (≤2000 chars). |
| **Delete** | Removes the seat from the working list (not saved yet). |

### Adding a new seat

Click **＋ Add Seat** to open the edit form for a blank entry. Fill in the required fields and click OK. Repeat for each new seat.

### Saving

Click **Save** to write the current seat list to `config.json`. The room immediately rebuilds — existing debate sessions are **not** affected (they snapshot the member list at creation time). If a session is running and you add/remove seats, the live session keeps its original member count.

### Validation rules (enforced server-side on Save)

- **2–6 seats** (inclusive)
- Each seat must have a unique `id` matching `[a-z0-9-]{1,32}`
- `adapter` must be one of `claude`, `codex`, `gemini`, `openai-compat`, or use the prefixes `claude-*` / `gemini-*`
- `color` (if set): `#rrggbb` hex
- `system_prompt` (if set): ≤2000 characters
- `sprite` (if set): must match `[a-z0-9_-]{1,32}` — drop a 16×16×4-frame PNG into `assets/sprites/` and set this field to use a custom character sprite (generator: `scripts/sprite_forge.py`).

### Adding a brand-new provider (Ollama, Mistral, etc.)

For any provider that exposes an OpenAI-compatible `/chat/completions` endpoint, use the built-in **`openai-compat`** adapter — no code changes required (see API Seats section below).

For providers that require a custom protocol, implement a `_run_<name>` function in **`adapters.py`** and register it in the `ADAPTERS` dict. After restarting the server you can use your new adapter name in the Seat Management form.

---

## API Seats (OpenAI-compatible)

Any provider that offers an OpenAI-compatible `/chat/completions` endpoint can be added as a seat without writing any code. Set `"adapter": "openai-compat"` in `config.json`, or use the **OpenAI-compatible API** option in the Seat Management panel.

**Security rule: never write API keys in `config.json`.** Store the key in an environment variable and reference the variable name via `api_key_env`.

### Required fields for `openai-compat` seats

| Field | Required | Description |
|---|---|---|
| `base_url` | yes | Endpoint root, e.g. `https://api.deepseek.com`. Must start with `http://` or `https://`. |
| `model` | yes | Model name the endpoint expects, e.g. `deepseek-chat`. Max 64 chars. |
| `api_key_env` | no | Environment-variable **name** (not the key itself) holding the Bearer token. If absent or the env var is empty, no `Authorization` header is sent — correct for local Ollama. Pattern: `[A-Z0-9_]{1,64}`. |

### Verified base URLs (queried 2026-07-10)

| Provider | `base_url` | Official source |
|---|---|---|
| **Ollama** (local) | `http://localhost:11434/v1` | [docs.ollama.com/api/openai-compatibility](https://docs.ollama.com/api/openai-compatibility) — no API key needed |
| **DeepSeek** | `https://api.deepseek.com` | [api-docs.deepseek.com](https://api-docs.deepseek.com/) |
| **GLM / 智谱 bigmodel** | `https://open.bigmodel.cn/api/paas/v4` | [docs.bigmodel.cn/cn/guide/develop/openai/introduction](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction) |
| **MiniMax** | `https://api.minimax.io/v1` | [platform.minimax.io/docs/api-reference/text-openai-api](https://platform.minimax.io/docs/api-reference/text-openai-api) |

> For any provider not listed, please check the official documentation directly — do not rely on third-party sources.

### Example: Ollama local seat (no key)

```json
{
  "id": "ollama-llama",
  "model_display": "Llama 3 (Ollama)",
  "adapter": "openai-compat",
  "base_url": "http://localhost:11434/v1",
  "model": "llama3",
  "color": "#60a060",
  "emblem": "moon"
}
```

### Example: DeepSeek seat (API key via env)

```bash
export DEEPSEEK_API_KEY=sk-xxxxx
```

```json
{
  "id": "deepseek",
  "model_display": "DeepSeek Chat",
  "adapter": "openai-compat",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "api_key_env": "DEEPSEEK_API_KEY",
  "color": "#4488cc",
  "emblem": "star"
}
```

> **Cost notice**: API seats are billed by the provider at their standard rates. Each parliament session = one API call per seat. The subscription-backed CLI adapters (Claude/ChatGPT/Gemini) are unaffected.

---

## Language Support (zh / en)

The UI is fully bilingual. All member prompts, chair instructions, and sheet labels switch together.

**In the browser**: click the **「EN」/ 「中」** toggle button (top-right HUD) to switch between English and Chinese. Your preference is saved in `localStorage`.

**Default language**: detected from `navigator.language` — `zh-*` locales default to Chinese; everything else defaults to English.

**API**: pass `"lang": "en"` in the POST body to `/api/parliament` to run a session in English mode:
```bash
curl -X POST http://localhost:8930/api/parliament \
  -H "Content-Type: application/json" \
  -H "X-Parliament-Pin: <pin>" \
  -d '{"question": "Should AI be regulated?", "lang": "en"}'
```
Omitting `lang` defaults to `"zh"`. Any value other than `"en"` or `"zh"` also falls back to `"zh"`.

**What switches with lang**:
- Member prompts: EN version uses `"Conclusion: "` marker; ZH uses `"【結論】"` marker
- Conclusion extraction: both markers are tried regardless of lang (cross-language answers work)
- Chair prompt: four-section headers in English (`1. Consensus / 2. Divergences / 3. Minority Report / 4. Chair's Synthesis`)
- Anonymisation token in chair-bound text: `[an AI]` (en) vs `[某AI]` (zh)
- All UI strings: sheet titles, badges, hints, table headers, placeholders

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

## Output Structure

Each session produces five layers of output:

| Layer | Source | Description |
|---|---|---|
| **原文並列 (Raw)** | Members | Full response text per member, visible in each member's bottom sheet |
| **結論並列 (Conclusion table)** | Deterministic extraction | Last `【結論】…` line from each member's answer, one sentence; `null` if format not followed. Shown above chair summary — zero LLM involvement |
| **共識點 (Consensus)** | Chair (LLM) | Points where all members substantially agree |
| **少數派報告 (Minority report)** | Chair (LLM) | Per-divergence: which member dissents and their strongest argument, one sentence; "無——全體一致" if all agree |
| **綜合結論 (Synthesis)** | Chair (LLM) | Chair's integrative opinion; may explicitly state "本題無共識" rather than forcing a false compromise |

The conclusion table is the only layer with a structural anonymisation guarantee at the data level — it is extracted before the chair ever runs.

---

## API

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/api/parliament` | POST | `{"question": "…"}` | Start a new session |
| `/api/parliament/{id}` | GET | — | Poll session state |
| `/api/parliament/{id}/followup` | POST | `{"member": "A", "question": "…"}` | Deep-dive with one member |
| `/api/parliament/{id}/summarize` | POST | — | Re-summarise after followups |

Poll every 2 seconds until `status === "done"`.

Each member object in the poll response now includes a `conclusion` field (string or `null`):

```json
{
  "members": {
    "A": {
      "status": "done",
      "conclusion": "此議題需要多角度評估，建議審慎權衡利弊。",
      "model_display": "Claude",
      ...
    }
  }
}
```
