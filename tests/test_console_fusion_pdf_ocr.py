"""Parcours privé de revue OCR; services SQLite/AES réels, inférence seulement simulée."""
from __future__ import annotations

import base64
import importlib.util
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from opsys import fusion_ap, fusion_pdf, fusion_pdf_ocr, identite, stockage
from opsys.console import fusion_ap_ui, fusion_pdf_ocr_ui, securite
from opsys.departements import charger_departements
from opsys.ocr_runtime import contexte_ocr
from opsys.stockage.schema import (
    APPROBATIONS,
    FUSION_AP_BROUILLONS,
    FUSION_AP_COMMANDES,
    FUSION_AP_OCR_SOURCES,
    FUSION_AP_SAISIES,
    FUSION_PDF_LOTS,
    FUSION_PDF_OCR_RUNS,
    META,
    REGISTRES,
)

SECRET = "secret-console-ocr-fictif-" + "x" * 32
PASSWORD = "mot-de-passe-console-ocr-fictif"
OWNER = "nathan"
ADMIN = "admin-console-ocr-fictif"
EMPLOYEE = "employe-console-ocr-fictif"
PREFIX = "/opsys"
KEY = base64.b64encode(b"o" * 32).decode("ascii")
CANARY = "<script>OCR-XSS-CANARY</script>"
_M5_SPEC = importlib.util.spec_from_file_location(
    "fixture_console_ocr_m5", Path(__file__).with_name("test_fusion_ap_m5.py"),
)
assert _M5_SPEC is not None and _M5_SPEC.loader is not None
_M5 = importlib.util.module_from_spec(_M5_SPEC)
_M5_SPEC.loader.exec_module(_M5)


@pytest.fixture(autouse=True)
def sqlite_fictive_uniquement(opsys_home, monkeypatch):
    opsys_home.mkdir(parents=True)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{opsys_home / 'console-ocr.db'}")
    monkeypatch.setenv("OPSYS_INGESTION_CLE", KEY)


def _session_page(request: Request) -> securite.Session:
    session = securite.lire_session(request.cookies.get(securite.NOM_COOKIE), SECRET)
    if session is None:
        raise HTTPException(401, "authentification requise")
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None:
        raise HTTPException(401, "authentification requise")
    session = replace(session, roles=personne.roles)
    if not personne.roles.intersection({"nathan_owner", "admin"}):
        raise HTTPException(403, "administration requise")
    return session


def _candidat(source: bytes, *, lot_id: str, revision_source: int, bundle: Path):
    contexte = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
    return {
        "schema_version": 1, "genre": "m5.ocr_scan_candidat", "statut": "CANDIDAT_A_REVOIR",
        "lot_id": contexte.lot_id, "source_sha256": contexte.source_sha256,
        "revision_source": contexte.revision_source, "configuration_sha256": contexte.configuration_sha256,
        "profil": {"rasteriseur": contexte.rasteriseur, "moteur": contexte.moteur,
                    "leptonica": contexte.leptonica, "pdfium_sha256": contexte.pdfium_sha256,
                    "modele_sha256": contexte.modele_sha256, "langue": "fra"},
        "page": {"numero": 1, "largeur_px": 100, "hauteur_px": 100, "tokens": [{
            "texte": CANARY, "x0": 1, "y0": 1, "x1": 40, "y1": 10, "confiance_brute": 80,
        }]},
    }


@pytest.fixture
def moteur_ocr_fictif(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle-administrateur-fictif"
    bundle.mkdir()
    monkeypatch.setattr(fusion_pdf_ocr, "valider_bundle", lambda _path: {"rasterizer/fictif": "0" * 64})
    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", _candidat)
    return bundle


@pytest.fixture
def client_ocr(monkeypatch, moteur_ocr_fictif, nathan):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN, "Administrateur OCR fictif", PASSWORD, ["admin"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé OCR fictif", PASSWORD, ["employee"])
    app = FastAPI(root_path=PREFIX)
    app.include_router(fusion_pdf_ocr_ui.creer_router(
        session_page=_session_page, prefixe=PREFIX, cnx_factory=stockage.transaction,
        bundle_ocr=moteur_ocr_fictif,
    ))
    app.include_router(fusion_ap_ui.creer_router(
        session_page=_session_page, prefixe=PREFIX, cnx_factory=stockage.transaction,
        deps=charger_departements(),
    ))
    with TestClient(app, base_url=f"http://testserver{PREFIX}", raise_server_exceptions=False) as client:
        _connecter(client, OWNER)
        yield client


def _connecter(client, utilisateur: str) -> str:
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, utilisateur)
    assert personne is not None
    session = securite.ouvrir_session(utilisateur, personne.roles, 3600)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, SECRET), path=PREFIX)
    return session.csrf


