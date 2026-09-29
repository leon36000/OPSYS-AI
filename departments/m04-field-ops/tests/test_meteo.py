"""PLAN T4.13 (M4.10) : `meteo.py`, pur, sur des règles et des prévisions FICTIVES (`fictif: true`, aucune donnée
réelle).

Quatre issues, jamais autre chose : bloquant, validation requise, ok, inconnu. Le pire l'emporte ; « inconnu » n'est
jamais « ok » ; une valeur météo ne vient jamais d'un modèle. Les règles ont la forme EXACTE du profil de l'entreprise
(`opsys.meteo.normaliser_meteo`), pour que la forme des tests ne dérive pas de celle du produit.
"""

from __future__ import annotations

import ast
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from m4_field_ops import meteo, verdicts

from opsys import meteo as meteo_entreprise

FICTIF = True
_SRC = Path(meteo.__file__).resolve()
DATE = "2026-10-05"
AUTRE_DATE = "2026-10-06"

# revêtement : les cinq risques sont jugés (seuils fictifs, ceux que le propriétaire choisira)
PROFIL = meteo_entreprise.normaliser_meteo(
    {
        "fuseau": "America/Toronto",
        "services": {
            "revetement": {
                "seuils": {
                    "vent_kmh": {"validation": 25, "blocage": 40},
                    "rafales_kmh": {"validation": 45, "blocage": 60},
                    "pluie_mm_h": {"validation": 1, "blocage": 3},
                    "pluie_probabilite_pct": {"validation": 40, "blocage": 70},
                    "gel_c": {"validation": 5, "blocage": 2},
                    "verglas": {"blocage": True},
                    "chaleur_c": {"validation": 30, "blocage": 35},
                }
            },
            "gouttieres": {
                "seuils": {
                    "vent_kmh": {"blocage": 50},
                    "pluie_mm_h": {"blocage": 5},
                    "gel_c": {"blocage": 0},
                    "verglas": {"validation": True},
                },
                "sans_objet": ["chaleur"],
            },
            "interieur": {"sans_objet": list(meteo_entreprise.RISQUES)},
        },
    }
)
REVETEMENT = PROFIL["services"]["revetement"]
GOUTTIERES = PROFIL["services"]["gouttieres"]
INTERIEUR = PROFIL["services"]["interieur"]
CALME = {
    "temperature_c": 12,
    "vent_kmh": 10,
    "rafales_kmh": 20,
    "precipitation_mm_h": 0,
    "probabilite_precipitation_pct": 10,
    "verglas": False,
}


def _point(heure, date=DATE, **valeurs):
    point = {champ: None for champ in meteo.CLES_POINT}
    point["heure"] = f"{date}T{heure:02d}:00:00-04:00"
    point.update(valeurs)
    return point


def _journee(date=DATE, modifs=None, sans=(), **defauts):
    """24 points horaires calmes ; `modifs` : {heure: {champ: valeur}} ; `sans` : heures absentes."""
    base = {**CALME, **defauts}
    points = []
    for heure in range(24):
        if heure in sans:
            continue
        points.append(_point(heure, date, **{**base, **(modifs or {}).get(heure, {})}))
    return points


def _previsions(points=None, **citation):
    return {
        "citation": {
            "source": "fournisseur-fictif",
            "emise_le": "2026-10-04T18:00:00-04:00",
            "heure_type": "heure_d_emission_saisie",
            **citation,
        },
        "points": _journee() if points is None else points,
    }


def _juger(regles=REVETEMENT, points=None, debut=480, fin=1020, date=DATE):
    return meteo.evaluer_creneau(regles, _previsions(points), date, debut, fin)


def _regle(resultat, mesure):
    (regle,) = [r for r in resultat["regles"] if r["mesure"] == mesure]
    return regle


# ---------------------------------------------------------------------------------------------
# Le pire l'emporte, « inconnu » n'est jamais « ok »
# ---------------------------------------------------------------------------------------------
class TestGravite:
    def test_l_ordre_du_plus_grave_au_moins_grave(self):
        assert meteo.STATUTS == ("bloquant", "validation_requise", "inconnu", "ok")

    @pytest.mark.parametrize(
        ("statuts", "attendu"),
        [
            (["ok", "ok"], "ok"),
            (["ok", "inconnu"], "inconnu"),
            (["inconnu", "validation_requise", "ok"], "validation_requise"),
            (["validation_requise", "bloquant", "inconnu"], "bloquant"),
            (["bloquant"], "bloquant"),
        ],
    )
    def test_le_pire_l_emporte(self, statuts, attendu):
        assert meteo.pire(statuts) == attendu
        assert meteo.pire(reversed(statuts)) == attendu

    def test_rien_n_a_ete_juge_donne_inconnu_jamais_ok(self):
        assert meteo.pire([]) == meteo.STATUT_INCONNU
        assert meteo.pire(iter(())) == meteo.STATUT_INCONNU


