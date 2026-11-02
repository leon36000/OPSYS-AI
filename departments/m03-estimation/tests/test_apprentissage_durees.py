"""Apprentissage des durées sur site (pur) : politique déclarée, observations certifiées, estimateur robuste,
gouvernance, dérive, équipes sans biais de difficulté. Données FICTIVES (fictif: true), horloge injectée, graine par
le contenu : aucun sleep, aucun réseau."""

from __future__ import annotations

import copy
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