def _lot_refuse(acteur: str, mutation: str = "admission-ocr-console-fictive"):
    source = f"%PDF-1.7\n% fixture OCR console {mutation}\n%%EOF\n".encode()
    lot = fusion_pdf.creer(stockage.transaction, acteur, mutation_id=mutation, pdf_octets=source)
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot["lot_id"]).values(
            statut="REFUSE", code="PDF_IMAGE_OU_MIXTE", revision=2,
        ))
    return lot


def _lire_run():
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one())


def _csrf(response) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def _poster(client, lot_id: str, csrf: str, **extras):
    return client.post(f"/fusion/pdf/lots/{lot_id}/ocr", data={
        "csrf": csrf, "revision_source": "2", "mutation_id": "ocr-console-mutation-fictive", **extras,
    }, follow_redirects=False)


def _donnees_ap(revision_ap: int, csrf: str, mutation: str) -> dict[str, str]:
    champs = (
        "fournisseur", "numero", "date", "po", "sous_total_imprime", "taxe_imprimee",
        "total_imprime", "devise",
    )
    fields = {
        "csrf": csrf, "mutation_id": mutation, "revision_pdf": "2", "revision_ap": str(revision_ap),
    }
    for champ in champs:
        fields[f"champ.{champ}"] = ""
        for index in range(1, 4):
            fields[f"citation.{champ}.{index}"] = ""
    return fields


def _creer_ap(client, lot_id: str, run: dict, csrf: str, mutation: str):
    return client.post(f"/fusion/pdf/lots/{lot_id}/ocr/{run['ocr_run_id']}/ap/creer", data={
        "csrf": csrf, "revision_source": "2", "revision_run": str(run["revision_run"]),
        "mutation_id": mutation,
    }, follow_redirects=False)


def test_ap_ocr_post_cree_vide_puis_saisie_citee_et_m5_disponible(client_ocr):
    lot = _lot_refuse(OWNER, "admission-ocr-ap-parcours")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    candidate_page = client_ocr.get(
        f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1",
    )
    assert candidate_page.status_code == 200
    assert "Token 0" in candidate_page.text and "80 / 100, non calibrée" in candidate_page.text
    assert "&lt;script&gt;OCR-XSS-CANARY&lt;/script&gt;" in candidate_page.text
    assert "<script>OCR-XSS-CANARY</script>" not in candidate_page.text
    assert "Créer un brouillon AP vide" in candidate_page.text

    created = _creer_ap(client_ocr, lot["lot_id"], run, csrf, "ap-ocr-create-ui")
    assert created.status_code == 303 and "/ap/ocr/" in created.headers["location"]
    editor = client_ocr.get(created.headers["location"].removeprefix(PREFIX))
    assert editor.status_code == 200 and "Total imprimé" in editor.text
    assert f'/fusion/pdf/lots/{lot["lot_id"]}/ap/verifier-m5' in editor.text
    for field in (
        "fournisseur", "numero", "date", "po", "sous_total_imprime", "taxe_imprimee",
        "total_imprime", "devise",
    ):
        assert f'name="champ.{field}" maxlength="128" value=""' in editor.text

    fields = _donnees_ap(1, _csrf(editor), "ap-ocr-save-ui")
    fields["champ.fournisseur"] = CANARY
    fields["champ.numero"] = "AP-UI-2042"
    fields["citation.fournisseur.1"] = "0"
    fields["citation.numero.1"] = "0"
    hors_source = dict(fields)
    hors_source["citation.fournisseur.1"] = "1"
    refuse = client_ocr.post(
        f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}/enregistrer",
        data=hors_source, follow_redirects=False,
    )
    assert refuse.status_code == 400
    saved = client_ocr.post(
        f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}/enregistrer",
        data=fields, follow_redirects=False,
    )
    assert saved.status_code == 303
    replay_save = client_ocr.post(
        f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}/enregistrer",
        data=fields, follow_redirects=False,
    )
    assert replay_save.status_code == 303
    after = client_ocr.get(saved.headers["location"].removeprefix(PREFIX))
    assert after.status_code == 200 and "&lt;script&gt;OCR-XSS-CANARY&lt;/script&gt;" in after.text
    assert '<input name="champ.total_imprime" maxlength="128" value="">' in after.text
    assert "<script>OCR-XSS-CANARY</script>" not in after.text
    proposition = fusion_ap.lire_champs(stockage.transaction, OWNER, lot["lot_id"])
    citation = proposition["citations"]["fournisseur"][0]
    assert citation["page"] == 1 and citation["token_index"] == 0 and len(citation["token_sha256"]) == 64
    with stockage.transaction() as cnx:
        draft = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        source = cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one()
        assert draft["statut"] == "A_REVOIR" and draft["revision"] == 2
        assert source["ocr_run_id"] == run["ocr_run_id"]
        assert len(cnx.execute(select(FUSION_AP_COMMANDES)).all()) == 2


