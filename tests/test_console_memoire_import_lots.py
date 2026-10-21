"""Contrat HTTP de reprise des lots M03, avec façade isolée de PostgreSQL."""

from __future__ import annotations

import hashlib
import re
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from opsys.console import memoire_ingestion_ui
from opsys.console.securite import Session
from opsys.memoire.ingestion_procedures import EmplacementLot, LotProcedure, ResumeLot
from opsys.memoire.store import MemoireIndisponible


class _FacadeLots:
    def __init__(self):
        self.lots: dict[str, LotProcedure] = {}
        self.mutations: list[tuple[str, int | None]] = []
        self.manifests = {}
        self.versions = {}
        self.echec_position: int | None = None
        self.lecture_indisponible = False
        self.retrait_role_apres_premier = False
        self.retirer_role = None

    def lister_lots(self, *, auteur):
        return tuple(
            ResumeLot(
                hashlib.sha256(cle.encode()).hexdigest(), len(lot.emplacements),
                sum(s.etat == "ATTENTE" for s in lot.emplacements),
                sum(s.etat == "RECU" for s in lot.emplacements),
                sum(s.etat == "INDEXE" for s in lot.emplacements),
                sum(s.active for s in lot.emplacements),
            )
            for cle, lot in self.lots.items() if lot.auteur == auteur
        )

    def creer_lot(self, cle_lot, sources, *, auteur):
        self.mutations.append(("creer", None))
        manifest = tuple(sources)
        if cle_lot in self.manifests:
            if self.manifests[cle_lot] != manifest:
                raise ValueError("conflit de manifeste")
            return self.lots[cle_lot]
        self.manifests[cle_lot] = manifest
        slots = tuple(
            EmplacementLot(source.position, source.titre, source.sha256, source.serie_cible_id, None, "ATTENTE", False)
            for source in sources
        )
        self.lots[cle_lot] = LotProcedure(cle_lot, auteur, slots)
        return self.lots[cle_lot]

    def admettre_emplacement(self, cle_lot, position, contenu, *, auteur):
        if self.echec_position == position:
            self.echec_position = None
            self.lecture_indisponible = True
            raise TimeoutError("erreur backend détaillée non exposée")
        lot = self.lots[cle_lot]
        old = next(slot for slot in lot.emplacements if slot.position == position)
        assert hashlib.sha256(contenu).hexdigest() == old.sha256
        if old.etat != "ATTENTE":
            return lot
        slots = tuple(
            EmplacementLot(
                slot.position, slot.titre, slot.sha256, slot.serie_cible_id,
                f"doc-{slot.position}" if slot.position == position else slot.document_id,
                "RECU" if slot.position == position else slot.etat,
                slot.active,
            )
            for slot in lot.emplacements
        )
        self.lots[cle_lot] = LotProcedure(cle_lot, auteur, slots)
        self.mutations.append(("admettre", position))
        self.versions[(cle_lot, position)] = self.versions.get((cle_lot, position), 0) + 1
        if self.retrait_role_apres_premier and len([event for event in self.mutations if event[0] == "admettre"]) == 1:
            self.retirer_role()
        return self.lots[cle_lot]

    def lire_lot(self, cle_lot, *, auteur):
        if self.lecture_indisponible:
            self.lecture_indisponible = False
            raise RuntimeError("stockage indisponible")
        lot = self.lots.get(cle_lot)
        if lot is None or lot.auteur != auteur:
            raise ValueError("lot absent")
        return lot


@pytest.fixture
def console_lots(monkeypatch):
    service = _FacadeLots()
    active = {"admin": True}
    session = Session("admin", frozenset({"admin"}), "csrf-import-lots", int(time.time()) + 3600)

    def session_page(request, *, administrateur=True):
        if not active["admin"]:
            raise HTTPException(403, "administration retirée")
        return session

    service.retirer_role = lambda: active.__setitem__("admin", False)
    monkeypatch.setattr(memoire_ingestion_ui, "_service", lambda: service)
    app = FastAPI()
    app.include_router(memoire_ingestion_ui.creer_router(session_page=session_page, prefixe=""))
    with TestClient(app) as client:
        yield client, service, active


def _fields(*, csrf="csrf-import-lots", **titles):
    fields = {"csrf": csrf, "attestation": "oui"}
    cle_lot = titles.pop("cle_lot", None)
    if cle_lot is not None:
        fields["cle_lot"] = cle_lot
    fields.update({f"titre_{position}": title for position, title in titles.items()})
    return fields


def _cle(client):
    response = client.get("/memoire/procedures/imports")
    assert response.status_code == 200
    match = re.search(r'name="cle_lot" value="([A-Za-z0-9_-]{16,128})"', response.text)
    assert match is not None
    return match.group(1)


def _files(*sources):
    return [(f"source_{position}", (filename, content, mime)) for position, filename, content, mime in sources]


