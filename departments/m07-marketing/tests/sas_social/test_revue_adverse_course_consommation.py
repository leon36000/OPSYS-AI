"""Revue adverse (app-01) : une approbation de publication sociale ne se consomme qu'UNE fois, même quand deux
exécuteurs se croisent (bail expiré pendant un appel lent, deux processus, redémarrage).

`executeur.executer` lit l'état une fois, fait ses contrôles, puis écrit `tentative` avant d'appeler le réseau. Sans
précondition de rang sur cette écriture, un second exécuteur qui a lu l'état AVANT la tentative du premier écrit sa
propre tentative (le rang est recalculé à l'écriture) et publie une seconde fois : le double ne déduplique pas, comme
la plupart des API réelles. Les journaux sont ici des listes : l'ordre des appels est déterministe.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import pytest
from fabriques_sociales import HORODATAGE, JETON, MAINTENANT, publication
from m7_marketing import journal_chaine
from m7_marketing.sas_social import doubles, etats, executeur, garde_fous, service

FICTIF = True
HEURE_PREVUE = datetime(2026, 1, 6, 15, 0, 0, tzinfo=UTC)


class Fournisseur:
    """Le fournisseur de secret (le coffre) : compte ses ouvertures."""

    def __init__(self):
        self.ouvertures = 0

    @contextlib.contextmanager
    def __call__(self):
        self.ouvertures += 1
        yield JETON


def planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire):
    cree = service.composer(journal, publication("facebook"), "cle-course-0123456789ab", comptes_actifs, "agent",
                            HORODATAGE)
    assert service.soumettre(journal, cree["publication_id"], declarations, politique_sas, MAINTENANT, HORODATAGE)[
        "accepte"]
    ok = service.approuver(journal, cree["publication_id"], cree["empreinte"], 3, proprietaire, declarations,
                           politique_sas, MAINTENANT, HORODATAGE)
    assert ok["accepte"], ok
    return cree["publication_id"]


def _tentatives(journal, publication_id):
    return [m for m in journal_chaine.de_type(journal, etats.MAILLON_TENTATIVE)
            if m["publication_id"] == publication_id]


def test_deux_executeurs_qui_se_croisent_ne_publient_pas_deux_fois(
    journal, comptes_actifs, declarations, politique_sas, proprietaire, monkeypatch
):
    pid = planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()
    fournisseur = Fournisseur()
    reel = garde_fous.quota_respecte
    etat = {"deja": False}

    def autre_executeur_passe_pendant_que_celui_ci_hesite(*args, **kwargs):
        # Le premier exécuteur a lu l'état et fait ses contrôles ; ICI un second exécuteur (bail repris) passe.
        if not etat["deja"]:
            etat["deja"] = True
            executeur.executer(journal, pid, {"facebook": double}, fournisseur, politique_sas, HEURE_PREVUE)
        return reel(*args, **kwargs)

    monkeypatch.setattr(garde_fous, "quota_respecte", autre_executeur_passe_pendant_que_celui_ci_hesite)
    resultat = executeur.executer(journal, pid, {"facebook": double}, fournisseur, politique_sas, HEURE_PREVUE)

    assert len(double.publiees) == 1, "la même approbation a fait publier deux fois"
    assert resultat["publie"] is False and resultat["refus"][0]["code"] == executeur.REJ_CONCURRENCE
    assert len(_tentatives(journal, pid)) == 1
    assert service.charger(journal)[0][pid].etat == etats.PUBLIE
    assert journal_chaine.integre(journal)


def test_un_executeur_qui_ecrit_juste_apres_la_lecture_de_l_etat_fait_refuser_la_tentative(
    journal, comptes_actifs, declarations, politique_sas, proprietaire, monkeypatch
):
    """Le rang est lu AVANT l'état : un autre exécuteur qui passe entre la lecture et les contrôles est détecté."""
    pid = planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()
    fournisseur = Fournisseur()
    reel = service.charger
    etat = {"deja": False}

    def lit_puis_l_autre_passe(j):
        lu = reel(j)
        if not etat["deja"]:
            etat["deja"] = True
            executeur.executer(j, pid, {"facebook": double}, fournisseur, politique_sas, HEURE_PREVUE)
        return lu  # l'état rendu à l'exécuteur lent est déjà périmé

    monkeypatch.setattr(service, "charger", lit_puis_l_autre_passe)
    resultat = executeur.executer(journal, pid, {"facebook": double}, fournisseur, politique_sas, HEURE_PREVUE)

    assert len(double.publiees) == 1 and resultat["publie"] is False
    assert resultat["refus"][0]["code"] == executeur.REJ_CONCURRENCE
    assert len(_tentatives(journal, pid)) == 1


def test_sans_croisement_la_publication_normale_reste_acceptee(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    pid = planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()
    resultat = executeur.executer(journal, pid, {"facebook": double}, Fournisseur(), politique_sas, HEURE_PREVUE)
    assert resultat["accepte"] is True and len(double.publiees) == 1
    suite = executeur.executer(journal, pid, {"facebook": double}, Fournisseur(), politique_sas, HEURE_PREVUE)
    assert suite["accepte"] is False and len(double.publiees) == 1  # le rejeu séquentiel reste refusé


def test_la_precondition_de_rang_du_journal_refuse_un_etat_perime():
    journal = []
    journal_chaine.ajouter(journal, "premier", {"x": 1}, "2026-01-01T00:00:00Z")
    journal_chaine.ajouter(journal, "deuxieme", {"x": 2}, "2026-01-01T00:00:01Z")
    with pytest.raises(journal_chaine.ConcurrenceJournal):
        journal_chaine.ajouter(journal, "perime", {"x": 3}, "2026-01-01T00:00:02Z", rang_attendu=1)
    assert len(journal) == 2
    journal_chaine.ajouter(journal, "courant", {"x": 4}, "2026-01-01T00:00:03Z", rang_attendu=2)
    assert len(journal) == 3 and journal_chaine.integre(journal)


