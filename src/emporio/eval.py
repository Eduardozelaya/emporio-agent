"""Behavioural evaluation.

An LLM does not produce the same sentence twice, so asserting on text would test the wrong
thing. These scenarios assert on **behaviour**: which tool ran, which facts appear, which
facts must never appear, and — the one that matters most — whether every number in the reply
can be traced back to a tool result, the conversation or the manual.

That last check is the automated version of "the agent must not invent prices".
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from emporio import agent, memory, policies, prompts
from emporio.config import PROJECT_ROOT, Settings, get_settings

SCENARIOS_PATH = PROJECT_ROOT / "eval" / "scenarios.yaml"
RESULTS_PATH = PROJECT_ROOT / "eval" / "results.md"

#: A number, but not the digits inside a model name. "GD20" and "APX600" are words, and
#: extracting 20 and 600 from them produced false alarms about invented prices. Requiring that
#: no word character precedes the match stops the regex restarting in the middle of a token.
_NUMBER = re.compile(r"(?<!\w)\d[\d.,]*")


def fold(text: str) -> str:
    """Lowercase and strip accents, so checks survive 'grátis' vs 'gratis'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def numbers_in(text: str, brazilian: bool = False) -> set[float]:
    """Every number in a text, as floats.

    Brazilian text writes 2.199,00; JSON writes 2199.0. When the format is ambiguous we add
    both readings to the corpus rather than guessing, because a false failure here would
    waste more time than it saves.
    """
    found: set[float] = set()
    for raw in _NUMBER.findall(text):
        token = raw.rstrip(".,")
        if not token:
            continue
        candidates = set()
        if "," in token:
            # Unambiguous Brazilian: dots group thousands, the comma is the decimal point.
            candidates.add(token.replace(".", "").replace(",", "."))
        elif "." in token:
            # Ambiguous: "2.199" is 2199 to a Brazilian and 2.199 to a parser, and a model
            # writing Portuguese still slips into "R$ 323.10". Keep both readings — a price
            # the agent invented matches neither, so nothing is lost by being generous.
            candidates.add(token)
            candidates.add(token.replace(".", ""))
        else:
            candidates.add(token)
        for candidate in candidates:
            try:
                found.add(float(candidate))
            except ValueError:
                continue
    return found


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    id: str
    title: str
    messages: list[str]
    replies: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    fallback: bool = False

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def evaluate(
    spec: dict[str, Any],
    reply_text: str,
    tools_called: list[str],
    tool_results: list[dict[str, Any]],
    user_messages: list[str],
    grounding_corpus: str,
) -> list[Check]:
    """All the checks for one scenario, against the final reply of the conversation."""
    checks: list[Check] = []
    folded = fold(reply_text)

    expected = spec.get("expect_tools") or []
    for name in expected:
        checks.append(
            Check(
                f"calls {name}",
                name in tools_called,
                "" if name in tools_called else f"tools called: {tools_called or 'none'}",
            )
        )

    # For scenarios where several tools are a legitimate route to the same behaviour.
    alternatives = spec.get("expect_any_tool") or []
    if alternatives:
        hit = [name for name in alternatives if name in tools_called]
        checks.append(
            Check(
                f"calls one of {alternatives}",
                bool(hit),
                "" if hit else f"tools called: {tools_called or 'none'}",
            )
        )

    forbidden = spec.get("forbid_tools") or []
    if forbidden == ["*"]:
        checks.append(
            Check("calls no tool", not tools_called, f"called: {tools_called}")
        )
    else:
        for name in forbidden:
            checks.append(
                Check(f"does not call {name}", name not in tools_called, f"called: {tools_called}")
            )

    for needle in spec.get("must_contain") or []:
        ok = fold(needle) in folded
        checks.append(Check(f"says {needle!r}", ok, "" if ok else "not found in the reply"))

    # For facts the agent can state in several equally correct ways. "Free shipping" is
    # "grátis", "sem custo" or "não paga frete" depending on the turn, and a check pinned to
    # one of them measures vocabulary rather than behaviour.
    synonyms = spec.get("must_contain_any") or []
    if synonyms:
        hit = [n for n in synonyms if fold(n) in folded]
        checks.append(
            Check(
                f"says one of {synonyms}",
                bool(hit),
                "" if hit else "none of them appear in the reply",
            )
        )

    for needle in spec.get("must_not_contain") or []:
        ok = fold(needle) not in folded
        checks.append(Check(f"never says {needle!r}", ok, "" if ok else "found in the reply"))

    if spec.get("numbers_grounded", True):
        corpus = grounding_corpus + " " + " ".join(user_messages)
        corpus += " " + json.dumps(tool_results, ensure_ascii=False, default=str)
        allowed = numbers_in(corpus) | numbers_in(corpus, brazilian=True)
        said = numbers_in(reply_text, brazilian=True)
        invented = sorted(said - allowed)
        checks.append(
            Check(
                "every number is grounded",
                not invented,
                "" if not invented else f"not found in any tool result or the manual: {invented}",
            )
        )

    return checks


