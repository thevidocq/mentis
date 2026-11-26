"""Native function calling (tool use) for the three API families, for integration lookups.

A `ToolConversation` keeps the provider's own message format between steps:
- anthropic:        tools [{name, description, input_schema}]; reply blocks "tool_use";
                    results as a user turn of "tool_result" blocks
- openai_chat:      tools [{type: function, function: {...}}]; reply message.tool_calls;
                    results as role "tool" messages
- openai_responses: tools [{type: function, name, ...}]; reply items "function_call";
                    the output items go back in the input, followed by "function_call_output" items

Only used to gather data: the answer itself is still written by the normal answer call.
"""

import json
from dataclasses import dataclass, field

import httpx

from app.services.llm import adapters
from app.services.llm import registry as llm_registry
from app.services.llm.base import LLMError, status_error


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict | None  # None: the model sent arguments that are not a JSON object


@dataclass
class ToolTurn:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class ToolConversation:
    def __init__(self, cfg: dict, system: str, user_text: str, tools: list[dict], timeout: float = 60):
        """tools: [{"name", "description", "parameters" (JSON Schema object)}]."""
        self.cfg, self.system, self.tools, self.timeout = cfg, system, tools, timeout
        self.kind = cfg["kind"]
        if self.kind not in ("anthropic", "openai_chat", "openai_responses"):
            raise LLMError(f"Unknown provider type: {self.kind}", retryable=False)
        self.messages: list = [{"role": "user", "content": user_text}]
        self._pending: list = []  # provider items of the last reply, to send back with the results

    # --- Requests --------------------------------------------------------------------------

    def _request(self) -> tuple[str, dict, dict]:
        url, headers, body = adapters.build(self.kind, self.cfg["base_url"], self.cfg["model"], self.cfg["api_key"],
                                            self.cfg["options"], self.system, [])
        if self.kind == "anthropic":
            body["messages"] = self.messages
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in self.tools]
        elif self.kind == "openai_chat":
            body["messages"] = [{"role": "system", "content": self.system}, *self.messages]
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["parameters"]}} for t in self.tools]
        else:
            body["input"] = self.messages
            body["tools"] = [{"type": "function", "name": t["name"], "description": t["description"],
                              "parameters": t["parameters"]} for t in self.tools]
        return url, headers, body

    def step(self) -> ToolTurn:
        url, headers, body = self._request()
        name = self.cfg["name"]
        try:
            with httpx.Client(timeout=self.timeout, transport=llm_registry._transport) as client:
                r = client.post(url, json=body, headers=headers)
                if r.status_code == 400 and "temperature" in body and "temperature" in r.text.lower():
                    body.pop("temperature")
                    r = client.post(url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise LLMError(f"{name} timed out") from None
        except httpx.HTTPError as e:
            raise LLMError(f"{name} not reachable: {e.__class__.__name__}") from None
        except (httpx.InvalidURL, ValueError):
            raise LLMError(f"{name}: invalid address") from None
        if r.status_code != 200:
            raise status_error(name, r.status_code, r.text, self.cfg.get("api_key"))
        try:
            data = r.json()
            return self._parse(data)
        except LLMError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError(f"{name}: unexpected tool answer format ({e.__class__.__name__})") from None

    def _parse(self, data: dict) -> ToolTurn:
        u = data.get("usage") or {}
        if self.kind == "anthropic":
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            calls = [ToolCall(str(b["id"]), str(b["name"]), b.get("input") if isinstance(b.get("input"), dict) else None)
                     for b in blocks if b.get("type") == "tool_use"]
            self._pending = [{"role": "assistant", "content": blocks}]
            return ToolTurn(text, calls, u.get("input_tokens") or 0, u.get("output_tokens") or 0)
        if self.kind == "openai_chat":
            msg = data["choices"][0]["message"]
            calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                calls.append(ToolCall(str(tc.get("id") or fn.get("name")), str(fn.get("name")), _args(fn.get("arguments"))))
            self._pending = [{"role": "assistant", "content": msg.get("content") or "", **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {})}]
            return ToolTurn(msg.get("content") or "", calls, u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0)
        items = data.get("output") or []
        calls = [ToolCall(str(i.get("call_id") or i.get("id")), str(i.get("name")), _args(i.get("arguments")))
                 for i in items if isinstance(i, dict) and i.get("type") == "function_call"]
        text = data.get("output_text") or "".join(c.get("text", "") for i in items if isinstance(i, dict) and i.get("type") == "message"
                                                  for c in i.get("content") or [] if c.get("type") in ("output_text", "text"))
        self._pending = [i for i in items if isinstance(i, dict)]
        return ToolTurn(text, calls, u.get("input_tokens") or 0, u.get("output_tokens") or 0)

    def add_results(self, results: list[tuple[str, str]]) -> None:
        """(call id, result text) for every call of the last step, in order."""
        self.messages += self._pending
        if self.kind == "anthropic":
            self.messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": text}
                                                              for cid, text in results]})
        elif self.kind == "openai_chat":
            self.messages += [{"role": "tool", "tool_call_id": cid, "content": text} for cid, text in results]
        else:
            self.messages += [{"type": "function_call_output", "call_id": cid, "output": text} for cid, text in results]
        self._pending = []


def _args(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
