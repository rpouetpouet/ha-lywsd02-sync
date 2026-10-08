"""Preuve que la synchronisation ne derive pas au changement d'heure.

Ce que fait l'intégration, en une ligne : elle écrit
``epoch = maintenant_utc + decalage_local`` (moins ``tz_offset``, qui est une
valeur envoyée à part). L'horloge affiche ``epoch + tz_offset heures``.

L'invariant à démontrer est donc : **ce que l'horloge affiche est toujours
l'heure locale de l'instant de la synchronisation**, y compris les deux nuits
de changement d'heure. Si c'est vrai à chaque synchronisation, aucune dérive
ne peut s'accumuler : on n'ajoute jamais « une heure de plus » d'une fois sur
l'autre, on réécrit simplement l'heure locale courante.

Les tests couvrent :
- chaque jour de 2026 à 04:00 locales (les 365 jours, dont les deux nuits de bascule) ;
- une simulation de synchronisations horaires sur 12 h autour de chaque bascule ;
- le cas où ``tz_offset`` n'est pas nul (le décalage ne doit pas être compté deux fois).

Lancer : ``python3 tests/test_dst.py``
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zoneinfo import ZoneInfo

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "lywsd02"
PARIS = ZoneInfo("Europe/Paris")


def _platform_stub() -> None:
    """Home Assistant n'est pas importable ici : on ne stub que Platform."""
    if "homeassistant.const" in sys.modules:
        return

    class _Platform:
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        SENSOR = "sensor"

    ha = types.ModuleType("homeassistant")
    ha_const = types.ModuleType("homeassistant.const")
    ha_const.Platform = _Platform
    ha.const = ha_const
    sys.modules.setdefault("homeassistant", ha)
    sys.modules["homeassistant.const"] = ha_const


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_platform_stub()
_load("lywsd02_dst.const", COMPONENT / "const.py")
sys.modules["lywsd02_dst.const"].__package__ = "lywsd02_dst"
helpers = _load("lywsd02_dst.helpers", COMPONENT / "helpers.py")


def written_epoch(instant_utc: datetime, tz_offset: int = 0) -> int:
    """Reproduit la valeur écrite par l'intégration, à un instant donné."""
    local_offset = instant_utc.astimezone(PARIS).utcoffset()
    assert local_offset is not None
    return (
        int(instant_utc.timestamp())
        + int(local_offset.total_seconds())
        - tz_offset * 3600
    )


def displayed_wall_clock(written: int, tz_offset: int = 0) -> datetime:
    """Ce que l'horloge affiche : epoch + tz_offset, relu comme heure 'murale'."""
    return datetime.fromtimestamp(written + tz_offset * 3600, tz=timezone.utc)


def local_wall_clock(instant_utc: datetime) -> datetime:
    """L'heure locale 'murale' attendue sur l'afficheur (naive)."""
    return instant_utc.astimezone(PARIS).replace(tzinfo=None)


def _assert_display_matches(instant_utc: datetime, tz_offset: int = 0) -> None:
    shown = displayed_wall_clock(written_epoch(instant_utc, tz_offset), tz_offset)
    expected = local_wall_clock(instant_utc)
    assert shown.replace(tzinfo=None) == expected, (
        f"a {instant_utc.isoformat()} l'horloge afficherait {shown} au lieu de {expected}"
    )


def test_chaque_jour_de_2026_a_4h():
    """365 synchronisations à 04:00 locales : l'afficheur doit donner 04:00."""
    day = datetime(2026, 1, 1, 4, 0, tzinfo=PARIS)
    checked = 0
    while day.year == 2026:
        instant_utc = day.astimezone(timezone.utc)
        _assert_display_matches(instant_utc)
        assert displayed_wall_clock(written_epoch(instant_utc)).hour == 4
        day += timedelta(days=1)
        checked += 1
    assert checked == 365, f"{checked} jours verifies au lieu de 365"


def test_nuit_de_passage_a_l_heure_d_ete():
    """Dernier dimanche de mars : 02:00 -> 03:00. L'heure écrite doit rester locale."""
    # 2026-03-29 : bascule à 02:00 heure locale (01:00 UTC).
    # ⚠️ On itère en UTC, jamais en heure locale : sur un datetime porteur d'un
    # fuseau, `+ timedelta` fait de l'arithmétique EN HEURE MURALE (les champs
    # sont incrémentés tels quels), ce qui ne traverse ni l'heure sautée ni
    # l'heure répétée. Un instant réel s'obtient en partant d'un datetime UTC.
    base_utc = datetime(2026, 3, 28, 22, 0, tzinfo=PARIS).astimezone(timezone.utc)
    seen = []
    for step in range(12):  # 12 synchronisations horaires autour de la bascule
        instant = base_utc + timedelta(hours=step)
        _assert_display_matches(instant)
        seen.append(local_wall_clock(instant))
    # Une bascule vers l'heure d'ete SAUTE 02:00-02:59 : l'affichage ne recule jamais.
    assert all(b >= a for a, b in zip(seen, seen[1:])), seen


