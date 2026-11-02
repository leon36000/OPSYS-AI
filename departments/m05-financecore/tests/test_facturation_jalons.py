"""Facturation par jalons (M5-FACT-1), module PUR : plan déterministe, somme au cent, arrondi, numérotation sans trou,
échéance, statut « en retard », factures de jalon, agrégat pour la rentabilité.

Aucun stockage, aucune horloge : les registres sont des `Registre` en mémoire. Tout est fictif (AGENTS.md). Les tests de
bout en bout sur le vrai socle sont dans `test_facturation_jalons_outils.py` et
`tests/test_facturation_jalons_bout_en_bout.py`.
"""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import facturation, facturation_jalons, taux_fiscaux, verdicts_facturation
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
H = "2026-11-02T10:00:00-05:00"
HUMAIN = {"par": "nathan", "role": "nathan_owner"}
TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"


def _taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(TAUX)
    assert erreurs == []
    return dictionnaire


def _devis(prix="10000.00", chantier=None):
    return {"devis_id": "D-1", "lead_id": "lead-1", "chantier_id": chantier, "prix_total": prix}


def _declencheur(i, n):
    return "acceptation" if i == 0 else "fin_travaux" if i == n - 1 else "chantier"


def _pct(*valeurs, declencheurs=None):
    n = len(valeurs)
    return [
        {
            "libelle": f"Jalon {i + 1}",
            "declencheur": declencheurs[min(i, len(declencheurs) - 1)] if declencheurs else _declencheur(i, n),
            "pourcentage": v,
        }
        for i, v in enumerate(valeurs)
    ]


def _montants(*valeurs):
    n = len(valeurs)
    return [
        {"libelle": f"Jalon {i + 1}", "declencheur": _declencheur(i, n), "montant_avant_taxes": v}
        for i, v in enumerate(valeurs)
    ]


def _plan(jalons, prix="10000.00", chantier="CH-1", delai=30, version=1):
    return facturation_jalons.construire_plan(
        _devis(prix),
        jalons,
        chantier_declare=chantier,
        client_id="client-1",
        version=version,
        delai_defaut=delai,
        humain=HUMAIN,
    )


def _plan_ok(jalons, **kw):
    plan, refus = _plan(jalons, **kw)
    assert refus is None, refus
    return plan


# ------------------------------------------------------------------------------------------------ somme et arrondi
def test_trois_jalons_en_pourcentage_totalisent_le_prix_au_cent():
    plan = _plan_ok(_pct("30", "40", "30"))
    assert [j["montant_avant_taxes"] for j in plan["jalons"]] == ["3000.00", "4000.00", "3000.00"]
    assert plan["mode"] == "pourcentage" and plan["total_avant_taxes"] == "10000.00"
    assert plan["jalons"][0]["jalon_id"] == f"{plan['plan_id']}-J1"
    assert D(plan["jalons"][2]["ecart_arrondi_absorbe"]) == 0


def test_le_dernier_jalon_est_le_solde_et_absorbe_l_arrondi():
    plan = _plan_ok(_pct("33.33", "33.33", "33.34"), prix="1000.01")
    montants = [D(j["montant_avant_taxes"]) for j in plan["jalons"]]
    assert montants[0] == (D("1000.01") * D("33.33") / 100).quantize(
        D("0.01")
    )  # 333.33 (arrondi au demi-cent supérieur)
    assert montants[1] == montants[0]
    assert sum(montants) == D("1000.01")
    assert montants[2] == D("1000.01") - montants[0] - montants[1]
    assert D(plan["jalons"][2]["ecart_arrondi_absorbe"]) == montants[2] - D("1000.01") * D("33.34") / 100


def test_arrondi_demi_cent_vers_le_haut_et_non_vers_le_banquier():
    # 0.5 % de 1.01 = 0.00505 -> 0.01 (ROUND_HALF_UP) ; ROUND_HALF_EVEN donnerait aussi 0.01 ; 2.5 % de 0.10 = 0.0025
    # -> 0.00
    # (sous le demi-cent) : on choisit un cas où seul HALF_UP monte : 12.5 % de 0.04 = 0.005 -> 0.01 (HALF_EVEN : 0.00).
    plan = _plan_ok(_pct("12.5", "87.5"), prix="0.04")
    assert [j["montant_avant_taxes"] for j in plan["jalons"]] == ["0.01", "0.03"]


@pytest.mark.parametrize("graine", range(40))
def test_la_somme_des_jalons_tombe_toujours_juste_pour_des_repartitions_quelconques(graine):
    hasard = random.Random(graine)
    prix = D(hasard.randint(1_00, 99_999_999)) / 100
    morceaux = hasard.randint(2, 6)
    coupes = sorted(hasard.sample(range(1, 10000), morceaux - 1))
    parts = [b - a for a, b in zip([0, *coupes], [*coupes, 10000], strict=True)]
    pourcentages = [format(D(p) / 100, "f") for p in parts]
    assert sum(D(p) for p in pourcentages) == 100
    plan, refus = _plan(_pct(*pourcentages), prix=format(prix, "f"))
    if refus is not None:
        assert refus["code"] == "REJ-PLAN-JALON-NUL"  # un jalon de moins d'un cent est refusé, jamais arrondi à zéro
        return
    assert sum(D(j["montant_avant_taxes"]) for j in plan["jalons"]) == prix


