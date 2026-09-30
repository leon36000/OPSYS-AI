"""PLAN T4.27-a2 : E2E « l'heure d'un report et d'une demande d'écart est celle du serveur » par la porte d'appareil.

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, personnes et appareils créés par les commandes réelles du socle). L'heure de réception du serveur
(`recu_le`) vient de l'horloge de test du moteur, que chaque test règle à la main.

Constat de départ : `m4_signaler_report` et `m4_creer_demande_ecart` inscrivaient l'heure que l'appelant écrit ; l'âge
d'un retard ou d'un incident (`m4_lire_retards_incidents`, « bloquée » dès 24 h) en héritait, et un appareil à l'heure
fausse faussait l'âge. Le pointage, le départ et la complétion gardaient déjà l'heure du serveur (T1.4-d, T1.5-c).

1. Un employé dont le téléphone retarde de trois jours (et un autre qui avance de trois jours) signale un report et un
   écart : l'heure du fait est celle du serveur, l'heure du téléphone reste à part dans la réponse ; l'admin lit un âge
   de deux heures, jamais 74 h « bloquées » ni un âge absent.
2. Un renvoi de la même clé, six heures plus tard, avec une autre horloge d'appareil, rend la MÊME réponse (heure de la
   première réception), marquée rejouée, sans rien écrire ; l'âge lu part de la première heure. Une autre clé pour le
   même report est refusée et ne change pas son heure.
3. Un fait d'avant (heure écrite par un agent) garde son heure ; le relevé lu par l'admin dit `appelant` pour lui,
   `serveur` pour les faits d'appareil. L'anomalie d'un pointage d'appareil se lit `serveur` aussi.

Ce que ces tests ne prouvent PAS : l'écran de l'app (Jest, `mobile/`), le core réel (poignée de main, jeton d'appareil).
Données fictives (AGENTS.md).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from m4_field_ops import cedule
from m4_field_ops import registre as registre_m4
from sqlalchemy import select

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
M4 = "m04-field-ops"
SEL = "sel-t4-27-a2-e2e-fictif"
FENETRE = {"debut": "2026-09-29T00:00:00+00:00", "fin": "2026-09-30T00:00:00+00:00"}
T0 = dt.datetime.fromisoformat("2026-09-29T07:00:00-04:00")  # l'heure de RÉCEPTION du serveur (11:00 UTC)
REFERENCE = "2026-09-29T09:00:00-04:00"  # l'instant présent selon l'appareil de l'admin : deux heures après T0
VERSION_PREVUE = {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]}
VERSION_DECLAREE = {"duree_minutes": 90, "perimetre": "PERIMETRE-LIBRE-DU-TERRAIN", "materiaux": ["m2"]}
FIX_LOIN = {"latitude": 46.8139, "longitude": -71.2080}  # à environ 230 km du référentiel : une anomalie
TROIS_JOURS = dt.timedelta(days=3)


# -- l'amont : interventions inscrites directement (aucune n'est un geste de l'app) ------------------------------
def _outils_m4(moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements[M4].charger_outils()}


def _planifier(moteur, lead_id: str, technicien: str) -> str:
    reponse = executer_atomique(
        _outils_m4(moteur)["m4_planifier_intervention"],
        {
            "contrat": {
                "lead_id": lead_id,
                "conversation_id": f"conv-{lead_id}",
                "type_travaux": "renovation_totale",
                "ville": "Montreal",
                "canal": "telephone",
                "contact": {"nom": "Client fictif", "telephone": "0102030405"},
                "urgence_declaree": False,
            },
            "marqueur": {
                "readiness_ok": True,
                "lead_id": lead_id,
                "hash_tete_registre": None,
                "horodatage": "2026-09-01T12:00:00-04:00",
                "empreinte": "ab" * 32,
            },
            "horodatage": "2026-09-02T06:00:00-04:00",
            "sel": SEL,
            "techniciens_disponibles": [technicien],
            "fenetres_disponibles": [FENETRE],
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


def _maillons_m4() -> list[dict[str, Any]]:
    with stockage.transaction():
        return [dict(m) for m in stockage.maillons(M4, "principal")]


def _mutations(cle: str) -> list[tuple[str, str, str]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(MUTATIONS_APPLIQUEES.c.outil, MUTATIONS_APPLIQUEES.c.recu_le, MUTATIONS_APPLIQUEES.c.statut).where(
                MUTATIONS_APPLIQUEES.c.cle_idempotence == cle
            )
        ).all()
    return [tuple(ligne) for ligne in lignes]


# -- les gestes de l'app ----------------------------------------------------------------------------------------
def _signaler(porte, intervention: str, cle: str, horloge_appareil: dt.datetime, motif: str = "client_absent"):
    """Ce que l'app envoie : `horodatage` (heure de l'appareil, demandée par le contrat v1) ET `_meta` de la porte."""
    return porte.appeler(
        "m4_signaler_report",
        {"intervention_id": intervention, "motif": motif, "horodatage": horloge_appareil.isoformat()},
        cle=cle,
        horodatage_appareil=horloge_appareil.isoformat(),
    )


def _declarer(porte, intervention: str, cle: str, horloge_appareil: dt.datetime):
    return porte.appeler(
        "m4_creer_demande_ecart",
        {
            "intervention_id": intervention,
            "version_prevue": VERSION_PREVUE,
            "version_declaree": VERSION_DECLAREE,
            "horodatage": horloge_appareil.isoformat(),
        },
        cle=cle,
        horodatage_appareil=horloge_appareil.isoformat(),
    )


def _lire(admin, reference: str = REFERENCE):
    reponse = admin.appeler("m4_lire_retards_incidents", {"horodatage_reference": reference})
    assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
    assert reponse.mesure.tronque is False
    return reponse.resultat


@pytest.fixture
def deux_employes(moteur, equipe, monkeypatch):
    """Étienne (déjà appairé par `equipe`) et un second employé, chacun avec son appareil."""
    moteur.creer_personne("employe.bis", "Employé bis (fictif)", ["employee"], monkeypatch)
    return {"etienne": equipe["employe"], "bis": moteur.appairer("employe.bis", "employee")}


# ========================================================================================================
# 1. Un appareil à l'heure fausse ne fausse plus l'âge
# ========================================================================================================
@SQLITE_SEULEMENT
def test_un_telephone_qui_retarde_ou_avance_de_trois_jours_ne_fausse_plus_l_age_lu_par_l_admin(
    moteur, equipe, deux_employes
):
    admin = equipe["admin"]
    a_retard = _planifier(moteur, "L-RETARD", "etienne")
    b_retard = _planifier(moteur, "L-RETARD-B", "etienne")
    a_avance = _planifier(moteur, "L-AVANCE", "employe.bis")
    moteur.horloge.maintenant = T0
    en_retard, en_avance = T0 - TROIS_JOURS, T0 + TROIS_JOURS

    # 1. le geste de l'app : `horodatage` et `_meta` portent l'heure (fausse) du téléphone ; le serveur date le fait
    report = _signaler(deux_employes["etienne"], a_retard, "cle-report-retard", en_retard)
    ecart = _declarer(deux_employes["etienne"], b_retard, "cle-ecart-retard", en_retard)
    avance = _signaler(deux_employes["bis"], a_avance, "cle-report-avance", en_avance, motif="meteo")
    for reponse in (report, ecart, avance):
        assert reponse.statut == 200 and reponse.metier["accepte"] is True, reponse.corps
        assert reponse.enveloppe["rejoue"] is False
    assert report.resultat["horodatage"] == "2026-09-29T11:00:00+00:00", "l'heure du serveur, en UTC"
    assert report.resultat["horodatage_appareil"] == en_retard.isoformat(), "celle du téléphone reste à part"
    assert ecart.resultat["horodatage"] == "2026-09-29T11:00:00+00:00"
    assert ecart.resultat["horodatage_appareil"] == en_retard.isoformat()
    assert avance.resultat["horodatage"] == "2026-09-29T11:00:00+00:00"
    assert avance.resultat["horodatage_appareil"] == en_avance.isoformat()

    # 2. l'admin lit : deux heures pour chaque fait, jamais 74 h « bloquées » ni un âge absent
    releve = _lire(admin)
    lignes = {ligne["intervention_id"]: ligne for ligne in releve["reports"]["liste"]}
    assert set(lignes) == {a_retard, a_avance}
    for ligne in lignes.values():
        assert ligne["depuis"] == "2026-09-29T11:00:00+00:00" and ligne["heures_ecoulees"] == 2
        assert ligne["origine_heure"] == "serveur"
    (incident,) = releve["incidents"]["liste"]
    assert incident["intervention_id"] == b_retard and incident["depuis"] == "2026-09-29T11:00:00+00:00"
    assert (incident["heures_ecoulees"], incident["bloquee"], incident["origine_heure"]) == (2, False, "serveur")
    assert releve["incidents"]["bloques"] == 0
    texte = json.dumps(releve, ensure_ascii=False)
    for heure_du_telephone in (en_retard.isoformat(), en_avance.isoformat(), "2026-09-26", "2026-10-02"):
        assert heure_du_telephone not in texte, "l'heure du téléphone ne sort pas du relevé"
    for interdit in ("PERIMETRE-LIBRE-DU-TERRAIN", "materiaux", "Client fictif", "0102030405", "etienne"):
        assert interdit not in texte, interdit


@SQLITE_SEULEMENT
def test_le_registre_garde_l_heure_du_serveur_et_celle_de_l_appareil_a_part_et_reste_valide(
    moteur, equipe, deux_employes
):
    intervention = _planifier(moteur, "L-REGISTRE", "etienne")
    moteur.horloge.maintenant = T0
    _signaler(deux_employes["etienne"], intervention, "cle-report", T0 - TROIS_JOURS)
    (maillon,) = [m for m in _maillons_m4() if m.get("statut") == "reportee"]
    assert maillon["horodatage"] == "2026-09-29T11:00:00+00:00"
    assert maillon["horodatage_appareil"] == (T0 - TROIS_JOURS).isoformat()
    assert maillon["motif"] == "client_absent"
    with stockage.transaction():
        assert registre_m4.Registre(stockage.maillons(M4, "principal")).valider_chaine() is True


# ========================================================================================================
# 2. Le rejeu de la même clé rend la même heure
# ========================================================================================================
@SQLITE_SEULEMENT
def test_un_renvoi_de_la_meme_cle_par_la_porte_rend_la_meme_heure_et_n_ecrit_rien(moteur, equipe, deux_employes):
    admin, etienne = equipe["admin"], deux_employes["etienne"]
    a, b = _planifier(moteur, "L-REJEU-A", "etienne"), _planifier(moteur, "L-REJEU-B", "etienne")
    moteur.horloge.maintenant = T0
    premier_report = _signaler(etienne, a, "cle-report", T0 - TROIS_JOURS)
    premier_ecart = _declarer(etienne, b, "cle-ecart", T0 - TROIS_JOURS)
    assert premier_report.metier["accepte"] is True and premier_ecart.metier["accepte"] is True
    avant, maillons_avant = moteur.empreinte_etat(), json.dumps(_maillons_m4(), sort_keys=True)

    # le réseau a coupé pendant la réponse : six heures plus tard, l'app renvoie la MÊME mutation (même clé, mêmes
    # arguments), avec l'horloge qu'a maintenant son téléphone
    moteur.horloge.maintenant = T0 + dt.timedelta(hours=6)
    tard = T0 - TROIS_JOURS + dt.timedelta(hours=6)
    renvoi_report = etienne.appeler(
        "m4_signaler_report",
        {"intervention_id": a, "motif": "client_absent", "horodatage": (T0 - TROIS_JOURS).isoformat()},
        cle="cle-report",
        horodatage_appareil=tard.isoformat(),
    )
    renvoi_ecart = etienne.appeler(
        "m4_creer_demande_ecart",
        {
            "intervention_id": b,
            "version_prevue": VERSION_PREVUE,
            "version_declaree": VERSION_DECLAREE,
            "horodatage": (T0 - TROIS_JOURS).isoformat(),
        },
        cle="cle-ecart",
        horodatage_appareil=tard.isoformat(),
    )

    for premier, renvoi in ((premier_report, renvoi_report), (premier_ecart, renvoi_ecart)):
        assert renvoi.statut == 200 and renvoi.enveloppe["rejoue"] is True and renvoi.mesure.rejoue is True
        assert renvoi.enveloppe["resultat"] == premier.enveloppe["resultat"], "exactement la réponse enregistrée"
        assert renvoi.resultat["horodatage"] == "2026-09-29T11:00:00+00:00", "jamais une nouvelle heure"
        assert renvoi.resultat["horodatage_appareil"] == (T0 - TROIS_JOURS).isoformat(), "celle du premier envoi"
    assert moteur.empreinte_etat() == avant, "aucun double effet : ni maillon, ni événement, ni approbation, ni journal"
    assert json.dumps(_maillons_m4(), sort_keys=True) == maillons_avant
    assert _mutations("cle-report") == [("m4_signaler_report", "2026-09-29T11:00:00+00:00", "ok")]
    assert _mutations("cle-ecart") == [("m4_creer_demande_ecart", "2026-09-29T11:00:00+00:00", "ok")]

    # l'admin lit six heures après : l'âge part de la PREMIÈRE réception
    relu = _lire(admin, "2026-09-29T13:00:00-04:00")
    (report,) = relu["reports"]["liste"]
    (incident,) = relu["incidents"]["liste"]
    assert (report["depuis"], report["heures_ecoulees"]) == ("2026-09-29T11:00:00+00:00", 6)
    assert (incident["depuis"], incident["heures_ecoulees"]) == ("2026-09-29T11:00:00+00:00", 6)
    assert relu["reports"]["total"] == 1 and relu["incidents"]["total"] == 1


@SQLITE_SEULEMENT
def test_une_autre_cle_pour_le_meme_report_est_refusee_et_la_meme_cle_avec_d_autres_arguments_est_un_conflit(
    moteur, equipe, deux_employes
):
    etienne = deux_employes["etienne"]
    a = _planifier(moteur, "L-CLES", "etienne")
    moteur.horloge.maintenant = T0
    assert _signaler(etienne, a, "cle-1", T0).metier["accepte"] is True
    registres_avant = moteur.empreinte_etat()["registres"]
    moteur.horloge.maintenant = T0 + dt.timedelta(hours=6)

    autre_cle = _signaler(etienne, a, "cle-2", T0 + dt.timedelta(hours=6))
    assert autre_cle.statut == 200 and autre_cle.metier["accepte"] is False
    assert autre_cle.metier["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
    conflit = _signaler(etienne, a, "cle-1", T0, motif="meteo")
    assert conflit.statut == 200 and conflit.enveloppe["ok"] is False
    assert conflit.enveloppe["erreur"] == "mutation_conflit"

    assert moteur.empreinte_etat()["registres"] == registres_avant, "ni l'un ni l'autre n'écrit au registre de M4"
    (maillon,) = [m for m in _maillons_m4() if m.get("statut") == "reportee"]
    assert maillon["horodatage"] == "2026-09-29T11:00:00+00:00", "l'heure du premier report ne bouge pas"


# ========================================================================================================
# 3. Les faits d'avant gardent leur heure ; le relevé dit d'où vient chaque heure
# ========================================================================================================
def _referentiel() -> dict[str, Any]:
    return {cedule.tokeniser_ville(SEL, "Montreal"): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


@SQLITE_SEULEMENT
def test_les_faits_d_avant_gardent_leur_heure_et_le_releve_dit_d_ou_vient_chaque_heure(
    moteur, equipe, deux_employes
):
    admin, etienne = equipe["admin"], deux_employes["etienne"]
    ancien_report = _planifier(moteur, "L-ANCIEN-REPORT", "etienne")
    ancien_ecart = _planifier(moteur, "L-ANCIEN-ECART", "etienne")
    nouveau_report = _planifier(moteur, "L-NOUVEAU-REPORT", "etienne")
    nouvelle_anomalie = _planifier(moteur, "L-NOUVELLE-ANOMALIE", "etienne")

    # 1. deux faits d'AVANT : écrits comme avant par un agent (l'heure de l'appelant), sans porte d'appareil
    outils = _outils_m4(moteur)
    report_d_avant = executer_atomique(
        outils["m4_signaler_report"],
        {"intervention_id": ancien_report, "motif": "meteo", "horodatage": "2026-09-27T08:00:00-04:00"},
    )
    ecart_d_avant = executer_atomique(
        outils["m4_creer_demande_ecart"],
        {
            "intervention_id": ancien_ecart,
            "version_prevue": VERSION_PREVUE,
            "version_declaree": VERSION_DECLAREE,
            "horodatage": "2026-09-27T09:00:00-04:00",
        },
    )
    assert report_d_avant["resultat"]["accepte"] is True and ecart_d_avant["resultat"]["accepte"] is True
    demande_d_avant = ecart_d_avant["resultat"]["resultat"]["demande_id"]
    assert "horodatage_appareil" not in report_d_avant["resultat"]["resultat"]
    heures_d_avant = ("2026-09-27T08:00:00-04:00", "2026-09-27T09:00:00-04:00")
    faits_d_avant = [m for m in _maillons_m4() if m["horodatage"] in heures_d_avant]
    assert len(faits_d_avant) == 2

    # 2. des faits d'appareil, par la porte : un report, puis une anomalie de pointage (fix à 230 km)
    moteur.horloge.maintenant = T0
    assert _signaler(etienne, nouveau_report, "cle-nouveau-report", T0 - TROIS_JOURS).metier["accepte"] is True
    consentement = etienne.appeler(
        "m4_definir_consentement_gps",
        {
            "technicien_id": "etienne",
            "action": "donne",
            "horodatage": T0.isoformat(),
            "version_politique": "POLITIQUE-geolocalisation-v1-test",
            "preuve": {"fictif": True, "reference": "consentement-t4-27-a2-e2e-fictif"},
        },
        cle="cle-consentement",
        horodatage_appareil=T0.isoformat(),
    )
    assert consentement.metier["accepte"] is True, consentement.corps
    route = etienne.appeler(
        "m4_demarrer_route",
        {"intervention_id": nouvelle_anomalie, "technicien_id": "etienne", "horodatage": T0.isoformat()},
        cle="cle-route",
        horodatage_appareil=T0.isoformat(),
    )
    assert route.metier["accepte"] is True, route.corps
    moteur.horloge.maintenant = T0 + dt.timedelta(minutes=30)
    pointage = etienne.appeler(
        "m4_pointer",
        {
            "intervention_id": nouvelle_anomalie,
            "technicien_id": "etienne",
            "action": "arrivee",
            "horodatage": T0.isoformat(),
            "fix_gps": FIX_LOIN,
            "attestation": {"fictif": True, "appareil_id": "APP-T4-27-A2-E2E-FICTIF"},
            "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(),
            "ville": "Montreal",
            "sel": SEL,
        },
        cle="cle-pointage",
        horodatage_appareil=T0.isoformat(),
    )
    assert pointage.metier["accepte"] is True, pointage.corps
    assert pointage.resultat["statut"] == "en_revue" and pointage.resultat["demande_id"] is not None

    # 3. l'admin lit : les faits d'avant gardent leur heure, `appelant` ; les faits d'appareil sont `serveur`
    releve = _lire(admin)
    reports = {ligne["intervention_id"]: ligne for ligne in releve["reports"]["liste"]}
    assert reports[ancien_report]["depuis"] == "2026-09-27T08:00:00-04:00", "un fait d'avant garde son heure"
    assert reports[ancien_report]["origine_heure"] == "appelant" and reports[ancien_report]["heures_ecoulees"] == 49
    assert reports[nouveau_report]["depuis"] == "2026-09-29T11:00:00+00:00"
    assert reports[nouveau_report]["origine_heure"] == "serveur" and reports[nouveau_report]["heures_ecoulees"] == 2
    incidents = {ligne["demande_id"]: ligne for ligne in releve["incidents"]["liste"]}
    assert incidents[demande_d_avant]["depuis"] == "2026-09-27T09:00:00-04:00"
    assert incidents[demande_d_avant]["origine_heure"] == "appelant"
    anomalie = incidents[pointage.resultat["demande_id"]]
    assert anomalie["type_demande"] == "anomalie_pointage" and anomalie["origine_heure"] == "serveur"
    assert anomalie["depuis"] == "2026-09-29T11:30:00+00:00" and anomalie["heures_ecoulees"] == 1
    # l'ordre suit les instants : le fait d'avant, plus ancien, passe le premier
    assert [ligne["intervention_id"] for ligne in releve["reports"]["liste"]] == [ancien_report, nouveau_report]

    # 4. la chaîne reste valide et les faits d'avant sont intacts, octet pour octet
    with stockage.transaction():
        assert registre_m4.Registre(stockage.maillons(M4, "principal")).valider_chaine() is True
    for fait in faits_d_avant:
        assert fait in _maillons_m4()
    assert moteur.bilan()["troncatures"] == []
