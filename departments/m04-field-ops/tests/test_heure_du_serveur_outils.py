"""PLAN T4.27-a2 : l'heure d'un report (`m4_signaler_report`) et d'une demande d'écart (`m4_creer_demande_ecart`)
est celle de RÉCEPTION DU SERVEUR pendant un appel d'appareil, comme le pointage (T1.4-d, R12 §4). VRAIS outils,
base SQLite migrée, vraies personnes, appelés comme en production (`executer_atomique`, identité et heures posées
par `opsys.contexte`).

Constat de départ : ces deux gestes inscrivaient l'heure que l'appelant écrit. L'âge d'un retard ou d'un incident
(`m4_lire_retards_incidents`, « bloquée » dès 24 h) en héritait : un appareil à l'heure fausse faussait l'âge.

Ce que ce fichier prouve, avec une heure écrite par l'appelant ET une heure d'appareil volontairement fausses :
  * pendant un appel d'appareil, l'heure du fait est celle du serveur ; l'heure de l'appareil reste À PART (clé sœur
    `horodatage_appareil`, sur le maillon et l'accusé, jamais lue pour un calcul) ; `demande_id` suit l'heure du
    serveur ;
  * l'`horodatage` écrit est encore demandé (contrat v1 gelé : un ancien appel reste valide) mais n'est pas lu : même
    illisible ou énorme, il est ignoré et n'entre jamais dans le registre ; hors appel d'appareil, il fait foi et
    doit être lisible, comme avant ;
  * un appareil qui retarde ou avance de trois jours ne fausse plus l'âge, ni le « bloquée » du relevé ni celui du
    digest ;
  * les faits d'avant gardent leur heure, et le relevé dit, pour chaque ligne, d'où vient son heure ; une anomalie de
    pointage prend l'origine de son pointage ;
  * le contrat des deux outils est celui d'avant (schéma d'entrée intact).
Le rejeu de la même clé : `test_heure_du_serveur_rejeu.py`. La porte d'appareil :
`tests/e2e/test_heure_du_serveur_appareil.py`.
Données fictives (`fictif: true`) : personnes, appareils et identifiants portent « fictif ».
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json

import pytest
from m4_field_ops import cedule, encodage
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
SEL = "sel-t4-27-a2-fictif"
VILLE = "Montreal"
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
REFERENCE = "2025-06-05T09:30:00+00:00"
FIX_LOIN = {"latitude": 46.8139, "longitude": -71.2080}  # à environ 230 km du référentiel : une anomalie
ATTESTATION = {"fictif": True, "appareil_id": "APP-T4-27-A2-FICTIF"}
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")

# Trois heures différentes, pour qu'aucune ne passe pour une autre : celle que l'appelant écrit, celle de l'appareil
# (déréglée), celle de réception du serveur (la seule qui fait foi).
HEURE_ECRITE = "2001-02-03T04:05:06+00:00"
HORLOGE_APPAREIL = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
RECU_LE = dt.datetime(2025, 6, 5, 9, 0, 0, tzinfo=dt.UTC)
VERSION_PREVUE = {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]}
VERSION_DECLAREE = {"duree_minutes": 90, "perimetre": "perimetre declare", "materiaux": ["m2"]}


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def par_nom(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    return {o.nom: o for o in outils()}


@contextlib.contextmanager
def _appareil(identite_appelante, recu_le=None, horloge_appareil=HORLOGE_APPAREIL):
    """Ce que `Capacites` et `serveur_mcp` posent pour un appel d'appareil : l'identité authentifiée ET, quand la
    mutation porte une clé d'idempotence, les deux horloges. Sans `recu_le`, aucune heure de réception."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        if recu_le is not None:
            pile.enter_context(
                contexte.receptionne_de(
                    contexte.HorodatageAppareil(
                        appareil="tel-fictif-t4-27-a2", horodatage_appareil=horloge_appareil, recu_le=recu_le
                    )
                )
            )
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None, recu_le=None, horloge_appareil=HORLOGE_APPAREIL):
    with _appareil(identite_appelante, recu_le, horloge_appareil):
        return executer_atomique(par_nom[nom], arguments)


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _maillons():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire()


def _registre_valide() -> bool:
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).valider_chaine()


def _octets_maillons():
    return json.dumps(_maillons(), sort_keys=True, ensure_ascii=False)


def _maillon_de_report(intervention_id):
    (maillon,) = [
        m
        for m in _maillons()
        if m["type_entree"] == "transition_statut"
        and m["intervention_id"] == intervention_id
        and m["statut"] == "reportee"
    ]
    return maillon


