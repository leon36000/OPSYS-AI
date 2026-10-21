"""Références stables et index propriétaire des imports M03 sur PostgreSQL réel."""

from __future__ import annotations

import hashlib

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker, vider

from opsys.memoire.ingestion_procedures import ResumeLot, SourceLot
from opsys.memoire.store import MemoireEntreprise

RAISON_SANS_DOCKER = raison_sans_docker()
avec_postgres = pytest.mark.skipif(RAISON_SANS_DOCKER is not None, reason=str(RAISON_SANS_DOCKER))


@pytest.fixture(scope="module")
def url_pg():
    if RAISON_SANS_DOCKER is not None:
        pytest.skip(RAISON_SANS_DOCKER)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        MemoireEntreprise(url).migrer()
        yield url


def _sql(url: str, query: str, *params):
    import psycopg

    with psycopg.connect(url) as cnx:
        curseur = cnx.execute(query, params)
        return curseur.fetchall() if curseur.description else []


def _vider(url: str) -> None:
    _sql(url, "DELETE FROM memoire.procedure_lots")
    _sql(url, "DELETE FROM memoire.procedure_admission_oubliees")
    _sql(url, "DELETE FROM memoire.procedure_lots_oublies")
    vider(url)


def _source(position: int, contenu: bytes, *, titre: str | None = None) -> SourceLot:
    return SourceLot(position, titre or f"Procédure {position}", hashlib.sha256(contenu).hexdigest())


def _service(url: str):
    return MemoireEntreprise(url).procedures()


@avec_postgres
def test_index_lots_isole_par_auteur_et_borne_a_64(url_pg):
    _vider(url_pg)
    service = _service(url_pg)
    for numero in range(64):
        cle = f"lots-reference-quota-r26-{numero:03d}"
        auteur = "admin:b" if numero == 0 else "admin:a"
        contenu = f"Procédure {numero}".encode()
        service.creer_lot(cle, (_source(1, contenu),), auteur=auteur)

    lots_a = service.lister_lots(auteur="admin:a")
    lots_b = service.lister_lots(auteur="admin:b")
    lots_inconnu = service.lister_lots(auteur="admin:absent")
    assert len(lots_a) == 63 and len(lots_b) == 1 and lots_inconnu == ()
    assert len(lots_a) + len(lots_b) <= 64
    assert all(isinstance(lot, ResumeLot) for lot in (*lots_a, *lots_b))
    assert all(len(lot.reference) == 64 and all(char in "0123456789abcdef" for char in lot.reference)
               for lot in (*lots_a, *lots_b))
    with pytest.raises(ValueError, match="64 lots"):
        service.creer_lot("lot-reference-quota-overflow-r26", (_source(1, b"extra"),), auteur="admin:a")


@avec_postgres
def test_projection_derive_etat_indexation_et_activation(url_pg):
    _vider(url_pg)
    service = _service(url_pg)
    cle = "lot-reference-etat-r26-0001"
    contenu = b"# Repere\n\nRegle de terrain verifiable."
    service.creer_lot(cle, (_source(1, contenu), _source(5, b"En attente.")), auteur="admin:etat-ref")
    slot = service.admettre_emplacement(cle, 1, contenu, auteur="admin:etat-ref").emplacements[0]
    assert slot.document_id is not None
    reference, = (lot.reference for lot in service.lister_lots(auteur="admin:etat-ref"))

    attente_recu = service.lister_lots(auteur="admin:etat-ref")[0]
    assert (attente_recu.nombre_emplacements, attente_recu.attente, attente_recu.recu,
            attente_recu.indexe, attente_recu.actifs) == (2, 1, 1, 0, 0)
    service.indexer(slot.document_id, slot.sha256)
    indexe = service.lister_lots(auteur="admin:etat-ref")[0]
    assert (indexe.attente, indexe.recu, indexe.indexe, indexe.actifs) == (1, 0, 1, 0)
    service.activer(slot.document_id, slot.sha256, attendu_sha256=None, auteur="admin:etat-ref")
    actif = service.lister_lots(auteur="admin:etat-ref")[0]
    assert (actif.attente, actif.recu, actif.indexe, actif.actifs) == (1, 0, 1, 1)
    assert actif.reference == reference


