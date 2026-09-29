"""PLAN T4.13 : `m4_verifier_meteo_creneau`, de bout en bout, sur les VRAIS outils, le VRAI bus, les VRAIS fichiers
`entreprise.yaml` (équipes et météo, déclarés par `opsys equipes declarer` et `opsys meteo declarer`) et une base SQLite
migrée. Aucun réseau (sockets bloqués : un fournisseur est injecté ou aucun n'est ouvert).

Le trajet : trois devis acceptés (deux ravalements, une réparation « autre »), une charge de matériel prêt de M6 par
devis, les adresses confirmées, un plan proposé par `m4_proposer_cedule` (deux jours de quart), puis la météo du plan :

  * sans prévision ni fournisseur ouvert : chaque créneau est INCONNU (jamais ok), sans aucune connexion ;
  * prévision saisie calme : ok ; prévision saisie de vent fort le jour des ravalements : BLOQUANT, report proposé
    (motif `meteo`, jamais appliqué) et cédule relancée pour les jours restants ;
  * lecture seule : le registre ne change pas d'un octet, deux appels donnent le même résultat ;
  * les arguments de la cédule relancée, rejoués à `m4_proposer_cedule`, donnent le MÊME `plan_id` que l'aperçu ;
  * un fournisseur en panne : inconnu ; un autre nom que le sien : refusé ; l'employé : refusé.

Données fictives (`fictif: true`) : personnes, adresses, prévisions et seuils de test, aucune entreprise réelle.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import socket
from pathlib import Path

import pytest
import yaml
from m4_field_ops import etats
from m4_field_ops import outils as outils_m4
from m4_field_ops import registre as registre_m4
from m4_field_ops.meteo import CODE_FOURNISSEUR_INDISPONIBLE
from m4_field_ops.outils import outils

from opsys import cli, contexte, evenements, identite, jetons, politiques, stockage, taxonomie
from opsys import meteo as meteo_entreprise
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
_FIXTURES = Path(__file__).parent / "fixtures"
SCENARIO = json.loads((_FIXTURES / "scenario_cedule_repentigny_joliette.json").read_text(encoding="utf-8"))
EQUIPES = json.loads((_FIXTURES / "equipes_repentigny_joliette.json").read_text(encoding="utf-8"))
M4, M6 = "m04-field-ops", "m06-material-control"
HORODATAGE = "2030-01-01T00:00:00+00:00"
ACCEPTE_LE = "2030-01-01T10:00:00-05:00"
DEBUT_BUS = dt.datetime(2030, 1, 2, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
LEADS_DU_TEST = ("L-E2E-01", "L-E2E-02", "L-E2E-10")  # ravalement, autre, ravalement
LEADS = {lead["lead_id"]: lead for lead in SCENARIO["leads"]}
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="luc.fictif", role="employee")
CALENDRIER = {"0": "2026-10-05", "1": "2026-10-06"}
PERSONNES = (
    ("admin.fictif", ["admin"]),
    ("luc.fictif", ["employee"]),
    ("marc.fictif", ["employee"]),
    ("nadia.fictif", ["employee"]),
)
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
        "autre": {"seuils": {"vent_kmh": {"blocage": 60}}, "sans_objet": ["pluie", "gel", "verglas", "chaleur"]},
        "extension": {"sans_objet": list(meteo_entreprise.RISQUES)},
        "isolation_thermique": {"sans_objet": list(meteo_entreprise.RISQUES)},
        "renovation_totale": {"sans_objet": list(meteo_entreprise.RISQUES)},
    },
}


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(EQUIPES["services_propres"])
    with stockage.transaction() as cnx:
        for identifiant, roles in PERSONNES:
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", roles)
    yield tmp_path
    stockage.liberer()


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket : un fournisseur en panne est INJECTÉ, jamais une vraie connexion coupée."""


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _maillons():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons(M4, "principal")).lire()


def _octets(objet) -> str:
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


