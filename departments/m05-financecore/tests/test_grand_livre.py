"""Grand livre en partie double (tranche 1) : le noyau pur, sur un registre en mémoire.

Plan comptable (base et extension), chaque refus nommé (cas positif ET négatif), idempotence par pièce, immuabilité
(correction par contre-passation seulement), clôture cumulative, balance, grand livre d'un compte, génération des
brouillons depuis les factures M5, rapprochement TPS/TVQ contre `taxes.py`, export Beancount (forme et équilibre), et la
propriété « toute écriture acceptée est équilibrée » sur des cas générés (générateur déterministe à graine : hypothesis
n'est pas dans l'environnement). Données fictives (AGENTS.md).
"""

from __future__ import annotations

import random
import re
from decimal import Decimal
from pathlib import Path

import pytest
from m5_financecore import (
    facturation,
    grand_livre,
    grand_livre_beancount,
    plan_comptable,
    taux_fiscaux,
    validation,
    verdicts_grand_livre,
)
from m5_financecore import registre as registre_module

FICTIF = True
D = Decimal
_M5 = Path(__file__).resolve().parents[1]
_PLAN = _M5 / "contracts" / "plan_comptable_pme_qc.v1.yaml"
H = "2026-10-15T10:00:00-04:00"
HUMAIN = {"par": "nathan", "role": "nathan_owner", "voie": "approbation"}


@pytest.fixture
def plan():
    base, refus = plan_comptable.charger_plan(_PLAN)
    assert refus is None, refus
    return base


@pytest.fixture
def reg():
    return registre_module.Registre()


@pytest.fixture
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_M5 / "contracts" / "taux_fiscaux.v1.yaml")
    assert erreurs == []
    return dictionnaire


def L(compte, debit=None, credit=None):
    return {"compte": compte, "debit": debit, "credit": credit}


def _proposer(reg, plan, *, ref="M-1", jour="2026-10-01", lignes=None, piece_type="manuelle", **autres):
    lignes = lignes if lignes is not None else [L("5600", "1000.00"), L("1010", credit="1000.00")]
    return grand_livre.proposer_ecriture(
        reg, plan, cle_piece=f"saisie:{piece_type}:{ref}", piece={"type": piece_type, "reference": ref},
        nature="saisie", date_effet=jour, libelle=autres.pop("libelle", "Loyer d'octobre (fictif)"),
        lignes_brutes=lignes, horodatage=autres.pop("horodatage", H), origine="saisie", **autres)


def _accepte(couple):
    resultat, refus = couple
    assert refus is None, refus
    return resultat


def _code(couple):
    resultat, refus = couple
    assert resultat is None and refus is not None
    assert refus["code"] in verdicts_grand_livre.CODES_GL
    return refus["code"]


def _etat(reg):
    return grand_livre.etat_grand_livre(reg.lire())


def _valider(reg, plan, ident, horodatage=H):
    return grand_livre.valider_ecriture(reg, plan, ecriture_id=ident, humain=HUMAIN, horodatage=horodatage)


# ================================================================================================ catalogue
def test_le_catalogue_des_refus_est_ferme_documente_et_hors_du_code_de_paie_epingle():
    with pytest.raises(verdicts_grand_livre.CodeGrandLivreInconnu):
        verdicts_grand_livre.construire_verdict("REJ-GL-INVENTE")
    assert len(set(verdicts_grand_livre.CODES_GL)) == len(verdicts_grand_livre.CODES_GL)
    doc = (_M5 / "docs" / "grand-livre.md").read_text(encoding="utf-8")
    absents = [code for code in verdicts_grand_livre.CODES_GL if code not in doc]
    assert absents == [], f"codes non documentés : {absents}"
    # validation.py est épinglé par le contrat d'admission de la paie : le grand livre n'y ajoute rien.
    assert not any(code.startswith("REJ-GL-") for code in validation.CODES_M5_LIST)


# ================================================================================================ plan comptable
def test_le_plan_par_defaut_porte_les_comptes_pme_qc_et_sa_version(plan):
    comptes = plan["comptes"]
    assert plan["version_effective"] == plan["version"] == "2026-v2"
    for numero, mot in [("2300", "TPS à percevoir"), ("2310", "TVQ à percevoir"), ("1400", "CTI"), ("1410", "RTI"),
                        ("2200", "Salaires à payer"), ("2400", "Retenues à la source"),
                        ("2420", "Cotisations de l'employeur")]:
        assert mot in comptes[numero]["nom"], numero
    assert {c["type"] for c in comptes.values()} == {"actif", "passif", "capitaux_propres", "produits", "charges"}
    assert all(c["actif"] for c in comptes.values())
    assert plan_comptable.sens_normal("actif") == plan_comptable.sens_normal("charges") == "debiteur"
    assert plan_comptable.sens_normal("produits") == plan_comptable.sens_normal("passif") == "crediteur"


