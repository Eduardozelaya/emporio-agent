"""E1 acceptance criteria, checked against the real challenge files.

The oracle is specs/02_DATA_FINDINGS.md: if these tests pass, the document is reproduced.
"""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from emporio import data_loader
from emporio.config import PROJECT_ROOT, Settings
from emporio.data_loader import (
    derive_availability,
    normalize_text,
    parse_payment_method,
)

REAL_RAW = PROJECT_ROOT / "data" / "raw"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    """Build the database once, into a temp dir, from a copy of the real raw files."""
    root = tmp_path_factory.mktemp("emporio")
    shutil.copytree(REAL_RAW, root / "data" / "raw")
    settings = Settings(
        llm_api_key=None,
        llm_base_url=None,
        llm_model="test",
        llm_temperature=0.0,
        llm_timeout_s=1,
        max_tool_steps=1,
        history_window=1,
        emporio_today=None,
        data_dir=root / "data",
    )
    return data_loader.build(settings)


@pytest.fixture(scope="module")
def db(built) -> sqlite3.Connection:
    connection = sqlite3.connect(built.db_path)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def codes_for(built, entity: str, entity_id: int) -> set[str]:
    return {i.code for i in built.issues if i.entity == entity and i.entity_id == str(entity_id)}


# ------------------------------------------------------------------------------ pure helpers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Violões", "violoes"),
        ("TAKAMINE GD20", "takamine gd20"),
        ("Crafter HT-100 Folk Aço Natural", "crafter ht-100 folk aco natural"),
        ("  Ukulele   Soprano ", "ukulele soprano"),
    ],
)
def test_normalize_text(raw, expected) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("status", "stock", "expected"),
    [
        ("active", 12, "available"),
        ("active", 0, "out_of_stock"),  # product 96
        ("discontinued", 13, "discontinued"),  # product 136: status wins over stock
        ("discontinued", 0, "discontinued"),  # product 113
        ("coming_soon", 2, "coming_soon"),  # product 130
    ],
)
def test_derive_availability(status, stock, expected) -> None:
    assert derive_availability(status, stock) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pix", ("pix", 1)),
        ("debit", ("debit", 1)),
        ("boleto", ("boleto", 1)),
        ("credit_3x", ("credit", 3)),
        ("credit_12x", ("credit", 12)),
    ],
)
def test_parse_payment_method(raw, expected) -> None:
    assert parse_payment_method(raw) == expected


# ------------------------------------------------------------------- AC1: tables and counts


def test_row_counts_match_the_raw_files(built) -> None:
    assert built.row_counts == {
        "categories": 9,
        "products": 65,
        "promotions": 25,
        "customers": 50,
        "orders": 20,
        "order_items": 22,
    }


def test_every_table_and_the_view_exist(db) -> None:
    names = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }
    assert {
        "categories",
        "products",
        "promotions",
        "customers",
        "orders",
        "order_items",
        "data_quality_issues",
        "active_promotions",
    } <= names


def test_build_is_idempotent(built) -> None:
    """AC1: a second run must give the same result, not duplicate rows."""
    settings = Settings(
        llm_api_key=None,
        llm_base_url=None,
        llm_model="test",
        llm_temperature=0.0,
        llm_timeout_s=1,
        max_tool_steps=1,
        history_window=1,
        emporio_today=None,
        data_dir=built.db_path.parent.parent,
    )
    again = data_loader.build(settings)
    assert again.row_counts == built.row_counts
    assert [(i.entity, i.entity_id, i.code) for i in again.issues] == [
        (i.entity, i.entity_id, i.code) for i in built.issues
    ]


def test_raw_files_are_never_modified(built) -> None:
    """AC2. The loader only ever reads from data/raw."""
    copied = built.db_path.parent.parent / "raw"
    for original in REAL_RAW.iterdir():
        assert (copied / original.name).read_bytes() == original.read_bytes()


# -------------------------------------------------------------- AC3/AC4: product derivation