def _preparer_parcours_m5_ui(request, client, monkeypatch, tmp_path, bundle, mutation):
    assert bundle.is_dir()
    _M5.ap_m5.__wrapped__(request.getfixturevalue("nathan"), monkeypatch, tmp_path)
    textes = [
        "fournisseur-fictif", "FICTIF-2042", "2026-10-01", "PO-FICTIF-7",
        "100.00", "14.98", "114.98", "CAD",
    ]

    def candidat(source, *, lot_id, revision_source, bundle):
        contexte = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
        tokens = [{
            "texte": texte, "x0": 1 + index * 10, "y0": 1, "x1": 9 + index * 10,
            "y1": 10, "confiance_brute": 91,
        } for index, texte in enumerate(textes)]
        return {
            "schema_version": 1, "genre": "m5.ocr_scan_candidat", "statut": "CANDIDAT_A_REVOIR",
            "lot_id": contexte.lot_id, "source_sha256": contexte.source_sha256,
            "revision_source": contexte.revision_source,
            "configuration_sha256": contexte.configuration_sha256,
            "profil": {
                "rasteriseur": contexte.rasteriseur, "moteur": contexte.moteur,
                "leptonica": contexte.leptonica, "pdfium_sha256": contexte.pdfium_sha256,
                "modele_sha256": contexte.modele_sha256, "langue": "fra",
            },
            "page": {"numero": 1, "largeur_px": 100, "hauteur_px": 100, "tokens": tokens},
        }

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", candidat)
    lot = _lot_refuse(OWNER, mutation)
    csrf = _connecter(client, OWNER)
    assert _poster(client, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert _creer_ap(client, lot["lot_id"], run, csrf, mutation + "-create").status_code == 303
    editor = client.get(f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}")
    assert editor.status_code == 200
    fields = _donnees_ap(1, _csrf(editor), mutation + "-save")
    for champ, valeur in zip(
        ("fournisseur", "numero", "date", "po", "sous_total_imprime", "taxe_imprimee",
         "total_imprime", "devise"), textes, strict=True,
    ):
        fields[f"champ.{champ}"] = valeur
        fields[f"citation.{champ}.1"] = str(textes.index(valeur))
    saved = client.post(
        f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}/enregistrer",
        data=fields, follow_redirects=False,
    )
    assert saved.status_code == 303
    editor = client.get(saved.headers["location"].removeprefix(PREFIX))
    assert editor.status_code == 200 and "/ap/verifier-m5\"" in editor.text
    return lot, run, editor


def _confirmation_m5(html: str, *, csrf: str, mutation: str) -> dict[str, str]:
    snapshot = re.search(r'name="snapshot_attendu" value="([0-9a-f]{64})"', html)
    assert snapshot
    return {
        "csrf": csrf, "revision_pdf": "2", "revision_ap": "2", "po_id": "PO-FICTIF-7",
        "fournisseur_id": "fournisseur-fictif", "correspondance_confirmee": "oui",
        "saisie_confirmee": "oui", "snapshot_attendu": snapshot.group(1), "mutation_id": mutation,
    }


def _nombre_saisies_m5() -> int:
    with stockage.transaction() as cnx:
        return len(cnx.execute(select(REGISTRES.c.rang).where(
            (REGISTRES.c.departement == "m05-financecore")
            & (REGISTRES.c.registre == "comptes_a_payer")
        )).all())


def _compteurs_saisie_et_approbation() -> tuple[int, int]:
    with stockage.transaction() as cnx:
        return (
            len(cnx.execute(select(FUSION_AP_SAISIES.c.lot_id)).all()),
            len(cnx.execute(select(APPROBATIONS.c.id)).all()),
        )


