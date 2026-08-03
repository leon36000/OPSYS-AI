import sys
from pathlib import Path

import pytest
import yaml

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import taux_fiscaux, validation

_CHEMIN_REEL = (
    Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
)


def _ecrire_yaml(chemin, contenu):
    chemin.write_text(yaml.safe_dump(contenu, sort_keys=False), encoding="utf-8")


def _item(**modifications):
    item = {
        "id": "tps_federale",
        "nom": "Taxe fédérale",
        "taux": 0.05,
        "version": "2026-v1",
        "source": "Source fiscale",
    }
    item.update(modifications)
    return item


def test_charger_fichier_reel():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_REEL)

    assert erreurs == []
    assert len(dictionnaire) == 2
    assert "tps_federale" in dictionnaire
    assert "tvq_quebec" in dictionnaire
    assert dictionnaire["tps_federale"]["taux"] == 0.05


def test_rechercher_taux_trouve():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_REEL)

    assert erreurs == []
    trouve, verdict = taux_fiscaux.rechercher_taux(
        dictionnaire, "tps_federale"
    )

    assert trouve is dictionnaire["tps_federale"]
    assert verdict is None


def test_rechercher_taux_absent():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_REEL)

    assert erreurs == []
    trouve, verdict = taux_fiscaux.rechercher_taux(
        dictionnaire, "taux_inexistant"
    )

    assert trouve is None
    assert verdict["code"] == "REJ-TAUX-INCONNU"


def test_code_verdict_taux_inconnu_est_declare():
    assert "REJ-TAUX-INCONNU" in validation.CODES_M5_LIST


def test_schema_version_invalide(tmp_path):
    chemin = tmp_path / "taux.yaml"
    _ecrire_yaml(
        chemin,
        {
            "schema_version": 2,
            "taux": [_item()],
        },
    )

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(chemin)

    assert erreurs
    assert dictionnaire == {}


@pytest.mark.parametrize(
    "item",
    [
        {
            "id": "tps_federale",
            "nom": "Taxe fédérale",
            "taux": 0.05,
            "version": "2026-v1",
            "source": "Source fiscale",
            "extra": "interdit",
        },
        {
            "nom": "Taxe fédérale",
            "taux": 0.05,
            "version": "2026-v1",
            "source": "Source fiscale",
        },
    ],
    ids=["cle-en-trop", "cle-manquante"],
)
def test_item_avec_cles_invalides_est_exclu(tmp_path, item):
    chemin = tmp_path / "taux.yaml"
    _ecrire_yaml(
        chemin,
        {
            "schema_version": 1,
            "taux": [item],
        },
    )

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(chemin)

    assert erreurs
    assert "tps_federale" not in dictionnaire
    assert dictionnaire == {}


def test_taux_chaine_est_exclu(tmp_path):
    chemin = tmp_path / "taux.yaml"
    _ecrire_yaml(
        chemin,
        {
            "schema_version": 1,
            "taux": [_item(taux="0.05")],
        },
    )

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(chemin)

    assert erreurs
    assert dictionnaire == {}


def test_taux_booleen_est_exclu(tmp_path):
    chemin = tmp_path / "taux.yaml"
    _ecrire_yaml(
        chemin,
        {
            "schema_version": 1,
            "taux": [_item(taux=True)],
        },
    )

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(chemin)

    assert erreurs
    assert dictionnaire == {}


def test_id_duplique_conserve_le_premier(tmp_path):
    chemin = tmp_path / "taux.yaml"
    premier = _item(nom="Premier taux", taux=0.05)
    second = _item(nom="Second taux", taux=0.10)
    _ecrire_yaml(
        chemin,
        {
            "schema_version": 1,
            "taux": [premier, second],
        },
    )

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(chemin)

    assert erreurs
    assert any(
        "dupli" in erreur.lower() and "tps_federale" in erreur
        for erreur in erreurs
    )
    assert dictionnaire["tps_federale"]["nom"] == "Premier taux"
    assert dictionnaire["tps_federale"]["taux"] == 0.05


def test_champ_texte_vide_est_exclu(tmp_path):
    chemin = tmp_path / "taux.yaml"
    _ecrire_yaml(
        chemin,
        {
            "schema_version": 1,
            "taux": [_item(source="")],
        },
    )

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(chemin)

    assert erreurs
    assert dictionnaire == {}