# ---------------------------------------------------------------------------------------------
# Un créneau calme est « ok » ; chaque seuil, chaque sens, chaque borne
# ---------------------------------------------------------------------------------------------
class TestVerdictDuCreneau:
    def test_un_creneau_calme_est_ok_et_juge_les_sept_mesures(self):
        resultat = _juger()
        assert resultat["statut"] == meteo.STATUT_OK
        assert [r["mesure"] for r in resultat["regles"]] == list(REVETEMENT["seuils"])
        assert all(r["statut"] == meteo.STATUT_OK for r in resultat["regles"])
        assert resultat["a_configurer"] == [] and resultat["sans_objet"] == []
        assert (resultat["date"], resultat["debut_min"], resultat["fin_min"]) == (DATE, 480, 1020)

    @pytest.mark.parametrize(
        ("mesure", "champ", "valeur", "statut"),
        [
            ("vent_kmh", "vent_kmh", 24, "ok"),
            ("vent_kmh", "vent_kmh", 25, "validation_requise"),
            ("vent_kmh", "vent_kmh", 39, "validation_requise"),
            ("vent_kmh", "vent_kmh", 40, "bloquant"),
            ("rafales_kmh", "rafales_kmh", 44, "ok"),
            ("rafales_kmh", "rafales_kmh", 45, "validation_requise"),
            ("rafales_kmh", "rafales_kmh", 60, "bloquant"),
            ("pluie_mm_h", "precipitation_mm_h", 0, "ok"),
            ("pluie_mm_h", "precipitation_mm_h", 1, "validation_requise"),
            ("pluie_mm_h", "precipitation_mm_h", 3, "bloquant"),
            ("pluie_probabilite_pct", "probabilite_precipitation_pct", 39, "ok"),
            ("pluie_probabilite_pct", "probabilite_precipitation_pct", 40, "validation_requise"),
            ("pluie_probabilite_pct", "probabilite_precipitation_pct", 70, "bloquant"),
            ("chaleur_c", "temperature_c", 29, "ok"),
            ("chaleur_c", "temperature_c", 30, "validation_requise"),
            ("chaleur_c", "temperature_c", 35, "bloquant"),
        ],
    )
    def test_chaque_seuil_se_declenche_a_la_borne_incluse_vers_le_haut(self, mesure, champ, valeur, statut):
        resultat = _juger(points=_journee(modifs={13: {champ: valeur}}))
        regle = _regle(resultat, mesure)
        assert regle["statut"] == statut
        if statut != "ok":
            assert regle["observe"] == {"valeur": str(valeur), "heure": "13:00"}
        assert resultat["statut"] == statut, "les autres mesures sont calmes : le verdict est celui de cette règle"

    @pytest.mark.parametrize(
        ("temperature", "statut"),
        [(6, "ok"), (5, "validation_requise"), (3, "validation_requise"), (2, "bloquant"), (-10, "bloquant")],
    )
    def test_le_gel_se_mesure_vers_le_bas(self, temperature, statut):
        # les autres mesures qui lisent la température (chaleur) restent calmes : 12 par défaut, 6 ou moins ici
        resultat = _juger(points=_journee(modifs={9: {"temperature_c": temperature}}))
        assert _regle(resultat, "gel_c")["statut"] == statut
        assert _regle(resultat, "chaleur_c")["statut"] == "ok"

    def test_le_verglas_prevu_bloque_ou_demande_validation_selon_le_niveau_declare(self):
        avec = _journee(modifs={10: {"verglas": True}})
        assert _regle(_juger(REVETEMENT, avec), "verglas")["statut"] == meteo.STATUT_BLOQUANT
        assert _regle(_juger(GOUTTIERES, avec), "verglas")["statut"] == meteo.STATUT_VALIDATION
        regle = _regle(_juger(REVETEMENT, avec), "verglas")
        assert regle["observe"] == {"valeur": True, "heure": "10:00"}
        assert "verglaçantes prévues à 10:00" in regle["detail"]

    def test_le_verglas_absent_de_la_prevision_est_ok_seulement_si_partout_faux(self):
        assert _regle(_juger(), "verglas")["statut"] == meteo.STATUT_OK
        inconnu = _juger(points=_journee(modifs={9: {"verglas": None}}))
        assert _regle(inconnu, "verglas")["statut"] == meteo.STATUT_INCONNU
        assert inconnu["statut"] == meteo.STATUT_INCONNU

    def test_la_pire_heure_du_creneau_fait_foi_et_est_nommee(self):
        points = _journee(modifs={9: {"vent_kmh": 30}, 11: {"vent_kmh": 44}, 15: {"vent_kmh": 26}})
        regle = _regle(_juger(points=points), "vent_kmh")
        assert regle["statut"] == meteo.STATUT_BLOQUANT
        assert regle["observe"] == {"valeur": "44", "heure": "11:00"}
        assert "44 km/h à 11:00" in regle["detail"] and "blocage >= 40" in regle["detail"]

    def test_a_valeur_egale_l_heure_la_plus_tot_est_nommee(self):
        points = _journee(modifs={9: {"vent_kmh": 50}, 14: {"vent_kmh": 50}})
        assert _regle(_juger(points=points), "vent_kmh")["observe"]["heure"] == "09:00"

    def test_un_seuil_de_validation_seul_ne_bloque_jamais(self):
        regles = meteo_entreprise.normaliser_meteo(
            {
                "services": {
                    "s": {
                        "seuils": {"vent_kmh": {"validation": 20}},
                        "sans_objet": ["pluie", "gel", "verglas", "chaleur"],
                    }
                }
            }
        )
        resultat = meteo.evaluer_creneau(regles["services"]["s"], _previsions(_journee(vent_kmh=200)), DATE, 480, 1020)
        assert resultat["statut"] == meteo.STATUT_VALIDATION

    def test_un_seuil_de_blocage_seul_ne_demande_jamais_de_validation(self):
        resultat = _juger(GOUTTIERES, _journee(modifs={12: {"vent_kmh": 49}}))
        assert _regle(resultat, "vent_kmh")["statut"] == meteo.STATUT_OK
        assert _juger(GOUTTIERES, _journee(modifs={12: {"vent_kmh": 50}}))["statut"] == meteo.STATUT_BLOQUANT

    def test_les_valeurs_decimales_sont_exactes_et_citees_en_texte(self):
        justesous = _journee(modifs={12: {"vent_kmh": Decimal("39.9")}})
        assert _regle(_juger(points=justesous), "vent_kmh")["statut"] == meteo.STATUT_VALIDATION
        assert _regle(_juger(points=justesous), "vent_kmh")["observe"]["valeur"] == "39.9"
        borne = _journee(modifs={12: {"vent_kmh": Decimal("40.0")}})
        assert _regle(_juger(points=borne), "vent_kmh")["statut"] == meteo.STATUT_BLOQUANT
        assert _regle(_juger(points=borne), "vent_kmh")["observe"]["valeur"] == "40"

    def test_le_texte_des_nombres_est_canonique(self):
        assert meteo.en_texte(Decimal("62.50")) == "62.5"
        assert meteo.en_texte(Decimal("100")) == "100"
        assert meteo.en_texte(Decimal("0.0")) == "0"
        assert meteo.en_texte(7) == "7"
        assert meteo.en_texte(Decimal("-3.10")) == "-3.1"


