"""Apprentissage des durées sur site (pur) : politique déclarée, observations certifiées, estimateur robuste,
gouvernance, dérive, équipes sans biais de difficulté. Données FICTIVES (fictif: true), horloge injectée, graine par
le contenu : aucun sleep, aucun réseau."""

from __future__ import annotations

import copy
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import apprentissage_durees as ad  # noqa: E402

FICTIF = True
MAINTENANT = "2026-09-01T12:00:00Z"
_REF = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
POLITIQUE_BRUTE = {
    "version": "m3-apprentissage-durees/1", "echantillon_minimum": 8, "echantillon_minimum_equipe": 4,
    "demi_vie_jours": 90, "aberrantes_k": "3.5", "echelle_minimale_relative": "0.05", "niveau_confiance": "0.90",
    "replications": 300, "variation_minimale_pct": "1", "variation_auto_max_pct": "20", "facteur_min": "0.5",
    "facteur_max": "2", "derive_fenetre": 8, "derive_seuil_pct": "15", "complexites": ["standard", "difficile"],
}
BASELINE = "30"  # minutes par pi_lin ; 28 pi_lin = 840 min = 14 h


def politique():
    p, verdict = ad.lire_politique(copy.deepcopy(POLITIQUE_BRUTE))
    assert verdict is None
    return p


def obs(i, taux, *, jours=10, quantite=28, service="gouttieres", equipe=None, complexite=None, **plus):
    fin = _REF - timedelta(days=jours, hours=i % 5)
    brute = {
        "wct_id": f"wct-{service}-{i:03d}", "chantier_id": f"job-{service}-{i:03d}",
        "type_service": service, "unite_quantite": "pi_lin", "quantite": str(quantite),
        "duree_reelle_minutes": round(quantite * Decimal(str(taux))),
        "horodatage_debut": (fin - timedelta(hours=7)).isoformat().replace("+00:00", "Z"),
        "horodatage_completion": fin.isoformat().replace("+00:00", "Z"), "statut": "completed_verified",
        "preuve": {"liaison_exacte": True, "chaine_m3_valide": True, "semantique_reel": "duree_ecoulee_intervention",
                   "unite_duree_reelle": "minute"},
        "equipe_ref": equipe, "complexite": complexite,
    }
    brute.update(plus)
    return brute


def lignes(brutes, pol=None):
    r = ad.preparer_observations(brutes, maintenant_utc=MAINTENANT, politique=pol or politique())
    assert r["statut"] == "ok"
    return r


def cohorte(brutes, *, baseline=BASELINE, courant=None, regime=None, service="gouttieres"):
    r = lignes(brutes)
    return ad.calculer_cohorte(
        r["lignes"], type_service=service, unite_quantite="pi_lin", taux_baseline=baseline, taux_courant=courant,
        regime_depuis_utc=regime, politique=politique(),
    )


BRUIT = [0.98, 1.02, 1.0, 0.99, 1.01, 1.0, 1.02, 0.98, 1.0, 1.01, 0.99, 1.0, 1.01, 0.99, 1.0, 1.02]


def serie(n, centre, *, depart=0, jours0=10, **plus):
    return [obs(depart + i, centre * BRUIT[i % len(BRUIT)], jours=jours0 + i, **plus) for i in range(n)]


# ------------------------------------------------------------------------------------------ politique
def test_politique_complete_acceptee_et_decimaux_exacts():
    p = politique()
    assert p["variation_auto_max_pct"] == Decimal("20") and p["derive_fenetre"] == 8
    assert len(p["empreinte"]) == 64


def test_politique_absente_fail_closed_et_dit_quoi_declarer():
    for brut in (None, {}, {k: None for k in ad.CHAMPS_POLITIQUE}):
        p, verdict = ad.lire_politique(brut)
        assert p is None and verdict["code"] == "REJ-APPRENTISSAGE-POLITIQUE-ABSENTE"
        assert "echantillon_minimum" in verdict["detail"] and "aucune valeur par défaut" in verdict["detail"]


@pytest.mark.parametrize("champ", ad.CHAMPS_POLITIQUE)
def test_chaque_champ_de_la_politique_est_obligatoire(champ):
    brut = copy.deepcopy(POLITIQUE_BRUTE)
    brut[champ] = None
    p, verdict = ad.lire_politique(brut)
    assert p is None and verdict["code"] == "REJ-APPRENTISSAGE-POLITIQUE-ABSENTE"
    brut = copy.deepcopy(POLITIQUE_BRUTE)
    del brut[champ]
    assert ad.lire_politique(brut)[0] is None


