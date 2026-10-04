"""PLAN T4.19-b : le constat du cash libre ne fait JAMAIS bouger d'argent. Aucun paiement, aucune remise, aucune
déclaration, aucune paie, aucun décaissement, aucune écriture au grand livre : c'est de l'argent réel et un acte fiscal
(N5, Nathan ET le CPA, ADR-0009 §5). Le code de T4.19-b lit, calcule, trace son propre constat et le publie.

La garde AST `conformite.verifier_aucun_decaissement` (T4.15, T4.16, T4.16-d) couvre le nouveau code, en deux régimes :
- STRICT (aucun mot de mouvement, aucun import du registre des mouvements) pour `constat_cash_libre.py` (pur) et pour
  `_constater_cash_libre`, qui reçoit le registre des mouvements déjà ouvert, ne le nomme pas et n'écrit qu'au registre
  dérivé des constats et au bus ;
- LECTURE SEULE pour `constater_cash_libre`, qui OUVRE le registre des mouvements pour en tirer le solde : le lire est
  permis, l'écrire ou faire bouger de l'argent ne l'est pas. L'écriture du constat est donc, exprès, dans l'autre
  fonction.

Chaque violation injectée, dans du code inventé et dans des copies des VRAIS fichiers, est nommée. Fictif (AGENTS.md).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import conformite

from opsys.outils import Autonomie

FICTIF = True
_RACINE_M5 = Path(__file__).resolve().parents[1]
_PAQUET = _RACINE_M5 / "src" / "m5_financecore"


# --------------------------------------------------------------------------------------- 1. le vrai paquet
def test_le_vrai_paquet_est_conforme_aux_deux_regimes():
    assert conformite.verifier_aucun_decaissement(_PAQUET) == (True, "")


def test_le_nouveau_code_est_dans_la_portee_de_la_garde():
    strict = conformite._SURVEILLE_SANS_DECAISSEMENT
    lecture = conformite._SURVEILLE_EN_LECTURE_SEULE

    assert strict["constat_cash_libre"] is None and (_PAQUET / "constat_cash_libre.py").is_file(), "le module entier"
    assert "_constater_cash_libre" in strict["outils"], "l'écriture du constat : en strict"
    assert "constater_cash_libre" in lecture["outils"] and "constater_cash_libre" not in strict["outils"]
    assert "_constater_cash_libre" not in lecture["outils"]


def test_chaque_fonction_surveillee_du_nouveau_code_existe_un_renommage_ne_desarme_pas_la_garde():
    source = (_PAQUET / "outils.py").read_text(encoding="utf-8")

    for nom in ("_constater_cash_libre", "constater_cash_libre"):
        assert re.search(rf"^def {re.escape(nom)}\(", source, re.MULTILINE), nom


def test_le_module_pur_du_constat_n_importe_ni_le_registre_ni_un_autre_departement():
    source = (_PAQUET / "constat_cash_libre.py").read_text(encoding="utf-8")

    imports = re.findall(r"^(?:from|import)\s+(.+)$", source, re.MULTILINE)
    assert imports == ["__future__ import annotations", "re", "collections.abc import Mapping", "datetime import date",
                       "typing import Any", ". import cash_libre, validation"]
    assert conformite.verifier_aucun_import_domaine(_PAQUET) == (True, "")


def test_le_module_du_constat_n_a_ni_horloge_ni_alea_ni_reseau_ni_litteral_de_cout():
    rapport = conformite.verifier_conformite(_PAQUET)

    assert rapport["conforme"] is True, rapport["violations"]
    source = (_PAQUET / "constat_cash_libre.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(now|today|utcnow|monotonic|time_ns)\s*\(", source)
    assert "quantize" not in source and "float(" not in source, "aucun arrondi, aucun flottant : rien n'est calculé"
    assert conformite.verifier_arrondi_monetaire_explicite(_PAQUET) == (True, "")
    assert conformite.verifier_aucune_cause_signalee(_PAQUET) == (True, "")


def test_le_module_pur_ne_fait_aucune_arithmetique_sur_un_montant():
    """Un montant passe du calcul à la charge par sa lecture (`vue_cash_libre`), jamais par une opération."""
    arbre = ast.parse((_PAQUET / "constat_cash_libre.py").read_text(encoding="utf-8"))

    arithmetique = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    operations = [n for n in ast.walk(arbre)
                  if (isinstance(n, ast.BinOp) and isinstance(n.op, arithmetique)) or isinstance(n, ast.AugAssign)]
    assert operations == [], "aucun `+`, `-`, `*` ni `/` dans le module (le `|` d'une annotation n'en est pas une)"
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    assert not {"Decimal", "float", "round", "sum"} & noms


def test_seul_l_outil_ouvre_le_registre_des_mouvements_et_le_passe_a_la_fonction_qui_ecrit():
    outils = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    ecrit = outils[outils.index("def _constater_cash_libre("):outils.index("def constater_cash_libre(")]
    outil = outils[outils.index("def constater_cash_libre("):outils.index("def _recevoir_variance_chantier(")]

    assert "_registre_mouvements" not in ecrit and "enregistrer_mouvement" not in ecrit
    assert "principal" not in ecrit and "_NOM_REGISTRE_MOUVEMENTS" not in ecrit
    assert "_NOM_REGISTRE_CONSTATS" in ecrit and ".append(" in ecrit and "evenements.publier(" in ecrit
    assert "_constater_cash_libre(_registre_mouvements(None), jour)" in outil
    assert ".append(" not in outil and "evenements.publier(" not in outil, "la lecture seule n'écrit pas"


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
def test_chaque_violation_injectee_dans_le_module_pur_du_constat_est_nommee(tmp_path, ligne, attendu):
    conforme, detail = _garde(tmp_path, {"constat_cash_libre": f"def f(x, y, reg):\n    {ligne}\n"},
                              {"constat_cash_libre": None})

    assert conforme is False and attendu in detail and "constat_cash_libre.py:2" in detail


def test_un_docstring_qui_mentionne_le_mot_n_est_pas_une_violation_du_regime_strict(tmp_path):
    source = '"""Aucun DECAISSEMENT, aucune remise, jamais de mouvement_enregistre : payer est N5."""\n\nx = 1\n'

    assert _garde(tmp_path, {"constat_cash_libre": source}, {"constat_cash_libre": None}) == (True, "")


def test_un_module_du_constat_absent_est_une_violation_la_garde_ne_se_desarme_pas(tmp_path):
    conforme, detail = _garde(tmp_path, {}, {"constat_cash_libre": None})

    assert conforme is False and "constat_cash_libre.py: module surveillé illisible" in detail


# ------------------------------------------------- 3. régime STRICT, sur la fonction qui écrit la trace et publie
def test_la_fonction_qui_ecrit_le_constat_peut_ecrire_son_registre_et_publier_mais_rien_de_plus(tmp_path):
    source = (
        "def _constater_cash_libre(registre_mouvements, jour):\n"
        "    constats = stockage.maillons('m05-financecore', 'constats_cash_libre')\n"
        "    constats.append({'type_entree': 'cash_libre_constate'})\n"
        "    evenements.publier('m5.cash_libre_constate', 'm05-financecore', {}, evenement_id='x')\n"
    )

    assert _garde(tmp_path, {"outils": source}, {"outils": ("_constater_cash_libre",)}) == (True, "")


@pytest.mark.parametrize("ligne, attendu", [
    ("_registre_mouvements(None)", "nomme _registre_mouvements"),
    ("enregistrer_mouvement({}, registre_mouvements)", "nomme enregistrer_mouvement"),
    ("stockage.maillons('m05-financecore', 'principal').append({})", "porte le texte 'principal'"),
    ("x = _NOM_REGISTRE_MOUVEMENTS", "nomme _NOM_REGISTRE_MOUVEMENTS"),
    ("x = {'type_mouvement': 'DECAISSEMENT'}", "porte le texte 'DECAISSEMENT'"),
    ("x = 'PROVISION'", "porte le texte 'PROVISION'"),
])
def test_un_mouvement_glisse_dans_la_fonction_qui_ecrit_le_constat_est_nomme(tmp_path, ligne, attendu):
    source = f"def _constater_cash_libre(registre_mouvements, jour):\n    {ligne}\n"

    conforme, detail = _garde(tmp_path, {"outils": source}, {"outils": ("_constater_cash_libre",)})

    assert conforme is False and attendu in detail and "_constater_cash_libre()" in detail


# ------------------------------------------------------- 4. régime LECTURE SEULE, sur du code inventé (l'outil)
def test_lire_le_registre_des_mouvements_est_permis_dans_l_outil_du_constat(tmp_path):
    source = (
        "def constater_cash_libre(aujourd_hui, jour):\n"
        "    constat = _constater_cash_libre(_registre_mouvements(None), jour)\n"
        "    return constat, soldes.calculer_solde(_registre_mouvements(None))\n"
    )

    assert _garde(tmp_path, {"outils": source}, {}, {"outils": ("constater_cash_libre",)}) == (True, "")


@pytest.mark.parametrize("ligne, attendu", [
    ("enregistrer_mouvement(x, y)", "nomme enregistrer_mouvement"),
    ("registre_mouvements.ajouter({})", "nomme ajouter"),
    ("constats.append({})", "nomme append"),
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
def test_chaque_ecriture_ou_mouvement_d_argent_injecte_dans_l_outil_du_constat_est_nomme(tmp_path, ligne, attendu):
    source = f"def constater_cash_libre(x, y, reg, registre_mouvements, constats, outil):\n    {ligne}\n"

    conforme, detail = _garde(tmp_path, {"outils": source}, {}, {"outils": ("constater_cash_libre",)})

    assert conforme is False and attendu in detail and "constater_cash_libre()" in detail


def test_une_fonction_de_lecture_seule_de_l_outil_qui_disparait_est_une_violation(tmp_path):
    conforme, detail = _garde(tmp_path, {"outils": "def autre():\n    return 1\n"}, {},
                              {"outils": ("constater_cash_libre",)})

    assert conforme is False and "fonction surveillée introuvable : constater_cash_libre" in detail


# ---------------------------------------------------------------- 5. sur des copies des VRAIS fichiers
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


def test_un_decaissement_glisse_dans_le_vrai_module_du_constat_est_attrape(tmp_path):
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _ajouter("constat_cash_libre", '\n\ndef _piege():\n    return {"type_mouvement": "DECAISSEMENT"}\n'))

    assert conforme is False and "constat_cash_libre.py" in detail and "DECAISSEMENT" in detail
    assert "type_mouvement" in detail


def test_l_import_du_registre_dans_le_vrai_module_du_constat_est_attrape(tmp_path):
    def modifier(nom, texte):
        ancre = "from . import cash_libre, validation"
        if nom != "constat_cash_libre":
            return texte
        assert ancre in texte
        return texte.replace(ancre, "from . import cash_libre, registre, validation")

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "constat_cash_libre.py" in detail and "importe registre.py" in detail


def test_l_enregistrement_d_un_mouvement_glisse_dans_le_vrai_module_du_constat_est_attrape(tmp_path):
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _ajouter("constat_cash_libre", "\n\ndef _piege(reg):\n    enregistrer_mouvement({}, reg)\n"))

    assert conforme is False and "constat_cash_libre.py" in detail and "nomme enregistrer_mouvement" in detail


@pytest.mark.parametrize("insertion, attendu", [
    ("    _registre_mouvements(None)\n", "nomme _registre_mouvements"),
    ("    enregistrer_mouvement({}, registre_mouvements)\n", "nomme enregistrer_mouvement"),
    ("    type_du_geste = 'DECAISSEMENT'\n", "porte le texte 'DECAISSEMENT'"),
    ("    stockage.maillons(_DEPARTEMENT, 'principal').append({})\n", "porte le texte 'principal'"),
])
def test_un_acces_aux_mouvements_glisse_dans_la_vraie_fonction_qui_ecrit_le_constat_est_attrape(
        tmp_path, insertion, attendu):
    ancre = "    resultat = _resultat_cash_libre(_lectures_finance(registre_mouvements))\n    constats = "

    def modifier(nom, texte):
        if nom != "outils":
            return texte
        assert ancre in texte, ancre
        return texte.replace(ancre, insertion + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "_constater_cash_libre()" in detail and attendu in detail


def test_une_ecriture_glissee_dans_la_vraie_fonction_de_l_outil_est_attrapee_en_lecture_seule(tmp_path):
    ancre = "    constat = _constater_cash_libre(_registre_mouvements(None), jour)\n"

    for insertion, mot in (("    _registre_mouvements(None).ajouter({})\n", "ajouter"),
                           ("    enregistrer_mouvement({}, None)\n", "enregistrer_mouvement"),
                           ("    facturation.enregistrer_paiement_facture('F', '1', 'n', 'h', None)\n",
                            "enregistrer_paiement_facture"),
                           ("    vue.setdefault('x', []).append(1)\n", "append")):
        def modifier(nom, texte, insertion=insertion):
            if nom != "outils":
                return texte
            assert ancre in texte
            return texte.replace(ancre, insertion + ancre, 1)

        dossier = tmp_path / mot
        dossier.mkdir()
        conforme, detail = _sur_les_vrais_fichiers(dossier, modifier)

        assert conforme is False and "constater_cash_libre()" in detail and f"nomme {mot}" in detail, mot


def test_une_ecriture_glissee_dans_les_aides_de_la_lecture_des_registres_reste_attrapee(tmp_path):
    """Les aides que le constat partage avec le cash libre et la prévision sont en STRICT : le constat ne les désarme
    pas."""
    conforme, detail = _sur_les_vrais_fichiers(
        tmp_path, _dans_outils("    declarees = declarees if isinstance(declarees, dict) else {}\n",
                               "    type_du_geste = 'DECAISSEMENT'\n"))

    assert conforme is False and "_lectures_finance()" in detail and "porte le texte 'DECAISSEMENT'" in detail


# ---------------------------------------------------------------- 6. aucun outil de plus ne déplace de l'argent
def test_l_outil_du_constat_est_une_ecriture_interne_les_seuls_outils_t3_restent_les_deux_d_avant():
    par_nom = {o.nom: o for o in m5_outils.outils()}

    assert par_nom["m5_constater_cash_libre"].autonomie is Autonomie.T1
    assert {nom for nom, o in par_nom.items() if o.autonomie is Autonomie.T3} == {
        "m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture"}
    verbes = r"(remise|remet|paye|paiement|decaisse|virement|rembours|declar)"
    argent = {nom for nom in par_nom if re.search(verbes, nom)}
    assert argent == {"m5_enregistrer_paiement_facture", "m5_lister_comptes_a_payer"}, "aucun outil de remise"


def test_la_description_de_l_outil_dit_qu_il_ne_paie_ni_ne_remet_ni_n_ecrit_aux_mouvements():
    description = {o.nom: o for o in m5_outils.outils()}["m5_constater_cash_libre"].description

    for morceau in ("aucun paiement", "aucune remise", "aucune écriture aux mouvements", "jamais zéro",
                    "Analyse préparatoire", "Écriture interne (T1)"):
        assert morceau in description, morceau
    assert not re.search(r"\b(paye|payer|remet|virer|verse)\b", description)
