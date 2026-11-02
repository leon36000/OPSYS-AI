"""Aucun secret dans le dépôt, les journaux, les messages d'erreur ni les sorties de la passerelle de modèles."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import pytest
from faux_litellm import CLE_FICTIVE
from modeles_aide import (
    ALIAS,
    AMONT,
    CLE_AMONT,
    PROPRIETAIRE,
    affecter,
)
from sqlalchemy import text

from opsys.roles_modeles import appel, decouverte, generation
from opsys.roles_modeles.appel import Escalade
from opsys.roles_modeles.codes import ModelesErreur

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
DOSSIERS = (
    "src/opsys/roles_modeles",
    "src/opsys/console/modeles_ui.py",
    "departments/m10-memoire/src/m10_memoire/modeles_roles.py",
    "docs/architecture/PASSERELLE-DE-MODELES.md",
    "docs/architecture/FOURNISSEURS-ET-SECRETS.md",
    "docs/exploitation/INSTALLATION.md",
    "deploy",
    "tests/fixtures/faux_litellm.py",
    "tests/fixtures/modeles_aide.py",
)
FORMES_DE_CLE = re.compile(
    r"sk-(?:or-|ant-|proj-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|ya29\.[0-9A-Za-z_.-]{20,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{24,}"
)


def _fichiers():
    for nom in DOSSIERS:
        chemin = RACINE / nom
        if chemin.is_file():
            yield chemin
        elif chemin.is_dir():
            yield from (
                p
                for p in chemin.rglob("*")
                if p.is_file()
                and p.suffix in {".py", ".md", ".sh", ".yml", ".yaml", ".example", ".json", ""}
                and "__pycache__" not in p.parts
            )
    yield from (RACINE / "tests").glob("test_modeles_*.py")


def test_aucune_forme_de_cle_dans_les_fichiers_du_chantier():
    trouves = [
        (str(f.relative_to(RACINE)), m.group(0)[:12])
        for f in _fichiers()
        for m in [FORMES_DE_CLE.search(f.read_text(encoding="utf-8", errors="ignore"))]
        if m
    ]
    assert trouves == []


def test_la_vraie_cle_d_essai_n_est_dans_aucun_fichier_du_depot():
    """Opt-in : si le fichier de clé d'essai existe, sa valeur ne doit apparaître nulle part dans le dépôt."""
    chemin = os.environ.get("OPSYS_LITELLM_TEST_KEY_FILE")
    if not chemin or not Path(chemin).is_file():
        pytest.skip("OPSYS_LITELLM_TEST_KEY_FILE absent : balayage de la clé réelle non demandé")
    cle = Path(chemin).read_text(encoding="utf-8").strip()
    assert len(cle) >= 16
    for fichier in RACINE.rglob("*"):
        if (
            fichier.is_file()
            and ".git" not in fichier.parts
            and ".venv" not in fichier.parts
            and "node_modules" not in fichier.parts
            and fichier.stat().st_size < 5_000_000
        ):
            assert cle not in fichier.read_text(encoding="utf-8", errors="ignore"), str(fichier)


def test_parcours_complet_ne_laisse_aucune_valeur_dans_logs_erreurs_sorties_et_tables(
    pret, faux, faux_local, caplog, capsys, tmp_path
):

    caplog.set_level(logging.DEBUG)
    messages_erreur: list[str] = []
    decouverte.decouvrir(pret, acteur=PROPRIETAIRE)
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="llm_rapide")
    appel.completer(pret, classe="classification", messages=[{"role": "user", "content": "x"}], max_tokens=8)
    generation.ecrire_env(pret, tmp_path / "e.env")
    with pret() as cnx:
        generation.config_depuis_roles(cnx, {})
    # refus de toutes sortes : leurs messages ne portent jamais une valeur
    for action in (
        lambda: appel.completer(pret, classe="escalade_raisonnement", messages=[{"role": "user", "content": "x"}]),
        lambda: appel.completer(pret, classe="inconnue", messages=[{"role": "user", "content": "x"}]),
        lambda: appel.completer(
            pret,
            classe="escalade_raisonnement",
            messages=[{"role": "user", "content": "x"}],
            escalade=Escalade("vendeur_fictif", "Analyse contractuelle complexe"),
        ),
        lambda: generation.ecrire_env(pret, tmp_path / "absent" / "e.env"),
    ):
        with pytest.raises(ModelesErreur) as exc:
            action()
        messages_erreur.append(str(exc.value))
    faux.cle = "cle-changee-fictive-0123456789-QWERTYUI"
    with pytest.raises(ModelesErreur) as exc:
        appel.completer(pret, classe="classification", messages=[{"role": "user", "content": "x"}], max_tokens=8)
    messages_erreur.append(str(exc.value))
    faux.cle = CLE_FICTIVE
    sortie = capsys.readouterr()
    ensemble = "\n".join([*messages_erreur, caplog.text, sortie.out, sortie.err])
    for valeur in (CLE_FICTIVE, CLE_AMONT, "cle-changee-fictive-0123456789-QWERTYUI"):
        assert valeur not in ensemble
    with pret() as cnx:
        for table in (
            "journal",
            "modeles_historique",
            "modeles_reglages",
            "modeles_roles",
            "modeles_usage",
            "coffre_acces",
            "fournisseurs_configurations",
            "fournisseurs_selections",
        ):
            contenu = json.dumps([list(map(str, ligne)) for ligne in cnx.execute(text(f"SELECT * FROM {table}"))])
            for valeur in (CLE_FICTIVE, CLE_AMONT):
                assert valeur not in contenu, table
    # le fichier d'environnement est le SEUL endroit où une valeur est écrite hors du coffre
    assert CLE_FICTIVE in (tmp_path / "e.env").read_text()
