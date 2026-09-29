"""besoins_prevus.py — le prévu PROVISOIRE d'une estimation M3 (PLAN T2.3-e), rangé dans le registre
EXISTANT des besoins prévus, jamais un second. Module pur : `maillons_existants` est une liste
Python en mémoire.

Ce que ces tests tiennent : une estimation ne bloque jamais le prévu définitif du devis accepté (ni
ne lui vole son `chantier_id`) ; `pour_devis` reste UNE notion (définitif d'abord, sinon la version
d'estimation la plus récente) ; les versions s'ajoutent sans rien réécrire et l'idempotence est par
version ; une version périmée arrivée en retard n'écrase jamais la plus récente. Fixtures fictives.
"""

from __future__ import annotations

import copy

import pytest
from m6_material_control import besoins_prevus

HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64
DEVIS = "M3-DEVIS-0123456789abcdef"


def _charge(estimation_id=HASH_1, rang=0, devis_id=DEVIS, quantite="13.32", **surcharges):
    charge = {
        "devis_id": devis_id,
        "lead_id": "lead-fictif-001",
        "estimation_id": estimation_id,
        "rang_registre": rang,
        "bareme_version": "2026.1",
        "niveau_confiance": 0.9,
        "lignes": [
            {
                "materiau": "Revêtement vinyle (fictif)", "sku": "SKU-FICTIF-VINYLE",
                "quantite_estimee": quantite, "unite": "carton", "facteur_perte": "0.10",
            },
            {"materiau": "Clous (fictif)", "quantite_estimee": "600", "unite": "boite"},
        ],
        "facteurs_perte_absents": ["Clous (fictif)"],
    }
    charge.update(surcharges)
    return charge


def _ligne_definitive(materiau_id="SKU-FICTIF-VINYLE", quantite=40.0):
    return {"materiau_id": materiau_id, "quantite_estimee": quantite, "unite": "carton"}


def _ranger(charge, maillons):
    maillon, statut = besoins_prevus.enregistrer_estimation(charge, maillons)
    if maillon is not None:
        maillons.append(maillon)
    return maillon, statut


# ------------------------------------------------------------------------------------ nominal
def test_estimation_nominale_construit_un_prevu_provisoire_sans_ecrire():
    maillons: list[dict] = []
    maillon, statut = besoins_prevus.enregistrer_estimation(_charge(), maillons)
    assert statut == "enregistre"
    assert maillons == [], "enregistrer_estimation() ne mute jamais maillons_existants"
    assert maillon["source"] == besoins_prevus.SOURCE_ESTIMATION_M3 == "estimation_m3"
    assert maillon["devis_id"] == DEVIS
    assert maillon["chantier_id"] is None, "M3 ne connaît pas le chantier à l'estimation : jamais deviné"
    assert maillon["estimation_id"] == HASH_1
    assert maillon["rang_registre"] == 0


def test_les_lignes_du_prevu_ont_le_format_interne_de_m6_et_la_quantite_nette():
    maillon, _ = besoins_prevus.enregistrer_estimation(_charge(), [])
    assert maillon["lignes"] == [
        {"materiau_id": "SKU-FICTIF-VINYLE", "quantite_estimee": 13.32, "unite": "carton"},
        {"materiau_id": "Clous (fictif)", "quantite_estimee": 600.0, "unite": "boite"},
    ], "la quantité est NETTE : le facteur de perte n'est jamais appliqué à la réception"


def test_le_detail_garde_les_textes_exacts_le_facteur_de_perte_et_les_pertes_absentes():
    maillon, _ = besoins_prevus.enregistrer_estimation(_charge(), [])
    vinyle, clous = maillon["detail_lignes"]
    assert vinyle["materiau_id"] == "SKU-FICTIF-VINYLE"
    assert vinyle["quantite_estimee"] == "13.32"
    assert vinyle["facteur_perte"] == "0.10"
    assert "facteur_perte" not in clous, "absent reste absent, jamais mis à zéro"
    assert maillon["facteurs_perte_absents"] == ["Clous (fictif)"]
    assert maillon["bareme_version"] == "2026.1"
    assert maillon["niveau_confiance"] == 0.9
    assert maillon["lead_id"] == "lead-fictif-001"


