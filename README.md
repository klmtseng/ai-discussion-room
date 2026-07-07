# AI 眾議院 (AI Parliament)

Bring-your-own-subscription multi-AI deliberation tool.
Ask one question, get answers from Claude + ChatGPT + Gemini simultaneously,
then have a chair AI synthesise consensus, disagreements, and a conclusion — all anonymised.

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

Each round, members A / B / C are assigned to Claude / ChatGPT / Gemini in a random
order (seed stored for debug, never sent to chair). Two layers of anonymisation:

1. **Prompt layer**: members are instructed not to reveal their identity.
2. **Deterministic filter**: 11 regex patterns remove self-identification phrases
   (e.g., "I'm Claude", "我是ChatGPT", "身為AI語言模型") in both English and Chinese,
   replacing them with `[委員X]`. This layer is the primary defence.

The chair receives only `[委員A/B/C]` labels, never model names.

---

## Configuration (`config.json`)

Copy from `config.example.json` and edit system prompts per role.
`config.json` is gitignored — no credentials, no personal data in the repo.

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

## API

| Endpoint | Method | Body | Description |
|---|---|---|---|
| `/api/parliament` | POST | `{"question": "…"}` | Start a new session |
| `/api/parliament/{id}` | GET | — | Poll session state |
| `/api/parliament/{id}/followup` | POST | `{"member": "A", "question": "…"}` | Deep-dive with one member |
| `/api/parliament/{id}/summarize` | POST | — | Re-summarise after followups |

Poll every 2 seconds until `status === "done"`.
