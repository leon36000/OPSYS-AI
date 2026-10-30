"""M9.9 — tendances extrapolées : droite, moyenne mobile, saisonnier, garde-fous, déterminisme (données fictives)."""

import datetime as dt
import json

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import tendances as td

FICTIF = True
LECTURE = "m2.leads"
CHEMIN = "resultat.resultat.total"
DEBUT = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)
CONNAISSANCE = "2026-12-31T00:00:00Z"


def _leads(total, suivant=None, leads=()):
    return {
        "ok": True,
        "resultat": {"accepte": True, "resultat": {"total": total, "leads": list(leads), "suivant": suivant}},
    }


def _refusee():
    return {"ok": True, "resultat": {"accepte": False, "verdict": {"code": "REJ-FICTIF"}}}


def _recu(jour, seconde=0):
    return (DEBUT + dt.timedelta(days=jour, seconds=seconde)).isoformat().replace("+00:00", "Z")


def _chaine(*specs):
    """specs : (réponse, jour, seconde, arguments)."""
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (reponse, jour, seconde, arguments) in enumerate(specs):
        capture = cs.construire(
            cat.obtenir(LECTURE),
            arguments,
            [reponse],
            recu_a=_recu(jour, seconde),
            reference=None,
            index=index,
            hash_precedent=precedent,
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def _serie(valeurs, jours):
    return _chaine(*[(_leads(v), j, 0, {}) for v, j in zip(valeurs, jours, strict=True)])


def _projeter(chaine, horizons=("7j",), **options):
    return td.projeter(
        chaine, lecture_id=LECTURE, chemin=CHEMIN, connaissance=CONNAISSANCE, horizons=list(horizons), **options
    )


def _methode(res, nom):
    (methode,) = [m for m in res["methodes"] if m["methode"] == nom]
    return methode


def _horizon(methode, nom):
    (entree,) = [p for p in methode["projections"] if p["horizon"] == nom]
    return entree


def _flottants(valeur):
    if isinstance(valeur, float):
        return 1
    if isinstance(valeur, dict):
        return sum(_flottants(v) for v in valeur.values())
    if isinstance(valeur, list):
        return sum(_flottants(v) for v in valeur)
    return 0


def test_droite_parfaite_ecart_type_nul_et_projection_calculee_a_la_main():
    # y = 10 + x sur les jours 0, 2, …, 10 : pente 1/jour, ordonnée 10, résidus nuls.
    res = _projeter(_serie([10, 12, 14, 16, 18, 20], [0, 2, 4, 6, 8, 10]), horizons=("7j", "30j"))
    assert res["statut"] == "PROJETEE" and res["n"] == 6 and res["duree_historique_jours"] == 10
    droite = _methode(res, "droite")
    assert droite["ecart_type_residuel"] == "0.00" and droite["residus"] == 6
    assert droite["parametres"] == {"pente_par_jour": "1.000000", "ordonnee_origine": "10.000000"}
    sept = _horizon(droite, "7j")  # x = 10 + 7 = 17 → 27
    assert sept["abscisse"] == 17 and sept["statut"] == "PROJETEE"
    assert (sept["valeur"], sept["borne_basse"], sept["borne_haute"]) == ("27.00", "27.00", "27.00")
    trente = _horizon(droite, "30j")
    assert trente["statut"] == "HORIZON_AU_DELA_DE_L_HISTORIQUE" and "valeur" not in trente
    assert res["origine"] == "tendance_extrapolee" and res["prevision_de_proprietaire"] is False
    assert res["libelle"] == "tendance extrapolée, pas une prévision de propriétaire"
    assert res["intervalle"] == {"facteur": "1.96", "libelle": "approximation, pas une probabilité calibrée"}
    assert res["politique_min_points"] == {"minimum": 6, "statut": "PROPOSEE_NON_VALIDEE_PAR_NATHAN"}
    assert [p["adresse"] for p in res["points"]] == [f"m2.leads#{i}:p0.resultat.resultat.total" for i in range(6)]
    assert [p["x"] for p in res["points"]] == [0, 2, 4, 6, 8, 10]
    assert [p["valeur"] for p in res["points"]] == ["10", "12", "14", "16", "18", "20"]


def test_moyenne_mobile_niveau_et_ecart_type_calcules_a_la_main():
    res = _projeter(_serie([10, 12, 14, 16, 18, 20], [0, 2, 4, 6, 8, 10]))
    mobile = _methode(res, "moyenne_mobile")
    # Niveau (16+18+20)/3 = 18 ; résidus 16-12, 18-14, 20-16 = 4 → écart-type √(48/3) = 4 ; marge 1,96 × 4 = 7,84.
    assert mobile["parametres"] == {"fenetre": 3, "niveau": "18.000000"}
    assert mobile["ecart_type_residuel"] == "4.00" and mobile["residus"] == 3
    sept = _horizon(mobile, "7j")
    assert (sept["valeur"], sept["borne_basse"], sept["borne_haute"]) == ("18.00", "10.16", "25.84")
    assert sept["avertissements"] == []


def test_droite_avec_bruit_arrondi_demi_haut():
    # Jours 0..7, y = 0,1,2,3,4,5,6,8 : n=8, Σx=28, Σx²=140, Σy=29, Σxy=147 → pente 364/336 = 13/12,
    # ordonnée (29 − 28 × 13/12)/8 = −1/6 ; projection à x = 7 + 7 = 14 : −1/6 + 14 × 13/12 = 15.
    res = _projeter(_serie([0, 1, 2, 3, 4, 5, 6, 8], list(range(8))), decimales=3)
    droite = _methode(res, "droite")
    assert droite["parametres"] == {"pente_par_jour": "1.0833333", "ordonnee_origine": "-0.1666667"}
    assert _horizon(droite, "7j")["valeur"] == "15.000"
    # Résidus ×12 : 2, 1, 0, −1, −2, −3, −4, 7 → SSR = 84/144 = 7/12 ; /(n−2) = 7/72 → √ = 0,31180… → 0,312.
    assert droite["ecart_type_residuel"] == "0.312"


def test_saisonnier_naif_deux_saisons_completes():
    # Saison de 7 jours ; deuxième semaine = première + 1 → résidus 1 → écart-type 1.
    valeurs = [1, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7, 8]
    res = _projeter(_serie(valeurs, list(range(14))), saison_jours=7)
    saison = _methode(res, "saisonnier_naif")
    assert saison["statut"] == "CALCULEE" and saison["ecart_type_residuel"] == "1.00" and saison["residus"] == 7
    sept = _horizon(saison, "7j")  # jour 20 → jour 13 (une saison plus tôt) = 8
    assert (sept["valeur"], sept["borne_basse"], sept["borne_haute"]) == ("8.00", "6.04", "9.96")


def test_saisonnier_refuse_sans_deux_saisons_ou_sans_saison():
    chaine = _serie([1, 2, 3, 4, 5, 6, 7, 2, 3, 4, 5, 6, 7], list(range(13)))
    insuffisant = _methode(_projeter(chaine, saison_jours=7), "saisonnier_naif")
    assert insuffisant["statut"] == "SAISONS_INSUFFISANTES" and insuffisant["projections"] == []
    assert "14 requis" in insuffisant["raison"]
    absente = _methode(_projeter(chaine), "saisonnier_naif")
    assert absente["statut"] == "NON_DEMANDEE" and absente["projections"] == []


def test_moins_de_six_points_historique_insuffisant_avec_ce_qui_manque():
    res = _projeter(_serie([1, 2, 3, 4, 5], [0, 1, 2, 3, 4]))
    assert res["statut"] == "HISTORIQUE_INSUFFISANT" and res["methodes"] == [] and res["n"] == 5
    assert res["manque"].startswith("1 point(s) de plus") and "non validée par Nathan" in res["manque"]


def test_horizon_au_dela_de_l_historique_sans_valeur():
    res = _projeter(_serie([1, 2, 3, 5, 6, 8], [0, 1, 2, 3, 4, 5]), horizons=("7j", "12m"))
    for methode in res["methodes"]:
        for entree in methode["projections"]:
            assert entree["statut"] == "HORIZON_AU_DELA_DE_L_HISTORIQUE" and "valeur" not in entree


def test_serie_constante_et_abscisses_identiques_nommees():
    constante = _projeter(_serie([4] * 6, [0, 1, 2, 3, 4, 5]))
    assert constante["statut"] == "SERIE_CONSTANTE" and constante["valeur_observee"] == "4"
    assert constante["methodes"] == []
    meme_jour = _chaine(*[(_leads(v), 0, s, {}) for s, v in enumerate([1, 2, 3, 4, 5, 6])])
    identiques = _projeter(meme_jour)
    assert identiques["statut"] == "ABSCISSES_IDENTIQUES" and identiques["methodes"] == []


def test_captures_partielle_refusee_et_contradictoire_ecartees_et_nommees():
    lead = {"lead_id": "L-fictif", "ingere_le": "2026-09-01T10:00:00Z"}
    chaine = _chaine(
        (_leads(1), 0, 0, {}),
        (_leads(2), 1, 0, {}),
        (_leads(99, suivant=20), 2, 0, {}),  # page suivante non lue : PARTIELLE
        (_refusee(), 3, 0, {}),  # REFUSEE
        (_leads(3, leads=[lead]), 4, 0, {}),
        (_leads(98, leads=[lead]), 4, 1, {}),  # même instant métier, réponse différente : CONTRADICTOIRE
        (_leads(5), 5, 0, {}),
        (_leads(6), 6, 0, {}),
        (_leads(7), 7, 0, {}),
        (_leads(1000), 8, 0, {"statut": "nouveau"}),  # autre série (autre filtre) : ignorée
    )
    res = _projeter(chaine)
    assert {(e["capture"], e["raison"]) for e in res["captures_ecartees"]} == {
        (2, "PARTIELLE"),
        (3, "REFUSEE"),
        (4, "CONTRADICTOIRE"),
        (5, "CONTRADICTOIRE"),
    }
    assert [p["capture"] for p in res["points"]] == [0, 1, 6, 7, 8]
    assert res["statut"] == "HISTORIQUE_INSUFFISANT"
    autre = _projeter(chaine, arguments={"statut": "nouveau"})
    assert [p["capture"] for p in autre["points"]] == [9]


def test_capture_inconnue_a_la_connaissance_ignoree():
    chaine = _serie([1, 2, 3, 4, 5, 7], [0, 1, 2, 3, 4, 5])
    res = td.projeter(chaine, lecture_id=LECTURE, chemin=CHEMIN, connaissance=_recu(4), horizons=["7j"])
    assert res["n"] == 5 and res["statut"] == "HISTORIQUE_INSUFFISANT"


def test_valeur_non_numerique_refusee_avec_son_adresse():
    for mauvaise in ("beaucoup", True, 3.5, None, "NaN"):
        chaine = _chaine(*[(_leads(v), j, 0, {}) for j, v in enumerate([1, 2, mauvaise, 4, 5, 6])])
        with pytest.raises(ValueError, match=r"REJ-TENDANCE-VALEUR-NON-NUMERIQUE : m2\.leads#2:p0\.resultat"):
            _projeter(chaine)


def test_texte_decimal_accepte_et_fait_absent_ecarte():
    chaine = _chaine(*[(_leads(v), j, 0, {}) for j, v in enumerate(["1.5", "2.5", "3.5", "4.5", "5.5", "7.5"])])
    assert _projeter(chaine)["statut"] == "PROJETEE"
    sans_total = {"ok": True, "resultat": {"accepte": True, "resultat": {"leads": [], "suivant": None}}}
    res = _projeter(_chaine((sans_total, 0, 0, {})))
    assert res["captures_ecartees"] == [{"capture": 0, "recu_a": _recu(0), "raison": "FAIT_ABSENT"}]


def test_valeur_negative_calculee_conservee_et_signalee():
    res = _projeter(_serie([20, 16, 12, 8, 4, 0], [0, 2, 4, 6, 8, 10]))  # y = 20 − 2x
    sept = _horizon(_methode(res, "droite"), "7j")
    assert sept["valeur"] == "-14.00" and sept["avertissements"]


def test_parametres_invalides_refuses():
    chaine = _serie([1, 2, 3, 4, 5, 7], [0, 1, 2, 3, 4, 5])
    with pytest.raises(ValueError, match="REJ-TENDANCE-HORIZONS"):
        _projeter(chaine, horizons=("8j",))
    with pytest.raises(ValueError, match="REJ-TENDANCE-HORIZONS"):
        _projeter(chaine, horizons=())
    with pytest.raises(ValueError, match="REJ-TENDANCE-CHEMIN"):
        td.projeter(chaine, lecture_id=LECTURE, chemin="resultat.resultat.leads[*].x", connaissance=CONNAISSANCE,
                    horizons=["7j"])  # fmt: skip
    with pytest.raises(ValueError, match="REJ-CAPTURE-LECTURE"):
        td.projeter(chaine, lecture_id="m99.inconnue", chemin=CHEMIN, connaissance=CONNAISSANCE, horizons=["7j"])
    with pytest.raises(ValueError, match="REJ-TENDANCE-SAISON"):
        _projeter(chaine, saison_jours=1)
    with pytest.raises(ValueError, match="REJ-TENDANCE-ARGUMENTS"):
        _projeter(chaine, arguments={"horodatage": "2026-10-01T00:00:00Z"})
    with pytest.raises(ValueError, match="REJ-CAPTURE-TEMPS"):
        td.projeter(chaine, lecture_id=LECTURE, chemin=CHEMIN, connaissance="2026-10-01T00:00:00", horizons=["7j"])


def test_deterministe_meme_projection_id_et_aucun_flottant():
    chaine = _serie([0, 1, 2, 3, 4, 5, 7, 6, 9, 8, 11, 12, 13, 15], list(range(14)))
    a = _projeter(chaine, horizons=("7j",), saison_jours=7)
    b = _projeter(chaine, horizons=("7j",), saison_jours=7)
    assert a == b and len(a["projection_id"]) == 64 and a["projection_id"] == b["projection_id"]
    sans_id = {k: v for k, v in a.items() if k != "projection_id"}
    assert a["projection_id"] == cs.empreinte(sans_id)
    assert _flottants(a) == 0
    json.dumps(a, allow_nan=False)  # sérialisable sans NaN
    assert _projeter(chaine, horizons=("7j",))["projection_id"] != a["projection_id"]


def test_les_limites_disent_que_l_intervalle_sous_estime_l_incertitude_au_loin():
    res = td.projeter(
        [], lecture_id="m2.leads", chemin="resultat.resultat.total", connaissance=CONNAISSANCE, horizons=["7j"]
    )
    assert any("sous-estime" in limite for limite in res["limites"]) and res["statut"] == "HISTORIQUE_INSUFFISANT"
