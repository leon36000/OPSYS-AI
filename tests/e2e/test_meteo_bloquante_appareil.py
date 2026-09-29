"""PLAN T4.13 : E2E « météo bloquante » par la porte d'appareil et par le VRAI bus (DEFINITION-PRODUIT §6 « un chantier
de revêtement sous un vent fort se reporte » ; §9.5 « dispatch du jour » ; M4.10, M4.21).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, personnes et appareils créés par les commandes réelles du socle). Aucune requête météo ne sort : la
prévision est saisie par l'admin (sa source et son heure d'émission sont citées), et la panne d'un fournisseur ouvert
par le profil est simulée en coupant les connexions vers l'extérieur (le serveur de test, lui, reste joignable en boucle
locale).

Le trajet (deux revêtements ; quantités et prévisions fictives) :

1. `m3.devis_accepte` -> le bus livre M4 (interventions `a_planifier`) ET le VRAI M6 (réservation `a_commander`, aucun
stock) :
   le volet « matériel » de la préparation dit ce qui manque, la cédule refuse de partir ;
2. l'admin RÉCEPTIONNE le matériel sur son téléphone : M6 publie `pret`, le bus le livre à M4, le volet suit ;
3. l'admin confirme les adresses, fait PROPOSER la cédule (deux jours de quart), puis vérifie la MÉTÉO du plan :
   * sans prévision ni fournisseur ouvert : `inconnu` (jamais `ok`), le registre ne bouge pas ;
   * prévision saisie de vent fort le jour du premier revêtement : `bloquant`, report proposé (motif `meteo`), cédule
     relancée sur les jours restants, rien d'écrit, rien d'appliqué ;
4. les arguments de la cédule relancée, rejoués à `m4_proposer_cedule`, donnent le MÊME plan que l'aperçu ; l'admin
   l'APPLIQUE (N3, sous son nom) : les deux revêtements sont planifiés le jour calme, et le premier plan n'a jamais été
   appliqué ;
5. la météo du nouveau plan, prévision calme : `ok` ; le premier plan, que le second a remplacé, est PÉRIMÉ (aucun
créneau
   vivant, aucun report, aucune relance) ; si le vent se lève le jour calme, le report d'un revêtement planifié est un
   geste N3 de l'admin (`m4_signaler_report`, motif `meteo`) que la vérification propose et n'exécute jamais ;
6. un fournisseur ouvert par le profil dont le réseau est coupé : `inconnu`, jamais `ok` ;
7. l'employé n'a aucune portée sur la vérification météo (fermé à la porte) ; aucune réponse n'a été tronquée.

Données fictives (AGENTS.md).
"""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml
from harnais_e2e import Moteur, iso
from sqlalchemy import select

from opsys import cli, evenements, stockage, taxonomie
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
M4, M6 = "m04-field-ops", "m06-material-control"
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
        devis_id = f"DEVIS-METEO-{lead_id}"
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
                "po_id": "PO-E2E-METEO",
                "chantier_id": "CHANTIER-DEPOT",
                "horodatage": iso(maintenant),
                "lignes_demandees": [{"materiau_id": REVETEMENT, "quantite_demandee": quantite}],
            },
            "reception_po": {
                "po_id": "PO-E2E-METEO",
                "chantier_id": "CHANTIER-DEPOT",
                "horodatage": iso(maintenant),
                "lignes_recues": [{"materiau_id": REVETEMENT, "quantite_recue": quantite}],
            },
            "catalogue_materiaux": CATALOGUE,
        },
        cle=cle,
        horodatage_appareil=iso(maintenant),
    )


def _maillons_m4() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(M4, "principal"))


def _octets(objet: Any) -> str:
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


def _saisie(dates_vent_fort=(), vent=55) -> dict[str, Any]:
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


def _meteo(moteur: Moteur, admin: Any, plan_id: str, saisie: dict[str, Any] | None = None, calendrier=None) -> Any:
    arguments: dict[str, Any] = {"plan_id": plan_id, "calendrier": CALENDRIER if calendrier is None else calendrier}
    if saisie is not None:
        arguments["previsions_saisies"] = saisie
    return admin.appeler("m4_verifier_meteo_creneau", arguments)


