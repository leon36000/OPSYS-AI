"""PLAN T4.14 (M6.8, M6.9, M6.15) : `disponible = en main - réservé` et le réapprovisionnement qui en découle — modules
purs `stock.py` et `reapprovisionnement.py`.

Ce que ces tests fixent :
- `stock.deriver_disponibilite` retranche le hors main (fournisseur, retour, rebut) puis le réservé, en décimal exact,
  sans jamais ramener un en main négatif à zéro (une donnée à vérifier reste visible) ;
- le réapprovisionnement compare le DISPONIBLE au seuil quand du stock est réservé, et rien ne change sans réservation :
  les verdicts d'avant sont identiques, clé pour clé ;
- le texte canonique d'une quantité ne dépend pas de l'arithmétique qui l'a produite.

Identifiants et quantités fictifs (`fictif: true` au sens d'AGENTS.md).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from m6_material_control import emplacements, reapprovisionnement, stock

FICTIF = True
ARTICLES = {"gouttiere-5po": {"seuil_reapprovisionnement": 150, "quantite_cible": 300}}


def _mouvement(materiau_id, quantite, type_mouvement="RECEPTION", chantier_id="CH-FICT-1"):
    return {"type_mouvement": type_mouvement, "chantier_id": chantier_id, "materiau_id": materiau_id,
            "quantite": quantite, "cout_unitaire": 1.0}


# ------------------------------------------------------------------------------------- texte canonique
@pytest.mark.parametrize("valeur, attendu", [
    (Decimal("100.0"), "100"), (Decimal("100"), "100"), (Decimal("0.30"), "0.3"), (Decimal("0.0"), "0"),
    (Decimal("-0.0"), "0"), (Decimal("1E+2"), "100"), (Decimal("0.0000001"), "0.0000001"), (Decimal("12.50"), "12.5"),
    (Decimal("-5.0"), "-5"),
])
def test_le_texte_canonique_ne_depend_pas_de_l_arithmetique(valeur, attendu):
    assert stock.texte_canonique(valeur) == attendu


# ------------------------------------------------------------------------------- deriver_disponibilite
def test_disponible_est_en_main_moins_reserve_et_en_main_est_le_stock_moins_le_hors_main():
    mouvements = [_mouvement("gouttiere-5po", 100.0), _mouvement("gouttiere-5po", -10.0, "CONSOMMATION")]

    resultat = stock.deriver_disponibilite(
        ["gouttiere-5po"], mouvements, {"gouttiere-5po": Decimal("20")}, {"gouttiere-5po": Decimal("30")})

    assert resultat == {"gouttiere-5po": {
        "stock_theorique": Decimal("90"), "hors_main": Decimal("20"), "en_main": Decimal("70"),
        "reserve": Decimal("30"), "disponible": Decimal("40")}}


def test_un_article_sans_hors_main_ni_reserve_a_tout_son_stock_disponible():
    resultat = stock.deriver_disponibilite(["a", "b"], [_mouvement("a", 5.0)], {}, {})
    assert resultat["a"]["disponible"] == 5 and resultat["a"]["hors_main"] == 0 and resultat["a"]["reserve"] == 0
    assert resultat["b"]["stock_theorique"] == 0 and resultat["b"]["disponible"] == 0, "sans mouvement : stock vide"


def test_un_en_main_negatif_reste_negatif_jamais_ramene_a_zero():
    resultat = stock.deriver_disponibilite(["a"], [_mouvement("a", -3.0, "PERTE")], {}, {"a": Decimal("2")})
    assert resultat["a"]["en_main"] == -3 and resultat["a"]["disponible"] == -5


def test_les_sommes_sont_exactes_en_decimal():
    mouvements = [_mouvement("scellant", 0.1), _mouvement("scellant", 0.2)]
    resultat = stock.deriver_disponibilite(["scellant"], mouvements, {}, {"scellant": Decimal("0.3")})
    assert resultat["scellant"]["disponible"] == 0 and resultat["scellant"]["stock_theorique"] == Decimal("0.3")


def test_seuls_les_articles_demandes_sont_rendus():
    resultat = stock.deriver_disponibilite(["a"], [_mouvement("a", 1.0), _mouvement("b", 9.0)], {}, {})
    assert list(resultat) == ["a"]


def test_les_mouvements_d_inventaire_ne_comptent_pas_dans_le_disponible():
    mouvements = [_mouvement("a", 10.0), _mouvement("a", -4.0, "VARIANCE_INVENTAIRE")]
    assert stock.deriver_disponibilite(["a"], mouvements, {}, {})["a"]["en_main"] == 10


# ------------------------------------------------------------------ variation de l'en main d'un transfert
@pytest.mark.parametrize("origine, destination, attendu", [
    ({"type": "inconnu"}, {"type": "depot"}, 0),
    ({"type": "depot"}, {"type": "camion", "reference": "C1"}, 0),
    ({"type": "depot"}, {"type": "rebut"}, -1),
    ({"type": "camion", "reference": "C1"}, {"type": "fournisseur", "reference": "gentek"}, -1),
    ({"type": "chantier", "reference": "CH1"}, {"type": "retour"}, -1),
    ({"type": "rebut"}, {"type": "depot"}, 1),
    ({"type": "fournisseur", "reference": "gentek"}, {"type": "camion", "reference": "C1"}, 1),
    ({"type": "rebut"}, {"type": "retour"}, 0),
])
def test_variation_en_main_d_un_transfert(origine, destination, attendu):
    normalise = [emplacements.normaliser(e)[0] for e in (origine, destination)]
    assert emplacements.variation_en_main(*normalise) == attendu


# -------------------------------------------------------------------------- réapprovisionnement, T4.14
def test_sans_reservation_le_verdict_est_celui_d_avant_cle_pour_cle():
    bas = reapprovisionnement.evaluer("gouttiere-5po", Decimal("100"), ARTICLES)
    assert bas == {
        "materiau_id": "gouttiere-5po", "statut": "stock_bas", "stock_theorique": "100",
        "seuil_reapprovisionnement": "150", "quantite_cible": "300", "quantite_a_commander": "200",
        "stock_negatif": False}
    suffisant = reapprovisionnement.evaluer("gouttiere-5po", Decimal("150"), ARTICLES)
    assert suffisant == {"materiau_id": "gouttiere-5po", "statut": "stock_suffisant", "stock_theorique": "150"}
    assert reapprovisionnement.evaluer("gouttiere-5po", Decimal("100"), ARTICLES, reserve=None) == bas


def test_un_stock_suffisant_en_main_est_bas_quand_le_disponible_passe_sous_le_seuil():
    """200 en main, seuil 150 : suffisant. Avec 100 réservés, le disponible (100) est sous le seuil : bas, et la
    quantité à commander est cible - DISPONIBLE (200), pas cible - en main (100)."""
    sans = reapprovisionnement.evaluer("gouttiere-5po", Decimal("200"), ARTICLES)
    avec = reapprovisionnement.evaluer("gouttiere-5po", Decimal("200"), ARTICLES, reserve=Decimal("100"))

    assert sans["statut"] == "stock_suffisant"
    assert avec["statut"] == "stock_bas"
    assert (avec["stock_theorique"], avec["stock_reserve"], avec["stock_disponible"]) == ("200", "100", "100")
    assert avec["quantite_a_commander"] == "200"


def test_un_disponible_egal_au_seuil_n_est_pas_bas():
    verdict = reapprovisionnement.evaluer("gouttiere-5po", Decimal("250"), ARTICLES, reserve=Decimal("100"))
    assert verdict["statut"] == "stock_suffisant" and verdict["stock_disponible"] == "150"


def test_le_verdict_suffisant_porte_aussi_le_reserve_et_le_disponible_quand_il_y_en_a():
    verdict = reapprovisionnement.evaluer("gouttiere-5po", Decimal("400"), ARTICLES, reserve=Decimal("100"))
    assert verdict == {"materiau_id": "gouttiere-5po", "statut": "stock_suffisant", "stock_theorique": "400",
                       "stock_reserve": "100", "stock_disponible": "300"}


def test_un_en_main_negatif_reste_signale_sans_quantite_meme_avec_du_reserve():
    verdict = reapprovisionnement.evaluer("gouttiere-5po", Decimal("-4"), ARTICLES, reserve=Decimal("10"))
    assert verdict["statut"] == "stock_bas" and verdict["stock_negatif"] is True
    assert verdict["quantite_a_commander"] is None


def test_un_article_sans_seuil_n_est_jamais_evalue_meme_avec_du_reserve():
    verdict = reapprovisionnement.evaluer("autre-article", Decimal("1"), ARTICLES, reserve=Decimal("1"))
    assert verdict == {"materiau_id": "autre-article", "statut": "seuil_absent"}


def test_le_constat_ne_porte_le_reserve_que_quand_il_y_en_a():
    sans = reapprovisionnement.evaluer("gouttiere-5po", Decimal("100"), ARTICLES)
    avec = reapprovisionnement.evaluer("gouttiere-5po", Decimal("100"), ARTICLES, reserve=Decimal("30"))
    constat_sans = reapprovisionnement.construire_constat(
        sans, evenement_declencheur="WCT-1", horodatage="h", chantier_id="CH", unite="pi")
    constat_avec = reapprovisionnement.construire_constat(
        avec, evenement_declencheur="WCT-1", horodatage="h", chantier_id="CH", unite="pi")
    assert "stock_reserve" not in constat_sans and "stock_disponible" not in constat_sans
    assert (constat_avec["stock_reserve"], constat_avec["stock_disponible"]) == ("30", "70")
    assert constat_avec["quantite_a_commander"] == "230"


def _constat(materiau_id="gouttiere-5po"):
    return {"type_entree": "besoin_commande", "constat_id": f"besoin_commande:{materiau_id}:WCT-1",
            "materiau_id": materiau_id, "evenement_declencheur": "WCT-1", "chantier_id": "CH-FICT-1", "unite": "pi",
            "horodatage": "2026-10-07T12:00:00+00:00"}


def test_les_attentes_de_l_admin_partent_du_disponible_quand_du_stock_est_reserve():
    mouvements = [_mouvement("gouttiere-5po", 200.0)]

    sans = reapprovisionnement.attentes([_constat()], mouvements, ARTICLES)
    avec = reapprovisionnement.attentes(
        [_constat()], mouvements, ARTICLES, reserves={"gouttiere-5po": Decimal("100")})

    assert sans == [], "200 en main, seuil 150"
    (attente,) = avec
    assert attente["type"] == "besoin_commande"
    assert "200.0 pi en main dont 100 pi réservé(s) pour des chantiers, 100.0 pi disponible(s)" in attente["resume"]
    assert "200.0 pi pour atteindre 300 pi" in attente["resume"]


def test_les_attentes_retranchent_ce_qui_est_hors_main():
    mouvements = [_mouvement("gouttiere-5po", 200.0)]
    (attente,) = reapprovisionnement.attentes(
        [_constat()], mouvements, ARTICLES, hors_main={"gouttiere-5po": Decimal("80")})
    assert "120.0 pi en main, sous le seuil" in attente["resume"]
    assert "réservé" not in attente["resume"]


def test_un_reserve_nul_est_traite_comme_une_absence_de_reservation():
    mouvements = [_mouvement("gouttiere-5po", 100.0)]
    a = reapprovisionnement.attentes([_constat()], mouvements, ARTICLES, reserves={"gouttiere-5po": Decimal(0)})
    b = reapprovisionnement.attentes([_constat()], mouvements, ARTICLES)
    assert a == b
