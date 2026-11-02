"""Thin wrapper over an OpenAI-compatible chat API.

Deliberately small: the agent loop owns the orchestration, this file only turns one request
into one answer, with a timeout, one retry and the token usage captured.

Any OpenAI-compatible endpoint works through `LLM_BASE_URL` (DeepSeek, Groq, Ollama, …), so
swapping provider is configuration, not code (DECISIONS D3).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from emporio.config import Settings, get_settings

#: "42.1875s", "577ms", "1m30s" — the shapes providers use for a retry delay.
_DURATION = re.compile(r"(?:(\d+)m)?(\d+(?:\.\d+)?)(ms|s)?")


def parse_duration(raw: str | None) -> float | None:
    """Seconds from a provider's retry hint, or None when it is not one."""
    if not raw:
        return None
    match = _DURATION.fullmatch(raw.strip())
    if not match:
        return None
    minutes, value, unit = match.groups()
    seconds = float(value) / 1000 if unit == "ms" else float(value)
    return seconds + (int(minutes) * 60 if minutes else 0)


def retry_after(exc: Exception) -> float | None:
    """How long the provider asked us to wait, from its headers or its message.

    Honouring this matters: a rate-limited provider that says "try again in 42s" will keep
    refusing a request retried half a second later, and the customer gets a fallback for a
    problem that would have cleared itself.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            delay = parse_duration(headers.get(header))
            if delay:
                return delay
    found = re.search(r"try again in ([\d.]+(?:ms|s))", str(exc))
    return parse_duration(found.group(1)) if found else None


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked for. `arguments` is the raw JSON string it produced."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    finish_reason: str = "stop"


class LLMError(RuntimeError):
    """The provider failed after the retry. The caller falls back to a safe reply."""


class LLMClient:
    """One request, one answer. Retries once, then gives up and lets the agent fall back."""

    #: A provider can send headers and then stall, so the timeout has to cover the whole
    #: response, not just the connection. Lesson from a production bot.
    RETRIES = 1

    #: Rate limits clear on their own, so they get their own, more patient budget. Raised
    #: from 3 after a live run gave up with the provider asking for only 6.7 s more — on a
    #: shared free-tier quota, a few consecutive refusals are normal.
    RATE_LIMIT_RETRIES = 5

    #: Never sit on a customer's message for longer than this waiting for a quota to reset.
    MAX_RATE_LIMIT_WAIT_S = 75.0

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.require_api_key(),
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout_s,
                max_retries=0,  # retrying is our job, so the timeout budget stays predictable
            )
        return self._client

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        last_error: Exception | None = None
        attempts = 0
        plain_retries_left = self.RETRIES
        rate_limit_retries_left = self.RATE_LIMIT_RETRIES

        while True:
            attempts += 1
            try:
                return self._complete_once(messages, tools)
            except Exception as exc:  # noqa: BLE001 - every provider error is handled alike
                last_error = exc
                wait = retry_after(exc)
                if wait is not None and wait <= self.MAX_RATE_LIMIT_WAIT_S:
                    if rate_limit_retries_left <= 0:
                        break
                    rate_limit_retries_left -= 1
                    time.sleep(wait + 0.5)  # half a second of slack for clock skew
                    continue
                if plain_retries_left <= 0:
                    break
                plain_retries_left -= 1
                time.sleep(0.5)

        raise LLMError(
            f"{self.settings.llm_model} failed after {attempts} attempts: {last_error}"
        ) from last_error

    def _complete_once(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "timeout": self.settings.llm_timeout_s,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        completion = self.client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        message = choice.message

        tool_calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments or "{}")
            for call in (message.tool_calls or [])
        ]
        usage = Usage(
            prompt_tokens=getattr(completion.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(completion.usage, "completion_tokens", 0) or 0,
        )
        return LLMResponse(
            text=message.content,
            tool_calls=tool_calls,
            usage=usage,
            model=getattr(completion, "model", self.settings.llm_model),
            finish_reason=choice.finish_reason or "stop",
        )


def assistant_message(response: LLMResponse) -> dict[str, Any]:
    """The assistant turn in OpenAI wire format, tool calls included.

    The message that requested the tools must be kept next to their results: the API rejects
    a `tool` message whose call is missing, which is also why memory windowing may never
    split the group (E5).
    """
    message: dict[str, Any] = {"role": "assistant", "content": response.text}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in response.tool_calls
        ]
    return message


def tool_result_message(call: ToolCall, result_json: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": result_json,
    }