def test_montants_declares_qui_tombent_juste_sont_acceptes():
    plan = _plan_ok(_montants("2500.00", "5000.00", "2500.00"))
    assert plan["mode"] == "montant" and sum(D(j["montant_avant_taxes"]) for j in plan["jalons"]) == D("10000.00")
    assert all(j["pourcentage"] is None for j in plan["jalons"])


@pytest.mark.parametrize("derniere,ecart", [("2499.99", "-0.01"), ("2500.01", "0.01"), ("0.01", "-2499.99")])
def test_une_somme_de_montants_qui_ne_tombe_pas_juste_est_refusee_avec_l_ecart(derniere, ecart):
    plan, refus = _plan(_montants("2500.00", "5000.00", derniere))
    assert plan is None and refus["code"] == "REJ-PLAN-SOMME-INCORRECTE"
    assert f"écart {ecart} $" in refus["detail"] and "10000.00" in refus["detail"]


@pytest.mark.parametrize("pourcentages", [("30", "40", "29.99"), ("30", "40", "30.01"), ("50", "50.0001")])
def test_des_pourcentages_qui_ne_totalisent_pas_100_sont_refuses(pourcentages):
    plan, refus = _plan(_pct(*pourcentages))
    assert plan is None and refus["code"] == "REJ-PLAN-SOMME-POURCENTAGES"


def test_un_jalon_qui_vaudrait_moins_d_un_cent_est_refuse_dans_les_deux_modes():
    _, refus = _plan(_pct("99.99", "0.01"), prix="1.00")
    assert refus["code"] == "REJ-PLAN-JALON-NUL"
    _, refus = _plan(_montants("1.00", "0.00"), prix="1.00")
    assert refus["code"] == "REJ-PLAN-JALON-NUL"


def test_les_montants_ne_se_melangent_pas_aux_pourcentages_et_un_jalon_declare_une_seule_valeur():
    mixte = [_pct("50")[0], {"libelle": "B", "declencheur": "chantier", "montant_avant_taxes": "5000.00"}]
    assert _plan(mixte)[1]["code"] == "REJ-PLAN-MODE-MIXTE"
    deux = [
        {"libelle": "A", "declencheur": "acceptation", "pourcentage": "50", "montant_avant_taxes": "5000.00"},
        _pct("50")[0],
    ]
    assert _plan(deux)[1]["code"] == "REJ-PLAN-JALON-MONTANT-AMBIGU"
    aucun = [{"libelle": "A", "declencheur": "acceptation"}, _pct("100")[0]]
    assert _plan(aucun)[1]["code"] == "REJ-PLAN-JALON-MONTANT-AMBIGU"


@pytest.mark.parametrize("valeur", [30, 30.0, True, "abc", "NaN", "Infinity", "-5", "0", "100.01", "30.00001", ""])
def test_un_pourcentage_est_un_texte_decimal_borne(valeur):
    plan, refus = _plan(_pct(valeur, "70"))
    assert plan is None and refus["code"] in ("REJ-PLAN-ENTREE-INVALIDE", "REJ-PLAN-SOMME-POURCENTAGES")


@pytest.mark.parametrize("valeur", [2500, 2500.0, "1E+3", "2500.001", "-1.00", "NaN", "9999999999999.00"])
def test_un_montant_declare_est_un_texte_decimal_au_cent(valeur):
    plan, refus = _plan(_montants(valeur, "7500.00"))
    assert plan is None and refus["code"] in (
        "REJ-PLAN-ENTREE-INVALIDE",
        "REJ-PLAN-JALON-NUL",
        "REJ-PLAN-SOMME-INCORRECTE",
    )


# ------------------------------------------------------------------------------------- structure et déclarations
def test_le_nombre_et_l_ordre_des_jalons_sont_bornes():
    assert _plan(_pct("100"))[1]["code"] == "REJ-PLAN-JALONS-INVALIDES"
    assert _plan(_pct(*["1"] * 13))[1]["code"] == "REJ-PLAN-JALONS-INVALIDES"
    assert _plan("pas une liste")[1]["code"] == "REJ-PLAN-JALONS-INVALIDES"
    hors_ordre = _pct("50", "50", declencheurs=("chantier", "acceptation"))
    assert _plan(hors_ordre)[1]["code"] == "REJ-PLAN-JALONS-INVALIDES"
    deux_soldes = _pct("30", "30", "40", declencheurs=("acceptation", "fin_travaux", "fin_travaux"))
    assert _plan(deux_soldes)[1]["code"] == "REJ-PLAN-JALONS-INVALIDES"
    inconnu = [{**_pct("50")[0], "extra": 1}, _pct("50")[0]]
    assert _plan(inconnu)[1]["code"] == "REJ-PLAN-JALONS-INVALIDES"
    assert len(_plan_ok(_pct(*["8.3333"] * 11, "8.3337"))["jalons"]) == 12


@pytest.mark.parametrize("libelle", ["", "   ", "x" * 81, "ligne\nsuivante", "tab\tulé", "nul\x00", 5, None])
def test_le_libelle_est_une_ligne_de_texte_sans_controle(libelle):
    jalons = _pct("50", "50")
    jalons[0]["libelle"] = libelle
    assert _plan(jalons)[1]["code"] == "REJ-PLAN-ENTREE-INVALIDE"


