"""Parcours privé du pilote PDF natif, avec devis entièrement fictif."""

from __future__ import annotations

import base64
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from m3_estimation import devis_durable, soumission_pdf
from sqlalchemy import select, update
from starlette.datastructures import UploadFile

from opsys import fusion_pdf, identite, stockage
from opsys.console import application, securite
from opsys.console.securite import Configuration
from opsys.stockage.schema import FUSION_PDF_LOTS, FUSION_PDF_QUOTA

SECRET = "secret-console-pdf-fictif-" + "x" * 32
PASSWORD = "mot-de-passe-pdf-fictif-1234"
OWNER = "nathan"
ADMIN = "admin-pdf-second-fictif"
EMPLOYEE = "employe-pdf-fictif"
PREFIX = "/opsys"
KEY = base64.b64encode(b"p" * 32).decode("ascii")
MARKER = "PDF-CANARI-FICTIF-CLIENT"


@pytest.fixture
def pdf_fictif():
    devis, erreur = devis_durable.creer_devis(
        devis_id="DEVIS-CONSOLE-PDF-FICTIF",
        lead_id="lead-fictif",
        chantier_id=None,
        lignes=[
            {
                "description": MARKER,
                "quantite": "2",
                "unite": "pi_lin",
                "cout_unitaire": "10.00",
                "reference_besoin_materiau": None,
            }
        ],
        taux_marge="0.25",
        horodatage="2026-10-02T08:00:00+00:00",
        registre_cible=[],
    )
    assert erreur is None and isinstance(devis["prix_total"], Decimal)
    contenu, erreur = soumission_pdf.generer_brouillon_pdf(devis)
    assert erreur is None and contenu.startswith(b"%PDF-")
    return contenu


@pytest.fixture
def client_pdf(nathan, monkeypatch):
    monkeypatch.delenv("OPSYS_DATABASE_URL", raising=False)
    monkeypatch.setenv("OPSYS_INGESTION_CLE", KEY)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN, "Administrateur fictif", PASSWORD, ["admin"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé fictif", PASSWORD, ["employee"])
    app = application.creer_application(Configuration(SECRET, cookie_securise=False), cnx_factory=stockage.transaction)
    with TestClient(app, base_url=f"http://testserver{PREFIX}", raise_server_exceptions=False) as client:
        _connecter(client, OWNER)
        yield client


def _connecter(client: TestClient, utilisateur: str) -> str:
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, utilisateur)
    assert personne is not None
    session = securite.ouvrir_session(utilisateur, personne.roles, 3600)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, SECRET), path=PREFIX)
    return session.csrf


def _admettre(client: TestClient, csrf: str, source: bytes, mutation: str = "pdf-console-fictif-1", **extra):
    return client.post(
        "/fusion/pdf/lots",
        data={"csrf": csrf, "mutation_id": mutation, **extra},
        files={"pdf_file": ("devis-fictif.pdf", source, "application/pdf")},
        follow_redirects=False,
    )


def _quota_et_lots():
    with stockage.transaction() as cnx:
        quota = cnx.execute(select(FUSION_PDF_QUOTA.c.lots, FUSION_PDF_QUOTA.c.octets_cipher)).one()
        lots = cnx.execute(select(FUSION_PDF_LOTS)).mappings().all()
    return quota, lots