def _declarer(dossier: Path, commande: str, profil: dict) -> None:
    fichier = dossier / f"{commande}-declare.yaml"
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main([commande, "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


def _profil_equipes_deux_jours() -> dict:
    """Le profil de la démonstration Repentigny-Joliette, avec DEUX jours de quart (0 et 1) : la cédule relancée a un
    jour restant où replacer les chantiers dont le jour 0 est fermé par la météo."""
    profil = copy.deepcopy(EQUIPES["profil"])
    for equipe in profil["liste"]:
        equipe["quarts"] = [{"jour": jour, "debut_min": 480, "fin_min": 1020} for jour in (0, 1)]
    profil["fenetre_par_defaut"]["jours"] = [0, 1]
    return profil


def _charge_pret(devis_id):
    ligne = {
        "materiau_id": "gouttiere-fictive",
        "unite": "pi",
        "quantite_besoin": "10",
        "quantite_reservee": "10",
        "quantite_manquante": "0",
    }
    return {
        "evenement_id": f"m6-materiel-pret-{devis_id}-1",
        "devis_id": devis_id,
        "chantier_id": None,
        "revision": 1,
        "statut": "pret",
        "reservation_active": True,
        "declencheur": "devis_accepte",
        "horodatage": "2030-01-01T12:00:00-05:00",
        "lignes": [ligne],
        "lignes_manquantes": [],
    }


def _naitre(leads=LEADS_DU_TEST) -> dict[str, str]:
    """Un devis accepté et sa charge de matériel prêt par lead : ``{lead_id: intervention_id}``, livrés à M4 par le
    bus."""
    for lead_id in leads:
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
                "horodatage": HORODATAGE,
                "signal_id": f"sms:{lead_id}",
            },
            evenement_id=f"m1-lead-qualifie-{lead_id}",
        )
        devis_id = f"DEVIS-{lead_id}"
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
                        "description": "Travaux (fictif)",
                        "quantite": "1",
                        "unite": "forfait",
                        "prix_unitaire": "100.00",
                        "prix_ligne": "100.00",
                        "reference_besoin_materiau": None,
                    }
                ],
                "cout_total": "80.00",
                "prix_total": "100.00",
                "taux_marge": "0.25",
                "horodatage_acceptation": ACCEPTE_LE,
            },
            evenement_id=f"m3-devis-accepte-{devis_id}",
        )
        evenements.publier(
            "m6.materiel_pret", M6, _charge_pret(devis_id), evenement_id=_charge_pret(devis_id)["evenement_id"]
        )
    deps = {M4: charger_departements()[M4]}
    total = {"livres": 0, "echecs": 0, "quarantaines": 0}
    for tour in range(4):
        resume = evenements.repartir(deps, maintenant=(DEBUT_BUS + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    # un devis accepté et une charge de matériel prêt par lead
    assert total["echecs"] == 0 and total["quarantaines"] == 0 and total["livres"] == 2 * len(leads), total
    with stockage.transaction():
        liste = etats.lister_interventions(
            registre_m4.Registre(stockage.maillons(M4, "principal")), statut="a_planifier"
        )
    par_lead = {ligne["lead_id"]: ligne["intervention_id"] for ligne in liste}
    assert sorted(par_lead) == sorted(leads)
    return par_lead


def _confirmer_les_positions(par_nom, leads=LEADS_DU_TEST) -> None:
    for lead_id in leads:
        lead = LEADS[lead_id]
        _resultat(
            _appeler(
                par_nom,
                "m4_confirmer_localisation",
                {
                    "chantier_id": lead_id,
                    "action": "confirmee",
                    "horodatage": HORODATAGE,
                    "confirme_par": "admin.fictif",
                    "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": lead["secteur"]},
                    "source": "manuel",
                    "motif": "",
                    "latitude_microdegres": lead["latitude_microdegres"],
                    "longitude_microdegres": lead["longitude_microdegres"],
                },
            )
        )


@pytest.fixture
def monde(instance, par_nom):
    """Profils déclarés, trois interventions prêtes, adresses confirmées, un plan proposé sur deux jours."""
    _declarer(instance, "equipes", _profil_equipes_deux_jours())
    _declarer(instance, "meteo", METEO)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE}))
    assert proposition["non_cedulees"] == [] and proposition["non_pretes"] == []
    visites = {
        v["chantier"]: (r["jour"], v["debut_min"], v["fin_min"]) for r in proposition["plan"] for v in r["visites"]
    }
    assert sorted(visites) == sorted(interventions.values())
    # Le plan est déterministe (le solveur, les profils, le registre) : L-E2E-01 (ravalement) et L-E2E-02 (réparation)
    # le jour 0, L-E2E-10 (ravalement) le jour 1. Si le solveur change, ce constat le dit avant tout autre test.
    assert (
        visites[interventions["L-E2E-01"]][0],
        visites[interventions["L-E2E-02"]][0],
        visites[interventions["L-E2E-10"]][0],
    ) == (0, 0, 1), visites
    return {
        "interventions": interventions,
        "plan_id": proposition["plan_id"],
        "visites": visites,
        "ravalements": {interventions["L-E2E-01"], interventions["L-E2E-10"]},
    }