def test_un_delai_non_declare_bloque_et_dit_quoi_declarer():
    plan, refus = _plan(_pct("50", "50"), delai=None)
    assert plan is None and refus["code"] == "REJ-PLAN-DELAI-A-DECLARER"
    assert "configuration.facturation.conditions_paiement.delai_jours" in refus["detail"]
    assert "jalon(s) [1, 2]" in refus["detail"]
    un_seul = _pct("50", "50")
    un_seul[0]["delai_paiement_jours"] = 0
    assert _plan(un_seul, delai=None)[1]["detail"].startswith("jalon(s) [2]")


def test_le_delai_du_jalon_prime_sur_les_conditions_declarees_et_la_source_est_dite():
    jalons = _pct("30", "70")
    jalons[0]["delai_paiement_jours"] = 0
    plan = _plan_ok(jalons, delai=45)
    assert [(j["delai_paiement_jours"], j["delai_source"]) for j in plan["jalons"]] == [
        (0, "jalon"),
        (45, "conditions_paiement"),
    ]
    mauvais = _pct("30", "70")
    mauvais[0]["delai_paiement_jours"] = 366
    assert _plan(mauvais)[1]["code"] == "REJ-PLAN-ENTREE-INVALIDE"
    mauvais[0]["delai_paiement_jours"] = True
    assert _plan(mauvais)[1]["code"] == "REJ-PLAN-ENTREE-INVALIDE"


def test_le_chantier_vient_du_devis_ou_se_declare_jamais_inventé():
    assert _plan(_pct("50", "50"), chantier=None)[1]["code"] == "REJ-PLAN-CHANTIER-A-DECLARER"
    assert _plan(_pct("50", "50"), chantier="  ")[1]["code"] == "REJ-PLAN-CHANTIER-A-DECLARER"
    assert _plan_ok(_pct("50", "50"), chantier="CH-9")["chantier_id"] == "CH-9"
    plan, refus = facturation_jalons.construire_plan(
        _devis(chantier="CH-DEVIS"),
        _pct("50", "50"),
        chantier_declare=None,
        client_id="c",
        version=1,
        delai_defaut=30,
        humain=HUMAIN,
    )
    assert refus is None and plan["chantier_id"] == "CH-DEVIS"
    _, refus = facturation_jalons.construire_plan(
        _devis(chantier="CH-DEVIS"),
        _pct("50", "50"),
        chantier_declare="CH-AUTRE",
        client_id="c",
        version=1,
        delai_defaut=30,
        humain=HUMAIN,
    )
    assert refus["code"] == "REJ-PLAN-CHANTIER-A-DECLARER"


@pytest.mark.parametrize("prix", ["0.00", "-5.00", "abc", None, 100, "1000.001"])
def test_un_devis_sans_prix_lisible_est_refuse(prix):
    _, refus = facturation_jalons.construire_plan(
        {**_devis(), "prix_total": prix},
        _pct("50", "50"),
        chantier_declare="CH",
        client_id="c",
        version=1,
        delai_defaut=30,
        humain=HUMAIN,
    )
    assert refus["code"] == "REJ-PLAN-ENTREE-INVALIDE"


def test_le_plan_est_deterministe_et_son_empreinte_detecte_une_alteration():
    a, b = _plan_ok(_pct("30", "40", "30")), _plan_ok(_pct("30", "40", "30"))
    assert a == b and a["plan_id"].startswith("pf-") and a["plan_id"].endswith("-v1")
    assert _plan_ok(_pct("30", "40", "30"), version=2)["plan_id"] != a["plan_id"]
    registre = registre_module.Registre()
    resultat, refus = facturation_jalons.ajouter_plan(registre, facturation_jalons.etat_plans([]), a, H)
    assert refus is None and resultat["statut"] == "ecrit"
    maillons = registre.lire()
    assert facturation_jalons.etat_plans(maillons)["anomalies"] == []
    maillons[0]["jalons"][0]["montant_avant_taxes"] = "1.00"
    assert "contenu altéré" in facturation_jalons.etat_plans(maillons)["anomalies"][0]
    assert (
        facturation_jalons.refus_anomalies(facturation_jalons.etat_plans(maillons))["code"]
        == "REJ-PLAN-CHAINE-INVALIDE"
    )


def test_declarer_deux_fois_le_meme_plan_ne_cree_rien_et_un_autre_plan_actif_est_refuse():
    registre = registre_module.Registre()
    plan = _plan_ok(_pct("30", "70"))
    premier, _ = facturation_jalons.ajouter_plan(registre, facturation_jalons.etat_plans(registre.lire()), plan, H)
    assert premier["statut"] == "ecrit"
    rejeu, refus = facturation_jalons.ajouter_plan(
        registre, facturation_jalons.etat_plans(registre.lire()), _plan_ok(_pct("30", "70"), version=2), H
    )
    assert refus is None and rejeu["statut"] == "deja" and registre.taille() == 1
    _, refus = facturation_jalons.ajouter_plan(
        registre, facturation_jalons.etat_plans(registre.lire()), _plan_ok(_pct("20", "80"), version=2), H
    )
    assert refus["code"] == "REJ-PLAN-DEJA-DECLARE" and registre.taille() == 1


