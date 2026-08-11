"""Tests pour core/scripts/bootstrap_toolchain.py (C02-001).

Couvre les 3 cas RED obligatoires de tasks/C02-001.md :
  1. refuser version non exacte
  2. refuser digest absent
  3. détecter binaire différent de la lock

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core — un ToolchainLock est le contrat qui
garantit qu'un tool inventorié aujourd'hui est LE MÊME BINAIRE demain,
jamais une version approximative ni un binaire substitué silencieusement.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from bootstrap_toolchain import (  # noqa: E402
    ToolSpec,
    ToolchainLock,
    detect_drift,
    inventorier_toolchain,
    validate_toolchain_lock,
)


# ---------------------------------------------------------------------------
# Cas RED 1 — refuser version non exacte
# ---------------------------------------------------------------------------


def test_pinner_la_toolchain_core_1():
    """Une version exprimée en plage/wildcard (>=3.12, 3.*, ^3.12, ~3.12)
    n'est PAS une version exacte — un ToolchainLock qui en contient une
    doit être refusé, jamais silencieusement accepté comme « assez proche »."""
    lock_range = ToolchainLock(
        tools={"python": ToolSpec(version=">=3.12", digest="a" * 64)}
    )
    erreurs = validate_toolchain_lock(lock_range)
    assert erreurs, "une version en plage doit produire au moins une erreur"
    assert any("python" in e and "version" in e for e in erreurs)

    lock_wildcard = ToolchainLock(
        tools={"python": ToolSpec(version="3.*", digest="a" * 64)}
    )
    assert validate_toolchain_lock(lock_wildcard)

    # Version exacte : aucune erreur de CE type (le digest est valide ici,
    # donc la liste d'erreurs est vide pour cet outil).
    lock_exact = ToolchainLock(
        tools={"python": ToolSpec(version="3.12.3", digest="a" * 64)}
    )
    assert validate_toolchain_lock(lock_exact) == []


def test_version_avec_suffixe_pre_release_refusee():
    """Une version avec suffixe non numérique (3.12.3-rc1, 3.12.3+build)
    n'est pas non plus une version exacte au sens strict de ce lock."""
    lock = ToolchainLock(
        tools={"uv": ToolSpec(version="0.5.0-rc1", digest="b" * 64)}
    )
    assert validate_toolchain_lock(lock)


# ---------------------------------------------------------------------------
# Cas RED 2 — refuser digest absent
# ---------------------------------------------------------------------------


def test_pinner_la_toolchain_core_2():
    """Un ToolSpec sans digest (chaîne vide) doit être refusé — un digest
    absent signifie qu'aucune preuve d'intégrité binaire n'existe pour cet
    outil, la version seule ne suffit jamais."""
    lock_sans_digest = ToolchainLock(
        tools={"docker": ToolSpec(version="27.3.1", digest="")}
    )
    erreurs = validate_toolchain_lock(lock_sans_digest)
    assert erreurs
    assert any("docker" in e and "digest" in e for e in erreurs)


def test_digest_mal_forme_refuse():
    """Un digest présent mais qui n'est pas un sha256 hexadécimal valide
    (64 caractères hex) doit aussi être refusé — un digest tronqué ou
    inventé ne prouve rien."""
    lock = ToolchainLock(
        tools={"helm": ToolSpec(version="3.16.1", digest="pas-un-sha256")}
    )
    assert validate_toolchain_lock(lock)

    lock_trop_court = ToolchainLock(
        tools={"helm": ToolSpec(version="3.16.1", digest="abc123")}
    )
    assert validate_toolchain_lock(lock_trop_court)


# ---------------------------------------------------------------------------
# Cas RED 3 — détecter binaire différent de la lock
# ---------------------------------------------------------------------------


