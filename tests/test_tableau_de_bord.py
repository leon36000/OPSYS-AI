"""Fonctions du tableau de bord (sans transport HTTP), sur le département démo et un OPSYS_HOME temporaire."""

from __future__ import annotations

import dataclasses
import datetime as dt

import demo_outils
import pytest
import sqlalchemy.exc
from sqlalchemy import text

from opsys import approbations, jetons, modeles, tableau_de_bord
from opsys.capacites import Capacites

JOUR = dt.date(2026, 9, 28)


@pytest.fixture
def horloge(monkeypatch):
    """Horodatage déterministe des demandes et décisions (une minute d'écart par appel)."""
    instants = (f"2026-09-28T08:{minute:02d}:00+00:00" for minute in range(60))
    monkeypatch.setattr(approbations, "_maintenant", lambda: next(instants))


@pytest.fixture
def demandes(departements_demo, session, horloge):
    """Deux demandes en attente créées par le vrai chemin des capacités (mode supervise).

    Le paiement (T3) est créé avant le message (T2) : le message est donc le plus récent.
    """
    demo_outils.JOURNAL.clear()
    capacites = Capacites(departements_demo, session)
    paiement = capacites.appeler("m9_payer", {"montant": 100})
    message = capacites.appeler("m9_envoyer_message", {"destinataire": "client", "texte": "Bonjour <b>"})
    assert paiement["statut"] == message["statut"] == "en_attente_approbation"
    return paiement["demande_id"], message["demande_id"]


# -- vue d'ensemble des départements -------------------------------------------------------------


def test_vue_departements_reprend_manifeste_mode_outils_et_consommation(departements_demo, session):
    with session() as cnx:
        jetons.enregistrer_usage(cnx, "m09-demo", "modele-x", {"input_tokens": 700, "output_tokens": 150}, JOUR)
        [demo] = tableau_de_bord.vue_departements(cnx, departements_demo, JOUR)

    assert (demo["id"], demo["code"], demo["nom"]) == ("m09-demo", "M9", "Démo")
    assert demo["mission"] == "Département fictif des tests du socle."
    assert demo["mode"] == demo["mode_manifeste"] == "supervise"
    outils = {o["nom"]: o for o in demo["outils"]}
    assert list(outils) == ["m9_additionner", "m9_refuser_si_negatif", "m9_envoyer_message", "m9_payer",
                            "m9_gros_rapport", "m9_echouer_puis_reussir", "m9_pointer",
                            "m9_voir_horodatage", "m9_voir_identite"]
    assert outils["m9_additionner"] == {"nom": "m9_additionner", "description": "Additionne deux nombres.",
                                        "autonomie": "T0", "approbation_requise": False}
    assert (outils["m9_envoyer_message"]["autonomie"], outils["m9_envoyer_message"]["approbation_requise"]) == (
        "T2", True)
    assert (outils["m9_payer"]["autonomie"], outils["m9_payer"]["approbation_requise"]) == ("T3", True)
    assert demo["erreur_outils"] is None
    assert demo["skills"] == ["procedure-demo"]
    assert demo["planifications"] == [{"nom": "digest", "cron": "0 7 * * 1-5", "consigne": "Résume la journée."}]
    assert demo["budget"] == {"tokens_jour": 1000, "tokens_mois": 20000, "alerte_pct": 80}
    assert demo["consommation"]["niveau"] == "alerte"
    assert demo["consommation"]["jour"] == {"utilise": 850, "limite": 1000, "pct": 85.0}
    assert demo["kpis"] == [{"id": "exemple", "description": "KPI d'exemple."}]
    assert demo["modeles"] == {"defaut": "standard", "extraction": "rapide"}
    assert demo["dependances"] == [] and demo["dependances_manquantes"] == []


def test_vue_suit_le_mode_effectif_et_recalcule_les_approbations(departements_demo, session):
    with session() as cnx:
        tableau_de_bord.changer_mode(cnx, departements_demo, "m09-demo", "autonome", "nathan")
        [demo] = tableau_de_bord.vue_departements(cnx, departements_demo, JOUR)
    assert (demo["mode"], demo["mode_manifeste"]) == ("autonome", "supervise")
    requises = {o["nom"]: o["approbation_requise"] for o in demo["outils"]}
    assert requises["m9_envoyer_message"] is False  # T2 passe en autonome
    assert requises["m9_payer"] is True  # T3 n'est jamais autonome


def test_vue_signale_dependance_manquante_et_outils_illisibles(departements_demo, session):
    casse = dataclasses.replace(
        departements_demo["m09-demo"], dependances=("m02-revenue-crm",), module_outils="module_absent_opsys"
    )
    with session() as cnx:
        [vue] = tableau_de_bord.vue_departements(cnx, {"m09-demo": casse}, JOUR)
    assert vue["dependances"] == vue["dependances_manquantes"] == ["m02-revenue-crm"]
    assert vue["outils"] == []
    assert "module_absent_opsys" in vue["erreur_outils"]


