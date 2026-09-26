"""The two LLM providers the router picks between (step 20): Gemini Flash and Grok, over HTTPS.

Both are asked for JSON that matches the agent's schema, and both are asked to show their
reasoning. Gemini returns thought summaries when includeThoughts is on. Grok's Responses API
returns reasoning summaries. The reasoning panel shows whatever comes back.

Settings come from the root .env. Never log a key.
  GEMINI_API_KEY          Google AI Studio key
  GEMINI_MODEL            default gemini-3.8-flash
  GEMINI_THINKING_LEVEL   low, medium, or high for Gemini 3.x (default low: fast)
  XAI_API_KEY             xAI key
  GROK_MODEL              default grok-4.3 (fast; grok-4.7 is slower)
  GROK_REASONING_EFFORT   none, low, medium, high (default none: lowest latency)
  GROK_API                responses (default, returns reasoning summaries) or chat
  LLM_TIMEOUT_S           per call, default 25
  GEMINI_BASE_URL, XAI_BASE_URL   for a proxy or a local mock
"""

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import BaseModel

# Importing this loads the repo root .env. This module is the one that reads the API keys, so it
# is the one that has to guarantee they are there: without it, a caller that imports only the
# agents package sees every provider as unconfigured and the router raises "no API key".
import app.config  # noqa: F401
from .schemas import ProviderName, Usage

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_GROK_MODEL = "grok-4.3"
DEFAULT_TIMEOUT_S = 25.0
# Thinking tokens count against Gemini's output limit, so leave room for them and the JSON.
MAX_OUTPUT_TOKENS = 8192
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    schema: dict
    schema_name: str


@dataclass(frozen=True)
class LLMResult:
    text: str  # the answer, which should be the JSON object
    thoughts: list[str]  # the provider's reasoning summary, when it returns one
    model: str  # the model version that answered
    usage: Usage
    latency_ms: int