@avec_postgres
def test_reprise_par_reference_apres_nouveau_service_sans_doublon(url_pg):
    _vider(url_pg)
    service = _service(url_pg)
    cle = "lot-reference-reprise-r26-0001"
    contenu = "# Reprise\n\nSource durable après fermeture.".encode()
    service.creer_lot(cle, (_source(4, contenu, titre="Guide reprise"),), auteur="admin:reprise-ref")
    (resume,) = service.lister_lots(auteur="admin:reprise-ref")

    nouveau_service = _service(url_pg)
    lot = nouveau_service.lire_lot_reference(resume.reference, auteur="admin:reprise-ref")
    assert lot.cle_lot == resume.reference
    assert lot.emplacements[0].etat == "ATTENTE"
    admis = nouveau_service.admettre_emplacement_reference(
        resume.reference, 4, contenu, auteur="admin:reprise-ref"
    )
    rejoue = nouveau_service.admettre_emplacement_reference(
        resume.reference, 4, contenu, auteur="admin:reprise-ref"
    )
    assert admis == rejoue and admis.cle_lot == resume.reference
    assert admis.emplacements[0].etat == "RECU"
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0] == 1
    assert _sql(
        url_pg, "SELECT count(*) FROM memoire.procedure_lot_emplacements WHERE version_id IS NOT NULL"
    )[0][0] == 1


@avec_postgres
def test_reference_invalide_et_autre_auteur_refuses_sans_mutation(url_pg):
    _vider(url_pg)
    service = _service(url_pg)
    cle = "lot-reference-droits-r26-0001"
    contenu = b"Source privee en attente."
    service.creer_lot(cle, (_source(1, contenu),), auteur="admin:proprietaire")
    (resume,) = service.lister_lots(auteur="admin:proprietaire")
    avant = (
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots")[0][0],
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lot_emplacements WHERE version_id IS NOT NULL")[0][0],
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0],
    )

    with pytest.raises(ValueError, match="référence"):
        service.lire_lot_reference("a" * 63, auteur="admin:proprietaire")
    with pytest.raises(ValueError, match="référence"):
        service.lire_lot_reference("A" * 64, auteur="admin:proprietaire")
    with pytest.raises(ValueError, match="référence"):
        service.admettre_emplacement_reference("../" + resume.reference, 1, contenu, auteur="admin:proprietaire")
    with pytest.raises(ValueError, match="auteur"):
        service.lire_lot_reference(resume.reference, auteur="admin:autre")
    with pytest.raises(ValueError, match="auteur"):
        service.admettre_emplacement_reference(resume.reference, 1, contenu, auteur="admin:autre")

    apres = (
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots")[0][0],
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lot_emplacements WHERE version_id IS NOT NULL")[0][0],
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0],
    )
    assert apres == avant == (1, 0, 0)


@avec_postgres
def test_oubli_retire_liste_et_bloque_lecture_ecriture_par_reference(url_pg):
    _vider(url_pg)
    service = _service(url_pg)
    cle = "lot-reference-oubli-r26-0001"
    contenu = b"Source oubliee par son proprietaire."
    service.creer_lot(cle, (_source(3, contenu),), auteur="admin:oubli-ref")
    slot = service.admettre_emplacement(cle, 3, contenu, auteur="admin:oubli-ref").emplacements[0]
    assert slot.document_id is not None
    (resume,) = service.lister_lots(auteur="admin:oubli-ref")
    service.oublier(slot.document_id, demandeur="admin:oubli-ref", motif="oubli de test")

    assert service.lister_lots(auteur="admin:oubli-ref") == ()
    avant = (
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots")[0][0],
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0],
    )
    with pytest.raises(ValueError, match="oublié"):
        service.lire_lot_reference(resume.reference, auteur="admin:oubli-ref")
    with pytest.raises(ValueError, match="oublié"):
        service.admettre_emplacement_reference(
            resume.reference, 3, contenu, auteur="admin:oubli-ref"
        )
    apres = (
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots")[0][0],
        _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0],
    )
    assert apres == avant == (0, 0)
