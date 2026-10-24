"""Schéma OCR M5 isolé et migration SQLite additive."""

from __future__ import annotations

import base64
import uuid

import pytest
from alembic import command, op
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, literal_column, select, text
from sqlalchemy.exc import IntegrityError

from opsys import stockage
from opsys.stockage.schema import (
    FUSION_AP_BROUILLONS,
    FUSION_AP_OCR_SOURCES,
    FUSION_PDF_LOTS,
    FUSION_PDF_OCR_COMMANDES,
    FUSION_PDF_OCR_QUOTA,
    FUSION_PDF_OCR_RUNS,
    FUSION_PDF_QUOTA,
)

_RESERVATION_MAX = 262_160
FICTIF = True


def _revision_tete():
    return ScriptDirectory.from_config(stockage._config()).get_current_head()


@pytest.fixture
def base_ocr(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-ocr.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _migration(revision: str, *, descendre: bool = False) -> None:
    configuration = stockage._config()
    with stockage.moteur().begin() as cnx:
        configuration.attributes["connection"] = cnx
        (command.downgrade if descendre else command.upgrade)(configuration, revision)


def _pdf_fictif(cnx, lot_id: str = "00000000-0000-4000-8000-000000000001") -> None:
    cnx.execute(FUSION_PDF_LOTS.insert().values(
        lot_id=lot_id, acteur="admin-fictif", mutation_id="admission-fictive",
        empreinte_requete="a" * 64, cle_deduplication="b" * 64,
        type_source="pdf_natif", classe="FINANCIAL", extracteur="pypdf-6.19.0/pdf-natif-1",
        configuration_sha256="c" * 64, source_sha256="d" * 64, source_octets=1,
        source_nonce="AAAAAAAAAAAAAAAA", source_cipher="A" * 23, source_cipher_octets=17,
        resultat_nonce=None, resultat_cipher=None, resultat_cipher_octets=0,
        cle_reference="OPSYS_INGESTION_CLE", version_format=1, statut="REFUSE", revision=1,
        total_pages=0, code="PDF_IMAGE_OU_MIXTE", cree_le="fictif", modifie_le="fictif",
    ))


def _brouillon_ap_fictif(lot_id: str = "00000000-0000-4000-8000-000000000001") -> dict:
    return {
        "lot_id": lot_id, "source_sha256": "d" * 64, "configuration_sha256": "c" * 64,
        "extracteur": "pypdf-6.19.0/pdf-natif-1", "revision_pdf": 1, "revision": 1,
        "statut": "A_REVOIR", "auteur": "admin-fictif", "modifie_par": "admin-fictif",
        "cle_reference": "OPSYS_INGESTION_CLE", "version_format": 1,
        "proposition_nonce": "A" * 16, "proposition_cipher": "A" * 24,
        "proposition_cipher_octets": 17,
        "cree_le": "2026-10-04T00:00:00+00:00", "modifie_le": "2026-10-04T00:00:00+00:00",
    }


def _run(lot_id: str = "00000000-0000-4000-8000-000000000001", **changes):
    row = {
        "ocr_run_id": "00000000-0000-4000-8000-000000000002",
        "pdf_lot_id": lot_id,
        "acteur": "admin-fictif",
        "source_sha256": "d" * 64,
        "revision_pdf_source": 1,
        "configuration_sha256": "e" * 64,
        "profil_id": "ocr-scan-fictif",
        "cle_reference": "OPSYS_INGESTION_CLE",
        "version_format": 1,
        "revision_run": 1,
        "statut": "RESERVE",
        "reserve_octets": _RESERVATION_MAX,
        "resultat_nonce": None,
        "resultat_cipher": None,
        "resultat_cipher_octets": 0,
        "code": None,
        "cree_le": "2026-10-04T00:00:00+00:00",
        "modifie_le": "2026-10-04T00:00:00+00:00",
    }
    row.update(changes)
    return row


def _cipher_base64(octets: int) -> str:
    return base64.b64encode(b"x" * octets).decode("ascii")


def test_migration_0024_0026_preserve_pdf_legacy_ap_et_quota(base_ocr):
    _migration("0024", descendre=True)
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(text("UPDATE fusion_pdf_quota SET lots=1,octets_cipher=17 WHERE id=1"))
        pdf_before = cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()

    _migration("head")

    with stockage.moteur().begin() as cnx:
        assert cnx.execute(select(FUSION_PDF_LOTS)).mappings().one() == pdf_before
        assert tuple(cnx.execute(select(FUSION_PDF_QUOTA.c.lots, FUSION_PDF_QUOTA.c.octets_cipher)).one()) == (1, 17)
        assert tuple(cnx.execute(select(FUSION_PDF_OCR_QUOTA)).one()) == (1, 0, 0)
        tables = set(inspect(cnx).get_table_names())
        assert {
            FUSION_AP_OCR_SOURCES.name, FUSION_PDF_OCR_RUNS.name,
            FUSION_PDF_OCR_COMMANDES.name, FUSION_PDF_OCR_QUOTA.name,
        } <= tables
        for table in (FUSION_AP_OCR_SOURCES, FUSION_PDF_OCR_RUNS, FUSION_PDF_OCR_COMMANDES,
                      FUSION_PDF_OCR_QUOTA):
            assert {column["name"] for column in inspect(cnx).get_columns(table.name)} == set(table.c.keys())
        assert {fk["referred_table"] for fk in inspect(cnx).get_foreign_keys(FUSION_AP_OCR_SOURCES.name)} == {
            FUSION_AP_BROUILLONS.name, FUSION_PDF_OCR_RUNS.name,
        }


def test_migration_0025_0026_preserve_native_ap_default_et_linkage(base_ocr):
    _migration("0025", descendre=True)
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        draft = _brouillon_ap_fictif()
        cnx.execute(FUSION_AP_BROUILLONS.insert().values(**draft))
    _migration("head")
    assert stockage.revision_courante(base_ocr) == _revision_tete()
    with stockage.moteur().begin() as cnx:
        after = dict(cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one())
        assert {key: after[key] for key in draft} == draft
        assert cnx.execute(select(FUSION_AP_OCR_SOURCES)).all() == []


def test_source_type_inconnu_refuse_a_l_insertion(base_ocr):
    lot_id = "00000000-0000-4000-8000-000000000001"
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx, lot_id)
        run = _run(lot_id)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**run))
        cnx.execute(FUSION_AP_BROUILLONS.insert().values(**_brouillon_ap_fictif(lot_id)))
    bad = {
        "lot_id": lot_id, "source_type": "OCR_AUTRE", "ocr_run_id": run["ocr_run_id"],
        "revision_run": run["revision_run"], "ocr_configuration_sha256": run["configuration_sha256"],
        "ocr_profil_id": run["profil_id"],
    }
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_AP_OCR_SOURCES.insert().values(**bad))


