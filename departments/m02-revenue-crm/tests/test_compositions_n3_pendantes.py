"""Compositions de `m2_preparer_relance` proposée par un agent (N3, mode `ombre`), restée EN ATTENTE pendant qu'un autre
fait est commité, puis exécutée par la vraie décision humaine (`approbations.decider`).

Les invariants simples sont prouvés ailleurs (`test_relances_outils.py`, `test_consommer_retrait_consentement.py`,
`test_reassignation.py`) ; ici seulement ce qu'ils ne composent pas :
- R1 : un STOP publié par M1 sur le VRAI bus pour l'AUTRE lead du même client, réparti et commité pendant l'attente,
  ferme le message proposé avant lui ; témoin frais sans STOP du même client ; l'appel reste permis ;
- R2 : l'identité réellement portée à l'effet après une réassignation commitée pendant l'attente : la demande ne porte
  aucune origine vendeur, l'effet est celui de l'agent approuvé par Nathan (portée globale documentée), le vendeur
  déchu reste actif et ne passe plus ; un appareil vendeur valide sans ticket n'est pas mis en file, et le CONSTAT
  qu'avec un ticket de session la demande N3 attend sans origine vendeur (arbitrage Root, aucun refus inventé) ;
- R3 : deux demandes en attente pour deux leads d'une même personne ; la première préparation commitée, la seconde
  décision relit la fréquence de la PERSONNE sans rien dire de l'autre dossier ; limite exacte et configuration absente.
Seuils, dates et fréquence sont des valeurs de fixture (`department.yaml` copié), pas une politique livrée. Rien n'est
envoyé. Données fictives (`fictif: true`).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from m2_revenue_crm import clients, consentements, outils
from sqlalchemy import select

from opsys import approbations, contexte, evenements, idempotence, identite, liaison_cibles, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements, lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, JOURNAL, META

FICTIF = True

M2 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m02-revenue-crm"
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")

H_INGERE = "2026-09-01T09:00:00-04:00"
H_QUALIFIE = "2026-09-01T10:00:00-04:00"
ENVOI = "2026-09-10T09:00:00-04:00"
MAINTENANT = "2026-09-29T12:00:00-04:00"  # 16:00 UTC ; à 7 jours : 2026-10-06T16:00:00+00:00
LIMITE = "2026-10-06T16:00:00+00:00"
UNE_SECONDE_AVANT = "2026-10-06T15:59:59+00:00"
STOP_PENDANT_L_ATTENTE = "2026-09-30T09:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
CONTACT_PARTAGE = {"nom": "Cliente Partagée", "telephone": "418-555-0104", "courriel": "partagee@example.test"}
CONTACT_AUTRE = {"nom": "Client Autre", "telephone": "418-555-0105", "courriel": "autre@example.test"}
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}
SECRETS_CONTACT = ("418-555-0104", "4185550104", "partagee@example.test", "Cliente Partagée")
TABLES_METIER = ("registres_maillons", "evenements_sortants", "evenements_recus")
TABLES_DECISION = frozenset({"approbations", "liaisons_tickets", "journal"})


# -- installation ------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m2-compositions.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


def _installer_configuration(monkeypatch, tmp_path, *, relances_):
    """Copie du `department.yaml` réel dont seuls `segments` et `relances` portent des valeurs de fixture."""
    reel = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste = {**reel, "configuration": {
        "segments": {"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14}, "relances": relances_}}
    chemin = tmp_path / f"department-m2-compositions-{len(relances_)}.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])


@pytest.fixture
def configure(personnes, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path, relances_={"jours_entre_relances": 7})


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils.outils()}


@pytest.fixture
def capacites(personnes):
    dep = lire_manifeste(M2)
    return Capacites({dep.id: dep}, stockage.transaction, appelant=dep.id, memoire=False)


@pytest.fixture
def meme_client(configure):
    """Deux opportunités d'une même personne, chacune chez son vendeur, chacune avec un devis envoyé par M3."""
    _lead("partage-a", "vendeur.un", CONTACT_PARTAGE)
    _lead("partage-b", "vendeur.deux", CONTACT_PARTAGE)
    _envoyer_devis("devis-partage-a", "partage-a")
    _envoyer_devis("devis-partage-b", "partage-b")


