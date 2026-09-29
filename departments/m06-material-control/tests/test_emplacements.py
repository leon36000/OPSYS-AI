"""PLAN T4.14 (M6.9) : emplacements de stock et transferts audités — module pur `emplacements.py`.

Ce que ces tests fixent :
- la liste des emplacements est FERMÉE (neuf noms, `inconnu` compris) et une référence est requise, ou interdite, selon
  l'emplacement ;
- un transfert déplace, il ne crée ni ne détruit : la somme des emplacements vaut toujours le stock en main, `inconnu`
  est le résidu, et aucune quantité par emplacement n'est jamais négative ;
- chaque transfert garde acteur, motif, horodatage, quantité et l'avant et l'après de ses deux extrémités, dans une
  chaîne hash-chaînée qui se valide et qui dénonce toute retouche ;
- les hachages de la chaîne de mouvements EXISTANTE ne changent pas d'un octet (empreintes figées, calculées avant
  T4.14).

Identifiants et quantités fictifs (`fictif: true` au sens d'AGENTS.md).
"""

from __future__ import annotations

import ast
import math
from decimal import Decimal
from pathlib import Path

import pytest
from m6_material_control import emplacements
from m6_material_control.registre import Registre

FICTIF = True
MATERIAU = "gouttiere-5po"
DEPOT = {"type": "depot"}
INCONNU = {"type": "inconnu"}
CAMION = {"type": "camion", "reference": "CAM-FICT-1"}
REBUT = {"type": "rebut"}
H = "2026-09-29T09:15:00-04:00"


def _transferer(maillons, de, vers, quantite, stock_total=Decimal(100), transfert_id=None, motif="rangement",
                materiau=MATERIAU, acteur="nathan"):
    resultat, verdict = emplacements.construire_transfert(
        transfert_id or f"T-FICT-{len(maillons) + 1}", materiau, quantite, de, vers, acteur, motif, H,
        stock_total, maillons)
    if resultat is not None and not resultat["deja_enregistre"]:
        maillons.append(resultat["maillon"])
    return resultat, verdict


# ----------------------------------------------------------------------------------------- la liste fermée
def test_la_liste_des_emplacements_est_fermee_et_contient_inconnu():
    assert {
        "depot", "camion", "remorque", "chantier", "employe", "fournisseur", "retour", "rebut", "inconnu"
    } == emplacements.EMPLACEMENTS
    assert isinstance(emplacements.EMPLACEMENTS, frozenset)


@pytest.mark.parametrize("brut", [
    {"type": "depot"}, {"type": "retour"}, {"type": "rebut"}, {"type": "inconnu"},
    {"type": "camion", "reference": "CAM-FICT-1"}, {"type": "remorque", "reference": "REM-FICT-1"},
    {"type": "employe", "reference": "P-FICT-1"}, {"type": "chantier", "reference": "CH-FICT-1"},
    {"type": "fournisseur", "reference": "gentek"},
])
def test_chaque_emplacement_valide_se_normalise(brut):
    normalise, verdict = emplacements.normaliser(brut)
    assert verdict is None and normalise["type"] == brut["type"]
    assert normalise["reference"] == brut.get("reference")


def test_la_cle_d_un_emplacement_est_canonique():
    assert emplacements.cle({"type": "depot", "reference": None}) == "depot"
    assert emplacements.cle({"type": "camion", "reference": "CAM-FICT-1"}) == "camion:CAM-FICT-1"


def test_une_reference_est_rognee():
    normalise, _ = emplacements.normaliser({"type": "camion", "reference": "  CAM-FICT-1 "})
    assert normalise == {"type": "camion", "reference": "CAM-FICT-1"}