def test_migration_0026_ddl_panne_rollback_ajout_et_table(base_ocr, monkeypatch):
    _migration("0025", descendre=True)
    tables_avant = None
    with stockage.moteur().begin() as cnx:
        tables_avant = set(inspect(cnx).get_table_names())
    creer = op.create_table

    def panne(nom, *args, **kwargs):
        resultat = creer(nom, *args, **kwargs)
        if nom == FUSION_AP_OCR_SOURCES.name:
            raise RuntimeError("panne DDL AP OCR fictive")
        return resultat

    monkeypatch.setattr(op, "create_table", panne)
    with pytest.raises(RuntimeError, match="panne DDL AP OCR fictive"):
        _migration("0026")
    assert stockage.revision_courante(base_ocr) == "0025"
    with stockage.moteur().begin() as cnx:
        assert set(inspect(cnx).get_table_names()) == tables_avant
        assert FUSION_AP_OCR_SOURCES.name not in inspect(cnx).get_table_names()


def test_downgrade_0026_refuse_lien_ocr_conserve(base_ocr):
    lot_id = "00000000-0000-4000-8000-000000000001"
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx, lot_id)
        run = _run(lot_id, statut="RESERVE")
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**run))
        cnx.execute(FUSION_AP_BROUILLONS.insert().values(**_brouillon_ap_fictif(lot_id)))
        source = {
            "lot_id": lot_id, "source_type": "OCR_CANDIDAT", "ocr_run_id": run["ocr_run_id"],
            "revision_run": run["revision_run"], "ocr_configuration_sha256": run["configuration_sha256"],
            "ocr_profil_id": run["profil_id"],
        }
        cnx.execute(FUSION_AP_OCR_SOURCES.insert().values(**source))
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_AP_OCR_SOURCES.update().where(
            FUSION_AP_OCR_SOURCES.c.lot_id == lot_id,
        ).values(revision_run=2))
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_AP_OCR_SOURCES.delete().where(FUSION_AP_OCR_SOURCES.c.lot_id == lot_id))
    with pytest.raises(RuntimeError, match="références OCR"):
        _migration("0025", descendre=True)
    assert stockage.revision_courante(base_ocr) == _revision_tete()
    with stockage.moteur().begin() as cnx:
        assert dict(cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one()) == source


