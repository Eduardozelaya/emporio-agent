# Ambiguity, price and payment rules

> Four products match 'Takamine', so the agent asks instead of guessing. Every value then comes from `quote_price`: the 5% PIX discount and the installment tiers of manual §3.1 are computed in Python, never by the model.

*Generated from a real run by `scripts/run_examples.py`. Model: `deepseek-flash`. Clock fixed at 2026-11-01T12:20:00 so the conversation is reproducible.*

---

**Cliente:** Quanto custa o Takamine?

**Loja:** Temos quatro Takamine aqui, todos violões: o GD20 Dreadnought (R$ 2.199,00), o GC1CE Elétrico Nylon (R$ 2.499,00), o GC5CE Elétrico Nylon (R$ 3.299,00) e o GN51CE Elétrico Aço (R$ 4.199,00).

Qual deles você quer que eu detalhe?

<details><summary>ferramentas consultadas neste turno</summary>

```json
search_products({"query": "Takamine"})
  -> {"items": [{"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "category": "Violões", "price": 2199.0, "promo": null, "availability": "available", "stock": 5}, {"product_id": 115, "name": "Takamine GC1CE Elétrico Nylon Natural", "category": "Violões", "price": 2499.0, "promo": null, "availability": "available", "stock": 5}, {"product_id": 100, "name": "Takamine GC5CE Elétrico Nylon Natural", "category": "Violões", "price": 3299.0, "promo": null, "availability": "available", "stock": 3}, {"product_id": 105, "name": "Takamine GN51CE Elétrico Aço Natural", "category": "Violões", "pric
```

</details>

**Cliente:** O GD20.

**Loja:** O GD20 é um dreadnought com tampo sólido em cedro, fundo e laterais em sapele, braço de mogno e cordas de aço — timbre quente, ótimo pra fingerstyle. Tem 5 unidades em estoque.

Preço: R$ 2.199,00. No PIX sai por R$ 2.089,05 (5% de desconto), ou em até 12x de R$ 183,25 sem juros no cartão.

Quer que eu veja o frete pra sua região ou prefere retirar na loja?

<details><summary>ferramentas consultadas neste turno</summary>

```json
get_product({"product_id": 95})
  -> {"product": {"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "category": "Violões", "price": 2199.0, "promo": null, "availability": "available", "stock": 5, "description": "Violão dreadnought Takamine com tampo sólido em cedro. Excelente para fingerstyle com timbre quente e definido.", "specs": {"back_sides": "Sapele", "color": "Natural", "electronics": "no", "neck": "Mogno", "scale": "650mm", "strings": "steel", "top": "Cedro Sólido"}, "strings": "steel", "electric": false}}
quote_price({"product_id": 95})
  -> {"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "payment_method": "pix", "by_payment_method": {"pix": 2089.05, "debit": 2199.0, "credit": 2199.0, "boleto": 2199.0}, "quantity": 1, "unit_price": 2199.0, "promo": null, "subtotal": 2199.0, "pix_discount": 109.95, "final_total": 2089.05, "shipping": {"cost": 0.0, "rule": "Retirada na loja, sem frete."}, "grand_total": 2089.05, "installments": null, "max_installments_allowed": 12, "max_installment_value": 183.25, "notes": []}
```

</details>

**Cliente:** Quanto fica no PIX? E em 12x?

**Loja:** No PIX fica R$ 2.089,05 (5% de desconto sobre os R$ 2.199,00).

No cartão em 12x sai 12 parcelas de R$ 183,25 sem juros, totalizando R$ 2.199,00.

Quer que eu inclua o frete?

*(nenhuma ferramenta — respondido a partir do manual de políticas)*

