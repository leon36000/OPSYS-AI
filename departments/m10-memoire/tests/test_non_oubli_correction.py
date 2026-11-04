"""Correction M10-05 : contrats des registres (R2) et agrégats par occurrence (R1).

Toutes les données de ce fichier sont FICTIVES. Les maillons sont produits par le vrai
``registre.Registre`` et par les vrais outils d'écriture de M10 ; aucun stockage réel, aucune
ACL, aucun réseau n'est touché. Les tests R2 refusent les formes réellement malformées sans
interdire un maillon de registre valide qui sort du périmètre de la batterie.
"""

from __future__ import annotations

import pytest
from m10_memoire import amont, batterie, registre

HORODATAGE = "2026-11-02T09:00:00-05:00"


def _mini():
    return {
        "schema": batterie.SCHEMA_BATTERIE,
        "fictif": True,
        "version": "correction-fictive",
        "auteur": "correction fictive",
        "entreprise": "Entreprise fictive de correction",
        "documents": [{"id": "DOC-A", "domaine": "affaires", "texte": "Texte fictif A."}],
        "faits": [
            {
                "id": "F-A",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m1.lead_qualifie",
                "identifiant": "A-FICTIF-1",
                "sources": ["DOC-A"],
            }
        ],
        "questions": [
            {
                "id": "Q-A",
                "texte": "Quel lead fictif ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m1.lead_qualifie"],
                "attendus": ["F-A"],
            }
        ],
    }


def _deux_questions_meme_fait():
    corpus = _mini()
    corpus["questions"] = [
        {
            "id": "Q-PARTAGEE-1",
            "texte": "Première question fictive ?",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": ["F-A"],
        },
        {
            "id": "Q-PARTAGEE-2",
            "texte": "Seconde question fictive ?",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": ["F-A"],
        },
    ]
    return corpus


def _deux_questions_deux_faits_un_seul_retourne():
    """Q-1 retrouve F-A ; Q-2 attend F-B (absent) mais sa portée retourne F-A."""
    corpus = _mini()
    corpus["faits"].append(
        {
            "id": "F-B",
            "affaire_id": "A-FICTIF-1",
            "type_evenement": "m1.lead_qualifie",
            "identifiant": "A-FICTIF-2",
            "sources": ["DOC-A"],
        }
    )
    corpus["questions"] = [
        {
            "id": "Q-1",
            "texte": "Première question fictive ?",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": ["F-A"],
        },
        {
            "id": "Q-2",
            "texte": "Seconde question fictive ?",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": ["F-B"],
        },
    ]
    return corpus


def _lead(registre_cible):
    resultat, verdict = amont.memoriser(
        "m1.lead_qualifie",
        {
            "lead": {
                "lead_id": "A-FICTIF-1",
                "service": "gouttieres",
                "canal": "texte",
                "urgence_declaree": False,
            },
            "horodatage": HORODATAGE,
        },
        registre_cible,
    )
    assert verdict is None and resultat is not None
    return registre_cible


def _refus_evaluation(corpus, evenements, affaires, inventaire):
    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.evaluer_batterie(corpus, evenements, affaires, inventaire)
    assert erreur.value.code == "REJ-BATTERIE-FORME"


# ---------------------------------------------------------------------------------------------------------------
# R2 : les conteneurs et les maillons réellement malformés sont refusés, pas lus silencieusement
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "conteneur",
    [
        {},
        {"cle": "valeur"},
        {"DOC-A": 1},
        {"type_entree": "evenement_memorise"},
    ],
)
def test_un_mapping_comme_conteneur_de_maillons_est_refuse(conteneur):
    """Un registre est une séquence de maillons : un mapping n'est pas une séquence de maillons."""
    _refus_evaluation(_mini(), conteneur, [], ["DOC-A"])
    _refus_evaluation(_mini(), [], conteneur, ["DOC-A"])


@pytest.mark.parametrize("maillon", [None, 42, "texte", ["imbrique"]])
def test_un_maillon_non_mapping_est_refuse(maillon):
    """None, un entier, une chaîne ou une liste ne sont pas des maillons de registre."""
    _refus_evaluation(_mini(), [maillon], [], ["DOC-A"])
    _refus_evaluation(_mini(), [], [maillon], ["DOC-A"])


@pytest.mark.parametrize(
    "maillon",
    [
        {},
        {"cle": "valeur"},
        {"type_entree": "type_inconnu"},
        {"type_entree": 3},
        {"type_entree": None},
    ],
)
def test_un_maillon_sans_type_entree_ou_avec_type_inconnu_est_refuse(maillon):
    """Le contrat du registre exige un ``type_entree`` de son énuméré fermé."""
    _refus_evaluation(_mini(), [maillon], [], ["DOC-A"])
    _refus_evaluation(_mini(), [], [maillon], ["DOC-A"])


