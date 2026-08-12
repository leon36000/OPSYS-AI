"""Prouve que la passerelle de consensus refuse tout schéma d'URL hors liste blanche.

Ce test existe parce que bandit signale `urlopen` (B310) sans pouvoir suivre la
garde placée en amont : l'annotation `# nosec B310` de `consensus_run.py` n'est
donc PAS une affirmation, elle renvoie ici. Si la garde disparaissait, ce test
rougirait — c'est lui qui la prouve, pas le commentaire.
"""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consensus_run import (  # noqa: E402 — chemin ajouté ci-dessus
    _SCHEMAS_RESEAU_AUTORISES,
    TransportError,
    _valider_schema_url,
)


@pytest.mark.parametrize(
    "url_refusee",
    [
        "file:///etc/passwd",
        "ftp://exemple.invalid/x",
        "gopher://exemple.invalid/x",
        "data:text/plain,coucou",
        "/chemin/sans/schema",
    ],
)
def test_refuse_tout_schema_hors_liste_blanche(url_refusee: str) -> None:
    """Prouve le refus par LISTE BLANCHE : un schéma inconnu est refusé par défaut,
    et pas seulement les quelques schémas qu'on aurait pensé à interdire."""
    with pytest.raises(TransportError) as erreur:
        _valider_schema_url(url_refusee)
    assert "Schéma refusé" in str(erreur.value)


@pytest.mark.parametrize(
    ("url_acceptee", "schema_attendu"),
    [("http://127.0.0.1:4000/v1", "http"), ("https://exemple.invalid/v1", "https")],
)
def test_accepte_les_deux_schemas_reseau_autorises(
    url_acceptee: str, schema_attendu: str
) -> None:
    """Prouve que la garde ne casse pas le chemin nominal ET que ce qui passe est
    bien un membre de la liste blanche — un simple « ne lève pas » ne prouverait
    rien sur CE QUI a été autorisé."""
    _valider_schema_url(url_acceptee)
    assert urllib.parse.urlsplit(url_acceptee).scheme == schema_attendu
    assert schema_attendu in _SCHEMAS_RESEAU_AUTORISES


def test_la_liste_blanche_ne_contient_que_les_deux_schemas_reseau() -> None:
    """Prouve que la liste blanche n'a pas été élargie en silence : tout ajout
    futur d'un schéma doit passer par la modification EXPLICITE de ce test."""
    assert _SCHEMAS_RESEAU_AUTORISES == frozenset({"http", "https"})
