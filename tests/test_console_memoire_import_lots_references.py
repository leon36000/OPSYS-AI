"""Reprise depuis Mes imports : nouveau navigateur, propriétaire et PostgreSQL réel."""
from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys import identite
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.memoire.ingestion_procedures import IngestionProcedures
from opsys.memoire.store import MemoireEntreprise, MemoireIndisponible


@pytest.fixture(scope="module")
def url_pg():
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        MemoireEntreprise(url).migrer()
        yield url


@pytest.fixture
def navigateurs(request, departements_demo, session, monkeypatch, url_pg):
    suffixe = hashlib.sha256(request.node.name.encode()).hexdigest()[:12]
    comptes = ("ref-a-" + suffixe, "ref-b-" + suffixe)
    password_fictif = "mot-de-passe-fictif-reference-1234"
    with session() as cnx:
        for compte in comptes:
            identite.creer_personne(cnx, compte, "Compte de test fictif", password_fictif, ["admin"])
    monkeypatch.setenv("OPSYS_DATABASE_URL", url_pg)
    configuration = Configuration("console-reference-fixture-" + "x" * 40)

    @contextmanager
    def ouvrir(compte):
        app = application.creer_application(configuration, departements_demo, session)
        with TestClient(app, base_url="https://testserver/opsys") as client:
            response = client.post("/connexion", data={"identifiant": compte, "mot_de_passe": password_fictif},
                                   follow_redirects=False)
            assert response.status_code == 303
            yield client

    return ouvrir, comptes


