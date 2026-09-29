"""PLAN T4.9 (M2.7, M2.13) : `m2_lister_relances`, `m2_preparer_relance` et `m2_enregistrer_consentement_contact`, par
les VRAIS outils, comme en production.

Le vrai `outils()` de M2, le registre durable adossé à une base SQLite migrée, `executer_atomique` (la transaction et la
validation des arguments d'un appel réel), `Capacites` (le mode `ombre` réel du manifeste, la file d'approbation réelle,
l'idempotence d'appareil réelle), de vraies personnes (`opsys.identite`). L'identité d'un appel d'appareil est celle que
`Capacites.appeler` et `serveur_mcp.appeler_outil` posent (`contexte.appele_par_appareil`) ; la porte d'appareil
complète (jeton, `_meta`, moteur HTTP) est prouvée par `tests/e2e/test_relances_vendeur_appareil.py`.

Ce qui est prouvé ici :
- la fréquence maximale vient de `department.yaml`, jamais d'un défaut : absente ou invalide, « à configurer » ;
- un vendeur ne voit et ne prépare que les relances de SES leads (propriétaire courant compris), l'admin toutes ;
- une relance préparée date la fréquence de la PERSONNE : refus avant la prochaine date, permis pile à la limite ;
- sans consentement actif, un message est refusé et l'appel reste permis ; après un STOP, plus aucun message ;
- rien n'est envoyé (`envoye: False`), le texte est le gabarit fixe, l'heure du serveur fait foi pour un appareil ;
- le consentement est une décision de PERSONNE, jamais celle d'un agent seul, et un retrait ne se lève pas ;
- chaque refus est prouvé sans aucune écriture (toutes les tables de la base comparées avant et après).
Données fictives (`fictif: true`).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from m2_revenue_crm import acces, consentements, gabarits_relance, liste_leads, outils, relances
from sqlalchemy import select, update

from opsys import approbations, contexte, idempotence, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS, META

FICTIF = True

M2 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m02-revenue-crm"
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
ANCIEN = contexte.IdentiteAppelante(personne="ancien.vendeur", role="seller")
INCONNUE = contexte.IdentiteAppelante(personne="personne.inconnue", role="seller")

CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
CODE_NON_ASSIGNE = "REJ-LEAD-NON-ASSIGNE"
CODE_HUMAIN = "REJ-HUMAIN-REQUIS"

H_INGERE = "2026-09-01T09:00:00-04:00"
H_QUALIFIE = "2026-09-01T10:00:00-04:00"
ENVOI_UN = "2026-09-10T09:00:00-04:00"  # 13:00 UTC ; le seuil de 14 jours arrive le 24 septembre à 13:00 UTC
ENVOI_DEUX = "2026-09-12T09:00:00-04:00"
MAINTENANT = "2026-09-29T12:00:00-04:00"  # 16:00 UTC
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
CONTACT_A = {"nom": "Cliente A", "telephone": "418-555-0101", "courriel": "a@example.test"}
CONTACT_B = {"nom": "Client B", "telephone": "418-555-0102", "courriel": "b@example.test"}
CONTACT_C = {"nom": "Client C", "telephone": "418-555-0103", "courriel": "c@example.test"}
CONTACT_PARTAGE = {"nom": "Cliente Partagée", "telephone": "418-555-0104", "courriel": "partagee@example.test"}
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}
RECUEILLI = "2026-09-20T10:00:00-04:00"
SEGMENTS_CONFIGURES = {"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14}
RELANCES_CONFIGUREES = {"jours_entre_relances": 7}
NUMEROS = ("418-555-0101", "418-555-0102", "418-555-0103", "418-555-0104", "4185550101", "@example.test")


# -- installation ------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m2-relances.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        outils.reinitialiser_registre()
        stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(
            cnx, "ancien.vendeur", "Ancien Vendeur", "mot-de-passe-ancien-123", ["seller"], actif=False)


def _installer_configuration(monkeypatch, tmp_path, *, segments=SEGMENTS_CONFIGURES, relances_=RELANCES_CONFIGUREES):
    """Le `department.yaml` de M2 dont seuls les blocs `segments` et `relances` changent : M2 le relit à chaque
    appel."""
    reel = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste = {**reel, "configuration": {"segments": segments, "relances": relances_}}
    chemin = tmp_path / "department-m2-relances.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)


@pytest.fixture
def configure(personnes, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path)


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils.outils()}


@pytest.fixture
def dep(personnes):
    return lire_manifeste(M2)


@pytest.fixture
def capacites(dep):
    return Capacites({dep.id: dep}, stockage.transaction, memoire=False)


def _contrat(lead_id, contact, ingere=H_INGERE):
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "contact": contact,
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }


def _lead(lead_id, owner, contact, *, ingere=H_INGERE, qualifie=H_QUALIFIE):
    assert outils.ingerer_lead(_contrat(lead_id, contact), ingere)["accepte"] is True
    if owner is not None:
        reponse = outils.transitionner_statut(
            lead_id, "qualifie", qualifie, owner=owner, prochaine_action=ACTION)
        assert reponse["accepte"] is True, reponse


def _envoyer_devis(devis_id, lead_id, instant):
    """Le fait que M3 publie à l'approbation de l'envoi, livré à M2 par son consommateur réel."""
    with stockage.transaction():
        resultat = outils._recevoir_devis_envoye(
            {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": instant})
    assert resultat["traite"] is True, resultat


def _stop(lead_ids, canal="sms", signal="sms:SM-STOP-1", instant="2026-09-25T09:00:00-04:00"):
    with stockage.transaction():
        return outils._recevoir_retrait_consentement(
            {"lead_ids": list(lead_ids), "canal": canal, "horodatage": instant, "signal_id": signal})


@pytest.fixture
def monde(configure):
    """Quatre relances dues : un devis envoyé à chaque vendeur, un lead dormant du vendeur un, un lead nouveau dormant
    (sans propriétaire : l'admin seul le voit)."""
    _lead("lead-un", "vendeur.un", CONTACT_A)
    _lead("lead-deux", "vendeur.deux", CONTACT_B)
    _lead("lead-dormant", "vendeur.un", CONTACT_C,
          ingere="2026-08-01T09:00:00-04:00", qualifie="2026-08-01T10:00:00-04:00")
    _lead("lead-nouveau", None, {"nom": "Client N", "courriel": "n@example.test"}, ingere="2026-07-01T09:00:00-04:00")
    _envoyer_devis("devis-un", "lead-un", ENVOI_UN)
    _envoyer_devis("devis-deux", "lead-deux", ENVOI_DEUX)


# -- aides --------------------------------------------------------------------------------------------------
def _appeler(par_nom, nom, arguments, identite_appelante=None, *, recu_le=None):
    """Un appel de l'outil réel. `recu_le` : l'heure de RÉCEPTION du serveur d'un appel d'appareil idempotent."""
    reception = None
    if recu_le is not None:
        reception = contexte.HorodatageAppareil(
            appareil="tel-fictif", horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
            recu_le=dt.datetime.fromisoformat(recu_le))
    with contexte.receptionne_de(reception):
        if identite_appelante is None:
            return executer_atomique(par_nom[nom], arguments)
        with contexte.appele_par_appareil(identite_appelante):
            return executer_atomique(par_nom[nom], arguments)


def _lister(par_nom, identite_appelante=ADMIN, **plus):
    return _appeler(par_nom, "m2_lister_relances", {"horodatage": MAINTENANT, **plus}, identite_appelante)


def _preparer(par_nom, lead_id="lead-un", regle="relance_devis_sans_reponse", canal="appel",
              identite_appelante=VENDEUR_UN, horodatage=MAINTENANT, **plus):
    arguments = {"lead_id": lead_id, "regle": regle, "canal": canal, "horodatage": horodatage, **plus}
    return _appeler(par_nom, "m2_preparer_relance", arguments, identite_appelante)


def _arguments_consentement(lead_id="lead-un", canal="sms", **plus):
    return {
        "lead_id": lead_id, "canal": canal, "enonce_version": "consentement-sms-v1", "source": "formulaire",
        "preuve": dict(PREUVE), "recueilli_le": RECUEILLI, "horodatage": "2026-09-20T10:05:00-04:00", **plus}


def _consentement(lead_id="lead-un", canal="sms", identite_appelante=VENDEUR_UN, **plus):
    arguments = _arguments_consentement(lead_id, canal, **plus)
    return _appeler(par_nom_global(), "m2_enregistrer_consentement_contact", arguments, identite_appelante)


def _forcer_une_decision_en_cours(arguments, *, decide_par="nathan", decide_role="nathan_owner", statut="en_cours",
                                  departement=DEPARTEMENT, outil="m2_enregistrer_consentement_contact"):
    """Écrit dans la file la ligne que `approbations.decider` écrit au moment d'exécuter, et rend son identifiant : pour
    prouver, sans passer par `decider`, ce que l'outil accepte et refuse comme décision d'une personne."""
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, departement, outil, arguments, niveau=Niveau.N3)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut=statut, decide_par=decide_par, decide_role=decide_role))
    return ident


