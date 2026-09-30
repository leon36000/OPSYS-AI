"""PLAN T4.27-a : E2E « les lectures pures du propriétaire » (M4) par la porte d'appareil et par le VRAI bus
(DEFINITION-PRODUIT §9.5 : le propriétaire lit son dispatch, sa météo et ce qui va mal sur son téléphone).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, personnes et appareils créés par les commandes réelles du socle). Aucune requête météo ne sort : la
prévision est saisie par l'admin (sa source et son heure d'émission sont citées).

Trois lectures, toutes en lecture pure (T0) : aucun maillon, aucun événement, aucune approbation, aucune entrée de
journal ne s'écrit.

1. `m4_lire_meteo_intervention` : la météo du créneau d'UNE intervention, SANS `plan_id`. Le créneau est celui du
   dernier plan APPLIQUÉ qui place l'intervention ; l'évaluation est celle de T4.13 (`m4_verifier_meteo_creneau`), pas
   une seconde. `inconnu` (jamais `ok`) sans créneau, sans date, sans prévision, ou quand l'intervention est reportée ;
   aucun report ni cédule n'est proposé ; l'employé et le vendeur reçoivent 403.
2. `m4_lire_retards_incidents` : ce que M4 a déjà enregistré (reports en cours, demandes d'écart ouvertes, avec leur
   âge) ; le retard sur la cédule n'est pas mesurable (M4 ne tient aucun calendrier) et la réponse le dit ; 403 pour
   l'employé et le vendeur.
3. `m4_lister_interventions` par pages (clés sœurs `curseur` et `taille_page`, contrat v1 gelé) : l'admin lit TOUTES les
   interventions, une seule fois, chaque page sous la borne du socle, alors que la liste v1 entière est tronquée ;
   l'employé ne voit que SES interventions, page par page.

Ce que ces tests ne prouvent PAS : l'écran de l'app (Jest, `mobile/`), le core réel (poignée de main, jeton d'appareil).
Données fictives (AGENTS.md).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml
from harnais_e2e import Moteur, iso
from sqlalchemy import select

from opsys import cli, evenements, openclaw, stockage, taxonomie
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
M4, M6 = "m04-field-ops", "m06-material-control"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`
_FIXTURES_M4 = Path(__file__).resolve().parents[2] / "departments" / "m04-field-ops" / "tests" / "fixtures"
EQUIPES = json.loads((_FIXTURES_M4 / "equipes_repentigny_joliette.json").read_text(encoding="utf-8"))
SCENARIO = json.loads((_FIXTURES_M4 / "scenario_cedule_repentigny_joliette.json").read_text(encoding="utf-8"))
LEADS = {lead["lead_id"]: lead for lead in SCENARIO["leads"]}
LEADS_DU_TEST = ("L-E2E-01", "L-E2E-10")  # deux ravalements : Repentigny et Joliette
REVETEMENT = "revetement-vinyle-fictif"
CATALOGUE = {
    "version": "v1-fictif",
    "unite_monetaire": "CAD",
    "postes": {REVETEMENT: {"cout_unitaire": 4.0, "libelle": "Revêtement de vinyle (fictif)"}},
}
CALENDRIER = {"0": "2026-10-05", "1": "2026-10-06"}
CALME = {
    "temperature_c": 12,
    "vent_kmh": 10,
    "rafales_kmh": 20,
    "precipitation_mm_h": 0,
    "probabilite_precipitation_pct": 10,
    "verglas": False,
}
METEO = {
    "fuseau": "America/Toronto",
    "services": {
        "ravalement": {
            "seuils": {
                "vent_kmh": {"validation": 25, "blocage": 40},
                "pluie_mm_h": {"blocage": 3},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
                "chaleur_c": {"blocage": 35},
            }
        },
        "autre": {"sans_objet": ["vent", "pluie", "gel", "verglas", "chaleur"]},
        "extension": {"sans_objet": ["vent", "pluie", "gel", "verglas", "chaleur"]},
        "isolation_thermique": {"sans_objet": ["vent", "pluie", "gel", "verglas", "chaleur"]},
        "renovation_totale": {"sans_objet": ["vent", "pluie", "gel", "verglas", "chaleur"]},
    },
}
# Les deux outils nouveaux : lecture pure, propriétaire seul.
OUTILS_DU_PROPRIETAIRE = ("m4_lire_meteo_intervention", "m4_lire_retards_incidents")

# Interventions inscrites directement (sans lead M2 ni devis M3) : de quoi remplir plusieurs pages.
SEL = "sel-t4-27-a-e2e-fictif"
FENETRE = {"debut": "2026-10-05T07:00:00-04:00", "fin": "2026-10-05T19:00:00-04:00"}
NOMBRE_ETIENNE, NOMBRE_BIS = 30, 15  # de quoi dépasser la borne de 6 000 caractères de la liste v1 et de la page


# -- installation : profils déclarés par les commandes réelles ----------------------------------------------
def _profil_equipes() -> dict[str, Any]:
    """La démonstration Repentigny-Joliette : deux équipes, DEUX jours de quart, membres = les personnes du scénario."""
    profil = copy.deepcopy(EQUIPES["profil"])
    membres = {"eq-a": ["etienne"], "eq-b": ["nathan"]}
    for equipe in profil["liste"]:
        equipe["membres"] = membres[equipe["id"]]
        equipe["quarts"] = [{"jour": jour, "debut_min": 480, "fin_min": 1020} for jour in (0, 1)]
    profil["fenetre_par_defaut"]["jours"] = [0, 1]
    return profil


def _declarer(dossier: Path, commande: str, profil: dict[str, Any]) -> None:
    fichier = dossier / f"{commande}-declare.yaml"
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main([commande, "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


@pytest.fixture
def profils(moteur, equipe, tmp_path, monkeypatch):
    """Services, équipes et règles météo de l'entreprise, déclarés comme le fait le propriétaire."""
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    taxonomie.enregistrer_services(EQUIPES["services_propres"])
    _declarer(tmp_path, "equipes", _profil_equipes())
    _declarer(tmp_path, "meteo", METEO)
    return tmp_path