@pytest.mark.parametrize("brut, code", [
    ({"type": "garage"}, "REJ-EMPLACEMENT-INCONNU"),
    ({"type": "Depot"}, "REJ-EMPLACEMENT-INCONNU"),
    ({"type": 3}, "REJ-EMPLACEMENT-INCONNU"),
    ({"type": "camion"}, "REJ-EMPLACEMENT-REFERENCE-MANQUANTE"),
    ({"type": "camion", "reference": "  "}, "REJ-EMPLACEMENT-REFERENCE-MANQUANTE"),
    ({"type": "chantier", "reference": None}, "REJ-EMPLACEMENT-REFERENCE-MANQUANTE"),
    ({"type": "depot", "reference": "principal"}, "REJ-EMPLACEMENT-REFERENCE-INATTENDUE"),
    ({"type": "rebut", "reference": "R1"}, "REJ-EMPLACEMENT-REFERENCE-INATTENDUE"),
    ({"reference": "CAM-FICT-1"}, "REJ-EMPLACEMENT-STRUCTURE-INVALIDE"),
    ({"type": "depot", "zone": "A"}, "REJ-EMPLACEMENT-STRUCTURE-INVALIDE"),
    ("depot", "REJ-EMPLACEMENT-STRUCTURE-INVALIDE"),
    (None, "REJ-EMPLACEMENT-STRUCTURE-INVALIDE"),
])
def test_un_emplacement_invalide_est_refuse_par_son_code(brut, code):
    normalise, verdict = emplacements.normaliser(brut)
    assert normalise is None and verdict["code"] == code


# --------------------------------------------------------------------------------------- un transfert
def test_ranger_du_stock_inconnu_au_depot_localise_sans_creer_de_stock():
    maillons: list[dict] = []

    resultat, verdict = _transferer(maillons, INCONNU, DEPOT, 60.0)

    assert verdict is None and resultat["deja_enregistre"] is False
    maillon = resultat["maillon"]
    assert (maillon["materiau_id"], maillon["quantite"], maillon["acteur"], maillon["motif"]) == (
        MATERIAU, "60", "nathan", "rangement")
    assert maillon["avant"] == {"de": "100", "vers": "0"} and maillon["apres"] == {"de": "40", "vers": "60"}
    repartition = emplacements.repartition(MATERIAU, Decimal(100), maillons)
    assert repartition == {"depot": Decimal("60"), "inconnu": Decimal("40")}
    assert sum(repartition.values()) == Decimal(100), "un transfert déplace, il ne crée rien"


def test_un_stock_jamais_localise_est_tout_entier_a_l_emplacement_inconnu():
    assert emplacements.repartition(MATERIAU, Decimal(25), []) == {"inconnu": Decimal(25)}


def test_de_depot_a_camion_puis_du_camion_au_chantier():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 60.0)
    _, verdict = _transferer(maillons, DEPOT, CAMION, 25.0)
    assert verdict is None
    _, verdict = _transferer(maillons, CAMION, {"type": "chantier", "reference": "CH-FICT-1"}, 10.0)
    assert verdict is None

    assert emplacements.repartition(MATERIAU, Decimal(100), maillons) == {
        "camion:CAM-FICT-1": Decimal("15"), "chantier:CH-FICT-1": Decimal("10"),
        "depot": Decimal("35"), "inconnu": Decimal("40")}


def test_on_ne_sort_jamais_d_un_emplacement_plus_que_ce_qu_il_contient():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 10.0)

    resultat, verdict = _transferer(maillons, DEPOT, CAMION, 10.5)

    assert resultat is None and verdict["code"] == "REJ-TRANSFERT-STOCK-INSUFFISANT"
    assert "depot" in verdict["detail"] and "10" in verdict["detail"]
    assert len(maillons) == 1, "aucun maillon de plus"


def test_on_ne_localise_jamais_plus_que_le_stock_qui_existe():
    _, verdict = _transferer([], INCONNU, DEPOT, 100.5)
    assert verdict["code"] == "REJ-TRANSFERT-STOCK-INSUFFISANT"
    _, verdict = _transferer([], INCONNU, DEPOT, 1.0, stock_total=Decimal(0))
    assert verdict["code"] == "REJ-TRANSFERT-STOCK-INSUFFISANT"