@pytest.fixture
def monde_complet(instance, par_nom):
    """Les six chantiers de la démonstration Repentigny-Joliette : un plan assez gros pour que la réponse de la météo
    doive être résumée avant d'être rendue à un appareil."""
    _declarer(instance, "equipes", _profil_equipes_deux_jours())
    _declarer(instance, "meteo", METEO)
    interventions = _naitre(tuple(LEADS))
    _confirmer_les_positions(par_nom, tuple(LEADS))
    proposition = _resultat(_appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE}))
    assert proposition["non_cedulees"] == [] and proposition["non_pretes"] == []
    assert sum(len(r["visites"]) for r in proposition["plan"]) == 6
    return {"interventions": interventions, "plan_id": proposition["plan_id"]}


# -- prévisions saisies -----------------------------------------------------------------------------
def _saisie(auteur="admin.fictif", dates_vent_fort=(), vent=55):
    points = []
    for date in CALENDRIER.values():
        for heure in range(6, 21):
            point = {**CALME, "heure": f"{date}T{heure:02d}:00"}
            if date in dates_vent_fort:
                point["vent_kmh"] = vent
            points.append(point)
    return {
        "saisi_par": auteur,
        "source": "Bulletin fictif du 4 octobre, 18 h",
        "emise_le": "2026-10-04T18:00:00-04:00",
        "points": points,
    }


def _verifier(par_nom, plan_id, saisie=None, identite_appelante=ADMIN, calendrier=None):
    arguments = {"plan_id": plan_id, "calendrier": CALENDRIER if calendrier is None else calendrier}
    if saisie is not None:
        arguments["previsions_saisies"] = saisie
    return _appeler(par_nom, "m4_verifier_meteo_creneau", arguments, identite_appelante)


def _date_du_jour(jour):
    return CALENDRIER[str(jour)]


# =========================================================================================
# 1. L'outil : T0, réservé à l'admin, décrit
# =========================================================================================
def test_l_outil_est_de_lecture_t0_reserve_a_l_admin_et_sa_description_tient_dans_la_limite(par_nom):
    outil = par_nom["m4_verifier_meteo_creneau"]
    assert outil.autonomie.name == "T0" and outil.roles_appareil == frozenset({"admin"})
    assert not politiques.approbation_requise_niveau(outil.niveau_effectif, "ombre")
    assert len(outil.description) <= 1024
    assert outil.parametres["required"] == ["plan_id", "calendrier"]
    assert set(outil.parametres["properties"]) == {"plan_id", "calendrier", "previsions_saisies", "jours"}
    assert "jamais appliqué" in outil.description and "N3" in outil.description


# =========================================================================================
# 2. Sans prévision ni fournisseur ouvert : inconnu, jamais ok, aucun réseau
# =========================================================================================
def test_sans_prevision_ni_fournisseur_ouvert_chaque_creneau_est_inconnu_jamais_ok(par_nom, monde):
    resultat = _resultat(_verifier(par_nom, monde["plan_id"]))
    assert resultat["statut"] == "inconnu" and resultat["plan_id"] == monde["plan_id"]
    assert len(resultat["creneaux"]) == 3
    for creneau in resultat["creneaux"]:
        assert creneau["statut"] == "inconnu" and creneau["regles"] == [] and creneau["prevision"] is None
        assert creneau["cause"]["code"] == "REJ-METEO-FOURNISSEUR-FERME"
        assert "aucun fournisseur météo n'est ouvert" in creneau["cause"]["detail"]
    assert resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None and resultat["a_valider"] == []
    assert resultat["attributions"] == []


