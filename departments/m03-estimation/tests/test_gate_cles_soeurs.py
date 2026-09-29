"""Batterie durable de mutations du contrôle 22 du gate BMAD : les clés SŒURS d'`EstimationV1` (PLAN T4.11).

Le contrôle confronte trois descriptions : le tableau de l'architecture (§2.10), les constantes `CHAMPS_*` de
`scenarios.py`, et les douze clés du contrat gelé (§2.2 et `contrats.CHAMPS_ESTIMATION_V1`). Un contrôle qu'on ne fait
plus rougir devient décoratif : ce fichier le fait rougir, une divergence à la fois, et exige qu'il reste vert sur les
artefacts réels.

Les documents sont mutés EN MÉMOIRE (chaînes) ; les deux sources sont copiées dans un dossier temporaire du test, jamais
mutées en place : une suite interrompue ne doit rien laisser de corrompu dans le dépôt.
"""

import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _commun_gate import ARCHI, GATE, PRD, RACINE_MODULE  # noqa: E402

SOURCES = RACINE_MODULE / "src" / "m3_estimation"
REGEX_CONTRAT_2_2 = r"^#+\s*2\.2\s+Contrat de sortie.*$"


@pytest.fixture
def copies(tmp_path):
    """Copies jetables des deux sources, que chaque test peut muter."""
    chemins = {"scenarios": tmp_path / "scenarios.py", "contrats": tmp_path / "contrats.py"}
    shutil.copy(SOURCES / "scenarios.py", chemins["scenarios"])
    shutil.copy(SOURCES / "contrats.py", chemins["contrats"])
    return chemins


def _controle(archi=ARCHI, chemins=None):
    if chemins is None:
        return GATE.verifier_cles_soeurs_estimation(archi)
    return GATE.verifier_cles_soeurs_estimation(archi, chemins["scenarios"], chemins["contrats"])


def _muter(chemin, avant, apres):
    texte = chemin.read_text(encoding="utf-8")
    assert texte.count(avant) == 1, f"mutation ambiguë ou sans effet : {avant!r} ({texte.count(avant)} fois)"
    chemin.write_text(texte.replace(avant, apres), encoding="utf-8")


def _archi_muee(avant, apres):
    assert ARCHI.count(avant) == 1, f"mutation ambiguë ou sans effet : {avant!r} ({ARCHI.count(avant)} fois)"
    return ARCHI.replace(avant, apres)


LIGNE_SCENARIO = (
    "| `scenarios_prix.scenarios[]` | `scenario`, `base_cout`, `cout`, `taux_marge`, `source_taux`, `prix`, "
    "`alerte_rouge`, `motifs`, `verdict` |"
)


# --------------------------------------------------------------------------------------- nominal
def test_le_controle_est_vert_sur_les_artefacts_reels():
    assert _controle() == []


def test_le_controle_est_vert_sur_les_copies_non_mutees(copies):
    assert _controle(chemins=copies) == []


def test_la_fonction_est_branchee_au_gate_et_le_gate_reste_vert():
    """Un contrôle défini mais jamais appelé par `main` ne garde rien."""
    source = Path(GATE.__file__).read_text(encoding="utf-8")
    assert "errs = verifier_cles_soeurs_estimation(archi)" in source


def test_le_tableau_de_l_architecture_a_six_objets_et_les_constantes_de_scenarios_les_decrivent():
    section = ARCHI[ARCHI.index("### 2.10 Clés sœurs de l'estimation"):]
    section = section[:section.index("\n---\n")]
    objets = re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE)
    assert objets == ["reponse", "distribution_cout", "distribution_cout.postes[]", "facteurs_dominants[]",
                      "scenarios_prix", "scenarios_prix.scenarios[]"]


# ----------------------------------------------------- l'extracteur des clés gelées lit les noms chiffrés
def test_l_extracteur_de_cles_gelees_lit_empreinte_marqueur_m2_dans_les_deux_documents():
    """Avant T4.11, `[a-z_]+` s'arrêtait au chiffre : onze clés sur douze, des DEUX côtés du contrôle 11."""
    from m3_estimation import contrats

    cles_archi = GATE._cles_contrat(ARCHI, REGEX_CONTRAT_2_2)
    cles_prd = GATE._cles_contrat(PRD, r"^## 5\. CONTRAT GELÉ.*$")
    assert "empreinte_marqueur_m2" in cles_archi and "empreinte_marqueur_m2" in cles_prd
    assert cles_archi == cles_prd == set(contrats.CHAMPS_ESTIMATION_V1)
    assert len(cles_archi) == 12


