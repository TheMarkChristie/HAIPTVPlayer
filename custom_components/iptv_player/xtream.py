"""The Xtream Codes player API, asked gently: one request at a time, a second apart.

    player_api.php?username=&password=                          the account (user_info) and the server (server_info)
    player_api.php?...&action=get_live_categories               live groups
    player_api.php?...&action=get_live_streams                  live channels
    xmltv.php?username=&password=                               the provider's guide
    <protocol>://<server>:<port>/live/<user>/<password>/<stream id>.<m3u8|ts>     a channel

The password is in every address, so addresses are only ever built here and used by the relay on the server; none
is logged."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp

from .const import PROVIDER_GAP_SECONDS, PROVIDER_TIMEOUT_SECONDS


class XtreamError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class XtreamAuthError(XtreamError):
    """The provider refused the username and password, or the account is not active."""


class XtreamClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, username: str, password: str, user_agent: str) -> None:
        self._session = session
        self.base = url.strip().rstrip("/")
        self._username = username
        self._password = password
        self.user_agent = user_agent
        self._lock = asyncio.Lock()
        self._last = 0.0
        self.server_info: dict[str, Any] = {}

    def _scrub(self, text: str) -> str:
        return text.replace(self._password, "***").replace(self._username, "***") if self._password else text

    @property
    def _creds(self) -> dict[str, str]:
        return {"username": self._username, "password": self._password}

    async def _get_json(self, **params: str) -> Any:
        url = f"{self.base}/player_api.php?" + urlencode({**self._creds, **params})
        async with self._lock:
            wait = self._last + PROVIDER_GAP_SECONDS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with self._session.get(url, headers={"User-Agent": self.user_agent},
                                             timeout=aiohttp.ClientTimeout(total=PROVIDER_TIMEOUT_SECONDS)) as resp:
                    if resp.status in (401, 403):
                        raise XtreamAuthError(f"the provider refused the login (HTTP {resp.status})", resp.status)
                    if resp.status >= 400:
                        raise XtreamError(f"the provider answered HTTP {resp.status}", resp.status)
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise XtreamError(self._scrub(f"{type(err).__name__}: {err}")) from err
            finally:
                self._last = time.monotonic()

    async def account(self) -> dict[str, Any]:
        """user_info without the username and password, plus server_info (kept for building play addresses)."""
        data = await self._get_json()
        if not isinstance(data, dict) or not isinstance(data.get("user_info"), dict):
            raise XtreamError("not an Xtream Codes panel: player_api.php gave no account")
        user = data["user_info"]
        if str(user.get("auth")) != "1":
            raise XtreamAuthError("the provider refused the login")
        if str(user.get("status") or "Active").lower() not in ("active", ""):
            raise XtreamAuthError(f"the account is {user.get('status')}")
        self.server_info = data.get("server_info") or {}
        return {k: v for k, v in user.items() if k not in ("username", "password")}

    async def live_categories(self) -> list[dict[str, Any]]:
        data = await self._get_json(action="get_live_categories")
        return data if isinstance(data, list) else []

    async def live_streams(self) -> list[dict[str, Any]]:
        data = await self._get_json(action="get_live_streams")
        return data if isinstance(data, list) else []

    def guide_url(self) -> str:
        return f"{self.base}/xmltv.php?" + urlencode(self._creds)

    def stream_base(self) -> str:
        """Where the panel says its streams are (server_info), else the address the API answered on."""
        s = self.server_info
        host = str(s.get("url") or "").strip()
        if not host:
            return self.base
        proto = str(s.get("server_protocol") or "http").lower()
        port = str((s.get("https_port") if proto == "https" else s.get("port")) or "").strip()
        default = "443" if proto == "https" else "80"
        return f"{proto}://{host}" + (f":{port}" if port and port != default else "")

    def stream_url(self, stream_id: str, output: str) -> str:
        ext = "ts" if output == "ts" else "m3u8"
        return f"{self.stream_base()}/live/{quote(self._username)}/{quote(self._password)}/{quote(str(stream_id))}.{ext}"
