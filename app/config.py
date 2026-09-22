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

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(ROOT / "chroma_db"))
CORPUS_DIR = ROOT / "corpus"
MOCK_DATA_DIR = ROOT / "mock_data"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
LLM_TIMEOUT_S = 30.0
