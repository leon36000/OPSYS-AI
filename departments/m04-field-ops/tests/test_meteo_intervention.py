"""PLAN T4.27-a (M4.10) : `meteo_creneaux.verifier_intervention`, pur, sur un registre EN MÉMOIRE, des positions
injectées, un profil météo injecté et un fournisseur fictif : aucune base, aucun réseau, aucune clé.

`m4_verifier_meteo_creneau` juge les créneaux d'un plan PROPOSÉ et exige son `plan_id` : le seul moyen d'en obtenir un
était de ranger une proposition (`m4_proposer_cedule` écrit). `verifier_intervention` juge le créneau d'UNE
intervention, sans `plan_id` : celui que le dernier plan APPLIQUÉ qui la place lui donne. Ce fichier prouve :

  * c'est la MÊME évaluation que `verifier` : le créneau rendu est identique, octet pour octet, à celui du plan, et
    `meteo.evaluer_creneau` reçoit les mêmes arguments ;
  * bloquant, validation requise, ok, inconnu : `inconnu` n'est JAMAIS `ok` (date, seuil, prévision, position,
    fournisseur, créneau absents) ;
  * un plan seulement proposé ne tient rien ; le dernier plan appliqué tient l'intervention ; une intervention
    reportée, à planifier ou planifiée à la main n'a aucun créneau : `creneaux` vide, statut `inconnu`, la cause dite ;
  * aucune écriture, aucun report ni cédule relancée, aucune coordonnée ni contact ni prix.

Le scénario par les vrais outils, le vrai bus et la porte d'appareil : `test_meteo_intervention_outil.py` et
`tests/e2e/test_lectures_admin_m4_appareil.py`. Tout est fictif (`fictif: true`) : Repentigny à Joliette, coordonnées
approximatives (`fixtures/tournees_repentigny_joliette.json`).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import (
    cedule_tournees,
    etats,
    materiel,
    meteo,
    meteo_creneaux,
    verdicts,
)
from m4_field_ops.registre import Registre

from opsys import meteo as meteo_entreprise

FICTIF = True
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tournees_repentigny_joliette.json").read_text("utf-8"))
SITES = {site["id"]: site for site in FIXTURE["sites"]}
HORODATAGE = "2030-01-01T00:00:00+00:00"
PARAMETRES = {
    "facteur_detour_milliemes": 1300,
    "vitesse_moyenne_kmh": 50,
    "marge_par_trajet_secondes": 600,
    "iterations": 300,
    "cout_non_cedule_m": 500000,
}
FENETRE = {"jours": [0, 1], "debut_min": 480, "fin_min": 1020}
CALENDRIER = {"0": "2026-10-05", "1": "2026-10-06"}
DATES = {0: "2026-10-05", 1: "2026-10-06"}
SERVICES = (("ch-01", "revetement"), ("ch-02", "revetement"), ("ch-10", "gouttieres"))

METEO = meteo_entreprise.normaliser_meteo(
    {
        "fuseau": "America/Toronto",
        "services": {
            "revetement": {
                "seuils": {
                    "vent_kmh": {"validation": 25, "blocage": 40},
                    "rafales_kmh": {"blocage": 60},
                    "pluie_mm_h": {"blocage": 3},
                    "gel_c": {"blocage": 0},
                    "verglas": {"blocage": True},
                    "chaleur_c": {"blocage": 35},
                }
            },
            "gouttieres": {
                "seuils": {
                    "vent_kmh": {"blocage": 50},
                    "rafales_kmh": {"blocage": 70},
                    "pluie_mm_h": {"blocage": 5},
                    "gel_c": {"blocage": 0},
                    "verglas": {"blocage": True},
                },
                "sans_objet": ["chaleur"],
            },
            "reparation": {"sans_objet": list(meteo_entreprise.RISQUES)},
            "soffite_fascia": {
                "seuils": {"vent_kmh": {"blocage": 45}},
                "sans_objet": ["pluie", "gel", "verglas", "chaleur"],
            },
        },
    }
)
METEO_SANS_REVETEMENT = meteo_entreprise.normaliser_meteo(
    {
        "fuseau": "America/Toronto",
        "services": {code: regles for code, regles in METEO["services"].items() if code != "revetement"},
    }
)
CALME = {
    "temperature_c": 12,
    "vent_kmh": 10,
    "rafales_kmh": 20,
    "precipitation_mm_h": 0,
    "probabilite_precipitation_pct": 10,
    "verglas": False,
}


def _profil_equipes():
    depot = {
        site: {
            "id": site,
            "latitude_microdegres": SITES[site]["latitude_microdeg"],
            "longitude_microdegres": SITES[site]["longitude_microdeg"],
        }
        for site in ("depot-repentigny", "depot-joliette")
    }
    quarts = [{"jour": 0, "debut_min": 480, "fin_min": 1020}, {"jour": 1, "debut_min": 480, "fin_min": 1020}]
    return {
        "liste": [
            {
                "id": "eq-a",
                "membres": ["membre-a.fictif"],
                "competences": ["gouttieres", "revetement"],
                "depot": depot["depot-repentigny"],
                "quarts": quarts,
            },
            {
                "id": "eq-b",
                "membres": ["membre-b.fictif"],
                "competences": ["gouttieres", "revetement"],
                "depot": depot["depot-joliette"],
                "quarts": quarts,
            },
        ],
        "services": {
            "gouttieres": {"duree_min": 90, "competences": ["gouttieres"]},
            "revetement": {"duree_min": 120, "competences": ["revetement"]},
            "reparation": {"duree_min": 60, "competences": []},
            "soffite_fascia": {"duree_min": 60, "competences": []},
        },
        "cedule": dict(PARAMETRES),
        "fenetre_par_defaut": dict(FENETRE),
    }


@pytest.fixture(autouse=True)
def _services(declarer_services):
    declarer_services()


# -- aides --------------------------------------------------------------------------------------------
def _lead(lead_id, service):
    return {
        "schema_version": 2,
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100"},
        "service": service,
        "ville": "Repentigny",
        "urgence_declaree": False,
        "canal": "texte",
    }


class Positions:
    """`lire_position(registre, lead_id)` fictif : les positions « confirmées » sont un dictionnaire."""

    def __init__(self, sites):
        self.sites = dict(sites)

    def __call__(self, registre, lead_id):
        site = self.sites.get(lead_id)
        if site is None:
            return None, verdicts.construire_verdict(
                "REJ-COORDONNEES-A-CONFIRMER", detail=f"coordonnées manquantes : à confirmer ({lead_id})"
            )
        return {
            "latitude_microdegres": site["latitude_microdeg"],
            "longitude_microdegres": site["longitude_microdeg"],
            "version": 1,
            "ligne_id": "x",
        }, None


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
        "horodatage": "2026-09-30T10:00:00-04:00",
        "lignes": [ligne],
        "lignes_manquantes": [],
    }


def _monde(services=SERVICES):
    registre = Registre()
    ids = {}
    for rang, (lead, service) in enumerate(services):
        accuse, verdict = etats.inscrire_depuis_devis(
            registre, f"DEVIS-{lead}", _lead(lead, service), "sel-fictif", f"2030-01-01T00:00:{rang:02d}+00:00"
        )
        assert verdict is None, verdict
        ids[lead] = accuse["intervention_id"]
        registre.ajouter(materiel.maillon_de_la_charge(_charge_pret(f"DEVIS-{lead}")))
    return registre, ids, Positions({lead: SITES[lead] for lead, _ in services})


def _lecteur_equipes():
    lecture = (_profil_equipes(), None)
    return lambda: lecture


def _lecteur_meteo(profil=METEO, verdict=None):
    lecture = (profil, verdict)
    return lambda: lecture


def _plan(registre, positions, arguments=None):
    resultat, verdict = cedule_tournees.proposer(
        registre,
        {} if arguments is None else arguments,
        positions,
        HORODATAGE,
        moteur="dp",
        lire_equipes=_lecteur_equipes(),
        lire_meteo=_lecteur_meteo(),
    )
    assert verdict is None, verdict
    return resultat


def _appliquer(registre, plan_id, positions):
    resultat, verdict = cedule_tournees.appliquer(
        registre,
        plan_id,
        positions,
        HORODATAGE,
        "admin.fictif",
        lire_equipes=_lecteur_equipes(),
        lire_meteo=_lecteur_meteo(),
    )
    assert verdict is None, verdict
    return resultat


def _monde_applique(services=SERVICES):
    """Un monde dont le plan a été proposé PUIS appliqué : les interventions sont planifiees, avec un créneau."""
    registre, ids, positions = _monde(services)
    plan = _plan(registre, positions)
    _appliquer(registre, plan["plan_id"], positions)
    return registre, ids, positions, plan


def _monde_applique_un():
    """Un seul revêtement, plan proposé puis appliqué."""
    return _monde_applique((("ch-01", "revetement"),))


class Fournisseur:
    """Fournisseur fictif du port : une prévision par date (`{date: {champ: valeur ou {heure: {...}}}}`), et la trace
    des appels."""

    def __init__(self, journees=None, verdict=None, attribution="Météo fictive (test), sans licence réelle"):
        self.journees = {} if journees is None else journees
        self.verdict = verdict
        self.attribution = attribution
        self.appels = []

    def descripteur(self):
        return {"fournisseur": "fictif"}

    def previsions(self, lieu, date_debut, date_fin):
        self.appels.append((dict(lieu), date_debut, date_fin))
        if self.verdict is not None:
            return None, self.verdict
        points = []
        for date in sorted(self.journees):
            spec = self.journees[date]
            for heure in range(24):
                valeurs = {**CALME, **{k: v for k, v in spec.items() if not isinstance(k, int)}, **spec.get(heure, {})}
                point = {champ: None for champ in meteo.CLES_POINT}
                point.update(valeurs)
                point["heure"] = f"{date}T{heure:02d}:00:00-04:00"
                points.append(point)
        return {
            "citation": {
                "source": "fournisseur-fictif",
                "emise_le": "2026-10-04T18:00:00-04:00",
                "heure_type": "heure_d_emission_saisie",
                "attribution": self.attribution,
            },
            "points": points,
        }, None


def _calme():
    return Fournisseur({"2026-10-05": {}, "2026-10-06": {}})


def _vent_fort_le(date, valeur=62):
    autre = "2026-10-06" if date == "2026-10-05" else "2026-10-05"
    return Fournisseur({date: {"vent_kmh": valeur, "rafales_kmh": valeur + 10}, autre: {}})


def _visite(plan, intervention_id):
    for route in plan["plan"]:
        for visite in route["visites"]:
            if visite["chantier"] == intervention_id:
                return route, visite
    raise AssertionError(intervention_id)


def _lire(
    registre,
    intervention_id,
    positions,
    fournisseur,
    date="2026-10-05",
    profil=METEO,
    verdict_profil=None,
    verdict_fournisseur=None,
):
    return meteo_creneaux.verifier_intervention(
        registre, intervention_id, date, positions, profil, verdict_profil, fournisseur, verdict_fournisseur
    )


def _resultat(couple):
    resultat, verdict = couple
    assert verdict is None, verdict
    return resultat


def _refuse(couple, code, morceau=""):
    resultat, verdict = couple
    assert resultat is None and verdict["code"] == code and morceau in verdict["detail"], (resultat, verdict)
    return verdict


def _octets(objet):
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


def _verifier_le_plan(registre, plan_id, positions, fournisseur, profil=METEO):
    return _resultat(
        meteo_creneaux.verifier(
            registre,
            plan_id,
            CALENDRIER,
            positions,
            profil,
            None,
            fournisseur,
            None,
            lire_equipes=_lecteur_equipes(),
            lire_meteo=_lecteur_meteo(profil),
        )
    )


# =========================================================================================
# 1. Le créneau d'une intervention placée par un plan appliqué, sans plan_id
# =========================================================================================
def test_une_intervention_placee_par_un_plan_applique_a_son_creneau_juge_sans_plan_id():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, visite = _visite(plan, ids["ch-01"])
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[route["jour"]]))
    assert resultat["statut"] == meteo.STATUT_OK and resultat["cause"] is None
    assert resultat["intervention_id"] == ids["ch-01"] and resultat["statut_intervention"] == "planifiee"
    assert resultat["plan_id"] == plan["plan_id"], "le plan qui tient le créneau est cité"
    (creneau,) = resultat["creneaux"]
    assert (creneau["equipe"], creneau["jour"], creneau["date"]) == (
        route["equipe"],
        route["jour"],
        DATES[route["jour"]],
    )
    assert (creneau["debut_min"], creneau["fin_min"]) == (visite["debut_min"], visite["fin_min"])
    assert creneau["service"] == "revetement" and creneau["plan_perime"] is False
    citation = creneau["prevision"]["citation"]
    assert citation["source"] == "fournisseur-fictif" and citation["emise_le"] == "2026-10-04T18:00:00-04:00"


def test_le_creneau_rendu_est_celui_de_verifier_octet_pour_octet_pour_chaque_intervention_du_plan():
    """La MÊME évaluation : pour chaque intervention du plan, le créneau de `verifier_intervention` est celui que
    `verifier` (avec un plan_id) donne, quel que soit le verdict (bloquant le jour venteux, ok l'autre jour)."""
    registre, ids, positions, plan = _monde_applique()
    jour_venteux = next(iter({route["jour"] for route in plan["plan"]}))
    fournisseur = _vent_fort_le(DATES[jour_venteux])
    du_plan = {
        c["intervention_id"]: c
        for c in _verifier_le_plan(registre, plan["plan_id"], positions, fournisseur)["creneaux"]
    }
    statuts = set()
    for identifiant in ids.values():
        route, _ = _visite(plan, identifiant)
        resultat = _resultat(
            _lire(registre, identifiant, positions, _vent_fort_le(DATES[jour_venteux]), DATES[route["jour"]])
        )
        assert _octets(resultat["creneaux"][0]) == _octets(du_plan[identifiant]), identifiant
        assert resultat["statut"] == du_plan[identifiant]["statut"]
        statuts.add(resultat["statut"])
    assert statuts <= {meteo.STATUT_OK, meteo.STATUT_BLOQUANT} and meteo.STATUT_BLOQUANT in statuts


def test_l_evaluation_est_celle_de_meteo_evaluer_creneau_avec_les_memes_arguments(monkeypatch):
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, visite = _visite(plan, ids["ch-01"])
    appels = []
    vraie = meteo.evaluer_creneau

    def espion(regles, previsions, date, debut_min, fin_min):
        appels.append((_octets(regles), _octets(previsions), date, debut_min, fin_min))
        return vraie(regles, previsions, date, debut_min, fin_min)

    monkeypatch.setattr(meteo, "evaluer_creneau", espion)
    _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[route["jour"]]))
    intervention = list(appels)
    appels.clear()
    plan_complet = _verifier_le_plan(registre, plan["plan_id"], positions, _calme())
    assert plan_complet["creneaux"] and len(intervention) == 1
    assert intervention[0] in appels, (
        "la même fonction, les mêmes règles, la même prévision, la même date et les mêmes minutes"
    )
    assert intervention[0][2:] == (DATES[route["jour"]], visite["debut_min"], visite["fin_min"])