# ============================================================================================ le trajet
@SQLITE_SEULEMENT
def test_meteo_bloquante_report_propose_cedule_relancee_puis_appliquee_par_l_admin(
    moteur, equipe, profils, monkeypatch
):
    admin, employe = equipe["admin"], equipe["employe"]

    # 1. deux devis acceptés : M4 (a_planifier) et M6 (a_commander, aucun stock) ; le matériel manque, la cédule ne
    # part pas
    _devis_acceptes(moteur)
    _livrer(moteur)
    interventions = {i["lead_id"]: i["intervention_id"] for i in admin.appeler("m4_lister_interventions", {}).resultat}
    assert sorted(interventions) == sorted(LEADS_DU_TEST)
    for lead_id in LEADS_DU_TEST:
        _confirmer = admin.appeler(
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
        assert _confirmer.ok and _confirmer.metier["accepte"] is True, _confirmer.corps
    premier, second = interventions["L-E2E-01"], interventions["L-E2E-10"]
    avant_reception = admin.appeler("m4_verifier_preparation", {"intervention_id": premier}).resultat
    assert avant_reception["pret"] is False and avant_reception["volets"]["materiel"]["statut"] == "manque"
    assert avant_reception["volets"]["materiel"]["detail"] == "a_commander"
    assert avant_reception["volets"]["meteo"]["statut"] == "ok", "le profil météo est déclaré : la météo se juge"
    refus = admin.appeler(
        "m4_proposer_cedule",
        {"horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-proposer-trop-tot",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert refus.ok and refus.metier["accepte"] is False, "le matériel manque : aucune cédule"

    # 2. l'admin réceptionne le matériel : M6 dit `pret`, le bus le livre à M4, le volet suit
    reception = _reception(moteur, admin, 80.0, "cle-reception-meteo")
    assert reception.ok and reception.metier["accepte"] is True, reception.corps
    _livrer(moteur)
    for identifiant in (premier, second):
        verdict = admin.appeler("m4_verifier_preparation", {"intervention_id": identifiant}).resultat
        assert verdict["pret"] is True and verdict["a_fournir"] == [], verdict
        assert verdict["volets"]["materiel"]["statut"] == verdict["volets"]["meteo"]["statut"] == "ok"

    # 3. la cédule est proposée (deux jours de quart) ; la météo du plan
    proposition = admin.appeler(
        "m4_proposer_cedule",
        {"horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-proposer-1",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert proposition.ok and proposition.metier["accepte"] is True, proposition.corps
    premier_plan = proposition.resultat
    plan_id = premier_plan["plan_id"]
    visites = {
        v["chantier"]: (r["jour"], v["debut_min"], v["fin_min"]) for r in premier_plan["plan"] for v in r["visites"]
    }
    assert sorted(visites) == sorted([premier, second]) and premier_plan["non_cedulees"] == []
    jour_bloque = visites[premier][0]
    jour_calme = 1 - jour_bloque

    # 3a. sans prévision ni fournisseur ouvert : inconnu, jamais ok ; le registre ne bouge pas
    avant = moteur.empreinte_etat()
    maillons_avant = _octets(_maillons_m4())
    sans_prevision = _meteo(moteur, admin, plan_id)
    assert sans_prevision.ok and sans_prevision.resultat["statut"] == "inconnu"
    assert {c["statut"] for c in sans_prevision.resultat["creneaux"]} == {"inconnu"}
    assert sans_prevision.resultat["creneaux"][0]["cause"]["code"] == "REJ-METEO-FOURNISSEUR-FERME"
    assert moteur.empreinte_etat() == avant and _octets(_maillons_m4()) == maillons_avant

    # 3b. vent fort le jour du premier revêtement (55 km/h, blocage à 40) : bloquant, report proposé, cédule relancée
    saisie = _saisie(dates_vent_fort=[CALENDRIER[str(jour_bloque)]])
    bloquee = _meteo(moteur, admin, plan_id, saisie)
    assert bloquee.ok, bloquee.corps
    resultat = bloquee.resultat
    assert resultat["statut"] == "bloquant" and resultat["plan_id"] == plan_id
    par_intervention = {c["intervention_id"]: c for c in resultat["creneaux"]}
    creneau = par_intervention[premier]
    assert creneau["statut"] == "bloquant" and creneau["service"] == "ravalement"
    assert creneau["date"] == CALENDRIER[str(jour_bloque)]
    assert any(r["statut"] == "bloquant" and "vent" in r["detail"] for r in creneau["regles"])
    citation = creneau["prevision"]
    assert (citation["source"], citation["saisi_par"], citation["emise_le"]) == (
        "saisie_manuelle",
        "nathan",
        "2026-10-04T18:00:00-04:00",
    ), "la prévision est citée : source, auteur, heure"
    assert resultat["reports_proposes"][0]["motif"] == "meteo"
    assert resultat["reports_proposes"][0]["intervention_id"] == premier
    relance = resultat["cedule_relancee"]
    assert relance["statut"] == "apercu" and relance["jours_retires"] == {"ravalement": [jour_bloque]}
    fenetres = {c["intervention_id"]: c["fenetre"]["jours"] for c in relance["arguments"]["chantiers"]}
    assert fenetres == {premier: [jour_calme], second: [jour_calme]}
    apercu_visites = {v["chantier"]: r["jour"] for r in relance["apercu"]["plan"] for v in r["visites"]}
    assert apercu_visites == {premier: jour_calme, second: jour_calme}
    # rien n'est écrit, rien n'est appliqué : la vérification est une lecture
    assert moteur.empreinte_etat() == avant and _octets(_maillons_m4()) == maillons_avant
    assert [m["type_entree"] for m in _maillons_m4()].count("cedule_appliquee") == 0
    assert admin.appeler("m4_statut_intervention", {"intervention_id": premier}).resultat["statut"] == "a_planifier"
    texte = json.dumps(resultat, ensure_ascii=False)
    for interdit in ("latitude", "longitude", "microdegres", "Client Fictif", "5145550142", "prix"):
        assert interdit not in texte, interdit

    # 4. les arguments de la cédule relancée donnent le même plan que l'aperçu ; l'admin l'applique (N3, sous son nom)
    relancee = admin.appeler(
        "m4_proposer_cedule",
        {"horodatage": iso(moteur.horloge.maintenant), **relance["arguments"]},
        cle="cle-proposer-2",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert relancee.ok and relancee.metier["accepte"] is True, relancee.corps
    assert relancee.resultat["plan_id"] == relance["apercu"]["plan_id"] != plan_id
    assert _octets(relancee.resultat["plan"]) == _octets(relance["apercu"]["plan"])
    application = admin.appeler(
        "m4_appliquer_cedule",
        {
            "plan_id": relancee.resultat["plan_id"],
            "horodatage": iso(moteur.horloge.maintenant),
            "confirme_par": "nathan",
        },
        cle="cle-appliquer-2",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert application.ok and application.metier["accepte"] is True, application.corps
    assert application.resultat["appliquee_par"] == "nathan" and application.resultat["deja_appliquee"] is False
    for identifiant in (premier, second):
        assert (
            admin.appeler("m4_statut_intervention", {"intervention_id": identifiant}).resultat["statut"] == "planifiee"
        )
    appliquees = [m for m in _maillons_m4() if m["type_entree"] == "cedule_appliquee"]
    assert [m["plan_id"] for m in appliquees] == [relancee.resultat["plan_id"]], (
        "le premier plan n'a jamais été appliqué"
    )
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(APPROBATIONS.c.statut, APPROBATIONS.c.decide_par).where(
                APPROBATIONS.c.outil == "m4_appliquer_cedule"
            )
        ).all()
    assert lignes == [("executee", "nathan")], "geste N3 exécuté par l'humain lui-même, tracé sous son nom"

    # 5. la météo du nouveau plan (prévision calme) : ok ; le premier plan, que le second a remplacé, est PÉRIMÉ
    nouveau_plan = relancee.resultat["plan_id"]
    calme = _meteo(moteur, admin, nouveau_plan, _saisie())
    assert calme.ok and calme.resultat["statut"] == "ok" and calme.resultat["cedule_relancee"] is None
    assert {c["date"] for c in calme.resultat["creneaux"]} == {CALENDRIER[str(jour_calme)]}
    periume = _meteo(moteur, admin, plan_id, saisie)
    assert periume.ok and periume.resultat["statut"] == "inconnu", (
        "aucun créneau vivant : le second plan tient les deux"
    )
    assert sorted(p["intervention_id"] for p in periume.resultat["perimes"]) == sorted([premier, second])
    assert {p["tenu_par"] for p in periume.resultat["perimes"]} == {nouveau_plan}
    assert periume.resultat["reports_proposes"] == [] and periume.resultat["cedule_relancee"] is None
    assert "périmé" in periume.resultat["avertissement"]

    # 5b. le vent se lève AUSSI le jour calme : les revêtements sont planifiés, le report est un geste N3 de l'admin
    vent_le_jour_calme = _meteo(moteur, admin, nouveau_plan, _saisie(dates_vent_fort=[CALENDRIER[str(jour_calme)]]))
    assert vent_le_jour_calme.ok and vent_le_jour_calme.resultat["statut"] == "bloquant"
    reports = {r["intervention_id"]: r for r in vent_le_jour_calme.resultat["reports_proposes"]}
    assert sorted(reports) == sorted([premier, second])
    geste = reports[premier]["geste"]
    assert reports[premier]["statut_intervention"] == "planifiee"
    assert (geste["outil"], geste["niveau"], geste["a_completer"]) == ("m4_signaler_report", "N3", "horodatage")
    assert geste["arguments"] == {"intervention_id": premier, "motif": "meteo"}
    assert admin.appeler("m4_statut_intervention", {"intervention_id": premier}).resultat["statut"] == "planifiee"
    report = admin.appeler(
        "m4_signaler_report",
        {**geste["arguments"], "horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-report-meteo",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert report.ok and report.metier["accepte"] is True, report.corps
    assert admin.appeler("m4_statut_intervention", {"intervention_id": premier}).resultat["statut"] == "reportee"
    assert admin.appeler("m4_statut_intervention", {"intervention_id": second}).resultat["statut"] == "planifiee", (
        "le second n'est reporté que par un geste de l'admin, jamais par la vérification"
    )

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
    en_panne = _meteo(moteur, admin, nouveau_plan)
    assert en_panne.ok, en_panne.corps
    assert en_panne.resultat["statut"] == "inconnu"
    assert {c["statut"] for c in en_panne.resultat["creneaux"]} == {"inconnu"}
    assert en_panne.resultat["creneaux"][0]["cause"]["code"] == "REJ-METEO-FOURNISSEUR-INDISPONIBLE"
    assert en_panne.resultat["reports_proposes"] == []

    # 7. l'employé n'a aucune portée sur la vérification météo ; rien n'a été tronqué
    avant_employe = moteur.empreinte_etat()
    refuse = employe.appeler("m4_verifier_meteo_creneau", {"plan_id": plan_id, "calendrier": CALENDRIER})
    assert refuse.statut == 403 and refuse.ok is False, refuse.corps
    assert moteur.empreinte_etat() == avant_employe
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_sans_regles_meteo_declarees_la_cedule_ne_part_pas_et_le_dit(moteur, equipe, tmp_path, monkeypatch):
    """Le propriétaire n'a rien déclaré pour la météo : le volet manque (« seuil à configurer », avec la commande), la
    préparation n'est jamais prête et la cédule refuse de partir : jamais un seuil inventé."""
    admin = equipe["admin"]
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    taxonomie.enregistrer_services(EQUIPES["services_propres"])
    _declarer(tmp_path, "equipes", _profil_equipes())
    _devis_acceptes(moteur)
    _livrer(moteur)
    assert _reception(moteur, admin, 80.0, "cle-reception-sans-meteo").metier["accepte"] is True
    _livrer(moteur)
    (une, *_) = [i["intervention_id"] for i in admin.appeler("m4_lister_interventions", {}).resultat]
    verdict = admin.appeler("m4_verifier_preparation", {"intervention_id": une}).resultat
    assert verdict["pret"] is False and verdict["volets"]["materiel"]["statut"] == "ok"
    assert verdict["volets"]["meteo"]["statut"] == "manque"
    assert "opsys meteo declarer" in verdict["volets"]["meteo"]["manque"]
    refus = admin.appeler(
        "m4_proposer_cedule",
        {"horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-proposer-sans-meteo",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert refus.ok and refus.metier["accepte"] is False
    assert refus.metier["verdict"]["code"] == "REJ-CEDULE-RIEN-A-PLANIFIER"
    assert "meteo" in refus.metier["verdict"]["detail"]
    assert [m["type_entree"] for m in _maillons_m4()].count("cedule_proposee") == 0
