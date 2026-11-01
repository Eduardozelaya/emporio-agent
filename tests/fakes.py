"""A scripted stand-in for the model, so the loop is testable without a key or a network.

The loop's behaviour is what we actually want to pin down — which tool ran, what happens on
a timeout, where it stops — and that is all deterministic. The model's prose is not, and is
checked separately by the live evaluation in E6.
"""

from __future__ import annotations

import itertools
from typing import Any

from emporio.llm import LLMError, LLMResponse, ToolCall, Usage

_ids = itertools.count(1)


def says(text: str, *, prompt_tokens: int = 1000, completion_tokens: int = 50) -> LLMResponse:
    """A plain text answer, ending the turn."""
    return LLMResponse(
        text=text,
        usage=Usage(prompt_tokens, completion_tokens),
        model="fake-model",
    )


def calls(name: str, arguments: dict[str, Any] | str = "{}", **more: Any) -> LLMResponse:
    """A turn where the model asks for one tool."""
    import json

    raw = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return LLMResponse(
        text=None,
        tool_calls=[ToolCall(id=f"call_{next(_ids)}", name=name, arguments=raw)],
        usage=Usage(more.get("prompt_tokens", 1000), more.get("completion_tokens", 20)),
        model="fake-model",
        finish_reason="tool_calls",
    )


class FakeLLM:
    """Replays a script. Anything that is an exception is raised instead of returned."""

    def __init__(self, *script: LLMResponse | Exception) -> None:
        self.script = list(script)
        self.calls: list[list[dict[str, Any]]] = []
        self.tools_seen: list[list[dict[str, Any]]] = []

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        # Keep a copy: the loop mutates its own list as it goes.
        self.calls.append([dict(message) for message in messages])
        self.tools_seen.append(tools or [])

        if not self.script:
            raise AssertionError("FakeLLM ran out of script: the loop called it once too often")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def system_prompt(self, call_index: int = 0) -> str:
        return self.calls[call_index][0]["content"]


class AlwaysFailingLLM:
    """Stands in for a provider that is down: `LLMClient` already retried and gave up."""

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, messages, tools=None) -> LLMResponse:  # noqa: ARG002
        self.call_count += 1
        raise LLMError("provider unreachable")
