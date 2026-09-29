"""Règle de stock bas de M6 (M6.15, PLAN T1.5-d) : module pur `reapprovisionnement.py` et
`stock.deriver_stock_articles`. Aucune base : ce fichier prouve la RÈGLE (seuil strict, quantité cible,
seuil non configuré, stock négatif, idempotence du constat, état courant des attentes) ; la chaîne réelle
(déclaration, registre durable, bus, file de l'admin) est prouvée par `test_stock_bas_cascade.py`.

Fixtures fictives : les identifiants portent « fictif ».
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from m6_material_control import reapprovisionnement as rea
from m6_material_control import stock

_SRC = Path(__file__).resolve().parents[1] / "src" / "m6_material_control"

GOUTTIERE = "gouttiere-alu-5po-fictif"
VIS = "vis-inox-fictif"
ARTICLES = {
    GOUTTIERE: {"seuil_reapprovisionnement": 150, "quantite_cible": 300},
    VIS: {"seuil_reapprovisionnement": 40.5, "quantite_cible": 100},
}


def _mouvement(type_mouvement, materiau_id, quantite, chantier_id="CH-1-fictif"):
    return {
        "type_mouvement": type_mouvement, "chantier_id": chantier_id, "materiau_id": materiau_id,
        "quantite": quantite, "cout_unitaire": 8.0,
    }


# -- stock de l'article, tous lieux confondus -----------------------------------------------------------
def test_stock_article_somme_tous_les_lieux_et_les_types_du_theorique():
    mouvements = [
        _mouvement("RECEPTION", GOUTTIERE, 200.0, "CH-1-fictif"),
        _mouvement("CONSOMMATION", GOUTTIERE, -42.0, "CH-1-fictif"),
        _mouvement("RECEPTION", GOUTTIERE, 50.0, "CH-2-fictif"),
        _mouvement("RETOUR", GOUTTIERE, 2.0, "CH-1-fictif"),
        _mouvement("PERTE", GOUTTIERE, -3.0, "CH-2-fictif"),
        _mouvement("BRIS", GOUTTIERE, -1.0, "CH-2-fictif"),
        _mouvement("RECEPTION", VIS, 10.0),
    ]

    assert stock.deriver_stock_articles([GOUTTIERE, VIS], mouvements) == {
        GOUTTIERE: Decimal("206.0"), VIS: Decimal("10.0")}


def test_stock_article_exclut_la_variance_d_inventaire_et_les_autres_articles():
    mouvements = [
        _mouvement("RECEPTION", GOUTTIERE, 100.0),
        _mouvement("VARIANCE_INVENTAIRE", GOUTTIERE, -30.0),  # un constat, pas une correction (DA-M6-09)
        _mouvement("RECEPTION", "autre-fictif", 999.0),
    ]

    assert stock.deriver_stock_articles([GOUTTIERE], mouvements) == {GOUTTIERE: Decimal("100.0")}


def test_stock_article_sans_mouvement_vaut_zero_et_la_somme_est_exacte():
    mouvements = [_mouvement("RECEPTION", VIS, 0.1), _mouvement("RECEPTION", VIS, 0.2)]

    stocks = stock.deriver_stock_articles([VIS, GOUTTIERE], mouvements)

    assert stocks[VIS] == Decimal("0.3")  # 0.1 + 0.2 en flottant vaut 0.30000000000000004
    assert stocks[GOUTTIERE] == Decimal(0)


# -- lecture des paramètres : jamais un seuil deviné ----------------------------------------------------
def test_parametres_valides_sont_lus_en_decimal_exact():
    parametres = rea.lire_parametres(ARTICLES, VIS)

    assert parametres == {"statut": "configure", "seuil": Decimal("40.5"), "quantite_cible": Decimal("100")}


def test_article_absent_de_la_configuration_est_seuil_absent():
    assert rea.lire_parametres(ARTICLES, "inconnu-fictif") == {"statut": "seuil_absent"}
    assert rea.lire_parametres({}, GOUTTIERE) == {"statut": "seuil_absent"}


def test_bloc_illisible_n_est_pas_un_bloc_vide():
    parametres = rea.lire_parametres(None, GOUTTIERE)

    assert parametres["statut"] == "configuration_invalide"
    assert parametres["code"] == "REJ-REAPPRO-CONFIGURATION-ILLISIBLE"


@pytest.mark.parametrize(("entree", "code"), [
    ({"seuil_reapprovisionnement": 150}, "REJ-REAPPRO-ARTICLE-INVALIDE"),  # cible absente
    ({"quantite_cible": 300}, "REJ-REAPPRO-ARTICLE-INVALIDE"),  # seuil absent
    ({"seuil_reapprovisionnement": 150, "quantite_cible": 300, "prix": 8}, "REJ-REAPPRO-ARTICLE-INVALIDE"),
    (["seuil", 150], "REJ-REAPPRO-ARTICLE-INVALIDE"),
    (None, "REJ-REAPPRO-ARTICLE-INVALIDE"),
    ({"seuil_reapprovisionnement": 0, "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": -5, "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": "150", "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": True, "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": float("nan"), "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": float("inf"), "quantite_cible": 300}, "REJ-REAPPRO-SEUIL-INVALIDE"),
    ({"seuil_reapprovisionnement": 150, "quantite_cible": 100}, "REJ-REAPPRO-CIBLE-INVALIDE"),  # cible < seuil
    ({"seuil_reapprovisionnement": 150, "quantite_cible": "300"}, "REJ-REAPPRO-CIBLE-INVALIDE"),
    ({"seuil_reapprovisionnement": 150, "quantite_cible": float("nan")}, "REJ-REAPPRO-CIBLE-INVALIDE"),
])
def test_parametres_invalides_sont_refuses_avec_un_code_jamais_repares(entree, code):
    parametres = rea.lire_parametres({GOUTTIERE: entree}, GOUTTIERE)

    assert parametres["statut"] == "configuration_invalide"
    assert parametres["code"] == code
    assert parametres["detail"]  # dit quoi renseigner


def test_un_article_invalide_ne_rend_pas_les_autres_inutilisables():
    articles = {**ARTICLES, "casse-fictif": {"seuil_reapprovisionnement": -1, "quantite_cible": 5}}

    assert rea.lire_parametres(articles, "casse-fictif")["statut"] == "configuration_invalide"
    assert rea.lire_parametres(articles, GOUTTIERE)["statut"] == "configure"


def test_cible_egale_au_seuil_est_acceptee():
    parametres = rea.lire_parametres({GOUTTIERE: {"seuil_reapprovisionnement": 50, "quantite_cible": 50}}, GOUTTIERE)

    assert parametres["statut"] == "configure"


# -- évaluation : seuil strict, quantité cible, stock négatif -------------------------------------------
def test_stock_sous_le_seuil_donne_un_besoin_de_commande_avec_la_quantite_cible_moins_le_stock():
    verdict = rea.evaluer(GOUTTIERE, Decimal("144.0"), ARTICLES)

    assert verdict == {
        "materiau_id": GOUTTIERE, "statut": "stock_bas", "stock_theorique": "144.0",
        "seuil_reapprovisionnement": "150", "quantite_cible": "300", "quantite_a_commander": "156.0",
        "stock_negatif": False,
    }


def test_stock_egal_au_seuil_n_est_pas_bas():
    verdict = rea.evaluer(GOUTTIERE, Decimal("150"), ARTICLES)

    assert verdict["statut"] == "stock_suffisant"


def test_stock_au_dessus_du_seuil_est_suffisant():
    assert rea.evaluer(GOUTTIERE, Decimal("158.0"), ARTICLES)["statut"] == "stock_suffisant"


def test_stock_juste_sous_le_seuil_decimal_est_bas_sans_bruit_de_flottant():
    verdict = rea.evaluer(VIS, Decimal("40.4"), ARTICLES)

    assert verdict["statut"] == "stock_bas"
    assert verdict["quantite_a_commander"] == "59.6"


def test_stock_negatif_est_signale_sans_quantite_a_commander():
    verdict = rea.evaluer(GOUTTIERE, Decimal("-16.0"), ARTICLES)

    assert verdict["statut"] == "stock_bas"
    assert verdict["stock_negatif"] is True
    assert verdict["quantite_a_commander"] is None  # une erreur de livre ne se commande pas


def test_stock_nul_est_bas_et_se_commande_jusqu_a_la_cible():
    verdict = rea.evaluer(GOUTTIERE, Decimal(0), ARTICLES)

    assert (verdict["statut"], verdict["stock_negatif"], verdict["quantite_a_commander"]) == ("stock_bas", False, "300")


def test_article_sans_parametres_n_est_jamais_evalue_avec_un_seuil():
    verdict = rea.evaluer("inconnu-fictif", Decimal(0), ARTICLES)

    assert verdict == {"materiau_id": "inconnu-fictif", "statut": "seuil_absent"}
    assert "seuil_reapprovisionnement" not in verdict and "quantite_a_commander" not in verdict


# -- constats : ce qui s'écrit au registre --------------------------------------------------------------
def _constat(verdict, evenement="wct-1", **plus):
    base = {"evenement_declencheur": evenement, "horodatage": "2026-09-15T12:00:00+00:00",
            "chantier_id": "CH-1-fictif", "unite": "pi"}
    return rea.construire_constat(verdict, **{**base, **plus})


def test_stock_suffisant_ne_produit_aucun_constat():
    assert _constat(rea.evaluer(GOUTTIERE, Decimal("158.0"), ARTICLES)) is None


def test_constat_besoin_de_commande_fige_les_nombres_de_l_instant():
    constat = _constat(rea.evaluer(GOUTTIERE, Decimal("144.0"), ARTICLES))

    assert constat == {
        "type_entree": "besoin_commande", "constat_id": f"besoin_commande:{GOUTTIERE}:wct-1",
        "materiau_id": GOUTTIERE, "evenement_declencheur": "wct-1", "chantier_id": "CH-1-fictif", "unite": "pi",
        "horodatage": "2026-09-15T12:00:00+00:00", "stock_theorique": "144.0",
        "seuil_reapprovisionnement": "150", "quantite_cible": "300", "quantite_a_commander": "156.0",
        "stock_negatif": False,
    }


def test_constat_seuil_a_configurer_dit_pourquoi():
    absent = _constat(rea.evaluer("inconnu-fictif", Decimal(5), ARTICLES))
    invalide = _constat(rea.evaluer(GOUTTIERE, Decimal(5), {GOUTTIERE: {"seuil_reapprovisionnement": 0,
                                                                        "quantite_cible": 5}}))

    assert absent["type_entree"] == "seuil_a_configurer" and absent["motif"] == "seuil_absent"
    assert absent["code"] is None and absent["constat_id"] == "seuil_a_configurer:inconnu-fictif:wct-1"
    assert invalide["motif"] == "configuration_invalide" and invalide["code"] == "REJ-REAPPRO-SEUIL-INVALIDE"
    assert "seuil_reapprovisionnement" not in invalide  # jamais un seuil recopié d'une configuration refusée


def test_constat_est_idempotent_par_article_et_evenement_declencheur():
    constat = _constat(rea.evaluer(GOUTTIERE, Decimal("144.0"), ARTICLES))
    autre_evenement = _constat(rea.evaluer(GOUTTIERE, Decimal("100.0"), ARTICLES), evenement="wct-2")
    autre_article = _constat(rea.evaluer(VIS, Decimal("1"), ARTICLES))

    assert rea.constat_deja_range(constat, [constat]) is True
    assert rea.constat_deja_range(constat, [autre_evenement, autre_article]) is False
    assert rea.constat_deja_range(constat, []) is False


def test_les_constats_ne_portent_ni_prix_ni_cout_ni_montant():
    constat = _constat(rea.evaluer(GOUTTIERE, Decimal("144.0"), ARTICLES))

    assert not [cle for cle in constat if any(mot in cle for mot in ("prix", "cout", "montant", "marge"))]


# -- attentes : l'état d'AUJOURD'HUI --------------------------------------------------------------------
def _constats_bas(*evenements, materiau=GOUTTIERE, stock_avant="144.0"):
    return [
        _constat(rea.evaluer(materiau, Decimal(stock_avant), ARTICLES), evenement=evenement)
        for evenement in evenements
    ]


def test_sans_constat_aucune_attente():
    assert rea.attentes([], [_mouvement("RECEPTION", GOUTTIERE, 1.0)], ARTICLES) == []


def test_besoin_de_commande_attente_a_la_forme_commune_avec_les_nombres_d_aujourd_hui():
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 200.0), _mouvement("CONSOMMATION", GOUTTIERE, -56.0)]

    (attente,) = rea.attentes(_constats_bas("wct-b"), mouvements, ARTICLES)

    assert set(attente) == {"type", "id", "resume", "niveau", "depuis", "action_proposee"}
    assert attente["type"] == "besoin_commande"
    assert attente["id"] == f"besoin_commande:{GOUTTIERE}"
    assert attente["depuis"] == "2026-09-15T12:00:00+00:00" and attente["niveau"] == "N2"
    assert attente["resume"] == (
        f"Stock bas : {GOUTTIERE} — 144.0 pi en main, sous le seuil de 150 pi ; besoin de commande : "
        "156.0 pi pour atteindre 300 pi (chantier CH-1-fictif)")
    assert "jamais seul" in attente["action_proposee"] and len(attente["action_proposee"]) <= 160


def test_le_besoin_utilise_le_stock_d_aujourd_hui_pas_celui_du_constat():
    constats = _constats_bas("wct-b")  # constaté à 144
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 200.0), _mouvement("CONSOMMATION", GOUTTIERE, -100.0)]

    (attente,) = rea.attentes(constats, mouvements, ARTICLES)

    assert "100.0 pi en main" in attente["resume"] and "besoin de commande : 200.0 pi" in attente["resume"]


def test_une_reception_qui_reconstitue_le_stock_fait_disparaitre_le_besoin():
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 200.0), _mouvement("CONSOMMATION", GOUTTIERE, -56.0)]
    assert len(rea.attentes(_constats_bas("wct-b"), mouvements, ARTICLES)) == 1

    mouvements.append(_mouvement("RECEPTION", GOUTTIERE, 156.0, "DEPOT-fictif"))  # 300 en main

    assert rea.attentes(_constats_bas("wct-b"), mouvements, ARTICLES) == []


def test_un_besoin_par_article_meme_constate_a_plusieurs_evenements():
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 144.0)]
    jours = ("2026-09-15T12:00:00+00:00", "2026-09-16T12:00:00+00:00", "2026-09-17T12:00:00+00:00")
    constats = [
        _constat(rea.evaluer(GOUTTIERE, Decimal("144.0"), ARTICLES), evenement=f"wct-{i}", horodatage=jour)
        for i, jour in enumerate(jours)
    ]

    (attente,) = rea.attentes(constats, mouvements, ARTICLES)  # un article, une attente : pas trois lignes

    assert attente["id"] == f"besoin_commande:{GOUTTIERE}"  # stable d'un chantier à l'autre
    assert attente["depuis"] == "2026-09-17T12:00:00+00:00"  # le dernier constat


def test_stock_negatif_d_aujourd_hui_est_signale_sans_quantite():
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 40.0), _mouvement("CONSOMMATION", GOUTTIERE, -56.0)]

    (attente,) = rea.attentes(_constats_bas("wct-b"), mouvements, ARTICLES)

    assert "stock théorique négatif (-16.0 pi)" in attente["resume"]
    assert "à vérifier avant de commander" in attente["resume"] and "besoin de commande :" not in attente["resume"]


def test_articles_sans_parametres_forment_une_seule_attente_a_configurer():
    verdicts = [rea.evaluer(nom, Decimal(0), {}) for nom in ("a-fictif", "b-fictif")]
    constats = [
        _constat(verdicts[0], evenement="wct-2", horodatage="2026-09-16T12:00:00+00:00"),
        _constat(verdicts[1], evenement="wct-1", horodatage="2026-09-15T12:00:00+00:00"),
    ]

    (attente,) = rea.attentes(constats, [], {})

    assert attente["type"] == "seuil_a_configurer" and attente["id"] == "seuils-reapprovisionnement"
    assert attente["resume"] == (
        "Seuil de réapprovisionnement non configuré : a-fictif, b-fictif. Le stock bas de ces articles "
        "n'est pas évalué.")
    assert attente["depuis"] == "2026-09-15T12:00:00+00:00"  # la plus ancienne
    assert "configuration.reapprovisionnement.articles" in attente["action_proposee"]
    assert len(attente["action_proposee"]) <= 160 and len(attente["resume"]) <= 240


def test_un_seul_article_a_configurer_parle_au_singulier_et_les_invalides_sont_dits():
    articles = {GOUTTIERE: {"seuil_reapprovisionnement": 0, "quantite_cible": 5}}
    constats = [_constat(rea.evaluer(GOUTTIERE, Decimal(0), articles))]

    (attente,) = rea.attentes(constats, [], articles)

    assert f"{GOUTTIERE} (invalide)" in attente["resume"] and "cet article" in attente["resume"]


def test_beaucoup_d_articles_a_configurer_restent_lisibles_dans_le_resume():
    noms = [f"article-{i}-fictif" for i in range(9)]
    constats = [_constat(rea.evaluer(nom, Decimal(0), {}), evenement=f"wct-{i}") for i, nom in enumerate(noms)]

    (attente,) = rea.attentes(constats, [], {})

    assert "article-0-fictif, article-1-fictif, article-2-fictif, article-3-fictif et 5 autre(s)" in attente["resume"]
    assert len(attente["resume"]) <= 240


def test_un_article_configure_depuis_et_au_dessus_de_son_seuil_ne_signale_plus_rien():
    constats = [_constat(rea.evaluer(GOUTTIERE, Decimal(0), {}))]  # constaté « seuil absent »
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 400.0)]

    assert rea.attentes(constats, mouvements, ARTICLES) == []


def test_un_article_constate_sans_seuil_puis_configure_et_bas_devient_un_besoin():
    constats = [_constat(rea.evaluer(GOUTTIERE, Decimal(0), {}), evenement="wct-1")]
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 90.0)]

    (attente,) = rea.attentes(constats, mouvements, ARTICLES)

    assert attente["type"] == "besoin_commande" and attente["id"] == f"besoin_commande:{GOUTTIERE}"
    assert "90.0 pi en main" in attente["resume"]


def test_une_configuration_qui_devient_invalide_renvoie_l_article_a_configurer():
    constats = _constats_bas("wct-b")

    (attente,) = rea.attentes(constats, [_mouvement("RECEPTION", GOUTTIERE, 10.0)], None)

    assert attente["type"] == "seuil_a_configurer" and f"{GOUTTIERE} (invalide)" in attente["resume"]


def test_besoins_et_configurations_a_faire_se_rendent_ensemble():
    constats = [*_constats_bas("wct-b"), _constat(rea.evaluer("inconnu-fictif", Decimal(0), ARTICLES))]
    mouvements = [_mouvement("RECEPTION", GOUTTIERE, 144.0)]

    attentes = rea.attentes(constats, mouvements, ARTICLES)

    assert [a["type"] for a in attentes] == ["besoin_commande", "seuil_a_configurer"]


def test_un_horodatage_illisible_ne_casse_pas_le_tri_de_la_file():
    constat = _constat(rea.evaluer(GOUTTIERE, Decimal("144.0"), ARTICLES), horodatage=None)

    (attente,) = rea.attentes([constat], [_mouvement("RECEPTION", GOUTTIERE, 144.0)], ARTICLES)

    assert attente["depuis"] == ""  # une chaîne, comparable aux autres `depuis` ; jamais une date inventée


# -- frontières : constater n'est jamais commander ------------------------------------------------------
def _importations(module: str) -> set[str]:
    arbre = ast.parse((_SRC / f"{module}.py").read_text(encoding="utf-8"))
    noms: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            noms.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom):
            noms.add(("." * noeud.level) + (noeud.module or ""))
            noms.update(alias.name for alias in noeud.names if noeud.level)
    return noms


def test_reapprovisionnement_est_pur_et_n_atteint_ni_po_ni_paiement_ni_fournisseur():
    importe = _importations("reapprovisionnement")

    assert "opsys" not in importe
    for interdit in ("bons_commande", "fournisseurs", "livre_prix", "materiel", "registre", "reorder"):
        assert interdit not in importe, interdit


def test_reapprovisionnement_n_appelle_ni_creation_de_po_ni_horloge_ni_alea():
    arbre = ast.parse((_SRC / "reapprovisionnement.py").read_text(encoding="utf-8"))
    appels = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            if isinstance(noeud.func, ast.Name):
                appels.add(noeud.func.id)
            elif isinstance(noeud.func, ast.Attribute):
                appels.add(noeud.func.attr)

    for mot in ("creer", "brouillon", "approuver", "envoyer", "payer", "paiement", "now", "today", "uuid", "random"):
        assert not [nom for nom in appels if mot in nom.lower()], mot
