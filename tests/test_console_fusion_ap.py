"""Parcours privé de revue AP avec un PDF et des valeurs fictifs."""

from __future__ import annotations

import base64
import concurrent.futures
import io
import re
import threading
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, update

from opsys import fusion_ap, fusion_pdf, identite, stockage
from opsys.console import application, securite
from opsys.console.securite import Configuration
from opsys.stockage.schema import (
    FUSION_AP_BROUILLONS,
    FUSION_AP_COMMANDES,
    FUSION_LOTS,
    FUSION_PDF_LOTS,
    REGISTRES,
)

_PREFIXE = "/opsys"
_SECRET = "secret-console-ap-ui-fictif-" + "x" * 32
_MOT_DE_PASSE = "mot-de-passe-ap-ui-fictif-1234"
_CLE = base64.b64encode(b"v" * 32).decode("ascii")
_ADMIN = "admin-ap-ui-fictif"
_EMPLOYEE = "employe-ap-ui-fictif"
_MARQUEUR = "<img src=x onerror=alert(1)>"


def _pdf_fictif() -> bytes:
    sortie = io.BytesIO()
    document = canvas.Canvas(sortie, invariant=1)
    document.drawString(40, 760, "FOURNISSEUR EXEMPLE FICTIF")
    document.drawString(40, 730, "Facture no: AP-UI-2042")
    document.drawString(40, 700, "Total imprimé: 114.98 CAD")
    document.showPage()
    document.save()
    return sortie.getvalue()


@pytest.fixture
def client_ap(session, nathan, monkeypatch):
    monkeypatch.delenv("OPSYS_DATABASE_URL", raising=False)
    monkeypatch.setenv("OPSYS_INGESTION_CLE", _CLE)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, _ADMIN, "Admin fictif", _MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, _EMPLOYEE, "Employé fictif", _MOT_DE_PASSE, ["employee"])
    app = application.creer_application(Configuration(_SECRET, cookie_securise=False), cnx_factory=stockage.transaction)
    with TestClient(app, base_url=f"http://testserver{_PREFIXE}", raise_server_exceptions=False) as client:
        _connecter(client, nathan)
        yield client


def _connecter(client: TestClient, utilisateur: str) -> str:
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, utilisateur)
    assert personne is not None
    session = securite.ouvrir_session(utilisateur, personne.roles, 3600)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, _SECRET), path=_PREFIXE)
    return session.csrf


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def _lot_ap(client: TestClient) -> tuple[str, int]:
    lot = fusion_pdf.creer(
        stockage.transaction,
        "nathan",
        mutation_id="ap-ui-pdf-fictif-1",
        pdf_octets=_pdf_fictif(),
    )
    extrait = fusion_pdf.preparer(stockage.transaction, "nathan", lot["lot_id"], lot["revision"])
    assert extrait["statut"] == "EXTRAIT_PREPARATOIRE"
    return lot["lot_id"], extrait["revision"]


def _reference(html: str, champ: str) -> str:
    bloc = re.search(rf'<select name="citation\.{re.escape(champ)}\.1">(.*?)</select>', html)
    assert bloc
    values = re.findall(r'<option value="([^"]*)"[^>]*>', bloc.group(1))
    references = [value for value in values if value]
    assert references
    return references[0]


def _data_enregistrement(html: str, *, revision_pdf: int, revision_ap: int, mutation: str) -> dict[str, str]:
    csrf = _csrf(html)
    fields = {
        "csrf": csrf,
        "mutation_id": mutation,
        "revision_pdf": str(revision_pdf),
        "revision_ap": str(revision_ap),
    }
    for champ in (
        "fournisseur",
        "numero",
        "date",
        "po",
        "sous_total_imprime",
        "taxe_imprimee",
        "total_imprime",
        "devise",
    ):
        fields[f"champ.{champ}"] = ""
        for index in range(1, 4):
            fields[f"citation.{champ}.{index}"] = ""
    fields["champ.fournisseur"] = _MARQUEUR
    fields["champ.numero"] = "AP-UI-2042"
    fields["citation.fournisseur.1"] = _reference(html, "fournisseur")
    fields["citation.numero.1"] = _reference(html, "numero")
    return fields


