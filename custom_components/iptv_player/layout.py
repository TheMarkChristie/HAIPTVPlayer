"""The order of the groups on the TV page across every source (Mark, 19 Oct 2026: "rename the Group categories in the
backend and the sort order"). Each source keeps its own group names in its selection; this list orders
"<entry_id>:<group_id>" ids, so the provider's groups and the free ones can be mixed. Groups not in the list follow
in each source's own order."""
from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORE_VERSION

_DATA = f"{DOMAIN}_layout"
_LOCK = f"{DOMAIN}_layout_lock"


class Layout:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.layout")
        self.group_order: list[str] = []

    async def async_save_order(self, order: list[str]) -> None:
        self.group_order = [str(x) for x in order]
        await self._store.async_save({"group_order": self.group_order})


async def async_get_layout(hass: HomeAssistant) -> Layout:
    if (layout := hass.data.get(_DATA)) is not None:
        return layout
    lock = hass.data.setdefault(_LOCK, asyncio.Lock())
    async with lock:
        if (layout := hass.data.get(_DATA)) is None:
            layout = Layout(hass)
            stored: Any = await layout._store.async_load() or {}
            layout.group_order = [str(x) for x in stored.get("group_order") or []]
            hass.data[_DATA] = layout
    return layout


def sort_groups(groups: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    """Groups (dicts with an "id" of "<entry_id>:<group_id>") in the saved order, the rest after in their own order."""
    pos = {uid: i for i, uid in enumerate(order)}
    natural = {g["id"]: i for i, g in enumerate(groups)}
    return sorted(groups, key=lambda g: (0, pos[g["id"]]) if g["id"] in pos else (1, natural[g["id"]]))