@pytest.mark.parametrize("dernier", [b"\xff invalide", b"texte\x00 invalide"])
def test_creation_valide_tous_les_fichiers_avant_le_premier_dml(console_lots, dernier):
    client, service, _ = console_lots
    cle = _cle(client)
    response = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot=cle, **{"1": "Guide sûr", "2": "Autre guide"}),
        files=_files(
            (1, "guide.txt", "procédure ok".encode(), "text/plain"),
            (2, "dernier.txt", dernier, "text/plain"),
        ),
    )
    assert response.status_code == 400
    assert service.mutations == []
    assert "dernier.txt" not in response.text
    assert "invalide" not in response.text


def test_creation_refuse_champs_inconnus_et_doublons_sans_mutation(console_lots):
    client, service, _ = console_lots
    cle = _cle(client)
    unknown = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot=cle, **{"1": "Guide", "acteur": "forgé"}),
        files=_files((1, "guide.txt", b"texte", "text/plain")),
    )
    duplicate = client.post(
        "/memoire/procedures/imports/creer",
        files=[(name, (None, value)) for name, value in
               [*_fields(cle_lot=cle, **{"1": "Guide"}).items(), ("titre_1", "autre")]]
        + _files((1, "guide.txt", b"texte", "text/plain")),
    )
    assert unknown.status_code == duplicate.status_code == 400
    assert service.mutations == []


def test_cle_formulaire_malformee_refusee_avant_dml(console_lots):
    client, service, _ = console_lots
    response = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot="bad", **{"1": "Guide"}),
        files=_files((1, "guide.txt", b"texte", "text/plain")),
    )
    assert response.status_code == 400
    assert service.mutations == []


def test_double_post_meme_cle_et_manifest_ne_duplique_pas_les_versions(console_lots):
    client, service, _ = console_lots
    cle = _cle(client)
    fields = _fields(cle_lot=cle, **{"1": "Guide stable"})
    files = _files((1, "guide.txt", b"texte stable", "text/plain"))
    first = client.post("/memoire/procedures/imports/creer", data=fields, files=files)
    second = client.post("/memoire/procedures/imports/creer", data=fields, files=files)
    assert first.status_code == second.status_code == 200
    assert service.versions == {(cle, 1): 1}
    assert len(service.lots[cle].emplacements) == 1


def test_role_retire_entre_deux_emplacements_arrete_le_lot_apres_le_premier(console_lots):
    client, service, _ = console_lots
    cle = _cle(client)
    service.retrait_role_apres_premier = True
    response = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot=cle, **{"1": "Guide 1", "2": "Guide 2"}),
        files=_files(
            (1, "one.txt", b"un", "text/plain"),
            (2, "two.txt", b"deux", "text/plain"),
        ),
    )
    assert response.status_code == 403
    assert [event for event in service.mutations if event[0] == "admettre"] == [("admettre", 1)]
    assert sum(slot.etat == "RECU" for lot in service.lots.values() for slot in lot.emplacements) == 1


def test_timeout_puis_reprise_accepte_seulement_le_slot_2_exact(console_lots):
    client, service, _ = console_lots
    cle_form = _cle(client)
    service.echec_position = 2
    initial = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot=cle_form, **{"1": "Guide 1", "2": "Guide 2"}),
        files=_files(
            (1, "one.txt", b"un", "text/plain"),
            (2, "two.txt", b"deux", "text/plain"),
        ),
    )
    assert initial.status_code == 503
    assert f"/memoire/procedures/imports/{cle_form}" in initial.text
    key = cle_form
    state = client.get(f"/memoire/procedures/imports/{key}")
    assert state.status_code == 200
    assert [slot.etat for slot in service.lots[key].emplacements] == ["RECU", "ATTENTE"]

    wrong = client.post(
        f"/memoire/procedures/imports/{key}/reprendre",
        data=_fields(cle_lot=key, **{"2": "Guide 2"}),
        files=_files((2, "changed.txt", b"autre", "text/plain")),
    )
    assert wrong.status_code == 409
    assert [event for event in service.mutations if event[0] == "admettre"] == [("admettre", 1)]

    resumed = client.post(
        f"/memoire/procedures/imports/{key}/reprendre",
        data=_fields(cle_lot=key, **{"2": "Guide 2"}),
        files=_files((2, "two.txt", b"deux", "text/plain")),
    )
    assert resumed.status_code == 200
    assert [event for event in service.mutations if event[0] == "admettre"] == [("admettre", 1), ("admettre", 2)]
    assert [slot.etat for slot in service.lots[key].emplacements] == ["RECU", "RECU"]


def test_session_csrf_et_entetes_prives(console_lots):
    client, _, _ = console_lots
    page = client.get("/memoire/procedures/imports")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    query = client.get("/memoire/procedures/imports?cle=forgee")
    assert query.status_code == 400