def test_hub_et_admission_rejeu_prive_et_preparation_explicite(client_pdf, pdf_fictif, monkeypatch):
    client = client_pdf
    hub = client.get("/fusion")
    assert hub.status_code == 200 and "/fusion-operationnelle" in hub.text and "/fusion/pdf" in hub.text
    lire_resultat_original = fusion_pdf.lire_resultat
    monkeypatch.setattr(fusion_pdf, "lire_resultat", lambda *_: pytest.fail("GET implicite du résultat"))
    page = client.get("/fusion/pdf")
    assert page.status_code == 200 and "private" in page.headers["cache-control"]
    assert MARKER not in page.text
    csrf = _csrf(page.text)

    first = _admettre(client, csrf, pdf_fictif)
    assert first.status_code == 303, first.text
    lot_id = _lot_id(first.headers["location"])
    assert MARKER not in first.text
    quota, rows = _quota_et_lots()
    assert quota.lots == 1 and len(rows) == 1
    assert rows[0]["source_cipher"].encode() != pdf_fictif
    assert pdf_fictif not in rows[0]["source_cipher"].encode()

    replay = _admettre(client, csrf, pdf_fictif)
    assert replay.status_code == 303 and _lot_id(replay.headers["location"]) == lot_id
    assert _quota_et_lots()[0].lots == 1

    detail = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert detail.status_code == 200 and MARKER not in detail.text
    assert "Préparer les extraits" in detail.text
    assert detail.headers["cache-control"] == "private, no-store, max-age=0"

    prepared = client.post(
        f"/fusion/pdf/lots/{lot_id}/preparer",
        data={"csrf": csrf, "revision_attendue": "1"},
        follow_redirects=False,
    )
    assert prepared.status_code == 303, prepared.text
    with stockage.transaction() as cnx:
        row = cnx.execute(select(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id)).one()
        assert row.statut == "EXTRAIT_PREPARATOIRE" and row.revision == 2
        assert MARKER not in row.resultat_cipher

    detail = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert detail.status_code == 200 and MARKER not in detail.text
    monkeypatch.setattr(fusion_pdf, "lire_resultat", lire_resultat_original)
    extrait = client.get(f"/fusion/pdf/lots/{lot_id}/extraits?page=1")
    assert extrait.status_code == 200 and MARKER in extrait.text
    assert "préparatoire" in extrait.text.lower() and "comptable" in extrait.text.lower()


def test_admin_partage_les_lots_de_la_meme_sqlite_sans_acces_employe(client_pdf, pdf_fictif):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    cree = _admettre(client, csrf, pdf_fictif, mutation="auteur-owner-fictif")
    assert cree.status_code == 303
    lot_id = _lot_id(cree.headers["location"])
    csrf_admin = _connecter(client, ADMIN)
    listing = client.get("/fusion/pdf")
    assert listing.status_code == 200 and lot_id in listing.text and OWNER in listing.text
    detail = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert detail.status_code == 200 and OWNER in detail.text
    refuse = client.post(
        f"/fusion/pdf/lots/{lot_id}/preparer",
        data={"csrf": csrf_admin, "revision_attendue": "1"},
        follow_redirects=False,
    )
    assert refuse.status_code == 303, refuse.text
    assert client.get(f"/fusion/pdf/lots/{lot_id}/extraits?page=1").status_code == 200

    _connecter(client, EMPLOYEE)
    assert client.get("/fusion/pdf").status_code == 403
    assert client.get(f"/fusion/pdf/lots/{lot_id}").status_code == 403


@pytest.mark.parametrize("case", ["csrf", "query", "unknown", "bad_magic", "too_large", "large_envelope", "duplicate"])
def test_refus_admission_sans_ecriture(client_pdf, pdf_fictif, case):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    before = _quota_et_lots()[0].lots
    if case == "csrf":
        response = _admettre(client, "incorrect", pdf_fictif, mutation="csrf-fictif")
        assert response.status_code == 403
    elif case == "query":
        response = client.post(
            "/fusion/pdf/lots?mode=autre",
            data={"csrf": csrf, "mutation_id": "query-fictif"},
            files={"pdf_file": ("a.pdf", pdf_fictif, "application/pdf")},
        )
        assert response.status_code == 400
    elif case == "unknown":
        response = _admettre(client, csrf, pdf_fictif, mutation="extra-fictif", acteur="forged")
        assert response.status_code == 400
    elif case == "bad_magic":
        response = _admettre(client, csrf, b"not a PDF", mutation="magic-fictif")
        assert response.status_code == 400
    elif case == "too_large":
        response = _admettre(client, csrf, b"%PDF-" + b"x" * 1_048_572, mutation="large-fictif")
        assert response.status_code == 413
    elif case == "large_envelope":
        response = client.post(
            "/fusion/pdf/lots",
            data={
                "csrf": csrf,
                "mutation_id": "enveloppe-fictive",
                "unrelated": "x" * 1_120_000,
            },
            files={"pdf_file": ("a.pdf", pdf_fictif, "application/pdf")},
        )
        assert response.status_code == 413
    else:
        response = client.post(
            "/fusion/pdf/lots",
            files=[
                ("csrf", (None, csrf)),
                ("csrf", (None, csrf)),
                ("mutation_id", (None, "dup-fictif")),
                ("pdf_file", ("a.pdf", pdf_fictif, "application/pdf")),
            ],
        )
        assert response.status_code == 400
    assert _quota_et_lots()[0].lots == before
    assert KEY not in response.text and pdf_fictif[:32].decode("latin1") not in response.text