class TestBornesDuCreneau:
    @pytest.mark.parametrize(
        ("debut", "fin", "attendues"),
        [
            (480, 1020, list(range(8, 18))),  # 08:00 à 17:00 : les dix heures pleines, bornes incluses
            (510, 570, [8, 9, 10]),  # 08:30 à 09:30 : de l'heure d'avant à l'heure d'après
            (480, 540, [8, 9]),
            (0, 60, [0, 1]),
            (1380, 1439, [23]),  # plafonné à 23 : le lendemain n'est pas exigé
            (600, 601, [10, 11]),
        ],
    )
    def test_heures_attendues(self, debut, fin, attendues):
        assert meteo.heures_attendues(debut, fin) == attendues

    def test_un_point_apres_la_fin_ou_avant_le_debut_ne_compte_pas(self):
        points = _journee(modifs={7: {"vent_kmh": 90}, 18: {"vent_kmh": 90}})
        assert _juger(points=points)["statut"] == meteo.STATUT_OK

    def test_les_deux_bouts_du_creneau_comptent(self):
        assert _juger(points=_journee(modifs={8: {"vent_kmh": 90}}))["statut"] == meteo.STATUT_BLOQUANT
        assert _juger(points=_journee(modifs={17: {"vent_kmh": 90}}))["statut"] == meteo.STATUT_BLOQUANT

    def test_un_creneau_court_ne_juge_que_ses_heures(self):
        points = _journee(modifs={14: {"vent_kmh": 90}})
        assert _juger(points=points, debut=480, fin=720)["statut"] == meteo.STATUT_OK  # 08:00 à 12:00
        assert _juger(points=points, debut=780, fin=900)["statut"] == meteo.STATUT_BLOQUANT  # 13:00 à 15:00

    def test_les_points_d_une_autre_date_ne_servent_jamais(self):
        points = _journee(DATE) + _journee(AUTRE_DATE, vent_kmh=90)
        assert _juger(points=points, date=DATE)["statut"] == meteo.STATUT_OK
        assert _juger(points=points, date=AUTRE_DATE)["statut"] == meteo.STATUT_BLOQUANT

    def test_la_prevision_ne_cite_que_les_points_du_creneau_en_texte(self):
        prevision = _juger(points=_journee(modifs={9: {"vent_kmh": Decimal("12.50")}}))["prevision"]
        assert [p["heure"][11:13] for p in prevision["points"]] == [f"{h:02d}" for h in range(8, 18)]
        assert prevision["points"][1]["vent_kmh"] == "12.5" and prevision["points"][0]["verglas"] is False
        assert prevision["citation"]["source"] == "fournisseur-fictif"
        assert prevision["citation"]["emise_le"] == "2026-10-04T18:00:00-04:00"


