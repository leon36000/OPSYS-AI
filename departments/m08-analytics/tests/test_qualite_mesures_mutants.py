"""Tests tueurs de mutants pour ``qualite_mesures.py`` : bornes exactes, gardes de cohérence et comptes.

Chaque cas isole une règle de ``definitions/m8-qualite.v1.yaml`` ou une vérification de fait, sur des données
fictives et déterministes. Les tests passent par ``valider``/``evaluer``/``appliquer`` (comportement observable),
jamais par une copie du code.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from m8_analytics import catalogue_mesures, jeux_fictifs, qualite_mesures

CATALOGUE = catalogue_mesures.charger()
SCHEMA = qualite_mesures.SCHEMA


def _regle_plage(minimum: str = "0", **surcharges) -> dict:
    base = {
        "id": "Q-TEST-PLAGE",
        "type": "plage",
        "libelle": "Une borne de test.",
        "correction": "Corriger la valeur.",
        "mesures": ["m8_cash_libre_cad"],
        "min": minimum,
    }
    base.update(surcharges)
    return base


def _brut(*regles: dict) -> dict:
    return {"schema": SCHEMA, "version": 1, "regles": list(regles) or [_regle_plage()]}


def _regles(regle: dict) -> dict:
    return {"version": 1, "regles": [regle]}


def _mesure(metric_id: str = "m8_cash_libre_cad", statut: str = "calculee", valeur: str | None = "10") -> dict:
    return {"metric_id": metric_id, "statut": statut, "valeur": valeur, "proprietaire": "m08-analytics",
            "nom": "Mesure fictive"}


def _verdict_controle(controle: str, registres: dict, metric_id: str = "m8_x") -> dict:
    regle = {
        "id": "Q-TEST-CONTROLE",
        "type": "controle",
        "libelle": "Cohérence de test.",
        "correction": "Corriger le fait.",
        "controle": controle,
        "bloque": [metric_id],
    }
    return qualite_mesures.evaluer(_regles(regle), [_mesure(metric_id)], registres)[metric_id]


def _registres() -> dict:
    return jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True)


def _registres_factures(**modifs) -> dict:
    registres = copy.deepcopy(_registres())
    for fait in registres["operations"]:
        if fait["type_entree"] == "facture_emise":
            fait.update(modifs)
    return registres


def _registres_cash(**constat) -> dict:
    base = {
        "type_entree": "cash_libre_constate",
        "evenement_id": "evt-cash-fictif-1",
        "sequence": 1,
        "date_reference": "2026-11-12",
        "statut": "CALCULE",
        "cash_libre_cad": "100.00",
        "en_deficit": False,
    }
    base.update(constat)
    return {"cash_libre": [base]}


# ================================================================ bornes du fichier de règles
def test_le_plafond_de_regles_est_de_deux_cents_inclus():
    """200 règles passent, 201 sont refusées : la constante ``_REGLES_MAX`` est une borne, pas un ordre de grandeur."""
    acceptees = [_regle_plage(str(rang), id=f"Q-RANG-{rang}") for rang in range(1, 201)]
    assert len(qualite_mesures.valider(_brut(*acceptees), CATALOGUE)["regles"]) == 200

    refusees = [_regle_plage(str(rang), id=f"Q-RANG-{rang}") for rang in range(1, 202)]
    with pytest.raises(qualite_mesures.QualiteRefusee, match="1 à 200"):
        qualite_mesures.valider(_brut(*refusees), CATALOGUE)


def test_une_seule_regle_est_un_fichier_valide():
    assert len(qualite_mesures.valider(_brut(_regle_plage()), CATALOGUE)["regles"]) == 1


def test_un_texte_de_quatre_cents_caracteres_est_accepte_au_plafond_et_un_de_plus_refuse():
    au_plafond = _regle_plage(libelle="x" * 400)
    assert len(qualite_mesures.valider(_brut(au_plafond), CATALOGUE)["regles"]) == 1

    with pytest.raises(qualite_mesures.QualiteRefusee):
        qualite_mesures.valider(_brut(_regle_plage(libelle="x" * 401)), CATALOGUE)


def test_une_reference_de_fait_est_bornee_a_sa_longueur_maximale():
    assert qualite_mesures.reference_sure("a" * 61) == "a" * 60


@pytest.mark.parametrize("libelle", [5, "", "texte "])
def test_un_texte_non_chaîne_vide_ou_avec_espace_aux_bords_est_refuse(libelle):
    with pytest.raises(qualite_mesures.QualiteRefusee, match="libelle"):
        qualite_mesures.valider(_brut(_regle_plage(libelle=libelle)), CATALOGUE)


def test_un_identifiant_de_regle_doit_commencer_par_Q_et_tenir_en_80_caracteres_inclus():
    assert len(qualite_mesures.valider(_brut(_regle_plage(id="Q-" + "A" * 78)), CATALOGUE)["regles"]) == 1

    for identifiant in ("PAS-Q", "Q-" + "A" * 79):
        with pytest.raises(qualite_mesures.QualiteRefusee, match="Q-"):
            qualite_mesures.valider(_brut(_regle_plage(id=identifiant)), CATALOGUE)

    with pytest.raises(qualite_mesures.QualiteRefusee, match="Q-"):
        qualite_mesures.valider(_brut(_regle_plage(id=5)), CATALOGUE)


def test_des_bornes_egales_sont_valides_seul_un_min_superieur_est_refuse():
    assert len(qualite_mesures.valider(_brut(_regle_plage(min="5", max="5")), CATALOGUE)["regles"]) == 1
    with pytest.raises(qualite_mesures.QualiteRefusee, match="min dépasse max"):
        qualite_mesures.valider(_brut(_regle_plage(min="6", max="5")), CATALOGUE)


def test_une_version_non_entiere_est_refusee_sans_comparaison_hasardeuse():
    with pytest.raises(qualite_mesures.QualiteRefusee, match="version"):
        qualite_mesures.valider({**_brut(), "version": "1"}, CATALOGUE)


# ================================================================ les vérifications de faits
def _creances(registres: dict) -> dict:
    for fait in registres["operations"]:
        if fait["type_entree"] == "mesures_comptables_constatees":
            return fait["creances"]
    raise AssertionError("constat comptable fictif absent")


def test_un_total_de_creances_nul_avec_aucune_tranche_reste_incoherent():
    registres = copy.deepcopy(_registres())
    creances = _creances(registres)
    creances["total"] = "0.00"
    creances["par_tranche"] = {}

    assert _verdict_controle("creances_total_egale_tranches", registres)["statut"] == "echec"


def test_une_tranche_de_creances_illisible_bloque_meme_si_les_tranches_lisibles_somment_le_total():
    registres = copy.deepcopy(_registres())
    creances = _creances(registres)
    lues = [Decimal(valeur) for valeur in creances["par_tranche"].values()]
    creances["total"] = str(sum(lues))
    creances["par_tranche"]["illisible"] = "abc"

    assert _verdict_controle("creances_total_egale_tranches", registres)["statut"] == "echec"


def test_un_echec_ne_garde_que_cinq_references_meme_s_il_en_compte_six():
    registres = _registres_factures(montant_apres_taxes_cad="99999.00")
    for fait in list(registres["operations"]):
        if fait["type_entree"] == "facture_emise":
            for rang in range(2, 3):
                copie = copy.deepcopy(fait)
                copie["facture_id"] = f"{fait['facture_id']}-{rang}"
                registres["operations"].append(copie)
    echecs = _verdict_controle("factures_emises_coherentes", registres)["echecs"]
    echec = next(e for e in echecs if e["regle"] == "Q-TEST-CONTROLE")

    assert echec["nombre"] == 6
    assert len(echec["references"]) == 5


def test_l_absence_d_un_champ_de_facture_est_signalee_pas_une_comparaison_avec_None():
    for champ in ("montant_avant_taxes_cad", "total_taxes_cad", "montant_apres_taxes_cad"):
        registres = _registres_factures(**{champ: None})
        assert _verdict_controle("factures_emises_coherentes", registres)["statut"] == "echec", champ


def test_des_montants_de_facture_a_zero_sont_coherents_la_borne_negative_est_stricte():
    registres = _registres_factures(
        montant_avant_taxes_cad="0.00", total_taxes_cad="0.00", montant_apres_taxes_cad="0.00"
    )

    assert _verdict_controle("factures_emises_coherentes", registres)["statut"] != "echec"


def test_un_montant_avant_taxes_negatif_avec_des_taxes_nulles_est_incoherent():
    registres = _registres_factures(
        montant_avant_taxes_cad="-100.00", total_taxes_cad="0.00", montant_apres_taxes_cad="-100.00"
    )

    assert _verdict_controle("factures_emises_coherentes", registres)["statut"] == "echec"


def test_un_cash_libre_a_zero_avec_un_drapeau_de_deficit_faux_est_coherent():
    registres = _registres_cash(cash_libre_cad="0.00", en_deficit=False)

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] != "echec"


def test_un_statut_de_cash_libre_inconnu_avec_un_montant_reste_incoherent():
    registres = _registres_cash(statut="EN_ATTENTE", cash_libre_cad="100.00")

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] == "echec"


def _cash_avec_composante(**composante) -> dict:
    return _registres_cash(composantes=[composante])


def test_une_composante_autre_que_comptes_a_payer_n_est_pas_controlee():
    registres = _cash_avec_composante(id="autre_composante", statut="CALCULE", montant_cad="-5.00")

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] != "echec"


def test_une_composante_comptes_a_payer_negative_est_incoherente():
    registres = _cash_avec_composante(id="comptes_a_payer", statut="CALCULE", montant_cad="-5.00")

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] == "echec"


def test_une_composante_comptes_a_payer_non_calculee_n_est_pas_jugee():
    registres = _cash_avec_composante(id="comptes_a_payer", statut="BROUILLON", montant_cad="-5.00")

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] != "echec"


def test_une_composante_comptes_a_payer_calculee_mais_illisible_est_incoherente():
    registres = _cash_avec_composante(id="comptes_a_payer", statut="CALCULE", montant_cad=None)

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] == "echec"


def test_une_composante_comptes_a_payer_a_zero_est_coherente():
    registres = _cash_avec_composante(id="comptes_a_payer", statut="CALCULE", montant_cad="0.00")

    assert _verdict_controle("cash_libre_coherent", registres)["statut"] != "echec"


# ================================================================ comptes de règles jugées
def test_une_regle_de_plage_ne_compte_qu_une_fois_par_mesure():
    regle = qualite_mesures.valider(_brut(_regle_plage(min="0")), CATALOGUE)
    verdict = qualite_mesures.evaluer(regle, [_mesure()], {})["m8_cash_libre_cad"]

    assert verdict["statut"] == "ok"
    assert verdict["regles_evaluees"] == 1


def test_une_regle_de_relation_ne_compte_qu_une_fois_par_mesure_jugee():
    regle = {
        "id": "Q-TEST-RELATION",
        "type": "relation",
        "libelle": "Gauche au plus droite.",
        "correction": "Corriger.",
        "gauche": "m8_gauche",
        "droite": "m8_droite",
        "operateur": "au_plus",
    }
    mesures = [_mesure("m8_gauche", valeur="10"), _mesure("m8_droite", valeur="20")]
    verdicts = qualite_mesures.evaluer(_regles(regle), mesures, {})

    assert verdicts["m8_gauche"]["statut"] == "ok"
    assert verdicts["m8_droite"]["statut"] == "ok"
    assert verdicts["m8_gauche"]["regles_evaluees"] == 1
    assert verdicts["m8_droite"]["regles_evaluees"] == 1


def test_une_relation_dont_une_mesure_n_est_pas_calculable_n_est_pas_jugee():
    regle = {
        "id": "Q-TEST-RELATION",
        "type": "relation",
        "libelle": "Gauche au plus droite.",
        "correction": "Corriger.",
        "gauche": "m8_gauche",
        "droite": "m8_droite",
        "operateur": "au_plus",
    }
    mesures = [_mesure("m8_gauche"), _mesure("m8_droite", statut="non_calculable", valeur=None)]
    verdicts = qualite_mesures.evaluer(_regles(regle), mesures, {})

    assert verdicts["m8_gauche"]["statut"] == "non_evaluee"
    assert verdicts["m8_gauche"]["regles_evaluees"] == 0


def test_une_relation_avec_une_valeur_illisible_est_incoherente_pas_un_plantage():
    regle = {
        "id": "Q-TEST-RELATION",
        "type": "relation",
        "libelle": "Gauche au plus droite.",
        "correction": "Corriger.",
        "gauche": "m8_gauche",
        "droite": "m8_droite",
        "operateur": "au_plus",
    }
    mesures = [_mesure("m8_gauche", valeur="abc"), _mesure("m8_droite", valeur="20")]

    verdicts = qualite_mesures.evaluer(_regles(regle), mesures, {})

    assert verdicts["m8_gauche"]["statut"] == "echec"
    assert verdicts["m8_droite"]["statut"] == "echec"


def test_deux_valeurs_egales_ne_franchissent_pas_la_relation():
    regle = {
        "id": "Q-TEST-RELATION",
        "type": "relation",
        "libelle": "Gauche au plus droite.",
        "correction": "Corriger.",
        "gauche": "m8_gauche",
        "droite": "m8_droite",
        "operateur": "au_plus",
    }
    mesures = [_mesure("m8_gauche", valeur="10"), _mesure("m8_droite", valeur="10")]

    verdicts = qualite_mesures.evaluer(_regles(regle), mesures, {})

    assert verdicts["m8_gauche"]["statut"] == "ok"


def test_une_regle_de_controle_ne_compte_qu_une_fois_par_mesure_bloquee():
    regle = {
        "id": "Q-TEST-CONTROLE",
        "type": "controle",
        "libelle": "Cash libre cohérent.",
        "correction": "Corriger le constat.",
        "controle": "cash_libre_coherent",
        "bloque": ["m8_x"],
    }
    verdict = qualite_mesures.evaluer(_regles(regle), [_mesure("m8_x")], _registres_cash())["m8_x"]

    assert verdict["statut"] == "ok"
    assert verdict["regles_evaluees"] == 1


def test_une_mesure_bloquee_ne_cite_que_les_deux_premieres_regles_en_echec():
    regles = qualite_mesures.valider(
        _brut(
            _regle_plage("2", id="Q-UN", libelle="Première règle."),
            _regle_plage("3", id="Q-DEUX", libelle="Deuxième règle."),
            _regle_plage("4", id="Q-TROIS", libelle="Troisième règle."),
        ),
        CATALOGUE,
    )
    mesure = _mesure(valeur="1")
    bloquee = qualite_mesures.appliquer(regles, [mesure], {})[0]

    assert bloquee["statut"] == "non_calculable"
    assert "Première règle." in bloquee["detail"]
    assert "Deuxième règle." in bloquee["detail"]
    assert "Troisième règle." not in bloquee["detail"]
