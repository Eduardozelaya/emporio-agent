"""E6: the checks themselves, verified with fabricated replies and no API key.

The evaluation is the thing that tells us the agent behaves. If the checks are wrong, a green
report means nothing — so they get their own tests, including a reply with an invented price.
"""

from __future__ import annotations

import pytest

from emporio import eval as evaluation
from emporio.eval import Check, ScenarioResult, evaluate, fold, load_scenarios, numbers_in

CORPUS = 'preço de tabela R$ 2.199,00; 7 dias corridos; 5% de desconto; 12x sem juros'


def run_checks(spec, reply, tools=(), tool_results=(), messages=("pergunta",)):
    return evaluate(spec, reply, list(tools), list(tool_results), list(messages), CORPUS)


def failures(checks):
    return [c.name for c in checks if not c.passed]


# --------------------------------------------------------------------------- text folding


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Grátis", "gratis"), ("VIOLÕES", "varies"), ("Terça-feira", "terca-feira")],
)
def test_fold_strips_accents_and_case(raw, expected) -> None:
    folded = fold(raw)
    assert folded == folded.lower()
    assert "á" not in folded and "õ" not in folded and "ç" not in folded


def test_contains_check_ignores_accents() -> None:
    checks = run_checks({"must_contain": ["grátis"]}, "O frete fica gratis para você")
    assert not failures(checks)


# ------------------------------------------------------------------------ number parsing


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R$ 2.199,00", 2199.0),
        ("2.089,05", 2089.05),
        ("183,25", 183.25),
        ("12x", 12.0),
        ("R$ 35,00", 35.0),
    ],
)
def test_brazilian_numbers_are_parsed(text, expected) -> None:
    assert expected in numbers_in(text, brazilian=True)


def test_json_numbers_are_parsed() -> None:
    assert {2199.0, 2089.05} <= numbers_in('{"price": 2199.0, "final_total": 2089.05}')


def test_the_two_formats_meet() -> None:
    """2.199,00 in the reply and 2199.0 in the tool result are the same number."""
    assert numbers_in("R$ 2.199,00", brazilian=True) & numbers_in('{"price": 2199.0}')


@pytest.mark.parametrize("name", ["Takamine GD20", "Yamaha C40", "Yamaha APX600", "Yamaha FG800"])
def test_digits_glued_to_a_model_name_are_not_numbers(name) -> None:
    """Caught by a failing test: 'GD20' yielded 20 and was reported as an invented price."""
    assert not numbers_in(name, brazilian=True)


@pytest.mark.parametrize(("name", "number"), [("Kalani KAL-700T", 700.0), ("Martin D-28", 28.0)])
def test_digits_after_a_hyphen_are_still_read_as_numbers(name, number) -> None:
    """A known imprecision, and a harmless one.

    'D-28' yields 28, but the same product name appears in the tool result the reply is
    checked against, so it is grounded there. Being slightly permissive beats a false alarm.
    """
    assert number in numbers_in(name, brazilian=True)
    assert number in numbers_in(f'{{"name": "{name}"}}')


# ------------------------------------------------------- the check that matters most


def test_an_invented_price_is_caught() -> None:
    """The automated form of 'the agent must not invent prices'."""
    checks = run_checks(
        {"numbers_grounded": True},
        "O Martin D-28 sai por R$ 1.234,56 à vista.",
        tool_results=[{"product": {"name": "Martin D-28", "price": 18999.0}}],
    )
    assert "every number is grounded" in failures(checks)


def test_a_price_taken_from_the_tool_passes() -> None:
    checks = run_checks(
        {"numbers_grounded": True},
        "O Takamine GD20 sai por R$ 2.199,00, e no PIX fica R$ 2.089,05.",
        tool_results=[{"price": 2199.0, "final_total": 2089.05}],
    )
    assert not failures(checks)


def test_a_number_from_the_manual_passes() -> None:
    """'7 dias' is policy, not data: it is grounded in the manual, with no tool involved."""
    checks = run_checks(
        {"numbers_grounded": True}, "Você tem 7 dias corridos após o recebimento."
    )
    assert not failures(checks)


def test_a_number_the_customer_said_passes() -> None:
    checks = run_checks(
        {"numbers_grounded": True},
        "Procurando violões até R$ 1.500,00, então.",
        messages=["tenho até 1500 para gastar"],
    )
    assert not failures(checks)


# ------------------------------------------------------------------------- tool checks


def test_expected_tool_missing_fails() -> None:
    checks = run_checks({"expect_tools": ["quote_price"]}, "fica R$ 10", tools=["get_product"])
    assert "calls quote_price" in failures(checks)


def test_expected_tool_present_passes() -> None:
    checks = run_checks(
        {"expect_tools": ["get_product", "quote_price"], "numbers_grounded": False},
        "pronto",
        tools=["get_product", "quote_price"],
    )
    assert not failures(checks)