def test_revoquer_un_plan_sans_facture_permet_d_en_declarer_un_autre_mais_pas_avec_une_facture():
    registre = registre_module.Registre()
    plan = _plan_ok(_pct("30", "70"))
    facturation_jalons.ajouter_plan(registre, facturation_jalons.etat_plans([]), plan, H)
    etat = facturation_jalons.etat_plans(registre.lire())
    _, refus = facturation_jalons.revoquer_plan(
        registre, etat, plan["plan_id"], "x", HUMAIN, [{"facture_id": "f", "plan_id": plan["plan_id"]}], H
    )
    assert refus["code"] == "REJ-PLAN-REVOCATION-IMPOSSIBLE"
    _, refus = facturation_jalons.revoquer_plan(registre, etat, plan["plan_id"], "   ", HUMAIN, [], H)
    assert refus["code"] == "REJ-PLAN-ENTREE-INVALIDE"
    _, refus = facturation_jalons.revoquer_plan(registre, etat, "pf-inconnu", "motif", HUMAIN, [], H)
    assert refus["code"] == "REJ-PLAN-INTROUVABLE"
    ok, refus = facturation_jalons.revoquer_plan(registre, etat, plan["plan_id"], "plan à refaire", HUMAIN, [], H)
    assert refus is None and ok["statut"] == "REVOQUE"
    etat = facturation_jalons.etat_plans(registre.lire())
    assert facturation_jalons.plan_actif_pour_devis(etat, "D-1") is None
    assert facturation_jalons.revoquer_plan(registre, etat, plan["plan_id"], "encore", HUMAIN, [], H)[1]["code"] == (
        "REJ-PLAN-DEJA-REVOQUE"
    )
    nouveau = _plan_ok(_pct("20", "80"), version=2)
    assert facturation_jalons.ajouter_plan(registre, etat, nouveau, H)[1] is None
    assert (
        facturation_jalons.plan_actif_pour_devis(facturation_jalons.etat_plans(registre.lire()), "D-1")["plan_id"]
        == nouveau["plan_id"]
    )


# ------------------------------------------------------------------------------------------------ configuration
@pytest.mark.parametrize(
    "brut",
    [
        None,
        {},
        {"delai_jours": -1},
        {"delai_jours": 366},
        {"delai_jours": "30"},
        {"delai_jours": True},
        {"delai_jours": 30, "autre": 1},
        "30",
    ],
)
def test_des_conditions_de_paiement_mal_declarees_disent_quoi_declarer(brut):
    conditions, refus = facturation_jalons.lire_conditions_paiement(brut)
    assert conditions is None and refus["code"] == "REJ-CONDITIONS-A-DECLARER"
    assert "delai_jours" in refus["detail"]


def test_des_conditions_valides_sont_lues_telles_quelles():
    assert facturation_jalons.lire_conditions_paiement({"delai_jours": 0}) == ({"delai_jours": 0}, None)
    assert facturation_jalons.lire_conditions_paiement({"delai_jours": 365}) == ({"delai_jours": 365}, None)


@pytest.mark.parametrize(
    "brut",
    [
        None,
        {},
        {"prefixe": "F-"},
        {"prefixe": "F-", "premier_numero": 0, "largeur": 5},
        {"prefixe": "F-", "premier_numero": 1, "largeur": 0},
        {"prefixe": "F-", "premier_numero": 1, "largeur": 13},
        {"prefixe": "trop-long-prefixe", "premier_numero": 1, "largeur": 5},
        {"prefixe": "F 1", "premier_numero": 1, "largeur": 5},
        {"prefixe": "F-", "premier_numero": "1", "largeur": 5},
        {"prefixe": "F-", "premier_numero": True, "largeur": 5},
        {"prefixe": "F-", "premier_numero": 1000000000, "largeur": 5},
        {"prefixe": 5, "premier_numero": 1, "largeur": 5},
        {"prefixe": "F-", "premier_numero": 1, "largeur": 5, "x": 1},
    ],
)
def test_une_numerotation_mal_declaree_dit_quoi_declarer_et_aucun_numero_n_est_suppose(brut):
    numerotation, refus = facturation_jalons.lire_numerotation(brut)
    assert numerotation is None and refus["code"] == "REJ-NUMEROTATION-A-DECLARER"
    assert "premier_numero" in refus["detail"] and "décision du propriétaire" in refus["detail"]


def test_une_numerotation_valide_est_lue():
    declaration = {"prefixe": "", "premier_numero": 1, "largeur": 1}
    assert facturation_jalons.lire_numerotation(declaration)[0] == declaration


# ------------------------------------------------------------------------------------------------ numérotation
NUM = {"prefixe": "F-", "premier_numero": 1000, "largeur": 6}


def _attribuer(registre, facture_id, numerotation=NUM):
    return facturation_jalons.attribuer_numero(registre, numerotation, facture_id, H)


def test_les_numeros_se_suivent_sans_trou_a_partir_du_premier_declare():
    registre = registre_module.Registre()
    numeros = []
    for i in range(5):
        resultat, refus = _attribuer(registre, f"f-{i}")
        assert refus is None and resultat["statut"] == "nouveau"
        numeros.append((resultat["numero"]["sequence"], resultat["numero"]["numero_facture"]))
    assert numeros == [(1000 + i, f"F-{1000 + i:06d}") for i in range(5)]
    verification = facturation_jalons.verifier_numerotation(registre.lire())
    assert verification == {
        "ok": True,
        "nombre": 5,
        "premier": 1000,
        "dernier": 1004,
        "trous": [],
        "doublons": [],
        "anomalies": [],
    }


