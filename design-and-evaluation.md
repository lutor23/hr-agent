# Design & Evaluation

Companion to [`README.md`](./README.md) (setup/usage) and [`deployed.md`](./deployed.md)
(live deployment, cold-start behavior). This document covers architecture, design
rationale for every major decision, the two demo tasks' expected tool-call sequences,
and full evaluation results and methodology.

## 1. Architecture

![Architecture diagram: browser/curl calls the FastAPI app, which runs one long-lived agent orchestrator; the orchestrator calls an LLM provider and, over the real MCP protocol, an MCP server exposing 7 tools; the MCP server reads the RAG index (ChromaDB + corpus) and mock employee data](docs/architecture.svg)

**Why this shape.** The web app never touches the RAG index or employee data
directly — every read goes through an MCP tool, so the same tool surface that a
human-reviewed grader hits over `/chat` is exactly what the agent itself calls. This
is also why MCP tools, not direct function calls, satisfy the project's core
requirement: the agent only ever learns what's in the corpus or the mock data through
a real `call_tool()` round-trip, provable by the `trace` on every response.

## 2. RAG design

| Decision | Choice | Why |
|---|---|---|
| Corpus | 17 Acme Corp HR/IT policy documents (~91K characters, ~30-46 estimated pages): 15 Markdown, 1 HTML, 1 PDF | ≥2 source formats required; chosen formats match how real policy docs actually show up (wiki markdown, a web page, a signed PDF) |
| Chunking | Heading-aware, then paragraph-packed to ~1200 chars | Keeps a policy section's ideas together instead of splitting mid-thought; the heading becomes the chunk's `section` metadata, which is what citations are built from |
| Embedding model | `all-MiniLM-L6-v2`, via chromadb's bundled ONNX runtime (not sentence-transformers/torch) | Same model either way; the ONNX path has no torch dependency, which matters a lot once the free-tier memory story (§6) is accounted for |
| Vector store | ChromaDB, local persistent client, cosine similarity | No external service, persists to disk, trivial to reset for tests |
| Retrieval | `top_k` (tool-exposed, model picks; default 5), cosine ≥ 0.25 cutoff | Below-threshold chunks are dropped before the LLM ever sees them — an out-of-corpus question returns *no* chunks, not a weak match dressed up as an answer |
| Citations | `[DOC-ID: Section]`, verified post-hoc against what a tool actually returned | The model cites inline; `app/agent.py` then checks every cited doc/section against the real tool results for that turn and silently drops anything that isn't verifiable — the model cannot cite a document it never retrieved |

**Guardrail in practice:** asking "What's the best pizza topping?" returns zero
chunks (score threshold), so the agent has nothing to answer from and says so,
without ever reaching the LLM for retrieval-dependent content.

**Multi-document questions:** retrieval runs at the chunk level across the whole
corpus (no per-document silo), so a single `search_policy_documents` call can and does
surface chunks from two different policies in one result set. Section 5 (ablation)
measures how reliably this captures *both* relevant documents on genuinely two-topic
questions.

## 3. MCP design

**Transport.** Two modes, selected by `MCP_TRANSPORT`:

- **`stdio` (default — local dev and every test use this):** the agent spawns
  `mcp/server.py` as a real, separate OS process and talks to it over the actual MCP
  wire protocol (`StdioServerParameters`, `ClientSession`). This is the architecture
  the project's rubric describes and the one `tests/test_mcp_tools.py` and
  `tests/test_agent.py` exercise directly.
