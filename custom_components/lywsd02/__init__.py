"""LYWSD02 Sync - set the clock of Xiaomi LYWSD02 e-Ink clocks over Bluetooth.

Fork of https://github.com/ashald/home-assistant-lywsd02 (Unlicense), based on
the work of ashald (Borys Pierov) and the contributors of pull request #22
(ernetas). Two things were added on top of that base:

* an optional scheduler, so the daily sync happens inside the integration
  instead of in a hand-written YAML automation;
* diagnostic entities (last sync + failure flag), because this integration
  writes to a device that reports nothing back - without them a failure is
  invisible.

The legacy ``lywsd02.set_time`` service is kept for backwards compatibility.
"""

from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    CALLBACK_TYPE,
    async_call_later,
    async_track_time_change,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLOCK_MODE,
    CONF_SYNC_ENABLED,
    CONF_SYNC_ON_START,
    CONF_SYNC_TIME,
    CONF_TEMP_MODE,
    CONF_TIMEOUT,
    DEFAULT_SYNC_ENABLED,
    DEFAULT_SYNC_ON_START,
    DEFAULT_SYNC_TIME,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PLATFORMS,
    RESULT_ERROR,
    RESULT_OK,
    MIN_RESYNC_INTERVAL,
    RESULT_PENDING,
    SIGNAL_UPDATE,
    STARTUP_SYNC_DELAY,
    TRIGGER_SCHEDULE,
    TRIGGER_STARTUP,
    UUID_TEMP_MODE,
    UUID_TIME,
)
from .helpers import (
    as_int,
    get_localized_timestamp,
    options_for,
    parse_sync_time,
    should_skip_resync,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


@dataclass
class LywsdRuntimeData:
    """State of the last sync attempt, shared by the diagnostic entities.

    Without this, a scheduled sync that fails is invisible: nothing raises,
    nothing changes in the entity states, and the user believes the clock is
    being kept in sync when it is not.
    """

    result: str = RESULT_PENDING
    last_sync: Any = None  # datetime of the last SUCCESSFUL sync
    last_attempt: Any = None  # datetime of the last attempt, successful or not
    last_error: str | None = None
    last_trigger: str | None = None
    duration_ms: int | None = None
    sync_count: int = 0
    skipped_count: int = 0
    unsubscribers: list[CALLBACK_TYPE] = field(default_factory=list)


async def async_sync_lywsd02(
    hass: HomeAssistant,
    mac: str,
    *,
    tz_offset: int = 0,
    timestamp: int | None = None,
    temp_mode: str | None = None,
    clock_mode: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> int:
    """Connect to a LYWSD02/LYWSD02MMC and set its clock.

    Returns the epoch value written. Raises ``HomeAssistantError`` when the
    clock cannot be reached or written - unlike the upstream version a failure
    is never swallowed, so an automation (or the button) really fails and can be
    alerted on.
    """
    mac = mac.upper()

    ble_device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
    if not ble_device:
        raise HomeAssistantError(
            f"Could not find a connectable Bluetooth path to '{mac}'. Check that "
            "an ESPHome Bluetooth proxy (or an adapter) is in range and that the "
            "clock has not been removed."
        )

    _LOGGER.debug("Found '%s' - attempting to set the time", ble_device)

    temp_payload: bytes | None = None
    normalized_temp = (temp_mode or "").upper()
    if normalized_temp in ("C", "F"):
        temp_payload = struct.pack("B", (0x01 if normalized_temp == "F" else 0xFF))

    clock_payload: bytes | None = None
    if clock_mode in (12, 24):
        clock_payload = struct.pack("IHB", 0, 0, 0xAA if clock_mode == 12 else 0x00)

    # A plain BleakClient regularly fails on the first attempt when the device
    # is reached through an ESPHome/Shelly proxy rather than a local adapter.
    # establish_connection retries and handles the proxy's connection slots.
    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            mac,
            timeout=timeout,
        )
    except (BleakError, TimeoutError, OSError) as err:
        raise HomeAssistantError(f"Could not connect to '{mac}': {err}") from err

    try:
        resolved = (
            int(timestamp)
            if timestamp is not None
            else get_localized_timestamp(tz_offset)
        )
        try:
            await client.write_gatt_char(UUID_TIME, struct.pack("Ib", resolved, tz_offset))
            if temp_payload is not None:
                await client.write_gatt_char(UUID_TEMP_MODE, temp_payload)
        except (BleakError, TimeoutError, OSError) as err:
            raise HomeAssistantError(f"Could not write the time to '{mac}': {err}") from err

        if clock_payload is not None:
            # 12/24-hour switching is only implemented on the LYWSD02MMC (upstream
            # issue #10). On the plain LYWSD02 the characteristic is a fixed
            # 5-byte time attribute and rejects the 7-byte payload: warn, do not
            # fail, the time itself has already been written.
            try:
                await client.write_gatt_char(UUID_TIME, clock_payload)
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.warning(
                    "clock_mode (12/24-hour) is only supported on the LYWSD02MMC; "
                    "'%s' rejected the write (%s). The time was set anyway.",
                    mac,
                    err,
                )
    finally:
        await client.disconnect()

    _LOGGER.debug("Time set on '%s' to epoch %s", mac, resolved)
    return resolved


async def async_request_sync(
    hass: HomeAssistant,
    entry: ConfigEntry,
    trigger: str,
    *,
    raise_on_error: bool = True,
) -> bool:
    """Run one sync for a configured clock and record the outcome.

    ``raise_on_error`` is True for user-initiated syncs (button, service), so
    the caller sees the failure, and False for background ones (scheduler,
    startup), where the diagnostic entities carry the information instead.
    """
    runtime: LywsdRuntimeData = entry.runtime_data
    options = options_for(entry)
    mac = str(entry.data[CONF_MAC]).upper()

    # Garde-fou anti-boucle : voir should_skip_resync(). Une synchro manuelle
    # (bouton) passe toujours.
    if should_skip_resync(
        runtime.last_attempt,
        dt_util.utcnow(),
        trigger,
        min_interval=MIN_RESYNC_INTERVAL,
        manual_trigger=TRIGGER_BUTTON,
    ):
        runtime.skipped_count += 1
        _LOGGER.debug("LYWSD02: synchro '%s' ignoree (tentative trop recente)", trigger)
        return True

    started = time.monotonic()
    runtime.last_trigger = trigger
    runtime.last_attempt = dt_util.utcnow()
    try:
        await async_sync_lywsd02(
            hass,
            mac,
            temp_mode=options.get(CONF_TEMP_MODE),
            clock_mode=as_int(options.get(CONF_CLOCK_MODE)),
            timeout=int(options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        )
    except HomeAssistantError as err:
        runtime.result = RESULT_ERROR
        runtime.last_error = str(err)
        runtime.duration_ms = int((time.monotonic() - started) * 1000)
        _LOGGER.error("LYWSD02 sync failed (%s): %s", trigger, err)
        async_dispatcher_send(hass, f"{SIGNAL_UPDATE}_{entry.entry_id}")
        if raise_on_error:
            raise
        return False

    runtime.result = RESULT_OK
    runtime.last_error = None
    runtime.last_sync = dt_util.utcnow()
    runtime.duration_ms = int((time.monotonic() - started) * 1000)
    runtime.sync_count += 1
    _LOGGER.debug(
        "LYWSD02 '%s' synced (%s, %s ms)", mac, trigger, runtime.duration_ms
    )
    async_dispatcher_send(hass, f"{SIGNAL_UPDATE}_{entry.entry_id}")
    return True


def _async_schedule(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the built-in scheduler for an entry, if enabled."""
    runtime: LywsdRuntimeData = entry.runtime_data
    options = options_for(entry)

    if options.get(CONF_SYNC_ENABLED, DEFAULT_SYNC_ENABLED):
        parsed = parse_sync_time(options.get(CONF_SYNC_TIME, DEFAULT_SYNC_TIME))
        if parsed is None:
            _LOGGER.warning(
                "LYWSD02: invalid sync time (%r), built-in schedule disabled",
                options.get(CONF_SYNC_TIME),
            )
        else:
            hour, minute, second = parsed

            async def _scheduled(_now) -> None:
                await async_request_sync(
                    hass, entry, TRIGGER_SCHEDULE, raise_on_error=False
                )

            runtime.unsubscribers.append(
                async_track_time_change(
                    hass, _scheduled, hour=hour, minute=minute, second=second
                )
            )
            _LOGGER.debug(
                "LYWSD02: daily sync scheduled at %02d:%02d:%02d", hour, minute, second
            )

    if options.get(CONF_SYNC_ON_START, DEFAULT_SYNC_ON_START):

        async def _on_start(_now) -> None:
            await async_request_sync(hass, entry, TRIGGER_STARTUP, raise_on_error=False)

        runtime.unsubscribers.append(async_call_later(hass, STARTUP_SYNC_DELAY, _on_start))


@callback
def _async_cancel_schedule(entry: ConfigEntry) -> None:
    """Cancel the timers registered for an entry."""
    runtime: LywsdRuntimeData = entry.runtime_data
    for unsubscribe in runtime.unsubscribers:
        unsubscribe()
    runtime.unsubscribers.clear()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the legacy YAML service (kept for backwards compatibility)."""

    async def set_time(call: ServiceCall) -> None:
        mac = call.data.get("mac")
        if not mac:
            raise HomeAssistantError("The 'mac' parameter is required.")
        await async_sync_lywsd02(
            hass,
            mac,
            tz_offset=call.data.get("tz_offset", 0),
            timestamp=call.data.get("timestamp"),
            temp_mode=call.data.get("temp_mode"),
            clock_mode=call.data.get("clock_mode", 0),
            timeout=int(call.data.get("timeout", DEFAULT_TIMEOUT)),
        )

    hass.services.async_register(DOMAIN, "set_time", set_time)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a LYWSD02 / LYWSD02MMC clock from a config entry."""
    entry.runtime_data = LywsdRuntimeData()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_schedule(hass, entry)
    entry.async_on_unload(lambda: _async_cancel_schedule(entry))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _async_cancel_schedule(entry)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so a new schedule takes effect immediately."""
    await hass.config_entries.async_reload(entry.entry_id)
