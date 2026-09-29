"""PLAN T4.11 (M3.12) : les quantiles du coût et le tirage PERT de `monte_carlo.py`.

Deux ajouts au Monte Carlo déterministe, sans toucher à ce qu'il rendait avant :

- `simuler_quantiles` rend des quantiles du coût (P50, P80…) sur les MÊMES tirages que `simuler_intervalle` : même
  générateur local, même graine, même loi, même tri, même convention de rang que la borne haute de l'intervalle. Ce
  n'est pas une seconde simulation : c'est la lecture d'un autre rang du même échantillon ;
- un poste du barème qui porte `cout_unitaire_mode` est tiré en PERT (loi bêta d'un mode fourni) ; sans mode, le tirage
  reste uniforme, bit à bit comme avant (valeur d'or de `test_monte_carlo.py`). Le mode n'est jamais inventé : fourni de
  travers (hors des bornes, non numérique), il est refusé.

Les données sont fictives (`fictif: true`) : aucun coût réel.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from m3_estimation import monte_carlo, verdicts  # noqa: E402

FICTIF = True
SERVICE = "ravalement"
GRAINES = tuple(range(1, 41))


def _bareme(**poste):
    """Un barème fictif à un poste ; `poste` surcharge ses clés (ajouter `cout_unitaire_mode`, par exemple)."""
    valeurs = {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}
    valeurs.update(poste)
    return {"version": "fictif-2026.1", "unite": "pi2", "postes": {SERVICE: valeurs}}


def _quantiles(bareme, probabilites, graine=42, quantite=1200):
    valeurs, verdict = monte_carlo.simuler_quantiles(
        bareme, SERVICE, quantite, graine, probabilites, services=(SERVICE,))
    assert verdict is None, verdict
    return valeurs


def _intervalle(bareme, niveau, graine=42, quantite=1200):
    intervalle, verdict = monte_carlo.simuler_intervalle(bareme, SERVICE, quantite, graine, niveau, services=(SERVICE,))
    assert verdict is None, verdict
    return intervalle


# --------------------------------------------------------------------------------- quantiles : mêmes tirages
@pytest.mark.parametrize("graine", GRAINES)
def test_p50_ne_depasse_jamais_p80(graine):
    p50, p80 = _quantiles(_bareme(), (0.5, 0.8), graine)
    assert p50 <= p80


def test_les_quantiles_sont_rendus_dans_l_ordre_demande():
    p80, p50 = _quantiles(_bareme(), (0.8, 0.5))
    assert p50 <= p80
    assert (p80, p50) == tuple(reversed(_quantiles(_bareme(), (0.5, 0.8))))


def test_meme_graine_memes_quantiles_bit_a_bit():
    premier = _quantiles(_bareme(), (0.5, 0.8), graine=20260929)
    _quantiles(_bareme(), (0.5, 0.8), graine=7)  # un appel entrelacé ne contamine rien
    assert _quantiles(_bareme(), (0.5, 0.8), graine=20260929) == premier


def test_une_autre_graine_donne_d_autres_quantiles():
    assert _quantiles(_bareme(), (0.5, 0.8), graine=1) != _quantiles(_bareme(), (0.5, 0.8), graine=2)


@pytest.mark.parametrize("graine", GRAINES)
@pytest.mark.parametrize("niveau", [0.6, 0.8, 0.9, 0.95, 0.99])
def test_un_quantile_est_la_borne_haute_de_l_intervalle_sur_les_memes_tirages(graine, niveau):
    """La borne haute d'un intervalle symétrique de niveau `n` est le quantile `1 - (1 - n) / 2` de l'échantillon :
    le quantile rendu par `simuler_quantiles` lui est donc EXACTEMENT égal, jamais approximativement. Si l'un des deux
    changeait de tirage, de loi ou de rang, ce test tomberait."""
    alpha = (1.0 - niveau) / 2.0
    (quantile,) = _quantiles(_bareme(), (1.0 - alpha,), graine)
    assert quantile == _intervalle(_bareme(), niveau, graine)["borne_haute"]


def test_p80_est_la_borne_haute_a_soixante_pour_cent_et_p50_est_le_rang_central():
    intervalle_p80 = _intervalle(_bareme(), 0.6)
    intervalle_p50 = _intervalle(_bareme(), 1e-9)  # deux rangs centraux : 4999 et 5000
    p50, p80 = _quantiles(_bareme(), (0.5, 0.8))
    assert p80 == intervalle_p80["borne_haute"]
    assert intervalle_p50["borne_basse"] <= p50 == intervalle_p50["borne_haute"]


@pytest.mark.parametrize("graine", GRAINES[:10])
def test_les_quantiles_restent_dans_les_bornes_du_bareme(graine):
    quantite = 1200
    for valeur in _quantiles(_bareme(), (0.001, 0.5, 0.8, 0.999), graine, quantite):
        assert 8.0 * quantite <= valeur <= 14.0 * quantite


def test_un_cout_fixe_donne_le_meme_quantile_partout():
    bareme = _bareme(cout_unitaire_min=10.0, cout_unitaire_max=10.0)
    assert _quantiles(bareme, (0.5, 0.8), quantite=100) == (1000.0, 1000.0)


def test_la_quantite_change_l_echelle_des_quantiles():
    simple = _quantiles(_bareme(), (0.5, 0.8), quantite=100)
    double = _quantiles(_bareme(), (0.5, 0.8), quantite=200)
    assert double == pytest.approx((simple[0] * 2, simple[1] * 2), rel=1e-12)


# ------------------------------------------------- quantiles : mêmes refus que l'intervalle, et leurs propres refus
@pytest.mark.parametrize(
    ("bareme", "type_travaux", "quantite", "graine"),
    [
        (None, SERVICE, 10, 1),
        ({"version": "v", "unite": "u"}, SERVICE, 10, 1),
        (_bareme(), "gouttieres", 10, 1),
        (_bareme(cout_unitaire_min=20.0), SERVICE, 10, 1),
        (_bareme(), SERVICE, 0, 1),
        (_bareme(), SERVICE, True, 1),
        (_bareme(), SERVICE, 10, 1.5),
        (_bareme(), SERVICE, 10, True),
    ],
    ids=["sans_bareme", "bareme_incomplet", "poste_absent", "bornes_inversees", "quantite_nulle", "quantite_booleenne",
         "graine_flottante", "graine_booleenne"],
)
def test_un_intrant_invalide_donne_le_meme_verdict_que_l_intervalle(bareme, type_travaux, quantite, graine):
    _, verdict_intervalle = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, graine, 0.9, services=(SERVICE,))
    valeurs, verdict = monte_carlo.simuler_quantiles(
        bareme, type_travaux, quantite, graine, (0.5, 0.8), services=(SERVICE,))
    assert valeurs is None
    assert verdict == verdict_intervalle
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "probabilites",
    [
        (), [], None, 0.5, "0.5", (0.0,), (1.0,), (-0.1,), (1.5,), (0.5, 1.0), (1,), (True,), (float("nan"),),
        (0.5, "0.8"),
    ],
    ids=["tuple_vide", "liste_vide", "none", "scalaire", "texte", "zero", "un", "negative", "superieure_a_un",
         "une_borne_invalide", "entier", "booleen", "nan", "texte_dans_la_liste"],
)
def test_des_probabilites_invalides_sont_refusees_sans_exception(probabilites):
    valeurs, verdict = monte_carlo.simuler_quantiles(_bareme(), SERVICE, 10, 1, probabilites, services=(SERVICE,))
    assert valeurs is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "probabilit" in verdict["detail"]


def test_la_validation_du_bareme_precede_celle_des_probabilites():
    """Un barème absent est dit avant une probabilité fautive : le verdict nomme la première cause."""
    _, verdict = monte_carlo.simuler_quantiles(None, SERVICE, 10, 1, (), services=(SERVICE,))
    assert "barème" in verdict["detail"]


# ----------------------------------------------------------------------------------------- PERT : le mode du poste
def _oracle(graine, quantite, probabilites, tirer):
    """Le quantile d'un échantillon écrit ICI, à la main, sans rien emprunter à `monte_carlo` : un générateur local
    ensemencé, dix mille tirages, le tri, le rang `ceil(p x (n - 1))`."""
    generateur = random.Random(graine)
    echantillon = sorted(tirer(generateur) * quantite for _ in range(10000))
    return tuple(echantillon[math.ceil(p * 9999)] for p in probabilites)


@pytest.mark.parametrize("graine", GRAINES[:8])
def test_un_poste_sans_mode_est_tire_en_uniforme(graine):
    """Sans `cout_unitaire_mode`, le tirage est `uniform(min, max)` : les quantiles égalent l'oracle écrit à la main."""
    assert "cout_unitaire_mode" not in _bareme()["postes"][SERVICE]
    attendu = _oracle(graine, 1200, (0.5, 0.8), lambda g: g.uniform(8.0, 14.0))
    assert _quantiles(_bareme(), (0.5, 0.8), graine) == attendu


