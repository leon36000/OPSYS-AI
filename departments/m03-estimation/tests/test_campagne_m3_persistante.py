"""Probe cross-processus du reçu durable, hors des suites mutation imbriquées."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("phase", ("premier", "reprise"))
def test_reprise_exacte_du_meme_outil_sur_deux_processus_pytest(
    phase, campagne_gardes
):
    racine = Path(__file__).resolve().parents[3]
    marqueur = racine / "preuves/revision-9/reprise-cross-processus-r2d.json"
    assert os.environ.get("M3_CAMPAGNE_RUN_ID") == "r9-cross-processus-r2d"
    assert campagne_gardes.campagne.dossier_persistance is not None

    existait = marqueur.exists()
    environnement = campagne_gardes.environnement_nominal()
    acces = campagne_gardes.nominal(
        campagne_gardes.outils_mutation[0], environnement=environnement
    )
    env_reel = dict(environnement)
    env_reel.pop("PYTEST_CURRENT_TEST", None)
    env_sha256 = hashlib.sha256(
        json.dumps(sorted(env_reel.items()), separators=(",", ":")).encode()
    ).hexdigest()
    if phase == "premier":
        assert not existait, "le marqueur doit être supprimé avant la première commande"
        assert acces.processus_lance_ici is True
        assert acces.preuve.retour == 0
        assert acces.recu_durable is not None
        recu = Path(acces.recu_durable)
        assert recu.is_file()
        octets_recu = recu.read_bytes()
        objet = json.loads(octets_recu)
        assert objet["schema"] == 2
        assert objet["identifiant_campagne"] == "r9-cross-processus-r2d"
        assert objet["cle"] == acces.preuve.cle
        assert objet["commande"] == list(acces.preuve.commande)
        assert objet["specification"]["python"].startswith(sys.executable + " | ")
        assert objet["specification"]["environnement_sha256"] == env_sha256
        assert objet["entrees_sha256"] == acces.preuve.entrees_sha256
        assert objet["avant"]["sha256"] == acces.preuve.avant.sha256
        assert objet["apres"]["sha256"] == acces.preuve.apres.sha256
        assert isinstance(objet["stdout"], str)
        assert isinstance(objet["stderr"], str)
        empreinte_recu = hashlib.sha256(octets_recu).hexdigest()
        marqueur.write_text(
            json.dumps(
                {
                    "cle": acces.preuve.cle,
                    "retour": acces.preuve.retour,
                    "recu": recu.name,
                    "recu_sha256_octets": empreinte_recu,
                    "environment_sha256": env_sha256,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        assert existait, "la première commande n'a pas persisté son marqueur"
        original = json.loads(marqueur.read_text(encoding="utf-8"))
        assert acces.processus_lance_ici is False
        assert acces.preuve.cle == original["cle"]
        assert acces.preuve.retour == original["retour"] == 0
        assert acces.recu_durable is not None
        recu = Path(acces.recu_durable)
        assert recu.name == original["recu"]
        assert hashlib.sha256(recu.read_bytes()).hexdigest() == original[
            "recu_sha256_octets"
        ]
        assert original["environment_sha256"] == env_sha256
