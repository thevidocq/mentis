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
        self.model_requests: list[dict] = []
        self.reply_override: str | None = None
        # Answer check (level 2): its requests apart from the answers'; statements it rejects (by number)
        # or, for a sentence checker, claims containing one of `minicheck_no` get "No".
        self.check_requests: list[dict] = []
        self.unsupported: list[int] = []
        self.minicheck_no: list[str] = []

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

    def judge_unsupported(self, user: str) -> list[int]:
        """Statement numbers (S1, S2...) the fake checker rejects."""
        return self.unsupported

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # model list: status page and the provider form
            self.model_requests.append({"url": str(request.url), "headers": dict(request.headers)})
            if request.url.host in self.fail:
                return httpx.Response(self.fail[request.url.host], text='{"error": "boom"}')
            if "anthropic-version" in request.headers:  # Anthropic format
                return httpx.Response(200, json={"data": [
                    {"id": "claude-old", "display_name": "Claude Old", "created_at": "2025-01-01T00:00:00Z"},
                    {"id": "claude-new", "display_name": "Claude New", "created_at": "2026-06-01T00:00:00Z"}]})
            return httpx.Response(200, json={"data": [{"id": "m"}, {"id": "b-model", "created": 2}, {"id": "a-model", "created": 3}]})
        body = json.loads(request.content)
        record = {"url": str(request.url), "headers": dict(request.headers), "body": body}
        system = body.get("system") or body.get("instructions") or (body.get("messages") or [{}])[0].get("content") or ""
        user = self.last_user_text(body)
        if "MENTIS ANSWER CHECK" in system or user.startswith("Document: "):
            self.check_requests.append(record)
            if request.url.host in self.fail:
                return httpx.Response(self.fail[request.url.host], text='{"error": "boom"}')
            if user.startswith("Document: "):
                text = "No" if any(s in user.split("Claim: ", 1)[-1] for s in self.minicheck_no) else "Yes"
            else:
                text = json.dumps({"unsupported": [{"s": n, "reason": "not in the passage"} for n in self.judge_unsupported(user)]})
            return self._reply(request, text)
        self.requests.append(record)
        if request.url.host in self.fail:
            return httpx.Response(self.fail[request.url.host], text='{"error": "boom"}')
        return self._reply(request, self.answer_for(body))

    def _reply(self, request: httpx.Request, text: str) -> httpx.Response:
        path = request.url.path
        if path.endswith("/v1/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 100, "output_tokens": 20}})
        if path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        if path.endswith("/responses"):
            return httpx.Response(200, json={"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": text}]}],
                                             "usage": {"input_tokens": 100, "output_tokens": 20}})
        return httpx.Response(404, text="unknown path")
