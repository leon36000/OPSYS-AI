"""M2.15 — le calcul PUR de l'analytique et des prévisions : méthodes stdlib, bootstrap à graine, seuils d'échantillon.

Valeurs connues calculées à la main, propriétés (reproductibilité, monotonie, bornes), refus typés. Données fictives."""

from __future__ import annotations

import json
import random
from fractions import Fraction

import pytest
from m2_revenue_crm import previsions

FICTIF = True
SERIE = [3, 5, 4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11]
PARAM = {
    "methode": "moyenne_mobile",
    "fenetre": 3,
    "alpha": None,
    "horizon": 3,
    "niveau": 80,
    "graine": 42,
    "repetitions": 500,
    "periodes_minimum": 12,
    "evenements_minimum": 20,
}
ENTREES = {"serie": SERIE, "unite": "semaine", "nom": "leads_ingeres"}


def _prevoir(entrees=ENTREES, **surcharge):
    return previsions.prevoir(entrees, {**PARAM, **surcharge})


def test_la_moyenne_mobile_a_les_valeurs_calculees_a_la_main():
    sortie, verdict = _prevoir()
    assert verdict is None
    # niveau = moyenne des 3 dernières valeurs (9, 10... ici 8+... ) : (10 + 9 + 11) / 3 = 10
    assert sortie["resultat"]["niveau_courant"] == "10.0000"
    assert sortie["resultat"]["prevision_totale"]["centre"] == "30.00"
    # erreur absolue moyenne à un pas, à la main : prévu_t = moyenne(y[t-3:t]) pour t = 3..13
    attendu = sum(abs(SERIE[t] - Fraction(sum(SERIE[t - 3 : t]), 3)) for t in range(3, 14)) / 11
    assert sortie["resultat"]["erreur_absolue_moyenne_un_pas"] == f"{float(attendu):.4f}"


def test_le_lissage_exponentiel_a_les_valeurs_calculees_a_la_main():
    sortie, verdict = _prevoir(methode="lissage_exponentiel", fenetre=None, alpha="0.5")
    assert verdict is None
    niveau = Fraction(SERIE[0])
    for y in SERIE[1:]:
        niveau = Fraction(1, 2) * y + Fraction(1, 2) * niveau
    assert sortie["resultat"]["niveau_courant"] == f"{float(niveau):.4f}"
    # alpha = 1 : le niveau est la dernière valeur
    dernier, _ = _prevoir(methode="lissage_exponentiel", fenetre=None, alpha="1")
    assert dernier["resultat"]["niveau_courant"] == "11.0000"


def test_la_prevision_est_toujours_un_intervalle_qui_encadre_le_centre_de_facon_ordonnee():
    sortie, _ = _prevoir()
    total = sortie["resultat"]["prevision_totale"]
    bas, haut = float(total["intervalle"]["bas"]), float(total["intervalle"]["haut"])
    assert bas < haut and "niveau" in total["intervalle"]
    for periode in sortie["resultat"]["par_periode"]:
        assert 0 <= float(periode["intervalle"]["bas"]) <= float(periode["intervalle"]["haut"])


def test_reproductible_par_la_graine_et_la_graine_compte():
    a, _ = _prevoir()
    b, _ = _prevoir()
    assert a == b
    rng = random.Random(9)
    bruitee = {**ENTREES, "serie": [rng.randrange(0, 15) for _ in range(30)]}
    resultats = {
        json.dumps(_prevoir(bruitee, graine=g, periodes_minimum=12)[0]["resultat"]["par_periode"]) for g in range(1, 12)
    }
    assert len(resultats) > 1, "au moins deux graines donnent des tirages différents"


def test_un_niveau_plus_haut_donne_un_intervalle_au_moins_aussi_large():
    largeur = {}
    for niveau in (80, 90, 95):
        i = _prevoir(niveau=niveau)[0]["resultat"]["prevision_totale"]["intervalle"]
        largeur[niveau] = float(i["haut"]) - float(i["bas"])
    assert largeur[80] <= largeur[90] <= largeur[95]