def test_un_vent_fort_le_jour_du_creneau_bloque_et_cite_la_valeur_l_heure_et_le_seuil():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    assert resultat["statut"] == meteo.STATUT_BLOQUANT
    (creneau,) = resultat["creneaux"]
    bloquantes = [r for r in creneau["regles"] if r["statut"] == meteo.STATUT_BLOQUANT]
    assert {r["mesure"] for r in bloquantes} == {"vent_kmh", "rafales_kmh"}
    assert any("62 km/h" in r["detail"] and "blocage >= 40" in r["detail"] for r in bloquantes)
    assert resultat["creneaux"][0]["statut"] == resultat["statut"]


def test_un_vent_au_niveau_validation_demande_une_validation():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]], 30), DATES[route["jour"]])
    )
    assert resultat["statut"] == meteo.STATUT_VALIDATION


def test_le_jour_calme_de_la_date_donnee_est_ok_meme_si_un_autre_jour_est_venteux():
    """La date est celle du créneau : ce que la prévision dit d'un autre jour ne compte pas."""
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, _ = _visite(plan, ids["ch-01"])
    jour_calme = DATES[route["jour"]]
    autre = DATES[1 - route["jour"]]
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _vent_fort_le(autre), jour_calme))
    assert resultat["statut"] == meteo.STATUT_OK