def test_l_extension_du_client_ajoute_desactive_et_change_la_version(plan):
    effectif = _accepte(plan_comptable.appliquer_extension(plan, {
        "comptes_ajoutes": [{"numero": "5450", "nom": "Location d'équipement", "type": "charges"}],
        "comptes_desactives": ["5600"]}))
    assert effectif["comptes"]["5450"]["actif"] and not effectif["comptes"]["5600"]["actif"]
    assert effectif["version_effective"].startswith("2026-v2+client.")
    assert plan["comptes"]["5600"]["actif"], "le plan de base n'est pas modifié"
    assert _accepte(plan_comptable.appliquer_extension(plan, None))["version_effective"] == "2026-v2"


@pytest.mark.parametrize("extension", [
    {"comptes_ajoutes": [{"numero": "5600", "nom": "Doublon", "type": "charges"}]},
    {"comptes_ajoutes": [{"numero": "1450", "nom": "Mauvais type", "type": "charges"}]},
    {"comptes_ajoutes": [{"numero": "54", "nom": "Trop court", "type": "charges"}]},
    {"comptes_ajoutes": [{"numero": 5450, "nom": "Nombre", "type": "charges"}]},
    {"comptes_desactives": ["9999"]},
    {"comptes_desactives": ["5600", "5600"]},
    {"autre_cle": []},
    "pas un dictionnaire",
])
def test_une_extension_invalide_est_refusee_en_entier(plan, extension):
    assert _code(plan_comptable.appliquer_extension(plan, extension)) == "REJ-GL-PLAN-INVALIDE"


def test_un_fichier_de_plan_incoherent_est_refuse(tmp_path):
    chemin = tmp_path / "plan.yaml"
    chemin.write_text(_PLAN.read_text(encoding="utf-8").replace('banque: "1010"', 'banque: "1099"'), encoding="utf-8")
    assert _code(plan_comptable.charger_plan(chemin)) == "REJ-GL-PLAN-INVALIDE"
    chemin.write_text("schema_version: 2\n", encoding="utf-8")
    assert _code(plan_comptable.charger_plan(chemin)) == "REJ-GL-PLAN-INVALIDE"


# ============================================================================================ proposer : accepté
def test_une_ecriture_equilibree_nait_brouillon_et_n_entre_pas_a_la_balance(reg, plan):
    resultat = _accepte(_proposer(reg, plan))
    ecriture = resultat["ecriture"]
    assert resultat["statut"] == "proposee" and ecriture["statut"] == "BROUILLON" and ecriture["numero"] is None
    assert ecriture["piece"]["verification"] == "declaree_non_verifiee"
    assert [(li["compte"], li["debit"], li["credit"]) for li in ecriture["lignes"]] == [
        ("5600", "1000.00", None), ("1010", None, "1000.00")]
    balance = _accepte(grand_livre.balance_verification(_etat(reg), plan, "2026-12-31"))
    assert balance["comptes"] == [] and balance["brouillons_non_comptabilises"] == 1
    assert balance["total_debits"] == balance["total_credits"] == "0.00"


def test_les_montants_sont_ramenes_au_cent_sans_arrondi_cache(reg, plan):
    ecriture = _accepte(_proposer(reg, plan, lignes=[L("5600", "10"), L("1010", credit="10.0")]))["ecriture"]
    assert ecriture["lignes"][0]["debit"] == "10.00" and ecriture["lignes"][1]["credit"] == "10.00"
    maillon = reg.lire()[-1]
    assert all(isinstance(li["debit"], Decimal) and isinstance(li["credit"], Decimal) for li in maillon["lignes"])


# ============================================================================================ proposer : refus
@pytest.mark.parametrize(("lignes", "code"), [
    ([L("5600", "1000.00"), L("1010", credit="999.99")], "REJ-GL-ECRITURE-DESEQUILIBREE"),
    ([L("5600", "1000.00")], "REJ-GL-LIGNES-INSUFFISANTES"),
    ([], "REJ-GL-LIGNES-INSUFFISANTES"),
    ([L("5600", "10.00", "10.00"), L("1010", credit="0.00")], "REJ-GL-LIGNE-INVALIDE"),
    ([L("5600"), L("1010", credit="10.00")], "REJ-GL-LIGNE-INVALIDE"),
    ([{"compte": "5600", "debit": "1.00"}, L("1010", credit="1.00")], "REJ-GL-LIGNE-INVALIDE"),
    ([L("5600", 1000.0), L("1010", credit="1000.00")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5600", "10.005"), L("1010", credit="10.005")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5600", "-10.00"), L("1010", credit="-10.00")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5600", "0.00"), L("1010", credit="0.00")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5600", "NaN"), L("1010", credit="NaN")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5600", "dix"), L("1010", credit="dix")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5600", "1000000000000.00"), L("1010", credit="1000000000000.00")], "REJ-GL-MONTANT-INVALIDE"),
    ([L("5601", "10.00"), L("1010", credit="10.00")], "REJ-GL-COMPTE-INCONNU"),
    ([L(5600, "10.00"), L("1010", credit="10.00")], "REJ-GL-COMPTE-INCONNU"),
], ids=["desequilibree", "une-ligne", "aucune-ligne", "debit-et-credit", "ni-l-un-ni-l-autre", "ligne-mal-formee",
        "float", "millieme", "negatif", "zero", "nan", "texte", "hors-domaine", "compte-inconnu", "compte-nombre"])
