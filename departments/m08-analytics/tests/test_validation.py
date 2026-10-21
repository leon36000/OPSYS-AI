import pytest
from m8_analytics import validation


@pytest.fixture
def dictionnaire_m7():
    return {
        "M7-marketing": {
            "m7_cpl": {
                "id": "m7_cpl",
                "nom": "Coût par lead",
                "definition": "Coût total marketing divisé par le nombre de leads.",
                "unite": "CAD/lead",
                "source_donnees": "Module M7",
                "frequence": "mensuelle",
                "consommateur": "entrepôt M8",
            }
        }
    }


def test_valider_snapshot_valide_contre_dictionnaire_local(dictionnaire_m7):
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"m7_cpl": "42.0"},
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (True, None)


def test_valider_snapshot_rejette_cle_manquante(dictionnaire_m7):
    snapshot = {
        "module_source": "M7-marketing",
        "valeurs": {"m7_cpl": "42.0"},
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (
        False,
        "REJ-SNAPSHOT-STRUCTURE-INVALIDE",
    )


def test_valider_snapshot_rejette_cle_inattendue(dictionnaire_m7):
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"m7_cpl": "42.0"},
        "extra": "interdit",
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (
        False,
        "REJ-SNAPSHOT-STRUCTURE-INVALIDE",
    )


def test_valider_snapshot_rejette_valeurs_non_dict(dictionnaire_m7):
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": "pas un dict",
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (
        False,
        "REJ-SNAPSHOT-STRUCTURE-INVALIDE",
    )


def test_valider_snapshot_rejette_module_inconnu_avec_code_distinct(dictionnaire_m7):
    snapshot = {
        "module_source": "Module-inconnu",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {},
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (
        False,
        "REJ-SNAPSHOT-MODULE-INCONNU",
    )


def test_valider_snapshot_rejette_metric_id_inconnu_pour_module(dictionnaire_m7):
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"m7_inconnue": "42.0"},
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (
        False,
        "REJ-SNAPSHOT-METRIC-ID-INCONNU",
    )


def test_valider_snapshot_verifie_metric_id_dans_le_module_du_snapshot():
    dictionnaire = {
        "ModuleA": {
            "a_x": {
                "id": "a_x",
                "nom": "A",
                "definition": "Définition A",
                "unite": "unité",
                "source_donnees": "source A",
                "frequence": "mensuelle",
                "consommateur": "entrepôt M8",
            }
        },
        "ModuleB": {
            "b_y": {
                "id": "b_y",
                "nom": "B",
                "definition": "Définition B",
                "unite": "unité",
                "source_donnees": "source B",
                "frequence": "mensuelle",
                "consommateur": "entrepôt M8",
            }
        },
    }
    snapshot = {
        "module_source": "ModuleA",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"b_y": "1"},
    }

    assert validation.valider_snapshot(snapshot, dictionnaire) == (
        False,
        "REJ-SNAPSHOT-METRIC-ID-INCONNU",
    )


def test_valider_snapshot_rejette_une_valeur_numerique(dictionnaire_m7):
    """PRD §5.2 : les valeurs de SnapshotModule sont TOUJOURS du texte — la
    conversion numérique n'a lieu QUE dans la couche sémantique (semantique.py),
    jamais avant. Un snapshot est un fait rapporté, pas encore un calcul.
    """
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"m7_cpl": 42.0},
    }

    valide, code = validation.valider_snapshot(snapshot, dictionnaire_m7)

    assert valide is False
    assert isinstance(code, str)
    assert code.startswith("REJ-")


def test_valider_snapshot_rejette_un_booleen_comme_valeur(dictionnaire_m7):
    """bool est une sous-classe d'int en Python : garde explicite requise."""
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {"m7_cpl": True},
    }

    valide, code = validation.valider_snapshot(snapshot, dictionnaire_m7)

    assert valide is False
    assert code.startswith("REJ-")


def test_valider_snapshot_accepte_valeurs_vides(dictionnaire_m7):
    snapshot = {
        "module_source": "M7-marketing",
        "horodatage": "2026-01-01T00:00:00Z",
        "valeurs": {},
    }

    assert validation.valider_snapshot(snapshot, dictionnaire_m7) == (True, None)