def test_un_article_sans_stock_ne_se_transfere_pas_d_un_emplacement_vide():
    _, verdict = _transferer([], CAMION, DEPOT, 1.0)
    assert verdict["code"] == "REJ-TRANSFERT-STOCK-INSUFFISANT"


def test_le_transfert_exact_de_tout_le_contenu_est_permis_et_vide_l_emplacement():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 30.0)
    _, verdict = _transferer(maillons, DEPOT, CAMION, 30.0)
    assert verdict is None
    repartition = emplacements.repartition(MATERIAU, Decimal(100), maillons)
    assert "depot" not in repartition and repartition["camion:CAM-FICT-1"] == Decimal("30")


def test_origine_et_destination_identiques_sont_refusees():
    _, verdict = _transferer([], DEPOT, {"type": "depot"}, 1.0)
    assert verdict["code"] == "REJ-TRANSFERT-MEME-EMPLACEMENT"
    _, verdict = _transferer([], CAMION, {"type": "camion", "reference": "CAM-FICT-1"}, 1.0)
    assert verdict["code"] == "REJ-TRANSFERT-MEME-EMPLACEMENT"


def test_deux_camions_distincts_ne_sont_pas_le_meme_emplacement():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, CAMION, 10.0)
    _, verdict = _transferer(maillons, CAMION, {"type": "camion", "reference": "CAM-FICT-2"}, 4.0)
    assert verdict is None


@pytest.mark.parametrize("quantite", [0, 0.0, -1.0, -0.001, math.nan, math.inf, -math.inf, True, "5", None, [1]])
def test_une_quantite_invalide_est_refusee(quantite):
    resultat, verdict = _transferer([], INCONNU, DEPOT, quantite)
    assert resultat is None and verdict["code"] == "REJ-TRANSFERT-QUANTITE-INVALIDE"


def test_une_quantite_trop_longue_est_refusee():
    _, verdict = _transferer([], INCONNU, DEPOT, 1e-300, stock_total=Decimal(1))
    assert verdict["code"] == "REJ-TRANSFERT-QUANTITE-INVALIDE"


@pytest.mark.parametrize("motif", ["", "   ", None, 3])
def test_un_motif_vide_est_refuse_chaque_transfert_garde_sa_raison(motif):
    resultat, verdict = _transferer([], INCONNU, DEPOT, 1.0, motif=motif)
    assert resultat is None and verdict["code"] == "REJ-TRANSFERT-MOTIF-VIDE"


def test_identifiants_horodatage_et_acteur_requis():
    for arguments, code in (
        ({"transfert_id": " "}, "REJ-TRANSFERT-ID-VIDE"),
        ({"materiau": ""}, "REJ-TRANSFERT-MATERIAU-VIDE"),
        ({"acteur": ""}, "REJ-TRANSFERT-HORODATAGE-VIDE"),
    ):
        arguments = {"transfert_id": "T-FICT-1", "materiau": MATERIAU, "acteur": "nathan", **arguments}
        resultat, verdict = emplacements.construire_transfert(
            arguments["transfert_id"], arguments["materiau"], 1.0, INCONNU, DEPOT, arguments["acteur"], "m", H,
            Decimal(10), [])
        assert resultat is None and verdict["code"] == code
    _, verdict = emplacements.construire_transfert("T-FICT-1", MATERIAU, 1.0, INCONNU, DEPOT, "nathan", "m", "",
                                                   Decimal(10), [])
    assert verdict["code"] == "REJ-TRANSFERT-HORODATAGE-VIDE"


