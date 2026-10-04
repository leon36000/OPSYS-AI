"""Parcours TestClient de l'usine de contenu et du calendrier M7 à partir d'un WCT fictif."""

from __future__ import annotations

import base64
import hashlib
import html
import struct
import zlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from m7_marketing import outils as outils_m7
from m7_marketing.brand import profil_client
from m7_marketing.usine import service as usine_service
from sqlalchemy import select

from opsys import contexte, fichiers, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES

SECRET = "secret-console-calendrier-fictif-2026-" + "x" * 32
PREFIXE = "/opsys"
MOT_DE_PASSE = "mot-de-passe-console-fictif-1234"
_OUTILS = {outil.nom: outil for outil in outils_m7.outils()}


def _wct_fictif() -> dict[str, object]:
    return {
        "wct_id": "wct-console-fictif-001",
        "intervention_id": "intervention-console-fictif-001",
        "lead_id": "lead-console-fictif-001",
        "technicien_id": "technicien-fictif",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 180,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "ab" * 32,
        "consommateurs_cibles": ["M7"],
        "devis_id": "devis-console-fictif-001",
        "statut": "completed_verified",
        "ville": "Repentigny",
        "type_travaux": "gouttières",
        "photos": ["photo-fictive-1", "photo-fictive-2"],
        "description_factuelle": "Installation terminée, sans imprévu.",
        "consentement_marketing": True,
        "client_satisfait": True,
        "consentement_recueilli_par": "technicien-fictif",
        "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
        "consentement_version_texte": "consentement-client-fr-CA-v1",
    }


def _png_fictif(pixel: bytes) -> bytes:
    def bloc(type_bloc: bytes, contenu: bytes) -> bytes:
        donnees = type_bloc + contenu
        return struct.pack(">I", len(contenu)) + donnees + struct.pack(">I", zlib.crc32(donnees))

    return (
        b"\x89PNG\r\n\x1a\n"
        + bloc(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + bloc(b"IDAT", zlib.compress(b"\x00" + pixel))
        + bloc(b"IEND", b"")
    )


@pytest.fixture
def client_calendrier(session, monkeypatch):
    profil = {
        "name": "Entreprise Fictive",
        "tagline": "Travaux extérieurs faits avec soin",
        "tone": "professionnel, factuel",
        "colors": ["#123456"],
        "langue": "fr",
        "site_url": "https://exemple-fictif.ca/",
        "heures_publication": {"facebook": "18:30"},
    }
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire fictive", MOT_DE_PASSE, ["admin"])
    with stockage.transaction():
        stockage.maillons(*usine_service.REGISTRE_WCT_RECUS).append(_wct_fictif())
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session
    )
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client: TestClient, utilisateur: str = "nathan") -> str:
    connexion = client.post(
        "/connexion",
        data={"identifiant": utilisateur, "mot_de_passe": MOT_DE_PASSE},
        follow_redirects=False,
    )
    assert connexion.status_code == 303, connexion.text
    return client.get("/api/session").json()["csrf"]


def _mutation(client: TestClient, csrf: str, **corps):
    return client.post(
        "/api/marketing/calendrier",
        json={**corps, "mutation_id": corps.get("mutation_id", "cal-ui-" + corps["action"])},
        headers={"x-csrf-token": csrf},
    )


def _proposer_contenus(client: TestClient, csrf: str):
    return _mutation(
        client,
        csrf,
        action="proposer_contenus",
        wct_id="wct-console-fictif-001",
        mutation_id="cal-ui-proposer-contenus",
    )


def _futur_iso() -> str:
    return (datetime.now(UTC) + timedelta(days=3)).astimezone(timezone(timedelta(hours=-4))).isoformat(
        timespec="seconds"
    )


def _preparer_contenu_approuve(client: TestClient, csrf: str) -> tuple[dict, dict]:
    propose = _proposer_contenus(client, csrf)
    assert propose.status_code == 200 and propose.json()["ok"] is True, propose.text
    lecture = client.get("/api/marketing/calendrier")
    assert lecture.status_code == 200, lecture.text
    contenu = next(
        item for item in lecture.json()["resultat"]["contenus"] if item["plateforme"] == "facebook"
    )
    tranche = _mutation(
        client,
        csrf,
        action="decider_contenu",
        contenu_id=contenu["contenu_id"],
        decision="approuver",
        mutation_id="cal-ui-approuver-contenu",
    )
    assert tranche.status_code == 200 and tranche.json()["ok"] is True, tranche.text
    return contenu, lecture.json()["resultat"]


