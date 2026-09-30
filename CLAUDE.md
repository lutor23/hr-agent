# HR Agent — Quantic "AI Engineering Techniques and Architectures" Capstone

**Owner:** Luis Toruno (lutor23) | **Deadline:** October 4, 2026
Source spec: `ai project.pdf` (Quantic). This file condenses it; when in doubt, the PDF wins.
Goal: a deployed, agentic HR policy/operations assistant = **RAG over policy docs + agent orchestrator + MCP tools over mock data**, with cited, grounded answers.

## Stack
- Python venv at `.venv/` (system Python is 3.14, too new for chromadb/sentence-transformers wheels — use `uv venv --python 3.12 .venv`), deps in `requirements.txt`. Secrets only via env vars (`.env` is gitignored; `.env.example` is committed).
- FastAPI web app + chat UI; LLM via OpenRouter (OpenAI-compatible client, free-tier model); local embeddings (`all-MiniLM-L6-v2`); Chroma vector store persisted to `CHROMA_PERSIST_DIR`.
- MCP server (`mcp` SDK) over stdio by default (`MCP_TRANSPORT`), optionally HTTP. Single-service deploy on Render.
- `SEED=42` everywhere deterministic behavior matters (chunking, eval sampling).

## Repo Layout (required by the grader)
| Path | Contents |
|---|---|
| `app/` | FastAPI app, agent orchestrator, MCP client, RAG code |
| `mcp/` | MCP server + tool definitions |
| `corpus/` | Policy docs (md, html, pdf — need ≥2 formats; 5–20 files, 30–120 pages total) |
| `mock_data/` | Synthetic employees, PTO, benefits, tickets (clearly fake) |
| `evaluation/` | 20–30 questions with gold answers/rubrics, scripts, reported results |
| `docs/` | Supporting docs |
| `README.md` | Intro, setup, local run, deployment, evaluation, **deployed URL** |
| `design-and-evaluation.md` | Architecture, RAG design, MCP design, orchestration, tool schemas, guardrails, deploy choices, eval questions/answers/results |
| `ai-tooling.md` | Which AI tools were used, how, what worked / didn't |
| `deployed.md` | Deployed URL, `/health` URL, cold-start notes |
| `.github/workflows/` | CI/CD |

> A prior planning pass used `src/`/`data/`/`eval/` instead of `app/`/`mock_data/`/`evaluation/`; renamed Sep 22 to match the grader spec. If `src.` or `data/` shows up in an old doc or comment, it's stale.

Repo must be shared with GitHub user **`quantic-grader`**.

## Requirements Checklist
**RAG**
- Parse/clean ≥2 formats; heading-aware chunking (justify the choice); embed; store in vector DB.
- Persist citation metadata per chunk: doc title/ID, section, source snippet.
- Top-k retrieval (optional filter / query rewrite / rerank); prompt injects chunks + source metadata.
- Answers cite doc IDs/titles/sections with snippets. Guardrails: refuse/redirect out-of-corpus questions, no unsupported claims, separate policy facts from recommendations.
- Include ≥1 multi-document question.

**Agent**
- Orchestrator interprets intent, decides if RAG alone suffices, selects tools, calls MCP tools, synthesizes.
- ≥2 multi-step workflows (e.g. remote-work eligibility; PTO request guidance; expense compliance; benefits triage; HR case triage).
- Visible/logged **operational trace** (tools, args, outputs, retrieved sources, answer basis, escalation decision). Never expose hidden chain-of-thought.
- Graceful failures: MCP tool down, missing employee ID, weak evidence, ambiguous request → clarify.
- No irreversible actions: tickets/emails/case updates are **mock** or need explicit user confirmation.

**MCP** — ≥5 tools, and the agent must *actually call them through the MCP layer* (no direct function calls).
- Suggested: `search_policy_documents`, `get_policy_section`, `lookup_employee_profile`, `check_pto_balance`, `lookup_benefits_status`, `create_mock_hr_ticket`, `draft_hr_email`, `check_policy_compliance`.
- ≥1 tool uses the RAG index; ≥1 uses mock data / performs a mock op.
- Document architecture, transport, tool schemas, and how the client discovers/calls tools.

