"""Manifeste persistant d'import M03 : transactions et reprises sur PostgreSQL réel."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker, vider

from opsys.memoire.ingestion_procedures import SourceLot
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


def _reset(url: str) -> None:
    _sql(url, "DELETE FROM memoire.procedure_lots")
    _sql(url, "DELETE FROM memoire.procedure_admission_oubliees")
    _sql(url, "DELETE FROM memoire.procedure_lots_oublies")
    vider(url)


def _source(position: int, contenu: bytes, *, titre: str | None = None, cible: str | None = None) -> SourceLot:
    return SourceLot(position, titre or f"Guide {position}", hashlib.sha256(contenu).hexdigest(), cible)


def _service(url: str):
    return MemoireEntreprise(url).procedures()


@avec_postgres
def test_manifest_immuable_rejeu_et_slots_creux(url_pg):
    _reset(url_pg)
    MemoireEntreprise(url_pg).migrer()
    service = _service(url_pg)
    cle = "lot-opaque-r26-00000001"
    sources = (_source(1, b"Guide initial."), _source(4, b"Guide final."))

    cree = service.creer_lot(cle, sources, auteur="admin:lots")
    rejoue = service.creer_lot(cle, sources, auteur="admin:lots")
    assert rejoue == cree
    assert [slot.position for slot in cree.emplacements] == [1, 4]
    assert [slot.etat for slot in cree.emplacements] == ["ATTENTE", "ATTENTE"]
    assert all(slot.document_id is None and slot.serie_cible_id is None for slot in cree.emplacements)
    with pytest.raises(ValueError, match="conflit"):
        service.creer_lot(cle, (_source(1, b"Autre contenu."), sources[1]), auteur="admin:lots")
    with pytest.raises(ValueError, match="conflit"):
        service.creer_lot(cle, sources, auteur="admin:autre")
    with pytest.raises(ValueError, match="auteur"):
        service.lire_lot(cle, auteur="admin:autre")

    source_existante = service.admettre(
        "Série cible déjà créée.".encode(), "Guide cible", auteur="admin:lots",
        cle_admission="lot-hist-r26-00001"
    )
    source_cible = _source(5, b"Nouvelle version cible.", cible=source_existante.document_id)
    lot_cible = service.creer_lot("lot-cible-r26-0000001", (source_cible,), auteur="admin:lots")
    admis_cible = service.admettre_emplacement(
        lot_cible.cle_lot, 5, b"Nouvelle version cible.", auteur="admin:lots"
    ).emplacements[0]
    assert admis_cible.serie_cible_id == source_existante.document_id == admis_cible.document_id
    assert len(service.lister_versions(source_existante.document_id)) == 2

    slot = service.admettre_emplacement(cle, 4, b"Guide final.", auteur="admin:lots")
    assert slot.emplacements[0].position == 1 and slot.emplacements[0].etat == "ATTENTE"
    admis = slot.emplacements[1]
    assert admis.etat == "RECU" and not admis.active
    assert admis.document_id is not None and admis.serie_cible_id is None
    assert service.admettre_emplacement(cle, 4, b"Guide final.", auteur="admin:lots") == slot
    with pytest.raises(ValueError, match="empreinte"):
        service.admettre_emplacement(cle, 4, b"Contenu modifie.", auteur="admin:lots")


@avec_postgres
def test_admission_et_rattachement_slot_rollbackent_ensemble_puis_reprise(url_pg):
    import psycopg

    _reset(url_pg)
    service = _service(url_pg)
    cle = "lot-rollback-r26-0000001"
    contenu = b"Source reprise atomique."
    service.creer_lot(cle, (_source(2, contenu),), auteur="admin:rollback")
    with psycopg.connect(url_pg, autocommit=True) as cnx:
        cnx.execute("""CREATE FUNCTION memoire.test_lot_refuse_rattachement() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected slot update failure'; END $$""")
        cnx.execute("CREATE TRIGGER test_lot_refuse_rattachement BEFORE UPDATE ON memoire.procedure_lot_emplacements"
                    " FOR EACH ROW EXECUTE FUNCTION memoire.test_lot_refuse_rattachement()")
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="injected slot update failure"):
            service.admettre_emplacement(cle, 2, contenu, auteur="admin:rollback")
        assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0] == 0
        assert service.lire_lot(cle, auteur="admin:rollback").emplacements[0].etat == "ATTENTE"
    finally:
        with psycopg.connect(url_pg, autocommit=True) as cnx:
            cnx.execute("DROP TRIGGER IF EXISTS test_lot_refuse_rattachement ON memoire.procedure_lot_emplacements")
            cnx.execute("DROP FUNCTION IF EXISTS memoire.test_lot_refuse_rattachement()")
    repris = service.admettre_emplacement(cle, 2, contenu, auteur="admin:rollback")
    assert repris.emplacements[0].etat == "RECU"
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0] == 1


