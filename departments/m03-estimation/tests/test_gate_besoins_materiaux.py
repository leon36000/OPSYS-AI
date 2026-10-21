"""Batterie durable de mutations du contrôle « contrat BesoinsMateriauxM3 » du gate BMAD (PLAN T2.3-e).

Le contrôle confronte QUATRE descriptions d'un même contrat inter-départements : le bloc yaml de
l'architecture, la constante de l'émetteur (M3), la copie épinglée du récepteur (M6) et le schéma du
catalogue du bus. Un contrôle qu'on ne fait plus rougir devient décoratif : ce fichier le fait
rougir, une divergence à la fois, et exige qu'il reste vert sur les artefacts réels.

Les documents sont mutés EN MÉMOIRE (chaînes) ; les sources et le catalogue sont copiés dans un
dossier temporaire du test, jamais mutés en place : une suite interrompue ne doit rien laisser de
corrompu dans le dépôt.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _commun_gate import ARCHI, GATE, RACINE_MODULE  # noqa: E402

DEPOT = RACINE_MODULE.parents[1]
SOURCE_M3 = RACINE_MODULE / "src" / "m3_estimation" / "besoins_materiaux.py"
SOURCE_M6 = (
    DEPOT / "departments" / "m06-material-control" / "src" / "m6_material_control" / "besoins_materiaux_recus.py"
)
CATALOGUE = DEPOT / "src" / "opsys" / "evenements" / "catalogue" / "m3.besoins_materiaux.json"


@pytest.fixture
def copies(tmp_path):
    """Copies jetables des trois sources, que chaque test peut muter."""
    chemins = {
        "m3": tmp_path / "besoins_materiaux.py",
        "m6": tmp_path / "besoins_materiaux_recus.py",
        "catalogue": tmp_path / "m3.besoins_materiaux.json",
    }
    shutil.copy(SOURCE_M3, chemins["m3"])
    shutil.copy(SOURCE_M6, chemins["m6"])
    shutil.copy(CATALOGUE, chemins["catalogue"])
    return chemins


def _controle(archi=ARCHI, chemins=None):
    if chemins is None:
        return GATE.verifier_contrat_besoins_materiaux(archi)
    return GATE.verifier_contrat_besoins_materiaux(archi, chemins["m3"], chemins["m6"], chemins["catalogue"])


def _muter(chemin, avant, apres, occurrences=1):
    texte = chemin.read_text(encoding="utf-8")
    assert texte.count(avant) >= 1, f"la mutation ne mord sur rien : {avant!r} absent de {chemin.name}"
    chemin.write_text(texte.replace(avant, apres, occurrences), encoding="utf-8")


def _muter_catalogue(chemin, transformation):
    schema = json.loads(chemin.read_text(encoding="utf-8"))
    transformation(schema)
    chemin.write_text(json.dumps(schema), encoding="utf-8")


def _archi_muee(avant, apres):
    assert ARCHI.count(avant) == 1, f"mutation ambiguë ou sans effet : {avant!r} ({ARCHI.count(avant)} fois)"
    return ARCHI.replace(avant, apres)


# --------------------------------------------------------------------------------------- nominal
def test_le_controle_est_vert_sur_les_artefacts_reels():
    assert _controle() == []


def test_le_controle_est_vert_sur_les_copies_non_mutees(copies):
    assert _controle(chemins=copies) == []


def test_la_fonction_est_branchee_au_gate_et_le_gate_reste_vert():
    """Un contrôle défini mais jamais appelé par `main` ne garde rien."""
    source = (GATE.__file__ and Path(GATE.__file__).read_text(encoding="utf-8"))
    assert "errs = verifier_contrat_besoins_materiaux(archi)" in source


# --------------------------------------------------------------------- bloc de l'architecture
def test_cle_de_premier_niveau_retiree_de_l_architecture_est_detectee():
    erreurs = _controle(_archi_muee("  rang_registre: int\n", ""))
    assert any("premier niveau du bloc" in erreur and "rang_registre" in erreur for erreur in erreurs)


def test_cle_de_premier_niveau_ajoutee_a_l_architecture_est_detectee():
    erreurs = _controle(
        _archi_muee("  lead_id: str\n  estimation_id: str", "  lead_id: str\n  surprise: str\n  estimation_id: str")
    )
    assert any("surprise" in erreur for erreur in erreurs)


def test_cle_de_ligne_retiree_de_l_architecture_est_detectee():
    erreurs = _controle(_archi_muee("      unite: str\n", ""))
    assert any("Clés de ligne du bloc" in erreur and "unite" in erreur for erreur in erreurs)


def test_cle_optionnelle_declaree_requise_est_detectee():
    erreurs = _controle(_archi_muee("      sku: str                # OPTIONNEL", "      sku: str                #"))
    assert any("OPTIONNELLES du bloc" in erreur and "sku" in erreur for erreur in erreurs)


def test_cle_requise_declaree_optionnelle_est_detectee():
    erreurs = _controle(_archi_muee("      unite: str\n", "      unite: str              # OPTIONNEL\n"))
    assert any("OPTIONNELLES du bloc" in erreur and "unite" in erreur for erreur in erreurs)


def test_cle_de_premier_niveau_marquee_optionnelle_est_detectee():
    erreurs = _controle(_archi_muee(
        "  lead_id: str\n  estimation_id: str", "  lead_id: str             # OPTIONNEL\n  estimation_id: str"
    ))
    assert any("marquées OPTIONNEL" in erreur and "lead_id" in erreur for erreur in erreurs)


@pytest.mark.parametrize("cle", ["prix_unitaire", "cout_total", "taux_marge", "intervalle_confiance"])
def test_une_cle_de_prix_ou_de_cout_ajoutee_au_bloc_est_detectee(cle):
    erreurs = _controle(
        _archi_muee("  lead_id: str\n  estimation_id: str", f"  lead_id: str\n  {cle}: str\n  estimation_id: str")
    )
    assert any(cle in erreur and "aucune donnée financière" in erreur for erreur in erreurs), erreurs


def test_bloc_absent_ancrage_errone_ou_titre_renomme_est_non_probant():
    titre_renomme = _archi_muee("Contrat de sortie — `BesoinsMateriauxM3`", "Sortie — `Autre`")
    assert any("introuvable" in e for e in _controle(titre_renomme))
    ancrage_errone = _archi_muee("BesoinsMateriauxM3:\n  devis_id", "Autre:\n  devis_id")
    assert any("ancrage erroné" in e for e in _controle(ancrage_errone))
    assert any("introuvable" in e for e in _controle(""))


# ------------------------------------------------------------------------- récepteur M6 (copie)
def test_cle_retiree_de_la_copie_du_recepteur_est_detectee(copies):
    _muter(copies["m6"], '        "rang_registre",\n', "", occurrences=1)
    erreurs = _controle(chemins=copies)
    assert any("récepteur M6" in erreur and "rang_registre" in erreur for erreur in erreurs)


def test_cle_de_ligne_optionnelle_changee_dans_le_recepteur_est_detectee(copies):
    _muter(
        copies["m6"],
        'CHAMPS_LIGNE_BESOINS_OPTIONNELS = frozenset({"sku", "facteur_perte"})',
        'CHAMPS_LIGNE_BESOINS_OPTIONNELS = frozenset({"sku"})',
    )
    erreurs = _controle(chemins=copies)
    assert any("OPTIONNELLES du récepteur M6" in erreur and "facteur_perte" in erreur for erreur in erreurs)


def test_cle_de_ligne_requise_changee_dans_le_recepteur_est_detectee(copies):
    _muter(
        copies["m6"],
        'CHAMPS_LIGNE_BESOINS_REQUIS = frozenset({"materiau", "quantite_estimee", "unite"})',
        'CHAMPS_LIGNE_BESOINS_REQUIS = frozenset({"materiau", "quantite_estimee"})',
    )
    assert any("requises du récepteur M6" in erreur for erreur in _controle(chemins=copies))


def test_cle_de_prix_retiree_de_l_interdiction_du_recepteur_est_detectee(copies):
    _muter(copies["m6"], '        "taux_marge",\n', "")
    erreurs = _controle(chemins=copies)
    assert any("interdites du récepteur M6" in erreur and "taux_marge" in erreur for erreur in erreurs)


def test_cle_de_prix_retiree_de_l_interdiction_de_l_emetteur_est_detectee(copies):
    _muter(copies["m3"], '        "cout_total",\n', "")
    erreurs = _controle(chemins=copies)
    assert any("interdites du récepteur M6" in erreur and "cout_total" in erreur for erreur in erreurs)


# --------------------------------------------------------------------------- émetteur M3 (source)
def test_cle_retiree_de_la_constante_de_l_emetteur_est_detectee(copies):
    _muter(copies["m3"], '    "facteurs_perte_absents",\n', "", occurrences=1)
    erreurs = _controle(chemins=copies)
    assert any("facteurs_perte_absents" in erreur for erreur in erreurs)


# ------------------------------------------------------------------------------------- catalogue
def test_propriete_ajoutee_au_catalogue_est_detectee(copies):
    _muter_catalogue(
        copies["catalogue"], lambda schema: schema["properties"].update({"prix_total": {"type": "string"}})
    )
    erreurs = _controle(chemins=copies)
    assert any("Propriétés du premier niveau du catalogue" in erreur and "prix_total" in erreur for erreur in erreurs)


def test_propriete_de_ligne_ajoutee_au_catalogue_est_detectee(copies):
    _muter_catalogue(
        copies["catalogue"],
        lambda schema: schema["properties"]["lignes"]["items"]["properties"].update(
            {"prix_unitaire": {"type": "string"}}
        ),
    )
    assert any("Propriétés de ligne du catalogue" in erreur for erreur in _controle(chemins=copies))


def test_cle_requise_retiree_du_catalogue_est_detectee(copies):
    _muter_catalogue(copies["catalogue"], lambda schema: schema["required"].remove("estimation_id"))
    assert any("requises du premier niveau du catalogue" in erreur for erreur in _controle(chemins=copies))


def test_catalogue_non_ferme_est_detecte(copies):
    _muter_catalogue(copies["catalogue"], lambda schema: schema.pop("additionalProperties"))
    assert any("pas fermé" in erreur for erreur in _controle(chemins=copies))


def test_catalogue_de_ligne_non_ferme_est_detecte(copies):
    _muter_catalogue(
        copies["catalogue"],
        lambda schema: schema["properties"]["lignes"]["items"].update({"additionalProperties": True}),
    )
    assert any("pas fermé" in erreur for erreur in _controle(chemins=copies))


def test_catalogue_illisible_est_non_probant(copies):
    copies["catalogue"].write_text("{pas du json", encoding="utf-8")
    assert any("illisible ou incomplet" in erreur for erreur in _controle(chemins=copies))


# ------------------------------------------------------------------------------- fail-closed
@pytest.mark.parametrize("cle", ["m3", "m6", "catalogue"])
def test_source_absente_est_non_probante_jamais_verte(copies, cle):
    copies[cle].unlink()
    erreurs = _controle(chemins=copies)
    assert len(erreurs) == 1 and "introuvable" in erreurs[0] and "jamais silencieusement vert" in erreurs[0]


def test_constante_introuvable_dans_le_recepteur_est_non_probante(copies):
    _muter(copies["m6"], "CHAMPS_BESOINS_MATERIAUX_RECUS", "CHAMPS_RENOMMES", occurrences=-1)
    erreurs = _controle(chemins=copies)
    assert any("introuvable(s) ou vide(s)" in erreur and "récepteur M6" in erreur for erreur in erreurs)


def test_constante_non_litterale_est_non_probante_au_lieu_d_etre_devinee(copies):
    _muter(copies["m3"], "CHAMPS_LIGNE_BESOINS_REQUIS = (", "CHAMPS_LIGNE_BESOINS_REQUIS = tuple(x for x in (")
    _muter(copies["m3"], '"quantite_estimee", "unite")', '"quantite_estimee", "unite"))')
    assert any("introuvable(s) ou vide(s)" in erreur for erreur in _controle(chemins=copies))


def test_source_non_analysable_est_non_probante(copies):
    copies["m6"].write_text("def (:\n", encoding="utf-8")
    assert any("introuvable(s) ou vide(s)" in erreur for erreur in _controle(chemins=copies))


def test_le_controle_lit_les_constantes_par_l_arbre_syntaxique_pas_par_le_texte(copies):
    """Une constante citée dans un commentaire ou une docstring n'est pas la constante."""
    _muter(
        copies["m6"],
        "CHAMPS_BESOINS_MATERIAUX_RECUS = frozenset(",
        "# CHAMPS_BESOINS_MATERIAUX_RECUS = frozenset(\nAUTRE = frozenset(",
    )
    assert any("introuvable(s) ou vide(s)" in erreur for erreur in _controle(chemins=copies))
