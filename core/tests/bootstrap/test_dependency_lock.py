"""Tests pour core/scripts/verify_dependencies.py (C02-002).

Couvre les 3 cas RED obligatoires de tasks/C02-002.md :
  1. déclarer PyYAML si importé
  2. refuser dépendance flottante
  3. refuser paquet sans hash pour profil air-gap

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core — verify_lock() est le contrat qui garantit
qu'aucune dépendance Core n'est installée sans version exacte, sans hash
(profil air-gap), ni utilisée sans être déclarée.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from verify_dependencies import LockReport, verify_lock  # noqa: E402


def _ecrire(chemin: Path, texte: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")


# ---------------------------------------------------------------------------
# Cas RED 1 — déclarer PyYAML si importé
# ---------------------------------------------------------------------------


def test_cr_er_les_manifests_et_locks_de_d_pendances_reproductibles_1(tmp_path):
    """Un module sous core/ qui importe yaml (PyYAML) sans que pyproject.toml
    ne le déclare dans ses dépendances doit être signalé — jamais une
    dépendance implicite qui marche « par hasard » parce qu'un autre paquet
    l'a installée en transitif."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = []\n')
    _ecrire(lock, "")
    _ecrire(core / "scripts" / "un_module.py", "import yaml\n\ndef f():\n    return yaml.safe_load('a: 1')\n")

    rapport = verify_lock(pyproject, lock)
    assert isinstance(rapport, LockReport)
    assert rapport.ok is False
    assert any("PyYAML" in e or "yaml" in e for e in rapport.declared_but_undeclared_imports)

    # Contrôle : PyYAML déclarée -> plus de signalement pour CE motif.
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = ["PyYAML==6.0.2"]\n')
    _ecrire(lock, "PyYAML==6.0.2 --hash=sha256:" + "a" * 64 + "\n")
    rapport_ok = verify_lock(pyproject, lock)
    assert rapport_ok.declared_but_undeclared_imports == []


def test_import_non_mappe_est_ignore_sans_planter(tmp_path):
    """Un import stdlib (json, pathlib) ou d'un module local ne doit jamais
    être confondu avec une dépendance PyPI manquante — seuls les imports
    présents dans la table de correspondance connue (yaml -> PyYAML) sont
    évalués ; les autres sont silencieusement ignorés par CE contrôle."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = []\n')
    _ecrire(lock, "")
    _ecrire(core / "scripts" / "un_module.py", "import json\nimport pathlib\nfrom collections import OrderedDict\n")

    rapport = verify_lock(pyproject, lock)
    assert rapport.declared_but_undeclared_imports == []


# ---------------------------------------------------------------------------
# Cas RED 2 — refuser dépendance flottante
# ---------------------------------------------------------------------------


def test_cr_er_les_manifests_et_locks_de_d_pendances_reproductibles_2(tmp_path):
    """Une dépendance exprimée en plage/wildcard dans le lock (>=, ~=, *,
    ^) n'est pas reproductible — un `pip install` demain peut résoudre un
    binaire différent d'aujourd'hui. Refusée, jamais acceptée comme
    « assez proche »."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = ["requests"]\n')
    _ecrire(lock, "requests>=2.31.0 --hash=sha256:" + "b" * 64 + "\n")

    rapport = verify_lock(pyproject, lock)
    assert rapport.ok is False
    assert any("requests" in e for e in rapport.floating_dependencies)

    # Contrôle : version exacte -> plus de signalement pour CE motif.
    _ecrire(lock, "requests==2.31.0 --hash=sha256:" + "b" * 64 + "\n")
    rapport_ok = verify_lock(pyproject, lock)
    assert rapport_ok.floating_dependencies == []


def test_plusieurs_motifs_de_plage_tous_detectes(tmp_path):
    """~=, *, ^ (pas seulement >=) doivent tous être détectés comme
    flottants — une liste blanche de motifs, pas une liste noire d'un
    seul symbole."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = ["a", "b", "c"]\n')
    hash_valide = "--hash=sha256:" + "c" * 64
    _ecrire(lock, f"a~=1.0 {hash_valide}\nb==2.0.* {hash_valide}\nc^3.0 {hash_valide}\n")

    rapport = verify_lock(pyproject, lock)
    noms_flottants = {e.split()[0] if " " in e else e for e in rapport.floating_dependencies}
    for nom in ("a", "b", "c"):
        assert any(nom in e for e in rapport.floating_dependencies), f"{nom} flottant non détecté: {rapport.floating_dependencies}"


# ---------------------------------------------------------------------------
# Cas RED 3 — refuser paquet sans hash pour profil air-gap
# ---------------------------------------------------------------------------


def test_cr_er_les_manifests_et_locks_de_d_pendances_reproductibles_3(tmp_path):
    """Un paquet du lock sans --hash=sha256:... ne peut jamais être installé
    en profil air-gap (pip --require-hashes refuserait de toute façon) —
    signalé nommément, jamais une entrée silencieusement acceptée."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = ["click"]\n')
    _ecrire(lock, "click==8.1.7\n")

    rapport = verify_lock(pyproject, lock)
    assert rapport.ok is False
    assert any("click" in e for e in rapport.missing_hash_packages)

    # Contrôle : hash présent -> plus de signalement pour CE motif.
    _ecrire(lock, "click==8.1.7 --hash=sha256:" + "d" * 64 + "\n")
    rapport_ok = verify_lock(pyproject, lock)
    assert rapport_ok.missing_hash_packages == []


def test_hash_mal_forme_refuse_aussi(tmp_path):
    """Un `--hash=` présent mais tronqué/mal formé (pas 64 hex) ne prouve
    rien de plus qu'une absence — refusé comme les paquets sans hash."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = ["click"]\n')
    _ecrire(lock, "click==8.1.7 --hash=sha256:tronque\n")

    rapport = verify_lock(pyproject, lock)
    assert any("click" in e for e in rapport.missing_hash_packages)


# ---------------------------------------------------------------------------
# Robustesse structurelle
# ---------------------------------------------------------------------------


def test_lockreport_est_gele(tmp_path):
    """LockReport est immuable — un rapport ne doit pas pouvoir être
    réécrit après coup pour fabriquer une conformité."""
    import pytest

    rapport = LockReport(declared_but_undeclared_imports=[], floating_dependencies=[], missing_hash_packages=[])
    with pytest.raises(Exception):
        rapport.floating_dependencies = ["x"]


def test_pyproject_absent_devient_erreur_nommee_jamais_exception_brute(tmp_path):
    """Un pyproject.toml absent ne doit jamais lever une exception non
    gérée (FileNotFoundError brute) — la fonction reste fail-closed avec
    un rapport signalant l'absence, exploitable par l'appelant."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(lock, "")

    rapport = verify_lock(pyproject, lock)
    assert rapport.ok is False


def test_lock_vide_sans_dependance_declaree_est_ok(tmp_path):
    """Aucune dépendance déclarée, aucun paquet dans le lock, aucun import
    à mapper : cas nominal vide, ne doit jamais être signalé à tort."""
    core = tmp_path / "core"
    pyproject = core / "pyproject.toml"
    lock = core / "requirements.lock"
    _ecrire(pyproject, '[project]\nname = "opsys-core"\ndependencies = []\n')
    _ecrire(lock, "")

    rapport = verify_lock(pyproject, lock)
    assert rapport.ok is True
