"""PLAN T4.16 : le calendrier fiscal et le cash libre ne font JAMAIS bouger d'argent. Aucune remise à Revenu Québec,
aucune déclaration, aucun paiement, aucune paie, aucun décaissement : c'est de l'argent réel et un acte fiscal (N5,
Nathan ET le CPA, ADR-0009 §5). Le code de T4.16 lit, calcule et propose.

La garde AST `conformite.verifier_aucun_decaissement` (T4.15) couvre le nouveau code, en deux régimes :
- STRICT (aucun mot de mouvement, aucun import du registre des mouvements) pour `calendrier_fiscal.py`,
  `cash_libre.py`, `analyse.py` et les fonctions d'`outils.py` qui lisent le calendrier et les registres (dont
  `_cash_libre`, qui reçoit le registre des mouvements déjà ouvert) ;
- LECTURE SEULE pour le code qui OUVRE le registre des mouvements afin d'en tirer le solde (`soldes.py`,
  `etat_financier.py`, `etat_tresorerie`) : le lire est permis, l'écrire ou faire bouger de l'argent ne l'est pas.

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


# --------------------------------------------------------------------------------- 1. le vrai paquet
def test_le_vrai_paquet_est_conforme_aux_deux_regimes():
    assert conformite.verifier_aucun_decaissement(_PAQUET) == (True, "")


def test_la_garde_surveille_ce_qu_elle_dit_surveiller_les_fonctions_existent():
    """Un renommage ne doit pas désarmer la garde en silence : chaque fonction surveillée existe dans le vrai
    `outils.py`."""
    source = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    for table in (conformite._SURVEILLE_SANS_DECAISSEMENT, conformite._SURVEILLE_EN_LECTURE_SEULE):
        for nom in table["outils"]:
            assert re.search(rf"^def {re.escape(nom)}\(", source, re.MULTILINE), nom


def test_le_nouveau_code_est_dans_la_portee_de_la_garde():
    strict = conformite._SURVEILLE_SANS_DECAISSEMENT
    lecture = conformite._SURVEILLE_EN_LECTURE_SEULE

    for module in ("calendrier_fiscal", "calendrier_obligations", "cash_libre", "analyse", "comptes_a_payer"):
        assert strict[module] is None and (_PAQUET / f"{module}.py").is_file(), f"{module} : le module entier"
    assert {
        "lire_echeances_fiscales",
        "lire_calendrier_obligations",
        "_taxes_par_echeance",
        "_calendrier_fiscal",
        "_configuration_manifeste",
        "_cash_libre",
    } <= set(strict["outils"])
    # T4.16-d : la prévision ouvre elle aussi le registre des mouvements pour en tirer le solde (lecture seule) ;
    # T4.19-b : le constat aussi (`constater_cash_libre`), qui confie son écriture à une fonction en strict
    assert set(lecture["outils"]) == {"etat_tresorerie", "prevoir_tresorerie", "constater_cash_libre"}
    assert lecture["soldes"] is None and lecture["etat_financier"] is None


def test_seuls_etat_tresorerie_et_prevoir_tresorerie_ouvrent_le_registre_des_mouvements_le_reste_ne_le_nomme_pas():
    """Ce qui justifie deux régimes : `etat_tresorerie` et (T4.16-d) `prevoir_tresorerie` nomment l'adaptateur des
    mouvements (ils ouvrent le registre pour en tirer le solde) et le passent à `_cash_libre` ou `_page_prevision` ; ni
    ces aides, ni le module pur du cash libre, ni ceux du calendrier et de la prévision ne le nomment (le solde leur est
    apporté déjà calculé)."""
    outils = (_PAQUET / "outils.py").read_text(encoding="utf-8")
    corps_etat = outils[outils.index("def etat_tresorerie("):outils.index("def calculer_taxes_tps_tvq(")]
    debut_lectures = outils.index("def _lectures_finance(")
    corps_cash = outils[debut_lectures:outils.index("def _taxes_par_echeance(")]
    debut_prevision = outils.index("def _reglages_prevision(")
    corps_prevision = outils[debut_prevision:outils.index("def prevoir_tresorerie(")]
    corps_outil = outils[outils.index("def prevoir_tresorerie("):outils.index("def _recevoir_variance_chantier(")]
    assert "_registre_mouvements(mouvements_historique)" in corps_etat
    assert "_registre_mouvements(None)" in corps_outil
    for corps in (corps_cash, corps_prevision):
        assert "_registre_mouvements" not in corps and "principal" not in corps
    for module in ("cash_libre", "calendrier_fiscal", "analyse", "prevision"):
        texte = (_PAQUET / f"{module}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\b.*\bregistre\b", texte, re.MULTILINE), module
    for module in ("cash_libre", "calendrier_fiscal", "prevision"):
        texte = (_PAQUET / f"{module}.py").read_text(encoding="utf-8")
        assert "enregistrer_mouvement" not in texte and "_registre_mouvements" not in texte, module


# ---------------------------------------------------------------- 2. régime STRICT, sur du code inventé
def _garde(tmp_path, sources, surveille=None, lecture_seule=None):
    for nom, contenu in sources.items():
        (tmp_path / f"{nom}.py").write_text(contenu, encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path, surveille, lecture_seule)


@pytest.mark.parametrize("module", ["calendrier_fiscal", "cash_libre", "analyse"])
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
def test_chaque_violation_injectee_dans_le_nouveau_code_pur_est_nommee(tmp_path, module, ligne, attendu):
    conforme, detail = _garde(tmp_path, {module: f"def f(x, y, reg):\n    {ligne}\n"}, {module: None})

    assert conforme is False and attendu in detail and f"{module}.py:2" in detail


def test_un_docstring_qui_mentionne_le_mot_n_est_pas_une_violation_du_regime_strict(tmp_path):
    source = '"""Aucun DECAISSEMENT, aucune remise, jamais de mouvement_enregistre : payer est N5."""\n\nx = 1\n'

    assert _garde(tmp_path, {"cash_libre": source}, {"cash_libre": None}) == (True, "")


# -------------------------------------------------------- 3. régime LECTURE SEULE, sur du code inventé
def test_lire_le_registre_des_mouvements_est_permis_en_lecture_seule(tmp_path):
    source = (
        "def etat_tresorerie(registre_mouvements):\n"
        "    maillons = registre_mouvements.lire()\n"
        "    solde = soldes.calculer_solde(_registre_mouvements(None))\n"
        "    provisions, nombre, derniere = soldes.calculer_provisions(registre_module.Registre(maillons=maillons))\n"
        "    return solde, provisions, [m for m in maillons if m.get('type_entree') == 'mouvement_enregistre']\n"
    )

    assert _garde(tmp_path, {"outils": source}, {}, {"outils": ("etat_tresorerie",)}) == (True, "")


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
def test_chaque_ecriture_ou_mouvement_d_argent_injecte_en_lecture_seule_est_nomme(tmp_path, ligne, attendu):
    source = f"def etat_tresorerie(x, y, reg, registre_mouvements, outil):\n    {ligne}\n"

    conforme, detail = _garde(tmp_path, {"outils": source}, {}, {"outils": ("etat_tresorerie",)})

    assert conforme is False and attendu in detail and "etat_tresorerie()" in detail


def test_en_lecture_seule_seules_les_fonctions_surveillees_comptent(tmp_path):
    source = ("def ailleurs(reg):\n    reg.ajouter({})\n\n"
              "def etat_tresorerie(reg):\n    return reg.lire()\n")

    assert _garde(tmp_path, {"outils": source}, {}, {"outils": ("etat_tresorerie",)}) == (True, "")
    en_faute = source.replace("    return reg.lire()\n", "    reg.ajouter({})\n    return reg.lire()\n")
    assert _garde(tmp_path, {"outils": en_faute}, {}, {"outils": ("etat_tresorerie",)})[0] is False


def test_une_fonction_de_lecture_seule_qui_disparait_est_une_violation(tmp_path):
    source = "def autre():\n    return 1\n"

    conforme, detail = _garde(tmp_path, {"outils": source}, {}, {"outils": ("etat_tresorerie",)})

    assert conforme is False and "fonction surveillée introuvable : etat_tresorerie" in detail


def test_un_module_de_lecture_seule_entier_est_surveille(tmp_path):
    conforme, detail = _garde(tmp_path, {"soldes": "def f(reg):\n    reg.ajouter({})\n"}, {}, {"soldes": None})

    assert conforme is False and "soldes.py" in detail and "le module" in detail and "ajouter" in detail


def test_un_appel_qui_ne_donne_que_surveille_ne_controle_que_le_regime_strict(tmp_path):
    """Compatibilité avec la garde de T4.15 : `verifier_aucun_decaissement(dossier, surveille)` ne cherche pas les
    modules de lecture seule (les fichiers d'un test n'en ont pas)."""
    (tmp_path / "cash_libre.py").write_text("x = 1\n", encoding="utf-8")

    assert conformite.verifier_aucun_decaissement(tmp_path, {"cash_libre": None}) == (True, "")


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


def _sur_les_vrais_fichiers(tmp_path, modifier, **portees):
    for nom in _FICHIERS:
        texte = (_PAQUET / f"{nom}.py").read_text(encoding="utf-8")
        (tmp_path / f"{nom}.py").write_text(modifier(nom, texte), encoding="utf-8")
    return conformite.verifier_aucun_decaissement(tmp_path, **portees)


def test_les_vrais_fichiers_copies_tels_quels_sont_conformes(tmp_path):
    assert _sur_les_vrais_fichiers(tmp_path, lambda _nom, texte: texte) == (True, "")


def test_donner_seulement_la_lecture_seule_garde_le_regime_strict_de_la_livraison_et_remplace_l_autre(tmp_path):
    """`lecture_seule` donné seul REMPLACE le régime de lecture seule (ici : aucun module) sans désarmer le régime
    strict, qui reste celui de la livraison."""
    def intrus_dans_soldes(nom, texte):
        return texte + "\n\ndef _intrus(reg):\n    reg.ajouter({})\n" if nom == "soldes" else texte

    def decaissement_dans_cash_libre(nom, texte):
        return texte + '\n\n_INTRUS = "DECAISSEMENT"\n' if nom == "cash_libre" else texte

    assert _sur_les_vrais_fichiers(tmp_path, intrus_dans_soldes)[0] is False, "par défaut : soldes est surveillé"
    assert _sur_les_vrais_fichiers(tmp_path, intrus_dans_soldes, lecture_seule={}) == (True, "")
    conforme, detail = _sur_les_vrais_fichiers(tmp_path, decaissement_dans_cash_libre, lecture_seule={})
    assert conforme is False and "cash_libre.py" in detail and "DECAISSEMENT" in detail


def test_un_decaissement_glisse_dans_le_vrai_cash_libre_est_attrape(tmp_path):
    def modifier(nom, texte):
        return texte + '\n\ndef _piege():\n    return {"type_mouvement": "DECAISSEMENT", "montant": 1}\n' \
            if nom == "cash_libre" else texte

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "cash_libre.py" in detail and "DECAISSEMENT" in detail and "type_mouvement" in detail


def test_l_import_du_registre_dans_le_vrai_calendrier_est_attrape(tmp_path):
    def modifier(nom, texte):
        ancre = "from . import analyse, validation"
        if nom != "calendrier_fiscal":
            return texte
        assert ancre in texte
        return texte.replace(ancre, "from . import analyse, registre, validation")

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "calendrier_fiscal.py" in detail and "importe registre.py" in detail


def test_une_ecriture_glissee_dans_la_vraie_lecture_des_registres_du_cash_libre_est_attrapee(tmp_path):
    """T4.16-d : `_lectures_finance` lit les registres pour le cash libre ET pour la prévision (le même instantané)."""
    def modifier(nom, texte):
        ancre = "    provisions, nombre_provisions, derniere_provision = soldes.calculer_provisions(mouvements)\n"
        if nom != "outils":
            return texte
        assert ancre in texte
        return texte.replace(ancre, ancre + "    registre_module.enregistrer_mouvement({}, registre_mouvements)\n", 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "_lectures_finance()" in detail and "enregistrer_mouvement" in detail


def test_un_paiement_glisse_dans_le_vrai_etat_de_tresorerie_est_attrape(tmp_path):
    def modifier(nom, texte):
        ancre = "    registre_cible = _registre_mouvements(mouvements_historique)\n    etat = etat_financier."
        if nom != "outils":
            return texte
        assert ancre in texte
        piege = "    facturation.enregistrer_paiement_facture('F', '1', 'n', 'h', None)\n"
        return texte.replace(ancre, piege + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "etat_tresorerie()" in detail and "enregistrer_paiement_facture" in detail


def test_une_ecriture_glissee_dans_le_vrai_solde_est_attrapee(tmp_path):
    def modifier(nom, texte):
        if nom != "soldes":
            return texte
        ancre = "        total = Decimal(\"0\")\n        for maillon"
        return texte.replace(ancre, "        registre_cible.ajouter({})\n" + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "soldes.py" in detail and "ajouter" in detail


def test_une_ecriture_glissee_dans_la_lecture_des_echeances_est_attrapee(tmp_path):
    def modifier(nom, texte):
        ancre = ("    fiscal = _configuration_manifeste().get(\"fiscal\")\n"
                 "    resultat, verdict = calendrier_fiscal.prochaines_echeances(")
        if nom != "outils":
            return texte
        assert ancre in texte
        return texte.replace(ancre, "    _registre_mouvements(None)\n" + ancre, 1)

    conforme, detail = _sur_les_vrais_fichiers(tmp_path, modifier)

    assert conforme is False and "lire_echeances_fiscales()" in detail and "_registre_mouvements" in detail


# ---------------------------------------------------------------- 5. aucun outil de plus ne déplace de l'argent
def test_les_seuls_outils_t3_de_m5_restent_les_deux_d_avant_et_le_calendrier_est_en_lecture_seule():
    par_nom = {o.nom: o for o in m5_outils.outils()}

    assert {nom for nom, o in par_nom.items() if o.autonomie is Autonomie.T3} == {
        "m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture"}
    assert par_nom["m5_lire_echeances_fiscales"].autonomie is Autonomie.T0
    assert par_nom["m5_etat_tresorerie"].autonomie is Autonomie.T0
    parlent_d_argent = {nom for nom in par_nom if re.search(r"(remise|remet|paye|paiement|decaisse|virement|rembours|"
                                                            r"declar)", nom)}
    assert parlent_d_argent == {"m5_enregistrer_paiement_facture", "m5_lister_comptes_a_payer"}, (
        "aucun outil de remise ni de déclaration fiscale : le calendrier PROPOSE des dates")


def test_l_etat_de_tresorerie_et_les_echeances_ne_declarent_ni_remise_ni_declaration_dans_leur_description():
    par_nom = {o.nom: o for o in m5_outils.outils()}
    for nom in ("m5_etat_tresorerie", "m5_lire_echeances_fiscales"):
        description = par_nom[nom].description
        assert "Lecture pure" in description or "Analyse préparatoire" in description, nom
    assert "Ni remise, ni déclaration, ni paiement" in par_nom["m5_lire_echeances_fiscales"].description
