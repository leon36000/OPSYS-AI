from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from opsys.console import finance_snapshot_prive as candidate


def test_snapshot_builder_binds_all_financial_sources_and_active_obligations():
    build = candidate._snapshot_builder(
        "1" * 64,
        {"principal": {"taille": 1, "tete": "a"}, "factures": {"taille": 0, "tete": None},
         "comptes_a_payer": {"taille": 0, "tete": None}},
        {"legacy": {}, "provisions": {}},
        {"calendrier": "2" * 64, "taux": "3" * 64},
    )
    first = build("4" * 64)
    same_active_state = build("4" * 64)
    changed_active_state = build("5" * 64)
    assert first == same_active_state
    assert first["finance_snapshot_id"] != changed_active_state["finance_snapshot_id"]
    assert first["obligations_sha256"] == "4" * 64
    assert "revision" not in first and "paie_das_head" not in first


def test_source_catalogue_hashes_complete_provision_maillon_and_keeps_exact_line_id():
    line = {
        "ligne_id": "a" * 64,
        "type_entree": "mouvement_enregistre",
        "type_mouvement": "PROVISION",
        "montant": Decimal("125.50"),
        "horodatage": "2026-10-03T12:00:00+00:00",
    }
    result = candidate._sources({"declarees": {}, "maillons_mouvements": [line]})
    assert result["provisions"][line["ligne_id"]] == {
        "sha256": candidate.encodage.empreinte(line),
        "montant_cad": "125.50",
    }


def test_private_projection_subtracts_only_explicit_credit_and_does_not_mutate_base():
    base = {"declarees": {}, "provisions": (Decimal("150.00"), 2, "2026-10-01T10:00:00+00:00")}
    projected = {
        "montant_utilisable": {
            "obligations": [{"id": "id1", "obligation": {"type": "paies", "montant_cad": "30.00",
                "source_consultee_le": "2026-10-01"}}],
            "rapprochements": [{"obligation_id": "id1", "mode": "NOUVELLE_COMPOSANTE"}],
            "credits_provisions": {"a" * 64: "25.00"},
        }
    }
    result = candidate._private_declarations(base, projected)
    assert result["declarees"]["paies"] == {
        "montant": "30.00", "source": "rapprochement privé confirmé", "au": "2026-10-01"
    }
    assert result["provisions"] == (Decimal("125.00"), 2, base["provisions"][2])
    assert base == {"declarees": {}, "provisions": (Decimal("150.00"), 2, "2026-10-01T10:00:00+00:00")}


def test_projection_refuses_legacy_double_count_or_negative_reserves():
    private = {"type": "paies", "montant_cad": "20.00", "source_consultee_le": "2026-10-01"}
    with pytest.raises(ValueError):
        candidate._private_declarations(
            {"declarees": {"paies": {"montant": "20.00", "source": "legacy", "au": "2026-10-01"}},
             "provisions": (Decimal("10.00"), 1, "2026-10-01")},
            {"montant_utilisable": {"obligations": [{"id": "id", "obligation": private}],
             "rapprochements": [{"obligation_id": "id", "mode": "NOUVELLE_COMPOSANTE"}],
             "credits_provisions": {}}},
        )
    with pytest.raises(ValueError):
        candidate._private_declarations(
            {"declarees": {}, "provisions": (Decimal("10.00"), 1, "2026-10-01")},
            {"montant_utilisable": {"obligations": [], "rapprochements": [],
             "credits_provisions": {"a" * 64: "10.01"}}},
        )


def test_capture_uses_snapshot_builder_and_calls_existing_cash_owner_once(monkeypatch: pytest.MonkeyPatch,
                                                                           tmp_path: Path):
    config = tmp_path / "department.yaml"
    config.write_text("configuration: {}\n", encoding="utf-8")
    fiscal = tmp_path / "fiscal.yaml"
    fiscal.write_text("version: test\n", encoding="utf-8")
    calls = {"cash": 0, "snapshot": []}
    monkeypatch.setattr(candidate.outils, "_MANIFESTE", config)
    monkeypatch.setattr(candidate.outils, "_CHEMIN_CALENDRIER_FISCAL", fiscal)
    monkeypatch.setattr(candidate.outils, "_CHEMIN_TAUX_FISCAUX", fiscal)
    monkeypatch.setattr(candidate.outils, "_stockage_durable_actif", True)
    monkeypatch.setattr(candidate.stockage, "connexion_courante", lambda: cnx)
    monkeypatch.setattr(candidate, "_guard_registers", lambda _cnx: None)
    empty = {"maillons_mouvements": [], "maillons_factures": [], "maillons_a_payer": [],
             "declarees": {}, "provisions": (Decimal("0.00"), 0, None)}
    monkeypatch.setattr(candidate.outils, "_lectures_finance", lambda *a, **k: empty)
    monkeypatch.setattr(candidate, "_current_refs", lambda _cnx: {
        "principal": {"taille": 0, "tete": None},
        "factures": {"taille": 0, "tete": None},
        "comptes_a_payer": {"taille": 0, "tete": None},
    })

    def cash(lectures):
        calls["cash"] += 1
        assert lectures is not empty
        return {"cash_libre": "100.00"}

    monkeypatch.setattr(candidate.outils, "_resultat_cash_libre", cash)

    class Journal:
        def lire_rapprochements(self, _cnx, builder):
            snapshot = builder("4" * 64)
            calls["snapshot"].append(snapshot)
            return {"statut": "CONNU", "revision": 2, "paie_das_head": "5" * 64,
                    "obligations_sha256": "4" * 64,
                    "montant_utilisable": {"obligations": [], "rapprochements": [], "credits_provisions": {}}}

    cnx = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    result = candidate.calculer_vue_privee(cnx, Journal())
    assert result["statut"] == "CONNU"
    assert result["cash_libre"] == {"cash_libre": "100.00"}
    assert calls["cash"] == 1
    assert calls["snapshot"][0]["obligations_sha256"] == "4" * 64
    assert result["finance_snapshot_id"] == calls["snapshot"][0]["finance_snapshot_id"]