@pytest.mark.parametrize("action", ["creer", "reprendre"])
def test_csrf_invalide_refuse_creation_et_reprise_avant_toute_mutation(console_lots, action):
    client, service, _ = console_lots
    cle = _cle(client)
    path = "/memoire/procedures/imports/creer" if action == "creer" else f"/memoire/procedures/imports/{cle}/reprendre"
    response = client.post(
        path, data=_fields(csrf="faux-jeton", cle_lot=cle, **{"1": "Guide"}),
        files=_files((1, "guide.txt", b"texte", "text/plain")),
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert service.mutations == []


def test_attestation_absente_refuse_avant_dml(console_lots):
    client, service, _ = console_lots
    fields = _fields(cle_lot=_cle(client), **{"1": "Guide"})
    fields.pop("attestation")
    response = client.post(
        "/memoire/procedures/imports/creer", data=fields,
        files=_files((1, "guide.txt", b"texte", "text/plain")),
    )
    assert response.status_code == 400
    assert service.mutations == []


def test_panne_memoire_valueerror_reste_503_sur_la_lecture(console_lots, monkeypatch):
    client, service, _ = console_lots
    cle = _cle(client)

    def panne(*args, **kwargs):
        raise MemoireIndisponible("détail privé de configuration PostgreSQL")

    monkeypatch.setattr(service, "lire_lot", panne)
    response = client.get(f"/memoire/procedures/imports/{cle}")
    assert response.status_code == 503
    assert "PostgreSQL" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert service.mutations == []


def test_retrait_role_pendant_lecture_ne_revele_pas_le_manifeste(console_lots, monkeypatch):
    client, service, active = console_lots
    cle = _cle(client)
    response = client.post(
        "/memoire/procedures/imports/creer", data=_fields(cle_lot=cle, **{"1": "Titre confidentiel fictif"}),
        files=_files((1, "guide.txt", b"source interne fictive", "text/plain")),
    )
    assert response.status_code == 200
    original = service.lire_lot

    def retirer_pendant_lecture(*args, **kwargs):
        lot = original(*args, **kwargs)
        active["admin"] = False
        return lot

    monkeypatch.setattr(service, "lire_lot", retirer_pendant_lecture)
    response = client.get(f"/memoire/procedures/imports/{cle}")
    assert response.status_code == 403
    assert "Titre confidentiel fictif" not in response.text
    assert "SHA-256" not in response.text


@pytest.mark.parametrize("exc", [MemoireIndisponible("panne privée"), TimeoutError("panne privée")])
def test_retrait_role_pendant_lecture_du_resultat_partiel_bloque_affichage(console_lots, monkeypatch, exc):
    client, service, active = console_lots
    cle = _cle(client)
    original = service.admettre_emplacement

    def echouer_second(cle_lot, position, contenu, *, auteur):
        if position == 2:
            raise exc
        return original(cle_lot, position, contenu, auteur=auteur)

    original_lire = service.lire_lot

    def retirer_apres_lecture(*args, **kwargs):
        lot = original_lire(*args, **kwargs)
        active["admin"] = False
        return lot

    monkeypatch.setattr(service, "admettre_emplacement", echouer_second)
    monkeypatch.setattr(service, "lire_lot", retirer_apres_lecture)
    response = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot=cle, **{"1": "Titre privé fictif", "2": "Titre suivant fictif"}),
        files=_files((1, "one.txt", b"un", "text/plain"), (2, "two.txt", b"deux", "text/plain")),
    )
    assert response.status_code == 403
    assert "Titre privé fictif" not in response.text and "SHA-256" not in response.text
    assert service.versions == {(cle, 1): 1}


@pytest.mark.parametrize("sources", [
    [(i, f"guide{i}.txt", b"texte", "text/plain") for i in range(1, 7)],
    [(1, "grand.txt", b"a" * (1_048_576 + 1), "text/plain")],
])
def test_limites_nombre_et_octets_refusent_sans_mutation(console_lots, sources):
    client, service, _ = console_lots
    cle = _cle(client)
    response = client.post(
        "/memoire/procedures/imports/creer",
        data=_fields(cle_lot=cle, **{str(i): f"Guide {i}" for i, *_ in sources}),
        files=_files(*sources),
    )
    assert response.status_code in {400, 413}
    assert service.mutations == []



def test_role_retire_pendant_liste_imports_bloque_affichage(console_lots, monkeypatch):
    client, service, active = console_lots
    original = service.lister_lots

    def retirer_role(*args, **kwargs):
        lots = original(*args, **kwargs)
        active["admin"] = False
        return lots

    monkeypatch.setattr(service, "lister_lots", retirer_role)
    response = client.get("/memoire/procedures/imports")
    assert response.status_code == 403
    assert "Mes imports M03" not in response.text
    assert response.headers["cache-control"] == "no-store"
