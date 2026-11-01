"""E1-T6: the curated manual is the agent's only source of policy facts, so it is guarded.

These tests are the safety net behind DECISIONS D5: `policies.md` is hand-curated, and a bad
edit would silently remove a rule from the system prompt instead of failing loudly.
"""

from __future__ import annotations

import pytest

from emporio import policies
from emporio.config import PROJECT_ROOT, get_settings

CURATED = PROJECT_ROOT / "data" / "processed" / "policies.md"


@pytest.fixture(scope="module")
def text() -> str:
    return CURATED.read_text(encoding="utf-8")


def test_curated_manual_is_committed() -> None:
    assert CURATED.exists(), "data/processed/policies.md must be in the repository (D5)"


@pytest.mark.parametrize("fact", policies.REQUIRED_FACTS)
def test_every_required_fact_survives_curation(text, fact) -> None:
    assert fact in text


@pytest.mark.parametrize(
    "heading",
    [
        "## 1. Sobre a Empório da Música",
        "## 2. Horário de Funcionamento",
        "## 3. Formas de Pagamento",
        "## 4. Política de Trocas e Devoluções",
        "## 5. Política de Frete e Entregas",
        "## 6. Promoções e Descontos",
        "## 7. Atendimento via WhatsApp",
        "## 8. Garantia",
        "## 9. Privacidade e Proteção de Dados",
        "## 10. Disposições Finais",
    ],
)
def test_all_ten_sections_are_present(text, heading) -> None:
    assert heading in text


@pytest.mark.parametrize(
    ("ambiguity", "needle"),
    [
        ("A1 two phone numbers", "(67) 3321-4500"),
        ("A2 accented e-mail", "contato@emporiodamusica.com.br"),
        ("A3 installment tiers", "até 3x mínimo R$ 50,00"),
        ("A14 shipping boundary", "R$ 500,00 como frete grátis"),
        ("D8 order privacy", "número do pedido E o e-mail ou telefone"),
    ],
)
def test_ambiguity_notes_are_carried_into_the_prompt(text, ambiguity, needle) -> None:
    """E1 AC8: the decisions from 03_POLICY_NOTES must travel with the manual."""
    assert needle in text, ambiguity


def test_notes_are_marked_as_ours_not_the_manual(text) -> None:
    """The agent must not quote our annotations as if the store had written them."""
    assert text.count("> **Nota da equipe") >= 10


def test_accented_email_appears_only_inside_the_explanatory_note(text) -> None:
    """A2: the PDF table writes contato@empóriodamusica.com.br.

    The accented form is quoted once, inside the note that explains why we drop the accent,
    so a reviewer can see what the source said. It must never appear as the usable address.
    """
    accented_lines = [line for line in text.splitlines() if "empóriodamusica.com.br" in line]
    assert len(accented_lines) == 1
    assert accented_lines[0].lstrip().startswith(">"), "only allowed inside a team note"

    company_row = next(line for line in text.splitlines() if line.startswith("| E-mail |"))
    assert "contato@emporiodamusica.com.br" in company_row


def test_load_policies_returns_the_file() -> None:
    assert policies.load_policies(get_settings()).startswith("# Empório da Música")


def test_load_policies_explains_how_to_restore_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EMPORIO_DATA_DIR", str(tmp_path))
    from emporio.config import load_settings

    with pytest.raises(FileNotFoundError, match="E1-T6"):
        policies.load_policies(load_settings())


def test_raw_extraction_is_unusable_as_is() -> None:
    """Documents why D5 exists: pypdf puts one word per line and flattens the tables."""
    raw = policies.extract_raw_text(get_settings().raw_dir / "store_policies.pdf")
    assert "Formas" in raw and "Pagamento" in raw
    # The curated file keeps the heading together; the extraction does not.
    assert "## 3. Formas de Pagamento" not in raw