@pytest.mark.parametrize("changes", [
    {"revision_pdf_source": 0},
    {"revision_pdf_source": 2_147_483_648},
    {"revision_run": 0},
    {"version_format": 2},
    {"source_sha256": "short"},
    {"configuration_sha256": "short"},
    {"profil_id": ""},
    {"cle_reference": ""},
    {"statut": "INCONNU"},
    {"reserve_octets": _RESERVATION_MAX - 1},
    {"resultat_cipher_octets": 262_161},
])
def test_contraintes_run_rejettent_versions_tailles_et_etats_invalides(base_ocr, changes):
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**_run(**changes)))


@pytest.mark.parametrize("changes", [
    {"statut": "RESERVE", "reserve_octets": 262_159},
    {"statut": "RESERVE", "resultat_nonce": "A" * 16},
    {"statut": "A_REVOIR", "reserve_octets": 1, "resultat_nonce": "A" * 16,
     "resultat_cipher": "A" * 24, "resultat_cipher_octets": 17},
    {"statut": "A_REVOIR", "resultat_nonce": "A" * 16,
     "resultat_cipher": "A" * 23, "resultat_cipher_octets": 17},
    {"statut": "A_REVOIR", "resultat_nonce": "A" * 16,
     "resultat_cipher": "A" * 24, "resultat_cipher_octets": 17, "code": "OCR_REFUS"},
    {"statut": "REFUSE", "reserve_octets": 0, "resultat_nonce": "A" * 16,
     "resultat_cipher": "A" * 24, "resultat_cipher_octets": 17, "code": "OCR_REFUS"},
    {"statut": "PERIME", "reserve_octets": 0, "code": None},
    {"statut": "ERREUR_REPRENABLE", "reserve_octets": 0, "code": ""},
])
def test_contraintes_lient_statut_reservation_et_payload(base_ocr, changes):
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**_run(**changes)))


def test_run_a_revoir_et_commande_idempotente_sont_lies_au_pdf_et_quota(base_ocr):
    run = _run(
        statut="A_REVOIR", reserve_octets=0,
        resultat_nonce="AAAAAAAAAAAAAAAA", resultat_cipher=_cipher_base64(17),
        resultat_cipher_octets=17,
    )
    commande = {
        "acteur": "admin-fictif", "mutation_id": "ocr-mutation-fictive",
        "empreinte_requete": "f" * 64, "ocr_run_id": run["ocr_run_id"], "cree_le": "fictif",
    }
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**run))
        cnx.execute(FUSION_PDF_OCR_COMMANDES.insert().values(**commande))
        cnx.execute(FUSION_PDF_OCR_QUOTA.update().where(FUSION_PDF_OCR_QUOTA.c.id == 1).values(
            lots=1, octets_cipher=17,
        ))
        assert cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one()["statut"] == "A_REVOIR"
        assert cnx.execute(select(FUSION_PDF_OCR_COMMANDES)).mappings().one()["ocr_run_id"] == run["ocr_run_id"]
        assert tuple(cnx.execute(select(FUSION_PDF_OCR_QUOTA.c.lots,
                                       FUSION_PDF_OCR_QUOTA.c.octets_cipher)).one()) == (1, 17)


