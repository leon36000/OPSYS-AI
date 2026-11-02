"""Réglages de direction (CFG-1) : la déclaration au manifeste (schéma fermé) et la validation d'une valeur.

Prouve : les manifestes livrés (M2, M8) déclarent des réglages valides dont chaque proposition est étiquetée
« recommandation, non validée », sourcée par un fichier du dépôt, et dans ses propres bornes ; M8 ne propose AUCUNE
borne ; l'ordre « pire / cible » de M8 suit le sens du catalogue et ses indicateurs sont exactement ceux du score de
santé ; le schéma est fermé (clé, type, niveau, chemin, doublon, proposition mal formée sont des refus) ; chaque type
de valeur refuse l'ambigu (booléen, flottant pour un entier, texte pour un nombre, hors bornes, mauvais sens) et
normalise le décimal en texte. Données fictives.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from opsys.departements import charger_departements, lire_manifeste, racine_departements
from opsys.outils import Niveau
from opsys.reglages import declaration
from opsys.reglages.declaration import ETIQUETTE_PROPOSITION, ReglageRefuse, analyser_saisie, valider_valeur

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]


def _declarations(departement: str):
    return {r.cle: r for r in charger_departements()[departement].reglages}


def _entree(**plus):
    base = {
        "cle": "m2.jours_exemple", "libelle": "Délai d'exemple fictif",
        "chemin": "configuration.segments.jours_exemple",
        "type": "entier", "unite": "jours", "min": 1, "max": 100, "niveau": "N3",
        "debloque": "Une fonction fictive de démonstration du schéma.",
    }
    return {**base, **plus}


def _lire(entrees, code="M2", departement="m02-revenue-crm"):
    return declaration.lire(entrees, "manifeste-fictif", code, departement)


# -- les manifestes livrés ---------------------------------------------------------------------------------------
def test_les_manifestes_livres_declarent_les_reglages_de_m2_et_de_m8():
    m2 = _declarations("m02-revenue-crm")
    assert set(m2) == {"m2.jours_inactivite_dormant", "m2.jours_soumission_perimee", "m2.jours_entre_relances",
                       "m2.bandes_valeur_cents"}
    m8 = _declarations("m08-analytics")
    assert len(m8) == 6 and all(c.startswith("m8.bornes_") for c in m8)
    for reglage in [*m2.values(), *m8.values()]:
        assert reglage.niveau is Niveau.N3 and reglage.debloque and reglage.libelle
        assert reglage.chemin[0] == "configuration"


def test_chaque_proposition_est_etiquetee_non_validee_sourcee_par_un_fichier_du_depot_et_dans_ses_bornes():
    propositions = 0
    for reglage in [*_declarations("m02-revenue-crm").values(), *_declarations("m08-analytics").values()]:
        if reglage.proposition is None:
            continue
        propositions += 1
        p = reglage.proposition
        assert p.etiquette == ETIQUETTE_PROPOSITION == "recommandation, non validée"
        assert valider_valeur(reglage, p.valeur) == p.valeur
        fichier = p.source.split(" ")[0]
        assert (RACINE / fichier).is_file(), f"source introuvable dans le dépôt : {p.source}"
        assert "non calibr" in p.justification or "aucune calibration" in p.justification
    assert propositions == 3  # les trois délais de M2, venus des exemples écrits du manifeste


def test_m8_ne_propose_aucune_borne_et_m2_ne_propose_pas_de_montant():
    assert all(r.proposition is None for r in _declarations("m08-analytics").values())
    assert _declarations("m02-revenue-crm")["m2.bandes_valeur_cents"].proposition is None


def test_les_valeurs_proposees_par_m2_sont_celles_des_exemples_ecrits_dans_le_manifeste():
    texte = (racine_departements() / "m02-revenue-crm" / "department.yaml").read_text(encoding="utf-8")
    m2 = _declarations("m02-revenue-crm")
    assert m2["m2.jours_inactivite_dormant"].proposition.valeur == 30 and "jours_inactivite_dormant: 30" in texte
    assert m2["m2.jours_soumission_perimee"].proposition.valeur == 14 and "jours_soumission_perimee: 14" in texte
    assert m2["m2.jours_entre_relances"].proposition.valeur == 7 and "jours_entre_relances: 7" in texte


def test_les_reglages_de_m8_sont_exactement_les_indicateurs_du_score_de_sante_avec_le_sens_du_catalogue():
    racine = racine_departements() / "m08-analytics"
    sante = yaml.safe_load((racine / "definitions" / "m8-sante.v1.yaml").read_text(encoding="utf-8"))
    catalogue = yaml.safe_load((racine / "definitions" / "m8-catalogue.v1.yaml").read_text(encoding="utf-8"))
    sens = {m["metric_id"]: m["sens"] for m in catalogue["mesures"]}
    indicateurs = {i["mesure"] for c in sante["composantes"] for i in c["indicateurs"]}
    declares = {r.chemin[-1]: r for r in _declarations("m08-analytics").values()}
    assert set(declares) == indicateurs
    for mesure, reglage in declares.items():
        assert reglage.chemin[:3] == ("configuration", "sante", "bornes") and reglage.type == "bornes_pire_cible"
        attendu = "croissant" if sens[mesure] == "plus_est_mieux" else "decroissant"
        assert reglage.ordre == attendu, mesure


def test_les_bornes_de_saisie_de_m8_acceptent_les_bornes_fictives_du_jeu_de_calibration():
    from m8_analytics import jeux_fictifs

    for cle, valeur in jeux_fictifs.BORNES_SANTE_FICTIVES.items():
        reglage = _declarations("m08-analytics")[f"m8.bornes_{cle[3:]}"]
        assert valider_valeur(reglage, valeur) == valeur


# -- le schéma est fermé -------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("modification", "fragment"), [
    ({"inconnue": 1}, "inconnue"),
    ({"cle": "m3.jours_exemple"}, "clé « m2."),
    ({"cle": "jours"}, "clé « m2."),
    ({"type": "flottant"}, "type 'flottant' inconnu"),
    ({"niveau": "N4"}, "non pris en charge"),
    ({"niveau": "N0"}, "non pris en charge"),
    ({"niveau": None}, "non pris en charge"),
    ({"chemin": "segments.jours_exemple"}, "chemin"),
    ({"chemin": "configuration"}, "chemin"),
    ({"chemin": "configuration.Segments.x"}, "chemin"),
    ({"min": 100}, "min doit être inférieur à max"),
    ({"min": True}, "entier requis"),
    ({"unite": ""}, "unite"),
    ({"libelle": "x"}, "libelle"),
    ({"debloque": "court"}, "debloque"),
    ({"ordre": "croissant"}, "ordre ne concerne que"),
    ({"longueur": 3}, "longueur ne concerne que"),
    ({"longueur_max": 20}, "longueur_max ne concerne que"),
])
def test_une_declaration_mal_formee_est_refusee(modification, fragment):
    with pytest.raises(ValueError, match=fragment):
        _lire([_entree(**modification)])


def test_min_et_max_sont_obligatoires_une_borne_de_saisie_n_est_jamais_implicite():
    entree = _entree()
    del entree["max"]
    with pytest.raises(ValueError, match="min et max obligatoires"):
        _lire([entree])


def test_un_doublon_de_cle_et_un_conflit_de_chemin_sont_refuses():
    with pytest.raises(ValueError, match="en double"):
        _lire([_entree(), _entree(chemin="configuration.segments.autre")])
    with pytest.raises(ValueError, match="conflit"):
        _lire([_entree(), _entree(cle="m2.jours_autre", chemin="configuration.segments")])


def test_reglages_doit_etre_une_liste_d_objets():
    assert _lire(None) == ()
    with pytest.raises(ValueError, match="liste"):
        _lire({"cle": "x"})
    with pytest.raises(ValueError, match="objet"):
        _lire(["m2.jours_exemple"])


def _proposition(**plus):
    base = {"valeur": 30, "etiquette": ETIQUETTE_PROPOSITION,
            "justification": "Exemple fictif de justification écrite.",
            "source": "docs/architecture/ROLES.md"}
    return {**base, **plus}


@pytest.mark.parametrize(("modification", "fragment"), [
    ({"etiquette": "recommandation"}, "etiquette doit être exactement"),
    ({"etiquette": "validée"}, "etiquette doit être exactement"),
    ({"source": ""}, "source"),
    ({"justification": "courte"}, "justification"),
    ({"valeur": 1000}, "proposition.valeur"),
    ({"valeur": "30"}, "proposition.valeur"),
    ({"valeur": True}, "proposition.valeur"),
])
def test_une_proposition_sans_etiquette_source_justification_ou_hors_bornes_est_refusee(modification, fragment):
    with pytest.raises(ValueError, match=fragment):
        _lire([_entree(proposition=_proposition(**modification))])


def test_une_proposition_a_exactement_ses_quatre_champs():
    sans_source = _proposition()
    del sans_source["source"]
    with pytest.raises(ValueError, match="exactement"):
        _lire([_entree(proposition=sans_source)])
    with pytest.raises(ValueError, match="exactement"):
        _lire([_entree(proposition=_proposition(auto_adoption=True))])


def test_une_declaration_valide_se_charge_avec_sa_proposition():
    (r,) = _lire([_entree(proposition=_proposition())])
    assert r.cle == "m2.jours_exemple" and r.departement == "m02-revenue-crm" and r.proposition.valeur == 30
    assert r.chemin == ("configuration", "segments", "jours_exemple") and r.niveau is Niveau.N3


def test_un_manifeste_au_bloc_reglages_invalide_est_refuse_a_la_lecture(tmp_path):
    source = racine_departements() / "m02-revenue-crm"
    cible = tmp_path / "m02-revenue-crm"
    cible.mkdir()
    (cible / "SOUL.md").write_text((source / "SOUL.md").read_text(encoding="utf-8"), encoding="utf-8")
    donnees = yaml.safe_load((source / "department.yaml").read_text(encoding="utf-8"))
    donnees["reglages"][0]["niveau"] = "N4"
    for sous in (source / "skills").iterdir():
        (cible / "skills" / sous.name).mkdir(parents=True, exist_ok=True)
        (cible / "skills" / sous.name / "SKILL.md").write_text((sous / "SKILL.md").read_text(encoding="utf-8"),
                                                              encoding="utf-8")
    (cible / "department.yaml").write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="non pris en charge"):
        lire_manifeste(cible)
    donnees["reglages"][0]["niveau"] = "N3"
    (cible / "department.yaml").write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    assert lire_manifeste(cible).reglages[0].niveau is Niveau.N3


# -- la validation d'une valeur ----------------------------------------------------------------------------------
def _r(type_, **plus):
    base = {"entier": {"min": 1, "max": 100, "unite": "jours"}, "decimal": {"min": "0", "max": "100", "unite": "%"},
            "texte": {"longueur_max": 20}, "liste_entiers_croissants": {"min": 1, "max": 1000, "unite": "cents",
                                                                        "longueur": 3},
            "bornes_pire_cible": {"min": "-100", "max": "1000", "unite": "%", "ordre": "croissant"}}[type_]
    entree = _entree(type=type_, **{**base, **plus})
    if type_ == "texte":
        entree.pop("unite", None), entree.pop("min", None), entree.pop("max", None)
    return _lire([entree])[0]


@pytest.mark.parametrize(("brut", "attendu"), [(1, 1), (100, 100), (30, 30)])
def test_un_entier_dans_les_bornes_est_accepte(brut, attendu):
    assert valider_valeur(_r("entier"), brut) == attendu


@pytest.mark.parametrize("brut", [0, 101, -5, True, False, 30.0, 12.5, "30", None, [30], {"v": 30}, float("nan")])
def test_un_entier_refuse_booleen_flottant_texte_et_hors_bornes(brut):
    with pytest.raises(ReglageRefuse) as exc:
        valider_valeur(_r("entier"), brut)
    assert exc.value.code in {"REJ-REGLAGE-TYPE", "REJ-REGLAGE-HORS-BORNES"}


def test_les_bornes_sont_inclusives_au_cran_pres():
    reglage = _r("entier")
    assert valider_valeur(reglage, 1) == 1 and valider_valeur(reglage, 100) == 100
    for hors in (0, 101):
        with pytest.raises(ReglageRefuse) as exc:
            valider_valeur(reglage, hors)
        assert exc.value.code == "REJ-REGLAGE-HORS-BORNES"


@pytest.mark.parametrize(("brut", "attendu"), [("12.50", "12.5"), (40, "40"), ("40.0", "40"), (12.5, "12.5"),
                                              ("0", "0"),
                                              ("-0", "0"), ("1E+1", "10")])
def test_un_decimal_est_normalise_en_texte_jamais_en_flottant(brut, attendu):
    reglage = _r("decimal", min="-1000")
    assert valider_valeur(reglage, brut) == attendu


@pytest.mark.parametrize("brut", [True, None, "", "abc", "NaN", "Infinity", "1e999", 10**30, "100.01", "-0.5", [], {}])
def test_un_decimal_refuse_le_non_nombre_le_non_fini_et_le_hors_bornes(brut):
    with pytest.raises(ReglageRefuse):
        valider_valeur(_r("decimal"), brut)


def test_une_liste_exige_la_longueur_exacte_des_entiers_strictement_croissants_dans_les_bornes():
    reglage = _r("liste_entiers_croissants")
    assert valider_valeur(reglage, [10, 20, 30]) == [10, 20, 30]
    assert valider_valeur(reglage, (10, 20, 30)) == [10, 20, 30]
    for mauvais in ([10, 20], [10, 20, 30, 40], [10, 10, 30], [30, 20, 10], [0, 20, 30], [10, 20, 1001],
                    [10, 20, "30"], [10, 20, True], [10, 20, 30.0], "10,20,30", None, {}):
        with pytest.raises(ReglageRefuse):
            valider_valeur(reglage, mauvais)


def test_des_bornes_pire_cible_exigent_deux_nombres_distincts_dans_le_sens_declare():
    croissant = _r("bornes_pire_cible")
    assert valider_valeur(croissant, {"pire": "20", "cible": 60}) == {"pire": "20", "cible": "60"}
    for mauvais in ({"pire": 60, "cible": 20}, {"pire": 20, "cible": 20}, {"pire": 20},
                    {"pire": 20, "cible": 60, "x": 1},
                    {"pire": True, "cible": 60}, {"pire": "a", "cible": 60}, {"pire": -101, "cible": 60},
                    {"pire": 20, "cible": 1001}, [20, 60], "20;60", None):
        with pytest.raises(ReglageRefuse):
            valider_valeur(croissant, mauvais)
    decroissant = _r("bornes_pire_cible", ordre="decroissant")
    assert valider_valeur(decroissant, {"pire": 10, "cible": 0}) == {"pire": "10", "cible": "0"}
    with pytest.raises(ReglageRefuse) as exc:
        valider_valeur(decroissant, {"pire": 0, "cible": 10})
    assert "supérieure" in exc.value.detail


def test_un_texte_est_nettoye_borne_et_imprimable():
    reglage = _r("texte")
    assert valider_valeur(reglage, "  Nathan   (fictif) ") == "Nathan (fictif)"
    for mauvais in ("ab", "x" * 21, "ligne\x00nulle", 12, None, ["a"]):
        with pytest.raises(ReglageRefuse):
            valider_valeur(reglage, mauvais)


def test_la_normalisation_est_idempotente_et_deterministe():
    for type_, brut in (("entier", 7), ("decimal", "12.50"), ("liste_entiers_croissants", [1, 2, 3]),
                        ("bornes_pire_cible", {"pire": "1.50", "cible": "9"})):
        reglage = _r(type_)
        une = valider_valeur(reglage, copy.deepcopy(brut))
        assert valider_valeur(reglage, copy.deepcopy(une)) == une == valider_valeur(reglage, copy.deepcopy(brut))


# -- la saisie d'un formulaire -----------------------------------------------------------------------------------
def test_la_saisie_d_un_formulaire_se_lit_selon_le_type_sans_rien_deviner():
    assert analyser_saisie(_r("entier"), " 30 ") == 30
    assert analyser_saisie(_r("decimal"), "12,5") == "12.5"
    assert analyser_saisie(_r("liste_entiers_croissants"), "10, 20,30") == [10, 20, 30]
    assert analyser_saisie(_r("bornes_pire_cible"), "20 ; 60,5") == {"pire": "20", "cible": "60.5"}
    assert analyser_saisie(_r("texte"), "Nathan") == "Nathan"
    for reglage, mauvais in ((_r("entier"), "3.5"), (_r("entier"), "abc"), (_r("entier"), ""),
                             (_r("liste_entiers_croissants"), "1;2;3"), (_r("bornes_pire_cible"), "20"),
                             (_r("bornes_pire_cible"), "1;2;3")):
        with pytest.raises(ReglageRefuse):
            analyser_saisie(reglage, mauvais)
    with pytest.raises(ReglageRefuse):
        analyser_saisie(_r("entier"), "1" * 500)


def test_la_valeur_en_texte_se_rejoue_dans_la_saisie():
    for type_, valeur in (("entier", 7), ("liste_entiers_croissants", [1, 2, 3]),
                          ("bornes_pire_cible", {"pire": "1.5", "cible": "9"})):
        reglage = _r(type_)
        assert valider_valeur(reglage, analyser_saisie(reglage, declaration.valeur_en_texte(reglage, valeur))) == valeur
    assert declaration.valeur_en_texte(_r("entier"), None) == ""
    assert declaration.texte_decimal(Decimal("12.50")) == "12.5"