def _sauver(client: TestClient, lot_id: str, pdf_revision: int, ap_revision: int = 0, mutation="ap-ui-save-1"):
    page = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200
    return client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/enregistrer",
        data=_data_enregistrement(page.text, revision_pdf=pdf_revision, revision_ap=ap_revision, mutation=mutation),
        follow_redirects=False,
    )


def test_revue_ap_privee_ne_lit_pas_sur_get_et_echappe_apres_post(client_ap):
    client = client_ap
    lot_id, revision_pdf = _lot_ap(client)
    detail = client.get(f"/fusion/pdf/lots/{lot_id}")
    assert detail.status_code == 200 and f"/fusion/pdf/lots/{lot_id}/ap" in detail.text

    vierge = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert vierge.status_code == 200 and "private" in vierge.headers["cache-control"]
    assert "Aucun brouillon AP" in vierge.text and _MARQUEUR not in vierge.text
    assert "Afficher les champs enregistrés" not in vierge.text

    saved = client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/enregistrer",
        data=_data_enregistrement(vierge.text, revision_pdf=revision_pdf, revision_ap=0, mutation="ap-ui-save-1"),
        follow_redirects=False,
    )
    assert saved.status_code == 303
    meta = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert meta.status_code == 200 and "A_REVOIR" in meta.text and _MARQUEUR not in meta.text

    read = client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/lire",
        data={"csrf": _csrf(meta.text), "revision_pdf": str(revision_pdf), "revision_ap": "1"},
    )
    assert read.status_code == 200 and read.headers["cache-control"] == "private, no-store, max-age=0"
    assert _MARQUEUR not in read.text and "&lt;img src=x onerror=alert(1)&gt;" in read.text
    again = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert again.status_code == 200 and _MARQUEUR not in again.text
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 1


def test_boite_ap_bornee_privee_lie_a_revue_sans_clair_ni_ecriture(client_ap, monkeypatch):
    lot_id, revision_pdf = _lot_ap(client_ap)
    assert _sauver(client_ap, lot_id, revision_pdf, mutation="ap-ui-inbox-save").status_code == 303
    before = client_ap.get("/fusion/pdf/lots/" + lot_id + "/ap")
    assert before.status_code == 200
    with stockage.transaction() as cnx:
        avant = (
            cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
        )

    monkeypatch.setattr(fusion_ap, "_dechiffrer", lambda *_: pytest.fail("boîte AP a déchiffré"))
    response = client_ap.get("/fusion/pdf/ap/a-revoir")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "À rouvrir et revalider" in response.text
    assert f"/fusion/pdf/lots/{lot_id}/ap" in response.text
    for secret in (_MARQUEUR, "AP-UI-2042", "source_sha256", "proposition_cipher", _CLE):
        assert secret not in response.text
    with stockage.transaction() as cnx:
        apres = (
            cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
        )
    assert apres == avant


def test_boite_ap_indique_source_perimee_et_revalide_au_clic(client_ap):
    lot_id, revision_pdf = _lot_ap(client_ap)
    assert _sauver(client_ap, lot_id, revision_pdf, mutation="ap-ui-inbox-stale").status_code == 303
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id).values(revision=revision_pdf + 1))
    inbox = client_ap.get("/fusion/pdf/ap/a-revoir")
    assert inbox.status_code == 200 and "Indisponible — à revalider" in inbox.text
    assert f"/fusion/pdf/lots/{lot_id}/ap" in inbox.text
    detail = client_ap.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert detail.status_code == 409 and "BROUILLON_OBSOLETE" in detail.text


def test_boite_ap_refuse_query_et_role_revoque_apres_lecture(client_ap, monkeypatch):
    original = fusion_ap.lister_a_revoir
    monkeypatch.setattr(fusion_ap, "lister_a_revoir", lambda *_args, **_kwargs: pytest.fail("query avant validation"))
    assert client_ap.get("/fusion/pdf/ap/a-revoir?x=1").status_code == 400

    _connecter(client_ap, _EMPLOYEE)
    assert client_ap.get("/fusion/pdf/ap/a-revoir").status_code == 403
    _connecter(client_ap, "nathan")
    monkeypatch.setattr(fusion_ap, "lister_a_revoir", original)

    def lire_puis_revoquer(*args, **kwargs):
        result = original(*args, **kwargs)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        return result

    monkeypatch.setattr(fusion_ap, "lister_a_revoir", lire_puis_revoquer)
    response = client_ap.get("/fusion/pdf/ap/a-revoir")
    assert response.status_code == 403
    assert "Brouillons AP" not in response.text