@pytest.mark.parametrize("champ,valeur", [
    ("echantillon_minimum", 1), ("echantillon_minimum", True), ("variation_auto_max_pct", "0"),
    ("variation_auto_max_pct", 20.0), ("facteur_min", "1.5"), ("facteur_max", "0.9"), ("niveau_confiance", "1"),
    ("derive_fenetre", 7), ("variation_minimale_pct", "25"), ("complexites", ["inconnue"]),
    ("complexites", ["a", "a"]), ("complexites", []), ("demi_vie_jours", 1), ("replications", 10),
])
def test_valeurs_structurellement_absurdes_refusees(champ, valeur):
    brut = copy.deepcopy(POLITIQUE_BRUTE)
    brut[champ] = valeur
    assert ad.lire_politique(brut)[0] is None


def test_empreinte_trie_les_cles_echappe_les_non_ascii_et_refuse_nan():
    assert ad.empreinte({"x": "é"}) == hashlib.sha256(b'{"x":"\\u00e9"}').hexdigest()
    assert ad.empreinte({"b": 1, "a": 2}) == hashlib.sha256(b'{"a":2,"b":1}').hexdigest()
    with pytest.raises(ValueError):
        ad.empreinte(float("nan"))


def test_politique_canonique_est_toute_la_politique_sauf_son_empreinte():
    canon = ad.politique_canonique(politique())
    assert set(canon) == set(ad.CHAMPS_POLITIQUE)
    assert "empreinte" not in canon


def test_texte_decimal_est_borne_a_quarante_caracteres():
    assert ad._decimal("1" * 40) is not None
    assert ad._decimal("1" * 41) is None


def test_entier_accepte_les_bornes_exactes_et_refuse_juste_au_dela():
    assert ad._entier(3, 3, 1000) == 3
    assert ad._entier(1000, 3, 1000) == 1000
    assert ad._entier(2, 3, 1000) is None
    assert ad._entier(1001, 3, 1000) is None
    assert ad._entier(True, 3, 1000) is None


def _politique_avec(**champs):
    brut = copy.deepcopy(POLITIQUE_BRUTE)
    brut.update(champs)
    return brut


@pytest.mark.parametrize("champs,attendu", [
    ({"echantillon_minimum": 3}, True),
    ({"echantillon_minimum": 1000, "derive_fenetre": 1000}, True),
    ({"echantillon_minimum": 2}, False),
    ({"echantillon_minimum": 1001, "derive_fenetre": 1000}, False),
    ({"echantillon_minimum_equipe": 3}, True),
    ({"echantillon_minimum_equipe": 1000}, True),
    ({"echantillon_minimum_equipe": 1001}, False),
    ({"echantillon_minimum_equipe": 2}, False),
    ({"demi_vie_jours": 7}, True),
    ({"demi_vie_jours": 3650}, True),
    ({"demi_vie_jours": 6}, False),
    ({"demi_vie_jours": 3651}, False),
    ({"replications": 200}, True),
    ({"replications": 5000}, True),
    ({"replications": 199}, False),
    ({"replications": 5001}, False),
    ({"echantillon_minimum": 3, "derive_fenetre": 3}, True),
    ({"derive_fenetre": 1000}, True),
    ({"echantillon_minimum": 3, "derive_fenetre": 2}, False),
    ({"derive_fenetre": 1001}, False),
])
def test_les_bornes_des_entiers_de_la_politique_sont_exactes(champs, attendu):
    assert (ad.lire_politique(_politique_avec(**champs))[0] is not None) == attendu


@pytest.mark.parametrize("champ,valeurs_acceptees,valeurs_refusees", [
    ("aberrantes_k", ["2", "10"], ["1.9", "10.1"]),
    ("echelle_minimale_relative", ["0.001", "1"], ["0.0009", "1.1"]),
    ("niveau_confiance", ["0.5", "0.999"], ["0.499", "1"]),
    ("facteur_min", ["0.01", "1"], ["0.009", "1.1"]),
    ("facteur_max", ["1", "100"], ["0.9", "101"]),
    ("derive_seuil_pct", ["1", "1000"], ["0.9", "1001"]),
])
def test_les_bornes_des_decimaux_de_la_politique_sont_exactes(champ, valeurs_acceptees, valeurs_refusees):
    for valeur in valeurs_acceptees:
        assert ad.lire_politique(_politique_avec(**{champ: valeur}))[0] is not None, valeur
    for valeur in valeurs_refusees:
        assert ad.lire_politique(_politique_avec(**{champ: valeur}))[0] is None, valeur


