from datetime import datetime
from zoneinfo import ZoneInfo

from emporio.settings import DEFAULT_STORE_TIMEZONE
from emporio.store_hours import describe_store_status, format_moment, get_store_status

TIMEZONE = ZoneInfo(DEFAULT_STORE_TIMEZONE)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    # March 2026: the 23rd is a Monday, the 28th a Saturday, the 29th a Sunday.
    return datetime(2026, 3, day, hour, minute, tzinfo=TIMEZONE)


def test_open_during_weekday_hours():
    status = get_store_status(at(23, 10))

    assert status.is_open
    assert status.closes_at == at(23, 18)
    assert status.next_opening is None


def test_open_exactly_at_opening_time():
    assert get_store_status(at(23, 9)).is_open


def test_closed_exactly_at_closing_time():
    status = get_store_status(at(23, 18))

    assert not status.is_open
    assert status.next_opening == at(24, 9)


def test_before_opening_on_a_weekday_reopens_the_same_day():
    status = get_store_status(at(25, 7, 30))

    assert not status.is_open
    assert status.next_opening == at(25, 9)


def test_after_closing_on_friday_reopens_on_saturday():
    status = get_store_status(at(27, 19))

    assert not status.is_open
    assert status.next_opening == at(28, 9)


def test_open_on_saturday_morning_and_closes_at_one():
    status = get_store_status(at(28, 12, 59))

    assert status.is_open
    assert status.closes_at == at(28, 13)


def test_after_saturday_closing_reopens_on_monday():
    status = get_store_status(at(28, 13))

    assert not status.is_open
    assert status.next_opening == at(30, 9)


def test_sunday_reopens_on_monday():
    status = get_store_status(at(29, 11))

    assert not status.is_open
    assert status.next_opening == at(30, 9)


def test_format_moment_uses_portuguese_weekday():
    assert format_moment(at(23, 10)) == "segunda-feira, 23/03/2026, 10:00"
    assert format_moment(at(28, 9)) == "sábado, 28/03/2026, 09:00"


def test_describe_when_open():
    assert describe_store_status(at(23, 10)) == "A loja está aberta e fecha às 18:00."


def test_describe_when_closed_says_when_the_team_is_back():
    assert describe_store_status(at(29, 11)) == (
        "A loja está fechada. A equipe volta segunda-feira, 30/03/2026, 09:00."
    )