@pytest.mark.parametrize("graine", GRAINES[:8])
def test_un_poste_avec_mode_est_tire_en_pert(graine):
    """Avec un mode, le tirage est la bêta PERT : `min + (max - min) x Bêta(1 + 4(m - min)/(max - min), 1 + 4(max - m)/
    (max - min))`. L'oracle est écrit d'après la définition de la loi, pas d'après le code."""
    a, b, m = 8.0, 14.0, 9.0
    alpha, beta = 1 + 4 * (m - a) / (b - a), 1 + 4 * (b - m) / (b - a)
    attendu = _oracle(graine, 1200, (0.5, 0.8), lambda g: a + (b - a) * g.betavariate(alpha, beta))
    assert _quantiles(_bareme(cout_unitaire_mode=m), (0.5, 0.8), graine) == attendu


def test_un_mode_change_la_loi_du_tirage():
    uniforme = _quantiles(_bareme(), (0.5, 0.8))
    pert = _quantiles(_bareme(cout_unitaire_mode=9.0), (0.5, 0.8))
    assert pert != uniforme
    # un mode proche de la borne basse tire la loi vers le bas : le coût médian et le P80 baissent
    assert pert[0] < uniforme[0]
    assert pert[1] < uniforme[1]


def test_un_mode_central_resserre_la_loi_autour_du_mode():
    """La bêta PERT symétrique (mode au centre) est plus resserrée que l'uniforme : l'écart P50-P80 est plus étroit."""
    centre = 11.0
    uniforme = _quantiles(_bareme(), (0.5, 0.8))
    pert = _quantiles(_bareme(cout_unitaire_mode=centre), (0.5, 0.8))
    assert pert[1] - pert[0] < (uniforme[1] - uniforme[0]) * 0.75
    assert pert[0] == pytest.approx(centre * 1200, rel=0.01)  # la médiane suit le mode quand la loi est symétrique