class ProviderError(Exception):
    """A call that returned no usable answer. `retryable` means the same call may work again."""

    def __init__(self, provider: ProviderName, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status = status


class Provider(Protocol):
    name: ProviderName
    model: str

    @property
    def configured(self) -> bool: ...

    @property
    def label(self) -> str: ...

    async def generate(self, request: LLMRequest) -> LLMResult: ...


def model_label(model: str) -> str:
    """'gemini-3.8-flash' to 'Gemini 3.8 Flash', 'grok-4.3' to 'Grok 4.3'."""
    words = [w for w in model.replace("_", "-").split("-") if w]
    return " ".join(w if w[0].isdigit() else w.capitalize() for w in words)


def llm_schema(model: type[BaseModel]) -> dict:
    """The model's JSON schema in the subset both providers accept: $refs inlined, titles and
    defaults dropped, const as a one-value enum, and every object closed with all fields required.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def clean(node):
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = definitions[node["$ref"].rsplit("/", 1)[-1]]
            return clean({**target, **{k: v for k, v in node.items() if k != "$ref"}})
        out = {}
        for key, value in node.items():
            if key in ("title", "default"):
                continue
            if key == "const":
                out["enum"] = [value]
            elif key == "properties":
                out[key] = {name: clean(sub) for name, sub in value.items()}
            else:
                out[key] = clean(value)
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out

    return clean(schema)


def _error_text(response: httpx.Response) -> str:
    """A short, key-free description of an error response."""
    detail = ""
    try:
        body = response.json()
        error = body.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("status") or ""
        elif isinstance(error, str):
            detail = error
        detail = detail or body.get("message") or body.get("code") or ""
    except (json.JSONDecodeError, AttributeError):
        detail = response.text[:200]
    return f"HTTP {response.status_code}: {str(detail)[:240]}".rstrip(": ")


@dataclass
class _HttpProvider:
    """What both providers share: the key, the model, the timeout, and one POST."""

    name: ProviderName
    api_key: str
    model: str
    base_url: str
    timeout: float
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def label(self) -> str:
        return model_label(self.model)

    async def _post(self, path: str, headers: dict, body: dict) -> tuple[dict, int]:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(f"{self.base_url}{path}", headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"timed out after {self.timeout:.0f} s", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"could not reach the API ({type(exc).__name__})", retryable=True) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise ProviderError(self.name, _error_text(response), retryable=response.status_code in RETRYABLE_STATUS,
                                status=response.status_code)
        try:
            return response.json(), latency_ms
        except json.JSONDecodeError as exc:
            raise ProviderError(self.name, "the response was not JSON", retryable=True) from exc


class GeminiProvider(_HttpProvider):
    """Gemini Flash through generateContent, with thought summaries."""

    def __init__(self, env: Mapping[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None):
        env = os.environ if env is None else env
        super().__init__(
            name="gemini",
            api_key=env.get("GEMINI_API_KEY", "").strip(),
            model=env.get("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
            base_url=(env.get("GEMINI_BASE_URL", "").strip() or "https://generativelanguage.googleapis.com").rstrip("/"),
            timeout=float(env.get("LLM_TIMEOUT_S", "").strip() or DEFAULT_TIMEOUT_S),
            transport=transport,
        )
        self.thinking_level = env.get("GEMINI_THINKING_LEVEL", "").strip() or "low"

    def body(self, request: LLMRequest) -> dict:
        thinking: dict = {"includeThoughts": True}
        if self.model.startswith("gemini-2."):
            thinking["thinkingBudget"] = 1024  # 2.x models take a token budget, 3.x a level. Never both.
        else:
            thinking["thinkingLevel"] = self.thinking_level
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": request.schema,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "thinkingConfig": thinking,
            },
        }

    async def generate(self, request: LLMRequest) -> LLMResult:
        data, latency_ms = await self._post(
            f"/v1beta/models/{self.model}:generateContent",
            {"x-goog-api-key": self.api_key},
            self.body(request),
        )
        return parse_gemini(data, self.model, latency_ms)


def parse_gemini(data: dict, model: str, latency_ms: int) -> LLMResult:
    blocked = (data.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise ProviderError("gemini", f"the prompt was blocked ({blocked})", retryable=False)
    candidates = data.get("candidates") or []
    if not candidates:
        raise ProviderError("gemini", "the response had no candidates", retryable=True)
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    thoughts = [p["text"].strip() for p in parts if p.get("thought") and (p.get("text") or "").strip()]
    text = "".join(p.get("text") or "" for p in parts if not p.get("thought"))
    finish = candidate.get("finishReason")
    if finish == "MAX_TOKENS":
        raise ProviderError("gemini", "the answer was cut off at the token limit", retryable=False)
    if not text.strip():
        raise ProviderError("gemini", f"the answer was empty (finishReason {finish})",
                            retryable=finish not in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"))
    usage = data.get("usageMetadata") or {}
    return LLMResult(
        text=text,
        thoughts=thoughts,
        model=data.get("modelVersion") or model,
        usage=Usage(
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            reasoning_tokens=usage.get("thoughtsTokenCount"),
        ),
        latency_ms=latency_ms,
    )


class GrokProvider(_HttpProvider):
    """Grok through the Responses API (reasoning summaries), or Chat Completions with GROK_API=chat."""

    def __init__(self, env: Mapping[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None):
        env = os.environ if env is None else env
        super().__init__(
            name="grok",
            api_key=env.get("XAI_API_KEY", "").strip(),
            model=env.get("GROK_MODEL", "").strip() or DEFAULT_GROK_MODEL,
            base_url=(env.get("XAI_BASE_URL", "").strip() or "https://api.x.ai").rstrip("/"),
            timeout=float(env.get("LLM_TIMEOUT_S", "").strip() or DEFAULT_TIMEOUT_S),
            transport=transport,
        )
        self.effort = env.get("GROK_REASONING_EFFORT", "").strip() or "none"
        self.api = (env.get("GROK_API", "").strip() or "responses").lower()

    def body(self, request: LLMRequest) -> dict:
        messages = [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}]
        if self.api == "chat":
            return {
                "model": self.model,
                "messages": messages,
                "reasoning_effort": self.effort,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": request.schema_name, "schema": request.schema, "strict": True}},
            }
        return {
            "model": self.model,
            "input": messages,
            "reasoning": {"effort": self.effort},
            "text": {"format": {"type": "json_schema", "name": request.schema_name, "schema": request.schema,
                                "strict": True}},
            "store": False,
        }

    async def generate(self, request: LLMRequest) -> LLMResult:
        path = "/v1/chat/completions" if self.api == "chat" else "/v1/responses"
        data, latency_ms = await self._post(path, {"Authorization": f"Bearer {self.api_key}"}, self.body(request))
        if self.api == "chat":
            return parse_grok_chat(data, self.model, latency_ms)
        return parse_grok_responses(data, self.model, latency_ms)


def _grok_usage(usage: dict) -> Usage:
    details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    return Usage(
        input_tokens=usage.get("input_tokens", usage.get("prompt_tokens")),
        output_tokens=usage.get("output_tokens", usage.get("completion_tokens")),
        reasoning_tokens=details.get("reasoning_tokens"),
    )


def parse_grok_responses(data: dict, model: str, latency_ms: int) -> LLMResult:
    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason", "unknown")
        raise ProviderError("grok", f"the answer was incomplete ({reason})", retryable=False)
    thoughts, texts = [], []
    for item in data.get("output") or []:
        if item.get("type") == "reasoning":
            for part in item.get("summary") or []:
                if (part.get("text") or "").strip():
                    thoughts.append(part["text"].strip())
        elif item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") in ("output_text", "text") and part.get("text"):
                    texts.append(part["text"])
    text = "".join(texts) or data.get("output_text") or ""
    if not text.strip():
        raise ProviderError("grok", "the answer was empty", retryable=True)
    return LLMResult(text=text, thoughts=thoughts, model=data.get("model") or model,
                     usage=_grok_usage(data.get("usage") or {}), latency_ms=latency_ms)


def parse_grok_chat(data: dict, model: str, latency_ms: int) -> LLMResult:
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("grok", "the response had no choices", retryable=True)
    message = choices[0].get("message") or {}
    if choices[0].get("finish_reason") == "length":
        raise ProviderError("grok", "the answer was cut off at the token limit", retryable=False)
    text = message.get("content") or ""
    if not text.strip():
        raise ProviderError("grok", "the answer was empty", retryable=True)
    reasoning = (message.get("reasoning_content") or "").strip()
    return LLMResult(text=text, thoughts=[reasoning] if reasoning else [], model=data.get("model") or model,
                     usage=_grok_usage(data.get("usage") or {}), latency_ms=latency_ms)


def make_providers(env: Mapping[str, str] | None = None,
                   transport: httpx.AsyncBaseTransport | None = None) -> dict[ProviderName, Provider]:
    """Both providers, configured or not. The router skips any without a key."""
    return {"gemini": GeminiProvider(env, transport), "grok": GrokProvider(env, transport)}
