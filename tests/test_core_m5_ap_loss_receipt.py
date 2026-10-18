"""Receipt transport checks; these do not qualify the real PostgreSQL commit witness."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def loss_gate(tmp_path, monkeypatch):
    import uvicorn

    from opsys import approbations, departements, serveur_mcp

    path = Path(__file__).resolve().parents[1] / "core/test/opsys-m5-ap-postcommit-fixture.py"
    spec = importlib.util.spec_from_file_location("m5_loss_receipt_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path))
    monkeypatch.setenv("OPSYS_MCP_JETON", "fictive-public-token")
    monkeypatch.setenv("OPSYS_CONTEXT_MCP_JETON", "fictive-context-token")
    monkeypatch.setattr(approbations, "_maintenant", approbations._maintenant)
    monkeypatch.setattr(module, "_configure", lambda: None)
    monkeypatch.setattr(module, "_original_handlers", lambda *_: None)
    monkeypatch.setattr(module, "_origins", lambda: {})
    monkeypatch.setattr(module.stockage, "migrer", lambda: None)
    monkeypatch.setattr(departements, "charger_departements", lambda: [])
    request = {
        "jsonrpc": "2.0",
        "id": "fictive-decision-1",
        "method": "tools/call",
        "params": {"name": module.M9_DECIDE, "arguments": {"demande_id": "fictive-demand"}},
    }
    headers = {"type": "http.response.start", "status": 200, "headers": [(b"x-fictive", b"1")]}
    body = b'{"jsonrpc":"2.0","id":"fictive-decision-1","result":{}}'
    forwarded = []

    async def application(scope, receive, send):
        assert (await receive())["body"] == json.dumps(request).encode()
        await send(headers)
        await send({"type": "http.response.body", "body": body, "more_body": False})

    monkeypatch.setattr(serveur_mcp, "application_http_departements", lambda *a, **k: application)

    def run(observed, **_kwargs):
        async def receive():
            return {"type": "http.request", "body": json.dumps(request).encode(), "more_body": False}

        async def send(message):
            forwarded.append(message)

        asyncio.run(observed({"type": "http", "method": "POST", "path": "/mcp/" + module.M9}, receive, send))

    monkeypatch.setattr(uvicorn, "run", run)
    return module, tmp_path, request, headers, body, forwarded


@pytest.mark.parametrize(
    "timestamp",
    [datetime(2026, 10, 17, 12, 10, tzinfo=UTC), "2026-10-17T12:10:00+00:00"],
    ids=["native-postgresql-datetime", "sqlite-string"],
)
def test_lost_response_receipt_serializes_timestamp_without_forwarding_body(loss_gate, monkeypatch, timestamp):
    module, home, request, headers, body, forwarded = loss_gate
    proof = {"fictif": True, "sql_cree_le": timestamp}

    def committed(actual_home, generation, actual_request, actual_headers, actual_body):
        assert (actual_home, generation, actual_request, actual_headers, actual_body) == (
            home,
            1,
            request,
            headers,
            body,
        )
        assert forwarded == []
        return proof

    monkeypatch.setattr(module, "_committed_decision", committed)
    with pytest.raises(RuntimeError, match="^FICTIVE_M9_DECISION_RESPONSE_LOST_AFTER_NATIVE_COMMIT$"):
        module.serve(12345, 1, True)
    receipt = json.loads((home / module.RESPONSE_LOST).read_text())
    assert receipt == {"fictif": True, "sql_cree_le": "2026-10-17T12:10:00+00:00", "original_headers_forwarded": True}
    assert proof == {"fictif": True, "sql_cree_le": timestamp}
    assert forwarded == [headers]
    assert not (home / module.GATE_REFUSED).exists()


def test_unproven_commit_keeps_headers_body_and_loss_receipt_blocked(loss_gate, monkeypatch):
    module, home, _, _, _, forwarded = loss_gate

    def unproven(*_args):
        raise RuntimeError("commit not proven")

    monkeypatch.setattr(module, "_committed_decision", unproven)
    with pytest.raises(RuntimeError, match="^commit not proven$"):
        module.serve(12345, 1, True)
    assert forwarded == []
    assert not (home / module.RESPONSE_LOST).exists()
    assert json.loads((home / module.GATE_REFUSED).read_text()) == {
        "fictif": True,
        "error": "RuntimeError",
        "reason": "commit not proven",
    }
