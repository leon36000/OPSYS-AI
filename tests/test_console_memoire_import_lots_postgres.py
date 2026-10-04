"""Parcours console authentifiée -> lot PostgreSQL -> interruption -> reprise durable."""
from __future__ import annotations

import re

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
def console_admin(departements_demo, session, monkeypatch, url_pg):
    with session() as cnx:
        identite.creer_personne(cnx, "r26-admin", "Admin fictif", "mot-de-passe-admin-test-1234", ["admin"])
    monkeypatch.setenv("OPSYS_DATABASE_URL", url_pg)
    configuration = Configuration("console-import-lot-fixture-" + "x" * 40)
    app = application.creer_application(configuration, departements_demo, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        response = client.post("/connexion", data={"identifiant": "r26-admin",
                               "mot_de_passe": "mot-de-passe-admin-test-1234"}, follow_redirects=False)
        assert response.status_code == 303
        yield client


def _csrf(client):
    response = client.get("/api/session")
    assert response.status_code == 200
    return response.json()["csrf"]


def _cle_formulaire(client):
    page = client.get('/memoire/procedures/imports')
    assert page.status_code == 200
    match = re.search(r'name="cle_lot" value="([A-Za-z0-9_-]{16,128})"', page.text)
    assert match is not None, 'clé du lot conservée avant tout effet'
    return match.group(1)


def _sources():
    return {'source_1': ('a.txt', b'Regle fictive toiture.', 'text/plain'),
            'source_4': ('b.md', b'# Guide\n\nRegle fictive gouttieres.', 'text/markdown')}


def _champs(client, cle):
    return {'csrf': _csrf(client), 'cle_lot': cle, 'attestation': 'oui',
            'titre_1': 'Guide toiture fictif', 'titre_4': 'Guide gouttieres fictif'}


def test_lot_http_rejouable_et_recharge_depuis_un_nouveau_service_postgres(console_admin, url_pg):
    client = console_admin
    cle = _cle_formulaire(client)
    initial = MemoireEntreprise(url_pg).procedures().lister_series().total
    fields = _champs(client, cle)
    for _ in range(2):
        response = client.post('/memoire/procedures/imports/creer', data=fields, files=_sources())
        assert response.status_code == 200
        assert 'RECU 2' in response.text and 'ATTENTE 0' in response.text
    service = MemoireEntreprise(url_pg).procedures()
    lot = service.lire_lot(cle, auteur='r26-admin')
    assert [slot.position for slot in lot.emplacements] == [1, 4]
    assert all(slot.etat == 'RECU' and not slot.active for slot in lot.emplacements)
    assert service.lister_series().total == initial + 2
    page = client.get('/memoire/procedures/imports/' + cle)
    assert page.status_code == 200 and 'RECU 2' in page.text
    assert 'Regle fictive toiture.' not in page.text


def test_panne_apres_un_succes_et_reprise_seul_slot4_sans_nouvelle_version(
    console_admin, url_pg, monkeypatch
):
    client = console_admin
    cle = _cle_formulaire(client)
    reel = MemoireEntreprise(url_pg).procedures()
    initial = reel.lister_series().total

    original = IngestionProcedures.admettre_emplacement

    def interruption(self, cle_lot, position, contenu, *, auteur):
        if position == 4:
            raise MemoireIndisponible('panne PostgreSQL simulée après un vrai succès')
        return original(self, cle_lot, position, contenu, auteur=auteur)

    monkeypatch.setattr(IngestionProcedures, 'admettre_emplacement', interruption)
    response = client.post('/memoire/procedures/imports/creer', data=_champs(client, cle), files=_sources())
    assert response.status_code == 503
    assert cle in response.text and 'RECU 1' in response.text and 'ATTENTE 1' in response.text
    avant = MemoireEntreprise(url_pg).procedures().lire_lot(cle, auteur='r26-admin')
    premier_id = avant.emplacements[0].document_id
    assert premier_id is not None and avant.emplacements[1].document_id is None
    monkeypatch.setattr(IngestionProcedures, 'admettre_emplacement', original)
    response = client.post(
        f'/memoire/procedures/imports/{cle}/reprendre',
        data={'csrf': _csrf(client), 'cle_lot': cle, 'attestation': 'oui', 'titre_4': 'Guide gouttieres fictif'},
        files={'source_4': _sources()['source_4']},
    )
    assert response.status_code == 200 and 'RECU 2' in response.text
    apres = MemoireEntreprise(url_pg).procedures().lire_lot(cle, auteur='r26-admin')
    assert apres.emplacements[0].document_id == premier_id
    assert apres.emplacements[1].etat == 'RECU'
    assert MemoireEntreprise(url_pg).procedures().lister_series().total == initial + 2