# ---------------------------------------------------------------------------------------------
# Ce qu'on ne sait pas n'est jamais « ok »
# ---------------------------------------------------------------------------------------------
class TestInconnu:
    def test_une_heure_sans_donnee_rend_le_creneau_inconnu_et_la_nomme(self):
        resultat = _juger(points=_journee(sans=(11, 12)))
        assert resultat["statut"] == meteo.STATUT_INCONNU
        regle = _regle(resultat, "vent_kmh")
        assert regle["statut"] == meteo.STATUT_INCONNU and regle["heures_sans_donnee"] == ["11:00", "12:00"]
        assert "sans donnée à 11:00, 12:00" in regle["detail"] and "jamais présumé" in regle["detail"]
        assert regle["observe"] is not None, "le maximum des heures connues reste cité"

    def test_un_blocage_observe_l_emporte_sur_les_heures_sans_donnee(self):
        resultat = _juger(points=_journee(modifs={9: {"vent_kmh": 45}}, sans=(15, 16)))
        assert _regle(resultat, "vent_kmh")["statut"] == meteo.STATUT_BLOQUANT
        assert resultat["statut"] == meteo.STATUT_BLOQUANT

    def test_une_validation_observee_l_emporte_sur_inconnu(self):
        resultat = _juger(points=_journee(modifs={9: {"vent_kmh": 30}}, sans=(15,)))
        assert resultat["statut"] == meteo.STATUT_VALIDATION

    def test_une_mesure_que_la_source_ne_donne_pas_reste_inconnue_jamais_zero(self):
        points = _journee(rafales_kmh=None, precipitation_mm_h=None)
        resultat = _juger(points=points)
        assert _regle(resultat, "rafales_kmh")["statut"] == meteo.STATUT_INCONNU
        assert _regle(resultat, "pluie_mm_h")["statut"] == meteo.STATUT_INCONNU
        assert _regle(resultat, "rafales_kmh")["observe"] is None
        assert resultat["statut"] == meteo.STATUT_INCONNU

    def test_aucune_prevision_pour_la_date_donne_inconnu(self):
        resultat = meteo.evaluer_creneau(REVETEMENT, _previsions(_journee(AUTRE_DATE)), DATE, 480, 1020)
        assert resultat["statut"] == meteo.STATUT_INCONNU
        assert all(r["statut"] == meteo.STATUT_INCONNU for r in resultat["regles"])
        assert resultat["prevision"]["points"] == []

    def test_des_regles_absentes_disent_seuil_a_configurer_et_rendent_inconnu(self):
        resultat = meteo.evaluer_creneau(None, _previsions(), DATE, 480, 1020)
        assert resultat["statut"] == meteo.STATUT_INCONNU and resultat["regles"] == []
        assert [a.split(" : ")[0] for a in resultat["a_configurer"]] == list(meteo.RISQUES)
        assert all("seuil à configurer" in a for a in resultat["a_configurer"])

    def test_des_regles_vides_sont_comme_des_regles_absentes(self):
        assert meteo.evaluer_creneau({}, _previsions(), DATE, 480, 1020)["statut"] == meteo.STATUT_INCONNU

    def test_un_risque_sans_decision_reste_a_configurer_meme_si_le_reste_est_calme(self):
        partielles = meteo_entreprise.normaliser_meteo({"services": {"s": {"seuils": {"vent_kmh": {"blocage": 40}}}}})
        resultat = meteo.evaluer_creneau(partielles["services"]["s"], _previsions(), DATE, 480, 1020)
        assert _regle(resultat, "vent_kmh")["statut"] == meteo.STATUT_OK
        assert [a.split(" : ")[0] for a in resultat["a_configurer"]] == ["pluie", "gel", "verglas", "chaleur"]
        assert resultat["statut"] == meteo.STATUT_INCONNU

    def test_un_blocage_l_emporte_sur_un_risque_a_configurer(self):
        partielles = meteo_entreprise.normaliser_meteo({"services": {"s": {"seuils": {"vent_kmh": {"blocage": 40}}}}})
        resultat = meteo.evaluer_creneau(
            partielles["services"]["s"], _previsions(_journee(vent_kmh=80)), DATE, 480, 1020
        )
        assert resultat["statut"] == meteo.STATUT_BLOQUANT and resultat["a_configurer"]

    def test_un_risque_sans_objet_est_liste_et_ne_compte_pas(self):
        resultat = _juger(GOUTTIERES, _journee(temperature_c=50))
        assert resultat["sans_objet"] == ["chaleur"] and resultat["a_configurer"] == []
        assert "chaleur_c" not in [r["mesure"] for r in resultat["regles"]]
        assert resultat["statut"] == meteo.STATUT_OK

    def test_tous_les_risques_sans_objet_ne_demandent_aucune_prevision_et_sont_ok(self):
        assert meteo.regles_exigent_une_prevision(INTERIEUR) is False
        resultat = meteo.evaluer_creneau(INTERIEUR, None, DATE, 480, 1020)
        assert resultat["statut"] == meteo.STATUT_OK and resultat["prevision"] is None
        assert resultat["regles"] == [] and resultat["sans_objet"] == list(meteo.RISQUES)

    def test_des_regles_absentes_ou_a_seuils_demandent_ou_non_une_prevision(self):
        assert meteo.regles_exigent_une_prevision(REVETEMENT) is True
        assert meteo.regles_exigent_une_prevision(None) is False
        assert meteo.regles_exigent_une_prevision({}) is False

    def test_resultat_inconnu_dit_la_cause_et_n_evalue_rien(self):
        cause = {"code": "REJ-METEO-FOURNISSEUR-INDISPONIBLE", "detail": "fournisseur fictif a répondu HTTP 503"}
        resultat = meteo.resultat_inconnu(REVETEMENT, DATE, 480, 1020, cause)
        assert resultat["statut"] == meteo.STATUT_INCONNU and resultat["regles"] == []
        assert resultat["cause"] == cause and resultat["prevision"] is None
        assert resultat["a_configurer"] == []
        vide = meteo.resultat_inconnu(None, DATE, 480, 1020, cause)
        assert len(vide["a_configurer"]) == 5 and vide["statut"] == meteo.STATUT_INCONNU

    def test_resultat_inconnu_garde_les_risques_sans_objet(self):
        cause = {"code": "REJ-CHAMP-MANQUANT", "detail": "date à fournir"}
        assert meteo.resultat_inconnu(GOUTTIERES, DATE, 480, 1020, cause)["sans_objet"] == ["chaleur"]