def test_attribuer_deux_fois_au_meme_document_rend_le_meme_numero_sans_rien_ecrire():
    registre = registre_module.Registre()
    premier, _ = _attribuer(registre, "f-a")
    _attribuer(registre, "f-b")
    taille = registre.taille()
    rejeu, refus = _attribuer(registre, "f-a")
    assert (
        refus is None
        and rejeu["statut"] == "deja"
        and rejeu["numero"]["numero_facture"] == premier["numero"]["numero_facture"]
    )
    assert registre.taille() == taille


def test_le_premier_numero_ne_peut_plus_changer_une_fois_la_suite_commencee():
    registre = registre_module.Registre()
    _attribuer(registre, "f-a")
    _, refus = _attribuer(registre, "f-b", {**NUM, "premier_numero": 5000})
    assert refus["code"] == "REJ-NUMEROTATION-PREMIER-CHANGE" and registre.taille() == 1
    # le préfixe et la largeur, eux, peuvent évoluer (changement d'année) sans casser la suite
    resultat, refus = _attribuer(registre, "f-c", {**NUM, "prefixe": "G-", "largeur": 4})
    assert refus is None and resultat["numero"]["numero_facture"] == "G-1001"
    assert facturation_jalons.verifier_numerotation(registre.lire())["ok"] is True


def _entree(sequence, facture_id, premier=1000, numero=None):
    return {
        "type_entree": "numero_facture_attribue",
        "facture_id": facture_id,
        "sequence": sequence,
        "numero_facture": numero or f"F-{sequence:06d}",
        "prefixe": "F-",
        "largeur": 6,
        "premier_numero": premier,
        "horodatage": H,
    }


def test_un_trou_un_doublon_ou_une_alteration_sont_dits_et_bloquent_toute_attribution():
    avec_trou = registre_module.Registre()
    for e in (_entree(1000, "a"), _entree(1002, "c")):
        avec_trou.ajouter(e)
    verification = facturation_jalons.verifier_numerotation(avec_trou.lire())
    assert verification["ok"] is False and verification["trous"] == [1001]
    resultat, refus = _attribuer(avec_trou, "z")
    assert resultat is None and refus["code"] == "REJ-NUMEROTATION-CHAINE-INVALIDE" and avec_trou.taille() == 2

    doublon_numero = registre_module.Registre()
    for e in (_entree(1000, "a"), _entree(1000, "b")):
        doublon_numero.ajouter(e)
    assert "numéro 1000 écrit deux fois" in facturation_jalons.verifier_numerotation(doublon_numero.lire())["doublons"]

    doublon_facture = registre_module.Registre()
    for e in (_entree(1000, "a"), _entree(1001, "a")):
        doublon_facture.ajouter(e)
    assert (
        "facture a numérotée deux fois" in facturation_jalons.verifier_numerotation(doublon_facture.lire())["doublons"]
    )

    incoherent = registre_module.Registre()
    incoherent.ajouter(_entree(1000, "a", numero="F-999999"))
    assert facturation_jalons.verifier_numerotation(incoherent.lire())["ok"] is False

    desordre = registre_module.Registre()
    for e in (_entree(1000, "a"), _entree(1001, "b"), _entree(1000 - 1, "c")):
        desordre.ajouter(e)
    assert facturation_jalons.verifier_numerotation(desordre.lire())["ok"] is False

    premier_change = registre_module.Registre()
    for e in (_entree(1000, "a"), _entree(1001, "b", premier=7)):
        premier_change.ajouter(e)
    assert facturation_jalons.verifier_numerotation(premier_change.lire())["ok"] is False

    etranger = [{"type_entree": "mouvement_enregistre"}]
    assert facturation_jalons.verifier_numerotation(etranger)["ok"] is False


def test_la_suite_vide_est_ok_et_sans_premier():
    assert facturation_jalons.verifier_numerotation([]) == {
        "ok": True,
        "nombre": 0,
        "premier": None,
        "dernier": None,
        "trous": [],
        "doublons": [],
        "anomalies": [],
    }


# ------------------------------------------------------------------------------------------ échéance et retard
def test_l_echeance_est_le_jour_d_emission_plus_le_delai_declare():
    assert facturation.echeance_apres("2026-11-02T10:00:00-05:00", 30) == "2026-12-02"
    assert facturation.echeance_apres("2026-11-02T23:30:00-05:00", 0) == "2026-11-02"  # le jour LOCAL de la donnée
    assert facturation.echeance_apres("2026-12-15T10:00:00-05:00", 30) == "2027-01-14"
    assert facturation.echeance_apres("2026-02-27T10:00:00-05:00", 2) == "2026-03-01"
    assert facturation.echeance_apres("pas une date", 30) is None
    assert facturation.echeance_apres("2026-11-02T10:00:00-05:00", -1) is None
    assert facturation.echeance_apres("2026-11-02T10:00:00-05:00", True) is None


def _envoyee(echeance="2026-12-02", statut="ENVOYEE"):
    return {"facture_id": "f", "statut": statut, "echeance": echeance}


def test_en_retard_seulement_apres_l_echeance_jamais_le_jour_meme():
    assert facturation.statut_effectif(_envoyee(), date(2026, 12, 1))["statut_effectif"] == "ENVOYEE"
    veille = facturation.statut_effectif(_envoyee(), date(2026, 12, 2))
    assert veille == {
        "statut_effectif": "ENVOYEE",
        "echeance": "2026-12-02",
        "jours_de_retard": 0,
        "retard_calculable": True,
    }
    lendemain = facturation.statut_effectif(_envoyee(), date(2026, 12, 3))
    assert lendemain == {
        "statut_effectif": "EN_RETARD",
        "echeance": "2026-12-02",
        "jours_de_retard": 1,
        "retard_calculable": True,
    }
    assert facturation.statut_effectif(_envoyee(), date(2027, 3, 2))["jours_de_retard"] == 90