def test_les_paliers_de_variation_doivent_rester_strictement_ordonnes():
    assert ad.lire_politique(_politique_avec(variation_minimale_pct="20", variation_auto_max_pct="20"))[0] is None


@pytest.mark.parametrize("complexites", [["aa"], ["aa", "bb", "cc", "dd", "ee", "ff", "gg", "hh"]])
def test_une_a_huit_complexites_distinctes_sont_acceptees(complexites):
    assert ad.lire_politique(_politique_avec(complexites=complexites))[0] is not None


@pytest.mark.parametrize("complexites", [[], ["aa", "bb", "cc", "dd", "ee", "ff", "gg", "hh", "ii"], [1]])
def test_complexites_hors_bornes_ou_non_textuelles_sont_refusees(complexites):
    assert ad.lire_politique(_politique_avec(complexites=complexites))[0] is None


# ---------------------------------------------------------------------------------------- observations
def test_exclusions_comptees_par_raison_et_le_deplacement_n_entre_jamais():
    pol = politique()
    bonnes = serie(3, 30)
    mauvaises = [
        obs(10, 30, statut="completed_unverified"),
        obs(11, 30, preuve={"liaison_exacte": False, "chaine_m3_valide": True,
                            "semantique_reel": "duree_ecoulee_intervention", "unite_duree_reelle": "minute"}),
        obs(19, 30, preuve={"liaison_exacte": True, "chaine_m3_valide": False,
                            "semantique_reel": "duree_ecoulee_intervention", "unite_duree_reelle": "minute"}),
        obs(12, 30, preuve={"liaison_exacte": True, "chaine_m3_valide": True,
                            "semantique_reel": "duree_porte_a_porte", "unite_duree_reelle": "minute"}),
        obs(13, 30, inclut_deplacement=True),
        obs(14, 30, preuve={"liaison_exacte": True, "chaine_m3_valide": True,
                            "semantique_reel": "duree_ecoulee_intervention", "unite_duree_reelle": "heure"}),
        obs(15, 30, duree_reelle_minutes=0),
        obs(16, 30, duree_reelle_minutes=840.5),
        obs(17, 30, horodatage_completion="2026-09-02T00:00:00Z"),  # futur
        obs(18, 30, complexite="extreme"),
        "pas un dict",
    ]
    r = ad.preparer_observations(bonnes + mauvaises, maintenant_utc=MAINTENANT, politique=pol)
    assert len(r["lignes"]) == 3
    assert r["exclusions"] == {
        "non_certifiee": 3, "semantique_non_sur_site": 2, "unite_non_minute": 1, "mesure_invalide": 2,
        "dans_le_futur": 1, "complexite_hors_echelle": 1, "forme_invalide": 1,
    }


def test_rejeu_identique_compte_une_fois_et_conflit_exclut_toutes_les_versions():
    pol = politique()
    a = obs(1, 30)
    divergente = {**a, "duree_reelle_minutes": a["duree_reelle_minutes"] + 60}
    r = ad.preparer_observations([a, copy.deepcopy(a), obs(2, 30), divergente, divergente], maintenant_utc=MAINTENANT,
                                 politique=pol)
    assert [x["wct_id"] for x in r["lignes"]] == ["wct-gouttieres-002"]
    assert r["rejeux"] == 1 and r["exclusions"] == {"conflit_rejeu": 1}


def test_entree_hors_limite_ou_horloge_invalide_refusee():
    assert ad.preparer_observations([], maintenant_utc="hier", politique=politique())["statut"] == "refuse"
    assert ad.preparer_observations("x", maintenant_utc=MAINTENANT, politique=politique())["statut"] == "refuse"
    assert ad.preparer_observations([{}] * 2001, maintenant_utc=MAINTENANT, politique=politique())["statut"] == "refuse"


def test_instant_borne_a_quarante_caracteres_et_fuseau_obligatoire():
    quarante = "2026-09-01T12:00:00." + "1" * 14 + "+00:00"
    quarante_et_un = "2026-09-01T12:00:00." + "1" * 15 + "+00:00"
    assert len(quarante) == 40 and ad._instant(quarante) is not None
    assert len(quarante_et_un) == 41 and ad._instant(quarante_et_un) is None
    assert ad._instant(123) is None
    assert ad._instant("2026-09-01T12:00:00") is None


def test_identite_non_textuelle_et_chronologie_incomplete_sont_exclues_par_raison():
    r = ad.preparer_observations(
        [obs(20, 30, wct_id=123), obs(21, 30, horodatage_debut="pas une date"),
         obs(22, 30, horodatage_completion="pas une date")],
        maintenant_utc=MAINTENANT, politique=politique(),
    )
    assert r["lignes"] == []
    assert r["exclusions"] == {"identite_invalide": 1, "chronologie_invalide": 2}