def test_un_service_sans_regle_reste_inconnu_meme_avec_une_prevision_calme(instance, par_nom, monde):
    partiel = copy.deepcopy(METEO)
    del partiel["services"]["autre"]
    _declarer(instance, "meteo", partiel)
    resultat = _resultat(_verifier(par_nom, monde["plan_id"], _saisie()))
    par_intervention = {c["intervention_id"]: c for c in resultat["creneaux"]}
    autre = par_intervention[monde["interventions"]["L-E2E-02"]]
    assert autre["statut"] == "inconnu" and "seuil à configurer" in autre["cause"]["detail"]
    assert "'autre'" in autre["cause"]["detail"]
    ravalement = par_intervention[monde["interventions"]["L-E2E-01"]]
    assert ravalement["statut"] == "ok"
    assert resultat["statut"] == "inconnu", "le pire des créneaux : un seul inconnu suffit"


# =========================================================================================
# 3. Prévision saisie : ok, puis bloquant avec report proposé et cédule relancée
# =========================================================================================
def test_une_prevision_saisie_calme_rend_chaque_creneau_ok_et_cite_l_auteur_la_source_et_l_heure(par_nom, monde):
    resultat = _resultat(_verifier(par_nom, monde["plan_id"], _saisie()))
    assert resultat["statut"] == "ok" and resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None
    for creneau in resultat["creneaux"]:
        assert creneau["statut"] == "ok" and creneau["date"] == _date_du_jour(creneau["jour"])
        citation = creneau["prevision"]
        assert citation["source"] == "saisie_manuelle" and citation["saisi_par"] == "admin.fictif"
        assert citation["reference"] == "Bulletin fictif du 4 octobre, 18 h"
        assert citation["emise_le"] == "2026-10-04T18:00:00-04:00", "l'heure de la prévision, jamais l'horloge de M4"


def test_un_vent_fort_le_jour_0_bloque_le_ravalement_de_ce_jour_propose_le_report_et_relance_la_cedule(par_nom, monde):
    premier, second, autre_jour = (monde["interventions"][lead] for lead in ("L-E2E-01", "L-E2E-02", "L-E2E-10"))
    resultat = _resultat(_verifier(par_nom, monde["plan_id"], _saisie(dates_vent_fort=[_date_du_jour(0)])))
    par_intervention = {c["intervention_id"]: c for c in resultat["creneaux"]}
    bloque = par_intervention[premier]
    assert bloque["statut"] == "bloquant" and bloque["service"] == "ravalement" and bloque["date"] == "2026-10-05"
    assert any("vent" in r["detail"] and r["statut"] == "bloquant" for r in bloque["regles"])
    assert par_intervention[second]["statut"] == "ok", (
        "55 km/h ne dépasse pas le seuil de blocage de 60 km/h de la réparation"
    )
    assert par_intervention[autre_jour]["statut"] == "ok", "le jour 1 est calme : ce ravalement tient"
    assert resultat["statut"] == "bloquant"

    # le report proposé : un motif, un jour, jamais fait ici ; a_planifier n'a pas de transition de report
    (report,) = resultat["reports_proposes"]
    assert (report["intervention_id"], report["motif"], report["jour"]) == (premier, "meteo", 0)
    assert report["statut_intervention"] == "a_planifier" and report["geste"] is None
    assert "fenêtre" in report["explication"] and report["regles_franchies"]

    # la cédule relancée : le jour 0 est fermé pour le SERVICE ravalement (les deux chantiers), un aperçu, rien de rangé
    relance = resultat["cedule_relancee"]
    assert (
        relance["statut"] == "apercu" and relance["jours_retires"] == {"ravalement": [0]} and relance["exclues"] == []
    )
    jours = {c["intervention_id"]: c["fenetre"]["jours"] for c in relance["arguments"]["chantiers"]}
    assert jours == {premier: [1], autre_jour: [1], second: [0, 1]}
    visites = {v["chantier"]: r["jour"] for r in relance["apercu"]["plan"] for v in r["visites"]}
    assert visites[premier] == visites[autre_jour] == 1
    assert relance["apercu"]["deja_proposee"] is False and relance["apercu"]["non_cedulees"] == []


