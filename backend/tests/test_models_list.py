"""AI provider form: models are listed from the provider, not hard-coded."""

from tests.test_chat import _analyst, _provider, fake_llm  # noqa: F401 - fixture


def test_presets_have_no_model_names(super_admin):
    presets = super_admin.get("/api/llm/kinds").json()["presets"]
    assert presets and all(p["model"] == "" for p in presets)
    assert not any("haiku" in p["label"].lower() for p in presets)


def test_list_models_anthropic_and_openai(super_admin, fake_llm):  # noqa: F811
    r = super_admin.post("/api/llm/models", json={"kind": "anthropic", "base_url": "https://api.anthropic.com", "api_key": "sk-typed"})
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()] == ["claude-new", "claude-old"]  # newest first
    assert r.json()[0]["label"] == "Claude New (claude-new)"
    assert fake_llm.model_requests[-1]["headers"]["x-api-key"] == "sk-typed"
    r = super_admin.post("/api/llm/models", json={"kind": "openai_chat", "base_url": "http://ollama:11434/v1"})
    assert [m["id"] for m in r.json()] == ["a-model", "b-model", "m"]
    assert "authorization" not in fake_llm.model_requests[-1]["headers"]


def test_list_models_uses_the_stored_key_and_reports_errors(super_admin, fake_llm):  # noqa: F811
    p = _provider(super_admin)  # stored key sk-test
    r = super_admin.post("/api/llm/models", json={"kind": "anthropic", "base_url": "https://api.anthropic.com", "provider_id": p["id"]})
    assert r.status_code == 200 and fake_llm.model_requests[-1]["headers"]["x-api-key"] == "sk-test"
    fake_llm.fail["api.anthropic.com"] = 401
    r = super_admin.post("/api/llm/models", json={"kind": "anthropic", "base_url": "https://api.anthropic.com", "provider_id": p["id"]})
    assert r.status_code == 502 and "invalid API key" in r.json()["detail"] and "sk-test" not in r.text


def test_list_models_is_super_admin_only(super_admin, fake_llm):  # noqa: F811
    an = _analyst(super_admin)
    assert an.post("/api/llm/models", json={"kind": "anthropic", "base_url": "https://api.anthropic.com"}).status_code == 403