def test_parcours_console_ocr_m5_verification_pure_n3_reference_et_rejeu(
    request, client_ocr, moteur_ocr_fictif, monkeypatch, tmp_path,
):
    lot, run, editor = _preparer_parcours_m5_ui(
        request, client_ocr, monkeypatch, tmp_path, moteur_ocr_fictif, "parcours-m5-ocr-ui-fictif",
    )
    before = _nombre_saisies_m5()
    before_liaisons = _compteurs_saisie_et_approbation()
    verification = client_ocr.post(f"/fusion/pdf/lots/{lot['lot_id']}/ap/verifier-m5", data={
        "csrf": _csrf(editor), "revision_pdf": "2", "revision_ap": "2", "po_id": "PO-FICTIF-7",
        "fournisseur_id": "fournisseur-fictif", "correspondance_confirmee": "oui",
    })
    assert verification.status_code == 200
    assert f"OCR_CANDIDAT — candidat {run['ocr_run_id']} révision {run['revision_run']}" in verification.text
    assert "aucune facture, dette, approbation ni paiement créé" in verification.text
    assert _nombre_saisies_m5() == before
    assert _compteurs_saisie_et_approbation() == before_liaisons

    confirmation = _confirmation_m5(
        verification.text, csrf=_csrf(verification), mutation="a" * 32,
    )
    saved = client_ocr.post(f"/fusion/pdf/lots/{lot['lot_id']}/ap/saisir-m5", data=confirmation)
    assert saved.status_code == 200 and "Rejeu idempotent : non" in saved.text
    assert _nombre_saisies_m5() == before + 1
    with stockage.transaction() as cnx:
        liaison = cnx.execute(select(FUSION_AP_SAISIES).where(
            FUSION_AP_SAISIES.c.lot_id == lot["lot_id"],
        )).mappings().one()
        approval = cnx.execute(select(APPROBATIONS).where(
            APPROBATIONS.c.id == liaison["approbation_id"],
        )).mappings().one()
        draft = cnx.execute(select(FUSION_AP_BROUILLONS).where(
            FUSION_AP_BROUILLONS.c.lot_id == lot["lot_id"],
        )).mappings().one()
    assert approval["niveau"] == "N3" and approval["statut"] == "executee"
    assert draft["statut"] == "A_REVOIR"
    preuve = json.loads(liaison["preuve_json"])
    assert preuve["source"]["source_type"] == "OCR_CANDIDAT"
    assert preuve["source"]["ocr_run_id"] == run["ocr_run_id"]
    assert "Aucun paiement n’a été lancé" in saved.text

    replay = client_ocr.post(f"/fusion/pdf/lots/{lot['lot_id']}/ap/saisir-m5", data=confirmation)
    assert replay.status_code == 200 and "Rejeu idempotent : oui" in replay.text
    assert _nombre_saisies_m5() == before + 1
    after = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}")
    assert after.status_code == 200 and "Référence de saisie M5" in after.text
    assert "/ap/verifier-m5\"" not in after.text


@pytest.mark.parametrize("alteration", ["pdf_perime", "revision_aad_corrompue"])
def test_parcours_console_ocr_m5_source_alteree_avant_confirmation_n3_refuse_sans_append(
    request, client_ocr, moteur_ocr_fictif, monkeypatch, tmp_path, alteration,
):
    lot, run, editor = _preparer_parcours_m5_ui(
        request, client_ocr, monkeypatch, tmp_path, moteur_ocr_fictif, "parcours-m5-ocr-stale-fictif",
    )
    verification = client_ocr.post(f"/fusion/pdf/lots/{lot['lot_id']}/ap/verifier-m5", data={
        "csrf": _csrf(editor), "revision_pdf": "2", "revision_ap": "2", "po_id": "PO-FICTIF-7",
        "fournisseur_id": "fournisseur-fictif", "correspondance_confirmee": "oui",
    })
    assert verification.status_code == 200
    confirmation = _confirmation_m5(
        verification.text, csrf=_csrf(verification), mutation="b" * 32,
    )
    with stockage.transaction() as cnx:
        if alteration == "pdf_perime":
            cnx.execute(update(FUSION_PDF_LOTS).where(
                FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
            ).values(revision=FUSION_PDF_LOTS.c.revision + 1))
        else:
            # La révision du run est dans l'AAD : l'altérer sans rechiffrer
            # invalide le candidat; ce n'est pas un nouveau run OCR valide.
            cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
                FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
            ).values(revision_run=FUSION_PDF_OCR_RUNS.c.revision_run + 1))
    before_saisies = _nombre_saisies_m5()
    before_liaisons = _compteurs_saisie_et_approbation()
    refused = client_ocr.post(f"/fusion/pdf/lots/{lot['lot_id']}/ap/saisir-m5", data=confirmation)
    status, code = ((409, "OCR_RESULTAT_INDISPONIBLE") if alteration == "pdf_perime"
                    else (503, "OCR_RESULTAT_CORROMPU"))
    assert refused.status_code == status and code in refused.text, refused.text
    assert _nombre_saisies_m5() == before_saisies
    assert _compteurs_saisie_et_approbation() == before_liaisons


