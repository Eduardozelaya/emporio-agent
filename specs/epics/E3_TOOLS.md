---
type: epic
epic: E3
status: done
created: 2026-11-01
estimate: 2.5h
depends_on: [E1, E2]
---

# E3 — Tools (the agent's only access to data)

## Goal
Six tools with strict input schemas and a stable error contract, as specified in
[01_ARCHITECTURE](../01_ARCHITECTURE.md) §5, plus a dispatcher the agent loop can call blindly.

## Why
Tools are where accuracy and privacy are **guaranteed** (the LLM only decides *which* tool to
call). A good tool description is also the main routing lever for the model.

## Scope
`tools.py` (or `tools/` package if it grows): repository queries, Pydantic argument models,
JSON schemas for the LLM, dispatcher, tickets in `app.db`, and a debug CLI to call tools by hand.

## Acceptance criteria
1. WHEN `search_products(category="Violões", max_price=1000)` is called THEN it SHALL return the
   12 available products of 02_DATA_FINDINGS §7, sorted by price, and SHALL NOT include 96 or 113.
   (The default `limit` is **12** so this query is not truncated; `total_found` always reports the
   full count regardless of `limit`.)
2. WHEN `include_unavailable=true` THEN unavailable products SHALL be returned with their `availability`.
3. WHEN a search matches nothing (e.g. category "Instrumentos de Sopro (Metais)") THEN it SHALL
   return `items: []` with `total_found: 0` (not an error).
4. WHEN `get_product(name="Takamine GD20")` is called THEN it SHALL return product 95; WHEN
   `get_product(name="Takamine")` THEN it SHALL return `matches` with 95, 100, 105, 115.
   Matching SHALL be accent- and case-insensitive.
5. WHEN `quote_price` is called THEN it SHALL delegate all math to `pricing.quote` and return its result.
6. WHEN `get_order_status` is called with a contact that does not match the order's customer
   (or the order does not exist) THEN it SHALL return `{"error":"verification_failed"}` and no order data.
7. WHEN the contact matches THEN it SHALL return the order with items, pt-BR status label,
   tracking/estimated delivery when present, cancellation notes, `customer_first_name` (D20) and
   `needs_attention` + `attention_reason` computed with `config.now()` (D17). No other customer
   field SHALL ever leave the tool.
8. WHEN `escalate_to_human` is called THEN it SHALL insert a ticket in `app.db` and return
   `ticket_id` and `expected_response` from `store_hours.expected_response`.
9. WHEN the dispatcher receives an unknown tool, invalid JSON or invalid arguments THEN it SHALL
   return an error dict (never raise) and log the event.
10. WHEN tool schemas are exported THEN each SHALL have a description that states **when to use
    it** and **when not to** (see below).

## Tool descriptions (draft — tune in E6)

- `search_products`: "Busca instrumentos no catálogo com filtros. Use SEMPRE que o cliente pedir
  opções, preços, disponibilidade ou recomendações de produtos. Não use para acessórios (a loja
  não vende). Categorias: Guitarras (elétricas), Baixos, Baterias e Percussão, Teclados e Pianos,
  Violões (acústicos), Instrumentos de Sopro (Madeiras), Instrumentos de Sopro (Metais), Cordas
  Orquestrais, Ukuleles."
- `get_product`: "Detalhes de um produto específico (descrição, especificações, preço, estoque).
  Use quando o cliente citar um modelo. Se vierem várias correspondências, pergunte qual."
- `list_active_promotions`: "Lista as promoções ATIVAS agora. Use quando perguntarem sobre
  promoções, ofertas ou descontos. Nunca prometa promoção que não esteja nesta lista."
- `quote_price`: "Calcula o valor final por forma de pagamento (PIX, débito, crédito com parcelas,
  boleto) e, se o cliente falar em entrega, o frete. Use SEMPRE que precisar informar valor no PIX,
  parcelamento ou total. Nunca calcule de cabeça. Informe `delivery` quando o cliente mencionar
  entrega: `metro_campo_grande` (Campo Grande e região), `other_city` (outras cidades — exige
  cotação) ou `pickup` (retirada na loja, padrão)."
- `get_order_status`: "Consulta um pedido. Exige o número do pedido E o e-mail ou telefone do
  cliente. Se o cliente não informou o contato, peça antes de chamar."
- `escalate_to_human`: "Encaminha para a equipe. Use para reclamações, pedidos de
  cancelamento/troca/reembolso, casos que a política não cobre com clareza, pedidos com dados
  inconsistentes (needs_attention), frete especial ou quando o cliente pedir um atendente."

## Design notes
- `db.py`: `connect(read_only=True)` for `emporio.db` (`file:...?mode=ro`), separate writable `app.db`.
- Always parameterised SQL. Name search: `name_norm LIKE` per token, then `difflib.get_close_matches`
  fallback for typos ("takamini gd 20").
- Pydantic models generate the JSON schema (`model_json_schema()`) → converted to the OpenAI
  `tools=[{"type":"function","function":{...}}]` format in one place.
- Status labels pt-BR: delivered "entregue", shipped "enviado", confirmed "confirmado (em
  separação)", pending "aguardando pagamento/confirmação", cancelled "cancelado".
- Debug CLI: `python -m emporio tool search_products '{"category":"Violões","max_price":1000}'`
  — prints JSON. Great for understanding and for the README.

## Tasks

| ID | Task | Depends | Commit message | Done when |
|---|---|---|---|---|
| E3-T1 | `db.py` read-only/writable connections + `app.db` schema (messages, tickets) | E1 | `feat(db): database access helpers and app schema` | Tests use a temp DB |
| E3-T2 | Argument models + schema export + dispatcher with error contract | T1 | `feat(tools): argument schemas and safe dispatcher` | Tests for unknown tool / bad args |
| E3-T3 | `search_products` + `get_product` (accent-insensitive, fuzzy, ambiguity) | T2 | `feat(tools): catalog search and product details` | AC1–AC4 tests |
| E3-T4 | `list_active_promotions` + `quote_price` | T2, E2 | `feat(tools): promotions and price quote` | AC5 + oracle values |
| E3-T5 | `get_order_status` with verification and attention flags | T2 | `feat(tools): order status with ownership verification` | AC6–AC7 tests (order 8 right/wrong e-mail, order 14) |
| E3-T6 | `escalate_to_human` + tickets | T1, E2 | `feat(tools): human handoff tickets` | AC8 test |
| E3-T7 | `python -m emporio tool <name> '<json>'` debug command | T3–T6 | `feat(cli): debug command to call tools directly` | Manual run prints JSON |

## Independent test
`pytest tests/test_tools.py` green, then try the debug command for each tool by hand.
