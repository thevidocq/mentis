"""A fake LLM speaking the Anthropic, OpenAI Chat and OpenAI Responses formats.

It answers with the first passage it receives, citing it, so tests can check grounding and citations.
"""

import json
import re

import httpx


class FakeLLM:
    def __init__(self):
        self.requests: list[dict] = []  # {"url", "headers", "body"}
        self.fail: dict[str, int] = {}  # host -> status code to return
        self.reply_override: str | None = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def last_user_text(self, body: dict) -> str:
        if "messages" in body:
            return body["messages"][-1]["content"]
        return body["input"][-1]["content"]

    def answer_for(self, body: dict) -> str:
        if self.reply_override is not None:
            return self.reply_override
        user = self.last_user_text(body)
        m = re.search(r'<passage n="1" customer="([^"]+)"[^>]*>\n(.*?)\n</passage>', user, re.S)
        if m is None:  # e.g. the provider "Test" button
            return "ready"
        system = body.get("system") or body.get("instructions") or body["messages"][0]["content"]
        followups = ["What is the SLA?", "Who is the backup contact?"] if "always an empty list" not in system else []
        title = "Escalation procedure" if '"title": always null' not in system else None
        return json.dumps({"answer": f"For **{m.group(1)}**: {m.group(2)[:200]} [1] [9]", "not_found": False,
                           "followups": followups, "title": title})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # model list, used by the status page
            if request.url.host in self.fail:
                return httpx.Response(self.fail[request.url.host], text='{"error": "boom"}')
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        if request.url.host in self.fail:
            return httpx.Response(self.fail[request.url.host], text='{"error": "boom"}')
        text = self.answer_for(body)
        path = request.url.path
        if path.endswith("/v1/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 100, "output_tokens": 20}})
        if path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        if path.endswith("/responses"):
            return httpx.Response(200, json={"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": text}]}],
                                             "usage": {"input_tokens": 100, "output_tokens": 20}})
        return httpx.Response(404, text="unknown path")
