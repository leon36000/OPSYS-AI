"""E4 / D1 : opérateur Core des politiques de service M4 → M5, par la console admin.

Octroi, renouvellement et révocation des trois politiques (`m4.verifier_v3`, `m4.recalculer_v3`,
`m4.relire_faits_pour_m5_v1`) : admin actif relu en base, CSRF, champs fermés, journal append-only, expiration à
90 jours, révocation immédiate, jamais par un agent, SQLite seulement. Base éphémère, personnes fictives.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DatabaseError

from opsys import contexte, identite, service_politiques, stockage
from opsys import service_capability as sc
from opsys.console.securite import Session
from opsys.stockage.schema import SERVICE_AUDIT, SERVICE_POLITIQUES, SERVICE_POLITIQUES_JOURNAL

_spec = importlib.util.spec_from_file_location("politiques_console_fixtures",
                                               Path(__file__).with_name("test_console_finance.py"))
f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f)
client_finance = f.client_finance

URL = "/api/administration/politiques-service"
ADMIN = "admin.fictif"


def _admin_client(client):
    return f._connecter(client, ADMIN)


def _post(client, corps, *, csrf=True):
    entetes = {"x-csrf-token": f._csrf(client)} if csrf else {}
    return client.post(URL, json=corps, headers=entetes)


def _lignes(operation):
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(SERVICE_POLITIQUES).where(
            SERVICE_POLITIQUES.c.operation == operation).order_by(SERVICE_POLITIQUES.c.revision)).mappings()]


def _journal():
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(SERVICE_POLITIQUES_JOURNAL).order_by(
            SERVICE_POLITIQUES_JOURNAL.c.id)).mappings()]


def test_les_trois_politiques_octroi_renouvellement_revocation_avec_journal(client_finance):
    client = _admin_client(client_finance)
    etat = client.get(URL)
    assert etat.status_code == 200 and etat.headers["cache-control"] == "no-store"
    assert [p["statut"] for p in etat.json()["politiques"]] == ["absente"] * 3
    assert etat.json()["duree_jours"] == 90
    for operation in service_politiques.OPERATIONS:
        avant = int(time.time())
        r = _post(client, {"action": "octroyer", "operation": operation, "motif": "Mise en service fictive"})
        assert r.status_code == 200, r.text
        (ligne,) = _lignes(operation)
        assert ligne["active"] is True and ligne["revision"] == 1
        # Expiration EXACTE à 90 jours (jamais sans échéance, jamais plus longue).
        assert avant + 90 * 86400 <= ligne["expire_le"] <= int(time.time()) + 90 * 86400
    # un second octroi d'une politique active est refusé (renouveler explicitement), sans écriture
    assert _post(client, {"action": "octroyer", "operation": "m4.recalculer_v3", "motif": "doublon"}).status_code == 409
    assert len(_lignes("m4.recalculer_v3")) == 1
    r = _post(client, {"action": "renouveler", "operation": "m4.recalculer_v3", "motif": "Renouvellement fictif"})
    assert r.status_code == 200 and r.json()["resultat"]["revision"] == 2
    r = _post(client, {"action": "revoquer", "operation": "m4.recalculer_v3", "motif": "Révocation fictive"})
    assert r.status_code == 200 and r.json()["resultat"]["statut"] == "revoquee"
    lignes = _lignes("m4.recalculer_v3")
    assert [(li["revision"], li["active"]) for li in lignes] == [(1, True), (2, True), (3, False)]
    assert lignes[2]["expire_le"] == lignes[1]["expire_le"]
    # révoquée : ni renouvelable, ni re-révocable ; un nouvel octroi est possible
    assert _post(client, {"action": "renouveler", "operation": "m4.recalculer_v3", "motif": "x" * 4}).status_code == 409
    assert _post(client, {"action": "revoquer", "operation": "m4.recalculer_v3", "motif": "x" * 4}).status_code == 409
    journal = _journal()
    assert [(j["operation"], j["action"], j["acteur"]) for j in journal] == [
        *((op, "octroi", ADMIN) for op in service_politiques.OPERATIONS),
        ("m4.recalculer_v3", "renouvellement", ADMIN), ("m4.recalculer_v3", "revocation", ADMIN)]
    with stockage.transaction() as cnx:
        audits = cnx.execute(select(SERVICE_AUDIT.c.operation, SERVICE_AUDIT.c.action, SERVICE_AUDIT.c.revision)
                             ).all()
    assert [tuple(a) for a in audits] == [("m4.recalculer_v3", "revocation", 3)]
    vue = client.get(URL).json()
    assert {p["operation"]: p["statut"] for p in vue["politiques"]} == {
        "m4.verifier_v3": "active", "m4.recalculer_v3": "revoquee", "m4.relire_faits_pour_m5_v1": "active"}
    assert vue["journal"][0]["action"] == "revocation"


def test_journal_et_politiques_immuables(client_finance):
    client = _admin_client(client_finance)
    _post(client, {"action": "octroyer", "operation": "m4.verifier_v3", "motif": "Mise en service fictive"})
    with pytest.raises(DatabaseError, match="immuable"), stockage.transaction() as cnx:
        cnx.execute(update(SERVICE_POLITIQUES_JOURNAL).values(motif="réécrit"))
    with pytest.raises(DatabaseError, match="immutable"), stockage.transaction() as cnx:
        cnx.execute(update(SERVICE_POLITIQUES).values(expire_le=2**40))


def test_refus_csrf_champs_non_admin_et_proprietaire_sans_admin(client_finance):
    client = _admin_client(client_finance)
    corps = {"action": "octroyer", "operation": "m4.verifier_v3", "motif": "Mise en service fictive"}
    assert _post(client, corps, csrf=False).status_code == 403
    assert _post(client, {**corps, "expire_le": 2**40}).status_code == 400  # aucune durée fournie par l'appelant
    assert _post(client, {**corps, "operation": "m4.autre"}).status_code == 400
    assert _post(client, {**corps, "action": "supprimer"}).status_code == 400
    assert _post(client, {**corps, "motif": "  "}).status_code == 400
    assert _lignes("m4.verifier_v3") == [] and _journal() == []
    # le propriétaire sans rôle admin ne passe pas l'opérateur (rôle admin relu en base)
    f._connecter(client, f.NOM)
    assert _post(client, corps).status_code == 403
    _admin_client(client)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN, "admin")
    assert client.get(URL).status_code == 403
    assert _post(client, corps).status_code in (401, 403)
    assert _lignes("m4.verifier_v3") == [] and _journal() == []


def test_formulaire_console_octroie_puis_revoque(client_finance):
    import re

    client = _admin_client(client_finance)
    page = client.get("/administration/politiques-service")
    assert page.status_code == 200 and "Octroyer 90 jours" in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    sans_csrf = client.post("/administration/politiques-service", data={
        "operation": "m4.recalculer_v3", "action": "octroyer", "motif": "fictif"}, follow_redirects=False)
    assert sans_csrf.status_code == 403
    r = client.post("/administration/politiques-service", data={
        "csrf": csrf, "operation": "m4.recalculer_v3", "action": "octroyer", "motif": "<motif fictif>"},
        follow_redirects=False)
    assert r.status_code == 303, r.text
    page = client.get("/administration/politiques-service")
    assert "Révoquer maintenant" in page.text and "&lt;motif fictif&gt;" in page.text
    assert "<motif fictif>" not in page.text
    r = client.post("/administration/politiques-service", data={
        "csrf": csrf, "operation": "m4.recalculer_v3", "action": "revoquer", "motif": "fin fictive"},
        follow_redirects=False)
    assert r.status_code == 303
    assert [li["active"] for li in _lignes("m4.recalculer_v3")] == [True, False]


def _session_admin():
    return Session(ADMIN, frozenset({"admin"}), "csrf-fictif", int(time.time()) + 3600)


def test_jamais_par_un_agent_ni_hors_console(client_finance):
    """Aucun outil MCP n'expose l'opérateur ; même un appel direct sous une identité d'agent/appareil est refusé."""
    with stockage.transaction() as cnx, contexte.appeler_en_tant_que("m05-financecore"), pytest.raises(
            service_politiques.RefusOperateur) as exc:
        service_politiques.octroyer(cnx, _session_admin(), "m4.recalculer_v3", motif="agent fictif")
    assert exc.value.code == "APPEL_AGENT_INTERDIT"
    with stockage.transaction() as cnx, contexte.appele_par_appareil(
            contexte.IdentiteAppelante(ADMIN, "admin", source="appareil")), pytest.raises(
            service_politiques.RefusOperateur) as exc:
        service_politiques.octroyer(cnx, _session_admin(), "m4.recalculer_v3", motif="appareil fictif")
    assert exc.value.code == "APPEL_AGENT_INTERDIT"
    with stockage.transaction() as cnx, pytest.raises(service_politiques.RefusOperateur) as exc:
        service_politiques.octroyer(cnx, object(), "m4.recalculer_v3", motif="objet fictif")
    assert exc.value.code == "SESSION_INVALIDE"
    assert _lignes("m4.recalculer_v3") == []
    # aucun outil de département ne nomme l'opérateur
    racine = Path(__file__).resolve().parent.parent
    for chemin in (racine / "departments").glob("*/src/**/*.py"):
        assert "service_politiques" not in chemin.read_text(encoding="utf-8", errors="ignore"), chemin


