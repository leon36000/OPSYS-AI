"""Parcours console de médias privés M7.3a, avec CAS PNG et identité synthétiques."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
import zlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
import starlette.formparsers as formparsers
from fastapi import HTTPException
from fastapi.testclient import TestClient
from m7_marketing import outils as outils_m7
from m7_marketing.brand import profil_client
from m7_marketing.usine import service as usine_service
from sqlalchemy import func, select, update
from starlette.requests import Request

from opsys import contexte, fichiers, identite, stockage
from opsys.console import application, calendrier_marketing_ui
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, FICHIERS_BLOCS, MUTATIONS_APPLIQUEES, REGISTRES

SECRET = "secret-m73a-console-fictif-" + "x" * 32
PREFIXE = "/opsys"
MOT_DE_PASSE = "mot-de-passe-m73a-fictif-1234"
WCT_ID = "wct-m73a-fictif-001"
OUTILS = {outil.nom: outil for outil in outils_m7.outils()}
ATTESTATION = "Je confirme cette préparation humaine pour la revue fictive."


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer()
    yield stockage.transaction
    stockage.liberer()


def _png(pixel: bytes = b"\xff\x00\x00") -> bytes:
    def chunk(nom: bytes, donnees: bytes) -> bytes:
        contenu = nom + donnees
        return struct.pack(">I", len(donnees)) + contenu + struct.pack(">I", zlib.crc32(contenu))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" + pixel, 9))
        + chunk(b"IEND", b"")
    )


def _wct(reference: str) -> dict[str, object]:
    return {
        "wct_id": WCT_ID,
        "intervention_id": "intervention-m73a-fictive-001",
        "lead_id": "lead-m73a-fictif-001",
        "technicien_id": "technicien-m73a-fictif",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 180,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "ab" * 32,
        "consommateurs_cibles": ["M7"],
        "devis_id": "devis-m73a-fictif-001",
        "statut": "completed_verified",
        "ville": "Repentigny",
        "type_travaux": "gouttières",
        "photos": [reference],
        "description_factuelle": "Chantier fictif terminé sans imprévu.",
        "consentement_marketing": True,
        "client_satisfait": True,
        "consentement_recueilli_par": "technicien-m73a-fictif",
        "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
        "consentement_version_texte": "consentement-client-fr-CA-m73a-v1",
    }


@pytest.fixture
def medias(session, monkeypatch):
    profil = {
        "name": "Entreprise M73a fictive",
        "tagline": "Travaux faits avec soin",
        "tone": "professionnel, factuel",
        "colors": ["#123456"],
        "langue": "fr",
        "site_url": "https://exemple-fictif.ca/",
        "heures_publication": {"facebook": "18:30"},
    }
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))
    source = _png()
    source_ref = fichiers.reference_pour(hashlib.sha256(source).hexdigest())
    unrelated = _png(b"\x00\xff\x00")
    unrelated_ref = fichiers.reference_pour(hashlib.sha256(unrelated).hexdigest())
    with session() as cnx:
        for octets in (source, unrelated):
            sha = hashlib.sha256(octets).hexdigest()
            resultat = fichiers.deposer_bloc(
                cnx, sha, len(octets), "image/png", 0, 1,
                base64.b64encode(octets).decode("ascii"), recu_le="2026-09-28T10:00:00+00:00",
            )
            assert resultat.accepte and resultat.complet
        identite.creer_personne(cnx, "owner_m73a", "Owner M73a fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "admin_m73a", "Admin M73a fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employee_m73a", "Employé M73a fictif", MOT_DE_PASSE, ["employee"])
        identite.creer_personne(cnx, "agent_m73a", "Agent M73a fictif", MOT_DE_PASSE, ["system_agent"])
    with stockage.transaction():
        stockage.maillons(*usine_service.REGISTRE_WCT_RECUS).append(_wct(source_ref))
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session
    )
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield {
            "client": client,
            "session": session,
            "source": source,
            "source_ref": source_ref,
            "unrelated_ref": unrelated_ref,
        }


def _login(client: TestClient, user: str = "owner_m73a") -> str:
    response = client.post(
        "/connexion", data={"identifiant": user, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return client.get("/api/session").json()["csrf"]


def _mutation(client: TestClient, csrf: str, action: str, mutation_id: str, **body):
    return client.post(
        "/api/marketing/calendrier",
        json={"action": action, "mutation_id": mutation_id, **body},
        headers={"x-csrf-token": csrf},
    )


def _preparer_contenu_et_creneau(client: TestClient, csrf: str) -> tuple[dict, dict]:
    propose = _mutation(
        client, csrf, "proposer_contenus", "m73a-propose-contenu", wct_id=WCT_ID
    )
    assert propose.status_code == 200 and propose.json()["ok"] is True, propose.text
    listing = client.get("/api/marketing/calendrier").json()["resultat"]
    contenu = next(item for item in listing["contenus"] if item["plateforme"] == "facebook")
    approve = _mutation(
        client, csrf, "decider_contenu", "m73a-approuve-contenu",
        contenu_id=contenu["contenu_id"], decision="approuver",
    )
    assert approve.status_code == 200 and approve.json()["ok"] is True, approve.text
    plan = (datetime.now(UTC) + timedelta(days=3)).astimezone(
        timezone(timedelta(hours=-4))
    ).isoformat(timespec="seconds")
    proposed_slot = _mutation(
        client, csrf, "proposer_creneau", "m73a-propose-slot",
        contenu_id=contenu["contenu_id"], planifie_le=plan,
    )
    assert proposed_slot.status_code == 200 and proposed_slot.json()["ok"] is True, proposed_slot.text
    slot = proposed_slot.json()["resultat"]["resultat"]["resultat"]
    approve_slot = _mutation(
        client, csrf, "decider_creneau", "m73a-approuve-slot",
        creneau_id=slot["creneau_id"], decision="approuver",
    )
    assert approve_slot.status_code == 200 and approve_slot.json()["ok"] is True, approve_slot.text
    return contenu, slot


def _dossier(client: TestClient, contenu_id: str) -> dict:
    response = client.get(f"/api/marketing/calendrier/medias/{contenu_id}")
    assert response.status_code == 200 and response.json()["ok"] is True, response.text
    return response.json()["resultat"]["resultat"]


def _contenu_id(client: TestClient) -> str:
    listing = client.get("/api/marketing/calendrier").json()["resultat"]["contenus"]
    return next(item["contenu_id"] for item in listing if item["plateforme"] == "facebook")


def _lire_registre(nom: str) -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _preparer_dossier(client: TestClient, csrf: str, refs: dict) -> tuple[dict, dict]:
    contenu, slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    upload = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-upload-complete",
            "contenu_id": contenu["contenu_id"],
            "source_ref": refs["source_ref"],
            "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"],
            "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepare.png", _png(b"\x00\x00\xff"), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert upload.status_code == 200 and upload.json()["ok"] is True, upload.text
    dossier = _dossier(client, contenu["contenu_id"])
    assert type(dossier.get("revision")) is int, dossier
    decision = _mutation(
        client, csrf, "decider_medias", "m73a-review-media", contenu_id=contenu["contenu_id"],
        decision="approuver", revision_attendue=dossier["revision"],
        empreinte_attendue=dossier["empreinte_dossier"], snapshot_attendu=dossier["snapshot_sha256"],
        attestation_humaine="Je confirme la revue privée de chaque variante préparée.",
    )
    assert decision.status_code == 200 and decision.json()["ok"] is True, decision.text
    approved = _dossier(client, contenu["contenu_id"])
    assert approved["statut"] == "APPROUVE", approved
    return contenu, slot


# Note: les cas ci-dessous exercent les routes console/API réelles et les registres existants.


def test_remise_manuelle_binaire_est_exacte_privee_et_rejouable(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, slot = _preparer_dossier(client, csrf, medias)
    remise = _mutation(
        client, csrf, "remettre_medias", "m73a-remise-manual-1", creneau_id=slot["creneau_id"]
    )
    assert remise.status_code == 200 and remise.json()["ok"] is True, remise.text
    exports_avant = _lire_registre("exports_paquet")
    exports_cal_avant = _lire_registre("exports_calendrier")
    evenements = _lire_registre("dossiers_medias")
    assert len(exports_avant) == 1 and exports_cal_avant == []
    assert any(e.get("type_maillon") == "media_remise" for e in evenements)
    relecture = _dossier(client, contenu["contenu_id"])
    media_ref = relecture["medias"][0]["prepared_ref"]
    response = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": media_ref, "mode": "remise"},
    )
    assert response.status_code == 200
    assert response.content == _png(b"\x00\x00\xff")
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    reexecute = _mutation(
        client, csrf, "remettre_medias", "m73a-remise-manual-1", creneau_id=slot["creneau_id"]
    )
    assert reexecute.status_code == 200
    assert reexecute.json()["resultat"]["rejoue"] is True
    assert reexecute.json()["resultat"]["resultat"] == remise.json()["resultat"]["resultat"]
    assert len(_lire_registre("dossiers_medias")) == len(evenements)
    assert len(_lire_registre("exports_paquet")) == len(exports_avant)
    assert len(_lire_registre("exports_calendrier")) == len(exports_cal_avant)


def test_admin_employee_et_agent_ne_peuvent_ni_lire_dossier_ni_telecharger(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    for user in ("admin_m73a", "employee_m73a", "agent_m73a"):
        _login(client, user)
        dossier = client.get(f"/api/marketing/calendrier/medias/{contenu['contenu_id']}")
        assert dossier.status_code in {403, 409}, (user, dossier.text)
        binary = client.get(
            f"/marketing/calendrier/medias/{contenu['contenu_id']}",
            params={"reference": medias["source_ref"], "mode": "apercu"},
        )
        assert binary.status_code == 403, (user, binary.text)
        assert binary.content != medias["source"]


def test_csrf_absent_refuse_upload_sans_maillon(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    response = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-csrf-absent", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepared.png", _png(), "image/png")},
    )
    assert response.status_code == 403
    assert _lire_registre("dossiers_medias") == []


def test_source_etrangere_et_octets_non_image_sont_refuses_sans_preparation(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    for mutation_id, source_ref, octets in (
        ("m73a-foreign", medias["unrelated_ref"], _png()),
        ("m73a-wrong-mime-bytes", medias["source_ref"], b"octets qui ne sont pas une image"),
    ):
        dossier = _dossier(client, contenu["contenu_id"])
        response = client.post(
            "/api/marketing/calendrier/medias",
            data={
                "mutation_id": mutation_id, "contenu_id": contenu["contenu_id"],
                "source_ref": source_ref, "revision_attendue": str(dossier["revision"]),
                "empreinte_attendue": dossier["empreinte_dossier"],
                "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
            },
            files={"fichier": ("prepared.png", octets, "image/png")},
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 409, response.text
        assert response.json()["ok"] is False
    assert _lire_registre("dossiers_medias") == []


def test_replay_upload_identique_est_idempotent_et_octets_divergents_en_conflit(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    champs = {
        "mutation_id": "m73a-replay-upload", "contenu_id": contenu["contenu_id"],
        "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"]),
        "empreinte_attendue": dossier["empreinte_dossier"],
        "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
    }
    payload = _png(b"\x12\x34\x56")
    premier = client.post(
        "/api/marketing/calendrier/medias", data=champs,
        files={"fichier": ("prepared.png", payload, "image/png")}, headers={"x-csrf-token": csrf},
    )
    assert premier.status_code == 200, premier.text
    replay = client.post(
        "/api/marketing/calendrier/medias", data=champs,
        files={"fichier": ("prepared.png", payload, "image/png")}, headers={"x-csrf-token": csrf},
    )
    assert replay.status_code == 200
    assert replay.json()["resultat"]["rejoue"] is True
    assert replay.json()["resultat"]["resultat"] == premier.json()["resultat"]["resultat"]
    divergent = client.post(
        "/api/marketing/calendrier/medias", data=champs,
        files={"fichier": ("prepared.png", _png(b"\xaa\xbb\xcc"), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert divergent.status_code == 409
    assert len(_lire_registre("dossiers_medias")) == 1


def test_preparation_perimee_apres_retrait_consentement_est_refusee(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    outil = OUTILS["m7_enregistrer_retrait_consentement_marketing"]
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner_m73a", "admin")):
        retrait = executer_atomique(
            outil,
            {"wct_id": WCT_ID, "canal": "courriel", "horodatage": "2026-09-30T10:00:00-04:00"},
        )
    assert retrait.get("resultat", {}).get("accepte") is True, retrait
    response = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-consent-revoked", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepared.png", _png(), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 409
    assert _lire_registre("dossiers_medias") == []


def test_cas_incomplet_est_signale_et_cote_meme_source_les_autres_droits_restent_prives(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    response = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": medias["source_ref"], "mode": "remise"},
    )
    assert response.status_code in {403, 404}
    owner_preview = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": medias["source_ref"], "mode": "apercu"},
    )
    assert owner_preview.status_code == 200 and owner_preview.content == medias["source"]
    assert owner_preview.headers["cache-control"] == "private, no-store, max-age=0"
    stockage.liberer()
    stockage.migrer()
    persisted = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": medias["source_ref"], "mode":"apercu"},
    )
    assert persisted.status_code == 200 and persisted.content == medias["source"]


def test_demande_preparation_perimee_par_revision_ou_snapshot_ne_cree_pas_maillon(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    stale = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-stale-snapshot", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"] + 1),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepared.png", _png(), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert stale.status_code == 409
    assert _lire_registre("dossiers_medias") == []


def test_retrait_role_pendant_parse_multipart_refuse_avant_tout_maillon(medias, monkeypatch):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    parser_reel = calendrier_marketing_ui._multipart_media_borne

    async def parser_puis_retirer_role(request):
        formulaire = await parser_reel(request)
        with medias["session"]() as cnx:
            identite.retirer_role(cnx, "owner_m73a", "nathan_owner")
        return formulaire

    monkeypatch.setattr(calendrier_marketing_ui, "_multipart_media_borne", parser_puis_retirer_role)
    response = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-role-retired-after-body", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepared.png", _png(), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 403
    assert _lire_registre("dossiers_medias") == []


def test_corps_multipart_hors_borne_est_refuse_sans_stockage(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    oversized = b"x" * (10 * 1024 * 1024 + 40_000)
    response = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-oversized", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": "0",
            "empreinte_attendue": "0" * 64, "snapshot_attendu": "0" * 64,
            "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("too-large.png", oversized, "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 413, response.text
    assert _lire_registre("dossiers_medias") == []


def test_page_console_affiche_les_medias_sans_exposer_payload_wct_brut(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    page = client.get("/marketing/calendrier")
    assert page.status_code == 200
    assert contenu["contenu_id"] in page.text
    # Descriptif de chantier/GPS issu du WCT restent hors de la vue média console.
    assert "Chantier fictif terminé sans imprévu" not in page.text
    metadata = client.get(f"/api/marketing/calendrier/medias/{contenu['contenu_id']}")
    assert metadata.status_code == 200
    assert "Chantier fictif terminé sans imprévu" not in metadata.text
    assert "fix_gps_completion" not in metadata.text
    assert "snapshot\"" not in metadata.text
    assert "media" in page.text.lower()


def test_profil_modifie_apres_affichage_invalide_la_preparation(medias, monkeypatch):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    monkeypatch.setattr(
        profil_client, "charger_profil_client",
        lambda: ({"name": "Profil M73a remplacé", "langue": "fr"}, None),
    )
    response = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-profile-stale", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepared.png", _png(), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 409
    assert _lire_registre("dossiers_medias") == []


def test_cas_prepare_corrompu_apres_upload_ne_peut_pas_etre_approuve(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    upload = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "m73a-prepare-to-tamper", "contenu_id": contenu["contenu_id"],
            "source_ref": medias["source_ref"], "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"], "attestation_humaine": ATTESTATION,
        },
        files={"fichier": ("prepared.png", _png(b"\x91\x82\x73"), "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert upload.status_code == 200, upload.text
    prepared = _dossier(client, contenu["contenu_id"])["medias"][0]
    sha = fichiers.empreinte_depuis_reference(prepared["prepared_ref"])
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FICHIERS_BLOCS)
            .where(FICHIERS_BLOCS.c.empreinte_sha256 == sha)
            .values(contenu_base64=base64.b64encode(b"\x00" * prepared["prepared_taille"]).decode("ascii"))
        )
    current = _dossier(client, contenu["contenu_id"])
    decision = _mutation(
        client, csrf, "decider_medias", "m73a-approve-corrupted-prepare",
        contenu_id=contenu["contenu_id"], decision="approuver",
        revision_attendue=current["revision"], empreinte_attendue=current["empreinte_dossier"],
        snapshot_attendu=current["snapshot_sha256"],
        attestation_humaine="Je confirme la revue privée de chaque variante préparée.",
    )
    assert decision.status_code == 409
    after = _dossier(client, contenu["contenu_id"])
    assert after["statut"] == "EN_ATTENTE_REVUE"
    assert not any(item.get("type_maillon") == "media_revue" for item in after["evenements"])


def test_wct_photo_absente_du_cas_refuse_lecture_dossier_sans_vue_partielle(medias):
    client = medias["client"]
    csrf = _login(client)
    missing = "fichier:sha256:" + "0" * 64
    wct = _wct(missing)
    wct["wct_id"] = "wct-m73a-sans-cas"
    wct["hash_maillon"] = "cd" * 32
    with stockage.transaction():
        stockage.maillons(*usine_service.REGISTRE_WCT_RECUS).append(wct)
    propose = _mutation(
        client, csrf, "proposer_contenus", "m73a-propose-incomplete-wct", wct_id=wct["wct_id"]
    )
    assert propose.status_code == 200 and propose.json()["ok"] is True, propose.text
    listing = client.get("/api/marketing/calendrier").json()["resultat"]["contenus"]
    contenu = next(item for item in listing if item["wct_id"] == wct["wct_id"])
    response = client.get(f"/api/marketing/calendrier/medias/{contenu['contenu_id']}")
    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert response.json()["erreur"]["message"] == "une photo du WCT n'est plus vérifiable"
    assert not any(
        item.get("contenu_id") == contenu["contenu_id"]
        for item in _lire_registre("dossiers_medias")
    )


def _chercher_cle(valeur, cle: str):
    if isinstance(valeur, dict):
        if cle in valeur:
            return valeur[cle]
        for enfant in valeur.values():
            trouve = _chercher_cle(enfant, cle)
            if trouve is not None:
                return trouve
    elif isinstance(valeur, list):
        for enfant in valeur:
            trouve = _chercher_cle(enfant, cle)
            if trouve is not None:
                return trouve
    return None


def test_nouvelle_mutation_de_remise_reemet_le_meme_export_sans_append(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, slot = _preparer_dossier(client, csrf, medias)
    first = _mutation(
        client, csrf, "remettre_medias", "m73a-remise-first-id", creneau_id=slot["creneau_id"]
    )
    assert first.status_code == 200 and _chercher_cle(first.json(), "accepte") is True, first.text
    first_media_export = _chercher_cle(first.json(), "media_export_id")
    first_export = _chercher_cle(first.json(), "export_id")
    assert isinstance(first_media_export, str) and isinstance(first_export, str), first.text
    dossiers = _lire_registre("dossiers_medias")
    paquet = _lire_registre("exports_paquet")
    calendriers = _lire_registre("exports_calendrier")
    response_events = _lire_sorties_evenement()

    second = _mutation(
        client, csrf, "remettre_medias", "m73a-remise-new-id", creneau_id=slot["creneau_id"]
    )
    assert second.status_code == 200 and _chercher_cle(second.json(), "accepte") is True, second.text
    assert _chercher_cle(second.json(), "media_export_id") == first_media_export
    assert _chercher_cle(second.json(), "export_id") == first_export
    assert _lire_registre("dossiers_medias") == dossiers
    assert _lire_registre("exports_paquet") == paquet
    assert _lire_registre("exports_calendrier") == calendriers
    assert _lire_sorties_evenement() == response_events

    dossier = _dossier(client, contenu["contenu_id"])
    prepared_ref = dossier["medias"][0]["prepared_ref"]
    download = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": prepared_ref, "mode": "remise"},
    )
    assert download.status_code == 200
    assert download.content == _png(b"\x00\x00\xff")
    assert download.headers["cache-control"] == "private, no-store, max-age=0"


def _lire_sorties_evenement() -> list[dict]:
    with stockage.transaction() as cnx:
        return [dict(row) for row in cnx.execute(select(EVENEMENTS_SORTANTS)).mappings()]


def test_plafond_fichier_sous_borne_totale_ferme_spool_et_n_ecrit_rien(medias, monkeypatch):
    client = medias["client"]
    csrf = _login(client)
    contenu, _slot = _preparer_contenu_et_creneau(client, csrf)
    dossier = _dossier(client, contenu["contenu_id"])
    mutation_id = "m73a-stream-oversize-no-length"
    boundary = "m73a-boundary-fictif-r2"
    champs = {
        "mutation_id": mutation_id,
        "contenu_id": contenu["contenu_id"],
        "source_ref": medias["source_ref"],
        "revision_attendue": str(dossier["revision"]),
        "empreinte_attendue": dossier["empreinte_dossier"],
        "snapshot_attendu": dossier["snapshot_sha256"],
        "attestation_humaine": ATTESTATION,
    }

    def flux():
        for nom, valeur in champs.items():
            yield (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nom}\"\r\n\r\n"
                f"{valeur}\r\n"
            ).encode()
        yield (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"fichier\"; "
            "filename=\"oversize.png\"\r\nContent-Type: image/png\r\n\r\n"
        ).encode()
        yield _png()
        for _ in range(10):
            yield b"x" * (1024 * 1024)
        yield b"x" * 1024
        yield f"\r\n--{boundary}--\r\n".encode()

    opened = []
    real_spool = formparsers.SpooledTemporaryFile

    def spool_tracked(*args, **kwargs):
        fichier = real_spool(*args, **kwargs)
        opened.append(fichier)
        return fichier

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool_tracked)
    parser = __import__("opsys.console.calendrier_marketing_ui", fromlist=["_multipart_media_borne"])
    parser_reel = parser._multipart_media_borne
    entetes_sans_longueur = []

    async def parser_spy(request):
        entetes_sans_longueur.append("content-length" not in request.headers)
        return await parser_reel(request)

    monkeypatch.setattr(parser, "_multipart_media_borne", parser_spy)
    dossiers_avant = _lire_registre("dossiers_medias")
    paquet_avant = _lire_registre("exports_paquet")
    evenements_avant = _lire_sorties_evenement()
    with stockage.transaction() as cnx:
        mutations_avant = cnx.execute(
            select(func.count()).select_from(MUTATIONS_APPLIQUEES).where(
                MUTATIONS_APPLIQUEES.c.cle_idempotence == mutation_id
            )
        ).scalar_one()
    response = client.post(
        "/api/marketing/calendrier/medias",
        content=flux(),
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "x-csrf-token": csrf,
        },
    )
    assert entetes_sans_longueur == [True]
    assert response.status_code == 413, response.text
    assert opened and all(fichier.closed for fichier in opened)
    assert _lire_registre("dossiers_medias") == dossiers_avant
    assert _lire_registre("exports_paquet") == paquet_avant
    assert _lire_sorties_evenement() == evenements_avant
    with stockage.transaction() as cnx:
        mutations_apres = cnx.execute(
            select(func.count()).select_from(MUTATIONS_APPLIQUEES).where(
                MUTATIONS_APPLIQUEES.c.cle_idempotence == mutation_id
            )
        ).scalar_one()
    assert mutations_apres == mutations_avant == 0


def test_borne_totale_directe_apres_spool_asgi_sans_content_length(monkeypatch):
    ui = calendrier_marketing_ui
    boundary = b"m73a-total-boundary-r3"
    prefixe = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="fichier"; filename="oversize.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
        + _png()
    )
    restant = ui._MAX_CORPS_MEDIA + 64 * 1024 - len(prefixe)
    blocs = [prefixe, *([b"x" * (1024 * 1024)] * (restant // (1024 * 1024)))]
    if restant % (1024 * 1024):
        blocs.append(b"x" * (restant % (1024 * 1024)))
    ouverts = []
    vrai_spool = formparsers.SpooledTemporaryFile

    def spool_suivi(*args, **kwargs):
        fichier = vrai_spool(*args, **kwargs)
        ouverts.append(fichier)
        return fichier

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool_suivi)
    entetes = [(b"content-type", b"multipart/form-data; boundary=" + boundary)]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/marketing/calendrier/medias",
        "raw_path": b"/api/marketing/calendrier/medias", "query_string": b"",
        "headers": entetes, "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
    }
    curseur = 0

    async def receive():
        nonlocal curseur
        if curseur < len(blocs):
            bloc = blocs[curseur]
            curseur += 1
            return {"type": "http.request", "body": bloc, "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def lire():
        with pytest.raises(HTTPException) as refus:
            await ui._multipart_media_borne(Request(scope, receive))
        assert refus.value.status_code == 413

    asyncio.run(lire())
    assert "content-length" not in dict((k.decode(), v.decode()) for k, v in entetes)
    assert curseur > 1
    assert ouverts and all(fichier.closed for fichier in ouverts)


def test_texte_courant_refuse_avant_remise_et_ajout_de_toute_trace(medias, monkeypatch):
    client = medias["client"]
    csrf = _login(client)
    _contenu, slot = _preparer_dossier(client, csrf, medias)
    dossier_events = _lire_registre("dossiers_medias")
    exports = _lire_registre("exports_paquet")
    exports_cal = _lire_registre("exports_calendrier")
    bus = _lire_sorties_evenement()

    def refus_texte(_proposition):
        return {"accepte": False, "verdict": {"code": "REJ-TEXTE-FICTIF", "detail": "texte invalide"}}

    monkeypatch.setattr(usine_service, "_refus_texte", refus_texte)
    response = _mutation(
        client, csrf, "remettre_medias", "m73a-remise-texte-invalide", creneau_id=slot["creneau_id"]
    )
    assert response.status_code == 409
    assert _chercher_cle(response.json(), "accepte") is False
    assert _lire_registre("dossiers_medias") == dossier_events
    assert _lire_registre("exports_paquet") == exports
    assert _lire_registre("exports_calendrier") == exports_cal
    assert _lire_sorties_evenement() == bus


def test_texte_stocke_modifie_sans_empreinte_approuvee_refuse_avant_effets(medias):
    client = medias["client"]
    csrf = _login(client)
    contenu, slot = _preparer_dossier(client, csrf, medias)
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
                REGISTRES.c.departement == "m07-marketing",
                REGISTRES.c.registre == "contenus_chantier",
            ).order_by(REGISTRES.c.rang)
        ).all()
        proposition = None
        rang_proposition = None
        for ligne in lignes:
            valeur = codec.decoder(ligne.maillon)
            if valeur.get("contenu_id") == contenu["contenu_id"]:
                proposition = valeur
                rang_proposition = ligne.rang
                break
        assert proposition is not None and type(rang_proposition) is int
        empreinte_approuvee = proposition["empreinte_texte"]
        proposition["texte"] += " Travaux terminés."
        assert hashlib.sha256(proposition["texte"].encode("utf-8")).hexdigest() != empreinte_approuvee
        cnx.execute(
            update(REGISTRES)
            .where(
                REGISTRES.c.departement == "m07-marketing",
                REGISTRES.c.registre == "contenus_chantier",
                REGISTRES.c.rang == rang_proposition,
            )
            .values(maillon=codec.encoder(proposition))
        )

    dossiers_avant = _lire_registre("dossiers_medias")
    exports_avant = _lire_registre("exports_paquet")
    calendriers_avant = _lire_registre("exports_calendrier")
    bus_avant = _lire_sorties_evenement()
    response = _mutation(
        client, csrf, "remettre_medias", "m73a-remise-texte-hash-mismatch", creneau_id=slot["creneau_id"]
    )
    assert response.status_code == 409
    assert _chercher_cle(response.json(), "accepte") is False
    assert _lire_registre("dossiers_medias") == dossiers_avant
    assert _lire_registre("exports_paquet") == exports_avant
    assert _lire_registre("exports_calendrier") == calendriers_avant
    assert _lire_sorties_evenement() == bus_avant