def test_modes_disponibles_derives_des_politiques():
    assert tableau_de_bord.modes_disponibles() == [
        {"mode": "ombre", "approbation_des": "T1"},
        {"mode": "supervise", "approbation_des": "T2"},
        {"mode": "autonome", "approbation_des": "T3"},
    ]


# -- changement de mode signé --------------------------------------------------------------------


def test_changer_mode_signe_et_persiste(departements_demo, session):
    with session() as cnx:
        resultat = tableau_de_bord.changer_mode(cnx, departements_demo, "m09-demo", "ombre", "nathan")
        assert resultat == {"departement": "m09-demo", "mode": "ombre", "par": "nathan"}
        assert approbations.mode_effectif(cnx, "m09-demo", "supervise") == "ombre"


@pytest.mark.parametrize(
    ("ident", "mode", "par", "erreur", "message"),
    [
        ("m09-inconnu", "autonome", "nathan", KeyError, "département inconnu"),
        ("m09-demo", "libre", "nathan", ValueError, "mode inconnu"),
        ("m09-demo", "ombre", "  ", ValueError, "signé"),
    ],
)
def test_changer_mode_refuse_sans_rien_modifier(departements_demo, session, ident, mode, par, erreur, message):
    with session() as cnx, pytest.raises(erreur, match=message):
        tableau_de_bord.changer_mode(cnx, departements_demo, ident, mode, par)
    with session() as cnx:
        assert approbations.mode_effectif(cnx, "m09-demo", "supervise") == "supervise"


# -- approbations --------------------------------------------------------------------------------


def test_lister_approbations_en_attente_d_abord_et_enrichies(departements_demo, session, demandes, nathan):
    paiement, message = demandes
    with session() as cnx:
        approbations.decider(cnx, message, False, nathan, {}, departements_demo, "non")
        toutes = tableau_de_bord.lister_approbations(cnx, departements_demo)
        refusees = tableau_de_bord.lister_approbations(cnx, departements_demo, "refusee")
        en_attente = tableau_de_bord.nombre_en_attente(cnx)

    # Le message traité est plus récent que le paiement en attente : l'attente passe quand même devant.
    assert [d["id"] for d in toutes] == [paiement, message]
    premier = toutes[0]
    assert (premier["statut"], premier["arguments"]) == ("en_attente", {"montant": 100})
    assert (premier["autonomie"], premier["description_outil"]) == ("T3", "Paie un fournisseur.")
    assert premier["departement_nom"] == "Démo"
    assert [d["id"] for d in refusees] == [message]
    assert (refusees[0]["decide_par"], refusees[0]["motif_decision"]) == ("nathan", "non")
    assert en_attente == 1


def test_lister_approbations_statut_inconnu_refuse(departements_demo, session):
    with session() as cnx, pytest.raises(ValueError, match="statut inconnu"):
        tableau_de_bord.lister_approbations(cnx, departements_demo, "bidon")


def test_statuts_connus_de_la_base(session, demandes):
    """STATUTS reste aligné sur la contrainte CHECK de la table approbations (opsys.etat)."""
    _, message = demandes
    with session() as cnx:
        for statut in tableau_de_bord.STATUTS:
            cnx.execute(text("UPDATE approbations SET statut = :statut WHERE id = :id"),
                       {"statut": statut, "id": message})
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            cnx.execute(text("UPDATE approbations SET statut = 'bidon' WHERE id = :id"), {"id": message})


def test_approuver_execute_l_outil_avec_les_arguments_exacts(departements_demo, session, demandes, nathan):
    _, message = demandes
    with session() as cnx:
        resultat = tableau_de_bord.decider_approbation(
            cnx, departements_demo, message, "approuver", nathan, "client d'accord"
        )
    assert resultat["statut"] == "executee" and resultat["reponse"]["ok"] is True
    assert demo_outils.JOURNAL == [{"a": "client", "texte": "Bonjour <b>"}]
    with session() as cnx:
        [traitee] = tableau_de_bord.lister_approbations(cnx, departements_demo, "executee")
    assert (traitee["decide_par"], traitee["motif_decision"]) == ("nathan", "client d'accord")
    assert traitee["decide_role"] == "nathan_owner"


def test_refuser_n_execute_rien(departements_demo, session, demandes, nathan):
    paiement, _ = demandes
    with session() as cnx:
        resultat = tableau_de_bord.decider_approbation(
            cnx, departements_demo, paiement, "refuser", nathan, "pas maintenant"
        )
    assert resultat == {"id": paiement, "statut": "refusee"}
    assert demo_outils.JOURNAL == []


def test_refus_possible_meme_si_les_outils_sont_illisibles(departements_demo, session, demandes, nathan):
    paiement, message = demandes
    casses = {"m09-demo": dataclasses.replace(departements_demo["m09-demo"], module_outils="module_absent_opsys")}
    with session() as cnx:
        assert tableau_de_bord.decider_approbation(cnx, casses, paiement, "refuser",
                                                    nathan)["statut"] == "refusee"
        with pytest.raises(ModuleNotFoundError):
            tableau_de_bord.decider_approbation(cnx, casses, message, "approuver", nathan)
        [restante] = tableau_de_bord.lister_approbations(cnx, casses, "en_attente")
    assert restante["id"] == message  # fail-closed : rien n'est exécuté, la demande reste en attente
    assert demo_outils.JOURNAL == []


