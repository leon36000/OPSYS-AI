"""Tests de l'orchestrateur d'estimation M3 (PLAN T2.3, `estimation.py`).

Referme le constat central de `docs/departements/M3-audit.md` §0 : l'ancien `m3_estimer_projet`
n'assemblait que 6 des 15 modules du paquet, n'émettait jamais de `devis_id`, n'écrivait jamais au
registre append-only, et ne calculait jamais `REFERENCE_ECHELLE_ABSENTE`. Ces tests exercent
`estimation.orchestrer_estimation` directement, avec un `registre.Registre()` EN MÉMOIRE
(protocole liste, jamais `outils.registre_production()` durable — même discipline que les autres
suites unitaires du département)."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, estimation, registre, verdicts  # noqa: E402

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}
BAREME_AVEC_DUREE = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {
        "ravalement": {
            "cout_unitaire_min": 8.0,
            "cout_unitaire_max": 14.0,
            "duree_minutes_par_unite": 2.5,
        }
    },
}


def _contrat(**surcharges):
    contrat = {
        "lead_id": "lead-estimation-001",
        "conversation_id": "conv-estimation-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    contrat.update(surcharges)
    return contrat


def _marqueur(**surcharges):
    marqueur = {
        "readiness_ok": True,
        "lead_id": "lead-estimation-001",
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:00:00-04:00",
        "empreinte": "a" * 64,
    }
    marqueur.update(surcharges)
    return marqueur


def _photo(i, reference=None, largeur=3000, angle="face", eclairage=7):
    return {
        "photo_id": f"p{i}",
        "resolution_largeur": largeur,
        "resolution_hauteur": 2000,
        "eclairage": eclairage,
        "angle": angle,
        "reference_echelle": reference,
    }


def _orchestrer(**surcharges):
    parametres = {
        "contrat": _contrat(),
        "marqueur": _marqueur(),
        "photos": [_photo(1, reference={"type": "porte", "dimensions_connues": True})],
        "seuils": SEUILS,
        "bareme": BAREME,
        "quantite": 1200,
        "plancher_rentable": 9000,
        "registre_cible": registre.Registre(),
        "graine": 42,
    }
    parametres.update(surcharges)
    return estimation.orchestrer_estimation(**parametres)


# --------------------------------------------------------------------------------- voie complète
def test_estimation_complete_emet_un_devis_id_stable_et_un_hash_maillon():
    """Referme l'écart central de l'audit : devis_id et hash_maillon sont désormais émis."""
    reponse = _orchestrer()
    assert reponse["etape"] == "complet"
    assert reponse["accepte"] is True
    estimation_v1 = reponse["estimation"]
    assert set(estimation_v1) == set(contrats.CHAMPS_ESTIMATION_V1)
    assert estimation_v1["devis_id"].startswith("M3-DEVIS-")
    assert estimation_v1["hash_maillon"]
    assert estimation_v1["prix_bloque"] is False
    assert estimation_v1["verdict_estimation"] == "AUCUN_BLOCAGE"
    assert estimation_v1["intervalle_confiance"]["borne_basse"] is not None


def test_devis_id_stable_et_deterministe_meme_lead_meme_empreinte():
    registre_a = registre.Registre()
    registre_b = registre.Registre()
    reponse_a = _orchestrer(registre_cible=registre_a)
    reponse_b = _orchestrer(registre_cible=registre_b)
    assert reponse_a["estimation"]["devis_id"] == reponse_b["estimation"]["devis_id"]


def test_lead_differents_donnent_des_devis_id_distincts():
    reponse_a = _orchestrer(contrat=_contrat(lead_id="lead-A"), marqueur=_marqueur(lead_id="lead-A"))
    reponse_b = _orchestrer(contrat=_contrat(lead_id="lead-B"), marqueur=_marqueur(lead_id="lead-B"))
    assert reponse_a["estimation"]["devis_id"] != reponse_b["estimation"]["devis_id"]


def test_estimation_est_inscrite_au_registre_hash_chaine():
    journal = registre.Registre()
    reponse = _orchestrer(registre_cible=journal)
    maillons = journal.lire()
    assert len(maillons) == 1
    assert maillons[0]["charge"]["devis_id"] == reponse["estimation"]["devis_id"]
    valide, diagnostic = journal.valider_chaine()
    assert valide is True, diagnostic


def test_meme_demande_meme_intervalle_bit_a_bit():
    a = _orchestrer(registre_cible=registre.Registre())
    b = _orchestrer(registre_cible=registre.Registre())
    assert a["estimation"]["intervalle_confiance"] == b["estimation"]["intervalle_confiance"]
    assert a["estimation"]["graine_monte_carlo"] == b["estimation"]["graine_monte_carlo"]


# --------------------------------------------------------------------- validation (S001) câblée
def test_contrat_invalide_est_rejete_avant_toute_estimation():
    reponse = _orchestrer(contrat=_contrat(type_travaux="piscine"))
    assert reponse["accepte"] is False
    assert reponse["etape"] == "validation"
    assert reponse["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"


def test_marqueur_readiness_false_est_rejete():
    reponse = _orchestrer(marqueur=_marqueur(readiness_ok=False))
    assert reponse["accepte"] is False
    assert reponse["etape"] == "validation"
    assert reponse["verdict"]["code"] == "REJ-READINESS-NON-CONSTATEE"


def test_lead_id_discordant_entre_contrat_et_marqueur_est_rejete():
    reponse = _orchestrer(marqueur=_marqueur(lead_id="lead-autre"))
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-LEAD-ID-DISCORDANT"


# ------------------------------------------------------------------------- blocage (S002/S004)
def test_photos_insuffisantes_bloquent_le_prix_mais_rendent_un_devis_id():
    """Le prix bloqué reste une estimation COMPLÈTE et valide (accepte=True), avec devis_id —
    referme le second constat de l'audit : plus de « estimation orpheline » sans identifiant."""
    reponse = _orchestrer(photos=[_photo(1, largeur=10)])
    assert reponse["accepte"] is True
    estimation_v1 = reponse["estimation"]
    assert estimation_v1["prix_bloque"] is True
    assert estimation_v1["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert estimation_v1["intervalle_confiance"]["borne_basse"] is None
    assert estimation_v1["bareme_version"] is None
    assert estimation_v1["raison_blocage"]
    assert estimation_v1["devis_id"].startswith("M3-DEVIS-")
    assert reponse["duree_estimee_minutes"] is None


def test_liste_photos_vide_bloque_avec_devis_id():
    reponse = _orchestrer(photos=[])
    assert reponse["estimation"]["prix_bloque"] is True
    assert reponse["estimation"]["devis_id"]


def test_elements_manquants_liste_explicite_quand_bloque():
    """SOUL.md : « tu expliques simplement au client ce qui manque » — une liste EXPLOITABLE,
    pas seulement la phrase composée de raison_blocage."""
    reponse = _orchestrer(photos=[_photo(1, largeur=10)])
    assert reponse["elements_manquants"]
    assert all(isinstance(e, str) and e for e in reponse["elements_manquants"])


def test_elements_manquants_vide_quand_non_bloque_et_taux_marge_fourni():
    """`taux_marge` fourni et valide : plus rien à signaler (ni photos, ni prix manquant)."""
    reponse = _orchestrer(taux_marge="0.25")
    assert reponse["elements_manquants"] == []


def test_elements_manquants_signale_taux_marge_absent_quand_non_bloque():
    """PLAN T2.3 (reste de T2.3-b, séparer coût et prix) : `taux_marge` ABSENT sur la voie NON
    bloquée n'est pas une erreur, mais `elements_manquants` le dit explicitement — jamais un
    silence sur l'absence de prix recommandé."""
    reponse = _orchestrer()  # taux_marge omis
    assert reponse["elements_manquants"] != []
    assert any("taux_marge" in element for element in reponse["elements_manquants"])
    assert reponse["prix_recommande"] is None


# ----------------------------------------------------------------------- REFERENCE_ECHELLE_ABSENTE
def test_multi_vues_sans_reference_signale_sans_bloquer():
    photos = [_photo(1, angle="face"), _photo(2, angle="gauche"), _photo(3, angle="droite")]
    reponse = _orchestrer(photos=photos)
    estimation_v1 = reponse["estimation"]
    assert reponse["niveau_confiance_hierarchie"] == "MULTI_VUES"
    assert estimation_v1["verdict_estimation"] == "REFERENCE_ECHELLE_ABSENTE"
    assert estimation_v1["prix_bloque"] is False
    assert estimation_v1["intervalle_confiance"]["borne_basse"] is not None


def test_mono_vue_sans_reference_signale_sans_bloquer():
    photos = [_photo(1), _photo(2, angle="gauche")]
    reponse = _orchestrer(photos=photos)
    estimation_v1 = reponse["estimation"]
    assert reponse["niveau_confiance_hierarchie"] == "MONO_VUE_BORNES_LARGES"
    assert estimation_v1["verdict_estimation"] == "REFERENCE_ECHELLE_ABSENTE"
    assert estimation_v1["prix_bloque"] is False


def test_reference_echelle_presente_najamais_le_verdict_absente():
    """REFERENCE_ECHELLE (une référence certifiée existe) ne doit JAMAIS produire
    REFERENCE_ECHELLE_ABSENTE : les deux verdicts sont mutuellement exclusifs par construction."""
    reponse = _orchestrer(photos=[_photo(1, reference={"type": "porte", "dimensions_connues": True})])
    assert reponse["niveau_confiance_hierarchie"] == "REFERENCE_ECHELLE"
    assert reponse["estimation"]["verdict_estimation"] != "REFERENCE_ECHELLE_ABSENTE"


def test_reference_echelle_absente_najamais_sur_la_voie_bloquee():
    """Sur la voie bloquée (INDETERMINE, une seule photo faible), QUALITE_ENTREE_INSUFFISANTE
    prime toujours — REFERENCE_ECHELLE_ABSENTE ne doit jamais masquer un blocage réel."""
    reponse = _orchestrer(photos=[_photo(1, largeur=10)])
    assert reponse["estimation"]["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert reponse["estimation"]["prix_bloque"] is True


def test_alerte_plancher_prime_sur_reference_echelle_absente_dans_le_verdict_mais_les_deux_restent_vrais():
    """`_PRIORITE_VERDICTS` (devis.py) place REFERENCE_ECHELLE_ABSENTE AVANT
    PLANCHER_RENTABILITE_FRANCHI : le verdict affiché est REFERENCE_ECHELLE_ABSENTE, mais
    `alerte_plancher` reste un booléen EXACT et indépendant."""
    photos = [_photo(1), _photo(2, angle="gauche")]  # MONO_VUE_BORNES_LARGES, sans référence
    reponse = _orchestrer(photos=photos, plancher_rentable=999999999)
    estimation_v1 = reponse["estimation"]
    assert estimation_v1["verdict_estimation"] == "REFERENCE_ECHELLE_ABSENTE"
    assert estimation_v1["alerte_plancher"] is True


# ------------------------------------------------------ largeur d'intervalle vs niveau de confiance
def _largeur(reponse):
    intervalle = reponse["estimation"]["intervalle_confiance"]
    return float(intervalle["borne_haute"]) - float(intervalle["borne_basse"])


def test_intervalle_plus_etroit_avec_reference_echelle_quavec_multi_vues_ou_mono_vue():
    """BUG CORRIGÉ (repris de l'ancien test_outils_agent.py) : l'intervalle Monte Carlo ne
    dépendait jamais du niveau de confiance — REFERENCE_ECHELLE (mesure certifiée) rendait
    exactement le même intervalle que MONO_VUE_BORNES_LARGES (dont le NOM MÊME annonce des bornes
    larges, brief analyste §3 : « MAE ~0,45 m au mieux »). Même barème, même type de travaux, même
    quantité : seule la classification de confiance change, donc seule elle doit expliquer un
    écart de largeur."""
    reponse_reference = _orchestrer(
        photos=[_photo(1, reference={"type": "porte", "dimensions_connues": True})]
    )
    reponse_multi_vues = _orchestrer(
        photos=[_photo(1, angle="face"), _photo(2, angle="gauche"), _photo(3, angle="droite")]
    )
    reponse_mono_vue = _orchestrer(photos=[_photo(1), _photo(2, angle="gauche")])

    assert reponse_reference["niveau_confiance_hierarchie"] == "REFERENCE_ECHELLE"
    assert reponse_multi_vues["niveau_confiance_hierarchie"] == "MULTI_VUES"
    assert reponse_mono_vue["niveau_confiance_hierarchie"] == "MONO_VUE_BORNES_LARGES"

    assert _largeur(reponse_reference) < _largeur(reponse_multi_vues) < _largeur(reponse_mono_vue)


def test_elargissement_reste_dans_les_bornes_du_bareme():
    reponse = _orchestrer(photos=[_photo(1), _photo(2, angle="gauche")])  # MONO_VUE : le plus élargi
    intervalle = reponse["estimation"]["intervalle_confiance"]
    assert 8.0 * 1200 <= float(intervalle["borne_basse"]) < float(intervalle["borne_haute"]) <= 14.0 * 1200


def test_bornes_de_intervalle_sont_arrondies_au_cent():
    reponse = _orchestrer(photos=[_photo(1, reference={"type": "porte", "dimensions_connues": True})])
    intervalle = reponse["estimation"]["intervalle_confiance"]
    for cle in ("borne_basse", "borne_haute"):
        valeur = Decimal(str(intervalle[cle]))
        assert valeur == valeur.quantize(Decimal("0.01")), f"{cle}={intervalle[cle]!r} pas arrondi au cent"


# ------------------------------------------------------------------------------------ plancher
def test_alerte_plancher_sans_reference_echelle_absente():
    reponse = _orchestrer(
        photos=[_photo(1, reference={"type": "porte", "dimensions_connues": True})],
        plancher_rentable=999999999,
    )
    estimation_v1 = reponse["estimation"]
    assert estimation_v1["verdict_estimation"] == "PLANCHER_RENTABILITE_FRANCHI"
    assert estimation_v1["alerte_plancher"] is True
    assert estimation_v1["prix_bloque"] is False


# --------------------------------------------------------------------------- durée main-d'œuvre
def test_duree_estimee_minutes_calculee_quand_le_bareme_la_porte():
    reponse = _orchestrer(bareme=BAREME_AVEC_DUREE, quantite=1200)
    assert reponse["duree_estimee_minutes"] == str(Decimal("1200") * Decimal("2.5"))


def test_duree_estimee_minutes_absente_du_bareme_reste_none_sans_bloquer_le_prix():
    reponse = _orchestrer(bareme=BAREME)  # BAREME sans duree_minutes_par_unite
    assert reponse["duree_estimee_minutes"] is None
    assert reponse["estimation"]["prix_bloque"] is False  # le prix N'EST PAS affecté


def test_duree_estimee_minutes_absente_nest_jamais_ecrite_au_registre():
    journal = registre.Registre()
    _orchestrer(bareme=BAREME, registre_cible=journal)
    assert "duree_estimee_minutes" not in journal.lire()[0]["charge"]


def test_duree_estimee_minutes_ecrite_au_registre_quand_disponible():
    journal = registre.Registre()
    _orchestrer(bareme=BAREME_AVEC_DUREE, registre_cible=journal)
    charge = journal.lire()[0]["charge"]
    assert charge["duree_estimee_minutes"] == str(Decimal("1200") * Decimal("2.5"))


def test_duree_minutes_par_unite_negative_est_un_verdict_nomme():
    bareme_invalide = {
        "version": "2026.1",
        "unite": "pi2",
        "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "duree_minutes_par_unite": -1}},
    }
    reponse = _orchestrer(bareme=bareme_invalide)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "duree_main_doeuvre"
    assert reponse["verdict"]["code"] == "REJ-ECART-DUREE-ESTIMEE-INVALIDE"
    assert verdicts.est_verdict(reponse["verdict"]["code"])


def test_duree_minutes_par_unite_non_numerique_est_un_verdict_nomme():
    bareme_invalide = {
        "version": "2026.1",
        "unite": "pi2",
        "postes": {
            "ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "duree_minutes_par_unite": "vite"}
        },
    }
    reponse = _orchestrer(bareme=bareme_invalide)
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-ECART-DUREE-ESTIMEE-INVALIDE"


def test_duree_estimee_minutes_jamais_calculee_sur_la_voie_bloquee():
    reponse = _orchestrer(bareme=BAREME_AVEC_DUREE, photos=[_photo(1, largeur=10)])
    assert reponse["estimation"]["prix_bloque"] is True
    assert reponse["duree_estimee_minutes"] is None


# ------------------------------------------------------------------------------- fail-closed
def test_barreme_sans_poste_pour_le_type_demande_est_un_verdict_nomme():
    bareme_incomplet = {"version": "2026.1", "unite": "pi2", "postes": {}}
    reponse = _orchestrer(bareme=bareme_incomplet)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "intervalle"
    assert reponse["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"


def test_seuils_invalides_est_un_verdict_nomme_avant_toute_autre_etape():
    reponse = _orchestrer(seuils={"resolution_minimale": "beaucoup", "eclairage_minimal": 4})
    assert reponse["accepte"] is False
    assert reponse["etape"] == "qualite_photos"
    assert reponse["verdict"]["code"] == "REJ-SEUILS-INVALIDES"


@pytest.mark.parametrize("plancher_rentable", ["cher", None, True])
def test_plancher_rentable_invalide_est_un_verdict_nomme(plancher_rentable):
    reponse = _orchestrer(plancher_rentable=plancher_rentable)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "plancher"


def test_aucune_exception_neschappe_jamais_meme_sur_des_entrees_hostiles():
    """Contrat non-dict, marqueur non-dict, bareme non-dict, quantite non numérique : chaque
    étape rend un verdict nommé, jamais une exception qui remonterait à l'appelant."""
    for surcharges in (
        {"contrat": "pas-un-dict"},
        {"marqueur": None},
        {"bareme": "pas-un-bareme"},
        {"quantite": "beaucoup"},
    ):
        reponse = _orchestrer(**surcharges)
        assert reponse["accepte"] is False
        assert "verdict" in reponse
        assert reponse["verdict"]["code"] in verdicts.CODES_M3_LIST


# --------------------------------------------------------- prix recommandé (PLAN T2.3, reste T2.3-b)
def test_prix_recommande_derive_du_cout_par_le_taux_de_marge_fourni():
    """`prix_recommande` reprend EXACTEMENT la formule de `devis_durable.prix_depuis_cout`
    (réutilisée, jamais dupliquée) — bornes basse/haute du COÛT x (1 + taux_marge), ROUND_HALF_UP
    au cent."""
    reponse = _orchestrer(taux_marge="0.25")
    cout = reponse["estimation"]["intervalle_confiance"]
    prix = reponse["prix_recommande"]
    attendu_basse = (Decimal(str(cout["borne_basse"])) * Decimal("1.25")).quantize(Decimal("0.01"))
    attendu_haute = (Decimal(str(cout["borne_haute"])) * Decimal("1.25")).quantize(Decimal("0.01"))
    assert Decimal(str(prix["borne_basse"])) == attendu_basse
    assert Decimal(str(prix["borne_haute"])) == attendu_haute
    assert set(prix) == {"borne_basse", "borne_haute"}


def test_prix_recommande_ne_touche_jamais_les_champs_geles_destimationv1():
    """P5 : EstimationV1 ne se modifie pas en place — `prix_recommande` vit à côté, jamais dedans."""
    reponse = _orchestrer(taux_marge="0.25")
    assert set(reponse["estimation"]) == set(contrats.CHAMPS_ESTIMATION_V1)
    assert "prix_recommande" not in reponse["estimation"]


def test_prix_recommande_absent_quand_taux_marge_absent_sans_bloquer_le_prix():
    reponse = _orchestrer()  # taux_marge omis
    assert reponse["accepte"] is True
    assert reponse["estimation"]["prix_bloque"] is False
    assert reponse["prix_recommande"] is None


def test_prix_recommande_reste_none_sur_la_voie_bloquee_meme_taux_marge_fourni():
    """Un prix sans coût produit n'aurait pas de socle — même raisonnement que la durée de
    main-d'œuvre : `prix_recommande` reste `None`, `elements_manquants` continue de porter les
    éléments PHOTO manquants (jamais mêlé à la note taux_marge)."""
    reponse = _orchestrer(photos=[_photo(1, largeur=10)], taux_marge="0.25")
    assert reponse["estimation"]["prix_bloque"] is True
    assert reponse["prix_recommande"] is None
    assert all("taux_marge" not in element for element in reponse["elements_manquants"])


@pytest.mark.parametrize("taux_marge", ["pas-un-nombre", "-1", "-2"])
def test_taux_marge_invalide_est_un_verdict_nomme(taux_marge):
    """Fournie de travers (texte non décimal, ou <= -1) : rejet NOMMÉ de l'orchestrateur entier —
    jamais un prix silencieusement absent, même discipline que `plancher_rentable`."""
    reponse = _orchestrer(taux_marge=taux_marge)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "prix_recommande"
    assert reponse["verdict"]["code"] == "REJ-DEVIS-TAUX-MARGE-INVALIDE"


def test_taux_marge_non_texte_est_un_verdict_nomme():
    reponse = _orchestrer(taux_marge=0.25)  # nombre JSON, jamais accepté (texte décimal attendu)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "prix_recommande"
    assert reponse["verdict"]["code"] == "REJ-DEVIS-TAUX-MARGE-INVALIDE"


# --------------------------------------------------- signal de relance M2 (PLAN T2.3, signaux.py)
def test_signal_relance_m2_emis_quand_qualite_photo_insuffisante():
    reponse = _orchestrer(photos=[_photo(1, largeur=10)])
    assert reponse["estimation"]["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    signal = reponse["signal_relance_m2"]
    assert signal is not None
    assert signal["type"] == "DEMANDE_ENTREES_VISUELLES"
    assert signal["lead_id"] == reponse["estimation"]["lead_id"]
    assert signal["devis_id"] == reponse["estimation"]["devis_id"]
    assert signal["elements_manquants"] == reponse["elements_manquants"]
    assert signal["emission_count"] == 1


def test_signal_relance_m2_absent_quand_aucun_blocage():
    reponse = _orchestrer()
    assert reponse["signal_relance_m2"] is None


def test_signal_relance_m2_absent_sur_indetermine_seul():
    """INDETERMINE (photos structurellement acceptables mais hiérarchie indécidable) peut porter
    `elements_manquants == []` : câbler le signal ici casserait `construire_signal_relance`
    (liste vide refusée). Le signal reste donc réservé à QUALITE_ENTREE_INSUFFISANTE."""
    photos = [_photo(1, angle="face"), _photo(2, angle="face"), _photo(3, angle="gauche")]
    reponse = _orchestrer(photos=photos)
    assert reponse["niveau_confiance_hierarchie"] == "INDETERMINE"
    assert reponse["estimation"]["verdict_estimation"] == "INDETERMINE"
    assert reponse["estimation"]["prix_bloque"] is True
    assert reponse["elements_manquants"] == []
    assert reponse["signal_relance_m2"] is None


def test_signal_relance_m2_liste_vide_de_photos():
    reponse = _orchestrer(photos=[])
    assert reponse["estimation"]["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert reponse["signal_relance_m2"]["elements_manquants"] == ["aucune entrée visuelle n'a été fournie"]
