"""Parcours privé du pilote PDF natif, avec devis entièrement fictif."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from m3_estimation import devis_durable, soumission_pdf
from sqlalchemy import delete, select, update
from starlette.datastructures import UploadFile

from opsys import fusion_pdf, identite, stockage
from opsys.console import application, securite
from opsys.console.securite import Configuration
from opsys.stockage.schema import FUSION_PDF_LOTS, FUSION_PDF_QUOTA, META, REGISTRES

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
        "lire_avec_provenance",
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

    monkeypatch.setattr(fusion_pdf, "lire_avec_provenance", retirer_et_refuser)
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


def _instantane_pdf_et_memoire():
    """Toutes les tables réelles de la fixture : GET ne modifie ni quotas, ni provenance, ni journal."""
    with stockage.transaction() as cnx:
        return {
            table.name: tuple(sorted((tuple(row) for row in cnx.execute(select(table))), key=repr))
            for table in META.sorted_tables
        }


def _preparation_fictive(monkeypatch):
    """Seule frontière simulée : le worker PDF. Stockage, chiffrement et provenance restent réels."""
    def worker_fictif(source):
        texte = "Extrait entièrement fictif " + MARKER
        return {"ok": True, "resultat": {
            "schema_version": 1, "source_sha256": hashlib.sha256(source).hexdigest(),
            "extracteur": fusion_pdf.EXTRACTEUR, "configuration_sha256": fusion_pdf.CONFIGURATION_SHA256,
            "pages": [{"numero": 1, "fragments": [{
                "id": "p1-f1", "texte": texte, "sha256": hashlib.sha256(texte.encode()).hexdigest(),
            }]}],
        }}

    monkeypatch.setattr(fusion_pdf, "_extraire_isole", worker_fictif)


@pytest.mark.parametrize("lecteur", [OWNER, ADMIN])
def test_provenance_m10_pdf_apres_reconnexion_est_privee_et_sans_ecriture(client_pdf, pdf_fictif, lecteur, monkeypatch):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="provenance-admission-fictive")
    assert admission.status_code == 303, admission.text
    lot_id = _lot_id(admission.headers["location"])
    client.cookies.clear()
    csrf = _connecter(client, lecteur)
    avant = _instantane_pdf_et_memoire()
    detail = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert detail.status_code == 200, detail.text
    assert "Provenance M10" in detail.text and "FINANCIAL" in detail.text
    assert "Source candidate préparatoire, non validée" in detail.text
    assert "<dt>Révision du lot PDF</dt><dd>1</dd>" in detail.text
    assert "<dt>Révision M10</dt><dd>1</dd>" in detail.text
    assert hashlib.sha256(pdf_fictif).hexdigest() in detail.text
    reference = f"opsys-ingestion://m05-financecore/pdf/lots/{lot_id}"
    assert reference in detail.text and f'href="{reference}"' not in detail.text
    assert MARKER not in detail.text and KEY not in detail.text and "devis-fictif.pdf" not in detail.text
    assert detail.headers["cache-control"] == "private, no-store, max-age=0"
    assert _instantane_pdf_et_memoire() == avant

    _preparation_fictive(monkeypatch)
    prepared = client.post(
        f"/fusion/pdf/lots/{lot_id}/preparer", data={"csrf": csrf, "revision_attendue": "1"},
        follow_redirects=False,
    )
    assert prepared.status_code == 303, prepared.text
    avant = _instantane_pdf_et_memoire()
    detail = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert detail.status_code == 200, detail.text
    assert "<dt>État de la source</dt><dd>EXTRAIT_PREPARATOIRE</dd>" in detail.text
    assert "<dt>Révision du lot PDF</dt><dd>2</dd>" in detail.text
    assert "<dt>Révision M10</dt><dd>2</dd>" in detail.text
    assert "<dt>Pages préparées</dt><dd>1</dd>" in detail.text
    assert MARKER not in detail.text and "non validée" in detail.text
    assert _instantane_pdf_et_memoire() == avant
    extrait = client.get(f"/fusion/pdf/lots/{lot_id}/extraits?page=1")
    assert extrait.status_code == 200 and MARKER in extrait.text
    assert _instantane_pdf_et_memoire() == avant


def test_lot_historique_sans_trace_reste_absent_sans_backfill(client_pdf, pdf_fictif):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="ancien-lot-fictif")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    # Image historique synthétique : seul ce registre documentaire de fixture est retiré.
    with stockage.transaction() as cnx:
        cnx.execute(delete(REGISTRES).where(
            (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        ))
    avant = _instantane_pdf_et_memoire()
    for _ in range(2):
        detail = client.get(f"/fusion/pdf/lots/{lot_id}")
        assert detail.status_code == 200, detail.text
        assert "Provenance M10 absente pour ce lot" in detail.text
        assert "Source candidate préparatoire, non validée" not in detail.text
    assert _instantane_pdf_et_memoire() == avant


@pytest.mark.parametrize("champ,valeur", [
    ("source_sha256", "0" * 64), ("configuration_sha256", "0" * 64),
    ("source_revision", 2), ("revision", True), ("total_pages", True),
    ("reference_locale", "javascript:CANARI-FICTIF"), ("horodatage", "date-sans-fuseau"),
    ("horodatage", "2030-10-04T08:00:00+00:00"),
    ("texte", MARKER), ("statut", "VALIDE"), ("acteur_transition", "nom@example.com"),
])
def test_projection_provenance_malfomee_ou_divergente_est_503_sans_corps(
    client_pdf, pdf_fictif, monkeypatch, champ, valeur,
):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="projection-fictive")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    original = fusion_pdf.lire_avec_provenance

    def projection_alteree(*args):
        lecture = original(*args)
        assert lecture["provenance"] is not None
        return {**lecture, "provenance": {**lecture["provenance"], champ: valeur}}

    monkeypatch.setattr(fusion_pdf, "lire_avec_provenance", projection_alteree)
    avant = _instantane_pdf_et_memoire()
    response = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert response.status_code == 503, response.text
    assert "PDF_PROVENANCE_INDISPONIBLE" in response.text
    assert MARKER not in response.text and "CANARI-FICTIF" not in response.text
    assert "Source candidate" not in response.text and "no-store" in response.headers["cache-control"]
    assert _instantane_pdf_et_memoire() == avant


def test_provenance_source_reelle_alteree_refuse_sans_ecriture(client_pdf, pdf_fictif):
    from opsys.stockage import codec

    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="chaine-alteree-fictive")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    with stockage.transaction() as cnx:
        filtre = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        row = cnx.execute(select(REGISTRES).where(filtre)).one()
        document = codec.decoder(row.maillon)
        assert document["lot_id"] == lot_id
        document["source_sha256"] = "0" * 64  # Aucun recalcul de la chaîne : vraie altération SQL.
        cnx.execute(update(REGISTRES).where(filtre & (REGISTRES.c.rang == row.rang)).values(
            maillon=codec.encoder(document),
        ))
    avant = _instantane_pdf_et_memoire()
    response = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert response.status_code == 503, response.text
    assert "PDF_PROVENANCE_INDISPONIBLE" in response.text
    assert MARKER not in response.text and KEY not in response.text and lot_id not in response.text
    assert _instantane_pdf_et_memoire() == avant


def test_quota_provenance_refuse_avant_decodeur_et_sans_ecriture(client_pdf, pdf_fictif, monkeypatch):
    from opsys.stockage import codec

    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="quota-provenance-fictif")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    with stockage.transaction() as cnx:
        filtre = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(REGISTRES).where(filtre)).one().maillon
        cnx.execute(update(REGISTRES).where(filtre).values(maillon="x" * 65_537))
    avant = _instantane_pdf_et_memoire()
    appels_decodeur = []

    def decoder_interdit(*args, **kwargs):
        appels_decodeur.append(True)
        raise AssertionError("le quota doit refuser avant le décodage")

    monkeypatch.setattr(codec, "decoder", decoder_interdit)
    response = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert response.status_code == 503, response.text
    assert "PDF_PROVENANCE_INDISPONIBLE" in response.text and appels_decodeur == []
    assert _instantane_pdf_et_memoire() == avant


def test_provenance_valide_passe_par_echappement_et_reference_locale_non_active(client_pdf, pdf_fictif, monkeypatch):
    from opsys.console import fusion_pdf_ui

    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="escape-provenance-fictive")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    original = fusion_pdf_ui.pages.e
    echappees = []

    def observer_echappement(valeur):
        echappees.append(valeur)
        return original(valeur)

    monkeypatch.setattr(fusion_pdf_ui.pages, "e", observer_echappement)
    response = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert response.status_code == 200, response.text
    assert f"opsys-ingestion://m05-financecore/pdf/lots/{lot_id}" in echappees
    assert fusion_pdf.EXTRACTEUR in echappees and "FINANCIAL" in echappees
    assert 'href="opsys-ingestion:' not in response.text


@pytest.mark.parametrize("champ,valeur,statut", [
    ("extracteur", '<svg onload="CANARI-FICTIF">', "RECU"),
    ("auteur", "nom@example.com", "RECU"),
    ("code", "CODE_INCONNU_FICTIF", "REFUSE"),
    ("code", None, "REFUSE"),
    ("code", "PDF_MALFORME", "ERREUR_REPRENABLE"),
])
def test_projection_substituee_reste_stricte_meme_si_lot_et_trace_correspondent(
    client_pdf, pdf_fictif, monkeypatch, champ, valeur, statut,
):
    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="projection-substituee-fictive")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    original = fusion_pdf.lire_avec_provenance

    def projection_substituee(*args):
        lecture = original(*args)
        cle_lot = "acteur" if champ == "auteur" else champ
        return {"lot": {**lecture["lot"], cle_lot: valeur, "statut": statut},
                "provenance": {**lecture["provenance"], champ: valeur, "statut": statut}}

    monkeypatch.setattr(fusion_pdf, "lire_avec_provenance", projection_substituee)
    avant = _instantane_pdf_et_memoire()
    response = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert response.status_code == 503, response.text
    assert "PDF_PROVENANCE_INDISPONIBLE" in response.text
    assert "CANARI-FICTIF" not in response.text and "nom@example.com" not in response.text
    assert _instantane_pdf_et_memoire() == avant


@pytest.mark.parametrize("incident", ["role", "desactivation", "expiration"])
def test_provenance_reverifie_autorite_apres_rendu_sans_corps(client_pdf, pdf_fictif, monkeypatch, incident):
    from opsys.console import fusion_pdf_ui

    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="retrait-provenance-fictive")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    original = fusion_pdf_ui._reponse
    maintenant = [int(datetime.now(UTC).timestamp())]
    if incident == "expiration":
        monkeypatch.setattr(securite, "time", SimpleNamespace(time=lambda: maintenant[0]))

    def rendu_puis_retrait(*args, **kwargs):
        response = original(*args, **kwargs)
        assert "Provenance M10" in response.body.decode()
        if incident == "expiration":
            maintenant[0] += 10_000_000
        else:
            with stockage.transaction() as cnx:
                if incident == "role":
                    identite.retirer_role(cnx, OWNER, "nathan_owner")
                else:
                    identite.activer(cnx, OWNER, False)
        return response

    monkeypatch.setattr(fusion_pdf_ui, "_reponse", rendu_puis_retrait)
    response = client.get(f"/fusion/pdf/lots/{lot_id}", follow_redirects=False)
    assert response.status_code == (403 if incident == "role" else 303), response.text
    assert "Provenance M10" not in response.text and lot_id not in response.text and MARKER not in response.text


def test_projection_lot_et_trace_uuid_malforme_meme_si_36_caracteres_autorises(client_pdf, pdf_fictif):
    from opsys.console import fusion_pdf_ui

    client = client_pdf
    csrf = _csrf(client.get("/fusion/pdf"))
    admission = _admettre(client, csrf, pdf_fictif, mutation="uuid-provenance-fictif")
    assert admission.status_code == 303
    lot_id = _lot_id(admission.headers["location"])
    lecture = fusion_pdf.lire_avec_provenance(stockage.transaction, OWNER, lot_id)
    malforme = "a" * 36
    lot = {**lecture["lot"], "lot_id": malforme}
    trace = {**lecture["provenance"], "lot_id": malforme,
             "reference_locale": f"opsys-ingestion://m05-financecore/pdf/lots/{malforme}"}
    avant = _instantane_pdf_et_memoire()
    with pytest.raises(fusion_pdf.FusionPDFErreur) as refus:
        fusion_pdf_ui._provenance(lot, trace)
    assert refus.value.code == "PDF_PROVENANCE_INDISPONIBLE" and refus.value.statut_http == 503
    assert _instantane_pdf_et_memoire() == avant