def test_chaque_refus_de_lignes_n_ecrit_rien(reg, plan, lignes, code):
    assert _code(_proposer(reg, plan, lignes=lignes)) == code
    assert reg.taille() == 0


def test_un_compte_desactive_est_refuse_et_le_meme_compte_actif_est_accepte(reg, plan):
    desactive = _accepte(plan_comptable.appliquer_extension(plan, {"comptes_desactives": ["5600"]}))
    assert _code(_proposer(reg, desactive)) == "REJ-GL-COMPTE-INACTIF" and reg.taille() == 0
    assert _accepte(_proposer(reg, plan))["statut"] == "proposee"


@pytest.mark.parametrize(("champ", "valeur", "code"), [
    ("jour", "2026-13-01", "REJ-GL-DATE-INVALIDE"),
    ("jour", "20261001", "REJ-GL-DATE-INVALIDE"),
    ("jour", None, "REJ-GL-DATE-INVALIDE"),
    ("libelle", "", "REJ-GL-CHAMP-INVALIDE"),
    ("libelle", "deux\nlignes", "REJ-GL-CHAMP-INVALIDE"),
    ("libelle", "x" * 201, "REJ-GL-CHAMP-INVALIDE"),
    ("horodatage", "2026-10-15T10:00:00", "REJ-GL-CHAMP-INVALIDE"),
    ("ref", "", "REJ-GL-PIECE-INVALIDE"),
    ("piece_type", "facture_inventee", "REJ-GL-PIECE-INVALIDE"),
])
def test_chaque_refus_de_champ_n_ecrit_rien(reg, plan, champ, valeur, code):
    assert _code(_proposer(reg, plan, **{champ: valeur})) == code
    assert reg.taille() == 0


def test_une_piece_m5_inexistante_est_refusee_et_une_piece_existante_acceptee(reg, plan):
    connues = {"facture_client": {"F-1"}, "facture_fournisseur": set()}
    assert _code(_proposer(reg, plan, ref="F-2", piece_type="facture_client", pieces_connues=connues)) \
        == "REJ-GL-PIECE-INTROUVABLE"
    assert _code(_proposer(reg, plan, ref="apf-1", piece_type="facture_fournisseur", pieces_connues=connues)) \
        == "REJ-GL-PIECE-INTROUVABLE"
    ecriture = _accepte(_proposer(reg, plan, ref="F-1", piece_type="facture_client", pieces_connues=connues,
                                  lignes=[L("1100", "10.00"), L("4100", credit="10.00")]))["ecriture"]
    assert ecriture["piece"] == {"type": "facture_client", "reference": "F-1", "verification": "verifiee"}


# ============================================================================================ idempotence
def test_la_meme_piece_au_meme_contenu_ne_recree_rien(reg, plan):
    premiere = _accepte(_proposer(reg, plan))
    redite = _accepte(_proposer(reg, plan, horodatage="2026-10-16T10:00:00-04:00"))
    assert redite["statut"] == "deja_proposee"
    assert redite["ecriture"]["ecriture_id"] == premiere["ecriture"]["ecriture_id"]
    assert reg.taille() == 1


def test_la_meme_piece_a_un_autre_contenu_est_un_conflit(reg, plan):
    _accepte(_proposer(reg, plan))
    assert _code(_proposer(reg, plan, lignes=[L("5600", "999.00"), L("1010", credit="999.00")])) \
        == "REJ-GL-PIECE-CONFLIT"
    assert reg.taille() == 1
    assert _accepte(_proposer(reg, plan, ref="M-2", lignes=[L("5600", "999.00"), L("1010", credit="999.00")]))


