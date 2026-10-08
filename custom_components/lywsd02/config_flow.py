"""Config flow and options flow for the LYWSD02 Sync integration.

Two ways to add a clock: automatic Bluetooth discovery (the manifest declares
the ``LYWSD02`` / ``LYWSD02MMC`` local names) or manual entry of its MAC
address. The config entry is what unlocks the device page, the "Sync now"
button, the diagnostic entities and the built-in scheduler.

The legacy ``lywsd02.set_time`` YAML service keeps working without any entry.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfo
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_CLOCK_MODE,
    CONF_SYNC_ENABLED,
    CONF_SYNC_ON_START,
    CONF_SYNC_TIME,
    CONF_TEMP_MODE,
    CONF_TIMEOUT,
    DOMAIN,
)
from .helpers import options_for

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

TEMP_MODE_CHOICES = ["none", "C", "F"]
CLOCK_MODE_CHOICES = ["none", "12", "24"]


class LywsdConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LYWSD02 / LYWSD02MMC."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_mac: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfo
    ) -> ConfigFlowResult:
        """Handle a LYWSD02/LYWSD02MMC discovered over Bluetooth."""
        mac = discovery_info.address.upper()
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        self._discovered_mac = mac
        self._discovered_name = discovery_info.name or mac
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup of a discovered device."""
        assert self._discovered_mac is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name or self._discovered_mac,
                data={CONF_MAC: self._discovered_mac},
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovered_name or ""},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual entry of a MAC address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = user_input[CONF_MAC].upper()
            if not _MAC_RE.match(mac):
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or mac,
                    data={CONF_MAC: mac},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Optional(CONF_NAME): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (built-in schedule + display settings)."""
        return LywsdOptionsFlow()


class LywsdOptionsFlow(OptionsFlow):
    """Options flow: the built-in schedule replaces a YAML automation.

    No ``__init__`` taking the config entry: Home Assistant injects
    ``self.config_entry`` itself, and passing it explicitly is deprecated.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = options_for(self.config_entry)
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SYNC_ENABLED, default=options[CONF_SYNC_ENABLED]
                ): bool,
                vol.Optional(
                    CONF_SYNC_TIME, default=options[CONF_SYNC_TIME]
                ): TimeSelector(),
                vol.Optional(
                    CONF_SYNC_ON_START, default=options[CONF_SYNC_ON_START]
                ): bool,
                vol.Optional(
                    CONF_TEMP_MODE, default=str(options[CONF_TEMP_MODE])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=TEMP_MODE_CHOICES,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="temp_mode",
                    )
                ),
                vol.Optional(
                    CONF_CLOCK_MODE, default=str(options[CONF_CLOCK_MODE])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=CLOCK_MODE_CHOICES,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="clock_mode",
                    )
                ),
                vol.Optional(
                    CONF_TIMEOUT, default=int(options[CONF_TIMEOUT])
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5,
                        max=300,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
