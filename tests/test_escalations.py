import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import BaseTool

from emporio.escalations import EscalationReason, record_escalation
from emporio.prompt import build_system_prompt
from emporio.settings import DEFAULT_STORE_TIMEZONE, Settings
from emporio.tools import build_tools

COMPLAINT_SUMMARY = "Cliente relata tampo riscado no violão e falta de resposta no WhatsApp."


def read_log(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def escalate(tools: dict[str, BaseTool], **arguments: object) -> object:
    return tools["escalate_to_team"].invoke(arguments)


def test_record_is_appended_as_one_well_formed_line(
    escalation_log: Path, reference_date: datetime
):
    record_escalation(
        escalation_log, "late_order", "Pedido enviado está atrasado.", 8, reference_date
    )

    (line,) = escalation_log.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record == {
        "reason": "late_order",
        "summary": "Pedido enviado está atrasado.",
        "order_id": 8,
        "recorded_at": "2026-03-23T10:00:00-04:00",
    }
    assert datetime.fromisoformat(record["recorded_at"]) == reference_date


def test_log_keeps_accents_unescaped(escalation_log: Path, reference_date: datetime):
    record_escalation(escalation_log, "complaint", COMPLAINT_SUMMARY, None, reference_date)

    assert "violão" in escalation_log.read_text(encoding="utf-8")


def test_unknown_reason_is_rejected_and_nothing_is_written(
    escalation_log: Path, reference_date: datetime
):
    with pytest.raises(ValueError, match="Unknown escalation reason 'refund'"):
        record_escalation(escalation_log, "refund", "Resumo.", None, reference_date)

    assert not escalation_log.exists()


@pytest.mark.parametrize("summary", ["", "   ", "\n"])
def test_blank_summary_is_rejected(
    escalation_log: Path, reference_date: datetime, summary: str
):
    with pytest.raises(ValueError, match="summary must not be empty"):
        record_escalation(escalation_log, "other", summary, None, reference_date)

    assert not escalation_log.exists()


def test_naive_timestamp_is_rejected(escalation_log: Path):
    with pytest.raises(ValueError, match="timezone-aware"):
        record_escalation(escalation_log, "other", "Resumo.", None, datetime(2026, 3, 23, 10))


def test_tool_records_a_complaint_without_order(
    tools: dict[str, BaseTool], escalation_log: Path
):
    escalate(tools, reason="complaint", summary=COMPLAINT_SUMMARY)

    (record,) = read_log(escalation_log)
    assert record["reason"] == "complaint"
    assert record["summary"] == COMPLAINT_SUMMARY
    assert record["order_id"] is None
    assert record["recorded_at"] == "2026-03-23T10:00:00-04:00"


def test_tool_records_the_order_number(tools: dict[str, BaseTool], escalation_log: Path):
    escalate(tools, reason="late_order", summary="Pedido atrasado.", order_id=8)

    (record,) = read_log(escalation_log)
    assert record["order_id"] == 8


def test_two_calls_produce_two_lines(tools: dict[str, BaseTool], escalation_log: Path):
    escalate(tools, reason="complaint", summary="Primeiro caso.")
    escalate(tools, reason="policy_doubt", summary="Segundo caso.")

    assert [record["summary"] for record in read_log(escalation_log)] == [
        "Primeiro caso.",
        "Segundo caso.",
    ]


def test_tool_creates_the_log_directory(tools: dict[str, BaseTool], escalation_log: Path):
    assert not escalation_log.parent.exists()

    escalate(tools, reason="other", summary="Caso fora do comum.")

    assert escalation_log.exists()


def test_tool_rejects_unknown_reason_with_the_valid_ones(
    tools: dict[str, BaseTool], escalation_log: Path
):
    result = escalate(tools, reason="refund", summary="Resumo.")

    assert isinstance(result, str)
    for reason in EscalationReason:
        assert reason.value in result
    assert not escalation_log.exists()


def test_tool_rejects_blank_summary(tools: dict[str, BaseTool], escalation_log: Path):
    result = escalate(tools, reason="other", summary="  ")

    assert isinstance(result, str)
    assert "summary" in result
    assert not escalation_log.exists()


def test_payload_says_the_store_is_open_on_the_default_date(tools: dict[str, BaseTool]):
    result = escalate(tools, reason="complaint", summary=COMPLAINT_SUMMARY)

    assert result == {
        "recorded": True,
        "reason": "complaint",
        "response_time": "24 horas úteis",
        "store_is_open": True,
        "team_back_at": None,
        "store_status": "A loja está aberta e fecha às 18:00.",
    }


def test_payload_says_when_the_team_is_back_on_a_sunday(
    store_db: Path, escalation_log: Path
):
    sunday = datetime(2026, 3, 29, 11, 0, tzinfo=ZoneInfo(DEFAULT_STORE_TIMEZONE))
    sunday_tools = {t.name: t for t in build_tools(store_db, escalation_log, sunday)}

    result = escalate(sunday_tools, reason="complaint", summary=COMPLAINT_SUMMARY)

    assert isinstance(result, dict)
    assert result["store_is_open"] is False
    assert result["team_back_at"] == "segunda-feira, 30/03/2026, 09:00"
    assert read_log(escalation_log)[0]["recorded_at"] == "2026-03-29T11:00:00-04:00"


def test_prompt_has_the_escalation_rules(reference_date: datetime):
    settings = Settings(
        llm_base_url="http://localhost",
        llm_api_key="test-key",
        llm_model="test-model",
        reference_date=reference_date,
        store_timezone=ZoneInfo(DEFAULT_STORE_TIMEZONE),
        store_db_path=Path("unused.db"),
        conversations_db_path=Path("unused-conversations.db"),
        escalation_log_path=Path("unused.jsonl"),
    )

    prompt = build_system_prompt(settings)

    for anchor in (
        "Encaminhamento para a equipe:",
        "escalate_to_team",
        "complaint",
        "cancellation_request",
        "policy_doubt",
        "late_order",
        "24 horas úteis",
        "recorded true",
        "team_back_at",
    ):
        assert anchor in prompt