@avec_postgres
def test_admissions_concurrentes_du_meme_slot_ne_creent_qu_une_version(url_pg):
    _reset(url_pg)
    service = _service(url_pg)
    cle = "lot-concurrent-r26-000001"
    contenu = b"Une seule version concurrente."
    service.creer_lot(cle, (_source(3, contenu),), auteur="admin:concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.admettre_emplacement, cle, 3, contenu, auteur="admin:concurrent")
                   for _ in range(2)]
        resultats = [future.result() for future in futures]
    assert resultats[0] == resultats[1]
    assert resultats[0].emplacements[0].etat == "RECU"
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0] == 1
    attaches = _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lot_emplacements WHERE version_id IS NOT NULL")
    assert attaches[0][0] == 1


@avec_postgres
def test_etat_et_activation_courante_sont_derives_des_versions(url_pg):
    _reset(url_pg)
    service = _service(url_pg)
    cle = "lot-etat-r26-00000001"
    contenu = "Règle indexable avec provenance.".encode()
    service.creer_lot(cle, (_source(1, contenu), _source(5, b"En attente.")), auteur="admin:etat")
    recu = service.admettre_emplacement(cle, 1, contenu, auteur="admin:etat")
    version = recu.emplacements[0]
    assert version.etat == "RECU" and not version.active
    service.indexer(version.document_id, version.sha256)
    indexe = service.lire_lot(cle, auteur="admin:etat")
    assert indexe.emplacements[0].etat == "INDEXE" and not indexe.emplacements[0].active
    service.activer(version.document_id, version.sha256, attendu_sha256=None, auteur="admin:etat")
    actif = service.lire_lot(cle, auteur="admin:etat")
    assert actif.emplacements[0].active and actif.emplacements[0].etat == "INDEXE"
    assert actif.emplacements[1].etat == "ATTENTE"
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_activations")[0][0] == 1


