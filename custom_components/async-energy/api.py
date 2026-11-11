"""Browserless client for the my.ekz.ch portal.

Logs in through the portal's Keycloak form with plain HTTP (no JavaScript is
needed), then reads the consumption JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import json
import logging
from typing import Any

import aiohttp
from yarl import URL

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.util.dt as dt_util

from .const import (
    CONSUMPTION_URL,
    DOMAIN,
    DETAILED_KEYS,
    LOCAL_TIMEZONE,
    LOGIN_URL,
    PORTAL_HOST,
    REQUEST_TIMEOUT,
    TYPE_15MIN,
    TYPE_DAILY,
)
from .tariffs import DEFAULT_SCHEDULE, MissingTariff, TariffSchedule

_LOGGER = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class ApiError(Exception):
    """The portal could not be reached or returned unusable data."""


class InvalidAuth(ApiError):
    """The portal rejected the username / password."""


@dataclass(frozen=True)
class HourlyReading:
    """Consumption and cost of one hour."""

    start: datetime  # UTC, on the hour
    kwh: float
    chf: float


@dataclass(frozen=True)
class FetchResult:
    """Readings plus the days skipped because no tariff covers them."""

    readings: list[HourlyReading]
    missing_tariff_days: list[date]


class _LoginFormParser(HTMLParser):
    """Find the form that contains a username/password field."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._current = {"action": attributes.get("action"), "fields": {}}
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None and attributes.get("name"):
            # Like a browser: unchecked checkboxes / radios are not submitted.
            if attributes.get("type") in ("checkbox", "radio") and (
                "checked" not in attributes
            ):
                return
            self._current["fields"][attributes["name"]] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current = None


def _find_login_form(html: str) -> dict[str, Any] | None:
    parser = _LoginFormParser()
    parser.feed(html)
    for form in parser.forms:
        if "username" in form["fields"] or "password" in form["fields"]:
            return form
    return None


async def _async_login(
    session: aiohttp.ClientSession, username: str, password: str
) -> None:
    """Log in; the session's cookie jar then carries the portal session."""
    async with session.get(LOGIN_URL) as response:
        response.raise_for_status()
        html = await response.text()
        page_url = response.url

    form = _find_login_form(html)
    if form is None or not form["action"]:
        raise ApiError("Login page has no login form; the portal may have changed")

    data = {**form["fields"], "username": username, "password": password}
    async with session.post(page_url.join(URL(form["action"])), data=data) as response:
        html = await response.text()
        final_url = response.url

    if final_url.host != PORTAL_HOST:
        if _find_login_form(html) is not None:
            raise InvalidAuth("Username or password rejected")
        raise ApiError(
            "Login did not return to the portal (extra verification required?)"
        )


async def _async_get_day(
    session: aiohttp.ClientSession, installation_id: str, data_type: str, day: date
) -> tuple[str, dict[str, Any]]:
    """Return (raw text, parsed JSON) for one day and data type."""
    params = {
        "installationId": installation_id,
        "type": data_type,
        "from": day.isoformat(),
        "to": day.isoformat(),
    }
    async with session.get(CONSUMPTION_URL, params=params) as response:
        response.raise_for_status()
        text = await response.text()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as err:
        raise ApiError(f"Response for {day} is not JSON") from err
    if not isinstance(parsed, dict):
        raise ApiError(f"Response for {day} has an unexpected shape")
    return text, parsed


# Called with (file name, raw JSON text) for every response worth archiving.
ArchiveFn = Callable[[str, str], Awaitable[None]]


def hourly_from_detailed(
    day: date, detailed: dict[str, Any], schedule: TariffSchedule = DEFAULT_SCHEDULE
) -> list[HourlyReading]:
    """Sum the 15 minute values of one day into priced hourly readings."""
    zone = dt_util.get_time_zone(LOCAL_TIMEZONE)
    values = detailed["seriesHt"]["values"] + detailed["seriesNt"]["values"]

    per_hour: dict[int, float] = {}
    for item in values:
        hour = int(item["time"].split(":")[0])
        per_hour[hour] = per_hour.get(hour, 0.0) + float(item["value"])

    readings = []
    for hour, kwh in sorted(per_hour.items()):
        local = datetime(day.year, day.month, day.day, hour, tzinfo=zone)
        readings.append(
            HourlyReading(
                start=dt_util.as_utc(local),
                kwh=kwh,
                chf=kwh * schedule.rate(local),
            )
        )
    return readings


async def async_fetch_hourly(
    hass: HomeAssistant,
    username: str,
    password: str,
    installation_id: str,
    days: int,
    archive: ArchiveFn | None = None,
    schedule: TariffSchedule = DEFAULT_SCHEDULE,
) -> FetchResult:
    """Log in and return hourly readings for the `days` days ending yesterday.

    If `archive` is given it receives the raw responses (15 minute and daily).
    Days that no tariff period covers are skipped and reported in the result.
    Raises InvalidAuth for bad credentials and ApiError for anything else.
    """
    session, lock = _get_session(hass)
    # One run at a time: the session's cookie jar holds the portal login.
    async with lock:
        session.cookie_jar.clear()
        return await _async_fetch_hourly(
            hass, session, username, password, installation_id, days, archive, schedule
        )


def _get_session(hass: HomeAssistant) -> tuple[aiohttp.ClientSession, asyncio.Lock]:
    """Return the shared session (own cookie jar, closed by Home Assistant)."""
    key = f"{DOMAIN}_ekz_session"
    if key not in hass.data:
        hass.data[key] = (
            async_create_clientsession(
                hass,
                cookie_jar=aiohttp.CookieJar(),
                headers={"User-Agent": _USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ),
            asyncio.Lock(),
        )
    return hass.data[key]


async def _async_fetch_hourly(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    username: str,
    password: str,
    installation_id: str,
    days: int,
    archive: ArchiveFn | None,
    schedule: TariffSchedule,
) -> FetchResult:
    missing_tariff_days: list[date] = []
    readings: list[HourlyReading] = []
    failures = 0
    today = dt_util.now(dt_util.get_time_zone(LOCAL_TIMEZONE)).date()
    try:
        await _async_login(session, username, password)

        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)
            try:
                text, detailed = await _async_get_day(
                    session, installation_id, TYPE_15MIN, day
                )
                if any(key not in detailed for key in DETAILED_KEYS):
                    raise ApiError(f"Response for {day} lacks {DETAILED_KEYS}")
                day_readings = hourly_from_detailed(day, detailed, schedule)
                if archive is not None:
                    await archive(f"{day}-detailed.json", text)
                    daily_text, _ = await _async_get_day(
                        session, installation_id, TYPE_DAILY, day
                    )
                    await archive(f"{day}-daily.json", daily_text)
            except InvalidAuth:
                raise
            except MissingTariff:
                missing_tariff_days.append(day)
                continue
            except (
                ApiError,
                aiohttp.ClientError,
                TimeoutError,
                KeyError,
                TypeError,
                ValueError,
            ) as err:
                failures += 1
                _LOGGER.warning("Skipping %s: %s", day, err)
                continue
            readings.extend(day_readings)
    except InvalidAuth:
        raise
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ApiError(f"Error talking to my.ekz.ch: {err}") from err

    if failures and not readings and not missing_tariff_days:
        raise ApiError("No day could be retrieved")
    return FetchResult(readings, missing_tariff_days)