class TestPurete:
    def test_le_resultat_est_serialisable_deterministe_et_ne_modifie_rien(self):
        regles, previsions = copy.deepcopy(REVETEMENT), _previsions(_journee(modifs={9: {"vent_kmh": Decimal("41.5")}}))
        avant = copy.deepcopy((regles, previsions))
        premier = meteo.evaluer_creneau(regles, previsions, DATE, 480, 1020)
        second = meteo.evaluer_creneau(regles, previsions, DATE, 480, 1020)
        assert json.dumps(premier, sort_keys=True) == json.dumps(second, sort_keys=True)
        assert (regles, previsions) == avant
        json.dumps(premier)  # aucun Decimal dans le résultat

    def test_deux_services_deux_verdicts_sur_la_meme_prevision(self):
        points = _journee(modifs={12: {"vent_kmh": 45}})
        assert _juger(REVETEMENT, points)["statut"] == meteo.STATUT_BLOQUANT
        assert _juger(GOUTTIERES, points)["statut"] == meteo.STATUT_OK

    def test_les_mesures_du_module_sont_celles_du_profil_de_l_entreprise(self):
        assert meteo.RISQUES == meteo_entreprise.RISQUES
        assert set(meteo.MESURES) == set(meteo_entreprise.MESURES)
        for mesure, (risque, sens, _champ, _unite) in meteo.MESURES.items():
            assert (risque, sens) == meteo_entreprise.MESURES[mesure][:2], mesure


