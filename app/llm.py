"""OpenRouter (OpenAI-compatible) client factories shared by the retriever, agent and MCP tools."""

from openai import AsyncOpenAI, OpenAI

from app import config


def _kwargs() -> dict:
    return dict(
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        timeout=config.LLM_TIMEOUT_S,
        max_retries=1,
    )


def get_client() -> OpenAI:
    return OpenAI(**_kwargs())


def get_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(**_kwargs())
