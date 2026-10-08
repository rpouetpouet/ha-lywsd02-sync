"""Button platform for the LYWSD02 Sync integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_request_sync
from .const import DOMAIN, TRIGGER_BUTTON


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sync-time button for a config entry."""
    async_add_entities([LywsdSyncTimeButton(entry)])


class LywsdSyncTimeButton(ButtonEntity):
    """Button that syncs a LYWSD02/LYWSD02MMC clock on press.

    Goes through ``async_request_sync`` so the press is recorded in the
    diagnostic entities and a failure raises ``HomeAssistantError`` - Home
    Assistant then shows it as a failed action instead of pretending success.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sync_now"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the button for one configured clock."""
        self._entry = entry
        self._mac = str(entry.data[CONF_MAC]).upper()
        self._attr_unique_id = f"{self._mac}_sync_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=entry.title,
            manufacturer="Xiaomi",
            model="LYWSD02 / LYWSD02MMC",
        )

    async def async_press(self) -> None:
        """Sync the clock to Home Assistant's current time."""
        await async_request_sync(
            self.hass, self._entry, TRIGGER_BUTTON, raise_on_error=True
        )
