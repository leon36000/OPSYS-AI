"""M9 : interposition fictive d'un append dans la transaction SQLite native.

Ce modèle vérifie le rang et le rollback ; il ne prétend pas reproduire deux
transactions PostgreSQL distinctes ni prouver qu'un autre commit survit.
"""
from __future__ import annotations

import pytest
from m9_strategic_intelligence import outils, registre

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

DEPARTEMENT = "m09-strategic-intelligence"
REGISTRE = "snapshots"


def _snapshot(valeur, source="source-declaree-fictive"):
    return {
        "module_source": source,
        "horodatage": "2026-01-04T12:00:00Z",
        "valeurs": {"prevision": valeur},
    }


@pytest.fixture
def base_fictive(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'ingestion-fictive.db'}")
    stockage.migrer()
    yield
    stockage.liberer()


def _outil(cible=None):
    return next(o for o in outils.outils(cible, []) if o.nom == "m9_etat_consolide")


def _relire():
    return registre.RegistreSnapshots(stockage.maillons(DEPARTEMENT, REGISTRE))


def test_ingestions_durables_successives_restent_chainees(base_fictive):
    outil = _outil()
    for valeur in ("100.00", "200.00"):
        reponse = executer_atomique(outil, {"snapshot": _snapshot(valeur)})
        assert reponse["ok"] and reponse["resultat"]["accepte"]
        assert valeur in str(reponse["resultat"]["etat_consolide"])
    relue = _relire()
    assert [m["index"] for m in relue.lire()] == [0, 1]
    assert relue.valider_chaine() == (True, "")


def test_append_intercale_refuse_le_rang_perime_annule_et_permet_reprise(base_fictive, monkeypatch):
    outil = _outil()
    assert executer_atomique(outil, {"snapshot": _snapshot("100.00")})["ok"]
    avant = _relire().lire()
    originale = MaillonsDurables.append
    observations = []

    def intercaler(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE) and (
            maillon["valeurs"]["prevision"] == "200.00"
        ):
            connexion = stockage.connexion_courante()
            assert connexion is not None
            # Append légitime après calcul du candidat A, dans la même transaction
            # pour observer son rollback. Aucun propriétaire ou hash n'est falsifié.
            autre = registre.RegistreSnapshots(self)
            autre.ajouter(_snapshot("300.00", "autre-source-fictive"))
            assert autre.valider_chaine() == (True, "")
            assert stockage.connexion_courante() is connexion
            observations.append(len(self))
        return originale(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", intercaler)
    with pytest.raises(EcritureConcurrente):
        executer_atomique(outil, {"snapshot": _snapshot("200.00")})
        valide, message = _relire().valider_chaine()
        assert valide, f"ingestion acceptée avec une chaîne rompue : {message}"
    assert observations == [2]
    assert _relire().lire() == avant  # transaction A entièrement annulée, B fictif inclus
    assert _relire().valider_chaine() == (True, "")

    monkeypatch.setattr(MaillonsDurables, "append", originale)
    reprise = executer_atomique(outil, {"snapshot": _snapshot("200.00")})
    assert reprise["ok"] and reprise["resultat"]["accepte"]
    relue = _relire()
    assert [m["index"] for m in relue.lire()] == [0, 1]
    assert [m["valeurs"]["prevision"] for m in relue.lire()] == ["100.00", "200.00"]
    assert relue.valider_chaine() == (True, "")


def test_registre_memoire_injecte_conserve_ses_ajouts_et_necrit_pas_le_durable(base_fictive):
    cible = registre.RegistreSnapshots()
    outil = _outil(cible)
    for valeur in ("100.00", "200.00"):
        reponse = executer_atomique(outil, {"snapshot": _snapshot(valeur)})
        assert reponse["ok"] and reponse["resultat"]["accepte"]
    assert [m["index"] for m in cible.lire()] == [0, 1]
    assert cible.valider_chaine() == (True, "")
    assert _relire().lire() == []