def test_les_attributions_de_licence_sont_rendues_une_fois():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[route["jour"]]))
    assert resultat["attributions"] == [
        {"source": "fournisseur-fictif", "attribution": "Météo fictive (test), sans licence réelle"}
    ]
    sans = _resultat(
        _lire(
            registre,
            ids["ch-01"],
            positions,
            Fournisseur({"2026-10-05": {}, "2026-10-06": {}}, attribution=None),
            DATES[route["jour"]],
        )
    )
    assert sans["attributions"] == []


# =========================================================================================
# 2. inconnu n'est JAMAIS ok
# =========================================================================================
def test_sans_date_le_creneau_est_inconnu_la_date_n_est_jamais_devinee_et_rien_n_est_demande_au_fournisseur():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    fournisseur = _calme()
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, fournisseur, None))
    assert resultat["statut"] == meteo.STATUT_INCONNU
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU and creneau["date"] is None and creneau["regles"] == []
    assert creneau["cause"]["code"] == "REJ-CHAMP-MANQUANT" and "pas de date" in creneau["cause"]["detail"]
    assert fournisseur.appels == []
    assert resultat["plan_id"] == plan["plan_id"], "le créneau existe : seule sa date manque"


@pytest.mark.parametrize(
    "date", ["2026-02-30", "5 octobre", "", "2026-13-01", "26-10-05", 20261005, 5.0, ["2026-10-05"]]
)
def test_une_date_qui_n_existe_pas_est_refusee_sans_rien_deviner(date):
    registre, ids, positions, _ = _monde_applique((("ch-01", "revetement"),))
    _refuse(_lire(registre, ids["ch-01"], positions, _calme(), date), "REJ-CONTRAT-INVALIDE", "AAAA-MM-JJ")