@pytest.fixture
def vendeur(moteur, equipe, monkeypatch):
    moteur.creer_personne("vendeur.lect", "Vendeur (fictif)", ["seller"], monkeypatch)
    return moteur.appairer("vendeur.lect", "seller")


# -- le bus : devis acceptés, M4 et M6 réels ------------------------------------------------------------------
def _devis_acceptes(moteur: Moteur) -> None:
    for lead_id in LEADS_DU_TEST:
        lead = LEADS[lead_id]
        evenements.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            {
                "lead": {
                    "schema_version": 2,
                    "lead_id": lead_id,
                    "conversation_id": f"sms-{lead_id}",
                    "contact": {"nom": "Client Fictif", "telephone": "+15145550142"},
                    "service": lead["type_travaux"],
                    "ville": lead["secteur"],
                    "urgence_declaree": False,
                    "canal": "texte",
                    "source": "sms",
                },
                "horodatage": iso(moteur.horloge.maintenant),
                "signal_id": f"sms:{lead_id}",
            },
            evenement_id=f"m1-lead-qualifie-{lead_id}",
        )
        devis_id = f"DEVIS-LECT-{lead_id}"
        evenements.publier(
            "m3.devis_accepte",
            "m03-estimation",
            {
                "devis_id": devis_id,
                "lead_id": lead_id,
                "chantier_id": None,
                "lignes": [
                    {
                        "reference_ligne": f"{devis_id}-L0",
                        "description": "Revêtement (fictif)",
                        "quantite": "40",
                        "unite": "pi2",
                        "prix_unitaire": "10.00",
                        "prix_ligne": "400.00",
                        "reference_besoin_materiau": REVETEMENT,
                    }
                ],
                "cout_total": "300.00",
                "prix_total": "400.00",
                "taux_marge": "0.25",
                "horodatage_acceptation": iso(moteur.horloge.maintenant),
            },
            evenement_id=f"m3-devis-accepte-{devis_id}",
        )


def _livrer(moteur: Moteur) -> None:
    """Le vrai répartiteur, M4 et M6 SEULS : `m3.devis_accepte` est aussi consommé par M2, M5 et M8, dont ce trajet
    n'est pas l'objet (un lead inconnu de M2 partirait en quarantaine, légitimement)."""
    departements = {M4: moteur.departements[M4], M6: moteur.departements[M6]}
    for _ in range(10):
        resume = evenements.repartir(departements, maintenant=iso(moteur.horloge.maintenant))
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        if resume["livres"] == 0:
            return
    raise AssertionError("le bus n'a pas atteint le repos")


def _reception(moteur: Moteur, appareil: Any, quantite: float, cle: str) -> Any:
    maintenant = moteur.horloge.maintenant
    return appareil.appeler(
        "m6_receptionner_commande",
        {
            "bon_demande": {
                "po_id": "PO-E2E-LECT",
                "chantier_id": "CHANTIER-DEPOT",
                "horodatage": iso(maintenant),
                "lignes_demandees": [{"materiau_id": REVETEMENT, "quantite_demandee": quantite}],
            },
            "reception_po": {
                "po_id": "PO-E2E-LECT",
                "chantier_id": "CHANTIER-DEPOT",
                "horodatage": iso(maintenant),
                "lignes_recues": [{"materiau_id": REVETEMENT, "quantite_recue": quantite}],
            },
            "catalogue_materiaux": CATALOGUE,
        },
        cle=cle,
        horodatage_appareil=iso(maintenant),
    )


def _confirmer_les_adresses(moteur: Moteur, admin: Any) -> None:
    for lead_id in LEADS_DU_TEST:
        confirmation = admin.appeler(
            "m4_confirmer_localisation",
            {
                "chantier_id": lead_id,
                "action": "confirmee",
                "horodatage": iso(moteur.horloge.maintenant),
                "confirme_par": "nathan",
                "adresse": {
                    "numero_municipal": "10",
                    "odonyme": "rue Fictive",
                    "municipalite": LEADS[lead_id]["secteur"],
                },
                "source": "manuel",
                "motif": "",
                "latitude_microdegres": LEADS[lead_id]["latitude_microdegres"],
                "longitude_microdegres": LEADS[lead_id]["longitude_microdegres"],
            },
            cle=f"cle-localisation-{lead_id}",
            horodatage_appareil=iso(moteur.horloge.maintenant),
        )
        assert confirmation.ok and confirmation.metier["accepte"] is True, confirmation.corps


