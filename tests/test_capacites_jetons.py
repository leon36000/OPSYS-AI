from __future__ import annotations

import datetime as dt

import demo_outils
import pytest

from opsys import approbations, jetons
from opsys.capacites import Capacites


@pytest.fixture
def capacites(departements_demo, session):
    demo_outils.JOURNAL.clear()
    return Capacites(departements_demo, session, limite_sortie=800)


def test_liste_contient_outils_du_departement_et_communs(capacites):
    noms = {o.nom for o in capacites.lister()}
    assert {"m9_additionner", "m9_payer", "opsys_lire_artefact", "opsys_etat_budget"} <= noms


def test_t0_execute_directement(capacites):
    assert capacites.appeler("m9_additionner", {"a": 0.1, "b": 0.2}) == {
        "ok": True, "resultat": {"somme": "0.3"}}


def test_refus_metier_et_outil_inconnu(capacites):
    assert capacites.appeler("m9_refuser_si_negatif", {"valeur": -1})["erreur"] == "refus_metier"
    assert capacites.appeler("m9_inexistant", {})["erreur"] == "outil_inconnu"


def test_t2_en_mode_supervise_passe_par_approbation(capacites, session):
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "client", "texte": "Bonjour"})
    assert reponse["statut"] == "en_attente_approbation"
    assert demo_outils.JOURNAL == []  # rien n'a été envoyé

    index = {o.nom: o for o in capacites.lister()}
    with session() as cnx:
        decision = approbations.decider(cnx, reponse["demande_id"], True, "nathan", index)
        assert decision["statut"] == "executee"
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, reponse["demande_id"], True, "nathan", index)
    assert demo_outils.JOURNAL == [{"a": "client", "texte": "Bonjour"}]


def test_t3_toujours_approuve_meme_en_autonome(capacites, session):
    with session() as cnx:
        approbations.fixer_mode(cnx, "m09-demo", "autonome", "nathan")
    reponse = capacites.appeler("m9_payer", {"montant": 100})
    assert reponse["statut"] == "en_attente_approbation"
    with session() as cnx:
        refus = approbations.decider(cnx, reponse["demande_id"], False, "nathan", {}, "pas maintenant")
    assert refus == {"id": reponse["demande_id"], "statut": "refusee"}
    assert demo_outils.JOURNAL == []


def test_t2_en_mode_autonome_execute(capacites, session):
    with session() as cnx:
        approbations.fixer_mode(cnx, "m09-demo", "autonome", "nathan")
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "c", "texte": "t"})
    assert reponse["ok"] is True and reponse["resultat"]["envoye"] is True


def test_demande_invalide_non_enregistree(capacites, session):
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "c"})
    assert reponse["erreur"] == "arguments_invalides"
    with session() as cnx:
        assert approbations.lister(cnx) == []


def test_budget_epuise_bloque_les_actions(capacites, session):
    with session() as cnx:
        jetons.enregistrer_usage(cnx, "m09-demo", "modele-x", {"input_tokens": 900, "output_tokens": 200})
    bloque = capacites.appeler("m9_envoyer_message", {"destinataire": "c", "texte": "t"})
    assert bloque["erreur"] == "budget_epuise"


def test_troncature_et_lecture_artefact(capacites):
    reponse = capacites.appeler("m9_gros_rapport", {"lignes": 100})
    assert reponse["tronque"] is True
    assert "opsys_lire_artefact" in reponse["apercu"]
    ident = reponse["apercu"].split("artefact ")[1].split(" ")[0]
    lecture = capacites.appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})
    assert lecture["ok"] is True and len(lecture["resultat"]["contenu"]) == 100


def test_normalisation_usage_fournisseurs():
    assert jetons.normaliser_usage({"prompt_tokens": 10, "completion_tokens": 5}) == {
        "tokens_entree": 10, "tokens_sortie": 5, "tokens_cache_lus": 0}
    assert jetons.normaliser_usage({"input_tokens": 7, "output_tokens": 3, "cache_read_tokens": 4}) == {
        "tokens_entree": 7, "tokens_sortie": 3, "tokens_cache_lus": 4}
    assert jetons.normaliser_usage(None)["tokens_entree"] == 0


def test_niveaux_de_budget(departements_demo, session):
    budget = departements_demo["m09-demo"].budget
    jour = dt.date(2026, 9, 28)
    with session() as cnx:
        assert jetons.etat_budget(cnx, "m09-demo", budget, jour)["niveau"] == "ok"
        jetons.enregistrer_usage(cnx, "m09-demo", "m", {"input_tokens": 850}, jour)
        assert jetons.etat_budget(cnx, "m09-demo", budget, jour)["niveau"] == "alerte"
        jetons.enregistrer_usage(cnx, "m09-demo", "m", {"input_tokens": 150}, jour)
        etat = jetons.etat_budget(cnx, "m09-demo", budget, jour)
    assert etat["niveau"] == "epuise"
    assert etat["jour"] == {"utilise": 1000, "limite": 1000, "pct": 100.0}


def test_lecture_artefact_bornes(session):
    with session() as cnx:
        texte = "a" * 10000
        apercu = jetons.tronquer(cnx, texte, "test", limite=1000)
        assert len(apercu) < 1200
        ident = apercu.split("artefact ")[1].split(" ")[0]
        fin = jetons.lire_artefact(cnx, ident, debut=9990, longueur=100)
        assert fin["contenu"] == "a" * 10 and fin["reste"] == 0
        with pytest.raises(ValueError):
            jetons.lire_artefact(cnx, ident, debut=-1)
        with pytest.raises(KeyError):
            jetons.lire_artefact(cnx, "inconnu")
