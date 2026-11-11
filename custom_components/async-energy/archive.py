"""Optional archive of the raw EKZ responses: local folder or Google Drive.

Archiving never raises: a failure is logged and the statistics import goes on.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
import json
import logging
import os
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ArchiveFn
from .const import (
    ARCHIVE_DRIVE,
    ARCHIVE_LOCAL,
    CONF_ARCHIVE,
    CONF_DRIVE_CREDENTIALS,
    CONF_DRIVE_FOLDER_ID,
    RAW_DATA_DIR,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _signed_jwt(info: Mapping[str, Any]) -> str:
    """Build the service-account JWT assertion (RS256, via `cryptography`)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": info["client_email"],
        "scope": _DRIVE_SCOPE,
        "aud": _TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        _b64(json.dumps(header).encode()) + b"." + _b64(json.dumps(claims).encode())
    )
    key = serialization.load_pem_private_key(info["private_key"].encode(), None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _b64(signature)).decode()


def _write_local(directory: str, name: str, text: str) -> None:
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, name)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, target)


class _DriveUploader:
    """Create-or-update JSON files in one Drive folder."""

    def __init__(self, hass: HomeAssistant, credentials_json: str, folder_id: str):
        self._hass = hass
        self._info = json.loads(credentials_json)
        self._folder = folder_id
        self._token: str | None = None
        self._expires = 0.0

    async def _auth(self, session: aiohttp.ClientSession) -> dict[str, str]:
        if self._token is None or time.time() > self._expires - 60:
            assertion = await self._hass.async_add_executor_job(
                _signed_jwt, self._info
            )
            async with session.post(
                _TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            ) as response:
                response.raise_for_status()
                body = await response.json()
            self._token = body["access_token"]
            self._expires = time.time() + int(body.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}"}

    async def upload(self, name: str, text: str) -> None:
        session = async_get_clientsession(self._hass)
        headers = await self._auth(session)
        query = f"name = '{name}' and '{self._folder}' in parents and trashed = false"
        async with session.get(
            _FILES_URL, params={"q": query, "fields": "files(id)"}, headers=headers
        ) as response:
            response.raise_for_status()
            files = (await response.json())["files"]
        if len(files) > 1:
            raise ValueError(f"{len(files)} files named {name} in the Drive folder")

        if files:
            async with session.patch(
                f"{_UPLOAD_URL}/{files[0]['id']}",
                params={"uploadType": "media"},
                data=text.encode(),
                headers={**headers, "Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
            return

        boundary = "ekzarchiveboundary"
        meta = json.dumps({"name": name, "parents": [self._folder]})
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n"
            f"{text}\r\n--{boundary}--"
        )
        async with session.post(
            _UPLOAD_URL,
            params={"uploadType": "multipart"},
            data=body.encode(),
            headers={
                **headers,
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
        ) as response:
            response.raise_for_status()


def build_archive(hass: HomeAssistant, options: Mapping[str, Any]) -> ArchiveFn | None:
    """Return the archive callback for the configured target, or None."""
    target = options.get(CONF_ARCHIVE)

    if target == ARCHIVE_LOCAL:
        directory = hass.config.path(RAW_DATA_DIR)

        async def _local(name: str, text: str) -> None:
            try:
                await hass.async_add_executor_job(_write_local, directory, name, text)
            except OSError as err:
                _LOGGER.warning("Could not archive %s locally: %s", name, err)

        return _local

    if target == ARCHIVE_DRIVE:
        try:
            uploader = _DriveUploader(
                hass,
                options[CONF_DRIVE_CREDENTIALS],
                options[CONF_DRIVE_FOLDER_ID],
            )
        except (KeyError, ValueError) as err:
            _LOGGER.warning("Google Drive archive is misconfigured: %s", err)
            return None

        async def _drive(name: str, text: str) -> None:
            try:
                await uploader.upload(name, text)
            except (
                aiohttp.ClientError,
                TimeoutError,
                KeyError,
                ValueError,
            ) as err:
                _LOGGER.warning("Could not archive %s to Google Drive: %s", name, err)

        return _drive

    return None
