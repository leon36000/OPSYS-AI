"""Ordre de vérité de M10 : une DONNÉE (contracts/ordre-verite.v1.json), jamais une logique codée.

Ce qu'on prouve : l'ordre livré est celui du condensé de Nathan ; il est validé en schéma fermé ; la résolution ne
connaît
aucune classe par son nom (changer le fichier change le résultat) ; une classe haute ne s'obtient pas par déclaration
(admission par canal) ; la criticité est lue des données ; chaque fichier du dépôt prend sa classe de sa place.
Données fictives."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from m10_memoire import verite

FICTIF = True
CHEMIN = Path(verite.CHEMIN_DEFAUT)
ORDRE_DU_CONDENSE = (
    "constitution",
    "decision_proprietaire",
    "matrice_vivante",
    "rapport_valide",
    "test_sonde",
    "code",
    "documentation",
    "journal",
    "memoire_ancienne",
    "hypothese",
)


def _donnees():
    return json.loads(CHEMIN.read_text(encoding="utf-8"))


def _aff(classe, valeur="x"):
    return {"classe": classe, "valeur": valeur}


def test_l_ordre_livre_est_celui_du_condense_de_nathan():
    ordre = verite.charger()
    assert ordre.classes == ORDRE_DU_CONDENSE
    assert [ordre.rang(c) for c in ORDRE_DU_CONDENSE] == list(range(10))
    assert ordre.version and len(ordre.empreinte) == 64


def test_l_ordre_est_une_donnee_la_logique_suit_le_fichier_pas_les_noms():
    donnees = _donnees()
    donnees["classes"] = list(reversed(donnees["classes"]))  # l'hypothèse devient la plus haute autorité
    inverse = verite.depuis_dict(donnees)
    normal = verite.charger()
    avant = verite.resoudre(_aff("constitution"), _aff("hypothese"), "statut", normal)
    apres = verite.resoudre(_aff("constitution"), _aff("hypothese"), "statut", inverse)
    assert avant["retenue"] == "a" and apres["retenue"] == "b"
    assert normal.empreinte != inverse.empreinte  # l'ordre utilisé est traçable par son empreinte


@pytest.mark.parametrize(
    "gauche, droite, retenue",
    [
        ("constitution", "decision_proprietaire", "a"),
        ("matrice_vivante", "memoire_ancienne", "a"),
        ("hypothese", "journal", "b"),
        ("code", "documentation", "a"),
        ("rapport_valide", "test_sonde", "a"),
    ],
)
def test_la_classe_de_plus_haute_autorite_est_proposee(gauche, droite, retenue):
    proposition = verite.resoudre(_aff(gauche), _aff(droite), "statut", verite.charger())
    assert proposition["retenue"] == retenue and proposition["regle"] == "ordre_verite"


def test_deux_sources_de_meme_rang_ne_donnent_aucune_proposition():
    proposition = verite.resoudre(_aff("journal"), _aff("journal"), "statut", verite.charger())
    assert proposition["retenue"] is None and proposition["regle"] == "egalite_de_rang"


def test_la_criticite_vient_des_donnees_classe_ou_attribut():
    ordre = verite.charger()
    assert verite.resoudre(_aff("decision_proprietaire"), _aff("journal"), "statut", ordre)["critique"] is True
    assert verite.resoudre(_aff("constitution"), _aff("hypothese"), "statut", ordre)["critique"] is True
    assert verite.resoudre(_aff("journal"), _aff("hypothese"), "statut", ordre)["critique"] is False
    critique_par_attribut = verite.resoudre(_aff("journal"), _aff("hypothese"), "gate_humain", ordre)
    assert critique_par_attribut["critique"] is True and critique_par_attribut["motifs_criticite"] == [
        "attribut:gate_humain"
    ]
    donnees = _donnees()
    donnees["criticite"]["classes"] = []
    donnees["criticite"]["attributs"] = []
    sans = verite.depuis_dict(donnees)
    assert verite.resoudre(_aff("constitution"), _aff("hypothese"), "gate_humain", sans)["critique"] is False


def test_une_classe_haute_ne_s_obtient_pas_par_declaration():
    ordre = verite.charger()
    for classe in ("constitution", "decision_proprietaire", "matrice_vivante", "rapport_valide", "test_sonde", "code"):
        assert ordre.admet(classe, "affaires", "agent") is False, classe
        assert ordre.admet(classe, "developpement", "agent") is False, classe
    assert ordre.admet("hypothese", "affaires", "agent") and ordre.admet("journal", "affaires", "agent")
    assert ordre.admet("decision_proprietaire", "affaires", "humain") and not ordre.admet(
        "constitution", "affaires", "humain"
    )
    assert ordre.admet("constitution", "developpement", "ingestion")
    assert ordre.admet("constitution", "affaires", "ingestion") is False  # les domaines ne se mêlent pas


def test_chaque_fichier_du_depot_prend_sa_classe_de_sa_place():
    ordre = verite.charger()
    attendu = {
        "docs/produit/DIRECTIVES-NATHAN.md": ("decision_proprietaire", "directive"),
        "docs/decisions/ADR-0012-reutilisation.md": ("constitution", "adr"),
        "AGENTS.md": ("constitution", "regle"),
        "docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json": ("matrice_vivante", "matrice"),
        "docs/reprise/PROMPTS-NATHAN-ANCIENS/M10-MEMOIRE.md": ("memoire_ancienne", "condense"),
        "docs/architecture/CONNAISSANCES.md": ("documentation", "document"),
    }
    for chemin, classement in attendu.items():
        assert ordre.classe_de_fichier(chemin) == classement, chemin
    assert ordre.classe_de_fichier("src/opsys/outils.py") is None
    assert ordre.classe_de_fichier("docs/decisions/../../etc/passwd") is None
    position_adr, _, _ = ordre.classement("docs/decisions/ADR-0001-x.md")
    position_doc, _, _ = ordre.classement("docs/architecture/CONNAISSANCES.md")
    assert position_adr < position_doc  # les motifs précis passent avant la documentation générale


def _refuse(donnees):
    with pytest.raises(ValueError, match="REJ-VERITE-ORDRE-INVALIDE"):
        verite.depuis_dict(donnees)


def test_le_schema_est_ferme_et_chaque_defaut_est_un_refus_nomme():
    base = _donnees()
    for mutation in (
        lambda d: d.update(schema="autre"),
        lambda d: d.update(inconnu=1),
        lambda d: d.update(classes=[]),
        lambda d: d["classes"].append(copy.deepcopy(d["classes"][0])),  # doublon
        lambda d: d["classes"][0].update(admission=[]),
        lambda d: d["classes"][0].update(admission=["partout:tous"]),
        lambda d: d["classes"][0].update(id="Majuscule"),
        lambda d: d["criticite"].update(classes=["inexistante"]),
        lambda d: d.update(sujets={"affaires": ["a"]}),
        lambda d: d["sources_fichiers"][0].update(classe="inexistante"),
        lambda d: d["sources_fichiers"][0].update(genre="inconnu"),
        lambda d: d["sources_fichiers"].append({"motif": "x.md", "classe": "journal", "genre": "document", "extra": 1}),
        lambda d: d.pop("version"),
    ):
        donnees = copy.deepcopy(base)
        mutation(donnees)
        _refuse(donnees)
    _refuse("pas un objet")


def test_une_source_de_fichier_ne_peut_viser_qu_une_classe_admise_par_ingestion():
    donnees = _donnees()
    donnees["sources_fichiers"].append({"motif": "x/*.md", "classe": "hypothese", "genre": "document"})
    verite.depuis_dict(donnees)  # l'hypothèse est admise par ingestion dans le domaine développement
    donnees["classes"][-1]["admission"] = ["affaires:agent"]
    _refuse(donnees)


def test_un_fichier_d_ordre_illisible_est_un_refus_pas_une_valeur_supposee(tmp_path):
    with pytest.raises(ValueError, match="REJ-VERITE-ORDRE-INVALIDE"):
        verite.charger(tmp_path / "absent.json")
    (tmp_path / "casse.json").write_text("{pas du json", encoding="utf-8")
    with pytest.raises(ValueError, match="REJ-VERITE-ORDRE-INVALIDE"):
        verite.charger(tmp_path / "casse.json")


def test_une_classe_inconnue_est_refusee_sans_rang_suppose():
    ordre = verite.charger()
    with pytest.raises(ValueError, match="REJ-VERITE-ORDRE-INVALIDE"):
        ordre.rang("inventee")
    assert ordre.connait("inventee") is False and ordre.connait(None) is False