# -- aides --------------------------------------------------------------------------------------------------
def _lead(lead_id, owner, contact):
    contrat = {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "contact": contact,
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }
    assert outils.ingerer_lead(contrat, H_INGERE)["accepte"] is True
    reponse = outils.transitionner_statut(lead_id, "qualifie", H_QUALIFIE, owner=owner, prochaine_action=ACTION)
    assert reponse["accepte"] is True, reponse


def _envoyer_devis(devis_id, lead_id):
    with stockage.transaction():
        resultat = outils._recevoir_devis_envoye(
            {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": ENVOI})
    assert resultat["traite"] is True, resultat


def _appeler(par_nom, nom, arguments, identite_appelante, *, recu_le=None):
    reception = None
    if recu_le is not None:
        reception = contexte.HorodatageAppareil(
            appareil="tel-fictif", horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
            recu_le=dt.datetime.fromisoformat(recu_le))
    with contexte.receptionne_de(reception), contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _arguments(lead_id, canal="appel", horodatage=MAINTENANT):
    return {"lead_id": lead_id, "regle": "relance_devis_sans_reponse", "canal": canal, "horodatage": horodatage}


def _proposer(capacites, arguments, appelante=None, meta=None):
    """Proposition d'agent avec le ticket M10 réel du lead ; doit rester EN ATTENTE d'une personne. `appelante` et
    `meta` : la même proposition portée en plus par la session d'un appareil (identité du jeton, enveloppe)."""
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    lead_id = arguments["lead_id"]
    cle_session = f"agent:{DEPARTEMENT}:tests:{lead_id}"
    with stockage.transaction() as cnx:
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        active = liaison_m10.liaison_courante(cle_session, reg_m10)
        if active is None:
            _, refus = liaison_m10.lier_session_affaire(
                cle_session, lead_id, "nathan", "admin", "appareil", "liaison M2 de fixture fictive",
                MAINTENANT, reg_m10,
            )
            assert refus is None
        else:
            assert active["affaire_id"] == lead_id
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement=DEPARTEMENT, agent_id=DEPARTEMENT, cle_session=cle_session,
            affaire_id=lead_id, origine_affaire="session", outil="m2_preparer_relance", arguments=arguments,
        )
    with contexte.appele_par_appareil(appelante):
        proposition = capacites.appeler(
            "m2_preparer_relance", arguments, meta, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))
    assert proposition["ok"] is True and proposition["statut"] == "en_attente_approbation", proposition
    return proposition["demande_id"]


def _decider(capacites, demande_id, par="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, True, par,
            outils_executables(capacites.departements, stockage.transaction), capacites.departements)


def _demande(demande_id):
    with stockage.transaction() as cnx:
        return approbations.lire(cnx, demande_id)


def _en_attente():
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, "en_attente")


def _preparees():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "relances_preparees"))


def _instantane():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _tables_changees(avant, apres):
    return {nom for nom in avant if avant[nom] != apres[nom]}


def _verdict_execute(decision):
    reponse = decision["reponse"]
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, decision
    return reponse["resultat"]["verdict"]


def _canaux_de_la_personne(lead_id):
    with stockage.transaction():
        reg = outils._obtenir_registre()
        contenus, retraits, _ = outils._registres_de_relance()
        return consentements.canaux_permis(outils._perimetre_du_lead(reg, lead_id), contenus, retraits)


def _client(lead_id):
    with stockage.transaction():
        return clients.client_de_lead(outils._obtenir_registre(), lead_id)


