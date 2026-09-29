"""PLAN T4.13 (M4.10, M4.21) : `meteo_creneaux.py`, pur, sur un registre EN MÉMOIRE, des positions injectées, un profil
météo injecté et un fournisseur fictif : aucune base, aucun réseau, aucune clé.

On juge la météo de chaque créneau (visite) d'un plan PROPOSÉ. Un créneau bloquant donne un report proposé (motif
`meteo`) et une nouvelle proposition de cédule pour les jours restants : arguments et aperçu, jamais rangée ni
appliquée. Le scénario par les vrais outils, le vrai bus et la porte d'appareil est
`tests/e2e/test_meteo_bloquante_appareil.py`. Tout est fictif (`fictif: true`) : Repentigny à Joliette, coordonnées
approximatives (`fixtures/tournees_repentigny_joliette.json`).
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import (
    cedule_tournees,
    encodage,
    etats,
    materiel,
    meteo,
    meteo_creneaux,
    preparation,
    verdicts,
)
from m4_field_ops.registre import Registre

from opsys import meteo as meteo_entreprise

FICTIF = True
_SRC = Path(meteo_creneaux.__file__).resolve()
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
METEO_SANS_SOFFITE = meteo_entreprise.normaliser_meteo(
    {
        "fuseau": "America/Toronto",
        "services": {code: regles for code, regles in METEO["services"].items() if code != "soffite_fascia"},
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


def _lecteur_equipes(profil=None):
    lecture = (_profil_equipes() if profil is None else profil, None)
    return lambda: lecture


def _lecteur_meteo(profil=METEO, verdict=None):
    lecture = (profil, verdict)
    return lambda: lecture


def _proposer(registre, positions, arguments=None, **kwargs):
    return cedule_tournees.proposer(
        registre,
        {} if arguments is None else arguments,
        positions,
        HORODATAGE,
        moteur="dp",
        lire_equipes=kwargs.get("lire_equipes", _lecteur_equipes()),
        lire_meteo=kwargs.get("lire_meteo", _lecteur_meteo()),
    )


def _plan(registre, positions, arguments=None):
    resultat, verdict = _proposer(registre, positions, arguments)
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


class Fournisseur:
    """Fournisseur fictif du port : une prévision par date (`{date: {champ: valeur ou {heure: {...}}}}`), et la trace
    des appels."""

    def __init__(
        self, journees=None, verdict=None, rendu=None, attribution="Météo fictive (test), sans licence réelle"
    ):
        self.journees = {} if journees is None else journees
        self.verdict = verdict
        self.rendu = rendu
        self.attribution = attribution
        self.appels = []

    def descripteur(self):
        return {"fournisseur": "fictif"}

    def previsions(self, lieu, date_debut, date_fin):
        self.appels.append((dict(lieu), date_debut, date_fin))
        if self.verdict is not None:
            return None, self.verdict
        if self.rendu is not None:
            return copy.deepcopy(self.rendu), None
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


def _verifier(
    registre,
    plan_id,
    positions,
    fournisseur,
    calendrier=None,
    profil=METEO,
    verdict_profil=None,
    verdict_fournisseur=None,
    lire_equipes=None,
    jours=None,
):
    return meteo_creneaux.verifier(
        registre,
        plan_id,
        CALENDRIER if calendrier is None else calendrier,
        positions,
        profil,
        verdict_profil,
        fournisseur,
        verdict_fournisseur,
        lire_equipes=_lecteur_equipes() if lire_equipes is None else lire_equipes,
        lire_meteo=_lecteur_meteo(profil, verdict_profil),
        jours=jours,
    )


def _resultat(couple):
    resultat, verdict = couple
    assert verdict is None, verdict
    return resultat


def _refuse(couple, code, morceau=""):
    resultat, verdict = couple
    assert resultat is None and verdict["code"] == code and morceau in verdict["detail"], (resultat, verdict)
    return verdict


def _jours_du_plan(plan):
    return {route["jour"] for route in plan["plan"]}


def _du_jour(plan, jour):
    return [v["chantier"] for r in plan["plan"] if r["jour"] == jour for v in r["visites"]]


def _vent_fort_le(date, valeur=62):
    autre = "2026-10-06" if date == "2026-10-05" else "2026-10-05"
    return Fournisseur({date: {"vent_kmh": valeur, "rafales_kmh": valeur + 10}, autre: {}})


def _octets(objet):
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


# =========================================================================================
# 1. Un plan calme est ok ; la vérification ne fait que lire
# =========================================================================================
def test_un_plan_sous_un_ciel_calme_est_ok_sans_report_ni_relance():
    registre, ids, positions = _monde()
    plan = _plan(registre, positions)
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _calme()))
    assert resultat["statut"] == meteo.STATUT_OK and resultat["plan_id"] == plan["plan_id"]
    assert resultat["reports_proposes"] == [] and resultat["a_valider"] == [] and resultat["cedule_relancee"] is None
    assert len(resultat["creneaux"]) == 3 and {c["intervention_id"] for c in resultat["creneaux"]} == set(ids.values())
    assert all(c["statut"] == meteo.STATUT_OK for c in resultat["creneaux"])


def test_chaque_creneau_dit_qui_quand_quel_service_et_cite_la_prevision():
    registre, ids, positions = _monde()
    plan = _plan(registre, positions)
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _calme()))
    par_id = {c["intervention_id"]: c for c in resultat["creneaux"]}
    creneau = par_id[ids["ch-10"]]
    assert creneau["service"] == "gouttieres" and creneau["statut_intervention"] == "a_planifier"
    route = next(r for r in plan["plan"] if any(v["chantier"] == ids["ch-10"] for v in r["visites"]))
    visite = next(v for v in route["visites"] if v["chantier"] == ids["ch-10"])
    assert (creneau["equipe"], creneau["jour"], creneau["date"]) == (
        route["equipe"],
        route["jour"],
        DATES[route["jour"]],
    )
    assert (creneau["debut_min"], creneau["fin_min"]) == (visite["debut_min"], visite["fin_min"])
    citation = creneau["prevision"]["citation"]
    assert citation["source"] == "fournisseur-fictif" and citation["emise_le"] == "2026-10-04T18:00:00-04:00"
    assert citation["heure_type"] == "heure_d_emission_saisie"


def test_la_verification_ne_fait_que_lire_le_registre_est_intact():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    avant = _octets(registre.lire())
    _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[min(_jours_du_plan(plan))])))
    assert _octets(registre.lire()) == avant, "même la nouvelle proposition (aperçu) n'est pas rangée"
    assert registre.valider_chaine()


def test_le_resultat_est_serialisable_deterministe_et_sans_coordonnee_ni_contact_ni_prix():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    fournisseur = _vent_fort_le(DATES[min(_jours_du_plan(plan))])
    premier = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    second = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[min(_jours_du_plan(plan))])))
    assert _octets(premier) == _octets(second)
    texte = json.dumps(premier, ensure_ascii=False)
    for site in SITES.values():
        for cle in ("latitude_microdeg", "longitude_microdeg"):
            assert str(site[cle]) not in texte and str(abs(site[cle])) not in texte, site["id"]
    for interdit in ("latitude", "longitude", "Client Fictif", "418-555-0100", "Repentigny", "prix", "montant"):
        assert interdit not in texte, interdit


# =========================================================================================
# 2. Le lieu envoyé au fournisseur est généralisé, une prévision par lieu et par date
# =========================================================================================
def test_le_fournisseur_ne_recoit_que_des_lieux_generalises_au_dixieme_de_degre():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    fournisseur = _calme()
    _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    assert fournisseur.appels
    for lieu, debut, fin in fournisseur.appels:
        assert meteo.est_lieu_generalise(lieu) and debut == fin
    fins = {site["latitude_microdeg"] for site in SITES.values() if site["latitude_microdeg"] % 100_000}
    assert fins, "le scénario a des latitudes fines à protéger"
    envoyes = {lieu["latitude_microdegres"] for lieu, _, _ in fournisseur.appels}
    assert not envoyes & fins, "aucune latitude fine d'un chantier ne part"


def _plan_de_deux_revetements(registre, ids, positions, jours):
    """Deux revêtements du même secteur (ch-01 et ch-02 se généralisent au même lieu), chacun sur son jour."""
    return _plan(
        registre,
        positions,
        {
            "chantiers": [
                {
                    "intervention_id": ids[lead],
                    "fenetre": {"jours": [jour], "debut_min": 480, "fin_min": 1020},
                    "creneau_fige": None,
                }
                for lead, jour in zip(("ch-01", "ch-02"), jours, strict=True)
            ]
        },
    )


def test_une_prevision_par_lieu_et_par_date_pas_une_par_creneau():
    registre, ids, _ = _monde((("ch-01", "revetement"), ("ch-02", "revetement")))
    positions = Positions({"ch-01": SITES["ch-01"], "ch-02": SITES["ch-01"]})  # deux chantiers au même endroit
    # même lieu, MÊME jour : une seule demande pour les deux créneaux
    meme_jour = _plan_de_deux_revetements(registre, ids, positions, (0, 0))
    fournisseur = _calme()
    resultat = _resultat(_verifier(registre, meme_jour["plan_id"], positions, fournisseur))
    assert len(resultat["creneaux"]) == 2 and {c["jour"] for c in resultat["creneaux"]} == {0}
    assert [(lieu, debut) for lieu, debut, _ in fournisseur.appels] == [
        ({"latitude_microdegres": 45700000, "longitude_microdegres": -73400000}, DATES[0])
    ]
    # même lieu, DEUX jours : une demande par date, jamais la prévision d'un jour pour l'autre
    deux_jours = _plan_de_deux_revetements(registre, ids, positions, (0, 1))
    fournisseur = _calme()
    resultat = _resultat(_verifier(registre, deux_jours["plan_id"], positions, fournisseur))
    assert sorted(c["jour"] for c in resultat["creneaux"]) == [0, 1]
    assert sorted(debut for _, debut, _ in fournisseur.appels) == [DATES[0], DATES[1]]
    assert all(debut == fin for _, debut, fin in fournisseur.appels), "une demande par journée, pas une plage"


def test_un_fournisseur_qui_rend_une_prevision_hors_du_port_donne_inconnu_avec_la_raison():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    mauvais = Fournisseur(rendu={"citation": {"source": "s"}, "points": []})
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, mauvais))
    assert resultat["statut"] == meteo.STATUT_INCONNU
    assert all(c["cause"]["code"] == meteo.CODE_REPONSE_INVALIDE for c in resultat["creneaux"])
    assert resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None


# =========================================================================================
# 3. Créneau bloquant : report proposé et nouvelle proposition pour les jours restants
# =========================================================================================
def test_un_vent_fort_sur_le_jour_du_plan_bloque_et_propose_un_report_motif_meteo():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour])))
    assert resultat["statut"] == meteo.STATUT_BLOQUANT
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_BLOQUANT
    vent = next(r for r in creneau["regles"] if r["mesure"] == "vent_kmh")
    assert vent["statut"] == "bloquant" and vent["observe"]["valeur"] == "62"
    (report,) = resultat["reports_proposes"]
    assert report["intervention_id"] == ids["ch-01"] and report["motif"] == "meteo" and report["jour"] == jour
    assert report["date"] == DATES[jour] and report["statut_intervention"] == "a_planifier"
    assert report["geste"] is None and "reste sur a_planifier" not in report["explication"]
    assert "retiré de sa fenêtre" in report["explication"]
    assert any("vent_kmh" in phrase and "blocage" in phrase for phrase in report["regles_franchies"])


def test_la_relance_propose_les_jours_restants_arguments_apercu_et_meme_plan_id_que_la_vraie_proposition():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    jour_ferme = next(iter(_jours_du_plan(plan)))
    jour_restant = 1 - jour_ferme
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour_ferme])))
    relance = resultat["cedule_relancee"]
    assert relance["statut"] == meteo_creneaux.STATUT_RELANCE_APERCU and relance["exclues"] == []
    assert relance["jours_retires"] == {"revetement": [jour_ferme]}
    assert relance["arguments"] == {
        "intervention_ids": [ids["ch-01"]],
        "moteur": "dp",
        "chantiers": [
            {
                "intervention_id": ids["ch-01"],
                "creneau_fige": None,
                "fenetre": {"jours": [jour_restant], "debut_min": 480, "fin_min": 1020},
            }
        ],
    }
    apercu = relance["apercu"]
    assert apercu["deja_proposee"] is False and apercu["plan_id"] != plan["plan_id"]
    assert _jours_du_plan(apercu) == {jour_restant} and _du_jour(apercu, jour_restant) == [ids["ch-01"]]
    assert "rien n'est appliqué ici" in relance["explication"]
    # la VRAIE proposition avec ces arguments donne le même plan_id que l'aperçu, et range un plan proposé, jamais
    # appliqué
    vrai = _plan(
        registre,
        positions,
        {"intervention_ids": relance["arguments"]["intervention_ids"], "chantiers": relance["arguments"]["chantiers"]},
    )
    assert vrai["plan_id"] == apercu["plan_id"]
    assert _octets(vrai["plan"]) == _octets(apercu["plan"])
    assert [m["type_entree"] for m in registre.lire() if m["type_entree"] == "cedule_appliquee"] == []


def test_la_relance_ne_touche_pas_aux_autres_services_ni_aux_autres_jours_des_chantiers_non_touches():
    registre, ids, positions = _monde()
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    # vent fort SEULEMENT pour le revêtement (seuil 40) : la gouttière (seuil 50) tient à 45
    fournisseur = Fournisseur({DATES[jour]: {"vent_kmh": 45, "rafales_kmh": 50}, DATES[1 - jour]: {}})
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    par_id = {c["intervention_id"]: c for c in resultat["creneaux"]}
    bloques = [i for i, c in par_id.items() if c["statut"] == "bloquant"]
    assert set(bloques) == {i for lead, i in ids.items() if lead in ("ch-01", "ch-02") and par_id[i]["jour"] == jour}
    if par_id[ids["ch-10"]]["jour"] == jour:
        assert par_id[ids["ch-10"]]["statut"] == meteo.STATUT_OK
    fenetres = {
        c["intervention_id"]: c["fenetre"]["jours"] for c in resultat["cedule_relancee"]["arguments"]["chantiers"]
    }
    assert fenetres[ids["ch-01"]] == fenetres[ids["ch-02"]] == [1 - jour], "le jour est fermé pour tout le revêtement"
    assert fenetres[ids["ch-10"]] == [0, 1], "la gouttière tient : sa fenêtre est intacte"


def test_le_jour_ferme_pour_un_service_l_est_aussi_pour_un_chantier_du_meme_service_non_touche():
    """ch-01 est bloqué le jour du plan ; ch-02 (même service) a son propre créneau un autre jour : il perd aussi le
    jour fermé, sinon la nouvelle cédule pourrait le replacer dans le vent."""
    registre, ids, positions = _monde((("ch-01", "revetement"), ("ch-02", "revetement")))
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour])))
    for chantier in resultat["cedule_relancee"]["arguments"]["chantiers"]:
        assert jour not in chantier["fenetre"]["jours"]
    assert set(_jours_du_plan(resultat["cedule_relancee"]["apercu"])) == {1 - jour}


def test_sans_jour_restant_rien_n_est_a_relancer_et_la_raison_est_dite():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(
        registre,
        positions,
        {
            "chantiers": [
                {
                    "intervention_id": ids["ch-01"],
                    "fenetre": {"jours": [0], "debut_min": 480, "fin_min": 1020},
                    "creneau_fige": None,
                }
            ]
        },
    )
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[0])))
    relance = resultat["cedule_relancee"]
    assert relance["statut"] == meteo_creneaux.STATUT_RELANCE_RIEN and relance["arguments"] is None
    assert relance["apercu"] is None
    assert [e["raison"] for e in relance["exclues"]] == ["sans_jour_restant"]
    assert resultat["reports_proposes"][0]["intervention_id"] == ids["ch-01"]


def test_un_creneau_confirme_au_client_sur_un_jour_ferme_n_est_jamais_deplace_et_le_report_est_propose():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    premier = _plan(registre, positions)
    _appliquer(registre, premier["plan_id"], positions)  # l'intervention devient planifiee
    fige = {"equipe": "eq-a", "jour": 0, "debut_min": 600}
    plan = _plan(
        registre,
        positions,
        {
            "intervention_ids": [ids["ch-01"]],
            "chantiers": [{"intervention_id": ids["ch-01"], "fenetre": dict(FENETRE), "creneau_fige": fige}],
        },
    )
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[0])))
    (report,) = resultat["reports_proposes"]
    assert report["statut_intervention"] == "planifiee"
    assert report["geste"] == {
        "outil": "m4_signaler_report",
        "niveau": "N3",
        "a_completer": "horodatage",
        "arguments": {"intervention_id": ids["ch-01"], "motif": "meteo"},
    }
    relance = resultat["cedule_relancee"]
    assert relance["statut"] == meteo_creneaux.STATUT_RELANCE_RIEN
    assert [e["raison"] for e in relance["exclues"]] == ["creneau_fige"]
    assert etats.statut_courant(registre, ids["ch-01"]) == "planifiee", "rien n'est appliqué"


def test_une_intervention_planifiee_bloquee_recoit_le_geste_signaler_report_jamais_applique():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    _appliquer(registre, plan["plan_id"], positions)
    jour = next(iter(_jours_du_plan(plan)))
    avant = _octets(registre.lire())
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour])))
    (report,) = resultat["reports_proposes"]
    assert report["statut_intervention"] == "planifiee" and report["geste"]["outil"] == "m4_signaler_report"
    assert "reportee" in report["explication"] and "M1" in report["explication"]
    assert _octets(registre.lire()) == avant and etats.statut_courant(registre, ids["ch-01"]) == "planifiee"


def test_une_intervention_deja_en_route_recoit_aussi_le_geste_signaler_report():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    _appliquer(registre, plan["plan_id"], positions)
    equipe = etats.technicien_assigne(registre, ids["ch-01"])
    _, verdict = etats.transitionner(
        ids["ch-01"], "en_route", registre, HORODATAGE,
        assignation={"intervention_id": ids["ch-01"], "technicien_id": equipe},
    )
    assert verdict is None and etats.statut_courant(registre, ids["ch-01"]) == "en_route"
    jour = next(iter(_jours_du_plan(plan)))
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour])))
    (report,) = resultat["reports_proposes"]
    assert report["statut_intervention"] == "en_route" and report["geste"]["outil"] == "m4_signaler_report"
    assert report["geste"]["arguments"] == {"intervention_id": ids["ch-01"], "motif": "meteo"}
    assert etats.statut_courant(registre, ids["ch-01"]) == "en_route", "rien n'est appliqué"


def test_un_plan_propose_avec_des_surcharges_ne_rend_pas_d_apercu_et_dit_de_rejouer_les_surcharges():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    equipes = [
        {cle: copy.deepcopy(e[cle]) for cle in ("id", "competences", "depot", "quarts")}
        for e in _profil_equipes()["liste"]
    ]
    plan = _plan(registre, positions, {"equipes": equipes})
    jour = next(iter(_jours_du_plan(plan)))
    relance = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour])))["cedule_relancee"]
    assert relance["statut"] == meteo_creneaux.STATUT_RELANCE_A_REJOUER and relance["apercu"] is None
    assert "surcharge (equipes)" in relance["explication"] and relance["arguments"]["intervention_ids"] == [
        ids["ch-01"]
    ]


# =========================================================================================
# 4. Validation requise, et le pire l'emporte
# =========================================================================================
def test_un_vent_au_niveau_validation_demande_une_validation_et_ne_propose_aucun_report():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour], valeur=30)))
    assert resultat["statut"] == meteo.STATUT_VALIDATION
    assert resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None
    (a_valider,) = resultat["a_valider"]
    assert a_valider["intervention_id"] == ids["ch-01"] and a_valider["date"] == DATES[jour]
    assert any("vent_kmh" in phrase for phrase in a_valider["regles"])


def test_le_statut_d_ensemble_est_le_pire_des_creneaux():
    registre, ids, positions = _monde()
    plan = _plan(registre, positions)
    jours = sorted(_jours_du_plan(plan))
    fournisseur = _vent_fort_le(DATES[jours[0]], valeur=30)  # validation pour le revêtement, ok pour la gouttière
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    statuts = {c["statut"] for c in resultat["creneaux"]}
    assert resultat["statut"] == meteo.pire(statuts)
    assert resultat["statut"] in (meteo.STATUT_VALIDATION, meteo.STATUT_OK)


# =========================================================================================
# 5. Ce qu'on ne sait pas n'est jamais « ok »
# =========================================================================================
PANNE = verdicts.construire_verdict(meteo.CODE_FOURNISSEUR_INDISPONIBLE, detail="Fournisseur fictif a répondu HTTP 503")


def test_une_panne_du_fournisseur_donne_inconnu_pour_chaque_creneau_jamais_ok():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, Fournisseur(verdict=PANNE)))
    assert resultat["statut"] == meteo.STATUT_INCONNU
    for creneau in resultat["creneaux"]:
        assert creneau["statut"] == meteo.STATUT_INCONNU and creneau["prevision"] is None and creneau["regles"] == []
        assert creneau["cause"] == {
            "code": "REJ-METEO-FOURNISSEUR-INDISPONIBLE",
            "detail": "Fournisseur fictif a répondu HTTP 503",
        }
    assert resultat["reports_proposes"] == [] and resultat["a_valider"] == [] and resultat["cedule_relancee"] is None
    assert resultat["attributions"] == []


def test_sans_fournisseur_ouvert_le_creneau_est_inconnu_et_dit_quoi_faire():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, None))
    assert resultat["statut"] == meteo.STATUT_INCONNU
    cause = resultat["creneaux"][0]["cause"]
    assert cause["code"] == "REJ-METEO-FOURNISSEUR-FERME"
    assert "previsions_saisies" in cause["detail"] and "opsys-metier meteo declarer" in cause["detail"]


def test_le_verdict_de_fermeture_du_fournisseur_est_repris_tel_quel_comme_cause():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    ferme = verdicts.construire_verdict(
        meteo.CODE_FOURNISSEUR_FERME, detail="Open-Meteo fermé : forfait non commercial"
    )
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, None, verdict_fournisseur=ferme))
    assert resultat["creneaux"][0]["cause"] == {
        "code": "REJ-METEO-FOURNISSEUR-FERME",
        "detail": "Open-Meteo fermé : forfait non commercial",
    }


def test_sans_profil_meteo_le_creneau_est_inconnu_avec_le_verdict_du_profil_et_les_cinq_risques_a_configurer():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    absent = {"code": "REJ-METEO-NON-CONFIGUREE", "detail": "aucune règle météo déclarée : opsys-metier meteo declarer"}
    fournisseur = _calme()
    resultat = _resultat(
        _verifier(registre, plan["plan_id"], positions, fournisseur, profil=None, verdict_profil=absent)
    )
    assert resultat["statut"] == meteo.STATUT_INCONNU
    creneau = resultat["creneaux"][0]
    assert creneau["cause"] == absent and fournisseur.appels == [], "aucune prévision n'est demandée sans règles"
    assert len(creneau["a_configurer"]) == 5


def test_un_profil_meteo_invalide_garde_son_code_distinct_de_l_absence():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    invalide = {"code": "REJ-PROFIL-INVALIDE", "detail": "profil d'entreprise invalide : fuseau mal formé"}
    resultat = _resultat(
        _verifier(registre, plan["plan_id"], positions, _calme(), profil=None, verdict_profil=invalide)
    )
    assert {c["cause"]["code"] for c in resultat["creneaux"]} == {"REJ-PROFIL-INVALIDE"}


def test_un_service_sans_regles_dit_seuil_a_configurer_et_ne_demande_aucune_prevision():
    """Le plan est proposé quand les règles existent ; elles ont disparu du profil depuis : le créneau est inconnu."""
    registre, _, positions = _monde((("ch-01", "soffite_fascia"),))
    plan = _plan(registre, positions)
    fournisseur = _calme()
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur, profil=METEO_SANS_SOFFITE))
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU and "seuil à configurer" in creneau["cause"]["detail"]
    assert "'soffite_fascia'" in creneau["cause"]["detail"] and fournisseur.appels == []
    assert len(creneau["a_configurer"]) == 5


def test_un_service_dont_les_cinq_risques_sont_sans_objet_est_ok_sans_aucune_prevision():
    registre, _, positions = _monde((("ch-01", "reparation"),))
    plan = _plan(registre, positions)
    fournisseur = Fournisseur(verdict=PANNE)  # même un fournisseur en panne ne change rien : il n'est pas consulté
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_OK and creneau["prevision"] is None and fournisseur.appels == []
    assert creneau["sans_objet"] == list(meteo_entreprise.RISQUES)


def test_un_jour_sans_date_au_calendrier_est_inconnu_jamais_devine():
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    autre = 1 - jour
    fournisseur = _calme()
    resultat = _resultat(
        _verifier(registre, plan["plan_id"], positions, fournisseur, calendrier={str(autre): "2026-10-06"})
    )
    (creneau,) = resultat["creneaux"]
    assert creneau["date"] is None and creneau["statut"] == meteo.STATUT_INCONNU
    assert f"jour {jour}" in creneau["cause"]["detail"] and "jamais la deviner" in creneau["cause"]["detail"]
    assert fournisseur.appels == []


def test_une_position_a_confirmer_rend_le_creneau_inconnu_avec_le_verdict_de_la_position():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    # la position confirmée a été retirée depuis la proposition
    resultat = _resultat(_verifier(registre, plan["plan_id"], Positions({}), _calme()))
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU
    assert creneau["cause"]["code"] == "REJ-COORDONNEES-A-CONFIRMER" and "à confirmer" in creneau["cause"]["detail"]
    assert creneau["prevision"] is None and ids["ch-01"] == creneau["intervention_id"]


def test_un_lead_v1_n_a_pas_de_service_donc_pas_de_regles_meteo_et_son_creneau_est_inconnu():
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
    fournisseur = _calme()
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    (creneau,) = resultat["creneaux"]
    assert creneau["service"] is None and creneau["statut"] == meteo.STATUT_INCONNU
    assert "lead v1" in creneau["cause"]["detail"] and fournisseur.appels == []


def _fenetre_du_creneau(plan):
    visite = next(iter(plan["plan"]))["visites"][0]
    return meteo.heures_attendues(visite["debut_min"], visite["fin_min"])


def _sans_les_heures(fournisseur, heures):
    original = fournisseur.previsions

    def filtre(lieu, debut, fin):
        previsions, verdict = original(lieu, debut, fin)
        previsions["points"] = [p for p in previsions["points"] if int(p["heure"][11:13]) not in heures]
        return previsions, verdict

    fournisseur.previsions = filtre
    return fournisseur


def test_une_prevision_incomplete_rend_le_creneau_inconnu_et_nomme_l_heure_sans_donnee():
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    heures = _fenetre_du_creneau(plan)
    fournisseur = _sans_les_heures(_calme(), {heures[1]})
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == meteo.STATUT_INCONNU
    assert any(r["heures_sans_donnee"] == [f"{heures[1]:02d}:00"] for r in creneau["regles"])


def test_un_blocage_observe_l_emporte_meme_quand_la_prevision_est_incomplete():
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    heures = _fenetre_du_creneau(plan)
    fournisseur = _sans_les_heures(_vent_fort_le(DATES[jour]), set(heures[1:]))  # seule la première heure est connue
    assert _resultat(_verifier(registre, plan["plan_id"], positions, fournisseur))["statut"] == meteo.STATUT_BLOQUANT


# =========================================================================================
# 6. Refus : calendrier et plan
# =========================================================================================
@pytest.mark.parametrize(
    ("calendrier", "code", "morceau"),
    [
        (None, "REJ-CHAMP-MANQUANT", "calendrier"),
        ({}, "REJ-CHAMP-MANQUANT", "au moins un jour"),
        ([], "REJ-CHAMP-MANQUANT", "calendrier"),
        ({"lundi": "2026-10-05"}, "REJ-CONTRAT-INVALIDE", "jour entier"),
        ({"-1": "2026-10-05"}, "REJ-CONTRAT-INVALIDE", "jour entier"),
        ({"0": "2026-02-30"}, "REJ-CONTRAT-INVALIDE", "date civile"),
        ({"0": "5 octobre"}, "REJ-CONTRAT-INVALIDE", "date civile"),
        ({"0": None}, "REJ-CONTRAT-INVALIDE", "date civile"),
        ({True: "2026-10-05"}, "REJ-CONTRAT-INVALIDE", "jour entier"),
    ],
)
def test_un_calendrier_absent_ou_mal_forme_est_refuse_sans_rien_deviner(calendrier, code, morceau):
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    _refuse(
        meteo_creneaux.verifier(registre, plan["plan_id"], calendrier, positions, METEO, None, _calme(), None),
        code,
        morceau,
    )


def test_un_plan_inconnu_est_refuse():
    registre, _, positions = _monde((("ch-01", "revetement"),))
    _refuse(
        _verifier(registre, "plan-inexistant", positions, _calme()), "REJ-CEDULE-PLAN-INTROUVABLE", "plan-inexistant"
    )


def test_un_plan_deja_applique_se_verifie_aussi():
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    _appliquer(registre, plan["plan_id"], positions)
    assert _resultat(_verifier(registre, plan["plan_id"], positions, _calme()))["statut"] == meteo.STATUT_OK


def test_le_calendrier_accepte_des_jours_entiers_ou_leur_texte():
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    par_texte = _resultat(
        _verifier(registre, plan["plan_id"], positions, _calme(), calendrier={"0": "2026-10-05", "1": "2026-10-06"})
    )
    par_entier = _resultat(
        _verifier(registre, plan["plan_id"], positions, _calme(), calendrier={0: "2026-10-05", 1: "2026-10-06"})
    )
    assert _octets(par_texte) == _octets(par_entier)


# =========================================================================================
# 7. Attribution des licences
# =========================================================================================
def test_les_attributions_de_licence_sont_rendues_une_par_source():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _calme()))
    assert resultat["attributions"] == [
        {"source": "fournisseur-fictif", "attribution": "Météo fictive (test), sans licence réelle"}
    ]


def test_une_prevision_sans_attribution_n_en_invente_pas():
    registre, _, positions = _monde()
    plan = _plan(registre, positions)
    resultat = _resultat(
        _verifier(
            registre, plan["plan_id"], positions, Fournisseur({"2026-10-05": {}, "2026-10-06": {}}, attribution=None)
        )
    )
    assert resultat["attributions"] == []


# =========================================================================================
# 8. Le volet météo de la préparation, jugé sur le profil
# =========================================================================================
def test_un_plan_n_est_propose_que_si_la_meteo_est_prete_dans_la_preparation():
    registre, ids, positions = _monde((("ch-01", "soffite_fascia"),))
    resultat, verdict = _proposer(registre, positions, lire_meteo=_lecteur_meteo(METEO_SANS_SOFFITE))  # aucune règle
    assert resultat is None and verdict["code"] == "REJ-CEDULE-RIEN-A-PLANIFIER"
    assert "meteo" in verdict["detail"] and "seuil à configurer" in verdict["detail"]


def test_l_empreinte_de_la_preparation_suit_les_regles_meteo_declarees():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    autres_regles = meteo_entreprise.normaliser_meteo(
        {
            "fuseau": "America/Toronto",
            "services": {
                "revetement": {
                    "seuils": {"vent_kmh": {"blocage": 40}},
                    "sans_objet": ["pluie", "gel", "verglas", "chaleur"],
                }
            },
        }
    )
    empreintes = []
    for profil in (METEO, METEO, autres_regles):
        verdict, refus = preparation.evaluer(
            registre, ids["ch-01"], positions, _lecteur_equipes(), _lecteur_meteo(profil)
        )
        assert refus is None and verdict["volets"]["meteo"]["statut"] == "ok"
        empreintes.append(verdict["empreinte"])
    assert empreintes[0] == empreintes[1] != empreintes[2]


# =========================================================================================
# 8b. Plan périmé : un autre plan appliqué tient déjà l'intervention
# =========================================================================================
def test_un_plan_perime_pour_une_intervention_ne_compte_ni_dans_le_statut_ni_les_reports_ni_la_relance():
    registre, ids, positions = _monde((("ch-01", "revetement"),))
    premier = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(premier)))
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
    resultat = _resultat(_verifier(registre, premier["plan_id"], positions, _vent_fort_le(DATES[jour])))
    (creneau,) = resultat["creneaux"]
    assert creneau["plan_perime"] is True and creneau["statut"] == meteo.STATUT_BLOQUANT, "jugé, mais plus tenu"
    assert resultat["statut"] == meteo.STATUT_INCONNU, "aucun créneau vivant : rien n'est jugé pour de bon"
    assert resultat["reports_proposes"] == [] and resultat["cedule_relancee"] is None and resultat["a_valider"] == []
    assert resultat["perimes"] == [{"intervention_id": ids["ch-01"], "tenu_par": second["plan_id"]}]
    assert "périmé" in resultat["avertissement"]
    # le plan qui tient l'intervention est vivant : vent fort son jour -> report proposé, sans avertissement
    vivant = _resultat(_verifier(registre, second["plan_id"], positions, _vent_fort_le(DATES[1 - jour])))
    assert vivant["creneaux"][0]["plan_perime"] is False and "perimes" not in vivant and "avertissement" not in vivant
    (report,) = vivant["reports_proposes"]
    assert report["statut_intervention"] == "planifiee" and report["geste"]["outil"] == "m4_signaler_report"


class _RegistreFictif:
    def __init__(self, maillons):
        self._maillons = maillons

    def lire(self):
        return self._maillons


def _proposee(plan_id):
    return {"type_entree": "cedule_proposee", "plan_id": plan_id}


def _appliquee(plan_id, *interventions):
    return {
        "type_entree": "cedule_appliquee",
        "plan_id": plan_id,
        "assignations": [{"intervention_id": i} for i in interventions],
    }


def test_seul_un_plan_applique_apres_la_proposition_perime_le_plan():
    avant = _RegistreFictif([_appliquee("P0", "i1"), _proposee("P1")])
    assert meteo_creneaux._plans_perimes(avant, "P1") == {}, "appliqué avant : P1 propose un nouveau placement"
    apres = _RegistreFictif([_proposee("P1"), _appliquee("P0", "i1")])
    assert meteo_creneaux._plans_perimes(apres, "P1") == {"i1": "P0"}
    tenu = _RegistreFictif([_proposee("P1"), _appliquee("P0", "i1"), _appliquee("P1", "i1")])
    assert meteo_creneaux._plans_perimes(tenu, "P1") == {}, "P1 appliqué en dernier : il tient l'intervention"
    autre = _RegistreFictif([_proposee("P1"), _appliquee("P0", "i2")])
    assert meteo_creneaux._plans_perimes(autre, "P1") == {"i2": "P0"}
    assert meteo_creneaux._plans_perimes(_RegistreFictif([]), "P1") == {}
    assert meteo_creneaux._plans_perimes(_RegistreFictif([_appliquee("P0", "i1")]), "P1") == {}, "P1 inconnu"


# =========================================================================================
# 8c. Jours : ne juger que certains jours d'un plan
# =========================================================================================
def _plan_sur_deux_jours(registre, ids, positions):
    return _plan(
        registre,
        positions,
        {
            "chantiers": [
                {
                    "intervention_id": ids["ch-01"],
                    "fenetre": {"jours": [0], "debut_min": 480, "fin_min": 1020},
                    "creneau_fige": None,
                },
                {
                    "intervention_id": ids["ch-10"],
                    "fenetre": {"jours": [1], "debut_min": 480, "fin_min": 1020},
                    "creneau_fige": None,
                },
            ]
        },
    )


def test_jours_ne_juge_que_les_creneaux_des_jours_demandes():
    registre, ids, positions = _monde((("ch-01", "revetement"), ("ch-10", "gouttieres")))
    plan = _plan_sur_deux_jours(registre, ids, positions)
    vent_le_jour_0 = _vent_fort_le(DATES[0])
    tout = _resultat(_verifier(registre, plan["plan_id"], positions, vent_le_jour_0))
    assert {c["jour"] for c in tout["creneaux"]} == {0, 1} and tout["statut"] == meteo.STATUT_BLOQUANT
    zero = _resultat(_verifier(registre, plan["plan_id"], positions, vent_le_jour_0, jours=[0]))
    assert [c["intervention_id"] for c in zero["creneaux"]] == [ids["ch-01"]] and zero[
        "statut"
    ] == meteo.STATUT_BLOQUANT
    un = _resultat(_verifier(registre, plan["plan_id"], positions, vent_le_jour_0, jours=[1]))
    assert [c["intervention_id"] for c in un["creneaux"]] == [ids["ch-10"]]
    assert un["statut"] == meteo.STATUT_OK and un["cedule_relancee"] is None, "le jour 0, bloquant, n'est pas jugé ici"
    assert [a[1] for a in vent_le_jour_0.appels[2:]] == [DATES[0], DATES[1]], "une prévision par jour jugé, pas plus"


def test_jours_mal_formes_ou_absents_du_plan_sont_refuses():
    registre, ids, positions = _monde((("ch-01", "revetement"), ("ch-10", "gouttieres")))
    plan = _plan_sur_deux_jours(registre, ids, positions)
    for jours in ([], 0, "0", [-1], [1.5], [True], ["0"], [None]):
        _refuse(_verifier(registre, plan["plan_id"], positions, _calme(), jours=jours), "REJ-CONTRAT-INVALIDE", "jours")
    _refuse(
        _verifier(registre, plan["plan_id"], positions, _calme(), jours=[7]),
        "REJ-CONTRAT-INVALIDE",
        "jours du plan : [0, 1]",
    )
    assert meteo_creneaux.normaliser_jours(None) == (None, None)
    assert meteo_creneaux.normaliser_jours([1, 1, 0]) == ({0, 1}, None)


# =========================================================================================
# 8d. Présentation : bornée, jamais un créneau à regarder caché
# =========================================================================================
def _resultat_a_presenter():
    registre, ids, positions = _monde()
    plan = _plan(registre, positions)
    jour = next(iter(_jours_du_plan(plan)))
    resultat = _resultat(_verifier(registre, plan["plan_id"], positions, _vent_fort_le(DATES[jour])))
    assert {c["statut"] for c in resultat["creneaux"]} >= {"bloquant"} and resultat["cedule_relancee"]["apercu"]
    return resultat


def test_la_vue_compacte_ne_modifie_pas_le_resultat_et_ne_perd_aucun_creneau_a_regarder():
    resultat = _resultat_a_presenter()
    avant = _octets(resultat)
    a_regarder = {c["intervention_id"] for c in resultat["creneaux"] if c["statut"] != "ok"}
    tous = {c["intervention_id"] for c in resultat["creneaux"]}
    for niveau in range(meteo_creneaux.NIVEAU_DETAIL_MAX + 1):
        vue = meteo_creneaux.vue_compacte(resultat, niveau)
        assert {c["intervention_id"] for c in vue["creneaux"] if c["statut"] != "ok"} == a_regarder
        assert all("regles" in c for c in vue["creneaux"] if c["statut"] != "ok"), "le détail de ce qui bloque reste"
        assert vue["statut"] == resultat["statut"]
        assert [(r["intervention_id"], r["motif"], r["jour"], r["date"], r["statut_intervention"], r["geste"])
                for r in vue["reports_proposes"]] == [
            (r["intervention_id"], r["motif"], r["jour"], r["date"], r["statut_intervention"], r["geste"])
            for r in resultat["reports_proposes"]]
        assert vue["cedule_relancee"]["arguments"] == resultat["cedule_relancee"]["arguments"]
        retrouves = {c["intervention_id"] for c in vue["creneaux"]} | (tous if "ok_resume" not in vue else set())
        assert retrouves == tous or "ok_resume" in vue
    assert _octets(resultat) == avant


def test_chaque_niveau_de_la_vue_retire_un_peu_plus_et_le_dit():
    resultat = _resultat_a_presenter()
    nombre_ok = sum(1 for c in resultat["creneaux"] if c["statut"] == "ok")
    zero, un, deux, trois = (meteo_creneaux.vue_compacte(resultat, n) for n in range(4))
    assert "detail_reduit" not in zero and all(
        set(r) == {"risque", "statut", "detail"} for c in zero["creneaux"] for r in c["regles"]
    )
    assert all("points" not in c["prevision"] for c in zero["creneaux"] if c["prevision"])
    assert len(zero["creneaux"]) == len(un["creneaux"]) == 3 and "ok_resume" not in un
    assert all("regles" not in c for c in un["creneaux"] if c["statut"] == "ok") and "detail_reduit" in un
    assert len(deux["creneaux"]) == 3 - nombre_ok and sum(j["nombre"] for j in deux["ok_resume"]) == nombre_ok
    assert "ok_resume" in trois and "plan" not in trois["cedule_relancee"]["apercu"]
    # dès le niveau 2, un créneau à regarder ne garde que les règles qui ne sont pas ok, un report perd son explication
    for niveau, vue in enumerate((zero, un, deux, trois)):
        a_regarder = [c for c in vue["creneaux"] if c["statut"] != "ok"]
        assert a_regarder and all(c["statut"] == "bloquant" for c in a_regarder)
        assert all(any(r["statut"] == "bloquant" for r in c["regles"]) for c in a_regarder), (
            "un créneau à regarder garde toujours la règle qui le bloque"
        )
        if niveau >= 2:
            assert all(r["statut"] != "ok" for c in a_regarder for r in c["regles"])
            assert all("explication" not in r and "regles_franchies" not in r for r in vue["reports_proposes"])
        else:
            assert all("explication" in r and "regles_franchies" in r for r in vue["reports_proposes"])
    assert "plan" in deux["cedule_relancee"]["apercu"]
    assert trois["cedule_relancee"]["apercu"]["plan_id"] == resultat["cedule_relancee"]["apercu"]["plan_id"]
    assert (
        len(
            {
                zero.get("detail_reduit"),
                un["detail_reduit"],
                deux["detail_reduit"],
                trois["detail_reduit"],
            }
        )
        == 4
    )


def test_le_presentateur_rend_la_vue_la_plus_detaillee_qui_tient_ou_refuse_en_nommant_jours():
    resultat = _resultat_a_presenter()
    vue, verdict = meteo_creneaux.presenter(resultat, lambda vue: True)
    assert verdict is None and "detail_reduit" not in vue
    vue, verdict = meteo_creneaux.presenter(resultat, lambda vue: "ok_resume" in vue)
    assert verdict is None and "ok_resume" in vue and "plan" in vue["cedule_relancee"]["apercu"]
    vue, verdict = meteo_creneaux.presenter(resultat, lambda vue: "plan" not in vue["cedule_relancee"]["apercu"])
    assert verdict is None and "plan" not in vue["cedule_relancee"]["apercu"]
    _refuse(meteo_creneaux.presenter(resultat, lambda vue: False), "REJ-CONTRAT-INVALIDE", "jours")


# =========================================================================================
# 9. Garde par analyse du code : pur (aucun opsys, aucun réseau, aucune horloge, aucun aléa)
# =========================================================================================
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_reseau_horloge_ni_alea():
    autorises = {"__future__", "functools"}
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in autorises, alias.name
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module in autorises or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} <= {"cedule_tournees", "etats", "meteo", "registre", "verdicts"}
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "socket", "float", "opsys", "os", "sys"}


def test_le_module_n_ecrit_jamais_au_registre_reel():
    """Seule la COPIE du registre, faite pour l'aperçu, reçoit un `ajouter` : jamais le registre passé en argument."""
    ajouts = [n for n in ast.walk(_arbre()) if isinstance(n, ast.Attribute) and n.attr == "ajouter"]
    assert ajouts == [], "le module n'appelle jamais `ajouter` lui-même (l'aperçu passe par cedule_tournees.proposer)"


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_les_verdicts_du_module_sont_tous_au_catalogue():
    codes = {
        n.value
        for n in ast.walk(_arbre())
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert codes and codes <= verdicts.CODES_M4, codes - verdicts.CODES_M4


def test_encodage_du_plan_id_est_celui_de_cedule_tournees():
    """Le plan_id de l'aperçu est celui que `proposer` calcule : les mêmes empreintes (`encodage`), pas une copie."""
    registre, _, positions = _monde((("ch-01", "revetement"),))
    plan = _plan(registre, positions)
    maillon = cedule_tournees.plan_propose(cedule_tournees.instantane_du_registre(registre), plan["plan_id"])
    assert maillon["plan_id"] == encodage.empreinte(
        cedule_tournees.VERSION_PROPOSITION,
        maillon["empreinte_entree"],
        maillon["empreinte_sortie"],
        maillon["empreinte_etat"],
    )
