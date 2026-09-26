"""Gemini and Grok request shapes and response parsing, against a mock transport. No network."""

import asyncio
import json

import httpx
import pytest

from app.agents.providers import (
    GeminiProvider,
    GrokProvider,
    LLMRequest,
    ProviderError,
    llm_schema,
    model_label,
)
from app.agents.schemas import TrailReport

ANSWER = {"severity": "high", "confidence": 0.8, "note": "Miles 4.6 to 4.9.", "reasoning": ["a", "b"]}
REQUEST = LLMRequest(system="You are the Trail Analyst.", user="Facts: {}", schema=llm_schema(TrailReport),
                     schema_name="trail_report")


def run(provider, request=REQUEST):
    return asyncio.run(provider.generate(request))


def transport(status, body, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def gemini(status, body, seen, **env):
    return GeminiProvider({"GEMINI_API_KEY": "test-key", **env}, transport(status, body, seen))


def grok(status, body, seen, **env):
    return GrokProvider({"XAI_API_KEY": "test-key", **env}, transport(status, body, seen))


def test_model_labels():
    assert model_label("gemini-3.8-flash") == "Gemini 3.8 Flash"
    assert model_label("grok-4.3") == "Grok 4.3"


def test_gemini_request_and_thoughts():
    seen = {}
    body = {
        "candidates": [{"content": {"parts": [
            {"text": "The flagged miles cross a drainage.", "thought": True},
            {"text": json.dumps(ANSWER), "thoughtSignature": "abc"},
        ]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 60, "thoughtsTokenCount": 210},
        "modelVersion": "gemini-3.8-flash-001",
    }
    result = run(gemini(200, body, seen))
    assert seen["url"].endswith("/v1beta/models/gemini-3.8-flash:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "test-key"
    config = seen["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["required"] == ["severity", "confidence", "note", "reasoning"]
    assert config["thinkingConfig"] == {"includeThoughts": True, "thinkingLevel": "low"}
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == REQUEST.system
    assert json.loads(result.text) == ANSWER
    assert result.thoughts == ["The flagged miles cross a drainage."]
    assert result.model == "gemini-3.8-flash-001"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.reasoning_tokens) == (900, 60, 210)


def test_gemini_2x_uses_a_thinking_budget():
    seen = {}
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER)}]}, "finishReason": "STOP"}]}
    run(gemini(200, body, seen, GEMINI_MODEL="gemini-2.5-flash"))
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"includeThoughts": True, "thinkingBudget": 1024}


@pytest.mark.parametrize(("status", "body", "retryable", "message"), [
    (429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, True, "Quota"),
    (503, {"error": {"code": 503, "message": "Overloaded", "status": "UNAVAILABLE"}}, True, "Overloaded"),
    (400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}}, False, "API key"),
    (200, {"promptFeedback": {"blockReason": "SAFETY"}}, False, "blocked"),
    (200, {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}, False, "token limit"),
    (200, {"candidates": []}, True, "no candidates"),
])
def test_gemini_errors(status, body, retryable, message):
    with pytest.raises(ProviderError, match=message) as caught:
        run(gemini(status, body, {}))
    assert caught.value.retryable is retryable
    assert "test-key" not in str(caught.value)


def test_grok_responses_request_and_reasoning_summary():
    seen = {}
    body = {
        "model": "grok-4.7",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Weighing the bypass."}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(ANSWER)}]},
        ],
        "usage": {"input_tokens": 800, "output_tokens": 70, "output_tokens_details": {"reasoning_tokens": 300}},
    }
    result = run(grok(200, body, seen))
    assert seen["url"] == "https://api.x.ai/v1/responses"
    assert seen["headers"]["authorization"] == "Bearer test-key"
    fmt = seen["body"]["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "trail_report"
    assert seen["body"]["reasoning"] == {"effort": "none"}
    assert seen["body"]["store"] is False
    assert [m["role"] for m in seen["body"]["input"]] == ["system", "user"]
    assert json.loads(result.text) == ANSWER
    assert result.thoughts == ["Weighing the bypass."]
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.reasoning_tokens) == (800, 70, 300)


def test_grok_chat_completions():
    seen = {}
    body = {
        "model": "grok-4.7",
        "choices": [{"message": {"content": json.dumps(ANSWER), "reasoning_content": "Checked the miles."},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 500, "completion_tokens": 40, "completion_tokens_details": {"reasoning_tokens": 90}},
    }
    result = run(grok(200, body, seen, GROK_API="chat"))
    assert seen["url"] == "https://api.x.ai/v1/chat/completions"
    assert seen["body"]["response_format"]["json_schema"]["strict"] is True
    assert seen["body"]["reasoning_effort"] == "none"
    assert result.thoughts == ["Checked the miles."]
    assert result.usage.reasoning_tokens == 90


@pytest.mark.parametrize(("status", "body", "retryable"), [
    (400, {"code": "Client specified an invalid argument", "error": "Incorrect API key provided: xa***en."}, False),
    (404, {"code": "Some requested entity was not found", "error": "The model grok-9 does not exist."}, False),
    (429, {"code": "Some resource has been exhausted", "error": "Rate limit."}, True),
    (200, {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, False),
])
def test_grok_errors(status, body, retryable):
    with pytest.raises(ProviderError) as caught:
        run(grok(status, body, {}))
    assert caught.value.retryable is retryable


def test_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    provider = GeminiProvider({"GEMINI_API_KEY": "k", "LLM_TIMEOUT_S": "5"}, httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="timed out after 5 s") as caught:
        run(provider)
    assert caught.value.retryable


def test_unconfigured_without_a_key():
    assert not GeminiProvider({}).configured
    assert not GrokProvider({}).configured
    assert GrokProvider({"XAI_API_KEY": " k "}).configured
