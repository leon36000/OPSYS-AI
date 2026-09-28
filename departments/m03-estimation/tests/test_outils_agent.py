"""Capacités d'agent de M3 : contrat des outils et chaîne d'estimation composée."""

from __future__ import annotations

from pathlib import Path

from m3_estimation.outils import estimer_projet, outils

from opsys.departements import lire_manifeste
from opsys.outils import executer

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}


def _photo(i, reference=None, largeur=3000, angle="face"):
    return {"photo_id": f"p{i}", "resolution_largeur": largeur, "resolution_hauteur": 2000,
            "eclairage": 7, "angle": angle, "reference_echelle": reference}


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m3_estimer_projet"
    assert all(nom.startswith("m3_") for nom in noms)


def test_photos_insuffisantes_bloquent_le_prix():
    reponse = estimer_projet([_photo(1, largeur=500)], SEUILS, BAREME, "ravalement", 1200, 9000)
    assert reponse["prix_bloque"] is True
    assert "intervalle" not in reponse
    assert reponse["elements_manquants"]


def test_estimation_complete_avec_reference_d_echelle():
    reponse = estimer_projet(
        [_photo(1, reference={"type": "porte", "dimensions_connues": True})],
        SEUILS, BAREME, "ravalement", 1200, 9000,
    )
    assert reponse["etape"] == "complet" and reponse["prix_bloque"] is False
    intervalle = reponse["intervalle"]
    assert 8.0 * 1200 <= intervalle["borne_basse"] < intervalle["borne_haute"] <= 14.0 * 1200
    assert reponse["niveau_confiance"] == "REFERENCE_ECHELLE"


def test_meme_demande_meme_intervalle():
    photos = [_photo(1), _photo(2, angle="gauche")]
    a = estimer_projet(photos, SEUILS, BAREME, "ravalement", 800, 5000)
    b = estimer_projet(photos, SEUILS, BAREME, "ravalement", 800, 5000)
    assert a["intervalle"] == b["intervalle"] and a["graine_monte_carlo"] == b["graine_monte_carlo"]


def test_type_de_travaux_hors_contrat_refuse_par_le_schema():
    outil = next(o for o in outils() if o.nom == "m3_estimer_projet")
    reponse = executer(outil, {"photos": [], "seuils": SEUILS, "bareme": BAREME,
                               "type_travaux": "piscine", "quantite": 1, "plancher_rentable": 1})
    assert reponse["erreur"] == "arguments_invalides"


# ------------------------------------------------------------------ largeur d'intervalle vs niveau de confiance
def _largeur(reponse):
    intervalle = reponse["intervalle"]
    return float(intervalle["borne_haute"]) - float(intervalle["borne_basse"])


def test_intervalle_plus_etroit_avec_reference_echelle_quavec_multi_vues_ou_mono_vue():
    """BUG CORRIGÉ : l'intervalle Monte Carlo ne dépendait jamais du niveau de
    confiance — REFERENCE_ECHELLE (mesure certifiée) rendait exactement le
    même intervalle que MONO_VUE_BORNES_LARGES (dont le NOM MÊME annonce des
    bornes larges, brief analyste §3 : « MAE ~0,45 m au mieux »). Même
    barème, même type de travaux, même quantité : seule la classification de
    confiance change, donc seule elle doit expliquer un écart de largeur."""
    reponse_reference = estimer_projet(
        [_photo(1, reference={"type": "porte", "dimensions_connues": True})],
        SEUILS, BAREME, "ravalement", 1200, 9000,
    )
    reponse_multi_vues = estimer_projet(
        [_photo(1, angle="face"), _photo(2, angle="gauche"), _photo(3, angle="droite")],
        SEUILS, BAREME, "ravalement", 1200, 9000,
    )
    reponse_mono_vue = estimer_projet(
        [_photo(1), _photo(2, angle="gauche")],
        SEUILS, BAREME, "ravalement", 1200, 9000,
    )
    assert reponse_reference["niveau_confiance"] == "REFERENCE_ECHELLE"
    assert reponse_multi_vues["niveau_confiance"] == "MULTI_VUES"
    assert reponse_mono_vue["niveau_confiance"] == "MONO_VUE_BORNES_LARGES"

    largeur_reference = _largeur(reponse_reference)
    largeur_multi_vues = _largeur(reponse_multi_vues)
    largeur_mono_vue = _largeur(reponse_mono_vue)

    assert largeur_reference < largeur_multi_vues < largeur_mono_vue


def test_elargissement_reste_dans_les_bornes_du_bareme():
    reponse = estimer_projet(
        [_photo(1), _photo(2, angle="gauche")],  # MONO_VUE_BORNES_LARGES : le plus élargi
        SEUILS, BAREME, "ravalement", 1200, 9000,
    )
    intervalle = reponse["intervalle"]
    assert 8.0 * 1200 <= float(intervalle["borne_basse"]) < float(intervalle["borne_haute"]) <= 14.0 * 1200


# ------------------------------------------------------------------ montants arrondis au cent (Decimal, CAD)
def test_bornes_de_intervalle_sont_arrondies_au_cent():
    from decimal import Decimal
    reponse = estimer_projet(
        [_photo(1, reference={"type": "porte", "dimensions_connues": True})],
        SEUILS, BAREME, "ravalement", 1200, 9000,
    )
    intervalle = reponse["intervalle"]
    for cle in ("borne_basse", "borne_haute"):
        valeur = Decimal(str(intervalle[cle]))
        assert valeur == valeur.quantize(Decimal("0.01")), f"{cle}={intervalle[cle]!r} pas arrondi au cent"


def test_simuler_intervalle_outil_arrondit_aussi_au_cent():
    from decimal import Decimal
    outil = next(o for o in outils() if o.nom == "m3_simuler_intervalle")
    reponse = executer(outil, {"bareme": BAREME, "type_travaux": "ravalement",
                               "quantite": 1200, "graine": 42})
    assert reponse["ok"] is True
    intervalle = reponse["resultat"]["resultat"]
    for cle in ("borne_basse", "borne_haute"):
        valeur = Decimal(str(intervalle[cle]))
        assert valeur == valeur.quantize(Decimal("0.01")), f"{cle}={intervalle[cle]!r} pas arrondi au cent"