def test_a_revoir_accepte_ciphertext_base64_a_la_limite_262160(base_ocr):
    cipher = _cipher_base64(262_160)
    assert len(cipher) == 349_548
    run = _run(
        statut="A_REVOIR", reserve_octets=0, resultat_nonce="AAAAAAAAAAAAAAAA",
        resultat_cipher=cipher, resultat_cipher_octets=262_160,
    )
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**run))
        stocke = cnx.execute(select(FUSION_PDF_OCR_RUNS.c.resultat_cipher,
                                    literal_column("typeof(resultat_cipher)").label("type_sqlite"))).one()
        assert stocke.resultat_cipher == cipher
        assert stocke.type_sqlite == "text"


@pytest.mark.parametrize("cipher", [b"x" * 24, "!" * 24])
def test_sqlite_ne_valide_pas_type_ou_alphabet_cipher_service_doit_le_faire(base_ocr, cipher):
    run = _run(
        statut="A_REVOIR", reserve_octets=0, resultat_nonce="AAAAAAAAAAAAAAAA",
        resultat_cipher=cipher, resultat_cipher_octets=17,
    )
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**run))
        type_stocke = cnx.execute(select(literal_column("typeof(resultat_cipher)")).select_from(
            FUSION_PDF_OCR_RUNS,
        )).scalar_one()
        assert type_stocke == ("blob" if isinstance(cipher, bytes) else "text")


def test_unicite_source_config_independante_acteur_et_revision_ou_config_separee(base_ocr):
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**_run()))
    duplicate = _run(
        ocr_run_id="00000000-0000-4000-8000-000000000003", acteur="autre-admin-fictif",
    )
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**duplicate))
    distinct_revision = _run(
        ocr_run_id="00000000-0000-4000-8000-000000000004", revision_pdf_source=2,
    )
    distinct_profile = _run(
        ocr_run_id="00000000-0000-4000-8000-000000000005", configuration_sha256="9" * 64,
    )
    with stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**distinct_revision))
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**distinct_profile))
        assert cnx.execute(select(FUSION_PDF_OCR_RUNS.c.ocr_run_id)).all().__len__() == 3


def test_quota_ocr_est_independant_et_borne(base_ocr):
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_QUOTA.update().where(FUSION_PDF_OCR_QUOTA.c.id == 1).values(lots=17))
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_QUOTA.update().where(FUSION_PDF_OCR_QUOTA.c.id == 1).values(
            octets_cipher=4_194_305,
        ))
    with stockage.moteur().begin() as cnx:
        assert tuple(cnx.execute(select(FUSION_PDF_QUOTA.c.lots,
                                       FUSION_PDF_QUOTA.c.octets_cipher)).one()) == (0, 0)
        assert tuple(cnx.execute(select(FUSION_PDF_OCR_QUOTA)).one()) == (1, 0, 0)


def test_downgrade_refuse_runs_commandes_et_reservations_sans_perte(base_ocr):
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        run = _run()
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**run))
        cnx.execute(FUSION_PDF_OCR_COMMANDES.insert().values(
            acteur=run["acteur"], mutation_id="ocr-mutation-fictive", empreinte_requete="f" * 64,
            ocr_run_id=run["ocr_run_id"], cree_le="fictif",
        ))
    with pytest.raises(RuntimeError, match="rétrogradation refusée"):
        _migration("0024", descendre=True)
    assert stockage.revision_courante(base_ocr) == _revision_tete()
    with stockage.moteur().begin() as cnx:
        assert cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one()["ocr_run_id"] == run["ocr_run_id"]
        assert cnx.execute(select(FUSION_PDF_OCR_COMMANDES)).scalar_one()
        assert tuple(cnx.execute(select(FUSION_PDF_OCR_QUOTA)).one()) == (1, 0, 0)