def test_pinner_la_toolchain_core_3():
    """Si le binaire RÉELLEMENT mesuré (digest différent, même version
    affichée) ne correspond pas à ce que le lock déclare, c'est une
    DÉRIVE détectée — un binaire substitué qui prétend la même version ne
    doit jamais passer inaperçu."""
    lock = ToolchainLock(
        tools={
            "python": ToolSpec(version="3.12.3", digest="a" * 64),
            "docker": ToolSpec(version="27.3.1", digest="b" * 64),
        }
    )
    mesures_identiques = {
        "python": ToolSpec(version="3.12.3", digest="a" * 64),
        "docker": ToolSpec(version="27.3.1", digest="b" * 64),
    }
    assert detect_drift(lock, mesures_identiques) == []

    # Même version affichée, digest DIFFÉRENT -> binaire substitué détecté.
    mesures_derivees = {
        "python": ToolSpec(version="3.12.3", digest="c" * 64),  # substitué
        "docker": ToolSpec(version="27.3.1", digest="b" * 64),
    }
    derives = detect_drift(lock, mesures_derivees)
    assert derives == ["python"]


def test_outil_absent_des_mesures_est_une_derive():
    """Un outil verrouillé mais absent des mesures réelles (jamais
    installé, ou disparu depuis le lock) est aussi une dérive — jamais
    silencieusement ignoré."""
    lock = ToolchainLock(tools={"podman": ToolSpec(version="5.2.2", digest="d" * 64)})
    derives = detect_drift(lock, mesures={})
    assert derives == ["podman"]


# ---------------------------------------------------------------------------
# Robustesse structurelle
# ---------------------------------------------------------------------------


def test_toolchain_lock_est_gele():
    """ToolchainLock/ToolSpec sont immuables (frozen) — un lock ne doit
    pas pouvoir être réécrit après coup pour fabriquer une conformité."""
    lock = ToolchainLock(tools={"python": ToolSpec(version="3.12.3", digest="a" * 64)})
    import pytest

    with pytest.raises(Exception):
        lock.tools["python"] = ToolSpec(version="9.9.9", digest="z" * 64)
    with pytest.raises(Exception):
        lock.tools["python"].version = "9.9.9"


def test_inventaire_jamais_de_telechargement_silencieux_sur_outil_absent(monkeypatch, tmp_path):
    """Un outil déclaré introuvable dans PATH doit devenir un blocker
    explicite — jamais une tentative d'installation, jamais une entrée
    fantôme dans le lock produit. subprocess.run est AUSSI mocké en
    SUCCÈS (jamais laissé s'exécuter réellement) : si on ne mockait que
    which(), un vrai binaire absent (`outil-inexistant-xyz`) ferait aussi
    échouer subprocess.run par FileNotFoundError — une exception qui
    produit un blocker EN APPARENCE identique via un chemin totalement
    différent (le except générique, pas le refus explicite), rendant le
    test incapable de distinguer « garde present » de « garde retirée
    mais l'appel échoue quand même pour une autre raison ». Mesuré :
    c'est exactement ce qui se produit (cf. mutation_proof.py, M4)."""
    import shutil as shutil_module

    import bootstrap_toolchain as bt

    monkeypatch.setattr(shutil_module, "which", lambda nom: None)

    appels = []

    def _run_qui_ne_doit_jamais_etre_appele(*a, **k):
        appels.append((a, k))

        class _FauxCompletedProcess:
            stdout = "1.2.3"
            stderr = ""

        return _FauxCompletedProcess()

    monkeypatch.setattr(bt.subprocess, "run", _run_qui_ne_doit_jamais_etre_appele)

    lock, blockers = inventorier_toolchain({"outil-inexistant": ["outil-inexistant-xyz", "--version"]})
    assert appels == [], "subprocess.run ne doit JAMAIS être invoqué pour un outil non résolu par which()"
    assert lock.tools == {}
    assert len(blockers) == 1
    assert "outil-inexistant" in blockers[0]


def test_inventaire_mesure_reellement_python_present():
    """Preuve directe (pas un mock) : l'inventaire mesure RÉELLEMENT
    l'interpréteur Python courant (garanti présent, sys.executable) —
    version ET digest non vides, cohérents avec le binaire réel."""
    lock, blockers = inventorier_toolchain({"python": [sys.executable, "--version"]})
    assert "python" not in [b.split(":")[0] for b in blockers]
    assert "python" in lock.tools
    spec = lock.tools["python"]
    assert spec.version
    assert len(spec.digest) == 64
    # Le digest doit être celui du VRAI binaire, pas un placeholder.
    import hashlib

    digest_reel = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    assert spec.digest == digest_reel


