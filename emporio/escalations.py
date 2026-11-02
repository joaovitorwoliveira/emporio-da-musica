import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class EscalationReason(StrEnum):
    COMPLAINT = "complaint"
    CANCELLATION_REQUEST = "cancellation_request"
    POLICY_DOUBT = "policy_doubt"
    LATE_ORDER = "late_order"
    OTHER = "other"


@dataclass(frozen=True)
class EscalationRecord:
    reason: EscalationReason
    summary: str
    order_id: int | None
    recorded_at: str


def parse_reason(value: str) -> EscalationReason:
    try:
        return EscalationReason(value.strip().lower())
    except ValueError as error:
        valid_reasons = ", ".join(reason.value for reason in EscalationReason)
        raise ValueError(
            f"Unknown escalation reason '{value}'. Use one of: {valid_reasons}."
        ) from error


def record_escalation(
    log_path: Path,
    reason: str,
    summary: str,
    order_id: int | None,
    recorded_at: datetime,
) -> EscalationRecord:
    parsed_reason = parse_reason(reason)
    cleaned_summary = summary.strip()
    if not cleaned_summary:
        raise ValueError("The escalation summary must not be empty.")
    if recorded_at.tzinfo is None:
        raise ValueError("recorded_at must be timezone-aware.")
    record = EscalationRecord(
        reason=parsed_reason,
        summary=cleaned_summary,
        order_id=order_id,
        recorded_at=recorded_at.isoformat(),
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    return record