@pytest.mark.parametrize(
    ("product_id", "availability"),
    [(96, "out_of_stock"), (113, "discontinued"), (136, "discontinued"), (130, "coming_soon")],
)
def test_availability_of_the_documented_products(db, product_id, availability) -> None:
    row = db.execute(
        "SELECT availability FROM products WHERE product_id = ?", (product_id,)
    ).fetchone()
    assert row["availability"] == availability


def test_specs_are_normalised_json(db) -> None:
    import json

    for row in db.execute("SELECT product_id, specs_json FROM products"):
        spec = json.loads(row["specs_json"])
        assert spec, f"product {row['product_id']} has empty specs"
        assert list(spec) == sorted(spec), "keys must be sorted so the output is stable"


def test_strings_and_electric_only_for_violoes_and_ukuleles(db) -> None:
    """In Guitarras/Baixos the same `strings` key holds a count ('6', '4'), not a material."""
    for row in db.execute("SELECT category_id, strings, electric FROM products"):
        if row["category_id"] in (5, 9):
            assert row["strings"] in ("nylon", "steel")
            assert row["electric"] in (0, 1)
        else:
            assert row["strings"] is None
            assert row["electric"] is None


def test_name_norm_supports_accent_insensitive_search(db) -> None:
    row = db.execute(
        "SELECT name FROM products WHERE name_norm LIKE ?", ("%crafter ht-100%",)
    ).fetchone()
    assert row["name"] == "Crafter HT-100 Folk Aço Natural"


def test_category_product_counts(db) -> None:
    """AC4: categories 6, 7 and 8 are empty."""
    counts = {
        row["category_id"]: row["product_count"]
        for row in db.execute("SELECT category_id, product_count FROM categories")
    }
    assert counts == {1: 5, 2: 4, 3: 3, 4: 3, 5: 35, 6: 0, 7: 0, 8: 0, 9: 15}


# ------------------------------------------------------------ AC5/AC6: customers and orders


def test_duplicate_customer_is_linked_to_the_canonical_record(db) -> None:
    rows = {
        row["customer_id"]: row["duplicate_of"]
        for row in db.execute("SELECT customer_id, duplicate_of FROM customers")
    }
    assert rows[43] == 11
    assert rows[11] is None
    assert sum(1 for value in rows.values() if value is not None) == 1


def test_contacts_are_normalised_for_verification(db) -> None:
    row = db.execute("SELECT * FROM customers WHERE customer_id = 2").fetchone()
    assert row["email_norm"] == "anacarol.ferreira@coldmail.com"
    assert row["phone_digits"] == "67996547821"


def test_payment_method_is_split(db) -> None:
    rows = {
        row["order_id"]: (row["payment_method"], row["installments"])
        for row in db.execute("SELECT order_id, payment_method, installments FROM orders")
    }
    assert rows[1] == ("pix", 1)
    assert rows[2] == ("credit", 6)
    assert rows[3] == ("credit", 12)
    assert all(method in {"pix", "debit", "credit", "boleto"} for method, _ in rows.values())


def test_missing_tracking_becomes_null(db) -> None:
    """Only shipped/delivered orders carry a tracking code."""
    for row in db.execute("SELECT status, tracking_code FROM orders"):
        if row["status"] in ("pending", "confirmed", "cancelled"):
            assert row["tracking_code"] is None
        else:
            assert row["tracking_code"] is not None


# ------------------------------------------------------------------- AC7: quality findings


@pytest.mark.parametrize(
    ("entity", "entity_id", "code"),
    [
        ("order", 3, "total_mismatch"),
        ("order", 20, "total_mismatch"),
        ("order", 9, "installment_rule_violation"),
        ("order", 16, "installment_rule_violation"),
        ("order", 18, "installment_rule_violation"),
        ("order", 1, "pix_without_discount"),
        ("order", 5, "pix_without_discount"),
        ("order", 10, "pix_without_discount"),
        ("order", 13, "pix_without_discount"),
        ("order", 17, "pix_without_discount"),
        ("order", 3, "coming_soon_product_sold"),
        ("order", 14, "coming_soon_product_sold"),
        ("product", 96, "active_without_stock"),
        ("product", 136, "discontinued_with_stock"),
        ("category", 6, "empty_category"),
        ("category", 7, "empty_category"),
        ("category", 8, "empty_category"),
        ("customer", 43, "duplicate_customer"),
    ],
)
def test_every_documented_issue_is_detected(built, entity, entity_id, code) -> None:
    assert code in codes_for(built, entity, entity_id)


