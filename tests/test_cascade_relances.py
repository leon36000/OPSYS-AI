"""PLAN T4.9 (M2.7, M2.13) — les relances dues, avec consentement et fréquence limitée, par le VRAI bus.

Le trajet, sans réseau ni core (le core ne s'exécute pas ici) :

    SMS du client -> `m1_recevoir_message_canal` (vrai M1) -> `m1.lead_qualifie` -> M2 ingère, un vendeur qualifie
    M3 : `m3_creer_devis`, le vendeur DEMANDE l'envoi (N4), le propriétaire l'approuve dans la vraie file d'approbation
      -> le devis passe `envoye` et M3 PUBLIE `m3.devis_envoye` (vrai M3, même transaction)
    -> `evenements.repartir` (vrai répartiteur) -> M2 range l'envoi à l'instant que M3 a publié
    le délai passe : `m2_lister_relances` (vrai outil, identité d'appareil) liste la relance due, avec la règle citée
    le vendeur inscrit le consentement SMS du client, puis PRÉPARE la relance : un texte fixe, rien n'est envoyé
    SMS « STOP » -> M1 inscrit le retrait et PUBLIE `m1.retrait_consentement` -> M2 le range (le `lead_id`, jamais le
      numéro) : plus aucune relance SMS ni courriel pour cette personne, l'appel reste permis, un retrait ne se lève pas

Vrais départements (`charger_departements`), vrais outils (`Capacites` pour M1 et M3, `executer_atomique` avec une
identité d'appareil pour M2), vrai répartiteur, base SQLite migrée. Ce que ce fichier ne prouve PAS : l'envoi réel d'un
SMS (T2.1-c, N4, une personne), le core, l'écran. La porte d'appareil complète est prouvée par
`tests/e2e/test_relances_vendeur_appareil.py`. Le délai (14 jours) et la fréquence (7 jours) sont ceux d'un manifeste
JETABLE : les vraies valeurs sont à décider par Nathan. Données fictives (numéro en 555, personnes de test).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from m1_front_office import outils as m1_outils
from m2_revenue_crm import gabarits_relance
from m2_revenue_crm import outils as m2_outils
from m3_estimation import contrats, hierarchie_echelle
from m3_estimation import outils as m3_outils
from sqlalchemy import func, select

from opsys import approbations, contexte, evenements, idempotence, identite, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
M1, M2, M3 = "m01-front-office", "m02-revenue-crm", "m03-estimation"
CONSOMMATEURS_DU_TEST = {M1, M2}
DEBUT = dt.datetime(2026, 9, 29, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
GOUTTIERES = "Bonjour, mes gouttières fuient à Laval, c'est urgent."
SOFFITE = "Aussi le soffite à Laval, merci."
SMS_INITIAL = "2026-09-01T09:15:00-04:00"
QUALIFIE_LE = "2026-09-02T09:00:00-04:00"
DEVIS_CREE_LE = "2026-09-09T10:00:00-04:00"
ENVOI = "2026-09-10T13:00:00+00:00"  # la décision du propriétaire (figée) : l'envoi approuvé, publié par M3
ECHEANCE = "2026-09-24T13:00:00+00:00"  # l'envoi + 14 jours
STOP_LE = "2026-09-26T09:00:00-04:00"
RECUEILLI = "2026-09-20T10:00:00-04:00"
ACTION = {"description": "Préparer la soumission (fictif)", "echeance": "2026-09-05T09:00:00-04:00"}

VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}

SEGMENTS = {"jours_inactivite_dormant": 60, "jours_soumission_perimee": 14}
RELANCES = {"jours_entre_relances": 7}
CONTEXTE_REVUE = {
    "niveau_confiance_hierarchie": hierarchie_echelle.NIVEAUX_CONFIANCE[2],
    "verdict_estimation": contrats.VERDICT_AUCUN_BLOCAGE,
    "alerte_plancher": False, "service_complexe": False, "client_a_risque": False, "distance_km": "20",
    "donnees_fournisseur_completes": True,
}
SEUILS_REVUE = {
    "confiance_minimale": hierarchie_echelle.NIVEAUX_CONFIANCE[1], "montant_maximal_cad": 10000, "marge_minimale": 0.10,
    "distance_maximale_km": 50, "minimum_rentable_cad": 500,
}


# -- installation ------------------------------------------------------------------------------------------
def _manifeste_jetable(module: Any, tmp_path: Path, nom: str, configuration: dict[str, Any], monkeypatch) -> None:
    """Le `department.yaml` du département, dont seule `configuration` change (relu à chaque appel par le module)."""
    reel = yaml.safe_load(module._MANIFESTE.read_text(encoding="utf-8")) or {}
    chemin = tmp_path / nom
    chemin.write_text(yaml.safe_dump({**reel, "configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(module, "_MANIFESTE", chemin)


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    """Base migrée, M1 et M2 sur le stockage durable, les personnes, le délai et la fréquence de l'entreprise."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    _manifeste_jetable(m2_outils, tmp_path, "m2.yaml", {"segments": SEGMENTS, "relances": RELANCES}, monkeypatch)
    _manifeste_jetable(m3_outils, tmp_path, "m3.yaml", {"revue_devis": SEUILS_REVUE}, monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
    deps = charger_departements()
    yield deps
    m1_outils.reinitialiser_registre()
    m2_outils.reinitialiser_registre()
    stockage.liberer()


@pytest.fixture
def capacites_m1(instance):
    return Capacites(instance, stockage.transaction, filtre={M1}, memoire=False)


@pytest.fixture
def capacites_m3(instance):
    return Capacites(instance, stockage.transaction, filtre={M3}, memoire=False)


# -- aides -------------------------------------------------------------------------------------------------
def _drainer(deps, *, max_tours: int = 12) -> dict[str, int]:
    """Livre le bus jusqu'à quiescence, à M1 et à M2 seulement (le vrai répartiteur, leurs vrais manifestes)."""
    sous_ensemble = {i: d for i, d in deps.items() if i in CONSOMMATEURS_DU_TEST}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = evenements.repartir(
            sous_ensemble, maintenant=(DEBUT + dt.timedelta(hours=3, seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _sms(texte: str, message_id: str, recu_le: str, expediteur: str = NUMERO) -> dict[str, str]:
    return {"canal": "sms", "expediteur": expediteur, "message_id": message_id, "recu_le": recu_le, "texte": texte}


def _client_ecrit(capacites, texte: str, message_id: str, recu_le: str) -> dict[str, Any]:
    reponse = capacites.appeler("m1_recevoir_message_canal", _sms(texte, message_id, recu_le))
    assert reponse["ok"] is True and "statut" not in reponse, reponse
    return reponse["resultat"]


def _m2(deps, nom: str, arguments: dict[str, Any], appelant: contexte.IdentiteAppelante | None = None):
    outil = next(o for o in deps[M2].charger_outils() if o.nom == nom)
    if appelant is None:
        return executer_atomique(outil, arguments)
    with contexte.appele_par_appareil(appelant):
        return executer_atomique(outil, arguments)


def _accepte(reponse: dict[str, Any]) -> Any:
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refuse(reponse: dict[str, Any]) -> dict[str, Any]:
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _qualifier(deps, lead_id: str, proprietaire: str = "vendeur.un") -> None:
    _accepte(_m2(deps, "m2_transitionner_statut", {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": QUALIFIE_LE, "owner": proprietaire,
        "prochaine_action": ACTION}))


def _envoyer_le_devis(deps, capacites_m3, monkeypatch, lead_id: str, devis_id: str, proprietaire: str = "vendeur.un"):
    """La chaîne RÉELLE de M3 : le devis est créé, le vendeur DEMANDE l'envoi (N4), le propriétaire l'approuve dans la
    file d'approbation ; le socle date la décision (ici figée à `ENVOI`) et M3 publie `m3.devis_envoye`. Rend l'id."""
    monkeypatch.setattr(approbations, "_maintenant", lambda: ENVOI)
    creation = executer_atomique(next(o for o in deps[M3].charger_outils() if o.nom == "m3_creer_devis"), {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Gouttière alu 5 po (fictif)", "quantite": "1", "unite": "forfait",
                    "cout_unitaire": "1600.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.25", "horodatage": DEVIS_CREE_LE})
    assert creation["ok"] is True and creation["resultat"]["accepte"] is True, creation
    meta = idempotence.Meta(cle=f"cle-envoi-{devis_id}", appareil="tel-vendeur-fictif",
                            horodatage_appareil="2026-09-09T10:05:00-04:00")
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=proprietaire, role="seller")):
        proposition = capacites_m3.appeler(
            "m3_demander_envoi_devis", {"devis_id": devis_id, "contexte_revue": CONTEXTE_REVUE}, meta)
    assert proposition["ok"] is True and proposition["statut"] == "en_attente_approbation", proposition
    with stockage.transaction() as cnx:
        outils = outils_executables(deps, lambda: contextlib.nullcontext(cnx))
        decision = approbations.decider(cnx, proposition["demande_id"], True, "nathan", outils, deps)
    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"] is True, decision
    return f"m3-devis-envoye-{devis_id}"


def _lister(deps, appelant, maintenant: str, **plus):
    return _accepte(_m2(deps, "m2_lister_relances", {"horodatage": maintenant, **plus}, appelant))


def _preparer(deps, lead_id: str, canal: str, maintenant: str, appelant=VENDEUR_UN):
    return _m2(deps, "m2_preparer_relance", {
        "lead_id": lead_id, "regle": "relance_devis_sans_reponse", "canal": canal, "horodatage": maintenant}, appelant)


def _consentement(deps, lead_id: str, canal: str = "sms", appelant=VENDEUR_UN, **plus):
    return _m2(deps, "m2_enregistrer_consentement_contact", {
        "lead_id": lead_id, "canal": canal, "enonce_version": "consentement-sms-v1", "source": "formulaire",
        "preuve": dict(PREUVE), "recueilli_le": RECUEILLI, "horodatage": "2026-09-20T10:05:00-04:00", **plus}, appelant)


def _registre(nom: str, departement: str = M2) -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(departement, nom))


def _registres_de_relance() -> dict[str, list[dict[str, Any]]]:
    return {nom: _registre(nom) for nom in ("devis_envoyes_recus", "consentements_contact", "relances_preparees")}


def _recu(evenement_id: str, consommateur: str = M2) -> dict[str, Any] | None:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == consommateur)
        )).mappings().first()
    return None if ligne is None else dict(ligne)