def test_revocation_immediate_et_expiration_ferment_la_capacite(client_finance, monkeypatch):
    """La dernière révision fait foi à chaque garde : la révocation et l'échéance des 90 jours ferment l'accès sans
    délai (le moteur de recalcul relit les deux politiques et nomme celle qui manque)."""
    from opsys import moteur_recalcul_m4 as moteur

    with stockage.transaction() as cnx:
        for operation in ("m4.verifier_v3", "m4.recalculer_v3"):
            service_politiques.octroyer(cnx, _session_admin(), operation, motif="Mise en service fictive")
        instance = cnx.execute(select(SERVICE_POLITIQUES.c.instance_id)).scalars().first()
        assert moteur._politiques(cnx, instance)  # deux politiques effectives
        service_politiques.revoquer(cnx, _session_admin(), "m4.recalculer_v3", motif="Révocation fictive")
        with pytest.raises(moteur.RefusRecalculM4) as exc:
            moteur._politiques(cnx, instance)
        assert exc.value.code == "POLITIQUE_REVOQUEE"
        service_politiques.octroyer(cnx, _session_admin(), "m4.recalculer_v3", motif="Nouvel octroi fictif")
        assert moteur._politiques(cnx, instance)
    # 90 jours plus une seconde : expirée partout (moteur et livraison V1 relisent `expire_le`)
    futur = time.time() + 90 * 86400 + 1
    monkeypatch.setattr(moteur, "time", lambda: futur)
    monkeypatch.setattr(service_politiques, "time", lambda: futur)
    with stockage.transaction() as cnx:
        with pytest.raises(moteur.RefusRecalculM4) as exc:
            moteur._politiques(cnx, instance)
        assert exc.value.code == "POLITIQUE_EXPIREE"
        assert {p["operation"]: p["statut"] for p in service_politiques.etat(cnx, _session_admin())["politiques"]}[
            "m4.recalculer_v3"] == "expiree"
        # renouvelable après échéance ; la nouvelle échéance part de MAINTENANT (aucun cumul)
        r = service_politiques.renouveler(cnx, _session_admin(), "m4.recalculer_v3", motif="Renouvellement fictif")
        assert r["expire_le"] == int(futur) + 90 * 86400
        with pytest.raises(moteur.RefusRecalculM4) as exc:  # la seconde politique reste expirée
            moteur._politiques(cnx, instance)
        assert exc.value.code == "POLITIQUE_EXPIREE" and "m4.verifier_v3" in str(exc.value)
        service_politiques.renouveler(cnx, _session_admin(), "m4.verifier_v3", motif="Renouvellement fictif")
        assert moteur._politiques(cnx, instance)


