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
- [x] **Second real Render deploy failed** with "Out of memory (used over 512Mi)" — the port-bind fix worked (port opened immediately, `/health` correctly 503'd while building), but embedding the corpus crossed 512Mi. Root cause, found by measuring both processes' real RSS locally (not guessed): **the embedding model was loading in *two* separate processes at once.** `app/main.py`'s background task ingested in the FastAPI process itself; separately, the MCP server subprocess loaded its *own* copy the first time `search_policy_documents` ran. Isolated measurement: constructing `SentenceTransformerEmbeddingFunction` alone used ~470MB (torch's own baseline, before embedding anything) — twice, in two processes, on top of each process's other overhead.
  - **Fix 1 — one embedding owner.** Switched to chromadb's bundled `ONNXMiniLM_L6_V2` (onnxruntime, not torch/sentence-transformers — same all-MiniLM-L6-v2 model, ~330MB lower baseline) and moved ALL index-building into `app/ingest.get_ready_collection()`, called only from `app/retriever.py` (i.e. only ever from the MCP subprocess). `app/main.py` (FastAPI) now only ever calls `count_chunks()`, which never constructs an embedding function at all — verified by a test that spies on `get_embedding_function` rather than checking `sys.modules` (checking `sys.modules` for `onnxruntime` doesn't work: `import chromadb` alone already imports it as chromadb's *own* internal side effect, confirmed directly, so that's not a usable signal — the real guarantee is that the expensive constructor is never called).
  - **Fix 2 — batch the ingest.** Embedding all 97 chunks in one `upsert()` call peaks near 900MB regardless of library (onnxruntime's/torch's scratch memory scales with batch size). `INGEST_BATCH_SIZE = 4` in `app/ingest.py` brings that down to its floor (~300MB, onnxruntime's own fixed overhead — batching below 4 barely helps further).
  - **Fix 3 — background build inside the MCP subprocess**, not the FastAPI process: `mcp/server.py`'s `_serve()` runs `mcp.run_stdio_async()` and a background index-build concurrently (`anyio.to_thread`, a real OS thread — not an asyncio task on the same thread, which would block the stdio handshake the same way the FastAPI-process version once blocked the port bind). `/health` now reports `ok` within ~2s of startup with no user traffic needed, same as the Day-8-first-attempt design intended, but now scoped to one process.
  - **Correctness bug found along the way, not just a performance one:** the naive version of fix 3 (each caller building its own fresh `chromadb.Collection` object) let two concurrent first-callers both pass the "is it empty?" check and both call `ingest()` — a *second*, separate `PersistentClient`/`Collection` instance against the same on-disk path isn't guaranteed to immediately see a first instance's just-committed write. Caught by a real concurrency test (5 threads racing `get_ready_collection()` on an empty index), not by inspection. Fixed by caching one `Collection` object per `db_path` in `app/ingest.py` (`_collection_cache`, `threading.RLock` — an `RLock` specifically because `get_ready_collection()` holds the lock while calling `ingest()`, which itself calls the now-lock-acquiring `get_collection()` on the same thread; a plain `Lock` deadlocks there).
  - **Also applied:** `render.yaml`'s `startCommand` adds `--loop asyncio --http h11`, forcing uvicorn's pure-Python loop/HTTP parser instead of auto-selecting `uvloop`/`httptools` — measured ~20MB lower FastAPI-process baseline for a low-traffic API that doesn't need the throughput they're for.
  - **Result, measured end-to-end locally** (empty index → auto-ready → 3 concurrent `/chat` calls, real `ps` RSS on both processes): **combined peak ~745MB → ~570-595MB.** A real, verified ~150-175MB reduction — but per this same local measurement, still likely over Render's exact 512Mi. macOS ARM numbers aren't guaranteed to match Render's Linux x86_64 container exactly (different allocator, thread scheduling), so this is the honest current estimate, not a settled number — only a real deploy resolves that.
  - **Considered and set aside:** tuning onnxruntime's `SessionOptions` (thread count, memory arena) — measured *worse*, not better, so not applied. Removed now-unused `sentence-transformers`/`langchain*`/`markdown`/`tqdm` from `requirements.txt` and the dead `EMBEDDING_MODEL` env var along the way.
  - **The bigger lever, not yet attempted [superseded below]:** merging the MCP server into the FastAPI process itself would eliminate a *second Python process's* baseline overhead entirely, not just the double-embedding-load.
- [x] **Deployed the fix above via `render deploys create` (Render CLI). It worked, but marginally: the first cold-start attempt crashed partway through ingestion (~56/97 chunks) with no "Out of memory" banner this time (a graceful `Shutting down`, more like Render proactively cycling the container near the limit than a hard OOM-kill) and auto-restarted; the retry made it to 97/97 and has been stable since, answering real `/chat` requests correctly (~9s, one real question tested end-to-end).** This is real progress — from a guaranteed hard crash to a service that works once warm — but every future cold start (which the free tier does automatically after inactivity, and there's no persistent disk to skip re-ingesting) repeats that same 1-in-N-attempts risk. Decided not to leave this as "works, mostly" for a graded demo.
- [x] **Pursued the bigger lever: merged the MCP server into the FastAPI process for the deployed instance**, using the MCP SDK's in-memory transport (`mcp.shared.memory.create_connected_server_and_client_session`) instead of a stdio subprocess — eliminating a second whole process's baseline, not just the double-embedding-load fixed above.
  - **Kept both transports, not a rip-and-replace.** `config.MCP_TRANSPORT` ("stdio" default | "inmemory"). Local dev and every existing test still get a real subprocess talking real MCP-over-stdio — that's the architecture actually demonstrated and covered by all the existing subprocess tests, and it's genuinely useful to be able to see/debug locally. `render.yaml` sets `MCP_TRANSPORT=inmemory` only for the deployed instance, where the 512Mi budget is real.
  - **The `mcp/` vs `mcp`-SDK name collision (Day 4/5's constraint) meant `mcp/server.py` still can't be `import`ed by dotted path** even to merge it in-process. Solved with `app/agent.py`'s `_load_mcp_server_module()`: loads it by file path via `importlib.util.spec_from_file_location` under an internal name, so `import mcp.server` is never written anywhere and the SDK is never shadowed. Its `if __name__ == "__main__":` block correctly never fires under this load path (module name isn't `"__main__"`), so it doesn't try to also run its own stdio loop.
  - **`HRAgent.connect()`** branches on transport: "inmemory" loads that module, connects through `create_connected_server_and_client_session(server_module.mcp._mcp_server)`, and fires the *same* `_build_index_in_background()` coroutine mcp/server.py's subprocess mode uses (via `asyncio.create_task`, not `anyio.to_thread`'s own subprocess-mode task group — `anyio.to_thread.run_sync` inside it works fine on a plain asyncio loop regardless) so `/health` still goes ready without needing traffic first, same guarantee as the subprocess mode. `app/main.py`'s `create_app()` gained a `transport` parameter so tests can exercise the *real app* under either mode.
  - **Result, measured locally:** in-memory mode is genuinely one process — confirmed via `ps`/`pgrep`, no `mcp/server.py` process exists at all — peaking at **~409MB** (vs the ~570-595MB two-process sum before). ~160-185MB of real margin recovered, on top of the ~150-175MB already recovered in the fixes above. 6 new tests (`tests/test_agent.py`, prefixed `test_inmemory_*`) prove this path is genuinely functional end to end (tool discovery, a real multi-step workflow with real citations, own-records-only enforcement, the background build, and the full FastAPI app under `TestClient` in this exact mode) — not just that it type-checks. 111/111 tests passing, `ruff check .` clean.
  - **Not yet done:** redeploy with this change and confirm it survives cold start reliably (ideally several times, not once) before calling this closed.
- [ ] Once a deploy is confirmed reliably stable: create the Render service from `render.yaml` if not already done, set `OPENROUTER_API_KEY` in its dashboard, copy its Deploy Hook URL into the GitHub repo's `RENDER_DEPLOY_HOOK_URL` secret
- [ ] Share the repo with GitHub user `quantic-grader` (repo Settings → Collaborators)
- [ ] `deployed.md` (deployed URL, `/health` URL, cold-start notes) — needs a real, reliably stable deployment to write truthfully

### ✅ Days 9–10 — Evaluation DONE
- [x] `evaluation/eval_set.json` — 25 items: 6 straightforward, 5 multi-doc, 6 tool-requiring, 4 ambiguous, 4 out-of-scope. Each has `expected_doc_ids`, `expected_tools`, `expected_behavior` (answer/clarify/decline/escalate/refuse_other_employee) grounded against the actual corpus content and mock employee data (verified against the real `.md`/HTML/PDF section headings and `mock_data/*.json`, not guessed).
- [x] `evaluation/run_eval.py` — runs the real agent (stdio transport, the architecture the tests demonstrate) over the full set. Scores: groundedness (LLM-as-judge, batched into one call per run — see below for why), citation accuracy (recall of expected doc_ids), tool-selection accuracy, workflow completion rate, escalation/clarification/decline accuracy, latency p50/p95 + cold-vs-warm split. Plus one ablation (retrieval top_k recall, no LLM, exact).
- [x] **A real eval found a real production bug, not just a scoring artifact.** First full run: 3 of 5 multi-doc items scored `citation_accuracy = 0.0` even though manual inspection showed the model's answers *were* correctly, fully cited. Root cause: `nvidia/nemotron-3-super-120b-a12b:free` sometimes writes citations using Unicode lookalikes instead of plain ASCII — fullwidth CJK brackets (`【POL-HR-005: Day 1 Activities】`) and `U+2011 NON-BREAKING HYPHEN` inside doc ids (`POL‑IT‑001`) — which `app/agent.py`'s `CITATION_RE` silently failed to match, dropping real citations from the response. **This affects live `/chat` responses too, not just eval scoring** — any user whose answer happened to get this formatting would see "no citations" despite a fully grounded answer. Fixed by normalizing known lookalikes (`_CITATION_MARKUP_NORMALIZE`) before matching, rather than trying to enumerate every Unicode variant inside the regex itself. Verified directly against the real stored answers from the failing run: all 3 now extract both expected doc_ids correctly. Two regression tests added (`test_citation_survives_unicode_lookalike_brackets_and_hyphens`, `test_citation_survives_non_breaking_hyphen_in_doc_id`). 115 tests passing.
- [x] **Groundedness judging is batched into one LLM call for the whole run**, not one per item — discovered mid-build that OpenRouter's free tier caps requests at **50/day account-wide** (`x-ratelimit-limit: 50`, confirmed via response headers; the error message says "free-models-per-day", i.e. shared across all free models, so switching models doesn't help). A 25-item multi-turn agent run already uses ~50+ calls on its own; judging each item separately would have guaranteed exceeding the cap before the run even finished. One batched judge prompt (all items, numbered, one score per line) keeps nearly the whole budget for the agent run itself.
- [x] **First full run results (`evaluation/results.json`), recorded before the citation fix above:**
  - `workflow_completion_rate`: 0.92 · `groundedness_avg`: 0.833 (target ≥0.80 ✅) · `citation_accuracy_avg`: **0.708** (target ≥0.75, just under — but this number includes the 3 since-fixed false negatives above; manual re-extraction on the same stored answers confirms citation_accuracy would be ~0.96 post-fix, comfortably over target) · `tool_selection_accuracy`: 0.96 · `escalation_clarification_accuracy`: 0.90
  - By category: tool-requiring 1.0, out-of-scope 1.0, ambiguous 0.75 (one of four ambiguous items — "Can I take some time off?" — called `search_policy_documents` instead of asking for an employee ID first; a real, legitimate miss, not a scoring bug)
  - Latency: p50 **93.9s**, p95 **228.2s**, cold (first call) 58.7s. Far past the originally-hoped <8s target (already flagged as unlikely since Day 6) — and slower than typical even for this model: the run happened right after OpenRouter's daily quota reset at 00:00 UTC, likely under heavy shared-pool load from every free-tier user resetting at once. Earlier smoke tests of the same model saw 2-8s/item.
  - Ablation (retrieval top_k, no LLM): recall@k=3 = 0.792, recall@k=10 = 1.0 — raising top_k meaningfully improves retrieval recall on this corpus, at the cost of a longer prompt.
  - All 25 items completed with **zero crashes/unhandled errors** — a real stress test of Day 8's `LLMResponseError` fix and the agent's existing graceful-degradation handling, under much worse latency than any manual testing had hit before.
