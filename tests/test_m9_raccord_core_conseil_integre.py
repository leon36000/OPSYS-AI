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
    trace = [{"acteur": "agent", "outil": outil, "resultat": "refus", "code": rc.CODE_REFUS_IDENTITE}]
    verdict = rc.verifier_trace(trace)
    assert verdict["verdict"] == "INCOMPLETE" and verdict["regles"][0]["statut"] == "CONFORME"


def test_les_profils_proposes_nomment_tous_l_outil_d_entree_admin_strict(capacites):
    """Constat de l'écart documenté : les profils listent un outil que leur propre agent ne peut pas appeler."""
    from m9_strategic_intelligence import conseil

    profils = [
        conseil.profil_agent(r.id, outils=[rc.OUTIL_ENTREE], budget_jour=1, budget_mois=1)
        for r in conseil.ROLES
        if r.etape != "audit"
    ]
    assert profils and all(p["outils"] == [rc.OUTIL_ENTREE] for p in profils)
    assert {p["id"] for p in profils} == {rc.agent_id(r.id) for r in conseil.ROLES if r.etape != "audit"}