def test_no_broken_references(built) -> None:
    assert not [i for i in built.issues if i.code == "broken_reference"]


def test_issues_are_persisted_and_reported(db, built) -> None:
    stored = db.execute("SELECT COUNT(*) AS n FROM data_quality_issues").fetchone()["n"]
    assert stored == len(built.issues)
    report = built.report_path.read_text(encoding="utf-8")
    assert "Data quality report" in report
    assert "Order total does not match its items" in report
    # Every finding must say what the agent does about it, not just that it exists.
    assert "The recorded total is what the customer was charged" in report


# ------------------------------------------------------- AC: active promotions view (D9)


def test_active_promotions_view(db) -> None:
    rows = {
        row["product_id"]: row["discount_percent"]
        for row in db.execute("SELECT * FROM active_promotions")
    }
    assert rows == {90: 18, 94: 8, 121: 20, 127: 10}


def test_inactive_promotion_is_not_offered(db) -> None:
    """The Takamine GD20 carries a 12% 'Oferta Especial' row, but it is inactive."""
    assert db.execute("SELECT * FROM active_promotions WHERE product_id = 95").fetchone() is None


# ------------------------------------------------------------------- E1-T7: data oracle


def test_oracle_violoes_up_to_1000(db) -> None:
    """02_DATA_FINDINGS section 7: exactly 12 products, 96 and 113 excluded."""
    rows = db.execute(
        "SELECT product_id FROM products "
        "WHERE category_id = 5 AND price_brl <= 1000 AND availability = 'available' "
        "ORDER BY price_brl"
    ).fetchall()
    assert [row["product_id"] for row in rows] == [
        83,
        85,
        89,
        88,
        81,
        84,
        87,
        86,
        107,
        82,
        91,
        112,
    ]


def test_oracle_takamine_gd20(db) -> None:
    row = db.execute("SELECT * FROM products WHERE product_id = 95").fetchone()
    assert row["name"] == "Takamine GD20 Dreadnought Natural"
    assert row["price_brl"] == pytest.approx(2199.00)
    assert row["stock_quantity"] == 5
    assert row["availability"] == "available"


def test_oracle_takamine_is_ambiguous(db) -> None:
    rows = db.execute(
        "SELECT product_id FROM products WHERE name_norm LIKE ? ORDER BY product_id",
        ("%takamine%",),
    ).fetchall()
    assert [row["product_id"] for row in rows] == [95, 100, 105, 115]


def test_oracle_order_8(db) -> None:
    row = db.execute("SELECT * FROM orders WHERE order_id = 8").fetchone()
    assert row["customer_id"] == 2
    assert row["status"] == "shipped"
    assert row["tracking_code"] == "BRJL5544332BR"
    assert row["estimated_delivery"] == "2026-02-28"


def test_oracle_empty_wind_and_orchestral_categories(db) -> None:
    """A saxophone question must find a real but empty category."""
    for category_id in (6, 7, 8):
        row = db.execute(
            "SELECT COUNT(*) AS n FROM products WHERE category_id = ?", (category_id,)
        ).fetchone()
        assert row["n"] == 0


def test_product_ids_are_unique_and_in_range(db) -> None:
    rows = db.execute("SELECT product_id FROM products ORDER BY product_id").fetchall()
    ids = [row["product_id"] for row in rows]
    assert len(set(ids)) == len(ids) == 65
    assert min(ids) == 81 and max(ids) == 145


def test_tracking_codes_match_the_manual_format(db) -> None:
    import re

    for row in db.execute("SELECT tracking_code FROM orders WHERE tracking_code IS NOT NULL"):
        assert re.fullmatch(r"BR[A-Z0-9]{9}BR", row["tracking_code"])