def test_le_maillon_ne_porte_aucun_prix_ni_cout():
    maillon, _ = besoins_prevus.enregistrer_estimation(_charge(), [])
    interdits = {"prix", "prix_unitaire", "cout", "cout_unitaire", "montant", "marge", "taux_marge"}
    assert not interdits & set(maillon)
    assert not interdits & {cle for ligne in maillon["detail_lignes"] for cle in ligne}


def test_le_maillon_ne_partage_rien_de_mutable_avec_le_contrat():
    charge = _charge()
    maillon, _ = besoins_prevus.enregistrer_estimation(charge, [])
    maillon["detail_lignes"][0]["quantite_estimee"] = "999"
    maillon["facteurs_perte_absents"].append("x")
    assert charge["lignes"][0]["quantite_estimee"] == "13.32"
    assert charge["facteurs_perte_absents"] == ["Clous (fictif)"]


# ---------------------------------------------------------------------------- idempotence / versions
def test_meme_version_deux_fois_est_un_no_op():
    maillons: list[dict] = []
    _ranger(_charge(), maillons)
    assert besoins_prevus.enregistrer_estimation(_charge(), maillons) == (None, "deja_recu")
    assert len(maillons) == 1


def test_meme_estimation_id_avec_un_contenu_different_reste_un_rejeu_jamais_une_fusion():
    maillons: list[dict] = []
    _ranger(_charge(quantite="13.32"), maillons)
    assert besoins_prevus.enregistrer_estimation(_charge(quantite="99"), maillons) == (None, "deja_recu")
    assert maillons[0]["detail_lignes"][0]["quantite_estimee"] == "13.32"


def test_une_version_plus_recente_s_ajoute_sans_rien_reecrire():
    maillons: list[dict] = []
    _ranger(_charge(HASH_1, rang=0, quantite="13.32"), maillons)
    premier = copy.deepcopy(maillons[0])
    maillon, statut = _ranger(_charge(HASH_2, rang=1, quantite="20"), maillons)
    assert statut == "enregistre"
    assert len(maillons) == 2, "append-only : la version précédente reste au registre"
    assert maillons[0] == premier
    assert maillon["estimation_id"] == HASH_2


def test_une_version_perimee_arrivee_en_retard_est_ignoree():
    maillons: list[dict] = []
    _ranger(_charge(HASH_2, rang=5, quantite="20"), maillons)
    assert besoins_prevus.enregistrer_estimation(_charge(HASH_1, rang=2), maillons) == (None, "version_perimee")
    assert len(maillons) == 1


def test_un_rang_egal_avec_une_autre_empreinte_n_ecrase_pas_la_version_rangee():
    maillons: list[dict] = []
    _ranger(_charge(HASH_1, rang=3), maillons)
    assert besoins_prevus.enregistrer_estimation(_charge(HASH_2, rang=3), maillons) == (None, "version_perimee")


def test_l_idempotence_est_par_devis_deux_devis_ne_se_genent_pas():
    maillons: list[dict] = []
    _ranger(_charge(HASH_1, rang=0), maillons)
    _, statut = _ranger(_charge(HASH_1, rang=0, devis_id="M3-DEVIS-autre"), maillons)
    assert statut == "enregistre"
    assert len(maillons) == 2


def test_un_rang_plus_ancien_pour_un_autre_devis_n_est_pas_perime():
    maillons: list[dict] = []
    _ranger(_charge(HASH_2, rang=9), maillons)
    _, statut = _ranger(_charge(HASH_3, rang=0, devis_id="M3-DEVIS-autre"), maillons)
    assert statut == "enregistre"


# ------------------------------------------------------------------------------------ pour_devis
def test_pour_devis_rend_la_version_d_estimation_la_plus_recente_faute_de_definitif():
    maillons: list[dict] = []
    _ranger(_charge(HASH_1, rang=0, quantite="13.32"), maillons)
    _ranger(_charge(HASH_2, rang=1, quantite="20"), maillons)
    courant = besoins_prevus.pour_devis(DEVIS, maillons)
    assert courant["estimation_id"] == HASH_2
    assert courant["lignes"][0]["quantite_estimee"] == 20.0


def test_pour_devis_rend_toujours_un_maillon_de_la_forme_que_les_lecteurs_attendent():
    maillons: list[dict] = []
    _ranger(_charge(), maillons)
    courant = besoins_prevus.pour_devis(DEVIS, maillons)
    assert {"chantier_id", "devis_id", "lignes"} <= set(courant)
    assert courant["chantier_id"] is None