def test_les_valeurs_simulees_ne_sont_jamais_negatives():
    serie = [0, 0, 5, 0, 0, 6, 0, 0, 4, 0, 0, 7, 0, 0]
    sortie, verdict = previsions.prevoir(
        {"serie": serie, "unite": "semaine", "nom": "leads_perdus"}, {**PARAM, "periodes_minimum": 12}
    )
    assert verdict is None
    assert all(float(p["intervalle"]["bas"]) >= 0 for p in sortie["resultat"]["par_periode"])


def test_la_prevision_refuse_sous_les_seuils_et_dit_ce_qu_il_faut():
    court, verdict = _prevoir({**ENTREES, "serie": SERIE[:10]})
    assert court is None and verdict["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT"
    assert "10 semaine" in verdict["detail"] and "12" in verdict["detail"] and "Aucune prévision" in verdict["detail"]
    peu, verdict = _prevoir({**ENTREES, "serie": [1] * 6 + [2] * 6})
    assert peu is None and verdict["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT" and "12 semaine" in verdict["detail"]
    constante, verdict = _prevoir({**ENTREES, "serie": [3] * 14})
    assert constante is None and verdict["code"] == "REJ-PREV-SERIE-DEGENEREE"
    # pile au seuil : 12 semaines et 20 événements passent
    limite, verdict = _prevoir({**ENTREES, "serie": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 2, 3]})  # 12 semaines, 20 événements
    assert verdict is None and limite is not None
    une_de_moins, verdict = _prevoir({**ENTREES, "serie": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 2, 2]})  # 19 événements
    assert une_de_moins is None and verdict["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT"
    onze, verdict = _prevoir({**ENTREES, "serie": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 5]})  # 11 semaines
    assert onze is None and verdict["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT"


def test_un_seuil_se_releve_il_ne_s_abaisse_pas():
    for cle in ("periodes_minimum", "evenements_minimum"):
        bas, verdict = _prevoir(**{cle: 5})
        assert (
            bas is None and verdict["code"] == "REJ-PREV-PARAMETRE-INVALIDE" and "ne s'abaisse pas" in verdict["detail"]
        )
    releve, verdict = _prevoir(periodes_minimum=20)
    assert releve is None and verdict["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT"


@pytest.mark.parametrize(
    "surcharge",
    [
        {"methode": "arima"},
        {"methode": None},
        {"fenetre": 1},
        {"fenetre": 13},
        {"fenetre": 3.0},
        {"fenetre": True},
        {"alpha": "0.3"},
        {"horizon": 0},
        {"horizon": 9},
        {"horizon": 5},
        {"niveau": 85},
        {"graine": -1},
        {"graine": "1"},
        {"repetitions": 10},
        {"repetitions": 10**7},
        {"fenetre": 8},
    ],
)
def test_parametres_invalides_refuses_nommement(surcharge):
    sortie, verdict = _prevoir(**surcharge)
    assert sortie is None and verdict["code"] == "REJ-PREV-PARAMETRE-INVALIDE", surcharge


@pytest.mark.parametrize("alpha", ["0", "1.2", "-0.1", "0.1234", "abc", "", "NaN", "1e-1", 0.3, None])
def test_alpha_invalide_refuse(alpha):
    sortie, verdict = _prevoir(methode="lissage_exponentiel", fenetre=None, alpha=alpha)
    assert sortie is None and verdict["code"] == "REJ-PREV-PARAMETRE-INVALIDE"


def test_parametres_manquants_ou_en_trop_refuses():
    assert (
        previsions.prevoir(ENTREES, {k: v for k, v in PARAM.items() if k != "graine"})[1]["code"]
        == "REJ-PREV-PARAMETRE-INVALIDE"
    )
    assert previsions.prevoir(ENTREES, {**PARAM, "autre": 1})[1]["code"] == "REJ-PREV-PARAMETRE-INVALIDE"
    for entrees in (
        None,
        {},
        {**ENTREES, "unite": "mois"},
        {**ENTREES, "nom": "tout"},
        {**ENTREES, "serie": "abc"},
        {**ENTREES, "serie": [1, -1] + SERIE},
        {**ENTREES, "serie": [1.5] + SERIE},
        {**ENTREES, "serie": [True] + SERIE},
        {**ENTREES, "extra": 1},
    ):
        assert previsions.prevoir(entrees, PARAM)[1]["code"] == "REJ-PREV-PARAMETRE-INVALIDE", entrees


def test_aucun_flottant_ne_traverse_le_resultat():
    sortie, _ = _prevoir()
    texte = json.dumps(sortie)  # sérialisable en JSON strict
    assert isinstance(sortie["resultat"]["niveau_courant"], str)

    def sans_flottant(v):
        if isinstance(v, float):
            raise AssertionError(v)
        if isinstance(v, dict):
            for x in v.values():
                sans_flottant(x)
        if isinstance(v, list):
            for x in v:
                sans_flottant(x)

    sans_flottant(sortie)
    assert texte


# ---------------------------------------------------------------------------------------- analytique pure
def _lead(statut="nouveau", ingere=0, qualifie=None, converti=None, perdu=None, valeur=None):
    return {
        "statut": statut,
        "ingere_s": ingere,
        "qualifie_s": qualifie,
        "converti_s": converti,
        "perdu_s": perdu,
        "valeur_cents": valeur,
    }


def _monde(n_convertis=12, n_perdus=10, n_ouverts=6):
    jour = 86400
    leads = []
    for i in range(n_convertis):
        leads.append(
            _lead("converti", ingere=i * jour, qualifie=i * jour + jour, converti=i * jour + (5 + i % 3) * jour)
        )
    for i in range(n_perdus):
        leads.append(_lead("perdu", ingere=i * jour, qualifie=i * jour + jour, perdu=i * jour + 2 * jour))
    for i in range(n_ouverts):
        leads.append(
            _lead(
                "qualifie" if i % 2 else "nouveau",
                ingere=i * jour,
                qualifie=(i * jour + jour) if i % 2 else None,
                valeur=100_000 * (i + 1),
            )
        )
    return leads


PARAM_A = {"graine": 7, "repetitions": 300, "niveau": 80}


def test_l_analytique_compte_exactement():
    sortie, verdict = previsions.analyser({"leads": _monde()}, PARAM_A)
    assert verdict is None
    r = sortie["resultat"]
    assert r["pipeline"]["total"] == 28 and r["pipeline"]["par_statut"]["converti"] == 12
    assert r["pipeline"]["par_statut"]["perdu"] == 10 and r["pipeline"]["ouverts"] == 6
    assert r["entonnoir"] == {
        "ingeres": 28,
        "qualifies_un_jour": 12 + 10 + 3,
        "convertis_un_jour": 12,
        "perdus": 10,
        "resolus": 22,
    }
    assert r["taux_conversion_des_resolus"] == {"valeur": "0.5455", "n": 22, "seuil": 20, "succes": 12}
    cycle = r["delai_de_cycle"]
    assert cycle["n"] == 12 and cycle["valeurs"] is not None
    # délais : 4 + i%3 jours (converti - ingéré = 5 + i%3 jours... moins zéro) : cinq, six ou sept jours
    assert 5 <= float(cycle["valeurs"]["mediane"]) <= 7 and float(cycle["valeurs"]["p25"]) <= float(
        cycle["valeurs"]["p75"]
    )
    assert r["seuils_declares"] == dict(previsions.SEUILS)


def test_chaque_mesure_refuse_sous_son_seuil_et_dit_l_effectif():
    petit = _monde(n_convertis=4, n_perdus=3, n_ouverts=2)
    r = previsions.analyser({"leads": petit}, PARAM_A)[0]["resultat"]
    assert r["taux_conversion_des_resolus"]["valeur"] is None and r["taux_conversion_des_resolus"]["n"] == 7
    assert (
        "7 observé" in r["taux_conversion_des_resolus"]["refus"]
        and "20 exigés" in r["taux_conversion_des_resolus"]["refus"]
    )
    assert r["delai_de_cycle"]["valeurs"] is None and r["taux_qualification"]["valeur"] is None
    assert r["probabilite_de_conversion_par_etape"]["nouveau"]["valeur"] is None
    assert r["valeur_ponderee"]["valeur_ponderee"] is None


def test_le_seuil_est_exact_a_la_limite():
    exact = _monde(n_convertis=12, n_perdus=8, n_ouverts=0)  # 20 résolus : pile le seuil
    une_de_moins = _monde(n_convertis=12, n_perdus=7, n_ouverts=0)
    assert (
        previsions.analyser({"leads": exact}, PARAM_A)[0]["resultat"]["taux_conversion_des_resolus"]["valeur"]
        == "0.6000"
    )
    assert (
        previsions.analyser({"leads": une_de_moins}, PARAM_A)[0]["resultat"]["taux_conversion_des_resolus"]["valeur"]
        is None
    )


def test_la_valeur_ponderee_est_la_somme_des_valeurs_fois_la_probabilite_d_etape():
    leads = _monde()
    r = previsions.analyser({"leads": leads}, PARAM_A)[0]["resultat"]
    probas = r["probabilite_de_conversion_par_etape"]
    p_nouveau = Fraction(probas["nouveau"]["succes"], probas["nouveau"]["n"])
    p_qualifie = Fraction(probas["qualifie"]["succes"], probas["qualifie"]["n"])
    attendu = sum(
        Fraction(lead["valeur_cents"]) * (p_qualifie if lead["statut"] == "qualifie" else p_nouveau)
        for lead in leads
        if lead["statut"] in ("nouveau", "qualifie") and lead["valeur_cents"]
    )
    valeur = r["valeur_ponderee"]["valeur_ponderee"]
    assert valeur["centre"] == f"{float(attendu / 100):.2f}"
    assert float(valeur["intervalle"]["bas"]) <= float(valeur["intervalle"]["haut"])
    assert (
        r["valeur_ponderee"]["valeur_declaree_totale"] == "21000.00"
        and r["valeur_ponderee"]["sans_valeur_declaree"] == 0
    )


def test_sans_valeur_declaree_ou_sans_probabilite_la_valeur_ponderee_refuse():
    leads = [dict(lead, valeur_cents=None) for lead in _monde()]
    r = previsions.analyser({"leads": leads}, PARAM_A)[0]["resultat"]["valeur_ponderee"]
    assert r["valeur_ponderee"] is None and "aucune valeur déclarée" in r["refus"]
    # des valeurs sur des leads « nouveau » seulement, mais trop peu de leads résolus pour la probabilité
    peu = _monde(n_convertis=3, n_perdus=2, n_ouverts=4)
    r = previsions.analyser({"leads": peu}, PARAM_A)[0]["resultat"]["valeur_ponderee"]
    assert r["valeur_ponderee"] is None and "insuffisant" in r["refus"]


def test_l_analytique_est_reproductible_et_ne_depend_pas_de_l_ordre_des_leads():
    leads = _monde()
    a = previsions.analyser({"leads": leads}, PARAM_A)[0]
    b = previsions.analyser({"leads": leads}, PARAM_A)[0]
    assert a == b
    melange = list(leads)
    random.Random(3).shuffle(melange)
    c = previsions.analyser({"leads": melange}, PARAM_A)[0]
    assert c["resultat"]["entonnoir"] == a["resultat"]["entonnoir"]
    assert c["resultat"]["taux_conversion_des_resolus"] == a["resultat"]["taux_conversion_des_resolus"]


@pytest.mark.parametrize(
    "leads",
    [
        None,
        "x",
        [{}],
        [
            {
                "statut": "inconnu",
                "ingere_s": 0,
                "qualifie_s": None,
                "converti_s": None,
                "perdu_s": None,
                "valeur_cents": None,
            }
        ],
        [{**_lead(), "valeur_cents": -5}],
        [{**_lead(), "ingere_s": "0"}],
        [{**_lead(), "extra": 1}],
    ],
)
def test_enregistrements_mal_formes_refuses(leads):
    sortie, verdict = previsions.analyser({"leads": leads}, PARAM_A)
    assert sortie is None and verdict["code"] == "REJ-PREV-PARAMETRE-INVALIDE"


@pytest.mark.parametrize(
    "param",
    [
        {},
        {"graine": 1, "repetitions": 300},
        {**PARAM_A, "niveau": 70},
        {**PARAM_A, "repetitions": 5},
        {**PARAM_A, "graine": -3},
        {**PARAM_A, "x": 1},
    ],
)
def test_parametres_d_analyse_invalides(param):
    assert previsions.analyser({"leads": _monde()}, param)[1]["code"] == "REJ-PREV-PARAMETRE-INVALIDE"


def test_la_serie_hebdomadaire_ignore_la_semaine_en_cours_et_l_avant_crm():
    s = 86400
    maintenant = 100 * s
    records = [_lead(ingere=maintenant - i * s) for i in range(0, 30)]  # un lead par jour sur 30 jours
    serie = previsions.serie_hebdomadaire(records, "leads_ingeres", maintenant)
    assert len(serie) == 4 and sum(serie) == 28  # quatre semaines complètes, 7 leads chacune
    assert serie == [7, 7, 7, 7]
    assert previsions.serie_hebdomadaire([], "leads_ingeres", maintenant) == []
    assert previsions.serie_hebdomadaire([_lead(ingere=maintenant - 3 * s)], "leads_ingeres", maintenant) == []
    # un événement exactement à `maintenant` compte dans la dernière semaine ; à fin - 7 j exactement, il est dans
    # l'avant-dernière
    r = [_lead(ingere=maintenant - 14 * s), _lead(ingere=maintenant), _lead(ingere=maintenant - 7 * s)]
    assert previsions.serie_hebdomadaire(r, "leads_ingeres", maintenant) == [1, 1]


def test_les_quantiles_du_delai_de_cycle_suivent_la_regle_du_rang_le_plus_proche():
    jour = 86400
    # des cycles de 1, 2, …, 12 jours
    leads = [_lead("converti", ingere=0, qualifie=jour, converti=(i + 1) * jour) for i in range(12)]
    cycle = previsions.analyser({"leads": leads}, PARAM_A)[0]["resultat"]["delai_de_cycle"]
    assert cycle["n"] == 12
    assert cycle["valeurs"] == {"p25": "3.00", "mediane": "6.00", "p75": "9.00", "moyenne": "6.50"}
    dix = [_lead("converti", ingere=0, qualifie=jour, converti=(i + 1) * jour) for i in range(10)]
    assert previsions.analyser({"leads": dix}, PARAM_A)[0]["resultat"]["delai_de_cycle"]["valeurs"] == {
        "p25": "3.00", "mediane": "5.00", "p75": "8.00", "moyenne": "5.50"}
    neuf = dix[:9]
    assert previsions.analyser({"leads": neuf}, PARAM_A)[0]["resultat"]["delai_de_cycle"]["valeurs"] is None


def test_une_semaine_est_ouverte_a_gauche_et_fermee_a_droite_aux_frontieres_exactes():
    s = 86400
    maintenant = 100 * s
    # (maintenant - 7 j ; maintenant] est la dernière semaine : l'instant exact « maintenant » y est, « − 7 j »
    # exactement est dans la semaine d'avant, « − 7 j + 1 s » est encore dans la dernière.
    instants = [maintenant, maintenant - 7 * s + 1, maintenant - 7 * s, maintenant - 14 * s + 1, maintenant - 15 * s]
    serie = previsions.serie_hebdomadaire([_lead(ingere=i) for i in instants], "leads_ingeres", maintenant)
    assert serie == [2, 2], "deux semaines complètes ; l'événement d'il y a 15 jours précède la première"