def test_un_emplacement_invalide_est_refuse_avant_tout_calcul():
    _, verdict = _transferer([], {"type": "garage"}, DEPOT, 1.0)
    assert verdict["code"] == "REJ-EMPLACEMENT-INCONNU"
    _, verdict = _transferer([], INCONNU, {"type": "camion"}, 1.0)
    assert verdict["code"] == "REJ-EMPLACEMENT-REFERENCE-MANQUANTE"


# ---------------------------------------------------------------------------------------- idempotence
def test_le_meme_identifiant_et_le_meme_geste_est_un_rejeu_rien_n_est_deplace_deux_fois():
    maillons: list[dict] = []
    premier, _ = _transferer(maillons, INCONNU, DEPOT, 60.0, transfert_id="T-FICT-A")

    rejeu, verdict = _transferer(maillons, INCONNU, DEPOT, 60.0, transfert_id="T-FICT-A")

    assert verdict is None and rejeu["deja_enregistre"] is True
    assert rejeu["maillon"] == premier["maillon"] and len(maillons) == 1
    assert emplacements.repartition(MATERIAU, Decimal(100), maillons)["depot"] == Decimal("60")


def test_le_meme_identifiant_pour_un_autre_geste_est_refuse():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 60.0, transfert_id="T-FICT-A")
    for de, vers, quantite in ((INCONNU, DEPOT, 61.0), (INCONNU, CAMION, 60.0), (DEPOT, CAMION, 60.0)):
        resultat, verdict = _transferer(maillons, de, vers, quantite, transfert_id="T-FICT-A")
        assert resultat is None and verdict["code"] == "REJ-TRANSFERT-ID-DEJA-UTILISE"
    assert len(maillons) == 1


# ------------------------------------------------------------------------------------ stock localisé
def test_une_sortie_non_localisee_qui_depasse_le_reste_bloque_tout_transfert_jusqu_a_regularisation():
    """100 en main, 90 localisés au dépôt. Une consommation non localisée de 30 ramène le total à 70 : le dépôt
    « contient » 90 pour 70 en main, l'emplacement inconnu vaut -20. Aucun transfert ne passe, sauf celui qui
    régularise (dépôt vers inconnu)."""
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 90.0)
    total_apres_sortie = Decimal(70)
    assert emplacements.repartition(MATERIAU, total_apres_sortie, maillons)["inconnu"] == Decimal(-20)

    resultat, verdict = _transferer(maillons, DEPOT, CAMION, 5.0, stock_total=total_apres_sortie)
    assert resultat is None and verdict["code"] == "REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT"
    assert "inconnu" in verdict["detail"]

    _, verdict = _transferer(maillons, DEPOT, INCONNU, 20.0, stock_total=total_apres_sortie)
    assert verdict is None
    repartition = emplacements.repartition(MATERIAU, total_apres_sortie, maillons)
    assert repartition == {"depot": Decimal("70"), "inconnu": Decimal("0")}
    _, verdict = _transferer(maillons, DEPOT, CAMION, 5.0, stock_total=total_apres_sortie)
    assert verdict is None


def test_aucune_quantite_par_emplacement_n_est_jamais_negative_sur_une_suite_de_transferts():
    """Suite pseudo-aléatoire fixe (graine) : après chaque transfert accepté, chaque emplacement est >= 0 et la somme
    vaut le stock. Les refusés n'ont rien écrit."""
    import random

    hasard = random.Random(4014)
    lieux = [INCONNU, DEPOT, CAMION, {"type": "remorque", "reference": "REM-FICT-1"},
             {"type": "chantier", "reference": "CH-FICT-1"}, REBUT, {"type": "retour"}]
    maillons: list[dict] = []
    total = Decimal(200)
    acceptes = refuses = 0
    for _ in range(300):
        de, vers = hasard.sample(lieux, 2)
        avant = list(maillons)
        resultat, verdict = _transferer(maillons, de, vers, hasard.randint(1, 60) / 2, stock_total=total)
        if verdict is None:
            acceptes += 1
        else:
            refuses += 1
            assert maillons == avant
        repartition = emplacements.repartition(MATERIAU, total, maillons)
        assert all(quantite >= 0 for quantite in repartition.values()), repartition
        assert sum(repartition.values()) == total
    assert acceptes > 50 and refuses > 20, (acceptes, refuses)
    assert emplacements.valider_chaine(maillons) == (True, "")