# -- l'amont des interventions inscrites directement (hors porte d'appareil : aucun n'est un geste de l'app) ------
def _outils_m4(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements[M4].charger_outils()}


def _planifier(moteur: Moteur, lead_id: str, technicien: str) -> str:
    """Un lead qualifié devient une intervention planifiée et assignée à `technicien` (`m4_planifier_intervention`)."""
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
                "horodatage": "2026-10-01T12:00:00-04:00",
                "empreinte": "ab" * 32,
            },
            "horodatage": "2026-10-02T06:00:00-04:00",
            "sel": SEL,
            "techniciens_disponibles": [technicien],
            "fenetres_disponibles": [FENETRE],
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


def _maillons_m4() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(M4, "principal"))


def _octets(objet: Any) -> str:
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


def _saisie(dates_vent_fort=(), vent=55) -> dict[str, Any]:
    """La prévision que l'admin saisit : calme deux jours, `vent` km/h les dates de `dates_vent_fort`."""
    points = []
    for date in CALENDRIER.values():
        for heure in range(6, 21):
            point = {**CALME, "heure": f"{date}T{heure:02d}:00"}
            if date in dates_vent_fort:
                point["vent_kmh"] = vent
            points.append(point)
    return {
        "saisi_par": "nathan",
        "source": "Bulletin fictif du 4 octobre, 18 h",
        "emise_le": "2026-10-04T18:00:00-04:00",
        "points": points,
    }


def _lire_meteo(porte: Any, intervention_id: str, date: str | None = None, saisie: dict | None = None, **en_plus: Any):
    arguments: dict[str, Any] = {"intervention_id": intervention_id, **en_plus}
    if date is not None:
        arguments["date"] = date
    if saisie is not None:
        arguments["previsions_saisies"] = saisie
    return porte.appeler("m4_lire_meteo_intervention", arguments)


def _refus_de_la_porte(reponse: Any) -> bool:
    message = reponse.corps["error"]["message"]
    return (
        reponse.statut == 403
        and reponse.corps["ok"] is False
        and reponse.corps["error"]["type"] == "tool_call_blocked"
        and "tool_out_of_scope" in message
    )


def _projection(creneau: dict[str, Any]) -> dict[str, Any]:
    """Ce que deux vérifications d'un même créneau disent pareil : où, quand, le verdict, ses règles, sa source."""
    citation = creneau["prevision"]
    return {
        "intervention_id": creneau["intervention_id"],
        "service": creneau["service"],
        "date": creneau["date"],
        "jour": creneau["jour"],
        "debut_min": creneau["debut_min"],
        "fin_min": creneau["fin_min"],
        "statut": creneau["statut"],
        "regles": [(r["statut"], r["detail"]) for r in creneau["regles"]],
        "prevision": (citation["source"], citation["saisi_par"], citation["emise_le"]),
    }


