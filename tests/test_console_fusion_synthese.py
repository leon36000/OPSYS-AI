"""Synthèse privée des métadonnées Fusion; les valeurs métier restent hors écran."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from memoire.doubles import postgres_ephemere, raison_sans_docker, vider
from sqlalchemy import delete

from opsys import fusion_ap, fusion_csv, fusion_pdf, identite, stockage
from opsys.console import application, fusion_synthese, securite
from opsys.console.securite import Configuration
from opsys.memoire.store import MemoireEntreprise
from opsys.stockage.schema import ROLES_PERSONNES

SECRET = "secret-fusion-synthese-fictif-" + "x" * 32
PASSWORD = "mot-de-passe-synthese-fictif-1234"
ADMIN = "admin-synthese-fictif"
EMPLOYEE = "employe-synthese-fictif"
PREFIX = "/opsys"


class _Procedures:
    def __init__(self, *, total=1, status="INDEXE", active=True, versions=1):
        self.total = total
        self.status = status
        self.active = active
        self.versions = versions
        self.offsets = []

    def lister_series(self, *, limite, offset):
        self.offsets.append(offset)
        items = [
            {
                "fictif": True, "document_id": f"uuid-secret-{i}",
                "titre": "TITRE-SECRET", "version_courante": "sha-secret",
            }
            for i in range(offset, min(self.total, offset + limite))
        ]
        return SimpleNamespace(total=self.total, series=tuple(items))

    def lister_versions(self, document_id):
        return tuple(
            SimpleNamespace(etat=self.status, active=self.active if i == self.versions - 1 else False)
            for i in range(self.versions)
        )


@pytest.fixture
def client_synthese(nathan, monkeypatch):
    monkeypatch.delenv("OPSYS_DATABASE_URL", raising=False)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN, "Administrateur fictif", PASSWORD, ["admin"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé fictif", PASSWORD, ["employee"])
    app = application.creer_application(Configuration(SECRET, cookie_securise=False), cnx_factory=stockage.transaction)
    with TestClient(app, base_url=f"http://testserver{PREFIX}", raise_server_exceptions=False) as client:
        _connecter(client, "nathan")
        yield client


def _connecter(client: TestClient, utilisateur: str) -> str:
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, utilisateur)
    assert personne is not None
    session = securite.ouvrir_session(utilisateur, personne.roles, 3600)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, SECRET), path=PREFIX)
    return session.csrf


def _sources(monkeypatch, *, procedures=None, csv=None, pdf=None, ap=None):
    procedures = procedures or _Procedures()
    csv = csv if csv is not None else [
        {"fictif": True, "statut": "PROPOSITIONS", "curseur": 10, "total_lignes": 10, "nombre_propositions": 2,
         "compte_interne_id": "COMPTE-SECRET", "source_sha256": "SHA-SECRET", "montant": "9999.00"},
        {"fictif": True, "statut": "SNAPSHOT_OBSOLETE", "curseur": 3, "total_lignes": 3, "nombre_propositions": 7,
         "reference_facture": "FACTURE-SECRET"},
    ]
    pdf = pdf if pdf is not None else [
        {"fictif": True, "statut": "EXTRAIT_PREPARATOIRE", "total_pages": 2, "source_sha256": "PDF-SHA-SECRET",
         "titre": "CLIENT-PDF-SECRET"},
        {"fictif": True, "statut": "RECU", "total_pages": 0, "description": "DESCRIPTION-SECRET"},
    ]
    monkeypatch.setattr(fusion_csv, "lister", lambda *_: csv)
    monkeypatch.setattr(fusion_pdf, "lister", lambda *_, **__: pdf)
    monkeypatch.setattr(fusion_ap, "lister_a_revoir", lambda *_, **__: ap if ap is not None else [])
    monkeypatch.setattr(fusion_synthese, "lire_procedures", lambda: procedures)
    return procedures


def test_synthese_affiche_compteurs_observes_sans_donnees_sensibles(client_synthese, monkeypatch):
    _sources(monkeypatch)
    reponse = client_synthese.get("/fusion-operationnelle/synthese")
    assert reponse.status_code == 200, reponse.text
    assert reponse.headers["cache-control"] == "private, no-store, max-age=0"
    assert "Lots admis" in reponse.text and "2" in reponse.text
    assert "propositions potentiellement consultables" in reponse.text.lower()
    assert "Brouillons repérés" in reponse.text and "Ouvrir la boîte des brouillons AP" in reponse.text
    assert "/fusion/pdf/ap/a-revoir" in reponse.text
    assert "TITRE-SECRET" not in reponse.text
    for secret in ("COMPTE-SECRET", "SHA-SECRET", "9999.00", "FACTURE-SECRET", "PDF-SHA-SECRET",
                   "CLIENT-PDF-SECRET", "DESCRIPTION-SECRET", "uuid-secret"):
        assert secret not in reponse.text
    assert "entreprise connue" not in reponse.text.lower()
    assert "observ" in reponse.text.lower()


def test_hub_fusion_pointe_vers_synthese(client_synthese):
    response = client_synthese.get("/fusion")
    assert response.status_code == 200
    assert "/fusion-operationnelle/synthese" in response.text


def test_employe_refuse_avant_toute_lecture(client_synthese, monkeypatch):
    _sources(monkeypatch)
    _connecter(client_synthese, EMPLOYEE)
    monkeypatch.setattr(fusion_csv, "lister", lambda *_: pytest.fail("lecture CSV après refus"))
    response = client_synthese.get("/fusion-operationnelle/synthese")
    assert response.status_code == 403
    assert "lots" not in response.text.lower()


def test_revocation_pendant_lecture_empeche_toute_reponse(client_synthese, monkeypatch):
    _sources(monkeypatch)

    def lire_puis_revoquer(*_):
        with stockage.transaction() as cnx:
            cnx.execute(delete(ROLES_PERSONNES).where(
                (ROLES_PERSONNES.c.identifiant == "nathan") & (ROLES_PERSONNES.c.role == "nathan_owner")
            ))
        return [{"statut": "RECU", "curseur": 0, "total_lignes": None, "nombre_propositions": 0}]

    monkeypatch.setattr(fusion_csv, "lister", lire_puis_revoquer)
    response = client_synthese.get("/fusion-operationnelle/synthese")
    assert response.status_code == 403
    assert "État indisponible" not in response.text and "Lots admis" not in response.text


@pytest.mark.parametrize(
    ("source", "rows"),
    [
        ("csv", [{"statut": "ETAT_INVENTE", "curseur": 0, "total_lignes": None, "nombre_propositions": 0}]),
        ("pdf", [{"statut": "INDEXE", "total_pages": 1}]),
    ],
)
def test_etat_inconnu_indisponible_sans_exposer_sa_valeur(client_synthese, monkeypatch, source, rows):
    _sources(monkeypatch, **{source: rows})
    response = client_synthese.get("/fusion-operationnelle/synthese")
    assert response.status_code == 200
    assert "État indisponible" in response.text
    assert "ETAT_INVENTE" not in response.text and "INDEXE" not in response.text


def test_panne_d_une_source_est_indisponible_et_ne_devient_pas_zero(client_synthese, monkeypatch):
    _sources(monkeypatch)

    def panne(*_):
        raise RuntimeError("MONTANT-SECRET-ERREUR")

    monkeypatch.setattr(fusion_pdf, "lister", panne)
    response = client_synthese.get("/fusion-operationnelle/synthese")
    assert response.status_code == 200
    assert "Finance · PDF natif" in response.text and "État indisponible" in response.text
    assert "MONTANT-SECRET-ERREUR" not in response.text
    assert "M5 · CSV bancaire" in response.text and "Lots admis" in response.text


def test_panne_ap_est_indisponible_sans_masquer_les_autres_filieres(client_synthese, monkeypatch):
    _sources(monkeypatch)

    def panne(*_args, **_kwargs):
        raise RuntimeError("FICTIF-AP-ERREUR-SECRET")

    monkeypatch.setattr(fusion_ap, "lister_a_revoir", panne)
    response = client_synthese.get("/fusion-operationnelle/synthese")
    assert response.status_code == 200
    assert "Finance · Brouillons AP" in response.text
    assert "État indisponible" in response.text
    assert "FICTIF-AP-ERREUR-SECRET" not in response.text
    assert "M5 · CSV bancaire" in response.text and "Finance · PDF natif" in response.text


def test_etat_ap_inconnu_et_quota_de_liste_sont_indisponibles_non_zero():
    row = {
        "lot_id": "00000000-0000-4000-8000-000000000001",
        "revision": 1,
        "statut": "INDISPONIBLE",
        "cree_le": "2026-10-03T00:00:00+00:00",
        "modifie_le": "2026-10-03T00:00:00+00:00",
        "etat_source": "INDISPONIBLE",
    }
    assert fusion_synthese._compteurs_ap([row]) == {"brouillons": 1, "a_revalider": 0, "indisponibles": 1}
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_ap([{**row, "etat_source": "ETAT_INVENTE"}])
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_ap([row] * (fusion_pdf.NB_LOTS_MAX + 1))


@pytest.mark.parametrize("query", ["?mode=autre", "?x=1&x=2"])
def test_parametres_inconnus_refuses_avant_lecture(client_synthese, monkeypatch, query):
    monkeypatch.setattr(fusion_csv, "lister", lambda *_: pytest.fail("backend appelé avant validation query"))
    response = client_synthese.get("/fusion-operationnelle/synthese" + query)
    assert response.status_code == 400


def test_compteurs_excluent_propositions_des_snapshots_perimes():
    counts = fusion_synthese._compteurs_csv([
        {"statut": "PROPOSITIONS", "curseur": 9, "total_lignes": 9, "nombre_propositions": 4},
        {"statut": "SNAPSHOT_OBSOLETE", "curseur": 7, "total_lignes": 7, "nombre_propositions": 4},
    ])
    assert counts["lots"] == 2
    assert counts["propositions_potentielles"] == 4
    assert counts["snapshot_obsolete"] == 1


def test_bornes_fusion_procedures_64_series_8_versions_et_pagination():
    service = _Procedures(total=64, status="INDEXE", active=True, versions=8)
    counts = fusion_synthese._compteurs_procedures(service, lambda: None)
    assert counts == {
        "series": 64, "versions": 512, "versions_recues": 0,
        "versions_indexees": 512, "versions_actives": 64,
    }
    assert service.offsets == [0, 50]


def test_refuse_etats_procedures_inconnus_et_series_au_dela_quota():
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_procedures(_Procedures(status="ACTIVE_INVENTE"), lambda: None)
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_procedures(_Procedures(total=65), lambda: None)
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_procedures(_Procedures(versions=9), lambda: None)


def test_capacites_csv_pdf_sont_refusees_si_lecteur_depasse_le_quota():
    csv_lots = [
        {"statut": "RECU", "curseur": 0, "total_lignes": None, "nombre_propositions": 0}
        for _ in range(65)
    ]
    pdf_lots = [{"statut": "RECU", "total_pages": 0} for _ in range(17)]
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_csv(csv_lots)
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_pdf(pdf_lots)


def test_page_pdf_incoherente_et_plusieurs_versions_actives_sont_refusees():
    with pytest.raises(ValueError):
        fusion_synthese._compteurs_pdf([{"statut": "EXTRAIT_PREPARATOIRE", "total_pages": 21}])

    class _DeuxActives(_Procedures):
        def lister_versions(self, document_id):
            return (SimpleNamespace(etat="INDEXE", active=True), SimpleNamespace(etat="INDEXE", active=True))

    with pytest.raises(ValueError):
        fusion_synthese._compteurs_procedures(_DeuxActives(versions=2), lambda: None)


def test_pages_pdf_inconnues_incluent_refus_recu_et_erreur():
    counts = fusion_synthese._compteurs_pdf([
        {"fictif": True, "statut": "RECU", "total_pages": 0},
        {"fictif": True, "statut": "ERREUR_REPRENABLE", "total_pages": 0},
        {"fictif": True, "statut": "REFUSE", "total_pages": 0},
        {"fictif": True, "statut": "EXTRAIT_PREPARATOIRE", "total_pages": 2},
    ])
    assert counts["lots_pages_inconnues"] == 3
    assert counts["pages_extraites_preparatoires"] == 2


@pytest.fixture(scope="module")
def url_pg_procedures():
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        yield url


def test_synthese_compte_parcours_procedures_pg_reel_et_pagine_sans_citations(
    client_synthese, monkeypatch, url_pg_procedures,
):
    memoire = MemoireEntreprise(url_pg_procedures)
    memoire.migrer()
    vider(url_pg_procedures)
    procedures = memoire.procedures()
    acteur = "admin:synthese-fictif"
    secret_titre = "TITRE-PROCEDURE-SECRET-FICTIF"
    secret_corps = "CORPS-PROCEDURE-SECRET-FICTIF"
    for numero in range(50):
        procedures.admettre(
            f"# Procédure fictive {numero:02d}\n\nRègle interne fictive {numero:02d}.\n".encode(),
            f"Procédure témoin fictive {numero:02d}", auteur=acteur,
            cle_admission=f"synthese-pagination-{numero:03d}-fictif",
        )
    source_v1 = f"# {secret_titre}\n\n{secret_corps}\n".encode()
    v1 = procedures.admettre(
        source_v1, secret_titre, auteur=acteur, cle_admission="synthese-v1-admission-fictive",
    )
    assert v1.etat == "RECU"
    procedures.indexer(v1.document_id, v1.sha256)
    procedures.activer(v1.document_id, v1.sha256, attendu_sha256=None, auteur=acteur)
    source_v2 = f"# {secret_titre}\n\nVersion deux fictive.\n".encode()
    v2 = procedures.admettre(
        source_v2, secret_titre, auteur=acteur, cle_admission="synthese-v2-admission-fictive",
        document_id=v1.document_id,
    )
    assert v2.etat == "RECU"
    procedures.indexer(v1.document_id, v2.sha256)
    procedures.activer(v1.document_id, v2.sha256, attendu_sha256=v1.sha256, auteur=acteur)
    monkeypatch.setattr(fusion_synthese, "lire_procedures", lambda: procedures)
    offsets = []
    lister_original = procedures.lister_series

    def lister_trace(*, limite, offset):
        offsets.append(offset)
        return lister_original(limite=limite, offset=offset)

    monkeypatch.setattr(procedures, "lister_series", lister_trace)
    response = client_synthese.get("/fusion-operationnelle/synthese")
    assert response.status_code == 200, response.text
    assert offsets == [0, 50]
    assert "<dt>Séries admises</dt><dd>51</dd>" in response.text
    assert "<dt>Versions</dt><dd>52</dd>" in response.text
    assert "<dt>Versions reçues</dt><dd>50</dd>" in response.text
    assert "<dt>Versions indexées</dt><dd>2</dd>" in response.text
    assert "<dt>Versions actives</dt><dd>1</dd>" in response.text
    assert secret_titre not in response.text and secret_corps not in response.text
    assert v1.sha256 not in response.text and v2.sha256 not in response.text
    assert "opsys-document://" not in response.text and "citations_verifiees" not in response.text
    assert "<dt>Lots admis</dt><dd>0</dd>" in response.text  # SQLite Finance isolée et vide.
