"""The store policy manual: PDF -> raw text -> curated Markdown.

DECISIONS D5. The extraction is mechanical and lossy (the PDF tables come out as loose
lines), so `data/processed/policies.md` is reviewed by hand once and committed. The raw dump
is written next to it, gitignored, only so the curated file can be diffed against the source.

DECISIONS D2: no RAG. The manual is eight pages, so the whole curated text goes into the
system prompt as a static prefix, which also makes it cacheable by the provider.
"""

from __future__ import annotations

from pathlib import Path

from emporio.config import Settings, get_settings

#: Facts a reviewer should be able to find in the curated file. Asserted by the tests so a
#: botched re-extraction cannot silently empty the agent's knowledge of the policies.
REQUIRED_FACTS = (
    "Rua 14 de Maio, 3200",
    "(67) 3341-4444",
    "09:00",
    "5% de desconto",
    "12x sem juros",
    "7 (sete) dias corridos",
    "30 (trinta) dias",
    "90 (noventa) dias",
    "R$ 500,00",
    "24 horas úteis",
    "LGPD",
)


def extract_raw_text(pdf_path: Path) -> str:
    """Plain text of every page, in order, as pypdf sees it."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(
        f"--- page {number} ---\n{text}" for number, text in enumerate(pages, start=1)
    )


def dump_raw_text(settings: Settings | None = None) -> Path:
    """Write the mechanical extraction to data/processed/policies_raw.txt (gitignored)."""
    settings = settings or get_settings()
    pdf_path = settings.raw_dir / "store_policies.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing {pdf_path}")
    destination = settings.processed_dir / "policies_raw.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(extract_raw_text(pdf_path), encoding="utf-8")
    return destination


def load_policies(settings: Settings | None = None) -> str:
    """The curated manual that goes into the system prompt."""
    settings = settings or get_settings()
    path = settings.policies_path
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. It is committed to the repository; if it was deleted, "
            "regenerate the raw text with `python -m emporio build-data` and curate it again "
            "(see specs/epics/E1_DATA_LAYER.md, task E1-T6)."
        )
    return path.read_text(encoding="utf-8")
