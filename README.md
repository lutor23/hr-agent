# Acme HR Policy Assistant

An agentic HR assistant for Acme Corp employees. Ask it about PTO, benefits, remote
work, leave, equipment, conduct, or security, and it retrieves the relevant policy
text and cites its sources — or looks up an individual's real PTO balance and
benefits enrollment through MCP tools. Built as a Quantic MS AIE capstone
demonstrating RAG, an MCP tool server, an agentic orchestration loop, a web API,
CI/CD, a free-tier deployment, and a quantitative evaluation set.

**Live app:** https://hr-agent-xds2.onrender.com
**Health check:** https://hr-agent-xds2.onrender.com/health
**Repo:** https://github.com/lutor23/hr-agent

See [`deployed.md`](./deployed.md) for cold-start behavior and operational notes, and
[`design-and-evaluation.md`](./design-and-evaluation.md) for architecture, design
rationale, and full evaluation results.

## What it does

- **Answers policy questions with citations.** Every policy claim is tied back to a
  `[DOC-ID: Section]` reference the retriever actually returned — never an
  unsupported guess. An out-of-corpus question ("what's the weather today?") gets a
  plain "I can't help with that," not a hallucinated answer.
- **Looks up real employee data** (PTO balance, benefits enrollment, profile) through
  MCP tools, and only for the employee currently signed in — it will not answer "what's
  E002's PTO balance?" if you're signed in as E001.
- **Combines both in one turn.** "Can I take two weeks off in December, and what's the
  process?" checks your actual PTO balance *and* looks up the PTO policy's approval
  process, then answers both halves together.
- **Escalates safely.** It can open a mock HR ticket or draft (never send) an email,
  but always says plainly that the action is mock/a draft.
- **Shows its work.** Every response includes the full tool-call trace (which MCP
  tools ran, with what arguments, and whether each succeeded) — not hidden
  chain-of-thought, an auditable record of what the agent actually did.

## Architecture at a glance

```
Browser / curl
      │
      ▼
FastAPI app (app/main.py) ── POST /chat, GET /health
      │
      ▼
Agent orchestrator (app/agent.py) ── LLM tool-calling loop (OpenRouter)
      │  real MCP protocol (ClientSession / list_tools / call_tool)
      ▼
MCP server (mcp/server.py) ── 7 tools
      │                              │
      ▼                              ▼
RAG index (ChromaDB + ONNX      Mock employee data
MiniLM-L6-v2 embeddings,        (mock_data/*.json)
corpus/ policy documents)
```

Full diagram, component-by-component rationale, and the two demo tasks' expected MCP
call sequences are in [`design-and-evaluation.md`](./design-and-evaluation.md).

## Repo layout

```
app/          FastAPI app, agent orchestrator, RAG retriever/ingest, shared config
mcp/          MCP tool server (7 tools) — see app/agent.py for why it's loaded two
              different ways (real subprocess locally/in tests, in-process on Render)
corpus/       10 policy documents: 8 Markdown, 1 HTML, 1 PDF
mock_data/    Synthetic employees, PTO balances, benefits (obviously fake)
evaluation/   25-item eval set, harness, and results
tests/        117 tests (unit, integration, real MCP protocol round-trips)
.github/      CI: lint, tests, gated deploy
```

## Setup

Requires Python 3.12 (the system default on most machines is too new for
`chromadb`/`onnxruntime` wheels as of this writing — if `pip install` fails, install
3.12 via [uv](https://docs.astral.sh/uv/) or pyenv).

```bash
git clone https://github.com/lutor23/hr-agent.git
cd hr-agent

uv venv --python 3.12 .venv          # or: python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt

cp .env.example .env
# edit .env: set OPENROUTER_API_KEY (free at https://openrouter.ai)
```

## Running locally

```bash
# Build the vector index (one-time, or after editing corpus/)
.venv/bin/python -m app.ingest --reset --smoke

# Start the web app
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
# -> open http://localhost:8000 for the chat UI, or POST to /chat directly
```

```bash
# Or drive the agent straight from the CLI, no web server needed
.venv/bin/python -m app.agent "Can I take two weeks off in December?" --employee E001
```

```bash
curl -X POST http://localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message": "How many PTO days do I get per year?", "employee_id": "E001"}'
```

### Tests

```bash
.venv/bin/python -m pytest tests/ -q          # 117 tests
.venv/bin/ruff check .                        # lint
```

`tests/conftest.py` builds the vector index automatically if it's missing, so the
suite passes on a fresh checkout with no manual setup.

## Evaluation

```bash
.venv/bin/python evaluation/run_eval.py
```

Runs all 25 items in [`evaluation/eval_set.json`](./evaluation/eval_set.json) against
the real agent and real LLM, writing a full report to `evaluation/results.json`.
Takes several minutes (it calls OpenRouter for every item) and is subject to the free
tier's daily request cap — see `design-and-evaluation.md` for details.

**Latest results:**

| Metric | Result | Target |
|---|---|---|
| Groundedness (LLM-judged) | 0.875 | ≥0.80 ✅ |
| Citation accuracy | 0.792 | ≥0.75 ✅ |
| Tool-selection accuracy | 0.96 | — |
| Workflow completion rate | 0.92 | — |
| Escalation/clarification accuracy | 0.90 | — |
| Latency p50 | 7.0s | <8s ✅ |
| Latency p95 | 42.7s | <8s |

Full per-item results, methodology, and two real bugs the evaluation process found
and fixed are in `design-and-evaluation.md`.

## Deployment

Deployed on [Render](https://render.com)'s free web-service tier via
[`render.yaml`](./render.yaml) (Infrastructure-as-Code). Deploys are gated on CI
passing — pushing to `main` doesn't deploy by itself; `.github/workflows/ci.yml`'s
`deploy` job triggers a Render deploy hook only after lint + all 117 tests pass. See
[`deployed.md`](./deployed.md) for the live URL, cold-start behavior, and how to
trigger a manual redeploy.

## Environment variables

See [`.env.example`](./.env.example) for the full, current list with inline
explanations of what each one does and why (e.g. why there's no `EMBEDDING_MODEL`
variable, and what `MCP_TRANSPORT` controls).

## Known limitations

- **Free-tier LLM latency and availability are genuinely variable.** OpenRouter's
  free models are rate-limited (50 requests/day account-wide, observed directly) and
  latency can spike under shared-pool load — the agent degrades gracefully (a plain
  "couldn't reach the language model, try again" answer) rather than crashing, but
  p95 latency can occasionally be high.
- **Cold starts re-embed the whole corpus.** Render's free tier has no persistent
  disk, so every cold start rebuilds the ~97-chunk index from scratch (seconds
  locally, a couple of minutes on Render's free CPU). See `deployed.md`.
- **No real authentication.** `employee_id` is passed directly in the request body —
  fine for a capstone demo over mock data, not something to deploy for real HR data
  without adding real auth.
