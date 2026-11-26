"""Platform administration and AI providers: regressions found in the stability round."""

import json

import httpx
import pytest

from app.services import llm
from tests.test_chat import _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _tenant


def _import(c, data, apply=True):
    files = {"file": ("c.json", json.dumps(data).encode(), "application/json")}
    return c.post("/api/platform/config/import", params={"apply": "true"} if apply else {}, files=files)


@pytest.mark.parametrize("base_url", ["https://api..anthropic.com", "https://" + "a" * 70 + ".example.com"])
def test_a_provider_address_the_network_layer_rejects_is_an_llm_error(super_admin, base_url):
    """Host names IDNA cannot encode raise UnicodeError in httpx, not httpx.HTTPError: it broke the
    status page, the Test button, the model list and the chat (no failover) with an error 500."""

    def refuse(request):
        raise UnicodeError("label empty or too long")

    llm.set_transport(httpx.MockTransport(refuse))
    try:
        p = _provider(super_admin, name="Typo", base_url=base_url)
        r = super_admin.post(f"/api/llm/providers/{p['id']}/test")
        assert r.status_code == 200 and r.json()["ok"] is False, r.text
        r = super_admin.get("/api/platform/status")
        assert r.status_code == 200, r.text
        line = next(s for s in r.json()["services"] if s["name"].startswith("LLM: Typo"))
        assert line["state"] == "down"
        r = super_admin.post("/api/llm/models", json={"kind": "anthropic", "base_url": base_url, "api_key": "sk-typed"})
        assert r.status_code == 502, r.text
        with pytest.raises(llm.LLMError):
            llm.call_with_failover({"name": "Typo", "kind": "anthropic", "base_url": base_url, "model": "m", "api_key": None,
                                    "options": {}}, None, "s", [llm.Turn("user", "q")])
    finally:
        llm.set_transport(None)


def test_model_list_error_never_echoes_the_typed_key(super_admin):
    def echo(request):
        return httpx.Response(401, text=f'{{"error": "invalid key {request.headers.get("x-api-key")}"}}')

    llm.set_transport(httpx.MockTransport(echo))
    try:
        r = super_admin.post("/api/llm/models", json={"kind": "anthropic", "base_url": "https://api.anthropic.com",
                                                      "api_key": "sk-typed-secret"})
    finally:
        llm.set_transport(None)
    assert r.status_code == 502 and "sk-typed-secret" not in r.text


def test_import_moving_the_default_to_another_role_keeps_one_default_per_role(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin, name="Claude")                      # default answers
    _provider(super_admin, name="Checker", role="checker")     # default checker
    data = {"format": "mentis-config/1", "llm_providers": [
        {"name": "Claude", "kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-haiku-5-5",
         "options": {}, "is_default": False, "role": "checker"},
        {"name": "Checker", "kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-haiku-5-5",
         "options": {}, "is_default": True, "role": "checker"}]}
    assert _import(super_admin, data).status_code == 200
    rows = super_admin.get("/api/llm/providers").json()
    checker_defaults = [p["name"] for p in rows if p["role"] == "checker" and p["is_default"]]
    assert checker_defaults == ["Checker"], rows


def test_import_of_an_export_older_than_the_answer_check_keeps_the_choices(super_admin, fake_llm):  # noqa: F811
    """Files exported before 0.3.6 have no checker and no answer_check: the tenant keeps its own."""
    p = _provider(super_admin)
    chk = _provider(super_admin, name="Checker", role="checker")
    alfa = _tenant(super_admin, "Alfa")
    r = super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": p["id"], "checker_id": chk["id"], "answer_check": "hide"})
    assert r.status_code == 200, r.text
    data = super_admin.get("/api/platform/config/export").json()
    for t in data["tenants"]:
        t.pop("checker"), t.pop("answer_check")
    for prov in data["llm_providers"]:
        prov.pop("role")
    data["llm_providers"] = [x for x in data["llm_providers"] if x["name"] != "Checker"]
    assert _import(super_admin, data, apply=False).json()["changes"] == []
    assert _import(super_admin, data).status_code == 200
    after = super_admin.get(f"/api/tenants/{alfa['id']}/llm").json()
    assert after["checker_id"] == chk["id"] and after["answer_check"] == "hide" and after["provider_id"] == p["id"]


def test_tenant_name_of_spaces_is_refused(super_admin):
    assert super_admin.post("/api/tenants", json={"name": "   "}).status_code == 422
    alfa = _tenant(super_admin, "Alfa")
    assert super_admin.patch(f"/api/tenants/{alfa['id']}", json={"name": "  x  "}).status_code == 422
    assert [t["name"] for t in super_admin.get("/api/tenants").json() if not t["is_global"]] == ["Alfa"]
