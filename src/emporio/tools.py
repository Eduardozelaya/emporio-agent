"""The agent's only access to data.

The model never touches the database: it can only *ask* for one of these six tools by name.
That boundary is where accuracy and privacy are enforced in code rather than in a prompt
(DECISIONS D1, D8).

Two conventions hold everywhere:

  * **Errors are data.** A tool returns ``{"error": code, "message": hint}`` and never raises
    into the agent loop, so the model can read the hint and correct itself.
  * **Money is a number with two decimals.** All arithmetic happens in `pricing.py`; tools
    only convert the Decimal to float at this boundary.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from emporio import pricing, store_hours
from emporio.config import Settings, get_settings, now
from emporio.data_loader import digits_only, normalize_text
from emporio.db import DatabaseMissingError, connect_app, connect_store

CategoryName = Literal[
    "Guitarras",
    "Baixos",
    "Baterias e Percussão",
    "Teclados e Pianos",
    "Violões",
    "Instrumentos de Sopro (Madeiras)",
    "Instrumentos de Sopro (Metais)",
    "Cordas Orquestrais",
    "Ukuleles",
]

EscalationReason = Literal[
    "complaint",
    "cancellation_or_refund",
    "exchange_or_return",
    "policy_exception",
    "data_inconsistency",
    "special_shipping_quote",
    "customer_request",
    "other",
]

STATUS_LABELS_PT = {
    "delivered": "entregue",
    "shipped": "enviado",
    "confirmed": "confirmado (em separação)",
    "pending": "aguardando pagamento/confirmação",
    "cancelled": "cancelado",
}

PAYMENT_LABELS_PT = {
    "pix": "PIX",
    "debit": "cartão de débito",
    "credit": "cartão de crédito",
    "boleto": "boleto bancário",
}

#: An order sitting in pending/confirmed for longer than this needs a human (D17).
STALE_OPEN_ORDER_DAYS = 15

#: Below this many digits a phone fragment is not specific enough to prove ownership.
MIN_PHONE_DIGITS = 8


def money(value: Decimal | float | int) -> float:
    """Decimal -> the 2-decimal float the model sees."""
    return float(pricing.round_brl(value))


def error(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


# ============================================================================= argument models


class SearchProductsArgs(BaseModel):
    query: str | None = Field(
        default=None, description="Texto livre: marca, modelo ou tipo. Ex.: 'Yamaha', 'tenor'."
    )
    category: CategoryName | None = Field(default=None, description="Categoria exata.")
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    strings: Literal["nylon", "steel"] | None = Field(
        default=None,
        description="Só para Violões e Ukuleles: nylon (clássico) ou steel (aço/folk).",
    )
    electric: bool | None = Field(
        default=None, description="Só para Violões e Ukuleles: true para eletroacústicos."
    )
    include_unavailable: bool = Field(
        default=False,
        description="true para incluir esgotados, descontinuados e lançamentos futuros.",
    )
    limit: int = Field(default=12, ge=1, le=15)


class GetProductArgs(BaseModel):
    product_id: int | None = None
    name: str | None = Field(default=None, description="Nome ou parte do nome do produto.")

    @model_validator(mode="after")
    def one_is_required(self) -> GetProductArgs:
        if self.product_id is None and not (self.name or "").strip():
            raise ValueError("informe product_id ou name")
        return self


class ListActivePromotionsArgs(BaseModel):
    pass


class QuotePriceArgs(BaseModel):
    product_id: int
    payment_method: Literal["pix", "debit", "credit", "boleto"]
    installments: int | None = Field(default=None, description="Só para crédito, de 1 a 12.")
    quantity: int = Field(default=1, ge=1, le=20)
    delivery: Literal["pickup", "metro_campo_grande", "other_city"] = Field(
        default="pickup",
        description=(
            "Informe quando o cliente falar em entrega. metro_campo_grande = Campo Grande e "
            "região; other_city = outras cidades (precisa de cotação); pickup = retirada."
        ),
    )


class GetOrderStatusArgs(BaseModel):
    order_id: int
    email_or_phone: str = Field(
        description="E-mail ou telefone cadastrado no pedido. Peça ao cliente antes de chamar."
    )


class EscalateToHumanArgs(BaseModel):
    reason: EscalationReason
    summary: str = Field(
        min_length=10, description="Resumo objetivo do caso em pt-BR para a equipe."
    )
    order_id: int | None = None


# ==================================================================================== catalog


def _product_row_to_item(row: sqlite3.Row, promo_percent: int | None) -> dict[str, Any]:
    promo = None
    if promo_percent:
        product = pricing.Product(
            product_id=row["product_id"],
            name=row["name"],
            price_brl=Decimal(str(row["price_brl"])),
            availability=row["availability"],
            promo_percent=promo_percent,
        )
        applied = pricing.promo_for(product)
        if applied:
            promo = {"percent": applied.percent, "price": money(applied.unit_price)}
    return {
        "product_id": row["product_id"],
        "name": row["name"],
        "category": row["category"],
        "price": money(row["price_brl"]),
        "promo": promo,
        "availability": row["availability"],
        "stock": row["stock_quantity"],
    }


_PRODUCT_SELECT = """
SELECT p.*, c.name AS category,
       (SELECT discount_percent FROM active_promotions ap WHERE ap.product_id = p.product_id)
           AS promo_percent