def test_un_vent_fort_les_deux_jours_ferme_les_deux_ravalements_et_le_dit_sans_relancer_ce_qui_ne_se_replace_pas(
    par_nom,
    monde,
):
    resultat = _resultat(_verifier(par_nom, monde["plan_id"], _saisie(dates_vent_fort=list(CALENDRIER.values()))))
    assert sorted(r["intervention_id"] for r in resultat["reports_proposes"]) == sorted(monde["ravalements"])
    relance = resultat["cedule_relancee"]
    assert relance["jours_retires"] == {"ravalement": [0, 1]}
    assert sorted(e["raison"] for e in relance["exclues"]) == ["sans_jour_restant", "sans_jour_restant"]
    assert [c["intervention_id"] for c in relance["arguments"]["chantiers"]] == [monde["interventions"]["L-E2E-02"]]


def test_les_reglages_du_profil_de_la_cedule_relancee_sont_ceux_du_plan_propose(par_nom, monde):
    resultat = _resultat(_verifier(par_nom, monde["plan_id"], _saisie(dates_vent_fort=[_date_du_jour(0)])))
    relance = resultat["cedule_relancee"]
    plan = next(m for m in _maillons() if m["type_entree"] == "cedule_proposee")
    assert relance["arguments"]["moteur"] == plan["moteur"], "le moteur du plan proposé, pas un autre"
    assert sorted(relance["arguments"]["intervention_ids"]) == sorted(monde["interventions"].values())
    assert set(relance["arguments"]) == {"intervention_ids", "chantiers", "moteur"}


# =========================================================================================
# 4. Lecture seule, déterminisme, arguments rejouables
# =========================================================================================
def test_l_outil_n_ecrit_rien_deux_appels_donnent_le_meme_resultat(par_nom, monde):
    saisie = _saisie(dates_vent_fort=[_date_du_jour(0)])
    avant = _octets(_maillons())
    premier = _resultat(_verifier(par_nom, monde["plan_id"], saisie))
    assert _octets(_maillons()) == avant, "le registre n'a pas bougé d'un octet, aperçu de la relance compris"
    second = _resultat(_verifier(par_nom, monde["plan_id"], saisie))
    assert _octets(premier) == _octets(second)
    assert _octets(_maillons()) == avant
    types = [m["type_entree"] for m in _maillons()]
    assert types.count("cedule_proposee") == 1 and "cedule_appliquee" not in types


def test_les_arguments_de_la_cedule_relancee_rejoues_donnent_le_meme_plan_id_que_l_apercu(par_nom, monde):
    relance = _resultat(_verifier(par_nom, monde["plan_id"], _saisie(dates_vent_fort=[_date_du_jour(0)])))[
        "cedule_relancee"
    ]
    rejouee = _resultat(_appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, **relance["arguments"]}))
    assert rejouee["plan_id"] == relance["apercu"]["plan_id"] != monde["plan_id"]
    assert rejouee["deja_proposee"] is False
    assert _octets(rejouee["plan"]) == _octets(relance["apercu"]["plan"])
    types = [m["type_entree"] for m in _maillons()]
    assert types.count("cedule_proposee") == 2 and "cedule_appliquee" not in types, "proposée, jamais appliquée"
    # la seconde proposition ne change pas l'état des interventions : rien n'est assigné
    with stockage.transaction():
        registre = registre_m4.Registre(stockage.maillons(M4, "principal"))
        assert {etats.statut_courant(registre, i) for i in monde["interventions"].values()} == {"a_planifier"}


def test_la_reponse_ne_porte_ni_coordonnee_ni_prix_ni_contact(par_nom, monde):
    texte = json.dumps(
        _resultat(_verifier(par_nom, monde["plan_id"], _saisie(dates_vent_fort=[_date_du_jour(0)]))), ensure_ascii=False
    )
    for interdit in (
        "latitude",
        "longitude",
        "microdegres",
        "Client Fictif",
        "5145550142",
        "prix",
        "montant",
        "45735000",
        "-73455000",
        "rue Fictive",
    ):
        assert interdit not in texte, interdit