def test_boite_ap_ocr_lie_au_run_et_marque_run_perime(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER, "liste-ap-ocr-lien-fictif")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert _creer_ap(client_ocr, lot["lot_id"], run, csrf, "liste-ap-ocr-brouillon-fictif").status_code == 303
    lien = f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}"
    with monkeypatch.context() as no_decrypt:
        no_decrypt.setattr(fusion_ap, "_dechiffrer", lambda *_: pytest.fail("liste OCR a déchiffré"))
        inbox = client_ocr.get("/fusion/pdf/ap/a-revoir")
    assert inbox.status_code == 200 and lien in inbox.text
    assert CANARY not in inbox.text and "proposition_cipher" not in inbox.text
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
            FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
        ).values(revision_run=FUSION_PDF_OCR_RUNS.c.revision_run + 1))
    stale = client_ocr.get("/fusion/pdf/ap/a-revoir")
    assert stale.status_code == 200 and "Indisponible — à revalider" in stale.text and lien in stale.text
    detail = client_ocr.get(lien)
    assert detail.status_code == 503 and "OCR_RESULTAT_CORROMPU" in detail.text
    assert CANARY not in detail.text


@pytest.mark.parametrize("revocation", ["reference", "relecture"])
def test_revue_ocr_ne_rend_pas_reference_m5_apres_retrait_finance(
    client_ocr, monkeypatch, revocation,
):
    lot = _lot_refuse(OWNER, f"ocr-reference-finance-{revocation}")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert _creer_ap(client_ocr, lot["lot_id"], run, csrf, f"ap-reference-finance-{revocation}").status_code == 303

    acteur = "admin-finance-ap-ocr-fictif"
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, acteur, "Admin finance fictif", PASSWORD, ["admin", "finance"])
    _connecter(client_ocr, acteur)
    secret = "REFERENCE-M5-CONFIDENTIEL-CANARY"
    reference = {
        "facture_id": secret, "approbation_id": "APPROBATION-CANARY", "statut_m5": "SAISIE",
        "corrections": 0,
    }
    from opsys.console import fusion_ap_m5_reference

    def retirer_finance():
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, acteur, "finance")

    def lire_reference(*_args, **_kwargs):
        if revocation == "reference":
            retirer_finance()
        return reference

    monkeypatch.setattr(fusion_ap_m5_reference, "lire", lire_reference)
    if revocation == "relecture":
        original = fusion_ap.lire_revue_privee
        nombre = 0

        def lire_revue(*args, **kwargs):
            nonlocal nombre
            resultat = original(*args, **kwargs)
            nombre += 1
            if nombre == 2:
                retirer_finance()
            return resultat

        monkeypatch.setattr(fusion_ap, "lire_revue_privee", lire_revue)

    response = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}")
    assert response.status_code == 403
    assert secret not in response.text and "APPROBATION-CANARY" not in response.text


def test_ap_ocr_creation_csrf_role_run_autre_lot_rejeu_et_stale(client_ocr):
    lot = _lot_refuse(OWNER, "admission-ocr-ap-gardes")
    autre = _lot_refuse(OWNER, "admission-ocr-ap-autre-lot")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert _creer_ap(client_ocr, lot["lot_id"], run, "csrf-invalide", "ap-ocr-csrf").status_code == 403
    employee_csrf = _connecter(client_ocr, EMPLOYEE)
    assert _creer_ap(client_ocr, lot["lot_id"], run, employee_csrf, "ap-ocr-role").status_code == 403
    csrf = _connecter(client_ocr, OWNER)
    bad_lot = _creer_ap(client_ocr, autre["lot_id"], run, csrf, "ap-ocr-autre-lot")
    assert bad_lot.status_code == 409
    created = _creer_ap(client_ocr, lot["lot_id"], run, csrf, "ap-ocr-rejeu")
    assert created.status_code == 303
    replay = _creer_ap(client_ocr, lot["lot_id"], run, csrf, "ap-ocr-rejeu")
    assert replay.status_code == 303
    with stockage.transaction() as cnx:
        assert len(cnx.execute(select(FUSION_AP_BROUILLONS)).all()) == 1
        source = dict(cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one())
    assert source["ocr_run_id"] == run["ocr_run_id"]

    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).where(
            FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
        ).values(source_sha256="f" * 64))
    stale = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ap/ocr/{run['ocr_run_id']}")
    assert stale.status_code in {409, 503}
    retry = _creer_ap(client_ocr, lot["lot_id"], run, csrf, "ap-ocr-nouvelle-tentative")
    assert retry.status_code in {409, 503}
    with stockage.transaction() as cnx:
        source_apres = dict(cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one())
        assert source_apres == source
        assert len(cnx.execute(select(FUSION_AP_BROUILLONS)).all()) == 1


