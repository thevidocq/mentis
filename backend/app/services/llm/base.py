from dataclasses import dataclass


class LLMError(RuntimeError):
    """A provider failed. `retryable` means another provider may succeed (network, 5xx, timeout, 429)."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Turn:
    role: str  # user | assistant
    content: str


@dataclass
class LLMReply:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def status_error(provider: str, status: int, body: str) -> LLMError:
    # 400/401/403/404: our configuration is wrong; a fallback provider might still work, but say clearly why.
    hint = {401: "invalid API key", 403: "access denied", 404: "wrong URL or model", 429: "rate limited"}.get(status, "")
    msg = f"{provider} answered {status}{f' ({hint})' if hint else ''}: {body[:200]}"
    return LLMError(msg, retryable=True)
