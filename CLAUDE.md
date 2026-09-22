# HR Agent — Quantic "AI Engineering Techniques and Architectures" Project

Source spec: `ai project.pdf` (Quantic). This file condenses it; when in doubt, the PDF wins.
Goal: a deployed, agentic HR policy/operations assistant = **RAG over policy docs + agent orchestrator + MCP tools over mock data**, with cited, grounded answers.

## Stack (decided)
- Python venv at `.venv/`, deps in `requirements.txt`. Secrets only via env vars (`.env` is gitignored; `.env.example` is committed).
- FastAPI web app + chat UI; LLM via OpenRouter (OpenAI-compatible client); local embeddings (`all-MiniLM-L6-v2`); Chroma vector store persisted to `CHROMA_PERSIST_DIR`.
- MCP server (`mcp` SDK) over stdio by default (`MCP_TRANSPORT`), optionally HTTP. Single-service deploy on Render/Railway free tier.
- `SEED=42` everywhere deterministic behavior matters (chunking, eval sampling).

## Repo layout (required by the grader)
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

Repo must be shared with GitHub user **`quantic-grader`**.

## Requirements checklist
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

## Demo video (7–10 min, screen share + voiceover)
Two end-to-end agentic tasks on the **deployed** app; for each, explain tool names, arguments, outputs, citations, final answer/action. Plus quick walkthrough of design, deployment, CI/CD, eval results. Group members must all speak, be on camera, and show government ID.

## Rubric emphasis (score 5)
Cited/grounded answers · fully working MCP with clear traces and error handling · two multi-step tasks using RAG + mock-data tools · clean separation of web app / orchestrator / MCP client+server / RAG / mock data / LLM · working free-tier deploy · CI with MCP test · strong eval across all metrics · strong docs and demo.

