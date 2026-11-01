import re
from pathlib import Path

import pytest

from emporio.policies import PAGE_HEADER, PolicyError, load_policy_text, normalize_policy_text


def test_extraction_contains_key_sections():
    text = load_policy_text()

    assert "Rua 14 de Maio, 3200" in text
    assert "3.1 Regras de Parcelamento" in text
    assert "8.1 Garantia Legal" in text
    assert "7.2 Fluxo de Atendimento Padrão" in text


def test_extraction_has_no_runs_of_blank_lines():
    assert not re.search(r"\n{3,}", load_policy_text())


def test_extraction_has_no_trailing_spaces_or_wide_padding():
    for line in load_policy_text().splitlines():
        assert line == line.rstrip()
        assert "  " not in line


def test_page_header_and_footers_are_removed():
    text = load_policy_text()

    assert PAGE_HEADER not in text
    assert not re.search(r"^Página \d+$", text, flags=re.MULTILINE)


def test_tables_stay_readable_row_by_row():
    text = load_policy_text()

    assert "Sábado | 09:00 às 13:00" in text
    assert "Domingo e Feriados | Fechado" in text


def test_policy_wording_is_not_edited():
    text = load_policy_text()

    assert "contato@empóriodamusica.com.br" in text
    assert "(67) 3321-4500" in text


def test_normalize_keeps_a_single_blank_line_between_paragraphs():
    raw = f"{PAGE_HEADER}\n\n\n\nTitulo   \n\n\n\n\nTexto\n\n       Página 2"

    assert normalize_policy_text(raw) == "Titulo\n\nTexto"


def test_missing_pdf_fails_with_the_path(tmp_path: Path):
    missing = tmp_path / "missing.pdf"

    with pytest.raises(PolicyError, match="missing.pdf"):
        load_policy_text(missing)