def test_un_service_sans_regle_reste_inconnu_meme_avec_une_prevision_calme():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, _ = _visite(plan, ids["ch-01"])
    fournisseur = _calme()
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, fournisseur, DATES[route["jour"]], profil=METEO_SANS_REVETEMENT)
    )
    (creneau,) = resultat["creneaux"]
    assert resultat["statut"] == creneau["statut"] == meteo.STATUT_INCONNU
    assert "seuil à configurer" in creneau["cause"]["detail"] and "'revetement'" in creneau["cause"]["detail"]
    assert fournisseur.appels == []


def test_sans_profil_meteo_le_creneau_est_inconnu_avec_le_verdict_du_profil():
    registre, ids, positions, plan = _monde_applique((("ch-01", "revetement"),))
    route, _ = _visite(plan, ids["ch-01"])
    verdict = verdicts.construire_verdict("REJ-PROFIL-INVALIDE", detail="profil météo illisible (test)")
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _calme(), DATES[route["jour"]], profil=None, verdict_profil=verdict)
    )
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU
    assert creneau["cause"] == {"code": "REJ-PROFIL-INVALIDE", "detail": "profil météo illisible (test)"}


def test_sans_fournisseur_ouvert_le_creneau_est_inconnu_et_dit_quoi_faire():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, None, DATES[route["jour"]]))
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU and creneau["prevision"] is None
    assert creneau["cause"]["code"] == meteo.CODE_FOURNISSEUR_FERME
    assert "previsions_saisies" in creneau["cause"]["detail"] and "meteo declarer" in creneau["cause"]["detail"]


