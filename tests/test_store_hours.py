"""E2 test table for opening hours, holidays (D18) and the escalation SLA (A13)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from emporio import store_hours
from emporio.config import STORE_TZ
from emporio.store_hours import expected_response, next_opening, status


def moment(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=STORE_TZ)


# ------------------------------------------------------------------------------ holidays


@pytest.mark.parametrize(
    ("day", "name"),
    [
        ("2026-01-01", "Confraternização Universal"),
        ("2026-04-21", "Tiradentes"),
        ("2026-05-01", "Dia do Trabalho"),
        ("2026-09-07", "Independência do Brasil"),
        ("2026-11-02", "Finados"),
        ("2026-11-15", "Proclamação da República"),
        ("2026-12-25", "Natal"),
    ],
)
def test_fixed_holidays(day, name) -> None:
    assert store_hours.holiday_name(date.fromisoformat(day)) == name


@pytest.mark.parametrize(
    ("year", "easter"),
    [(2026, "2026-04-05"), (2027, "2027-03-28"), (2024, "2024-03-31")],
)
def test_easter_sunday(year, easter) -> None:
    assert store_hours.easter_sunday(year) == date.fromisoformat(easter)


@pytest.mark.parametrize(
    ("day", "name"),
    [
        ("2026-04-03", "Sexta-feira Santa"),  # Easter 2026-04-05 minus 2
        ("2026-02-16", "Carnaval (segunda)"),
        ("2026-02-17", "Carnaval (terça)"),
        ("2026-06-04", "Corpus Christi"),
    ],
)
def test_easter_derived_holidays(day, name) -> None:
    assert store_hours.holiday_name(date.fromisoformat(day)) == name


def test_an_ordinary_weekday_is_not_a_holiday() -> None:
    assert store_hours.holiday_name(date(2026, 11, 3)) is None
    assert store_hours.is_open_day(date(2026, 11, 3))


# ------------------------------------------------------------------------- open / closed


@pytest.mark.parametrize(
    ("when", "is_open"),
    [
        ("2026-11-03T09:00", True),  # Tuesday, opening minute
        ("2026-11-03T17:59", True),
        ("2026-11-03T18:00", False),  # closing time is exclusive
        ("2026-11-03T08:59", False),
        ("2026-11-07T12:59", True),  # Saturday
        ("2026-11-07T13:00", False),  # Saturday closes at 13:00
        ("2026-11-01T12:20", False),  # Sunday
        ("2026-09-07T10:00", False),  # fixed holiday on a Monday
        ("2026-04-03T10:00", False),  # Good Friday
    ],
)
def test_open_or_closed(when, is_open) -> None:
    assert status(moment(when)).is_open is is_open


def test_sunday_skips_the_finados_monday() -> None:
    """The reason D18 exists: 2026-11-02 is Finados, so the next opening is Tuesday."""
    result = status(moment("2026-11-01T12:20"))
    assert result.is_open is False
    assert result.next_opening == moment("2026-11-03T09:00")
    assert "terça-feira" in result.next_opening_label
    assert "segunda" not in result.next_opening_label


@pytest.mark.parametrize(
    ("when", "expected_opening"),
    [
        ("2026-11-03T18:00", "2026-11-04T09:00"),  # Tuesday evening -> Wednesday
        ("2026-11-07T13:00", "2026-11-09T09:00"),  # Saturday afternoon -> Monday
        ("2026-11-03T06:00", "2026-11-03T09:00"),  # before opening, same day
        ("2026-09-07T10:00", "2026-09-08T09:00"),  # holiday Monday -> Tuesday
        ("2026-12-24T19:00", "2026-12-26T09:00"),  # Christmas Eve evening -> skips the 25th
    ],
)
def test_next_opening(when, expected_opening) -> None:
    assert next_opening(moment(when)) == moment(expected_opening)


def test_open_status_reports_the_closing_time() -> None:
    result = status(moment("2026-11-03T10:00"))
    assert result.is_open
    assert result.closes_at == moment("2026-11-03T18:00")
    assert "18:00" in result.reason
    assert result.next_opening is None


def test_holiday_reason_names_the_holiday() -> None:
    assert "Finados" in status(moment("2026-11-02T10:00")).reason


def test_sunday_reason_says_sunday() -> None:
    assert "domingo" in status(moment("2026-11-01T12:20")).reason


def test_naive_datetime_is_read_as_store_time() -> None:
    naive = datetime(2026, 11, 3, 10, 0)
    assert status(naive).is_open


# ------------------------------------------------------------- escalation response window


def test_response_window_is_the_next_business_day_at_the_same_time() -> None:
    """A13: 24 horas úteis read as one business day."""
    window = expected_response(moment("2026-11-03T10:30"))
    assert window.deadline == moment("2026-11-04T10:30")
    assert "quarta-feira" in window.label


def test_response_window_counts_from_the_next_opening_when_closed() -> None:
    """Sunday 12:20 -> opens Tuesday 09:00 (Finados Monday) -> answer by Wednesday 09:00."""
    window = expected_response(moment("2026-11-01T12:20"))
    assert window.deadline == moment("2026-11-04T09:00")


def test_response_window_is_clamped_to_the_closing_time() -> None:
    """Friday 17:30 would land on Saturday 17:30, when nobody is in the shop."""
    window = expected_response(moment("2026-11-06T17:30"))
    assert window.deadline == moment("2026-11-07T13:00")


def test_response_window_skips_a_holiday() -> None:
    """Friday 2026-04-02 10:00 -> Good Friday is skipped -> Saturday 10:00."""
    window = expected_response(moment("2026-04-02T10:00"))
    assert window.deadline == moment("2026-04-04T10:00")


def test_response_window_never_lands_before_opening() -> None:
    window = expected_response(moment("2026-11-07T09:30"))
    assert window.deadline == moment("2026-11-09T09:30")
    assert store_hours.status(window.deadline).is_open
