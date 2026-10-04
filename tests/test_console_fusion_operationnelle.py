"""Parcours durable du pilote CSV Fusion opérationnelle."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from m5_financecore import registre as registre_m5
from sqlalchemy import select, update

from opsys import fusion_csv, identite, stockage
from opsys.console import application, securite
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import FUSION_COMMANDES, FUSION_LIGNES, FUSION_LOTS, FUSION_QUOTA, JOURNAL

SECRET = "secret-fusion-csv-fictif-" + "x" * 32
OWNER = "owner-fusion-fictif"
PASSWORD = "owner-fusion-fictif-password"
PREFIX = "/opsys"
KEY = base64.b64encode(b"x" * 32).decode("ascii")
FIXTURE_FICTIVE = {"fictif": True, "compte_interne_id": "compte-fictif-01"}


@pytest.fixture
def client_fusion(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys"))
    monkeypatch.delenv("OPSYS_BASE_URL", raising=False)
    monkeypatch.setenv("OPSYS_INGESTION_CLE", KEY)
    stockage.migrer()
    racine_m5 = tmp_path / "m05-financecore"
    racine_m5.mkdir()
    (racine_m5 / "department.yaml").write_text(
        "configuration:\n  banque_csv:\n    comptes_internes: [compte-fictif-01]\n", encoding="utf-8"
    )
    deps = dict(charger_departements())
    deps["m05-financecore"] = replace(deps["m05-financecore"], racine=racine_m5)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "admin-fusion-second-fictif", "Admin secondaire", PASSWORD, ["admin"])
        identite.creer_personne(cnx, "employe-fusion-fictif", "Employé fictif", PASSWORD, ["employee"])
    app = application.creer_application(Configuration(SECRET, cookie_securise=False), deps, stockage.transaction)
    with TestClient(app, base_url=f"http://testserver{PREFIX}") as client:
        _authentifier(client)
        yield client
    stockage.liberer()


def _authentifier(client: TestClient, utilisateur: str = OWNER) -> str:
    session = securite.ouvrir_session(utilisateur, frozenset({"admin", "nathan_owner"}), 3600)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, SECRET), path=PREFIX)
    return session.csrf


def _csrf(client: TestClient) -> str:
    return client.get("/api/session").json()["csrf"]


def _csv(nombre: int = 1) -> bytes:
    lignes = ["Date,Montant,Facture,Description"]
    lignes.extend(
        f"2026-09-30,100.00,FAC-FUSION-{index:04d},DETAIL-CLIENT-SECRET-{index:04d}"
        for index in range(nombre)
    )
    return ("\n".join(lignes) + "\n").encode("utf-8")


def _corps(mutation_id: str, contenu: bytes, **extras):
    return {
        "mutation_id": mutation_id,
        "compte_interne_id": FIXTURE_FICTIVE["compte_interne_id"],
        "devise": "CAD",
        "mapping_colonnes": {"date": "Date", "montant": "Montant", "reference_facture": "Facture"},
        "csv_utf8": contenu.decode("utf-8"),
        **extras,
    }


def _factures(nombre: int = 1):
    with stockage.transaction():
        registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
        for index in range(nombre):
            facture = f"FAC-FUSION-{index:04d}"
            registre.ajouter({
                "type_entree": "facture_creee", "facture_id": facture, "statut": "BROUILLON",
                "montant_apres_taxes": Decimal("100.00"), "horodatage": "2026-09-29T12:00:00+00:00",
            })
            registre.ajouter({
                "type_entree": "transition_facture", "facture_id": facture, "statut": "ENVOYEE",
                "date_envoi": "2026-09-29T12:00:00+00:00", "horodatage": "2026-09-29T12:00:00+00:00",
            })


def _creer_multipart(client, csrf, contenu: bytes, mutation_id="fusion-multipart-fictif"):
    return client.post(
        "/api/fusion-operationnelle/lots", headers={"x-csrf-token": csrf},
        data={
            "mutation_id": mutation_id, "compte_interne_id": "compte-fictif-01", "devise": "CAD",
            "mapping_date": "Date", "mapping_montant": "Montant", "mapping_reference_facture": "Facture",
        },
        files={"csv_file": ("releve.csv", contenu, "text/csv")},
    )


def _creer_html(client, csrf, contenu: bytes, mutation_id="fusion-html-fictif"):
    return client.post(
        "/fusion-operationnelle/lots", data={
            "csrf": csrf, "mutation_id": mutation_id, "compte_interne_id": "compte-fictif-01",
            "devise": "CAD", "mapping_date": "Date", "mapping_montant": "Montant",
            "mapping_reference_facture": "Facture",
        }, files={"csv_file": ("releve.csv", contenu, "text/csv")}, follow_redirects=False,
    )


def test_upload_multipart_tranche_reprise_chiffrement_et_provenance_m10(client_fusion):
    csrf = _csrf(client_fusion)
    _factures(101)
    contenu = _csv(101)
    cree = _creer_multipart(client_fusion, csrf, contenu)
    assert cree.status_code == 201, cree.text
    lot = cree.json()["lot"]
    lot_id = lot["lot_id"]
    assert lot["statut"] == "RECU" and lot["source_sha256"]
    assert "DETAIL-CLIENT-SECRET" not in cree.text

    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot_id)).one()
        assert contenu.decode() not in saved.source_cipher
        assert "DETAIL-CLIENT-SECRET" not in saved.source_cipher
        assert cnx.execute(select(FUSION_QUOTA.c.lots, FUSION_QUOTA.c.octets_cipher)).one().lots == 1

    premier = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot_id}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": 1},
    )
    assert premier.status_code == 200, premier.text
    premier_lot = premier.json()["lot"]
    assert premier_lot["statut"] == "EN_COURS" and premier_lot["curseur"] == 100
    assert premier_lot["nombre_propositions"] == 101
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_LIGNES.c.cipher).where(FUSION_LIGNES.c.lot_id == lot_id)).first()
        assert all("DETAIL-CLIENT-SECRET" not in row.cipher for row in cnx.execute(
            select(FUSION_LIGNES.c.cipher).where(FUSION_LIGNES.c.lot_id == lot_id)
        ))
        assert len(stockage.maillons("m05-financecore", "principal")) == 0

    reprise = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot_id}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": premier_lot["revision"]},
    )
    assert reprise.status_code == 200, reprise.text
    final = reprise.json()["lot"]
    assert final["statut"] == "PROPOSITIONS" and final["curseur"] == 101
    details = client_fusion.get(f"/api/fusion-operationnelle/lots/{lot_id}")
    assert details.status_code == 200
    assert len(details.json()["lot"]["lignes"]) == 101
    assert "DETAIL-CLIENT-SECRET" not in details.text
    provenance = client_fusion.get(f"/api/fusion-operationnelle/lots/{lot_id}/provenance")
    assert provenance.status_code == 200, provenance.text
    document = provenance.json()["provenance"]
    assert document["genre"] == "m5.releve_bancaire_csv"
    assert document["classe"] == "FINANCIAL" and document["nombre_propositions"] == 101
    assert "affaire_id" not in document and "montant" not in document

    # Idempotence de mutation : un rejeu identique restitue le même lot, sans quota supplémentaire.
    replay = _creer_multipart(client_fusion, csrf, contenu)
    assert replay.status_code == 201 and replay.json()["lot"]["lot_id"] == lot_id
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_QUOTA.c.lots)).scalar_one() == 1


def test_json_ferme_borne_les_octets_et_refuse_champs_inconnus(client_fusion):
    csrf = _csrf(client_fusion)
    corps = _corps("json-fusion-fictif", _csv())
    reponse = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=corps, headers={"x-csrf-token": csrf}
    )
    assert reponse.status_code == 201, reponse.text
    extra = client_fusion.post(
        "/api/fusion-operationnelle/lots", json={**corps, "acteur": OWNER},
        headers={"x-csrf-token": csrf},
    )
    assert extra.status_code == 400
    too_large = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("csv-trop-grand-fictif", b"x" * (1_048_577)),
        headers={"x-csrf-token": csrf},
    )
    assert too_large.status_code == 413


def test_json_creation_cle_dupliquee_refuse_sans_lot_quota_ni_audit(client_fusion):
    csrf = _csrf(client_fusion)
    body = json.dumps(_corps("json-cle-dupliquee-fictif", _csv()), separators=(",", ":"))
    body = body.replace(
        '"mutation_id":"json-cle-dupliquee-fictif"',
        '"mutation_id":"json-cle-dupliquee-fictif","mutation_id":"autre-mutation-fictive"',
    )
    response = client_fusion.post(
        "/api/fusion-operationnelle/lots", headers={
            "x-csrf-token": csrf, "content-type": "application/json",
        }, content=body,
    )
    assert response.status_code == 400
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_QUOTA.c.lots)).scalar_one() == 0
        assert cnx.execute(select(FUSION_LOTS)).first() is None
        assert cnx.execute(select(JOURNAL).where(JOURNAL.c.action == "console.fusion_csv.cree")).first() is None


def test_cle_absente_roles_retirees_et_csrf_refuses_sans_ecriture(client_fusion, monkeypatch):
    contenu = _csv()
    csrf = _csrf(client_fusion)
    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    absent = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("sans-cle-fictif", contenu),
        headers={"x-csrf-token": csrf},
    )
    assert absent.status_code == 503
    monkeypatch.setenv("OPSYS_INGESTION_CLE", KEY)
    sans_csrf = client_fusion.post("/api/fusion-operationnelle/lots", json=_corps("sans-csrf-fictif", contenu))
    assert sans_csrf.status_code == 403
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, OWNER, "admin")
        identite.retirer_role(cnx, OWNER, "nathan_owner")
        identite.ajouter_role(cnx, OWNER, "employee")
        assert cnx.execute(select(FUSION_QUOTA.c.lots)).scalar_one() == 0
    assert client_fusion.get("/api/fusion-operationnelle/lots").status_code == 403


def test_snapshot_perime_bloque_reprise_lecture_et_nouvelle_evaluation(client_fusion):
    csrf = _csrf(client_fusion)
    _factures()
    contenu = _csv()
    cree = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("snapshot-lot-ancien-fictif", contenu),
        headers={"x-csrf-token": csrf},
    )
    assert cree.status_code == 201
    ancien = cree.json()["lot"]
    traite = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{ancien['lot_id']}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": ancien["revision"]},
    )
    assert traite.status_code == 200 and traite.json()["lot"]["statut"] == "PROPOSITIONS"

    # Nouvelle facture invalide explicitement les lectures préparatoires conservées.
    with stockage.transaction():
        registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
        registre.ajouter({
            "type_entree": "facture_creee", "facture_id": "FAC-SNAPSHOT-AJOUTEE-FICTIVE", "statut": "BROUILLON",
            "montant_apres_taxes": Decimal("5.00"), "horodatage": "2026-09-30T12:00:00+00:00",
        })
    lecture = client_fusion.get(f"/api/fusion-operationnelle/lots/{ancien['lot_id']}")
    assert lecture.status_code == 200
    assert lecture.json()["lot"]["statut"] == "SNAPSHOT_OBSOLETE"
    assert lecture.json()["lot"]["lignes"] == []
    assert client_fusion.get(f"/api/fusion-operationnelle/lots/{ancien['lot_id']}/provenance").json()[
        "provenance"]["statut"] == "SNAPSHOT_OBSOLETE"

    reevaluation = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("snapshot-lot-nouveau-fictif", contenu),
        headers={"x-csrf-token": csrf},
    )
    assert reevaluation.status_code == 201
    assert reevaluation.json()["lot"]["lot_id"] != ancien["lot_id"]


def test_revision_attendue_rejeu_conflictuel_et_quota_cipher_resultat(client_fusion):
    csrf = _csrf(client_fusion)
    _factures()
    cree = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("revision-fusion-fictif", _csv()),
        headers={"x-csrf-token": csrf},
    )
    lot = cree.json()["lot"]
    mauvaise = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": 7},
    )
    assert mauvaise.status_code == 409
    bonne = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": lot["revision"]},
    )
    assert bonne.status_code == 200 and bonne.json()["lot"]["statut"] == "PROPOSITIONS"
    with stockage.transaction() as cnx:
        quota = cnx.execute(select(FUSION_QUOTA.c.octets_cipher)).scalar_one()
        rows = cnx.execute(select(FUSION_LIGNES.c.cipher_octets).where(
            FUSION_LIGNES.c.lot_id == lot["lot_id"]
        )).scalars().all()
        assert quota >= sum(rows) and sum(rows) > 0
        assert "100.00" not in cnx.execute(select(FUSION_LIGNES.c.cipher).where(
            FUSION_LIGNES.c.lot_id == lot["lot_id"]
        )).scalar_one()


def test_provenance_chaine_multi_lots_revision_obsolete_et_rotation_cle(client_fusion, monkeypatch):
    from m10_memoire.registre import Registre

    csrf = _csrf(client_fusion)
    _factures(2)
    first_response = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("chaine-premier-fictif", _csv(1)),
        headers={"x-csrf-token": csrf},
    )
    first = first_response.json()["lot"]
    client_fusion.post(
        f"/api/fusion-operationnelle/lots/{first['lot_id']}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": first["revision"]},
    ).json()["lot"]

    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_INGESTION_CLE_V2")
    monkeypatch.setenv("OPSYS_INGESTION_CLE_V2", base64.b64encode(b"y" * 32).decode("ascii"))
    second_response = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("chaine-second-fictif", _csv(2)),
        headers={"x-csrf-token": csrf},
    )
    second = second_response.json()["lot"]
    assert second["lot_id"] != first["lot_id"]
    done_second = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{second['lot_id']}/traiter", headers={"x-csrf-token": csrf},
        json={"revision_attendue": second["revision"]},
    ).json()["lot"]
    assert done_second["statut"] == "PROPOSITIONS"
    assert len(client_fusion.get(f"/api/fusion-operationnelle/lots/{first['lot_id']}").json()["lot"]["lignes"]) == 1

    # Une évolution M5 rend le premier résultat illisible et ajoute une nouvelle révision M10.
    with stockage.transaction():
        registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
        registre.ajouter({
            "type_entree": "facture_creee", "facture_id": "FAC-CHAINE-OBSOLETE-FICTIVE", "statut": "BROUILLON",
            "montant_apres_taxes": Decimal("5.00"), "horodatage": "2026-09-30T12:00:00+00:00",
        })
    assert client_fusion.get(f"/api/fusion-operationnelle/lots/{first['lot_id']}").json()["lot"]["lignes"] == []
    assert client_fusion.get(f"/api/fusion-operationnelle/lots/{second['lot_id']}/provenance").status_code == 200
    with stockage.transaction():
        chaine = Registre(maillons=stockage.maillons("m10-memoire", "documents"))
        assert chaine.valider_chaine()[0]
        entries = chaine.lire()
        assert len([entry for entry in entries if entry.get("type_entree") == "provenance_documentaire"]) == 4


def test_html_refuse_json_sans_csrf_et_reel_multipart_traitement(client_fusion):
    _factures()
    csrf = _csrf(client_fusion)
    refused = client_fusion.post(
        "/fusion-operationnelle/lots", json=_corps("html-json-csrf-fictif", _csv()),
    )
    assert refused.status_code == 415
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_QUOTA.c.lots)).scalar_one() == 0

    uploaded = _creer_html(client_fusion, csrf, _csv())
    assert uploaded.status_code == 303
    lot = client_fusion.get("/api/fusion-operationnelle/lots").json()["lots"][0]
    detail_link = client_fusion.get("/fusion-operationnelle")
    assert f'/fusion-operationnelle/lots/{lot["lot_id"]}' in detail_link.text
    before = client_fusion.get(f"/fusion-operationnelle/lots/{lot['lot_id']}")
    assert "Traitement incomplet" in before.text
    assert "provenance M10 sera créée" in before.text
    processed = client_fusion.post(
        f"/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        data={"csrf": csrf, "revision_attendue": str(lot["revision"])},
    )
    assert processed.status_code == 200
    detail = client_fusion.get(f"/fusion-operationnelle/lots/{lot['lot_id']}")
    assert "Propositions préparatoires uniquement" in detail.text
    assert "DETAIL-CLIENT-SECRET" not in detail.text and "releve.csv" not in detail.text


def test_upload_multipart_ferme_fichier_apres_succes_et_source_trop_grande(client_fusion, monkeypatch):
    from starlette.datastructures import UploadFile

    closed = []
    original_close = UploadFile.close

    async def close_and_track(upload):
        await original_close(upload)
        closed.append(upload.filename)

    monkeypatch.setattr(UploadFile, "close", close_and_track)
    csrf = _csrf(client_fusion)
    success = _creer_multipart(client_fusion, csrf, _csv(), mutation_id="upload-ferme-succes-fictif")
    assert success.status_code == 201 and closed == ["releve.csv"]
    oversized = _creer_multipart(
        client_fusion, csrf, b"x" * (fusion_csv.TAILLE_SOURCE_MAX + 1),
        mutation_id="upload-ferme-trop-grand-fictif",
    )
    assert oversized.status_code == 413 and closed == ["releve.csv", "releve.csv"]
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_QUOTA.c.lots)).scalar_one() == 1


def test_multipart_duplique_json_traiter_borne_et_ferme(client_fusion, monkeypatch):
    _factures()
    csrf = _csrf(client_fusion)
    boundary = "opsys-duplicate-field-test"
    from starlette.datastructures import UploadFile

    closed = []
    original_close = UploadFile.close

    async def close_and_track(upload):
        await original_close(upload)
        closed.append(upload.filename)

    monkeypatch.setattr(UploadFile, "close", close_and_track)
    chunks = []
    for name, value in [
        ("mutation_id", "doublon-a-fictif"), ("mutation_id", "doublon-b-fictif"),
        ("compte_interne_id", "compte-fictif-01"), ("devise", "CAD"),
        ("mapping_date", "Date"), ("mapping_montant", "Montant"),
        ("mapping_reference_facture", "Facture"),
    ]:
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"csv_file\"; filename=\"releve.csv\"\r\n"
        "Content-Type: text/csv\r\n\r\n" + _csv().decode() + "\r\n"
    )
    duplicate_body = ("".join(chunks) + f"--{boundary}--\r\n").encode()
    duplicated = client_fusion.post(
        "/api/fusion-operationnelle/lots", headers={
            "x-csrf-token": csrf, "content-type": f"multipart/form-data; boundary={boundary}",
        }, content=duplicate_body,
    )
    assert duplicated.status_code == 400
    assert closed == ["releve.csv"]
    assert client_fusion.get("/api/fusion-operationnelle/lots").json()["lots"] == []

    lot_response = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("traiter-borne-fictif", _csv()),
        headers={"x-csrf-token": csrf},
    )
    lot = lot_response.json()["lot"]
    oversized = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        headers={"x-csrf-token": csrf, "content-type": "application/json"},
        content=b'{"revision_attendue":1,"x":"' + b"x" * 17_000 + b'"}',
    )
    assert oversized.status_code == 413
    duplicate_key = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        headers={"x-csrf-token": csrf, "content-type": "application/json"},
        content=b'{"revision_attendue":1,"revision_attendue":1}',
    )
    assert duplicate_key.status_code == 400


def test_detail_html_echappe_toutes_les_cellules_et_refuse_employe(client_fusion, monkeypatch):
    lot_id = "8c829871-5703-445e-9b70-c3798697f71c"
    monkeypatch.setattr(fusion_csv, "lire", lambda *_: {
        "lot_id": lot_id, "statut": "PROPOSITIONS", "curseur": 1, "total_lignes": 1,
        "snapshot_version": 1, "snapshot_empreinte": "a" * 64,
        "lignes": [{"numero": 2, "date": "2026-09-30", "montant": "1.00",
                    "reference_facture": "<script>alert(1)</script>",
                    "statut_rapprochement": "PROPOSITION_EXACTE"}],
    })
    response = client_fusion.get(f"/fusion-operationnelle/lots/{lot_id}")
    assert response.status_code == 200 and 'Cache-Control' in response.headers
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    _authentifier(client_fusion, "employe-fusion-fictif")
    refused = client_fusion.get(f"/fusion-operationnelle/lots/{lot_id}")
    assert refused.status_code in {303, 403}


@pytest.mark.parametrize("query", ["?autre=0", "?debut=0&autre=0", "?debut=0&debut=100"])
def test_detail_refuse_parametres_inconnus_ou_dupliques_avant_lecture(client_fusion, monkeypatch, query):
    def lecture_interdite(*_):
        raise AssertionError("le lot financier ne doit pas être lu pour une requête invalide")

    monkeypatch.setattr(fusion_csv, "lire", lecture_interdite)
    response = client_fusion.get(f"/fusion-operationnelle/lots/8c829871-5703-445e-9b70-c3798697f71c{query}")
    assert response.status_code == 400


def test_cipher_source_corrompu_et_mauvaise_cle_refuses(client_fusion, monkeypatch):
    csrf = _csrf(client_fusion)
    _factures(2)
    first = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("cipher-corrompu-fictif", _csv()),
        headers={"x-csrf-token": csrf},
    ).json()["lot"]
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == first["lot_id"]).values(
            source_cipher="bad",
        ))
    corrupt = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{first['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": first["revision"]},
    )
    assert corrupt.status_code == 409 and corrupt.json()["detail"]["code"] == "CIPHER_INVALIDE"

    second = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("cipher-mauvaise-cle-fictif", _csv(2)),
        headers={"x-csrf-token": csrf},
    ).json()["lot"]
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"z" * 32).decode("ascii"))
    wrong_key = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{second['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": second["revision"]},
    )
    assert wrong_key.status_code == 409 and wrong_key.json()["detail"]["code"] == "CIPHER_INVALIDE"


def test_saturation_quota_annule_resultat_curseur_lignes_et_m10(client_fusion):
    csrf = _csrf(client_fusion)
    _factures()
    lot = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("quota-cipher-fictif", _csv()),
        headers={"x-csrf-token": csrf},
    ).json()["lot"]
    m10_before = len(stockage.maillons("m10-memoire", "documents"))
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_QUOTA).values(octets_cipher=fusion_csv.QUOTA_CIPHER_MAX))
    saturated = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": lot["revision"]},
    )
    assert saturated.status_code == 409 and saturated.json()["detail"]["code"] == "QUOTA_ATTEINT"
    with stockage.transaction() as cnx:
        current = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot["lot_id"])).one()
        assert current.statut == "RECU" and current.curseur == 0 and current.resultat_cipher is None
        assert cnx.execute(select(FUSION_LIGNES).where(FUSION_LIGNES.c.lot_id == lot["lot_id"])).first() is None
        assert cnx.execute(select(FUSION_QUOTA.c.octets_cipher)).scalar_one() == fusion_csv.QUOTA_CIPHER_MAX
    assert len(stockage.maillons("m10-memoire", "documents")) == m10_before


def test_parser_une_fois_et_reprise_apres_liberation_stockage(client_fusion, monkeypatch):
    from m5_financecore import reconciliation_bancaire_csv

    csrf = _csrf(client_fusion)
    _factures(101)
    lot = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("reprise-redemarrage-fictif", _csv(101)),
        headers={"x-csrf-token": csrf},
    ).json()["lot"]
    original = reconciliation_bancaire_csv.previsualiser_releve_csv
    calls = []

    def compter(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(reconciliation_bancaire_csv, "previsualiser_releve_csv", compter)
    first = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": lot["revision"]},
    ).json()["lot"]
    assert first["curseur"] == 100 and len(calls) == 1
    stockage.liberer()
    resumed = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": first["revision"]},
    )
    assert resumed.status_code == 200 and resumed.json()["lot"]["curseur"] == 101
    assert len(calls) == 1


def test_dedup_second_admin_audit_acteur_live_et_mutation_non_reutilisable(client_fusion):
    csrf_owner = _csrf(client_fusion)
    _factures(2)
    first = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("dedup-acteur-source-fictif", _csv()),
        headers={"x-csrf-token": csrf_owner},
    ).json()["lot"]
    csrf_second = _authentifier(client_fusion, "admin-fusion-second-fictif")
    dedup = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("dedup-autre-admin-fictif", _csv()),
        headers={"x-csrf-token": csrf_second},
    )
    assert dedup.status_code == 201 and dedup.json()["lot"]["lot_id"] == first["lot_id"]
    reused = client_fusion.post(
        "/api/fusion-operationnelle/lots",
        json=_corps("dedup-autre-admin-fictif", _csv(2)), headers={"x-csrf-token": csrf_second},
    )
    assert reused.status_code == 409 and reused.json()["detail"]["code"] == "CONFLIT_MUTATION"
    with stockage.transaction() as cnx:
        command = cnx.execute(select(FUSION_COMMANDES).where(
            (FUSION_COMMANDES.c.acteur == "admin-fusion-second-fictif")
            & (FUSION_COMMANDES.c.mutation_id == "dedup-autre-admin-fictif")
        )).one()
        assert command.lot_id == first["lot_id"]
    processed = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{first['lot_id']}/traiter",
        headers={"x-csrf-token": csrf_second}, json={"revision_attendue": first["revision"]},
    )
    assert processed.status_code == 200
    with stockage.transaction() as cnx:
        entries = cnx.execute(select(JOURNAL.c.par, JOURNAL.c.action).where(
            JOURNAL.c.cible == first["lot_id"]
        )).all()
    assert ("admin-fusion-second-fictif", "console.fusion_csv.tranche") in [tuple(entry) for entry in entries]
    with stockage.transaction():
        registre = registre_m5.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
        registre.ajouter({
            "type_entree": "facture_creee", "facture_id": "FAC-AUDIT-OBSOLETE-FICTIVE", "statut": "BROUILLON",
            "montant_apres_taxes": Decimal("5.00"), "horodatage": "2026-09-30T12:00:00+00:00",
        })
    stale = client_fusion.get(f"/api/fusion-operationnelle/lots/{first['lot_id']}")
    assert stale.json()["lot"]["statut"] == "SNAPSHOT_OBSOLETE"
    with stockage.transaction() as cnx:
        audit = cnx.execute(select(JOURNAL.c.par).where(
            (JOURNAL.c.cible == first["lot_id"])
            & (JOURNAL.c.action == "console.fusion_csv.snapshot_obsolete")
        )).scalar_one()
    assert audit == "admin-fusion-second-fictif"


def test_retrait_role_apres_calcul_annule_tranche_et_snapshot_perime_avant_retour(
    client_fusion, monkeypatch,
):
    csrf = _csrf(client_fusion)
    _factures()
    lot = client_fusion.post(
        "/api/fusion-operationnelle/lots", json=_corps("droits-post-calcul-fictif", _csv()),
        headers={"x-csrf-token": csrf},
    ).json()["lot"]
    original_check = fusion_csv._exiger_personne
    checks = []

    def retirer_apres_calcul(cnx, acteur):
        checks.append(1)
        if len(checks) == 2:
            identite.retirer_role(cnx, acteur, "admin")
            identite.retirer_role(cnx, acteur, "nathan_owner")
        return original_check(cnx, acteur)

    monkeypatch.setattr(fusion_csv, "_exiger_personne", retirer_apres_calcul)
    refused = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{lot['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": lot["revision"]},
    )
    assert refused.status_code == 403 and len(checks) == 2
    monkeypatch.setattr(fusion_csv, "_exiger_personne", original_check)
    with stockage.transaction() as cnx:
        unchanged = cnx.execute(select(FUSION_LOTS).where(FUSION_LOTS.c.lot_id == lot["lot_id"])).one()
        assert unchanged.statut == "RECU" and unchanged.curseur == 0 and unchanged.resultat_cipher is None
        assert cnx.execute(select(FUSION_LIGNES).where(FUSION_LIGNES.c.lot_id == lot["lot_id"])).first() is None

    # Un snapshot détecté périmé lors de la dernière validation masque les lignes avant le retour HTTP.
    current = client_fusion.post(
        "/api/fusion-operationnelle/lots",
        json=_corps("snapshot-post-calcul-fictif", _csv().replace(b"DETAIL-CLIENT", b"AUTRE-CLIENT")),
        headers={"x-csrf-token": csrf},
    ).json()["lot"]
    original_snapshot = fusion_csv._snapshot
    calls = []

    def faire_evoluer_snapshot():
        calls.append(1)
        value = original_snapshot()
        if len(calls) >= 5:
            return {**value, "version": value["version"] + 1}
        return value

    monkeypatch.setattr(fusion_csv, "_snapshot", faire_evoluer_snapshot)
    response = client_fusion.post(
        f"/api/fusion-operationnelle/lots/{current['lot_id']}/traiter",
        headers={"x-csrf-token": csrf}, json={"revision_attendue": current["revision"]},
    )
    assert response.status_code == 200 and response.json()["lot"]["statut"] == "SNAPSHOT_OBSOLETE"
    assert len(client_fusion.get(f"/api/fusion-operationnelle/lots/{current['lot_id']}").json()["lot"]["lignes"]) == 0


def test_stockage_postgresql_refuse_explicitement_sans_mutation():
    class Dialect:
        name = "postgresql"

    class ConnectionPostgres:
        dialect = Dialect()

    with pytest.raises(fusion_csv.FusionErreur) as erreur:
        fusion_csv._isoler_transaction(ConnectionPostgres())
    assert erreur.value.code == "STOCKAGE_NON_QUALIFIE"