def test_le_verdict_de_fermeture_du_fournisseur_est_repris_tel_quel_comme_cause():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    ferme = meteo.verdict_meteo(meteo.CODE_FOURNISSEUR_FERME, "Open-Meteo fermé (test)")
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, None, DATES[route["jour"]], verdict_fournisseur=ferme)
    )
    assert resultat["creneaux"][0]["cause"] == {"code": ferme["code"], "detail": "Open-Meteo fermé (test)"}


def test_un_fournisseur_en_panne_donne_inconnu_avec_la_cause_jamais_ok():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    panne = meteo.verdict_meteo(meteo.CODE_FOURNISSEUR_INDISPONIBLE, "fournisseur fictif indisponible (panne simulée)")
    fournisseur = Fournisseur(verdict=panne)
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, fournisseur, DATES[route["jour"]]))
    (creneau,) = resultat["creneaux"]
    assert resultat["statut"] == creneau["statut"] == meteo.STATUT_INCONNU
    assert creneau["cause"]["code"] == meteo.CODE_FOURNISSEUR_INDISPONIBLE and creneau["prevision"] is None
    assert len(fournisseur.appels) == 1


def test_une_prevision_hors_du_port_donne_inconnu_avec_la_raison():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])

    class Bancal(Fournisseur):
        def previsions(self, lieu, date_debut, date_fin):
            return {"citation": {"source": "x"}, "points": []}, None

    resultat = _resultat(_lire(registre, ids["ch-01"], positions, Bancal(), DATES[route["jour"]]))
    assert resultat["statut"] == meteo.STATUT_INCONNU
    assert resultat["creneaux"][0]["cause"]["code"] == meteo.CODE_REPONSE_INVALIDE


def test_une_position_a_confirmer_rend_le_creneau_inconnu_avec_le_verdict_de_la_position():
    registre, ids, _, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    fournisseur = _calme()
    resultat = _resultat(_lire(registre, ids["ch-01"], Positions({}), fournisseur, DATES[route["jour"]]))
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU and creneau["prevision"] is None
    assert creneau["cause"]["code"] == "REJ-COORDONNEES-A-CONFIRMER" and fournisseur.appels == []


def test_un_lead_v1_place_par_un_plan_n_a_pas_de_service_donc_pas_de_regles_et_son_creneau_est_inconnu():
    registre = Registre()
    contrat = {
        "lead_id": "ch-01",
        "conversation_id": "C-v1",
        "type_travaux": "extension",
        "ville": "Repentigny",
        "canal": "telephone",
        "contact": {"nom": "Client Fictif"},
        "urgence_declaree": False,
    }
    marqueur = {
        "readiness_ok": True,
        "lead_id": "ch-01",
        "hash_tete_registre": None,
        "horodatage": HORODATAGE,
        "empreinte": "cd" * 32,
    }
    accuse, verdict = etats.inscrire_intervention(contrat, marqueur, registre, HORODATAGE, "sel-fictif")
    assert verdict is None
    positions = Positions({"ch-01": SITES["ch-01"]})
    plan = _plan(
        registre,
        positions,
        {
            "durees_par_type_travaux": {"extension": 120},
            "competences_par_type_travaux": {"extension": []},
            "chantiers": [
                {"intervention_id": accuse["intervention_id"], "fenetre": dict(FENETRE), "creneau_fige": None}
            ],
        },
    )
    _appliquer(registre, plan["plan_id"], positions)
    route, _ = _visite(plan, accuse["intervention_id"])
    fournisseur = _calme()
    resultat = _resultat(_lire(registre, accuse["intervention_id"], positions, fournisseur, DATES[route["jour"]]))
    (creneau,) = resultat["creneaux"]
    assert creneau["service"] is None and creneau["statut"] == meteo.STATUT_INCONNU
    assert "lead v1" in creneau["cause"]["detail"] and fournisseur.appels == []


# =========================================================================================
# 3. Ce qui tient un créneau : le dernier plan APPLIQUÉ, tant que l'intervention est planifiée ou en route
# =========================================================================================
def test_un_plan_seulement_propose_ne_tient_rien_l_intervention_n_a_aucun_creneau():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    route, _ = _visite(plan, ids["ch-01"])
    fournisseur = _calme()
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, fournisseur, DATES[route["jour"]]))
    assert resultat["creneaux"] == [] and resultat["statut"] == meteo.STATUT_INCONNU and resultat["plan_id"] is None
    assert resultat["statut_intervention"] == "a_planifier"
    assert resultat["cause"]["code"] == "REJ-CHAMP-MANQUANT" and "a_planifier" in resultat["cause"]["detail"]
    assert "m4_appliquer_cedule" in resultat["cause"]["detail"] and fournisseur.appels == []
    # le même plan, jugé avec son plan_id, a bien un créneau : c'est l'application qui manque, pas la proposition
    assert _verifier_le_plan(registre, plan["plan_id"], positions, _calme())["creneaux"]