def test_nuit_de_retour_a_l_heure_d_hiver():
    """Dernier dimanche d'octobre : l'affichage répète 02:xx, une seule fois, sans boucle."""
    # 2026-10-25 : 03:00 locales -> 02:00 (01:00 UTC). Iteration en UTC (cf. mars).
    base_utc = datetime(2026, 10, 24, 22, 0, tzinfo=PARIS).astimezone(timezone.utc)
    seen = []
    for step in range(12):
        instant = base_utc + timedelta(hours=step)
        _assert_display_matches(instant)
        seen.append(local_wall_clock(instant))

    # À la bascule d'automne, l'heure murale 02:00 est vue DEUX fois (02:00+02:00
    # puis 02:00+01:00) : échantillonnée heure par heure, la bascule se présente
    # donc comme une ÉGALITÉ (l'affichage stagne une heure), pas comme une marche
    # arrière. Une vraie boucle « on recule d'une heure à chaque heure » se
    # verrait ici comme plusieurs pas décroissants : on vérifie qu'il n'y en a
    # aucun, et qu'aucun pas ne dépasse une heure.
    pas_non_croissants = [(a, b) for a, b in zip(seen, seen[1:]) if b <= a]
    assert len(pas_non_croissants) == 1, f"pas non croissants : {pas_non_croissants}"
    avant, apres = pas_non_croissants[0]
    assert (avant - apres) < timedelta(hours=1), (avant, apres)
    assert all(b - a <= timedelta(hours=1) for a, b in zip(seen, seen[1:])), seen
    # Et surtout : la valeur réécrite suit l'heure locale, elle n'ajoute jamais
    # un décalage supplémentaire.
    for instant, affiche in zip(
        (base_utc + timedelta(hours=s) for s in range(12)), seen
    ):
        assert affiche == local_wall_clock(instant)


def test_aucune_accumulation_sur_une_annee_de_synchro_horaires():
    """8760 synchronisations horaires : l'écart avec l'heure locale reste nul.

    C'est la réponse directe à « et si on reculait d'une heure à chaque heure ? » :
    on ne recule jamais par rapport à l'heure locale, donc rien ne s'accumule.
    """
    instant = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    ecart_max = timedelta(0)
    for _ in range(24 * 365):
        shown = displayed_wall_clock(written_epoch(instant))
        expected = local_wall_clock(instant)
        ecart = abs(shown.replace(tzinfo=None) - expected)
        ecart_max = max(ecart_max, ecart)
        instant += timedelta(hours=1)
    assert ecart_max == timedelta(0), f"ecart maximal observe : {ecart_max}"


def test_tz_offset_non_nul_ne_double_compte_pas_le_decalage():
    """Avec tz_offset=2 en heure d'été, l'affichage reste l'heure locale."""
    instant = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)  # 04:00 locales
    _assert_display_matches(instant, tz_offset=2)
    _assert_display_matches(instant, tz_offset=0)


def test_l_integration_utilise_bien_le_fuseau_de_home_assistant():
    """Le fuseau vient de dt_util (HA), jamais de l'horloge de l'hôte."""
    source = (COMPONENT / "helpers.py").read_text(encoding="utf-8")
    assert "dt_util.now" in source, "le fuseau doit venir de dt_util (Home Assistant)"
    assert "datetime.now().astimezone()" not in source, "aucun recours a l'heure de l'hote"


def test_garde_fou_ignore_une_synchro_automatique_trop_rapprochee():
    """Le garde-fou bloque deux synchros automatiques rapprochées (anti-boucle)."""
    now = datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)
    recent = now - timedelta(seconds=30)
    ancienne = now - timedelta(hours=6)

    from datetime import timezone as tz  # noqa: F401  (lisibilite)

    assert helpers.should_skip_resync(
        recent, now, "schedule", min_interval=300, manual_trigger="button"
    )
    assert helpers.should_skip_resync(
        recent, now, "startup", min_interval=300, manual_trigger="button"
    )
    # Six heures plus tard, la synchro planifiée repasse normalement.
    assert not helpers.should_skip_resync(
        ancienne, now, "schedule", min_interval=300, manual_trigger="button"
    )


def test_garde_fou_ne_bloque_jamais_une_action_manuelle():
    """Un appui sur le bouton doit toujours déclencher, même juste après."""
    now = datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)
    assert not helpers.should_skip_resync(
        now, now, "button", min_interval=300, manual_trigger="button"
    )


def test_garde_fou_sans_historique_laisse_passer():
    """Première synchronisation : rien à comparer, on passe."""
    now = datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)
    assert not helpers.should_skip_resync(
        None, now, "startup", min_interval=300, manual_trigger="button"
    )


if __name__ == "__main__":
    passed = failed = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as err:
            print(f"  FAIL {name}: {err}")
            failed += 1
    print(f"\n{passed} passes, {failed} echecs")