# ---------------------------------------------------------------------------------------------
# La prévision du port : valider ce qu'un fournisseur rend
# ---------------------------------------------------------------------------------------------
class TestValiderPrevisions:
    def test_une_prevision_conforme_passe(self):
        assert meteo.valider_previsions(_previsions()) is None
        assert meteo.valider_previsions(_previsions([_point(9, vent_kmh=Decimal("12.5"))])) is None

    @pytest.mark.parametrize(
        ("previsions", "morceau"),
        [
            (None, "objet {citation, points}"),
            ({"citation": {}, "points": [], "en_trop": 1}, "objet {citation, points}"),
            ({"citation": "x", "points": []}, "citation : un objet"),
            ({"citation": {"source": "s", "emise_le": "t"}, "points": [_point(9)]}, "heure_type"),
            ({"citation": {"source": " ", "emise_le": "t", "heure_type": "h"}, "points": [_point(9)]}, "source"),
            ({"citation": {"source": "s", "emise_le": "", "heure_type": "h"}, "points": [_point(9)]}, "emise_le"),
            (_previsions([]), "au moins un point"),
            (_previsions("pas une liste"), "au moins un point"),
            (_previsions(["texte"]), "clés permises"),
            (_previsions([{**_point(9), "humidex": 30}]), "clés permises"),
            (_previsions([{**_point(9), "heure": "hier"}]), "heure locale"),
            (_previsions([{**_point(9), "heure": "2026-02-30T09:00:00-04:00"}]), "heure locale"),
            (_previsions([{**_point(9), "heure": "2026-10-05T25:00:00-04:00"}]), "heure locale"),
            (_previsions([{**_point(9), "heure": None}]), "heure locale"),
            (_previsions([{**_point(9), "heure": "2026-10-05T09:30:00-04:00"}]), "minutes à zéro"),
            (_previsions([_point(9), _point(9)]), "heure en double"),
            (_previsions([_point(9, vent_kmh=True)]), "nombre entier ou décimal exact"),
            (_previsions([_point(9, vent_kmh="12")]), "nombre entier ou décimal exact"),
            (_previsions([_point(9, vent_kmh=Decimal("NaN"))]), "nombre entier ou décimal exact"),
            (_previsions([_point(9, vent_kmh=Decimal("Infinity"))]), "nombre entier ou décimal exact"),
            (_previsions([_point(9, verglas=1)]), "true, false ou null"),
            (_previsions([_point(9, verglas="oui")]), "true, false ou null"),
        ],
    )
    def test_une_prevision_hors_du_port_est_refusee_avec_la_raison(self, previsions, morceau):
        probleme = meteo.valider_previsions(previsions)
        assert probleme is not None and morceau in probleme

    def test_un_float_n_est_pas_un_nombre_du_port(self):
        """Les adaptateurs lisent les décimaux en `Decimal` : un flottant n'entre jamais dans le jugement."""
        assert meteo.valider_previsions(_previsions([_point(9, vent_kmh=12.5)])) is not None

    def test_une_heure_avec_secondes_et_decalage_est_permise(self):
        point = {**_point(9), "heure": "2026-10-05T09:00"}
        assert meteo.valider_previsions(_previsions([point])) is None
        assert meteo.valider_previsions(_previsions([{**point, "heure": "2026-10-05T09:00:00Z"}])) is None