def _csrf(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    return response.json()["csrf"]


def _cle(client):
    page = client.get("/memoire/procedures/imports")
    assert page.status_code == 200
    match = re.search(r'name="cle_lot" value="([A-Za-z0-9_-]{16,128})"', page.text)
    assert match is not None
    return match.group(1)


def _reference_page(client):
    page = client.get("/memoire/procedures/imports")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    match = re.search(r'href="/opsys/memoire/procedures/imports/ref/([0-9a-f]{64})"', page.text)
    assert match is not None
    return match.group(1), page.text


def _admettre_un(client, titre="Guide privé fictif"):
    cle = _cle(client)
    response = client.post(
        "/memoire/procedures/imports/creer",
        data={"csrf": _csrf(client), "attestation": "oui", "cle_lot": cle, "titre_1": titre},
        files={"source_1": ("source.txt", b"Procedure interne fictive.", "text/plain")},
    )
    assert response.status_code == 200
    return cle


def test_nouveau_navigateur_retrouve_et_reprend_lot_sans_cle_initiale(navigateurs, url_pg, monkeypatch):
    ouvrir, (auteur, _) = navigateurs
    original = IngestionProcedures.admettre_emplacement
    fichiers = {"source_1": ("first.txt", b"Source fictive une.", "text/plain"),
                "source_4": ("last.txt", b"Source fictive quatre.", "text/plain")}

    def panne(self, cle_lot, position, contenu, *, auteur):
        if position == 4:
            raise MemoireIndisponible("panne de test après un vrai premier succès")
        return original(self, cle_lot, position, contenu, auteur=auteur)

    with ouvrir(auteur) as premier:
        cle = _cle(premier)
        monkeypatch.setattr(IngestionProcedures, "admettre_emplacement", panne)
        response = premier.post(
            "/memoire/procedures/imports/creer",
            data={"csrf": _csrf(premier), "attestation": "oui", "cle_lot": cle,
                  "titre_1": "Guide premier fictif", "titre_4": "Guide suivant fictif"}, files=fichiers,
        )
        assert response.status_code == 503 and "RECU 1" in response.text and "ATTENTE 1" in response.text
    monkeypatch.setattr(IngestionProcedures, "admettre_emplacement", original)

    with ouvrir(auteur) as nouveau:
        reference, liste = _reference_page(nouveau)
        assert cle not in liste
        assert "RECU 1" in liste and "ATTENTE 1" in liste
        page = nouveau.get(f"/memoire/procedures/imports/ref/{reference}")
        assert page.status_code == 200
        assert cle not in page.text
        assert f'/imports/ref/{reference}/reprendre' in page.text
        service = MemoireEntreprise(url_pg).procedures()
        avant = service.lire_lot_reference(reference, auteur=auteur)
        premier_id = avant.emplacements[0].document_id
        assert premier_id is not None and avant.emplacements[1].etat == "ATTENTE"
        response = nouveau.post(
            f"/memoire/procedures/imports/ref/{reference}/reprendre",
            data={"csrf": _csrf(nouveau), "attestation": "oui", "cle_lot": reference,
                  "titre_4": "Guide suivant fictif"}, files={"source_4": fichiers["source_4"]},
        )
        assert response.status_code == 200 and "RECU 2" in response.text
        apres = MemoireEntreprise(url_pg).procedures().lire_lot_reference(reference, auteur=auteur)
        assert apres.emplacements[0].document_id == premier_id
        assert apres.emplacements[1].etat == "RECU"
        assert len(service.lister_versions(premier_id)) == 1
        reference_rechargee, liste = _reference_page(nouveau)
        assert reference_rechargee == reference and "RECU 2" in liste and "ATTENTE 0" in liste


def test_autre_auteur_ne_voit_ni_ne_reprend_la_reference(navigateurs, url_pg):
    ouvrir, (auteur, autre) = navigateurs
    with ouvrir(auteur) as proprietaire:
        cle = _admettre_un(proprietaire)
        reference, _ = _reference_page(proprietaire)
    with ouvrir(autre) as tiers:
        page = tiers.get("/memoire/procedures/imports")
        assert page.status_code == 200
        assert reference not in page.text and cle not in page.text
        page = tiers.get(f"/memoire/procedures/imports/ref/{reference}")
        assert page.status_code == 404 and "Guide privé fictif" not in page.text
        response = tiers.post(
            f"/memoire/procedures/imports/ref/{reference}/reprendre",
            data={"csrf": _csrf(tiers), "attestation": "oui", "cle_lot": reference,
                  "titre_1": "Guide privé fictif"},
            files={"source_1": ("source.txt", b"Procedure interne fictive.", "text/plain")},
        )
        assert response.status_code == 404
        assert "Guide privé fictif" not in response.text
    lot = MemoireEntreprise(url_pg).procedures().lire_lot(cle, auteur=auteur)
    assert lot.emplacements[0].etat == "RECU"
    assert len(MemoireEntreprise(url_pg).procedures().lister_versions(lot.emplacements[0].document_id)) == 1


def test_index_activation_et_oubli_actualisent_liste_et_bloquent_reprise(navigateurs, url_pg):
    ouvrir, (auteur, _) = navigateurs
    service = MemoireEntreprise(url_pg).procedures()
    with ouvrir(auteur) as client:
        cle = _admettre_un(client)
        reference, _ = _reference_page(client)
        slot = service.lire_lot(cle, auteur=auteur).emplacements[0]
        service.indexer(slot.document_id, slot.sha256)
        _, page = _reference_page(client)
        assert "INDEXE 1" in page and "actifs 0" in page
        service.activer(slot.document_id, slot.sha256, attendu_sha256=None, auteur=auteur)
        _, page = _reference_page(client)
        assert "INDEXE 1" in page and "actifs 1" in page
        service.oublier(slot.document_id, demandeur=auteur, motif="effacement source fictive de test")
        page = client.get("/memoire/procedures/imports")
        assert page.status_code == 200 and reference not in page.text
        assert client.get(f"/memoire/procedures/imports/ref/{reference}").status_code == 404
        response = client.post(
            f"/memoire/procedures/imports/ref/{reference}/reprendre",
            data={"csrf": _csrf(client), "attestation": "oui", "cle_lot": reference,
                  "titre_1": "Guide privé fictif"},
            files={"source_1": ("source.txt", b"Procedure interne fictive.", "text/plain")},
        )
        assert response.status_code == 404
        assert service.lister_lots(auteur=auteur) == ()


@pytest.mark.parametrize("reference", ["bad", "F" * 64, "0" * 64])
def test_reference_malformee_ou_absente_sans_effect(navigateurs, url_pg, reference):
    ouvrir, (auteur, _) = navigateurs
    with ouvrir(auteur) as client:
        assert client.get(f"/memoire/procedures/imports/ref/{reference}").status_code == 404
        response = client.post(
            f"/memoire/procedures/imports/ref/{reference}/reprendre",
            data={"csrf": _csrf(client), "attestation": "oui", "cle_lot": reference, "titre_1": "Fictif"},
            files={"source_1": ("source.txt", b"Procedure fictive.", "text/plain")},
        )
        assert response.status_code == 404
    assert MemoireEntreprise(url_pg).procedures().lister_lots(auteur=auteur) == ()


def test_reprise_reference_refuse_csrf_et_source_modifiee_sans_nouvelle_version(navigateurs, url_pg):
    ouvrir, (auteur, _) = navigateurs
    with ouvrir(auteur) as client:
        cle = _admettre_un(client)
        reference, _ = _reference_page(client)
        path = f"/memoire/procedures/imports/ref/{reference}/reprendre"
        champs = {"csrf": "jeton-faux", "attestation": "oui", "cle_lot": reference,
                  "titre_1": "Guide privé fictif"}
        sources = {"source_1": ("source.txt", b"Procedure interne fictive.", "text/plain")}
        assert client.post(path, data=champs, files=sources).status_code == 403
        champs["csrf"] = _csrf(client)
        sources["source_1"] = ("source.txt", b"Autre source fictive.", "text/plain")
        assert client.post(path, data=champs, files=sources).status_code == 409
    service = MemoireEntreprise(url_pg).procedures()
    lot = service.lire_lot(cle, auteur=auteur)
    assert lot.emplacements[0].etat == "RECU"
    assert len(service.lister_versions(lot.emplacements[0].document_id)) == 1