@avec_postgres
def test_oubli_specifique_et_generique_tombstone_le_lot_sans_effacer_autre_serie(url_pg):
    _reset(url_pg)
    memoire = MemoireEntreprise(url_pg)
    service = memoire.procedures()
    cle = "lot-oubli-r26-00000001"
    contenu_a, contenu_b = b"Document A.", b"Document B."
    service.creer_lot(cle, (_source(1, contenu_a), _source(2, contenu_b)), auteur="admin:oubli")
    lot = service.admettre_emplacement(cle, 1, contenu_a, auteur="admin:oubli")
    doc_a = lot.emplacements[0].document_id
    lot = service.admettre_emplacement(cle, 2, contenu_b, auteur="admin:oubli")
    doc_b = lot.emplacements[1].document_id
    assert doc_a and doc_b and doc_a != doc_b

    service.oublier(doc_a, demandeur="admin:oubli", motif="oubli spécifique")
    with pytest.raises(ValueError, match="oublié"):
        service.lire_lot(cle, auteur="admin:oubli")
    with pytest.raises(ValueError, match="oublié"):
        service.creer_lot(cle, (_source(1, contenu_a), _source(2, contenu_b)), auteur="admin:oubli")
    assert service.lire_etat(doc_b).etat == "RECU"
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots")[0][0] == 0
    tombstone = _sql(url_pg, "SELECT cle_lot_sha256 FROM memoire.procedure_lots_oublies")
    assert len(tombstone) == 1 and cle not in str(tombstone)

    cible = service.admettre(
        "Série ciblée et oubliée.".encode(), "Cible oubliée", auteur="admin:oubli",
        cle_admission="target-forget-r26-01"
    )
    cle_cible = "lot-cible-oublie-r26-01"
    service.creer_lot(
        cle_cible, (_source(5, b"Version future.", cible=cible.document_id),), auteur="admin:oubli"
    )
    service.oublier(cible.document_id, demandeur="admin:oubli", motif="oubli série cible")
    with pytest.raises(ValueError, match="oublié"):
        service.lire_lot(cle_cible, auteur="admin:oubli")

    cle_generique = "lot-generic-r26-0000001"
    contenu_c, contenu_d = b"Document C.", b"Document D."
    service.creer_lot(cle_generique, (_source(1, contenu_c), _source(3, contenu_d)), auteur="admin:oubli")
    generique = service.admettre_emplacement(cle_generique, 1, contenu_c, auteur="admin:oubli")
    doc_c = generique.emplacements[0].document_id
    generique = service.admettre_emplacement(cle_generique, 3, contenu_d, auteur="admin:oubli")
    doc_d = generique.emplacements[1].document_id
    (pk_c,) = _sql(url_pg, "SELECT document_id FROM memoire.procedure_versions WHERE document_uuid=%s::uuid",
                   doc_c)[0]
    memoire.oublier({"document_id": pk_c}, demandeur="admin:oubli", motif="oubli générique")
    with pytest.raises(ValueError, match="oublié"):
        service.lire_lot(cle_generique, auteur="admin:oubli")
    assert service.lire_etat(doc_d).etat == "RECU"
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots_oublies")[0][0] == 3


@avec_postgres
def test_quota_lots_vivants_64(url_pg):
    _reset(url_pg)
    service = _service(url_pg)
    for numero in range(64):
        cle = f"lot-quota-r26-{numero:04d}"
        contenu = f"source {numero}".encode()
        service.creer_lot(cle, (_source(1, contenu),), auteur="admin:quota")
    with pytest.raises(ValueError, match="64 lots"):
        service.creer_lot("lot-quota-r26-0064", (_source(1, b"overflow"),), auteur="admin:quota")
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots")[0][0] == 64


@avec_postgres
def test_oubli_par_portee_tombstone_lot_et_cle_admission(url_pg):
    _reset(url_pg)
    memoire = MemoireEntreprise(url_pg)
    service = memoire.procedures()
    cle = "lot-forget-portee-r26-01"
    contenu = b"# Proc\xc3\xa9dure oubli\xc3\xa9e\n\nFragment index\xc3\xa9."
    service.creer_lot(cle, (_source(1, contenu),), auteur="admin:forget-portee")
    admis = service.admettre_emplacement(cle, 1, contenu, auteur="admin:forget-portee")
    slot = admis.emplacements[0]
    assert slot.document_id is not None
    service.indexer(slot.document_id, slot.sha256)

    memoire.oublier({"portee": "procedures"}, demandeur="admin:forget-portee", motif="oubli par portée")

    with pytest.raises(ValueError, match="oublié"):
        service.lire_lot(cle, auteur="admin:forget-portee")
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots WHERE cle_lot_sha256=%s",
                hashlib.sha256(b"opsys-m10-import-lot-v1\0" + cle.encode()).hexdigest())[0][0] == 0
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots_oublies")[0][0] == 1
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_admission_oubliees")[0][0] == 1
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0] == 0


