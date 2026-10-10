"""SDK MCP réel en mémoire + SQLite FICTIF, sans HTTP/DEVICE opaque."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import anyio
import mcp_types as types
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError
from sqlalchemy import update

from opsys import stockage
from opsys.serveur_mcp import creer_serveur
from opsys.stockage.schema import PERSONNES

spec = importlib.util.spec_from_file_location(
    "lecture_mcp_cap_fictif", Path(__file__).with_name("test_documents_affaire_lecture_cap_appareil.py"),
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
monde = h.monde
FICTIF = True
META_IDENTITE = {"opsys/personne": h.fx.ACTEUR.personne, "opsys/role": "admin"}


def appeler(c, nom=h.NOMS[0], args=h.INDEX, meta=META_IDENTITE, **filters):
    async def scenario():
        async with Client(creer_serveur(c, **filters)) as client:
            return await client.call_tool(nom, args, meta=meta)

    return anyio.run(scenario)


def test_sdk_refus_ferme_sans_factory():
    result = appeler(h.cap(factory=h.interdite), args=None)
    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"ok": False, "erreur": "REJ-M10-LECTURE-FORME-INVALIDE"}


def test_sdk_sqlite_lecture_sans_meta_mutation_ni_trace(monde):
    h.fx._first()
    avant = h.tables()
    result = appeler(h.cap())
    assert result.is_error is False and len(result.content) == 1
    body = json.loads(result.content[0].text)
    assert set(body) == {"ok", "resultat"} and body["resultat"]["accepte"] is True
    assert body["resultat"]["resultat"]["total_versions"] == 1
    assert h.tables() == avant


@pytest.mark.parametrize("key,value,code", [
    ("opsys/idempotencyKey", "FICTIF", "FORME"),
    ("opsys/appareil", "FICTIF", "FORME"),
    ("opsys/horodatageAppareil", h.fx.HORA, "FORME"),
    ("opsys/cibleTicket", "FICTIF", "AUTORITE"),
    ("opsys/memoireLectureTicket", "FICTIF", "AUTORITE"),
    ("opsys/cfoGrantTicket", "FICTIF", "AUTORITE"),
    ("opsys/runtimeProfileId", "FICTIF", "AUTORITE"),
    ("opsys/runtimeProfileRevision", 1, "AUTORITE"),
    ("opsys/runtimeServer", "opsys_m10", "AUTORITE"),
])
def test_meta_mutation_ticket_profil_refuses_sans_factory(key, value, code):
    result = appeler(h.cap(factory=h.interdite), meta={**META_IDENTITE, key: value})
    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"ok": False, "erreur": f"REJ-M10-LECTURE-{code}-INVALIDE"}
    assert "FICTIF" not in result.content[0].text


@pytest.mark.parametrize("meta", [None, {}, {**META_IDENTITE, "opsys/role": "employee"},
                                      {**META_IDENTITE, "opsys/role": "seller"},
                                      {**META_IDENTITE, "opsys/role": " admin "}])
def test_mcp_identite_stricte_sans_factory(meta):
    result = appeler(h.cap(factory=h.interdite), meta=meta)
    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE"}


def test_sdk_omet_meta_null_sans_inventer_intention(monde):
    # SDK 2.2 serializes requests excluding None before the server handler.
    # This is a genuine pure read after omission, not a claim of rejecting raw null.
    before = h.tables()
    result = appeler(h.cap(), meta={**META_IDENTITE, "opsys/idempotencyKey": None})
    assert result.is_error is False
    body = json.loads(result.content[0].text)
    assert body["resultat"]["resultat"]["total_versions"] == 0
    assert set(body) == {"ok", "resultat"} and h.tables() == before


@pytest.mark.parametrize("filters", [{"outils_permis": frozenset()}, {"outils_caches": frozenset(h.NOMS)}])
def test_mcp_visibilite_refusee_sans_factory(filters):
    result = appeler(h.cap(factory=h.interdite), **filters)
    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE"}


@pytest.mark.parametrize("args", [[], [["affaire_id", h.fx.AFFAIRE]], "FICTIF", 7])
def test_sdk_reel_refuse_non_mapping_avant_handler(args):
    with pytest.raises(ValidationError):
        types.CallToolRequestParams(name=h.NOMS[0], arguments=args)


@pytest.mark.parametrize("quota", [1, 40])
def test_mcp_quota_trop_petit_erreur_sdk_sans_donnees(quota):
    with pytest.raises(Exception) as exc:
        appeler(h.cap(quota, h.interdite), args=None)

    def feuilles(error):
        if isinstance(error, BaseExceptionGroup):
            return [e for child in error.exceptions for e in feuilles(child)]
        return [error]

    errors = feuilles(exc.value)
    assert len(errors) == 1 and isinstance(errors[0], MCPError)
    assert errors[0].code == -32603 and errors[0].message == "Internal server error" and errors[0].data is None


def test_sdk_sql_detail_relecture_retrait_role_sql_et_purete(monde):
    ack = h.fx._first()["resultat"]["resultat"]
    args = {"affaire_id": h.fx.AFFAIRE, "document_ref": ack["document_ref"], "version_source": ack["version_source"]}
    c = h.cap()
    before = h.tables()
    result = appeler(c, h.NOMS[1], args)
    assert result.is_error is False
    dto = json.loads(result.content[0].text)["resultat"]["resultat"]
    assert len(dto) == 14 and dto["corps"] == h.fx.CORPS and before == h.tables()
    assert appeler(c, h.NOMS[1], args).content[0].text == result.content[0].text and before == h.tables()
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == h.fx.ACTEUR.personne).values(actif=False))
    before = h.tables()
    refused = appeler(c, h.NOMS[1], args)
    assert refused.is_error is True
    assert json.loads(refused.content[0].text) == {"ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE"}
    assert before == h.tables()


def test_autre_nom_historique_pas_de_cadre_lecture_documentaire():
    result = appeler(h.cap(factory=h.interdite), "inconnu_fictif", {}, meta=None)
    assert json.loads(result.content[0].text) == {"ok": False, "erreur": "outil_inconnu", "details": "inconnu_fictif"}
