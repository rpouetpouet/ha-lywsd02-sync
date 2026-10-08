"""Binary sensor exposing a failed synchronisation.

Device class ``problem`` so it can be used directly in an automation or shown
as an alert: a LYWSD02 that stops being synchronised is not detected by
anything else - neither the clock nor Home Assistant raises on its own.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RESULT_ERROR, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sync-problem binary sensor for a config entry."""
    async_add_entities([LywsdSyncProblem(entry)])


class LywsdSyncProblem(BinarySensorEntity):
    """On when the last synchronisation attempt failed."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the binary sensor for one configured clock."""
        self._entry = entry
        self._mac = str(entry.data[CONF_MAC]).upper()
        self._attr_unique_id = f"{self._mac}_sync_problem"
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
    def is_on(self) -> bool:
        """True when the last attempt failed."""
        return self._entry.runtime_data.result == RESULT_ERROR

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Why it failed, and when it was last attempted."""
        runtime = self._entry.runtime_data
        return {
            "mac": self._mac,
            "last_error": runtime.last_error,
            "last_attempt": runtime.last_attempt,
            "last_trigger": runtime.last_trigger,
        }
