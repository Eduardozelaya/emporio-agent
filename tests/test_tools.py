"""E3 acceptance criteria.

The privacy tests are the important ones: they are what stops the agent from becoming a way
to read other people's orders.
"""

from __future__ import annotations

import shutil

import pytest

from emporio import data_loader, tools
from emporio.config import PROJECT_ROOT, Settings
from emporio.tools import dispatch

REAL_RAW = PROJECT_ROOT / "data" / "raw"

ORDER_8_EMAIL = "anacarol.ferreira@coldmail.com"
ORDER_8_PHONE = "(67) 99654-7821"


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A throwaway copy of the real data, so tickets never land in the developer's app.db."""
    root = tmp_path_factory.mktemp("tools")
    shutil.copytree(REAL_RAW, root / "data" / "raw")
    built = Settings(
        openai_api_key=None,
        llm_base_url=None,
        llm_model="test",
        llm_temperature=0.0,
        llm_timeout_s=1,
        max_tool_steps=1,
        history_window=1,
        emporio_today=None,
        data_dir=root / "data",
    )
    data_loader.build(built)
    return built


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sunday 2026-11-01: the date the examples and the eval scenarios use (D13)."""
    monkeypatch.setenv("EMPORIO_TODAY", "2026-11-01T12:20:00")


def call(name, args, settings, **kwargs):
    return dispatch(name, args, settings=settings, **kwargs)


# ------------------------------------------------------------------------ AC1-AC3: search


def test_violoes_up_to_1000(settings) -> None:
    """AC1: the 12 products of the oracle, by price, without 96 (no stock) or 113."""
    result = call("search_products", {"category": "Violões", "max_price": 1000}, settings)
    assert [item["product_id"] for item in result["items"]] == [
        83, 85, 89, 88, 81, 84, 87, 86, 107, 82, 91, 112,
    ]
    assert result["total_found"] == 12
    returned = {item["product_id"] for item in result["items"]}
    assert 96 not in returned and 113 not in returned


def test_include_unavailable_brings_them_back_with_their_status(settings) -> None:
    """AC2."""
    result = call(
        "search_products",
        {"category": "Violões", "max_price": 1000, "include_unavailable": True, "limit": 15},
        settings,
    )
    by_id = {item["product_id"]: item["availability"] for item in result["items"]}
    assert by_id[96] == "out_of_stock"
    assert by_id[113] == "discontinued"


def test_empty_category_is_an_empty_list_not_an_error(settings) -> None:
    """AC3: the category exists, it just has nothing in it. The agent must not invent one."""
    result = call("search_products", {"category": "Instrumentos de Sopro (Metais)"}, settings)
    assert result["items"] == []
    assert result["total_found"] == 0
    assert "error" not in result


def test_total_found_reports_the_full_count_not_the_page(settings) -> None:
    result = call("search_products", {"category": "Violões", "limit": 3}, settings)
    assert len(result["items"]) == 3
    assert result["total_found"] == 33  # 35 violões minus the two not for sale


def test_search_carries_the_active_promotion(settings) -> None:
    result = call("search_products", {"query": "Ohana CK-20"}, settings)
    assert result["items"][0]["promo"] == {"percent": 20, "price": 439.20}


def test_search_filters_are_accent_insensitive(settings) -> None:
    result = call("search_products", {"query": "aco folk"}, settings)
    assert any("Aço" in item["name"] for item in result["items"])


def test_strings_filter(settings) -> None:
    """16 nylon violões in the catalogue, 15 of them sellable (113 is discontinued)."""
    result = call("search_products", {"category": "Violões", "strings": "nylon"}, settings)
    assert result["total_found"] == 15
    assert 113 not in {item["product_id"] for item in result["items"]}


# ----------------------------------------------------------------------- AC4: get_product


def test_exact_name_returns_one_product(settings) -> None:
    result = call("get_product", {"name": "Takamine GD20"}, settings)
    assert result["product"]["product_id"] == 95
    assert result["product"]["price"] == 2199.00
    assert "specs" in result["product"] and "description" in result["product"]


def test_ambiguous_name_returns_matches(settings) -> None:
    result = call("get_product", {"name": "Takamine"}, settings)
    assert {m["product_id"] for m in result["matches"]} == {95, 100, 105, 115}
    assert "product" not in result


@pytest.mark.parametrize("name", ["takamine gd20", "TAKAMINE GD20", "Takamine  gd20 "])
def test_matching_ignores_case_and_spacing(settings, name) -> None:
    assert call("get_product", {"name": name}, settings)["product"]["product_id"] == 95


def test_typo_is_rescued(settings) -> None:
    """A customer typing from memory still gets an answer."""
    assert call("get_product", {"name": "takamini gd 20"}, settings)["product"]["product_id"] == 95


def test_category_word_in_the_query_is_dropped(settings) -> None:
    """No product is literally named "violão", but that is how people ask."""
    result = call("get_product", {"name": "violao Takamine GD20"}, settings)
    assert result["product"]["product_id"] == 95


def test_unknown_product_is_not_found(settings) -> None:
    result = call("get_product", {"name": "xilofone de bolso"}, settings)
    assert result["error"] == "not_found"


def test_get_product_requires_an_identifier(settings) -> None:
    assert call("get_product", {}, settings)["error"] == "invalid_arguments"


# ------------------------------------------------- AC5: promotions and quote delegate math


def test_active_promotions(settings) -> None:
    result = call("list_active_promotions", {}, settings)
    assert [(i["product_id"], i["percent"], i["promo_price"]) for i in result["items"]] == [
        (90, 18, 1967.18),
        (94, 8, 5519.08),
        (121, 20, 439.20),
        (127, 10, 323.10),
    ]


def test_inactive_promotion_is_never_offered(settings) -> None:
    """The GD20 has a 12% row in the data, but it is switched off."""
    result = call("list_active_promotions", {}, settings)
    assert 95 not in {item["product_id"] for item in result["items"]}


def test_quote_pix(settings) -> None:
    result = call("quote_price", {"product_id": 95, "payment_method": "pix"}, settings)
    assert result["final_total"] == 2089.05
    assert result["max_installments_allowed"] == 12


def test_quote_installments(settings) -> None:
    result = call(
        "quote_price", {"product_id": 95, "payment_method": "credit", "installments": 12}, settings
    )
    assert result["installments"] == {
        "requested": 12,
        "allowed": True,
        "value": 183.25,
        "reason": None,
    }


def test_quote_refuses_a_product_not_for_sale(settings) -> None:
    """Product 130 is coming_soon: it has a price in the table but cannot be sold."""
    result = call("quote_price", {"product_id": 130, "payment_method": "pix"}, settings)
    assert result["error"] == "not_for_sale"


def test_quote_with_delivery(settings) -> None:
    """Product 127 carries an active 10% promotion, so the shipping threshold sees 323.10."""
    result = call(
        "quote_price",
        {"product_id": 127, "payment_method": "debit", "delivery": "metro_campo_grande"},
        settings,
    )
    assert result["unit_price"] == 359.00
    assert result["promo"] == {"percent": 10, "unit_price": 323.10}
    assert result["final_total"] == 323.10
    assert result["shipping"]["cost"] == 35.00
    assert result["grand_total"] == 358.10


def test_free_shipping_above_the_threshold(settings) -> None:
    result = call(
        "quote_price",
        {"product_id": 95, "payment_method": "debit", "delivery": "metro_campo_grande"},
        settings,
    )
    assert result["shipping"]["cost"] == 0.00
    assert result["grand_total"] == result["final_total"] == 2199.00


def test_quote_for_another_city_cannot_be_computed(settings) -> None:
    result = call(
        "quote_price", {"product_id": 95, "payment_method": "pix", "delivery": "other_city"},
        settings,
    )
    assert result["shipping"]["cost"] is None
    assert result["grand_total"] is None


def test_quote_rejects_thirteen_installments(settings) -> None:
    result = call(
        "quote_price", {"product_id": 95, "payment_method": "credit", "installments": 13}, settings
    )
    assert result["error"] == "invalid_arguments"


# ------------------------------------------------------------- AC6-AC7: order and privacy


def test_order_requires_a_matching_contact(settings) -> None:
    """AC6. The core privacy guarantee."""
    result = call(
        "get_order_status", {"order_id": 8, "email_or_phone": "fulano@x.com"}, settings
    )
    assert result == {"error": "verification_failed", "message": result["message"]}
    assert "BRJL5544332BR" not in result["message"]


def test_unknown_order_and_wrong_contact_are_indistinguishable(settings) -> None:
    """Different messages would let anyone enumerate the store's orders (D8)."""
    wrong = call("get_order_status", {"order_id": 8, "email_or_phone": "fulano@x.com"}, settings)
    missing = call(
        "get_order_status", {"order_id": 999, "email_or_phone": "fulano@x.com"}, settings
    )
    assert wrong == missing