def test_action_seulement_lot_refuse_eligible_et_optin_actif(moteur_ocr_fictif):
    session = securite.ouvrir_session(OWNER, {"nathan_owner"}, 3600)
    lot = {"lot_id": "00000000-0000-4000-8000-000000000001", "statut": "REFUSE",
           "code": "PDF_IMAGE_OU_MIXTE", "revision": 2}
    form = fusion_pdf_ocr_ui.action_ocr(PREFIX, session, lot, actif=True)
    assert "/ocr\"" in form and 'name="revision_source" value="2"' in form
    assert 'name="mutation_id" value="' in form and f'name="csrf" value="{session.csrf}"' in form
    assert fusion_pdf_ocr_ui.action_ocr(PREFIX, session, lot, actif=False) == ""
    assert fusion_pdf_ocr_ui.action_ocr(PREFIX, session, {**lot, "code": "PDF_CHIFFRE"}, actif=True) == ""


def test_post_service_reel_puis_get_prive_pagine_et_sans_mutation(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER)
    # L'interface ne collecte aucune donnée de fournisseur ou de facture.
    panel = fusion_pdf_ocr_ui.action_ocr(
        PREFIX, securite.ouvrir_session(OWNER, {"nathan_owner"}, 3600),
        {**lot, "statut": "REFUSE", "code": "PDF_IMAGE_OU_MIXTE", "revision": 2}, actif=True,
    )
    assert "fournisseur" not in panel.lower() and "total_imprime" not in panel
    page = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/00000000-0000-4000-8000-000000000001?bloc=1")
    assert page.status_code == 404  # no OCR run yet
    csrf = _connecter(client_ocr, OWNER)
    posted = _poster(client_ocr, lot["lot_id"], csrf)
    assert posted.status_code == 303, posted.text
    run = _lire_run()
    assert run["statut"] == "A_REVOIR" and run["pdf_lot_id"] == lot["lot_id"]
    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("rejeu a relancé OCR"))
    replay = _poster(client_ocr, lot["lot_id"], csrf)
    assert replay.status_code == 303 and run["ocr_run_id"] in replay.headers["location"]
    with stockage.transaction() as cnx:
        assert len(cnx.execute(select(FUSION_PDF_OCR_RUNS)).all()) == 1
    with stockage.transaction() as cnx:
        avant = {table.name: tuple(tuple(row) for row in cnx.execute(select(table))) for table in META.sorted_tables}
    lu = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert lu.status_code == 200
    assert lu.headers["cache-control"] == "private, no-store, max-age=0"
    assert "Candidat OCR à vérifier" in lu.text and "Bloc 1" in lu.text
    assert "OCR-XSS-CANARY" in lu.text and "&lt;script&gt;" in lu.text
    assert "<script>OCR-XSS-CANARY</script>" not in lu.text
    assert run["source_sha256"] not in lu.text and run["cle_reference"] not in lu.text
    with stockage.transaction() as cnx:
        apres = {table.name: tuple(tuple(row) for row in cnx.execute(select(table))) for table in META.sorted_tables}
    assert apres == avant


def test_post_csrf_query_champs_duplicates_et_chemin_http_refuses_sans_ecriture(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER)
    csrf = _connecter(client_ocr, OWNER)
    monkeypatch.setattr(fusion_pdf_ocr, "preparer", lambda *_a, **_k: pytest.fail("préparer appelé"))
    assert _poster(client_ocr, lot["lot_id"], "csrf-invalid").status_code == 403
    assert client_ocr.post(f"/fusion/pdf/lots/{lot['lot_id']}/ocr?x=1", data={
        "csrf": csrf, "revision_source": "2", "mutation_id": "x",
    }).status_code == 400
    assert _poster(client_ocr, lot["lot_id"], csrf, bundle_ocr="/path/from/request").status_code == 400
    response = client_ocr.post(
        f"/fusion/pdf/lots/{lot['lot_id']}/ocr",
        content=f"csrf={csrf}&csrf={csrf}&revision_source=2&mutation_id=duplicate",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_PDF_OCR_RUNS)).all() == []