def test_formulaire_refuse_csrf_doublon_taille_et_reference_forgee_sans_ecriture(client_ap):
    client = client_ap
    lot_id, revision_pdf = _lot_ap(client)
    page = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    csrf = _csrf(page.text)
    lire_url = f"/fusion/pdf/lots/{lot_id}/ap/lire"
    absent = client.post(lire_url, data={"csrf": "mauvais", "revision_pdf": str(revision_pdf), "revision_ap": "0"})
    assert absent.status_code == 403
    json_body = client.post(
        lire_url,
        json={"csrf": csrf, "revision_pdf": revision_pdf, "revision_ap": 0},
    )
    assert json_body.status_code == 415
    duplicate = client.post(
        lire_url,
        content=urlencode(
            [
                ("csrf", csrf),
                ("csrf", csrf),
                ("revision_pdf", str(revision_pdf)),
                ("revision_ap", "0"),
            ]
        ),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert duplicate.status_code == 400
    large = client.post(
        lire_url,
        content=b"a" * 16_385,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert large.status_code == 413
    mauvais_utf8 = client.post(
        lire_url,
        content=f"csrf={csrf}&revision_pdf={revision_pdf}&revision_ap=%FF",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert mauvais_utf8.status_code == 400

    invalid = _data_enregistrement(page.text, revision_pdf=revision_pdf, revision_ap=0, mutation="ap-ui-forged-ref")
    invalid["citation.fournisseur.1"] = "1:p99-f1"
    forged = client.post(f"/fusion/pdf/lots/{lot_id}/ap/enregistrer", data=invalid)
    assert forged.status_code == 400
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0


@pytest.mark.parametrize("sequence", ["%ZZ", "%", "%0"])
def test_percent_malforme_refuse_sans_brouillon_ap(client_ap, sequence):
    client = client_ap
    lot_id, revision_pdf = _lot_ap(client)
    page = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    fields = _data_enregistrement(page.text, revision_pdf=revision_pdf, revision_ap=0, mutation="ap-ui-percent-fictif")
    fields["champ.numero"] = "sentinelle"
    body = urlencode(fields).replace("champ.numero=sentinelle", "champ.numero=" + sequence)
    response = client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/enregistrer",
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0


def test_revision_stale_et_role_revoque_apres_dechiffrement_ne_rendent_pas_de_clair(client_ap, monkeypatch):
    client = client_ap
    lot_id, revision_pdf = _lot_ap(client)
    saved = _sauver(client, lot_id, revision_pdf, mutation="ap-ui-first")
    assert saved.status_code == 303
    meta = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    first = client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/lire",
        data={"csrf": _csrf(meta.text), "revision_pdf": str(revision_pdf), "revision_ap": "1"},
    )
    updated = _data_enregistrement(first.text, revision_pdf=revision_pdf, revision_ap=1, mutation="ap-ui-update-a")
    updated["champ.fournisseur"] = "FOURNISSEUR CORRIGÉ FICTIF"
    changed = client.post(f"/fusion/pdf/lots/{lot_id}/ap/enregistrer", data=updated, follow_redirects=False)
    assert changed.status_code == 303, changed.text
    stale = dict(updated)
    stale["mutation_id"] = "ap-ui-update-stale"
    stale["champ.fournisseur"] = "STALE FICTIF"
    conflict = client.post(f"/fusion/pdf/lots/{lot_id}/ap/enregistrer", data=stale)
    assert conflict.status_code == 409 and "CONFLIT_REVISION" in conflict.text
    assert "STALE FICTIF" not in conflict.text

    _connecter(client, _ADMIN)
    admin_meta = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    lire_original = fusion_ap.lire_revue_privee

    def lire_puis_revoquer(*args, **kwargs):
        resultat = lire_original(*args, **kwargs)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, _ADMIN, "admin")
        return resultat

    monkeypatch.setattr(fusion_ap, "lire_revue_privee", lire_puis_revoquer)
    refused = client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/lire",
        data={"csrf": _csrf(admin_meta.text), "revision_pdf": str(revision_pdf), "revision_ap": "2"},
    )
    assert refused.status_code == 403 and _MARQUEUR not in refused.text