def _maillon_de_demande(demande_id):
    (maillon,) = [m for m in _maillons() if m.get("demande_id") == demande_id and m["type_entree"] == "demande_revue"]
    return maillon


def _contrat(lead_id):
    return {
        "lead_id": lead_id,
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": VILLE,
        "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"},
        "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00",
        "empreinte": "ab" * 32,
    }


def _planifier(par_nom, lead_id, technicien) -> str:
    reponse = _appeler(
        par_nom,
        "m4_planifier_intervention",
        {
            "contrat": _contrat(lead_id),
            "marqueur": _marqueur(lead_id),
            "horodatage": "2025-06-02T06:00:00+00:00",
            "sel": SEL,
            "techniciens_disponibles": [technicien],
            "fenetres_disponibles": [FENETRE],
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


def _report(par_nom, intervention_id, motif="meteo", horodatage=HEURE_ECRITE, identite_appelante=MARC, recu_le=RECU_LE):
    return _appeler(
        par_nom,
        "m4_signaler_report",
        {"intervention_id": intervention_id, "motif": motif, "horodatage": horodatage},
        identite_appelante,
        recu_le,
    )


def _ecart(par_nom, intervention_id, horodatage=HEURE_ECRITE, identite_appelante=MARC, recu_le=RECU_LE):
    return _appeler(
        par_nom,
        "m4_creer_demande_ecart",
        {
            "intervention_id": intervention_id,
            "version_prevue": VERSION_PREVUE,
            "version_declaree": VERSION_DECLAREE,
            "horodatage": horodatage,
        },
        identite_appelante,
        recu_le,
    )


def _lire(par_nom, reference=REFERENCE):
    reponse = _appeler(par_nom, "m4_lire_retards_incidents", {"horodatage_reference": reference}, ADMIN)
    return _resultat(reponse)


# =========================================================================================
# 1. Pendant un appel d'appareil : l'heure du fait est celle du serveur
# =========================================================================================
def test_un_report_d_appareil_est_date_par_le_serveur_jamais_par_l_horloge_de_l_appareil(par_nom):
    intervention = _planifier(par_nom, "L-A", "marc.fictif")

    accuse = _resultat(_report(par_nom, intervention))

    assert accuse["statut"] == "reportee"
    assert accuse["horodatage"] == RECU_LE.isoformat(), "l'heure du serveur fait foi"
    assert accuse["horodatage"] not in (HEURE_ECRITE, HORLOGE_APPAREIL.isoformat())
    assert accuse["horodatage_appareil"] == HORLOGE_APPAREIL.isoformat(), "l'heure de l'appareil reste lisible à côté"
    maillon = _maillon_de_report(intervention)
    assert maillon["horodatage"] == RECU_LE.isoformat()
    assert maillon["horodatage_appareil"] == HORLOGE_APPAREIL.isoformat()
    assert maillon["motif"] == "meteo"
    assert _registre_valide() is True


def test_une_demande_d_ecart_d_appareil_est_datee_par_le_serveur_et_son_identifiant_le_suit(par_nom):
    intervention = _planifier(par_nom, "L-B", "marc.fictif")

    accuse = _resultat(_ecart(par_nom, intervention))

    assert accuse["type_demande"] == "ecart_metier" and accuse["statut_arbitrage"] == "en_attente"
    assert accuse["horodatage"] == RECU_LE.isoformat() and accuse["horodatage_appareil"] == HORLOGE_APPAREIL.isoformat()
    assert accuse["demande_id"] == encodage.empreinte("demande_revue", intervention, RECU_LE.isoformat())
    assert accuse["demande_id"] != encodage.empreinte("demande_revue", intervention, HEURE_ECRITE)
    maillon = _maillon_de_demande(accuse["demande_id"])
    assert maillon["horodatage"] == RECU_LE.isoformat()
    assert maillon["horodatage_appareil"] == HORLOGE_APPAREIL.isoformat()
    assert _registre_valide() is True


def test_la_demande_d_ecart_d_un_chantier_en_route_passe_en_revue_a_l_heure_du_serveur(par_nom):
    """La transition `en_revue` que la demande provoque est datée elle aussi par le serveur, avec le même signe."""
    intervention = _planifier(par_nom, "L-C", "marc.fictif")
    _resultat(
        _appeler(
            par_nom,
            "m4_definir_consentement_gps",
            {
                "technicien_id": "marc.fictif",
                "action": "donne",
                "horodatage": "2025-06-02T06:30:00+00:00",
                "version_politique": "POLITIQUE-geolocalisation-v1-test",
                "preuve": {"fictif": True, "reference": "consentement-t4-27-a2-fictif"},
            },
        )
    )
    _resultat(
        _appeler(
            par_nom,
            "m4_demarrer_route",
            {
                "intervention_id": intervention,
                "technicien_id": "marc.fictif",
                "horodatage": "2025-06-02T07:30:00+00:00",
            },
        )
    )
    accuse = _resultat(_ecart(par_nom, intervention))
    assert accuse["statut"] == "en_revue"
    (transition,) = [
        m for m in _maillons() if m.get("statut") == "en_revue" and m["type_entree"] == "transition_statut"
    ]
    assert transition["horodatage"] == RECU_LE.isoformat()
    assert transition["horodatage_appareil"] == HORLOGE_APPAREIL.isoformat()


def test_l_admin_qui_reporte_par_son_appareil_est_daté_par_le_serveur_lui_aussi(par_nom):
    intervention = _planifier(par_nom, "L-D", "lea.fictif")
    accuse = _resultat(_report(par_nom, intervention, "decision_admin", identite_appelante=ADMIN))
    assert accuse["horodatage"] == RECU_LE.isoformat() and accuse["horodatage_appareil"] == HORLOGE_APPAREIL.isoformat()


# =========================================================================================
# 2. L'horodatage écrit : demandé (contrat v1 gelé), jamais lu pendant un appel d'appareil
# =========================================================================================
# Une chaîne non bornée : elle n'a aucun usage, elle ne doit pas être gardée.
ILLISIBLE = "ILLISIBLE-FICTIF-" + "x" * 50_000


@pytest.mark.parametrize(
    "ecrit", ["", "hier", "2025-06-05T09:00:00", ILLISIBLE], ids=["vide", "mot", "sans-fuseau", "enorme-illisible"]
)
def test_l_horodatage_ecrit_est_ignore_meme_illisible_ou_enorme_et_n_entre_jamais_au_registre(par_nom, ecrit):
    intervention_a = _planifier(par_nom, "L-A", "marc.fictif")
    intervention_b = _planifier(par_nom, "L-B", "marc.fictif")

    accuse_report = _resultat(_report(par_nom, intervention_a, horodatage=ecrit))
    accuse_ecart = _resultat(_ecart(par_nom, intervention_b, horodatage=ecrit))

    assert accuse_report["horodatage"] == RECU_LE.isoformat() == accuse_ecart["horodatage"]
    texte = _octets_maillons()
    assert "ILLISIBLE-FICTIF" not in texte and "hier" not in texte, "la valeur écrite n'est jamais gardée"
    assert len(texte) < 20_000, "aucune chaîne non bornée n'a fini dans le registre immuable"


@pytest.mark.parametrize(
    "ecrit", ["", "hier", "2025-06-05T09:00:00", ILLISIBLE], ids=["vide", "mot", "sans-fuseau", "enorme-illisible"]
)
def test_hors_appel_d_appareil_l_horodatage_ecrit_doit_encore_etre_lisible_comme_avant(par_nom, ecrit):
    intervention_a = _planifier(par_nom, "L-A", "marc.fictif")
    intervention_b = _planifier(par_nom, "L-B", "marc.fictif")
    avant = _octets_maillons()

    assert _code_refus(_report(par_nom, intervention_a, horodatage=ecrit, recu_le=None)) == "REJ-HORODATAGE-INVALIDE"
    assert _code_refus(_ecart(par_nom, intervention_b, horodatage=ecrit, recu_le=None)) == "REJ-HORODATAGE-INVALIDE"
    assert _code_refus(_report(par_nom, intervention_a, horodatage=ecrit, identite_appelante=None, recu_le=None)) == (
        "REJ-HORODATAGE-INVALIDE"
    )
    assert _octets_maillons() == avant, "rien n'est écrit"


def test_le_contrat_des_deux_outils_est_celui_d_avant_un_ancien_appel_reste_valide(par_nom):
    """Contrat v1 gelé : mêmes clés, même obligation. `horodatage` reste demandé (l'app et les agents l'envoient)."""
    report = par_nom["m4_signaler_report"].parametres
    assert report["required"] == ["intervention_id", "motif", "horodatage"]
    assert set(report["properties"]) == {"intervention_id", "motif", "horodatage"}
    assert report["properties"]["horodatage"] == {"type": "string"} and report["additionalProperties"] is False
    ecart = par_nom["m4_creer_demande_ecart"].parametres
    assert ecart["required"] == ["intervention_id", "version_prevue", "version_declaree", "horodatage"]
    assert set(ecart["properties"]) == {"intervention_id", "version_prevue", "version_declaree", "horodatage"}
    assert ecart["properties"]["horodatage"] == {"type": "string"} and ecart["additionalProperties"] is False
    # aucune clé nouvelle ne s'accepte en entrée : l'heure de l'appareil vient de `_meta`, jamais des arguments
    intervention = _planifier(par_nom, "L-A", "marc.fictif")
    avec_cle = _appeler(
        par_nom,
        "m4_signaler_report",
        {
            "intervention_id": intervention,
            "motif": "meteo",
            "horodatage": HEURE_ECRITE,
            "horodatage_appareil": HEURE_ECRITE,
        },
        MARC,
        RECU_LE,
    )
    assert avec_cle["ok"] is False and avec_cle["erreur"] == "arguments_invalides"
    assert _maillons()[-1]["type_entree"] == "assignation_technicien", "un refus du socle n'écrit rien"


def test_la_description_des_deux_outils_dit_la_regle(par_nom):
    for nom in ("m4_signaler_report", "m4_creer_demande_ecart"):
        description = par_nom[nom].description
        assert "réception du serveur" in description and "`horodatage_appareil`" in description, nom
        assert "même clé" in description and "agent, console" in description, nom
        assert len(description) <= 1024, nom


# =========================================================================================
# 3. Hors appel d'appareil : comme avant, l'heure écrite fait foi (et le fait le dit)
# =========================================================================================
@pytest.mark.parametrize(
    "identite_appelante", [None, MARC], ids=["agent-ou-console", "identite-sans-heure-de-reception"]
)
def test_hors_appel_d_appareil_l_heure_ecrite_fait_foi_et_aucune_cle_soeur_n_apparait(par_nom, identite_appelante):
    a = _planifier(par_nom, "L-A", "marc.fictif")
    b = _planifier(par_nom, "L-B", "marc.fictif")

    accuse_report = _resultat(
        _report(par_nom, a, horodatage="2025-06-03T08:00:00+00:00", identite_appelante=identite_appelante, recu_le=None)
    )
    accuse_ecart = _resultat(
        _ecart(par_nom, b, horodatage="2025-06-03T09:00:00+00:00", identite_appelante=identite_appelante, recu_le=None)
    )

    assert accuse_report["horodatage"] == "2025-06-03T08:00:00+00:00" and "horodatage_appareil" not in accuse_report
    assert "horodatage" not in accuse_ecart and "horodatage_appareil" not in accuse_ecart, "l'accusé d'avant"
    assert accuse_ecart["demande_id"] == encodage.empreinte("demande_revue", b, "2025-06-03T09:00:00+00:00")
    assert "horodatage_appareil" not in _maillon_de_report(a)
    assert "horodatage_appareil" not in _maillon_de_demande(accuse_ecart["demande_id"])
    releve = _lire(par_nom)
    assert [ligne["origine_heure"] for ligne in releve["reports"]["liste"]] == ["appelant"]
    assert [ligne["origine_heure"] for ligne in releve["incidents"]["liste"]] == ["appelant"]
    assert releve["reports"]["liste"][0]["depuis"] == "2025-06-03T08:00:00+00:00"


def test_un_refus_d_appareil_n_ecrit_rien_et_ne_change_pas_de_forme(par_nom):
    """Le contrôle d'accès passe avant tout : l'employé ne reporte pas l'intervention d'un collègue."""
    de_lea = _planifier(par_nom, "L-LEA", "lea.fictif")
    avant = _octets_maillons()
    assert _code_refus(_report(par_nom, de_lea)) == "REJ-INTERVENTION-NON-ASSIGNEE"
    assert _code_refus(_ecart(par_nom, de_lea)) == "REJ-INTERVENTION-NON-ASSIGNEE"
    assert _octets_maillons() == avant


# =========================================================================================
# 4. Le relevé : un appareil qui retarde ou avance ne fausse plus l'âge
# =========================================================================================
@pytest.mark.parametrize("decalage_jours", [-3, 3], ids=["retarde-de-trois-jours", "avance-de-trois-jours"])
def test_un_appareil_qui_retarde_ou_avance_de_trois_jours_ne_fausse_plus_l_age(par_nom, decalage_jours):
    """Avant T4.27-a2 : 3 jours de retard donnaient 74 h (« bloquée » à tort), 3 jours d'avance donnaient un âge nul
    (`None`). L'âge se compte maintenant depuis l'heure de réception du serveur : 2 h."""
    recu_le = dt.datetime(2025, 6, 5, 7, 30, 0, tzinfo=dt.UTC)  # deux heures avant la référence (09:30)
    horloge_fausse = recu_le + dt.timedelta(days=decalage_jours)
    a = _planifier(par_nom, "L-A", "marc.fictif")
    b = _planifier(par_nom, "L-B", "marc.fictif")
    _resultat(
        _appeler(
            par_nom,
            "m4_signaler_report",
            {"intervention_id": a, "motif": "client_absent", "horodatage": horloge_fausse.isoformat()},
            MARC,
            recu_le,
            horloge_appareil=horloge_fausse,
        )
    )
    _resultat(
        _appeler(
            par_nom,
            "m4_creer_demande_ecart",
            {
                "intervention_id": b,
                "version_prevue": VERSION_PREVUE,
                "version_declaree": VERSION_DECLAREE,
                "horodatage": horloge_fausse.isoformat(),
            },
            MARC,
            recu_le,
            horloge_appareil=horloge_fausse,
        )
    )

    releve = _lire(par_nom)

    (report,) = releve["reports"]["liste"]
    (incident,) = releve["incidents"]["liste"]
    assert (report["depuis"], report["heures_ecoulees"], report["origine_heure"]) == (recu_le.isoformat(), 2, "serveur")
    assert (incident["depuis"], incident["heures_ecoulees"], incident["bloquee"]) == (recu_le.isoformat(), 2, False)
    assert releve["incidents"]["bloques"] == 0
    assert horloge_fausse.isoformat() not in json.dumps(releve), "l'heure de l'appareil ne sort pas du relevé"


def test_le_digest_suit_lui_aussi_l_heure_du_serveur_pour_les_demandes_bloquees(par_nom):
    """Le digest (forme gelée) compte les demandes ouvertes depuis 24 h ou plus depuis l'heure du fait : le serveur."""
    intervention = _planifier(par_nom, "L-A", "marc.fictif")
    recu_le = dt.datetime(2025, 6, 4, 12, 0, 0, tzinfo=dt.UTC)
    demande = _resultat(_ecart(par_nom, intervention, recu_le=recu_le))["demande_id"]
    digest = _resultat(
        _appeler(
            par_nom,
            "m4_produire_digest",
            {"date_cible": "2025-06-05", "horodatage_reference": "2025-06-05T12:00:00+00:00"},
            ADMIN,
        )
    )
    assert [(ligne["demande_id"], ligne["heures_ecoulees"]) for ligne in digest["interventions_bloquees_en_revue"]] == [
        (demande, 24)
    ]
    trop_tot = _resultat(
        _appeler(
            par_nom,
            "m4_produire_digest",
            {"date_cible": "2025-06-05", "horodatage_reference": "2025-06-05T11:59:59+00:00"},
            ADMIN,
        )
    )
    assert trop_tot["interventions_bloquees_en_revue"] == []


# =========================================================================================
# 5. Les faits d'avant gardent leur heure, et le relevé dit d'où vient chaque heure
# =========================================================================================
def test_les_faits_d_avant_gardent_leur_heure_et_le_releve_dit_d_ou_vient_chaque_heure(par_nom):
    """Trois faits d'AVANT (écrits comme avant, l'heure de l'appelant) puis trois faits d'appareil : la chaîne reste
    valide, chaque fait garde son heure, et chaque ligne du relevé dit d'où vient la sienne."""
    anciens = [_planifier(par_nom, f"L-ANCIEN-{n}", "marc.fictif") for n in range(2)]
    recents = [_planifier(par_nom, f"L-RECENT-{n}", "marc.fictif") for n in range(2)]
    _resultat(
        _report(par_nom, anciens[0], horodatage="2025-06-03T08:00:00+00:00", identite_appelante=None, recu_le=None)
    )
    ancienne_demande = _resultat(
        _ecart(par_nom, anciens[1], horodatage="2025-06-03T09:00:00+00:00", identite_appelante=None, recu_le=None)
    )["demande_id"]
    avant = [m for m in _maillons() if m["horodatage"] in ("2025-06-03T08:00:00+00:00", "2025-06-03T09:00:00+00:00")]
    assert len(avant) == 2
    _resultat(_report(par_nom, recents[0], recu_le=dt.datetime(2025, 6, 4, 10, 0, tzinfo=dt.UTC)))
    recente_demande = _resultat(_ecart(par_nom, recents[1], recu_le=dt.datetime(2025, 6, 4, 11, 0, tzinfo=dt.UTC)))[
        "demande_id"
    ]

    assert _registre_valide() is True
    for maillon in avant:  # les faits d'avant sont intacts, octet pour octet
        assert maillon in _maillons()
    releve = _lire(par_nom)
    lignes = releve["reports"]["liste"]
    reports = [(ligne["intervention_id"], ligne["depuis"], ligne["origine_heure"]) for ligne in lignes]
    assert reports == [
        (anciens[0], "2025-06-03T08:00:00+00:00", "appelant"),
        (recents[0], "2025-06-04T10:00:00+00:00", "serveur"),
    ]
    assert {
        ligne["demande_id"]: (ligne["depuis"], ligne["origine_heure"]) for ligne in releve["incidents"]["liste"]
    } == {
        ancienne_demande: ("2025-06-03T09:00:00+00:00", "appelant"),
        recente_demande: ("2025-06-04T11:00:00+00:00", "serveur"),
    }
    assert [ligne["heures_ecoulees"] for ligne in releve["reports"]["liste"]] == [49, 23]


# -- les anomalies de pointage ---------------------------------------------------------------
def _referentiel():
    return {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _en_route(par_nom, lead_id, technicien):
    intervention = _planifier(par_nom, lead_id, technicien)
    _resultat(
        _appeler(
            par_nom,
            "m4_definir_consentement_gps",
            {
                "technicien_id": technicien,
                "action": "donne",
                "horodatage": "2025-06-02T06:30:00+00:00",
                "version_politique": "POLITIQUE-geolocalisation-v1-test",
                "preuve": {"fictif": True, "reference": "consentement-t4-27-a2-fictif"},
            },
        )
    )
    _resultat(
        _appeler(
            par_nom,
            "m4_demarrer_route",
            {"intervention_id": intervention, "technicien_id": technicien, "horodatage": "2025-06-02T07:30:00+00:00"},
        )
    )
    return intervention


def _pointer_loin(par_nom, intervention, technicien, horodatage, identite_appelante=None, recu_le=None):
    return _appeler(
        par_nom,
        "m4_pointer",
        {
            "intervention_id": intervention,
            "technicien_id": technicien,
            "action": "arrivee",
            "horodatage": horodatage,
            "fix_gps": FIX_LOIN,
            "attestation": ATTESTATION,
            "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(),
            "ville": VILLE,
            "sel": SEL,
        },
        identite_appelante,
        recu_le,
    )


def test_l_anomalie_d_un_pointage_d_appareil_dit_serveur_celle_d_un_agent_dit_appelant(par_nom):
    """Le pointage garde l'heure du serveur depuis T1.4-d : l'anomalie qu'il ouvre est datée par le serveur, et le
    relevé le dit, sans qu'aucun fait d'avant n'ait besoin d'être réécrit. Celle d'un agent est `appelant`."""
    par_appareil = _en_route(par_nom, "L-POINTAGE-APPAREIL", "marc.fictif")
    par_agent = _en_route(par_nom, "L-POINTAGE-AGENT", "lea.fictif")
    recu_le = dt.datetime(2025, 6, 2, 9, 0, tzinfo=dt.UTC)
    accuse_appareil = _resultat(_pointer_loin(par_nom, par_appareil, "marc.fictif", HEURE_ECRITE, MARC, recu_le))
    accuse_agent = _resultat(_pointer_loin(par_nom, par_agent, "lea.fictif", "2025-06-02T10:00:00+00:00"))
    assert accuse_appareil["statut"] == "en_revue" == accuse_agent["statut"]

    par_demande = {ligne["demande_id"]: ligne for ligne in _lire(par_nom)["incidents"]["liste"]}
    assert par_demande[accuse_appareil["demande_id"]]["origine_heure"] == "serveur"
    assert par_demande[accuse_appareil["demande_id"]]["depuis"] == recu_le.isoformat()
    assert par_demande[accuse_agent["demande_id"]]["origine_heure"] == "appelant"
    assert par_demande[accuse_agent["demande_id"]]["depuis"] == "2025-06-02T10:00:00+00:00"
    assert {ligne["type_demande"] for ligne in par_demande.values()} == {"anomalie_pointage"}