**Web app**
- Chat UI; `POST /chat` → answer, citations, snippets, concise tool-call trace; `GET /health` → JSON incl. MCP connectivity.
- Grader must be able to reproduce ≥2 agentic demo tasks (UI or API).

**Deployment** — free tier, shareable URL, no paid DB, env vars + cold-start behavior documented in README and `deployed.md`.

**CI/CD** — GitHub Actions on push/PR: install → import/start check → tests (incl. app-starts test and MCP tool discovery/call test) → deploy **only if tests pass**.

**Evaluation** (20–30 items: straightforward, multi-doc, tool-requiring, ambiguous, out-of-scope)
- Quality: groundedness, citation accuracy (optional exact/partial match).
- Agent: tool-selection accuracy, workflow completion rate, escalation/clarification accuracy, action-safety pass rate.
- System: latency p50/p95 over 10–20 queries; report cold vs warm start separately.
- ≥1 ablation (retrieval k, chunk size, prompt variant, or tool availability).

**Design docs** — justify: orchestration approach, MCP design, transport, tool schemas, embedding model, chunking, k, vector store, deploy architecture, guardrails. Include an architecture diagram (web app → orchestrator/MCP client → MCP server → RAG index + mock data; LLM provider) and the two demo tasks with expected MCP call sequences.

## Master Task List

### ✅ Day 1 — Scaffold (Sep 22) DONE
- [x] `requirements.txt`, `.env.example`, `.gitignore`
- [x] 10-document policy corpus: 8 Markdown + 1 HTML + 1 PDF in `corpus/`

### ✅ Day 2 — Data & Ingestion (Sep 22) DONE
- [x] `mock_data/employees.json`, `pto_balances.json`, `benefits.json` — 10 employees (E001–E010)
- [x] `app/loaders.py` — `Chunk` dataclass + MD/HTML/PDF loaders, heading-aware chunking → **97 chunks**
- [x] `app/ingest.py` — embed + upsert into ChromaDB, `--reset`/`--smoke` CLI flags, 5/5 smoke queries pass

### ✅ Day 3 — RAG Pipeline (Sep 22) DONE
- [x] `app/retriever.py` — `retrieve()`, `build_prompt()`, `ask()`, `extract_citations()`, `employee_context()`
- [x] Guardrail: chunks below cosine 0.25 are dropped; empty result → "couldn't find a policy" (no hallucination)
- [x] Unknown `employee_id` → graceful error, not a crash
- [x] LLM timeout/error → partial answer (top retrieved chunk + citation) instead of failing the request
- [x] Manually verified: single-doc, multi-doc (remote-work query spans 3 sections), off-topic, unknown-employee, personalized (with employee context)
- [x] `tests/test_loaders.py`, `tests/test_retriever.py` — 18 tests passing

### ✅ Day 4 — MCP Server DONE
- [x] `mcp/server.py` — FastMCP server, stdio transport, run as a script (`python mcp/server.py`)
- [x] 5 tools: `search_policy_documents`, `get_policy_section` (exact metadata lookup via new `app.retriever.get_section`), `lookup_employee_profile`, `check_pto_balance`, `lookup_benefits_status`
- [x] Errors are returned as structured payloads (`{"error": "employee_not_found", ...}`), never raised, so the agent can handle them without special exception logic
- [x] `mcp/_smoke_test.py` (manual) and `tests/test_mcp_tools.py` (12 tests) drive the server through a real MCP client over stdio — 30/30 tests passing overall

### ✅ Day 5 — Action Tools & Agent DONE
- [x] `create_mock_hr_ticket` (in-memory, ids `HR-0001`…, validated type/employee/description) and `draft_hr_email` (LLM-written, template fallback, `sent` always false) added to `mcp/server.py` → 7 tools
- [x] `app/agent.py` — `HRAgent`: spawns the MCP server, discovers tools via `list_tools`, runs an OpenAI-format tool-calling loop (max 6 tool calls); every call goes through `session.call_tool`. CLI: `python -m app.agent "question" --employee E001`
- [x] Operational trace: `ChatResponse.trace` (tool, args, ok, summary, ms) + one JSON log line per call on logger `hr_agent.trace`; `escalated` flag when a mock ticket is opened
- [x] Citations `[DOC_ID: Section]` are verified against what tools actually returned (fuzzy section match; unreturned citations dropped); snippets included
- [x] Guardrails: signed-in employee can only read their own records (`not_authorized`); missing employee ID → asks; LLM/tool failures → graceful answer + `error`; runaway loop → `max_steps_exceeded`
- [x] Two multi-step workflows verified live: PTO request (balance + PTO policy sections), out-of-state remote work; plus ticket+email and missing-ID flows
- [x] `tests/test_agent.py` (14, scripted fake LLM + real MCP server) and extended `test_mcp_tools.py` — 47 tests passing

