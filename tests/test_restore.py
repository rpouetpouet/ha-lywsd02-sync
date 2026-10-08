"""Reprise de l'etat de synchro au redemarrage de Home Assistant.

Les compteurs vivent en memoire : sans reprise, le capteur de diagnostic
retombait a « inconnu » a chaque redemarrage alors que l'horloge venait d'etre
reglee, et un echec memorise etait oublie.

Lancer : python3 tests/test_restore.py
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import types as _types
from pathlib import Path

COMPOSANT = Path(__file__).resolve().parents[1] / "custom_components" / "lywsd02"

if "homeassistant.const" not in sys.modules:
    _ha = _types.ModuleType("homeassistant")
    _ha_const = _types.ModuleType("homeassistant.const")

    class _Platform(str):
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"

    _ha_const.Platform = _Platform
    _ha.const = _ha_const
    sys.modules["homeassistant"] = _ha
    sys.modules["homeassistant.const"] = _ha_const

pkg = _types.ModuleType("pkg_restore")
pkg.__path__ = [str(COMPOSANT)]
sys.modules["pkg_restore"] = pkg
for nom in ("const", "helpers"):
    spec = importlib.util.spec_from_file_location(f"pkg_restore.{nom}", COMPOSANT / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"pkg_restore.{nom}"] = module
    spec.loader.exec_module(module)

helpers = sys.modules["pkg_restore.helpers"]


@dataclasses.dataclass
class FauxRuntime:
    """Meme surface que LywsdRuntimeData, sans Home Assistant."""

    last_sync: object = None
    result: str = "pending"
    last_trigger: object = None
    duration_ms: object = None
    last_error: object = None
    last_attempt: object = None
    sync_count: int = 0
    skipped_count: int = 0


ETAT_OK = {
    "result": "ok",
    "last_trigger": "button",
    "duration_ms": 7827,
    "last_error": None,
}


def test_reprise_d_une_synchro_reussie():
    runtime = FauxRuntime()
    ok = helpers.apply_restored_state(runtime, "2026-10-08T20:48:10+00:00", ETAT_OK)
    assert ok is True
    assert runtime.last_sync is not None
    assert runtime.last_sync.isoformat() == "2026-10-08T20:48:10+00:00"
    assert runtime.result == "ok"
    assert runtime.last_trigger == "button"
    assert runtime.duration_ms == 7827
    assert runtime.last_error is None


def test_reprise_d_un_echec_conserve_le_probleme():
    runtime = FauxRuntime()
    ok = helpers.apply_restored_state(
        runtime,
        "2026-10-08T20:48:10+00:00",
        {"result": "error", "last_error": "no connectable path", "duration_ms": 60000},
    )
    assert ok is True
    assert runtime.result == "error"
    assert runtime.last_error == "no connectable path"


def test_etat_absent_ne_restaure_rien():
    for valeur in (None, "", "unknown", "unavailable"):
        runtime = FauxRuntime()
        assert helpers.apply_restored_state(runtime, valeur, ETAT_OK) is False
        assert runtime.last_sync is None
        assert runtime.result == "pending"


def test_date_sans_fuseau_refusee():
    runtime = FauxRuntime()
    assert helpers.apply_restored_state(runtime, "2026-10-08 20:48:10", ETAT_OK) is False
    assert runtime.last_sync is None


def test_une_synchro_fraiche_gagne_sur_l_etat_restaure():
    """Ne jamais reecrire une information fraiche avec une information ancienne."""
    runtime = FauxRuntime(last_sync=None, result="ok")
    import datetime as _dt

    frais = _dt.datetime(2026, 10, 9, 4, 0, 5, tzinfo=_dt.timezone.utc)
    runtime.last_sync = frais
    runtime.result = "ok"
    assert helpers.apply_restored_state(runtime, "2026-10-08T20:48:10+00:00", ETAT_OK) is False
    assert runtime.last_sync == frais


def test_le_garde_fou_repart_vierge():
    """last_attempt ne doit JAMAIS etre restaure, sinon la synchro de demarrage
    tomberait dans la fenetre des 5 minutes a chaque redemarrage."""
    runtime = FauxRuntime()
    helpers.apply_restored_state(runtime, "2026-10-08T20:48:10+00:00", ETAT_OK)
    assert runtime.last_attempt is None
    # consequence : une synchro de demarrage n'est pas ignoree
    import datetime as _dt

    maintenant = _dt.datetime(2026, 10, 9, 4, 0, 0, tzinfo=_dt.timezone.utc)
    assert (
        helpers.should_skip_resync(
            runtime.last_attempt,
            maintenant,
            "startup",
            min_interval=helpers.MIN_RESYNC_INTERVAL
            if hasattr(helpers, "MIN_RESYNC_INTERVAL")
            else 300,
            manual_trigger="button",
        )
        is False
    )


def test_compteurs_non_restaures():
    """Les compteurs cumules repartent de zero : ils mesurent la session."""
    runtime = FauxRuntime()
    helpers.apply_restored_state(runtime, "2026-10-08T20:48:10+00:00", ETAT_OK)
    assert runtime.sync_count == 0
    assert runtime.skipped_count == 0


if __name__ == "__main__":
    passes = echecs = 0
    for nom in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[nom]()
            print(f"  PASS {nom}")
            passes += 1
        except AssertionError as err:
            print(f"  FAIL {nom}: {err}")
            echecs += 1
    print(f"\n{passes} passes, {echecs} echecs")
    sys.exit(1 if echecs else 0)
