"""Calling a configured provider, with failover to the tenant's fallback."""

import logging
import time

import httpx

from app.core import crypto
from app.models import LlmProvider
from app.services.llm import adapters
from app.services.llm.base import LLMError, LLMReply, Turn, status_error

_log = logging.getLogger("mentis.llm")

KINDS = {
    "anthropic": "Anthropic (Claude)",
    "openai_chat": "OpenAI Chat Completions (OpenAI, Ollama, vLLM)",
    "openai_responses": "OpenAI Responses API (gpt-oss, Daybreak Blue)",
}

# Starting points for the "Add provider" form. The admin can change any field.
PRESETS = [
    {"label": "Claude Haiku (Anthropic)", "kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-haiku-5-5", "options": {}},
    {"label": "OpenAI", "kind": "openai_chat", "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini", "options": {}},
    {"label": "Daybreak Blue (OpenAI, needs program approval)", "kind": "openai_responses", "base_url": "https://api.openai.com/v1", "model": "gpt-daybreak-blue-latest", "options": {}},
    {"label": "gpt-oss on vLLM (internal)", "kind": "openai_responses", "base_url": "http://vllm:8000/v1", "model": "openai/gpt-oss-120b", "options": {"reasoning_effort": "medium"}},
    {"label": "Ollama (local)", "kind": "openai_chat", "base_url": "http://ollama:11434/v1", "model": "llama3.1", "options": {}},
]

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests route every provider call through a mock transport."""
    global _transport
    _transport = transport


def provider_config(p: LlmProvider) -> dict:
    return {
        "name": p.name, "kind": p.kind, "base_url": p.base_url, "model": p.model,
        "api_key": crypto.decrypt(p.api_key_enc) if p.api_key_enc else None, "options": p.options or {},
    }


def call_provider(cfg: dict, system: str, turns: list[Turn], timeout: float = 120) -> LLMReply:
    url, headers, body = adapters.build(cfg["kind"], cfg["base_url"], cfg["model"], cfg["api_key"], cfg["options"], system, turns)
    try:
        with httpx.Client(timeout=timeout, transport=_transport) as client:
            r = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        raise LLMError(f"{cfg['name']} timed out") from None
    except httpx.HTTPError as e:
        raise LLMError(f"{cfg['name']} not reachable: {e.__class__.__name__}") from None
    if r.status_code != 200:
        raise status_error(cfg["name"], r.status_code, r.text)
    try:
        data = r.json()
    except ValueError:
        raise LLMError(f"{cfg['name']} returned non-JSON") from None
    reply = adapters.parse(cfg["kind"], data)
    if not reply.text.strip():
        raise LLMError(f"{cfg['name']} returned an empty answer")
    return reply


def ping(cfg: dict, timeout: float = 5) -> tuple[bool, str]:
    """Cheap reachability and key check for the status page: lists models, generates nothing."""
    base = cfg["base_url"].rstrip("/")
    if cfg["kind"] == "anthropic":
        url, headers = f"{base}/v1/models", {"anthropic-version": "2023-06-01"}
        if cfg["api_key"]:
            headers["x-api-key"] = cfg["api_key"]
    else:
        url, headers = f"{base}/models", {"Authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
    try:
        with httpx.Client(timeout=timeout, transport=_transport) as client:
            r = client.get(url, headers=headers)
    except httpx.HTTPError as e:
        return False, f"not reachable: {e.__class__.__name__}"
    if r.status_code == 200:
        return True, cfg["model"]
    return False, str(status_error(cfg["name"], r.status_code, r.text))


def call_with_failover(primary: dict | None, fallback: dict | None, system: str, turns: list[Turn]) -> tuple[LLMReply, dict, int]:
    """Try the primary, then the fallback. Returns (reply, provider used, latency ms)."""
    errors = []
    for cfg in (primary, fallback):
        if cfg is None:
            continue
        t0 = time.perf_counter()
        try:
            reply = call_provider(cfg, system, turns)
            return reply, cfg, round((time.perf_counter() - t0) * 1000)
        except LLMError as e:
            _log.warning("LLM %s failed: %s", cfg["name"], e)
            errors.append(str(e))
            if not e.retryable:
                break
    if not errors:
        raise LLMError("No LLM is configured. A super-admin must add one in AI providers.", retryable=False)
    raise LLMError("; ".join(errors))
