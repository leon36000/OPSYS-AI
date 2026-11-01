"""M8.11 — Score de santé : composite transparent, refus plutôt que faux score, historique, calibration.

Prouve (entreprises FICTIVES) : la définition est validée (pondérations entières de somme 100, mesures du catalogue et
non neutres, une mesure compte une fois) ; le calcul est exact et explicable (la somme des contributions est le score) ;
une mesure non calculable, périmée, de fraîcheur inconnue, ou des bornes absentes/invalides rendent la composante puis
le
score INDÉTERMINÉS (jamais un faux score, jamais une moyenne de ce qui reste) ; les bornes viennent du propriétaire ;
l'historique est append-only et sans bruit ; la calibration ordonne les entreprises dont l'état est connu et mesure la
sensibilité aux mesures et aux pondérations.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
import yaml
from m8_analytics import catalogue_mesures, fraicheur_mesures, jeux_fictifs, moteur_mesures, sante

FICTIF = True
_CAT = catalogue_mesures.charger()
_DEF = sante.charger(_CAT)
_MAINTENANT = "2026-10-30T20:00:00-04:00"
_CFG = sante.lire_configuration({"bornes": jeux_fictifs.BORNES_SANTE_FICTIVES}, _DEF)


def _mesures(maintenant=_MAINTENANT, **params):
    lues = moteur_mesures.lire(jeux_fictifs.registres_fictifs(**params), _CAT)
    return fraicheur_mesures.lire_mesures_avec_fraicheur(lues, _CAT, fraicheur_mesures.lire_maintenant(maintenant), {})


def _scenario(nom, maintenant=_MAINTENANT):
    return _mesures(maintenant, **jeux_fictifs.SCENARIOS_SANTE_FICTIFS[nom])


def test_la_definition_livree_est_valide_et_ses_ponderations_totalisent_cent():
    assert sum(c["poids"] for c in _DEF["composantes"]) == 100
    for composante in _DEF["composantes"]:
        assert sum(i["poids"] for i in composante["indicateurs"]) == 100
    assert {c["id"] for c in _DEF["composantes"]} == {"finance", "ventes", "operations", "qualite", "clientele"}
    assert len(_DEF["version_definition"]) == 64 and "CPA" in _DEF["mention"]
    proxies = [i["mesure"] for c in _DEF["composantes"] for i in c["indicateurs"] if i["proxy"]]
    assert proxies == ["m8_delai_lead_acceptation_jours"]


@pytest.fixture
def brut():
    return yaml.safe_load(sante._CHEMIN.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda d: d["composantes"][0].update({"poids": 30}), "totaliser 100"),
        (lambda d: d["composantes"][1]["indicateurs"][0].update({"poids": 10}), "totaliser 100"),
        (lambda d: d["composantes"][0]["indicateurs"][0].update({"mesure": "m8_sql_libre"}), "catalogue fermé"),
        (lambda d: d["composantes"][0]["indicateurs"][0].update({"mesure": "m8_chantiers_termines"}), "neutre"),
        (lambda d: d["composantes"][2]["indicateurs"][0].update({"mesure": "m8_cash_libre_cad"}), "deux indicateurs"),
        (lambda d: d["composantes"].append(copy.deepcopy(d["composantes"][0])), "en double"),
        (lambda d: d["composantes"][0].update({"extra": 1}), "exactement"),
        (lambda d: d["composantes"][0].update({"poids": True}), "poids"),
        (lambda d: d["composantes"][0]["indicateurs"][0].update({"proxy": "oui"}), "proxy"),
        (lambda d: d.update({"composantes": []}), "non vide"),
        (lambda d: d.update({"schema": "x"}), "schema"),
        (lambda d: d.update({"version": 0}), "version"),
        (lambda d: d.pop("mention"), "clés"),
    ],
)
def test_une_definition_mal_formee_est_refusee(brut, mutation, fragment):
    mutation(brut)
    with pytest.raises(sante.SanteRefusee, match=fragment) as exc:
        sante.valider_definition(brut, _CAT)
    assert exc.value.code == sante.REJ_SANTE_INVALIDE


# ---------------------------------------------------------------------------
# Le calcul est exact et explicable
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("valeur", "sens", "pire", "cible", "points"),
    [
        ("30", "plus_est_mieux", "20", "60", "25"),
        ("20", "plus_est_mieux", "20", "60", "0"),
        ("60", "plus_est_mieux", "20", "60", "100"),
        ("-5", "plus_est_mieux", "20", "60", "0"),
        ("90", "plus_est_mieux", "20", "60", "100"),
        ("4", "moins_est_mieux", "10", "0", "60"),
        ("12", "moins_est_mieux", "10", "0", "0"),
        ("-3", "moins_est_mieux", "10", "0", "100"),
    ],
)
def test_un_indicateur_interpole_lineairement_et_se_borne(valeur, sens, pire, cible, points):
    assert sante.score_indicateur(Decimal(valeur), sens, Decimal(pire), Decimal(cible)) == Decimal(points)


@pytest.mark.parametrize(("sens", "pire", "cible"), [("plus_est_mieux", "60", "20"), ("moins_est_mieux", "0", "10")])
def test_des_bornes_a_contre_sens_sont_refusees(sens, pire, cible):
    with pytest.raises(sante.SanteRefusee) as exc:
        sante.score_indicateur(Decimal("5"), sens, Decimal(pire), Decimal(cible))
    assert exc.value.code == sante.REJ_SANTE_BORNES_INVALIDES


def test_le_score_est_la_somme_des_contributions_et_chaque_composante_s_explique():
    resultat = sante.evaluer(_DEF, _scenario("correcte"), _CFG)
    assert resultat["statut"] == "determine" and resultat["score"] == "69.18"
    contributions = sum(Decimal(c["contribution"]) for c in resultat["composantes"])
    assert abs(contributions - Decimal(resultat["score"])) <= Decimal("0.03")  # écart d'arrondi seulement
    par_id = {c["id"]: c for c in resultat["composantes"]}
    assert par_id["finance"]["score"] == "60.00"  # cash 30000 entre 0 et 50000
    assert par_id["ventes"]["score"] == "73.00"  # 0,6 × 50 + 0,4 × 100... calculé sur 50 % et 3 sans réponse
    for composante in resultat["composantes"]:
        assert composante["explication"].startswith(composante["libelle"])
        for indicateur in composante["indicateurs"]:
            assert indicateur["valeur"] is not None and indicateur["source"] and indicateur["bornes"]
            assert indicateur["fraicheur"] in ("a_jour", "non_applicable")
    assert resultat["ponderations"]["composantes"] == {
        "finance": 25,
        "ventes": 25,
        "operations": 20,
        "qualite": 15,
        "clientele": 15,
    }
    assert "CPA" in resultat["mention"]


def test_les_chiffres_du_score_sont_du_texte_decimal_jamais_un_flottant():
    resultat = sante.evaluer(_DEF, _scenario("saine"), _CFG)
    textes = (
        [resultat["score"]]
        + [c["score"] for c in resultat["composantes"]]
        + [i["score"] for c in resultat["composantes"] for i in c["indicateurs"]]
    )
    assert all(isinstance(t, str) for t in textes)
    assert not [t for t in textes if "e" in t.lower()]


def test_le_calcul_est_deterministe_et_ne_modifie_pas_ses_entrees():
    mesures = _scenario("fragile")
    avant = copy.deepcopy(mesures)
    a = sante.evaluer(_DEF, mesures, _CFG)
    b = sante.evaluer(_DEF, mesures, _CFG)
    assert a == b and mesures == avant


# ---------------------------------------------------------------------------
# Refus plutôt que faux score
# ---------------------------------------------------------------------------
def test_sans_bornes_declarees_le_score_est_indetermine_et_dit_quoi_configurer():
    vide = sante.lire_configuration({}, _DEF)
    resultat = sante.evaluer(_DEF, _scenario("saine"), vide)
    assert resultat["statut"] == "indetermine" and resultat["score"] is None
    assert {m["raison"] for m in resultat["manques"]} == {sante.RAISON_BORNES_A_CONFIGURER}
    assert len(resultat["manques"]) == 6 and "bornes à configurer" in resultat["manques"][0]["detail"]
    assert all(c["statut"] == "indetermine" and c["score"] is None for c in resultat["composantes"])
    assert "INDÉTERMINÉ" in resultat["explication"] and "faux score" in resultat["explication"]


def test_une_mesure_non_calculable_rend_la_composante_et_le_score_indetermines():
    resultat = sante.evaluer(_DEF, _scenario("sans_constat_de_cash"), _CFG)
    assert resultat["statut"] == "indetermine" and resultat["score"] is None
    par_id = {c["id"]: c for c in resultat["composantes"]}
    assert par_id["finance"]["statut"] == "indetermine" and par_id["finance"]["score"] is None
    assert par_id["operations"]["score"] == "95.00"  # les composantes déterminables restent montrées
    assert [m["raison"] for m in resultat["manques"]] == [sante.RAISON_MESURE_MANQUANTE]
    assert "mesure non calculable" in par_id["finance"]["explication"]


def test_une_mesure_perimee_rend_le_score_indetermine_jamais_note():
    resultat = sante.evaluer(_DEF, _scenario("saine", maintenant="2026-11-09T09:00:00-04:00"), _CFG)
    assert resultat["statut"] == "indetermine" and resultat["score"] is None
    raisons = {m["raison"] for m in resultat["manques"]}
    assert raisons == {sante.RAISON_MESURE_PERIMEE}
    metriques = {m["metric_id"] for m in resultat["manques"]}
    assert "m8_cash_libre_cad" in metriques and "m8_taux_acceptation_pct" in metriques
    assert "m8_ecart_duree_equipe_pct" not in metriques  # une mesure terminale ne vieillit pas


def test_une_fraicheur_inconnue_rend_le_score_indetermine():
    mesures = _scenario("saine")
    mesures = [
        {
            **m,
            "dernier_fait_le": None,
            "fraicheur": {
                **m["fraicheur"],
                "statut": "inconnu",
                "peut_etre_montree_comme_a_jour": False,
                "motif": "aucun instant",
            },
        }
        if m["metric_id"] == "m8_cash_libre_cad"
        else m
        for m in mesures
    ]
    resultat = sante.evaluer(_DEF, mesures, _CFG)
    assert resultat["statut"] == "indetermine"
    assert [m["raison"] for m in resultat["manques"]] == [sante.RAISON_FRAICHEUR_INCONNUE]


def test_un_seul_indicateur_inconnu_suffit_aucune_moyenne_du_reste():
    mesures = _scenario("saine")
    mesures = [
        {**m, "statut": "non_calculable", "valeur": None, "detail": "non calculable, manque x"}
        if m["metric_id"] == "m8_devis_sans_reponse"
        else m
        for m in mesures
    ]
    resultat = sante.evaluer(_DEF, mesures, _CFG)
    assert resultat["score"] is None
    ventes = {c["id"]: c for c in resultat["composantes"]}["ventes"]
    assert ventes["statut"] == "indetermine" and ventes["score"] is None  # même si le taux d'acceptation est connu


def test_les_bornes_invalides_ou_inconnues_sont_dites_jamais_corrigees():
    cfg = sante.lire_configuration(
        {
            "bornes": {
                "m8_cash_libre_cad": {"pire": "5", "cible": "5"},
                "m8_taux_acceptation_pct": {"pire": True, "cible": "60"},
                "m8_devis_sans_reponse": {"pire": "10", "cible": "0", "extra": 1},
                "m8_chantiers_termines": {"pire": "0", "cible": "9"},
                "m8_ecart_duree_equipe_pct": {"pire": "0", "cible": "40"},  # à contre-sens de « moins_est_mieux »
            }
        },
        _DEF,
    )
    assert {i["metric_id"] for i in cfg["invalides"]} == {
        "m8_cash_libre_cad",
        "m8_taux_acceptation_pct",
        "m8_devis_sans_reponse",
    }
    assert cfg["ignorees"] == ["m8_chantiers_termines"]
    resultat = sante.evaluer(_DEF, _scenario("saine"), cfg)
    assert resultat["statut"] == "indetermine"
    raisons = {m["metric_id"]: m["raison"] for m in resultat["manques"]}
    assert raisons["m8_cash_libre_cad"] == sante.RAISON_BORNES_INVALIDES
    assert raisons["m8_ecart_duree_equipe_pct"] == sante.RAISON_BORNES_INVALIDES
    assert resultat["configuration"]["cles_ignorees"] == ["m8_chantiers_termines"]


@pytest.mark.parametrize("configuration", [None, "texte", 12, [], {"bornes": "x"}, {"bornes": None}])
def test_une_configuration_illisible_ne_donne_aucune_borne_inventee(configuration):
    cfg = sante.lire_configuration(configuration, _DEF)
    assert cfg["bornes"] == {} and sante.evaluer(_DEF, _scenario("saine"), cfg)["score"] is None


def test_les_ponderations_disent_si_elles_ont_ete_validees_sans_changer_le_score():
    sans = sante.evaluer(_DEF, _scenario("correcte"), _CFG)
    cfg = sante.lire_configuration(
        {"bornes": jeux_fictifs.BORNES_SANTE_FICTIVES, "ponderations_validees_par": "Propriétaire fictif"}, _DEF
    )
    avec = sante.evaluer(_DEF, _scenario("correcte"), cfg)
    assert sans["ponderations"]["validee"] is False and avec["ponderations"]["validee"] is True
    assert avec["ponderations"]["validee_par"] == "Propriétaire fictif" and avec["score"] == sans["score"]
    vide = sante.lire_configuration({"ponderations_validees_par": "  "}, _DEF)
    assert vide["ponderations_validees_par"] is None


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------
def test_la_ligne_d_historique_garde_le_jugement_pas_les_donnees():
    resultat = sante.evaluer(_DEF, _scenario("correcte"), _CFG)
    ligne = sante.ligne_historique(resultat, maintenant=_MAINTENANT, empreinte_registres="e" * 64)
    assert ligne["score"] == "69.18" and ligne["statut"] == "determine" and ligne["composantes"]["finance"] == "60.00"
    assert "valeur" not in repr(ligne) and ligne["empreinte_registres"] == "e" * 64
    autre = sante.ligne_historique(
        sante.evaluer(_DEF, _scenario("fragile"), _CFG), maintenant=_MAINTENANT, empreinte_registres="e" * 64
    )
    assert sante.meme_jugement(ligne, dict(ligne)) and not sante.meme_jugement(ligne, autre)
    with pytest.raises(ValueError, match="REJ-FRAICHEUR-MAINTENANT-INVALIDE"):
        sante.ligne_historique(resultat, maintenant="hier", empreinte_registres="e" * 64)


def test_une_ligne_indeterminee_garde_un_score_vide_dans_l_historique():
    resultat = sante.evaluer(_DEF, _scenario("sans_constat_de_cash"), _CFG)
    ligne = sante.ligne_historique(resultat, maintenant=_MAINTENANT, empreinte_registres="a" * 64)
    assert ligne["statut"] == "indetermine" and ligne["score"] is None and ligne["composantes"]["finance"] is None


# ---------------------------------------------------------------------------
# Calibration et sensibilité (entreprises fictives dont l'état est connu)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def rapport():
    scenarios = {nom: _scenario(nom) for nom in jeux_fictifs.SCENARIOS_SANTE_FICTIFS}
    return sante.calibrer(_DEF, _CFG, scenarios)


def test_la_calibration_ordonne_les_entreprises_dont_l_etat_est_connu(rapport):
    assert rapport["fictif"] is True
    assert rapport["ordre"] == ["saine", "correcte", "fragile"]
    scores = {nom: Decimal(s["score"]) for nom, s in rapport["scores"].items() if s["score"] is not None}
    assert all(Decimal(0) <= s <= Decimal(100) for s in scores.values())
    assert scores["saine"] - scores["correcte"] > 20 and scores["correcte"] - scores["fragile"] > 20
    assert rapport["scores"]["sans_constat_de_cash"] == {"statut": "indetermine", "score": None}


def test_la_sensibilite_aux_mesures_est_bornee_par_la_ponderation(rapport):
    poids = {i["mesure"]: i["poids"] * c["poids"] / 100 for c in _DEF["composantes"] for i in c["indicateurs"]}
    assert rapport["sensibilite_mesures"]
    for ligne in rapport["sensibilite_mesures"]:
        delta = abs(Decimal(ligne["points_globaux"]))
        # 10 % de l'étendue = 10 points d'indicateur au plus : jamais plus que 10 % de la pondération globale
        assert delta <= Decimal(str(poids[ligne["metric_id"]])) * Decimal("0.1") + Decimal("0.01")
        assert Decimal(ligne["points_globaux"]) >= 0  # déplacer vers le mieux ne baisse jamais le score


def test_l_ordre_des_entreprises_resiste_a_un_transfert_de_cinq_points_de_ponderation(rapport):
    assert rapport["sensibilite_ponderations"]
    assert all(ligne["ordre_inchange"] for ligne in rapport["sensibilite_ponderations"])
    for ligne in rapport["sensibilite_ponderations"]:
        assert set(ligne["scores"]) == {"saine", "correcte", "fragile"}


def test_la_calibration_ne_touche_pas_aux_scenarios(rapport):
    scenarios = {nom: _scenario(nom) for nom in jeux_fictifs.SCENARIOS_SANTE_FICTIFS}
    avant = copy.deepcopy(scenarios)
    sante.calibrer(_DEF, _CFG, scenarios)
    assert scenarios == avant