- [x] **Clean re-run after the quota reset (~24h later, per `x-ratelimit-reset`) — found a *second* real citation-formatting bug, same evaluation-driven process.** This run was much faster (free-tier load back to normal: 2-25s/item vs 58-230s the first time), and groundedness/citation accuracy both improved as predicted — but two multi-doc items still scored `citation_accuracy = 0.0`, for two *different* reasons this time:
  - `multidoc-01`: the model used **plain parentheses** instead of square brackets — `(POL-IT-001: Password and Authentication Requirements)` — a third citation-formatting variant `CITATION_RE` didn't anticipate, on top of the two already fixed. Folded `(`/`)` into `[`/`]` in the same normalization step; verified directly against this run's real stored answer (both expected doc_ids now extract correctly). Safe to fold globally (not just near a doc id) because `CITATION_RE` still requires the literal `POL-XX-NNN` pattern inside — confirmed with a dedicated test that unrelated parenthetical prose next to a real citation isn't mistaken for one.
  - `multidoc-03`: **not a bug.** The model called `search_policy_documents` and `get_policy_section` (real, relevant results came back), then chose to ask for the employee ID before synthesizing an answer, discarding the retrieved content from that turn's final response. A legitimate, if conservative, model choice this run didn't make the first time — free-tier LLM non-determinism, not something to "fix" in code. Worth noting in `design-and-evaluation.md` as an observed limitation.
  - Two more regression tests added (`test_citation_survives_parenthetical_style`, `test_parenthetical_prose_without_a_doc_id_is_not_mistaken_for_a_citation`). 117 tests passing, `ruff check .` clean.
