"""Constants for the LYWSD02 Sync integration.

Fork of ashald/home-assistant-lywsd02 (Unlicense), extended with an optional
built-in scheduler and diagnostic entities, so that everything lives in the
integration instead of a hand-written YAML automation.
"""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "lywsd02"
NAME: Final = "LYWSD02 Sync"

PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

# GATT characteristics of the LYWSD02 / LYWSD02MMC
UUID_TIME: Final = "EBE0CCB7-7A0A-4B0C-8A1A-6FF2997DA3A6"
UUID_TEMP_MODE: Final = "EBE0CCBE-7A0A-4B0C-8A1A-6FF2997DA3A6"

# Configuration / options
CONF_SYNC_ENABLED: Final = "sync_enabled"
CONF_SYNC_TIME: Final = "sync_time"
CONF_SYNC_ON_START: Final = "sync_on_start"
CONF_TEMP_MODE: Final = "temp_mode"
CONF_CLOCK_MODE: Final = "clock_mode"
CONF_TIMEOUT: Final = "timeout"

DEFAULT_SYNC_ENABLED: Final = True
DEFAULT_SYNC_TIME: Final = "04:00:00"
DEFAULT_SYNC_ON_START: Final = True
DEFAULT_TEMP_MODE: Final = "none"
DEFAULT_CLOCK_MODE: Final = "none"
DEFAULT_TIMEOUT: Final = 60

# Delay before the optional startup sync: the Bluetooth stack (and the ESPHome
# proxies feeding it) needs a moment to become usable after a restart.
STARTUP_SYNC_DELAY: Final = 60

# What triggered a sync - exposed as an attribute, so a real scheduled sync can
# be told apart from a manual press.
# Signal envoye apres CHAQUE tentative de synchronisation (succes ou echec) :
# les entites de diagnostic s'y abonnent pour se rafraichir.
SIGNAL_UPDATE: Final = f"{DOMAIN}_update"

TRIGGER_STARTUP: Final = "startup"
TRIGGER_SCHEDULE: Final = "schedule"
TRIGGER_BUTTON: Final = "button"
TRIGGER_SERVICE: Final = "service"

# Deux déclencheurs qui tombent en même temps (démarrage + horaire, ou un double
# tir au changement d'heure) ne doivent pas provoquer deux synchronisations
# rapprochées. L'écriture est idempotente, mais ce garde-fou rend toute boucle
# structurellement impossible. Les synchros manuelles (bouton, service) ne sont
# jamais filtrées : elles expriment une intention explicite.
MIN_RESYNC_INTERVAL: Final = 300  # secondes

RESULT_OK: Final = "ok"
RESULT_ERROR: Final = "error"
RESULT_PENDING: Final = "pending"