def test_bundle_off_par_defaut_et_ineligible_ne_lancent_pas_worker(monkeypatch, client_ocr):
    lot = _lot_refuse(OWNER, "admission-ocr-off-fictive")
    app = FastAPI(root_path=PREFIX)
    app.include_router(fusion_pdf_ocr_ui.creer_router(
        session_page=_session_page, prefixe=PREFIX, cnx_factory=stockage.transaction, bundle_ocr=None,
    ))
    with TestClient(app, base_url=f"http://testserver{PREFIX}", raise_server_exceptions=False) as off:
        csrf = _connecter(off, OWNER)
        assert fusion_pdf_ocr_ui.action_ocr(
            PREFIX, securite.ouvrir_session(OWNER, {"nathan_owner"}, 3600),
            {**lot, "statut": "REFUSE", "code": "PDF_IMAGE_OU_MIXTE", "revision": 2}, actif=False,
        ) == ""
        monkeypatch.setattr(fusion_pdf_ocr, "preparer", lambda *_a, **_k: pytest.fail("OCR opt-in off"))
        response = _poster(off, lot["lot_id"], csrf)
        assert response.status_code == 503
        assert "bundle" not in response.text.lower() and str(lot["lot_id"]) not in response.text


def test_run_autre_lot_query_strict_and_bad_run(client_ocr):
    lot = _lot_refuse(OWNER, "admission-ocr-assoc-a")
    autre = _lot_refuse(OWNER, "admission-ocr-assoc-b")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert lot["lot_id"] != autre["lot_id"] and run["pdf_lot_id"] == lot["lot_id"]
    response = client_ocr.get(f"/fusion/pdf/lots/{autre['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert response.status_code == 404
    assert client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1&bloc=1").status_code == 400
    assert client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?autre=1").status_code == 400
    bad_run = client_ocr.get(
        f"/fusion/pdf/lots/{lot['lot_id']}/ocr/00000000-0000-4000-8000-000000000099?bloc=1"
    )
    assert bad_run.status_code == 404


def test_candidat_129_tokens_128_par_bloc_sans_fuite_entre_pages(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER, "admission-ocr-pagination")

    def runtime_129(source, *, lot_id, revision_source, bundle):
        candidat = _candidat(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)
        modele = candidat["page"]["tokens"][0]
        candidat["page"]["tokens"] = [{**modele, "texte": f"token-{i}"} for i in range(129)]
        return candidat

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime_129)
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    with stockage.transaction() as cnx:
        avant = {table.name: tuple(tuple(row) for row in cnx.execute(select(table))) for table in META.sorted_tables}
    un = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    deux = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=2")
    assert un.status_code == deux.status_code == 200
    assert "token-127" in un.text and "token-128" not in un.text and "Bloc 1 sur 2" in un.text
    assert "token-128" in deux.text and "token-127" not in deux.text and "Bloc 2 sur 2" in deux.text
    assert client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=17").status_code == 400
    assert client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1&bloc=2").status_code == 400
    with stockage.transaction() as cnx:
        apres = {table.name: tuple(tuple(row) for row in cnx.execute(select(table))) for table in META.sorted_tables}
    assert apres == avant


def test_source_changee_entre_metadata_et_lecture_refuse_resultat(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER, "admission-ocr-source-change")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    original = fusion_pdf_ocr.lire_resultat

    def changer_revision_puis_lire(*args):
        with stockage.transaction() as cnx:
            cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot["lot_id"]).values(revision=3))
        return original(*args)

    monkeypatch.setattr(fusion_pdf_ocr, "lire_resultat", changer_revision_puis_lire)
    response = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert response.status_code == 409
    assert CANARY not in response.text and run["source_sha256"] not in response.text


def test_auth_owner_admin_only_and_role_retire_apres_worker_ou_get(client_ocr, moteur_ocr_fictif, monkeypatch):
    lot = _lot_refuse(OWNER, "admission-ocr-role-worker")
    _connecter(client_ocr, EMPLOYEE)
    employee_read = client_ocr.get(
        f"/fusion/pdf/lots/{lot['lot_id']}/ocr/00000000-0000-4000-8000-000000000099?bloc=1"
    )
    assert employee_read.status_code == 403
    _connecter(client_ocr, ADMIN)
    original = fusion_pdf_ocr.extraire_candidat

    def runtime_puis_retirer(source, *, lot_id, revision_source, bundle):
        candidat = original(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, ADMIN, "admin")
        return candidat

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime_puis_retirer)
    csrf = _connecter(client_ocr, ADMIN)
    response = _poster(client_ocr, lot["lot_id"], csrf)
    assert response.status_code == 403
    run = _lire_run()
    assert run["statut"] == "RESERVE"  # revocation before service commit cannot publish the candidate
    assert CANARY not in response.text


