"""E4 acceptance criteria: the loop, its guards, the prompt layout and the turn log."""

from __future__ import annotations

import json
import shutil

import pytest

from emporio import agent, data_loader, prompts
from emporio.config import PROJECT_ROOT, Settings
from emporio.llm import LLMError
from fakes import AlwaysFailingLLM, FakeLLM, calls, says

REAL_RAW = PROJECT_ROOT / "data" / "raw"
ORDER_8_EMAIL = "anacarol.ferreira@coldmail.com"


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("agent")
    shutil.copytree(REAL_RAW, root / "data" / "raw")
    built = Settings(
        llm_api_key=None,
        llm_base_url=None,
        llm_model="fake-model",
        llm_temperature=0.0,
        llm_timeout_s=5,
        max_tool_steps=3,
        history_window=20,
        emporio_today=None,
        data_dir=root / "data",
    )
    data_loader.build(built)
    # The curated manual is committed, not generated: copy it next to the built database.
    built.processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROJECT_ROOT / "data" / "processed" / "policies.md", built.policies_path)
    return built


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EMPORIO_TODAY", "2026-11-01T12:20:00")
    # Keep the real logs/turns.jsonl out of the test run.
    monkeypatch.setattr(agent, "log_path", lambda: tmp_path / "turns.jsonl")


# ---------------------------------------------------------------------- AC1: the happy path


def test_tool_call_then_text(settings) -> None:
    """AC1: run the tool, append the result, ask again, return the words."""
    llm = FakeLLM(
        calls("get_product", {"name": "Takamine GD20"}),
        says("O Takamine GD20 sai por R$ 2.199,00."),
    )
    reply = agent.run_turn("s1", "Quanto custa o Takamine GD20?", settings, llm=llm)

    assert reply.text == "O Takamine GD20 sai por R$ 2.199,00."
    assert reply.tool_names == ["get_product"]
    assert reply.tool_calls[0].result["product"]["product_id"] == 95
    assert llm.call_count == 2
    assert reply.fallback is False


def test_the_tool_result_is_fed_back_to_the_model(settings) -> None:
    llm = FakeLLM(calls("get_product", {"product_id": 95}), says("ok"))
    agent.run_turn("s1", "preço?", settings, llm=llm)

    second_call = llm.calls[1]
    assert second_call[-1]["role"] == "tool"
    assert "2199" in second_call[-1]["content"]
    # The assistant message that requested the tool must stay next to its result.
    assert second_call[-2]["role"] == "assistant"
    assert second_call[-2]["tool_calls"][0]["function"]["name"] == "get_product"


def test_several_tools_in_one_turn(settings) -> None:
    llm = FakeLLM(
        calls("get_product", {"name": "Takamine GD20"}),
        calls("quote_price", {"product_id": 95, "payment_method": "pix"}),
        says("No PIX fica R$ 2.089,05."),
    )
    reply = agent.run_turn("s1", "quanto fica no pix?", settings, llm=llm)
    assert reply.tool_names == ["get_product", "quote_price"]
    assert reply.tool_calls[1].result["final_total"] == 2089.05


def test_history_is_placed_between_system_and_user(settings) -> None:
    llm = FakeLLM(says("claro"))
    history = [
        {"role": "user", "content": "Quanto custa o Yamaha C40?"},
        {"role": "assistant", "content": "R$ 599,90."},
    ]
    agent.run_turn("s1", "e em 6x?", settings, history=history, llm=llm)

    roles = [message["role"] for message in llm.calls[0]]
    assert roles == ["system", "user", "assistant", "user"]
    assert llm.calls[0][-1]["content"] == "e em 6x?"