def test_capture_exposes_exact_source_catalogue_when_projection_is_incomplete(monkeypatch: pytest.MonkeyPatch,
                                                                               tmp_path: Path):
    config = tmp_path / "department.yaml"
    config.write_text("configuration: {}\n", encoding="utf-8")
    fiscal = tmp_path / "fiscal.yaml"
    fiscal.write_text("version: test\n", encoding="utf-8")
    provision = {
        "ligne_id": "b" * 64,
        "type_entree": "mouvement_enregistre",
        "type_mouvement": "PROVISION",
        "montant": Decimal("48.00"),
        "horodatage": "2026-10-02T10:00:00+00:00",
    }
    lectures = {"maillons_mouvements": [provision], "maillons_factures": [], "maillons_a_payer": [],
                "declarees": {}, "provisions": (Decimal("48.00"), 1, provision["horodatage"])}
    monkeypatch.setattr(candidate.outils, "_MANIFESTE", config)
    monkeypatch.setattr(candidate.outils, "_CHEMIN_CALENDRIER_FISCAL", fiscal)
    monkeypatch.setattr(candidate.outils, "_CHEMIN_TAUX_FISCAUX", fiscal)
    monkeypatch.setattr(candidate.outils, "_stockage_durable_actif", True)
    monkeypatch.setattr(candidate.stockage, "connexion_courante", lambda: cnx)
    monkeypatch.setattr(candidate, "_guard_registers", lambda _cnx: None)
    monkeypatch.setattr(candidate.outils, "_lectures_finance", lambda *a, **k: lectures)
    cnx = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    capture = candidate.capturer_snapshot_prive(cnx)
    result = candidate.presenter_capture_privee(capture, {
        "statut": "INCONNU", "obligations_sha256": "6" * 64,
        "revision": 3, "paie_das_head": "7" * 64,
        "obligations_actives": [], "rapprochements": [], "credits_provisions": {},
        "raisons": ["provision non classée"],
    })
    assert result["statut"] == "INCONNU"
    assert result["finance_snapshot_id"] is not None
    assert result["snapshot"]["obligations_sha256"] == "6" * 64
    assert result["sources"]["provisions"][provision["ligne_id"]]["montant_cad"] == "48.00"
    assert result["sources"]["provisions"][provision["ligne_id"]]["sha256"] == candidate.encodage.empreinte(
        provision
    )
    assert result["paie_das_revision"] == 3
    assert result["montant_utilisable"] is None


def test_final_source_guard_detects_file_and_register_changes_without_journal_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    config = tmp_path / "department.yaml"
    config.write_text("configuration: {}\n", encoding="utf-8")
    fiscal = tmp_path / "fiscal.yaml"
    fiscal.write_text("version: original\n", encoding="utf-8")
    lectures = {"maillons_mouvements": [], "maillons_factures": [], "maillons_a_payer": [],
                "declarees": {}, "provisions": (Decimal("0.00"), 0, None)}
    cnx = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    current_refs = {name: {"taille": 0, "tete": None}
                    for name in ("principal", "factures", "comptes_a_payer")}
    monkeypatch.setattr(candidate.outils, "_MANIFESTE", config)
    monkeypatch.setattr(candidate.outils, "_CHEMIN_CALENDRIER_FISCAL", fiscal)
    monkeypatch.setattr(candidate.outils, "_CHEMIN_TAUX_FISCAUX", fiscal)
    monkeypatch.setattr(candidate.outils, "_stockage_durable_actif", True)
    monkeypatch.setattr(candidate.stockage, "connexion_courante", lambda: cnx)
    monkeypatch.setattr(candidate, "_guard_registers", lambda _cnx: None)
    monkeypatch.setattr(candidate, "_current_refs", lambda _cnx: current_refs)
    monkeypatch.setattr(candidate.outils, "_lectures_finance", lambda *a, **k: lectures)
    capture = candidate.capturer_snapshot_prive(cnx)
    assert capture.verifier_sources_courantes() is True

    config.write_text("configuration: {changed: true}\n", encoding="utf-8")
    assert capture.verifier_sources_courantes() is False
    config.write_text("configuration: {}\n", encoding="utf-8")
    fiscal.write_text("version: changed\n", encoding="utf-8")
    assert capture.verifier_sources_courantes() is False
    fiscal.write_text("version: original\n", encoding="utf-8")
    current_refs["principal"] = {"taille": 1, "tete": "c" * 64}
    assert capture.verifier_sources_courantes() is False