def test_les_bornes_de_la_duree_reelle_sont_exactes():
    r = ad.preparer_observations(
        [obs(23, 30, quantite=1, duree_reelle_minutes=1),
         obs(24, 30, quantite=1_000_000, duree_reelle_minutes=1_000_000),
         obs(25, 30, quantite=1_000_000, duree_reelle_minutes=1_000_001)],
        maintenant_utc=MAINTENANT, politique=politique(),
    )
    assert {x["wct_id"] for x in r["lignes"]} == {"wct-gouttieres-023", "wct-gouttieres-024"}
    assert r["exclusions"] == {"mesure_invalide": 1}


def test_debut_egal_a_la_fin_et_fin_exactement_a_l_horloge_sont_acceptes():
    fin = "2026-09-01T07:00:00Z"
    r = ad.preparer_observations(
        [obs(30, 30, horodatage_debut=fin, horodatage_completion=fin),
         obs(31, 30, horodatage_debut="2026-09-01T05:00:00Z", horodatage_completion=MAINTENANT)],
        maintenant_utc=MAINTENANT, politique=politique(),
    )
    assert len(r["lignes"]) == 2 and r["exclusions"] == {}


def test_equipe_non_textuelle_est_exclue_au_lieu_de_faire_echouer_la_lecture():
    r = ad.preparer_observations([obs(32, 30, equipe=123)], maintenant_utc=MAINTENANT, politique=politique())
    assert r["lignes"] == [] and r["exclusions"] == {"equipe_invalide": 1}


def test_age_en_jours_compte_les_jours_et_les_secondes_du_jour():
    r = ad.preparer_observations(
        [obs(33, 30, horodatage_debut="2026-08-22T00:00:00Z",
             horodatage_completion="2026-08-22T07:00:00Z")],
        maintenant_utc=MAINTENANT, politique=politique(),
    )
    attendu = Decimal(10) + Decimal(5) / Decimal(24)
    assert r["lignes"][0]["age_jours"].quantize(Decimal("0.000001")) == attendu.quantize(Decimal("0.000001"))


def test_deux_mille_observations_exactement_sont_encore_lues():
    r = ad.preparer_observations(
        [obs(i, 30, jours=10 + i) for i in range(2000)], maintenant_utc=MAINTENANT, politique=politique(),
    )
    assert r["statut"] == "ok" and len(r["lignes"]) == 2000


def test_observation_invalide_puis_valide_du_meme_wct_reste_exclue():
    valide = obs(34, 30)
    invalide = {**valide, "duree_reelle_minutes": 0}
    r = ad.preparer_observations([invalide, valide], maintenant_utc=MAINTENANT, politique=politique())
    assert r["lignes"] == [] and r["exclusions"] == {"mesure_invalide": 1}


def test_observation_valide_puis_version_invalide_divergente_exclut_tout():
    valide = obs(35, 30)
    invalide = {**valide, "duree_reelle_minutes": 0}
    r = ad.preparer_observations([valide, invalide], maintenant_utc=MAINTENANT, politique=politique())
    assert r["lignes"] == []
    assert r["exclusions"] == {"mesure_invalide": 1, "conflit_rejeu": 1}


# ------------------------------------------------------------------------------------------- cohortes
def test_type_a_estime_14h_mais_16h_reelles_donne_une_candidate_auto_applicable_avec_intervalle():
    c = cohorte(serie(12, 960 / 28))
    assert c["decision"] == "auto_applicable" and c["raisons"] == ["petit_ajustement_dans_les_bornes"]
    assert c["n_chantiers"] == 12
    appris = Decimal(c["taux_appris"])
    assert Decimal("34.0") < appris < Decimal("34.6")  # 960/28 = 34,2857 min par pi_lin, soit ~16 h pour 28 pi_lin
    assert abs(appris * 28 - 960) < 20
    assert Decimal(c["intervalle"]["bas"]) <= appris <= Decimal(c["intervalle"]["haut"])
    assert Decimal(c["intervalle"]["bas"]) > Decimal(BASELINE)  # l'intervalle EXCLUT l'ancienne valeur
    assert Decimal("1.12") < Decimal(c["facteur"]) < Decimal("1.16")
    assert c["derive"]["detectee"] is False and c["exclues"] == {}


def test_type_b_stable_ne_bouge_pas():
    c = cohorte(serie(14, 30, service="revetement"), service="revetement")
    assert c["decision"] == "stable" and c["raisons"] == ["taux_en_vigueur_dans_l_intervalle"]