- **`inmemory` (Render's deployed instance only):** the same tools run inside the
  FastAPI process, connected through the SDK's `create_connected_server_and_client_session`
  — still genuine `ClientSession`/`list_tools`/`call_tool` protocol objects, just
  without a second OS process. This exists *only* because a second process's memory
  footprint didn't fit Render's free 512MB limit alongside the embedding model — see
  §6 for the full story. The tool implementations, schemas, and the client-side code
  path in `app/agent.py` are identical either way; only how the two ends connect
  differs.

One subtlety worth documenting: this project's required top-level directory name,
`mcp/`, collides with the installed `mcp` SDK package of the same name. `mcp/` has no
`__init__.py`, and `mcp/server.py` is never imported by dotted path anywhere in the
codebase (not even to merge it in-process — `app/agent.py` loads it by file path via
`importlib`) — either approach would otherwise shadow the real SDK.

**Tools (7).**

| Tool | Args | Returns | Backed by |
|---|---|---|---|
| `search_policy_documents` | `query: str, top_k: int = 5` | List of `{doc_id, title, section, source_file, text, score}` | RAG index |
| `get_policy_section` | `doc_id: str, section: str` | Full section text + metadata, or `{"error": "not_found"}` | RAG index (exact metadata match, not similarity search) |
| `lookup_employee_profile` | `employee_id: str` | Employee record, or `{"error": "employee_not_found"}` | Mock data |
| `check_pto_balance` | `employee_id: str` | PTO balance (available/pending/used/carryover hours) | Mock data |
| `lookup_benefits_status` | `employee_id: str` | Medical plan, coverage tier, 401(k), enrollment status | Mock data |
| `create_mock_hr_ticket` | `employee_id, type, description` | Ticket id + status (in-memory only, resets on restart) | Mock action |
| `draft_hr_email` | `to, subject, context` | Draft body (LLM-written, template fallback), `sent: false` always | Mock action, calls the LLM internally |

At least one tool reads the RAG index (`search_policy_documents`, `get_policy_section`)
and at least one performs a mock write (`create_mock_hr_ticket`, `draft_hr_email`),
per the requirement. Every tool returns **structured errors** (`{"error": "..."}`)
rather than raising — the agent handles a failed lookup the same way it handles a
successful one, no special exception-handling path needed, and a failed tool call
still shows up in the trace as a normal (if unsuccessful) step.

**Discovery.** The agent never hardcodes tool names or schemas: it calls
`session.list_tools()` on connect and passes whatever comes back straight through as
OpenAI-format `tools` on every LLM call. Adding a tool to `mcp/server.py` requires no
change to `app/agent.py` at all.

## 4. Agent orchestration

`app/agent.py`'s `HRAgent.run()` is a standard tool-calling loop, capped at 6 tool
calls per request:

1. Send the conversation (system prompt + user message + any prior tool results) to
   the LLM with the discovered tool schemas attached.
2. If the LLM's reply has no tool calls, that's the final answer — verify its
   citations against what tools actually returned this turn, and stop.
3. If it has tool calls, execute each one through `session.call_tool()` (never a
   direct function call), record a `TraceStep` (tool, arguments, success, a short
   result summary, duration), feed the result back to the LLM, and loop.
4. If the loop hits 6 steps without a final answer, stop and say so rather than
   looping forever.

**The operational trace is not chain-of-thought.** `ChatResponse.trace` is a list of
`{step, tool, arguments, ok, result_summary, duration_ms}` — exactly what ran, with
what inputs, and whether it worked. The model's own reasoning tokens are never
exposed; the trace is built entirely from the tool-call protocol messages, which is
why it's genuinely auditable rather than a paraphrase of the model's internal
monologue.

**Guardrails:**

- **Own-records-only.** If a signed-in employee's tool call requests a *different*
  employee's `employee_id`, `HRAgent` intercepts it before it reaches MCP at all and
  returns `{"error": "not_authorized"}` — the other employee's data never leaves the
  server, even transiently.
- **No guessing without an employee ID.** The system prompt instructs the model to
  ask for an employee ID rather than fabricate one; `ambiguous-*` eval items test
  this directly (§5).
- **No irreversible actions.** `create_mock_hr_ticket` and `draft_hr_email` are
  explicitly named as mock/draft-only in the system prompt, and the tools themselves
  enforce it (`sent: false` is hardcoded, tickets live only in server memory).
- **Graceful degradation, not crashes.** An LLM timeout, a malformed API response (see
  §6's `LLMResponseError`), or an MCP tool going unavailable all produce a plain
  "couldn't do that, try again" answer with `error` set — never an unhandled exception
  surfacing as a raw 500 to the caller. Verified directly: a bug that caused exactly
  this (OpenRouter returning HTTP 200 with `choices: null`) made it to the live
  deployment once and was fixed the same day (see `CLAUDE.md`'s Day 8 history).

## 5. Deployment choices

Free tier (Render web service), no paid database, `render.yaml` as
Infrastructure-as-Code. Three real failures during deployment drove the final design,
documented in full in `CLAUDE.md`'s Day 8 entries — summarized here:

1. **Port-bind deadlock.** Running ingestion as a blocking pre-step before `uvicorn`
   started meant the port never opened in time for Render's health-check scan.
   Fixed by building the index as a background task that runs concurrently with
   serving requests.
2. **Out-of-memory crash.** The embedding model was being loaded in *two* separate
   processes at once (the web process, eagerly, and the MCP subprocess, lazily on
   first search) — found by directly measuring both processes' real memory, not
   guessed. Fixed by giving exactly one process ownership of the embedding model,
   switching to the lower-memory ONNX embedding path, and batching the ingest.
3. **Marginal survival under load.** Even after fix 2, a stdio-subprocess
   architecture still needed two attempts to survive its own cold-start ingestion on
   Render's 512MB limit. Fixed by merging the MCP server into the FastAPI process
   itself for the deployed instance only (`MCP_TRANSPORT=inmemory`, §3) — eliminating
   a second whole process's baseline memory, not just the double-loading. Verified
   stable across repeated cold starts afterward.

**Cold starts** fully re-embed the corpus every time (no persistent disk on the free
tier) — the port opens in about a second regardless, and `/health`'s `chroma_docs`
count climbs as the background build progresses. Full detail in `deployed.md`.

## 6. Two demo tasks

Both run as a single `/chat` call; sequences below are **actually observed**, copied
from a real evaluation run (`evaluation/results.json`), not hypothetical.

### Task A — Personalized policy question (RAG + mock-data tool combined)

> **Request:** `POST /chat {"message": "Can I take two weeks off in December? What's my balance and what's the process?", "employee_id": "E001"}`

| Step | Tool | Arguments | Result |
|---|---|---|---|
| 1 | `check_pto_balance` | `{"employee_id": "E001"}` | 96h available, 8h pending, 48h used, 16h carryover |
| 2 | `search_policy_documents` | `{"query": "PTO request process time off request procedure", "top_k": 5}` | 5 chunks from the PTO Policy |

**Answer (excerpt):** "Your current PTO balance shows 96 hours available... which
covers the 80 hours needed for a 10-day (two-week) leave... **Process for a two-week
leave** [POL-HR-001: PTO Request Process]: submit in the HR portal, manager approval
within 2 business days, department-head approval required for 10+ consecutive
business days, HR notified at least 15 business days in advance..."

This demonstrates combining a mock-data tool (the employee's real balance) with a RAG
tool (the policy's approval steps) in one answer, citing only the policy half.

### Task B — Escalation workflow (profile lookup + RAG + two mock actions)

> **Request:** `POST /chat {"message": "I have a question about my FMLA eligibility. Please open an HR ticket and draft an email to hr@acmecorp.example.com about it.", "employee_id": "E004"}`

| Step | Tool | Arguments | Result |
|---|---|---|---|
| 1 | `lookup_employee_profile` | `{"employee_id": "E004"}` | Daniel Kim, HR Business Partner, hired 2022-01-24 |
| 2 | `search_policy_documents` | `{"query": "FMLA eligibility", "top_k": 5}` | 5 chunks, including the Leave of Absence Policy |
| 3 | `get_policy_section` | `{"doc_id": "POL-HR-010", "section": "Family and Medical Leave (FMLA)"}` | Full FMLA eligibility text |
| 4 | `create_mock_hr_ticket` | `{"employee_id": "E004", "type": "leave", "description": "..."}` | `{"ticket_id": "HR-0001", "status": "open (mock)", "mock": true}` |
| 5 | `draft_hr_email` | `{"to": "hr@acmecorp.example.com", "subject": "FMLA Eligibility Inquiry...", "context": "..."}` | Draft body, `sent: false` |

**Answer (excerpt):** "I've opened a mock HR ticket for your FMLA eligibility
question and drafted an email to HR for you to review. **Mock HR Ticket** — Ticket
ID: HR-0001, Status: open (mock)... **Draft Email** — [full body]... This is a draft;
it has not been sent."

This demonstrates a 5-step, 3-tool-type workflow (profile → RAG → two mock actions)
completing in one turn, with the response explicitly flagging both actions as
mock/draft per the no-irreversible-actions guardrail.

## 7. Evaluation

### Methodology

25 items in [`evaluation/eval_set.json`](./evaluation/eval_set.json), across the
required 5 categories, each grounded against the actual corpus section headings and
`mock_data/*.json` content (verified directly, not guessed):

| Category | n | Tests |
|---|---|---|
| Straightforward | 6 | Single-document policy lookups |
| Multi-doc | 5 | Questions spanning two policies (e.g. remote work + data security) |
| Tool-requiring | 6 | Personal data lookups, a combined PTO+policy workflow, an escalation workflow, and an own-records-only violation attempt |
| Ambiguous | 4 | No employee ID / no specifics — should ask, not guess |
| Out-of-scope | 4 | Not in the corpus at all — should decline, not hallucinate |

[`evaluation/run_eval.py`](./evaluation/run_eval.py) runs every item through the real
agent (stdio transport) and scores:

- **Groundedness** — LLM-as-judge, grading the answer against each citation's *full*
  section text (not the UI-truncated snippet — see the note on the groundedness-judge
  bug below). Batched into **one** LLM call for the whole run, not one per item: a
  discovered constraint, below.
- **Citation accuracy** — recall of `expected_doc_ids` against what the answer
  actually cited.
- **Tool-selection accuracy** — did the agent call (at least) the expected tools.
- **Workflow completion rate** — finished with no error and no failed tool step.
- **Escalation/clarification/decline accuracy** — category-specific behavior checks
  (asked a real clarifying question; declined without citing anything; escalated with
  `escalated: true`; refused another employee's data).
- **Action-safety pass rate** — for every item that actually called a mock-action tool
  (`create_mock_hr_ticket`, `draft_hr_email`), checks that the call succeeded *and* the
  final answer told the user the action was mock/a draft. The tools themselves are
  safe by construction regardless (`sent: false` and `mock: true` are hardcoded, unit
  -tested separately) — what this specifically checks is the thing code alone can't
  guarantee: whether the model actually communicated that to the user, rather than
  presenting a mock action as if it were real.
- **Latency** — p50/p95 across all 25 items, cold (first call) vs. warm.
- **Ablation** — retrieval `top_k` recall, computed directly against the index with no
  LLM involved.

### A hard constraint discovered mid-build

OpenRouter's free tier caps requests at **50/day, account-wide** (confirmed via
response headers; the error message — "free-models-per-day" — makes clear it's shared
across every free model, so switching models doesn't help). A 25-item multi-turn
agent run already costs ~50+ LLM calls on its own; judging each item's groundedness
separately would have guaranteed exceeding the cap before the agent run even
finished. Fixed by batching every item needing a groundedness score into a single
judge prompt instead.

### Results (latest run, `evaluation/results.json`)

| Metric | Result | Target |
|---|---|---|
| Groundedness | **0.875** | ≥0.80 ✅ |
| Citation accuracy | **0.792** | ≥0.75 ✅ |
| Tool-selection accuracy | 0.96 | — |
| Workflow completion rate | 0.92 | — |
| Escalation/clarification accuracy | 0.90 | — |
| Action-safety pass rate | **1.0** | — |
| Latency p50 | **7.0s** | <8s ✅ |
| Latency p95 | 42.7s | <8s |
| Latency, cold (first call) | 2.2s | — |

By category, escalation/clarification/decline accuracy: tool-requiring **1.0**,
out-of-scope **1.0**, ambiguous **0.75** (one of four ambiguous items called
`search_policy_documents` instead of asking for an employee ID first — a real,
legitimate model miss, not a scoring artifact).

**Ablation — retrieval `top_k`:** recall@k=3 = 0.792, recall@k=10 = 1.0, computed
directly against the index (no LLM, deterministic) over every item with a known
expected document. Raising `top_k` meaningfully improves whether the right document
is even in the candidate set on this corpus, at the cost of a longer prompt — a
concrete, measured trade-off rather than an assumed one.

All 25 items completed with **zero crashes or unhandled errors**, across two full
runs.

### Two real bugs the evaluation process found (and fixed)

A first full run scored 3 of 5 multi-doc items at `citation_accuracy = 0.0` despite
the model's answers being, on inspection, fully and correctly cited. The root cause
mattered more than the score: `nvidia/nemotron-3-super-120b-a12b:free` sometimes
writes citations using characters that *look* like the requested `[DOC-ID: Section]`
format but aren't — fullwidth CJK brackets (`【...】`), `U+2011 NON-BREAKING HYPHEN`
inside doc IDs, and, in a second clean run, plain parentheses instead of square
brackets. Each silently defeated the citation-extraction regex and dropped real
citations from the response shown to the user — **a live production bug, not just an
eval scoring artifact**, since the exact same code parses every real `/chat` answer.
Fixed by normalizing known lookalikes before matching rather than trying to enumerate
every variant inside the regex itself; verified directly against the real failing
answers from both runs, with four regression tests added. Full before/after numbers
and root-cause analysis for both rounds are in `CLAUDE.md`'s Day 9 history.

A related, separate groundedness-judge bug was caught while *building* the harness,
before any full run: judging an answer against its 240-character UI-display snippet
(rather than the full cited section) scored a fully correct "5+ years of service = 20
days PTO" answer as 0.0 "ungrounded," simply because the snippet truncated mid-table
before the supporting row. Fixed by having the judge fetch each citation's complete
section text instead.

Both findings are the kind of thing a real evaluation is supposed to surface —
documented here in full rather than only as a passing score, per the project's design
emphasis on rigor over a clean-looking number.
