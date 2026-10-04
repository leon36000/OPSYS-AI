"""Tests candidats du schema 3; exécutables par ROOT dans l'environnement qualifié seulement."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import update

from opsys import cles_chiffrement, stockage
from opsys.console import obligations_privees as op
from opsys.stockage.schema import REGISTRES

OWNER = "owner.rapprochement.fictif"

FICTIF = True


def _obligation(montant="1250.00", *, ident="a" * 32):
    return {
        "type": "paies", "montant_cad": montant,
        "periode_debut": "2026-09-01", "periode_fin": "2026-09-15",
        "date_paie": "2026-09-18", "echeance": "2026-09-21",
        "reference_piece": "piece-fictive", "autorite": "déclarée fictive",
        "source_consultee_le": "2026-09-17", "applicable_du": "2026-01-01",
        "applicable_au": "2026-12-31", "version": "fictive-2026",
    }


def _snapshot(*, provisions=None, legacy=None, finance_id="base-fictif"):
    catalogues = {"legacy": legacy or {}, "provisions": provisions or {}}
    def builder(obligations_sha256):
        import hashlib
        donnees = json.dumps({"base": finance_id, "obligations": obligations_sha256, "sources": catalogues},
                             sort_keys=True, separators=(",", ":"))
        return {"finance_snapshot_id": hashlib.sha256(donnees.encode()).hexdigest(),
                "obligations_sha256": obligations_sha256, "sources": catalogues}
    return builder


def _ajouter(cnx, *, ident="a" * 32, montant="1250.00", actor_check=lambda *_: None):
    return op.ajouter(
        cnx, _obligation(montant), revision_attendue=0, mutation_id=ident,
        confirme_par=OWNER, confirme_le="2026-10-03T12:00:00+00:00", verifier_acteur=actor_check,
    )


def _rapprocher(cnx, snap, *, ident="b" * 32, obligation_id="a" * 32, mode="LEGACY_IDENTIQUE",
                source_kind="legacy", source_ref="paies", source_hash="1" * 64, amount="1250.00",
                revision=1, actor_check=lambda *_: None):
    payload = {
        "obligation_id": obligation_id, "mode": mode, "source_kind": source_kind,
        "source_ref": source_ref, "source_sha256": source_hash, "montant_cad": amount,
    }
    etat = op.lire(cnx)
    snapshot_id = snap(op._empreinte_obligations(etat))["finance_snapshot_id"]
    return op.rapprocher(
        cnx, payload, snapshot=snap, revision_attendue=revision, snapshot_id_attendu=snapshot_id, mutation_id=ident,
        confirme_par=OWNER, confirme_le="2026-10-03T12:01:00+00:00", verifier_acteur=actor_check,
    )


def test_schema3_legacy_exact_chiffre_cas_et_projection_connue(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        resultat = _rapprocher(cnx, snap)
        assert resultat == {"id": "b" * 32, "revision": 2, "statut": "CONFIRMEE"}
    with session() as cnx:
        projection = op.lire_rapprochements(cnx, snap)
    assert projection["statut"] == "CONNU"
    assert projection["montant_utilisable"] is not None
    assert projection["rapprochements"] == [{
        "obligation_id": "a" * 32, "mode": "LEGACY_IDENTIQUE", "montant_cad": "1250.00",
        "source_kind": "legacy", "source_ref": "paies",
    }]
    assert projection["credits_provisions"] == {}
    assert "1250.00" not in json.dumps(list(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)))
    assert projection["obligations_sha256"] and projection["paie_das_head"]
    assert projection["revision"] == 2
    assert projection["obligations_actives"][0]["id"] == "a" * 32


def test_snapshot_financier_change_ou_obligation_remplacee_invalide(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap)
    changed = _snapshot(legacy={"paies": {"sha256": "2" * 64, "montant_cad": "1250.00"}}, finance_id="changed-fictif")
    with session() as cnx:
        projection = op.lire_rapprochements(cnx, changed)
    assert projection["statut"] == "INCONNU" and projection["montant_utilisable"] is None
    assert any("modifiés" in reason or "modifiée" in reason for reason in projection["raisons"])


def test_credits_provision_bornes_et_source_exclusive(session):
    prov_id = "9" * 64
    snap = _snapshot(provisions={prov_id: {"sha256": "8" * 64, "montant_cad": "700.00"}})
    with session() as cnx:
        _ajouter(cnx, ident="a" * 32, montant="1250.00")
        op.ajouter(cnx, _obligation("500.00"), revision_attendue=1, mutation_id="c" * 32,
                   confirme_par=OWNER, confirme_le="2026-10-03T12:00:30+00:00", verifier_acteur=lambda *_: None)
        _rapprocher(cnx, snap, mode="PROVISION_CREDIT", source_kind="provision", source_ref=prov_id,
                    source_hash="8" * 64, amount="400.00", revision=2)
        with pytest.raises(op.RefusObligation, match="source déjà affectée"):
            _rapprocher(cnx, snap, ident="d" * 32, obligation_id="c" * 32, mode="PROVISION_CREDIT",
                        source_kind="provision", source_ref=prov_id, source_hash="8" * 64,
                        amount="300.00", revision=3)
    with session() as cnx:
        projection = op.lire_rapprochements(cnx, snap)
    assert projection["statut"] == "INCONNU"  # le même crédit ne peut être affecté à deux obligations.
    assert projection["montant_utilisable"] is None


def test_montant_provision_superieur_obligation_refuse_avant_append(session):
    prov_id = "9" * 64
    snap = _snapshot(provisions={prov_id: {"sha256": "8" * 64, "montant_cad": "2000.00"}})
    with session() as cnx:
        _ajouter(cnx, montant="1250.00")
        with pytest.raises(op.RefusObligation, match="supérieur"):
            _rapprocher(cnx, snap, mode="PROVISION_CREDIT", source_kind="provision", source_ref=prov_id,
                        source_hash="8" * 64, amount="1300.00")
        assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1


def test_rejeu_idempotent_et_contenu_ou_acteur_different_refuse(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap)
    with session() as cnx:
        rejoue = _rapprocher(cnx, snap)
        assert rejoue["statut"] == "REJOUEE" and rejoue["revision"] == 2
        with pytest.raises(op.RefusObligation):
            _rapprocher(cnx, snap, source_hash="2" * 64)
        with pytest.raises(PermissionError):
            _rapprocher(cnx, snap, actor_check=lambda _cnx, acteur: (_ for _ in ()).throw(PermissionError(acteur)))
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 2


def test_role_revoque_a_la_seconde_validation_nappend_pas(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    appels = 0
    def revoke(_cnx, _actor):
        nonlocal appels
        appels += 1
        if appels == 2:
            raise PermissionError("rôle retiré")
    with session() as cnx:
        _ajouter(cnx)
        with pytest.raises(PermissionError):
            _rapprocher(cnx, snap, actor_check=revoke)
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1


def test_remplacement_terminal_invalide_ancien_rapprochement(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap)
        op.transition(cnx, "REMPLACER", "a" * 32, _obligation("1300.00"), revision_attendue=2,
                      mutation_id="c" * 32, confirme_par=OWNER, confirme_le="2026-10-03T12:02:00+00:00",
                      verifier_acteur=lambda *_: None)
    with session() as cnx:
        projection = op.lire_rapprochements(cnx, snap)
    assert projection["statut"] == "INCONNU" and projection["montant_utilisable"] is None
    assert all(x["obligation_id"] != "a" * 32 for x in projection["rapprochements"])
    actualise = _snapshot(legacy={"paies": {"sha256": "2" * 64, "montant_cad": "1300.00"}})
    with session() as cnx:
        _rapprocher(cnx, actualise, ident="d" * 32, obligation_id="c" * 32,
                    source_hash="2" * 64, amount="1300.00", revision=3)
        nouvelle = op.lire_rapprochements(cnx, actualise)
    assert nouvelle["statut"] == "CONNU"
    assert len(nouvelle["rapprochements"]) == 1
    assert nouvelle["rapprochements"][0]["obligation_id"] == "c" * 32


def test_conflit_cas_financier_refuse_et_ciphertext_sans_clair(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        with pytest.raises(op.RefusObligation):
            _rapprocher(cnx, snap, revision=0)
    env = stockage.maillons(op.DEPARTEMENT, op.REGISTRE)[0]
    assert "1250.00" not in json.dumps(env)


def test_nouvelle_composante_et_provision_hors_paie_classifiees(session):
    prov_id = "9" * 64
    snap = _snapshot(provisions={prov_id: {"sha256": "8" * 64, "montant_cad": "2000.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap, mode="NOUVELLE_COMPOSANTE", source_kind="none", source_ref="",
                    source_hash="0" * 64)
        _rapprocher(cnx, snap, ident="c" * 32, obligation_id=None, mode="PROVISION_HORS_PAIE",
                    source_kind="provision", source_ref=prov_id, source_hash="8" * 64, amount="2000.00",
                    revision=2)
    with session() as cnx:
        projection = op.lire_rapprochements(cnx, snap)
    assert projection["statut"] == "CONNU"
    assert projection["montant_utilisable"] is not None
    assert projection["credits_provisions"] == {}


def test_legacy_montant_inexact_refuse_et_source_absente_inconnue(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.01"}})
    with session() as cnx:
        _ajouter(cnx)
        with pytest.raises(op.RefusObligation, match="non identique"):
            _rapprocher(cnx, snap)
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1


def test_credit_provision_et_legacy_exact_peuvent_coexister_sans_double_compter(session):
    prov_id = "9" * 64
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}},
                     provisions={prov_id: {"sha256": "8" * 64, "montant_cad": "500.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap)
        _rapprocher(cnx, snap, ident="c" * 32, mode="PROVISION_CREDIT", source_kind="provision",
                    source_ref=prov_id, source_hash="8" * 64, amount="500.00", revision=2)
    with session() as cnx:
        projection = op.lire_rapprochements(cnx, snap)
    assert projection["statut"] == "CONNU"
    assert projection["credits_provisions"] == {prov_id: "500.00"}
    assert len(projection["rapprochements"]) == 2


def test_schema3_ciphertext_altere_refuse_projection(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap)
    env = stockage.maillons(op.DEPARTEMENT, op.REGISTRE)[1]
    cipher = bytes.fromhex(env["ciphertext"])
    env["ciphertext"] = bytes([cipher[0] ^ 1, *cipher[1:]]).hex()
    import hashlib
    env["cipher_sha256"] = hashlib.sha256(bytes.fromhex(env["ciphertext"])).hexdigest()
    with session() as cnx:
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == op.DEPARTEMENT) & (REGISTRES.c.registre == op.REGISTRE)
            & (REGISTRES.c.rang == 1)
        ).values(maillon=json.dumps(env, separators=(",", ":"))))
    with session() as cnx, pytest.raises(op.RefusObligation, match="donnée chiffrée invalide"):
        op.lire_rapprochements(cnx, snap)


def test_schema3_cle_absente_refuse_projection(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        _rapprocher(cnx, snap)
    with session() as cnx:
        assert cles_chiffrement.detruire(cnx, op.PORTEE_CLE, "b" * 32)
    with session() as cnx, pytest.raises(op.RefusObligation, match="clé absente"):
        op.lire_rapprochements(cnx, snap)


def test_snapshot_id_formulaire_stale_refuse_append(session):
    snap = _snapshot(legacy={"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}})
    with session() as cnx:
        _ajouter(cnx)
        with pytest.raises(op.RefusObligation, match="périmé"):
            payload = {"obligation_id": "a" * 32, "mode": "LEGACY_IDENTIQUE", "source_kind": "legacy",
                       "source_ref": "paies", "source_sha256": "1" * 64, "montant_cad": "1250.00"}
            op.rapprocher(cnx, payload, snapshot=snap, revision_attendue=1, snapshot_id_attendu="0" * 64,
                          mutation_id="b" * 32, confirme_par=OWNER,
                          confirme_le="2026-10-03T12:01:00+00:00", verifier_acteur=lambda *_: None)
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1


def test_transition_reclassement_nouvel_id_redevient_connu_sans_ancien_credit(session):
    prov_id = "9" * 64
    premier_snapshot = _snapshot(
        provisions={prov_id: {"sha256": "8" * 64, "montant_cad": "100.00"}},
        finance_id="finance-avant",
    )
    with session() as cnx:
        _ajouter(cnx, montant="1250.00")
        _rapprocher(cnx, premier_snapshot, mode="NOUVELLE_COMPOSANTE", source_kind="none",
                    source_ref="", source_hash="0" * 64, revision=1)
        _rapprocher(cnx, premier_snapshot, ident="c" * 32, mode="PROVISION_CREDIT", source_kind="provision",
                    source_ref=prov_id, source_hash="8" * 64, amount="100.00", revision=2)
        op.transition(cnx, "REMPLACER", "a" * 32, _obligation("1300.00"), revision_attendue=3,
                      mutation_id="d" * 32, confirme_par=OWNER, confirme_le="2026-10-03T12:02:00+00:00",
                      verifier_acteur=lambda *_: None)
    with session() as cnx:
        apres_transition = op.lire_rapprochements(cnx, premier_snapshot)
    assert apres_transition["statut"] == "INCONNU"
    assert apres_transition["montant_utilisable"] is None
    nouveau_id = "d" * 32
    nouveau_snapshot = _snapshot(
        provisions={prov_id: {"sha256": "8" * 64, "montant_cad": "100.00"}},
        finance_id="finance-apres",
    )
    with session() as cnx:
        _rapprocher(cnx, nouveau_snapshot, ident="e" * 32, obligation_id=nouveau_id,
                    mode="NOUVELLE_COMPOSANTE", source_kind="none", source_ref="", source_hash="0" * 64,
                    amount="1300.00", revision=4)
        _rapprocher(cnx, nouveau_snapshot, ident="f" * 32, obligation_id=None,
                    mode="PROVISION_HORS_PAIE", source_kind="provision", source_ref=prov_id,
                    source_hash="8" * 64, amount="100.00", revision=5)
    with session() as cnx:
        current = op.lire_rapprochements(cnx, nouveau_snapshot)
    assert current["statut"] == "CONNU"
    assert current["credits_provisions"] == {}
    assert [line["obligation_id"] for line in current["rapprochements"]] == [nouveau_id]
    assert "1250.00" not in json.dumps(current)
