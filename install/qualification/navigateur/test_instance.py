"""Tests ciblés des fixtures jetables du banc navigateur."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[2]
sys.path[:0] = [str(RACINE / "src"), *(str(p) for p in sorted((RACINE / "departments").glob("*/src")))]

SPEC = importlib.util.spec_from_file_location("instance_banc_navigateur", ICI / "instance.py")
assert SPEC and SPEC.loader
instance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(instance)


def _environnement(monkeypatch: pytest.MonkeyPatch, dossier: Path) -> dict[str, str]:
    cles = ("OPSYS_HOME", "OPSYS_BASE_URL", "OPSYS_COFFRE_CLE_FICHIER", "OPSYS_QUALIF_EFFETS",
            "OPENCLAW_CONFIG_DIR", "OPSYS_CONSOLE_SECRET")
    for cle in cles:
        if cle in os.environ:
            monkeypatch.setenv(cle, os.environ[cle])
        else:
            monkeypatch.delenv(cle, raising=False)
    env = instance.preparer_environnement(dossier)
    return env


def _stub_runtime(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Empêche tout accès au stockage/département réel si un mutant dépasse une garde."""
    from opsys import identite, stockage

    captures: dict[str, list[dict]] = {}

    class Cible:
        def __init__(self, nom: str) -> None:
            self.nom = nom
            captures.setdefault(nom, [])

        def append(self, fait: dict) -> None:
            captures[self.nom].append(fait)

    @contextmanager
    def transaction():
        yield object()

    class CapacitesFictives:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def appeler(self, *_args, **_kwargs):
            return {"statut": "en_attente_approbation"}

    monkeypatch.setattr(stockage, "migrer", lambda: None)
    monkeypatch.setattr(stockage, "transaction", transaction)
    monkeypatch.setattr(stockage, "maillons", lambda _departement, nom: Cible(nom))
    monkeypatch.setattr(identite, "creer_personne", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(instance, "deps_instance", dict)
    monkeypatch.setattr("opsys.capacites.Capacites", CapacitesFictives)
    return captures


def test_refuse_opsys_home_externe_sans_y_ecrire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dossier = tmp_path / "instance"
    _environnement(monkeypatch, dossier)
    _stub_runtime(monkeypatch)
    externe = tmp_path / "hors-instance"
    externe.mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(externe))

    with pytest.raises(SystemExit, match="OPSYS_HOME doit rester dans le dossier jetable"):
        instance.initialiser(dossier)

    assert list(externe.iterdir()) == []
    assert not (dossier / "instance.db").exists()


def test_refuse_sans_ecraser_un_profil_preexistant_different(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dossier = tmp_path / "instance"
    env = _environnement(monkeypatch, dossier)
    _stub_runtime(monkeypatch)
    profil = Path(env["OPSYS_HOME"]) / "entreprise.yaml"
    profil.parent.mkdir(parents=True, exist_ok=True)
    contenu_initial = b"profil-preexistant-fictif"
    profil.write_bytes(contenu_initial)

    with pytest.raises(SystemExit, match="profil préexistant différent"):
        instance.initialiser(dossier)

    assert profil.read_bytes() == contenu_initial
    assert not (dossier / "instance.db").exists()


def test_initialisation_amorce_les_faits_operationnels_fictifs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from m8_analytics import jeux_fictifs

    dossier = tmp_path / "instance"
    env = _environnement(monkeypatch, dossier)
    Path(env["OPSYS_COFFRE_CLE_FICHIER"]).write_text("cle-fictive-de-test", encoding="utf-8")
    captures = _stub_runtime(monkeypatch)

    instance.initialiser(dossier)

    attendus = jeux_fictifs.registres_fictifs(avec_operations=True)["operations"]
    assert attendus
    assert captures["faits_operations"] == attendus
    assert Path(env["OPSYS_HOME"], "entreprise.yaml").read_bytes() == (
        json.dumps({"canaux_marketing": jeux_fictifs.CANAUX_FICTIFS}).encode("utf-8")
    )