- [x] **Final `evaluation/results.json` (this clean re-run, kept as the authentic record — not hand-corrected further):**
  - `workflow_completion_rate`: 0.92 · `groundedness_avg`: **0.875** (target ≥0.80 ✅) · `citation_accuracy_avg`: **0.792** (target ≥0.75 ✅ — already meets target as recorded; the parens fix above was verified but not re-run live a third time to avoid spending more of the daily quota chasing a number that already clears the bar) · `tool_selection_accuracy`: 0.96 · `escalation_clarification_accuracy`: 0.90
  - Latency: p50 **7.0s** (meets the <8s target!), p95 42.7s, cold (first call) 2.2s — confirms the first run's 94s/228s was genuinely abnormal post-reset load, not representative of this model's normal behavior.
  - Ablation (retrieval top_k, no LLM): recall@k=3 = 0.792, recall@k=10 = 1.0 — unchanged from the first run (deterministic, no LLM involved), confirms raising top_k meaningfully improves recall on this corpus.
  - Zero crashes/unhandled errors across all 25 items, second run in a row.

### 🟡 Days 11–12 — Docs & Demo IN PROGRESS
- [x] `README.md`, `design-and-evaluation.md`, `ai-tooling.md` (drafted — user's edit pass pending), `deployed.md` — all at repo root per spec
- [x] Architecture diagram — real SVG (`docs/architecture.svg`), rendered and visually checked before committing (one overlap fix), embedded in `design-and-evaluation.md`
- [x] Two demo tasks documented with real, observed MCP call sequences (pulled directly from `evaluation/results.json`, not hypothetical) — doubles as the demo video script
- [ ] **Not done — needs you:** the actual 7–10 min demo video recording (all group members on camera with ID — not something I can do)
- [x] `quantic-grader` repo access and `RENDER_DEPLOY_HOOK_URL` GitHub secret — both confirmed done by the user; verified the resulting CI→Render pipeline actually works end-to-end with two real triggered deploys, both succeeding

### 🟡 Day 13 — Final Review & Submit IN PROGRESS
- [x] **Full project retest (Oct 2), three real gaps found, all three fixed:**
  - **Fixed:** `evaluation/run_eval.py` never computed `action_safety_pass_rate`, despite the grading spec naming it explicitly alongside tool-selection/workflow-completion/escalation accuracy. Added `action_safety_ok()`: for every item that actually called a mock-action tool (`create_mock_hr_ticket`/`draft_hr_email`), checks the call succeeded *and* the final answer told the user it was mock/a draft — the thing code alone can't guarantee, since the tools themselves are already hardcoded safe. Computed retroactively against the already-stored `evaluation/results.json` (no new LLM calls needed, same quota-conscious principle as the citation-bug fixes) — result: **1.0** (the one item that triggers a mock action passed). `README.md`/`design-and-evaluation.md` updated.
  - **Fixed:** `evaluation/run_eval.py` had zero automated test coverage — only validated through two full live runs. Added `tests/test_run_eval.py` (23 tests) covering every deterministic, no-LLM-call piece: `score_item`'s per-category behavior checks, `action_safety_ok`, `summarize`'s aggregation and percentile math, `run_ablation`. 140 tests passing overall.
  - **Fixed, smaller:** `.github/workflows/ci.yml`'s embedding-model cache comment still referenced sentence-transformers/HF Hub, contradicting the actual path (`~/.cache/chroma/onnx_models`) fixed in an earlier session — cleaned up for consistency.
  - **Found and fixed:** the corpus was sized at ~14-21 estimated pages (42,531 total chars across 97 chunks, 10 documents), under the spec's required 30-120 page range. Expanded to **17 documents, 177 chunks, ~91,357 chars** (~30.5-45.7 estimated pages depending on chars/page assumption, comfortably inside the required range) by adding 3 brand-new policy documents (Performance Management POL-HR-011, Compensation POL-HR-012, Termination/Offboarding POL-HR-013) plus 4 more (Workplace Safety POL-HR-014, DEI POL-HR-015, Learning & Development POL-HR-016, Business Ethics POL-HR-017), and expanding 6 of the originally-shorter documents (PTO, Remote Work, Expense Reimbursement, Benefits, Onboarding, Workplace Conduct, Data Security) with genuinely new subsections (sabbatical, FSA/wellness, mobile device management, equity compensation, etc.), all cross-referencing real doc_ids consistent with the existing corpus style. Re-ran `app/ingest.py --reset --smoke` (7/7 smoke queries pass, including 2 new ones added for the new documents) and updated every stale "10 documents"/"97 chunks" reference across `README.md`, `design-and-evaluation.md`, `deployed.md`, `docs/architecture.svg`, `app/ingest.py`'s batching comment, and `tests/test_loaders.py`. Full suite: 140 tests passing, `ruff check .` clean.
  - **Confirmed healthy via Render's own telemetry** (internal health-check probes returning 200 OK, deploy status `not_suspended`) but **could not verify external reachability from this sandbox** — `https://hr-agent-xds2.onrender.com` returned TLS-level connection resets on every attempt, while unrelated sites (google.com, Render's own dashboard) worked fine from the same sandbox. Most likely cause: this sandbox's IP tripped some edge-level rate-limit/abuse-protection from the sheer volume of automated requests sent to this one endpoint across today's testing — not an application defect, since Render's own internal checks confirm the app itself is responding normally. **Needs the user to verify from their own browser/network** for a trustworthy external confirmation.
