"""Opening hours, holidays and the escalation response window.

Manual section 2: Mon-Fri 09:00-18:00, Sat 09:00-13:00, Sundays and holidays closed.
The manual names holidays as a closing rule but lists none, so DECISIONS D18 puts a minimal
Brazilian calendar here. Without it the agent would tell a customer the store opens on
2026-11-02 (Finados) — the exact date the reproducible examples use.

All times are in America/Campo_Grande and come from `config.now()`, never `datetime.now()`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache

from pydantic import BaseModel

from emporio.config import STORE_TZ

#: weekday() -> (opening, closing), or None when the store is closed that day.
OPENING_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(9), time(18)),  # Monday
    1: (time(9), time(18)),
    2: (time(9), time(18)),
    3: (time(9), time(18)),
    4: (time(9), time(18)),  # Friday
    5: (time(9), time(13)),  # Saturday
    6: None,  # Sunday
}

WEEKDAYS_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

#: (month, day, name) — national holidays with a fixed date.
FIXED_HOLIDAYS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Consciência Negra"),  # national since Lei 14.759/2023
    (12, 25, "Natal"),
)

#: (offset in days from Easter Sunday, name). Carnival and Corpus Christi are "ponto
#: facultativo" rather than statutory holidays, but retail in Campo Grande closes on them,
#: so the store treats them as closed. Municipal and state dates are NOT covered — that is
#: the remaining limitation documented in the README.
EASTER_HOLIDAYS: tuple[tuple[int, str], ...] = (
    (-48, "Carnaval (segunda)"),
    (-47, "Carnaval (terça)"),
    (-2, "Sexta-feira Santa"),
    (60, "Corpus Christi"),
)


def easter_sunday(year: int) -> date:
    """Easter Sunday by the anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    the_l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * the_l) // 451
    month, day = divmod(h + the_l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=16)
def holidays(year: int) -> dict[date, str]:
    """Dates the store is closed for, mapped to the holiday name."""
    result = {date(year, month, day): name for month, day, name in FIXED_HOLIDAYS}
    easter = easter_sunday(year)
    for offset, name in EASTER_HOLIDAYS:
        result[easter + timedelta(days=offset)] = name
    return result


def holiday_name(day: date) -> str | None:
    return holidays(day.year).get(day)


def is_open_day(day: date) -> bool:
    """True when the store opens at all on this date (not Sunday, not a holiday)."""
    return OPENING_HOURS[day.weekday()] is not None and holiday_name(day) is None


def hours_for(day: date) -> tuple[time, time] | None:
    """Opening and closing time for a date, or None when closed."""
    return OPENING_HOURS[day.weekday()] if is_open_day(day) else None


def _label(moment: datetime) -> str:
    """'terça-feira (03/11) às 09:00'."""
    return f"{WEEKDAYS_PT[moment.weekday()]} ({moment:%d/%m}) às {moment:%H:%M}"


def next_opening(moment: datetime) -> datetime:
    """The next instant the store is open, at or after `moment`."""
    today_hours = hours_for(moment.date())
    if today_hours and moment.time() < today_hours[0]:
        return datetime.combine(moment.date(), today_hours[0], tzinfo=moment.tzinfo)

    day = moment.date() + timedelta(days=1)
    # 10 days is far more than any run of consecutive closed days in this calendar.
    for _ in range(10):
        day_hours = hours_for(day)
        if day_hours:
            return datetime.combine(day, day_hours[0], tzinfo=moment.tzinfo)
        day += timedelta(days=1)
    raise RuntimeError(f"no opening found within 10 days of {moment.date()}")


class StoreStatus(BaseModel):
    is_open: bool
    #: Why, in pt-BR, ready to be dropped into the prompt's dynamic suffix.
    reason: str
    closes_at: datetime | None
    next_opening: datetime | None
    next_opening_label: str | None


def status(moment: datetime) -> StoreStatus:
    """Whether the store is open at `moment`, and when it opens again if not."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=STORE_TZ)
    day_hours = hours_for(moment.date())

    if day_hours and day_hours[0] <= moment.time() < day_hours[1]:
        closes_at = datetime.combine(moment.date(), day_hours[1], tzinfo=moment.tzinfo)
        return StoreStatus(
            is_open=True,
            reason=f"Aberto agora, até às {day_hours[1]:%H:%M}.",
            closes_at=closes_at,
            next_opening=None,
            next_opening_label=None,
        )

    opens = next_opening(moment)
    name = holiday_name(moment.date())
    if name:
        reason = f"Fechado hoje: {name} (feriado)."
    elif moment.weekday() == 6:
        reason = "Fechado: domingo."
    elif day_hours and moment.time() < day_hours[0]:
        reason = f"Ainda fechado: abrimos às {day_hours[0]:%H:%M}."
    else:
        reason = "Fechado: fora do horário de atendimento."

    return StoreStatus(
        is_open=False,
        reason=f"{reason} Reabrimos {_label(opens)}.",
        closes_at=None,
        next_opening=opens,
        next_opening_label=_label(opens),
    )


class ResponseWindow(BaseModel):
    deadline: datetime
    #: pt-BR sentence the agent repeats to the customer when it opens a ticket.
    label: str


def expected_response(moment: datetime) -> ResponseWindow:
    """Deadline for a complaint reply: "24 horas úteis" (manual 7.3, POLICY_NOTES A13).

    Read as one business day: the same time on the next day the store opens, counted from now
    when open or from the next opening when closed. The time is clamped to that day's closing
    time, so a Friday 17:30 ticket is promised for Saturday 13:00 rather than a moment when
    nobody is in the shop.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=STORE_TZ)
    base = moment if status(moment).is_open else next_opening(moment)

    day = base.date() + timedelta(days=1)
    for _ in range(10):
        day_hours = hours_for(day)
        if day_hours:
            opens, closes = day_hours
            target_time = min(max(base.time(), opens), closes)
            deadline = datetime.combine(day, target_time, tzinfo=base.tzinfo)
            return ResponseWindow(deadline=deadline, label=f"até {_label(deadline)}")
        day += timedelta(days=1)
    raise RuntimeError(f"no business day found within 10 days of {base.date()}")