# =========================================================================================
# 5. Refus : identité, rôle, plan, calendrier, saisie
# =========================================================================================
def test_le_nom_de_la_saisie_doit_etre_celui_de_la_personne_authentifiee(par_nom, monde):
    reponse = _verifier(par_nom, monde["plan_id"], _saisie(auteur="marc.fictif"))
    assert _code_refus(reponse) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"


def test_l_employe_n_a_pas_de_portee_sur_la_meteo_d_un_plan(par_nom, monde):
    reponse = _verifier(par_nom, monde["plan_id"], _saisie(auteur="luc.fictif"), identite_appelante=EMPLOYE)
    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"


@pytest.mark.parametrize(
    "saisie",
    [
        {"saisi_par": "admin.fictif", "source": "x", "emise_le": "2026-10-04T18:00:00-04:00", "points": "beau"},
        {"saisi_par": "admin.fictif", "source": "", "emise_le": "2026-10-04T18:00:00-04:00", "points": []},
        {"saisi_par": "admin.fictif", "source": "x", "emise_le": "hier soir", "points": []},
        {"saisi_par": "admin.fictif", "source": "x", "emise_le": "2026-10-04T18:00:00-04:00"},
    ],
)
def test_une_saisie_mal_formee_est_refusee_et_n_ecrit_rien(par_nom, monde, saisie):
    avant = _octets(_maillons())
    assert _code_refus(_verifier(par_nom, monde["plan_id"], saisie)) == "REJ-CONTRAT-INVALIDE"
    assert _octets(_maillons()) == avant


def test_un_plan_inconnu_est_refuse(par_nom, monde):
    assert _code_refus(_verifier(par_nom, "plan-inexistant")) == "REJ-CEDULE-PLAN-INTROUVABLE"


@pytest.mark.parametrize("calendrier", [{}, {"lundi": "2026-10-05"}, {"0": "2026-02-30"}, {"0": "5 octobre"}])
def test_un_calendrier_absent_ou_mal_forme_est_refuse(par_nom, monde, calendrier):
    code = _code_refus(_verifier(par_nom, monde["plan_id"], calendrier=calendrier))
    assert code in {"REJ-CHAMP-MANQUANT", "REJ-CONTRAT-INVALIDE"}


def test_un_jour_du_plan_sans_date_est_inconnu_jamais_devine(par_nom, monde):
    resultat = _resultat(_verifier(par_nom, monde["plan_id"], _saisie(), calendrier={"1": "2026-10-06"}))
    jour_zero = [c for c in resultat["creneaux"] if c["jour"] == 0]
    assert jour_zero and all(c["statut"] == "inconnu" and c["date"] is None for c in jour_zero)
    assert "pas de date dans le calendrier" in json.dumps(jour_zero[0], ensure_ascii=False)


# =========================================================================================
# 6. Un fournisseur en panne : inconnu, jamais ok
# =========================================================================================
class FournisseurEnPanne:
    """Un fournisseur du port qui répond toujours « indisponible » : ni réseau ni horloge."""

    def descripteur(self):
        return {"fournisseur": "panne_fictive"}

    def previsions(self, lieu, date_debut, date_fin):
        return None, {
            "code": CODE_FOURNISSEUR_INDISPONIBLE,
            "detail": "fournisseur fictif indisponible (panne simulée)",
        }


def test_un_fournisseur_en_panne_rend_inconnu_avec_la_cause_jamais_ok(instance, monde):
    en_panne = {o.nom: o for o in outils(fournisseur_meteo=FournisseurEnPanne())}
    resultat = _resultat(_verifier(en_panne, monde["plan_id"]))
    assert resultat["statut"] == "inconnu"
    for creneau in resultat["creneaux"]:
        assert creneau["statut"] == "inconnu"
        assert CODE_FOURNISSEUR_INDISPONIBLE in json.dumps(creneau, ensure_ascii=False)
    assert resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None


def test_la_saisie_a_la_main_l_emporte_sur_un_fournisseur_en_panne(instance, monde):
    en_panne = {o.nom: o for o in outils(fournisseur_meteo=FournisseurEnPanne())}
    resultat = _resultat(_verifier(en_panne, monde["plan_id"], _saisie()))
    assert resultat["statut"] == "ok"
    assert {c["prevision"]["source"] for c in resultat["creneaux"]} == {"saisie_manuelle"}