def test_reply_carries_the_turn_messages_for_memory(settings) -> None:
    llm = FakeLLM(calls("list_active_promotions", {}), says("Temos 4 promoções."))
    reply = agent.run_turn("s1", "quais promoções?", settings, llm=llm)

    roles = [message["role"] for message in reply.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert reply.messages[0]["content"] == "quais promoções?"


# ------------------------------------------------------------------------ AC2: max steps


def test_stops_at_max_tool_steps(settings) -> None:
    """AC2: a model stuck in a loop must not burn tokens while a customer waits."""
    llm = FakeLLM(*[calls("list_active_promotions", {}) for _ in range(10)])
    reply = agent.run_turn("s1", "promoções?", settings, llm=llm)

    assert reply.max_steps_reached is True
    assert reply.fallback is True
    assert llm.call_count == settings.max_tool_steps
    assert "(67) 3341-4444" in reply.text


# -------------------------------------------------------------------- AC3: provider down


def test_provider_failure_gives_a_safe_reply(settings) -> None:
    """AC3: no invented answer, a phone number and a way out."""
    llm = AlwaysFailingLLM()
    reply = agent.run_turn("s1", "quanto custa o GD20?", settings, llm=llm)

    assert reply.fallback is True
    assert reply.max_steps_reached is False
    assert "(67) 3341-4444" in reply.text
    assert "R$" not in reply.text.replace("(67) 3341-4444", "")  # no prices invented


def test_failure_after_a_successful_tool_keeps_what_it_learned(settings) -> None:
    llm = FakeLLM(calls("get_product", {"product_id": 95}), LLMError("boom"))
    reply = agent.run_turn("s1", "preço?", settings, llm=llm)
    assert reply.fallback is True
    assert reply.tool_names == ["get_product"]


def test_llm_client_retries_once_then_raises(monkeypatch) -> None:
    """A provider can send headers and then stall, so the retry lives in the client."""
    from emporio.llm import LLMClient

    class StallingCompletions:
        def __init__(self) -> None:
            self.attempts = 0

        def create(self, **kwargs):  # noqa: ANN003, ARG002
            self.attempts += 1
            raise TimeoutError("no response body")

    completions = StallingCompletions()
    sdk = type("SDK", (), {"chat": type("Chat", (), {"completions": completions})()})()

    monkeypatch.setattr("time.sleep", lambda _: None)  # no real backoff in tests
    client = LLMClient(client=sdk)

    with pytest.raises(LLMError, match="failed after 2 attempts"):
        client.complete([{"role": "user", "content": "oi"}])
    assert completions.attempts == 2  # the first try plus one retry


# ------------------------------------------------------------------ AC4: tool errors flow


def test_tool_error_is_handed_to_the_model_not_raised(settings) -> None:
    """AC4: an error dict is data the model can read and correct itself with."""
    llm = FakeLLM(
        calls("get_order_status", {"order_id": 8, "email_or_phone": "errado@x.com"}),
        says("Não consegui confirmar. Pode conferir o e-mail da compra?"),
    )
    reply = agent.run_turn("s1", "cadê meu pedido 8?", settings, llm=llm)

    assert reply.tool_calls[0].failed is True
    assert reply.tool_calls[0].result["error"] == "verification_failed"
    assert reply.fallback is False
    assert "verification_failed" in llm.calls[1][-1]["content"]


def test_unknown_tool_does_not_break_the_loop(settings) -> None:
    llm = FakeLLM(calls("cancel_order", {}), says("Não consigo cancelar, vou encaminhar."))
    reply = agent.run_turn("s1", "cancela meu pedido", settings, llm=llm)
    assert reply.tool_calls[0].result["error"] == "unknown_tool"
    assert reply.text.startswith("Não consigo cancelar")


def test_malformed_tool_arguments_are_reported_back(settings) -> None:
    llm = FakeLLM(calls("search_products", "{not json"), says("Deixa eu tentar de novo."))
    reply = agent.run_turn("s1", "violões?", settings, llm=llm)
    assert reply.tool_calls[0].result["error"] == "invalid_arguments"


def test_empty_model_answer_falls_back_instead_of_sending_nothing(settings) -> None:
    llm = FakeLLM(says("   "))
    reply = agent.run_turn("s1", "oi", settings, llm=llm)
    assert "(67) 3341-4444" in reply.text


# --------------------------------------------------------------------- AC5: prompt layout


def test_static_prefix_is_byte_identical_across_turns(settings) -> None:
    """AC5: a prefix that changes defeats the provider's prompt cache."""
    assert prompts.static_prefix(settings) == prompts.static_prefix(settings)


def test_dynamic_context_comes_last(settings) -> None:
    from datetime import datetime

    from emporio.config import STORE_TZ

    moment = datetime(2026, 11, 1, 12, 20, tzinfo=STORE_TZ)
    prompt = prompts.build_system_prompt(settings, moment)

    assert prompt.startswith(prompts.static_prefix(settings))
    assert prompt.rstrip().endswith(prompts.dynamic_suffix(moment).rstrip())
    assert prompt.index("## Contexto de agora") > prompt.index("## Manual de políticas")


def test_dynamic_context_knows_the_store_is_shut_and_when_it_reopens(settings) -> None:
    from datetime import datetime

    from emporio.config import STORE_TZ

    suffix = prompts.dynamic_suffix(datetime(2026, 11, 1, 12, 20, tzinfo=STORE_TZ))
    assert "domingo" in suffix
    assert "terça-feira" in suffix  # Monday 02/11 is Finados (D18)


def test_prompt_carries_the_whole_manual(settings) -> None:
    prompt = prompts.build_system_prompt(settings)
    for fact in ("Rua 14 de Maio, 3200", "24 horas úteis", "5% de desconto", "LGPD"):
        assert fact in prompt


def test_prompt_states_the_rules_that_cannot_live_in_code(settings) -> None:
    prefix = prompts.static_prefix(settings)
    for rule in (
        "Nunca invente um fato",
        "Nunca faça conta de cabeça",
        "acessórios",
        "nunca invente o\nnome de uma loja",
        "sem nenhum produto",
    ):
        assert rule in prefix


def test_tool_schemas_reach_the_model(settings) -> None:
    llm = FakeLLM(says("oi"))
    agent.run_turn("s1", "oi", settings, llm=llm)
    assert {schema["function"]["name"] for schema in llm.tools_seen[0]} == {
        "search_products",
        "get_product",
        "list_active_promotions",
        "quote_price",
        "get_order_status",
        "escalate_to_human",
    }


# ------------------------------------------------------------------------ AC6: turn log


def test_turn_is_logged_with_tokens_and_latency(settings, tmp_path) -> None:
    llm = FakeLLM(calls("list_active_promotions", {}), says("Temos 4."))
    reply = agent.run_turn("session-xyz", "promoções?", settings, llm=llm)

    entries = [
        json.loads(line)
        for line in (tmp_path / "turns.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    entry = entries[-1]
    assert entry["session_id"] == "session-xyz"
    assert entry["tools"][0]["name"] == "list_active_promotions"
    assert entry["tokens_in"] == reply.usage.prompt_tokens > 0
    assert entry["tokens_out"] == reply.usage.completion_tokens > 0
    assert entry["latency_s"] >= 0
    assert entry["fallback"] is False


def test_contact_details_never_reach_the_log(settings, tmp_path) -> None:
    """AC6: the log is for debugging, not a second copy of the customer database."""
    llm = FakeLLM(
        calls("get_order_status", {"order_id": 8, "email_or_phone": ORDER_8_EMAIL}),
        says("Seu pedido está com a equipe."),
    )
    agent.run_turn("s1", "pedido 8", settings, llm=llm)

    log = (tmp_path / "turns.jsonl").read_text(encoding="utf-8")
    assert ORDER_8_EMAIL not in log
    assert "anacarol" not in log
    assert "get_order_status" in log


def test_fallback_is_flagged_in_the_log(settings, tmp_path) -> None:
    agent.run_turn("s1", "oi", settings, llm=AlwaysFailingLLM())
    entry = json.loads((tmp_path / "turns.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["fallback"] is True


def test_the_provider_reason_reaches_the_operator_not_the_customer(settings) -> None:
    """A 429 "no credits remaining" is useless to a customer and essential to us.

    Found during the first live run: the fallback behaved correctly but swallowed the only
    sentence that explained why nothing worked.
    """
    reply = agent.run_turn("s1", "oi", settings, llm=AlwaysFailingLLM())
    assert "provider unreachable" in reply.error
    assert "provider" not in reply.text


def test_max_steps_records_why_it_stopped(settings) -> None:
    llm = FakeLLM(*[calls("list_active_promotions", {}) for _ in range(10)])
    reply = agent.run_turn("s1", "promoções?", settings, llm=llm)
    assert "tool steps" in reply.error


def test_token_usage_accumulates_over_the_steps(settings) -> None:
    llm = FakeLLM(
        calls("list_active_promotions", {}, prompt_tokens=1000, completion_tokens=20),
        says("pronto", prompt_tokens=1200, completion_tokens=60),
    )
    reply = agent.run_turn("s1", "promoções?", settings, llm=llm)
    assert reply.usage.prompt_tokens == 2200
    assert reply.usage.completion_tokens == 80
    assert reply.usage.total == 2280