@pytest.mark.parametrize("compteur", ["lots", "octets_cipher"])
def test_downgrade_refuse_compteur_quota_non_nul_sans_run(base_ocr, compteur):
    valeur = 1
    with stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_QUOTA.update().where(FUSION_PDF_OCR_QUOTA.c.id == 1).values(
            **{compteur: valeur},
        ))
    with pytest.raises(RuntimeError, match="rétrogradation refusée"):
        _migration("0024", descendre=True)
    assert stockage.revision_courante(base_ocr) == _revision_tete()
    with stockage.moteur().begin() as cnx:
        assert cnx.execute(select(FUSION_PDF_OCR_RUNS)).all() == []
        assert cnx.execute(select(FUSION_PDF_OCR_COMMANDES)).all() == []
        quota = cnx.execute(select(FUSION_PDF_OCR_QUOTA)).mappings().one()
        assert quota[compteur] == valeur


def test_downgrade_vide_puis_reupgrade_est_autorise(base_ocr):
    _migration("0024", descendre=True)
    assert stockage.revision_courante(base_ocr) == "0024"
    with stockage.moteur().begin() as cnx:
        tables = set(inspect(cnx).get_table_names())
        assert FUSION_PDF_OCR_RUNS.name not in tables
        assert FUSION_PDF_OCR_COMMANDES.name not in tables
        assert FUSION_PDF_OCR_QUOTA.name not in tables
    _migration("head")
    assert stockage.revision_courante(base_ocr) == _revision_tete()
    with stockage.moteur().begin() as cnx:
        assert tuple(cnx.execute(select(FUSION_PDF_OCR_QUOTA)).one()) == (1, 0, 0)
        assert FUSION_AP_OCR_SOURCES.name in inspect(cnx).get_table_names()


def test_fk_run_et_commande_refusent_les_parents_absents(base_ocr):
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_RUNS.insert().values(**_run("00000000-0000-4000-8000-000000000099")))
    with pytest.raises(IntegrityError), stockage.moteur().begin() as cnx:
        cnx.execute(FUSION_PDF_OCR_COMMANDES.insert().values(
            acteur="admin-fictif", mutation_id="sans-run", empreinte_requete="f" * 64,
            ocr_run_id=str(uuid.uuid4()), cree_le="fictif",
        ))


@pytest.mark.parametrize("table_en_panne", [
    FUSION_PDF_OCR_RUNS.name, FUSION_PDF_OCR_COMMANDES.name, FUSION_PDF_OCR_QUOTA.name,
])
def test_panne_ddl_ocr_annule_toutes_tables_et_revision_sans_perte_pdf(base_ocr, monkeypatch, table_en_panne):
    _migration("0024", descendre=True)
    with stockage.moteur().begin() as cnx:
        _pdf_fictif(cnx)
        avant = dict(cnx.execute(select(FUSION_PDF_LOTS)).mappings().one())
        tables_avant = set(inspect(cnx).get_table_names())
    creer = op.create_table

    def panne(nom, *args, **kwargs):
        table = creer(nom, *args, **kwargs)
        if nom == table_en_panne:
            raise RuntimeError("panne DDL OCR fictive")
        return table

    monkeypatch.setattr(op, "create_table", panne)
    with pytest.raises(RuntimeError, match="panne DDL OCR fictive"):
        _migration("0025")
    assert stockage.revision_courante(base_ocr) == "0024"
    with stockage.moteur().begin() as cnx:
        assert set(inspect(cnx).get_table_names()) == tables_avant
        assert dict(cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()) == avant