@pytest.mark.parametrize(
    "contact",
    [
        ORDER_8_EMAIL,
        "  ANACAROL.Ferreira@Coldmail.com ",  # normalised before comparing
        ORDER_8_PHONE,
        "67996547821",
        "996547821",  # without the area code
    ],
)
def test_order_accepted_for_every_form_of_the_real_contact(settings, contact) -> None:
    result = call("get_order_status", {"order_id": 8, "email_or_phone": contact}, settings)
    assert result["order"]["order_id"] == 8


@pytest.mark.parametrize("contact", ["7821", "67", "1", ""])
def test_short_fragments_never_prove_ownership(settings, contact) -> None:
    result = call("get_order_status", {"order_id": 8, "email_or_phone": contact}, settings)
    assert "order" not in result


def test_verified_order_8_is_flagged_as_stale(settings) -> None:
    """AC7. Shipped in February, promised for 28/02, asked about on 01/11 (D17)."""
    order = call("get_order_status", {"order_id": 8, "email_or_phone": ORDER_8_EMAIL}, settings)[
        "order"
    ]
    assert order["status_label_pt"] == "enviado"
    assert order["tracking_code"] == "BRJL5544332BR"
    assert order["needs_attention"] is True
    assert "28/02/2026" in order["attention_reason"]
    assert order["customer_first_name"] == "Ana"


