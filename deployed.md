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

Render's free tier spins the service down after inactivity and has **no persistent disk**, so every cold start re-embeds the entire policy corpus from scratch — there's no way to skip this on the free tier. In practice:

- The service **binds its port and starts responding within ~1 second** of a cold start — `/health` and `/chat` are reachable immediately, they just report the index isn't ready yet.
- Full ingestion (177 chunks) takes **roughly 2-3 minutes** on Render's free-tier CPU, versus a few seconds on a typical laptop — the shared CPU is genuinely slow for this.
- `/health`'s `chroma_docs` count climbs incrementally during that window (e.g. `8`, `12`, `16`, ... `177`) since ingestion is batched (`INGEST_BATCH_SIZE=4` in `app/ingest.py`) to stay within the free tier's 512MB memory limit — batching one huge embedding call was what originally OOM-killed this deployment (see `CLAUDE.md`'s Day 8 entry for the full incident history).
- **Known quirk:** `/health` reports `"status": "ok"` as soon as `chroma_docs > 0`, even if that's a partial count mid-build (e.g. `8` out of `177`). A `/chat` request during this window will get answers grounded only in whatever fraction of the corpus is indexed so far, not an error — it isn't wrong, just incomplete for those first couple of minutes. Waiting for `chroma_docs` to reach `177` (or just waiting ~2-3 minutes after a cold start) avoids this.
- Once warm, the service stays warm under normal traffic and `chroma_docs` stays at `177`.

## Architecture note specific to this deployment

The deployed instance runs with `MCP_TRANSPORT=inmemory` (set in `render.yaml`), meaning the MCP tool server runs inside the same process as the FastAPI app instead of as a separate subprocess. This is deploy-specific: local development and the full test suite default to `MCP_TRANSPORT=stdio`, a real separate process talking genuine MCP-over-stdio, which is the architecture actually demonstrated end-to-end in this repo's tests (`tests/test_mcp_tools.py`, `tests/test_agent.py`). The in-memory mode uses the same MCP SDK protocol objects (`ClientSession`, real `list_tools`/`call_tool` messages) over an in-process transport instead of a subprocess boundary — it exists solely because a second full Python process's memory overhead doesn't fit Render's free 512MB limit alongside the embedding model. Full reasoning and the two real failed-deploy incidents that led here are documented in `CLAUDE.md`'s Day 8 entry.

## Environment variables set on Render

See `render.yaml` for the full list. `OPENROUTER_API_KEY` is set directly in the Render dashboard (Environment tab) and is never committed to the repo.

Note: `LLM_MODEL` points at a specific OpenRouter free-tier model slug. Free-tier model availability on OpenRouter changes without notice — if `/chat` responses start erroring with a model-not-found or rate-limit error, check `GET https://openrouter.ai/api/v1/models` for a current `*:free` slug and update the `LLM_MODEL` env var in the Render dashboard (no code change needed).

## Redeploying

Deploys are **not** triggered automatically by pushing to `main` (`autoDeploy: false` in `render.yaml`) — they're gated behind CI passing, via a Render "Deploy Hook" URL stored as the `RENDER_DEPLOY_HOOK_URL` GitHub Actions secret (see `.github/workflows/ci.yml`'s `deploy` job). This means a push only reaches production if the full test suite and lint pass first.

To redeploy manually: Render dashboard → the `hr-agent` service → **Manual Deploy** → **Deploy latest commit**, or `render deploys create <service-id> --wait` via the [Render CLI](https://render.com/docs/cli).