def _evenements_retrait() -> list[tuple[str, dict[str, Any]]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.retrait_consentement"
        ).order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).all()
    return [(ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes]


def _nombre_de_maillons() -> dict[str, int]:
    """Ce qu'un rejeu ne doit JAMAIS changer : le nombre de maillons de chaque registre."""
    with stockage.transaction() as cnx:
        return {
            f"{ligne.departement}/{ligne.registre}": ligne.n
            for ligne in cnx.execute(select(REGISTRES.c.departement, REGISTRES.c.registre, func.count().label("n"))
                                     .group_by(REGISTRES.c.departement, REGISTRES.c.registre))
        }


def _relance_de(page: dict[str, Any], lead_id: str) -> dict[str, Any]:
    (item,) = [r for r in page["relances"] if r["lead_id"] == lead_id]
    return item


def _un_client_avec_un_devis_envoye(deps, capacites_m1, capacites_m3, monkeypatch):
    """Le début commun : SMS du client, lead ingéré par M2 et qualifié au vendeur un, devis envoyé (vrai M3), livré."""
    lead_id = _client_ecrit(capacites_m1, GOUTTIERES, "SM-1", SMS_INITIAL)["lead"]["lead_id"]
    assert _drainer(deps)["quarantaines"] == 0
    _qualifier(deps, lead_id)
    evenement_id = _envoyer_le_devis(deps, capacites_m3, monkeypatch, lead_id, "DEVIS-T49-1")
    resume = _drainer(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    return lead_id, evenement_id


# =====================================================================================================================
# Le scénario : l'envoi du devis, le délai, le consentement, la relance préparée, le STOP
# =====================================================================================================================
def test_de_l_envoi_du_devis_au_stop_par_le_vrai_bus(instance, capacites_m1, capacites_m3, monkeypatch):
    deps = instance
    lead_id, evenement_id = _un_client_avec_un_devis_envoye(deps, capacites_m1, capacites_m3, monkeypatch)

    # M3 a publié l'envoi (charge fermée, sans montant) ; M2 l'a reçu par le vrai répartiteur et l'a rangé.
    with stockage.transaction():
        charge = evenements.charge_publiee("m3.devis_envoye", evenement_id)
    assert charge == {"devis_id": "DEVIS-T49-1", "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": ENVOI}
    assert _recu(evenement_id)["statut"] == "traite"
    (envoi,) = _registre("devis_envoyes_recus")
    assert (envoi["devis_id"], envoi["lead_id"], envoi["horodatage_envoi"]) == ("DEVIS-T49-1", lead_id, ENVOI)

    # Le délai n'est pas écoulé : aucune relance due. À l'échéance exacte (l'envoi + 14 jours) : une, avec sa règle.
    avant = _lister(deps, VENDEUR_UN, "2026-09-24T12:59:59+00:00")
    assert avant["relances"] == [] and avant["total"] == 0 and avant["regles_non_calculables"] == []
    page = _lister(deps, VENDEUR_UN, ECHEANCE)
    relance = _relance_de(page, lead_id)
    assert (relance["regle"], relance["statut"], relance["proprietaire"]) == (
        "relance_devis_sans_reponse", "qualifie", "vendeur.un")
    assert relance["due_depuis"] == ECHEANCE
    assert relance["depart"]["fait"] == "m3.devis_envoye" and relance["depart"]["instant"] == ENVOI
    assert relance["segment"]["donnee"] | {"jours_ecoules": 14} == relance["segment"]["donnee"]
    assert relance["segment"]["donnee"]["devis_id"] == "DEVIS-T49-1"
    assert (relance["mode"], relance["canaux_permis"]) == ("appel_seulement", ["appel"])
    assert relance["derniere_relance"] is None and relance["permise_maintenant"] is True

    # Un seul vendeur la voit : l'autre vendeur n'a rien, l'admin voit tout.
    assert _lister(deps, VENDEUR_DEUX, ECHEANCE)["relances"] == []
    assert [r["lead_id"] for r in _lister(deps, ADMIN, ECHEANCE)["relances"]] == [lead_id]

    # Sans consentement, aucun SMS : refusé, rien n'est écrit. L'appel reste permis.
    assert _refuse(_preparer(deps, lead_id, "sms", "2026-09-25T09:00:00-04:00"))["code"] == "REJ-CONSENTEMENT-ABSENT"
    assert _registre("relances_preparees") == []

    # Le vendeur inscrit le consentement que le client a donné : le SMS devient permis. Rien n'est envoyé.
    consentement = _accepte(_consentement(deps, lead_id))
    assert (consentement["etat"], consentement["enregistre_par"], consentement["voie"]) == (
        "actif", "vendeur.un", "appareil")
    page = _lister(deps, VENDEUR_UN, "2026-09-25T09:00:00-04:00")
    assert _relance_de(page, lead_id)["canaux_permis"] == ["appel", "sms"]
    sms = _accepte(_preparer(deps, lead_id, "sms", "2026-09-25T09:00:00-04:00"))
    assert sms["envoye"] is False and sms["texte"] == gabarits_relance.GABARITS[
        ("relance_devis_sans_reponse", "sms")]["texte"]
    assert "répondez STOP" in sms["texte"]
    assert sms["prochaine_date_permise"] == "2026-10-02T13:00:00+00:00"

    # La fréquence : pas de seconde relance avant la prochaine date permise (elle est dite), permise pile à la date.
    trop_tot = _refuse(_preparer(deps, lead_id, "appel", "2026-10-02T12:59:59+00:00"))
    assert trop_tot["code"] == "REJ-RELANCE-TROP-PROCHE" and "2026-10-02T13:00:00+00:00" in trop_tot["detail"]
    assert len(_registre("relances_preparees")) == 1

    # Le STOP du client à M1 : M1 inscrit le retrait ET publie le fait ; M2 le reçoit par le vrai répartiteur.
    stop = _client_ecrit(capacites_m1, "STOP", "SM-STOP", STOP_LE)
    assert stop["decision"] == "RETRAIT_CONSENTEMENT"
    ((retrait_id, charge_retrait),) = _evenements_retrait()
    assert stop["retrait_publie"] == {"leads": 1, "evenement_id": retrait_id}
    assert charge_retrait["lead_ids"] == [lead_id] and charge_retrait["canal"] == "sms"
    resume = _drainer(deps)
    assert resume["traites"] == 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _recu(retrait_id)["statut"] == "traite"
    (retrait,) = [m for m in _registre("consentements_contact") if m["type_entree"] == "retrait_contact"]
    assert (retrait["lead_id"], retrait["canal"], retrait["source"]) == (lead_id, "sms", "bus:m1.retrait_consentement")

    # Plus aucun message : ni SMS ni courriel, même avec un consentement inscrit avant. L'appel reste permis.
    apres_frequence = "2026-10-05T12:00:00-04:00"
    page = _lister(deps, VENDEUR_UN, apres_frequence)
    relance = _relance_de(page, lead_id)
    assert (relance["mode"], relance["canaux_permis"]) == ("appel_seulement", ["appel"])
    assert relance["consentements"]["sms"]["etat"] == "retire"
    assert relance["derniere_relance"] == {"le": "2026-09-25T09:00:00-04:00", "canal": "sms"}
    assert relance["permise_maintenant"] is True
    for canal in ("sms", "courriel"):
        refus = _refuse(_preparer(deps, lead_id, canal, apres_frequence))
        assert refus["code"] == "REJ-CONSENTEMENT-RETIRE", canal
    assert _accepte(_preparer(deps, lead_id, "appel", apres_frequence))["canal"] == "appel"

    # Un retrait ne se lève pas : aucun consentement ne peut plus être inscrit, par personne.
    for appelant in (VENDEUR_UN, ADMIN):
        assert _refuse(_consentement(deps, lead_id, "sms", appelant, enonce_version="consentement-sms-v2"))[
            "code"] == "REJ-CONSENTEMENT-RETIRE"
    assert len([m for m in _registre("consentements_contact") if m["type_entree"] == "consentement_contact"]) == 1


def test_les_rejeux_du_bus_et_du_stop_n_ecrivent_rien_de_plus(instance, capacites_m1, capacites_m3, monkeypatch):
    deps = instance
    lead_id, evenement_id = _un_client_avec_un_devis_envoye(deps, capacites_m1, capacites_m3, monkeypatch)
    _accepte(_consentement(deps, lead_id))
    _client_ecrit(capacites_m1, "STOP", "SM-STOP", STOP_LE)
    assert _drainer(deps)["traites"] == 1
    ((retrait_id, charge_retrait),) = _evenements_retrait()
    avant = _registres_de_relance()
    maillons_avant = _nombre_de_maillons()
    assert len(avant["devis_envoyes_recus"]) == 1 and len(avant["consentements_contact"]) == 2

    # M1 reçoit le même STOP une seconde fois : un doublon, rien n'est publié, rien n'est livré.
    assert _client_ecrit(capacites_m1, "STOP", "SM-STOP", STOP_LE)["doublon"] is True
    assert _drainer(deps)["livres"] == 0

    # Les producteurs republient les mêmes faits, sous le même identifiant puis sous un autre : M2 n'écrit rien de plus.
    with stockage.transaction():
        evenements.publier("m3.devis_envoye", M3, {"devis_id": "DEVIS-T49-1", "lead_id": lead_id, "chantier_id": None,
                                                   "horodatage_envoi": ENVOI}, evenement_id=evenement_id)
        evenements.publier("m1.retrait_consentement", M1, charge_retrait, evenement_id=retrait_id)
    assert _drainer(deps)["livres"] == 0
    with stockage.transaction():
        evenements.publier("m3.devis_envoye", M3, {"devis_id": "DEVIS-T49-1", "lead_id": lead_id, "chantier_id": None,
                                                   "horodatage_envoi": ENVOI}, evenement_id="rejeu-autre-producteur")
        evenements.publier("m1.retrait_consentement", M1, charge_retrait, evenement_id="rejeu-retrait-autre-id")
    resume = _drainer(deps)
    assert resume["livres"] == 2 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _registres_de_relance() == avant
    assert _nombre_de_maillons() == maillons_avant, "aucun maillon de plus, dans aucun registre"
    assert evenements.etat()["quarantaine"] == []


def test_un_stop_qui_arrive_avant_le_devis_et_le_consentement_garde_l_appel_seulement(
        instance, capacites_m1, capacites_m3, monkeypatch):
    """L'ordre inverse : le client se retire d'abord ; le devis part ensuite ; jamais de message, ni consentement."""
    deps = instance
    lead_id = _client_ecrit(capacites_m1, GOUTTIERES, "SM-1", SMS_INITIAL)["lead"]["lead_id"]
    _drainer(deps)
    _qualifier(deps, lead_id)
    _client_ecrit(capacites_m1, "STOP", "SM-STOP", "2026-09-03T09:00:00-04:00")
    _envoyer_le_devis(deps, capacites_m3, monkeypatch, lead_id, "DEVIS-T49-2")
    resume = _drainer(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    relance = _relance_de(_lister(deps, VENDEUR_UN, ECHEANCE), lead_id)
    assert (relance["mode"], relance["canaux_permis"]) == ("appel_seulement", ["appel"])
    assert relance["consentements"]["sms"]["etat"] == "retire"
    assert _refuse(_consentement(deps, lead_id))["code"] == "REJ-CONSENTEMENT-RETIRE"
    assert _refuse(_preparer(deps, lead_id, "sms", ECHEANCE))["code"] == "REJ-CONSENTEMENT-RETIRE"
    assert _accepte(_preparer(deps, lead_id, "appel", ECHEANCE))["canal"] == "appel"


def test_le_devis_qui_arrive_avant_le_lead_attend_puis_tout_converge_sans_doublon(
        instance, capacites_m3, monkeypatch):
    """M3 publie l'envoi d'un devis dont le lead n'est pas encore chez M2 : incohérence de données, donc l'événement
    attend (réessais, jamais perdu ni ignoré en silence) ; le lead arrive, l'événement est livré, la relance se
    calcule."""
    deps = instance
    lead_id = "LEAD-T49-INVERSE"
    evenement_id = _envoyer_le_devis(deps, capacites_m3, monkeypatch, lead_id, "DEVIS-T49-3")  # lead inconnu de M2

    premier = evenements.repartir({M2: deps[M2]}, maintenant=DEBUT.isoformat())
    assert (premier["livres"], premier["echecs"], premier["quarantaines"]) == (1, 1, 0), premier
    assert _recu(evenement_id)["statut"] == "echec" and "LeadIntrouvable" in _recu(evenement_id)["derniere_erreur"]
    assert _registre("devis_envoyes_recus") == [], "rien n'est rangé à moitié"

    ingestion = _m2(deps, "m2_ingerer_lead", {"contrat": {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": NUMERO},
        "type_travaux": "renovation_totale", "ville": "Laval", "urgence_declaree": False, "canal": "telephone",
    }, "horodatage": SMS_INITIAL})
    assert ingestion["ok"] is True and ingestion["resultat"]["accepte"] is True, ingestion
    _qualifier(deps, lead_id)
    resume = _drainer(deps)
    assert (resume["traites"], resume["quarantaines"]) == (1, 0), resume
    assert _recu(evenement_id)["statut"] == "traite" and evenements.etat()["quarantaine"] == []
    (envoi,) = _registre("devis_envoyes_recus")
    assert (envoi["devis_id"], envoi["horodatage_envoi"]) == ("DEVIS-T49-3", ENVOI)
    relance = _relance_de(_lister(deps, VENDEUR_UN, ECHEANCE), lead_id)
    assert relance["depart"]["instant"] == ENVOI and relance["due_depuis"] == ECHEANCE


def test_le_stop_d_une_personne_ferme_les_canaux_de_tous_ses_leads(instance, capacites_m1, capacites_m3, monkeypatch):
    """Un même numéro, deux affaires : M2 les rattache à un seul client. Le STOP vaut pour la PERSONNE."""
    deps = instance
    premier = _client_ecrit(capacites_m1, GOUTTIERES, "SM-1", SMS_INITIAL)["lead"]["lead_id"]
    second = _client_ecrit(capacites_m1, SOFFITE, "SM-2", "2026-09-01T10:00:00-04:00")["lead"]["lead_id"]
    assert premier != second
    _drainer(deps)
    _qualifier(deps, premier)
    _qualifier(deps, second, "vendeur.deux")
    _envoyer_le_devis(deps, capacites_m3, monkeypatch, premier, "DEVIS-T49-A")
    _envoyer_le_devis(deps, capacites_m3, monkeypatch, second, "DEVIS-T49-B", "vendeur.deux")
    _drainer(deps)
    _accepte(_consentement(deps, premier))

    # Le consentement est celui de la personne : le second lead (l'autre vendeur) peut aussi recevoir un SMS.
    page = _lister(deps, VENDEUR_DEUX, ECHEANCE)
    assert _relance_de(page, second)["canaux_permis"] == ["appel", "sms"]
    # La fréquence est celle de la personne : une relance du premier lead ferme la seconde pour sept jours.
    _accepte(_preparer(deps, premier, "appel", ECHEANCE))
    trop_proche = _refuse(_preparer(deps, second, "appel", ECHEANCE, VENDEUR_DEUX))
    assert trop_proche["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert premier not in json.dumps(trop_proche) and "vendeur.un" not in json.dumps(trop_proche)

    _client_ecrit(capacites_m1, "STOP", "SM-STOP", STOP_LE)
    assert _drainer(deps)["echecs"] == 0
    for lead_id, vendeur in ((premier, VENDEUR_UN), (second, VENDEUR_DEUX)):
        relance = _relance_de(_lister(deps, vendeur, "2026-10-05T12:00:00-04:00"), lead_id)
        assert relance["canaux_permis"] == ["appel"], lead_id


def test_aucun_numero_ni_courriel_dans_ce_que_t4_9_ecrit_ni_dans_les_faits_du_bus(
        instance, capacites_m1, capacites_m3, monkeypatch):
    deps = instance
    lead_id, evenement_id = _un_client_avec_un_devis_envoye(deps, capacites_m1, capacites_m3, monkeypatch)
    _accepte(_consentement(deps, lead_id))
    _accepte(_preparer(deps, lead_id, "sms", ECHEANCE))
    _client_ecrit(capacites_m1, "STOP", "SM-STOP", STOP_LE)
    _drainer(deps)

    ecrit = json.dumps({**_registres_de_relance(), "evenements": [c for _, c in _evenements_retrait()]})
    with stockage.transaction():
        ecrit += json.dumps(evenements.charge_publiee("m3.devis_envoye", evenement_id))
    for secret in (NUMERO, NUMERO.removeprefix("+1"), "5145550142", "@"):
        assert secret not in ecrit, secret
    # Ni les montants du devis (M3 les garde) ne traversent : ni prix, ni coût, ni marge chez M2 pour les relances.
    for interdit in ("1600", "2000", "prix", "cout", "marge"):
        assert interdit not in ecrit, interdit


def test_le_bus_est_coherent_m3_publie_m1_publie_et_m2_consomme_les_deux_faits(instance):
    deps = instance
    assert "m3.devis_envoye" in evenements.types_connus() and "m1.retrait_consentement" in evenements.types_connus()
    assert "m3.devis_envoye" in deps[M3].evenements_publie
    assert "m1.retrait_consentement" in deps[M1].evenements_publie
    assert {"m3.devis_envoye", "m1.retrait_consentement"} <= set(deps[M2].evenements_consomme)
    consommateurs = deps[M2].charger_consommateurs()
    assert consommateurs["m3.devis_envoye"] is m2_outils.consommateurs()["m3.devis_envoye"]
    assert consommateurs["m1.retrait_consentement"] is m2_outils.consommateurs()["m1.retrait_consentement"]
    assert evenements.verifier_coherence(deps) == []