def test_une_intervention_a_planifier_sans_plan_n_a_aucun_creneau_et_le_dit():
    registre, ids, positions = _monde()
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme()))
    assert resultat["creneaux"] == [] and resultat["statut"] == meteo.STATUT_INCONNU
    assert resultat["attributions"] == [] and resultat["plan_id"] is None
    assert "aucune cédule appliquée ne la place" in resultat["cause"]["detail"]


def test_une_intervention_planifiee_a_la_main_n_a_aucun_creneau_au_registre():
    registre = Registre()
    contrat = {
        "lead_id": "ch-01",
        "conversation_id": "C-main",
        "type_travaux": "extension",
        "ville": "Repentigny",
        "canal": "telephone",
        "contact": {"nom": "Client Fictif"},
        "urgence_declaree": False,
    }
    marqueur = {
        "readiness_ok": True,
        "lead_id": "ch-01",
        "hash_tete_registre": None,
        "horodatage": HORODATAGE,
        "empreinte": "cd" * 32,
    }
    accuse, verdict = etats.inscrire_intervention(contrat, marqueur, registre, HORODATAGE, "sel-fictif")
    assert verdict is None
    resultat = _resultat(_lire(registre, accuse["intervention_id"], Positions({}), _calme()))
    assert resultat["statut_intervention"] == "planifiee" and resultat["creneaux"] == []
    assert resultat["statut"] == meteo.STATUT_INCONNU
    assert "m4_planifier_intervention" in resultat["cause"]["detail"]


def test_une_intervention_reportee_a_quitte_son_creneau():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    _, verdict = etats.transitionner(ids["ch-01"], "reportee", registre, HORODATAGE, motif="meteo")
    assert verdict is None
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    assert resultat["statut_intervention"] == "reportee" and resultat["creneaux"] == []
    assert resultat["statut"] == meteo.STATUT_INCONNU and resultat["plan_id"] is None
    assert "reportee" in resultat["cause"]["detail"] and "quitté son créneau" in resultat["cause"]["detail"]


def test_une_intervention_en_route_garde_son_creneau():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    equipe = etats.technicien_assigne(registre, ids["ch-01"])
    _, verdict = etats.transitionner(
        ids["ch-01"],
        "en_route",
        registre,
        HORODATAGE,
        assignation={"intervention_id": ids["ch-01"], "technicien_id": equipe},
    )
    assert verdict is None
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    assert resultat["statut_intervention"] == "en_route" and resultat["statut"] == meteo.STATUT_BLOQUANT
    assert len(resultat["creneaux"]) == 1 and resultat["creneaux"][0]["statut_intervention"] == "en_route"


def test_le_dernier_plan_applique_qui_place_l_intervention_la_tient():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    premier = _plan(registre, positions)
    jour = next(iter({route["jour"] for route in premier["plan"]}))
    second = _plan(
        registre,
        positions,
        {
            "intervention_ids": [ids["ch-01"]],
            "chantiers": [
                {
                    "intervention_id": ids["ch-01"],
                    "creneau_fige": None,
                    "fenetre": {"jours": [1 - jour], "debut_min": 480, "fin_min": 1020},
                }
            ],
        },
    )
    assert second["plan_id"] != premier["plan_id"]
    _appliquer(registre, second["plan_id"], positions)
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[1 - jour]))
    assert resultat["plan_id"] == second["plan_id"], (
        "le plan appliqué tient l'intervention, pas le premier, resté proposé"
    )
    (creneau,) = resultat["creneaux"]
    assert creneau["jour"] == 1 - jour and creneau["plan_perime"] is False


def test_un_plan_applique_apres_un_autre_le_remplace_pour_l_intervention():
    """Deux plans appliqués qui placent la même intervention : le dernier appliqué la tient (`_plans_perimes`)."""
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    premier = _plan(registre, positions)
    _appliquer(registre, premier["plan_id"], positions)
    jour = next(iter({route["jour"] for route in premier["plan"]}))
    second = _plan(
        registre,
        positions,
        {
            "intervention_ids": [ids["ch-01"]],
            "chantiers": [
                {
                    "intervention_id": ids["ch-01"],
                    "creneau_fige": None,
                    "fenetre": {"jours": [1 - jour], "debut_min": 480, "fin_min": 1020},
                }
            ],
        },
    )
    _appliquer(registre, second["plan_id"], positions)
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[1 - jour]))
    assert resultat["plan_id"] == second["plan_id"] and resultat["creneaux"][0]["jour"] == 1 - jour