def test_only_the_first_name_leaves_the_tool(settings) -> None:
    """D20 opened the smallest possible hole in D8: nothing else about the customer."""
    order = call("get_order_status", {"order_id": 8, "email_or_phone": ORDER_8_EMAIL}, settings)[
        "order"
    ]
    for leaked in ("email", "phone", "city", "customer_id", "customer_name"):
        assert leaked not in order
    assert " " not in order["customer_first_name"]


def owner_email(settings, order_id: int) -> str:
    """The e-mail registered on an order, read straight from the database."""
    import sqlite3

    connection = sqlite3.connect(settings.db_path)
    try:
        return connection.execute(
            "SELECT c.email FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
            "WHERE o.order_id = ?",
            (order_id,),
        ).fetchone()[0]
    finally:
        connection.close()


def test_pending_order_with_an_unreleased_product_needs_attention(settings) -> None:
    """Order 14 contains product 130, which has not been released."""
    order = call(
        "get_order_status",
        {"order_id": 14, "email_or_phone": owner_email(settings, 14)},
        settings,
    )["order"]
    assert order["needs_attention"] is True
    assert order["attention_reason"]


def test_cancelled_order_shares_its_reason_with_the_owner(settings) -> None:
    order = call(
        "get_order_status",
        {"order_id": 17, "email_or_phone": owner_email(settings, 17)},
        settings,
    )["order"]
    assert order["status_label_pt"] == "cancelado"
    assert order["notes"]


def test_delivered_order_is_not_flagged(settings) -> None:
    order = call(
        "get_order_status",
        {"order_id": 1, "email_or_phone": owner_email(settings, 1)},
        settings,
    )["order"]
    assert order["needs_attention"] is False
    assert order["status_label_pt"] == "entregue"


# ------------------------------------------------------------------- AC8: human handoff


def test_escalation_creates_a_ticket_with_a_response_window(settings) -> None:
    result = call(
        "escalate_to_human",
        {"reason": "complaint", "summary": "Violão chegou com o tampo rachado."},
        settings,
        session_id="test-session",
    )
    assert isinstance(result["ticket_id"], int)
    # Sunday 12:20 -> store reopens Tuesday (Finados Monday) -> answer by Wednesday 09:00.
    assert "quarta-feira" in result["expected_response"]


def test_escalation_is_persisted(settings) -> None:
    import sqlite3

    before = call(
        "escalate_to_human",
        {"reason": "cancellation_or_refund", "summary": "Cliente quer cancelar o pedido 14."},
        settings,
        session_id="test-session",
    )
    connection = sqlite3.connect(settings.app_db_path)
    row = connection.execute(
        "SELECT reason, summary, session_id FROM tickets WHERE ticket_id = ?",
        (before["ticket_id"],),
    ).fetchone()
    connection.close()
    assert row == ("cancellation_or_refund", "Cliente quer cancelar o pedido 14.", "test-session")