### ✅ Day 6 — FastAPI App DONE
- [x] `app/main.py` — `create_app(llm_fn=None)` factory; `uvicorn app.main:app --port 8000`. One long-lived `HRAgent` (one MCP subprocess) started in the lifespan and shared by all requests
- [x] `POST /chat` → `ChatResponse` (answer, citations+snippets, tools_used, trace, escalated, latency_ms, error). Validation: message 1–2000 chars (422). 503 if index empty or MCP server down; 504 after 90s
- [x] `GET /health` → `{status, chroma_docs, version, mcp_connected, mcp_tools}`; returns **503** with `status: "degraded"` if index is empty or the MCP ping fails
- [x] Chat UI at `/` (`app/static/index.html`, no build step): mock employee picker, example prompts for the demo tasks, answer, sources with snippets, tool-trace table, escalation/latency/error badges; verified in a real browser. `GET /employees` (id+name only) feeds the picker
- [x] `tests/test_api.py` (10 tests, real lifespan + MCP subprocess, scripted LLM) — includes the "app starts" test CI needs

### ✅ Day 7 — Tests & Lint DONE
- [x] Coverage measured (`pytest --cov=app`): 82% → **98%**; suite grew 58 → **100 tests** (`test_loaders`, `test_retriever`, `test_ingest`, `test_agent`, `test_api`, `test_mcp_tools`, `test_llm`). New: per-format loader behaviour (HTML/PDF/markdown), `split_text`, `get_section`, single-shot `ask()` with a faked LLM, `ingest()`/`smoke()`/CLI on a throwaway DB, malformed/failing tool calls, default-LLM wiring, agent CLI, **concurrent requests over one shared MCP session (no cross-talk)**
- [x] `tests/conftest.py` builds the ChromaDB index if missing, so the suite passes on a fresh checkout/CI (verified with `chroma_db/` deleted)
- [x] Regression tests for two easy-to-break invariants: `app.config` imported before `chromadb` (telemetry), and `count_chunks()` never importing torch (free-tier memory)
- [x] Lint: `ruff.toml` + `ruff check .` clean (rules E,F,W,I,B; `corpus/` excluded). `pytest.ini` added. `pytest-cov`, `ruff` pinned in requirements.txt. CI should run `ruff check .` (not `ruff format` — it would rewrite 9 files)
- Not unit-tested by design: `mcp/server.py` runs in a subprocess so it isn't in the coverage number, but every tool is exercised through it by `test_mcp_tools.py`/`test_agent.py`; live-LLM behaviour (model availability/latency) is never in the suite.