def test_un_plan_applique_dont_la_proposition_est_introuvable_ne_donne_aucun_creneau_jamais_un_creneau_devine():
    """Un registre incohérent (une application sans la proposition qu'elle applique, que `m4_appliquer_cedule` ne peut
    pas écrire) : la lecture ne devine ni jour ni minutes, elle dit qu'il n'y a aucun créneau."""
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    registre.ajouter(
        {
            "type_entree": etats.TYPE_TRANSITION,
            "intervention_id": ids["ch-01"],
            "statut": "planifiee",
            "horodatage": HORODATAGE,
        }
    )
    registre.ajouter(
        {
            "type_entree": cedule_tournees.TYPE_APPLIQUEE,
            "plan_id": "plan-sans-proposition",
            "horodatage": HORODATAGE,
            "assignations": [{"intervention_id": ids["ch-01"]}],
        }
    )
    fournisseur = _calme()
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, fournisseur, "2026-10-05"))
    assert resultat["statut_intervention"] == "planifiee"
    assert resultat["creneaux"] == [] and resultat["plan_id"] is None and resultat["statut"] == meteo.STATUT_INCONNU
    assert resultat["cause"]["code"] == "REJ-CHAMP-MANQUANT" and fournisseur.appels == []


# =========================================================================================
# 4. Refus : intervention inconnue ou hors des statuts d'avant le travail
# =========================================================================================
def test_une_intervention_inconnue_est_refusee():
    registre, _, positions = _monde()
    _refuse(_lire(registre, "intervention-fantome", positions, _calme()), "REJ-TRANSITION-ILLEGALE", "inexistante")


def test_un_registre_sans_inscription_pour_cet_identifiant_est_refuse_meme_avec_une_transition():
    """Un statut sans inscription (registre incohérent) ne fait pas une intervention : refus, jamais une exception."""
    registre, _, positions = _monde()
    registre.ajouter(
        {
            "type_entree": etats.TYPE_TRANSITION,
            "intervention_id": "sans-inscription",
            "statut": "planifiee",
            "horodatage": HORODATAGE,
        }
    )
    assert etats.statut_courant(registre, "sans-inscription") == "planifiee"
    _refuse(_lire(registre, "sans-inscription", positions, _calme()), "REJ-TRANSITION-ILLEGALE", "inexistante")


def test_la_date_est_validee_avant_la_lecture_du_registre():
    """Une date mal formée est refusée d'abord, quel que soit l'identifiant ; une date valide passe au registre."""
    registre, _, positions = _monde()
    _refuse(_lire(registre, "intervention-fantome", positions, _calme(), "5 octobre"), "REJ-CONTRAT-INVALIDE")
    _refuse(_lire(registre, "intervention-fantome", positions, _calme(), "2026-10-05"), "REJ-TRANSITION-ILLEGALE")


@pytest.mark.parametrize("statut", ["annulee", "sur_site", "en_revue", "completed_pending_review"])
def test_une_intervention_hors_des_statuts_d_avant_le_travail_est_refusee_avec_son_statut(statut):
    registre, ids, positions, plan = _monde_applique_un()
    identifiant = ids["ch-01"]
    equipe = etats.technicien_assigne(registre, identifiant)
    if statut == "annulee":
        assert etats.transitionner(identifiant, "annulee", registre, HORODATAGE)[1] is None
    else:
        _, verdict = etats.transitionner(
            identifiant,
            "en_route",
            registre,
            HORODATAGE,
            assignation={"intervention_id": identifiant, "technicien_id": equipe},
        )
        assert verdict is None
        assert etats.transitionner(identifiant, "sur_site", registre, HORODATAGE)[1] is None
        if statut == "en_revue":
            assert etats.transitionner(identifiant, "en_revue", registre, HORODATAGE)[1] is None
        if statut == "completed_pending_review":
            registre.ajouter(
                {
                    "type_entree": etats.TYPE_TRANSITION,
                    "intervention_id": identifiant,
                    "statut": statut,
                    "statut_precedent": "sur_site",
                    "horodatage": HORODATAGE,
                }
            )
    verdict = _refuse(_lire(registre, identifiant, positions, _calme()), "REJ-TRANSITION-ILLEGALE", "météo sans objet")
    assert verdict["statut"] == statut and statut in verdict["detail"]


def test_les_statuts_de_la_meteo_sont_ceux_d_avant_le_travail_et_connus_de_la_machine_a_etats():
    assert meteo_creneaux.STATUTS_METEO == ("a_planifier", "planifiee", "reportee", "en_route")
    assert meteo_creneaux.STATUTS_A_CRENEAU == ("planifiee", "en_route")
    assert set(meteo_creneaux.STATUTS_METEO) <= set(etats.ETATS)
    assert set(meteo_creneaux.STATUTS_A_CRENEAU) <= set(meteo_creneaux.STATUTS_METEO)


# =========================================================================================
# 5. Lecture pure : rien n'est écrit, ni report ni cédule relancée, ni coordonnée, ni contact, ni prix
# =========================================================================================
def test_la_lecture_n_ecrit_rien_le_registre_est_intact_meme_sous_un_vent_qui_bloque():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    avant = _octets(registre.lire())
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    assert resultat["statut"] == meteo.STATUT_BLOQUANT
    assert _octets(registre.lire()) == avant and registre.valider_chaine()
    assert etats.statut_courant(registre, ids["ch-01"]) == "planifiee", "aucun statut ne change"