# ============================================================================================ valider
def test_valider_rend_definitive_numerote_et_entre_a_la_balance(reg, plan):
    ident = _accepte(_proposer(reg, plan))["ecriture"]["ecriture_id"]
    definitive = _accepte(_valider(reg, plan, ident))["ecriture"]
    assert definitive["statut"] == "DEFINITIVE" and definitive["numero"] == 1
    assert definitive["validation"] == {**HUMAIN, "horodatage": H}
    balance = _accepte(grand_livre.balance_verification(_etat(reg), plan, "2026-10-31"))
    assert balance["equilibree"] and balance["total_debits"] == balance["total_credits"] == "1000.00"
    assert [(c["compte"], c["solde"], c["cote"]) for c in balance["comptes"]] == [
        ("1010", "1000.00", "crediteur"), ("5600", "1000.00", "debiteur")]
    assert _accepte(grand_livre.balance_verification(_etat(reg), plan, "2026-09-30"))["comptes"] == []


def test_valider_deux_fois_est_refuse_et_n_ecrit_rien(reg, plan):
    ident = _accepte(_proposer(reg, plan))["ecriture"]["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    taille = reg.taille()
    assert _code(_valider(reg, plan, ident)) == "REJ-GL-ECRITURE-DEJA-VALIDEE" and reg.taille() == taille
    assert _code(_valider(reg, plan, "gle-inconnue")) == "REJ-GL-ECRITURE-INTROUVABLE"


def test_valider_revérifie_le_plan_courant(reg, plan):
    ident = _accepte(_proposer(reg, plan))["ecriture"]["ecriture_id"]
    desactive = _accepte(plan_comptable.appliquer_extension(plan, {"comptes_desactives": ["5600"]}))
    assert _code(_valider(reg, desactive, ident)) == "REJ-GL-COMPTE-INACTIF"
    assert _accepte(_valider(reg, plan, ident))["statut"] == "validee"


# ============================================================================================ immuabilité
def test_aucune_api_ne_modifie_une_ecriture_et_une_alteration_est_detectee(reg, plan):
    ident = _accepte(_proposer(reg, plan))["ecriture"]["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    assert not hasattr(grand_livre, "modifier_ecriture") and not hasattr(grand_livre, "supprimer_ecriture")
    # Une main qui réécrirait un montant au registre : la chaîne et l'état la voient, la lecture refuse.
    reg._chain[0]["lignes"][0]["debit"] = D("1.00")
    assert reg.valider_chaine()[0] is False
    assert _code(grand_livre.balance_verification(_etat(reg), plan, "2026-12-31")) == "REJ-GL-CHAINE-INVALIDE"


def test_un_doublon_concurrent_est_ignore_le_premier_maillon_fait_foi(reg, plan):
    """Deux appels concurrents qui ont lu le même état : la même écriture proposée deux fois, validée deux fois. Le
    premier maillon fait foi, la lecture continue (aucun registre bloqué), le doublon est compté."""
    _accepte(_proposer(reg, plan))
    proposee = {k: v for k, v in reg.lire()[0].items() if k not in ("ligne_id", "precedent_ligne_id")}
    reg.ajouter(proposee)
    ident = proposee["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    validation_maillon = {k: v for k, v in reg.lire()[-1].items() if k not in ("ligne_id", "precedent_ligne_id")}
    reg.ajouter(validation_maillon)
    etat = _etat(reg)
    assert etat["anomalies"] == [] and len(etat["doublons"]) == 2 and etat["definitives"] == 1
    balance = _accepte(grand_livre.balance_verification(etat, plan, "2026-12-31"))
    assert balance["total_debits"] == "1000.00" and balance["doublons_ignores"] == 2


def test_un_maillon_illisible_ou_etranger_fait_refuser_la_lecture(reg, plan):
    _accepte(_proposer(reg, plan))
    reg.ajouter({"type_entree": "gl_periode_cloturee", "horodatage": H})
    assert _code(grand_livre.balance_verification(_etat(reg), plan, "2026-12-31")) == "REJ-GL-CHAINE-INVALIDE"
    assert grand_livre.etat_grand_livre([{"type_entree": "facture_creee"}])["anomalies"]


def test_contre_passation_inverse_les_lignes_et_s_annule_a_la_balance(reg, plan):
    ident = _accepte(_proposer(reg, plan))["ecriture"]["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    contre = _accepte(grand_livre.proposer_contre_passation(
        reg, plan, ecriture_id=ident, date_effet="2026-10-05", motif="loyer saisi au mauvais compte (fictif)",
        horodatage=H))["ecriture"]
    assert contre["contre_passe"] == ident and contre["statut"] == "BROUILLON"
    assert [(li["compte"], li["debit"], li["credit"]) for li in contre["lignes"]] == [
        ("5600", None, "1000.00"), ("1010", "1000.00", None)]
    _accepte(_valider(reg, plan, contre["ecriture_id"]))
    etat = _etat(reg)
    assert etat["ecritures"][ident]["contre_passee_par"] == contre["ecriture_id"]
    balance = _accepte(grand_livre.balance_verification(etat, plan, "2026-10-31"))
    assert all(c["solde"] == "0.00" for c in balance["comptes"]) and balance["equilibree"]
    # L'original est toujours là, intact : seule la contre-passation l'annule.
    assert etat["ecritures"][ident]["lignes"][0]["debit"] == D("1000.00")


def test_les_refus_de_contre_passation(reg, plan):
    ident = _accepte(_proposer(reg, plan))["ecriture"]["ecriture_id"]
    args = {"date_effet": "2026-10-05", "motif": "erreur (fictive)", "horodatage": H}
    assert _code(grand_livre.proposer_contre_passation(reg, plan, ecriture_id=ident, **args)) \
        == "REJ-GL-ECRITURE-NON-DEFINITIVE"
    _accepte(_valider(reg, plan, ident))
    assert _code(grand_livre.proposer_contre_passation(reg, plan, ecriture_id="gle-x", **args)) \
        == "REJ-GL-ECRITURE-INTROUVABLE"
    assert _code(grand_livre.proposer_contre_passation(reg, plan, ecriture_id=ident, **{**args, "motif": " "})) \
        == "REJ-GL-MOTIF-REQUIS"
    assert _code(grand_livre.proposer_contre_passation(
        reg, plan, ecriture_id=ident, **{**args, "date_effet": "2026-09-30"})) == "REJ-GL-DATE-INVALIDE"
    contre = _accepte(grand_livre.proposer_contre_passation(reg, plan, ecriture_id=ident, **args))["ecriture"]
    _accepte(_valider(reg, plan, contre["ecriture_id"]))
    assert _code(grand_livre.proposer_contre_passation(reg, plan, ecriture_id=ident, **args)) \
        == "REJ-GL-DEJA-CONTRE-PASSEE"
    assert _code(grand_livre.proposer_contre_passation(reg, plan, ecriture_id=contre["ecriture_id"], **args)) \
        == "REJ-GL-CONTRE-PASSATION-INVALIDE"


# ============================================================================================ périodes
def test_cloture_cumulative_refuse_les_ecritures_anterieures_et_accepte_les_suivantes(reg, plan):
    ident = _accepte(_proposer(reg, plan, jour="2026-09-10"))["ecriture"]["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    en_plan = _accepte(_proposer(reg, plan, ref="M-2", jour="2026-08-20"))["ecriture"]["ecriture_id"]
    close = _accepte(grand_livre.clore_periode(reg, periode="2026-09", humain=HUMAIN, horodatage=H))
    assert close["verrou"] == "2026-09-30" and close["total_debits"] == close["total_credits"] == "1000.00"
    assert close["brouillons_laisses_en_plan"] == [en_plan]
    taille = reg.taille()
    assert _code(_proposer(reg, plan, ref="M-3", jour="2026-09-30")) == "REJ-GL-PERIODE-CLOSE"
    assert _code(_proposer(reg, plan, ref="M-4", jour="2026-01-02")) == "REJ-GL-PERIODE-CLOSE"
    assert _code(_valider(reg, plan, en_plan)) == "REJ-GL-PERIODE-CLOSE"
    assert reg.taille() == taille
    assert _accepte(_proposer(reg, plan, ref="M-5", jour="2026-10-01"))["statut"] == "proposee"


def test_les_refus_de_cloture(reg, plan):
    assert _code(grand_livre.clore_periode(reg, periode="2026-13", humain=HUMAIN, horodatage=H)) \
        == "REJ-GL-PERIODE-INVALIDE"
    assert _code(grand_livre.clore_periode(reg, periode="2026-9", humain=HUMAIN, horodatage=H)) \
        == "REJ-GL-PERIODE-INVALIDE"
    _accepte(grand_livre.clore_periode(reg, periode="2026-09", humain=HUMAIN, horodatage=H))
    for periode in ("2026-09", "2026-08"):
        assert _code(grand_livre.clore_periode(reg, periode=periode, humain=HUMAIN, horodatage=H)) \
            == "REJ-GL-PERIODE-DEJA-CLOSE"
    assert _accepte(grand_livre.clore_periode(reg, periode="2026-10", humain=HUMAIN, horodatage=H))["statut"] == "close"


def test_contre_passer_une_ecriture_d_une_periode_close_se_fait_dans_une_periode_ouverte(reg, plan):
    ident = _accepte(_proposer(reg, plan, jour="2026-09-10"))["ecriture"]["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    _accepte(grand_livre.clore_periode(reg, periode="2026-09", humain=HUMAIN, horodatage=H))
    args = {"ecriture_id": ident, "motif": "erreur (fictive)", "horodatage": H}
    assert _code(grand_livre.proposer_contre_passation(reg, plan, date_effet="2026-09-15", **args)) \
        == "REJ-GL-PERIODE-CLOSE"
    assert _accepte(grand_livre.proposer_contre_passation(reg, plan, date_effet="2026-10-01", **args))


# ============================================================================================ grand livre d'un compte
def test_grand_livre_d_un_compte_ouverture_lignes_et_cloture(reg, plan):
    for ref, jour, montant in [("M-1", "2026-09-15", "300.00"), ("M-2", "2026-10-02", "100.00"),
                               ("M-3", "2026-10-20", "50.00")]:
        ident = _accepte(_proposer(reg, plan, ref=ref, jour=jour,
                                   lignes=[L("1010", montant), L("4900", credit=montant)]))["ecriture"]["ecriture_id"]
        _accepte(_valider(reg, plan, ident))
    livre = _accepte(grand_livre.grand_livre_compte(_etat(reg), plan, "1010", debut="2026-10-01", fin="2026-10-31"))
    assert livre["solde_ouverture_debiteur"] == "300.00" and livre["solde_cloture_debiteur"] == "450.00"
    assert [li["solde_debiteur"] for li in livre["lignes"]] == ["400.00", "450.00"]
    assert livre["total_debits"] == "150.00" and livre["sens_normal"] == "debiteur"
    page = _accepte(grand_livre.grand_livre_compte(_etat(reg), plan, "1010", debut="2026-10-01", fin="2026-10-31",
                                                    limite=1))
    assert len(page["lignes"]) == 1 and page["prochain_depart"] == 1 and page["lignes_total"] == 2
    assert _code(grand_livre.grand_livre_compte(_etat(reg), plan, "9999", debut="2026-10-01", fin="2026-10-31")) \
        == "REJ-GL-COMPTE-INCONNU"
    assert _code(grand_livre.grand_livre_compte(_etat(reg), plan, "1010", debut="2026-10-31", fin="2026-10-01")) \
        == "REJ-GL-DATE-INVALIDE"


# ============================================================================================ faits M5 -> brouillons
def _lignes_facture():
    return [{"description": "Gouttières 5po (fictif)", "quantite": "40", "unite": "pi", "prix_unitaire": "8.50",
             "reference_ligne_devis": "L1"},
            {"description": "Main-d'oeuvre (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": "260.00",
             "reference_ligne_devis": "L2"}]


def _factures(taux, *, payee=True, envoyees=("F-1",)):
    reg_f = registre_module.Registre()
    for numero, facture_id in enumerate(envoyees):
        _accepte(facturation.creer_facture_brouillon(facture_id, f"CH-{numero}", f"D-{numero}", "client-fictif",
                                                     _lignes_facture(), "2026-10-01T09:00:00-04:00", taux, reg_f))
        _accepte(facturation.envoyer_facture(facture_id, "2026-10-02T09:00:00-04:00", reg_f))
    if payee:
        _accepte(facturation.enregistrer_paiement_facture(envoyees[0], "689.85", "nathan",
                                                          "2026-10-20T09:00:00-04:00", reg_f))
    return [*facturation.factures_par_statut(reg_f, "ENVOYEE"), *facturation.factures_par_statut(reg_f, "PAYEE")]


def test_une_facture_emise_puis_payee_donne_deux_brouillons_equilibres(plan, taux):
    propositions, ignorees = grand_livre.propositions_factures_clients(_factures(taux), plan)
    assert ignorees == []
    emission, paiement = propositions
    assert (emission["nature"], emission["date_effet"]) == ("facture_emise", "2026-10-02")
    assert emission["lignes_brutes"] == [L("1100", "689.85"), L("4100", credit="600.00"),
                                         L("2300", credit="30.00"), L("2310", credit="59.85")]
    assert (paiement["nature"], paiement["date_effet"]) == ("paiement_recu", "2026-10-20")
    assert paiement["lignes_brutes"] == [L("1010", "689.85"), L("1100", credit="689.85")]


def test_une_facture_illisible_est_ignoree_jamais_completee(plan, taux):
    facture = dict(_factures(taux, payee=False)[0])
    facture["total_taxes"] = D("1.00")
    sans_date = {**_factures(taux, payee=False)[0], "date_envoi": None}
    propositions, ignorees = grand_livre.propositions_factures_clients([facture, sans_date], plan)
    assert propositions == [] and [i["code"] for i in ignorees] == ["REJ-GL-SOURCE-ILLISIBLE"] * 2


def test_un_brouillon_ne_vient_jamais_d_une_facture_brouillon(plan, taux):
    reg_f = registre_module.Registre()
    _accepte(facturation.creer_facture_brouillon("F-9", "CH", "D", "c", _lignes_facture(), H, taux, reg_f))
    assert grand_livre.propositions_factures_clients(facturation.factures_par_statut(reg_f, "BROUILLON"), plan) \
        == ([], [])


# ============================================================================================ rapprochement
def _comptabiliser(reg, plan, factures):
    propositions, _ = grand_livre.propositions_factures_clients(factures, plan)
    for proposition in propositions:
        ident = _accepte(grand_livre.proposer_ecriture(reg, plan, horodatage=H, origine="generation_automatique",
                                                       **proposition))["ecriture"]["ecriture_id"]
        _accepte(_valider(reg, plan, ident))


def test_rapprochement_concordant_quand_tout_est_comptabilise(reg, plan, taux):
    factures = _factures(taux, envoyees=("F-1", "F-2"))
    _comptabiliser(reg, plan, factures)
    resultat = _accepte(grand_livre.rapprocher(_etat(reg), plan, factures, taux, debut="2026-10-01",
                                               fin="2026-10-31"))
    assert resultat["verdict"] == "CONCORDANT" and resultat["equilibre"]["verdict"] == "EQUILIBRE"
    assert resultat["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "60.00"
    assert resultat["taxes"]["tvq_a_percevoir"]["au_grand_livre"] == "119.70"
    assert resultat["equilibre"]["total_debits"] == resultat["equilibre"]["total_credits"] == "2069.55"


def test_rapprochement_dit_l_ecart_d_une_facture_sans_ecriture_definitive(reg, plan, taux):
    factures = _factures(taux, envoyees=("F-1", "F-2"), payee=False)
    _comptabiliser(reg, plan, factures[:1])
    resultat = _accepte(grand_livre.rapprocher(_etat(reg), plan, factures, taux, debut="2026-10-01",
                                               fin="2026-10-31"))
    tps = resultat["taxes"]["tps_a_percevoir"]
    assert resultat["verdict"] == "ECART" and tps["verdict"] == "ECART"
    assert tps["ecarts"] == [{"facture_id": "F-2", "attendu_taxes": "30.00", "au_grand_livre": "0.00",
                              "raison": "sans écriture définitive"}]


def test_rapprochement_voit_une_taxe_mal_saisie_a_la_main(reg, plan, taux):
    factures = _factures(taux, payee=False)
    ident = _accepte(_proposer(reg, plan, ref="F-1", piece_type="facture_client", lignes=[
        L("1100", "689.86"), L("4100", credit="600.00"), L("2300", credit="30.01"), L("2310", credit="59.85")],
        jour="2026-10-02"))["ecriture"]["ecriture_id"]
    _accepte(_valider(reg, plan, ident))
    resultat = _accepte(grand_livre.rapprocher(_etat(reg), plan, factures, taux, debut="2026-10-01",
                                               fin="2026-10-31"))
    assert resultat["taxes"]["tps_a_percevoir"]["ecarts"][0]["raison"] == "montant différent"
    assert resultat["taxes"]["tvq_a_percevoir"]["verdict"] == "CONCORDANT"


# ============================================================================================ Beancount
_COMPTE_BEANCOUNT = re.compile(r"^(Assets|Liabilities|Equity|Income|Expenses)(:[A-Z0-9][A-Za-z0-9-]*)+$")


def _analyser_beancount(texte):
    """Lecteur minimal du sous-ensemble produit (open, transactions, méta, postings) : (ouverts, transactions)."""
    ouverts, transactions, courante = {}, [], None
    for ligne in texte.splitlines():
        if not ligne.strip() or ligne.startswith(";") or ligne.startswith("option "):
            courante = None
            continue
        if m := re.match(r"^(\d{4}-\d{2}-\d{2}) open (\S+) CAD$", ligne):
            assert _COMPTE_BEANCOUNT.match(m.group(2)), m.group(2)
            ouverts[m.group(2)] = m.group(1)
            continue
        if m := re.match(r'^(\d{4}-\d{2}-\d{2}) \* "((?:[^"\\]|\\.)*)"$', ligne):
            courante = {"date": m.group(1), "postings": [], "meta": {}}
            transactions.append(courante)
            continue
        assert courante is not None, ligne
        if m := re.match(r'^  ([a-z_]+): "((?:[^"\\]|\\.)*)"$', ligne):
            courante["meta"][m.group(1)] = m.group(2)
            continue
        m = re.match(r"^  (\S+)  (-?\d+\.\d{2}) CAD$", ligne)
        assert m, f"ligne Beancount inattendue : {ligne!r}"
        courante["postings"].append((m.group(1), D(m.group(2))))
    return ouverts, transactions


def test_export_beancount_forme_et_equilibre(reg, plan, taux, tmp_path):
    _comptabiliser(reg, plan, _factures(taux, envoyees=("F-1", "F-2")))
    _accepte(_proposer(reg, plan, ref='M-"1"', libelle='Loyer "octobre" \\ fictif', jour="2026-10-03"))
    chemin = grand_livre_beancount.ecrire_fichier_beancount(tmp_path / "gl.beancount", _etat(reg), plan)
    texte = chemin.read_text(encoding="utf-8")
    assert 'option "operating_currency" "CAD"' in texte and "À valider auprès d'un comptable (CPA)" in texte
    ouverts, transactions = _analyser_beancount(texte)
    assert len(transactions) == 3, "les brouillons ne sont jamais exportés"
    for transaction in transactions:
        assert sum(montant for _compte, montant in transaction["postings"]) == 0
        assert transaction["meta"]["ecriture_id"].startswith("gle-")
        for compte, _montant in transaction["postings"]:
            assert compte in ouverts and ouverts[compte] <= transaction["date"]
    assert "Assets:C1100-Comptes-Clients" in ouverts and "Liabilities:C2300-Tps-A-Percevoir" in ouverts
    assert [t["date"] for t in transactions] == sorted(t["date"] for t in transactions)


def test_export_beancount_refuse_un_grand_livre_altere(reg, plan):
    _accepte(_proposer(reg, plan))
    reg._chain[0]["lignes"][0]["debit"] = D("2.00")
    with pytest.raises(ValueError):
        grand_livre_beancount.exporter_beancount(_etat(reg), plan)


# ============================================================================================ propriété générée
def _cas_genere(alea, comptes):
    """Une écriture aléatoire : équilibrée (montants au cent répartis) ou volontairement faussée d'un cent ou plus."""
    nb_debits, nb_credits = alea.randint(1, 4), alea.randint(1, 4)
    total = D(alea.randint(1, 10_000_000)) / 100
    def repartir(n):
        coupes = sorted(alea.sample(range(1, int(total * 100)), n - 1)) if n > 1 and total * 100 > n else []
        if len(coupes) != n - 1:
            return [total]
        bornes = [0, *coupes, int(total * 100)]
        return [D(b - a) / 100 for a, b in zip(bornes, bornes[1:], strict=False)]
    debits, credits = repartir(nb_debits), repartir(nb_credits)
    variante = alea.random()
    if variante < 0.25:
        credits[-1] += D(alea.choice(["0.01", "-0.01", "1.00", "0.10"]))
    lignes = [L(alea.choice(comptes), f"{m:.2f}") for m in debits]
    lignes += [L(alea.choice(comptes), credit=f"{m:.2f}") for m in credits]
    if variante > 0.95:
        lignes[0]["debit"] = f"{D(lignes[0]['debit']) + D('0.001'):.3f}"
    alea.shuffle(lignes)
    return lignes


def test_propriete_toute_ecriture_acceptee_est_equilibree_sur_des_cas_generes(plan):
    alea = random.Random(20261031)
    comptes = sorted(plan["comptes"])
    reg = registre_module.Registre()
    acceptees = refusees = 0
    for index in range(600):
        lignes = _cas_genere(alea, comptes)
        resultat, refus = _proposer(reg, plan, ref=f"G-{index}", lignes=lignes,
                                    jour=f"2026-{alea.randint(1, 12):02d}-{alea.randint(1, 28):02d}")
        debits = sum((D(li["debit"]) for li in lignes if li["debit"] is not None), D(0))
        credits = sum((D(li["credit"]) for li in lignes if li["credit"] is not None), D(0))
        if refus is None:
            acceptees += 1
            ecriture = resultat["ecriture"]
            assert debits == credits
            assert sum(D(li["debit"] or 0) for li in ecriture["lignes"]) == \
                sum(D(li["credit"] or 0) for li in ecriture["lignes"])
            if alea.random() < 0.7:
                _accepte(_valider(reg, plan, ecriture["ecriture_id"]))
        else:
            refusees += 1
            assert refus["code"] in {"REJ-GL-ECRITURE-DESEQUILIBREE", "REJ-GL-MONTANT-INVALIDE"}
            assert debits != credits or refus["code"] == "REJ-GL-MONTANT-INVALIDE"
    assert acceptees > 300 and refusees > 100, (acceptees, refusees)
    etat = _etat(reg)
    assert etat["anomalies"] == [] and reg.valider_chaine() == (True, "")
    for ecriture in etat["ecritures"].values():
        assert sum(li["debit"] for li in ecriture["lignes"]) == sum(li["credit"] for li in ecriture["lignes"])
    balance = _accepte(grand_livre.balance_verification(etat, plan, "2026-12-31", limite=100))
    assert balance["equilibree"] and balance["total_debits"] == balance["total_credits"]
    _ouverts, transactions = _analyser_beancount(grand_livre_beancount.exporter_beancount(etat, plan))
    assert len(transactions) == etat["definitives"]
    assert all(sum(m for _c, m in t["postings"]) == 0 for t in transactions)
