"""Request/response mapping for each API family. Pure functions: easy to test against the exact formats.

- anthropic:        POST {base}/v1/messages           (x-api-key, anthropic-version)
- openai_chat:      POST {base}/chat/completions       (OpenAI, Ollama /v1, vLLM, compatible)
- openai_responses: POST {base}/responses              (OpenAI Responses API: OpenAI, gpt-oss on vLLM)
"""

import re

from app.services.llm.base import LLMError, LLMReply, Turn

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4000  # a long procedure in Italian with citations needs ~2,000; reasoning models count their thinking too


def build(kind: str, base_url: str, model: str, api_key: str | None, options: dict, system: str, turns: list[Turn]) -> tuple[str, dict, dict]:
    """Returns (url, headers, json body)."""
    base = base_url.rstrip("/")
    max_tokens = int(options.get("max_tokens") or DEFAULT_MAX_TOKENS)
    msgs = [{"role": t.role, "content": t.content} for t in turns]
    # Grounded answers and checks want determinism: temperature 0 unless the provider sets another
    # value; None = not sent (models that refuse the parameter, see call_provider).
    temperature = options.get("temperature", 0)

    if kind == "anthropic":
        headers = {"anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key
        body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": msgs}
        if temperature is not None:
            body["temperature"] = temperature
        return f"{base}/v1/messages", headers, body

    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    if kind == "openai_chat":
        # api.openai.com wants max_completion_tokens for current models; compatible servers use max_tokens.
        limit_key = "max_completion_tokens" if "api.openai.com" in base else "max_tokens"
        body = {"model": model, "messages": [{"role": "system", "content": system}, *msgs], limit_key: max_tokens}
        if temperature is not None:
            body["temperature"] = temperature
        return f"{base}/chat/completions", headers, body

    if kind == "openai_responses":
        body = {"model": model, "instructions": system, "input": msgs, "max_output_tokens": max_tokens}
        # Reasoning models on the Responses API refuse temperature: sent only when set explicitly.
        if "temperature" in options and options["temperature"] is not None:
            body["temperature"] = options["temperature"]
        effort = options.get("reasoning_effort")
        if effort:
            body["reasoning"] = {"effort": effort}
        return f"{base}/responses", headers, body

    raise LLMError(f"Unknown provider type: {kind}", retryable=False)


def _text(value) -> str:
    if not isinstance(value, str):
        raise TypeError(f"text is {type(value).__name__}, not a string")
    return value


def _stop(value) -> str | None:
    """The provider's stop reason, short and printable (it ends up in logs and error messages)."""
    if not isinstance(value, str) or not value:
        return None
    return value[:40] if re.fullmatch(r"[A-Za-z_]{1,40}", value) else "other"  # never echo arbitrary text


# Stop reasons that mean the answer was cut by the token limit, per API family.
CUT = {"max_tokens", "length", "max_output_tokens"}


def parse(kind: str, data: dict) -> LLMReply:
    try:
        if kind == "anthropic":
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            u = data.get("usage") or {}
            return LLMReply(_text(text), u.get("input_tokens"), u.get("output_tokens"), _stop(data.get("stop_reason")))

        if kind == "openai_chat":
            text = data["choices"][0]["message"]["content"] or ""
            if isinstance(text, list):  # some compatible servers send content as a list of parts
                text = "".join(c.get("text") or "" for c in text if isinstance(c, dict) and c.get("type") in ("text", "output_text"))
            u = data.get("usage") or {}
            return LLMReply(_text(text), u.get("prompt_tokens"), u.get("completion_tokens"), _stop(data["choices"][0].get("finish_reason")))

        if kind == "openai_responses":
            text = data.get("output_text") or ""
            if not text:
                parts = []
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        parts += [c.get("text", "") for c in item.get("content", []) if c.get("type") in ("output_text", "text")]
                text = "".join(parts)
            u = data.get("usage") or {}
            reason = (data.get("incomplete_details") or {}).get("reason") if isinstance(data.get("incomplete_details"), dict) else None
            return LLMReply(_text(text), u.get("input_tokens"), u.get("output_tokens"), _stop(reason or data.get("status")))
    except (KeyError, IndexError, TypeError, AttributeError) as e:  # not the expected JSON shape (e.g. a list, a proxy page)
        raise LLMError(f"Unexpected answer format: {e}") from None
    raise LLMError(f"Unknown provider type: {kind}", retryable=False)
