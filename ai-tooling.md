# AI Tooling

This capstone was built end-to-end with **Claude Code** (Anthropic's agentic CLI) as
the primary development tool, across all 13 days of the project plan in `CLAUDE.md`.
This document describes how it was used, what worked well, what didn't, and where its
output needed real verification or correction.

## How it was used

Claude Code wrote essentially all of the application code (`app/`, `mcp/`),
tests (`tests/`), the evaluation harness (`evaluation/`), CI configuration
(`.github/workflows/ci.yml`), the Render deployment config (`render.yaml`), and this
documentation set. It also ran commands directly — installing dependencies, running
the test suite, calling the live OpenRouter API to debug issues, and using the
Render CLI to trigger and monitor real deployments.

The working pattern across the project was consistently: **write code, then actually
run it** — against local tests, against a live LLM, against a real deployed service —
rather than writing code and assuming it worked. Several of the most useful outcomes
below came directly from that pattern (a written-and-tested claim turning out to be
wrong once actually exercised), not from writing more code.

## What worked well

- **Catching real bugs by actually running things, not just reading code.** The
  single clearest pattern across this project: nearly every significant bug was
  found by running the system against something real (a live deploy, a live LLM
  call, a full test suite), not by inspection. Examples:
  - The citation-formatting bug (§ below) was invisible from reading the code — the
    regex *looked* correct — and only showed up once the evaluation harness ran
    enough real LLM-generated answers to hit the model's actual, inconsistent
    output formatting.
  - The free-tier memory failures (Day 8) were diagnosed by directly measuring each
    process's real RSS with `ps`, not by reasoning about what *should* use how much
    memory — an estimate from reasoning alone would have missed that two processes
    were independently loading the same embedding model.
  - The OpenRouter 50-requests/day cap was discovered by hitting it mid-build, not
    documented anywhere obvious beforehand.
- **Holding a consistent project memory across many sessions.** `CLAUDE.md` was
  updated at the end of nearly every work session with what was decided, what broke,
  and why — including several points where the agent flagged its own earlier
  assumptions as wrong once better information arrived (e.g., an early chunk-count
  estimate, a stale model slug, a directory-naming decision that turned out to
  conflict with the grader's required layout). This let later sessions pick up
  accurately without re-deriving context, and gives this submission an honest,
  dated record of the actual build process rather than a reconstructed-after-the-fact
  narrative.
- **Treating ambiguous or consequential decisions as decisions, not defaults.** On
  several points with real trade-offs and no clearly "correct" answer — whether to
  rewrite git history to remove an accidentally committed virtualenv, whether to
  pursue a bigger architectural fix for a marginal deployment versus accepting the
  risk, whether to merge the MCP server into the web process for memory reasons —
  Claude Code asked before proceeding rather than silently picking one.

## What didn't work well / needed correction

- **A citation-parsing bug reached the live deployment before the evaluation caught
  it.** `app/agent.py`'s citation-extraction regex assumed the LLM would reliably
  follow the exact `[DOC-ID: Section]` format requested in the system prompt. In
  practice, the free-tier model (`nvidia/nemotron-3-super-120b-a12b:free`) sometimes
  used visually similar but different Unicode characters (fullwidth brackets, a
  non-breaking hyphen) or plain parentheses instead — silently dropping real,
  correct citations from the response. This wasn't caught by unit tests (which use a
  scripted fake LLM with predictable formatting) — only a real evaluation run against
  the actual model surfaced it, across two separate runs, two different specific
  formatting variants each time. Full details in `design-and-evaluation.md` §7 and
  `CLAUDE.md`'s Day 9 history.
- **An unhandled-exception path reached a live user.** OpenRouter occasionally
  returns HTTP 200 with `choices: null` in the body (an upstream provider hiccup),
  which crashed the agent's LLM-handling code with a raw `TypeError` instead of
  the graceful degradation every *other* LLM failure path already had. This was found
  because the user tested the live site immediately after a deploy and reported a
  failure — not something a code review would likely have caught, since the failure
  mode depends on a specific malformed API response that's easy to not think to guard
  against until it happens.
- **A multi-day deployment debugging arc that took real iteration, not one fix.**
  Getting the app to survive on Render's free tier took three separate real failures
  (a port-bind deadlock, an out-of-memory crash from double-loading the embedding
  model, and a still-marginal survival rate even after that fix) before landing on a
  stable architecture. Each fix was verified against a real deploy, not assumed to
  work from the code change alone — the first two "fixes" were each confirmed correct
  reasoning that nonetheless didn't fully solve the problem until measured again
  against the live service.
- **Early effort estimates for corpus chunk counts and similar details were
  sometimes wrong** (the project plan assumed 146 chunks at one point; the actual
  number, once the loaders were built and run, was 97) — a reminder that written
  plans made before any code exists are estimates, not specifications, and should be
  corrected against real output rather than carried forward unchallenged.

## GitHub CLI (`gh`) and Render CLI for operational troubleshooting

Beyond writing code, Claude Code used the **Render CLI** (from Day 8 onward) and the
**GitHub CLI (`gh`)** (installed and authenticated during the Day 13 final-review pass,
via `brew install gh` + `gh auth login`) to troubleshoot the deployed system directly,
rather than inferring its state from `git push` output or application code alone.

- **Render CLI** (`render services`, `render deploys list/create`, `render logs`,
  `render ssh`) was used throughout to trigger real deploys, pull real deploy history
  with timestamps and commit SHAs, and tail real production log lines — distinguishing,
  for example, Render's own internal `/health` probes (which stayed green throughout)
  from genuine external reachability (which repeatedly failed from this sandbox with a
  TLS-level connection reset, while unrelated sites worked fine from the same machine —
  pointing at a sandbox/network-boundary issue rather than an application defect).
- **`gh`** (`gh run list/view`, `gh auth status`) let Claude Code check real GitHub
  Actions run outcomes instead of assuming a push succeeded because the `git push`
  command itself returned no error. This directly surfaced a previously invisible
  problem: a deploy triggered earlier the same day (`bb50357`) had actually **crashed
  about 30 seconds after starting** and sat with zero running processes for 17 minutes
  before Render's own orchestrator gave up and marked it `update_failed` — something
  no one had caught, because there had been no way to introspect CI/deploy status
  directly until `gh` was installed. (Render never promotes a failed deploy into
  production, so the live site had kept serving the last *successful* build the whole
  time — real users were never actually affected — but the gap in visibility was real
  and is exactly the kind of thing that should be checked, not assumed, after every
  push to `main`.)
- A background **`Monitor`** loop (polling `render deploys list` every 15s until the
  next deploy reached a terminal status) was used to watch a subsequent deploy land
  cleanly end-to-end — live in ~2.5 minutes, no crash — turning "I pushed, it should be
  fine" into an actually-observed result, consistent with the project's broader pattern
  of verifying claims against real system behavior rather than code review alone.

## Render skills

The Render skills were installed locally with `render skills install` and consulted
for Render deployment and debugging guidance. They are generic agent reference
material, not application dependencies, so the installed `.openclaw/skills/` and
`.agents/skills/` packs are intentionally not included in this repository. The app's
deployment configuration remains in `render.yaml`.