def test_escalation_rejects_an_unknown_reason(settings) -> None:
    result = call(
        "escalate_to_human", {"reason": "whatever", "summary": "algo aconteceu aqui"}, settings
    )
    assert result["error"] == "invalid_arguments"


def test_escalation_requires_a_real_summary(settings) -> None:
    result = call("escalate_to_human", {"reason": "complaint", "summary": "oi"}, settings)
    assert result["error"] == "invalid_arguments"


# -------------------------------------------------------------- AC9-AC10: the dispatcher


def test_unknown_tool(settings) -> None:
    result = call("cancel_order", {}, settings)
    assert result["error"] == "unknown_tool"
    assert "search_products" in result["message"]


def test_invalid_json_string(settings) -> None:
    result = dispatch("search_products", "{not json", settings=settings)
    assert result["error"] == "invalid_arguments"


def test_json_string_arguments_are_accepted(settings) -> None:
    """This is the shape the LLM actually sends."""
    result = dispatch("search_products", '{"category": "Ukuleles", "limit": 2}', settings=settings)
    assert len(result["items"]) == 2


def test_invalid_arguments_explain_themselves(settings) -> None:
    result = call("search_products", {"limit": 999}, settings)
    assert result["error"] == "invalid_arguments"
    assert "limit" in result["message"]


def test_dispatcher_never_raises(settings) -> None:
    """AC9: whatever happens, the agent loop receives a dict."""
    for name, args in [
        ("search_products", {"min_price": "banana"}),
        ("quote_price", {}),
        ("get_order_status", {"order_id": "abc", "email_or_phone": "x"}),
        ("", {}),
    ]:
        result = call(name, args, settings)
        assert isinstance(result, dict) and "error" in result


def test_every_tool_description_says_when_to_use_it(settings) -> None:
    """AC10: the description is the main routing lever we have over the model.

    A description that only says what the tool returns leaves the routing to chance, so each
    one has to name the situation that should trigger it.
    """
    for name, description in tools.TOOL_DESCRIPTIONS.items():
        assert len(description) > 80, name
        assert "Use " in description, f"{name} never says when to use it"


@pytest.mark.parametrize(
    ("name", "guardrail"),
    [
        ("search_products", "acessórios"),  # the store sells instruments only
        ("get_product", "matches"),  # ask which one when ambiguous
        ("list_active_promotions", "Nunca prometa"),  # manual §7.3
        ("quote_price", "NUNCA calcule"),  # manual §7.1
        ("get_order_status", "peça antes de chamar"),  # D8
    ],
)
def test_descriptions_carry_their_guardrail(name, guardrail) -> None:
    assert guardrail in tools.TOOL_DESCRIPTIONS[name]


def test_schemas_are_openai_shaped() -> None:
    schemas = tools.tool_schemas()
    assert {s["function"]["name"] for s in schemas} == set(tools.TOOLS)
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["description"]
        assert schema["function"]["parameters"]["type"] == "object"


def test_order_contact_is_masked_in_logs() -> None:
    """E4 AC6 needs this: the raw e-mail must never reach logs/turns.jsonl."""
    masked = tools.mask_arguments({"order_id": 8, "email_or_phone": ORDER_8_EMAIL})
    assert ORDER_8_EMAIL not in str(masked)
    assert masked["order_id"] == 8


def test_store_database_is_opened_read_only(settings) -> None:
    import sqlite3

    from emporio.db import connect_store

    with connect_store(settings) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("UPDATE products SET price_brl = 1 WHERE product_id = 95")


def test_missing_database_tells_you_how_to_build_it(tmp_path) -> None:
    broken = Settings(
        openai_api_key=None,
        llm_base_url=None,
        llm_model="test",
        llm_temperature=0.0,
        llm_timeout_s=1,
        max_tool_steps=1,
        history_window=1,
        emporio_today=None,
        data_dir=tmp_path / "nothing",
    )
    result = dispatch("search_products", {}, settings=broken)
    assert result["error"] == "database_missing"
    assert "python -m emporio build-data" in result["message"]
