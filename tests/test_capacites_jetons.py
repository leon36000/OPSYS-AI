from __future__ import annotations

import dataclasses
import datetime as dt

import demo_outils
import pytest
from sqlalchemy import select

from opsys import approbations, contexte, jetons
from opsys.capacites import Capacites
from opsys.stockage.schema import ARTEFACTS


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


def test_t2_en_mode_supervise_passe_par_approbation(capacites, session, departements_demo, nathan):
    reponse = capacites.appeler("m9_envoyer_message", {"destinataire": "client", "texte": "Bonjour"})
    assert reponse["statut"] == "en_attente_approbation"
    assert demo_outils.JOURNAL == []  # rien n'a été envoyé

    index = {o.nom: o for o in capacites.lister()}
    with session() as cnx:
        decision = approbations.decider(cnx, reponse["demande_id"], True, nathan, index, departements_demo)
        assert decision["statut"] == "executee"
        with pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(cnx, reponse["demande_id"], True, nathan, index, departements_demo)
    assert demo_outils.JOURNAL == [{"a": "client", "texte": "Bonjour"}]


def test_t3_toujours_approuve_meme_en_autonome(capacites, session, departements_demo, nathan):
    with session() as cnx:
        approbations.fixer_mode(cnx, "m09-demo", "autonome", "nathan")
    reponse = capacites.appeler("m9_payer", {"montant": 100})
    assert reponse["statut"] == "en_attente_approbation"
    with session() as cnx:
        refus = approbations.decider(cnx, reponse["demande_id"], False, nathan, {}, departements_demo,
                                     "pas maintenant")
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


def test_troncature_et_lecture_artefact(capacites, session):
    reponse = capacites.appeler("m9_gros_rapport", {"lignes": 100})
    assert reponse["tronque"] is True
    assert "opsys_lire_artefact" in reponse["apercu"]
    ident = reponse["apercu"].split("artefact ")[1].split(" ")[0]
    lecteur = Capacites(capacites.departements, session, limite_sortie=800, appelant="m09-demo")
    lecture = lecteur.appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})
    assert lecture["ok"] is True and len(lecture["resultat"]["contenu"]) == 100


def test_artefact_ne_se_lit_que_depuis_son_origine_authentifiee(departements_demo, session):
    base = departements_demo["m09-demo"]
    departements = {
        **departements_demo,
        "m01-front-office": dataclasses.replace(base, id="m01-front-office"),
        "m02-revenue-crm": dataclasses.replace(base, id="m02-revenue-crm"),
    }
    appelant_reel = Capacites(
        departements, session, filtre={"m09-demo"}, limite_sortie=800, appelant="m01-front-office"
    )
    rapport = appelant_reel.appeler("m9_gros_rapport", {"lignes": 100})
    assert rapport["tronque"] is True
    ident = rapport["apercu"].split("artefact ")[1].split(" ")[0]
    with session() as cnx:
        artefact = cnx.execute(
            select(ARTEFACTS.c.departement, ARTEFACTS.c.origine).where(ARTEFACTS.c.id == ident)
        ).one()
    assert artefact == ("m09-demo", "m01-front-office")

    acces_origine = appelant_reel.appeler(
        "opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100}
    )
    acces_autre_departement = Capacites(
        departements, session, filtre={"m09-demo"}, limite_sortie=800, appelant="m02-revenue-crm"
    ).appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})

    assert acces_origine["ok"] is True
    assert acces_autre_departement["ok"] is False
    assert acces_autre_departement["erreur"] == "refus_metier"
    assert ident not in acces_autre_departement.get("details", "")


def test_artefact_legacy_sans_provenance_refuse_via_capacites(departements_demo, session):
    ident = "legacy0000000001"
    with session() as cnx:
        cnx.execute(ARTEFACTS.insert().values(
            id=ident, cree_le="2026-09-01T00:00:00+00:00", source="ancien", taille=12,
            contenu="contenu secret", departement=None, origine=None,
        ))
    lecteur = Capacites(departements_demo, session, appelant="m09-demo")
    reponse = lecteur.appeler("opsys_lire_artefact", {"id": ident, "debut": 0, "longueur": 100})
    assert reponse["erreur"] == "refus_metier"
    assert "contenu secret" not in str(reponse)
    assert ident not in str(reponse)


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
        apercu = jetons.tronquer(
            cnx, texte, "test", limite=1000, departement="m09-demo", origine="m09-demo"
        )
        assert len(apercu) < 1200
        ident = apercu.split("artefact ")[1].split(" ")[0]
        with contexte.appeler_en_tant_que("m09-demo"):
            fin = jetons.lire_artefact(cnx, ident, debut=9990, longueur=100)
        assert fin["contenu"] == "a" * 10 and fin["reste"] == 0
        with pytest.raises(ValueError):
            jetons.lire_artefact(cnx, ident, debut=-1)
        with pytest.raises(KeyError):
            jetons.lire_artefact(cnx, "inconnu")