def test_echantillon_insuffisant_ne_produit_aucune_decision_de_changement():
    c = cohorte(serie(7, 40))
    assert c["decision"] == "insuffisante" and c["raisons"] == ["echantillon_insuffisant"] and "taux_appris" not in c
    assert cohorte([])["raisons"] == ["aucune_observation"]


def test_seuil_d_echantillon_se_compte_en_chantiers_distincts_pas_en_observations():
    deux_par_chantier = []
    for i, brute in enumerate(serie(14, 40)):
        deux_par_chantier.append({**brute, "chantier_id": f"job-{i // 2}"})  # 14 WCT, 7 chantiers
    assert cohorte(deux_par_chantier)["decision"] == "insuffisante"


def test_observation_aberrante_exclue_et_comptee_sans_changer_le_resultat():
    base = cohorte(serie(12, 960 / 28))
    avec = cohorte(serie(12, 960 / 28) + [obs(90, 3 * 960 / 28), obs(91, 0.2 * 960 / 28)])
    assert avec["exclues"] == {"aberrante": 2}
    assert avec["taux_appris"] == base["taux_appris"] and avec["decision"] == "auto_applicable"


def test_donnees_identiques_ne_font_pas_rejeter_tout_ecart_grace_au_plancher_d_echelle():
    c = cohorte(serie(10, 30) + [obs(70, 30.4)])  # MAD nul ; 1,3 % d'écart n'est pas une aberration
    assert "aberrante" not in c["exclues"]


def test_variation_au_dela_du_palier_attend_une_approbation_humaine():
    c = cohorte(serie(12, 30 * 1.4))
    assert c["decision"] == "approbation_requise" and c["raisons"] == ["variation_superieure_au_palier"]


def test_palier_est_relatif_au_taux_en_vigueur_pas_au_bareme():
    # 34,3 contre barème 30 : +14 % (auto) ; contre une version en vigueur à 33 : +4 % (auto aussi) ;
    # mais contre une version en vigueur à 26 : +32 % -> approbation.
    assert cohorte(serie(12, 34.3), courant="33")["decision"] == "auto_applicable"
    assert cohorte(serie(12, 34.3), courant="26")["decision"] == "approbation_requise"


def test_facteur_hors_bornes_absolues_est_refuse_meme_pas_approuvable():
    c = cohorte(serie(12, 30 * 2.6))
    assert c["decision"] == "refusee_hors_bornes"
    assert cohorte(serie(12, 30 * 0.3))["decision"] == "refusee_hors_bornes"


def test_variation_minimale_evite_le_bruit():
    # Intervalle serré qui exclurait le barème d'un cheveu : sous 1 % de variation, rien ne change.
    c = cohorte(serie(14, 30.2))
    assert c["decision"] == "stable"


def test_derive_brutale_exige_approbation_et_reestime_sur_le_nouveau_regime():
    anciennes = serie(12, 30, jours0=60)                       # régime historique à 30
    recentes = serie(8, 30 * 1.45, depart=100, jours0=1)        # saut brutal à +45 %
    c = cohorte(anciennes + recentes, courant="30")
    assert c["derive"]["detectee"] is True and Decimal(c["derive"]["ecart_pct"]) > 15
    assert c["decision"] == "approbation_requise" and "derive_detectee" in c["raisons"]
    assert abs(Decimal(c["taux_appris"]) - Decimal("43.5")) < Decimal("1.5")  # ré-estimé sur la fenêtre récente
    assert c["regime_depuis_utc"] is not None


def test_derive_absorbee_par_la_version_en_vigueur_ne_se_repete_pas_et_l_ancien_regime_ne_dilue_pas():
    anciennes = serie(12, 30, jours0=60)
    recentes = serie(8, 43.5, depart=100, jours0=1)
    premier = cohorte(anciennes + recentes, courant="30")
    apres = cohorte(anciennes + recentes, courant="43.5", regime=premier["regime_depuis_utc"])
    assert apres["derive"].get("detectee") is not True
    assert apres["exclues"].get("avant_changement_de_regime") == 12
    assert apres["decision"] == "stable"


def test_derive_non_evaluable_sans_deux_fenetres():
    c = cohorte(serie(12, 30 * 1.45))
    assert c["derive"]["evaluable"] is False and c["derive"]["detectee"] is False


