from dataclasses import dataclass
from datetime import datetime, time, timedelta

WEEKDAY_NAMES_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
SATURDAY = 5
WEEKDAY_HOURS = (time(9, 0), time(18, 0))
SATURDAY_HOURS = (time(9, 0), time(13, 0))
# Indexed like datetime.weekday(); None means closed all day. There is no holiday
# calendar, so holidays are not modeled.
OPENING_HOURS: tuple[tuple[time, time] | None, ...] = (
    WEEKDAY_HOURS,
    WEEKDAY_HOURS,
    WEEKDAY_HOURS,
    WEEKDAY_HOURS,
    WEEKDAY_HOURS,
    SATURDAY_HOURS,
    None,
)
DAYS_IN_WEEK = 7
DATE_FORMAT = "%d/%m/%Y"
TIME_FORMAT = "%H:%M"


@dataclass(frozen=True)
class StoreStatus:
    is_open: bool
    closes_at: datetime | None
    next_opening: datetime | None


def get_store_status(now: datetime) -> StoreStatus:
    today_hours = OPENING_HOURS[now.weekday()]
    if today_hours is not None:
        opens_at = _at(now, today_hours[0])
        closes_at = _at(now, today_hours[1])
        if opens_at <= now < closes_at:
            return StoreStatus(is_open=True, closes_at=closes_at, next_opening=None)
    return StoreStatus(is_open=False, closes_at=None, next_opening=_next_opening(now))


def _next_opening(now: datetime) -> datetime:
    for days_ahead in range(DAYS_IN_WEEK + 1):
        day = now + timedelta(days=days_ahead)
        hours = OPENING_HOURS[day.weekday()]
        if hours is None:
            continue
        opens_at = _at(day, hours[0])
        if opens_at > now:
            return opens_at
    raise RuntimeError("OPENING_HOURS has no opening time in the week.")


def _at(moment: datetime, clock: time) -> datetime:
    return moment.replace(
        hour=clock.hour, minute=clock.minute, second=0, microsecond=0
    )


def format_moment(moment: datetime) -> str:
    weekday = WEEKDAY_NAMES_PT[moment.weekday()]
    return f"{weekday}, {moment.strftime(DATE_FORMAT)}, {moment.strftime(TIME_FORMAT)}"


def describe_store_status(now: datetime) -> str:
    status = get_store_status(now)
    if status.is_open and status.closes_at is not None:
        return f"A loja está aberta e fecha às {status.closes_at.strftime(TIME_FORMAT)}."
    if status.next_opening is None:
        raise RuntimeError("A closed store status must carry its next opening.")
    return f"A loja está fechada. A equipe volta {format_moment(status.next_opening)}."
