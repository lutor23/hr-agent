"""Shared settings, read from the environment (.env is loaded if present)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# chromadb 0.5.x's telemetry client crashes against the installed posthog version
# (capture() signature mismatch: a known chromadb bug, harmless but noisy). Setting
# anonymized_telemetry=False on Settings does not fully suppress it, so silence the
# logger that reports the caught exception instead.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

COLLECTION_NAME = "hr_policies"

# No EMBEDDING_MODEL setting: the embedding model (all-MiniLM-L6-v2, via chromadb's
# bundled ONNXMiniLM_L6_V2) is fixed by that class, not configurable — see
# app/ingest.py's get_embedding_function().
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(ROOT / "chroma_db"))
CORPUS_DIR = ROOT / "corpus"
MOCK_DATA_DIR = ROOT / "mock_data"

# "stdio" (default): the agent spawns mcp/server.py as a real separate OS process,
# talking to it over the actual MCP wire protocol — this is what all the tests use
# and what's normally meant by "the MCP server". "inmemory": the same tools run in
# THIS process instead, connected through the same ClientSession/protocol machinery
# but without a second process's memory overhead (~85-120MB) — used only by the
# deployed Render instance, whose 512Mi budget is real; see app/agent.py's
# _load_mcp_server_module() and CLAUDE.md's Day 8 entry for why this exists.
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Default matches .env.example / render.yaml. OpenRouter's free-tier slugs churn (see
# CLAUDE.md Day 3/Day 8); if this starts 404ing, check GET /api/v1/models for a live one.
LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
LLM_TIMEOUT_S = 30.0