def _consentir_sms_par_le_vendeur(par_nom, lead_id, vendeur):
    arguments = {
        "lead_id": lead_id, "canal": "sms", "enonce_version": "consentement-sms-v1", "source": "formulaire",
        "preuve": dict(PREUVE), "recueilli_le": "2026-09-20T10:00:00-04:00", "horodatage": "2026-09-20T10:05:00-04:00"}
    reponse = _appeler(par_nom, "m2_enregistrer_consentement_contact", arguments, vendeur)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _publier_stop_m1(lead_ids, evenement_id, horodatage=STOP_PENDANT_L_ATTENTE):
    """Charge conforme au catalogue, publiée sous l'identité du producteur M1 déclaré, sur le bus réel."""
    evenements.publier("m1.retrait_consentement", "m01-front-office", {
        "lead_ids": list(lead_ids), "canal": "sms", "horodatage": horodatage, "signal_id": "sms:SM-STOP-PENDANT-1",
    }, evenement_id=evenement_id)


def _repartir_m2(instant="2026-09-30T10:00:00-04:00"):
    return evenements.repartir({DEPARTEMENT: charger_departements()[DEPARTEMENT]}, maintenant=instant)


def _recu(evenement_id):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == DEPARTEMENT)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu M2 pour {evenement_id}"
    return codec.decoder(ligne["resultat"])