def test_decisions_invalides_refusees(departements_demo, session, demandes, nathan):
    paiement, message = demandes
    with session() as cnx:
        with pytest.raises(ValueError, match="décision inconnue"):
            tableau_de_bord.decider_approbation(cnx, departements_demo, paiement, "peut-etre", nathan)
        with pytest.raises(ValueError, match="signée"):
            tableau_de_bord.decider_approbation(cnx, departements_demo, paiement, "approuver", " ")
        with pytest.raises(KeyError, match="demande inconnue"):
            tableau_de_bord.decider_approbation(cnx, departements_demo, "inconnue", "refuser", nathan)
        tableau_de_bord.decider_approbation(cnx, departements_demo, message, "refuser", nathan)
        with pytest.raises(ValueError, match="déjà traitée"):
            tableau_de_bord.decider_approbation(cnx, departements_demo, message, "approuver", nathan)
    assert demo_outils.JOURNAL == []


# -- budgets -------------------------------------------------------------------------------------


def test_budgets_de_tous_les_departements(departements_demo, session):
    with session() as cnx:
        jetons.enregistrer_usage(cnx, "m09-demo", "m", {"input_tokens": 1000}, JOUR)
        [budget] = tableau_de_bord.budgets(cnx, departements_demo, JOUR)
    assert (budget["departement"], budget["code"], budget["nom"]) == ("m09-demo", "M9", "Démo")
    assert (budget["alerte_pct"], budget["niveau"]) == (80, "epuise")
    assert budget["jour"] == {"utilise": 1000, "limite": 1000, "pct": 100.0}
    assert budget["mois"] == {"utilise": 1000, "limite": 20000, "pct": 5.0}


# -- paliers de modèles --------------------------------------------------------------------------


def test_lire_paliers_sans_fichier_signale_les_paliers_requis(departements_demo, opsys_home):
    vue = tableau_de_bord.lire_paliers(departements_demo)
    assert [p["nom"] for p in vue["paliers"]] == ["local", "rapide", "standard", "fort"]
    assert all(p["configuration"] is None for p in vue["paliers"])
    requis = {p["nom"]: p["requis_par"] for p in vue["paliers"]}
    assert requis["standard"] == [{"departement": "m09-demo", "code": "M9", "usage": "defaut"}]
    assert requis["rapide"] == [{"departement": "m09-demo", "code": "M9", "usage": "extraction"}]
    assert requis["local"] == requis["fort"] == []
    assert vue["manquants"] == ["rapide", "standard"]
    assert vue["fichier"] == str(opsys_home / "paliers.yaml")


def test_ecrire_palier_valide_par_le_socle_et_persiste(departements_demo, opsys_home, session):
    local = {"provider": "custom", "model": " qwen3:8b ", "base_url": "http://ollama:11434/v1"}
    resultat = tableau_de_bord.ecrire_palier("local", local, "nathan")
    attendu = {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"}
    assert resultat == {"palier": "local", "configuration": attendu, "par": "nathan",
                        "fichier": str(opsys_home / "paliers.yaml")}
    # Un champ texte vide (formulaire) vaut « absent » : base_url n'est pas exigée hors fournisseur custom.
    tableau_de_bord.ecrire_palier("standard", {"provider": "anthropic", "model": "claude-sonnet-5", "base_url": ""},
                                  "nathan")
    assert modeles.charger_paliers() == {
        "local": attendu, "standard": {"provider": "anthropic", "model": "claude-sonnet-5"}}
    assert tableau_de_bord.lire_paliers(departements_demo)["manquants"] == ["rapide"]


@pytest.mark.parametrize(
    ("palier", "configuration", "par", "message"),
    [
        ("local", {"provider": "custom", "model": "qwen3:8b"}, "nathan", "exige base_url"),
        ("geant", {"provider": "x", "model": "y"}, "nathan", "palier inconnu"),
        ("rapide", {"provider": "x", "model": "  "}, "nathan", "requis"),
        ("rapide", {"provider": "x", "model": "y", "base_url": "ftp://x"}, "nathan", "URL http"),
        ("rapide", "pas un objet", "nathan", "objet"),
        ("rapide", {"provider": "x", "model": "y"}, " ", "signée"),
        # Une faute de frappe ne doit pas être ignorée en silence (le socle écarte les clés inconnues).
        ("rapide", {"provider": "x", "model": "y", "baseurl": "http://llm:8000/v1"}, "nathan", "champ inconnu"),
    ],
)
def test_ecrire_palier_invalide_refuse_sans_rien_ecrire(opsys_home, palier, configuration, par, message):
    with pytest.raises(ValueError, match=message):
        tableau_de_bord.ecrire_palier(palier, configuration, par)
    assert not (opsys_home / "paliers.yaml").exists()


def test_champs_de_palier_alignes_sur_le_socle():
    complet = modeles.valider_palier("local", {"provider": "custom", "model": "m", "base_url": "http://llm:8000/v1"})
    assert set(complet) == set(tableau_de_bord.CHAMPS_PALIER)