## Working conventions
- Never commit secrets or `.venv/`/`venv/`; keep `.env.example` in sync when adding env vars.
- Keep corpus and mock data small (free-tier resources); mock data must be obviously synthetic.
- Record AI-tool usage (what worked / what didn't) in `ai-tooling.md` as you go, not at the end.




# HR Agent — Claude Code Project Context

**Owner:** Luis Toruno (lutor23) | **Deadline:** October 4, 2026
**Repo layout below follows the grader spec above** (`app/`, `mcp/`, `mock_data/`, `evaluation/`, `docs/`) — a prior planning pass used `src/`/`data/`/`eval/` instead; that was renamed on Sep 22 to match the spec. If you see `src.` or `data/` in an old doc or comment, it's stale.

**Stack:** FastAPI · ChromaDB · sentence-transformers (all-MiniLM-L6-v2) · OpenRouter free tier · MCP SDK · pytest · GitHub Actions · Render

---

## Master Task List

### ✅ Day 1 — Scaffold (Sep 22) DONE
- [x] `requirements.txt`, `.env.example`, `.gitignore`
- [x] 10-document policy corpus: 8 Markdown + 1 HTML + 1 PDF in `corpus/`

### ✅ Day 2 — Data & Ingestion (Sep 22) DONE
- [x] `mock_data/employees.json`, `pto_balances.json`, `benefits.json` — 10 employees (E001–E010)
- [x] `app/loaders.py` — `Chunk` dataclass + MD/HTML/PDF loaders, heading-aware chunking → **97 chunks** (not 146 — that earlier estimate was wrong; 97 is correct for 10 docs at ~1200 chars/chunk)
- [x] `app/ingest.py` — embed + upsert into ChromaDB, `--reset`/`--smoke` CLI flags, 5/5 smoke queries pass

### ✅ Day 3 — RAG Pipeline (Sep 22) DONE
- [x] `app/retriever.py` — `retrieve()`, `build_prompt()`, `ask()`, `extract_citations()`, `employee_context()`
- [x] Guardrail: chunks below cosine 0.25 are dropped; empty result → "couldn't find a policy" (no hallucination)
- [x] Unknown `employee_id` → graceful error, not a crash
- [x] LLM timeout/error → partial answer (top retrieved chunk + citation) instead of failing the request
- [x] Manually verified: single-doc, multi-doc (remote-work query spans 3 sections), off-topic, unknown-employee, personalized (with employee context)
- [x] `tests/test_loaders.py`, `tests/test_retriever.py` — 18 tests passing

### 🔲 Day 4 — MCP Server (Sep 25)
- [ ] `mcp/server.py` — MCP server skeleton with stdio transport (spec requires a top-level `mcp/` dir, not `app/mcp_server.py`)
- [ ] Tool: `search_policy_documents(query, top_k=5)` — wraps `app.retriever.retrieve`
- [ ] Tool: `get_policy_section(doc_id, section)`
- [ ] Tool: `lookup_employee_profile(employee_id)`
- [ ] Tool: `check_pto_balance(employee_id)`
- [ ] Tool: `lookup_benefits_status(employee_id)`
- [ ] Verify all 5 tools register and return correctly typed responses; agent must call them *through* MCP, not as direct function calls

### 🔲 Day 5 — Action Tools & Agent (Sep 26)
- [ ] Tool: `create_mock_hr_ticket(employee_id, type, description)` → ticket ID (mock/in-memory only)
- [ ] Tool: `draft_hr_email(to, subject, context)` → draft string via LLM
- [ ] `app/agent.py` — orchestrator loop: plan → tool calls → synthesize answer
- [ ] ≥2 multi-step workflows (e.g. PTO request guidance + balance check; remote-work eligibility + data-security policy)
- [ ] Structured, visible tool-call trace (no hidden chain-of-thought)
- [ ] Graceful handling: MCP tool down, ambiguous request → ask for clarification

### 🔲 Day 6 — FastAPI App (Sep 27)
- [ ] `app/main.py` — FastAPI app + minimal chat UI (spec requires a UI, not just the API)
- [ ] `POST /chat` with `ChatRequest`/`ChatResponse` (already defined in `app/models.py`)
- [ ] `GET /health` → `{status, chroma_docs, version}` plus MCP connectivity
- [ ] Wire agent into `/chat`; 503 if ChromaDB empty

### 🔲 Day 7 — Tests (Sep 28)
- [ ] `tests/test_mcp_tools.py`, `tests/test_api.py` (loaders/retriever tests already exist)
- [ ] App-starts test + MCP tool discovery/call test (both required by CI spec)

### 🔲 Day 8 — CI/CD & Deployment (Sep 29)
- [ ] `.github/workflows/ci.yml` — install → app-starts check → tests → deploy only if green
- [ ] `render.yaml`; push to GitHub (`lutor23/hr-agent`) and **share the repo with `quantic-grader`**

### 🔲 Days 9–10 — Evaluation (Sep 30–Oct 1)
- [ ] `evaluation/eval_set.json` — 20–30 Q&As (straightforward, multi-doc, tool-requiring, ambiguous, out-of-scope)
- [ ] `evaluation/run_eval.py` — groundedness, citation accuracy, tool-selection accuracy, latency p50/p95, ≥1 ablation

### 🔲 Days 11–12 — Docs & Demo (Oct 2–3)
- [ ] `README.md`, `design-and-evaluation.md`, `ai-tooling.md`, `deployed.md` (all required at repo root, see spec above)
- [ ] Architecture diagram; 7–10 min demo video, two agentic tasks, all group members on camera with ID

### 🔲 Day 13 — Final Review & Submit (Oct 4)

---

## Key Files

| File | Purpose |
|------|---------|
| `app/loaders.py` | Chunk dataclass + MD/HTML/PDF loaders |
| `app/ingest.py` | Embed + upsert into ChromaDB |
| `app/retriever.py` | RAG query, prompt builder, citations (Day 3, done) |
| `app/employee_data.py` | Read-only lookups against `mock_data/*.json` |
| `app/models.py` | Shared `ChatRequest`/`ChatResponse`/`Citation`/`HealthResponse` |
| `app/config.py` | Env-driven settings |
| `mcp/` | MCP tool server (Day 4, not yet created) |
| `corpus/` | 10 policy docs (8 MD, 1 HTML, 1 PDF) |
| `mock_data/` | Mock employees, PTO balances, benefits |
| `evaluation/` | Eval set + metrics runner (Day 9–10, not yet created) |

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

- OpenRouter free tier: model availability and rate limits are unstable; `ask()` degrades gracefully (returns top chunk + citation) rather than failing outright.
- `requirements.txt` pins `pydantic==2.9.2`, which conflicts with `mcp==1.2.0`'s `pydantic>=2.10.1`; bumped to `pydantic==2.10.6` — don't revert without also relaxing the mcp pin.
- Never commit `.venv/`/`venv/` — an earlier local venv was accidentally added to git tracking before `.gitignore` was fixed; already untracked, stays untracked.
