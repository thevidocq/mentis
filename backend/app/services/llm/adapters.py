"""Request/response mapping for each API family. Pure functions: easy to test against the exact formats.

- anthropic:        POST {base}/v1/messages           (x-api-key, anthropic-version)
- openai_chat:      POST {base}/chat/completions       (OpenAI, Ollama /v1, vLLM, compatible)
- openai_responses: POST {base}/responses              (OpenAI Responses API: OpenAI, gpt-oss on vLLM)
"""

from app.services.llm.base import LLMError, LLMReply, Turn

ANTHROPIC_VERSION = "2023-06-01"


def build(kind: str, base_url: str, model: str, api_key: str | None, options: dict, system: str, turns: list[Turn]) -> tuple[str, dict, dict]:
    """Returns (url, headers, json body)."""
    base = base_url.rstrip("/")
    max_tokens = int(options.get("max_tokens", 1500))
    msgs = [{"role": t.role, "content": t.content} for t in turns]

    if kind == "anthropic":
        headers = {"anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key
        body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": msgs}
        return f"{base}/v1/messages", headers, body

    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    if kind == "openai_chat":
        # api.openai.com wants max_completion_tokens for current models; compatible servers use max_tokens.
        limit_key = "max_completion_tokens" if "api.openai.com" in base else "max_tokens"
        body = {"model": model, "messages": [{"role": "system", "content": system}, *msgs], limit_key: max_tokens}
        return f"{base}/chat/completions", headers, body

    if kind == "openai_responses":
        body = {"model": model, "instructions": system, "input": msgs, "max_output_tokens": max_tokens}
        effort = options.get("reasoning_effort")
        if effort:
            body["reasoning"] = {"effort": effort}
        return f"{base}/responses", headers, body

    raise LLMError(f"Unknown provider type: {kind}", retryable=False)


def parse(kind: str, data: dict) -> LLMReply:
    try:
        if kind == "anthropic":
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            u = data.get("usage") or {}
            return LLMReply(text, u.get("input_tokens"), u.get("output_tokens"))

        if kind == "openai_chat":
            text = data["choices"][0]["message"]["content"] or ""
            u = data.get("usage") or {}
            return LLMReply(text, u.get("prompt_tokens"), u.get("completion_tokens"))

        if kind == "openai_responses":
            text = data.get("output_text") or ""
            if not text:
                parts = []
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        parts += [c.get("text", "") for c in item.get("content", []) if c.get("type") in ("output_text", "text")]
                text = "".join(parts)
            u = data.get("usage") or {}
            return LLMReply(text, u.get("input_tokens"), u.get("output_tokens"))
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected answer format: {e}") from None
    raise LLMError(f"Unknown provider type: {kind}", retryable=False)