def test_un_evenement_valide_hors_perimetre_et_un_maillon_d_affaires_valide_sont_acceptes():
    """Ne pas confondre « hors périmètre de la batterie » et « malformé » : le registre accepte
    d'autres types d'entrée et un événement du bus que cette batterie ne modélise pas encore."""
    contrat = registre.types_entree()
    assert contrat == tuple(sorted(contrat))
    assert {"evenement_memorise", "fait_consolide", "fait_analytique"} <= set(contrat)
    evenements = _lead(registre.Registre())
    # Événement valide du bus, hors des faits attendus de cette batterie (devis envoyé, T4.7).
    evenements.ajouter(
        {
            "type_entree": "evenement_memorise",
            "type_evenement": "m3.devis_envoye",
            "lead_id": "A-FICTIF-1",
            "devis_id": "D-FICTIF-1",
            "chantier_id": None,
            "horodatage": HORODATAGE,
        }
    )
    evenements.ajouter(
        {
            "type_entree": "evenement_memorise",
            "type_evenement": "m9.evenement_futur_fictif",
            "lead_id": "A-FICTIF-1",
            "horodatage": HORODATAGE,
        }
    )
    affaires = registre.Registre()
    affaires.ajouter(
        {
            "type_entree": "fait_consolide",
            "horodatage": HORODATAGE,
            "cle_consolidation": "A-FICTIF-1:2026-11-02",
        }
    )
    affaires.ajouter(
        {"type_entree": "fait_analytique", "horodatage": HORODATAGE, "mesure_fictive": 1}
    )

    rapport = batterie.evaluer_batterie(_mini(), evenements.lire(), affaires.lire(), ["DOC-A"])

    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["par_question"][0]["retournes"] == 1
    assert rapport["nb_maillons_affaires"] == 2


def test_un_mapping_comme_inventaire_de_sources_est_refuse_et_ne_lit_pas_ses_cles():
    """Un dict d'inventaire n'est pas une liste d'identifiants : ses clés ne sont pas des sources."""
    _refus_evaluation(_mini(), [], [], {"DOC-A": 1})
    _refus_evaluation(_mini(), [], [], {"DOC-A": True})


def test_inventaire_none_reste_non_evaluable_et_liste_vide_reste_un_zero_connu():
    """Frontière du brief : ``None`` n'est pas ``[]`` ; ``[]`` est 0/N, pas une absence d'inventaire."""
    evenements = _lead(registre.Registre())

    sans_inventaire = batterie.evaluer_batterie(_mini(), evenements.lire(), [], None)
    assert sans_inventaire["couverture_sources"] == {
        "evaluable": False,
        "raison": batterie.RAISON_AUCUN_INVENTAIRE_SOURCES,
    }
    assert sans_inventaire["sources_absentes"] == []

    inventaire_vide = batterie.evaluer_batterie(_mini(), evenements.lire(), [], [])
    assert inventaire_vide["couverture_sources"] == {
        "evaluable": True,
        "numerateur": 0,
        "denominateur": 1,
        "valeur": 0.0,
        "valeur_pct": 0.0,
    }
    assert inventaire_vide["sources_absentes"] == [
        {"question": "Q-A", "fait": "F-A", "source": "DOC-A"}
    ]


# ---------------------------------------------------------------------------------------------------------------
# R1 : les agrégats sont des occurrences par question, pas une couverture d'ensemble
# ---------------------------------------------------------------------------------------------------------------
def test_deux_questions_partageant_un_fait_et_une_source_comptent_deux_occurrences():
    evenements = _lead(registre.Registre())
    corpus = _deux_questions_meme_fait()

    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], ["DOC-A"])
    assert rapport["rappel"]["numerateur"] == 2
    assert rapport["rappel"]["denominateur"] == 2
    assert rapport["couverture_sources"]["numerateur"] == 2
    assert rapport["couverture_sources"]["denominateur"] == 2
    assert {q["id"]: q["couverture_sources"]["denominateur"] for q in rapport["par_question"]} == {
        "Q-PARTAGEE-1": 1,
        "Q-PARTAGEE-2": 1,
    }

    # Une seule source DOC-A manque, mais DEUX occurrences la nomment (une par question).
    rapport_vide = batterie.evaluer_batterie(corpus, evenements.lire(), [], [])
    assert rapport_vide["couverture_sources"]["denominateur"] == 2
    assert rapport_vide["couverture_sources"]["numerateur"] == 0
    assert rapport_vide["sources_absentes"] == [
        {"question": "Q-PARTAGEE-1", "fait": "F-A", "source": "DOC-A"},
        {"question": "Q-PARTAGEE-2", "fait": "F-A", "source": "DOC-A"},
    ]


def test_le_rapport_declare_la_semantique_par_occurrence_et_ne_pretend_pas_une_couverture_d_ensemble():
    evenements = _lead(registre.Registre())
    rapport = batterie.evaluer_batterie(_deux_questions_meme_fait(), evenements.lire(), [], ["DOC-A"])

    semantique = rapport["semantique_agregation"]
    assert semantique["unite"] == "occurrence_par_question"
    assert semantique["couverture_ensemble"] is False
    assert "deux questions" in semantique["doublons"]
    assert "rappel" in semantique and "precision" in semantique and "couverture_sources" in semantique


def test_la_precision_agregee_suit_les_occurrences_par_question():
    """Q-1 retrouve F-A (1/1) ; Q-2 retourne F-A sans retrouver F-B (0/1) : précision 1/2, pas 1/1."""
    evenements = _lead(registre.Registre())
    rapport = batterie.evaluer_batterie(
        _deux_questions_deux_faits_un_seul_retourne(), evenements.lire(), [], ["DOC-A"]
    )

    par_question = {q["id"]: q for q in rapport["par_question"]}
    assert par_question["Q-1"]["precision"] == {
        "evaluable": True,
        "numerateur": 1,
        "denominateur": 1,
        "valeur": 1.0,
        "valeur_pct": 100.0,
    }
    assert par_question["Q-2"]["precision"] == {
        "evaluable": True,
        "numerateur": 0,
        "denominateur": 1,
        "valeur": 0.0,
        "valeur_pct": 0.0,
    }
    assert rapport["precision"] == {
        "evaluable": True,
        "numerateur": 1,
        "denominateur": 2,
        "valeur": 0.5,
        "valeur_pct": 50.0,
    }
    assert rapport["rappel"] == {
        "evaluable": True,
        "numerateur": 1,
        "denominateur": 2,
        "valeur": 0.5,
        "valeur_pct": 50.0,
    }