def _preparer_creneau(client: TestClient, csrf: str) -> tuple[dict, dict]:
    contenu, _ = _preparer_contenu_approuve(client, csrf)
    proposition = _mutation(
        client,
        csrf,
        action="proposer_creneau",
        contenu_id=contenu["contenu_id"],
        planifie_le=_futur_iso(),
        mutation_id="cal-ui-proposer-creneau",
    )
    assert proposition.status_code == 200 and proposition.json()["ok"] is True, proposition.text
    creneau = proposition.json()["resultat"]["resultat"]["resultat"]
    decision = _mutation(
        client,
        csrf,
        action="decider_creneau",
        creneau_id=creneau["creneau_id"],
        decision="approuver",
        mutation_id="cal-ui-approuver-creneau",
    )
    assert decision.status_code == 200 and decision.json()["ok"] is True, decision.text
    return contenu, creneau


def _lire_registre(nom: str) -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _retrait_consentement():
    outil = _OUTILS["m7_enregistrer_retrait_consentement_marketing"]
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin")):
        return executer_atomique(
            outil,
            {
                "wct_id": "wct-console-fictif-001",
                "canal": "courriel",
                "horodatage": "2026-09-30T10:00:00-04:00",
            },
        )


def test_parcours_html_json_brouillons_approbations_et_remise_manuelle(client_calendrier):
    client = client_calendrier
    csrf = _connecter(client)
    page = client.get("/marketing/calendrier")
    assert page.status_code == 200 and "aria-current=\"page\"" in page.text
    assert "WCT reçu" in page.text and "Aucun créneau proposé" in page.text

    contenu, _ = _preparer_contenu_approuve(client, csrf)
    page = client.get("/marketing/calendrier")
    assert html.escape(contenu["texte"]) in page.text, page.text
    assert contenu["wct_id"] in page.text and "Approuvé par le propriétaire" in page.text
    assert "Proposer un créneau" in page.text

    creneau = _mutation(
        client,
        csrf,
        action="proposer_creneau",
        contenu_id=contenu["contenu_id"],
        planifie_le=_futur_iso(),
        mutation_id="cal-ui-html-proposer-slot",
    )
    assert creneau.status_code == 200 and creneau.json()["ok"] is True
    creneau_id = creneau.json()["resultat"]["resultat"]["resultat"]["creneau_id"]
    tranche = _mutation(
        client,
        csrf,
        action="decider_creneau",
        creneau_id=creneau_id,
        decision="approuver",
        mutation_id="cal-ui-html-approuver-slot",
    )
    assert tranche.status_code == 200 and tranche.json()["ok"] is True
    exporte = _mutation(
        client,
        csrf,
        action="exporter_creneau",
        creneau_id=creneau_id,
        mutation_id="cal-ui-html-export-slot",
    )
    assert exporte.status_code == 200 and exporte.json()["ok"] is True
    assert "non publiée" in exporte.text
    assert len(_lire_registre("exports_calendrier")) == 1


def test_formulaire_html_propose_depuis_wct_et_conserve_la_source(client_calendrier):
    client = client_calendrier
    csrf = _connecter(client)
    reponse = client.post(
        "/marketing/calendrier",
        data={
            "csrf": csrf,
            "action": "proposer_contenus",
            "wct_id": "wct-console-fictif-001",
            "mutation_id": "cal-ui-form-proposer",
        },
        follow_redirects=False,
    )

    assert reponse.status_code == 200
    assert 'role="status"' in reponse.text
    assert "facebook" in reponse.text and "WCT : wct-console-fictif-001" in reponse.text
    assert len(_lire_registre("contenus_chantier")) == 5


