"""EKZ tariff tables (CHF per kWh), ported unchanged from the old service."""
from __future__ import annotations

from datetime import datetime

# Annual tariffs (2022-2025)
PEAK_TARIFF = {2022: 0.1849, 2023: 0.2366, 2024: 0.3277, 2025: 0.2815}
OFF_PEAK_TARIFF = {2022: 0.1386, 2023: 0.1935, 2024: 0.3115, 2025: 0.2685}

# Quarterly tariffs from 2026 onwards: {year: {quarter: tariff}}
# Quarter 1 = Jan-Mar, Quarter 2 = Apr-Jun, Quarter 3 = Jul-Sep, Quarter 4 = Oct-Dec
PEAK_TARIFF_QUARTERLY = {
    2026: {1: 0.2593, 2: 0.2128, 3: 0.2128, 4: 0.2593},
    2027: {1: 0.2526, 2: 0.2072, 3: 0.2072, 4: 0.2526},
}
OFF_PEAK_TARIFF_QUARTERLY = {
    2026: {1: 0.2593, 2: 0.2128, 3: 0.2128, 4: 0.2593},
    2027: {1: 0.2526, 2: 0.2072, 3: 0.2072, 4: 0.2526},
}


class MissingTariff(KeyError):
    """Raised when no tariff is known for a year."""


def _quarter(month: int) -> int:
    return (month - 1) // 3 + 1


def _lookup(annual: dict, quarterly: dict, year: int, month: int, kind: str) -> float:
    if year >= 2026:
        if year not in quarterly:
            raise MissingTariff(f"No {kind} tariff for {year}; add it to tariffs.py")
        return quarterly[year][_quarter(month)]
    if year not in annual:
        raise MissingTariff(f"No {kind} tariff for {year}; add it to tariffs.py")
    return annual[year]


def get_peak_tariff(year: int, month: int) -> float:
    """Peak tariff for a year and month."""
    return _lookup(PEAK_TARIFF, PEAK_TARIFF_QUARTERLY, year, month, "peak")


def get_off_peak_tariff(year: int, month: int) -> float:
    """Off-peak tariff for a year and month."""
    return _lookup(
        OFF_PEAK_TARIFF, OFF_PEAK_TARIFF_QUARTERLY, year, month, "off-peak"
    )


def get_tariff(local: datetime) -> float:
    """Tariff valid at a local (naive or aware) wall-clock time."""
    weekday, hour = local.weekday(), local.hour
    if weekday < 5:
        peak = 6 < hour < 20
    elif weekday == 5:
        peak = 6 < hour < 13
    else:
        peak = False
    if peak:
        return get_peak_tariff(local.year, local.month)
    return get_off_peak_tariff(local.year, local.month)