# ---------------------------------------------------------------------------------------------
# Dates civiles et lieu généralisé
# ---------------------------------------------------------------------------------------------
class TestDatesEtLieu:
    @pytest.mark.parametrize("date", ["2026-10-05", "2028-02-29", "2000-02-29", "2026-12-31", "2026-01-01"])
    def test_dates_valides(self, date):
        assert meteo.est_date(date) is True

    @pytest.mark.parametrize(
        "date",
        [
            "2027-02-29",
            "2100-02-29",
            "2026-13-01",
            "2026-00-10",
            "2026-04-31",
            "2026-10-00",
            "26-10-05",
            "2026-10-5",
            "2026/10/05",
            "",
            None,
            20261005,
            "2026-10-05T09:00",
        ],
    )
    def test_dates_invalides(self, date):
        assert meteo.est_date(date) is False

    def test_le_lieu_est_arrondi_au_dixieme_de_degre_demi_vers_le_haut(self):
        assert meteo.lieu_generalise(45_818_432, -73_431_299) == {
            "latitude_microdegres": 45_800_000,
            "longitude_microdegres": -73_400_000,
        }
        assert meteo.lieu_generalise(45_850_000, 45_849_999) == {
            "latitude_microdegres": 45_900_000,
            "longitude_microdegres": 45_800_000,
        }
        assert meteo.lieu_generalise(-73_450_000, -73_450_001) == {
            "latitude_microdegres": -73_400_000,
            "longitude_microdegres": -73_500_000,
        }
        assert meteo.lieu_generalise(0, 0) == {"latitude_microdegres": 0, "longitude_microdegres": 0}

    def test_le_lieu_generalise_est_idempotent_et_reconnu(self):
        lieu = meteo.lieu_generalise(45_741_500, -73_450_500)
        assert meteo.lieu_generalise(lieu["latitude_microdegres"], lieu["longitude_microdegres"]) == lieu
        assert meteo.est_lieu_generalise(lieu) is True

    def test_un_lieu_plus_precis_est_refuse(self):
        assert (
            meteo.est_lieu_generalise({"latitude_microdegres": 45_741_500, "longitude_microdegres": -73_450_500})
            is False
        )
        assert (
            meteo.est_lieu_generalise({"latitude_microdegres": 45_700_000, "longitude_microdegres": -73_450_500})
            is False
        )
        assert (
            meteo.est_lieu_generalise({"latitude_microdegres": 45_700_001, "longitude_microdegres": -73_400_000})
            is False
        )

    @pytest.mark.parametrize(
        "lieu",
        [
            None,
            [],
            {},
            {"latitude_microdegres": 45_700_000},
            {"latitude_microdegres": 45_700_000, "longitude_microdegres": -73_400_000, "adresse": "1 rue X"},
            {"latitude_microdegres": True, "longitude_microdegres": 0},
            {"latitude_microdegres": 45_700_000.0, "longitude_microdegres": -73_400_000},
            {"latitude_microdegres": "45700000", "longitude_microdegres": -73_400_000},
            {"latitude_microdegres": 91_000_000, "longitude_microdegres": 0},
            {"latitude_microdegres": 0, "longitude_microdegres": -181_000_000},
        ],
    )
    def test_un_lieu_mal_forme_n_est_pas_un_lieu_permis(self, lieu):
        assert meteo.est_lieu_generalise(lieu) is False


# ---------------------------------------------------------------------------------------------
# Report proposé : les jours restants
# ---------------------------------------------------------------------------------------------
def _chantier(identifiant, jours=(0, 1), fige=None, debut=480, fin=1020):
    return {
        "id": identifiant,
        "duree_min": 90,
        "fenetre": {"jours": list(jours), "debut_min": debut, "fin_min": fin},
        "competences_requises": [],
        "urgence": 0,
        "creneau_fige": fige,
    }


