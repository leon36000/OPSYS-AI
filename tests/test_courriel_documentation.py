"""La documentation des connecteurs courriel suit le code : codes de refus, scopes, tables, paquet déclaré."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from opsys.courriel_connecteurs.erreurs import CODES_COURRIEL
from opsys.courriel_connecteurs.oauth import PORTEES_GMAIL, PORTEES_GRAPH
from opsys.stockage import schema

RACINE = Path(__file__).resolve().parents[1]
DOC = (RACINE / "docs" / "architecture" / "CONNECTEURS-COURRIEL.md").read_text(encoding="utf-8")


def test_les_codes_de_la_documentation_sont_ceux_du_catalogue():
    dans_doc = set(re.findall(r"`(REJ-COURRIEL-[A-Z0-9-]+)`", DOC))
    assert set(CODES_COURRIEL) <= dans_doc
    assert dans_doc <= set(CODES_COURRIEL), sorted(dans_doc - set(CODES_COURRIEL))
    assert len(set(CODES_COURRIEL)) == len(CODES_COURRIEL)


def test_les_portees_minimales_sont_documentees_avec_leur_source():
    for portee in (*PORTEES_GMAIL.lecture, *PORTEES_GMAIL.envoi, *PORTEES_GRAPH.lecture, *PORTEES_GRAPH.envoi):
        assert f"`{portee}`" in DOC, portee
    assert "developers.google.com/workspace/gmail/api/auth/scopes" in DOC
    assert "learn.microsoft.com/graph/permissions-reference" in DOC


def test_les_tables_du_chantier_sont_documentees():
    tables = {nom for nom in schema.META.tables if nom.startswith("courriel_")}
    assert tables and all(f"`{nom}`" in DOC for nom in tables)


def test_le_paquet_est_declare_et_le_statut_est_honnete():
    declares = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["packages"]
    assert "opsys.courriel_connecteurs" in declares
    assert "qualifié contre des DOUBLES seulement" in DOC and "Jamais exécuté contre un vrai service" in DOC
    assert not re.search(r"\b(complet|qualifié pour la production)\b", DOC.split("## 12.")[0].split("Statut")[1][:400])