def test_rejeu_meme_mutation_autre_source_est_conflit(client_pdf, pdf_fictif):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    assert _admettre(client, csrf, pdf_fictif, mutation="conflit-fictif").status_code == 303
    autre = pdf_fictif.replace(b"BROUILLON", b"BROUILLON") + b"\n"
    conflit = _admettre(client, csrf, autre, mutation="conflit-fictif")
    assert conflit.status_code == 409
    assert "CONFLIT_MUTATION" in conflit.text
    assert _quota_et_lots()[0].lots == 1


def test_retrait_role_pendant_upload_ne_cree_pas_de_lot(client_pdf, pdf_fictif, monkeypatch):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    from opsys.console import fusion_pdf_ui

    parser_original = fusion_pdf_ui._multipart_pdf

    async def retirer_apres_lecture(request):
        fields, source = await parser_original(request)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, OWNER, "nathan_owner")
        return fields, source

    monkeypatch.setattr(fusion_pdf_ui, "_multipart_pdf", retirer_apres_lecture)
    response = _admettre(client, csrf, pdf_fictif, mutation="retrait-role-fictif")
    assert response.status_code == 403
    assert _quota_et_lots()[0].lots == 0


def test_retrait_role_apres_worker_masque_reponse_mais_conserve_etat_durable(client_pdf, pdf_fictif, monkeypatch):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    cree = _admettre(client, csrf, pdf_fictif, mutation="retrait-post-worker-fictif")
    assert cree.status_code == 303
    lot_id = _lot_id(cree.headers["location"])
    preparer_original = fusion_pdf.preparer

    def preparer_puis_retirer_role(fabrique, acteur, identifiant, revision):
        resultat = preparer_original(fabrique, acteur, identifiant, revision)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, OWNER, "nathan_owner")
        return resultat

    monkeypatch.setattr(fusion_pdf, "preparer", preparer_puis_retirer_role)
    response = client.post(
        f"/fusion/pdf/lots/{lot_id}/preparer",
        data={"csrf": csrf, "revision_attendue": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id)).one()
        assert saved.statut == "EXTRAIT_PREPARATOIRE" and saved.revision == 2


def test_revision_obsolete_refuse_et_session_absente_redirige(client_pdf, pdf_fictif):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    cree = _admettre(client, csrf, pdf_fictif, mutation="revision-obsolete-fictif")
    assert cree.status_code == 303
    lot_id = _lot_id(cree.headers["location"])
    response = client.post(
        f"/fusion/pdf/lots/{lot_id}/preparer",
        data={"csrf": csrf, "revision_attendue": "2"},
        follow_redirects=False,
    )
    assert response.status_code == 409 and "CONFLIT_REVISION" in response.text
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id)).one()
        assert saved.statut == "RECU" and saved.revision == 1

    client.cookies.clear()
    assert client.get("/fusion/pdf", follow_redirects=False).status_code == 303


def test_erreur_service_garde_la_cle_de_rejeu_et_upload_est_ferme(client_pdf, pdf_fictif, monkeypatch):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    mutation = "reprise-cle-fictive"
    fermetures = []
    close_original = UploadFile.close

    async def close_suivi(fichier):
        fermetures.append(fichier.filename)
        await close_original(fichier)

    monkeypatch.setattr(UploadFile, "close", close_suivi)
    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    response = _admettre(client, csrf, pdf_fictif, mutation=mutation)
    assert response.status_code == 503
    assert f'name="mutation_id" value="{mutation}"' in response.text
    assert "PDF-CANARI-FICTIF" not in response.text and KEY not in response.text
    assert fermetures == ["devis-fictif.pdf"]
    assert _quota_et_lots()[0].lots == 0


@pytest.mark.parametrize("query", ["?page=0", "?page=999", "?page=1&page=1", "?page=1&other=1"])
def test_extraits_rejettent_pagination_invalide_avant_lecture(client_pdf, query, monkeypatch):
    from opsys.console import fusion_pdf_ui

    monkeypatch.setattr(fusion_pdf_ui.fusion_pdf, "lire_resultat", lambda *_: pytest.fail("lecture prématurée"))
    response = client_pdf.get(f"/fusion/pdf/lots/00000000-0000-4000-8000-000000000001/extraits{query}")
    assert response.status_code == 400