def test_un_fournisseur_ouvert_par_le_profil_dont_le_reseau_est_coupe_rend_inconnu_jamais_ok(
    instance,
    par_nom,
    monde,
    monkeypatch,
):
    """Le profil ouvre MSC GeoMet ; le réseau est coupé (la connexion échoue, aucune n'aboutit) : chaque créneau est
    inconnu avec la cause, jamais ok, jamais une valeur devinée."""
    profil = copy.deepcopy(METEO)
    profil["fournisseur"] = "msc_geomet"
    _declarer(instance, "meteo", profil)

    def coupure(*_args, **_kwargs):
        raise OSError("réseau coupé (simulé par le test)")

    monkeypatch.setattr(socket, "create_connection", coupure)
    resultat = _resultat(_verifier(par_nom, monde["plan_id"]))
    assert resultat["statut"] == "inconnu"
    assert {c["statut"] for c in resultat["creneaux"]} == {"inconnu"}
    assert CODE_FOURNISSEUR_INDISPONIBLE in json.dumps(resultat["creneaux"], ensure_ascii=False)
    assert resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None


# =========================================================================================
# 7. Le volet météo de la préparation, par le vrai outil
# =========================================================================================
def test_le_volet_meteo_de_la_preparation_est_verifiable_par_le_vrai_outil(par_nom, monde):
    for identifiant in monde["interventions"].values():
        verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": identifiant}))
        assert verdict["volets"]["meteo"]["statut"] == "ok" and verdict["volets"]["materiel"]["statut"] == "ok"
        assert verdict["pret"] is True and verdict["a_fournir"] == []


def test_la_preparation_suit_le_profil_meteo_declare_sans_le_garder(instance, par_nom, monde):
    identifiant = monde["interventions"]["L-E2E-01"]
    partiel = copy.deepcopy(METEO)
    del partiel["services"]["ravalement"]
    _declarer(instance, "meteo", partiel)
    verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": identifiant}))
    assert verdict["pret"] is False and verdict["volets"]["meteo"]["statut"] == "manque"
    assert "seuil à configurer pour le service 'ravalement'" in verdict["volets"]["meteo"]["manque"]


# =========================================================================================
# 8. La réponse tient dans une réponse d'appareil (6 000 caractères), sinon elle est résumée, puis refusée
# =========================================================================================
def _taille(reponse) -> int:
    return len(json.dumps(reponse, ensure_ascii=False))


def test_la_reponse_d_un_plan_bloquant_tient_dans_une_reponse_d_appareil_et_cite_les_valeurs_jugees(par_nom, monde):
    reponse = _verifier(par_nom, monde["plan_id"], _saisie(dates_vent_fort=[_date_du_jour(0)]))
    assert _taille(reponse) < 6000, "au-delà, l'appareil recevrait un aperçu tronqué"
    resultat = _resultat(reponse)
    assert len(resultat["creneaux"]) + sum(j["nombre"] for j in resultat.get("ok_resume", [])) == 3
    bloque = next(c for c in resultat["creneaux"] if c["statut"] == "bloquant")
    assert [r["detail"] for r in bloque["regles"] if r["statut"] == "bloquant"] == [
        "vent_kmh : 55 km/h à 08:00, blocage >= 40"
    ], "le créneau à regarder garde toujours le détail de ses règles"
    assert set(bloque["prevision"]) == {"source", "emise_le", "heure_type", "saisi_par", "reference"}, (
        "citée, sans les points horaires"
    )
    for creneau in resultat["creneaux"]:
        assert "points" not in json.dumps(creneau) and all(
            set(r) == {"risque", "statut", "detail"} for r in creneau.get("regles", [])
        )
    if "detail_reduit" in resultat:
        assert all("regles" not in c for c in resultat["creneaux"] if c["statut"] == "ok"), resultat["detail_reduit"]