- [x] **Installed and authenticated the GitHub CLI (`gh`) in this sandbox** (`brew install gh`, then `gh auth login` — user completed the device-code browser flow), so CI run status can be checked directly going forward instead of guessing from push output alone.
- [x] **Pushed the corpus expansion (commit `a27e382`) and watched both CI and the resulting Render deploy end-to-end, via `gh run list`/`gh run view` and the Render CLI/`Monitor`:**
  - CI (`run 37040025706`): lint → tests → index-build smoke → app-start check → `test` job passed, `deploy` job (gated on tests passing) fired the Render deploy hook — both jobs green.
  - **The *previous* deploy (commit `bb50357`, the action-safety-metric fix — triggered earlier the same day but not verified live at the time since `gh` wasn't available yet) was found, retroactively, to have genuinely crashed**: its new server process bound the port and served `/health` 200 OK for ~30s, then **both** the outgoing and incoming uvicorn processes shut down at 16:03:53-54 with no OOM banner (same "graceful `Shutting down`, more like Render proactively cycling near the memory limit" signature as the Day 8 incidents) and **never restarted** — the deploy then sat with zero running processes for 17 minutes until Render's own orchestrator gave up with "Timed Out" and marked it `update_failed`. Render does not swap a failed deploy into production, so the site kept serving the prior successful build throughout — real users were never actually down — but this is a second, previously-undetected data point that the in-memory/merged-process architecture is still marginal on Render's free 512Mi tier, now worth paying attention to as the corpus (and its embedding memory use) grows.
  - **The corpus-expansion deploy (`a27e382`, 177 chunks vs. 97) did not repeat that crash**: clean build (~1 min), port bound and `/health` flipped 503→200 in ~37s, deploy reached `live` in ~2.5 minutes total, zero crashes observed. One data point only — doesn't rule out the same intermittent risk recurring on a future cold start, consistent with Day 8's "1-in-N-attempts" framing — but a bigger corpus did not make it worse in this instance.
  - **External reachability still could not be verified from this sandbox** on this attempt either (TLS `Connection reset by peer` immediately after the Client Hello, both over IPv6 and with `-4` forcing IPv4; control requests to google.com and render.com succeeded from the same sandbox in the same minute) — same unresolved sandbox-vs-Render's-edge issue as earlier in the day, still not resolved, still needs the user's own browser/network to confirm.
- [x] **User confirmed the live site worked from their own browser** (Oct 2) — the sandbox TLS-reset issue above was confirmed sandbox-specific, not an app defect.
- [x] **(Oct 3) User reported the live site "timing out again."** Root-caused via `render logs` (now checkable directly thanks to the `gh`/Render CLI access set up the day before) to a genuine crash loop, not LLM latency: a live `/chat` request calling tools would get ~60-70s in, then the **entire container would restart** — no OOM banner, same "proactively cycling near the memory limit" signature as the Day 8 incidents — discarding the in-flight request. Traced further: **every single restart, not just the first cold start, was re-downloading the 79MB ONNX model and re-embedding all 177 chunks from scratch** before serving again. That's the real regression introduced by the Day 13 corpus expansion (97 → 177 chunks): the batch-bounded-but-still-real embedding memory spike that used to happen once per deploy was now recurring on *every* crash, and doing so while a live request's own memory use was active is plausibly exactly what was pushing the process over 512Mi.
  - **Fix:** moved ingestion from the running process into the Render **build** step (`render.yaml`'s `buildCommand` now runs `python -m app.ingest --reset --smoke` after `pip install`, instead of just `pip install`). The running process's `get_ready_collection()` already only calls `ingest()` when `count_chunks() == 0` — with the index pre-built at build time, that's never true at runtime, so the live process now only ever embeds one short query at a time (for retrieval), never the whole corpus. Every restart — cold start or crash — comes back with the index already on disk instead of rebuilding it from scratch. `--smoke` fails the *build* (not a half-broken deploy) if retrieval quality regresses.
  - Verified locally first (not just reasoned about): ran the exact build command against a throwaway `CHROMA_PERSIST_DIR`, confirmed 7/7 smoke queries pass, then confirmed `count_chunks()` alone (the only thing the FastAPI process calls, per its existing no-embedding-function guarantee) sees the pre-built 177 immediately without touching the embedding function. Full suite: 140 tests passing, `ruff check .` clean.
  - **Not yet verified against a real deploy** — this is a real-time-in-progress fix; the next step is pushing it and watching both the build step and live chat traffic (via `render logs`) to confirm the crash loop is actually gone, not just theoretically fixed.

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
| `app/agent.py` | Orchestrator: MCP client + tool-calling loop + trace (Day 5, done). `HRAgent(transport=...)`: "stdio" (subprocess, default/tests) or "inmemory" (in-process, Day 8's deployed mode) |
| `mcp/server.py` | MCP tool server, 7 tools (Days 4–5, done); `mcp/_smoke_test.py` manual client check |
| `corpus/` | 10 policy docs (8 MD, 1 HTML, 1 PDF) |
| `mock_data/` | Mock employees, PTO balances, benefits |
| `evaluation/` | Eval set + metrics runner (Day 9–10, not yet created) |
| `.github/workflows/ci.yml` | CI: lint, import/start checks, tests, gated deploy (Day 8, workflow written; not yet run for real) |
| `render.yaml` | Render blueprint (Day 8); sets `MCP_TRANSPORT=inmemory` for the deployed instance only |

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
- **Memory for Render's free tier (512Mi).** The deployed instance runs `MCP_TRANSPORT=inmemory` (`render.yaml`) specifically because two real deploys showed a stdio subprocess architecture is too tight on 512Mi (one hard OOM, one deploy that needed 2 cold-start attempts to survive even after fixing that) — see Day 8's full history above before touching `app/ingest.py`, `app/agent.py`'s transport branch, `mcp/server.py`'s `_serve()`, or `render.yaml`'s env. Local dev / tests default to `MCP_TRANSPORT=stdio` (a real subprocess) and don't have this constraint. Several non-obvious things are documented in that Day 8 history: why `count_chunks()` must never call `get_embedding_function()`, why the collection cache needs an `RLock` not a `Lock`, why ingest is batched at exactly `INGEST_BATCH_SIZE=4`, why `mcp/server.py` is loaded via `importlib` by file path rather than imported normally even from `app/agent.py`.
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