# ------------------------------------------------------------------------------------------ hors main
def test_fournisseur_retour_et_rebut_ne_sont_pas_en_main():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 50.0)
    _transferer(maillons, DEPOT, REBUT, 8.0)
    _transferer(maillons, DEPOT, {"type": "fournisseur", "reference": "gentek"}, 5.0)
    _transferer(maillons, DEPOT, {"type": "retour"}, 2.0)

    assert emplacements.hors_main_par_article(maillons) == {MATERIAU: Decimal("15")}
    assert {"fournisseur", "retour", "rebut"} == emplacements.EMPLACEMENTS_HORS_MAIN


def test_ce_qui_revient_du_rebut_dans_le_depot_est_de_nouveau_en_main():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, REBUT, 8.0)
    assert emplacements.hors_main_par_article(maillons) == {MATERIAU: Decimal("8")}
    _transferer(maillons, REBUT, DEPOT, 3.0)
    assert emplacements.hors_main_par_article(maillons) == {MATERIAU: Decimal("5")}


def test_un_deplacement_entre_emplacements_en_main_ne_change_pas_le_hors_main():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 50.0)
    _transferer(maillons, DEPOT, CAMION, 20.0)
    assert emplacements.hors_main_par_article(maillons) == {}


def test_le_hors_main_se_compte_par_article():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, REBUT, 4.0)
    _transferer(maillons, INCONNU, REBUT, 6.0, materiau="vis-inox")
    assert emplacements.hors_main_par_article(maillons) == {MATERIAU: Decimal("4"), "vis-inox": Decimal("6")}


# ------------------------------------------------------------------------------------- la chaîne d'audit
def test_la_chaine_des_transferts_se_valide_et_chaque_maillon_porte_le_precedent():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 60.0)
    _transferer(maillons, DEPOT, CAMION, 25.0)
    _transferer(maillons, CAMION, DEPOT, 5.0)

    assert emplacements.valider_chaine(maillons) == (True, "")
    assert maillons[0]["hash_precedent"] == ""
    assert maillons[1]["hash_precedent"] == maillons[0]["hash_maillon"]
    assert emplacements.hash_tete(maillons) == maillons[2]["hash_maillon"]
    assert [m["index"] for m in maillons] == [0, 1, 2]
    assert emplacements.hash_tete([]) == ""


@pytest.mark.parametrize("champ, valeur", [
    ("acteur", "quelqu-un-d-autre"), ("motif", "autre raison"), ("quantite", "1"),
    ("horodatage", "2027-01-01T00:00:00-05:00"), ("materiau_id", "vis-inox"),
    ("de", {"type": "rebut", "reference": None}), ("vers", {"type": "rebut", "reference": None}),
])
def test_retoucher_un_transfert_apres_coup_se_voit(champ, valeur):
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 60.0)
    _transferer(maillons, DEPOT, CAMION, 25.0)
    maillons[0][champ] = valeur

    ok, detail = emplacements.valider_chaine(maillons)

    assert ok is False and detail == "maillon invalide à l'index 0"


def test_retirer_un_transfert_du_milieu_se_voit():
    maillons: list[dict] = []
    for i in range(3):
        _transferer(maillons, INCONNU, DEPOT, 1.0 + i)
    del maillons[1]
    assert emplacements.valider_chaine(maillons)[0] is False


def test_la_chaine_est_deterministe():
    a: list[dict] = []
    b: list[dict] = []
    for maillons in (a, b):
        _transferer(maillons, INCONNU, DEPOT, 60.0)
        _transferer(maillons, DEPOT, CAMION, 25.0)
    assert [m["hash_maillon"] for m in a] == [m["hash_maillon"] for m in b]