### 🟡 Day 8 — CI/CD & Deployment IN PROGRESS
- [x] `.github/workflows/ci.yml`: install (pip, cached) → `ruff check .` → import check → build index (`--reset --smoke`) → **app-starts check** (real `uvicorn` bound to a port, real `curl /health`, asserts `mcp_connected`/`mcp_tools: 7` — not just the in-process TestClient) → `pytest --cov=app`. Deploy job `needs: test`, only on push to main, skips gracefully (not red) if `RENDER_DEPLOY_HOOK_URL` isn't set yet
- [x] `render.yaml`: free plan, `autoDeploy: false` (CI's deploy hook gates it instead of Render's own git-push trigger), `healthCheckPath: /health`
- [x] Fixed two drifted config values found while cross-checking these files: `config.py`'s `LLM_MODEL` fallback default was still the Day-3-broken model (only mattered if `.env`/env vars were absent); `.env.example` listed `MCP_TRANSPORT`/`MCP_SERVER_PORT`/`APP_HOST`/`APP_PORT`/`LOG_LEVEL`/`SEED`, none of which any code reads. Added `test_llm.py::test_default_model_matches_env_example_and_render_yaml` so the two files can't silently drift apart again
- [x] Locally validated the exact app-starts check CI will run (real port bind + curl), not just its intent
- [x] **First real Render deploy failed** with "No open ports detected" / port-scan timeout. Root cause: `startCommand` was `python -m app.ingest --reset && uvicorn ...` — uvicorn (and its port bind) never even started until the standalone ingest process finished, and on Render's free tier (no persistent disk, so the ~90MB embedding model re-downloads every cold start, plus slow shared CPU) that routinely exceeds Render's port-scan timeout. Confirmed via uvicorn source that `Server.startup()` awaits `lifespan.startup()` *before* `loop.create_server(...)`, so even awaiting ingestion inside the FastAPI lifespan would have hit the same wall. **Fix:** `render.yaml`'s `startCommand` is now just `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; `app/main.py`'s lifespan fires index-building as a background `asyncio.create_task` it never awaits (`_build_index_if_empty`), so the port opens in ~1s regardless of index state. `/health` already reported `{"status": "degraded"}` for an empty index, so this needed no new endpoint behavior — verified locally end-to-end against a throwaway `CHROMA_PERSIST_DIR`: port answers 503/degraded in ~1s, flips to 200/ok with `chroma_docs: 97` a few seconds later once the background embed finishes
- [x] That change had one test-isolation side effect, caught and fixed: `test_empty_index_gives_503_on_chat_and_degraded_health` monkeypatches `main.count_chunks` to always return 0, which the new background task also reads — it was triggering a real, destructive (`reset=True`) re-embed of the shared on-disk test index in the background during that one test. Fixed by also stubbing `main._build_index_if_empty` to a no-op in that test. 101/101 tests pass, `ruff check .` clean
- [ ] **Not yet done — needs your accounts, not just code:** create the Render service from `render.yaml` (render.com/select-repo), set `OPENROUTER_API_KEY` in its dashboard (never committed), copy its Deploy Hook URL into the GitHub repo's `RENDER_DEPLOY_HOOK_URL` secret, push to trigger the first real CI run + deploy with the port fix, then **measure actual memory** on Render (the free-tier 512MB question flagged since Day 6 is still open — nothing here confirms it fits, only that it isn't obviously precluded)
- [ ] Share the repo with GitHub user `quantic-grader` (repo Settings → Collaborators)
- [ ] `deployed.md` (deployed URL, `/health` URL, cold-start notes) — needs a real deployment to write truthfully

### 🔲 Days 9–10 — Evaluation (Sep 30–Oct 1)
- [ ] `evaluation/eval_set.json` — 20–30 Q&As (straightforward, multi-doc, tool-requiring, ambiguous, out-of-scope)
- [ ] `evaluation/run_eval.py` — groundedness, citation accuracy, tool-selection accuracy, latency p50/p95, ≥1 ablation

### 🔲 Days 11–12 — Docs & Demo (Oct 2–3)
- [ ] `README.md`, `design-and-evaluation.md`, `ai-tooling.md`, `deployed.md` (all required at repo root, see spec above)
- [ ] Architecture diagram; 7–10 min demo video, two agentic tasks, all group members on camera with ID

### 🔲 Day 13 — Final Review & Submit (Oct 4)

## Key Files

| File | Purpose |
|------|---------|
| `app/loaders.py` | Chunk dataclass + MD/HTML/PDF loaders |
| `app/ingest.py` | Embed + upsert into ChromaDB |
| `app/retriever.py` | RAG query, prompt builder, citations (Day 3, done) |
| `app/employee_data.py` | Read-only lookups against `mock_data/*.json` |
| `app/models.py` | Shared `ChatRequest`/`ChatResponse`/`Citation`/`HealthResponse` |
| `app/config.py` | Env-driven settings |
| `app/main.py` | FastAPI app + lifespan-managed agent (Day 6, done) |
| `app/static/index.html` | Chat UI served at `/` |
| `app/agent.py` | Orchestrator: MCP client + tool-calling loop + trace (Day 5, done) |
| `mcp/server.py` | MCP tool server, 7 tools (Days 4–5, done); `mcp/_smoke_test.py` manual client check |
| `corpus/` | 10 policy docs (8 MD, 1 HTML, 1 PDF) |
| `mock_data/` | Mock employees, PTO balances, benefits |
| `evaluation/` | Eval set + metrics runner (Day 9–10, not yet created) |
| `.github/workflows/ci.yml` | CI: lint, import/start checks, tests, gated deploy (Day 8, workflow written; not yet run for real) |
| `render.yaml` | Render blueprint (Day 8, written; service not yet created) |

