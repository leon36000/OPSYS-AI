"""L'orchestrateur d'estimation produit les besoins matériaux (PLAN T2.3-e) : quand, et seulement
quand, une estimation NON bloquée a des quantités défendables — jamais dans `EstimationV1` (gelé),
toujours avec une version (`estimation_id` = `hash_maillon`), jamais après une écriture qu'un rejet
aurait dû empêcher.

Registre EN MÉMOIRE (module pur) : le câblage durable et le bus sont éprouvés par
`test_besoins_materiaux_evenement.py`. Fixtures fictives.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import besoins_materiaux, contrats, estimation, registre  # noqa: E402

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
MATERIAUX = [
    {
        "materiau": "Revêtement vinyle (fictif)",
        "sku": "SKU-FICTIF-VINYLE",
        "quantite_par_unite": "0.0111",
        "unite": "carton",
        "facteur_perte": "0.10",
    },
    {"materiau": "Clous (fictif)", "quantite_par_unite": "0.5", "unite": "boite"},
]


def _bareme(materiaux=MATERIAUX, **poste_extra):
    poste = {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, **poste_extra}
    if materiaux is not None:
        poste["materiaux"] = copy.deepcopy(materiaux)
    return {"version": "2026.1", "unite": "pi2", "postes": {"ravalement": poste}}


def _contrat(lead_id="lead-bm-001"):
    return {
        "lead_id": lead_id,
        "conversation_id": "conv-bm-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }


def _marqueur(lead_id="lead-bm-001", empreinte="a" * 64):
    return {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:00:00-04:00",
        "empreinte": empreinte,
    }


def _photo(i=1, reference=None, largeur=3000):
    return {
        "photo_id": f"p{i}",
        "resolution_largeur": largeur,
        "resolution_hauteur": 2000,
        "eclairage": 7,
        "angle": "face",
        "reference_echelle": reference,
    }


PHOTO_AVEC_REFERENCE = _photo(reference={"type": "porte", "dimensions_connues": True})


def _estimer(registre_cible=None, *, bareme=None, photos=None, quantite=1200, lead_id="lead-bm-001",
             empreinte="a" * 64, **surcharges):
    registre_cible = registre_cible if registre_cible is not None else registre.Registre()
    arguments = {
        "contrat": _contrat(lead_id),
        "marqueur": _marqueur(lead_id, empreinte),
        "photos": photos if photos is not None else [PHOTO_AVEC_REFERENCE],
        "seuils": SEUILS,
        "bareme": bareme if bareme is not None else _bareme(),
        "quantite": quantite,
        "plancher_rentable": 9000,
        "registre_cible": registre_cible,
    }
    arguments.update(surcharges)
    return estimation.orchestrer_estimation(**arguments), registre_cible


def _cles_recursives(objet):
    if isinstance(objet, dict):
        for cle, valeur in objet.items():
            yield cle
            yield from _cles_recursives(valeur)
    elif isinstance(objet, list):
        for element in objet:
            yield from _cles_recursives(element)


# ----------------------------------------------------------------------------------------- nominal
def test_estimation_non_bloquee_avec_materiaux_rend_le_contrat_de_besoins():
    reponse, _ = _estimer()
    assert reponse["accepte"] is True
    besoins = reponse["besoins_materiaux"]
    assert besoins is not None
    assert tuple(besoins) == besoins_materiaux.CHAMPS_BESOINS_MATERIAUX_V1
    assert besoins["lignes"] == [
        {
            "materiau": "Revêtement vinyle (fictif)",
            "sku": "SKU-FICTIF-VINYLE",
            "quantite_estimee": "13.32",
            "unite": "carton",
            "facteur_perte": "0.10",
        },
        {"materiau": "Clous (fictif)", "quantite_estimee": "600", "unite": "boite"},
    ]
    assert besoins["facteurs_perte_absents"] == ["Clous (fictif)"]


def test_le_contrat_est_valide_par_la_validation_stricte_de_lemetteur():
    reponse, _ = _estimer()
    contrat, verdict = besoins_materiaux.valider_besoins_materiaux(reponse["besoins_materiaux"])
    assert verdict is None
    assert contrat == reponse["besoins_materiaux"]


def test_la_provenance_reprend_celle_de_lestimation_sans_la_recalculer():
    reponse, registre_cible = _estimer()
    besoins, estimation_v1 = reponse["besoins_materiaux"], reponse["estimation"]
    assert besoins["devis_id"] == estimation_v1["devis_id"]
    assert besoins["lead_id"] == estimation_v1["lead_id"]
    assert besoins["estimation_id"] == estimation_v1["hash_maillon"]
    assert besoins["bareme_version"] == estimation_v1["bareme_version"] == "2026.1"
    # `niveau_confiance` reprend la forme du CODE (le nombre d'EstimationV1), pas la chaîne du PRD.
    assert besoins["niveau_confiance"] == estimation_v1["niveau_confiance"]
    assert isinstance(besoins["niveau_confiance"], float)
    maillon = registre_cible.lire()[0]
    assert besoins["rang_registre"] == maillon["rang"] == 0
    assert besoins["estimation_id"] == maillon["hash_maillon"]


def test_estimation_v1_reste_gelee_les_besoins_sont_une_cle_soeur():
    reponse, _ = _estimer()
    assert set(reponse["estimation"]) == set(contrats.CHAMPS_ESTIMATION_V1)
    assert "besoins_materiaux" not in reponse["estimation"]


def test_le_hash_du_maillon_couvre_les_quantites():
    """L'`estimation_id` n'est pas une étiquette : le maillon qui le porte contient les lignes, donc
    changer une quantité change la version."""
    reponse_a, _ = _estimer()
    autre = copy.deepcopy(MATERIAUX)
    autre[1]["quantite_par_unite"] = "0.6"
    reponse_b, _ = _estimer(bareme=_bareme(autre))
    assert reponse_a["estimation"]["hash_maillon"] != reponse_b["estimation"]["hash_maillon"]


def test_la_charge_du_registre_porte_les_besoins_et_la_chaine_reste_valide():
    reponse, registre_cible = _estimer()
    charge = registre_cible.lire()[0]["charge"]
    assert charge["besoins_materiaux"] == {
        "lignes": reponse["besoins_materiaux"]["lignes"],
        "facteurs_perte_absents": ["Clous (fictif)"],
    }
    assert registre_cible.valider_chaine() == (True, "")


def test_ni_prix_ni_cout_dans_les_besoins_meme_quand_un_prix_recommande_existe():
    reponse, _ = _estimer(taux_marge="0.35")
    assert reponse["prix_recommande"] is not None, "le prix existe côté réponse"
    cles = set(_cles_recursives(reponse["besoins_materiaux"]))
    assert not cles & besoins_materiaux.CLES_PRIX_ET_COUT_INTERDITES
    assert not {"prix_recommande", "intervalle_confiance", "borne_basse", "borne_haute"} & cles


def test_le_facteur_perte_absent_est_signale_aussi_a_lappelant():
    reponse, _ = _estimer(taux_marge="0.35")
    assert reponse["elements_manquants"] == [
        "facteur_perte non fourni par le barème pour : Clous (fictif) (besoins publiés sans majoration de perte)"
    ]


def test_aucune_note_quand_tous_les_facteurs_de_perte_sont_fournis():
    materiaux = [dict(MATERIAUX[0])]
    reponse, _ = _estimer(bareme=_bareme(materiaux), taux_marge="0.35")
    assert reponse["elements_manquants"] == []
    assert reponse["besoins_materiaux"]["facteurs_perte_absents"] == []


def test_meme_demande_meme_besoins_sur_un_registre_vierge():
    a, _ = _estimer()
    b, _ = _estimer()
    assert a["besoins_materiaux"] == b["besoins_materiaux"]


# --------------------------------------------------------------------------- versions d'estimation
def test_une_nouvelle_estimation_du_meme_devis_est_une_nouvelle_version():
    registre_cible = registre.Registre()
    premiere, _ = _estimer(registre_cible)
    seconde, _ = _estimer(registre_cible)
    v1, v2 = premiere["besoins_materiaux"], seconde["besoins_materiaux"]
    assert v1["devis_id"] == v2["devis_id"], "même lead, même marqueur : même devis"
    assert v1["estimation_id"] != v2["estimation_id"]
    assert (v1["rang_registre"], v2["rang_registre"]) == (0, 1), "ordre total et monotone des versions"
    assert besoins_materiaux.identifiant_evenement(v1) != besoins_materiaux.identifiant_evenement(v2)


def test_deux_devis_distincts_ont_des_besoins_distincts():
    registre_cible = registre.Registre()
    a, _ = _estimer(registre_cible, lead_id="lead-a", empreinte="a" * 64)
    b, _ = _estimer(registre_cible, lead_id="lead-b", empreinte="b" * 64)
    assert a["besoins_materiaux"]["devis_id"] != b["besoins_materiaux"]["devis_id"]


# ------------------------------------------------------------------------- quand rien n'est produit
def test_poste_sans_materiaux_ne_produit_aucun_besoin_et_rien_de_plus_dans_le_registre():
    reponse, registre_cible = _estimer(bareme=_bareme(None), taux_marge="0.35")
    assert reponse["accepte"] is True
    assert reponse["besoins_materiaux"] is None
    assert "besoins_materiaux" not in registre_cible.lire()[0]["charge"]
    assert reponse["elements_manquants"] == [], "un barème sans nomenclature n'est pas une lacune signalée"


def test_voie_bloquee_ne_produit_aucun_besoin_meme_avec_des_materiaux_au_bareme():
    reponse, registre_cible = _estimer(photos=[_photo(largeur=100)])
    assert reponse["accepte"] is True
    assert reponse["estimation"]["prix_bloque"] is True
    assert reponse["besoins_materiaux"] is None
    assert "besoins_materiaux" not in registre_cible.lire()[0]["charge"]


def test_liste_de_photos_vide_ne_produit_aucun_besoin():
    reponse, _ = _estimer(photos=[])
    assert reponse["estimation"]["prix_bloque"] is True
    assert reponse["besoins_materiaux"] is None


def test_estimation_rejetee_en_amont_ne_produit_aucun_besoin():
    contrat_invalide = _contrat()
    del contrat_invalide["ville"]
    registre_cible = registre.Registre()
    reponse = estimation.orchestrer_estimation(
        contrat_invalide, _marqueur(), [PHOTO_AVEC_REFERENCE], SEUILS, _bareme(), 1200, 9000, registre_cible
    )
    assert reponse["accepte"] is False
    assert "besoins_materiaux" not in reponse
    assert registre_cible.lire() == []


# ------------------------------------------------------------------------- rejets, avant toute écriture
@pytest.mark.parametrize(
    "materiaux",
    [
        [],
        "texte",
        [{"materiau": "M", "quantite_par_unite": 0.5, "unite": "u"}],
        [{"materiau": "M", "quantite_par_unite": "-1", "unite": "u"}],
        [{"materiau": "M", "quantite_par_unite": "1", "unite": "u", "prix_unitaire": "3.00"}],
        [{"materiau": "M", "quantite_par_unite": "1", "unite": "u", "facteur_perte": "10"}],
        [{"materiau": "M", "quantite_par_unite": "1", "unite": "u"}] * 2,
    ],
)
def test_bloc_materiaux_malforme_est_un_rejet_nomme_et_rien_nest_ecrit(materiaux):
    registre_cible = registre.Registre()
    bareme = _bareme(None)
    bareme["postes"]["ravalement"]["materiaux"] = materiaux
    reponse, _ = _estimer(registre_cible, bareme=bareme)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "besoins_materiaux"
    assert reponse["verdict"]["code"] == "REJ-BESOINS-MATERIAUX-INVALIDE"
    assert registre_cible.lire() == [], "aucune écriture avant la validation stricte du contrat"


def test_bloc_materiaux_malforme_sur_la_voie_bloquee_ne_bloque_pas_lestimation():
    """Des photos faibles ne produisent aucun besoin : le bloc n'est même pas lu, le blocage du prix
    (l'anti-précision-inventée) reste la seule réponse."""
    bareme = _bareme(None)
    bareme["postes"]["ravalement"]["materiaux"] = "malformé"
    reponse, _ = _estimer(bareme=bareme, photos=[_photo(largeur=100)])
    assert reponse["accepte"] is True
    assert reponse["estimation"]["prix_bloque"] is True


def test_le_contrat_est_valide_a_blanc_avant_la_premiere_ecriture_au_registre():
    """Une version de barème qui n'est pas un texte ferait refuser le contrat à l'assemblage final,
    APRÈS l'inscription au registre : l'assemblage à blanc la refuse avant toute écriture."""
    bareme = _bareme()
    bareme["version"] = 2026
    registre_cible = registre.Registre()
    reponse, _ = _estimer(registre_cible, bareme=bareme)
    assert reponse["accepte"] is False
    assert reponse["etape"] == "besoins_materiaux"
    assert reponse["verdict"]["code"] == "REJ-BESOINS-MATERIAUX-INVALIDE"
    assert registre_cible.lire() == []


def test_un_rejet_du_prix_recommande_ou_de_la_duree_precede_toujours_celui_des_besoins():
    reponse, registre_cible = _estimer(taux_marge="pas-un-taux")
    assert reponse["accepte"] is False
    assert reponse["etape"] == "prix_recommande"
    assert registre_cible.lire() == []


def test_le_bareme_de_lappelant_nest_jamais_modifie():
    bareme = _bareme()
    avant = copy.deepcopy(bareme)
    _estimer(bareme=bareme)
    assert bareme == avant