class TestPreparerRelance:
    def test_le_jour_ferme_est_retire_de_la_fenetre_du_chantier_bloque(self):
        relance = meteo.preparer_relance(
            [_chantier("a"), _chantier("b")],
            [{"intervention_id": "a", "jour": 0}],
            {"a": "revetement", "b": "gouttieres"},
        )
        assert relance["exclues"] == [] and relance["intervention_ids"] == ["a", "b"]
        fenetres = {c["intervention_id"]: c["fenetre"]["jours"] for c in relance["chantiers"]}
        assert fenetres == {"a": [1], "b": [0, 1]}
        assert relance["jours_retires"] == {"revetement": [0]}

    def test_le_jour_ferme_pour_un_service_l_est_pour_tous_les_chantiers_de_ce_service(self):
        relance = meteo.preparer_relance(
            [_chantier("a"), _chantier("b"), _chantier("c")],
            [{"intervention_id": "a", "jour": 0}],
            {"a": "revetement", "b": "revetement", "c": "gouttieres"},
        )
        fenetres = {c["intervention_id"]: c["fenetre"]["jours"] for c in relance["chantiers"]}
        assert fenetres == {"a": [1], "b": [1], "c": [0, 1]}

    def test_un_lead_v1_sans_service_ne_perd_que_son_propre_jour(self):
        relance = meteo.preparer_relance(
            [_chantier("a"), _chantier("b")], [{"intervention_id": "a", "jour": 1}], {"a": None, "b": None}
        )
        fenetres = {c["intervention_id"]: c["fenetre"]["jours"] for c in relance["chantiers"]}
        assert fenetres == {"a": [0], "b": [0, 1]} and relance["jours_retires"] == {}

    def test_sans_jour_restant_le_chantier_est_exclu_avec_la_raison(self):
        relance = meteo.preparer_relance(
            [_chantier("a", jours=(0,)), _chantier("b")],
            [{"intervention_id": "a", "jour": 0}],
            {"a": "revetement", "b": "gouttieres"},
        )
        assert relance["intervention_ids"] == ["b"]
        (exclue,) = relance["exclues"]
        assert exclue["intervention_id"] == "a" and exclue["raison"] == meteo.RAISON_SANS_JOUR_RESTANT
        assert "élargir la fenêtre" in exclue["detail"]

    def test_un_creneau_confirme_au_client_sur_un_jour_ferme_n_est_jamais_deplace(self):
        fige = {"equipe": "eq-a", "jour": 0, "debut_min": 480}
        relance = meteo.preparer_relance(
            [_chantier("a", fige=fige)], [{"intervention_id": "a", "jour": 0}], {"a": "revetement"}
        )
        assert relance["chantiers"] == [] and relance["intervention_ids"] == []
        (exclue,) = relance["exclues"]
        assert exclue["raison"] == meteo.RAISON_CRENEAU_FIGE and "m4_signaler_report" in exclue["detail"]

    def test_un_creneau_fige_sur_un_jour_non_ferme_est_garde_tel_quel(self):
        fige = {"equipe": "eq-a", "jour": 1, "debut_min": 480}
        relance = meteo.preparer_relance(
            [_chantier("a", fige=fige), _chantier("b")],
            [{"intervention_id": "b", "jour": 0}],
            {"a": "gouttieres", "b": "revetement"},
        )
        garde = next(c for c in relance["chantiers"] if c["intervention_id"] == "a")
        assert garde["creneau_fige"] == fige and garde["fenetre"]["jours"] == [0, 1]

    def test_les_arguments_ont_le_format_de_m4_proposer_cedule_et_ne_modifient_rien(self):
        chantiers = [_chantier("a", debut=510, fin=990)]
        avant = copy.deepcopy(chantiers)
        relance = meteo.preparer_relance(chantiers, [{"intervention_id": "a", "jour": 0}], {"a": "revetement"})
        assert chantiers == avant
        assert relance["chantiers"] == [
            {"intervention_id": "a", "fenetre": {"jours": [1], "debut_min": 510, "fin_min": 990}, "creneau_fige": None}
        ]

    def test_sans_creneau_bloque_rien_ne_change(self):
        relance = meteo.preparer_relance([_chantier("a"), _chantier("b")], [], {"a": "revetement", "b": "revetement"})
        assert relance["exclues"] == [] and relance["jours_retires"] == {}
        assert [c["fenetre"]["jours"] for c in relance["chantiers"]] == [[0, 1], [0, 1]]


# ---------------------------------------------------------------------------------------------
# Le port
# ---------------------------------------------------------------------------------------------
class _Fournisseur:
    def descripteur(self):
        return {"fournisseur": "fictif"}

    def previsions(self, lieu, date_debut, date_fin):
        return _previsions(), None


def test_le_port_est_reconnu_par_isinstance():
    assert isinstance(_Fournisseur(), meteo.FournisseurMeteo)
    assert not isinstance(object(), meteo.FournisseurMeteo)


def test_les_verdicts_du_module_sont_au_catalogue_de_m4():
    assert set(meteo.CODES_METEO) <= verdicts.CODES_M4 and len(meteo.CODES_METEO) == 4
    codes = {
        n.value
        for n in ast.walk(ast.parse(_SRC.read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert codes <= verdicts.CODES_M4, codes - verdicts.CODES_M4


def test_verdict_meteo_construit_un_verdict_du_catalogue():
    verdict = meteo.verdict_meteo(meteo.CODE_FOURNISSEUR_FERME, "aucun fournisseur ouvert")
    assert verdict == {"code": "REJ-METEO-FOURNISSEUR-FERME", "statut": "", "detail": "aucun fournisseur ouvert"}
    with pytest.raises(verdicts.CodeVerdictInconnu):
        meteo.verdict_meteo("REJ-METEO-INVENTE", "x")


# ---------------------------------------------------------------------------------------------
# Garde par analyse du code : pur (aucun opsys, aucun réseau, aucune horloge, aucun aléa, aucun flottant)
# ---------------------------------------------------------------------------------------------
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_reseau_horloge_alea_ni_flottant():
    autorises = {"__future__", "re", "decimal", "typing"}
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in autorises, alias.name
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module in autorises or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} <= {"verdicts"}
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "socket", "float", "opsys", "os", "sys"}


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    arbre = _arbre()
    # Les deux méthodes du port (`Protocol`) n'ont que leur documentation : elles décrivent, l'adaptateur implémente.
    du_port = {
        id(m)
        for c in ast.walk(arbre)
        if isinstance(c, ast.ClassDef) and c.name == "FournisseurMeteo"
        for m in c.body
        if isinstance(m, ast.FunctionDef)
    }
    assert len(du_port) == 2
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and id(noeud) not in du_port:
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name
