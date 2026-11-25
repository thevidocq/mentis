"""LLM providers: one adapter per API family, a common call, and failover."""

from app.services.llm.base import LLMError, LLMReply, Turn
from app.services.llm.registry import (
    KINDS,
    PRESETS,
    call_provider,
    call_with_failover,
    ping,
    provider_config,
    set_transport,
)

__all__ = ["KINDS", "LLMError", "LLMReply", "PRESETS", "Turn", "call_provider", "call_with_failover", "ping", "provider_config", "set_transport"]