def test_poids_d_age_favorise_le_recent_sans_effacer_l_ancien():
    anciennes = [obs(i, 30, jours=400 + i) for i in range(7)]
    recentes = [obs(50 + i, 33, jours=1 + i) for i in range(5)]
    c = cohorte(anciennes + recentes)
    assert Decimal(c["taux_appris"]) > Decimal("32.5")  # sans poids d'âge, 7 anciennes contre 5 récentes donneraient 30
    pol = politique()
    plat = {**pol, "demi_vie_jours": 3650}
    r = ad.preparer_observations(anciennes + recentes, maintenant_utc=MAINTENANT, politique=plat)
    c2 = ad.calculer_cohorte(r["lignes"], type_service="gouttieres", unite_quantite="pi_lin", taux_baseline="30",
                             politique=plat)
    assert Decimal(c2["taux_appris"]) == Decimal("30")


def test_calcul_deterministe_et_independant_de_l_ordre():
    donnees = serie(12, 34.3)
    a = cohorte(donnees)
    b = cohorte(list(reversed(donnees)))
    assert a == b and a == cohorte(copy.deepcopy(donnees))


def test_horloge_injectee_change_les_poids_pas_la_decision_de_forme():
    donnees = serie(12, 34.3)
    pol = politique()
    plus_tard = ad.preparer_observations(donnees, maintenant_utc="2027-09-01T12:00:00Z", politique=pol)
    assert all(x["poids"] < Decimal("0.1") for x in plus_tard["lignes"])


@pytest.mark.parametrize("mois,saison", [
    (12, "hiver"), (1, "hiver"), (2, "hiver"), (3, "printemps"), (4, "printemps"), (5, "printemps"),
    (6, "ete"), (7, "ete"), (8, "ete"), (9, "automne"), (10, "automne"), (11, "automne"),
])
def test_chaque_mois_du_calendrier_a_sa_saison(mois, saison):
    assert ad.saison_de(datetime(2026, mois, 1, tzinfo=UTC)) == saison


def test_saisons_sont_decrites_sans_changer_le_taux():
    c = cohorte(serie(12, 34.3))
    assert set(c["saisons"]) <= {"hiver", "printemps", "ete", "automne"} and sum(
        s["n"] for s in c["saisons"].values()) == 12


def test_controle_d_application_exige_le_meme_bareme_et_la_meme_cohorte():
    v = {"cohorte": {"type_service": "gouttieres", "unite_quantite": "pi_lin"}, "taux_baseline": "30.0000",
         "taux_applique": "34.2857"}
    ok = dict(type_service="gouttieres", unite_quantite="pi_lin")
    assert ad.controler_application(v, taux_baseline="30", **ok) is None
    assert ad.controler_application(v, taux_baseline="31", **ok) == "bareme_modifie_depuis_la_version"
    autre = ad.controler_application(v, taux_baseline="30", type_service="x", unite_quantite="pi_lin")
    assert autre == "cohorte_differente"
    assert ad.controler_application(v, taux_baseline="0", **ok) == "taux_invalide"


# --------------------------------------------------------------------------------------------- équipes
def jobs_equipe(equipe, n, taux, *, complexite, depart, service="gouttieres"):
    return [obs(depart + i, taux * BRUIT[i % len(BRUIT)], jours=5 + i, equipe=equipe, complexite=complexite,
                service=service) for i in range(n)]


def perf(brutes):
    return ad.performance_equipes(lignes(brutes)["lignes"], politique=politique())


def ligne_equipe(rapport, equipe):
    return next(e for e in rapport["equipes"] if e["equipe_ref"] == equipe)


def test_l_equipe_reellement_plus_rapide_ressort_avec_un_intervalle_lisible():
    brutes = (jobs_equipe("eq-a", 9, 27, complexite="standard", depart=0)
              + jobs_equipe("eq-b", 9, 33, complexite="standard", depart=100))
    r = perf(brutes)
    a, b = ligne_equipe(r, "eq-a"), ligne_equipe(r, "eq-b")
    assert a["evaluable"] and b["evaluable"]
    assert Decimal(a["indice_median"]) < Decimal("0.95") < Decimal("1.05") < Decimal(b["indice_median"])
    assert a["chantiers"] == 9 and "9 chantiers de ce type" in a["lecture"]
    assert Decimal(a["borne_basse"]) <= Decimal(a["indice_median"]) <= Decimal(a["borne_haute"])


