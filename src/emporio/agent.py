"""The tool-calling loop.

One turn is: build the prompt, ask the model, run whatever tools it asked for, feed the
results back, repeat until it answers in words. Three things can go wrong and each has a
defined ending, because a customer-facing bot that hangs or crashes is worse than one that
says "call the shop":

  * the provider fails or times out  -> one retry inside `llm.py`, then a safe fixed reply
  * the model keeps calling tools    -> stop at MAX_TOOL_STEPS and hand off
  * a tool blows up                  -> the dispatcher returns an error dict, the model reads it

No framework (DECISIONS D1): the whole loop is the function below, and you can read it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from emporio import prompts, tools
from emporio.config import PROJECT_ROOT, Settings, get_settings, now
from emporio.llm import LLMClient, LLMError, Usage, assistant_message, tool_result_message


@dataclass
class ToolCallRecord:
    """What the agent did, for `/debug`, the evaluation and the turn log."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]

    @property
    def failed(self) -> bool:
        return "error" in self.result


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    #: New messages produced this turn, in wire format, for memory to persist (E5).
    messages: list[dict[str, Any]] = field(default_factory=list)
    fallback: bool = False
    max_steps_reached: bool = False
    latency_s: float = 0.0
    model: str = ""

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]


def run_turn(
    session_id: str,
    user_text: str,
    settings: Settings | None = None,
    history: list[dict[str, Any]] | None = None,
    llm: LLMClient | None = None,
) -> Reply:
    """Answer one customer message.

    `history` is the window of earlier messages in wire format; memory (E5) supplies it and
    persists `reply.messages` afterwards.
    """
    settings = settings or get_settings()
    llm = llm or LLMClient(settings)
    moment = now()
    started = time.monotonic()

    system = {"role": "system", "content": prompts.build_system_prompt(settings, moment)}
    user = {"role": "user", "content": user_text}
    conversation: list[dict[str, Any]] = [system, *(history or []), user]

    turn_messages: list[dict[str, Any]] = [user]
    records: list[ToolCallRecord] = []
    usage = Usage()
    model = settings.llm_model
    schemas = tools.tool_schemas()

    for _ in range(settings.max_tool_steps):
        try:
            response = llm.complete(conversation, schemas)
        except LLMError:
            return _finish(
                Reply(
                    text=prompts.fallback_reply(moment),
                    tool_calls=records,
                    usage=usage,
                    messages=turn_messages,
                    fallback=True,
                    model=model,
                ),
                settings,
                session_id,
                started,
            )

        usage = Usage(
            usage.prompt_tokens + response.usage.prompt_tokens,
            usage.completion_tokens + response.usage.completion_tokens,
        )
        model = response.model or model

        message = assistant_message(response)
        conversation.append(message)
        turn_messages.append(message)

        if not response.tool_calls:
            return _finish(
                Reply(
                    text=(response.text or "").strip() or prompts.fallback_reply(moment),
                    tool_calls=records,
                    usage=usage,
                    messages=turn_messages,
                    model=model,
                ),
                settings,
                session_id,
                started,
            )

        for call in response.tool_calls:
            result = tools.dispatch(
                call.name, call.arguments, settings=settings, session_id=session_id
            )
            records.append(
                ToolCallRecord(
                    name=call.name,
                    arguments=_safe_json(call.arguments),
                    result=result,
                )
            )
            result_message = tool_result_message(
                call, json.dumps(result, ensure_ascii=False, default=str)
            )
            conversation.append(result_message)
            turn_messages.append(result_message)

    # The model never stopped asking for tools. Better to hand off than to keep burning
    # tokens in a loop the customer is waiting on.
    return _finish(
        Reply(
            text=prompts.fallback_reply(moment),
            tool_calls=records,
            usage=usage,
            messages=turn_messages,
            fallback=True,
            max_steps_reached=True,
            model=model,
        ),
        settings,
        session_id,
        started,
    )


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}


def _finish(reply: Reply, settings: Settings, session_id: str, started: float) -> Reply:
    reply.latency_s = round(time.monotonic() - started, 3)
    log_turn(reply, session_id)
    return reply


def log_path() -> Path:
    return PROJECT_ROOT / "logs" / "turns.jsonl"


def log_turn(reply: Reply, session_id: str) -> None:
    """One JSON line per turn. Contact details are masked before they reach disk."""
    entry = {
        "ts": now().isoformat(),
        "session_id": session_id,
        "model": reply.model,
        "tools": [
            {
                "name": call.name,
                "arguments": tools.mask_arguments(call.arguments),
                "error": call.result.get("error"),
            }
            for call in reply.tool_calls
        ],
        "tokens_in": reply.usage.prompt_tokens,
        "tokens_out": reply.usage.completion_tokens,
        "latency_s": reply.latency_s,
        "fallback": reply.fallback,
        "max_steps": reply.max_steps_reached,
    }
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