def run_scenario(
    spec: dict[str, Any], settings: Settings, defaults: dict[str, Any]
) -> ScenarioResult:
    """Replay one conversation against the live model."""
    import os
    import time

    merged = {**defaults, **spec}
    result = ScenarioResult(id=spec["id"], title=spec.get("title", ""), messages=spec["messages"])

    previous_today = os.environ.get("EMPORIO_TODAY")
    if merged.get("today"):
        os.environ["EMPORIO_TODAY"] = merged["today"]

    session = f"eval-{spec['id']}-{memory.new_session_id()}"
    history: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    started = time.monotonic()

    try:
        for message in spec["messages"]:
            reply = agent.run_turn(session, message, settings, history=history)
            history = history + reply.messages
            result.replies.append(reply.text)
            result.tools_called.extend(reply.tool_names)
            tool_results.extend(call.result for call in reply.tool_calls)
            result.tokens_in += reply.usage.prompt_tokens
            result.tokens_out += reply.usage.completion_tokens
            result.fallback = result.fallback or reply.fallback

        result.seconds = round(time.monotonic() - started, 1)
        corpus = prompts.static_prefix(settings)
        result.checks = evaluate(
            merged,
            result.replies[-1],
            result.tools_called,
            tool_results,
            spec["messages"],
            corpus,
        )
        if result.fallback:
            result.checks.append(Check("no fallback", False, "the turn ended in the safe reply"))
    finally:
        if previous_today is None:
            os.environ.pop("EMPORIO_TODAY", None)
        else:
            os.environ["EMPORIO_TODAY"] = previous_today

    return result


def load_scenarios(path: Path = SCENARIOS_PATH) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("defaults", {}), data["scenarios"]


def render_report(results: list[ScenarioResult], settings: Settings) -> str:
    passed = [r for r in results if r.passed]
    total_checks = sum(len(r.checks) for r in results)
    failed_checks = sum(1 for r in results for c in r.checks if not c.passed)
    tokens_in = sum(r.tokens_in for r in results)
    tokens_out = sum(r.tokens_out for r in results)

    lines = [
        "# Evaluation results",
        "",
        "> Generated by `python -m emporio eval`. Behaviour, not wording: which tool ran,",
        "> which facts appear, and whether every number can be traced to a tool result.",
        "",
        f"**{len(passed)}/{len(results)} scenarios passed** "
        f"({total_checks - failed_checks}/{total_checks} individual checks).",
        "",
        f"- Model: `{settings.llm_model}`"
        + (f" via `{settings.llm_base_url}`" if settings.llm_base_url else " (OpenAI)"),
        f"- Tokens: {tokens_in:,} in / {tokens_out:,} out",
        f"- Wall time: {sum(r.seconds for r in results):.0f}s",
        "",
        "| # | Scenario | Tools called | Checks | Time |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        mark = "✅" if r.passed else "❌"
        ok = sum(1 for c in r.checks if c.passed)
        tools = ", ".join(f"`{t}`" for t in dict.fromkeys(r.tools_called)) or "—"
        lines.append(
            f"| {mark} {r.id} | {r.title} | {tools} | {ok}/{len(r.checks)} | {r.seconds}s |"
        )

    failures = [r for r in results if not r.passed]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines += [f"### {r.id} — {r.title}", ""]
            for check in r.checks:
                if not check.passed:
                    lines.append(f"- **{check.name}** — {check.detail}")
            lines += ["", "<details><summary>conversation</summary>", ""]
            for question, answer in zip(r.messages, r.replies, strict=False):
                lines += [f"**cliente:** {question}", "", f"**loja:** {answer}", ""]
            lines += ["</details>", ""]

    lines += ["", "## Transcripts", ""]
    for r in results:
        mark = "✅" if r.passed else "❌"
        lines += [f"<details><summary>{mark} {r.id} — {r.title}</summary>", ""]
        for question, answer in zip(r.messages, r.replies, strict=False):
            lines += [f"**cliente:** {question}", "", f"**loja:** {answer}", ""]
        if r.tools_called:
            lines.append(f"*ferramentas: {', '.join(r.tools_called)}*")
        lines += ["", "</details>", ""]

    return "\n".join(lines) + "\n"


def main(only: list[str] | None = None) -> int:
    settings = get_settings()
    settings.require_api_key()
    policies.load_policies(settings)  # fail early if the manual is missing

    defaults, scenarios = load_scenarios()
    # A partial run writes somewhere else: `--only S14` once overwrote the committed report
    # of a full run with four lines, which is exactly the sort of thing nobody notices until
    # the report is the deliverable.
    destination = RESULTS_PATH
    if only:
        scenarios = [s for s in scenarios if s["id"] in only]
        destination = RESULTS_PATH.with_name("results_partial.md")
        if not scenarios:
            print(f"No scenario matches {only}.")
            return 1

    results: list[ScenarioResult] = []
    for i, spec in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {spec['id']} {spec.get('title', '')}", flush=True)
        result = run_scenario(spec, settings, defaults)
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        print(f"      {mark}  tools={result.tools_called or '-'}  {result.seconds}s", flush=True)
        for check in result.checks:
            if not check.passed:
                print(f"        x {check.name}: {check.detail}", flush=True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_report(results, settings), encoding="utf-8")

    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} scenarios passed -> {destination}")
    return 0 if passed == len(results) else 1
