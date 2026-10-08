"""Tests de la decouverte Bluetooth.

Contient le test de regression qui aurait attrape le bug corrige en 0.4.2 :
un matcher `local_name` ne peut jamais se declencher sur cette horloge, dont
l'annonce BLE ne porte aucun nom (mesure : advertisement.name = None).

Lancer : python3 tests/test_discovery.py
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import time
import types as _types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
COMPOSANT = RACINE / "custom_components" / "lywsd02"
sys.path.insert(0, str(COMPOSANT.parent))

# helpers.py importe un paquet relatif (.const) : on charge le paquet a la main

# const.py importe Platform depuis Home Assistant : on fournit le strict
# minimum pour pouvoir tester ces modules hors Home Assistant (meme procede que
# tests/test_sync_logic.py).
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

pkg = _types.ModuleType("lywsd02pkg")
pkg.__path__ = [str(COMPOSANT)]
sys.modules["lywsd02pkg"] = pkg
for nom in ("const", "helpers"):
    s = importlib.util.spec_from_file_location(f"lywsd02pkg.{nom}", COMPOSANT / f"{nom}.py")
    m = importlib.util.module_from_spec(s)
    sys.modules[f"lywsd02pkg.{nom}"] = m
    s.loader.exec_module(m)

helpers = sys.modules["lywsd02pkg.helpers"]

# Charge utile REELLE de l'horloge de Rich, lue dans les diagnostics de Home
# Assistant le 08/10/2026 (service data MiBeacon 0xFE95).
CHARGE_UTILE_REELLE = bytes([0x70, 0x20, 0x5b, 0x04, 0xf9, 0x29, 0xdc, 0x01, 0x01,
                            0x2e, 0xe7, 0x09, 0x06, 0x10, 0x02, 0xbc, 0x02])
MAC_REELLE = "E7:2E:01:01:DC:29"
# Titres reellement produits par xiaomi-ble pour les appareils de Rich
TITRE_REELLE = "Temperature/Humidity Sensor DC29 (LYWSD02)"
AUTRES_TITRES = (
    "Temperature/Humidity Sensor BB89 (LYWSDCGQ)",
    "Plant Sensor DF8B (HHCCJCY01)",
    "Mi Smart Scale (917A)",
)
UUID_MIBEACON = "0000fe95-0000-1000-8000-00805f9b34fb"


@dataclasses.dataclass
class FausseAnnonce:
    """Duck-type de BluetoothServiceInfo pour interroger xiaomi-ble."""

    address: str = MAC_REELLE
    name: str = ""
    service_data: dict = dataclasses.field(default_factory=dict)
    manufacturer_data: dict = dataclasses.field(default_factory=dict)
    service_uuids: list = dataclasses.field(default_factory=list)
    rssi: int = -87
    time: float = 0.0
    connectable: bool = True


def test_le_modele_est_reconnu_sur_la_charge_utile_reelle():
    """xiaomi-ble identifie LYWSD02 sur les octets reellement emis."""
    try:
        from xiaomi_ble import XiaomiBluetoothDeviceData
    except ImportError:
        print("    (xiaomi-ble absent : test ignore)")
        return
    annonce = FausseAnnonce(
        service_data={UUID_MIBEACON: CHARGE_UTILE_REELLE},
        service_uuids=["0000181a-0000-1000-8000-00805f9b34fb"],
        time=time.time(),
    )
    appareil = XiaomiBluetoothDeviceData()
    assert appareil.supported(annonce), "la charge utile reelle doit etre prise en charge"
    titre = appareil.title or appareil.get_device_name()
    assert titre == TITRE_REELLE, f"titre inattendu : {titre!r}"
    assert helpers.model_from_title(titre) == "LYWSD02"
    assert helpers.device_name_from_title(titre) == "Temperature/Humidity Sensor DC29"
    assert str(appareil.encryption_scheme).endswith("NONE"), "horloge non chiffree"


def test_le_nom_est_absent_de_l_annonce():
    """La charge utile ne porte pas de nom : d'ou le matcher de manifest."""
    assert b"LYWSD02" not in CHARGE_UTILE_REELLE.upper()
    # 0x20 0x70 = version MiBeacon, 0x045b = identifiant produit
    assert CHARGE_UTILE_REELLE[0:2] == bytes([0x70, 0x20])
    assert int.from_bytes(CHARGE_UTILE_REELLE[2:4], "little") == 0x045B


def test_seuls_les_modeles_supportes_sont_retenus():
    assert helpers.model_from_title(TITRE_REELLE) == "LYWSD02"
    assert helpers.model_from_title("Temperature/Humidity Sensor X (LYWSD02MMC)") == "LYWSD02MMC"
    for titre in AUTRES_TITRES:
        assert helpers.model_from_title(titre) is None, f"{titre!r} ne doit pas etre retenu"
    for vide in ("", None, "sans modele", "( )"):
        assert helpers.model_from_title(vide) is None


def test_nom_de_repli_quand_le_titre_est_absent():
    assert helpers.device_name_from_title(None, MAC_REELLE) == MAC_REELLE
    assert helpers.device_name_from_title("", MAC_REELLE) == MAC_REELLE
    assert helpers.device_name_from_title("(LYWSD02)", MAC_REELLE) == MAC_REELLE


def test_le_manifest_ne_depend_pas_d_un_nom_qui_n_existe_pas():
    """Regression 0.4.2 : un matcher local_name ne se declencherait jamais."""
    manifest = json.loads((COMPOSANT / "manifest.json").read_text())
    matchers = manifest.get("bluetooth") or []
    assert matchers, "le manifest doit declarer un matcher Bluetooth"
    for matcher in matchers:
        assert "local_name" not in matcher, (
            "l'annonce de ces horloges ne contient aucun nom : un matcher "
            "local_name ne se declencherait jamais"
        )
        assert matcher.get("service_data_uuid") == UUID_MIBEACON
        assert matcher.get("connectable") is True, "la synchro exige une liaison connectable"


def test_le_manifest_declare_les_bonnes_dependances():
    """bluetooth_adapters est une integration, pas un paquet pip."""
    manifest = json.loads((COMPOSANT / "manifest.json").read_text())
    assert "bluetooth_adapters" in manifest["dependencies"]
    assert "bluetooth" in manifest["dependencies"]
    assert not [r for r in manifest["requirements"] if r.startswith("bluetooth")], (
        "une integration ne se declare pas dans requirements"
    )
    assert any(r.startswith("xiaomi-ble") for r in manifest["requirements"])
    assert any(r.startswith("bleak-retry-connector") for r in manifest["requirements"])
    # dependance non epinglee : la version deja installee avec Home Assistant
    assert "xiaomi-ble" in manifest["requirements"]


def test_la_version_est_a_jour_partout():
    """manifest et const doivent annoncer la meme version."""
    manifest = json.loads((COMPOSANT / "manifest.json").read_text())
    sys.modules["lywsd02pkg.const"].__dict__.get("VERSION")
    assert manifest["version"].count(".") == 2


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