def test_payee_brouillon_et_annulee_ne_sont_jamais_en_retard_et_sans_echeance_le_retard_n_est_pas_calculable():
    for statut in ("PAYEE", "BROUILLON", "ANNULEE"):
        vue = facturation.statut_effectif(_envoyee(statut=statut), date(2030, 1, 1))
        assert vue["statut_effectif"] == statut and vue["jours_de_retard"] is None
    sans = facturation.statut_effectif(_envoyee(echeance=None), date(2030, 1, 1))
    assert sans["statut_effectif"] == "ENVOYEE" and sans["retard_calculable"] is False
    assert (
        facturation.statut_effectif(_envoyee(echeance="pas une date"), date(2030, 1, 1))["retard_calculable"] is False
    )


# --------------------------------------------------------------------------------------------- factures de jalon
def _registre_plan_et_factures(jalons=None, prix="10000.00"):
    plan = _plan_ok(jalons or _pct("30", "40", "30"), prix=prix)
    plans = registre_module.Registre()
    facturation_jalons.ajouter_plan(plans, facturation_jalons.etat_plans([]), plan, H)
    return facturation_jalons.etat_plans(plans.lire())["plans"][plan["plan_id"]], registre_module.Registre()


def _creer_jalon(plan, factures, rang, *, travaux=False):
    preparation, refus = facturation_jalons.preparer_facture_jalon(
        plan, rang, facturation.etats_des_factures(factures), travaux_termines=travaux
    )
    if refus is not None:
        return None, refus
    return facturation.creer_facture_brouillon(
        preparation["facture_id"],
        plan["chantier_id"],
        plan["devis_id"],
        plan["client_id"],
        preparation["lignes"],
        H,
        _taux(),
        factures,
        montant_avant_taxes_fourni=preparation["lignes"][0]["prix_unitaire"],
        rattachement_plan=preparation["rattachement"],
    )


def test_la_facture_d_un_jalon_porte_le_montant_du_plan_et_les_taxes_du_moteur_fiscal():
    plan, factures = _registre_plan_et_factures()
    facture, verdict = _creer_jalon(plan, factures, 1)
    assert verdict is None and facture["statut"] == "BROUILLON"
    assert facture["montant_avant_taxes"] == D("3000.00")
    assert [(t["id"], t["montant"]) for t in facture["taxes"]] == [
        ("tps_federale", D("150.00")),
        ("tvq_quebec", D("299.25")),
    ]
    assert facture["montant_apres_taxes"] == D("3449.25")
    assert (facture["plan_id"], facture["jalon_rang"], facture["jalons_total"]) == (plan["plan_id"], 1, 3)
    assert facture["delai_paiement_jours"] == 30 and facture["plan_total_avant_taxes"] == "10000.00"
    assert facture["lignes"][0]["reference_ligne_devis"] == plan["jalons"][0]["jalon_id"]


def test_les_jalons_se_facturent_dans_l_ordre():
    plan, factures = _registre_plan_et_factures()
    _, refus = _creer_jalon(plan, factures, 2)
    assert refus["code"] == "REJ-PLAN-JALON-HORS-ORDRE" and "[1]" in refus["detail"]
    assert _creer_jalon(plan, factures, 1)[1] is None
    _, refus = _creer_jalon(plan, factures, 3, travaux=True)
    assert refus["code"] == "REJ-PLAN-JALON-HORS-ORDRE" and "[2]" in refus["detail"]
    assert _creer_jalon(plan, factures, 2)[1] is None


def test_le_solde_de_fin_de_travaux_n_est_jamais_facture_d_avance():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    _creer_jalon(plan, factures, 2)
    _, refus = _creer_jalon(plan, factures, 3, travaux=False)
    assert refus["code"] == "REJ-PLAN-TRAVAUX-NON-TERMINES" and "m4.travaux_termines" in refus["detail"]
    facture, verdict = _creer_jalon(plan, factures, 3, travaux=True)
    assert verdict is None and facture["montant_avant_taxes"] == D("3000.00")


def test_rejouer_la_creation_du_meme_jalon_ne_cree_rien_de_plus():
    plan, factures = _registre_plan_et_factures()
    premiere, _ = _creer_jalon(plan, factures, 1)
    taille = factures.taille()
    rejeu, verdict = _creer_jalon(plan, factures, 1)
    assert verdict is None and rejeu == premiere and factures.taille() == taille