def par_nom_global():
    return {o.nom: o for o in outils.outils()}


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _verdict(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _ids(page):
    return [(r["lead_id"], r["regle"]) for r in page["relances"]]


def _instantane_base():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _preparees():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "relances_preparees"))


def _journal_consentements():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "consentements_contact"))


def _relance(page, lead_id, regle="relance_devis_sans_reponse"):
    (item,) = [r for r in page["relances"] if r["lead_id"] == lead_id and r["regle"] == regle]
    return item


# =========================================================================================
# 1. La déclaration des trois outils
# =========================================================================================
def test_lister_relances_est_une_lecture_ouverte_au_vendeur_et_a_l_admin_seulement(par_nom):
    outil = par_nom["m2_lister_relances"]
    assert outil.autonomie is Autonomie.T0 and outil.niveau_effectif is Niveau.N0
    assert outil.roles_appareil == acces.ROLES_LEADS == frozenset({"seller", "admin"})
    assert outil.fonction is outils.lister_relances and len(outil.description) <= 1024
    assert "employee" not in outil.roles_appareil


def test_preparer_relance_est_une_ecriture_interne_n3_qui_n_envoie_rien(par_nom):
    outil = par_nom["m2_preparer_relance"]
    assert outil.autonomie is Autonomie.T1 and outil.niveau_effectif is Niveau.N3
    assert outil.frontiere_humaine is False
    assert outil.roles_appareil == acces.ROLES_LEADS
    assert outil.fonction is outils.preparer_relance and len(outil.description) <= 1024
    assert "N'ENVOIE RIEN" in outil.description


def test_le_consentement_est_une_ecriture_interne_n3_qui_exige_une_personne(par_nom):
    outil = par_nom["m2_enregistrer_consentement_contact"]
    assert outil.autonomie is Autonomie.T1 and outil.niveau_effectif is Niveau.N3
    assert outil.frontiere_humaine is False
    assert outil.roles_appareil == acces.ROLES_LEADS and "employee" not in outil.roles_appareil
    assert outil.fonction is outils.enregistrer_consentement_contact and len(outil.description) <= 1024


def test_les_schemas_exigent_ce_qu_il_faut_et_refusent_toute_identite_ou_tout_texte_fourni(par_nom):
    lister = par_nom["m2_lister_relances"].parametres
    assert lister["required"] == ["horodatage"] and lister["additionalProperties"] is False
    assert set(lister["properties"]) == {"regle", "permises_seulement", "decalage", "limite", "horodatage"}
    assert lister["properties"]["regle"]["enum"] == [*relances.REGLES, None]
    assert lister["properties"]["limite"]["maximum"] == relances.LIMITE_MAX

    preparer = par_nom["m2_preparer_relance"].parametres
    assert set(preparer["required"]) == {"lead_id", "regle", "canal", "horodatage"}
    assert preparer["additionalProperties"] is False
    assert preparer["properties"]["canal"]["enum"] == ["appel", "sms", "courriel"]
    assert set(preparer["properties"]) == {"lead_id", "regle", "canal", "horodatage"}, "ni texte, ni personne fournis"

    consentement = par_nom["m2_enregistrer_consentement_contact"].parametres
    assert set(consentement["required"]) == {
        "lead_id", "canal", "enonce_version", "source", "preuve", "recueilli_le", "horodatage"}
    assert consentement["properties"]["canal"]["enum"] == ["sms", "courriel"]
    assert consentement["properties"]["preuve"]["additionalProperties"] is False
    assert not {"enregistre_par", "voie", "par", "role", "client_id"} & set(consentement["properties"])


