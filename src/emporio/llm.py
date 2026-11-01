"""Thin wrapper over an OpenAI-compatible chat API.

Deliberately small: the agent loop owns the orchestration, this file only turns one request
into one answer, with a timeout, one retry and the token usage captured.

Any OpenAI-compatible endpoint works through `LLM_BASE_URL` (DeepSeek, Groq, Ollama, …), so
swapping provider is configuration, not code (DECISIONS D3).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from emporio.config import Settings, get_settings


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
        for attempt in range(self.RETRIES + 1):
            try:
                return self._complete_once(messages, tools)
            except Exception as exc:  # noqa: BLE001 - every provider error is handled alike
                last_error = exc
                if attempt < self.RETRIES:
                    time.sleep(0.5)
        raise LLMError(
            f"{self.settings.llm_model} failed after {self.RETRIES + 1} attempts: {last_error}"
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
