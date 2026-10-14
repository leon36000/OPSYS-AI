"""M8 : interposition SQLite dans une transaction native, jamais un commit concurrent PG.

Le maillon B interposé doit être annulé avec A quand son candidat est périmé.
La conservation d'un autre commit appartient au scénario PostgreSQL séparé.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from m8_analytics import encodage, outils, registre
from sqlalchemy import select, update

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables
from opsys.stockage.schema import REGISTRES

DEPARTEMENT = "m08-analytics"
REGISTRE = "snapshots"


@pytest.fixture
def base_fictive(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    yield
    stockage.liberer()


def _arguments(valeur):
    return {
        "dictionnaire": {"source-declaree-fictive": {"mesure-fictive": {}}},
        "snapshot": {"module_source": "source-declaree-fictive", "horodatage": "2026-10-14T12:00:00Z",
                     "valeurs": {"mesure-fictive": valeur}},
        "metric_ids": [], "horodatage_reference": "2026-10-14T12:00:00Z", "n_minimal": 1,
    }


def _outil(cible=None):
    return next(o for o in outils.outils(registre_cible=cible) if o.nom == "m8_rapport_metriques")


def _relire():
    return registre.RegistreSnapshots(stockage.maillons(DEPARTEMENT, REGISTRE))


def _interposer(monkeypatch, cible, est_a):
    originale = MaillonsDurables.append
    observations = []

    def append(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE) and est_a(maillon):
            connexion = stockage.connexion_courante()
            assert connexion is not None
            reponse = executer_atomique(cible, _arguments("300.00"))
            assert reponse["ok"] and reponse["resultat"]["accepte"]
            assert stockage.connexion_courante() is connexion
            assert _relire().valider_chaine() == (True, "")
            observations.append(len(self))
        return originale(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", append)
    return observations, originale


def test_ingestions_successives_durables_restent_chainees(base_fictive):
    outil = _outil()
    for valeur in ("100.00", "200.00"):
        reponse = executer_atomique(outil, _arguments(valeur))
        assert reponse["ok"] and reponse["resultat"]["accepte"]
    stockage.liberer()
    assert [m["index"] for m in _relire().lire()] == [0, 1]
    assert _relire().valider_chaine() == (True, "")


def test_rang_perime_refuse_outil_annule_et_permet_reprise(base_fictive, monkeypatch):
    outil = _outil()
    assert executer_atomique(outil, _arguments("100.00"))["ok"]
    avant = _relire().lire()
    observations, originale = _interposer(
        monkeypatch, outil, lambda m: m["valeurs"].get("mesure-fictive") == "200.00",
    )
    with pytest.raises(EcritureConcurrente):
        executer_atomique(outil, _arguments("200.00"))
        assert _relire().valider_chaine() == (True, ""), "outil accepté avec chaîne rompue"
    assert observations == [2]
    stockage.liberer()
    assert _relire().lire() == avant  # interposed B is not an independent commit.
    monkeypatch.setattr(MaillonsDurables, "append", originale)
    assert executer_atomique(outil, _arguments("200.00"))["ok"]
    assert [m["index"] for m in _relire().lire()] == [0, 1]
    assert _relire().valider_chaine() == (True, "")


def _wct():
    return {
        "wct_id": "wct-ingestion-fictif", "intervention_id": "intervention-fictive",
        "lead_id": "lead-fictif", "technicien_id": "technicien-fictif",
        "horodatage_completion": "2026-10-14T12:00:00Z", "fix_gps_completion": {},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 64, "consommateurs_cibles": ["M8"],
        "devis_id": None, "statut": "completed_verified",
    }


def test_consommateur_conserve_entree_et_reprend_apres_rang_perime(base_fictive, monkeypatch):
    outil = _outil()
    assert executer_atomique(outil, _arguments("100.00"))["ok"]
    avant = _relire().lire()
    charge = _wct()
    ident = charge["wct_id"]
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=ident)
    dep = charger_departements(Path(__file__).resolve().parents[2])[DEPARTEMENT]
    observations, originale = _interposer(
        monkeypatch, outil, lambda m: m["valeurs"].get("m4_wct_id") == ident,
    )
    reponse = evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:00Z")
    assert observations == [2]
    assert reponse["echecs"] == 1 and reponse["quarantaines"] == 0
    stockage.liberer()
    assert _relire().lire() == avant
    assert evenements.charge_publiee("m4.travaux_termines", ident) == charge
    assert len(stockage.maillons(DEPARTEMENT, "faits_chantier")) == 0
    monkeypatch.setattr(MaillonsDurables, "append", originale)
    reprise = evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-10-14T12:01:03Z")
    assert reprise["traites"] == 1 and reprise["echecs"] == 0
    assert _relire().valider_chaine() == (True, "")
    assert len(stockage.maillons(DEPARTEMENT, "faits_chantier")) == 1


@pytest.mark.parametrize("corruption", ["hash", "index"])
def test_chaine_native_invalide_refuse_avant_ecriture(base_fictive, corruption):
    outil = _outil()
    assert executer_atomique(outil, _arguments("100.00"))["ok"]
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE)
    with stockage.transaction() as cnx:
        maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        if corruption == "hash":
            maillon["hash_maillon"] = "0" * 64
        else:
            maillon["index"] = 10
            maillon["hash_maillon"] = encodage.empreinte(
                10, maillon["module_source"], maillon["horodatage"], maillon["valeurs"], maillon["hash_precedent"],
            )
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))
    avant = _relire().lire()
    reponse = executer_atomique(outil, _arguments("200.00"))
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    stockage.liberer()
    assert _relire().lire() == avant


def test_registre_injecte_garde_chemin_historique_en_memoire(base_fictive):
    memoire = registre.RegistreSnapshots()
    assert executer_atomique(_outil(memoire), _arguments("100.00"))["ok"]
    assert len(memoire.lire()) == 1 and memoire.valider_chaine() == (True, "")
    assert _relire().lire() == []


def test_rapport_et_historique_utilisent_la_meme_copie_acceptee(base_fictive, monkeypatch):
    outil = _outil()
    assert executer_atomique(outil, _arguments("100.00"))["ok"]
    deriver = outils.semantique.deriver_metrique
    detecter = outils.xmr.detecter_signal
    historiques = []

    def deriver_apres_interposition(*args):
        # B est accepté après A, avant sa dérivation. Le rapport A conserve
        # sa vue acceptée pour la valeur ET pour le signal historique.
        assert executer_atomique(outil, _arguments("300.00"))["ok"]
        return deriver(*args)

    def observer_historique(metric_id, valeurs, n_minimal):
        historiques.append(list(valeurs))
        return detecter(metric_id, valeurs, n_minimal)

    monkeypatch.setattr(outils.semantique, "deriver_metrique", deriver_apres_interposition)
    monkeypatch.setattr(outils.xmr, "detecter_signal", observer_historique)
    arguments = _arguments("200.00")
    arguments["metric_ids"] = ["mesure-fictive"]
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] and reponse["resultat"]["accepte"]
    metrique = reponse["resultat"]["rapport"]["metriques"][0]
    assert metrique["valeur"] == 200.0 and metrique["n"] == 2
    assert historiques == [[100.0, 200.0]]
    stockage.liberer()
    assert [m["valeurs"]["mesure-fictive"] for m in _relire().lire()] == ["100.00", "200.00", "300.00"]
    assert _relire().valider_chaine() == (True, "")