# ========================================================================================== la météo d'une intervention
@SQLITE_SEULEMENT
def test_la_meteo_d_une_intervention_se_lit_sans_plan_id_comme_celle_du_plan_et_n_ecrit_rien(
    moteur, equipe, profils, monkeypatch
):
    admin = equipe["admin"]

    # 1. deux devis acceptés : M4 (a_planifier). Aucune cédule appliquée : aucun créneau, donc jamais « ok »
    _devis_acceptes(moteur)
    _livrer(moteur)
    interventions = {i["lead_id"]: i["intervention_id"] for i in admin.appeler("m4_lister_interventions", {}).resultat}
    assert sorted(interventions) == sorted(LEADS_DU_TEST)
    premier, second = interventions["L-E2E-01"], interventions["L-E2E-10"]
    avant, maillons_avant = moteur.empreinte_etat(), _octets(_maillons_m4())
    sans_creneau = _lire_meteo(admin, premier, CALENDRIER["0"], _saisie())
    assert sans_creneau.statut == 200 and sans_creneau.metier["accepte"] is True, sans_creneau.corps
    lecture = sans_creneau.resultat
    assert lecture["statut"] == "inconnu" and lecture["creneaux"] == [] and lecture["plan_id"] is None
    assert lecture["statut_intervention"] == "a_planifier" and lecture["cause"]["code"] == "REJ-CHAMP-MANQUANT"
    assert "a_planifier" in lecture["cause"]["detail"] and "m4_proposer_cedule" in lecture["cause"]["detail"]
    assert moteur.empreinte_etat() == avant and _octets(_maillons_m4()) == maillons_avant

    # 2. le matériel arrive, les adresses sont confirmées, la cédule est proposée puis APPLIQUÉE par l'admin (N3)
    _confirmer_les_adresses(moteur, admin)
    assert _reception(moteur, admin, 80.0, "cle-reception-lect").metier["accepte"] is True
    _livrer(moteur)
    proposition = admin.appeler(
        "m4_proposer_cedule",
        {"horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-proposer-lect",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert proposition.ok and proposition.metier["accepte"] is True, proposition.corps
    plan = proposition.resultat
    plan_id = plan["plan_id"]
    visites = {v["chantier"]: (r["jour"], v["debut_min"], v["fin_min"]) for r in plan["plan"] for v in r["visites"]}
    assert sorted(visites) == sorted([premier, second]) and plan["non_cedulees"] == []
    date_premier = CALENDRIER[str(visites[premier][0])]
    date_second = CALENDRIER[str(visites[second][0])]
    proposee_seulement = _lire_meteo(admin, premier, date_premier, _saisie()).resultat
    assert proposee_seulement["creneaux"] == [] and proposee_seulement["statut"] == "inconnu", (
        "un plan seulement proposé ne tient rien : aucun créneau, jamais ok"
    )
    application = admin.appeler(
        "m4_appliquer_cedule",
        {"plan_id": plan_id, "horodatage": iso(moteur.horloge.maintenant), "confirme_par": "nathan"},
        cle="cle-appliquer-lect",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert application.ok and application.metier["accepte"] is True, application.corps
    for identifiant in (premier, second):
        statut = admin.appeler("m4_statut_intervention", {"intervention_id": identifiant}).resultat["statut"]
        assert statut == "planifiee"

    # 3. la lecture, sans plan_id : le créneau vient du plan appliqué ; rien n'est écrit
    avant, maillons_avant = moteur.empreinte_etat(), _octets(_maillons_m4())
    calme = _lire_meteo(admin, premier, date_premier, _saisie())
    assert calme.statut == 200 and calme.metier["accepte"] is True, calme.corps
    lecture = calme.resultat
    assert lecture["statut"] == "ok" and lecture["plan_id"] == plan_id and lecture["cause"] is None
    assert lecture["intervention_id"] == premier and lecture["statut_intervention"] == "planifiee"
    (creneau,) = lecture["creneaux"]
    assert (creneau["date"], creneau["service"], creneau["statut"]) == (date_premier, "ravalement", "ok")
    assert (creneau["jour"], creneau["debut_min"], creneau["fin_min"]) == (visites[premier][0], *visites[premier][1:])
    assert (creneau["prevision"]["source"], creneau["prevision"]["saisi_par"], creneau["prevision"]["emise_le"]) == (
        "saisie_manuelle",
        "nathan",
        "2026-10-04T18:00:00-04:00",
    ), "la prévision est citée : source, auteur, heure d'émission"
    assert "reports_proposes" not in lecture and "cedule_relancee" not in lecture, "la lecture ne propose rien"

    # 3a. vent modéré : validation requise ; vent fort : bloquant, avec le vent, l'heure et le seuil cités
    modere = _lire_meteo(admin, premier, date_premier, _saisie(dates_vent_fort=[date_premier], vent=30)).resultat
    assert modere["statut"] == "validation_requise"
    fort = _lire_meteo(admin, premier, date_premier, _saisie(dates_vent_fort=[date_premier])).resultat
    assert fort["statut"] == "bloquant" and fort["creneaux"][0]["statut"] == "bloquant"
    assert any(r["statut"] == "bloquant" and "vent" in r["detail"] for r in fort["creneaux"][0]["regles"])
    assert "reports_proposes" not in fort and "cedule_relancee" not in fort

    # 3b. la même évaluation que celle du plan (T4.13, `m4_verifier_meteo_creneau`), pas une seconde
    saisies = (_saisie(), _saisie(dates_vent_fort=[date_premier], vent=30), _saisie(dates_vent_fort=[date_premier]))
    for saisie in saisies:
        par_le_plan = admin.appeler(
            "m4_verifier_meteo_creneau", {"plan_id": plan_id, "calendrier": CALENDRIER, "previsions_saisies": saisie}
        )
        assert par_le_plan.ok, par_le_plan.corps
        du_plan = {c["intervention_id"]: c for c in par_le_plan.resultat["creneaux"]}
        sans_plan = _lire_meteo(admin, premier, date_premier, saisie).resultat["creneaux"][0]
        assert _projection(sans_plan) == _projection(du_plan[premier])
        sans_plan_second = _lire_meteo(admin, second, date_second, saisie).resultat["creneaux"][0]
        assert _projection(sans_plan_second) == _projection(du_plan[second])

    # 3c. donnée absente = inconnu, jamais ok : pas de date, pas de prévision ni de fournisseur ouvert
    sans_date = _lire_meteo(admin, premier, None, _saisie()).resultat
    assert sans_date["statut"] == "inconnu" and sans_date["creneaux"][0]["statut"] == "inconnu"
    assert "date" in sans_date["creneaux"][0]["cause"]["detail"]
    sans_prevision = _lire_meteo(admin, premier, date_premier).resultat
    assert sans_prevision["statut"] == "inconnu"
    assert sans_prevision["creneaux"][0]["cause"]["code"] == "REJ-METEO-FOURNISSEUR-FERME"

    # 3d. aucune de ces lectures n'a écrit : ni maillon, ni événement, ni approbation, ni journal
    assert moteur.empreinte_etat() == avant and _octets(_maillons_m4()) == maillons_avant
    assert [m["type_entree"] for m in _maillons_m4()].count("cedule_appliquee") == 1

    # 4. un `plan_id` n'est pas une entrée de l'outil (clé inconnue refusée) ; une date impossible ou une intervention
    # inconnue non plus
    avec_plan = _lire_meteo(admin, premier, date_premier, _saisie(), plan_id=plan_id)
    assert avec_plan.ok and avec_plan.enveloppe["ok"] is False, avec_plan.enveloppe
    date_impossible = _lire_meteo(admin, premier, "2026-02-30", _saisie())
    assert date_impossible.ok and date_impossible.metier["accepte"] is False
    assert date_impossible.metier["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    fantome = _lire_meteo(admin, "intervention-fantome", date_premier, _saisie())
    assert fantome.ok and fantome.metier["accepte"] is False
    assert fantome.metier["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
    assert moteur.empreinte_etat() == avant

    # 5. le report d'une intervention est un geste N3 de l'admin : une fois reportée, elle n'a plus de créneau, la
    # lecture le dit (jamais ok) et ne tient plus le plan pour le sien
    report = admin.appeler(
        "m4_signaler_report",
        {"intervention_id": premier, "motif": "meteo", "horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-report-lect",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert report.ok and report.metier["accepte"] is True, report.corps
    reportee = _lire_meteo(admin, premier, date_premier, _saisie()).resultat
    assert reportee["statut"] == "inconnu" and reportee["creneaux"] == [] and reportee["plan_id"] is None
    assert reportee["statut_intervention"] == "reportee" and "reportee" in reportee["cause"]["detail"]
    assert _lire_meteo(admin, second, date_second, _saisie()).resultat["statut"] == "ok", "le second est resté planifié"

    # 6. un fournisseur ouvert par le profil dont le réseau est coupé : inconnu, jamais ok
    profil_ouvert = copy.deepcopy(METEO)
    profil_ouvert["fournisseur"] = "msc_geomet"
    _declarer(profils, "meteo", profil_ouvert)
    vrai_create_connection = socket.create_connection

    def coupure_vers_l_exterieur(adresse, *args, **kwargs):
        if adresse[0] in ("127.0.0.1", "localhost", "::1"):
            return vrai_create_connection(adresse, *args, **kwargs)
        raise OSError("réseau coupé vers l'extérieur (simulé par le test)")

    monkeypatch.setattr(socket, "create_connection", coupure_vers_l_exterieur)
    en_panne = _lire_meteo(admin, second, date_second)
    assert en_panne.ok and en_panne.metier["accepte"] is True, en_panne.corps
    assert en_panne.resultat["statut"] == "inconnu"
    assert en_panne.resultat["creneaux"][0]["cause"]["code"] == "REJ-METEO-FOURNISSEUR-INDISPONIBLE"

    # 7. rien de ce qui précède n'a été tronqué, et seul le report de l'étape 5 (un geste, pas une lecture) a écrit
    assert moteur.bilan()["troncatures"] == []
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(APPROBATIONS.c.statut, APPROBATIONS.c.decide_par).where(
                APPROBATIONS.c.outil == "m4_appliquer_cedule"
            )
        ).all()
    assert lignes == [("executee", "nathan")]
    assert [m["type_entree"] for m in _maillons_m4()].count("transition_statut") >= 1


# ============================================================================================ retards et incidents
@SQLITE_SEULEMENT
def test_les_retards_et_les_incidents_se_lisent_avec_leur_age_sans_rien_ecrire(moteur, equipe, monkeypatch):
    admin, etienne = equipe["admin"], equipe["employe"]
    moteur.creer_personne("employe.bis", "Employé bis (fictif)", ["employee"], monkeypatch)
    a = _planifier(moteur, "L-RET-A", "etienne")
    b = _planifier(moteur, "L-RET-B", "etienne")
    c = _planifier(moteur, "L-RET-C", "employe.bis")

    # 0. rien n'est arrivé : des listes vides, et le retard sur la cédule reste « non mesurable » (jamais « aucun
    # retard »)
    reference = "2026-09-29T09:30:00-04:00"
    vide = admin.appeler("m4_lire_retards_incidents", {"horodatage_reference": reference})
    assert vide.statut == 200 and vide.metier["accepte"] is True, vide.corps
    assert vide.resultat["reports"]["total"] == 0 and vide.resultat["incidents"]["total"] == 0
    assert vide.resultat["retard_sur_cedule"]["statut"] == "non_mesurable"

    # 1. les gestes de l'app : l'employé signale un client absent et un écart de matériaux ; l'admin reporte une autre.
    # PLAN T4.27-a2 : l'heure d'un report et d'une demande d'écart est celle de RÉCEPTION du serveur (l'horloge de test
    # du moteur), plus celle que l'app écrit : on la règle avant chaque geste, l'âge lu en découle.
    moteur.horloge.maintenant = dt.datetime.fromisoformat("2026-09-27T08:00:00-04:00")
    report_employe = etienne.appeler(
        "m4_signaler_report",
        {"intervention_id": a, "motif": "client_absent", "horodatage": "2026-09-27T08:00:00-04:00"},
        cle="cle-report-client-absent",
        horodatage_appareil="2026-09-27T08:00:00-04:00",
    )
    assert report_employe.ok and report_employe.metier["accepte"] is True, report_employe.corps
    moteur.horloge.maintenant = dt.datetime.fromisoformat("2026-09-28T07:00:00-04:00")
    report_admin = admin.appeler(
        "m4_signaler_report",
        {"intervention_id": c, "motif": "decision_admin", "horodatage": "2026-09-28T07:00:00-04:00"},
        cle="cle-report-decision-admin",
        horodatage_appareil="2026-09-28T07:00:00-04:00",
    )
    assert report_admin.ok and report_admin.metier["accepte"] is True, report_admin.corps
    moteur.horloge.maintenant = dt.datetime.fromisoformat("2026-09-28T12:00:00-04:00")
    ecart = etienne.appeler(
        "m4_creer_demande_ecart",
        {
            "intervention_id": b,
            "version_prevue": {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]},
            "version_declaree": {"duree_minutes": 90, "perimetre": "PERIMETRE-LIBRE-DU-TERRAIN", "materiaux": ["m2"]},
            "horodatage": "2026-09-28T12:00:00-04:00",
        },
        cle="cle-ecart-materiaux",
        horodatage_appareil="2026-09-28T12:00:00-04:00",
    )
    assert ecart.ok and ecart.metier["accepte"] is True, ecart.corps
    demande_id = ecart.resultat["demande_id"]

    # 2. l'admin lit : ce que les gestes ont écrit (l'heure du serveur, écrite en UTC), avec l'âge calculé à partir de
    # SA référence ; rien n'est écrit
    avant, maillons_avant = moteur.empreinte_etat(), _octets(_maillons_m4())
    lecture = admin.appeler("m4_lire_retards_incidents", {"horodatage_reference": reference})
    assert lecture.statut == 200 and lecture.metier["accepte"] is True, lecture.corps
    releve = lecture.resultat
    assert releve["reference"] == reference and releve["seuil_blocage_heures"] == 24
    assert releve["reports"]["liste"] == [
        {
            "intervention_id": a,
            "motif": "client_absent",
            "depuis": "2026-09-27T12:00:00+00:00",
            "origine_heure": "serveur",
            "heures_ecoulees": 49,
        },
        {
            "intervention_id": c,
            "motif": "decision_admin",
            "depuis": "2026-09-28T11:00:00+00:00",
            "origine_heure": "serveur",
            "heures_ecoulees": 26,
        },
    ]
    assert releve["reports"]["par_motif"] == {"client_absent": 1, "meteo": 0, "decision_admin": 1}
    assert releve["incidents"]["liste"] == [
        {
            "demande_id": demande_id,
            "intervention_id": b,
            "type_demande": "ecart_metier",
            "depuis": "2026-09-28T16:00:00+00:00",
            "origine_heure": "serveur",
            "heures_ecoulees": 21,
            "bloquee": False,
        }
    ]
    assert releve["incidents"]["bloques"] == 0
    assert releve["retard_sur_cedule"]["statut"] == "non_mesurable" and releve["retard_sur_cedule"]["manque"]
    assert lecture.mesure.tronque is False
    texte = json.dumps(releve, ensure_ascii=False)
    for interdit in ("PERIMETRE-LIBRE-DU-TERRAIN", "materiaux", "Client fictif", "0102030405", "etienne", "prix"):
        assert interdit not in texte, interdit
    assert moteur.empreinte_etat() == avant and _octets(_maillons_m4()) == maillons_avant

    # 3. 24 h plus tard, la demande d'écart est « bloquée », comme le digest la compte ; deux lectures, même relevé
    plus_tard = "2026-09-29T12:00:00-04:00"
    bloquee = admin.appeler("m4_lire_retards_incidents", {"horodatage_reference": plus_tard}).resultat
    assert bloquee["incidents"]["liste"][0]["heures_ecoulees"] == 24 and bloquee["incidents"]["liste"][0]["bloquee"]
    assert bloquee["incidents"]["bloques"] == 1
    du_digest = admin.appeler(
        "m4_produire_digest", {"date_cible": "2026-09-29", "horodatage_reference": plus_tard}
    ).resultat
    assert [ligne["demande_id"] for ligne in du_digest["interventions_bloquees_en_revue"]] == [demande_id]
    assert admin.appeler("m4_lire_retards_incidents", {"horodatage_reference": plus_tard}).resultat == bloquee
    assert moteur.empreinte_etat() == avant

    # 4. une référence qui n'est pas une heure est refusée, sans écrire ; l'heure de l'appelant est la seule référence
    illisible = admin.appeler("m4_lire_retards_incidents", {"horodatage_reference": "hier matin"})
    assert illisible.ok and illisible.metier["accepte"] is False
    assert illisible.metier["verdict"]["code"] == "REJ-HORODATAGE-INVALIDE"
    sans_reference = admin.appeler("m4_lire_retards_incidents", {})
    assert sans_reference.ok and sans_reference.enveloppe["ok"] is False
    assert moteur.empreinte_etat() == avant and moteur.bilan()["troncatures"] == []


# ============================================================================================ la liste par pages
def _pages(porte: Any, arguments: dict[str, Any] | None = None, taille_page: int | None = None):
    """Toutes les pages de `m4_lister_interventions`, de la première à la dernière : `(lignes, réponses)`."""
    lignes, reponses, curseur = [], [], None
    for _ in range(60):
        demande = {**(arguments or {}), "curseur": curseur}
        if taille_page is not None:
            demande["taille_page"] = taille_page
        reponse = porte.appeler("m4_lister_interventions", demande)
        assert reponse.statut == 200 and reponse.ok, reponse.corps
        assert reponse.metier["interventions"] is not None, reponse.metier
        reponses.append(reponse)
        lignes.extend(reponse.metier["interventions"])
        page = reponse.metier["page"]
        if not page["reste"]:
            assert page["curseur_suivant"] is None
            return lignes, reponses
        assert page["curseur_suivant"] is not None
        curseur = page["curseur_suivant"]
    raise AssertionError("la lecture ne finit pas : plus de 60 pages")


@pytest.fixture
def monde_paginee(moteur, equipe, monkeypatch):
    """45 interventions planifiées : 30 à Étienne, 15 à un autre employé. `{intervention_id: technicien}`."""
    moteur.creer_personne("employe.bis", "Employé bis (fictif)", ["employee"], monkeypatch)
    assignees = {}
    for numero in range(NOMBRE_ETIENNE + NOMBRE_BIS):
        technicien = "employe.bis" if numero % 3 == 0 else "etienne"
        assignees[_planifier(moteur, f"L-PAGE-{numero:03d}", technicien)] = technicien
    assert sum(1 for t in assignees.values() if t == "etienne") == NOMBRE_ETIENNE
    return {"assignees": assignees, "autre": moteur.appairer("employe.bis", "employee")}


@SQLITE_SEULEMENT
def test_l_admin_lit_toutes_les_interventions_par_pages_sans_troncature_l_employe_seulement_les_siennes(
    moteur, equipe, monde_paginee
):
    admin, etienne, autre = equipe["admin"], equipe["employe"], monde_paginee["autre"]
    assignees = monde_paginee["assignees"]
    a_etienne = {i for i, t in assignees.items() if t == "etienne"}
    a_l_autre = {i for i, t in assignees.items() if t == "employe.bis"}
    avant = moteur.empreinte_etat()

    # 1. le contrat v1 est gelé : sans clé de pagination, la liste entière, que le socle tronque au-delà de 6 000 car.
    v1 = admin.appeler("m4_lister_interventions", {})
    assert v1.statut == 200 and v1.mesure.tronque is True, "la liste v1 des 45 interventions dépasse la borne du socle"
    depart = len(moteur.mesures)

    # 2. l'admin lit les 45, une fois chacune, dans l'ordre, sous la borne : aucune page tronquée
    lignes, reponses = _pages(admin)
    identifiants = [ligne["intervention_id"] for ligne in lignes]
    assert len(reponses) >= 3, "45 interventions ne tiennent pas dans une seule page de 6 000 caractères"
    assert identifiants == sorted(assignees) and len(set(identifiants)) == len(assignees)
    assert all(not r.mesure.tronque and r.mesure.octets_texte <= LIMITE_TRONCATURE for r in reponses)
    assert all(r.metier["page"]["total"] == len(assignees) for r in reponses)
    assert reponses[0].metier["page"]["curseur"] is None and reponses[-1].metier["page"]["reste"] == 0
    # `reste` compte les interventions qui viennent APRÈS la page : il descend jusqu'à zéro, page après page
    assert [r.metier["page"]["reste"] for r in reponses] == sorted(
        (r.metier["page"]["reste"] for r in reponses), reverse=True
    )
    assert sum(r.metier["page"]["taille"] for r in reponses) == len(assignees)
    assert moteur.bilan(depart)["troncatures"] == []

    # 3. une taille de page choisie : mêmes lignes, même ordre, plus de pages
    petites, pages_de_cinq = _pages(admin, taille_page=5)
    assert [ligne["intervention_id"] for ligne in petites] == identifiants
    assert len(pages_de_cinq) == 9 and all(r.metier["page"]["taille"] == 5 for r in pages_de_cinq)

    # 4. l'employé ne voit que SES interventions : `total`, `reste` et `curseur_suivant` ne comptent jamais celles des
    # autres
    siennes, pages_etienne = _pages(etienne)
    assert {ligne["intervention_id"] for ligne in siennes} == a_etienne
    assert [ligne["intervention_id"] for ligne in siennes] == sorted(a_etienne)
    assert all(r.metier["page"]["total"] == NOMBRE_ETIENNE for r in pages_etienne)
    assert all(not r.mesure.tronque for r in pages_etienne)
    les_autres, pages_autre = _pages(autre)
    assert {ligne["intervention_id"] for ligne in les_autres} == a_l_autre
    assert all(r.metier["page"]["total"] == NOMBRE_BIS for r in pages_autre)
    assert not ({ligne["intervention_id"] for ligne in siennes} & {ligne["intervention_id"] for ligne in les_autres})
    # une ligne de page est une ligne de la liste v1, octet pour octet (la liste v1 de l'autre employé tient sous la
    # borne)
    v1_de_l_autre = autre.appeler("m4_lister_interventions", {})
    assert v1_de_l_autre.statut == 200 and v1_de_l_autre.mesure.tronque is False
    assert sorted(v1_de_l_autre.resultat, key=lambda ligne: ligne["intervention_id"]) == les_autres

    # 4a. un curseur pris dans les pages de l'admin ne révèle rien à l'employé : il ne voit que les siennes après lui
    curseur_admin = reponses[0].metier["page"]["curseur_suivant"]
    apres = etienne.appeler("m4_lister_interventions", {"curseur": curseur_admin})
    assert apres.statut == 200 and apres.ok
    vus = [ligne["intervention_id"] for ligne in apres.metier["interventions"]]
    assert vus and set(vus) <= a_etienne and all(identifiant > curseur_admin for identifiant in vus)
    page = apres.metier["page"]
    assert page["total"] == NOMBRE_ETIENNE, "le total est celui des interventions de l'employé, jamais des autres"
    assert page["taille"] + page["reste"] == len([i for i in a_etienne if i > curseur_admin])

    # 4b. le statut demandé filtre AVANT la pagination
    planifiees, _ = _pages(etienne, {"statut": "planifiee"})
    assert {ligne["intervention_id"] for ligne in planifiees} == a_etienne
    annulees = etienne.appeler("m4_lister_interventions", {"statut": "annulee", "taille_page": 10})
    assert annulees.metier["interventions"] == [] and annulees.metier["page"]["total"] == 0
    assert annulees.metier["page"]["reste"] == 0 and annulees.metier["page"]["curseur_suivant"] is None

    # 5. des clés mal formées sont refusées, sans rien écrire
    for mauvais in ({"taille_page": 0}, {"taille_page": 51}, {"taille_page": 2.5}, {"curseur": "pas-un-curseur"}):
        refus = admin.appeler("m4_lister_interventions", mauvais)
        assert refus.ok and refus.enveloppe["ok"] is False, (mauvais, refus.enveloppe)
    assert moteur.empreinte_etat() == avant, "lire des pages n'écrit rien"


# ============================================================================================ les portes fermées
@SQLITE_SEULEMENT
def test_l_employe_et_le_vendeur_recoivent_403_sur_la_meteo_et_les_retards_l_admin_seul_les_lit(
    moteur, equipe, vendeur, profils
):
    admin, employe = equipe["admin"], equipe["employe"]
    interventions = [_planifier(moteur, f"L-403-{n}", "etienne") for n in range(2)]
    arguments = {
        "m4_lire_meteo_intervention": {"intervention_id": interventions[0], "date": CALENDRIER["0"]},
        "m4_lire_retards_incidents": {"horodatage_reference": "2026-09-29T09:30:00-04:00"},
    }
    assert set(arguments) == set(OUTILS_DU_PROPRIETAIRE)
    avant = moteur.empreinte_etat()

    for outil, args in arguments.items():
        assert _refus_de_la_porte(employe.appeler(outil, args)), f"l'employé n'a pas droit à {outil}"
        assert _refus_de_la_porte(vendeur.appeler(outil, args)), f"le vendeur n'a pas droit à {outil}"
        passe = admin.appeler(outil, args)
        assert passe.statut == 200 and passe.metier["accepte"] is True, (outil, passe.corps)
    # un outil permis, nommé avec son serveur ou en majuscules, est refusé, même à l'admin (la règle est le nom NU)
    for nom in (
        "m04-field-ops.m4_lire_retards_incidents",
        "mcp__m04-field-ops__m4_lire_meteo_intervention",
        "M4_LIRE_RETARDS_INCIDENTS",
    ):
        assert admin.appeler(nom, {}).statut == 403, nom
    assert moteur.empreinte_etat() == avant, "un refus de la porte n'écrit rien, et une lecture non plus"

    # la portée vient des fragments du core : les deux outils sont ceux de l'admin, et de lui seul
    portees = openclaw.roles_outils(moteur.departements)
    for outil in OUTILS_DU_PROPRIETAIRE:
        assert outil in portees["admin"], outil
        assert outil not in portees["employee"] and outil not in portees["seller"], outil
    assert "m4_lister_interventions" in portees["admin"] and "m4_lister_interventions" in portees["employee"]
    assert "m4_lister_interventions" not in portees["seller"]
    vendeur_liste = vendeur.appeler("m4_lister_interventions", {"taille_page": 5})
    assert _refus_de_la_porte(vendeur_liste), "le vendeur ne lit aucune intervention, par pages ou non"