def test_equipe_toujours_sur_les_chantiers_faciles_ne_ressort_pas_meilleure():
    # E fait 8 chantiers faciles (20 min/pi_lin) ; F en fait 4 faciles (20) et 8 difficiles (40) : même vitesse relat…
    # Sans normalisation E paraîtrait 40 % plus rapide ; avec elle, les deux valent ~1.
    brutes = (jobs_equipe("eq-e", 8, 20, complexite="standard", depart=0)
              + jobs_equipe("eq-f", 4, 20, complexite="standard", depart=100)
              + jobs_equipe("eq-f", 8, 40, complexite="difficile", depart=200)
              + jobs_equipe("eq-g", 4, 40, complexite="difficile", depart=300))
    r = perf(brutes)
    e, f = ligne_equipe(r, "eq-e"), ligne_equipe(r, "eq-f")
    assert e["evaluable"] and f["evaluable"]
    assert abs(Decimal(e["indice_median"]) - Decimal(f["indice_median"])) < Decimal("0.05")
    assert abs(Decimal(e["indice_median"]) - 1) < Decimal("0.05")


def test_strate_sans_comparaison_est_ignoree_et_l_equipe_devient_non_evaluable():
    brutes = (jobs_equipe("eq-solo", 9, 15, complexite="standard", depart=0)
              + jobs_equipe("eq-b", 9, 40, complexite="difficile", depart=100)
              + jobs_equipe("eq-c", 9, 41, complexite="difficile", depart=200))
    r = perf(brutes)
    solo = ligne_equipe(r, "eq-solo")
    assert solo["evaluable"] is False and solo["motif"] == "echantillon_comparable_insuffisant"
    assert solo["observations_sans_comparaison"] == 9 and "indice_median" not in solo
    assert ligne_equipe(r, "eq-b")["evaluable"] is True


def test_equipe_sans_historique_ou_trop_petite_n_a_jamais_un_indice_nul():
    brutes = (jobs_equipe("eq-a", 9, 27, complexite="standard", depart=0)
              + jobs_equipe("eq-b", 9, 33, complexite="standard", depart=100)
              + jobs_equipe("eq-nouvelle", 2, 20, complexite="standard", depart=200))
    r = perf(brutes)
    n = ligne_equipe(r, "eq-nouvelle")
    assert n["evaluable"] is False and "indice_median" not in n
    assert all(e["equipe_ref"] != "eq-inconnue" for e in r["equipes"])


def test_observations_sans_equipe_n_entrent_dans_aucun_agregat_et_aucune_personne_n_est_notee():
    brutes = jobs_equipe(None, 12, 30, complexite="standard", depart=0)
    r = perf(brutes)
    assert r["equipes"] == [] and r["observations_sans_equipe"] == 12
    assert "jamais une note de personne" in r["limite"]


def test_indice_par_type_de_travaux_pas_melange():
    brutes = (jobs_equipe("eq-a", 9, 27, complexite="standard", depart=0)
              + jobs_equipe("eq-b", 9, 33, complexite="standard", depart=100)
              + jobs_equipe("eq-a", 9, 33, complexite="standard", depart=200, service="revetement")
              + jobs_equipe("eq-b", 9, 27, complexite="standard", depart=300, service="revetement"))
    r = perf(brutes)
    par = {(e["equipe_ref"], e["type_service"]): Decimal(e["indice_median"]) for e in r["equipes"]}
    assert par[("eq-a", "gouttieres")] < 1 < par[("eq-b", "gouttieres")]
    assert par[("eq-a", "revetement")] > 1 > par[("eq-b", "revetement")]


def test_seed_est_le_prefixe_sha256_hexadecimal_de_seize_caracteres():
    attendu = int(hashlib.sha256(b"a\x1fb").hexdigest()[:16], 16)
    assert ad._seed("a", "b") == attendu


def test_mediane_pair_et_impair():
    assert ad._mediane([Decimal("3"), Decimal("1"), Decimal("2")]) == Decimal("2")
    assert ad._mediane([Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]) == Decimal("2.5")


def test_mediane_ponderee_milieu_exact_et_poids_jamais_nuls():
    assert ad._mediane_ponderee([(Decimal("1"), Decimal("1")), (Decimal("2"), Decimal("1"))]) == Decimal("1.5")
    assert ad._mediane_ponderee([
        (Decimal("1"), Decimal("1")), (Decimal("2"), Decimal("1")), (Decimal("3"), Decimal("2")),
    ]) == Decimal("2.5")


def test_intervalle_bootstrap_est_borne_a_quatre_cents_lignes_et_deterministe():
    paires = [(Decimal("-1000"), Decimal("1"))] + [(Decimal(10 + i % 50), Decimal("1")) for i in range(400)]
    assert ad._intervalle(paires, politique(), 1) == (Decimal("33"), Decimal("37"))


def test_aberrante_exactement_au_seuil_est_retenue():
    pol = politique()
    lignes = [{"taux": Decimal("10")}] * 4 + [{"taux": Decimal("11.75")}]
    retenues, nb = ad._sans_aberrantes(lignes, pol)
    assert nb == 0 and len(retenues) == 5