## Environment

See `.env.example`. Notable: `LLM_MODEL` currently `nvidia/nemotron-3-super-120b-a12b:free` — OpenRouter's free-tier slugs churn (hit a 404 on the originally-planned `meta-llama/llama-3.1-8b-instruct:free` and 429s on several others in one session). If `ask()` starts erroring, check `GET https://openrouter.ai/api/v1/models` for current `*:free` ids.

## To Resume

```bash
uv venv --python 3.12 .venv   # system Python is 3.14; too new for chromadb/sentence-transformers wheels
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env          # set OPENROUTER_API_KEY

.venv/bin/python -m app.ingest --reset --smoke
.venv/bin/python -m pytest tests/ -q
```

## Known Constraints
- **Memory for Render's free tier (512MB):** two processes run — the web app (light, ~140MB: `count_chunks()` deliberately skips the embedding function so torch never loads here) and the MCP server subprocess (loads torch + MiniLM, several hundred MB). Check real usage on Day 8; if too tight, options are a smaller/ONNX embedding path or loading the model only in the server (already the case).
- **Agent latency is dominated by the free LLM** (~20-25s for a 2-3 tool question; each LLM turn 3-8s, tools take ms). The p95 <8s eval target is unlikely on this model; the MCP server also loads the embedding model on its first search (~3s). Day 6 should keep one long-lived `HRAgent` (one server subprocess) for the app rather than one per request.
- Mock tickets live only in the MCP server process's memory (reset when it restarts).
- **`mcp/` collides with the installed `mcp` SDK package.** The grader requires a top-level `mcp/` dir, but an `mcp/__init__.py` (or dotted-importing `mcp.server`) would shadow the SDK and break `from mcp.server.fastmcp import FastMCP`. So `mcp/` has no `__init__.py`, and `server.py` is only ever run as a script/subprocess (sys.path[0] is then `mcp/` itself, so `import mcp` still finds the SDK). Never import our server by dotted path; spawn it via `StdioServerParameters` like the tests do.
- **FastMCP flattens list returns into one content item per element.** A client reading `search_policy_documents` must parse *every* `result.content` item (empty list → no items), not just `content[0]`. The Day 5 agent's MCP client needs this.
- Don't pipe MCP client scripts into `head`: the server's stderr logging blocks on the closed pipe and the process hangs (leaves orphaned `mcp/server.py` processes).
- OpenRouter free tier: model availability and rate limits are unstable; `ask()` degrades gracefully (returns top chunk + citation) rather than failing outright.
- `requirements.txt` pins `pydantic==2.9.2`, which conflicts with `mcp==1.2.0`'s `pydantic>=2.10.1`; bumped to `pydantic==2.10.6` — don't revert without also relaxing the mcp pin.
- Never commit `.venv/`/`venv/` — an earlier local venv was accidentally added to git tracking before `.gitignore` was fixed; already untracked, stays untracked. Keep `.env.example` in sync when adding new env vars.
- Keep corpus and mock data small (free-tier resources); mock data must be obviously synthetic.

## Demo Video (7–10 min, screen share + voiceover)
Two end-to-end agentic tasks on the **deployed** app; for each, explain tool names, arguments, outputs, citations, final answer/action. Plus quick walkthrough of design, deployment, CI/CD, eval results. Group members must all speak, be on camera, and show government ID.

## Rubric Emphasis (score 5)
Cited/grounded answers · fully working MCP with clear traces and error handling · two multi-step tasks using RAG + mock-data tools · clean separation of web app / orchestrator / MCP client+server / RAG / mock data / LLM · working free-tier deploy · CI with MCP test · strong eval across all metrics · strong docs and demo.

## Working Conventions
- Record AI-tool usage (what worked / what didn't) in `ai-tooling.md` as you go, not at the end.