# ------------------------------------------------------------------------- tableau de l'architecture
def test_une_cle_retiree_d_un_objet_du_tableau_est_detectee():
    erreurs = _controle(_archi_muee("`alerte_rouge`, `motifs`, `verdict` |", "`alerte_rouge`, `motifs` |"))
    assert any("scenarios_prix.scenarios[]" in e and "verdict" in e for e in erreurs), erreurs


def test_une_cle_ajoutee_a_un_objet_du_tableau_est_detectee():
    erreurs = _controle(_archi_muee("`rang`, `poste`, `amplitude`, `part_variance` |",
                                    "`rang`, `poste`, `amplitude`, `part_variance`, `surprise` |"))
    assert any("facteurs_dominants[]" in e and "surprise" in e for e in erreurs), erreurs


def test_une_cle_soeur_retiree_de_la_reponse_dans_l_architecture_est_detectee():
    erreurs = _controle(_archi_muee("`distribution_cout`, `facteurs_dominants`, `scenarios_prix` |",
                                    "`distribution_cout`, `scenarios_prix` |"))
    assert any("« reponse »" in e and "facteurs_dominants" in e for e in erreurs), erreurs


def test_une_cle_renommee_dans_le_tableau_est_detectee_des_deux_cotes():
    erreurs = _controle(_archi_muee("`tirages`, `graine`, `p50`, `p80`, `postes` |",
                                    "`tirages`, `graine`, `p50`, `p90`, `postes` |"))
    assert any("distribution_cout" in e and "p80" in e and "p90" in e for e in erreurs), erreurs


def test_un_objet_du_code_absent_du_tableau_est_detecte():
    erreurs = _controle(_archi_muee(LIGNE_SCENARIO + "\n", ""))
    assert any("absent(s) du tableau" in e and "scenarios_prix.scenarios[]" in e for e in erreurs), erreurs


def test_un_objet_du_tableau_sans_constante_est_detecte():
    erreurs = _controle(_archi_muee(LIGNE_SCENARIO, LIGNE_SCENARIO + "\n| `objet_fantome` | `a`, `b` |"))
    assert any("sans constante" in e and "objet_fantome" in e for e in erreurs), erreurs


def test_un_objet_decrit_deux_fois_est_detecte():
    erreurs = _controle(_archi_muee(LIGNE_SCENARIO, LIGNE_SCENARIO + "\n" + LIGNE_SCENARIO))
    assert any("décrit deux fois" in e and "scenarios_prix.scenarios[]" in e for e in erreurs), erreurs


def test_une_cle_soeur_qui_prend_le_nom_d_une_cle_gelee_dans_le_tableau_est_detectee():
    erreurs = _controle(_archi_muee("`distribution_cout`, `facteurs_dominants`, `scenarios_prix` |",
                                    "`distribution_cout`, `facteurs_dominants`, `devis_id` |"))
    assert erreurs, "la clé sœur `devis_id` n'est ni dans le code ni additive"
    assert any("« reponse »" in e for e in erreurs)


def test_section_absente_titre_renomme_ou_tableau_vide_est_non_probant():
    titre_renomme = _archi_muee("### 2.10 Clés sœurs de l'estimation", "### 2.10 Autre chose")
    assert any("introuvable" in e for e in _controle(titre_renomme))
    assert any("introuvable" in e for e in _controle(""))
    sans_tableau = re.sub(r"^\| `[^`]+` \|.*$", "", ARCHI, flags=re.MULTILINE)
    assert any("introuvable ou vide" in e or "introuvable" in e for e in _controle(sans_tableau))


# ---------------------------------------------------------------------------- constantes de scenarios.py
def test_une_cle_retiree_d_une_constante_du_code_est_detectee(copies):
    _muter(
        copies["scenarios"],
        '"taux_marge", "source_taux", "prix", "alerte_rouge", "motifs", "verdict",\n',
        '"taux_marge", "source_taux", "alerte_rouge", "motifs", "verdict",\n')
    erreurs = _controle(chemins=copies)
    assert any("scenarios_prix.scenarios[]" in e and "prix" in e for e in erreurs), erreurs


def test_une_cle_ajoutee_a_une_constante_du_code_est_detectee(copies):
    _muter(copies["scenarios"], 'CHAMPS_LOI_DU_POSTE = ("poste", "loi", "mode", "raison")',
           'CHAMPS_LOI_DU_POSTE = ("poste", "loi", "mode", "raison", "surprise")')
    erreurs = _controle(chemins=copies)
    assert any("distribution_cout.postes[]" in e and "surprise" in e for e in erreurs), erreurs


