"""Set up IPTV Player: a provider login (Xtream Codes: server, username, password) or an M3U playlist address.
Options: the guide sources, how far ahead the guide goes, the TVs for Play on TV, and the request headers."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import m3u
from .const import (
    CONF_GUIDE_HOUR, CONF_GUIDE_HOURS, CONF_GUIDE_URLS, CONF_KIND, CONF_NAME, CONF_OUTPUT, CONF_PASSWORD, CONF_PLAYERS,
    CONF_PROVIDER_GUIDE, CONF_URL, CONF_USER_AGENT, CONF_USERNAME, DEFAULT_GUIDE_HOUR, DEFAULT_GUIDE_HOURS,
    DEFAULT_OUTPUT, DEFAULT_USER_AGENT, DOMAIN, FREE_UK_GUIDE, KIND_M3U, KIND_XTREAM, PROVIDER_TIMEOUT_SECONDS,
)
from .guide import configured_urls
from .xtream import XtreamAuthError, XtreamClient, XtreamError

_LOGGER = logging.getLogger(__name__)
URL_TEXT = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL))
PASSWORD_TEXT = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
PLAIN_TEXT = selector.TextSelector()


def _clean_url(url: str) -> str:
    url = str(url).strip()
    if url and "://" not in url:
        url = "http://" + url
    return url.rstrip("/") if url.count("/") <= 3 else url


async def _check_xtream(hass: HomeAssistant, url: str, username: str, password: str) -> dict[str, Any]:
    client = XtreamClient(async_get_clientsession(hass), url, username, password, DEFAULT_USER_AGENT)
    account = await client.account()
    return {"account": account, "formats": [str(f).lower() for f in account.get("allowed_output_formats") or []]}


async def _check_m3u(hass: HomeAssistant, url: str) -> dict[str, Any]:
    session = async_get_clientsession(hass)
    async with session.get(url, headers={"User-Agent": DEFAULT_USER_AGENT},
                           timeout=aiohttp.ClientTimeout(total=PROVIDER_TIMEOUT_SECONDS)) as resp:
        if resp.status >= 400:
            raise ValueError(f"HTTP {resp.status}")
        text = (await resp.content.read(30 * 1024 * 1024)).decode("utf-8", "replace")
    entries = m3u.parse(text)
    if not entries:
        raise ValueError("no channels")
    return {"channels": len(entries), "guides": m3u.header_guides(text)}


class IPTVPlayerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["xtream", "m3u"])

    async def async_step_xtream(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = _clean_url(user_input[CONF_URL])
            username, password = str(user_input[CONF_USERNAME]).strip(), str(user_input[CONF_PASSWORD]).strip()
            try:
                info = await _check_xtream(self.hass, url, username, password)
            except XtreamAuthError:
                errors["base"] = "invalid_auth"
            except XtreamError as err:
                _LOGGER.debug("Xtream panel not reachable: %s", err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"xtream:{urlsplit(url).netloc.lower()}:{username}")
                self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_PASSWORD: password})
                title = str(user_input.get(CONF_NAME) or "").strip() or urlsplit(url).hostname or url
                output = DEFAULT_OUTPUT if not info["formats"] or "m3u8" in info["formats"] else "ts"
                return self.async_create_entry(
                    title=title,
                    data={CONF_KIND: KIND_XTREAM, CONF_URL: url, CONF_USERNAME: username, CONF_PASSWORD: password},
                    options={CONF_PROVIDER_GUIDE: True, CONF_GUIDE_URLS: FREE_UK_GUIDE, CONF_GUIDE_HOURS: DEFAULT_GUIDE_HOURS,
                             CONF_GUIDE_HOUR: DEFAULT_GUIDE_HOUR, CONF_OUTPUT: output, CONF_PLAYERS: [],
                             CONF_USER_AGENT: DEFAULT_USER_AGENT},
                )
        d = user_input or {}
        schema = vol.Schema({
            vol.Optional(CONF_NAME, default=d.get(CONF_NAME, "")): PLAIN_TEXT,
            vol.Required(CONF_URL, default=d.get(CONF_URL, "")): URL_TEXT,
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): PLAIN_TEXT,
            vol.Required(CONF_PASSWORD): PASSWORD_TEXT,
        })
        return self.async_show_form(step_id="xtream", data_schema=schema, errors=errors)

    async def async_step_m3u(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = str(user_input[CONF_URL]).strip()
            try:
                info = await _check_m3u(self.hass, url)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.debug("Playlist not read: %s", err)
                errors["base"] = "no_playlist"
            else:
                await self.async_set_unique_id(f"m3u:{url}")
                self._abort_if_unique_id_configured()
                title = str(user_input.get(CONF_NAME) or "").strip() or urlsplit(url).hostname or "Playlist"
                guides = "\n".join(configured_urls({}, info["guides"]))
                return self.async_create_entry(
                    title=title, data={CONF_KIND: KIND_M3U, CONF_URL: url},
                    options={CONF_GUIDE_URLS: guides, CONF_GUIDE_HOURS: DEFAULT_GUIDE_HOURS,
                             CONF_GUIDE_HOUR: DEFAULT_GUIDE_HOUR, CONF_PLAYERS: [], CONF_USER_AGENT: DEFAULT_USER_AGENT},
                )
        d = user_input or {}
        schema = vol.Schema({
            vol.Optional(CONF_NAME, default=d.get(CONF_NAME, "")): PLAIN_TEXT,
            vol.Required(CONF_URL, default=d.get(CONF_URL, "")): URL_TEXT,
        })
        return self.async_show_form(step_id="m3u", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            password = str(user_input[CONF_PASSWORD]).strip()
            try:
                await _check_xtream(self.hass, entry.data[CONF_URL], entry.data[CONF_USERNAME], password)
            except XtreamAuthError:
                errors["base"] = "invalid_auth"
            except XtreamError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: password})
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_TEXT}),
                                    errors=errors, description_placeholders={"name": entry.title})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IPTVPlayerOptionsFlow()


class IPTVPlayerOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        xtream = self.config_entry.data.get(CONF_KIND) == KIND_XTREAM
        if user_input is not None:
            cleaned = dict(user_input)
            cleaned[CONF_GUIDE_URLS] = "\n".join(u.strip() for u in str(cleaned.get(CONF_GUIDE_URLS) or "").splitlines() if u.strip())
            cleaned[CONF_USER_AGENT] = str(cleaned.get(CONF_USER_AGENT) or "").strip() or DEFAULT_USER_AGENT
            for key in (CONF_GUIDE_HOURS, CONF_GUIDE_HOUR):
                cleaned[key] = int(cleaned[key])
            return self.async_create_entry(title="", data=cleaned)
        o = self.config_entry.options
        fields: dict[Any, Any] = {}
        if xtream:
            fields[vol.Optional(CONF_PROVIDER_GUIDE, default=bool(o.get(CONF_PROVIDER_GUIDE, True)))] = selector.BooleanSelector()
        fields[vol.Optional(CONF_GUIDE_URLS, description={"suggested_value": o.get(CONF_GUIDE_URLS, "")})] = selector.TextSelector(
            selector.TextSelectorConfig(multiline=True))
        fields[vol.Optional(CONF_GUIDE_HOURS, default=int(o.get(CONF_GUIDE_HOURS, DEFAULT_GUIDE_HOURS)))] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=6, max=96, step=6, unit_of_measurement="h", mode=selector.NumberSelectorMode.BOX))
        fields[vol.Optional(CONF_GUIDE_HOUR, default=int(o.get(CONF_GUIDE_HOUR, DEFAULT_GUIDE_HOUR)))] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=23, step=1, mode=selector.NumberSelectorMode.BOX))
        fields[vol.Optional(CONF_PLAYERS, default=list(o.get(CONF_PLAYERS, [])))] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player", multiple=True))
        if xtream:
            fields[vol.Optional(CONF_OUTPUT, default=str(o.get(CONF_OUTPUT, DEFAULT_OUTPUT)))] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=["m3u8", "ts"], translation_key="output"))
        fields[vol.Optional(CONF_USER_AGENT, default=str(o.get(CONF_USER_AGENT, DEFAULT_USER_AGENT)))] = PLAIN_TEXT
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