def test_intervalle_sans_observation_ne_fabrique_pas_d_echantillon():
    c = cohorte([])
    assert c["n_observations"] == 0 and c["n_chantiers"] == 0


def test_derive_evaluable_exactement_a_deux_fenetres():
    assert cohorte(constante(16, 30))["derive"]["evaluable"] is True
    assert cohorte(constante(15, 30))["derive"]["evaluable"] is False


def test_ecart_au_seuil_exact_n_est_pas_une_derive():
    cas = [
        ([obs(200 + i, 29, jours=60 + i) for i in range(8)],
         [obs(300 + i, 34.5, jours=1 + i) for i in range(8)], "30"),   # régime > 15 %, référence = 15 %
        ([obs(400 + i, 30, jours=60 + i) for i in range(8)],
         [obs(500 + i, 34.5, jours=1 + i) for i in range(8)], "29"),   # régime = 15 %, référence > 15 %
    ]
    for anciennes, recentes, courant in cas:
        c = cohorte(anciennes + recentes, courant=courant)
        assert c["derive"]["detectee"] is False


def test_intervalle_aux_percentiles_et_bornes_extremes():
    paires = [(Decimal(i), Decimal("1")) for i in range(1, 402)]
    pol = politique()
    assert ad._intervalle(paires, pol, 7) == (Decimal("186.5"), Decimal("215.5"))
    pol_extreme = {**pol, "niveau_confiance": Decimal("0.999"), "replications": 200}
    assert ad._intervalle(paires, pol_extreme, 7) == (Decimal("178.5"), Decimal("225.5"))


def test_variation_minimale_exacte_n_est_pas_encore_un_petit_ajustement():
    c = cohorte([obs(i, 30.3, jours=10 + i, quantite=100) for i in range(10)])
    assert Decimal(c["variation_pct"]) == Decimal("1")
    assert c["decision"] == "auto_applicable"


def test_la_reference_egale_a_une_borne_de_l_intervalle_reste_stable(monkeypatch):
    donnees = serie(12, 34.3)
    for bornes in ((Decimal("30"), Decimal("35")), (Decimal("25"), Decimal("30"))):
        monkeypatch.setattr(ad, "_intervalle", lambda *_args, _bornes=bornes, **_kwargs: _bornes)
        assert cohorte(donnees)["decision"] == "stable"


# ---------------------------------------------------------------------------------------- bornes exactes
def constante(n, taux, **plus):
    return [obs(i, taux, jours=10 + i, **plus) for i in range(n)]


def test_seuil_d_echantillon_exact_huit_chantiers_suffisent_sept_non():
    assert cohorte(constante(8, 36))["decision"] != "insuffisante"
    assert cohorte(constante(7, 36))["decision"] == "insuffisante"


def test_palier_exact_est_inclus_et_un_cheveu_au_dela_exige_une_personne():
    # 36 = 30 x 1,20 : variation de 20 % pile, palier déclaré à 20 % -> automatique.
    assert cohorte(constante(10, 36))["decision"] == "auto_applicable"
    assert cohorte(constante(10, 36.3))["decision"] == "approbation_requise"


def test_bornes_absolues_exactes_facteur_deux_passe_au_dessus_est_refuse():
    assert cohorte(constante(10, 60))["decision"] == "approbation_requise"      # facteur 2 pile : dans les bornes
    assert cohorte(constante(10, 60.6))["decision"] == "refusee_hors_bornes"     # facteur 2,02
    assert cohorte(constante(10, 15))["decision"] == "approbation_requise"      # facteur 0,5 pile
    assert cohorte(constante(10, 14.7))["decision"] == "refusee_hors_bornes"


def test_variation_minimale_exacte_est_stable_juste_au_dessus_change():
    assert cohorte(constante(10, 30.2), baseline="30")["decision"] == "stable"      # 0,67 % < 1 %
    assert cohorte(constante(10, 30.4), baseline="30")["decision"] == "auto_applicable"  # 1,33 %


def test_derive_deja_absorbee_par_la_version_en_vigueur_n_est_pas_une_derive():
    anciennes = serie(12, 30, jours0=60)
    recentes = serie(8, 43.5, depart=100, jours0=1)
    # La version en vigueur est déjà à 43,5 : les récents ne s'en écartent pas, même si l'historique ancien reste là.
    c = cohorte(anciennes + recentes, courant="43.5")
    assert c["derive"]["detectee"] is False and float(c["derive"]["ecart_pct"]) > 15
    assert float(c["derive"]["ecart_reference_pct"]) < 15