def test_jours_ne_juge_que_les_creneaux_de_ces_jours_et_la_relance_garde_tous_les_chantiers(par_nom, monde):
    arguments = {
        "plan_id": monde["plan_id"],
        "calendrier": CALENDRIER,
        "jours": [0],
        "previsions_saisies": _saisie(dates_vent_fort=[_date_du_jour(0)]),
    }
    resultat = _resultat(_appeler(par_nom, "m4_verifier_meteo_creneau", arguments))
    assert {c["jour"] for c in resultat["creneaux"]} == {0} and len(resultat["creneaux"]) == 2
    assert resultat["statut"] == "bloquant"
    assert len(resultat["cedule_relancee"]["arguments"]["chantiers"]) == 3, "tous les chantiers du plan sont replacés"
    jour_un = _resultat(_appeler(par_nom, "m4_verifier_meteo_creneau", {**arguments, "jours": [1]}))
    assert {c["jour"] for c in jour_un["creneaux"]} == {1} and jour_un["statut"] == "ok"
    assert jour_un["cedule_relancee"] is None


@pytest.mark.parametrize("jours", [[], "0", [-1], [1.5], [True], ["0"]])
def test_des_jours_mal_formes_sont_refuses_et_n_ecrivent_rien(par_nom, monde, jours):
    avant = _octets(_maillons())
    reponse = _appeler(
        par_nom, "m4_verifier_meteo_creneau", {"plan_id": monde["plan_id"], "calendrier": CALENDRIER, "jours": jours}
    )
    assert reponse["ok"] is False or _code_refus(reponse) == "REJ-CONTRAT-INVALIDE"
    assert _octets(_maillons()) == avant


def test_un_jour_absent_du_plan_est_refuse_avec_les_jours_du_plan(par_nom, monde):
    reponse = _appeler(
        par_nom, "m4_verifier_meteo_creneau", {"plan_id": monde["plan_id"], "calendrier": CALENDRIER, "jours": [5]}
    )
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE"
    assert "jours du plan : [0, 1]" in reponse["resultat"]["verdict"]["detail"]


def test_un_gros_plan_est_resume_pour_tenir_dans_la_reponse_sans_cacher_un_creneau_a_regarder(par_nom, monde_complet):
    reponse = _verifier(par_nom, monde_complet["plan_id"], _saisie(dates_vent_fort=[_date_du_jour(0)]))
    assert _taille(reponse) < 6000, "au-delà, l'appareil recevrait un aperçu tronqué"
    resultat = _resultat(reponse)
    assert resultat["statut"] == "bloquant" and resultat["detail_reduit"]
    assert len(resultat["creneaux"]) + sum(j["nombre"] for j in resultat.get("ok_resume", [])) == 6
    bloques = [c for c in resultat["creneaux"] if c["statut"] == "bloquant"]
    assert bloques and all(c["regles"] for c in bloques), "ce qui bloque garde le détail de ses règles"
    assert sorted(r["intervention_id"] for r in resultat["reports_proposes"]) == sorted(
        c["intervention_id"] for c in bloques
    )


def test_la_limite_de_la_reponse_pilote_le_resume_et_le_refus(par_nom, monde_complet, monkeypatch):
    saisie = _saisie(dates_vent_fort=[_date_du_jour(0)])
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_METEO", 10**9)
    complet = _resultat(_verifier(par_nom, monde_complet["plan_id"], saisie))
    assert "detail_reduit" not in complet and len(complet["creneaux"]) == 6
    assert all("regles" in c for c in complet["creneaux"]) and "explication" in complet["reports_proposes"][0]
    # une limite plus serrée : le résumé le plus court qui tient, l'aperçu du plan relancé réduit à ses totaux
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_METEO", 5000)
    court = _resultat(_verifier(par_nom, monde_complet["plan_id"], saisie))
    assert "plan" not in court["cedule_relancee"]["apercu"] and "ok_resume" in court
    assert "explication" not in court["reports_proposes"][0]
    # une limite que rien ne peut tenir : refusé, avec la consigne, jamais tronqué
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_METEO", 300)
    refus = _verifier(par_nom, monde_complet["plan_id"], saisie)
    assert _code_refus(refus) == "REJ-CONTRAT-INVALIDE"
    assert "jours" in refus["resultat"]["verdict"]["detail"] and _taille(refus) < 1000


def test_la_limite_de_la_reponse_est_celle_de_l_appareil_moins_une_marge():
    assert outils_m4._LIMITE_REPONSE_METEO == jetons.LIMITE_SORTIE_DEFAUT - 500