def test_retrait_role_apres_lecture_resultat_masque_candidat(client_ocr, moteur_ocr_fictif, monkeypatch):
    lot = _lot_refuse(OWNER, "admission-ocr-role-get")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    original = fusion_pdf_ocr.lire_resultat

    def lire_puis_retirer(*args):
        candidat = original(*args)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, OWNER, "nathan_owner")
        return candidat

    monkeypatch.setattr(fusion_pdf_ocr, "lire_resultat", lire_puis_retirer)
    response = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert response.status_code == 403
    assert "OCR-XSS-CANARY" not in response.text


@pytest.mark.parametrize("code, statut, message", [
    ("OCR_STRUCTURE_REFUSEE", "REFUSE", "Document refusé"),
    ("OCR_TIMEOUT", "ERREUR_REPRENABLE", "Calcul interrompu"),
])
def test_refus_et_erreur_affiches_sans_faux_404_ni_recalcul(client_ocr, monkeypatch, code, statut, message):
    from opsys.ocr_runtime import OCRRuntimeErreur

    lot = _lot_refuse(OWNER)
    csrf = _connecter(client_ocr, OWNER)
    appels = []

    def erreur_runtime(*_args, **_kwargs):
        appels.append("inférence")
        raise OCRRuntimeErreur(code)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", erreur_runtime)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert run["statut"] == statut
    monkeypatch.setattr(fusion_pdf_ocr, "lire_resultat", lambda *_a: pytest.fail("décryptage sans candidat"))
    with stockage.transaction() as cnx:
        avant = {t.name: tuple(tuple(r) for r in cnx.execute(select(t))) for t in META.sorted_tables}
    page = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert page.status_code == 200 and message in page.text
    assert code not in page.text and CANARY not in page.text
    assert page.headers["cache-control"] == "private, no-store, max-age=0"
    assert page.headers["x-content-type-options"] == "nosniff"
    with stockage.transaction() as cnx:
        apres = {t.name: tuple(tuple(r) for r in cnx.execute(select(t))) for t in META.sorted_tables}
    assert apres == avant
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    assert appels == ["inférence"]


def test_perime_pendant_inference_est_affiche_sans_texte(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER)
    csrf = _connecter(client_ocr, OWNER)

    def changer_source(source, *, lot_id, revision_source, bundle):
        candidat = _candidat(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)
        with stockage.transaction() as cnx:
            cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id).values(revision=3))
        return candidat

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", changer_source)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 303
    run = _lire_run()
    assert run["statut"] == "PERIME"
    page = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert page.status_code == 200 and "Résultat périmé" in page.text
    assert CANARY not in page.text


def test_reservation_abandonnee_est_affichee_sans_affirmer_un_worker_actif(client_ocr, monkeypatch):
    lot = _lot_refuse(ADMIN)
    csrf = _connecter(client_ocr, ADMIN)

    def retirer_role(source, *, lot_id, revision_source, bundle):
        candidat = _candidat(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, ADMIN, "admin")
        return candidat

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", retirer_role)
    assert _poster(client_ocr, lot["lot_id"], csrf).status_code == 403
    run = _lire_run()
    assert run["statut"] == "RESERVE"
    _connecter(client_ocr, OWNER)
    page = client_ocr.get(f"/fusion/pdf/lots/{lot['lot_id']}/ocr/{run['ocr_run_id']}?bloc=1")
    assert page.status_code == 200 and "Calcul réservé" in page.text
    assert "Calcul en cours" not in page.text and CANARY not in page.text


def test_post_refuse_run_renvoye_associe_a_un_autre_lot(client_ocr, monkeypatch):
    lot = _lot_refuse(OWNER, "lot-a-fictif")
    autre = _lot_refuse(OWNER, "lot-b-fictif")
    csrf = _connecter(client_ocr, OWNER)
    assert _poster(client_ocr, autre["lot_id"], csrf).status_code == 303
    run = _lire_run()
    monkeypatch.setattr(fusion_pdf_ocr, "preparer", lambda *_a, **_k: dict(run))
    reponse = _poster(client_ocr, lot["lot_id"], csrf)
    assert reponse.status_code == 503 and "location" not in reponse.headers
    assert run["ocr_run_id"] not in reponse.text and CANARY not in reponse.text