def test_une_cle_soeur_du_code_qui_prend_le_nom_d_une_cle_gelee_est_detectee(copies):
    _muter(
        copies["scenarios"],
        'CHAMPS_SOEURS_ESTIMATION = ("distribution_cout", "facteurs_dominants", "scenarios_prix")',
        'CHAMPS_SOEURS_ESTIMATION = ("distribution_cout", "facteurs_dominants", "scenarios_prix", "devis_id")')
    erreurs = _controle(chemins=copies)
    assert any("portant le nom d'une clé du contrat gelé" in e and "devis_id" in e for e in erreurs), erreurs


@pytest.mark.parametrize("constante", ["CHAMPS_SOEURS_ESTIMATION", "CHAMPS_DISTRIBUTION_COUT", "CHAMPS_LOI_DU_POSTE",
                                       "CHAMPS_FACTEUR_DOMINANT", "CHAMPS_SCENARIOS_PRIX", "CHAMPS_SCENARIO"])
def test_une_constante_renommee_ou_disparue_rend_le_controle_non_probant(copies, constante):
    texte = copies["scenarios"].read_text(encoding="utf-8")
    copies["scenarios"].write_text(texte.replace(f"{constante} =", f"{constante}_RENOMMEE ="), encoding="utf-8")
    erreurs = _controle(chemins=copies)
    assert len(erreurs) == 1 and constante in erreurs[0] and "non probant" in erreurs[0]


def test_une_constante_qui_n_est_plus_un_litteral_de_chaines_rend_le_controle_non_probant(copies):
    _muter(copies["scenarios"], 'CHAMPS_LOI_DU_POSTE = ("poste", "loi", "mode", "raison")',
           'CHAMPS_LOI_DU_POSTE = tuple(dict.fromkeys(("poste", "loi", "mode", "raison")))')
    erreurs = _controle(chemins=copies)
    assert len(erreurs) == 1 and "CHAMPS_LOI_DU_POSTE" in erreurs[0]


def test_une_source_absente_ou_illisible_est_un_echec_explicite_jamais_un_vert(copies, tmp_path):
    copies["scenarios"].unlink()
    assert any("scenarios.py introuvable" in e for e in _controle(chemins=copies))
    copies["scenarios"] = tmp_path / "dossier"  # un dossier n'est pas un fichier
    copies["scenarios"].mkdir()
    assert any("introuvable" in e for e in _controle(chemins=copies))


def test_une_source_qui_ne_s_analyse_plus_rend_le_controle_non_probant(copies):
    copies["scenarios"].write_text("def (:\n", encoding="utf-8")
    erreurs = _controle(chemins=copies)
    assert len(erreurs) == 1 and "non probant" in erreurs[0]


# ------------------------------------------------------------------------------- le contrat gelé (§2.2)
def test_une_cle_gelee_retiree_du_code_est_detectee(copies):
    _muter(copies["contrats"], '    "graine_monte_carlo",\n    "hash_maillon",\n)', '    "hash_maillon",\n)')
    erreurs = _controle(chemins=copies)
    assert any("contrat gelé" in e and "graine_monte_carlo" in e for e in erreurs), erreurs


def test_une_cle_gelee_ajoutee_au_code_est_detectee(copies):
    _muter(copies["contrats"], '    "hash_maillon",\n)', '    "hash_maillon",\n    "distribution_cout",\n)')
    erreurs = _controle(chemins=copies)
    assert any("contrat gelé" in e and "distribution_cout" in e for e in erreurs), erreurs
    assert any("portant le nom d'une clé du contrat gelé" in e for e in erreurs), erreurs


def test_une_cle_gelee_retiree_de_l_architecture_est_detectee():
    erreurs = _controle(_archi_muee("  empreinte_marqueur_m2: str\n", ""))
    assert any("contrat gelé" in e and "empreinte_marqueur_m2" in e for e in erreurs), erreurs


def test_la_constante_gelee_manquante_rend_le_controle_non_probant(copies):
    texte = copies["contrats"].read_text(encoding="utf-8")
    copies["contrats"].write_text(texte.replace("CHAMPS_ESTIMATION_V1 =", "CHAMPS_RENOMMEE ="), encoding="utf-8")
    erreurs = _controle(chemins=copies)
    assert len(erreurs) == 1 and "CHAMPS_ESTIMATION_V1" in erreurs[0] and "non probant" in erreurs[0]
