"""LLM client factories read their settings from app.config."""

from app import config, llm


def test_clients_point_at_the_configured_endpoint_with_a_timeout(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", "https://example.test/v1")
    for client in (llm.get_client(), llm.get_async_client()):
        assert str(client.base_url).rstrip("/") == "https://example.test/v1"
        assert client.api_key == "sk-test"
        assert client.timeout == config.LLM_TIMEOUT_S
        assert client.max_retries == 1
