# Deployment

| | |
|---|---|
| **Live URL** | https://hr-agent-xds2.onrender.com |
| **Chat UI** | https://hr-agent-xds2.onrender.com/ |
| **Health check** | https://hr-agent-xds2.onrender.com/health |
| **API docs** | https://hr-agent-xds2.onrender.com/docs (FastAPI auto-generated) |
| **Platform** | Render, free web service plan, Oregon region |
| **Deployment config** | [`render.yaml`](./render.yaml) (Infrastructure-as-Code blueprint) |

## Try it

```bash
curl https://hr-agent-xds2.onrender.com/health

curl -X POST https://hr-agent-xds2.onrender.com/chat \
  -H 'content-type: application/json' \
  -d '{"message": "Can I take two weeks off in December, and what'"'"'s the process?", "employee_id": "E001"}'
```

Or open the chat UI directly and try the example prompts.

## Cold starts: what to expect

Render's free tier spins the service down after inactivity and has **no persistent disk** across *deploys* — but as of the Day 14 fix below, ingestion no longer happens at runtime at all, so a cold start within the current deploy is now fast rather than a multi-minute re-embed.

- **Corpus ingestion happens during Render's build step**, not at runtime: `render.yaml`'s `buildCommand` runs `python -m app.ingest --reset --smoke` after `pip install`, so all 177 chunks are embedded and smoke-tested *before* the service ever starts. The resulting index lives under `CHROMA_PERSIST_DIR` (a path inside the project directory), which — unlike the process's own memory — does persist from the build step into every start of the running container for that deploy, including a cold start after a period of inactivity.
- Because of that, a cold start now **binds its port, loads the already-built index, and reports `/health` as `200 OK` within about a second** — there's no 503/degraded window at all in normal operation, and no visible `chroma_docs` ramp-up to wait for.
- The ONNX embedding model itself (a separate ~79MB download, not the corpus data) is also cached under a path inside the project directory for the same reason, so it isn't re-downloaded on every restart either. The **very first retrieval call** in a freshly started process still takes a few seconds (one-time ONNX inference-session initialization — observed ~7s on a real cold start), but that's a one-time cost per process lifetime, not per-request, and doesn't involve any network download anymore.
- **Historical note:** this replaces an earlier, riskier design where ingestion happened lazily at runtime on first access. That design caused two real incidents: the first real deploy was OOM-killed batch-embedding the corpus in one process (Day 8; fixed then by batching and consolidating embedding-model ownership to one process). After the Day 13 corpus expansion (97 → 177 chunks), a second, more severe issue appeared live: the service would crash-loop under real chat traffic, because *every* restart — not just the first cold start — was re-downloading the model and re-embedding the full corpus from scratch, competing with a live request's own memory use. Moving ingestion to build time (Day 14) removes the runtime embedding spike entirely; full incident history and the real memory measurements behind this fix are in `CLAUDE.md`'s Day 13/14 entries.

## Architecture note specific to this deployment

The deployed instance runs with `MCP_TRANSPORT=inmemory` (set in `render.yaml`), meaning the MCP tool server runs inside the same process as the FastAPI app instead of as a separate subprocess. This is deploy-specific: local development and the full test suite default to `MCP_TRANSPORT=stdio`, a real separate process talking genuine MCP-over-stdio, which is the architecture actually demonstrated end-to-end in this repo's tests (`tests/test_mcp_tools.py`, `tests/test_agent.py`). The in-memory mode uses the same MCP SDK protocol objects (`ClientSession`, real `list_tools`/`call_tool` messages) over an in-process transport instead of a subprocess boundary — it exists solely because a second full Python process's memory overhead doesn't fit Render's free 512MB limit alongside the embedding model. Full reasoning and the two real failed-deploy incidents that led here are documented in `CLAUDE.md`'s Day 8 entry.

## Environment variables set on Render

See `render.yaml` for the full list. `OPENROUTER_API_KEY` is set directly in the Render dashboard (Environment tab) and is never committed to the repo.

Note: `LLM_MODEL` points at a specific OpenRouter free-tier model slug. Free-tier model availability on OpenRouter changes without notice — if `/chat` responses start erroring with a model-not-found or rate-limit error, check `GET https://openrouter.ai/api/v1/models` for a current `*:free` slug and update the `LLM_MODEL` env var in the Render dashboard (no code change needed).

## Redeploying

Deploys are **not** triggered automatically by pushing to `main` (`autoDeploy: false` in `render.yaml`) — they're gated behind CI passing, via a Render "Deploy Hook" URL stored as the `RENDER_DEPLOY_HOOK_URL` GitHub Actions secret (see `.github/workflows/ci.yml`'s `deploy` job). This means a push only reaches production if the full test suite and lint pass first.

To redeploy manually: Render dashboard → the `hr-agent` service → **Manual Deploy** → **Deploy latest commit**, or `render deploys create <service-id> --wait` via the [Render CLI](https://render.com/docs/cli).