def test_aucun_report_ni_cedule_relancee_n_est_propose():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    assert set(resultat) == {
        "intervention_id",
        "statut_intervention",
        "statut",
        "plan_id",
        "creneaux",
        "cause",
        "attributions",
    }
    for cle in ("reports_proposes", "cedule_relancee", "a_valider"):
        assert cle not in resultat


def test_le_resultat_est_deterministe_serialisable_et_sans_coordonnee_ni_contact_ni_prix():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    date = DATES[route["jour"]]
    premier = _resultat(_lire(registre, ids["ch-01"], positions, _vent_fort_le(date), date))
    second = _resultat(_lire(registre, ids["ch-01"], positions, _vent_fort_le(date), date))
    assert _octets(premier) == _octets(second)
    texte = json.dumps(premier, ensure_ascii=False)
    for site in SITES.values():
        for cle in ("latitude_microdeg", "longitude_microdeg"):
            assert str(site[cle]) not in texte and str(abs(site[cle])) not in texte, site["id"]
    for interdit in ("latitude", "longitude", "Client Fictif", "418-555-0100", "Repentigny", "prix", "montant"):
        assert interdit not in texte, interdit


def test_le_fournisseur_ne_recoit_qu_un_lieu_generalise_et_une_seule_demande():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    fournisseur = _calme()
    _resultat(_lire(registre, ids["ch-01"], positions, fournisseur, DATES[route["jour"]]))
    assert len(fournisseur.appels) == 1
    lieu, debut, fin = fournisseur.appels[0]
    assert meteo.est_lieu_generalise(lieu) and debut == fin == DATES[route["jour"]]


# =========================================================================================
# 6. La forme d'appareil : le créneau compact, sans les points horaires
# =========================================================================================
def test_la_vue_d_appareil_reduit_le_creneau_a_ses_regles_et_a_la_citation_de_la_prevision():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    avant = _octets(resultat)
    vue, verdict = meteo_creneaux.presenter_intervention(resultat, lambda v: True)
    assert verdict is None and _octets(resultat) == avant, "le résultat n'est pas modifié"
    (creneau,) = vue["creneaux"]
    assert "points" not in json.dumps(creneau) and set(creneau["prevision"]) == {"source", "emise_le", "heure_type"}
    assert all(set(r) == {"risque", "statut", "detail"} for r in creneau["regles"])
    assert [r["detail"] for r in creneau["regles"] if r["statut"] == "bloquant"][0].startswith("vent_kmh : 62 km/h")
    assert {cle: valeur for cle, valeur in vue.items() if cle != "creneaux"} == {
        cle: valeur for cle, valeur in resultat.items() if cle != "creneaux"
    }
    assert json.loads(json.dumps(vue)) == vue


def test_la_vue_d_appareil_qui_ne_tient_pas_est_refusee_jamais_tronquee():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[route["jour"]]))
    _refuse(meteo_creneaux.presenter_intervention(resultat, lambda v: False), "REJ-CONTRAT-INVALIDE", "trop grande")


def test_la_vue_d_un_creneau_absent_garde_la_cause():
    registre, ids, positions = _monde()
    resultat = _resultat(_lire(registre, ids["ch-01"], positions, _calme()))
    vue, verdict = meteo_creneaux.presenter_intervention(resultat, lambda v: True)
    assert verdict is None and vue["creneaux"] == [] and vue["cause"] == resultat["cause"]


def test_la_reponse_d_un_creneau_tient_largement_dans_une_reponse_d_appareil():
    """La borne d'une réponse est de 6 000 caractères : un créneau, sans points horaires, en prend moins de moitié."""
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    resultat = _resultat(
        _lire(registre, ids["ch-01"], positions, _vent_fort_le(DATES[route["jour"]]), DATES[route["jour"]])
    )
    vue, _ = meteo_creneaux.presenter_intervention(resultat, lambda v: True)
    enveloppe = {"ok": True, "resultat": {"accepte": True, "resultat": vue}}
    assert len(json.dumps(enveloppe, ensure_ascii=False)) < 3000


def test_les_verdicts_du_module_sont_tous_au_catalogue_apres_l_ajout():
    import ast

    source = Path(meteo_creneaux.__file__).read_text(encoding="utf-8")
    codes = {
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert {"REJ-TRANSITION-ILLEGALE", "REJ-CHAMP-MANQUANT", "REJ-CONTRAT-INVALIDE"} <= codes <= verdicts.CODES_M4


def test_les_arguments_du_profil_ne_sont_jamais_modifies():
    registre, ids, positions, plan = _monde_applique_un()
    route, _ = _visite(plan, ids["ch-01"])
    profil = copy.deepcopy(METEO)
    _resultat(_lire(registre, ids["ch-01"], positions, _calme(), DATES[route["jour"]], profil=profil))
    assert profil == METEO
