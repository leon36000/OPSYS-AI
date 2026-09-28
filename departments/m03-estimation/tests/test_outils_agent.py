"""Capacités d'agent de M3 : contrat des outils et chaîne d'estimation composée."""

from __future__ import annotations

from pathlib import Path

from m3_estimation.outils import estimer_projet, outils

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer

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


# ------------------------------------------------------------------ devis durable (PLAN T2.3-a) : contrat des outils
# Ces tests portent seulement sur le SCHÉMA JSON et l'autonomie déclarés : un rejet de schéma
# (`arguments_invalides`) court-circuite `executer()` avant tout appel à la fonction, donc avant
# tout accès au stockage — aucune base durable n'est nécessaire ici. Le comportement métier
# (calculs, idempotence, transitions, événement) est éprouvé par test_devis_durable.py et
# test_devis_durable_stockage.py.
_LIGNE_DEVIS_VALIDE = {
    "description": "Gouttière alu 5 po",
    "quantite": "30",
    "unite": "pi_lin",
    "cout_unitaire": "10.00",
    "reference_besoin_materiau": None,
}


def _outil_devis(nom):
    return next(o for o in outils() if o.nom == nom)


def test_les_trois_outils_devis_durable_sont_exposes_avec_lautonomie_attendue():
    """T1 pour la création (brouillon interne, PLAN T2.3-a), T0 pour la lecture, T3 pour
    l'acceptation (frontière humaine, AGENTS.md « engagements externes »)."""
    assert _outil_devis("m3_creer_devis").autonomie == Autonomie.T1
    assert _outil_devis("m3_lire_devis").autonomie == Autonomie.T0
    assert _outil_devis("m3_marquer_devis_accepte").autonomie == Autonomie.T3


def test_aucun_outil_denvoi_de_devis_au_client_nest_expose():
    """SOUL.md : « Envoyer un devis au client sans approbation : c'est une action externe. »
    L'envoi ira derrière les approbations du socle en T1.3 (PLAN T2.3-a) : aucun outil ne
    l'expose encore, exactement comme `m3_envoyer_devis_client` documenté mais absent (audit M3)."""
    noms = {o.nom for o in outils()}
    assert not any("envoy" in nom for nom in noms)


def test_creer_devis_champ_requis_manquant_refuse_par_le_schema():
    outil = _outil_devis("m3_creer_devis")
    arguments = {
        "devis_id": "M3-DEVIS-schema-001",
        "lead_id": "lead-1",
        "chantier_id": None,
        "lignes": [_LIGNE_DEVIS_VALIDE],
        "horodatage": "2026-09-28T14:00:00-04:00",
        # taux_marge manquant : requis par le schéma, jamais codé en dur.
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
    assert any("taux_marge" in detail for detail in reponse["details"])


def test_creer_devis_chantier_id_doit_etre_present_meme_null():
    """`chantier_id` est nullable mais REQUIS (présence de la clé) — même patron que `revue_id`
    dans le catalogue m4.travaux_termines.json : fail-closed, jamais un défaut silencieux."""
    outil = _outil_devis("m3_creer_devis")
    arguments = {
        "devis_id": "M3-DEVIS-schema-002",
        "lead_id": "lead-1",
        "lignes": [_LIGNE_DEVIS_VALIDE],
        "taux_marge": "0.20",
        "horodatage": "2026-09-28T14:00:00-04:00",
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_creer_devis_proprietes_inconnues_refusees_par_le_schema():
    outil = _outil_devis("m3_creer_devis")
    arguments = {
        "devis_id": "M3-DEVIS-schema-003",
        "lead_id": "lead-1",
        "chantier_id": None,
        "lignes": [_LIGNE_DEVIS_VALIDE],
        "taux_marge": "0.20",
        "horodatage": "2026-09-28T14:00:00-04:00",
        "prix": "1.00",  # jamais accepté en entrée (CLES_INTERDITES, cf. contrats.py)
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_lire_devis_role_hors_enum_refuse_par_le_schema():
    outil = _outil_devis("m3_lire_devis")
    reponse = executer(outil, {"devis_id": "M3-DEVIS-schema-004", "role": "proprietaire"})
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_marquer_devis_accepte_approbateur_manquant_refuse_par_le_schema():
    outil = _outil_devis("m3_marquer_devis_accepte")
    reponse = executer(
        outil, {"devis_id": "M3-DEVIS-schema-005", "horodatage": "2026-09-28T14:00:00-04:00"}
    )
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
