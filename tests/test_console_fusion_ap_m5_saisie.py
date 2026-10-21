"""Parcours HTTP explicite de saisie M5 depuis une observation AP Fusion."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsys import identite, stockage

_BASE_PATH = Path(__file__).with_name("test_console_fusion_ap_m5.py")
_BASE_SPEC = importlib.util.spec_from_file_location("_fusion_ap_m5_http_base", _BASE_PATH)
assert _BASE_SPEC is not None and _BASE_SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = _BASE
_BASE_SPEC.loader.exec_module(_BASE)

_URL_SAISIE = "/fusion/pdf/lots/{}/ap/saisir-m5"


@pytest.fixture
def client_ap_m5(session, nathan, monkeypatch):
    # Réutilise le TestClient et les réglages de la suite HTTP préparatoire.
    yield from _BASE.client_ap_m5.__wrapped__(session, nathan, monkeypatch)


def _hidden_form(html: str) -> tuple[str, dict[str, str]]:
    form = re.search(
        r'<form method="post" action="([^"]+/ap/saisir-m5)" class="pile">(.*?)</form>',
        html,
    )
    assert form, "la confirmation n'est offerte qu'après une observation compatible"
    fields = {
        name: value
        for name, value in re.findall(
            r'<input type="hidden" name="([^\"]+)" value="([^\"]*)">', form.group(2)
        )
    }
    assert set(fields) == {
        "csrf", "revision_pdf", "revision_ap", "po_id", "fournisseur_id",
        "correspondance_confirmee", "snapshot_attendu", "mutation_id",
    }
    fields["saisie_confirmee"] = "oui"
    # HTTPX ajoute déjà le préfixe de base_url à ces chemins relatifs.
    assert form.group(1).startswith(_BASE._PREFIXE + "/fusion/pdf/lots/")
    return form.group(1).removeprefix(_BASE._PREFIXE), fields


def _preparer_confirmation(client: TestClient, *, snapshot_override: str | None = None):
    _BASE._reception_m5()
    lot_id, revision_pdf = _BASE._lot_avec_brouillon(client)
    page = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    observation = _BASE._formulaire(page.text, revision_pdf)
    avant_observation = _BASE._snapshot_tables()
    response = client.post(_BASE._LOT_URL.format(lot_id), data=observation)
    assert response.status_code == 200, response.text
    assert "CONTROLES_M5_COMPATIBLES" in response.text
    assert _BASE._snapshot_tables() == avant_observation
    url, fields = _hidden_form(response.text)
    if snapshot_override is not None:
        fields["snapshot_attendu"] = snapshot_override
    return lot_id, revision_pdf, url, fields, response


def _taille_registre_ap() -> int:
    from m5_financecore import outils as m5_outils

    with stockage.transaction():
        return len(m5_outils._registre_comptes_a_payer().lire())


def test_observation_puis_saisie_confirmee_et_rejeu_creent_une_seule_reference(client_ap_m5):
    lot_id, revision_pdf, url, fields, observation = _preparer_confirmation(client_ap_m5)
    assert "créera une facture SAISIE" in observation.text
    assert "sans paiement" in observation.text
    assert "114.98" in observation.text  # Observation autorisée; les montants ne sont pas envoyés au second POST.
    assert not ({"montant", "total_facture", "date_facture", "numero_facture", "acteur"} & set(fields))
    before = _BASE._snapshot_tables()
    registre_before = _taille_registre_ap()

    first = client_ap_m5.post(url, data=fields)
    assert first.status_code == 200, first.text
    assert "SAISIE_M5_REFERENCEE" in first.text
    assert "Référence de facture" in first.text and "Référence d’approbation" in first.text
    assert "Rejeu idempotent : non" in first.text
    assert "114.98" not in first.text and "source_sha256" not in first.text
    after_first = _BASE._snapshot_tables()
    assert after_first != before
    assert _taille_registre_ap() == registre_before + 1

    replay = client_ap_m5.post(url, data=fields)
    assert replay.status_code == 200, replay.text
    assert "Rejeu idempotent : oui" in replay.text
    assert "Référence de facture" in replay.text
    assert _BASE._snapshot_tables() == after_first
    assert _taille_registre_ap() == registre_before + 1
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200 and "A_REVOIR — révision 1" in page.text


def test_saisie_m5_refuse_csrf_confirmation_hash_query_et_champs_inconnus_sans_effet(client_ap_m5):
    lot_id, _, url, fields, _ = _preparer_confirmation(client_ap_m5)
    before = _BASE._snapshot_tables()

    csrf = dict(fields, csrf="invalide")
    assert client_ap_m5.post(url, data=csrf).status_code == 403
    assert _BASE._snapshot_tables() == before

    unchecked = {key: value for key, value in fields.items() if key != "saisie_confirmee"}
    assert client_ap_m5.post(url, data=unchecked).status_code == 400
    assert _BASE._snapshot_tables() == before

    unattested = dict(fields, correspondance_confirmee="non")
    assert client_ap_m5.post(url, data=unattested).status_code == 400
    assert _BASE._snapshot_tables() == before

    bad_hash = dict(fields, snapshot_attendu="0" * 64)
    response = client_ap_m5.post(url, data=bad_hash)
    assert response.status_code == 409
    assert _BASE._snapshot_tables() == before

    unknown = dict(fields, total_facture="1.00", montant="1.00")
    assert client_ap_m5.post(url, data=unknown).status_code == 400
    assert client_ap_m5.post(url + "?acteur=admin", data=fields).status_code == 400
    assert _BASE._snapshot_tables() == before


def test_saisie_m5_refuse_admin_sans_finance_sans_appeler_le_backend(client_ap_m5, monkeypatch):
    _BASE._reception_m5()
    lot_id, _ = _BASE._lot_avec_brouillon(client_ap_m5)
    csrf = _BASE._connecter(client_ap_m5, _BASE._ADMIN)
    import opsys.console.fusion_ap_m5_saisie as backend

    monkeypatch.setattr(backend, "saisir", lambda *_args, **_kwargs: pytest.fail("backend appelé sans rôle finance"))
    fields = {
        "csrf": csrf, "revision_pdf": "1", "revision_ap": "1", "po_id": "PO-1",
        "fournisseur_id": "gentek", "correspondance_confirmee": "oui", "saisie_confirmee": "oui",
        "snapshot_attendu": "0" * 64, "mutation_id": "a" * 32,
    }
    response = client_ap_m5.post(_URL_SAISIE.format(lot_id), data=fields)
    assert response.status_code == 403 and "ACCES_FINANCE_REFUSE" in response.text


def test_saisie_m5_ne_rend_pas_le_recu_si_role_revoque_apres_commit(client_ap_m5, monkeypatch):
    lot_id, _, url, fields, _ = _preparer_confirmation(client_ap_m5)
    import opsys.console.fusion_ap_m5_saisie as backend

    original = backend.saisir

    def saisir_puis_revoquer(*args, **kwargs):
        result = original(*args, **kwargs)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        return result

    monkeypatch.setattr(backend, "saisir", saisir_puis_revoquer)
    before = _taille_registre_ap()
    response = client_ap_m5.post(url, data=fields)
    assert response.status_code == 403
    assert "SAISIE_M5_REFERENCEE" not in response.text and "Référence de facture" not in response.text
    # Le backend a commit avant la révocation simulée : le test ne prétend pas annuler cet engagement déjà commité.
    assert _taille_registre_ap() == before + 1
    assert client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap").status_code == 403