def test_primitive_interne_couvre_les_trois_operations(client_finance):
    with stockage.transaction() as cnx:
        for operation in service_politiques.OPERATIONS:
            service_politiques.octroyer(cnx, _session_admin(), operation, motif="Mise en service fictive")
        instance = cnx.execute(select(SERVICE_POLITIQUES.c.instance_id)).scalars().first()
        for operation in service_politiques.OPERATIONS:
            sc._revoquer(cnx, instance, "m05-financecore", operation)
            assert service_politiques.statut(service_politiques.derniere(cnx, instance, operation)) == "revoquee"
        with pytest.raises(sc.RefusAutorite):
            sc._revoquer(cnx, instance, "m05-financecore", "m4.autre")


def test_un_moteur_non_qualifie_refuse(monkeypatch):
    class Dialecte:
        name = "mysql"

    class Moteur:
        dialect = Dialecte()

    class Cnx:
        engine = Moteur()

    with pytest.raises(service_politiques.RefusOperateur) as exc:
        service_politiques.octroyer(Cnx(), _session_admin(), "m4.verifier_v3", motif="moteur fictif")
    assert exc.value.code == "BACKEND_NON_QUALIFIE"


def test_migration_0036_monte_sans_octroi_et_descend_seulement_vide(tmp_path):
    """0036 n'octroie rien ; la rétrogradation est sûre (vide) et refusée dès qu'un geste est journalisé."""
    from alembic import command
    from sqlalchemy import insert

    from opsys.stockage.schema import COUT_CERTIFIE_RECONCILIATIONS, OPSYS_INSTANCE

    engine = stockage.moteur("sqlite:///" + str(tmp_path / "migration-0036.db"))
    cfg = stockage._config()
    with engine.begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0035")
        instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        cnx.execute(insert(SERVICE_POLITIQUES).values(
            instance_id=instance, consommateur="m05-financecore", operation="m4.verifier_v3", revision=1,
            active=True, expire_le=int(time.time()) + 3600))
        avant = cnx.execute(select(SERVICE_POLITIQUES)).all()
        command.upgrade(cfg, "0036")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0036"
        assert cnx.execute(select(SERVICE_POLITIQUES)).all() == avant
        assert not cnx.execute(select(SERVICE_POLITIQUES_JOURNAL)).all()
        assert not cnx.execute(select(COUT_CERTIFIE_RECONCILIATIONS)).all()
        command.downgrade(cfg, "0035")  # vide : sûre
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0035"
        assert cnx.execute(select(SERVICE_POLITIQUES)).all() == avant
        command.upgrade(cfg, "0036")
        # une ligne de journal sans révision de politique correspondante est refusée (clé étrangère)
        with pytest.raises(DatabaseError), cnx.begin_nested():
            cnx.execute(insert(SERVICE_POLITIQUES_JOURNAL).values(
                instance_id=instance, consommateur="m05-financecore", operation="m4.verifier_v3", revision=9,
                action="octroi", acteur="admin.fictif", motif="fictif", epoch=1, expire_le=2))
        cnx.execute(insert(SERVICE_POLITIQUES_JOURNAL).values(
            instance_id=instance, consommateur="m05-financecore", operation="m4.verifier_v3", revision=1,
            action="octroi", acteur="admin.fictif", motif="fictif", epoch=1, expire_le=2))
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0035")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0036"
        assert len(cnx.execute(select(SERVICE_POLITIQUES_JOURNAL)).all()) == 1