def test_lecture_atomique_associe_champs_et_revision_pendant_modification_concurrente(client_ap):
    lot_id, revision_pdf = _lot_ap(client_ap)
    assert _sauver(client_ap, lot_id, revision_pdf, mutation="ap-ui-atomic-first").status_code == 303
    resultat = fusion_pdf.lire_resultat(stockage.transaction, "nathan", lot_id)
    fragment = resultat["pages"][0]["fragments"][0]
    reference = {"page": 1, "fragment_id": fragment["id"], "fragment_sha256": fragment["sha256"]}
    proposition = {
        "schema_version": 1,
        "champs": {
            "fournisseur": "VALEUR CONCURRENTE FICTIVE",
            "numero": "AP-UI-2042",
            "date": "",
            "po": "",
            "sous_total_imprime": "",
            "taxe_imprimee": "",
            "total_imprime": "",
            "devise": "",
        },
        "citations": {"fournisseur": [reference], "numero": [reference]},
    }
    depart = threading.Barrier(2)

    def lire():
        depart.wait(timeout=5)
        return fusion_ap.lire_revue_privee(stockage.transaction, "nathan", lot_id)

    def modifier():
        depart.wait(timeout=5)
        return fusion_ap.enregistrer(
            stockage.transaction,
            "nathan",
            lot_id,
            mutation_id="ap-ui-atomic-second",
            revision_pdf_attendue=revision_pdf,
            revision_attendue=1,
            proposition=proposition,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        lecture_future = pool.submit(lire)
        ecriture_future = pool.submit(modifier)
        lecture = lecture_future.result(timeout=10)
        ecriture_future.result(timeout=10)
    paire = (lecture["brouillon"]["revision"], lecture["proposition"]["champs"]["fournisseur"])
    assert paire in {(1, _MARQUEUR), (2, "VALEUR CONCURRENTE FICTIVE")}


def test_employe_cle_absente_et_cipher_corrompu_ne_peuvent_lire_les_champs(client_ap, monkeypatch):
    client = client_ap
    lot_id, revision_pdf = _lot_ap(client)
    assert _sauver(client, lot_id, revision_pdf, mutation="ap-ui-protected").status_code == 303
    meta = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    body = {"csrf": _csrf(meta.text), "revision_pdf": str(revision_pdf), "revision_ap": "1"}

    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    no_key = client.post(f"/fusion/pdf/lots/{lot_id}/ap/lire", data=body)
    assert no_key.status_code == 503 and "CLE_INDISPONIBLE" in no_key.text
    assert _MARQUEUR not in no_key.text
    monkeypatch.setenv("OPSYS_INGESTION_CLE", _CLE)
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FUSION_AP_BROUILLONS)
            .where(FUSION_AP_BROUILLONS.c.lot_id == lot_id)
            .values(proposition_cipher="corruption-fictive")
        )
    corrupt = client.post(f"/fusion/pdf/lots/{lot_id}/ap/lire", data=body)
    assert corrupt.status_code == 409 and "CIPHER_INVALIDE" in corrupt.text
    assert _MARQUEUR not in corrupt.text
    _connecter(client, _EMPLOYEE)
    denied = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert denied.status_code == 403 and _MARQUEUR not in denied.text


def test_role_revoque_pendant_rendu_ne_recoit_pas_le_html_dechiffre(client_ap, monkeypatch):
    client = client_ap
    lot_id, revision_pdf = _lot_ap(client)
    assert _sauver(client, lot_id, revision_pdf, mutation="ap-ui-render-revoke").status_code == 303
    page = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    from opsys.console import fusion_ap_ui

    editeur_original = fusion_ap_ui._editeur

    def editeur_puis_revoquer(*args, **kwargs):
        contenu = editeur_original(*args, **kwargs)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        return contenu

    monkeypatch.setattr(fusion_ap_ui, "_editeur", editeur_puis_revoquer)
    refuse = client.post(
        f"/fusion/pdf/lots/{lot_id}/ap/lire",
        data={"csrf": _csrf(page.text), "revision_pdf": str(revision_pdf), "revision_ap": "1"},
    )
    assert refuse.status_code == 403 and _MARQUEUR not in refuse.text
