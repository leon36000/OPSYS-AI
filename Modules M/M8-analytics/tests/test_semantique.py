import copy
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import encodage, registre, semantique
from m8_analytics.contrats import CHAMPS_DEFINITION_METRIQUE


def _definition():
    return {
        champ: f"valeur de test pour {champ}"
        for champ in CHAMPS_DEFINITION_METRIQUE
    }


def _ajouter(registre_cible, module_source, horodatage, valeurs):
    registre_cible.ajouter(
        {
            "module_source": module_source,
            "horodatage": horodatage,
            "valeurs": valeurs,
        }
    )


def test_deriver_metrique_retourne_la_valeur_d_un_unique_snapshot():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_cpl": "42.5"},
    )

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert resultat["valeur"] == 42.5
    assert resultat["n"] == 1
    assert resultat["fraicheur"] == 3.0
    assert resultat["version_definition"] == encodage.empreinte(definition)


def test_deriver_metrique_choisit_le_dernier_snapshot_par_ordre_du_registre():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-10T00:00:00Z",
        {"m7_cpl": "10"},
    )
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_cpl": "20"},
    )

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-11T00:00:00Z",
    )

    assert resultat["valeur"] == 20.0
    assert resultat["valeur"] != 10.0
    assert resultat["n"] == 2


def test_deriver_metrique_exclut_les_valeurs_non_numeriques_du_compte_et_du_choix():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_cpl": "15.0"},
    )
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-02T00:00:00Z",
        {"m7_cpl": "abc"},
    )
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-03T00:00:00Z",
        {"m7_cpl": "25.0"},
    )

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert resultat["n"] == 2
    assert resultat["valeur"] == 25.0


def test_deriver_metrique_echoue_ferme_sans_snapshot_et_sans_fraicheur():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert resultat == {
        "metric_id": "m7_cpl",
        "valeur": None,
        "version_definition": encodage.empreinte(definition),
        "fraicheur": None,
        "n": 0,
    }


def test_deriver_metrique_echoue_ferme_si_seules_des_valeurs_non_numeriques_existent():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_cpl": "non-numerique"},
    )

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert resultat["n"] == 0
    assert resultat["valeur"] is None


def test_deriver_metrique_filtre_strictement_le_module_source():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_cpl": "5"},
    )
    _ajouter(
        registre_cible,
        "AutreModule",
        "2026-01-02T00:00:00Z",
        {"m7_cpl": "999"},
    )

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert resultat["valeur"] == 5.0
    assert resultat["n"] == 1


def test_deriver_metrique_versionne_la_definition_selon_son_contenu():
    registre_cible = registre.RegistreSnapshots()
    definition_initiale = _definition()
    definition_modifiee = copy.deepcopy(definition_initiale)
    definition_modifiee["nom"] = definition_initiale["nom"] + "x"
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_cpl": "42.5"},
    )

    resultat_initial = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition_initiale,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )
    resultat_modifie = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition_modifiee,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert (
        resultat_initial["version_definition"]
        != resultat_modifie["version_definition"]
    )


def test_deriver_metrique_ignore_un_autre_metric_id_du_meme_module():
    registre_cible = registre.RegistreSnapshots()
    definition = _definition()
    _ajouter(
        registre_cible,
        "M7-marketing",
        "2026-01-01T00:00:00Z",
        {"m7_roi_par_canal": "1.0"},
    )

    resultat = semantique.deriver_metrique(
        "M7-marketing",
        "m7_cpl",
        definition,
        registre_cible,
        "2026-01-04T00:00:00Z",
    )

    assert resultat["n"] == 0
    assert resultat["valeur"] is None
