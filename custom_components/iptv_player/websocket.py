"""The websocket commands the card uses.

  iptv_player/channels       the channels to show, with now and next, plus the TVs for Play on TV (any signed-in user)
  iptv_player/guide          programmes for some channels over a time span (any signed-in user)
  iptv_player/stream         open (or share) a channel's relay session (any user, shown channels; admins any channel)
  iptv_player/release        the card left a channel
  iptv_player/subscribe      a message whenever channels, the guide or the selection change
  iptv_player/catalog        admins: every group, or one group's channels, or a search, for Manage channels
  iptv_player/select         admins: save Manage channels' changes
  iptv_player/guide_search   admins: guide channels by name, to pick one by hand

Logos on plain http are signed with the asking user's refresh token (the logo proxy needs a signed-in browser)."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_PLAYERS, DOMAIN, EVENT_UPDATED, KIND_XTREAM, SIGNED_URL_HOURS, WS_CATALOG, WS_CHANNELS, WS_GUIDE, WS_RELEASE,
    WS_SELECT, WS_STREAM, WS_SUBSCRIBE,
)
from .layout import async_get_layout, sort_groups
from .model import (
    display_name, group_name, is_shown, now_next, ordered_groups, programme_dict, search_guide_channels, tidy_name, window,
)
from .relay import RelayFull

WS_GUIDE_SEARCH = f"{DOMAIN}/guide_search"
WS_GROUP_ORDER = f"{DOMAIN}/group_order"
_SIGNED = f"{DOMAIN}_signed_urls"
_SIGNED_MAX = 6000


def _sign(hass: HomeAssistant, token_id: str | None, path: str | None) -> str | None:
    if not path or not path.startswith("/api/"):
        return path
    memo: dict[tuple[str | None, str], tuple[float, str]] = hass.data.setdefault(_SIGNED, {})
    now = time.time()
    hit = memo.get((token_id, path))
    if hit and hit[0] - now > 3600:
        return hit[1]
    if len(memo) > _SIGNED_MAX:
        for k in [k for k, v in memo.items() if v[0] - now <= 3600]:
            memo.pop(k, None)
    url = async_sign_path(hass, path, timedelta(hours=SIGNED_URL_HOURS), refresh_token_id=token_id)
    memo[(token_id, path)] = (now + SIGNED_URL_HOURS * 3600, url)
    return url


def _device_name(hass: HomeAssistant, entity_id: str) -> str:
    entry = er.async_get(hass).async_get(entity_id)
    if entry and entry.device_id and (device := dr.async_get(hass).async_get(entry.device_id)):
        return device.name_by_user or device.name or entity_id
    state = hass.states.get(entity_id)
    return state.name if state else entity_id


def players(hass: HomeAssistant, configured: list[str] | None) -> list[dict[str, Any]]:
    """The TVs offered on Play on TV: the options' list, else the house's Google Cast devices (as Plex Picks)."""
    ids = list(configured or [])
    if not ids:
        ids = [e.entity_id for e in er.async_get(hass).entities.values()
               if e.platform == "cast" and e.domain == "media_player" and not e.disabled_by]
    out = []
    for entity_id in ids:
        state = hass.states.get(entity_id)
        out.append({"entity_id": entity_id, "name": _device_name(hass, entity_id),
                    "available": bool(state) and state.state not in ("unavailable", "unknown")})
    return sorted(out, key=lambda p: p["name"].casefold()) if not configured else out


def _account(c: Any) -> dict[str, Any] | None:
    if c.kind != KIND_XTREAM or not c.account:
        return None
    a = c.account
    return {k: a.get(k) for k in ("status", "exp_date", "is_trial", "active_cons", "max_connections")}


def _channel(hass: HomeAssistant, token_id: str | None, c: Any, ch: Any, now: int) -> dict[str, Any]:
    current, nxt = now_next(c.guide.state.programmes.get(ch.key), now)
    renamed = str(c.selection["channels"].get(ch.key, {}).get("name") or "").strip()
    return {
        "uid": f"{c.entry.entry_id}:{ch.key}", "entry_id": c.entry.entry_id, "key": ch.key,
        "group": f"{c.entry.entry_id}:{ch.group}", "name": renamed or tidy_name(ch.name), "number": ch.number,
        "logo": _sign(hass, token_id, c.logo_path(ch)),
        "now": programme_dict(current), "next": programme_dict(nxt),
    }


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (ws_channels, ws_guide, ws_stream, ws_release, ws_subscribe, ws_catalog, ws_select, ws_guide_search,
                    ws_group_order):
        websocket_api.async_register_command(hass, command)


def _loaded(hass: HomeAssistant, entry_id: str | None = None) -> list[Any]:
    from . import coordinators  # noqa: PLC0415  (avoid an import cycle at module load)

    return [c for c in coordinators(hass) if entry_id in (None, c.entry.entry_id) and c.catalog is not None]


@websocket_api.websocket_command({vol.Required("type"): WS_CHANNELS, vol.Optional("entry_id"): str})
@websocket_api.async_response
async def ws_channels(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    loaded = _loaded(hass, msg.get("entry_id"))
    from . import coordinators  # noqa: PLC0415

    if not coordinators(hass):
        connection.send_error(msg["id"], "not_set_up", "IPTV Player is not set up")
        return
    now = int(time.time())
    token_id = connection.refresh_token_id
    entries, groups, channels, configured = [], [], [], []
    for c in loaded:
        shown = c.shown()
        names = {g.id: group_name(g, c.selection) for g in c.catalog.groups}
        entries.append({"entry_id": c.entry.entry_id, "title": c.entry.title, "kind": c.kind, "shown": len(shown),
                        "account": _account(c), "guide_updated": c.guide.state.built_at, "version": c.version})
        seen: list[str] = []
        for ch in shown:
            if ch.group not in seen:
                seen.append(ch.group)
            channels.append(_channel(hass, token_id, c, ch, now))
        originals = {g.id: g.name for g in c.catalog.groups}
        groups += [{"id": f"{c.entry.entry_id}:{gid}", "entry_id": c.entry.entry_id, "name": names.get(gid, gid),
                    "original": originals.get(gid, gid)} for gid in seen]
        configured += list(c.options.get(CONF_PLAYERS) or [])
    # the groups in Mark's order across every source, each group's channels keeping their own order
    groups = sort_groups(groups, (await async_get_layout(hass)).group_order)
    rank = {g["id"]: i for i, g in enumerate(groups)}
    channels.sort(key=lambda ch: rank.get(ch["group"], len(rank)))
    connection.send_result(msg["id"], {
        "entries": entries, "groups": groups, "channels": channels, "now": now,
        "players": players(hass, configured), "is_admin": bool(connection.user and connection.user.is_admin),
        "loading": len(loaded) < len(coordinators(hass)),
    })


@websocket_api.websocket_command({
    vol.Required("type"): WS_GUIDE,
    vol.Required("entry_id"): str,
    vol.Required("keys"): vol.All([str], vol.Length(max=120)),
    vol.Optional("start"): int,
    vol.Optional("end"): int,
    vol.Optional("details", default=False): bool,
})
@websocket_api.async_response
async def ws_guide(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    loaded = _loaded(hass, msg["entry_id"])
    if not loaded:
        connection.send_error(msg["id"], "not_ready", "That entry is not loaded")
        return
    c = loaded[0]
    now = int(time.time())
    start = int(msg.get("start") or now - 3600)
    end = min(int(msg.get("end") or now + 6 * 3600), start + 48 * 3600)
    out: dict[str, list[dict[str, Any]]] = {}
    for key in msg["keys"]:
        progs = window(c.guide.state.programmes.get(key), start, end)
        items = [programme_dict(p) for p in progs]
        if not msg["details"]:
            for item in items:
                item.pop("desc", None)
        out[key] = items
    connection.send_result(msg["id"], {"programmes": out, "start": start, "end": end})


@websocket_api.websocket_command({vol.Required("type"): WS_STREAM, vol.Required("entry_id"): str, vol.Required("key"): str})
@websocket_api.async_response
async def ws_stream(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    loaded = _loaded(hass, msg["entry_id"])
    channel = loaded[0].catalog.channel(msg["key"]) if loaded else None
    if channel is None:
        connection.send_error(msg["id"], "not_found", "No such channel")
        return
    c = loaded[0]
    if not is_shown(channel, c.selection) and not (connection.user and connection.user.is_admin):
        connection.send_error(msg["id"], "not_found", "No such channel")
        return
    session = await open_session(hass, c, channel)
    if isinstance(session, str):
        connection.send_error(msg["id"], "busy", session)
        return
    connection.send_result(msg["id"], {"token": session.token, "url": session.path, "kind": session.kind})


async def open_session(hass: HomeAssistant, c: Any, channel: Any) -> Any:
    """A relay session for one channel, or the reason there is none (a string)."""
    relay = hass.data[DOMAIN]["relay"]
    url, headers, kind = c.upstream(channel)
    if kind is None:
        kind = await relay.probe_kind(url, headers)
        c.play_kinds[channel.key] = kind
    try:
        return relay.open(c.entry.entry_id, channel.key, kind, url, headers, c.max_streams)
    except RelayFull as err:
        return str(err)


@websocket_api.websocket_command({vol.Required("type"): WS_RELEASE, vol.Required("token"): str})
@callback
def ws_release(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    hass.data[DOMAIN]["relay"].release(msg["token"])
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): WS_SUBSCRIBE})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    @callback
    def forward(event: Event) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], dict(event.data)))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(EVENT_UPDATED, forward)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({
    vol.Required("type"): WS_CATALOG,
    vol.Required("entry_id"): str,
    vol.Optional("group"): str,
    vol.Optional("query"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_catalog(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    loaded = _loaded(hass, msg["entry_id"])
    if not loaded:
        connection.send_error(msg["id"], "not_ready", "That entry is not loaded yet")
        return
    c = loaded[0]
    sel = c.selection
    token_id = connection.refresh_token_id
    matches = c.guide.state.matches
    sources = c.guide.state.sources

    def channel(ch: Any) -> dict[str, Any]:
        own = sel["channels"].get(ch.key, {})
        match = matches.get(ch.key)
        return {
            "key": ch.key, "name": ch.name, "display": display_name(ch, sel) if own.get("name") else "",
            "tidy": tidy_name(ch.name), "group": ch.group, "on": is_shown(ch, sel), "own": own.get("on"),
            "number": ch.number, "logo": _sign(hass, token_id, c.logo_path(ch)), "guide_id": ch.guide_id,
            "guide": {"source": sources[match[0]].label if match[0] < len(sources) else "?", "id": match[1], "how": match[2]} if match else None,
            "guide_manual": own.get("guide"),
        }

    if msg.get("group") is not None or msg.get("query"):
        if msg.get("query"):
            words = [w for w in msg["query"].lower().split() if w]
            picked = [ch for ch in c.catalog.channels if all(w in ch.name.lower() for w in words)][:300]
        else:
            in_group = [ch for ch in c.catalog.channels if ch.group == msg["group"]]
            pos = {k: i for i, k in enumerate(sel["channel_order"])}
            picked = sorted(in_group, key=lambda ch: (0, pos[ch.key]) if ch.key in pos else (1, ch.order))
        connection.send_result(msg["id"], {"channels": [channel(ch) for ch in picked]})
        return

    totals: dict[str, int] = {}
    shown: dict[str, int] = {}
    for ch in c.catalog.channels:
        totals[ch.group] = totals.get(ch.group, 0) + 1
        if is_shown(ch, sel):
            shown[ch.group] = shown.get(ch.group, 0) + 1
    connection.send_result(msg["id"], {
        "entry_id": c.entry.entry_id, "title": c.entry.title, "kind": c.kind,
        "groups": [{"id": g.id, "name": g.name, "display": sel["group_names"].get(g.id, ""), "on": bool(sel["groups"].get(g.id)),
                    "total": totals.get(g.id, 0), "shown": shown.get(g.id, 0)} for g in ordered_groups(c.catalog, sel)],
        "channels_total": len(c.catalog.channels), "skipped": c.catalog.skipped, "catalog_at": c.catalog_at,
        "guide": {"sources": c.guide.public_status(), "built_at": c.guide.state.built_at,
                  "matched": len(matches), "shown": len(c.shown())},
        "account": _account(c), "streams": hass.data[DOMAIN]["relay"].active(c.entry.entry_id),
    })


@websocket_api.websocket_command({
    vol.Required("type"): WS_SELECT,
    vol.Required("entry_id"): str,
    vol.Optional("changes", default=[]): [dict],
    vol.Optional("group_order"): [str],
    vol.Optional("channel_order"): [str],
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_select(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    loaded = _loaded(hass, msg["entry_id"])
    if not loaded:
        connection.send_error(msg["id"], "not_ready", "That entry is not loaded yet")
        return
    c = loaded[0]
    await c.async_select(msg["changes"], msg.get("group_order"), msg.get("channel_order"))
    connection.send_result(msg["id"], {"shown": len(c.shown()), "version": c.version})


@websocket_api.websocket_command({vol.Required("type"): WS_GUIDE_SEARCH, vol.Required("entry_id"): str, vol.Required("query"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_guide_search(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    loaded = _loaded(hass, msg["entry_id"])
    if not loaded or len(msg["query"].strip()) < 2:
        connection.send_result(msg["id"], {"results": []})
        return
    connection.send_result(msg["id"], {"results": search_guide_channels(loaded[0].guide.state.sources, msg["query"])})


@websocket_api.websocket_command({vol.Required("type"): WS_GROUP_ORDER, vol.Required("order"): [str]})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_group_order(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Admins: the order of the groups on the TV page across every source ("<entry_id>:<group_id>" ids)."""
    layout = await async_get_layout(hass)
    await layout.async_save_order(msg["order"])
    hass.bus.async_fire(EVENT_UPDATED, {"entry_id": None, "what": "layout"})
    connection.send_result(msg["id"], {"order": layout.group_order})