def test_export_html_affiche_le_paquet_complet_apres_double_approbation(client_calendrier):
    client = client_calendrier
    csrf = _connecter(client)
    contenu, creneau = _preparer_creneau(client, csrf)
    reponse = client.post(
        "/marketing/calendrier",
        data={
            "csrf": csrf,
            "action": "exporter_creneau",
            "creneau_id": creneau["creneau_id"],
            "mutation_id": "cal-ui-html-export-complet",
        },
        follow_redirects=False,
    )

    assert reponse.status_code == 200
    assert "Paquet remis pour copie manuelle" in reponse.text
    assert html.escape(contenu["texte"]) in reponse.text
    assert "M7 ne publie jamais" in reponse.text or "publication manuelle" in reponse.text.lower()
    assert len(_lire_registre("exports_calendrier")) == 1


def test_pagination_utilise_la_borne_canonique_de_huit_contenus(client_calendrier):
    client = client_calendrier
    csrf = _connecter(client)
    second = _wct_fictif()
    second["wct_id"] = "wct-console-fictif-002"
    second["lead_id"] = "lead-console-fictif-002"
    second["hash_maillon"] = "cd" * 32
    with stockage.transaction():
        stockage.maillons(*usine_service.REGISTRE_WCT_RECUS).append(second)
    for wct_id, mutation_id in (
        ("wct-console-fictif-001", "cal-ui-page-1"),
        ("wct-console-fictif-002", "cal-ui-page-2"),
    ):
        resultat = _mutation(
            client,
            csrf,
            action="proposer_contenus",
            wct_id=wct_id,
            mutation_id=mutation_id,
        )
        assert resultat.status_code == 200 and resultat.json()["ok"] is True, resultat.text

    premiere = client.get("/api/marketing/calendrier")
    prochain = premiere.json()["resultat"]["pagination"]["suivant"]
    seconde = client.get(f"/api/marketing/calendrier?decalage={prochain}")

    assert 1 <= len(premiere.json()["resultat"]["contenus"]) <= 8
    assert premiere.json()["resultat"]["pagination"] == {
        "total": 10,
        "decalage": 0,
        "suivant": prochain,
        "reste": 10 - len(premiere.json()["resultat"]["contenus"]),
    }
    assert len(seconde.json()["resultat"]["contenus"]) <= 8
    assert len(premiere.json()["resultat"]["contenus"]) + len(seconde.json()["resultat"]["contenus"]) == 10
    assert "Suivant" in client.get("/marketing/calendrier").text
    assert "Suivant" not in client.get(f"/marketing/calendrier?decalage={prochain}").text


def test_cle_idempotence_console_est_portee_par_l_utilisateur(client_calendrier, session):
    client = client_calendrier
    csrf_owner = _connecter(client)
    premiere = _mutation(
        client,
        csrf_owner,
        action="proposer_contenus",
        wct_id="wct-console-fictif-001",
        mutation_id="cle-identique-deux-personnes",
    )
    assert premiere.status_code == 200 and premiere.json()["ok"] is True
    csrf_admin = _connecter(client, "gestionnaire")
    seconde = _mutation(
        client,
        csrf_admin,
        action="proposer_contenus",
        wct_id="wct-console-fictif-001",
        mutation_id="cle-identique-deux-personnes",
    )

    assert seconde.status_code == 200 and seconde.json()["ok"] is True
    with session() as cnx:
        mutations = cnx.execute(
            select(MUTATIONS_APPLIQUEES).where(
                MUTATIONS_APPLIQUEES.c.outil == "m7_proposer_contenus_chantier"
            )
        ).mappings().all()
    assert len(mutations) == 2
    assert {row["appareil"] for row in mutations} == {"console:nathan", "console:gestionnaire"}


def test_retrait_consentement_apres_affichage_bloque_export_et_approbation_echec(client_calendrier, session):
    client = client_calendrier
    csrf = _connecter(client)
    _, creneau = _preparer_creneau(client, csrf)
    page = client.get("/marketing/calendrier")
    assert page.status_code == 200 and creneau["creneau_id"] in page.text
    avant = len(_lire_registre("exports_calendrier"))

    retrait = _retrait_consentement()
    assert retrait["ok"] is True and retrait["resultat"]["accepte"] is True
    exporte = _mutation(
        client,
        csrf,
        action="exporter_creneau",
        creneau_id=creneau["creneau_id"],
        mutation_id="cal-ui-export-apres-retrait",
    )

    assert exporte.status_code == 409 and exporte.json()["ok"] is False
    assert len(_lire_registre("exports_calendrier")) == avant
    with session() as cnx:
        approbations = cnx.execute(
            select(APPROBATIONS).where(APPROBATIONS.c.outil == "m7_exporter_creneau_manuel")
        ).mappings().all()
    assert len(approbations) == 1 and approbations[0]["statut"] == "echec"
    assert '"accepte": false' in approbations[0]["resultat"]