FROM products p
JOIN categories c ON c.category_id = p.category_id
"""


def search_products(args: SearchProductsArgs, settings: Settings) -> dict[str, Any]:
    """Catalogue search with filters; an empty result is data, not an error."""
    where: list[str] = []
    params: list[Any] = []

    if not args.include_unavailable:
        where.append("p.availability = 'available'")
    if args.category:
        where.append("c.name = ?")
        params.append(args.category)
    if args.min_price is not None:
        where.append("p.price_brl >= ?")
        params.append(args.min_price)
    if args.max_price is not None:
        where.append("p.price_brl <= ?")
        params.append(args.max_price)
    if args.strings:
        where.append("p.strings = ?")
        params.append(args.strings)
    if args.electric is not None:
        where.append("p.electric = ?")
        params.append(int(args.electric))
    if args.query:
        # Every word must appear somewhere in the normalised name.
        for token in normalize_text(args.query).split():
            where.append("p.name_norm LIKE ?")
            params.append(f"%{token}%")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"{_PRODUCT_SELECT} {clause} ORDER BY p.price_brl"

    with connect_store(settings) as connection:
        rows = connection.execute(sql, params).fetchall()

    items = [_product_row_to_item(row, row["promo_percent"]) for row in rows[: args.limit]]
    return {
        "items": items,
        # Always the full count, even when `limit` truncated the list, so the agent can say
        # "temos 35 violões" instead of implying the catalogue holds only what it received.
        "total_found": len(rows),
        "filters_applied": args.model_dump(exclude_none=True),
    }


def get_product(args: GetProductArgs, settings: Settings) -> dict[str, Any]:
    """Full detail of one product, or the list of candidates when the name is ambiguous."""
    with connect_store(settings) as connection:
        if args.product_id is not None:
            row = connection.execute(
                f"{_PRODUCT_SELECT} WHERE p.product_id = ?", (args.product_id,)
            ).fetchone()
            if row is None:
                return error("not_found", f"Não existe produto com id {args.product_id}.")
            return {"product": _product_detail(row)}

        rows = _find_by_name(connection, args.name or "")

    if not rows:
        return error(
            "not_found",
            f"Não encontrei nenhum produto com '{args.name}'. "
            "Confirme o modelo com o cliente ou use search_products.",
        )
    if len(rows) == 1:
        return {"product": _product_detail(rows[0])}
    return {
        "matches": [
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "price": money(row["price_brl"]),
                "availability": row["availability"],
            }
            for row in rows
        ],
        "message": "Vários produtos correspondem. Pergunte ao cliente qual deles.",
    }


#: Words customers use that describe the *category*, not the model. "Violão Yamaha" is a
#: perfectly normal way to ask, but no product name contains "violão".
_GENERIC_TOKENS = frozenset(
    {
        "violao", "violoes", "guitarra", "guitarras", "baixo", "baixos", "ukulele", "ukuleles",
        "bateria", "baterias", "teclado", "teclados", "piano", "pianos", "instrumento",
        "instrumentos", "modelo", "de", "da", "do", "o", "a", "um", "uma", "para", "com",
    }
)

#: Average per-token similarity a product needs to be offered as a typo correction.
_FUZZY_THRESHOLD = 0.7


def _token_similarity(query_norm: str, name_norm: str) -> float:
    """How well a query matches a product name, token by token.

    Comparing whole strings fails for real queries: "takamini gd 20" against "takamine gd20
    dreadnought natural" scores low simply because the product name is longer. Scoring each
    query token against its best match in the name keeps the signal.
    """
    query_tokens = query_norm.split()
    name_tokens = name_norm.split()
    if not query_tokens or not name_tokens:
        return 0.0
    total = sum(
        max(difflib.SequenceMatcher(None, token, candidate).ratio() for candidate in name_tokens)
        for token in query_tokens
    )
    return total / len(query_tokens)


def _find_by_name(connection: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """Exact-ish match first, then without category words, then typo tolerance."""
    tokens = normalize_text(name).split()
    if not tokens:
        return []

    def and_search(search_tokens: list[str]) -> list[sqlite3.Row]:
        clause = " AND ".join(["p.name_norm LIKE ?"] * len(search_tokens))
        return connection.execute(
            f"{_PRODUCT_SELECT} WHERE {clause} ORDER BY p.price_brl",
            [f"%{token}%" for token in search_tokens],
        ).fetchall()

    rows = and_search(tokens)
    if rows:
        return rows

    # "violão Yamaha" -> search for "yamaha" and let the caller disambiguate.
    specific = [token for token in tokens if token not in _GENERIC_TOKENS]
    if specific and specific != tokens:
        rows = and_search(specific)
        if rows:
            return rows

    candidates = connection.execute(_PRODUCT_SELECT).fetchall()
    scored = [
        (_token_similarity(" ".join(specific or tokens), row["name_norm"]), row)
        for row in candidates
    ]
    scored = [item for item in scored if item[0] >= _FUZZY_THRESHOLD]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:4]]


def _product_detail(row: sqlite3.Row) -> dict[str, Any]:
    detail = _product_row_to_item(row, row["promo_percent"])
    detail["description"] = row["description"]
    detail["specs"] = json.loads(row["specs_json"])
    if row["strings"] is not None:
        detail["strings"] = row["strings"]
        detail["electric"] = bool(row["electric"])
    return detail


def list_active_promotions(_: ListActivePromotionsArgs, settings: Settings) -> dict[str, Any]:
    """Only promotions flagged active right now (manual 7.3: never promise an expired one)."""
    with connect_store(settings) as connection:
        rows = connection.execute("SELECT * FROM active_promotions ORDER BY product_id").fetchall()

    items = []
    for row in rows:
        product = pricing.Product(
            product_id=row["product_id"],
            name=row["name"],
            price_brl=Decimal(str(row["original_price"])),
            availability=row["availability"],
            promo_percent=row["discount_percent"],
        )
        applied = pricing.promo_for(product)
        items.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "original_price": money(row["original_price"]),
                "percent": row["discount_percent"],
                "promo_price": money(applied.unit_price) if applied else None,
                "availability": row["availability"],
            }
        )
    return {"items": items, "total_found": len(items)}


def quote_price(args: QuotePriceArgs, settings: Settings) -> dict[str, Any]:
    """Final value by payment method and delivery. All math delegated to pricing.quote."""
    with connect_store(settings) as connection:
        row = connection.execute(
            f"{_PRODUCT_SELECT} WHERE p.product_id = ?", (args.product_id,)
        ).fetchone()

    if row is None:
        return error("not_found", f"Não existe produto com id {args.product_id}.")

    product = pricing.Product(
        product_id=row["product_id"],
        name=row["name"],
        price_brl=Decimal(str(row["price_brl"])),
        availability=row["availability"],
        promo_percent=row["promo_percent"],
    )
    try:
        result = pricing.quote(
            product,
            payment_method=args.payment_method,
            installments=args.installments,
            quantity=args.quantity,
            delivery=args.delivery,
        )
    except pricing.PricingError as exc:
        return error(exc.code, exc.message)

    return {
        "product_id": result.product_id,
        "name": result.name,
        "payment_method": result.payment_method,
        "quantity": result.quantity,
        "unit_price": money(result.unit_price),
        "promo": (
            {"percent": result.promo.percent, "unit_price": money(result.promo.unit_price)}
            if result.promo
            else None
        ),
        "subtotal": money(result.subtotal),
        "pix_discount": money(result.pix_discount),
        "final_total": money(result.final_total),
        "shipping": {
            "cost": None if result.shipping.cost is None else money(result.shipping.cost),
            "rule": result.shipping.rule,
        },
        "grand_total": None if result.grand_total is None else money(result.grand_total),
        "installments": (
            {
                "requested": result.installments.requested,
                "allowed": result.installments.allowed,
                "value": money(result.installments.value),
                "reason": result.installments.reason,
            }
            if result.installments
            else None
        ),
        "max_installments_allowed": result.max_installments_allowed,
        "notes": result.notes,
    }


# ===================================================================================== orders


def _contact_matches(given: str, email_norm: str | None, phone_digits: str | None) -> bool:
    """True when the caller proved they own the order (DECISIONS D8)."""
    given = (given or "").strip()
    if not given:
        return False
    if "@" in given:
        return bool(email_norm) and given.lower() == email_norm

    digits = digits_only(given)
    if len(digits) < MIN_PHONE_DIGITS or not phone_digits:
        return False
    # Accept the number with or without the 67 area code, but never a short fragment.
    return digits == phone_digits or phone_digits.endswith(digits)


def _attention(row: sqlite3.Row, has_unreleased_item: bool, today: date) -> tuple[bool, str | None]:
    """Why a human should look at this order before we promise anything (D17)."""
    status = row["status"]
    if status == "shipped" and row["estimated_delivery"]:
        estimated = date.fromisoformat(row["estimated_delivery"])
        if estimated < today:
            overdue = (today - estimated).days
            return True, (
                f"Consta como enviado, mas a previsão de entrega era {estimated:%d/%m/%Y}, "
                f"há {overdue} dias. Não diga que está a caminho: explique e encaminhe."
            )
    if status in ("pending", "confirmed"):
        ordered = date.fromisoformat(row["order_date"])
        age = (today - ordered).days
        if age > STALE_OPEN_ORDER_DAYS:
            return True, (
                f"Parado em '{STATUS_LABELS_PT[status]}' desde {ordered:%d/%m/%Y}, há {age} "
                "dias. Não estime prazo: encaminhe para a equipe."
            )
    if has_unreleased_item and status not in ("cancelled", "delivered"):
        return True, (
            "O pedido contém um produto que ainda não foi lançado. Não prometa entrega: "
            "encaminhe para a equipe."
        )
    return False, None


def get_order_status(args: GetOrderStatusArgs, settings: Settings) -> dict[str, Any]:
    """Order detail, only for someone who proved the order is theirs.

    An unknown order and a wrong contact return the **same** error on purpose: different
    messages would let anyone enumerate the store's orders one id at a time.
    """
    with connect_store(settings) as connection:
        row = connection.execute(
            """
            SELECT o.*, c.name AS customer_name, c.email_norm, c.phone_digits
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            WHERE o.order_id = ?
            """,
            (args.order_id,),
        ).fetchone()

        verification_failed = error(
            "verification_failed",
            "Não consegui confirmar esse pedido com os dados informados. Peça ao cliente o "
            "número do pedido e o e-mail ou telefone usados na compra, sem confirmar nem "
            "negar que o pedido existe.",
        )
        if row is None or not _contact_matches(
            args.email_or_phone, row["email_norm"], row["phone_digits"]
        ):
            return verification_failed

        items = connection.execute(
            """
            SELECT p.name, p.availability, i.quantity
            FROM order_items i JOIN products p ON p.product_id = i.product_id
            WHERE i.order_id = ?
            """,
            (args.order_id,),
        ).fetchall()

    today = now().date()
    has_unreleased = any(item["availability"] == "coming_soon" for item in items)
    needs_attention, reason = _attention(row, has_unreleased, today)

    payment_label = PAYMENT_LABELS_PT.get(row["payment_method"], row["payment_method"])
    if row["payment_method"] == "credit" and row["installments"] > 1:
        payment_label = f"{payment_label} em {row['installments']}x"

    return {
        "order": {
            "order_id": row["order_id"],
            # The only customer field that ever leaves this tool, and only now (D20).
            "customer_first_name": row["customer_name"].split()[0],
            "status": row["status"],
            "status_label_pt": STATUS_LABELS_PT.get(row["status"], row["status"]),
            "order_date": row["order_date"],
            "items": [{"name": item["name"], "quantity": item["quantity"]} for item in items],
            "total": money(row["total_brl"]),
            "payment_method_label": payment_label,
            "tracking_code": row["tracking_code"],
            "estimated_delivery": row["estimated_delivery"],
            "notes": row["notes"],
            "needs_attention": needs_attention,
            "attention_reason": reason,
        }
    }


def escalate_to_human(
    args: EscalateToHumanArgs, settings: Settings, session_id: str | None = None
) -> dict[str, Any]:
    """Open a ticket for the team and tell the customer when they will hear back."""
    created = now()
    with connect_app(settings) as connection:
        cursor = connection.execute(
            "INSERT INTO tickets (session_id, reason, summary, order_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, args.reason, args.summary, args.order_id, created.isoformat()),
        )
        connection.commit()
        ticket_id = cursor.lastrowid

    window = store_hours.expected_response(created)
    return {
        "ticket_id": ticket_id,
        "reason": args.reason,
        "expected_response": window.label,
        "expected_response_at": window.deadline.isoformat(),
        "message": (
            f"Chamado #{ticket_id} registrado. Informe ao cliente que a equipe responde "
            f"{window.label} (manual §7.3: 24 horas úteis)."
        ),
    }


# ================================================================================= dispatcher

TOOL_DESCRIPTIONS = {
    "search_products": (
        "Busca instrumentos no catálogo com filtros. Use SEMPRE que o cliente pedir opções, "
        "preços, disponibilidade ou recomendações de produtos. A loja vende apenas "
        "instrumentos: não use para acessórios (cordas, cabos, palhetas, pedais, "
        "amplificadores, cases). Atenção: 'violão' é acústico (categoria Violões) e 'guitarra' "
        "é elétrica (categoria Guitarras) — são coisas diferentes."
    ),
    "get_product": (
        "Detalhes de um produto específico: descrição, especificações, preço, estoque. Use "
        "quando o cliente citar um modelo. Se a resposta vier com 'matches', pergunte ao "
        "cliente qual deles antes de continuar."
    ),
    "list_active_promotions": (
        "Lista as promoções ATIVAS agora. Use quando perguntarem sobre promoções, ofertas ou "
        "descontos. Nunca prometa uma promoção que não esteja nesta lista, mesmo que o cliente "
        "cite uma campanha do calendário da loja."
    ),
    "quote_price": (
        "Calcula o valor final por forma de pagamento (PIX, débito, crédito com parcelas, "
        "boleto) e, se o cliente falar em entrega, o frete. Use SEMPRE que precisar informar "
        "valor no PIX, parcelamento, total ou frete. NUNCA calcule de cabeça."
    ),
    "get_order_status": (
        "Consulta a situação de um pedido. Use quando o cliente perguntar onde está o pedido, "
        "pedir rastreio ou falar de uma compra que já fez. Exige o número do pedido E o e-mail "
        "ou telefone cadastrados: se o cliente não informou o contato, peça antes de chamar, "
        "não chute. Se a resposta vier com 'needs_attention': true, NÃO diga que o pedido está "
        "a caminho — explique a situação e chame escalate_to_human com reason "
        "'data_inconsistency'."
    ),
    "escalate_to_human": (
        "Encaminha o caso para a equipe e abre um chamado. Use para reclamações, pedidos de "
        "cancelamento, troca ou reembolso, situações que a política não cobre com clareza, "
        "pedidos com dados inconsistentes, cotação de frete para outras cidades, ou quando o "
        "cliente pedir para falar com um atendente."
    ),
}

TOOLS: dict[str, tuple[type[BaseModel], Any]] = {
    "search_products": (SearchProductsArgs, search_products),
    "get_product": (GetProductArgs, get_product),
    "list_active_promotions": (ListActivePromotionsArgs, list_active_promotions),
    "quote_price": (QuotePriceArgs, quote_price),
    "get_order_status": (GetOrderStatusArgs, get_order_status),
    "escalate_to_human": (EscalateToHumanArgs, escalate_to_human),
}


def tool_schemas() -> list[dict[str, Any]]:
    """The `tools=[...]` payload for an OpenAI-compatible chat completion."""
    schemas = []
    for name, (args_model, _) in TOOLS.items():
        schema = args_model.model_json_schema()
        schema.pop("title", None)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": schema,
                },
            }
        )
    return schemas


def _validation_hint(exc: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'argumentos'}: {err['msg']}"
        for err in exc.errors()
    )
    return f"Argumentos inválidos — {problems}"


def dispatch(
    name: str,
    arguments: dict[str, Any] | str | None = None,
    settings: Settings | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Run a tool by name. Never raises: every failure comes back as an error dict."""
    settings = settings or get_settings()

    if name not in TOOLS:
        return error(
            "unknown_tool",
            f"'{name}' não existe. Ferramentas disponíveis: {', '.join(TOOLS)}.",
        )

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return error("invalid_arguments", f"JSON inválido: {exc}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return error("invalid_arguments", "Os argumentos devem ser um objeto JSON.")

    args_model, function = TOOLS[name]
    try:
        parsed = args_model(**arguments)
    except ValidationError as exc:
        return error("invalid_arguments", _validation_hint(exc))

    try:
        if name == "escalate_to_human":
            return function(parsed, settings, session_id)
        return function(parsed, settings)
    except DatabaseMissingError as exc:
        return error("database_missing", str(exc))
    except Exception as exc:  # noqa: BLE001 - the loop must never see an exception
        return error(
            "internal_error",
            f"Falha inesperada em {name}: {type(exc).__name__}. "
            "Peça desculpas ao cliente e ofereça encaminhar para a equipe.",
        )


def mask_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Copy of the arguments with contact details hidden, for logs (E4 AC6)."""
    masked = dict(arguments)
    if "email_or_phone" in masked:
        raw = str(masked["email_or_phone"])
        masked["email_or_phone"] = f"***{raw[-4:]}" if len(raw) > 4 else "***"
    return masked


__all__ = [
    "TOOLS",
    "TOOL_DESCRIPTIONS",
    "dispatch",
    "mask_arguments",
    "tool_schemas",
]
