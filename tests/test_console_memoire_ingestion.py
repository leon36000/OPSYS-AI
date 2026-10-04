"""Parcours console M03 avec la vraie persistance PostgreSQL éphémère."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from memoire.doubles import postgres_ephemere, raison_sans_docker, vider
from starlette.requests import Request

from opsys import identite
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.memoire.store import MemoireEntreprise

SECRET = "secret-console-memoire-r26-test-" + "x" * 32
RAISON_SANS_DOCKER = raison_sans_docker()


@pytest.fixture(scope="module")
def url_pg():
    if RAISON_SANS_DOCKER is not None:
        pytest.skip(RAISON_SANS_DOCKER)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        memoire = MemoireEntreprise(url)
        memoire.migrer()
        yield url


@pytest.fixture
def console_admin(departements_demo, session, monkeypatch, url_pg):
    with session() as cnx:
        identite.creer_personne(cnx, "r26-admin", "Admin R26", "mot-de-passe-admin-test-1234", ["admin"])
    monkeypatch.setenv("OPSYS_DATABASE_URL", url_pg)
    app = application.creer_application(Configuration(SECRET), departements_demo, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        response = client.post(
            "/connexion",
            data={"identifiant": "r26-admin", "mot_de_passe": "mot-de-passe-admin-test-1234"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        yield client


def _csrf(client: TestClient) -> str:
    return client.get("/api/session").json()["csrf"]


def _vider(url_pg: str) -> None:
    vider(url_pg)
    import psycopg

    with psycopg.connect(url_pg) as cnx:
        cnx.execute("DELETE FROM memoire.procedure_admission_oubliees")


def _upload(
    client: TestClient,
    *,
    nonce: str,
    title: str = "Guide",
    content: bytes = b"Regle toiture locale.",
    filename: str = "guide.txt",
    content_type: str = "text/plain",
    document_id: str = "",
    file_headers: dict[str, str] | None = None,
    csrf: str | None = None,
):
    return client.post(
        "/memoire/procedures/admettre",
        data={
            "csrf": csrf or _csrf(client),
            "titre": title,
            "cle_admission": nonce,
            "attestation": "oui",
            "document_id": document_id,
        },
        files={"source": (filename, content, content_type, file_headers or {})},
        follow_redirects=False,
    )


def test_sans_session_et_champs_forges_refuses_sans_appeler_le_backend(monkeypatch, departements_demo, session):
    from opsys.console import memoire_ingestion_ui

    def interdit():
        raise AssertionError("aucun appel mémoire attendu")

    monkeypatch.setattr(memoire_ingestion_ui, "_service", interdit)
    app = application.creer_application(Configuration(SECRET), departements_demo, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        assert client.get("/memoire/procedures", follow_redirects=False).status_code == 303
        response = client.post(
            "/memoire/procedures/admettre",
            data={"acteur": "forgé"},
            files={"source": ("x.txt", b"source sensible", "text/plain")},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "source sensible" not in response.text


def test_admission_reprise_indexation_activation_cas_et_oubli(console_admin, url_pg):
    _vider(url_pg)
    client = console_admin
    token = "r26-durable-nonce-000001"
    content = b"# Intervention\n\nVerifier la toiture locale."
    response = _upload(client, nonce=token, title="<script>canari</script>", content=content)
    assert response.status_code == 303
    replay = _upload(client, nonce=token, title="<script>canari</script>", content=content)
    assert replay.status_code == 303

    page = client.get("/memoire/procedures")
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert "RECU" in page.text and "&lt;script&gt;canari&lt;/script&gt;" in page.text
    assert "<script>canari</script>" not in page.text
    assert "Verifier la toiture locale" not in page.text
    assert client.get("/memoire/procedures?offset=" + "9" * 5000).status_code == 400
    memoire = MemoireEntreprise(url_pg)
    assert not memoire.rechercher("toiture", None, 5, {"portee": "procedures"}).resultats

    service = memoire.procedures()
    serie = service.lister_series().series
    assert len(serie) == 1
    ident = str(serie[0]["document_id"])
    version = service.lister_versions(ident)[0]
    assert version.etat == "RECU"
    assert f'name="document_id" value="{ident}"' in page.text
    second = _upload(
        client,
        nonce="r26-version-nonce-000002",
        title="Guide v2",
        content=b"Panneau solaire hors service.",
        document_id=ident,
    )
    assert second.status_code == 303
    versions = service.lister_versions(ident)
    assert len(versions) == 2 and versions[1].etat == "RECU" and not versions[1].active
    csrf = _csrf(client)
    indexed = client.post(
        f"/memoire/procedures/{ident}/{version.sha256}/indexer", data={"csrf": csrf}, follow_redirects=False
    )
    assert indexed.status_code == 303
    indexed_second = client.post(
        f"/memoire/procedures/{ident}/{versions[1].sha256}/indexer", data={"csrf": csrf}, follow_redirects=False
    )
    assert indexed_second.status_code == 303
    assert not memoire.rechercher("toiture", None, 5, {"portee": "procedures"}).resultats
    activated = client.post(
        f"/memoire/procedures/{ident}/{version.sha256}/activer",
        data={"csrf": csrf, "attendu_sha256": ""},
        follow_redirects=False,
    )
    assert activated.status_code == 303
    found = memoire.rechercher("toiture", None, 5, {"portee": "procedures"}).resultats
    assert found and found[0].citations_verifiees
    assert not memoire.rechercher("panneau solaire", None, 5, {"portee": "procedures"}).resultats
    forged_query = client.post(
        f"/memoire/procedures/{ident}/{versions[1].sha256}/activer?forged=1",
        data={"csrf": csrf, "attendu_sha256": version.sha256},
        follow_redirects=False,
    )
    assert forged_query.status_code == 400
    activate_second = client.post(
        f"/memoire/procedures/{ident}/{versions[1].sha256}/activer",
        data={"csrf": csrf, "attendu_sha256": version.sha256},
        follow_redirects=False,
    )
    assert activate_second.status_code == 303
    assert MemoireEntreprise(url_pg).rechercher("panneau solaire", None, 5, {"portee": "procedures"}).resultats
    assert "version active" in client.get("/memoire/procedures").text

    stale = client.post(
        f"/memoire/procedures/{ident}/{version.sha256}/activer",
        data={"csrf": csrf, "attendu_sha256": "a" * 64},
        follow_redirects=False,
    )
    assert stale.status_code == 409
    refused = client.post(
        f"/memoire/procedures/{ident}/oublier",
        data={"csrf": csrf, "motif": "test", "confirmation": "non"},
        follow_redirects=False,
    )
    assert refused.status_code == 400
    forgotten = client.post(
        f"/memoire/procedures/{ident}/oublier",
        data={"csrf": csrf, "motif": "fin de test", "confirmation": "OUBLIER"},
        follow_redirects=False,
    )
    assert forgotten.status_code == 303
    assert not memoire.rechercher("toiture", None, 5, {"portee": "procedures"}).resultats
    assert service.lister_series().total == 0


def test_invalid_upload_and_markdown_plain_text_compatibility(console_admin, url_pg):
    _vider(url_pg)
    client = console_admin
    csrf = _csrf(client)
    bad = _upload(
        client, nonce="r26-invalid-nonce-00001", content=b"SENSITIVE-CANARY", filename="../source.txt", csrf=csrf
    )
    assert bad.status_code == 400
    invalid_csrf = _upload(client, nonce="r26-invalid-nonce-00002", content=b"SENSITIVE-CANARY", csrf="invalid")
    assert invalid_csrf.status_code == 403
    markdown = _upload(
        client,
        nonce="r26-markdown-plain-nonce-003",
        filename="doc.md",
        content_type="text/plain; charset=UTF-8",
        content="# Guide\n\nRègle locale.".encode(),
        csrf=csrf,
    )
    oversized = _upload(client, nonce="r26-invalid-nonce-00004", content=b"x" * (1_048_576 + 1), csrf=csrf)
    encoded = _upload(
        client, nonce="r26-invalid-nonce-00005", file_headers={"Content-Transfer-Encoding": "base64"}, csrf=csrf
    )
    unknown_mime = _upload(client, nonce="r26-invalid-nonce-00006", content_type="application/x-private", csrf=csrf)
    missing_boundary = console_admin.post(
        "/memoire/procedures/admettre",
        content=b"ignored",
        headers={"content-type": "multipart/form-data"},
        follow_redirects=False,
    )
    assert markdown.status_code == 303
    assert oversized.status_code == 413
    assert encoded.status_code == 400
    assert unknown_mime.status_code == 415
    assert missing_boundary.status_code == 415
    assert 'name="cle_admission" value="r26-invalid-nonce-00002"' in invalid_csrf.text
    assert 'name="cle_admission" value="r26-invalid-nonce-00004"' in oversized.text
    assert "SENSITIVE-CANARY" not in bad.text + invalid_csrf.text + oversized.text + encoded.text
    assert "../source.txt" not in bad.text and "application/x-private" not in unknown_mime.text
    procedures = MemoireEntreprise(url_pg).procedures()
    assert procedures.lister_series().total == 1
    assert procedures.lister_versions(procedures.lister_series().series[0]["document_id"])[0].etat == "RECU"
    assert not MemoireEntreprise(url_pg).rechercher("Règle locale", None, 5, {"portee": "procedures"}).resultats


def test_corps_streame_sans_content_length_refuse_depassement():
    import asyncio

    from opsys.console.memoire_ingestion_ui import _corps_borne

    delivered = False

    async def recevoir():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": b"x" * (1_048_576 + 65_537), "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive=recevoir)
    with pytest.raises(HTTPException) as erreur:
        asyncio.run(_corps_borne(request))
    assert erreur.value.status_code == 413


def test_upload_ferme_les_parties_et_erreur_db_ne_revele_pas_le_dsn(console_admin, url_pg, monkeypatch):
    from starlette.requests import Request as StarletteRequest

    from opsys.console import memoire_ingestion_ui

    _vider(url_pg)
    captures = []
    parser_reel = StarletteRequest.form

    async def parser_capture(request, *args, **kwargs):
        form = await parser_reel(request, *args, **kwargs)
        captures.append(form)
        return form

    monkeypatch.setattr(StarletteRequest, "form", parser_capture)
    response = _upload(console_admin, nonce="r26-close-form-nonce-0001", filename="../secret.txt")
    assert response.status_code == 400
    assert captures and all(
        upload.file.closed for form in captures for _, upload in form.multi_items() if hasattr(upload, "file")
    )
    assert MemoireEntreprise(url_pg).procedures().lister_series().total == 0

    dsn = "postgresql://opsys:must-not-leak@db.invalid:5432/memoire"

    def unavailable():
        raise RuntimeError(dsn)

    monkeypatch.setattr(memoire_ingestion_ui, "_service", unavailable)
    status = console_admin.get("/memoire/procedures")
    assert status.status_code == 503
    assert "mémoire indisponible" in status.text
    assert dsn not in status.text


def test_role_retire_pendant_parse_ne_declenche_pas_admission(console_admin, session, url_pg, monkeypatch):
    from opsys.console import memoire_ingestion_ui

    _vider(url_pg)
    parser = memoire_ingestion_ui._formulaire

    async def parser_puis_retirer(request):
        resultat = await parser(request)
        with session() as cnx:
            identite.retirer_role(cnx, "r26-admin", "admin")
        return resultat

    monkeypatch.setattr(memoire_ingestion_ui, "_formulaire", parser_puis_retirer)
    response = _upload(console_admin, nonce="r26-role-revoke-nonce-001", content=b"No admission")
    assert response.status_code == 403
    assert MemoireEntreprise(url_pg).procedures().lister_series().total == 0


def test_session_revalidee_apres_lecture_de_liste(console_admin, session, monkeypatch):
    from opsys.console import memoire_ingestion_ui

    reel = memoire_ingestion_ui._service()

    class ServiceRetireRoleApresLecture:
        def lister_series(self, **kwargs):
            page = reel.lister_series(**kwargs)
            with session() as cnx:
                identite.retirer_role(cnx, "r26-admin", "admin")
            return page

    monkeypatch.setattr(memoire_ingestion_ui, "_service", lambda: ServiceRetireRoleApresLecture())
    response = console_admin.get("/memoire/procedures")
    assert response.status_code == 403
    assert "r26-admin" not in response.text


def test_mutation_terminee_avant_retrait_role_est_masquee_par_revalidation(console_admin, session, url_pg, monkeypatch):
    from opsys.console import memoire_ingestion_ui

    _vider(url_pg)
    admission = _upload(console_admin, nonce="r26-effect-revoke-nonce-0001", content=b"Trace locale d'essai.")
    assert admission.status_code == 303
    service = MemoireEntreprise(url_pg).procedures()
    serie = service.lister_series().series[0]
    ident = str(serie["document_id"])
    sha = service.lister_versions(ident)[0].sha256
    reel = memoire_ingestion_ui._service()

    class ServiceRetireRoleApresIndexation:
        def indexer(self, document_id, digest):
            resultat = reel.indexer(document_id, digest)
            with session() as cnx:
                identite.retirer_role(cnx, "r26-admin", "admin")
            return resultat

    monkeypatch.setattr(memoire_ingestion_ui, "_service", lambda: ServiceRetireRoleApresIndexation())
    response = console_admin.post(
        f"/memoire/procedures/{ident}/{sha}/indexer", data={"csrf": _csrf(console_admin)}, follow_redirects=False
    )
    assert response.status_code == 403
    assert service.lire_etat(ident).etat == "INDEXE"


def test_lot_indexation_recu_cinq_max_reprise_et_sans_activation(console_admin, url_pg):
    _vider(url_pg)
    client = console_admin
    for index in range(8):
        response = _upload(
            client, nonce=f"r26-batch-recu-{index:04d}", title=f"Guide {index}",
            content=f"Règle interne {index}.".encode(),
        )
        assert response.status_code == 303
    service = MemoireEntreprise(url_pg).procedures()
    serie_deja_indexee = service.lister_series(limite=50, offset=0).series[0]
    version_deja_indexee = service.lister_versions(str(serie_deja_indexee["document_id"]))[0]
    service.indexer(str(serie_deja_indexee["document_id"]), version_deja_indexee.sha256)
    candidats = service.lister_recues(limite=5)
    assert len(candidats) == 5 and len(set(candidats)) == 5
    assert service.lister_recues(limite=1) == candidats[:1]
    with pytest.raises(ValueError):
        service.lister_recues(limite=6)
    with pytest.raises(ValueError):
        service.lister_recues(limite=True)

    csrf = _csrf(client)
    premier = client.post(
        "/memoire/procedures/indexer-recues", data={"csrf": csrf}, follow_redirects=False
    )
    assert premier.status_code == 200 and "5 traitée(s)" in premier.text
    assert 'class="message message-ok"' in premier.text
    assert 'class="message message-erreur"' not in premier.text
    assert "Règle interne" not in premier.text
    series = service.lister_series(limite=50, offset=0).series
    versions = [service.lister_versions(str(row["document_id"]))[0] for row in series]
    assert sum(version.etat == "INDEXE" for version in versions) == 6
    assert all(not version.active for version in versions)
    assert sum(version.etat == "RECU" for version in versions) == 2
    assert _compter_occurrences(url_pg) == 6

    second = client.post(
        "/memoire/procedures/indexer-recues", data={"csrf": _csrf(client)}, follow_redirects=False
    )
    assert second.status_code == 200 and "2 traitée(s)" in second.text
    assert not service.lister_recues()
    assert _compter_occurrences(url_pg) == 8
    before = _compter_occurrences(url_pg)
    vide = client.post(
        "/memoire/procedures/indexer-recues", data={"csrf": _csrf(client)}, follow_redirects=False
    )
    assert vide.status_code == 200 and "Aucune version RECU" in vide.text
    assert _compter_occurrences(url_pg) == before


def test_lot_refuse_si_role_retire_apres_lecture_avant_mutation(
    console_admin, session, url_pg, monkeypatch
):
    from opsys.console import memoire_ingestion_ui
    from opsys.memoire.ingestion_procedures import IngestionProcedures

    _vider(url_pg)
    admission = _upload(
        console_admin, nonce="r26-batch-read-acl-0001", content="Source privée de test.".encode()
    )
    assert admission.status_code == 303
    service = memoire_ingestion_ui._service()
    reel = IngestionProcedures.lister_versions
    indexer_reel = IngestionProcedures.indexer
    appels_indexation = 0

    def lire_puis_retirer_role(self, document_id):
        resultat = reel(self, document_id)
        with session() as cnx:
            identite.retirer_role(cnx, "r26-admin", "admin")
        return resultat

    def compter_indexation(self, document_id, sha256):
        nonlocal appels_indexation
        appels_indexation += 1
        return indexer_reel(self, document_id, sha256)

    monkeypatch.setattr(IngestionProcedures, "lister_versions", lire_puis_retirer_role)
    monkeypatch.setattr(IngestionProcedures, "indexer", compter_indexation)
    refuse = console_admin.post(
        "/memoire/procedures/indexer-recues", data={"csrf": _csrf(console_admin)}, follow_redirects=False
    )
    assert refuse.status_code == 403
    assert appels_indexation == 0
    assert service.lister_recues()  # reçu reste disponible, aucun fragment n’a été indexé
    assert _compter_occurrences(url_pg) == 0


def test_lot_indexation_rejette_csrf_et_ne_fournit_aucune_limite_client(
    console_admin, monkeypatch
):
    from opsys.console import memoire_ingestion_ui

    def aucun_appel(*args, **kwargs):
        raise AssertionError("le backend doit être refusé avant sélection")

    monkeypatch.setattr(memoire_ingestion_ui, "_service", aucun_appel)
    bad_csrf = console_admin.post(
        "/memoire/procedures/indexer-recues", data={"csrf": "bad"}, follow_redirects=False
    )
    bad_limit = console_admin.post(
        "/memoire/procedures/indexer-recues",
        data={"csrf": _csrf(console_admin), "limite": "64"}, follow_redirects=False,
    )
    assert bad_csrf.status_code == 403
    assert bad_limit.status_code == 400


def _compter_occurrences(url_pg: str) -> int:
    import psycopg

    with psycopg.connect(url_pg) as cnx:
        return int(cnx.execute("SELECT count(*) FROM memoire.procedure_occurrences").fetchone()[0])


def test_lot_indexation_reprend_apres_echec_sans_doublons(console_admin, url_pg, monkeypatch):
    from opsys.console import memoire_ingestion_ui
    from opsys.memoire.ingestion_procedures import IngestionProcedures

    _vider(url_pg)
    for index in range(6):
        response = _upload(
            console_admin, nonce=f"r26-batch-retry-{index:04d}", title=f"Retry {index}",
            content=f"Source retry {index}.".encode(),
        )
        assert response.status_code == 303
    service = memoire_ingestion_ui._service()
    sha_en_echec = service.lister_recues(limite=5)[2][1]
    indexer_reel = IngestionProcedures.indexer
    echec_injecte = False

    def indexer_avec_coupure(self, document_id, sha256):
        nonlocal echec_injecte
        if sha256 == sha_en_echec and not echec_injecte:
            echec_injecte = True
            raise ValueError("source privée, ne pas afficher")
        return indexer_reel(self, document_id, sha256)

    monkeypatch.setattr(IngestionProcedures, "indexer", indexer_avec_coupure)
    premiere = console_admin.post(
        "/memoire/procedures/indexer-recues", data={"csrf": _csrf(console_admin)}, follow_redirects=False
    )
    assert premiere.status_code == 200 and "ERREUR_INDEXATION" in premiere.text
    assert "Lot incomplet" in premiere.text
    assert 'class="message message-erreur"' in premiere.text
    assert "source privée" not in premiere.text
    assert _compter_occurrences(url_pg) == 4
    assert len(service.lister_recues()) == 2

    reprise = console_admin.post(
        "/memoire/procedures/indexer-recues", data={"csrf": _csrf(console_admin)}, follow_redirects=False
    )
    assert reprise.status_code == 200 and "2 traitée(s)" in reprise.text
    assert not service.lister_recues()
    assert _compter_occurrences(url_pg) == 6


def test_lot_indexation_revalide_role_avant_chaque_document(
    console_admin, session, url_pg, monkeypatch
):
    from opsys.memoire.ingestion_procedures import IngestionProcedures

    _vider(url_pg)
    for index in range(3):
        response = _upload(
            console_admin, nonce=f"r26-batch-acl-{index:04d}", title=f"ACL {index}",
            content=f"Secret ACL {index}.".encode(),
        )
        assert response.status_code == 303
    from opsys.memoire.store import MemoireEntreprise

    service = MemoireEntreprise(url_pg).procedures()
    indexer_reel = IngestionProcedures.indexer
    appels = 0

    def indexer_puis_retirer_role(self, document_id, sha256):
        nonlocal appels
        resultat = indexer_reel(self, document_id, sha256)
        appels += 1
        if appels == 1:
            with session() as cnx:
                identite.retirer_role(cnx, "r26-admin", "admin")
        return resultat

    monkeypatch.setattr(IngestionProcedures, "indexer", indexer_puis_retirer_role)
    csrf = _csrf(console_admin)
    refuse = console_admin.post(
        "/memoire/procedures/indexer-recues", data={"csrf": csrf}, follow_redirects=False
    )
    assert refuse.status_code == 403
    assert appels == 1
    states = [
        version.etat
        for row in service.lister_series(limite=50, offset=0).series
        for version in service.lister_versions(str(row["document_id"]))
    ]
    assert states.count("INDEXE") == 1 and states.count("RECU") == 2
    assert "Secret ACL" not in refuse.text




def test_lot_intercalage_autre_indexation_idempotent_sans_double_occurrence(console_admin, url_pg, monkeypatch):
    """Intercalage déterministe d'un autre traitement; pas une mesure de charge parallèle."""
    from opsys.memoire.ingestion_procedures import IngestionProcedures

    _vider(url_pg)
    admission = _upload(
        console_admin, nonce="r26-batch-intercalage-01", title="Guide fictif intercalage",
        content=b"fictif: true\nVerifier le materiau du chantier.",
    )
    assert admission.status_code == 303
    reel = IngestionProcedures.indexer
    appels = 0

    def autre_traitement_avant_indexation(self, document_id, empreinte):
        nonlocal appels
        # Le traitement concurrent obtient le verrou et termine avant notre prise du même verrou.
        premiere = reel(self, document_id, empreinte)
        appels += 1
        seconde = reel(self, document_id, empreinte)
        assert premiere == seconde
        return seconde

    monkeypatch.setattr(IngestionProcedures, "indexer", autre_traitement_avant_indexation)
    reponse = console_admin.post(
        "/memoire/procedures/indexer-recues", data={"csrf": _csrf(console_admin)}, follow_redirects=False
    )
    assert reponse.status_code == 200 and "1 traitée(s)" in reponse.text
    assert "1 indexée(s)" not in reponse.text
    assert appels == 1 and _compter_occurrences(url_pg) == 1
    service = MemoireEntreprise(url_pg).procedures()
    assert not service.lister_recues()
    assert all(
        not version.active
        for serie in service.lister_series().series
        for version in service.lister_versions(str(serie["document_id"]))
    )
