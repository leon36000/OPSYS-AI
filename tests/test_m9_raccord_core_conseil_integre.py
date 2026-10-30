"""Raccord Core du conseil M9 : l'écart d'identité attendu est constaté sur le vrai ``Capacites`` (base fictive)."""

from __future__ import annotations

import json

import pytest
from m9_strategic_intelligence import raccord_core_conseil as rc

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

FICTIF = True
M9 = "m09-strategic-intelligence"


@pytest.fixture
def capacites(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'raccord.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield Capacites(charger_departements(), stockage.transaction, filtre={M9}, memoire=False)
    stockage.liberer()


@pytest.mark.parametrize(
    ("outil", "arguments"),
    [
        (rc.OUTIL_ENTREE, {"session_id": "s1", "role": "strategie_ventes", "depart": 0, "longueur": 500}),
        (rc.OUTIL_DEPOT, {"session_id": "s1", "role": "strategie_ventes", "sortie": {}, "reservation_id": "r1",
                          "horodatage": "2026-10-30T10:00:00Z"}),
    ],
)  # fmt: skip
def test_un_appel_sans_admin_authentifie_est_refuse_comme_le_contrat_du_raccord_l_attend(capacites, outil, arguments):
    """Le runtime natif d'un profil de rôle n'est pas un admin : l'entrée doit lui être remise par l'orchestrateur."""
    reponse = capacites.appeler(outil, arguments)
    assert rc.CODE_REFUS_IDENTITE in json.dumps(reponse)
    # L'événement de trace est DÉRIVÉ de la réponse réelle (et non écrit à la main) : ok seulement si accepté.
    accepte = reponse.get("ok") is True and reponse.get("resultat", {}).get("accepte") is True
    trace = [{"acteur": "agent", "outil": outil, "resultat": "ok" if accepte else "refus"}]
    verdict = rc.verifier_trace(trace)
    assert trace[0]["resultat"] == "refus"
    assert verdict["verdict"] == "INCOMPLETE" and verdict["regles"][0]["statut"] == "CONFORME"
