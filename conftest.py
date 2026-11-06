"""Test processes never make a real paid API request by accident."""
import pytest


@pytest.fixture(autouse=True)
def no_live_paid_api(monkeypatch, tmp_path):
    from cloud import openai_client, model_catalog
    monkeypatch.setattr(model_catalog, "DEFAULT_MODEL", "openai-mini")
    monkeypatch.setattr(model_catalog, "SETTINGS", tmp_path/"model-settings.json")
    monkeypatch.setattr(model_catalog, "CREDENTIALS", tmp_path/"credentials.json")
    from cloud import free_pool
    monkeypatch.setattr(free_pool, "STATE", tmp_path/"free-state.json")
    monkeypatch.setattr(free_pool, "QUOTA", tmp_path/"free-quota.json")
    from models.api_usage import ApiUsage
    monkeypatch.setattr(openai_client, "api_usage", ApiUsage(tmp_path/"usage.jsonl", tmp_path/"settings.json", tmp_path/"official.json"))
    from functions.work_memory import work_memory
    monkeypatch.setattr(work_memory,'enqueue',lambda *args,**kwargs:{'state':'disabled','extra_cloud_request':False})
    def blocked(*args,**kwargs):
        raise AssertionError('Live OpenAI calls are disabled in tests; provide an explicit fake.')
    monkeypatch.setattr(openai_client,'OpenAI',blocked)
    monkeypatch.setattr(openai_client,'AsyncOpenAI',blocked)
    provider_client = openai_client._get_provider_client
    provider_client.cache_clear()
    cached_client = openai_client._get_client
    cached_client.cache_clear()
    yield
    provider_client.cache_clear()
    cached_client.cache_clear()
