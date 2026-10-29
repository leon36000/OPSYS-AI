"""M9.10 — schéma proposé à 21 sections : forme, honnêteté des manques, ancrage et compatibilité 15 clés (fictif)."""

import copy

import pytest
from m9_strategic_intelligence import contrats, rapport_decision_v2, rapport_strategique

FICTIF = True


def _element(identifiant, texte, refs=None, **extra):
    element = {"id": identifiant, "texte": texte}
    if refs is not None:
        element["refs"] = refs
    return element | extra


def _sections():
    """Rapport complet fictif : chaque section renseignée, toutes les références ancrées en amont."""
    manque = {"statut": "NON_DISPONIBLE", "raison": "aucune prévision M5 publiée pour cet horizon"}
    return {
        "question": {"statut": "RENSEIGNEE", "contenu": {"texte": "Faut-il retarder le chantier fictif C-1 ?"}},
        "etat": {"statut": "RENSEIGNEE", "contenu": [_element("ET1", "M6 signale un stock insuffisant (fictif)")]},
        "donnees_utilisees": {
            "statut": "RENSEIGNEE",
            "contenu": [
                _element("E1", "snapshot M6 index 3 hash aaaa"),
                _element("E2", "snapshot M4 index 7 hash bbbb"),
            ],
        },
        "donnees_manquantes": {
            "statut": "RENSEIGNEE",
            "contenu": [_element("DM1", "coût de remplacement M5 non publié", ["E1"])],
        },
        "contradictions": manque | {"raison": "aucune contradiction détectée dans la capture"},
        "hypotheses": {"statut": "RENSEIGNEE", "contenu": [_element("H1", "le fournisseur livre sous 10 jours")]},
        "incertitudes": {
            "statut": "RENSEIGNEE",
            "contenu": [_element("IN1", "délai fournisseur non confirmé", ["H1"])],
        },
        "diagnostic": {
            "statut": "RENSEIGNEE",
            "contenu": [_element("D1", "rupture probable avant le chantier", ["E1", "E2"])],
        },
        "options_alternatives": {
            "statut": "RENSEIGNEE",
            "contenu": [
                _element("O1", "retarder d'une semaine", ["D1"]),
                _element("O2", "substituer le matériau", ["D1", "H1"]),
            ],
        },
        "scenarios": {"statut": "RENSEIGNEE", "contenu": [_element("S1", "retard de 7 jours", ["O1"])]},
        "impacts": {
            "statut": "RENSEIGNEE",
            "contenu": [
                _element("I1", "décalage de l'équipe", ["S1"], valeur="7", unite="jours", source_calcul="m4:capacite"),
            ],
        },
        "dependances": {"statut": "RENSEIGNEE", "contenu": [_element("DP1", "dépend de la livraison M6", ["E1"])]},
        "risques": {"statut": "RENSEIGNEE", "contenu": [_element("R1", "perte du créneau client", ["I1"])]},
        "priorites": {"statut": "RENSEIGNEE", "contenu": [_element("P1", "protéger le chantier C-1", ["D1"])]},
        "decision_recommandee": {
            "statut": "RENSEIGNEE",
            "contenu": [_element("DR1", "retarder d'une semaine", ["O1", "R1"])],
        },
        "conditions": {"statut": "RENSEIGNEE", "contenu": [_element("C1", "le client accepte le report", ["DR1"])]},
        "validation": {"statut": "RENSEIGNEE", "contenu": [_element("V1", "approbation du propriétaire requise")]},
        "plan_action": {"statut": "RENSEIGNEE", "contenu": [_element("A1", "proposer la nouvelle date", ["DR1"])]},
        "taches_par_departement": {
            "statut": "RENSEIGNEE",
            "contenu": [_element("T1", "M4 : reporter la visite", ["A1"])],
        },
        "mesure_succes_suivi": {
            "statut": "RENSEIGNEE",
            "contenu": [_element("MS1", "chantier livré sans rupture", ["DR1"])],
        },
        "memoire_m10": manque | {"raison": "aucun précédent M10 consulté dans cette capture"},
    }