def test_un_jalon_deja_facture_sous_un_autre_identifiant_est_refuse():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    etats = facturation.etats_des_factures(factures)
    etats[0] = {**etats[0], "facture_id": "fac-autre"}
    _, refus = facturation_jalons.preparer_facture_jalon(plan, 1, etats, travaux_termines=False)
    assert refus["code"] == "REJ-PLAN-JALON-DEJA-FACTURE"
    # la fonction pure de facturation défend aussi : une seconde facture ACTIVE pour le même jalon
    _, verdict = facturation.creer_facture_brouillon(
        "fac-autre",
        plan["chantier_id"],
        plan["devis_id"],
        "client-1",
        [
            {
                "description": "x",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": "3000.00",
                "reference_ligne_devis": "r",
            }
        ],
        H,
        _taux(),
        factures,
        rattachement_plan={
            "plan_id": plan["plan_id"],
            "jalon_id": plan["jalons"][0]["jalon_id"],
            "jalon_rang": 1,
            "jalons_total": 3,
            "libelle_jalon": "Jalon 1",
            "plan_total_avant_taxes": "10000.00",
            "delai_paiement_jours": 30,
        },
    )
    assert verdict["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE" and "jalon 1" in verdict["detail"]


def test_le_total_facture_n_excede_jamais_le_prix_du_devis():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    etats = facturation.etats_des_factures(factures)
    # un registre dont les écritures excèdent déjà le contrat (altération hors outils) : le jalon suivant est refusé
    etats[0] = {**etats[0], "montant_avant_taxes": D("7000.01")}
    _, refus = facturation_jalons.preparer_facture_jalon(plan, 2, etats, travaux_termines=False)
    assert refus["code"] == "REJ-PLAN-DEPASSEMENT" and "10000.00" in refus["detail"]
    etats[0] = {**etats[0], "montant_avant_taxes": D("6000.00")}  # 6000 + 4000 = 10000 : exactement le prix, permis
    assert facturation_jalons.preparer_facture_jalon(plan, 2, etats, travaux_termines=False)[1] is None


def test_une_facture_annulee_ne_compte_ni_pour_l_ordre_ni_pour_le_total():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    etats = facturation.etats_des_factures(factures)
    etats[0] = {**etats[0], "statut": "ANNULEE"}
    _, refus = facturation_jalons.preparer_facture_jalon(plan, 2, etats, travaux_termines=False)
    assert refus["code"] == "REJ-PLAN-JALON-HORS-ORDRE"


def test_jalon_inconnu_et_facture_globale_existante():
    plan, factures = _registre_plan_et_factures()
    for rang in (0, 4, -1, "1", None, True, 1.0):
        _, refus = facturation_jalons.preparer_facture_jalon(plan, rang, [], travaux_termines=True)
        assert refus["code"] == "REJ-PLAN-JALON-INCONNU", rang
    globale = [
        {"facture_id": "fac-D-1", "devis_id": "D-1", "statut": "BROUILLON", "montant_avant_taxes": D("10000.00")}
    ]
    _, refus = facturation_jalons.preparer_facture_jalon(plan, 1, globale, travaux_termines=True)
    assert refus["code"] == "REJ-PLAN-DEVIS-DEJA-FACTURE"
    globale[0]["statut"] = "ANNULEE"
    assert facturation_jalons.preparer_facture_jalon(plan, 1, globale, travaux_termines=True)[1] is None


def test_une_facture_globale_est_refusee_quand_une_facture_de_jalon_est_active_et_inversement():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    ligne = [
        {
            "description": "x",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "10000.00",
            "reference_ligne_devis": "r",
        }
    ]
    _, verdict = facturation.creer_facture_brouillon("fac-D-1", "CH-1", "D-1", "client-1", ligne, H, _taux(), factures)
    assert verdict["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE"
    plan2, factures2 = _registre_plan_et_factures()
    facturation.creer_facture_brouillon("fac-D-1", "CH-1", "D-1", "client-1", ligne, H, _taux(), factures2)
    rattachement = {
        "plan_id": plan2["plan_id"],
        "jalon_id": "j",
        "jalon_rang": 1,
        "jalons_total": 3,
        "libelle_jalon": "x",
        "plan_total_avant_taxes": "10000.00",
        "delai_paiement_jours": 30,
    }
    _, verdict = facturation.creer_facture_brouillon(
        "fac-j1", "CH-1", "D-1", "client-1", ligne, H, _taux(), factures2, rattachement_plan=rattachement
    )
    assert verdict["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE" and "hors de ce plan" in verdict["detail"]


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("plan_id", ""),
        ("jalon_rang", 0),
        ("jalon_rang", 4),
        ("jalon_rang", "1"),
        ("jalons_total", True),
        ("delai_paiement_jours", -1),
        ("libelle_jalon", None),
        ("plan_total_avant_taxes", ""),
    ],
)
def test_un_rattachement_mal_forme_est_refuse_par_la_facturation(champ, valeur):
    rattachement = {
        "plan_id": "pf-x",
        "jalon_id": "j",
        "jalon_rang": 1,
        "jalons_total": 3,
        "libelle_jalon": "x",
        "plan_total_avant_taxes": "10000.00",
        "delai_paiement_jours": 30,
        champ: valeur,
    }
    ligne = [
        {
            "description": "x",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "10.00",
            "reference_ligne_devis": "r",
        }
    ]
    _, verdict = facturation.creer_facture_brouillon(
        "f", "CH", "D", "c", ligne, H, _taux(), registre_module.Registre(), rattachement_plan=rattachement
    )
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"
    _, verdict = facturation.creer_facture_brouillon(
        "f", "CH", "D", "c", ligne, H, _taux(), registre_module.Registre(), rattachement_plan={"plan_id": "pf-x"}
    )
    assert verdict["code"] == "REJ-FACTURE-LIGNE-INVALIDE"


# ---------------------------------------------------------------------------------- émission, agrégat, résumé
def test_l_emission_fixe_numero_et_echeance_dans_le_meme_maillon_que_le_statut():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    maillon, verdict = facturation.envoyer_facture(
        "fac-" + plan["plan_id"] + "-J1",
        H,
        factures,
        {"numero_facture": "F-001000", "sequence_facture": 1000, "echeance": "2026-12-02", "delai_paiement_jours": 30},
    )
    assert verdict is None
    assert (maillon["statut"], maillon["numero_facture"], maillon["echeance"]) == ("ENVOYEE", "F-001000", "2026-12-02")
    etat = facturation.etats_des_factures(factures)[0]
    assert etat["numero_facture"] == "F-001000" and etat["montant_avant_taxes"] == D("3000.00")  # la fusion garde tout
    _, verdict = facturation.envoyer_facture(
        "fac-" + plan["plan_id"] + "-J1", H, factures, {"numero_facture": "F-001001"}
    )
    assert verdict["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE"


def test_une_emission_aux_champs_inconnus_est_refusee_sans_rien_ecrire():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    taille = factures.taille()
    _, verdict = facturation.envoyer_facture("fac-" + plan["plan_id"] + "-J1", H, factures, {"statut": "PAYEE"})
    assert verdict["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE" and factures.taille() == taille


def test_sans_emission_le_maillon_d_envoi_est_celui_d_avant():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    maillon, _ = facturation.envoyer_facture("fac-" + plan["plan_id"] + "-J1", H, factures)
    assert set(maillon) == {
        "type_entree",
        "facture_id",
        "statut",
        "date_envoi",
        "horodatage",
        "ligne_id",
        "precedent_ligne_id",
    }


def test_l_agregat_pour_la_rentabilite_est_le_prix_du_contrat_et_definitif_seulement_si_tous_les_jalons_sont_emis():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    agregat = facturation.factures_actives_par_devis(factures)["D-1"]
    assert agregat["statut"] == "BROUILLON" and agregat["montant_avant_taxes"] == D("10000.00")
    assert (agregat["jalons_factures"], agregat["jalons_total"]) == (1, 3)
    for rang in (2, 3):
        _creer_jalon(plan, factures, rang, travaux=True)
    for rang in (1, 2):
        facturation.envoyer_facture(f"fac-{plan['plan_id']}-J{rang}", H, factures)
    assert facturation.factures_actives_par_devis(factures)["D-1"]["statut"] == "BROUILLON"  # le solde n'est pas émis
    facturation.envoyer_facture(f"fac-{plan['plan_id']}-J3", H, factures)
    agregat = facturation.factures_actives_par_devis(factures)["D-1"]
    assert agregat["statut"] == "ENVOYEE" and agregat["montant_avant_taxes"] == D("10000.00")
    assert agregat["facture_id"] == plan["plan_id"]


def test_le_resume_du_plan_dit_le_facture_le_solde_et_l_ecart_d_arrondi_des_taxes():
    plan, factures = _registre_plan_et_factures()
    _creer_jalon(plan, factures, 1)
    facturation.envoyer_facture(
        f"fac-{plan['plan_id']}-J1",
        H,
        factures,
        {"numero_facture": "F-001000", "sequence_facture": 1000, "echeance": "2026-12-02", "delai_paiement_jours": 30},
    )
    resume, refus = facturation_jalons.resume_plan(
        plan, facturation.etats_des_factures(factures), _taux(), date(2026, 12, 3)
    )
    assert refus is None
    assert resume["facture_avant_taxes"] == "3000.00" and resume["solde_a_facturer_avant_taxes"] == "7000.00"
    premier, deuxieme, troisieme = resume["jalons"]
    assert (premier["etat"], premier["numero_facture"], premier["statut_effectif"], premier["jours_de_retard"]) == (
        "ENVOYEE",
        "F-001000",
        "EN_RETARD",
        1,
    )
    # 4000 x 5 % = 200.00 ; 4000 x 9,975 % = 399.00 (calcul indépendant du moteur)
    assert (deuxieme["etat"], deuxieme["taxes"], deuxieme["montant_apres_taxes"]) == ("A_FACTURER", "599.00", "4599.00")
    assert troisieme["facture_id"] is None
    assert resume["taxes_des_jalons"] == "1497.50" == resume["taxes_sur_le_total"]
    assert resume["ecart_arrondi_taxes"] == "0.00"
    assert "CPA" in resume["note_taxes"]


def test_l_ecart_d_arrondi_des_taxes_par_facture_est_rendu_tel_quel():
    # 3 jalons de 0.10 $ : par facture TPS 0.005 -> 0.01 et TVQ 0.009975 -> 0.01 (0.02 chacune, 0.06 en tout) ;
    # sur 0.30 $ : TPS 0.015 -> 0.02 et TVQ 0.029925 -> 0.03 (0.05) : l'écart est de +0.01, dit et non corrigé.
    plan = _plan_ok(_montants("0.10", "0.10", "0.10"), prix="0.30")
    resume, refus = facturation_jalons.resume_plan(plan | {"statut": "ACTIF"}, [], _taux(), None)
    assert refus is None
    assert (resume["taxes_des_jalons"], resume["taxes_sur_le_total"], resume["ecart_arrondi_taxes"]) == (
        "0.06",
        "0.05",
        "0.01",
    )


def test_les_codes_de_refus_sont_dans_le_catalogue_ferme():
    with pytest.raises(verdicts_facturation.CodeFacturationInconnu):
        verdicts_facturation.construire_verdict("REJ-PLAN-INEXISTANT")
    assert len(set(verdicts_facturation.CODES_FACTURATION)) == len(verdicts_facturation.CODES_FACTURATION)