@avec_postgres
def test_purge_expire_tombstone_lot_et_admission_procedure(url_pg):
    _reset(url_pg)
    memoire = MemoireEntreprise(url_pg)
    service = memoire.procedures()
    cle = "lot-purge-expire-r26-01"
    contenu = b"# Proc\xc3\xa9dure expir\xc3\xa9e\n\nFragment \xc3\xa0 purger."
    service.creer_lot(cle, (_source(1, contenu),), auteur="admin:purge")
    slot = service.admettre_emplacement(cle, 1, contenu, auteur="admin:purge").emplacements[0]
    assert slot.document_id is not None
    service.indexer(slot.document_id, slot.sha256)
    _sql(url_pg, "UPDATE memoire.fragments SET cree_le=now()-interval '2 days',"
         "expire_le=now()-interval '1 day' WHERE document_id=("
         "SELECT document_id FROM memoire.procedure_versions WHERE document_uuid=%s::uuid)", slot.document_id)

    memoire.purger_expires()

    with pytest.raises(ValueError, match="oublié"):
        service.lire_lot(cle, auteur="admin:purge")
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_lots_oublies")[0][0] == 1
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_admission_oubliees")[0][0] == 1


@avec_postgres
def test_oubli_par_portee_preserve_lot_et_version_survivante(url_pg):
    _reset(url_pg)
    memoire = MemoireEntreprise(url_pg)
    service = memoire.procedures()
    ancienne = service.admettre(
        b"# Version ancienne\n\nFragment indexable avant oubli.", "Historique", auteur="admin:survie",
        cle_admission="old-survival-r26-0001",
    )
    service.indexer(ancienne.document_id, ancienne.sha256)

    contenu_v2 = b"# Version deux\n\nSource recue qui survit."
    cle_v2 = "lot-survivant-version-r26-01"
    source_v2 = _source(2, contenu_v2, titre="Version deux", cible=ancienne.document_id)
    service.creer_lot(cle_v2, (source_v2,), auteur="admin:survie")
    v2 = service.admettre_emplacement(cle_v2, 2, contenu_v2, auteur="admin:survie").emplacements[0]
    assert v2.document_id == ancienne.document_id and v2.etat == "RECU"

    cle_pending = "lot-pending-series-r26-01"
    service.creer_lot(
        cle_pending,
        (_source(5, b"Future version trois.", titre="Future", cible=ancienne.document_id),),
        auteur="admin:survie",
    )
    memoire.oublier({"portee": "procedures"}, demandeur="admin:survie", motif="oubli version indexée")

    restante = service.lire_etat(ancienne.document_id)
    assert restante.etat == "RECU"
    assert [version.version for version in service.lister_versions(ancienne.document_id)] == [2]
    assert service.lire_lot(cle_v2, auteur="admin:survie").emplacements[0].etat == "RECU"
    assert service.lire_lot(cle_pending, auteur="admin:survie").emplacements[0].etat == "ATTENTE"


@avec_postgres
def test_creation_en_attente_advisory_ne_verrouille_pas_la_ligne_cible(url_pg):
    import time

    import psycopg

    _reset(url_pg)
    service = _service(url_pg)
    initial = service.admettre(
        b"Source cible fictive.", "Cible", auteur="admin:ordre", cle_admission="cible-ordre-r26-0001"
    )
    ident = initial.document_id
    source = _source(1, b"Version suivante fictive.", cible=ident)
    with psycopg.connect(url_pg) as verrou:
        verrou.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("opsys.memoire.procedure." + ident,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.creer_lot, "lot-ordre-verrou-r26-0001", (source,), auteur="admin:ordre")
            try:
                limite = time.monotonic() + 1.5
                with psycopg.connect(url_pg, autocommit=True) as sonde:
                    en_attente = False
                    while time.monotonic() < limite:
                        (en_attente,) = sonde.execute(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory'"
                            " AND NOT granted AND pid <> pg_backend_pid())"
                        ).fetchone()
                        if en_attente:
                            break
                        time.sleep(0.01)
                    assert en_attente, "la création doit attendre le verrou de série détenu"
                    # La création suspendue doit laisser la ligne disponible à son propriétaire.
                    with sonde.transaction():
                        assert sonde.execute(
                            "SELECT document_uuid::text FROM memoire.procedure_series"
                            " WHERE document_uuid=%s::uuid FOR UPDATE NOWAIT", (ident,)
                        ).fetchone() == (ident,)
            finally:
                verrou.commit()
            lot = future.result(timeout=5)
    assert lot.emplacements[0].serie_cible_id == ident
    assert lot.emplacements[0].etat == "ATTENTE"