def test_l_avant_et_l_apres_de_chaque_extremite_sont_gardes():
    maillons: list[dict] = []
    _transferer(maillons, INCONNU, DEPOT, 60.0)
    resultat, _ = _transferer(maillons, DEPOT, CAMION, 25.0)
    assert resultat["maillon"]["avant"] == {"de": "60", "vers": "0"}
    assert resultat["maillon"]["apres"] == {"de": "35", "vers": "25"}


# --------------------------------------------- la chaîne de mouvements existante ne change pas d'un octet
def test_les_hachages_de_la_chaine_de_mouvements_existante_sont_inchanges():
    """Empreintes figées, calculées AVANT T4.14 (commit de départ) sur cinq mouvements fictifs, avec et sans `wct_id` :
    ajouter les emplacements n'a pas touché à `registre.py`, donc aucun hachage n'a bougé et une chaîne écrite
    avant se valide encore."""
    registre = Registre()
    maillons, erreur = registre.ajouter_lot([
        {"type_mouvement": "RECEPTION", "chantier_id": "CH-FICT-1", "materiau_id": "gouttiere-5po",
         "quantite": 100.0, "cout_unitaire": 8.5},
        {"type_mouvement": "RECEPTION", "chantier_id": "CH-FICT-1", "materiau_id": "vis-inox",
         "quantite": 20.0, "cout_unitaire": 0.35},
        {"type_mouvement": "CONSOMMATION", "chantier_id": "CH-FICT-1", "materiau_id": "gouttiere-5po",
         "quantite": -40.0, "cout_unitaire": 8.5, "wct_id": "WCT-FICT-1"},
        {"type_mouvement": "PERTE", "chantier_id": "CH-FICT-1", "materiau_id": "vis-inox",
         "quantite": -2.0, "cout_unitaire": 0.35, "wct_id": "WCT-FICT-1"},
        {"type_mouvement": "VARIANCE_INVENTAIRE", "chantier_id": "CH-FICT-1", "materiau_id": "vis-inox",
         "quantite": -1.0, "cout_unitaire": None},
    ])

    assert erreur is None
    assert [m["hash_maillon"] for m in maillons] == [
        "9e9bc257bd782578503c26b1411635d058c521e48a12f6693709c713d09ab5d1",
        "fc4550a512f50d1c8282cd4e5e43ddabcabaff526df7795c78b3c22973e7126f",
        "d3d461f451925a16db28d9682f3e3f649e10aa310e999b6c6ca9242c3df227ab",
        "2c7d24fd3ca3b534a14f5f29b111129b273d96cfc87d58cb826c22762615b21a",
        "32a87ea1fcf820075641e80295a95a009c6f2c5ce37072814b25c623ce60cedc",
    ]
    assert registre.valider_chaine() == (True, "")
    assert set(maillons[0]) == {"index", "type_mouvement", "chantier_id", "materiau_id", "quantite",
                                "cout_unitaire", "hash_precedent", "hash_maillon"}, "aucun champ de plus"


# --------------------------------------------------------------------------------- module pur, sans opsys
def test_le_module_est_pur_aucun_import_opsys_ni_horloge():
    source = Path(emplacements.__file__).read_text(encoding="utf-8")
    importes = {
        noeud.module.split(".")[0] if isinstance(noeud, ast.ImportFrom) and noeud.module else alias.name.split(".")[0]
        for noeud in ast.walk(ast.parse(source))
        if isinstance(noeud, (ast.Import, ast.ImportFrom))
        for alias in (noeud.names if isinstance(noeud, ast.Import) else [ast.alias(name="")])
    }
    assert "opsys" not in importes and "datetime" not in importes and "time" not in importes
    assert "random" not in importes and "uuid" not in importes