# =========================================================================================
# R1. STOP de l'autre lead du même client, commité par le bus pendant l'attente N3
# =========================================================================================
def test_r1_un_stop_m1_sur_l_autre_lead_du_client_commite_pendant_l_attente_ferme_le_sms_approuve(
        par_nom, capacites, meme_client):
    _consentir_sms_par_le_vendeur(par_nom, "partage-a", VENDEUR_UN)
    assert _canaux_de_la_personne("partage-a")[0] == ["appel", "sms"]
    demande_sms = _proposer(capacites, _arguments("partage-a", "sms"))
    assert _preparees() == [], "rien n'est préparé avant la décision"

    _publier_stop_m1(["partage-b"], "m1-retrait-pendant-attente-1")
    resume = _repartir_m2()

    assert (resume["traites"], resume["echecs"], resume["quarantaines"]) == (1, 0, 0)
    assert evenements.etat()["quarantaine"] == []
    assert _recu("m1-retrait-pendant-attente-1") == {"traite": True, "retraits_ecrits": 1, "deja_enregistres": 0}
    assert _client("partage-a") is not None and _client("partage-a") == _client("partage-b"), "même Client 360"
    permis, etats = _canaux_de_la_personne("partage-a")
    assert permis == ["appel"] and etats["sms"]["etat"] == "retire"
    assert etats["sms"]["retire_le"] == STOP_PENDANT_L_ATTENTE
    assert etats["sms"]["source"] == consentements.SOURCE_BUS_RETRAIT
    assert _demande(demande_sms)["statut"] == "en_attente", "le STOP est commité PENDANT l'attente"
    with stockage.transaction() as cnx:
        nathan = identite.personne_active(cnx, "nathan")
    assert nathan is not None and {"nathan_owner", "admin"} <= set(nathan.roles)
    avant = _instantane()

    decision = _decider(capacites, demande_sms)

    verdict = _verdict_execute(decision)
    assert decision["statut"] == "echec" and verdict["code"] == "REJ-CONSENTEMENT-RETIRE", decision
    assert STOP_PENDANT_L_ATTENTE in verdict["detail"] and "appel seulement" in verdict["detail"]
    apres = _instantane()
    assert _tables_changees(avant, apres) <= TABLES_DECISION, "la décision ne laisse que sa trace d'approbation"
    assert all(avant[t] == apres[t] for t in TABLES_METIER), "aucune relance, aucun fait publié, aucun envoi"
    assert _preparees() == []
    trace = _demande(demande_sms)
    assert (trace["statut"], trace["decide_par"]) == ("echec", "nathan")
    assert trace["resultat"]["resultat"]["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"

    # Rejeu exact : même événement (no-op du bus) et même demande (déjà traitée) : aucun effet métier de plus.
    _publier_stop_m1(["partage-b"], "m1-retrait-pendant-attente-1")
    assert _repartir_m2("2026-09-30T11:00:00-04:00")["livres"] == 0
    with pytest.raises(ValueError, match="déjà traitée"):
        _decider(capacites, demande_sms)
    rejoue = _instantane()
    assert all(apres[t] == rejoue[t] for t in (*TABLES_METIER, "approbations"))

    # Même autorité, même configuration : l'appel reste permis et se prépare ; le STOP demeure.
    demande_appel = _proposer(capacites, _arguments("partage-a", "appel"))
    decision_appel = _decider(capacites, demande_appel)
    assert decision_appel["statut"] == "executee", decision_appel
    (entree,) = _preparees()
    assert (entree["lead_id"], entree["canal"], entree["prepare_par"], entree["voie"]) == (
        "partage-a", "appel", "agent", "agent")
    assert _canaux_de_la_personne("partage-a")[0] == ["appel"]
    assert _canaux_de_la_personne("partage-b")[0] == ["appel"]
    tout = json.dumps(_preparees(), ensure_ascii=False)
    for secret in SECRETS_CONTACT:
        assert secret not in tout, secret


def test_r1_temoin_frais_sans_stop_du_meme_client_le_meme_sms_approuve_est_prepare(par_nom, capacites, meme_client):
    """Témoin causal : même composition, le bus livre un STOP d'un AUTRE client pendant l'attente ; le SMS passe."""
    _lead("lead-autre", "vendeur.deux", CONTACT_AUTRE)
    _consentir_sms_par_le_vendeur(par_nom, "partage-a", VENDEUR_UN)
    demande_sms = _proposer(capacites, _arguments("partage-a", "sms"))

    _publier_stop_m1(["lead-autre"], "m1-retrait-autre-client-1")
    resume = _repartir_m2()
    assert (resume["traites"], resume["echecs"], resume["quarantaines"]) == (1, 0, 0)
    assert _client("lead-autre") != _client("partage-a")
    assert _demande(demande_sms)["statut"] == "en_attente"

    decision = _decider(capacites, demande_sms)

    assert decision["statut"] == "executee", decision
    resultat = decision["reponse"]["resultat"]["resultat"]
    assert resultat["canal"] == "sms" and resultat["envoye"] is False
    (entree,) = _preparees()
    assert (entree["lead_id"], entree["canal"], entree["prepare_par"]) == ("partage-a", "sms", "agent")


# =========================================================================================
# R2. Identité réellement portée à l'effet après une réassignation commitée pendant l'attente
# =========================================================================================
def test_r2_apres_une_reassignation_pendant_l_attente_l_effet_est_celui_de_l_agent_approuve_sans_origine_vendeur(
        par_nom, capacites, configure):
    _lead("lead-un", "vendeur.un", CONTACT_PARTAGE)
    _envoyer_devis("devis-un", "lead-un")
    demande = _proposer(capacites, _arguments("lead-un"))
    assert set(_demande(demande)["arguments"]) == {"lead_id", "regle", "canal", "horodatage"}, (
        "la demande ne porte aucune identité d'origine : seule l'autorité de la décision s'y ajoutera")

    with contexte.appele_par_appareil(ADMIN):
        accuse = executer_atomique(par_nom["m2_reassigner_lead"], {
            "lead_id": "lead-un", "nouveau_proprietaire": "vendeur.deux",
            "motif": "Le vendeur un part en congé, le dossier passe à un collègue.", "horodatage": MAINTENANT})
    assert accuse["ok"] is True and accuse["resultat"]["accepte"] is True, accuse
    with stockage.transaction() as cnx:
        ancien = identite.personne_active(cnx, "vendeur.un")
    assert ancien is not None and "seller" in ancien.roles, "aucune révocation : A reste vendeur actif"
    assert _demande(demande)["statut"] == "en_attente"

    decision = _decider(capacites, demande)

    assert decision["statut"] == "executee", decision
    (entree,) = _preparees()
    assert (entree["lead_id"], entree["prepare_par"], entree["voie"]) == ("lead-un", "agent", "agent")
    trace = _demande(demande)
    assert trace["decide_par"] == "nathan" and trace["decide_role"] in {"nathan_owner", "admin"}

    # L'ancien vendeur, toujours actif, ne voit ni ne prépare plus ce lead : refus du propriétaire courant, à l'effet.
    page = _appeler(par_nom, "m2_lister_relances", {"horodatage": MAINTENANT}, VENDEUR_UN)
    assert page["resultat"]["accepte"] is True and "lead-un" not in json.dumps(page, ensure_ascii=False)
    avant = _instantane()
    meta = idempotence.Meta(cle="mut-r2-ancien-1", appareil="tel-vendeur-un-fictif", horodatage_appareil=MAINTENANT)
    with contexte.appele_par_appareil(VENDEUR_UN):
        reponse = capacites.appeler("m2_preparer_relance", _arguments("lead-un"), meta)
    assert reponse.get("statut") != "en_attente_approbation", (
        "un appareil vendeur valide, avec enveloppe et sans ticket, n'est pas mis en file : refusé à l'effet")
    assert reponse["resultat"]["accepte"] is False and reponse["resultat"]["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"
    assert _en_attente() == [] and len(_preparees()) == 1
    apres = _instantane()
    assert all(avant[t] == apres[t] for t in TABLES_METIER), "aucun effet métier"
    # Seule la trace d'audit du socle (`tracer_validation_au_depart` : `echec` quand le verdict refuse) s'ajoute.
    with stockage.transaction() as cnx:
        (audit,) = [d for d in approbations.lister(cnx) if d["id"] not in {ligne[0] for ligne in avant["approbations"]}]
    assert (audit["outil"], audit["statut"], audit["decide_par"], audit["decide_role"]) == (
        "m2_preparer_relance", "echec", "vendeur.un", "seller")
    assert audit["motif_decision"] == approbations.MOTIF_VALIDATION_AU_DEPART
    assert audit["resultat"] == {"ok": True, "accepte": False}

    # Le vendeur courant, frais, prépare à la limite exacte de la fréquence (heure de réception du serveur).
    resultat = _appeler(par_nom, "m2_preparer_relance", _arguments("lead-un", horodatage="2031-01-01T00:00:00+00:00"),
                        VENDEUR_DEUX, recu_le=LIMITE)
    assert resultat["resultat"]["accepte"] is True, resultat
    assert [(p["prepare_par"], p["prepare_le"]) for p in _preparees()] == [
        ("agent", MAINTENANT), ("vendeur.deux", LIMITE)]


def test_r2_constat_une_proposition_avec_ticket_portee_par_l_appareil_du_vendeur_attend_sans_origine_vendeur(
        par_nom, capacites, configure):
    """CONSTAT du contrat actuel, pas une politique : avec un ticket de session, l'appel porté par l'appareil du
    vendeur suit la route du ticket (`Capacites._appeler_avec_ticket` -> `_distribuer` sans `appel_appareil`) et entre
    en file N3 SANS provenance (le socle n'en enregistre qu'en N4). Après une réassignation commitée pendant l'attente,
    la décision de Nathan s'exécute sans identité d'appareil : effet de l'agent, portée globale documentée. Garder
    l'origine vendeur jusqu'à l'effet exigerait le socle (`approbations.creer_demande`, `decider`) : arbitrage Root."""
    _lead("lead-un", "vendeur.un", CONTACT_PARTAGE)
    _envoyer_devis("devis-un", "lead-un")
    meta = idempotence.Meta(cle="mut-r2-ticket-1", appareil="tel-vendeur-un-fictif", horodatage_appareil=MAINTENANT)

    demande = _proposer(capacites, _arguments("lead-un"), VENDEUR_UN, meta)

    assert _preparees() == []
    ligne = _demande(demande)
    assert (ligne["statut"], ligne["niveau"], ligne["decide_par"]) == ("en_attente", "N3", None)
    assert set(ligne["arguments"]) == {"lead_id", "regle", "canal", "horodatage"}
    with stockage.transaction() as cnx:
        traces = cnx.execute(select(JOURNAL.c.par, JOURNAL.c.action).where(JOURNAL.c.cible == demande)).all()
    assert traces == [], "aucune provenance humaine journalisée pour une demande N3"

    with contexte.appele_par_appareil(ADMIN):
        accuse = executer_atomique(par_nom["m2_reassigner_lead"], {
            "lead_id": "lead-un", "nouveau_proprietaire": "vendeur.deux",
            "motif": "Le vendeur un part en congé, le dossier passe à un collègue.", "horodatage": MAINTENANT})
    assert accuse["ok"] is True and accuse["resultat"]["accepte"] is True, accuse
    with stockage.transaction() as cnx:
        ancien = identite.personne_active(cnx, "vendeur.un")
    assert ancien is not None and "seller" in ancien.roles

    decision = _decider(capacites, demande)

    assert decision["statut"] == "executee", decision
    (entree,) = _preparees()
    assert (entree["lead_id"], entree["prepare_par"], entree["voie"]) == ("lead-un", "agent", "agent")
    assert _demande(demande)["decide_par"] == "nathan"


# =========================================================================================
# R3. Deux demandes en attente pour la même personne : la seconde décision relit la fréquence commitée
# =========================================================================================
def test_r3_deux_demandes_en_attente_la_seconde_decision_relit_la_frequence_de_la_personne_sans_rien_reveler(
        capacites, meme_client):
    demande_a = _proposer(capacites, _arguments("partage-a"))
    demande_b = _proposer(capacites, _arguments("partage-b"))
    assert {d["id"] for d in _en_attente()} == {demande_a, demande_b} and _preparees() == []

    premiere = _decider(capacites, demande_a)

    assert premiere["statut"] == "executee", premiere
    (entree,) = _preparees()
    assert (entree["lead_id"], entree["prepare_le"], entree["client_id"]) == (
        "partage-a", MAINTENANT, _client("partage-b"))
    assert _demande(demande_b)["statut"] == "en_attente"
    avant = _instantane()

    seconde = _decider(capacites, demande_b)

    verdict = _verdict_execute(seconde)
    assert seconde["statut"] == "echec" and verdict["code"] == "REJ-RELANCE-TROP-PROCHE", seconde
    assert MAINTENANT in verdict["detail"] and LIMITE in verdict["detail"]
    apres = _instantane()
    assert _tables_changees(avant, apres) <= TABLES_DECISION
    assert all(avant[t] == apres[t] for t in TABLES_METIER) and len(_preparees()) == 1
    visible = json.dumps([verdict, _demande(demande_b)["resultat"]], ensure_ascii=False)
    for prive in ("partage-a", "vendeur.un", "devis-partage-a", *SECRETS_CONTACT):
        assert prive not in visible, prive

    # Limite exacte, par de nouvelles demandes fraîches : une seconde avant, refus ; pile à la limite, préparée.
    tot = _decider(capacites, _proposer(capacites, _arguments("partage-b", horodatage=UNE_SECONDE_AVANT)))
    assert tot["statut"] == "echec" and _verdict_execute(tot)["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert len(_preparees()) == 1
    pile = _decider(capacites, _proposer(capacites, _arguments("partage-b", horodatage=LIMITE)))
    assert pile["statut"] == "executee", pile
    assert [(p["lead_id"], p["prepare_le"]) for p in _preparees()] == [("partage-a", MAINTENANT), ("partage-b", LIMITE)]


def test_r3_une_demande_en_attente_executee_sans_frequence_configuree_reste_a_configurer(
        capacites, meme_client, monkeypatch, tmp_path):
    demande = _proposer(capacites, _arguments("partage-a"))
    _installer_configuration(monkeypatch, tmp_path, relances_={})
    avant = _instantane()

    decision = _decider(capacites, demande)

    assert decision["statut"] == "echec" and _verdict_execute(decision)["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert all(avant[t] == _instantane()[t] for t in TABLES_METIER) and _preparees() == []
