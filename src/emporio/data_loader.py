"""Raw CSV files -> clean SQLite, with a data quality report.

Every transform is a pure DataFrame -> DataFrame function so it can be tested on its own;
only `build()` touches the filesystem. Files in `data/raw/` are never modified (E1 AC2).

Time-dependent flags (stale orders) are deliberately NOT computed here: "stale" depends on
when you ask, so it belongs at query time (DECISIONS D17).
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from emporio import pricing
from emporio.config import Settings, get_settings

RAW_FILES = {
    "categories": ["category_id", "name", "description"],
    "products": [
        "product_id",
        "price_brl",
        "name",
        "category_id",
        "description",
        "stock_quantity",
        "status",
        "specs",
        "created_at",
    ],
    "promotions": ["promotion_id", "product_id", "discount_percent", "description", "is_active"],
    "customers": ["customer_id", "name", "phone", "email", "city"],
    "orders": [
        "order_id",
        "customer_id",
        "order_date",
        "status",
        "total_brl",
        "payment_method",
        "tracking_code",
        "estimated_delivery",
        "notes",
    ],
    "order_items": ["order_id", "quantity", "product_id"],
}

#: Categories whose `specs.strings` is a material (nylon/steel). In Guitarras and Baixos the
#: same key holds a string *count* ("6", "4"), so deriving a material there would be wrong.
STRINGED_ACOUSTIC_CATEGORIES = {5, 9}

PT_STATUS_LABELS = {
    "delivered": "entregue",
    "shipped": "enviado",
    "confirmed": "confirmado (em separação)",
    "pending": "aguardando pagamento/confirmação",
    "cancelled": "cancelado",
}


@dataclass(frozen=True)
class Issue:
    """One data quality finding, stored in the database and listed in the report."""

    entity: str
    entity_id: str
    code: str
    detail: str


@dataclass
class BuildResult:
    db_path: Path
    report_path: Path
    row_counts: dict[str, int]
    issues: list[Issue]


def normalize_text(value: str) -> str:
    """Lowercase and strip accents, for accent-insensitive search (E3)."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip().lower()


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


# --------------------------------------------------------------------------------- reading


