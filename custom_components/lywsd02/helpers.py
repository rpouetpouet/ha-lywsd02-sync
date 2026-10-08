"""Pure helpers for the LYWSD02 Sync integration.

Kept free of any Home Assistant component import so they can be unit tested
without spinning up Home Assistant.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any

from .const import (
    CONF_CLOCK_MODE,
    CONF_SYNC_ENABLED,
    CONF_SYNC_ON_START,
    CONF_SYNC_TIME,
    CONF_TEMP_MODE,
    CONF_TIMEOUT,
    DEFAULT_CLOCK_MODE,
    DEFAULT_SYNC_ENABLED,
    DEFAULT_SYNC_ON_START,
    DEFAULT_SYNC_TIME,
    DEFAULT_TEMP_MODE,
    DEFAULT_TIMEOUT,
)


def get_localized_timestamp(tz_offset: int = 0, now_factory=None) -> int:
    """Return the epoch that makes the device display Home Assistant's local time.

    The device shows ``timestamp + tz_offset hours`` as wall-clock time, so the
    local UTC offset has to be baked into the timestamp, minus whatever part of
    it ``tz_offset`` already contributes - baking the full offset in regardless
    of ``tz_offset`` double-counts it (upstream issue #13: at UTC+3 with
    ``tz_offset=3`` the clock ran three hours fast).

    ``now_factory`` is injected only so the behaviour can be tested; in
    production it defaults to Home Assistant's own time zone, never the host
    OS one (containerized installs usually keep the OS on UTC, which made the
    clock wrong by the DST offset).
    """
    if now_factory is None:
        from homeassistant.util import dt as dt_util

        now_factory = dt_util.now

    now = int(time.time())
    offset = now_factory().utcoffset()
    if offset is None:  # pragma: no cover - a tz-aware datetime always has one
        return now
    return now + int(offset.total_seconds()) - tz_offset * 3600


def parse_sync_time(value: Any) -> tuple[int, int, int] | None:
    """Parse ``HH:MM`` or ``HH:MM:SS`` into ``(hour, minute, second)``."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour, minute, second


