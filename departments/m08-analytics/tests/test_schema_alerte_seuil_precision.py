"""Compatibilité du schéma d'événement : seuil exact, valeur affichée à deux décimales."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from m8_analytics import mesures_chantier as mc


_SCHEMA = Path(__file__).resolve().parents[3] / "src" / "opsys" / "evenements" / "catalogue" / "m8.alerte_proposee.json"


def _charge(seuil: str, valeur: str = "33.34"):
    evaluation = {
        "metric_id": "m8_ecart_duree_pct", "valeur": valeur, "unite": "pourcentage",
        "sens": "au_dessus", "seuil": seuil,
    }
    mesure = {"nom": "Écart de durée", "version_definition": "empreinte-fictive"}
    definition = {"source_donnees": "faits QA fictifs"}
    return mc._charge_franchi(
        "qa-wct-fictif", evaluation, mesure, definition, "2026-02-01T12:00:00Z",
    )


def test_schema_evenement_accepte_anciens_seuils_et_precision_declared_supérieure():
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    charge_ancienne = _charge("33.30")
    charge_precise = _charge("33.335")

    jsonschema.validate(charge_ancienne, schema)
    jsonschema.validate(charge_precise, schema)
    assert charge_precise["preuve"]["valeur"] == "33.34"
    assert charge_precise["preuve"]["seuil"] == "33.335"
    assert "seuil configuré 33.335" in charge_precise["pourquoi"]


def test_schema_evenement_garde_la_valeur_a_deux_decimales_et_rejette_un_seuil_sous_deux():
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_charge("33.3"), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_charge("33.335", valeur="33.333"), schema)
