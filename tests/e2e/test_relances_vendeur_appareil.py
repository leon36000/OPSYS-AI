"""PLAN T4.9 (M2.7, M2.13) — le vendeur lit et prépare SES relances, par la vraie porte d'appareil (E2E moteur).

DEFINITION-PRODUIT §9.4 : « M2 : ses leads, priorité, pipeline personnel, relances autorisées » ; §9.5 : l'admin voit le
pipeline. Avant T4.9, aucune relance n'était calculée : ni délai depuis l'envoi d'un devis, ni consentement de contact,
ni fréquence maximale.

Le scénario est celui d'une équipe de vente, par la même porte que l'app (`PorteAppareil`, la règle du core relue dans
le fork, appliquée au vrai moteur HTTP MCP sur une base temporaire) :

- deux vendeurs (`vendeur.a`, `vendeur.b`), l'admin (Nathan) et un employé (Étienne) ;
- des devis envoyés, publiés au vrai bus comme M3 le fait (`m3.devis_envoye`), livrés à M2 par le vrai répartiteur ;
- le vendeur A lit ses relances, en prépare une (texte fixe, rien d'envoyé), inscrit le consentement du client ;
- le STOP du client, publié au vrai bus comme M1 le fait (`m1.retrait_consentement`), ferme les messages.

Ce que ces tests prouvent : le vendeur A ne voit ni ne prépare les relances de B (ni dans la liste, ni dans `total`, ni
dans le corps brut) ; l'employé reçoit 403 ; la lecture n'écrit rien ; l'heure de RÉCEPTION du serveur fait foi pour la
fréquence (un appareil au temps déréglé n'y gagne rien) ; le rejeu d'une même clé ne prépare pas deux relances ; le
consentement d'un client est inscrit par une PERSONNE ; après un STOP, plus aucun SMS ni courriel, l'appel reste
permis ; la liste se pagine sous la borne de sortie du socle ; l'identité est confirmée en base à chaque appel.
Ce que ces tests ne prouvent PAS : l'écran (Jest, `mobile/`), le core, ni l'envoi réel (T2.1-c, N4, une personne).
Les délais et la fréquence sont ceux d'un manifeste JETABLE : les vrais sont à décider par Nathan. Données fictives.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import m2_revenue_crm.outils as m2_outils
import pytest
import yaml
from harnais_e2e import Moteur, PorteAppareil, iso
from m1_front_office import retrait as m1_retrait
from m2_revenue_crm import gabarits_relance

from opsys import evenements, identite, stockage
from opsys.outils import executer_atomique

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LISTER = "m2_lister_relances"
PREPARER = "m2_preparer_relance"
CONSENTIR = "m2_enregistrer_consentement_contact"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`
REGLE = "relance_devis_sans_reponse"
HORODATAGE = "2026-09-29T12:00:00-04:00"  # l'instant de référence d'une lecture : 16:00 UTC
ENVOI = "2026-09-10T13:00:00+00:00"  # l'envoi approuvé (publié par M3) ; l'échéance de 14 jours est le 24 septembre
HORLOGE_APPAREIL_DEREGLEE = "2000-01-01T00:00:00+00:00"
ACTION = {"description": "Appeler le client (fictif)", "echeance": "2026-09-05T09:00:00-04:00"}
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}
SEGMENTS = {"jours_inactivite_dormant": 90, "jours_soumission_perimee": 14}
RELANCES = {"jours_entre_relances": 7}
NUMEROS = ("418-555-0101", "418-555-0102", "418-555-0103", "@exemple-fictif.test")
LEADS_A = ["lead-a-1", "lead-a-2"]
LEAD_B = "lead-b-1"


def _m2(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m02-revenue-crm"].charger_outils()}


def _ingerer(moteur: Moteur, lead_id: str, telephone: str) -> None:
    contrat = {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id} (fictif)", "telephone": telephone,
                    "courriel": f"{lead_id}@exemple-fictif.test"},
        "type_travaux": "renovation_totale", "ville": "Repentigny", "urgence_declaree": False, "canal": "telephone",
    }
    reponse = executer_atomique(
        _m2(moteur)["m2_ingerer_lead"], {"contrat": contrat, "horodatage": "2026-09-01T09:00:00-04:00"})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _qualifier(moteur: Moteur, lead_id: str, owner: str) -> None:
    reponse = executer_atomique(_m2(moteur)["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-09-02T09:00:00-04:00", "owner": owner,
        "prochaine_action": ACTION})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _publier_devis_envoye(devis_id: str, lead_id: str, instant: str = ENVOI) -> None:
    """Le fait que M3 publie à l'approbation de l'envoi : mêmes champs, même identifiant déterministe."""
    with stockage.transaction():
        evenements.publier(
            "m3.devis_envoye", "m03-estimation",
            {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": instant},
            evenement_id=f"m3-devis-envoye-{devis_id}")


def _publier_stop(lead_ids: list[str], signal_id: str = "sms:SM-STOP-1",
                  instant: str = "2026-09-26T09:00:00-04:00") -> None:
    """Le fait que M1 publie au STOP d'un correspondant : le `lead_id`, jamais le numéro ; l'id est celui de M1."""
    with stockage.transaction():
        evenements.publier(
            "m1.retrait_consentement", "m01-front-office",
            {"lead_ids": lead_ids, "canal": "sms", "horodatage": instant, "signal_id": signal_id},
            evenement_id=m1_retrait.identifiant_evenement(signal_id, lead_ids))


def _hh(moteur: Moteur) -> str:
    return iso(moteur.horloge.maintenant)


@pytest.fixture
def vendeurs(moteur, equipe, monkeypatch):
    moteur.creer_personne("vendeur.a", "Vendeur A (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.b", "Vendeur B (fictif)", ["seller"], monkeypatch)
    return {"a": moteur.appairer("vendeur.a", "seller"), "b": moteur.appairer("vendeur.b", "seller")}


@pytest.fixture
def configuration(monkeypatch, tmp_path):
    """Le `department.yaml` de M2 dont seuls `segments` et `relances` changent : M2 le relit à chaque appel."""
    reel = yaml.safe_load(m2_outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste = {**reel, "configuration": {"segments": SEGMENTS, "relances": RELANCES}}
    chemin = tmp_path / "department-m2-relances-e2e.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(m2_outils, "_MANIFESTE", chemin)


@pytest.fixture
def equipe_de_vente(moteur, equipe, vendeurs, configuration):
    """Trois leads qualifiés (deux au vendeur A, un au vendeur B), chacun avec son devis envoyé, livré à M2 par le vrai
    répartiteur. La journée de l'app est le 29 septembre : le délai de 14 jours est écoulé pour les trois."""
    telephones = {"lead-a-1": "418-555-0101", "lead-a-2": "418-555-0102", LEAD_B: "418-555-0103"}
    for lead_id, owner in (("lead-a-1", "vendeur.a"), ("lead-a-2", "vendeur.a"), (LEAD_B, "vendeur.b")):
        _ingerer(moteur, lead_id, telephones[lead_id])
        _qualifier(moteur, lead_id, owner)
    for devis_id, lead_id in (("devis-a-1", "lead-a-1"), ("devis-a-2", "lead-a-2"), ("devis-b-1", LEAD_B)):
        _publier_devis_envoye(devis_id, lead_id)
    moteur.horloge.maintenant = dt.datetime(2026, 9, 29, 12, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0, resume
    return {**equipe, **vendeurs}


def _lire(porte: PorteAppareil, **args: Any):
    reponse = porte.appeler(LISTER, {"horodatage": HORODATAGE, **args})
    assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
    assert reponse.mesure.tronque is False and reponse.mesure.octets_texte < LIMITE_TRONCATURE, reponse.mesure
    return reponse


def _ids(page: dict[str, Any]) -> list[str]:
    return [r["lead_id"] for r in page["relances"]]


def _preparer(moteur: Moteur, porte: PorteAppareil, lead_id: str, canal: str, cle: str, **plus: Any):
    return porte.appeler(
        PREPARER, {"lead_id": lead_id, "regle": REGLE, "canal": canal, "horodatage": HORLOGE_APPAREIL_DEREGLEE, **plus},
        cle=cle, horodatage_appareil=_hh(moteur))


def _consentir(moteur: Moteur, porte: PorteAppareil, lead_id: str, cle: str, canal: str = "sms", **plus: Any):
    return porte.appeler(CONSENTIR, {
        "lead_id": lead_id, "canal": canal, "enonce_version": "consentement-sms-v1", "source": "formulaire",
        "preuve": dict(PREUVE), "recueilli_le": "2026-09-20T10:00:00-04:00", "horodatage": HORLOGE_APPAREIL_DEREGLEE,
        **plus}, cle=cle, horodatage_appareil=_hh(moteur))


def _registre(nom: str) -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m02-revenue-crm", nom))


def _registres(moteur: Moteur) -> dict[str, int]:
    """Les registres de relance : ce qu'un refus ou une lecture ne doit jamais changer."""
    return {k: v for k, v in moteur.empreinte_etat()["registres"].items() if k.startswith("m02-revenue-crm/")}


# ---------------------------------------------------------------------------------------------------------
# Qui voit quoi : le vendeur A ne voit pas les relances de B
# ---------------------------------------------------------------------------------------------------------
def test_le_vendeur_a_ne_voit_pas_les_relances_de_b_et_l_admin_voit_tout(moteur, equipe_de_vente):
    a, b, admin = equipe_de_vente["a"], equipe_de_vente["b"], equipe_de_vente["admin"]

    page_a = _lire(a).resultat
    assert sorted(_ids(page_a)) == LEADS_A and page_a["total"] == 2
    page_b = _lire(b).resultat
    assert _ids(page_b) == [LEAD_B] and page_b["total"] == 1
    tout = _lire(admin).resultat
    assert sorted(_ids(tout)) == sorted([*LEADS_A, LEAD_B]) and tout["total"] == 3

    for porte, autres, personne in ((a, [LEAD_B, "devis-b-1"], "vendeur.b"), (b, [*LEADS_A, "devis-a-1"], "vendeur.a")):
        brut = json.dumps(_lire(porte).corps, ensure_ascii=False)
        assert not any(autre in brut for autre in autres) and personne not in brut

    relance = _lire(a).resultat["relances"][0]
    assert relance["regle"] == REGLE and relance["depart"]["fait"] == "m3.devis_envoye"
    assert relance["depart"]["instant"] == ENVOI and relance["due_depuis"] == "2026-09-24T13:00:00+00:00"
    assert (relance["mode"], relance["canaux_permis"]) == ("appel_seulement", ["appel"])


def test_l_employe_n_a_la_portee_d_aucun_des_trois_outils(moteur, equipe_de_vente):
    employe = equipe_de_vente["employe"]
    for outil, args in (
        (LISTER, {"horodatage": HORODATAGE}),
        (PREPARER, {"lead_id": "lead-a-1", "regle": REGLE, "canal": "appel", "horodatage": HORODATAGE}),
        (CONSENTIR, {"lead_id": "lead-a-1", "canal": "sms", "enonce_version": "v1", "source": "formulaire",
                     "preuve": PREUVE, "recueilli_le": HORODATAGE, "horodatage": HORODATAGE}),
    ):
        refus = employe.appeler(outil, args)
        assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"], outil


def test_aucun_argument_ne_designe_une_autre_personne_ni_un_texte(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    for cle in ("owner", "proprietaire", "vendeur", "personne", "prepare_par", "texte"):
        reponse = a.appeler(PREPARER, {"lead_id": "lead-a-1", "regle": REGLE, "canal": "appel",
                                       "horodatage": HORODATAGE, cle: "vendeur.b"},
                            cle=f"e2e-arg-{cle}", horodatage_appareil=_hh(moteur))
        assert reponse.statut == 200 and reponse.enveloppe["ok"] is False
        assert reponse.enveloppe["erreur"] == "arguments_invalides", cle
    assert _registre("relances_preparees") == []


@SQLITE_SEULEMENT
def test_lire_n_ecrit_rien_et_la_meme_lecture_rend_la_meme_page(moteur, equipe_de_vente):
    a, admin = equipe_de_vente["a"], equipe_de_vente["admin"]
    empreinte = moteur.empreinte_etat()
    premiere = _lire(a, limite=1, decalage=1)
    seconde = _lire(a, limite=1, decalage=1)
    assert premiere.resultat == seconde.resultat
    _lire(a)
    _lire(admin, regle="relance_devis_sans_reponse")
    assert moteur.empreinte_etat() == empreinte  # ni registre, ni événement, ni approbation, ni journal, ni mutation


@SQLITE_SEULEMENT
def test_un_role_retire_depuis_l_appairage_est_refuse_par_l_identite_confirmee_en_base(moteur, equipe_de_vente):
    b = equipe_de_vente["b"]
    assert _lire(b).resultat["total"] == 1
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "vendeur.b", "seller")
        identite.ajouter_role(cnx, "vendeur.b", "employee")
    avant = _registres(moteur)
    lecture = b.appeler(LISTER, {"horodatage": HORODATAGE})
    assert lecture.statut == 200  # le jeton passe la porte : c'est M2 qui refuse, sur la personne, pas sur le jeton
    verdict = lecture.metier["verdict"]
    assert verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE" and LEAD_B not in json.dumps(lecture.corps)
    # Une écriture N3 dont la personne n'est plus confirmée n'est PAS exécutée : le socle la met dans la file du
    # propriétaire (validation au départ non satisfaite), rien n'est préparé ni inscrit avant sa décision.
    for reponse in (_preparer(moteur, b, LEAD_B, "appel", "e2e-role-retire-1"),
                    _consentir(moteur, b, LEAD_B, "e2e-role-retire-2")):
        assert reponse.statut == 200 and reponse.enveloppe["statut"] == "en_attente_approbation", reponse.corps
    assert _registres(moteur) == avant
    assert _registre("relances_preparees") == [] and _registre("consentements_contact") == []


# ---------------------------------------------------------------------------------------------------------
# Préparer : l'heure du serveur, le rejeu, la fréquence, rien d'envoyé
# ---------------------------------------------------------------------------------------------------------
def test_le_vendeur_prepare_sa_relance_le_rejeu_ne_double_rien_et_l_heure_du_serveur_fait_foi(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    recu_le = iso(moteur.horloge.maintenant)
    sortants = moteur.empreinte_etat()["evenements_sortants"]

    premiere = _preparer(moteur, a, "lead-a-1", "appel", "e2e-relance-a1")
    resultat = premiere.resultat
    assert premiere.statut == 200 and premiere.enveloppe["rejoue"] is False
    assert resultat["envoye"] is False and resultat["canal"] == "appel"
    assert resultat["texte"] == gabarits_relance.GABARITS[(REGLE, "appel")]["texte"]
    # L'appareil annonçait l'an 2000 : c'est l'heure de RÉCEPTION du serveur qui date la relance et la fréquence.
    assert dt.datetime.fromisoformat(resultat["prepare_le"]) == dt.datetime.fromisoformat(recu_le)
    (entree,) = _registre("relances_preparees")
    assert (entree["prepare_par"], entree["voie"], entree["lead_id"]) == ("vendeur.a", "appareil", "lead-a-1")
    assert dt.datetime.fromisoformat(entree["prepare_le"]) == dt.datetime.fromisoformat(recu_le)

    # Le même appel rejoué (mauvais réseau) : la même réponse, rien de plus écrit, rien publié, aucune seconde relance.
    avant = moteur.empreinte_etat()
    rejeu = _preparer(moteur, a, "lead-a-1", "appel", "e2e-relance-a1")
    assert rejeu.enveloppe["rejoue"] is True and rejeu.resultat == resultat
    assert moteur.empreinte_etat() == avant and len(_registre("relances_preparees")) == 1
    assert avant["evenements_sortants"] == sortants, "préparer une relance ne publie rien : rien n'est envoyé"


def test_la_frequence_est_celle_de_la_personne_et_suit_l_heure_du_serveur(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    assert _preparer(moteur, a, "lead-a-1", "appel", "e2e-freq-1").resultat["canal"] == "appel"

    moteur.horloge.avancer(hours=1)
    proche = _preparer(moteur, a, "lead-a-1", "appel", "e2e-freq-2")
    assert proche.metier["accepte"] is False and proche.metier["verdict"]["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert "tous les 7 jours" in proche.metier["verdict"]["detail"]
    assert len(_registre("relances_preparees")) == 1

    moteur.horloge.avancer(days=7)  # au-delà des 7 jours depuis la première relance
    assert _preparer(moteur, a, "lead-a-1", "appel", "e2e-freq-3").resultat["canal"] == "appel"
    assert len(_registre("relances_preparees")) == 2


def test_un_vendeur_ne_prepare_ni_ne_consent_pour_le_lead_d_un_autre(moteur, equipe_de_vente):
    a, admin = equipe_de_vente["a"], equipe_de_vente["admin"]
    avant = _registres(moteur)
    for reponse in (_preparer(moteur, a, LEAD_B, "appel", "e2e-autre-1"), _consentir(moteur, a, LEAD_B, "e2e-autre-2"),
                    _preparer(moteur, a, "lead-inexistant", "appel", "e2e-autre-3")):
        assert reponse.statut == 200 and reponse.metier["accepte"] is False
        assert reponse.metier["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"
    assert _registres(moteur) == avant
    # L'admin, lui, prépare pour n'importe quel lead, et la relance porte son nom.
    assert _preparer(moteur, admin, LEAD_B, "appel", "e2e-admin-1").resultat["lead_id"] == LEAD_B
    assert _registre("relances_preparees")[0]["prepare_par"] == "nathan"


# ---------------------------------------------------------------------------------------------------------
# Consentement et STOP
# ---------------------------------------------------------------------------------------------------------
def test_sans_consentement_aucun_message_puis_le_consentement_inscrit_par_le_vendeur_ouvre_le_sms(
        moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    refus = _preparer(moteur, a, "lead-a-1", "sms", "e2e-sms-1")
    assert refus.metier["accepte"] is False and refus.metier["verdict"]["code"] == "REJ-CONSENTEMENT-ABSENT"
    assert _registre("relances_preparees") == []

    inscrit = _consentir(moteur, a, "lead-a-1", "e2e-consent-1").resultat
    assert (inscrit["etat"], inscrit["enregistre_par"], inscrit["voie"]) == ("actif", "vendeur.a", "appareil")
    assert inscrit["preuve"] == PREUVE and inscrit["deja_enregistre"] is False
    assert dt.datetime.fromisoformat(inscrit["enregistre_le"]) == moteur.horloge.maintenant, "heure du serveur"

    relance = _lire(a).resultat["relances"]
    assert {r["lead_id"]: r["canaux_permis"] for r in relance} == {
        "lead-a-1": ["appel", "sms"], "lead-a-2": ["appel"]}
    sms = _preparer(moteur, a, "lead-a-1", "sms", "e2e-sms-2").resultat
    assert sms["envoye"] is False and sms["nature"] == "message" and "répondez STOP" in sms["texte"]
    rejeu = _consentir(moteur, a, "lead-a-1", "e2e-consent-2").resultat
    assert rejeu["deja_enregistre"] is True and rejeu["consentement_id"] == inscrit["consentement_id"]
    assert len([m for m in _registre("consentements_contact") if m["type_entree"] == "consentement_contact"]) == 1


def test_le_stop_publie_comme_m1_ferme_les_messages_et_l_appel_reste_permis(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    assert _consentir(moteur, a, "lead-a-1", "e2e-stop-consent").resultat["etat"] == "actif"
    _publier_stop(["lead-a-1"])
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    (retrait,) = [m for m in _registre("consentements_contact") if m["type_entree"] == "retrait_contact"]
    assert (retrait["lead_id"], retrait["canal"], retrait["source"]) == (
        "lead-a-1", "sms", "bus:m1.retrait_consentement")
    relance = [r for r in _lire(a).resultat["relances"] if r["lead_id"] == "lead-a-1"][0]
    assert (relance["mode"], relance["canaux_permis"]) == ("appel_seulement", ["appel"])
    assert relance["consentements"]["sms"]["etat"] == "retire"
    for canal, cle in (("sms", "e2e-stop-sms"), ("courriel", "e2e-stop-courriel")):
        refus = _preparer(moteur, a, "lead-a-1", canal, cle)
        assert refus.metier["accepte"] is False and refus.metier["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    assert _registre("relances_preparees") == []
    assert _preparer(moteur, a, "lead-a-1", "appel", "e2e-stop-appel").resultat["canal"] == "appel"
    # Un retrait ne se lève pas : ni le vendeur ni l'admin ne peuvent inscrire un nouveau consentement.
    for porte, cle in ((a, "e2e-stop-reconsent-a"), (equipe_de_vente["admin"], "e2e-stop-reconsent-admin")):
        refus = _consentir(moteur, porte, "lead-a-1", cle, enonce_version="consentement-sms-v2")
        assert refus.metier["accepte"] is False and refus.metier["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    # Les autres clients ne sont pas touchés : le vendeur B garde l'inscription possible.
    assert _consentir(moteur, equipe_de_vente["b"], LEAD_B, "e2e-stop-autre").resultat["etat"] == "actif"


def test_le_rejeu_du_stop_et_du_devis_n_ecrit_rien_de_plus_chez_m2(moteur, equipe_de_vente):
    _publier_stop(["lead-a-1"])
    moteur.drainer_bus(moteur.horloge.maintenant)
    avant = _registres(moteur)
    donnees = (_registre("consentements_contact"), _registre("devis_envoyes_recus"))

    _publier_stop(["lead-a-1"])  # même identifiant : un no-op au bus
    _publier_devis_envoye("devis-a-1", "lead-a-1")
    assert moteur.drainer_bus(moteur.horloge.maintenant)["livres"] == 0
    with stockage.transaction():
        evenements.publier("m3.devis_envoye", "m03-estimation", {
            "devis_id": "devis-a-1", "lead_id": "lead-a-1", "chantier_id": None, "horodatage_envoi": ENVOI},
            evenement_id="rejeu-autre-producteur")
        evenements.publier("m1.retrait_consentement", "m01-front-office", {
            "lead_ids": ["lead-a-1"], "canal": "sms", "horodatage": "2026-09-26T09:00:00-04:00",
            "signal_id": "sms:SM-STOP-1"}, evenement_id="rejeu-retrait-autre-id")
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _registres(moteur) == avant
    assert (_registre("consentements_contact"), _registre("devis_envoyes_recus")) == donnees


@SQLITE_SEULEMENT
def test_aucun_numero_ni_courriel_dans_les_registres_de_relance_ni_dans_les_reponses(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    _consentir(moteur, a, "lead-a-1", "e2e-pii-consent")
    _preparer(moteur, a, "lead-a-1", "sms", "e2e-pii-sms")
    _publier_stop(["lead-a-1"])
    moteur.drainer_bus(moteur.horloge.maintenant)
    ecrit = json.dumps({nom: _registre(nom) for nom in (
        "devis_envoyes_recus", "consentements_contact", "relances_preparees")}, ensure_ascii=False)
    portes = [porte for cle, porte in equipe_de_vente.items() if cle != "employe"]
    lu = json.dumps([_lire(porte).corps for porte in portes], ensure_ascii=False)
    for secret in NUMEROS:
        assert secret not in ecrit and secret not in lu, secret
    for interdit in ("prix", "cout", "marge", "montant"):
        assert interdit not in ecrit and interdit not in lu, interdit


# ---------------------------------------------------------------------------------------------------------
# Pagination : la liste se recolle sous la borne de sortie du socle
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_beaucoup_de_relances_se_recollent_sans_doublon_ni_trou_et_jamais_tronquees(moteur, equipe_de_vente):
    a = equipe_de_vente["a"]
    nouveaux = [f"lead-a-masse-{i:02d}" for i in range(28)]
    for i, lead_id in enumerate(nouveaux):
        _ingerer(moteur, lead_id, f"418-555-{2000 + i}")
        _qualifier(moteur, lead_id, "vendeur.a")
        _publier_devis_envoye(f"devis-masse-{i:02d}", lead_id, f"2026-09-{1 + i % 9:02d}T13:00:00+00:00")
    assert moteur.drainer_bus(moteur.horloge.maintenant)["quarantaines"] == 0

    pages = [_lire(a, limite=30)]
    while pages[-1].resultat["suivant"] is not None:
        pages.append(_lire(a, limite=30, decalage=pages[-1].resultat["suivant"]))
        assert len(pages) <= 30, "la lecture ne progresse pas"
    ids = [lead for page in pages for lead in _ids(page.resultat)]
    assert len(pages) > 1, "la borne de sortie du socle n'est pas exercée"
    assert len(ids) == len(set(ids)) == len(nouveaux) + len(LEADS_A)
    assert set(ids) == {*nouveaux, *LEADS_A}
    assert {p.resultat["total"] for p in pages} == {len(ids)}
    assert all(p.mesure.tronque is False and p.mesure.octets_texte < LIMITE_TRONCATURE for p in pages)
    print("MESURE-RELANCES " + json.dumps({
        "relances": len(ids), "pages": len(pages), "par_page": [p.resultat["affichees"] for p in pages],
        "octets": [p.mesure.octets_texte for p in pages], "duree_s": [round(p.mesure.duree_s, 3) for p in pages]}))