# ---------------------------------------------------------------------------
# Gardes défensives de inventorier_toolchain — non couvertes par les 3 cas
# RED nommés ni par les tests ci-dessus, ajoutées pour fermer le trou de
# mutation (aucune exception ne doit jamais s'échapper, chaque échec de
# mesure devient un blocker explicite, jamais un plantage).
# ---------------------------------------------------------------------------


def test_inventaire_subprocess_oserror_devient_blocker_jamais_exception(monkeypatch):
    """Si subprocess.run lève OSError (binaire corrompu, ENOEXEC, etc.),
    l'exception ne doit JAMAIS s'échapper de inventorier_toolchain — elle
    devient un blocker nommé, et les autres outils de l'appel continuent
    d'être traités normalement."""
    import bootstrap_toolchain as bt

    def _explose(*a, **k):
        raise OSError("binaire corrompu (simulé)")

    monkeypatch.setattr(bt.subprocess, "run", _explose)

    lock, blockers = inventorier_toolchain({"python": [sys.executable, "--version"]})
    assert lock.tools == {}
    assert len(blockers) == 1
    assert blockers[0].split(":")[0] == "python"


def test_inventaire_timeout_devient_blocker_jamais_exception(monkeypatch):
    """Un outil qui ne répond jamais (timeout) doit devenir un blocker
    explicite, jamais laisser TimeoutExpired remonter jusqu'à l'appelant."""
    import subprocess as subprocess_module

    import bootstrap_toolchain as bt

    def _timeout(*a, **k):
        raise subprocess_module.TimeoutExpired(cmd=["python", "--version"], timeout=10)

    monkeypatch.setattr(bt.subprocess, "run", _timeout)

    lock, blockers = inventorier_toolchain({"python": [sys.executable, "--version"]})
    assert lock.tools == {}
    assert len(blockers) == 1
    assert blockers[0].split(":")[0] == "python"


def test_inventaire_sortie_sans_version_lisible_devient_blocker(monkeypatch):
    """Un binaire qui répond mais sans motif de version reconnaissable dans
    sa sortie doit devenir un blocker explicite — jamais une entrée fantôme
    au lock avec une version vide ou inventée."""
    import bootstrap_toolchain as bt

    class _FauxCompletedProcess:
        stdout = "aucune version ici"
        stderr = ""

    monkeypatch.setattr(bt.subprocess, "run", lambda *a, **k: _FauxCompletedProcess())

    lock, blockers = inventorier_toolchain({"python": [sys.executable, "--version"]})
    assert lock.tools == {}
    assert len(blockers) == 1
    assert blockers[0].split(":")[0] == "python"
    assert "version" in blockers[0]


def test_inventaire_digest_illisible_devient_blocker(monkeypatch, tmp_path):
    """Si le chemin résolu par shutil.which pointe vers quelque chose
    d'illisible en binaire (ici un RÉPERTOIRE — IsADirectoryError, sous-
    classe réelle d'OSError, non mockée), la lecture du digest échoue
    proprement en blocker — jamais une exception qui s'échappe, jamais un
    digest inventé."""
    import shutil as shutil_module

    import bootstrap_toolchain as bt

    repertoire = tmp_path / "faux-binaire-repertoire"
    repertoire.mkdir()

    class _FauxCompletedProcess:
        stdout = "outil version 1.2.3"
        stderr = ""

    monkeypatch.setattr(shutil_module, "which", lambda nom: str(repertoire))
    monkeypatch.setattr(bt.subprocess, "run", lambda *a, **k: _FauxCompletedProcess())

    lock, blockers = inventorier_toolchain({"outil": ["outil", "--version"]})
    assert lock.tools == {}
    assert len(blockers) == 1
    assert blockers[0].split(":")[0] == "outil"
    assert "digest" in blockers[0]