def test_pour_devis_prefere_le_definitif_meme_quand_l_estimation_est_arrivee_apres():
    maillons: list[dict] = []
    definitif, code = besoins_prevus.enregistrer("C1", DEVIS, [_ligne_definitive()], maillons)
    assert code is None
    maillons.append(definitif)
    _ranger(_charge(HASH_1, rang=0), maillons)
    _ranger(_charge(HASH_2, rang=1), maillons)
    courant = besoins_prevus.pour_devis(DEVIS, maillons)
    assert courant["chantier_id"] == "C1"
    assert courant["lignes"] == [_ligne_definitive()]
    assert "source" not in courant


def test_pour_devis_prefere_le_definitif_meme_quand_l_estimation_est_arrivee_avant():
    maillons: list[dict] = []
    _ranger(_charge(), maillons)
    definitif, _ = besoins_prevus.enregistrer("C1", DEVIS, [_ligne_definitive()], maillons)
    maillons.append(definitif)
    assert besoins_prevus.pour_devis(DEVIS, maillons)["chantier_id"] == "C1"


def test_pour_devis_sans_estimation_ni_definitif_rend_none():
    assert besoins_prevus.pour_devis(DEVIS, []) is None
    maillons: list[dict] = []
    _ranger(_charge(devis_id="M3-DEVIS-autre"), maillons)
    assert besoins_prevus.pour_devis(DEVIS, maillons) is None


@pytest.mark.parametrize("devis_id", [None, "", 3])
def test_pour_devis_avec_un_identifiant_invalide_rend_none(devis_id):
    maillons: list[dict] = []
    _ranger(_charge(), maillons)
    assert besoins_prevus.pour_devis(devis_id, maillons) is None


# --------------------------------------------- l'estimation ne bloque pas le prévu définitif (`enregistrer`)
def test_une_estimation_deja_rangee_ne_fait_pas_refuser_le_devis_accepte():
    maillons: list[dict] = []
    _ranger(_charge(), maillons)
    maillon, code = besoins_prevus.enregistrer("C1", DEVIS, [_ligne_definitive()], maillons)
    assert code is None, "sinon le devis accepté perdrait son prévu et son chantier_id"
    assert maillon["chantier_id"] == "C1"


def test_le_prevu_definitif_reste_idempotent_par_devis_meme_apres_une_estimation():
    maillons: list[dict] = []
    _ranger(_charge(), maillons)
    definitif, _ = besoins_prevus.enregistrer("C1", DEVIS, [_ligne_definitive()], maillons)
    maillons.append(definitif)
    maillon, code = besoins_prevus.enregistrer("C2", DEVIS, [_ligne_definitive(quantite=99.0)], maillons)
    assert maillon is None
    assert code == "REJ-BESOINS-PREVUS-DEJA-ENREGISTRES"
    assert besoins_prevus.pour_devis(DEVIS, maillons)["lignes"] == [_ligne_definitive()]


def test_une_estimation_arrivee_apres_le_definitif_est_rangee_mais_n_est_jamais_le_prevu():
    maillons: list[dict] = []
    definitif, _ = besoins_prevus.enregistrer("C1", DEVIS, [_ligne_definitive()], maillons)
    maillons.append(definitif)
    maillon, statut = _ranger(_charge(), maillons)
    assert statut == "enregistre", "traçabilité : le fait reçu reste au registre"
    assert maillon["source"] == "estimation_m3"
    assert besoins_prevus.pour_devis(DEVIS, maillons)["chantier_id"] == "C1"


# --------------------------------------------------------------- incohérence interne : panne explicite
def test_des_lignes_derivees_refusees_par_la_validation_interne_sont_une_panne_explicite():
    """Un contrat qui aurait échappé à `besoins_materiaux_recus.valider` (deux lignes de même
    identité) ne devient jamais un prévu fabriqué : `ValueError`, que le répartiteur réessaie puis
    met en quarantaine."""
    charge = _charge()
    charge["lignes"] = [charge["lignes"][1], dict(charge["lignes"][1])]
    with pytest.raises(ValueError, match="REJ-BESOIN-CHANTIER-DUPLIQUE"):
        besoins_prevus.enregistrer_estimation(charge, [])
