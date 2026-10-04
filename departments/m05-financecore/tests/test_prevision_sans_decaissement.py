"""PLAN T4.16-d : la prévision de trésorerie ne fait JAMAIS bouger d'argent. Aucun paiement, aucune remise, aucune
déclaration, aucune paie, aucun décaissement, aucune écriture : c'est de l'argent réel et un acte fiscal (N5, Nathan ET
le CPA, ADR-0009 §5). Le code de T4.16-d lit, date, calcule et propose.

La garde AST `conformite.verifier_aucun_decaissement` (T4.15, T4.16) couvre le nouveau code, en deux régimes :
- STRICT (aucun mot de mouvement, aucun import du registre des mouvements) pour `prevision.py` et pour les aides
  d'`outils.py` qui lisent les registres (`_lectures_finance`, `_resultat_cash_libre`, `_dettes_fournisseurs`,
  `_reglages_prevision`, `_page_prevision`) ;
- LECTURE SEULE pour `prevoir_tresorerie`, qui OUVRE le registre des mouvements pour en tirer le solde : le lire est
  permis, l'écrire ou faire bouger de l'argent ne l'est pas.

Chaque violation injectée, dans du code inventé et dans des copies des VRAIS fichiers, est nommée. Fictif (AGENTS.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import conformite

from opsys.outils import Autonomie

FICTIF = True
_RACINE_M5 = Path(__file__).resolve().parents[1]
_PAQUET = _RACINE_M5 / "src" / "m5_financecore"
_AIDES = ("_lectures_finance", "_resultat_cash_libre", "_dettes_fournisseurs", "_reglages_prevision", "_page_prevision")


# --------------------------------------------------------------------------------------- 1. le vrai paquet
def test_le_vrai_paquet_est_conforme_aux_deux_regimes():
    assert conformite.verifier_aucun_decaissement(_PAQUET) == (True, "")


def test_le_nouveau_code_est_dans_la_portee_de_la_garde():
    strict = conformite._SURVEILLE_SANS_DECAISSEMENT
    lecture = conformite._SURVEILLE_EN_LECTURE_SEULE

    assert strict["prevision"] is None and (_PAQUET / "prevision.py").is_file(), "le module pur entier"
    assert set(_AIDES) <= set(strict["outils"]), "les aides qui lisent les registres : en strict"
    assert "prevoir_tresorerie" in lecture["outils"] and "prevoir_tresorerie" not in strict["outils"]
    assert "comptes_a_payer" in strict and strict["comptes_a_payer"] is None, "dettes_datables : le module entier"


def test_chaque_fonction_surveillee_du_nouveau_code_existe_un_renommage_ne_desarme_pas_la_garde():
    source = (_PAQUET / "outils.py").read_text(encoding="utf-8")

    for nom in (*_AIDES, "prevoir_tresorerie"):
        assert re.search(rf"^def {re.escape(nom)}\(", source, re.MULTILINE), nom


def test_le_module_pur_de_la_prevision_n_importe_ni_le_registre_ni_un_autre_departement():
    source = (_PAQUET / "prevision.py").read_text(encoding="utf-8")

    imports = re.findall(r"^(?:from|import)\s+(.+)$", source, re.MULTILINE)
    assert imports == ["__future__ import annotations", "json", "re", "collections.abc import Iterable, Mapping",
                       "datetime import date, datetime, timedelta",
                       "decimal import ROUND_HALF_UP, Context, Decimal, localcontext",
                       "typing import Any", ". import analyse, calendrier_fiscal, cash_libre, encodage, validation"]
    assert conformite.verifier_aucun_import_domaine(_PAQUET) == (True, "")


def test_le_module_de_la_prevision_n_a_ni_horloge_ni_alea_ni_reseau():
    """La conformité générale du paquet (aucune horloge, aucun aléa, aucun réseau, aucun littéral de coût)."""
    rapport = conformite.verifier_conformite(_PAQUET)

    assert rapport["conforme"] is True, rapport["violations"]
    source = (_PAQUET / "prevision.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(now|today|utcnow|monotonic|time_ns)\s*\(", source)
    assert conformite.verifier_arrondi_monetaire_explicite(_PAQUET) == (True, "")


def test_les_aides_de_l_adaptateur_et_le_module_pur_ne_nomment_pas_le_registre_des_mouvements():
    outils = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    corps = outils[outils.index("def _reglages_prevision("):outils.index("def prevoir_tresorerie(")]
    corps_lectures = outils[outils.index("def _lectures_finance("):outils.index("def _taxes_par_echeance(")]

    for texte in (corps, corps_lectures, (_PAQUET / "prevision.py").read_text(encoding="utf-8")):
        assert "_registre_mouvements" not in texte and "enregistrer_mouvement" not in texte
        assert not re.search(r"^\s*(from|import)\b.*\bregistre\b", texte, re.MULTILINE)


def test_seul_l_outil_ouvre_le_registre_des_mouvements_et_le_passe_aux_aides():
    outils = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    corps = outils[outils.index("def prevoir_tresorerie("):outils.index("def _recevoir_variance_chantier(")]

    assert "_registre_mouvements(None)" in corps and "_page_prevision(_registre_mouvements(None), reglages)" in corps


# -------------------------------------------------------- 2. régime STRICT, sur du code inventé (le module pur)
def _garde(tmp_path, sources, surveille=None, lecture_seule=None):
    for nom, contenu in sources.items():
        (tmp_path / f"{nom}.py").write_text(contenu, encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path, surveille, lecture_seule)


@pytest.mark.parametrize("ligne, attendu", [
    ("from . import registre", "importe registre.py"),
    ("from .registre import enregistrer_mouvement", "importe registre.py"),
    ("enregistrer_mouvement(x, y)", "nomme enregistrer_mouvement"),
    ("_registre_mouvements(None)", "nomme _registre_mouvements"),
    ("_etat_mouvements(None, reg)", "nomme _etat_mouvements"),
    ("stockage.maillons('d', 'principal')", "porte le texte 'principal'"),
    ("x = 'DECAISSEMENT'", "porte le texte 'DECAISSEMENT'"),
    ("x = 'ENCAISSEMENT'", "porte le texte 'ENCAISSEMENT'"),
    ("x = 'PROVISION'", "porte le texte 'PROVISION'"),
    ("x = 'AJUSTEMENT'", "porte le texte 'AJUSTEMENT'"),
    ("x = {'type_entree': 'mouvement_enregistre'}", "porte le texte 'mouvement_enregistre'"),
    ("x = {'type_mouvement': 'AUTRE'}", "porte le texte 'type_mouvement'"),
])
def test_chaque_violation_injectee_dans_le_module_pur_de_la_prevision_est_nommee(tmp_path, ligne, attendu):
    conforme, detail = _garde(tmp_path, {"prevision": f"def f(x, y, reg):\n    {ligne}\n"}, {"prevision": None})

    assert conforme is False and attendu in detail and "prevision.py:2" in detail


def test_un_docstring_qui_mentionne_le_mot_n_est_pas_une_violation_du_regime_strict(tmp_path):
    source = '"""Aucun DECAISSEMENT, aucune remise, jamais de mouvement_enregistre : payer est N5."""\n\nx = 1\n'

    assert _garde(tmp_path, {"prevision": source}, {"prevision": None}) == (True, "")


def test_un_module_de_prevision_absent_est_une_violation_la_garde_ne_se_desarme_pas(tmp_path):
    conforme, detail = _garde(tmp_path, {}, {"prevision": None})

    assert conforme is False and "prevision.py: module surveillé illisible" in detail


# ------------------------------------------------------- 3. régime LECTURE SEULE, sur du code inventé (l'outil)
def test_lire_le_registre_des_mouvements_est_permis_dans_l_outil_de_prevision(tmp_path):
    source = (
        "def prevoir_tresorerie(aujourd_hui, reglages):\n"
        "    page, verdict = _page_prevision(_registre_mouvements(None), reglages)\n"
        "    return page, verdict, soldes.calculer_solde(_registre_mouvements(None))\n"
    )

    assert _garde(tmp_path, {"outils": source}, {}, {"outils": ("prevoir_tresorerie",)}) == (True, "")


@pytest.mark.parametrize("ligne, attendu", [
    ("enregistrer_mouvement(x, y)", "nomme enregistrer_mouvement"),
    ("registre_module.enregistrer_mouvement(x, y)", "nomme enregistrer_mouvement"),
    ("registre_mouvements.ajouter({})", "nomme ajouter"),
    ("reg.lire().append({})", "nomme append"),
    ("reg._chain.extend([])", "nomme extend"),
    ("reg.insert(0, {})", "nomme insert"),
    ("x = reg._chain", "nomme _chain"),
    ("enregistrer_paiement_facture('F-1', '1.00', 'n', 'h', reg)", "nomme enregistrer_paiement_facture"),
    ("facturation.marquer_facture_payee('F-1', 'n', 'h', reg)", "nomme marquer_facture_payee"),
    ("facturation.envoyer_facture('F-1', 'h', reg)", "nomme envoyer_facture"),
    ("comptes_a_payer.saisir_facture_fournisseur()", "nomme saisir_facture_fournisseur"),
    ("comptes_a_payer.enregistrer_reception(x, reg)", "nomme enregistrer_reception"),
    ("facturation.creer_facture_brouillon()", "nomme creer_facture_brouillon"),
    ("executer_atomique(outil, {})", "nomme executer_atomique"),
    ("from .registre import enregistrer_mouvement", "importe enregistrer_mouvement"),
])
def test_chaque_ecriture_ou_mouvement_d_argent_injecte_dans_l_outil_de_prevision_est_nomme(tmp_path, ligne, attendu):
    source = f"def prevoir_tresorerie(x, y, reg, registre_mouvements, outil):\n    {ligne}\n"

    conforme, detail = _garde(tmp_path, {"outils": source}, {}, {"outils": ("prevoir_tresorerie",)})

    assert conforme is False and attendu in detail and "prevoir_tresorerie()" in detail


def test_une_fonction_de_lecture_seule_de_l_outil_qui_disparait_est_une_violation(tmp_path):
    conforme, detail = _garde(tmp_path, {"outils": "def autre():\n    return 1\n"}, {},
                              {"outils": ("prevoir_tresorerie",)})

    assert conforme is False and "fonction surveillée introuvable : prevoir_tresorerie" in detail


# ---------------------------------------------------------------- 4. sur des copies des VRAIS fichiers
_FICHIERS = (
    "comptes_a_payer",
    "calendrier_fiscal",
    "calendrier_obligations",
    "cash_libre",
    "prevision",
    "constat_cash_libre",
    "analyse",
    "outils",
    "soldes",
    "etat_financier",
)


def _sur_les_vrais_fichiers(tmp_path, modifier):
    for nom in _FICHIERS:
        texte = (_PAQUET / f"{nom}.py").read_text(encoding="utf-8")
        (tmp_path / f"{nom}.py").write_text(modifier(nom, texte), encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path)


def _ajouter(nom_du_fichier, ajout):
    return lambda nom, texte: texte + ajout if nom == nom_du_fichier else texte


def _dans_outils(ancre, insertion):
    def modifier(nom, texte):
        if nom != "outils":
            return texte
        assert ancre in texte, ancre
        return texte.replace(ancre, ancre + insertion, 1)
    return modifier


def test_les_vrais_fichiers_copies_tels_quels_sont_conformes(tmp_path):
    assert _sur_les_vrais_fichiers(tmp_path, lambda _nom, texte: texte) == (True, "")


def test_un_decaissement_glisse_dans_le_vrai_module_de_prevision_est_attrape(tmp_path):
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _ajouter("prevision", '\n\ndef _piege():\n    return {"type_mouvement": "DECAISSEMENT"}\n'))

    assert conforme is False and "prevision.py" in detail and "DECAISSEMENT" in detail and "type_mouvement" in detail


def test_l_import_du_registre_dans_le_vrai_module_de_prevision_est_attrape(tmp_path):
    def modifier(nom, texte):
        ancre = "from . import analyse, calendrier_fiscal, cash_libre, encodage, validation"
        if nom != "prevision":
            return texte
        assert ancre in texte
        return texte.replace(
            ancre, "from . import analyse, calendrier_fiscal, cash_libre, encodage, registre, validation")

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "prevision.py" in detail and "importe registre.py" in detail


def test_l_enregistrement_d_un_mouvement_glisse_dans_la_vraie_prevision_est_attrape(tmp_path):
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _ajouter("prevision", "\n\ndef _piege(reg):\n    enregistrer_mouvement({}, reg)\n"))

    assert conforme is False and "prevision.py" in detail and "nomme enregistrer_mouvement" in detail


@pytest.mark.parametrize("aide, ancre", [
    ("_page_prevision", "    lectures = _lectures_finance(registre_mouvements, reglages[\"configuration\"])\n"),
    ("_reglages_prevision", "    jour, verdict = prevision.lire_jour(aujourd_hui)\n"),
    ("_dettes_fournisseurs", "    if lectures[\"dictionnaire_taux\"] is None:\n"),
])
def test_un_acces_au_registre_des_mouvements_glisse_dans_une_aide_de_la_prevision_est_attrape(tmp_path, aide, ancre):
    def modifier(nom, texte):
        if nom != "outils":
            return texte
        assert ancre in texte, ancre
        return texte.replace(ancre, "    _registre_mouvements(None)\n" + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and f"{aide}()" in detail and "nomme _registre_mouvements" in detail


def test_un_texte_de_mouvement_glisse_dans_la_vraie_lecture_des_registres_est_attrape(tmp_path):
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _dans_outils("    declarees = declarees if isinstance(declarees, dict) else {}\n",
                               "    type_du_geste = 'DECAISSEMENT'\n"))

    assert conforme is False and "_lectures_finance()" in detail and "porte le texte 'DECAISSEMENT'" in detail


def test_une_ecriture_glissee_dans_la_vraie_fonction_de_l_outil_est_attrapee_en_lecture_seule(tmp_path):
    ancre = "    page, verdict = _page_prevision(_registre_mouvements(None), reglages)\n"

    for insertion, mot in (("    _registre_mouvements(None).ajouter({})\n", "ajouter"),
                           ("    enregistrer_mouvement({}, None)\n", "enregistrer_mouvement"),
                           ("    facturation.enregistrer_paiement_facture('F', '1', 'n', 'h', None)\n",
                            "enregistrer_paiement_facture"),
                           ("    reglages.setdefault('x', []).append(1)\n", "append")):
        def modifier(nom, texte, insertion=insertion):
            if nom != "outils":
                return texte
            assert ancre in texte
            return texte.replace(ancre, insertion + ancre, 1)

        dossier = tmp_path / mot
        dossier.mkdir()
        conforme, detail = _sur_les_vrais_fichiers(dossier, modifier)

        assert conforme is False and "prevoir_tresorerie()" in detail and f"nomme {mot}" in detail, mot


def test_un_paiement_glisse_dans_le_vrai_etat_de_tresorerie_reste_attrape_et_la_prevision_ne_le_desarme_pas(tmp_path):
    def modifier(nom, texte):
        ancre = "    registre_cible = _registre_mouvements(mouvements_historique)\n    etat = etat_financier."
        if nom != "outils":
            return texte
        assert ancre in texte
        return texte.replace(
            ancre, "    facturation.enregistrer_paiement_facture('F', '1', 'n', 'h', None)\n" + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "etat_tresorerie()" in detail and "enregistrer_paiement_facture" in detail


def test_un_mouvement_glisse_dans_la_vraie_liste_des_dettes_est_attrape(tmp_path):
    """`comptes_a_payer.py` est surveillé en entier : `dettes_datables` y est couverte."""
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _ajouter("comptes_a_payer", "\n\ndef _piege():\n    return 'PROVISION'\n"))

    assert conforme is False and "comptes_a_payer.py" in detail and "porte le texte 'PROVISION'" in detail


# ---------------------------------------------------------------- 5. aucun outil de plus ne déplace de l'argent
def test_l_outil_de_prevision_est_de_lecture_les_seuls_outils_t3_restent_les_deux_d_avant():
    par_nom = {o.nom: o for o in m5_outils.outils()}

    assert par_nom["m5_prevoir_tresorerie"].autonomie is Autonomie.T0
    assert {nom for nom, o in par_nom.items() if o.autonomie is Autonomie.T3} == {
        "m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture"}
    verbes = r"(remise|remet|paye|paiement|decaisse|virement|rembours|declar)"
    argent = {nom for nom in par_nom if re.search(verbes, nom)}
    assert argent == {"m5_enregistrer_paiement_facture", "m5_lister_comptes_a_payer"}, "aucun outil de remise"


def test_la_description_de_l_outil_dit_qu_il_ne_paie_ni_ne_projette():
    description = {o.nom: o for o in m5_outils.outils()}["m5_prevoir_tresorerie"].description

    for morceau in ("Aucune projection", "aucune vente future", "jamais zéro", "Lecture pure", "Analyse préparatoire"):
        assert morceau in description, morceau
    assert not re.search(r"\b(paye|payer|remet|virer|verse)\b", description)