def test_retrait_role_apres_page_refuse_api_sans_mutation(client_calendrier, session):
    client = client_calendrier
    csrf = _connecter(client)
    _, creneau = _preparer_creneau(client, csrf)
    assert client.get("/marketing/calendrier").status_code == 200
    with session() as cnx:
        identite.retirer_role(cnx, "nathan", "nathan_owner")
    with session() as cnx:
        approbations_avant = [dict(row) for row in cnx.execute(select(APPROBATIONS)).mappings()]
        mutations_avant = [dict(row) for row in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings()]
    calendrier_avant = _lire_registre("calendrier_contenus")

    exporte = _mutation(
        client,
        csrf,
        action="exporter_creneau",
        creneau_id=creneau["creneau_id"],
        mutation_id="cal-ui-export-role-retire",
    )

    assert exporte.status_code == 403
    assert _lire_registre("calendrier_contenus") == calendrier_avant
    assert _lire_registre("exports_calendrier") == []
    with session() as cnx:
        assert [dict(row) for row in cnx.execute(select(APPROBATIONS)).mappings()] == approbations_avant
        assert [dict(row) for row in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings()] == mutations_avant


def test_csrf_est_verifie_avant_analyse_json_et_acteur_admin_non_proprietaire_echoue(
    client_calendrier, session
):
    client = client_calendrier
    csrf_owner = _connecter(client)
    raw = client.post("/api/marketing/calendrier", content=b"not-json")
    assert raw.status_code == 403
    assert _proposer_contenus(client, csrf_owner).status_code == 200
    contenu = next(
        item for item in client.get("/api/marketing/calendrier").json()["resultat"]["contenus"]
        if item["plateforme"] == "facebook"
    )
    csrf_admin = _connecter(client, "gestionnaire")
    with session() as cnx:
        approbations_avant = [dict(row) for row in cnx.execute(select(APPROBATIONS)).mappings()]
        mutations_avant = [dict(row) for row in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings()]
    decision = _mutation(
        client,
        csrf_admin,
        action="decider_contenu",
        contenu_id=contenu["contenu_id"],
        decision="rejeter",
        mutation_id="cal-ui-non-owner-decision",
    )

    assert decision.status_code == 403 and decision.json()["ok"] is False, decision.text
    decision_html = client.post(
        "/marketing/calendrier",
        data={
            "csrf": csrf_admin,
            "action": "decider_contenu",
            "contenu_id": contenu["contenu_id"],
            "decision": "rejeter",
            "mutation_id": "cal-ui-non-owner-decision-form",
        },
        follow_redirects=False,
    )
    assert decision_html.status_code == 403 and 'role="alert"' in decision_html.text
    assert _lire_registre("decisions_contenu") == []
    with session() as cnx:
        assert [dict(row) for row in cnx.execute(select(APPROBATIONS)).mappings()] == approbations_avant
        assert [dict(row) for row in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings()] == mutations_avant


@pytest.mark.parametrize("corps", [
    {"action": "decider_contenu", "contenu_id": "x", "decision": "approve", "mutation_id": "m"},
    {"action": "proposer_creneau", "contenu_id": "x", "planifie_le": "2030-01-01T12:00:00", "mutation_id": "m"},
    {"action": "exporter_creneau", "creneau_id": "x", "mutation_id": "m", "publication": True},
])
def test_commande_rejette_enum_fuseau_et_champ_extra_sans_mutation(client_calendrier, corps):
    client = client_calendrier
    csrf = _connecter(client)
    resultat = client.post(
        "/api/marketing/calendrier",
        json=corps,
        headers={"x-csrf-token": csrf},
    )

    assert resultat.status_code == 400
    assert _lire_registre("decisions_contenu") == []
    assert _lire_registre("calendrier_contenus") == []
    assert _lire_registre("exports_calendrier") == []


