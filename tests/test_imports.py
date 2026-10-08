"""Test statique : aucune constante utilisee ne doit manquer a l'import.

Motif reel : un garde-fou utilisait ``TRIGGER_BUTTON`` sans l'avoir importe.
``py_compile`` ne voit rien (ce n'est pas une erreur de syntaxe) et les tests de
logique pure non plus (le module fautif n'est importable que dans Home
Assistant). Ce test analyse l'AST et compare les constantes *utilisees* aux noms
*disponibles* dans chaque fichier - il attrape donc ce bug avant le deploiement.

Lancer : ``python3 tests/test_imports.py``
"""

from __future__ import annotations

import ast
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "lywsd02"

# Prefixes des constantes definies dans const.py
PREFIXES = (
    "CONF_",
    "DEFAULT_",
    "TRIGGER_",
    "RESULT_",
    "UUID_",
    "MIN_",
    "STARTUP_",
    "SIGNAL_",
    "DOMAIN",
    "PLATFORMS",
    "RESULT_",
)

MODULES = ("__init__.py", "button.py", "sensor.py", "binary_sensor.py", "config_flow.py", "helpers.py")


def _available_names(tree: ast.AST) -> set[str]:
    """Tous les noms definis ou importes au niveau du fichier."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {(alias.asname or alias.name) for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_constantes_utilisees_toutes_importees():
    """Chaque constante utilisee dans un module doit y etre importee ou definie."""
    problems: list[str] = []
    for module in MODULES:
        path = COMPONENT / module
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        available = _available_names(tree)
        used = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id.startswith(PREFIXES)
        }
        missing = sorted(used - available)
        if missing:
            problems.append(f"{module}: {missing}")
    assert not problems, "constantes utilisees mais non importees -> " + " | ".join(problems)


def test_const_py_contient_bien_les_constantes():
    """Les constantes attendues existent dans const.py (garde-fou de coherence)."""
    tree = ast.parse((COMPONENT / "const.py").read_text(encoding="utf-8"))
    available = _available_names(tree)
    for expected in (
        "CONF_SYNC_ENABLED",
        "CONF_SYNC_TIME",
        "CONF_SYNC_ON_START",
        "CONF_TEMP_MODE",
        "CONF_CLOCK_MODE",
        "CONF_TIMEOUT",
        "TRIGGER_BUTTON",
        "TRIGGER_SCHEDULE",
        "TRIGGER_STARTUP",
        "RESULT_OK",
        "RESULT_ERROR",
        "RESULT_PENDING",
        "MIN_RESYNC_INTERVAL",
        "SIGNAL_UPDATE",
        "UUID_TIME",
        "UUID_TEMP_MODE",
        "PLATFORMS",
    ):
        assert expected in available, f"{expected} absent de const.py"


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
