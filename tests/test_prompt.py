from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from emporio.prompt import POLICIES_HEADING, build_system_prompt
from emporio.settings import DEFAULT_STORE_TIMEZONE, Settings

SECTION_HEADINGS = (
    "# PERSONA E TOM",
    "# REGRAS",
    "# INFORMAÇÕES DA LOJA",
    "# DATA E HORÁRIO ATUAIS",
    POLICIES_HEADING,
    "# ESCLARECIMENTOS",
)


@pytest.fixture
def settings(reference_date: datetime) -> Settings:
    return Settings(
        llm_base_url="http://localhost",
        llm_api_key="test-key",
        llm_model="test-model",
        reference_date=reference_date,
        store_timezone=ZoneInfo(DEFAULT_STORE_TIMEZONE),
        store_db_path=Path("unused.db"),
        escalation_log_path=Path("unused.jsonl"),
    )


def test_prompt_has_every_section_in_order(settings: Settings):
    prompt = build_system_prompt(settings)

    positions = [prompt.index(heading) for heading in SECTION_HEADINGS]

    assert positions == sorted(positions)


def test_prompt_states_reference_date_and_open_status(settings: Settings):
    prompt = build_system_prompt(settings)

    assert (
        "Agora é segunda-feira, 23/03/2026, 10:00 (horário de Campo Grande). "
        "A loja está aberta e fecha às 18:00."
    ) in prompt


def test_prompt_says_when_the_team_is_back_when_closed(settings: Settings):
    sunday_morning = datetime(2026, 3, 29, 11, 0, tzinfo=ZoneInfo(DEFAULT_STORE_TIMEZONE))
    sunday = replace(settings, reference_date=sunday_morning)

    prompt = build_system_prompt(sunday)

    assert "Agora é domingo, 29/03/2026, 11:00" in prompt
    assert "A loja está fechada. A equipe volta segunda-feira, 30/03/2026, 09:00." in prompt


def test_prompt_includes_the_policy_text_whole(settings: Settings):
    prompt = build_system_prompt(settings)

    assert "3.1 Regras de Parcelamento" in prompt
    assert "8.1 Garantia Legal" in prompt
    assert "Rua 14 de Maio, 3200" in prompt


def test_clarifications_come_after_the_policy_text(settings: Settings):
    prompt = build_system_prompt(settings)
    clarifications = prompt.index("# ESCLARECIMENTOS")

    assert clarifications > prompt.index("8.1 Garantia Legal")
    assert clarifications > prompt.index("(67) 3321-4500")
    assert "seção 3.1 valem mais que a tabela-resumo" in prompt[clarifications:]
    assert "R$ 50,00" in prompt[clarifications:]
    assert "R$ 80,00" in prompt[clarifications:]
    assert "contato@emporiodamusica.com.br" in prompt[clarifications:]
    assert "(67) 3341-4444" in prompt[clarifications:]
    assert "fonte da verdade" in prompt[clarifications:]
    assert "nomes de lojas parceiras" in prompt[clarifications:]


def test_prompt_keeps_price_and_order_rules(settings: Settings):
    prompt = build_system_prompt(settings)

    assert "Nunca informe preços sem consultar a ferramenta find_product" in prompt
    assert "O valor que o cliente paga é o final_price" in prompt
    assert "Nunca revele dados de pedido sem que a ferramenta get_order devolva verified true" in prompt
    assert "A verificação vale só para o pedido consultado" in prompt


def test_prompt_covers_the_three_kinds_of_no(settings: Settings):
    prompt = build_system_prompt(settings)

    assert "Nunca diga que a loja não vende esse tipo de instrumento" in prompt
    assert "Nunca invente nomes de lojas parceiras" in prompt
    assert "Assuntos sem relação com a loja" in prompt


def test_prompt_has_the_after_sales_rules(settings: Settings):
    prompt = build_system_prompt(settings)

    assert "Devolução, troca e garantia de um pedido" in prompt
    assert "campo after_sales devolvido pela get_order" in prompt
    assert "Nunca calcule datas, prazos ou dias por conta própria" in prompt
    assert "Se um direito trouxer o campo note, repasse o conteúdo da nota" in prompt
    assert "em até 10 dias úteis" in prompt
    assert "o frete de devolução é por conta da loja" in prompt
    assert "a loja pode intermediar o processo" in prompt
    assert "itens não elegíveis para troca da seção 4.4" in prompt
    assert "Você não abre pedido de devolução, troca ou garantia" in prompt
