"""Diagnostic sensors for the LYWSD02 Sync integration.

A clock that never reports anything back is a black box: without these
entities a failed sync (no Bluetooth proxy in range, clock on another floor)
is completely invisible - the automation still shows green and the display
keeps showing the wrong time.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SYNC_ENABLED,
    CONF_SYNC_TIME,
    DEFAULT_SYNC_ENABLED,
    DEFAULT_SYNC_TIME,
    DOMAIN,
    SIGNAL_UPDATE,
)
from .helpers import next_sync_time, options_for


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors for a config entry."""
    async_add_entities([LywsdLastSyncSensor(entry)])


class LywsdLastSyncSensor(SensorEntity):
    """Timestamp of the last successful synchronisation.

    The state stays empty until a sync succeeds, so an empty state on a device
    that should have synced is itself the signal that something is wrong.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-check"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor for one configured clock."""
        self._entry = entry
        self._mac = str(entry.data[CONF_MAC]).upper()
        self._attr_unique_id = f"{self._mac}_last_sync"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=entry.title,
            manufacturer="Xiaomi",
            model="LYWSD02 / LYWSD02MMC",
        )

    async def async_added_to_hass(self) -> None:
        """Refresh the entity whenever a sync completes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._entry.entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the new state."""
        self.async_write_ha_state()

    @property
    def _runtime(self):
        """Runtime data of the entry (never None once set up)."""
        return self._entry.runtime_data

    @property
    def native_value(self):
        """Datetime of the last successful sync."""
        return self._runtime.last_sync

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything needed to tell a healthy clock from a silent failure."""
        runtime = self._runtime
        options = options_for(self._entry)
        attributes: dict[str, Any] = {
            "mac": self._mac,
            "result": runtime.result,
            "last_attempt": runtime.last_attempt,
            "last_error": runtime.last_error,
            "last_trigger": runtime.last_trigger,
            "duration_ms": runtime.duration_ms,
            "sync_count": runtime.sync_count,
            "skipped_count": runtime.skipped_count,
            "schedule_enabled": options.get(CONF_SYNC_ENABLED, DEFAULT_SYNC_ENABLED),
        }
        if attributes["schedule_enabled"]:
            sync_time = options.get(CONF_SYNC_TIME, DEFAULT_SYNC_TIME)
            attributes["schedule_time"] = sync_time
            attributes["next_sync"] = next_sync_time(sync_time, dt_util.now())
        return attributes