@pytest.mark.parametrize(("nom", "arguments"), [
    ("m2_lister_relances", {}),
    ("m2_lister_relances", {"horodatage": MAINTENANT, "lead_id": "lead-un"}),
    ("m2_lister_relances", {"horodatage": MAINTENANT, "limite": True}),
    ("m2_lister_relances", {"horodatage": MAINTENANT, "decalage": "0"}),
    ("m2_lister_relances", {"horodatage": MAINTENANT, "regle": "inconnue"}),
    ("m2_lister_relances", {"horodatage": MAINTENANT, "permises_seulement": "oui"}),
    ("m2_lister_relances", {"horodatage": 5}),
    ("m2_preparer_relance", {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel"}),
    ("m2_preparer_relance", {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "pigeon",
                             "horodatage": MAINTENANT}),
    ("m2_preparer_relance", {"lead_id": "lead-un", "regle": "inconnue", "canal": "appel", "horodatage": MAINTENANT}),
    ("m2_preparer_relance", {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel",
                             "horodatage": MAINTENANT, "texte": "Bonjour"}),
    ("m2_preparer_relance", {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel",
                             "horodatage": MAINTENANT, "prepare_par": "vendeur.deux"}),
    ("m2_enregistrer_consentement_contact", {"lead_id": "lead-un", "canal": "sms"}),
    ("m2_enregistrer_consentement_contact", {
        "lead_id": "lead-un", "canal": "appel", "enonce_version": "v1", "source": "formulaire", "preuve": PREUVE,
        "recueilli_le": RECUEILLI, "horodatage": RECUEILLI}),
    ("m2_enregistrer_consentement_contact", {
        "lead_id": "lead-un", "canal": "sms", "enonce_version": "v1", "source": "formulaire", "preuve": PREUVE,
        "recueilli_le": RECUEILLI, "horodatage": RECUEILLI, "enregistre_par": "vendeur.deux"}),
    ("m2_enregistrer_consentement_contact", {
        "lead_id": "lead-un", "canal": "sms", "enonce_version": "v1", "source": "rumeur", "preuve": PREUVE,
        "recueilli_le": RECUEILLI, "horodatage": RECUEILLI}),
])
def test_des_arguments_hors_schema_sont_refuses_avant_l_outil_sans_rien_ecrire(par_nom, monde, nom, arguments):
    avant = _instantane_base()
    reponse = _appeler(par_nom, nom, arguments, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", reponse
    assert _instantane_base() == avant


# =========================================================================================
# 2. m2_lister_relances : qui voit quoi
# =========================================================================================
def test_l_admin_voit_les_quatre_relances_dans_l_ordre_de_leur_echeance(par_nom, monde):
    page = _accepte(_lister(par_nom))
    assert _ids(page) == [
        ("lead-nouveau", "relance_lead_dormant"), ("lead-dormant", "relance_lead_dormant"),
        ("lead-un", "relance_devis_sans_reponse"), ("lead-deux", "relance_devis_sans_reponse"),
    ]
    assert [r["due_depuis"] for r in page["relances"]] == [
        "2026-07-31T13:00:00+00:00", "2026-08-31T14:00:00+00:00", "2026-09-24T13:00:00+00:00",
        "2026-09-26T13:00:00+00:00",
    ]
    assert (page["total"], page["suivant"], page["reste"]) == (4, None, 0)
    assert page["ordre"] == relances.ORDRE_RELANCES and page["jours_entre_relances"] == 7
    assert page["regles_non_calculables"] == [] and page["indetermines"] == 0


def test_chaque_relance_dit_sa_regle_son_segment_son_depart_sa_frequence_et_ses_canaux(par_nom, monde):
    page = _accepte(_lister(par_nom))
    devis = _relance(page, "lead-un")
    assert devis["statut"] == "qualifie" and devis["proprietaire"] == "vendeur.un"
    assert devis["segment"] == {
        "segment": "quote_stale", "regle": "devis_envoye_sans_reponse_perime",
        "donnee": {"devis_id": "devis-un", "statut_devis": "envoye", "horodatage_devis": ENVOI_UN, "jours_ecoules": 19,
                   "seuil_jours": 14},
    }
    assert devis["depart"]["fait"] == "m3.devis_envoye" and devis["depart"]["instant"] == ENVOI_UN
    assert "pas de la livraison au client" in devis["depart"]["remarque"]
    assert devis["derniere_relance"] is None and devis["prochaine_date_permise"] is None
    assert devis["permise_maintenant"] is True
    assert (devis["mode"], devis["canaux_permis"]) == ("appel_seulement", ["appel"])
    assert devis["consentements"] == {"sms": {"etat": "absent"}, "courriel": {"etat": "absent"}}
    dormant = _relance(page, "lead-dormant", "relance_lead_dormant")
    assert dormant["depart"] == {"fait": "derniere_activite_humaine", "instant": "2026-08-01T10:00:00-04:00"}
    assert dormant["segment"]["donnee"]["jours_ecoules"] == 59
    assert set(page["regles"]) == {"relance_devis_sans_reponse", "relance_lead_dormant"}
    assert set(page["regles_des_segments"]) == {"devis_envoye_sans_reponse_perime", "lead_ouvert_sans_activite"}


def test_le_vendeur_ne_voit_que_les_relances_de_ses_leads(par_nom, monde):
    page = _accepte(_lister(par_nom, VENDEUR_UN))
    assert _ids(page) == [("lead-dormant", "relance_lead_dormant"), ("lead-un", "relance_devis_sans_reponse")]
    assert page["total"] == 2
    texte = json.dumps(page, ensure_ascii=False)
    for invisible in ("lead-deux", "lead-nouveau", "vendeur.deux", "devis-deux"):
        assert invisible not in texte, invisible


def test_l_autre_vendeur_voit_les_siennes_et_pas_celles_du_premier(par_nom, monde):
    page = _accepte(_lister(par_nom, VENDEUR_DEUX))
    assert _ids(page) == [("lead-deux", "relance_devis_sans_reponse")] and page["total"] == 1
    assert "lead-un" not in json.dumps(page) and "lead-dormant" not in json.dumps(page)


def test_un_lead_sans_proprietaire_n_est_a_aucun_vendeur_l_admin_le_voit(par_nom, monde):
    assert ("lead-nouveau", "relance_lead_dormant") in _ids(_accepte(_lister(par_nom, ADMIN)))
    for vendeur in (VENDEUR_UN, VENDEUR_DEUX):
        assert "lead-nouveau" not in json.dumps(_accepte(_lister(par_nom, vendeur)))
    nouveau = _relance(_accepte(_lister(par_nom, ADMIN)), "lead-nouveau", "relance_lead_dormant")
    assert nouveau["proprietaire"] is None and nouveau["statut"] == "nouveau"


def test_sans_identite_d_appareil_l_agent_voit_toutes_les_relances_comme_le_reste_de_m2(par_nom, monde):
    assert len(_accepte(_lister(par_nom, None))["relances"]) == 4


def test_un_lead_reassigne_suit_son_nouveau_vendeur_pour_ses_relances(par_nom, monde):
    with contexte.appele_par_appareil(ADMIN):
        accuse = executer_atomique(par_nom["m2_reassigner_lead"], {
            "lead_id": "lead-un", "nouveau_proprietaire": "vendeur.deux",
            "motif": "Le vendeur un part en congé, le dossier passe à un collègue.", "horodatage": MAINTENANT})
    assert accuse["resultat"]["accepte"] is True, accuse
    assert _ids(_accepte(_lister(par_nom, VENDEUR_DEUX))) == [
        ("lead-un", "relance_devis_sans_reponse"), ("lead-deux", "relance_devis_sans_reponse")]
    assert _ids(_accepte(_lister(par_nom, VENDEUR_UN))) == [("lead-dormant", "relance_lead_dormant")]
    assert _relance(_accepte(_lister(par_nom, ADMIN)), "lead-un")["proprietaire"] == "vendeur.deux"


@pytest.mark.parametrize("appelante", [MARC, ANCIEN, INCONNUE])
def test_un_employe_ou_une_identite_non_confirmee_est_refuse_avant_toute_lecture(par_nom, monde, appelante):
    avant = _instantane_base()
    verdict = _verdict(_lister(par_nom, appelante))
    assert verdict["code"] == CODE_INVALIDE
    assert _instantane_base() == avant
    for nom in ("m2_preparer_relance",):
        refus = _verdict(_appeler(par_nom, nom, {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse",
                                                  "canal": "appel", "horodatage": MAINTENANT}, appelante))
        assert refus["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_un_appel_hors_transaction_est_refuse_meme_avec_une_identite(par_nom, monde):
    assert stockage.connexion_courante() is None
    with contexte.appele_par_appareil(ADMIN):
        reponse = outils.lister_relances(MAINTENANT)
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_INVALIDE


def test_la_sortie_ne_porte_ni_contact_ni_montant(par_nom, monde):
    tout = json.dumps(_accepte(_lister(par_nom)), ensure_ascii=False)
    for secret in NUMEROS + ("prix", "cout", "marge", "montant"):
        assert secret not in tout, secret
    assert "client_id" not in tout


# =========================================================================================
# 3. m2_lister_relances : la configuration, jamais un défaut
# =========================================================================================
@pytest.mark.parametrize("appelante", [ADMIN, VENDEUR_UN, None])
def test_sans_frequence_configuree_la_liste_dit_a_configurer_et_n_ecrit_rien(par_nom, monde, monkeypatch, tmp_path,
                                                                            appelante):
    _installer_configuration(monkeypatch, tmp_path, relances_={})
    avant = _instantane_base()

    verdict = _verdict(_lister(par_nom, appelante))

    assert verdict["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert "jours_entre_relances" in verdict["detail"] and "configuration.relances" in verdict["detail"]
    assert _instantane_base() == avant


@pytest.mark.parametrize("valeur", [0, -3, "7", 7.5, True, None])
def test_une_frequence_invalide_ou_nulle_est_refusee_jamais_corrigee(par_nom, monde, monkeypatch, tmp_path, valeur):
    _installer_configuration(monkeypatch, tmp_path, relances_={"jours_entre_relances": valeur})
    verdict = _verdict(_lister(par_nom))
    assert verdict["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert ("invalide" in verdict["detail"]) is (valeur is not None)


def test_le_vrai_manifeste_laisse_la_frequence_vide_a_dessein(par_nom, monde, monkeypatch):
    """Le `department.yaml` RÉEL de M2 : ni fréquence ni délais livrés, donc « à configurer » (décision de Nathan)."""
    chemin_reel = M2 / "department.yaml"
    reel = yaml.safe_load(chemin_reel.read_text(encoding="utf-8"))
    assert reel["configuration"]["relances"] == {} and reel["configuration"]["segments"] == {}
    monkeypatch.setattr(outils, "_MANIFESTE", chemin_reel)
    avant = _instantane_base()
    verdict = _verdict(_lister(par_nom))
    assert verdict["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert _verdict(_preparer(par_nom))["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert _instantane_base() == avant


def test_un_bloc_de_configuration_illisible_est_invalide_pas_devine(par_nom, monde, monkeypatch, tmp_path):
    reel = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
    chemin = tmp_path / "department-illisible.yaml"
    chemin.write_text(yaml.safe_dump({**reel, "configuration": "n'importe quoi"}), encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)
    assert _verdict(_lister(par_nom))["code"] == "REJ-RELANCES-A-CONFIGURER"


def test_un_delai_absent_rend_la_regle_non_calculable_et_les_autres_suivent(par_nom, monde, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path, segments={"jours_inactivite_dormant": 30})
    page = _accepte(_lister(par_nom))
    assert {r["regle"] for r in page["relances"]} == {"relance_lead_dormant"}
    (manque,) = page["regles_non_calculables"]
    assert manque["regle"] == "relance_devis_sans_reponse" and manque["segment"] == "quote_stale"
    assert "seuil à configurer" in manque["manque"] and "jours_soumission_perimee" in manque["manque"]


def test_un_filtre_sur_une_regle_non_calculable_est_refuse_pas_une_liste_vide(par_nom, monde, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path, segments={})
    verdict = _verdict(_lister(par_nom, regle="relance_devis_sans_reponse"))
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE" and "seuil à configurer" in verdict["detail"]
    sans_filtre = _accepte(_lister(par_nom))
    assert sans_filtre["relances"] == [] and len(sans_filtre["regles_non_calculables"]) == 2, (
        "la liste vide dit ce qui manque : elle ne se lit pas « aucune relance due »")


def test_un_horodatage_illisible_est_refuse_avec_le_verdict_de_l_instant(par_nom, monde):
    avant = _instantane_base()
    for mauvais in ("hier", "2026-09-29", "2026-09-29T12:00:00"):
        assert _verdict(_lister(par_nom, horodatage=mauvais))["code"] == "REJ-HORODATAGE-INVALIDE"
    assert _instantane_base() == avant


def test_hors_stockage_durable_rien_n_est_calcule_sans_historique_ni_consentement(par_nom, monde):
    """Le lead existe (registre en mémoire), mais les consentements, les relances déjà préparées et les faits de M3 ne
    sont pas lisibles : laisser passer serait une fréquence et un consentement inventés."""
    outils.reinitialiser_registre()
    _lead("lead-un", "vendeur.un", CONTACT_A)
    for verdict in (
        _verdict(_lister(par_nom, VENDEUR_UN)),
        _verdict(_preparer(par_nom, "lead-un", canal="appel")),
        _verdict(_lister(par_nom, None)),
    ):
        assert verdict["code"] == "REJ-BUS-INDISPONIBLE" and "aucune relance n'est calculée" in verdict["detail"]


def test_les_seuils_et_la_frequence_sont_relus_a_chaque_appel(par_nom, monde, monkeypatch, tmp_path):
    assert len(_accepte(_lister(par_nom))["relances"]) == 4
    _installer_configuration(
        monkeypatch, tmp_path, segments={"jours_inactivite_dormant": 30, "jours_soumission_perimee": 60})
    assert {r["regle"] for r in _accepte(_lister(par_nom))["relances"]} == {"relance_lead_dormant"}
    _installer_configuration(monkeypatch, tmp_path, relances_={"jours_entre_relances": 3})
    assert _accepte(_lister(par_nom))["jours_entre_relances"] == 3


# =========================================================================================
# 4. m2_lister_relances : pages, filtres, statuts
# =========================================================================================
def test_un_lead_perdu_ou_converti_n_a_plus_de_relance(par_nom, monde):
    assert outils.transitionner_statut("lead-un", "perdu", MAINTENANT, motif="Client parti (fictif)")["accepte"]
    assert outils.transitionner_statut("lead-deux", "converti", MAINTENANT, reference_devis_m3="devis-deux")["accepte"]
    assert _ids(_accepte(_lister(par_nom))) == [
        ("lead-nouveau", "relance_lead_dormant"), ("lead-dormant", "relance_lead_dormant")]


def test_un_devis_repond_par_l_acceptation_n_est_plus_relance(par_nom, monde):
    assert outils.transitionner_statut("lead-un", "converti", MAINTENANT, reference_devis_m3="devis-un")["accepte"]
    assert "lead-un" not in json.dumps(_accepte(_lister(par_nom)))


@pytest.mark.parametrize("plus", [{"limite": 0}, {"limite": 31}, {"limite": -1}, {"decalage": -1}])
def test_une_pagination_hors_bornes_est_refusee_sans_rien_lire_d_autre(par_nom, monde, plus):
    avant = _instantane_base()
    verdict = _verdict(_lister(par_nom, **plus))
    assert verdict["code"] == "REJ-PAGINATION-INVALIDE"
    assert _instantane_base() == avant


def test_le_filtre_par_regle_et_la_pagination_par_l_outil(par_nom, monde):
    dormants = _accepte(_lister(par_nom, regle="relance_lead_dormant"))
    assert _ids(dormants) == [("lead-nouveau", "relance_lead_dormant"), ("lead-dormant", "relance_lead_dormant")]
    assert dormants["filtre"] == {"regle": "relance_lead_dormant", "permises_seulement": False}
    premiere = _accepte(_lister(par_nom, limite=3))
    assert (premiere["affichees"], premiere["reste"], premiere["suivant"]) == (3, 1, 3)
    seconde = _accepte(_lister(par_nom, limite=3, decalage=premiere["suivant"]))
    assert (seconde["affichees"], seconde["reste"], seconde["suivant"]) == (1, 0, None)
    assert _ids(premiere) + _ids(seconde) == _ids(_accepte(_lister(par_nom)))
    au_dela = _accepte(_lister(par_nom, decalage=50))
    assert au_dela["relances"] == [] and au_dela["suivant"] is None


def test_beaucoup_de_relances_tiennent_sous_la_limite_de_sortie_et_se_recollent(par_nom, monde):
    for i in range(30):
        lead_id = f"lead-masse-{i:02d}"
        _lead(lead_id, "vendeur.un", {"nom": f"Client {i}", "courriel": f"masse{i}@example.test"})
        _envoyer_devis(f"devis-masse-{i:02d}", lead_id, f"2026-09-{1 + i % 9:02d}T09:00:00-04:00")
    lues, decalage = [], 0
    while True:
        reponse = _lister(par_nom, VENDEUR_UN, decalage=decalage, limite=30)
        page = _accepte(reponse)
        assert len(json.dumps(reponse["resultat"], ensure_ascii=False)) <= outils.BUDGET_SORTIE + 100
        assert page["affichees"] >= 1 and page["total"] == 32
        lues.extend(_ids(page))
        if page["suivant"] is None:
            break
        decalage = page["suivant"]
    assert len(lues) == 32 and len(set(lues)) == 32
    assert decalage > 0, "la sortie du socle bornait la page : plus d'une page"


# =========================================================================================
# 5. m2_preparer_relance : rien n'est envoyé, un texte fixe, une écriture
# =========================================================================================
def test_le_vendeur_prepare_l_appel_de_son_lead_le_texte_est_le_gabarit_fixe_et_rien_n_est_envoye(par_nom, monde):
    resultat = _accepte(_preparer(par_nom))

    gabarit = gabarits_relance.GABARITS[("relance_devis_sans_reponse", "appel")]
    assert resultat["envoye"] is False and resultat["texte"] == gabarit["texte"]
    assert resultat["nature"] == "points_d_appel" and resultat["gabarit"] == {"id": "relance_devis_appel", "version": 1}
    assert resultat["prepare_le"] == MAINTENANT and resultat["prochaine_date_permise"] == "2026-10-06T16:00:00+00:00"
    assert resultat["avertissements"] == [relances.AVERTISSEMENT_ENVOI_APPROUVE]
    assert resultat["depart"]["fait"] == "m3.devis_envoye"
    (entree,) = _preparees()
    assert entree["relance_id"] == resultat["relance_id"]
    assert (entree["lead_id"], entree["regle"], entree["canal"], entree["segment"]) == (
        "lead-un", "relance_devis_sans_reponse", "appel", "quote_stale")
    assert (entree["prepare_par"], entree["voie"], entree["prepare_le"]) == ("vendeur.un", "appareil", MAINTENANT)
    assert entree["texte"] == gabarit["texte"] and entree["gabarit"] == {"id": "relance_devis_appel", "version": 1}
    assert entree["echeance"] == "2026-09-24T13:00:00+00:00" and entree["client_id"]
    tout = json.dumps(entree)
    for secret in NUMEROS:
        assert secret not in tout, secret


def test_aucune_sortie_reseau_n_est_possible_pendant_la_preparation(par_nom, monde, monkeypatch):
    import socket

    def _interdit(*args, **kwargs):
        raise AssertionError("la préparation d'une relance ne doit ouvrir aucune connexion")

    monkeypatch.setattr(socket, "create_connection", _interdit)
    monkeypatch.setattr(socket.socket, "connect", _interdit)
    _accepte(_preparer(par_nom))
    assert _preparees()[0]["texte"]


def test_la_relance_d_un_lead_dormant_utilise_son_gabarit_sans_avertissement_de_livraison(par_nom, monde):
    resultat = _accepte(_preparer(par_nom, "lead-dormant", "relance_lead_dormant"))
    assert resultat["gabarit"]["id"] == "relance_dormant_appel" and resultat["avertissements"] == []
    assert resultat["depart"]["fait"] == "derniere_activite_humaine"


def test_l_admin_prepare_pour_n_importe_quel_lead_meme_sans_proprietaire(par_nom, monde):
    _accepte(_preparer(par_nom, "lead-nouveau", "relance_lead_dormant", identite_appelante=ADMIN))
    _accepte(_preparer(par_nom, "lead-deux", identite_appelante=ADMIN))
    assert {(p["lead_id"], p["prepare_par"]) for p in _preparees()} == {
        ("lead-nouveau", "admin.fictif"), ("lead-deux", "admin.fictif")}


def test_la_personne_qui_prepare_est_celle_du_jeton_jamais_un_argument(par_nom, monde):
    _accepte(_preparer(par_nom, identite_appelante=VENDEUR_UN))
    assert _preparees()[0]["prepare_par"] == "vendeur.un"
    avant = _instantane_base()
    reponse = _preparer(par_nom, "lead-deux", identite_appelante=VENDEUR_DEUX, prepare_par="vendeur.un")
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _instantane_base() == avant


def test_un_vendeur_ne_prepare_rien_pour_le_lead_d_un_autre_ni_pour_un_lead_inconnu(par_nom, monde):
    avant = _instantane_base()
    for lead in ("lead-deux", "lead-nouveau", "lead-inexistant"):
        assert _verdict(_preparer(par_nom, lead))["code"] == CODE_NON_ASSIGNE, lead
    assert _instantane_base() == avant, "le même refus pour un lead d'un autre et un lead inconnu : rien à sonder"


def test_l_admin_qui_vise_un_lead_inconnu_recoit_le_refus_du_lead_inconnu(par_nom, monde):
    avant = _instantane_base()
    assert _verdict(_preparer(par_nom, "lead-inexistant", identite_appelante=ADMIN))["code"] == "REJ-LEAD-INCONNU"
    assert _instantane_base() == avant


def test_une_relance_qui_n_est_pas_due_est_refusee_sans_ecriture(par_nom, monde):
    avant = _instantane_base()
    verdict = _verdict(_preparer(par_nom, "lead-un", "relance_lead_dormant"))
    assert verdict["code"] == "REJ-RELANCE-NON-DUE" and "dormant_lead" in verdict["detail"]
    assert _instantane_base() == avant


def test_avant_le_delai_du_devis_la_relance_n_est_pas_due(par_nom, monde):
    avant = _instantane_base()
    verdict = _verdict(_preparer(par_nom, horodatage="2026-09-24T08:59:59-04:00"))
    assert verdict["code"] == "REJ-RELANCE-NON-DUE"
    assert _instantane_base() == avant
    assert _accepte(_preparer(par_nom, horodatage="2026-09-24T09:00:00-04:00"))["prepare_le"] == (
        "2026-09-24T09:00:00-04:00")


def test_un_devis_qui_n_a_pas_ete_envoye_n_a_pas_de_relance_meme_apres_des_mois(par_nom, monde):
    _lead("lead-brouillon", "vendeur.un", {"nom": "Client D", "courriel": "d@example.test"})
    verdict = _verdict(_preparer(par_nom, "lead-brouillon", horodatage="2027-03-01T12:00:00-05:00"))
    assert verdict["code"] == "REJ-RELANCE-NON-DUE", "aucun envoi publié par M3 : aucun délai ne part d'une supposition"


# -- fréquence ----------------------------------------------------------------------------------------------
def test_une_seconde_preparation_le_meme_jour_est_refusee_avec_la_prochaine_date_permise(par_nom, monde):
    _accepte(_preparer(par_nom))
    avant = _instantane_base()

    verdict = _verdict(_preparer(par_nom, horodatage="2026-09-29T13:00:00-04:00"))

    assert verdict["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert MAINTENANT in verdict["detail"] and "2026-10-06T16:00:00+00:00" in verdict["detail"]
    assert "appel" in verdict["detail"] and "tous les 7 jours" in verdict["detail"]
    assert _instantane_base() == avant and len(_preparees()) == 1


def test_pile_a_la_prochaine_date_permise_la_relance_est_permise_une_seconde_avant_non(par_nom, monde):
    _accepte(_preparer(par_nom))  # MAINTENANT = 2026-09-29T16:00:00Z ; prochaine date = 2026-10-06T16:00:00Z
    avant = _instantane_base()
    assert _verdict(_preparer(par_nom, horodatage="2026-10-06T15:59:59+00:00"))["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert _instantane_base() == avant
    second = _accepte(_preparer(par_nom, horodatage="2026-10-06T16:00:00+00:00"))
    assert second["prepare_le"] == "2026-10-06T16:00:00+00:00" and len(_preparees()) == 2
    assert second["prochaine_date_permise"] == "2026-10-13T16:00:00+00:00"


def test_la_liste_montre_la_derniere_relance_la_prochaine_date_et_le_filtre_ecarte_la_trop_proche(par_nom, monde):
    _accepte(_preparer(par_nom, canal="appel"))
    page = _accepte(_lister(par_nom, VENDEUR_UN))
    devis = _relance(page, "lead-un")
    assert devis["derniere_relance"] == {"le": MAINTENANT, "canal": "appel"}
    assert devis["prochaine_date_permise"] == "2026-10-06T16:00:00+00:00" and devis["permise_maintenant"] is False
    permises = _accepte(_lister(par_nom, VENDEUR_UN, permises_seulement=True))
    assert _ids(permises) == [("lead-dormant", "relance_lead_dormant")]
    # La fréquence est celle de la PERSONNE : la relance de lead-dormant (autre client) reste permise.
    assert _relance(page, "lead-dormant", "relance_lead_dormant")["permise_maintenant"] is True
    plus_tard = _accepte(_lister(par_nom, VENDEUR_UN, horodatage="2026-10-06T16:00:00+00:00"))
    assert _relance(plus_tard, "lead-un")["permise_maintenant"] is True


def test_la_frequence_est_celle_d_une_personne_les_leads_d_un_meme_client_comptent_ensemble(par_nom, monde):
    _lead("partage-a", "vendeur.un", CONTACT_PARTAGE)
    _lead("partage-b", "vendeur.deux", CONTACT_PARTAGE)
    _envoyer_devis("devis-partage-a", "partage-a", ENVOI_UN)
    _envoyer_devis("devis-partage-b", "partage-b", ENVOI_UN)
    _accepte(_preparer(par_nom, "partage-a"))

    verdict = _verdict(_preparer(par_nom, "partage-b", identite_appelante=VENDEUR_DEUX))

    assert verdict["code"] == "REJ-RELANCE-TROP-PROCHE"
    for secret in ("partage-a", "vendeur.un", "devis-partage-a"):
        assert secret not in json.dumps(verdict), "rien ne dit à ce vendeur quel autre dossier a été relancé"
    page = _accepte(_lister(par_nom, VENDEUR_DEUX))
    item = _relance(page, "partage-b")
    assert item["derniere_relance"] == {"le": MAINTENANT, "canal": "appel"} and item["permise_maintenant"] is False
    assert "partage-a" not in json.dumps(page)


def test_un_autre_client_n_est_pas_limite_par_la_relance_de_celui_ci(par_nom, monde):
    _accepte(_preparer(par_nom, "lead-un"))
    assert _accepte(_preparer(par_nom, "lead-dormant", "relance_lead_dormant"))["lead_id"] == "lead-dormant"


def test_une_frequence_plus_courte_ou_plus_longue_configuree_s_applique(par_nom, monde, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path, relances_={"jours_entre_relances": 1})
    _accepte(_preparer(par_nom))
    assert _verdict(_preparer(par_nom, horodatage="2026-09-30T15:59:59+00:00"))["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert _accepte(_preparer(par_nom, horodatage="2026-09-30T16:00:00+00:00"))["prochaine_date_permise"] == (
        "2026-10-01T16:00:00+00:00")
    _installer_configuration(monkeypatch, tmp_path, relances_={"jours_entre_relances": 30})
    assert _verdict(_preparer(par_nom, horodatage="2026-10-29T15:59:59+00:00"))["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert _accepte(_preparer(par_nom, horodatage="2026-10-31T16:00:00+00:00"))


def test_sans_frequence_configuree_rien_n_est_prepare(par_nom, monde, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path, relances_={})
    avant = _instantane_base()
    assert _verdict(_preparer(par_nom))["code"] == "REJ-RELANCES-A-CONFIGURER"
    assert _instantane_base() == avant and _preparees() == []


def test_l_instant_illisible_est_refuse_avant_la_frequence_configuree(par_nom, monde, monkeypatch, tmp_path):
    """Ordre documenté de `m2_preparer_relance` : l'instant est contrôlé avant la fréquence maximale configurée."""
    _installer_configuration(monkeypatch, tmp_path, relances_={})
    avant = _instantane_base()
    for mauvais in ("hier", "2026-09-29", "2026-09-29T12:00:00"):
        assert _verdict(_preparer(par_nom, horodatage=mauvais))["code"] == "REJ-HORODATAGE-INVALIDE", mauvais
    assert _instantane_base() == avant
    assert _verdict(_preparer(par_nom))["code"] == "REJ-RELANCES-A-CONFIGURER"


def test_un_delai_absent_refuse_la_preparation_de_la_regle_avec_ce_qui_manque(par_nom, monde, monkeypatch, tmp_path):
    _installer_configuration(monkeypatch, tmp_path, segments={"jours_inactivite_dormant": 30})
    avant = _instantane_base()
    verdict = _verdict(_preparer(par_nom))
    assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE" and "jours_soumission_perimee" in verdict["detail"]
    assert _instantane_base() == avant
    assert _accepte(_preparer(par_nom, "lead-dormant", "relance_lead_dormant"))["lead_id"] == "lead-dormant"


# -- consentement -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("canal", ["sms", "courriel"])
def test_sans_consentement_actif_un_message_est_refuse_et_l_appel_reste_permis(par_nom, monde, canal):
    avant = _instantane_base()
    verdict = _verdict(_preparer(par_nom, canal=canal))
    assert verdict["code"] == "REJ-CONSENTEMENT-ABSENT" and canal in verdict["detail"]
    assert _instantane_base() == avant and _preparees() == []
    assert _accepte(_preparer(par_nom, canal="appel"))["canal"] == "appel"


def test_avec_un_consentement_actif_le_message_est_prepare_avec_le_gabarit_fixe(par_nom, monde):
    _accepte(_consentement("lead-un", "sms"))
    resultat = _accepte(_preparer(par_nom, canal="sms"))
    gabarit = gabarits_relance.GABARITS[("relance_devis_sans_reponse", "sms")]
    assert resultat["texte"] == gabarit["texte"] and resultat["nature"] == "message" and resultat["envoye"] is False
    assert "répondez STOP" in resultat["texte"]
    assert _verdict(_preparer(par_nom, "lead-un", canal="courriel", horodatage="2026-10-30T12:00:00-04:00"))[
        "code"] == "REJ-CONSENTEMENT-ABSENT", "le consentement d'un canal n'ouvre pas l'autre"


def test_apres_un_stop_aucun_message_meme_avec_un_consentement_et_l_appel_reste_permis(par_nom, monde):
    _accepte(_consentement("lead-un", "sms"))
    _accepte(_consentement("lead-un", "courriel"))
    assert _accepte(_lister(par_nom, VENDEUR_UN)) and _relance(
        _accepte(_lister(par_nom, VENDEUR_UN)), "lead-un")["canaux_permis"] == ["appel", "sms", "courriel"]
    _stop(["lead-un"])
    avant = _instantane_base()

    for canal in ("sms", "courriel"):
        verdict = _verdict(_preparer(par_nom, canal=canal))
        assert verdict["code"] == "REJ-CONSENTEMENT-RETIRE" and "appel seulement" in verdict["detail"]
    assert _instantane_base() == avant
    item = _relance(_accepte(_lister(par_nom, VENDEUR_UN)), "lead-un")
    assert (item["mode"], item["canaux_permis"]) == ("appel_seulement", ["appel"])
    assert item["consentements"]["sms"]["etat"] == "retire" and item["consentements"]["sms"]["retire_le"] == (
        "2026-09-25T09:00:00-04:00")
    assert _accepte(_preparer(par_nom, canal="appel"))["canal"] == "appel"


def test_le_stop_d_un_lead_ferme_les_canaux_de_tous_les_leads_du_meme_client(par_nom, monde):
    _lead("partage-a", "vendeur.un", CONTACT_PARTAGE)
    _lead("partage-b", "vendeur.deux", CONTACT_PARTAGE)
    _envoyer_devis("devis-partage-b", "partage-b", ENVOI_UN)
    _accepte(_consentement("partage-a", "sms"))
    assert _accepte(_lister(par_nom, VENDEUR_DEUX))["relances"][0]["canaux_permis"] == ["appel", "sms"]
    _stop(["partage-a"])
    item = _relance(_accepte(_lister(par_nom, VENDEUR_DEUX)), "partage-b")
    assert item["canaux_permis"] == ["appel"] and item["consentements"]["sms"]["etat"] == "retire"


def test_un_consentement_recueilli_d_un_lead_du_meme_client_ouvre_le_canal_pour_l_autre_lead(par_nom, monde):
    _lead("partage-a", "vendeur.un", CONTACT_PARTAGE)
    _lead("partage-b", "vendeur.deux", CONTACT_PARTAGE)
    _envoyer_devis("devis-partage-b", "partage-b", ENVOI_UN)
    _accepte(_consentement("partage-a", "courriel"))
    assert _accepte(_preparer(par_nom, "partage-b", canal="courriel", identite_appelante=VENDEUR_DEUX))["canal"] == (
        "courriel")


# -- agent, approbation, idempotence, heure du serveur ------------------------------------------------------
def test_un_agent_qui_propose_attend_une_personne_puis_la_relance_est_preparee_au_nom_de_l_agent(
        capacites, monde):
    proposition = capacites.appeler("m2_preparer_relance", {
        "lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel", "horodatage": MAINTENANT})
    assert proposition["ok"] is True and proposition["statut"] == "en_attente_approbation"
    assert _preparees() == [], "validation humaine au départ : rien n'est préparé avant la décision"
    with stockage.transaction() as cnx:
        (demande,) = approbations.lister(cnx, "en_attente")
    assert (demande["outil"], demande["niveau"], demande["departement"]) == ("m2_preparer_relance", "N3", DEPARTEMENT)

    with stockage.transaction() as cnx:
        approbations.decider(
            cnx, proposition["demande_id"], True, "nathan",
            outils_executables(capacites.departements, stockage.transaction), capacites.departements)

    (entree,) = _preparees()
    assert (entree["prepare_par"], entree["voie"], entree["prepare_le"]) == ("agent", "agent", MAINTENANT)


def test_le_vendeur_qui_renvoie_la_meme_cle_rejoue_la_reponse_sans_seconde_relance(capacites, monde):
    meta = idempotence.Meta(cle="mut-relance-1", appareil="tel-vendeur-fictif-1", horodatage_appareil=MAINTENANT)
    arguments = {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel",
                 "horodatage": "2000-01-01T00:00:00+00:00"}

    def appel():
        with contexte.appele_par_appareil(VENDEUR_UN):
            return capacites.appeler("m2_preparer_relance", arguments, meta)

    premiere = appel()
    avant = _instantane_base()
    seconde = appel()

    assert premiere["ok"] is True and premiere["resultat"]["accepte"] is True and premiere["rejoue"] is False
    assert seconde["rejoue"] is True and seconde["resultat"] == premiere["resultat"]
    assert _instantane_base() == avant and len(_preparees()) == 1
    (entree,) = _preparees()
    assert entree["prepare_le"] != arguments["horodatage"], "l'heure du serveur, jamais celle de l'appareil"
    assert abs((dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(entree["prepare_le"])).total_seconds()) < 120
    with stockage.transaction() as cnx:
        (trace,) = approbations.lister(cnx, "executee")
    assert (trace["outil"], trace["niveau"], trace["decide_par"], trace["decide_role"]) == (
        "m2_preparer_relance", "N3", "vendeur.un", "seller")


def test_pour_un_appel_d_appareil_l_heure_du_serveur_fait_foi_un_appareil_ne_peut_pas_avancer_l_heure(par_nom, monde):
    base = {"lead_id": "lead-un", "regle": "relance_devis_sans_reponse", "canal": "appel"}
    _accepte(_appeler(par_nom, "m2_preparer_relance", {**base, "horodatage": "2030-01-01T00:00:00+00:00"},
                      VENDEUR_UN, recu_le="2026-09-29T16:00:00+00:00"))
    (entree,) = _preparees()
    assert entree["prepare_le"] == "2026-09-29T16:00:00+00:00", "l'heure de réception, pas l'argument"
    # Un appareil qui annonce une heure future pour contourner la fréquence n'y gagne rien.
    verdict = _verdict(_appeler(par_nom, "m2_preparer_relance", {**base, "horodatage": "2031-01-01T00:00:00+00:00"},
                                VENDEUR_UN, recu_le="2026-09-30T16:00:00+00:00"))
    assert verdict["code"] == "REJ-RELANCE-TROP-PROCHE" and len(_preparees()) == 1


def test_les_preparations_gardent_un_registre_lisible_dans_l_ordre_et_sans_doublon(par_nom, monde):
    _accepte(_preparer(par_nom, "lead-un"))
    _accepte(_preparer(par_nom, "lead-dormant", "relance_lead_dormant"))
    assert [(p["lead_id"], p["regle"]) for p in _preparees()] == [
        ("lead-un", "relance_devis_sans_reponse"), ("lead-dormant", "relance_lead_dormant")]
    assert len({p["relance_id"] for p in _preparees()}) == 2


# =========================================================================================
# 6. m2_enregistrer_consentement_contact : une décision de personne, un retrait ne se lève pas
# =========================================================================================
def test_le_vendeur_inscrit_le_consentement_de_son_lead_avec_son_enonce_sa_preuve_et_son_nom(par_nom, monde):
    resultat = _accepte(_consentement("lead-un", "sms"))

    assert resultat["canal"] == "sms" and resultat["etat"] == "actif" and resultat["deja_enregistre"] is False
    assert (resultat["enregistre_par"], resultat["voie"], resultat["enonce_version"]) == (
        "vendeur.un", "appareil", "consentement-sms-v1")
    assert resultat["preuve"] == PREUVE and resultat["source"] == "formulaire"
    (entree,) = [m for m in _journal_consentements() if m["type_entree"] == "consentement_contact"]
    assert entree["consentement_id"] == resultat["consentement_id"] and entree["lead_id"] == "lead-un"
    assert entree["client_id"] and entree["recueilli_le"] == RECUEILLI
    assert entree["enregistre_le"] == "2026-09-20T10:05:00-04:00"
    tout = json.dumps(_journal_consentements())
    for secret in NUMEROS:
        assert secret not in tout, secret


def test_le_consentement_ouvre_le_canal_dans_la_liste_avec_son_enonce_versionne(par_nom, monde):
    _accepte(_consentement("lead-un", "sms"))
    item = _relance(_accepte(_lister(par_nom, VENDEUR_UN)), "lead-un")
    assert (item["mode"], item["canaux_permis"]) == ("appel_ou_message", ["appel", "sms"])
    assert item["consentements"]["sms"] == {
        "etat": "actif", "enonce_version": "consentement-sms-v1", "source": "formulaire", "preuve_type": "formulaire",
        "recueilli_le": RECUEILLI,
    }
    assert item["consentements"]["courriel"] == {"etat": "absent"}


def test_un_vendeur_n_inscrit_pas_pour_le_lead_d_un_autre_et_l_admin_le_peut(par_nom, monde):
    avant = _instantane_base()
    for lead in ("lead-deux", "lead-nouveau", "lead-inexistant"):
        assert _verdict(_consentement(lead, "sms"))["code"] == CODE_NON_ASSIGNE, lead
    assert _instantane_base() == avant
    assert _accepte(_consentement("lead-deux", "sms", identite_appelante=ADMIN))["enregistre_par"] == "admin.fictif"
    assert _accepte(_consentement("lead-nouveau", "courriel", identite_appelante=ADMIN))["lead_id"] == "lead-nouveau"


def test_l_admin_qui_inscrit_pour_un_lead_inconnu_recoit_le_refus_du_lead_inconnu(par_nom, monde):
    avant = _instantane_base()
    assert _verdict(_consentement("lead-inexistant", "sms", identite_appelante=ADMIN))["code"] == "REJ-LEAD-INCONNU"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [MARC, ANCIEN, INCONNUE])
def test_un_employe_ou_une_identite_non_confirmee_n_inscrit_aucun_consentement(par_nom, monde, appelante):
    avant = _instantane_base()
    assert _verdict(_consentement("lead-un", "sms", identite_appelante=appelante))["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_un_agent_seul_ne_peut_pas_inscrire_un_consentement_meme_en_supervise(par_nom, monde):
    """`executer_atomique` n'applique aucun mode : c'est l'outil qui refuse tout appel sans personne."""
    avant = _instantane_base()
    verdict = _verdict(_consentement("lead-un", "sms", identite_appelante=None))
    assert verdict["code"] == CODE_HUMAIN
    assert "inscrit par une personne" in verdict["detail"] and "Ne le présente pas comme inscrit" in verdict["detail"]
    assert _instantane_base() == avant and _journal_consentements() == []


def test_un_agent_qui_propose_attend_le_proprietaire_et_le_consentement_est_inscrit_a_son_nom(capacites, monde):
    arguments = {
        "lead_id": "lead-un", "canal": "sms", "enonce_version": "consentement-sms-v1", "source": "appel",
        "preuve": {"type": "verbal_documente", "reference": "note-appel-2026-09-20-A12"}, "recueilli_le": RECUEILLI,
        "horodatage": "2026-09-20T10:05:00-04:00"}
    proposition = capacites.appeler("m2_enregistrer_consentement_contact", arguments)
    assert proposition["ok"] is True and proposition["statut"] == "en_attente_approbation"
    assert _journal_consentements() == []

    with stockage.transaction() as cnx:
        approbations.decider(
            cnx, proposition["demande_id"], True, "nathan",
            outils_executables(capacites.departements, stockage.transaction), capacites.departements)

    (entree,) = _journal_consentements()
    assert (entree["enregistre_par"], entree["voie"], entree["source"]) == ("nathan", "approbation", "appel")
    assert entree["preuve"] == {"type": "verbal_documente", "reference": "note-appel-2026-09-20-A12"}


@pytest.mark.parametrize("approbateur", ["vendeur.un", "marc.fictif", "admin.fictif"])
def test_seul_le_proprietaire_approuve_le_consentement_propose_par_un_agent(capacites, monde, approbateur):
    proposition = capacites.appeler("m2_enregistrer_consentement_contact", {
        "lead_id": "lead-un", "canal": "sms", "enonce_version": "v1", "source": "appel", "preuve": PREUVE,
        "recueilli_le": RECUEILLI, "horodatage": "2026-09-20T10:05:00-04:00"})
    with pytest.raises(ValueError, match="aucun rôle autorisé"), stockage.transaction() as cnx:
        approbations.decider(
            cnx, proposition["demande_id"], True, approbateur,
            outils_executables(capacites.departements, stockage.transaction), capacites.departements)
    assert _journal_consentements() == []


@pytest.mark.parametrize("cas", [
    {"statut": "en_attente"}, {"statut": "refusee"}, {"statut": "executee"},
    {"decide_par": None, "decide_role": None},
    {"decide_par": "marc.fictif", "decide_role": "employee"},
    # Un humain qui porte son rôle, mais qui n'est ni l'admin ni le propriétaire : la politique du département peut le
    # laisser approuver, l'outil est plus strict (`assignation.ROLES_HUMAINS`).
    {"decide_par": "vendeur.un", "decide_role": "seller"},
    {"decide_par": "vendeur.un", "decide_role": "system_agent"},
    {"decide_par": "inconnu.fictif", "decide_role": "nathan_owner"},
    {"decide_par": "marc.fictif", "decide_role": "nathan_owner"},
    {"decide_par": "ancien.vendeur", "decide_role": "admin"},
    {"departement": "m03-estimation"}, {"outil": "m2_preparer_relance"},
])
def test_une_ligne_qui_n_est_pas_une_decision_humaine_en_cours_n_inscrit_aucun_consentement(par_nom, monde, cas):
    ident = _forcer_une_decision_en_cours(_arguments_consentement(), **cas)
    avant = _instantane_base()

    with contexte.executer_demande_approuvee(ident):
        reponse = _appeler(par_nom, "m2_enregistrer_consentement_contact", _arguments_consentement(), None)

    assert _verdict(reponse)["code"] == CODE_HUMAIN
    assert _instantane_base() == avant and _journal_consentements() == []


@pytest.mark.parametrize(("decide_par", "decide_role"), [("nathan", "nathan_owner"), ("admin.fictif", "admin")])
def test_la_decision_en_cours_du_proprietaire_ou_d_un_admin_inscrit_le_consentement_a_son_nom(
        par_nom, monde, decide_par, decide_role):
    ident = _forcer_une_decision_en_cours(_arguments_consentement(), decide_par=decide_par, decide_role=decide_role)

    with contexte.executer_demande_approuvee(ident):
        resultat = _accepte(
            _appeler(par_nom, "m2_enregistrer_consentement_contact", _arguments_consentement(), None))

    assert (resultat["enregistre_par"], resultat["voie"]) == (decide_par, "approbation")
    (entree,) = _journal_consentements()
    assert (entree["enregistre_par"], entree["voie"]) == (decide_par, "approbation")


def test_une_demande_seulement_en_attente_ne_donne_aucun_droit(par_nom, monde):
    with stockage.transaction() as cnx:
        approbations.creer_demande(cnx, DEPARTEMENT, "m2_enregistrer_consentement_contact", {"lead_id": "lead-un"},
                                   niveau=Niveau.N3)
    assert _verdict(_consentement("lead-un", "sms", identite_appelante=None))["code"] == CODE_HUMAIN


def test_le_meme_consentement_n_est_ecrit_qu_une_fois_et_le_rejeu_le_dit(par_nom, monde):
    premier = _accepte(_consentement("lead-un", "sms"))
    avant = _instantane_base()
    second = _accepte(_consentement("lead-un", "sms"))
    assert premier["deja_enregistre"] is False
    assert second["deja_enregistre"] is True and second["consentement_id"] == premier["consentement_id"]
    assert _instantane_base() == avant, "le rejeu n'écrit rien"
    assert len(_journal_consentements()) == 1


def test_un_autre_enonce_ou_un_autre_instant_est_un_autre_consentement(par_nom, monde):
    _accepte(_consentement("lead-un", "sms"))
    _accepte(_consentement("lead-un", "sms", enonce_version="consentement-sms-v2"))
    _accepte(_consentement(
        "lead-un", "sms", recueilli_le="2026-09-21T10:00:00-04:00", horodatage="2026-09-21T10:05:00-04:00"))
    _accepte(_consentement("lead-un", "courriel"))
    assert len(_journal_consentements()) == 4
    assert len({m["consentement_id"] for m in _journal_consentements()}) == 4


@pytest.mark.parametrize(("surcharge", "code"), [
    ({"enonce_version": "avec espace"}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"enonce_version": "x" * 65}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"preuve": {"type": "formulaire", "reference": "514-555-0142"}}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"preuve": {"type": "formulaire", "reference": "vendeur@exemple-fictif.test"}}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"preuve": {"type": "formulaire", "reference": "ab"}}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"recueilli_le": "2026-09-20T10:05:01-04:00"}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"recueilli_le": "hier"}, "REJ-HORODATAGE-INVALIDE"),
    ({"recueilli_le": "2026-09-20T10:00:00"}, "REJ-HORODATAGE-INVALIDE"),
    ({"horodatage": "hier"}, "REJ-HORODATAGE-INVALIDE"),
    ({"preuve": {"type": "formulaire"}}, "REJ-CONSENTEMENT-INVALIDE"),
    ({"preuve": {"type": "formulaire", "reference": "formulaire-web-0042", "telephone": "418-555-0101"}},
     "REJ-CONSENTEMENT-INVALIDE"),
    ({"preuve": {"type": "telepathie", "reference": "formulaire-web-0042"}}, "REJ-CONSENTEMENT-INVALIDE"),
])
def test_une_saisie_invalide_est_refusee_avec_son_verdict_sans_ecriture(par_nom, monde, surcharge, code):
    avant = _instantane_base()
    assert _verdict(_consentement("lead-un", "sms", **surcharge))["code"] == code
    assert _instantane_base() == avant and _journal_consentements() == []


def test_pour_un_appel_d_appareil_l_heure_du_serveur_borne_recueilli_le(par_nom, monde):
    arguments = {"lead_id": "lead-un", "canal": "sms", "enonce_version": "v1", "source": "formulaire", "preuve": PREUVE,
                 "recueilli_le": "2026-09-20T10:00:00-04:00", "horodatage": "2030-01-01T00:00:00+00:00"}
    # Le serveur reçoit l'appel AVANT l'instant du consentement : l'horodatage fourni (2030) ne compte pas.
    verdict = _verdict(_appeler(par_nom, "m2_enregistrer_consentement_contact", arguments, VENDEUR_UN,
                                recu_le="2026-09-20T13:00:00+00:00"))
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE" and "postérieur" in verdict["detail"]
    resultat = _accepte(_appeler(par_nom, "m2_enregistrer_consentement_contact", arguments, VENDEUR_UN,
                                 recu_le="2026-09-20T14:00:00+00:00"))
    assert resultat["enregistre_le"] == "2026-09-20T14:00:00+00:00"


def test_un_retrait_ne_se_leve_jamais_aucun_consentement_n_est_inscrit_apres_un_stop(par_nom, monde):
    _stop(["lead-un"])
    avant = _instantane_base()
    for canal in ("sms", "courriel"):
        verdict = _verdict(_consentement("lead-un", canal))
        assert verdict["code"] == "REJ-CONSENTEMENT-RETIRE" and "un retrait ne se lève pas" in verdict["detail"]
    assert _verdict(_consentement("lead-un", "sms", identite_appelante=ADMIN))["code"] == "REJ-CONSENTEMENT-RETIRE"
    assert _instantane_base() == avant
    assert [m for m in _journal_consentements() if m["type_entree"] == "consentement_contact"] == []


def test_le_stop_d_un_lead_interdit_aussi_le_consentement_sur_un_autre_lead_du_meme_client(par_nom, monde):
    _lead("partage-a", "vendeur.un", CONTACT_PARTAGE)
    _lead("partage-b", "vendeur.deux", CONTACT_PARTAGE)
    _stop(["partage-a"])
    assert _verdict(_consentement("partage-b", "sms", identite_appelante=VENDEUR_DEUX))["code"] == (
        "REJ-CONSENTEMENT-RETIRE")
    assert _accepte(_consentement("lead-un", "sms"))["canal"] == "sms", "un autre client n'est pas touché"


def test_hors_stockage_durable_le_consentement_est_refuse_meme_pour_un_lead_connu(par_nom, monde):
    outils.reinitialiser_registre()
    _lead("lead-un", "vendeur.un", CONTACT_A)
    verdict = _verdict(_consentement("lead-un", "sms"))
    assert verdict["code"] == "REJ-BUS-INDISPONIBLE"


def test_le_consentement_et_la_relance_par_sms_de_bout_en_bout_par_les_outils(par_nom, monde):
    """Le parcours d'un vendeur : sans consentement, le SMS est refusé ; il inscrit le consentement de son client,
    prépare le SMS (texte fixe, jamais envoyé) ; le client écrit STOP : plus aucun message, l'appel reste possible."""
    assert _verdict(_preparer(par_nom, canal="sms"))["code"] == "REJ-CONSENTEMENT-ABSENT"
    _accepte(_consentement("lead-un", "sms"))
    sms = _accepte(_preparer(par_nom, canal="sms"))
    assert sms["texte"] == gabarits_relance.GABARITS[("relance_devis_sans_reponse", "sms")]["texte"]
    _stop(["lead-un"])
    assert _verdict(_preparer(par_nom, canal="sms", horodatage="2026-10-30T12:00:00-04:00"))["code"] == (
        "REJ-CONSENTEMENT-RETIRE")
    assert _accepte(_preparer(par_nom, canal="appel", horodatage="2026-10-30T12:00:00-04:00"))["canal"] == "appel"


@pytest.mark.parametrize("outil", ["lister", "preparer"])
def test_seuls_les_leads_ouverts_sont_evalues_pour_les_relances(par_nom, monde, monkeypatch, outil):
    """Une relance ne se calcule que pour un lead ouvert (`quote_stale`, `dormant_lead`) : l'adaptateur ne fait pas
    évaluer les autres (converti, perdu, chantier...), dont la lecture ne servirait à rien."""
    evaluer = liste_leads.evaluer
    appels = []

    def espion(maillons, **kwargs):
        appels.append(kwargs.get("statuts_retenus"))
        return evaluer(maillons, **kwargs)

    monkeypatch.setattr(liste_leads, "evaluer", espion)
    if outil == "lister":
        _accepte(_lister(par_nom))
    else:
        _accepte(_preparer(par_nom))

    assert appels == [("nouveau", "qualifie")] and appels[0] == relances.STATUTS_A_RELANCER


def test_le_manifeste_du_departement_declare_les_deux_faits_qu_il_consomme_et_leurs_fonctions(dep):
    """Lu depuis le dossier du département lui-même (`lire_manifeste`), pas depuis un autre dépôt de manifestes."""
    assert {"m3.devis_envoye", "m1.retrait_consentement"} <= set(dep.evenements_consomme)
    assert set(dep.evenements_consomme) == set(dep.charger_consommateurs()), "ni fonction orpheline ni fait sans elle"


def test_l_evaluation_des_relances_lit_les_memes_segments_que_la_liste_des_leads(par_nom, monde):
    page = _accepte(_appeler(par_nom, "m2_lister_leads", {"horodatage": MAINTENANT, "segment": "quote_stale"}, ADMIN))
    assert sorted(lead["lead_id"] for lead in page["leads"]) == ["lead-deux", "lead-un"]
    page = _accepte(_appeler(par_nom, "m2_lister_leads", {"horodatage": MAINTENANT, "segment": "dormant_lead"}, ADMIN))
    assert sorted(lead["lead_id"] for lead in page["leads"]) == ["lead-dormant", "lead-nouveau"]
    relances_du_jour = {(r["lead_id"], r["segment"]["segment"]) for r in _accepte(_lister(par_nom))["relances"]}
    assert relances_du_jour == {
        ("lead-un", "quote_stale"), ("lead-deux", "quote_stale"), ("lead-dormant", "dormant_lead"),
        ("lead-nouveau", "dormant_lead")}


def test_un_registre_de_consentements_ne_porte_que_des_maillons_de_ses_deux_types(par_nom, monde):
    _accepte(_consentement("lead-un", "sms"))
    _stop(["lead-dormant"])
    assert {m["type_entree"] for m in _journal_consentements()} == {
        consentements.TYPE_CONSENTEMENT, consentements.TYPE_RETRAIT}