def next_sync_time(sync_time: Any, now):
    """Return the next occurrence of ``sync_time`` strictly after ``now``."""
    parsed = parse_sync_time(sync_time)
    if parsed is None:
        return None
    hour, minute, second = parsed
    candidate = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def as_int(value: Any) -> int | None:
    """Convert an option value to int, tolerating ``none``/empty values."""
    if value in (None, "", "none"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def should_skip_resync(
    last_attempt,
    now,
    trigger: str,
    *,
    min_interval: float,
    manual_trigger: str,
) -> bool:
    """Garde-fou anti-boucle : faut-il ignorer cette synchronisation ?

    Une synchronisation *automatique* (planificateur, démarrage) est ignorée si
    une tentative a eu lieu il y a moins de ``min_interval`` secondes. L'écriture
    est idempotente, donc le pire cas sans ce garde-fou serait bénin - mais il
    rend toute boucle structurellement impossible, y compris si deux
    déclencheurs tombent en même temps ou si un changement d'heure provoque un
    double tir.

    Une synchronisation *manuelle* (bouton, intention explicite de
    l'utilisateur) n'est jamais ignorée.
    """
    if trigger == manual_trigger or last_attempt is None:
        return False
    return (now - last_attempt).total_seconds() < min_interval


def options_for(entry) -> dict[str, Any]:
    """Return the effective options of an entry (options override data)."""
    merged = {**(entry.data or {}), **(entry.options or {})}
    merged.setdefault(CONF_SYNC_ENABLED, DEFAULT_SYNC_ENABLED)
    merged.setdefault(CONF_SYNC_TIME, DEFAULT_SYNC_TIME)
    merged.setdefault(CONF_SYNC_ON_START, DEFAULT_SYNC_ON_START)
    merged.setdefault(CONF_TEMP_MODE, DEFAULT_TEMP_MODE)
    merged.setdefault(CONF_CLOCK_MODE, DEFAULT_CLOCK_MODE)
    merged.setdefault(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    return merged


# --- Decouverte : identification du modele depuis l'annonce MiBeacon --------
#
# Mesure du 08/10/2026 sur l'horloge E7:2E:01:01:DC:29 : l'annonce BLE ne
# contient AUCUN nom (advertisement.name = None) ; seul le service data
# MiBeacon 0000fe95-... est present. Un matcher de manifest sur `local_name`
# ne peut donc JAMAIS se declencher (bug corrige en 0.4.2).
# On identifie le modele en analysant la charge utile avec la bibliotheque
# officielle `xiaomi-ble` (celle de l'integration Xiaomi BLE de Home Assistant),
# dont le titre porte le modele entre parentheses :
#   "Temperature/Humidity Sensor DC29 (LYWSD02)"
# Ces deux fonctions restent pures (aucun import Home Assistant) : elles sont
# testees hors Home Assistant avec le titre reellement observe.

SUPPORTED_MODELS = ("LYWSD02", "LYWSD02MMC")
ENCRYPTED_MODELS = ("LYWSD02MMC",)  # MiBeacon chiffre : exige une bindkey

_TITLE_MODEL_RE = re.compile(r"\(([A-Za-z0-9_-]+)\)\s*$")


def model_from_title(title: str | None) -> str | None:
    """Modele supporte annonce dans un titre xiaomi-ble, sinon None."""
    if not title:
        return None
    match = _TITLE_MODEL_RE.search(title.strip())
    if match is None:
        return None
    model = match.group(1).upper()
    return model if model in SUPPORTED_MODELS else None


def device_name_from_title(title: str | None, fallback: str = "") -> str:
    """Nom lisible d'un titre xiaomi-ble, sans son suffixe de modele."""
    if not title:
        return fallback
    return _TITLE_MODEL_RE.sub("", title.strip()).strip() or fallback


# --- Reprise d'etat au redemarrage -----------------------------------------
#
# Les compteurs de diagnostic vivent en memoire : au redemarrage de Home
# Assistant le capteur retombait a « inconnu » alors que l'horloge venait
# d'etre reglee, et l'information « la derniere synchro a echoue » etait perdue.
# La fonction ci-dessous reinjecte le dernier etat connu, en refusant tout ce
# qui pourrait fausser le diagnostic.

ETATS_ABSENTS = (None, "", "unknown", "unavailable")


def apply_restored_state(runtime, state_value: object, attributes: dict | None = None) -> bool:
    """Reinjecte le dernier etat connu d'une synchro reussie. Retourne True si applique.

    Regles volontaires :

    * une synchro deja effectuee depuis le demarrage **gagne** (on ne reecrit
      jamais une information fraiche avec une information ancienne) ;
    * ``last_attempt`` n'est **jamais** restaure : le garde-fou anti-boucle doit
      repartir vierge, sinon la synchro de demarrage serait ignoree apres chaque
      redemarrage (elle tomberait dans la fenetre des 5 minutes) ;
    * une date sans fuseau est refusee (Home Assistant ecrit toujours un
      horodatage ISO avec decalage) ;
    * ``unknown`` / ``unavailable`` / vide ne restaurent rien.
    """
    if getattr(runtime, "last_sync", None) is not None:
        return False
    if state_value in ETATS_ABSENTS:
        return False
    try:
        restored = datetime.fromisoformat(str(state_value))
    except ValueError:
        return False
    if restored.tzinfo is None:
        return False

    runtime.last_sync = restored
    attrs = attributes or {}
    if attrs.get("result") is not None:
        runtime.result = attrs["result"]
    if attrs.get("last_trigger") is not None:
        runtime.last_trigger = attrs["last_trigger"]
    if isinstance(attrs.get("duration_ms"), int):
        runtime.duration_ms = attrs["duration_ms"]
    runtime.last_error = attrs.get("last_error") or None
    return True