def test_wct_absent_est_rendu_comme_refus_sans_creation_de_contenu(client_calendrier):
    client = client_calendrier
    csrf = _connecter(client)
    resultat = _mutation(
        client,
        csrf,
        action="proposer_contenus",
        wct_id="wct-inconnu-fictif",
        mutation_id="cal-ui-wct-inconnu",
    )

    assert resultat.status_code == 409 and resultat.json()["ok"] is False
    assert "aucun m4.travaux_termines reçu" in resultat.json()["erreur"]["message"]
    assert _lire_registre("contenus_chantier") == []


def test_api_dossier_medias_expose_metadonnees_sans_charge_wct(client_calendrier, monkeypatch):
    client = client_calendrier
    csrf = _connecter(client)
    octets_source = _png_fictif(b"\x11\x22\x33")
    empreinte = hashlib.sha256(octets_source).hexdigest()
    reference = fichiers.reference_pour(empreinte)
    wct = _wct_fictif()
    wct.update({
        "wct_id": "wct-media-metadata-fictif",
        "photos": [reference],
        "description_factuelle": "SECRET-WCT-NE-DOIT-PAS-ETRE-RENVOYE",
    })
    with stockage.transaction():
        cnx = stockage.connexion_courante()
        depot = fichiers.deposer_bloc(
            cnx, empreinte, len(octets_source), "image/png", 0, 1,
            base64.b64encode(octets_source).decode("ascii"),
        )
        assert depot.accepte and depot.complet
        stockage.maillons(*usine_service.REGISTRE_WCT_RECUS).append(wct)

    proposition = _mutation(
        client, csrf, action="proposer_contenus", wct_id=wct["wct_id"],
        mutation_id="media-metadata-proposer",
    )
    assert proposition.status_code == 200, proposition.text
    contenus = client.get("/api/marketing/calendrier").json()["resultat"]["contenus"]
    contenu = next(item for item in contenus if item["wct_id"] == wct["wct_id"])

    reponse = client.get(f"/api/marketing/calendrier/medias/{contenu['contenu_id']}")

    assert reponse.status_code == 200, reponse.text
    resultat = reponse.json()["resultat"]["resultat"]
    assert resultat["wct_id"] == wct["wct_id"]
    assert resultat["sources"] == [{
        "source_ref": reference,
        "source_sha256": empreinte,
        "type_mime": "image/png",
        "taille": len(octets_source),
    }]
    assert "snapshot" not in resultat
    assert "SECRET-WCT-NE-DOIT-PAS-ETRE-RENVOYE" not in reponse.text
    assert "fix_gps_completion" not in reponse.text
    assert reponse.headers["cache-control"] == "private, no-store, max-age=0"

    contenu_approuve = _mutation(
        client, csrf, action="decider_contenu", contenu_id=contenu["contenu_id"],
        decision="approuver", mutation_id="media-metadata-approve-content",
    )
    assert contenu_approuve.status_code == 200, contenu_approuve.text
    slot_propose = _mutation(
        client, csrf, action="proposer_creneau", contenu_id=contenu["contenu_id"],
        planifie_le=_futur_iso(), mutation_id="media-metadata-propose-slot",
    )
    assert slot_propose.status_code == 200, slot_propose.text
    creneau_id = slot_propose.json()["resultat"]["resultat"]["resultat"]["creneau_id"]
    slot_approuve = _mutation(
        client, csrf, action="decider_creneau", creneau_id=creneau_id,
        decision="approuver", mutation_id="media-metadata-approve-slot",
    )
    assert slot_approuve.status_code == 200, slot_approuve.text

    octets_prepares = _png_fictif(b"\x44\x55\x66")
    sha_prepares = hashlib.sha256(octets_prepares).hexdigest()
    televersement = client.post(
        "/api/marketing/calendrier/medias",
        data={
            "mutation_id": "media-metadata-upload",
            "contenu_id": contenu["contenu_id"],
            "source_ref": reference,
            "revision_attendue": str(resultat["revision"]),
            "empreinte_attendue": resultat["empreinte_dossier"],
            "snapshot_attendu": resultat["snapshot_sha256"],
            "attestation_humaine": "Préparé manuellement pour le test fictif.",
        },
        files={"fichier": ("prepared.png", octets_prepares, "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert televersement.status_code == 200 and televersement.json()["ok"] is True, televersement.text
    dossier = client.get(f"/api/marketing/calendrier/medias/{contenu['contenu_id']}").json()
    courant = dossier["resultat"]["resultat"]
    assert courant["medias"][0]["prepared_sha256"] == sha_prepares
    decision_media = _mutation(
        client, csrf, action="decider_medias", contenu_id=contenu["contenu_id"],
        decision="approuver", revision_attendue=courant["revision"],
        empreinte_attendue=courant["empreinte_dossier"], snapshot_attendu=courant["snapshot_sha256"],
        attestation_humaine="Visages, plaques, adresse et EXIF vérifiés manuellement.",
        mutation_id="media-metadata-review",
    )
    assert decision_media.status_code == 200 and decision_media.json()["ok"] is True, decision_media.text
    dossier_approuve = client.get(f"/api/marketing/calendrier/medias/{contenu['contenu_id']}").json()
    assert dossier_approuve["ok"] is True, (dossier_approuve, _lire_registre("dossiers_medias"))
    assert dossier_approuve["resultat"]["resultat"]["statut"] == "APPROUVE", dossier_approuve

    lire_service = usine_service._lire

    def lire_texte_altere(nom):
        maillons = lire_service(nom)
        if nom != usine_service.REGISTRE_CONTENUS_CHANTIER:
            return maillons
        return [
            {**maillon, "texte": "x" * 9000}
            if maillon.get("contenu_id") == contenu["contenu_id"] else maillon
            for maillon in maillons
        ]

    maillons_medias_avant = len(_lire_registre("dossiers_medias"))
    exports_avant = len(_lire_registre("exports_paquet"))
    monkeypatch.setattr(usine_service, "_lire", lire_texte_altere)
    remise_texte_altere = _mutation(
        client, csrf, action="remettre_medias", creneau_id=creneau_id,
        mutation_id="media-metadata-handoff-texte-altere",
    )
    assert remise_texte_altere.status_code == 409, remise_texte_altere.text
    assert remise_texte_altere.json()["erreur"]["message"]
    assert len(_lire_registre("dossiers_medias")) == maillons_medias_avant
    assert len(_lire_registre("exports_paquet")) == exports_avant
    monkeypatch.setattr(usine_service, "_lire", lire_service)

    remise = _mutation(
        client, csrf, action="remettre_medias", creneau_id=creneau_id,
        mutation_id="media-metadata-handoff",
    )
    assert remise.status_code == 200 and remise.json()["ok"] is True, remise.text
    media_reference = "fichier:sha256:" + sha_prepares
    binaire = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": media_reference, "mode": "remise"},
    )
    assert binaire.status_code == 200 and binaire.content == octets_prepares
    assert binaire.headers["cache-control"] == "private, no-store, max-age=0"
    assert binaire.headers["x-content-type-options"] == "nosniff"

    monkeypatch.setattr(usine_service, "_lire", lire_texte_altere)
    refus_binaire_texte_altere = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": media_reference, "mode": "remise"},
    )
    assert refus_binaire_texte_altere.status_code == 404
    monkeypatch.setattr(usine_service, "_lire", lire_service)

    nombre_maillons_avant_reemission = len(_lire_registre("dossiers_medias"))
    exports_avant_reemission = len(_lire_registre("exports_paquet"))
    reemission = _mutation(
        client, csrf, action="remettre_medias", creneau_id=creneau_id,
        mutation_id="media-metadata-handoff-nouvelle-cle",
    )

    assert reemission.status_code == 200 and reemission.json()["ok"] is True, reemission.text
    assert len(_lire_registre("dossiers_medias")) == nombre_maillons_avant_reemission
    assert len(_lire_registre("exports_paquet")) == exports_avant_reemission
    reemission_resultat = reemission.json()["resultat"]["resultat"]["resultat"]
    premiere_remise = remise.json()["resultat"]["resultat"]["resultat"]["remise"]
    assert reemission_resultat["remise"]["media_export_id"] == premiere_remise["media_export_id"]
    binaire_reemis = client.get(
        f"/marketing/calendrier/medias/{contenu['contenu_id']}",
        params={"reference": media_reference, "mode": "remise"},
    )
    assert binaire_reemis.status_code == 200 and binaire_reemis.content == octets_prepares