def _rapport(sections=None):
    return rapport_decision_v2.assembler(sections if sections is not None else _sections())


def _code(rapport):
    valide, code = rapport_decision_v2.valider_rapport_decision_v2(rapport)
    assert valide is False and code.startswith("REJ-RAPPORT-V2-")
    return code


def test_enumeration_a_21_sections_et_origine_tracee():
    rapport_decision_v2.controler_enumeration()
    assert len(rapport_decision_v2.IDS_SECTIONS) == 21 and len(set(rapport_decision_v2.IDS_SECTIONS)) == 21
    assert set(rapport_decision_v2.origines().values()) == {"definition", "historique", "cahier"}
    # Les douze notions citées par la définition produit sont présentes (question…mesure du succès).
    for nom in (
        "question",
        "decision_recommandee",
        "options_alternatives",
        "donnees_utilisees",
        "donnees_manquantes",
        "hypotheses",
        "scenarios",
        "impacts",
        "dependances",
        "conditions",
        "validation",
        "plan_action",
        "mesure_succes_suivi",
    ):
        assert nom in rapport_decision_v2.IDS_SECTIONS


def test_les_15_cles_historiques_ont_chacune_une_section_distincte():
    correspondance = rapport_decision_v2.mapping_historique()
    assert set(correspondance) == set(contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    assert len(set(correspondance.values())) == 15
    assert all(section in rapport_decision_v2.IDS_SECTIONS for section in correspondance.values())


def test_rapport_complet_valide_et_jamais_presente_comme_ratifie():
    rapport = _rapport()
    assert rapport_decision_v2.valider_rapport_decision_v2(rapport) == (True, None)
    assert rapport["statut_contrat"] == "RETENU_PAR_DELEGATION"
    ratifie = copy.deepcopy(rapport)
    ratifie["statut_contrat"] = "RATIFIE"
    ratifie["rapport_id"] = rapport_decision_v2.identifiant(ratifie)
    assert _code(ratifie) == "REJ-RAPPORT-V2-SCHEMA"
    ancien = copy.deepcopy(rapport)
    ancien["statut_contrat"] = "PROPOSITION_NON_RATIFIEE"
    ancien["rapport_id"] = rapport_decision_v2.identifiant(ancien)
    assert _code(ancien) == "REJ-RAPPORT-V2-SCHEMA"
    assert any("délégation de Nathan" in x and "source canonique absente" in x for x in rapport["limites"])


def test_projection_vers_les_15_cles_passe_le_validateur_historique_inchange():
    projection = rapport_decision_v2.vers_contrat_historique(_rapport())
    assert set(projection) == set(contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    assert rapport_strategique.valider_rapport_strategique(projection) == (True, None)
    # Une section non disponible reste None : aucun contenu inventé pour satisfaire l'ancien contrat.
    assert projection["memoire_m10"] is None
    assert projection["recommandations"][0]["id"] == "DR1"


@pytest.mark.parametrize("section", rapport_decision_v2.IDS_SECTIONS)
def test_section_manquante_ou_en_trop_refusee(section):
    sections = _sections()
    del sections[section]
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-SECTIONS"
    sections = _sections()
    sections["section_inventee"] = {"statut": "NON_APPLICABLE", "raison": "x"}
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-SECTIONS"


def _rapport_brut(sections):
    """Enveloppe sans passer par assembler (qui valide) : pour tester le refus du validateur."""
    rapport = {
        "schema": rapport_decision_v2.SCHEMA,
        "statut_contrat": rapport_decision_v2.STATUT_CONTRAT,
        "rapport_id": "",
        "version": 1,
        "sections": sections,
        "limites": ["limite fictive"],
    }
    rapport["rapport_id"] = rapport_decision_v2.identifiant(rapport)
    return rapport


def test_un_manque_dit_sa_raison_et_ne_porte_aucun_contenu():
    sections = _sections()
    sections["memoire_m10"] = {"statut": "NON_DISPONIBLE"}
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-MANQUE"
    sections["memoire_m10"] = {"statut": "NON_DISPONIBLE", "raison": "absent", "contenu": [_element("X", "inventé")]}
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-MANQUE"
    sections["memoire_m10"] = {"statut": "VIDE", "raison": "?"}
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-SECTION"


def test_une_abstention_est_un_rapport_valide():
    sections = _sections()
    sections["decision_recommandee"] = {"statut": "NON_DISPONIBLE", "raison": "données M5 manquantes : abstention"}
    for suivant in ("conditions", "plan_action", "taches_par_departement", "mesure_succes_suivi"):
        sections[suivant] = {"statut": "NON_APPLICABLE", "raison": "aucune décision à suivre"}
    assert rapport_decision_v2.valider_rapport_decision_v2(_rapport_brut(sections)) == (True, None)


@pytest.mark.parametrize(
    "section",
    [
        "diagnostic",
        "options_alternatives",
        "scenarios",
        "impacts",
        "dependances",
        "risques",
        "priorites",
        "decision_recommandee",
        "conditions",
        "plan_action",
        "taches_par_departement",
        "mesure_succes_suivi",
    ],
)
def test_aucune_assertion_sans_source_ni_hypothese(section):
    sections = _sections()
    sections[section]["contenu"][0].pop("refs", None)
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-SANS-ANCRAGE"


def test_reference_inconnue_ulterieure_ou_circulaire_refusee():
    sections = _sections()
    sections["diagnostic"]["contenu"][0]["refs"] = ["E-INCONNU"]
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-REFERENCE"
    sections = _sections()
    sections["diagnostic"]["contenu"][0]["refs"] = ["DR1"]  # déclaré plus loin : jamais en avant
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-REFERENCE"
    sections = _sections()
    sections["options_alternatives"]["contenu"][0]["refs"] = ["O1"]  # soi-même
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-REFERENCE"


def test_identifiants_distincts_dans_tout_le_rapport():
    sections = _sections()
    sections["diagnostic"]["contenu"][0]["id"] = "E1"
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-ELEMENT"


def test_une_valeur_exige_unite_et_proprietaire_du_calcul():
    sections = _sections()
    del sections["impacts"]["contenu"][0]["source_calcul"]
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-VALEUR"
    sections = _sections()
    sections["impacts"]["contenu"][0]["valeur"] = 7  # un nombre natif n'est pas admis : texte seulement
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-VALEUR"
    sections = _sections()
    sections["etat"]["contenu"][0]["unite"] = "jours"
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-VALEUR"


def test_empreinte_liee_au_contenu():
    rapport = _rapport()
    rapport["sections"]["question"]["contenu"]["texte"] = "autre question"
    assert _code(rapport) == "REJ-RAPPORT-V2-EMPREINTE"


@pytest.mark.parametrize("mauvais", [None, [], "texte", 3, {"schema": "x"}])
def test_entree_malformee_refusee_sans_exception(mauvais):
    valide, code = rapport_decision_v2.valider_rapport_decision_v2(mauvais)
    assert valide is False and code.startswith("REJ-RAPPORT-V2-")


def test_json_non_fini_et_champs_etrangers_refuses():
    sections = _sections()
    sections["etat"]["contenu"][0]["texte"] = float("nan")
    assert _code(_rapport_brut_sans_empreinte(sections)) == "REJ-RAPPORT-V2-STRUCTURE"
    sections = _sections()
    sections["etat"]["contenu"][0]["secret"] = "x"
    assert _code(_rapport_brut(sections)) == "REJ-RAPPORT-V2-ELEMENT"


def _rapport_brut_sans_empreinte(sections):
    return {
        "schema": rapport_decision_v2.SCHEMA,
        "statut_contrat": rapport_decision_v2.STATUT_CONTRAT,
        "rapport_id": "0" * 64,
        "version": 1,
        "sections": sections,
        "limites": ["x"],
    }
