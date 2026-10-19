"""Sensors per entry: channels shown and guide updated; for a login also when the subscription ends and how many of
its connections are in use (for a "renew in 7 days" reminder, or to see why a TV was refused)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KIND_XTREAM, NAME
from .coordinator import IPTVCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: IPTVCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [ChannelsSensor(coordinator), GuideSensor(coordinator)]
    if coordinator.kind == KIND_XTREAM:
        entities += [SubscriptionSensor(coordinator), ConnectionsSensor(coordinator)]
    async_add_entities(entities)


class _Base(CoordinatorEntity[IPTVCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: IPTVCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=f"{NAME} {coordinator.entry.title}",
            manufacturer="IPTV Player", model="Xtream Codes login" if coordinator.kind == KIND_XTREAM else "M3U playlist",
            entry_type=DeviceEntryType.SERVICE,
        )


class ChannelsSensor(_Base):
    _attr_icon = "mdi:television-classic"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: IPTVCoordinator) -> None:
        super().__init__(coordinator, "channels_shown")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.shown())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        sel = c.selection
        return {"groups_ticked": sum(1 for v in sel["groups"].values() if v),
                "channels_in_list": len(c.catalog.channels) if c.catalog else 0,
                "list_read": datetime.fromtimestamp(c.catalog_at, timezone.utc).isoformat() if c.catalog_at else None}


class GuideSensor(_Base):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:television-guide"

    def __init__(self, coordinator: IPTVCoordinator) -> None:
        super().__init__(coordinator, "guide_updated")

    @property
    def native_value(self) -> datetime | None:
        built = self.coordinator.guide.state.built_at
        return datetime.fromtimestamp(built, timezone.utc) if built else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        return {"channels_matched": len(c.guide.state.matches), "channels_shown": len(c.shown()),
                "sources": [{k: v for k, v in s.items() if k in ("label", "channels", "error")} for s in c.guide.public_status()]}


class SubscriptionSensor(_Base):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: IPTVCoordinator) -> None:
        super().__init__(coordinator, "subscription_ends")

    @property
    def native_value(self) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(self.coordinator.account.get("exp_date")), timezone.utc)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        a = self.coordinator.account
        return {"status": a.get("status"), "trial": str(a.get("is_trial")) == "1"}


class ConnectionsSensor(_Base):
    _attr_icon = "mdi:connection"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: IPTVCoordinator) -> None:
        super().__init__(coordinator, "connections")

    @property
    def native_value(self) -> int | None:
        try:
            return int(self.coordinator.account.get("active_cons"))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"allowed": self.coordinator.max_streams}