def test_expect_any_tool_accepts_either_route() -> None:
    """Looking up 'Takamine' with search_products or get_product is equally correct."""
    spec = {"expect_any_tool": ["get_product", "search_products"], "numbers_grounded": False}
    assert not failures(run_checks(spec, "qual deles?", tools=["search_products"]))
    assert not failures(run_checks(spec, "qual deles?", tools=["get_product"]))
    assert failures(run_checks(spec, "qual deles?", tools=["quote_price"]))


def test_forbidden_tool_fails() -> None:
    checks = run_checks(
        {"forbid_tools": ["get_order_status"], "numbers_grounded": False},
        "pronto",
        tools=["get_order_status"],
    )
    assert "does not call get_order_status" in failures(checks)


def test_star_forbids_every_tool() -> None:
    assert "calls no tool" in failures(
        run_checks({"forbid_tools": ["*"], "numbers_grounded": False}, "oi", tools=["get_product"])
    )
    assert not failures(
        run_checks({"forbid_tools": ["*"], "numbers_grounded": False}, "oi", tools=[])
    )


def test_must_not_contain_catches_a_leak() -> None:
    """S08: a wrong contact must not leak the tracking code."""
    checks = run_checks(
        {"must_not_contain": ["BRJL5544332BR"], "numbers_grounded": False},
        "Seu código é BRJL5544332BR.",
    )
    assert failures(checks)


# ------------------------------------------------------------------ the scenario file


def test_scenarios_file_is_valid() -> None:
    defaults, scenarios = load_scenarios()
    assert len(scenarios) == 31
    assert defaults["today"] == "2026-11-01T12:20:00"

    known_tools = {
        "search_products",
        "get_product",
        "list_active_promotions",
        "quote_price",
        "get_order_status",
        "escalate_to_human",
    }
    ids = set()
    for spec in scenarios:
        assert spec["id"] not in ids, f"duplicate id {spec['id']}"
        ids.add(spec["id"])
        assert spec["messages"], spec["id"]
        assert spec.get("title"), spec["id"]
        for name in (spec.get("expect_tools") or []) + (spec.get("expect_any_tool") or []):
            assert name in known_tools, f"{spec['id']} expects unknown tool {name}"
        for name in spec.get("forbid_tools") or []:
            assert name in known_tools or name == "*", f"{spec['id']} forbids unknown tool {name}"


def test_every_scenario_has_at_least_one_assertion() -> None:
    _, scenarios = load_scenarios()
    for spec in scenarios:
        assertions = (
            (spec.get("expect_tools") or [])
            + (spec.get("expect_any_tool") or [])
            + (spec.get("forbid_tools") or [])
            + (spec.get("must_contain") or [])
            + (spec.get("must_not_contain") or [])
        )
        assert assertions or spec.get("numbers_grounded"), f"{spec['id']} asserts nothing"


# ---------------------------------------------------------------------------- reporting


def test_report_counts_and_lists_failures() -> None:
    from emporio.config import load_settings

    results = [
        ScenarioResult(
            id="S01",
            title="ok one",
            messages=["oi"],
            replies=["olá"],
            checks=[Check("a", True)],
            seconds=1.0,
        ),
        ScenarioResult(
            id="S02",
            title="broken one",
            messages=["oi"],
            replies=["olá"],
            tools_called=["get_product"],
            checks=[Check("b", False, "because")],
            seconds=2.0,
        ),
    ]
    report = evaluation.render_report(results, load_settings())
    assert "1/2 scenarios passed" in report
    assert "## Failures" in report
    assert "because" in report
    assert "`get_product`" in report


def test_fallback_counts_as_a_failure() -> None:
    result = ScenarioResult(id="S01", title="t", messages=["oi"], replies=["..."])
    result.checks = [Check("no fallback", False, "the turn ended in the safe reply")]
    assert result.passed is False


# --------------------------------------------- regressions from the stability runs


@pytest.mark.parametrize(
    ("reply", "corpus_json"),
    [
        ("R$ 323,10", '{"promo_price": 323.1}'),
        ("R$ 323.10", '{"promo_price": 323.1}'),  # the model slipping into US format
        ("R$ 2.199,00", '{"price": 2199.0}'),
        ("R$ 2199", '{"price": 2199.0}'),
        ("5.999,00", '{"price": 5999.0}'),
    ],
)
def test_a_price_is_recognised_in_either_decimal_format(reply, corpus_json) -> None:
    """A stability run reported six invented prices that were all real.

    The agent had written "R$ 323.10" with a dot, and the parser read Brazilian thousands
    separators only, turning it into 32,310. Both readings are kept now: a price the agent
    actually invented matches neither.
    """
    assert numbers_in(reply, brazilian=True) & numbers_in(corpus_json)


def test_must_contain_any_accepts_synonyms() -> None:
    """Free shipping is "grátis" or "sem custo" depending on the turn; both are correct."""
    spec = {"must_contain_any": ["gratis", "sem custo"], "numbers_grounded": False}
    assert not failures(run_checks(spec, "O frete fica sem custo pra você."))
    assert not failures(run_checks(spec, "Frete grátis!"))
    assert failures(run_checks(spec, "O frete fica R$ 35,00."))