def test_lot_uuid_inconnu_retourne_404_http_stable(client_pdf):
    response = client_pdf.get("/fusion/pdf/lots/00000000-0000-4000-8000-000000000001")
    assert response.status_code == 404
    assert "LOT_INCONNU" in response.text
    assert "no-store" in response.headers["cache-control"]
    assert SECRET not in response.text and KEY not in response.text


def test_extraits_lot_non_prepare_retourne_409_http_stable(client_pdf, pdf_fictif):
    csrf = _csrf(client_pdf.get("/fusion/pdf"))
    cree = _admettre(client_pdf, csrf, pdf_fictif, mutation="extraits-non-prepares-fictif")
    assert cree.status_code == 303
    lot_id = _lot_id(cree.headers["location"])
    response = client_pdf.get(f"/fusion/pdf/lots/{lot_id}/extraits?page=1")
    assert response.status_code == 409
    assert "PDF_RESULTAT_INDISPONIBLE" in response.text
    assert MARKER not in response.text and KEY not in response.text


def test_erreur_lister_devient_code_http_sans_detail_interne(client_pdf, monkeypatch):
    def echec(*_args, **_kwargs):
        raise fusion_pdf.FusionPDFErreur("PDF_ISOLATION_INDISPONIBLE", "secret interne fictif", 503)

    monkeypatch.setattr(fusion_pdf, "lister", echec)
    response = client_pdf.get("/fusion/pdf")
    assert response.status_code == 503
    assert "PDF_ISOLATION_INDISPONIBLE" in response.text
    assert "secret interne fictif" not in response.text
    assert "no-store" in response.headers["cache-control"]


def test_permission_error_est_normalisee_et_session_revokee_est_reverifiee(client_pdf, monkeypatch):
    monkeypatch.setattr(
        fusion_pdf,
        "lire",
        lambda *_: (_ for _ in ()).throw(PermissionError("secret permission fictif")),
    )
    lot_id = "00000000-0000-4000-8000-000000000001"
    refuse = client_pdf.get(f"/fusion/pdf/lots/{lot_id}")
    assert refuse.status_code == 403 and "ACCES_PDF_REFUSE" in refuse.text
    assert "secret permission fictif" not in refuse.text
    assert "no-store" in refuse.headers["cache-control"]

    def retirer_et_refuser(*_args):
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, OWNER, "nathan_owner")
        raise fusion_pdf.FusionPDFErreur("LOT_INCONNU", "detail sensible fictif", 404)

    monkeypatch.setattr(fusion_pdf, "lire", retirer_et_refuser)
    response = client_pdf.get(f"/fusion/pdf/lots/{lot_id}")
    assert response.status_code == 403
    assert "LOT_INCONNU" not in response.text and "detail sensible fictif" not in response.text


def test_cle_absente_et_cipher_resultat_corrompu_retournent_codes_stables(client_pdf, pdf_fictif, monkeypatch):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    cree = _admettre(client, csrf, pdf_fictif, mutation="resultat-protege-fictif")
    assert cree.status_code == 303
    lot_id = _lot_id(cree.headers["location"])
    prepared = client.post(
        f"/fusion/pdf/lots/{lot_id}/preparer",
        data={"csrf": csrf, "revision_attendue": "1"},
        follow_redirects=False,
    )
    assert prepared.status_code == 303

    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    cle_absente = client.get(f"/fusion/pdf/lots/{lot_id}/extraits?page=1")
    assert cle_absente.status_code == 503 and "CLE_INDISPONIBLE" in cle_absente.text
    assert MARKER not in cle_absente.text and KEY not in cle_absente.text

    monkeypatch.setenv("OPSYS_INGESTION_CLE", KEY)
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FUSION_PDF_LOTS)
            .where(FUSION_PDF_LOTS.c.lot_id == lot_id)
            .values(
                resultat_cipher="corruption-fictive",
            )
        )
    corrompu = client.get(f"/fusion/pdf/lots/{lot_id}/extraits?page=1")
    assert corrompu.status_code == 409 and "CIPHER_INVALIDE" in corrompu.text
    assert MARKER not in corrompu.text and KEY not in corrompu.text


def _csrf(page) -> str:
    import re

    contenu = page.text if hasattr(page, "text") else page
    match = re.search(r'name="csrf" value="([^"]+)"', contenu)
    assert match
    return match.group(1)


def _lot_id(location: str) -> str:
    import re

    match = re.search(r"/fusion/pdf/lots/([0-9a-f-]{36})", location)
    assert match, location
    return match.group(1)