def read_raw(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Read every CSV as text, so nothing is silently coerced, and check the columns."""
    tables: dict[str, pd.DataFrame] = {}
    for name, columns in RAW_FILES.items():
        path = raw_dir / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path}. Copy the challenge files to {raw_dir} "
                "with the names listed in specs/02_DATA_FINDINGS.md section 1."
            )
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        tables[name] = frame
    return tables


def check_referential_integrity(tables: dict[str, pd.DataFrame]) -> list[Issue]:
    """Foreign keys must resolve. Today they all do; the check guards against a new drop."""
    issues: list[Issue] = []
    product_ids = set(tables["products"]["product_id"])
    category_ids = set(tables["categories"]["category_id"])
    customer_ids = set(tables["customers"]["customer_id"])
    order_ids = set(tables["orders"]["order_id"])

    for table, column, known, entity in (
        ("products", "category_id", category_ids, "product"),
        ("promotions", "product_id", product_ids, "promotion"),
        ("order_items", "product_id", product_ids, "order_item"),
        ("order_items", "order_id", order_ids, "order_item"),
        ("orders", "customer_id", customer_ids, "order"),
    ):
        frame = tables[table]
        orphans = frame[~frame[column].isin(known)]
        for _, row in orphans.iterrows():
            issues.append(
                Issue(
                    entity=entity,
                    entity_id=str(row.iloc[0]),
                    code="broken_reference",
                    detail=f"{table}.{column} = {row[column]} does not exist",
                )
            )
    return issues


# ------------------------------------------------------------------------------ transforms


def derive_availability(status: str, stock_quantity: int) -> str:
    """Status wins over stock (02_DATA_FINDINGS section 3).

    Product 136 is discontinued with 13 units: still discontinued, we do not sell it.
    Product 96 is active with 0 units: out of stock, the price is real but we cannot deliver.
    """
    if status == "discontinued":
        return "discontinued"
    if status == "coming_soon":
        return "coming_soon"
    if stock_quantity <= 0:
        return "out_of_stock"
    return "available"


def transform_products(products: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["product_id"] = products["product_id"].astype(int)
    out["name"] = products["name"].str.strip()
    out["name_norm"] = out["name"].map(normalize_text)
    out["category_id"] = products["category_id"].astype(int)
    out["price_brl"] = products["price_brl"].astype(float)
    out["stock_quantity"] = products["stock_quantity"].astype(int)
    out["status"] = products["status"].str.strip()
    out["availability"] = [
        derive_availability(status, stock)
        for status, stock in zip(out["status"], out["stock_quantity"], strict=True)
    ]
    out["description"] = products["description"].str.strip()

    parsed = products["specs"].map(json.loads)
    # Re-serialise with sorted keys: the raw file mixes compact and spaced JSON.
    out["specs_json"] = parsed.map(
        lambda spec: json.dumps(spec, ensure_ascii=False, sort_keys=True)
    )
    out["strings"] = [
        spec.get("strings") if category in STRINGED_ACOUSTIC_CATEGORIES else None
        for spec, category in zip(parsed, out["category_id"], strict=True)
    ]
    out["electric"] = [
        int(spec.get("electronics") == "yes") if category in STRINGED_ACOUSTIC_CATEGORIES else None
        for spec, category in zip(parsed, out["category_id"], strict=True)
    ]
    out["created_at"] = products["created_at"].str.strip()
    return out.sort_values("product_id").reset_index(drop=True)


def transform_categories(categories: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["category_id"] = categories["category_id"].astype(int)
    out["name"] = categories["name"].str.strip()
    out["description"] = categories["description"].str.strip()
    counts = products["category_id"].value_counts()
    out["product_count"] = out["category_id"].map(counts).fillna(0).astype(int)
    return out.sort_values("category_id").reset_index(drop=True)


def transform_promotions(promotions: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["promotion_id"] = promotions["promotion_id"].astype(int)
    out["product_id"] = promotions["product_id"].astype(int)
    out["discount_percent"] = promotions["discount_percent"].astype(int)
    out["description"] = promotions["description"].str.strip()
    out["is_active"] = promotions["is_active"].astype(int)
    return out.sort_values("promotion_id").reset_index(drop=True)


def transform_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Normalise contacts for order verification and flag the duplicated person."""
    out = pd.DataFrame()
    out["customer_id"] = customers["customer_id"].astype(int)
    out["name"] = customers["name"].str.strip()
    out["phone"] = customers["phone"].str.strip()
    out["phone_digits"] = out["phone"].map(digits_only)
    out["email"] = customers["email"].str.strip()
    out["email_norm"] = out["email"].str.strip().str.lower()
    out["city"] = customers["city"].str.strip()

    # Same person registered twice (11 and 43 share an e-mail). The lowest id is the canonical
    # record; verification by e-mail keeps working for both.
    first_seen: dict[str, int] = {}
    duplicate_of: list[int | None] = []
    for customer_id, email in zip(out["customer_id"], out["email_norm"], strict=True):
        canonical = first_seen.get(email)
        if canonical is None:
            first_seen[email] = customer_id
            duplicate_of.append(None)
        else:
            duplicate_of.append(canonical)
    out["duplicate_of"] = duplicate_of
    return out.sort_values("customer_id").reset_index(drop=True)


def parse_payment_method(raw: str) -> tuple[str, int]:
    """'credit_12x' -> ('credit', 12); 'pix' -> ('pix', 1)."""
    match = re.fullmatch(r"credit_(\d+)x", raw.strip())
    if match:
        return "credit", int(match.group(1))
    return raw.strip(), 1


def transform_orders(orders: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["order_id"] = orders["order_id"].astype(int)
    out["customer_id"] = orders["customer_id"].astype(int)
    out["order_date"] = orders["order_date"].str.strip()
    out["status"] = orders["status"].str.strip()
    out["total_brl"] = orders["total_brl"].astype(float)
    parsed = orders["payment_method"].map(parse_payment_method)
    out["payment_method"] = [method for method, _ in parsed]
    out["installments"] = [n for _, n in parsed]
    # Empty strings become NULL so tools can simply check for None.
    for column in ("tracking_code", "estimated_delivery", "notes"):
        out[column] = orders[column].str.strip().replace("", None)
    return out.sort_values("order_id").reset_index(drop=True)


def transform_order_items(order_items: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["order_id"] = order_items["order_id"].astype(int)
    out["product_id"] = order_items["product_id"].astype(int)
    out["quantity"] = order_items["quantity"].astype(int)
    return out.sort_values(["order_id", "product_id"]).reset_index(drop=True)


# ------------------------------------------------------------------------- quality checks


def detect_issues(
    products: pd.DataFrame,
    categories: pd.DataFrame,
    promotions: pd.DataFrame,
    customers: pd.DataFrame,
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
) -> list[Issue]:
    """Everything in 02_DATA_FINDINGS that a human should know about, found automatically."""
    issues: list[Issue] = []
    price_by_id = dict(zip(products["product_id"], products["price_brl"], strict=True))
    name_by_id = dict(zip(products["product_id"], products["name"], strict=True))
    availability_by_id = dict(zip(products["product_id"], products["availability"], strict=True))

    # Catalogue ------------------------------------------------------------------
    for _, product in products.iterrows():
        if product["status"] == "active" and product["stock_quantity"] <= 0:
            issues.append(
                Issue(
                    "product",
                    str(product["product_id"]),
                    "active_without_stock",
                    f"{product['name']} is active with stock 0; sold as out_of_stock",
                )
            )
        if product["status"] == "discontinued" and product["stock_quantity"] > 0:
            issues.append(
                Issue(
                    "product",
                    str(product["product_id"]),
                    "discontinued_with_stock",
                    f"{product['name']} is discontinued but still holds "
                    f"{product['stock_quantity']} units",
                )
            )

    for _, category in categories.iterrows():
        if category["product_count"] == 0:
            issues.append(
                Issue(
                    "category",
                    str(category["category_id"]),
                    "empty_category",
                    f"{category['name']} has no products; the agent must say we do not carry "
                    "them instead of inventing one",
                )
            )

    # Promotions -----------------------------------------------------------------
    active = promotions[promotions["is_active"] == 1]
    for product_id, group in active.groupby("product_id"):
        if len(group) > 1:
            issues.append(
                Issue(
                    "product",
                    str(product_id),
                    "multiple_active_promotions",
                    f"{len(group)} active promotions; the highest discount wins (D9)",
                )
            )
    for _, promotion in promotions.iterrows():
        availability = availability_by_id.get(promotion["product_id"])
        if availability in ("discontinued", "coming_soon"):
            issues.append(
                Issue(
                    "promotion",
                    str(promotion["promotion_id"]),
                    "promotion_on_non_sellable_product",
                    f"product {promotion['product_id']} is {availability} "
                    f"(promotion is {'active' if promotion['is_active'] else 'inactive'})",
                )
            )

    # Customers ------------------------------------------------------------------
    for _, customer in customers[customers["duplicate_of"].notna()].iterrows():
        issues.append(
            Issue(
                "customer",
                str(customer["customer_id"]),
                "duplicate_customer",
                f"shares e-mail {customer['email']} with customer "
                f"{int(customer['duplicate_of'])}",
            )
        )

    # Orders ---------------------------------------------------------------------
    items_by_order = order_items.groupby("order_id")
    for _, order in orders.iterrows():
        order_id = order["order_id"]
        try:
            items = items_by_order.get_group(order_id)
        except KeyError:
            issues.append(Issue("order", str(order_id), "order_without_items", "no order_items"))
            continue

        items_total = sum(
            Decimal(str(price_by_id[row["product_id"]])) * row["quantity"]
            for _, row in items.iterrows()
        )
        recorded = Decimal(str(order["total_brl"]))
        if pricing.round_brl(items_total) != pricing.round_brl(recorded):
            issues.append(
                Issue(
                    "order",
                    str(order_id),
                    "total_mismatch",
                    f"recorded {pricing.format_brl(recorded)} but items add up to "
                    f"{pricing.format_brl(items_total)}; the recorded total is kept (D16)",
                )
            )

        if order["payment_method"] == "credit" and order["installments"] > 1:
            n = int(order["installments"])
            value = pricing.installment_value(recorded, n)
            minimum = pricing.min_installment_value(n)
            if value < minimum:
                issues.append(
                    Issue(
                        "order",
                        str(order_id),
                        "installment_rule_violation",
                        f"{n}x of {pricing.format_brl(value)} is below the "
                        f"{pricing.format_brl(minimum)} minimum for {n}x (manual §3.1)",
                    )
                )

        if order["payment_method"] == "pix":
            expected = pricing.round_brl(items_total * Decimal("0.95"))
            if pricing.round_brl(recorded) == pricing.round_brl(items_total) != expected:
                issues.append(
                    Issue(
                        "order",
                        str(order_id),
                        "pix_without_discount",
                        f"paid by PIX at list price {pricing.format_brl(recorded)}; with the 5% "
                        f"of manual §3 it would be {pricing.format_brl(expected)}",
                    )
                )

        for _, row in items.iterrows():
            if availability_by_id.get(row["product_id"]) == "coming_soon":
                issues.append(
                    Issue(
                        "order",
                        str(order_id),
                        "coming_soon_product_sold",
                        f"contains {name_by_id[row['product_id']]} "
                        f"({row['product_id']}), which is not released yet",
                    )
                )

    return sorted(issues, key=lambda issue: (issue.entity, issue.code, int(issue.entity_id)))


# ----------------------------------------------------------------------------- persistence

SCHEMA = """
DROP VIEW IF EXISTS active_promotions;
DROP TABLE IF EXISTS data_quality_issues;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS promotions;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;

CREATE TABLE categories (
    category_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    product_count INTEGER NOT NULL
);

CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    name_norm      TEXT NOT NULL,
    category_id    INTEGER NOT NULL REFERENCES categories(category_id),
    price_brl      REAL NOT NULL,
    stock_quantity INTEGER NOT NULL,
    status         TEXT NOT NULL,
    availability   TEXT NOT NULL,
    description    TEXT,
    specs_json     TEXT NOT NULL,
    strings        TEXT,
    electric       INTEGER,
    created_at     TEXT
);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_name_norm ON products(name_norm);

CREATE TABLE promotions (
    promotion_id     INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent INTEGER NOT NULL,
    description      TEXT,
    is_active        INTEGER NOT NULL
);

CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT,
    phone_digits TEXT,
    email        TEXT,
    email_norm   TEXT,
    city         TEXT,
    duplicate_of INTEGER REFERENCES customers(customer_id)
);
CREATE INDEX idx_customers_email_norm ON customers(email_norm);
CREATE INDEX idx_customers_phone_digits ON customers(phone_digits);

CREATE TABLE orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date         TEXT NOT NULL,
    status             TEXT NOT NULL,
    total_brl          REAL NOT NULL,
    payment_method     TEXT NOT NULL,
    installments       INTEGER NOT NULL,
    tracking_code      TEXT,
    estimated_delivery TEXT,
    notes              TEXT
);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL
);
CREATE INDEX idx_order_items_order ON order_items(order_id);

CREATE TABLE data_quality_issues (
    entity    TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    code      TEXT NOT NULL,
    detail    TEXT NOT NULL
);

-- One row per product (DECISIONS D9): only is_active = 1 counts, the highest discount wins,
-- and a promotion is never offered on something we cannot sell.
CREATE VIEW active_promotions AS
SELECT p.product_id,
       p.name,
       p.price_brl   AS original_price,
       MAX(pr.discount_percent) AS discount_percent,
       p.availability
FROM promotions pr
JOIN products p ON p.product_id = pr.product_id
WHERE pr.is_active = 1
  AND p.availability NOT IN ('discontinued', 'coming_soon')
GROUP BY p.product_id, p.name, p.price_brl, p.availability;
"""


def write_db(path: Path, frames: dict[str, pd.DataFrame], issues: list[Issue]) -> None:
    """Rebuild the database from scratch, so a second run gives exactly the same file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        for table in ("categories", "products", "promotions", "customers", "orders", "order_items"):
            frames[table].to_sql(table, connection, if_exists="append", index=False)
        connection.executemany(
            "INSERT INTO data_quality_issues (entity, entity_id, code, detail) VALUES (?, ?, ?, ?)",
            [(i.entity, i.entity_id, i.code, i.detail) for i in issues],
        )
        connection.commit()


ISSUE_HEADINGS = {
    "total_mismatch": "Order total does not match its items",
    "installment_rule_violation": "Installment below the manual's minimum",
    "pix_without_discount": "PIX order charged at list price",
    "coming_soon_product_sold": "Product sold before release",
    "active_without_stock": "Active product with no stock",
    "discontinued_with_stock": "Discontinued product still in stock",
    "empty_category": "Category with no products",
    "duplicate_customer": "Same person registered twice",
    "promotion_on_non_sellable_product": "Promotion on a product we cannot sell",
    "multiple_active_promotions": "More than one active promotion",
    "broken_reference": "Broken foreign key",
    "order_without_items": "Order with no items",
}

#: How the agent must behave because of each finding — the reason the report exists.
ISSUE_CONSEQUENCES = {
    "total_mismatch": "The recorded total is what the customer was charged, so it is shown as "
    "is and never recomputed (D16).",
    "installment_rule_violation": "Historical only. New quotes go through `pricing.quote`, "
    "which enforces the tiers.",
    "pix_without_discount": "Assumption: the stored totals are pre-discount, or the discount "
    "was applied at payment time. Flagged, not corrected.",
    "coming_soon_product_sold": "The agent must not promise delivery for these orders; it "
    "explains and escalates (`data_inconsistency`).",
    "active_without_stock": "Derived as `out_of_stock`: the price is real, the delivery is not "
    "promised (manual §7.3).",
    "discontinued_with_stock": "Status wins over stock: we do not sell it, we offer "
    "equivalents (manual §7.3).",
    "empty_category": "The agent says we do not carry them right now, and never invents a "
    "product (manual §7.1).",
    "duplicate_customer": "Verification by e-mail still works for both records.",
    "promotion_on_non_sellable_product": "Never applied (D9).",
    "multiple_active_promotions": "The highest discount wins (D9).",
}


def render_report(row_counts: dict[str, int], issues: list[Issue]) -> str:
    """Markdown report committed to the repo as evidence of the data treatment."""
    lines = [
        "# Data quality report",
        "",
        "> Generated by `python -m emporio build-data`. Do not edit by hand.",
        "> Cross-check against [`specs/02_DATA_FINDINGS.md`](../specs/02_DATA_FINDINGS.md).",
        "",
        "## Rows loaded",
        "",
        "| Table | Rows |",
        "|---|---|",
    ]
    lines += [f"| `{table}` | {count} |" for table, count in row_counts.items()]
    lines += ["", f"## Findings ({len(issues)})", ""]

    if not issues:
        lines.append("No issues found.")
        return "\n".join(lines) + "\n"

    by_code: dict[str, list[Issue]] = {}
    for issue in issues:
        by_code.setdefault(issue.code, []).append(issue)

    lines += ["| Finding | Count |", "|---|---|"]
    for code, found in sorted(by_code.items(), key=lambda item: -len(item[1])):
        lines.append(f"| {ISSUE_HEADINGS.get(code, code)} | {len(found)} |")
    lines.append("")

    for code, found in sorted(by_code.items(), key=lambda item: -len(item[1])):
        lines += [f"### {ISSUE_HEADINGS.get(code, code)} (`{code}`)", ""]
        consequence = ISSUE_CONSEQUENCES.get(code)
        if consequence:
            lines += [f"**How the agent handles it:** {consequence}", ""]
        lines += ["| Entity | Id | Detail |", "|---|---|---|"]
        lines += [f"| {i.entity} | {i.entity_id} | {i.detail} |" for i in found]
        lines.append("")

    return "\n".join(lines) + "\n"


def build(settings: Settings | None = None) -> BuildResult:
    """Read `data/raw`, clean it, write `emporio.db` and `reports/data_quality.md`."""
    settings = settings or get_settings()
    raw = read_raw(settings.raw_dir)

    products = transform_products(raw["products"])
    frames = {
        "categories": transform_categories(raw["categories"], products),
        "products": products,
        "promotions": transform_promotions(raw["promotions"]),
        "customers": transform_customers(raw["customers"]),
        "orders": transform_orders(raw["orders"]),
        "order_items": transform_order_items(raw["order_items"]),
    }

    issues = check_referential_integrity(raw) + detect_issues(
        products=frames["products"],
        categories=frames["categories"],
        promotions=frames["promotions"],
        customers=frames["customers"],
        orders=frames["orders"],
        order_items=frames["order_items"],
    )

    write_db(settings.db_path, frames, issues)

    row_counts = {name: len(frame) for name, frame in frames.items()}
    report_path = settings.data_dir.parent / "reports" / "data_quality.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(row_counts, issues), encoding="utf-8")

    return BuildResult(
        db_path=settings.db_path,
        report_path=report_path,
        row_counts=row_counts,
        issues=issues,
    )