def test_la_moyenne_de_la_loi_est_celle_de_la_formule_pert():
    """Moyenne PERT = (min + 4 x mode + max) / 6. Lue sans accès à l'échantillon : dix mille tirages à graine fixe, donc
    exacte à chaque exécution, et assez proche de la formule pour ne pas être celle d'une loi uniforme (11)."""
    moyenne_attendue = (8.0 + 4 * 9.0 + 14.0) / 6
    # cent quantiles régulièrement espacés : leur moyenne approche la moyenne de la loi
    probabilites = tuple((rang + 0.5) / 100 for rang in range(100))
    valeurs = _quantiles(_bareme(cout_unitaire_mode=9.0), probabilites, quantite=1)
    assert sum(valeurs) / len(valeurs) == pytest.approx(moyenne_attendue, abs=0.05)
    assert abs(moyenne_attendue - 11.0) > 1.0


def test_le_tirage_pert_est_reproductible_bit_a_bit():
    bareme = _bareme(cout_unitaire_mode=9.0)
    premier = _intervalle(bareme, 0.9, 20260929)
    _intervalle(bareme, 0.9, 5)
    assert _intervalle(bareme, 0.9, 20260929) == premier
    assert _quantiles(bareme, (0.5, 0.8), 20260929) == _quantiles(bareme, (0.5, 0.8), 20260929)


