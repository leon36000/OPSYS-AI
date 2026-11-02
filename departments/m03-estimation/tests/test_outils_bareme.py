"""Outils de barème et de mesure déclarés, vrais outils (``executer_atomique``), base SQLite migrée (M3-C1, M3-C2).

Prouve : (1) l'AUTEUR est une personne authentifiée et revérifiée, jamais un agent ; (2) l'heure est celle du serveur
(horloge INJECTÉE ``opsys.horloge.maintenant``) ; (3) la VOIE LIBRE est fermée à l'exploitation (variable
d'environnement absente, ou appel venu du MCP) et ne se mêle jamais à une référence ; (4) les références
mènent à un calcul rejouable ;
(5) rien n'est écrit sur un refus ; (6) le journal d'audit ne garde ni montant ni nom. Données fictives.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from m2_preparation_estimation import marqueur_m2
from sqlalchemy import select

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import bareme_registre, mesure_declaree, outils_bareme  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import contexte, evenements, horloge, identite, stockage  # noqa: E402
from opsys.outils import Autonomie, executer_atomique  # noqa: E402
from opsys.stockage.schema import JOURNAL  # noqa: E402

_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
CONTRAT = {
    "lead_id": cb.LEAD, "conversation_id": "conv-bareme-001", "type_travaux": cb.SERVICE, "ville": "Quebec",
    "canal": "formulaire", "contact": {"nom": "Durand", "telephone": "5145550000"}, "urgence_declaree": False,
}
PHOTOS = [{"photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
           "reference_echelle": {"type": "porte", "dimensions_connues": True}}]
BAREME_LIBRE = {"version": "2026.1", "unite": "pi2",
                "postes": {cb.SERVICE: {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}}


def _outil(nom):
    return next(o for o in outils_m3.outils() if o.nom == nom)


def _appeler(nom, arguments, *, identite_=None, mcp=False):
    """Appel d'outil réel. ``identite_`` = (personne, rôle) d'un appareil authentifié ; ``mcp`` = transport agent."""
    def appel():
        return executer_atomique(_outil(nom), arguments)

    def avec_mcp():
        with contexte.transport_mcp():
            return appel()

    executer = avec_mcp if mcp else appel
    if identite_ is None:
        return executer()
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=identite_[0], role=identite_[1])):
        return executer()


def _resultat(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-bareme.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.MAINTENANT)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(cnx, "proprio.un", "Proprio Un", _MOT_DE_PASSE, roles=["nathan_owner", "admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "employe.un", "Employé Un", _MOT_DE_PASSE, roles=["employee"])
        identite.creer_personne(cnx, "inactif.un", "Inactif Un", _MOT_DE_PASSE, roles=["admin"], actif=False)
        identite.creer_personne(cnx, "agent.mathis", "Agent Mathis", _MOT_DE_PASSE, roles=["system_agent"])
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": cb.LEAD, "proprietaire": "vendeur.un", "horodatage_assignation": "2026-11-01T09:00:00-04:00"},
            evenement_id=f"m2-lead-assigne-{cb.LEAD}",
        )
    yield url
    stockage.liberer()


def _declarer_bareme(**surcharges):
    arguments = {
        "bareme_id": "bareme-fictif", "version_attendue": 0, "lignes": cb.lignes(), "date_effet": cb.JOUR_EFFET_V1,
        "parametres": deepcopy(cb.PARAMETRES), "soumission": deepcopy(cb.SOUMISSION),
    }
    arguments.update(surcharges)
    return _appeler("m3_declarer_bareme", arguments, identite_=("admin.un", "admin"))


def _declarer_mesure(**surcharges):
    arguments = {
        "mesure_id": "mesure-fictive-1", "revision_attendue": 0, "lead_id": cb.LEAD, "service": cb.SERVICE,
        "grandeur": "surface de revêtement", "valeur": "1200", "unite": "pi2", "borne_basse": "1200",
        "borne_haute": "1200", "methode": "releve_sur_place", "confiance": "elevee",
        "mesure_le": "2026-11-02T09:00:00+00:00", "pieces": ["photo-fictive-1"],
    }
    identite_ = surcharges.pop("identite_", ("admin.un", "admin"))
    arguments.update(surcharges)
    return _appeler("m3_declarer_mesure", arguments, identite_=identite_)


def _estimer(**surcharges):
    arguments = {
        "contrat": CONTRAT, "marqueur": marqueur_m2(cb.LEAD, contrat=CONTRAT), "photos": PHOTOS, "seuils": SEUILS,
    }
    mcp = surcharges.pop("mcp", False)
    arguments.update(surcharges)
    return _appeler("m3_estimer_projet", arguments, mcp=mcp)


def _refs():
    return {"bareme_ref": {"bareme_id": "bareme-fictif", "version": 1}, "mesure_ref": {"mesure_id": "mesure-fictive-1"}}


def _journal_des_estimations():
    with stockage.transaction():
        return list(stockage.maillons("m03-estimation", "principal"))


# ------------------------------------------------------------------------------------------------ déclaration
def test_un_agent_sans_identite_ne_declare_ni_bareme_ni_mesure_et_rien_n_est_ecrit(monde):
    arguments = {"bareme_id": "bareme-fictif", "version_attendue": 0, "lignes": cb.lignes(),
                 "date_effet": cb.JOUR_EFFET_V1}
    for mcp in (False, True):
        reponse = _resultat(_appeler("m3_declarer_bareme", arguments, mcp=mcp))
        assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-BAREME-IDENTITE"
        assert "jamais par un agent" in reponse["verdict"]["detail"]
    mesure = _resultat(_appeler("m3_declarer_mesure", {
        "mesure_id": "m", "revision_attendue": 0, "lead_id": cb.LEAD, "service": cb.SERVICE, "grandeur": "g",
        "valeur": "1", "unite": "pi2", "borne_basse": "1", "borne_haute": "1", "methode": "plan",
        "confiance": "elevee", "mesure_le": "2026-11-02T09:00:00+00:00", "pieces": []}))
    assert mesure["verdict"]["code"] == "REJ-MESURE-IDENTITE"
    assert _resultat(_appeler("m3_lister_baremes", {}))["resultat"]["baremes"] == []
    valider = _resultat(_appeler("m3_valider_bareme", {"bareme_id": "x", "version": 1}))
    assert valider["verdict"]["code"] == "REJ-BAREME-IDENTITE"


@pytest.mark.parametrize("personne, role", [
    ("employe.un", "employee"), ("vendeur.un", "seller"), ("agent.mathis", "system_agent"),
    ("inactif.un", "admin"),            # personne désactivée depuis l'émission du jeton
    ("employe.un", "admin"),            # rôle prétendu que la personne ne porte pas
    ("inconnue.x", "admin"),
])
def test_seul_un_proprietaire_ou_un_admin_actif_declare_un_bareme(monde, personne, role):
    arguments = {"bareme_id": "bareme-fictif", "version_attendue": 0, "lignes": cb.lignes(),
                 "date_effet": cb.JOUR_EFFET_V1}
    reponse = _resultat(_appeler("m3_declarer_bareme", arguments, identite_=(personne, role)))
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-BAREME-IDENTITE"
    assert _resultat(_appeler("m3_lister_baremes", {}))["resultat"]["baremes"] == []


def test_un_admin_declare_le_bareme_avec_l_heure_du_serveur_et_son_nom_d_auteur(monde):
    reponse = _resultat(_declarer_bareme())
    assert reponse["accepte"] is True
    resume = reponse["resultat"]
    assert resume["bareme_ref"]["bareme_id"] == "bareme-fictif" and resume["bareme_ref"]["version"] == 1
    assert resume["declaree_par"] == "admin.un" and resume["declaree_le"] == "2026-11-02T12:00:00+00:00"
    assert resume["services"] == [cb.SERVICE] and resume["plancher_rentable_declare"] is True
    assert resume["rejoue"] is False and resume["valide"] is True
    lu = _resultat(_appeler("m3_lire_bareme", {"bareme_id": "bareme-fictif"}))["resultat"]
    assert lu["auteur"] == {"personne": "admin.un", "role": "admin"} and lu["horodatage"] == "2026-11-02T12:00:00+00:00"


def test_un_agent_peut_lire_et_lister_sans_pouvoir_ecrire(monde):
    _declarer_bareme()
    liste = _resultat(_appeler("m3_lister_baremes", {}, mcp=True))["resultat"]["baremes"]
    assert liste[0]["version_en_vigueur"] == 1 and liste[0]["versions"][0]["version"] == 1
    lu = _resultat(_appeler("m3_lire_bareme", {"bareme_id": "bareme-fictif", "service": cb.SERVICE}, mcp=True))
    assert lu["resultat"]["lignes"][0]["source_ecrite"]
    inconnu = _resultat(_appeler("m3_lire_bareme", {"bareme_id": "inconnu"}, mcp=True))
    assert inconnu["verdict"]["code"] == "REJ-BAREME-INTROUVABLE"


def test_la_revision_et_le_rejeu_passent_par_les_outils(monde):
    _declarer_bareme()
    rejoue = _resultat(_declarer_bareme())
    assert rejoue["resultat"]["rejoue"] is True
    v2 = _resultat(_declarer_bareme(version_attendue=1, date_effet=cb.JOUR_EFFET_V2))
    assert v2["resultat"]["bareme_ref"]["version"] == 2
    perimee = _resultat(_declarer_bareme(version_attendue=1, date_effet=cb.JOUR_EFFET_V2,
                                          lignes=cb.lignes(cout_unitaire_max="99.00")))
    assert perimee["verdict"]["code"] == "REJ-BAREME-REVISION-PERIMEE"


def test_un_service_hors_taxonomie_est_refuse_avec_la_liste_des_services_declares(monde, declarer_services):
    declarer_services()
    inconnu = cb.lignes(service="pavage_de_lune")
    inconnu[1]["service"] = "pavage_de_lune"
    reponse = _resultat(_declarer_bareme(lignes=inconnu))
    assert reponse["verdict"]["code"] == "REJ-BAREME-INVALIDE" and "pavage_de_lune" in reponse["verdict"]["detail"]
    avec_declare = cb.lignes(service="gouttieres")
    avec_declare[1]["service"] = "gouttieres"
    assert _resultat(_declarer_bareme(lignes=avec_declare))["accepte"] is True


def test_valeur_de_depart_a_valider_inutilisable_puis_validee_par_le_proprietaire(monde):
    _declarer_bareme(a_valider=True)
    _resultat(_declarer_mesure())
    refus = _resultat(_estimer(**_refs()))
    assert refus["accepte"] is False and refus["verdict"]["code"] == "REJ-BAREME-A-VALIDER"
    par_vendeur = _resultat(_appeler("m3_valider_bareme", {"bareme_id": "bareme-fictif", "version": 1},
                                     identite_=("vendeur.un", "seller")))
    assert par_vendeur["verdict"]["code"] == "REJ-BAREME-IDENTITE"
    valide = _resultat(_appeler("m3_valider_bareme", {"bareme_id": "bareme-fictif", "version": 1},
                                identite_=("proprio.un", "nathan_owner")))
    assert valide["resultat"]["valide"] is True
    assert _resultat(_estimer(**_refs()))["accepte"] is True


def test_le_journal_d_audit_note_les_gestes_sans_montant_ni_nom_ni_contact(monde):
    _declarer_bareme()
    _declarer_mesure()
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(JOURNAL.c.par, JOURNAL.c.action, JOURNAL.c.cible, JOURNAL.c.details)).all()
    actions = {ligne.action: ligne for ligne in lignes if ligne.action.startswith("m3.")}
    assert set(actions) == {"m3.bareme_declare", "m3.mesure_declaree"}
    texte = json.dumps([tuple(ligne) for ligne in actions.values()], ensure_ascii=False)
    for interdit in ("14.00", "8.00", "9000", "Durand", "5145550000", "Revêtement", "1200", "Feuille de prix"):
        assert interdit not in texte, interdit
    assert json.loads(actions["m3.mesure_declaree"].details) == {
        "mesure_id": "mesure-fictive-1", "revision": 1, "lead_id": cb.LEAD}


# --------------------------------------------------------------------------------------------------- mesures
def test_la_mesure_est_declaree_par_un_admin_ou_le_vendeur_proprietaire_du_lead_seulement(monde):
    assert _resultat(_declarer_mesure())["accepte"] is True
    chez_proprietaire = _declarer_mesure(identite_=("vendeur.un", "seller"), mesure_id="m-vendeur", revision_attendue=0)
    assert _resultat(chez_proprietaire)["accepte"] is True
    autre_vendeur = _resultat(_declarer_mesure(identite_=("vendeur.deux", "seller"), mesure_id="m-autre"))
    assert autre_vendeur["verdict"]["code"] == "REJ-MESURE-IDENTITE"
    assert "propriétaire" in autre_vendeur["verdict"]["detail"]
    employe = _resultat(_declarer_mesure(identite_=("employe.un", "employee"), mesure_id="m-emp"))
    assert employe["verdict"]["code"] == "REJ-MESURE-IDENTITE"
    lue = _resultat(_appeler("m3_lire_mesure", {"mesure_id": "m-vendeur"}, mcp=True))["resultat"]
    assert lue["auteur"] == {"personne": "vendeur.un", "role": "seller"}
    introuvable = _resultat(_appeler("m3_lire_mesure", {"mesure_id": "m-autre"}))
    assert introuvable["verdict"]["code"] == "REJ-MESURE-INTROUVABLE"


def test_mesure_invalide_est_refusee_par_l_outil_avec_le_champ_fautif(monde):
    reponse = _resultat(_declarer_mesure(borne_basse="1300"))
    assert reponse["verdict"]["code"] == "REJ-MESURE-INVALIDE" and "encadrer" in reponse["verdict"]["detail"]
    avant_schema = _appeler("m3_declarer_mesure", {"mesure_id": "m"}, identite_=("admin.un", "admin"))
    assert avant_schema["ok"] is False  # le schéma d'entrée ferme les arguments avant tout effet


# -------------------------------------------------------------------------------------- la voie libre est fermée
def test_sans_la_variable_d_essai_un_bareme_libre_est_refuse_en_disant_quoi_declarer(monde, monkeypatch):
    monkeypatch.delenv(outils_bareme.ENV_VOIE_LIBRE)
    reponse = _resultat(_estimer(bareme=BAREME_LIBRE, quantite=1200, plancher_rentable=9000))
    assert (reponse["etape"], reponse["accepte"]) == ("bareme", False)
    assert reponse["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    detail = reponse["verdict"]["detail"]
    assert "['bareme', 'plancher_rentable', 'quantite']" in detail
    assert "m3_declarer_bareme" in detail and "m3_declarer_mesure" in detail and "bareme_ref" in detail
    assert _journal_des_estimations() == []


def test_sans_aucune_reference_l_estimation_est_refusee_et_dit_quoi_declarer(monde, monkeypatch):
    monkeypatch.delenv(outils_bareme.ENV_VOIE_LIBRE)
    reponse = _resultat(_estimer())
    assert reponse["verdict"]["code"] == "REJ-BAREME-REFERENCE-REQUISE"
    assert "bareme_ref {bareme_id, version}" in reponse["verdict"]["detail"]


def test_un_appel_d_agent_par_le_mcp_ne_passe_jamais_par_la_voie_libre_meme_avec_la_variable(monde):
    # La variable d'essai est posée (autouse) : l'agent, lui, vient du transport MCP.
    assert outils_bareme.voie_libre_autorisee() is True
    reponse = _resultat(_estimer(bareme=BAREME_LIBRE, quantite=1200, plancher_rentable=9000, mcp=True))
    assert reponse["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    assert _resultat(_estimer(mcp=True))["verdict"]["code"] == "REJ-BAREME-REFERENCE-REQUISE"
    with contexte.transport_mcp():
        assert outils_bareme.voie_libre_autorisee() is False
    assert _journal_des_estimations() == []


@pytest.mark.parametrize("valeur", ["", "oui", "1", "Essai", "essai "])
def test_seule_la_valeur_exacte_de_la_variable_ouvre_la_voie_d_essai(monde, monkeypatch, valeur):
    monkeypatch.setenv(outils_bareme.ENV_VOIE_LIBRE, valeur)
    assert outils_bareme.voie_libre_autorisee() is False
    assert _resultat(_estimer(bareme=BAREME_LIBRE, quantite=1200, plancher_rentable=9000))["accepte"] is False


def test_la_voie_d_essai_reste_ouverte_hors_mcp_pour_les_tests_historiques(monde):
    reponse = _resultat(_estimer(bareme=BAREME_LIBRE, quantite=1200, plancher_rentable=9000, graine=42))
    assert reponse["accepte"] is True and "declaration" not in reponse
    assert reponse["estimation"]["bareme_version"] == "2026.1"


def test_la_voie_d_essai_exige_encore_les_trois_valeurs(monde):
    reponse = _resultat(_estimer(bareme=BAREME_LIBRE))
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert "plancher_rentable" in reponse["verdict"]["detail"]


@pytest.mark.parametrize("libre", [
    {"bareme": BAREME_LIBRE}, {"quantite": 1200}, {"plancher_rentable": 1}, {"taux_marge": "0.9"},
    {"taux_marge_scenarios": {"normal": "0.9"}}, {"graine": 7},
])
def test_une_valeur_libre_ne_corrige_jamais_une_reference(monde, libre):
    _declarer_bareme()
    _declarer_mesure()
    reponse = _resultat(_estimer(**_refs(), **libre))
    assert (reponse["etape"], reponse["accepte"]) == ("bareme", False)
    assert reponse["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE" and list(libre)[0] in reponse["verdict"]["detail"]
    assert _journal_des_estimations() == []


# ------------------------------------------------------------------------------------- estimation par référence
def test_estimation_complete_par_references_avec_un_appel_d_agent(monde):
    _declarer_bareme()
    _declarer_mesure(valeur="1200", borne_basse="1020", borne_haute="1380", confiance="moyenne")
    reponse = _resultat(_estimer(**_refs(), mcp=True))
    assert reponse["accepte"] is True
    bloc = reponse["declaration"]
    assert bloc["bareme_ref"]["bareme_id"] == "bareme-fictif" and bloc["bareme_ref"]["version"] == 1
    assert bloc["revue_humaine_requise"] is True and bloc["statut_prix"] == "a_revoir"
    assert reponse["estimation"]["bareme_version"] == "bareme-fictif@v1"
    assert len(_journal_des_estimations()) == 1


def test_references_inconnues_perimees_ou_sans_mesure_sont_refusees_avec_un_message_lisible(monde):
    sans_bareme = _resultat(_estimer(**_refs()))
    assert sans_bareme["verdict"]["code"] == "REJ-BAREME-INTROUVABLE"
    assert "m3_declarer_bareme" in sans_bareme["verdict"]["detail"]
    _declarer_bareme()
    sans_mesure = _resultat(_estimer(bareme_ref=_refs()["bareme_ref"]))
    assert (sans_mesure["etape"], sans_mesure["verdict"]["code"]) == ("mesure", "REJ-MESURE-REQUISE")
    mesure_inconnue = _resultat(_estimer(**{**_refs(), "mesure_ref": {"mesure_id": "fantome"}}))
    assert mesure_inconnue["verdict"]["code"] == "REJ-MESURE-INTROUVABLE"
    version_inconnue = _resultat(_estimer(bareme_ref={"bareme_id": "bareme-fictif", "version": 9},
                                          mesure_ref=_refs()["mesure_ref"]))
    assert version_inconnue["verdict"]["code"] == "REJ-BAREME-VERSION-INCONNUE"
    assert _journal_des_estimations() == []


def test_le_barème_perime_apres_une_revision_est_refuse_a_la_date_de_la_revision(monde, monkeypatch):
    _declarer_bareme()
    _declarer_bareme(version_attendue=1, date_effet=cb.JOUR_EFFET_V2)
    _declarer_mesure()
    assert _resultat(_estimer(**_refs()))["accepte"] is True          # le 2 novembre : la version 1 est en vigueur
    futur_ref = {"bareme_ref": {"bareme_id": "bareme-fictif", "version": 2}, "mesure_ref": _refs()["mesure_ref"]}
    assert _resultat(_estimer(**futur_ref))["verdict"]["code"] == "REJ-BAREME-HORS-VIGUEUR"
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.APRES_V2)    # le 12 novembre (mesure : validité 30 jours)
    perimee = _resultat(_estimer(**_refs()))
    assert perimee["verdict"]["code"] == "REJ-BAREME-PERIME" and "version 2" in perimee["verdict"]["detail"]
    assert _resultat(_estimer(**futur_ref))["accepte"] is True


def test_l_heure_vient_du_serveur_jamais_de_l_appelant(monde, monkeypatch):
    _declarer_bareme(valide_jusqu_au="2026-11-05T00:00:00+00:00")
    _declarer_mesure()
    assert _resultat(_estimer(**_refs()))["accepte"] is True
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.MAINTENANT.replace(day=6))
    expire = _resultat(_estimer(**_refs()))
    assert expire["verdict"]["code"] == "REJ-BAREME-HORS-VIGUEUR"
    schema = _outil("m3_estimer_projet").parametres["properties"]
    assert not any("horodatage" in nom or "maintenant" in nom or "date" in nom for nom in schema)


def test_le_rejeu_par_l_outil_refait_le_calcul_apres_une_revision(monde, monkeypatch):
    _declarer_bareme()
    _declarer_mesure(valeur="1200", borne_basse="1020", borne_haute="1380", confiance="moyenne")
    estimation_id = _resultat(_estimer(**_refs()))["estimation"]["hash_maillon"]
    _declarer_bareme(version_attendue=1, date_effet=cb.JOUR_EFFET_V2,
                     lignes=cb.lignes(cout_unitaire_min="20.00", cout_unitaire_mode="22.00", cout_unitaire_max="30.00"))
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.APRES_V2)
    rapport = _resultat(_appeler("m3_rejouer_estimation", {"estimation_id": estimation_id}, mcp=True))
    assert rapport["accepte"] is True
    resultat = rapport["resultat"]
    assert resultat["identique"] is True and resultat["bareme_toujours_en_vigueur"] is False
    assert resultat["bareme_ref"]["version"] == 1
    inconnu = _resultat(_appeler("m3_rejouer_estimation", {"estimation_id": "0" * 64}))
    assert inconnu["verdict"]["code"] == "REJ-REJEU-IMPOSSIBLE"


# ------------------------------------------------------------------------------ outils d'aide : même fermeture
def test_les_outils_d_aide_ferment_aussi_le_bareme_et_le_plancher_libres(monde, monkeypatch):
    intervalle = {"borne_basse": 10000.0, "borne_haute": 12000.0, "niveau": 0.9}
    _declarer_bareme()
    _declarer_mesure()
    declare = _resultat(_appeler("m3_simuler_intervalle", {**_refs(), "type_travaux": cb.SERVICE}, mcp=True))
    assert declare["accepte"] is True and declare["resultat"]["bareme_ref"]["version"] == 1
    assert declare["resultat"]["quantite"] == "1200"
    libre_et_ref = _resultat(_appeler("m3_simuler_intervalle", {**_refs(), "type_travaux": cb.SERVICE, "graine": 3}))
    assert libre_et_ref["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    plancher = _resultat(_appeler("m3_confronter_plancher", {
        "intervalle": intervalle, "bareme_ref": _refs()["bareme_ref"]}))
    assert plancher["accepte"] is True
    assert plancher["resultat"]["alerte_plancher"] is False  # plancher déclaré : 9 000 $
    melange = _resultat(_appeler("m3_confronter_plancher", {
        "intervalle": intervalle, "bareme_ref": _refs()["bareme_ref"], "plancher_rentable": 1}))
    assert melange["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    monkeypatch.delenv(outils_bareme.ENV_VOIE_LIBRE)
    simulation = _resultat(_appeler("m3_simuler_intervalle", {
        "bareme": BAREME_LIBRE, "type_travaux": cb.SERVICE, "quantite": 1200, "graine": 1}))
    assert simulation["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    comparaison = _resultat(_appeler("m3_confronter_plancher", {"intervalle": intervalle, "plancher_rentable": 99999}))
    assert comparaison["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    rien = _resultat(_appeler("m3_confronter_plancher", {"intervalle": intervalle}))
    assert rien["verdict"]["code"] == "REJ-BAREME-REFERENCE-REQUISE"


def test_les_outils_d_aide_gardent_la_voie_d_essai_pour_les_tests(monde):
    simulation = _resultat(_appeler("m3_simuler_intervalle", {
        "bareme": BAREME_LIBRE, "type_travaux": cb.SERVICE, "quantite": 1200, "graine": 1}))
    assert simulation["accepte"] is True
    comparaison = _resultat(_appeler("m3_confronter_plancher", {
        "intervalle": {"borne_basse": 1.0, "borne_haute": 2.0, "niveau": 0.9}, "plancher_rentable": 5}))
    assert comparaison["resultat"]["alerte_plancher"] is True


# --------------------------------------------------------------------------------------------- contrat d'outil
def test_contrats_d_outil_des_nouveaux_outils():
    attendus = {
        "m3_declarer_bareme": (Autonomie.T1, {"admin"}), "m3_valider_bareme": (Autonomie.T1, {"admin"}),
        "m3_declarer_mesure": (Autonomie.T1, {"seller", "admin"}),
        "m3_lire_mesure": (Autonomie.T0, {"seller", "admin"}),
        "m3_lire_bareme": (Autonomie.T0, {"admin"}), "m3_lister_baremes": (Autonomie.T0, {"admin"}),
        "m3_rejouer_estimation": (Autonomie.T0, set()),
    }
    for nom, (autonomie, roles) in attendus.items():
        outil = _outil(nom)
        assert outil.autonomie is autonomie and set(outil.roles_appareil) == roles, nom
        assert outil.parametres["additionalProperties"] is False and len(outil.description) <= 1024
    estimer = _outil("m3_estimer_projet")
    assert estimer.roles_appareil == frozenset()  # toujours fermé aux appareils
    assert estimer.parametres["required"] == ["contrat", "marqueur", "photos", "seuils"]
    assert {"bareme_ref", "mesure_ref"} <= set(estimer.parametres["properties"])
    assert estimer.parametres["properties"]["bareme_ref"]["required"] == ["bareme_id", "version"]


def test_les_ecritures_exposent_la_fonction_unique_que_les_reglages_de_direction_pourront_appeler():
    assert callable(bareme_registre.declarer_version) and callable(mesure_declaree.declarer)
    # un seul écrivain de versions dans le registre pur : aucun autre module n'ajoute de maillon de barème
    sources = Path(bareme_registre.__file__).read_text(encoding="utf-8")
    assert sources.count("_ajouter(") == 2  # déclaration et validation
