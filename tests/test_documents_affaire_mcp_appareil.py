"""SDK MCP en mémoire FICTIF, sans transport HTTP/stdio ou autorité DEVICE opaque."""

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

from opsys.capacites import Capacites
from opsys.serveur_mcp import creer_serveur

NOMS = (
    "m10_deposer_version_document_appareil",
    "m10_activer_version_document_appareil",
    "m10_retirer_document_appareil",
)
FICTIF = True

fixture_cap = Path(__file__).parent / "test_documents_affaire_cap_appareil.py"
spec = importlib.util.spec_from_file_location("fixture_mcp_cap_documents_fictifs", fixture_cap)
caph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(caph)
monde = caph.monde


def cap(quota=6000):
    def interdite():
        raise AssertionError("Aucune factory ne doit être ouverte.")

    return Capacites({}, interdite, limite_sortie=quota, memoire=False)


def appeler(c, nom, args, meta=None, **filters):
    async def scenario():
        async with Client(creer_serveur(c, **filters)) as client:
            return await client.call_tool(nom, args, meta=meta)

    return anyio.run(scenario)


@pytest.mark.parametrize("nom", NOMS)
@pytest.mark.parametrize(
    "meta",
    [
        None,
        {"opsys/idempotencyKey": 17},
        {"opsys/personne": "FICTIF", "opsys/role": "admin", "opsys/runtimeProfileId": "FICTIF"},
        {"opsys/cfoGrantTicket": "FICTIF"},
    ],
)
def test_named_errors_early_no_raw_detail_or_factory(nom, meta):
    r = appeler(cap(), nom, None, meta)
    assert r.is_error is True and len(r.content) == 1
    value = json.loads(r.content[0].text)
    assert set(value) == {"ok", "erreur"} and value["ok"] is False
    assert value["erreur"] in {"REJ-M10-DOC-AUTORITE-INVALIDE", "REJ-M10-DOC-FORME-INVALIDE"}
    assert "FICTIF" not in r.content[0].text


@pytest.mark.parametrize("filters", [{"outils_permis": frozenset()}, {"outils_caches": frozenset(NOMS)}])
def test_named_visibility_closed_without_details(filters):
    value = json.loads(appeler(cap(), NOMS[0], {}, **filters).content[0].text)
    assert value == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}


def test_named_tiny_quota_meta_error_constant40():
    response = appeler(cap(40), NOMS[0], None, {"opsys/idempotencyKey": 3})
    assert response.is_error is True and len(response.content[0].text) == 40
    assert json.loads(response.content[0].text) == {"ok": False, "erreur": "QUOTA-DEPASSE"}


def test_named_q1_technical_no_business_frame():
    with pytest.raises(Exception) as exc:
        appeler(cap(1), NOMS[0], None)

    def leaves(error):
        if isinstance(error, BaseExceptionGroup):
            return [item for child in error.exceptions for item in leaves(child)]
        return [error]

    errors = leaves(exc.value)
    assert len(errors) == 1 and isinstance(errors[0], MCPError)
    assert errors[0].code == -32603
    assert errors[0].message == "Internal server error" and errors[0].data is None


@pytest.mark.parametrize("args", [[], [["affaire_id", "FICTIF"]], 1, "FICTIF"])
def test_sdk_params_non_mapping_refused_before_handler(args):
    with pytest.raises(ValidationError):
        types.CallToolRequestParams(name=NOMS[0], arguments=args)


def test_other_name_legacy_unknown_shape_unchanged():
    r = appeler(cap(), "outil_fictif_inconnu", {})
    assert json.loads(r.content[0].text) == {"ok": False, "erreur": "outil_inconnu", "details": "outil_fictif_inconnu"}


def test_sdk_reel_cap_sql_frame_own_replay_role_et_legacy(monde):
    fx, tables = caph.fx, caph.tables
    from sqlalchemy import update

    from opsys import stockage
    from opsys.stockage.schema import PERSONNES

    meta = {
        "opsys/idempotencyKey": fx.META.cle,
        "opsys/appareil": fx.META.appareil,
        "opsys/horodatageAppareil": fx.HORA,
        "opsys/personne": fx.ACTEUR.personne,
        "opsys/role": "admin",
    }
    c = caph.cap()
    first = appeler(c, NOMS[0], fx.ARGS, meta)
    assert first.is_error is False
    body = json.loads(first.content[0].text)
    assert body["rejoue"] is False and set(body) == {"ok", "resultat", "rejoue"}
    assert body["resultat"]["resultat"]["horodatage_appareil_declare"] == fx.HORA
    after = tables()
    replay = appeler(c, NOMS[0], fx.ARGS, meta)
    assert json.loads(replay.content[0].text) == {**body, "rejoue": True} and after == tables()
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == fx.ACTEUR.personne).values(actif=False))
    before = tables()
    refused = appeler(c, NOMS[0], fx.ARGS, meta)
    assert refused.is_error is True
    assert json.loads(refused.content[0].text) == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}
    assert before == tables()