@pytest.mark.parametrize("graine", GRAINES[:15])
def test_l_intervalle_et_les_quantiles_partagent_aussi_les_tirages_pert(graine):
    bareme = _bareme(cout_unitaire_mode=9.0)
    (p80,) = _quantiles(bareme, (0.8,), graine)
    assert p80 == _intervalle(bareme, 0.6, graine)["borne_haute"]


def test_le_tirage_pert_reste_dans_les_bornes_du_bareme():
    bareme = _bareme(cout_unitaire_mode=8.0)  # mode sur la borne basse
    intervalle = _intervalle(bareme, 0.99, quantite=10)
    assert 80.0 <= intervalle["borne_basse"] <= intervalle["borne_haute"] <= 140.0


@pytest.mark.parametrize("mode", [8.0, 14.0, 11, 8, 14])
def test_un_mode_sur_une_borne_ou_entier_est_accepte(mode):
    (p50,) = _quantiles(_bareme(cout_unitaire_mode=mode), (0.5,))
    assert 8.0 * 1200 <= p50 <= 14.0 * 1200


def test_un_cout_fixe_avec_son_mode_donne_un_intervalle_degenere():
    bareme = _bareme(cout_unitaire_min=10.0, cout_unitaire_max=10.0, cout_unitaire_mode=10.0)
    intervalle = _intervalle(bareme, 0.9, quantite=100)
    assert intervalle["borne_basse"] == intervalle["borne_haute"] == 1000.0
    assert _quantiles(bareme, (0.5, 0.8), quantite=100) == (1000.0, 1000.0)


@pytest.mark.parametrize(
    "mode",
    [7.99, 14.01, -1.0, "9.0", None, True, False, float("nan"), float("inf"), [9.0], {"mode": 9.0}],
    ids=["sous_le_min", "au_dessus_du_max", "negatif", "texte", "null", "vrai", "faux", "nan", "infini", "liste",
         "objet"],
)
def test_un_mode_fourni_de_travers_est_refuse_jamais_ignore(mode):
    bareme = _bareme(cout_unitaire_mode=mode)
    for resultat, verdict in (
        monte_carlo.simuler_intervalle(bareme, SERVICE, 10, 1, 0.9, services=(SERVICE,)),
        monte_carlo.simuler_quantiles(bareme, SERVICE, 10, 1, (0.5,), services=(SERVICE,)),
    ):
        assert resultat is None
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
        assert "cout_unitaire_mode" in verdict["detail"]


def test_un_cout_fixe_refuse_un_mode_different_de_sa_valeur():
    bareme = _bareme(cout_unitaire_min=10.0, cout_unitaire_max=10.0, cout_unitaire_mode=10.5)
    _, verdict = monte_carlo.simuler_intervalle(bareme, SERVICE, 10, 1, 0.9, services=(SERVICE,))
    assert "cout_unitaire_mode" in verdict["detail"]


# ------------------------------------------------------------------------- lire_poste : ce que les autres lisent
def test_lire_poste_rend_les_bornes_et_le_mode_valides():
    parametres, verdict = monte_carlo.lire_poste(_bareme(cout_unitaire_mode=9.0), SERVICE, services=(SERVICE,))
    assert verdict is None
    assert parametres == {"cout_min": 8.0, "cout_max": 14.0, "mode": 9.0}


def test_lire_poste_sans_mode_rend_none_jamais_une_valeur_par_defaut():
    parametres, _ = monte_carlo.lire_poste(_bareme(), SERVICE, services=(SERVICE,))
    assert parametres["mode"] is None


def test_lire_poste_refuse_comme_la_simulation():
    parametres, verdict = monte_carlo.lire_poste(_bareme(cout_unitaire_min=20.0), SERVICE, services=(SERVICE,))
    assert parametres is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_nombre_de_tirages_reste_fixe_et_commun():
    assert monte_carlo.NOMBRE_TIRAGES == 10000
    assert math.ceil(0.8 * (monte_carlo.NOMBRE_TIRAGES - 1)) == 8000
