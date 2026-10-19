"""Group names and the order of the groups across sources (Mark, 19 Oct 2026: "can we rename the Group categories in
the backend and the sort order")."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from conftest import setup_xtream


async def test_rename_groups_and_order_across_sources(hass: HomeAssistant, provider, hass_ws_client) -> None:
    entry, c = await setup_xtream(hass)
    ws = await hass_ws_client(hass)
    eid = entry.entry_id
    await ws.send_json({"id": 1, "type": "iptv_player/select", "entry_id": eid,
                        "changes": [{"group": "7", "on": True}, {"group": "8", "on": True}]})
    await ws.receive_json()

    # renaming a group keeps it ticked and changes its name everywhere
    await ws.send_json({"id": 2, "type": "iptv_player/select", "entry_id": eid, "changes": [{"group": "7", "name": "UK"}]})
    assert (await ws.receive_json())["result"]["shown"] == 4
    await ws.send_json({"id": 3, "type": "iptv_player/channels"})
    result = (await ws.receive_json())["result"]
    assert [(g["name"], g["original"]) for g in result["groups"]] == [("UK", "UNITED KINGDOM"), ("UK-SPORTS", "UK-SPORTS")]
    assert [ch["key"] for ch in result["channels"]] == ["101", "102", "103", "201"]

    # the order across sources: sport first, and the channels follow their group
    await ws.send_json({"id": 4, "type": "iptv_player/group_order", "order": [f"{eid}:8", f"{eid}:7"]})
    assert (await ws.receive_json())["success"]
    await ws.send_json({"id": 5, "type": "iptv_player/channels"})
    result = (await ws.receive_json())["result"]
    assert [g["name"] for g in result["groups"]] == ["UK-SPORTS", "UK"]
    assert [ch["key"] for ch in result["channels"]] == ["201", "101", "102", "103"]

    # the catalogue shows the new name next to the provider's, and clearing it gives the provider's back
    await ws.send_json({"id": 6, "type": "iptv_player/catalog", "entry_id": eid})
    groups = (await ws.receive_json())["result"]["groups"]
    assert (groups[0]["name"], groups[0]["display"], groups[0]["on"]) == ("UNITED KINGDOM", "UK", True)
    await ws.send_json({"id": 7, "type": "iptv_player/select", "entry_id": eid, "changes": [{"group": "7", "name": ""}]})
    await ws.receive_json()
    await ws.send_json({"id": 8, "type": "iptv_player/channels"})
    assert [g["name"] for g in (await ws.receive_json())["result"]["groups"]] == ["UK-SPORTS", "UNITED KINGDOM"]

    # the order is kept by Home Assistant: it survives a reload of the source
    assert await hass.config_entries.async_reload(eid)
    await hass.async_block_till_done(wait_background_tasks=True)
    await ws.send_json({"id": 9, "type": "iptv_player/channels"})
    assert [g["name"] for g in (await ws.receive_json())["result"]["groups"]] == ["UK-SPORTS", "UNITED KINGDOM"]


async def test_group_order_is_admin_only(hass: HomeAssistant, provider, hass_ws_client, hass_admin_user) -> None:
    await setup_xtream(hass)
    hass_admin_user.groups = []                          # no longer an administrator
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/group_order", "order": []})
    msg = await ws.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
