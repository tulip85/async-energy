"""EKZ tariffs (CHF per kWh) as explicit, editable date periods.

A schedule is a list of periods, each with an inclusive date range and a peak
and an off-peak rate. The bundled default covers 2022-2027; users can replace
it in the integration's options (YAML), so a new tariff needs no release.

Which hours are "peak" is fixed (Mon-Fri 07:00-19:59, Sat 07:00-12:59,
everything else off-peak); public holidays are not treated specially.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import yaml


class MissingTariff(Exception):
    """No tariff period covers a date."""

    def __init__(self, day: date) -> None:
        super().__init__(f"No tariff defined for {day}")
        self.day = day


@dataclass(frozen=True)
class TariffPeriod:
    """Rates valid from `valid_from` to `valid_to`, both inclusive."""

    valid_from: date
    valid_to: date
    peak: float
    off_peak: float


def is_peak(local: datetime) -> bool:
    """Whether a local wall-clock time falls in the peak window."""
    weekday, hour = local.weekday(), local.hour
    if weekday < 5:
        return 6 < hour < 20
    if weekday == 5:
        return 6 < hour < 13
    return False


class TariffSchedule:
    """A validated, non-overlapping list of tariff periods."""

    def __init__(self, periods: Iterable[TariffPeriod]) -> None:
        self.periods = sorted(periods, key=lambda p: p.valid_from)
        if not self.periods:
            raise ValueError("At least one tariff period is required")
        for period in self.periods:
            if period.valid_to < period.valid_from:
                raise ValueError(
                    f"Period starting {period.valid_from} ends before it starts"
                )
            if period.peak < 0 or period.off_peak < 0:
                raise ValueError(f"Period {period.valid_from}: rates must be >= 0")
        for earlier, later in zip(self.periods, self.periods[1:]):
            if later.valid_from <= earlier.valid_to:
                raise ValueError(
                    f"Periods starting {earlier.valid_from} and "
                    f"{later.valid_from} overlap"
                )

    def period_for(self, day: date) -> TariffPeriod:
        """Period covering `day`. Raises MissingTariff if there is none."""
        for period in self.periods:
            if period.valid_from <= day <= period.valid_to:
                return period
        raise MissingTariff(day)

    def rate(self, local: datetime) -> float:
        """Rate (CHF/kWh) at a local wall-clock time."""
        period = self.period_for(local.date())
        return period.peak if is_peak(local) else period.off_peak

    def to_yaml(self) -> str:
        """Render as the YAML text shown in the options form."""
        return "".join(
            f"- from: {p.valid_from}\n  to: {p.valid_to}\n"
            f"  peak: {p.peak}\n  off_peak: {p.off_peak}\n"
            for p in self.periods
        )


def _as_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"'{field}' must be a date (YYYY-MM-DD), not a date and time")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as err:
        raise ValueError(f"'{field}': {value!r} is not a date (YYYY-MM-DD)") from err


def _as_rate(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{field}': {value!r} is not a number")
    return float(value)


def parse_schedule(text: str) -> TariffSchedule:
    """Parse the YAML from the options form. Raises ValueError with a reason."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise ValueError(f"Not valid YAML: {err}") from err
    if not isinstance(data, list) or not data:
        raise ValueError("Expected a list of periods")

    periods = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Entry {index} is not a mapping")
        missing = {"from", "to", "peak", "off_peak"} - set(item)
        if missing:
            raise ValueError(f"Entry {index} lacks: {', '.join(sorted(missing))}")
        periods.append(
            TariffPeriod(
                _as_date(item["from"], "from"),
                _as_date(item["to"], "to"),
                _as_rate(item["peak"], "peak"),
                _as_rate(item["off_peak"], "off_peak"),
            )
        )
    return TariffSchedule(periods)


def _default_periods() -> list[TariffPeriod]:
    """The tariffs of the old service: annual to 2025, quarterly from 2026."""
    annual = {  # year: (peak, off_peak)
        2022: (0.1849, 0.1386),
        2023: (0.2366, 0.1935),
        2024: (0.3277, 0.3115),
        2025: (0.2815, 0.2685),
    }
    quarterly = {  # year: {quarter: (peak, off_peak)}
        2026: {1: (0.2593, 0.2593), 2: (0.2128, 0.2128),
               3: (0.2128, 0.2128), 4: (0.2593, 0.2593)},
        2027: {1: (0.2526, 0.2526), 2: (0.2072, 0.2072),
               3: (0.2072, 0.2072), 4: (0.2526, 0.2526)},
    }
    periods = [
        TariffPeriod(date(y, 1, 1), date(y, 12, 31), peak, off)
        for y, (peak, off) in annual.items()
    ]
    for year, quarters in quarterly.items():
        for quarter, (peak, off) in quarters.items():
            start = date(year, 3 * quarter - 2, 1)
            end = (
                date(year + 1, 1, 1) if quarter == 4 else date(year, 3 * quarter + 1, 1)
            ) - timedelta(days=1)
            periods.append(TariffPeriod(start, end, peak, off))
    return periods


DEFAULT_SCHEDULE = TariffSchedule(_default_periods())
