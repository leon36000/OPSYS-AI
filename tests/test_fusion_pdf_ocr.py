"""Scénarios fictifs pour le compartiment OCR chiffré, sans moteur natif."""
from __future__ import annotations

import base64
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, update

from opsys import fusion_pdf, fusion_pdf_ocr, identite, stockage
from opsys.ocr_profil import MODELE_SHA256, PDFIUM_SHA256
from opsys.stockage.schema import (
    FUSION_PDF_LOTS,
    FUSION_PDF_OCR_COMMANDES,
    FUSION_PDF_OCR_QUOTA,
    FUSION_PDF_OCR_RUNS,
    PERSONNES,
)


@pytest.fixture(autouse=True)
def sqlite_fictive_uniquement(opsys_home, monkeypatch):
    opsys_home.mkdir(parents=True)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{opsys_home / 'qualification-fusion-pdf-ocr.db'}")


@pytest.fixture
def acteur_ocr(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"o" * 32).decode())
    return nathan


def _lot_refuse(acteur: str, *, pdf_octets: bytes = b"%PDF-1.7\n% FIXTURE OCR FICTIVE\n%%EOF\n"):
    lot = fusion_pdf.creer(
        stockage.transaction, acteur, mutation_id="admission-pdf-ocr-fictive", pdf_octets=pdf_octets,
    )
    with stockage.transaction() as cnx:
        cnx.execute(update(fusion_pdf.FUSION_PDF_LOTS).where(
            fusion_pdf.FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
        ).values(statut="REFUSE", code="PDF_IMAGE_OU_MIXTE", revision=2))
    return lot


def _runtime_fictif(source: bytes, *, lot_id: str, revision_source: int, bundle):
    from opsys.ocr_runtime import contexte_ocr

    contexte = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
    texte = "CANDIDAT OCR FICTIF"
    return {
        "schema_version": 1,
        "genre": "m5.ocr_scan_candidat",
        "statut": "CANDIDAT_A_REVOIR",
        "lot_id": contexte.lot_id,
        "source_sha256": contexte.source_sha256,
        "revision_source": contexte.revision_source,
        "configuration_sha256": contexte.configuration_sha256,
        "profil": {
            "rasteriseur": contexte.rasteriseur,
            "moteur": contexte.moteur,
            "leptonica": contexte.leptonica,
            "pdfium_sha256": contexte.pdfium_sha256,
            "modele_sha256": contexte.modele_sha256,
            "langue": "fra",
        },
        "page": {
            "numero": 1,
            "largeur_px": 100,
            "hauteur_px": 100,
            "tokens": [{"texte": texte, "x0": 1, "y0": 1, "x1": 20, "y1": 10, "confiance_brute": 91}],
        },
    }


@pytest.fixture
def moteur_ocr_fictif(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle-fictif"
    bundle.mkdir()
    monkeypatch.setattr(fusion_pdf_ocr, "valider_bundle", lambda _path: {"rasterizer/fiction": "0" * 64})
    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", _runtime_fictif)
    return bundle


def _quota():
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(FUSION_PDF_OCR_QUOTA)).mappings().one())


def test_preparer_chiffre_candidat_et_lecture_humaine_revalide_contexte(acteur_ocr, moteur_ocr_fictif):
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-fictive-01", bundle=moteur_ocr_fictif,
    )

    assert run["statut"] == "A_REVOIR"
    assert run["source_sha256"] == hashlib.sha256(b"%PDF-1.7\n% FIXTURE OCR FICTIVE\n%%EOF\n").hexdigest()
    assert run["profil_id"]
    candidat = fusion_pdf_ocr.lire_resultat(stockage.transaction, acteur_ocr, run["ocr_run_id"])
    assert candidat["statut"] == "CANDIDAT_A_REVOIR"
    assert candidat["profil"]["pdfium_sha256"] == PDFIUM_SHA256
    assert candidat["profil"]["modele_sha256"] == MODELE_SHA256
    assert "CANDIDAT OCR FICTIF" not in str(run)
    assert _quota()["lots"] == 1

    with stockage.transaction() as cnx:
        stored = cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one()
        commande = cnx.execute(select(FUSION_PDF_OCR_COMMANDES)).mappings().one()
    assert stored["statut"] == "A_REVOIR"
    assert stored["resultat_cipher"] and "CANDIDAT OCR FICTIF" not in stored["resultat_cipher"]
    assert commande["ocr_run_id"] == run["ocr_run_id"]


def test_rotation_cle_source_historique_run_avec_reference_active(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    lot = _lot_refuse(acteur_ocr)
    cle = base64.b64encode(b"o" * 32).decode()
    monkeypatch.setenv("OPSYS_INGESTION_CLE_ACTIVE_FICTIVE", cle)
    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_INGESTION_CLE_ACTIVE_FICTIVE")
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-rotation-cle", bundle=moteur_ocr_fictif,
    )
    assert run["statut"] == "A_REVOIR"
    candidat = fusion_pdf_ocr.lire_resultat(stockage.transaction, acteur_ocr, run["ocr_run_id"])
    assert candidat["statut"] == "CANDIDAT_A_REVOIR"
    with stockage.transaction() as cnx:
        stored = cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one()
    assert stored["cle_reference"] == "OPSYS_INGESTION_CLE_ACTIVE_FICTIVE"


def test_rejeu_mutation_identique_ne_relance_pas_le_moteur(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-fictive-rejeu", bundle=moteur_ocr_fictif,
    )
    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("appel OCR dupliqué"))
    rejoue = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-fictive-rejeu", bundle=moteur_ocr_fictif,
    )
    assert rejoue["ocr_run_id"] == run["ocr_run_id"]


def test_pdf_non_eligible_refuse_avant_moteur_et_sans_reservation(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    lot = fusion_pdf.creer(
        stockage.transaction, acteur_ocr, mutation_id="admission-pdf-non-ocr", pdf_octets=b"%PDF-1.7\n%%EOF\n",
    )
    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("appel OCR interdit"))
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur):
        fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], lot["revision"], "ocr-non-eligible",
            bundle=moteur_ocr_fictif,
        )
    assert _quota()["lots"] == 0


def test_saturation_quota_est_avant_runtime(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    lot = _lot_refuse(acteur_ocr)
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_OCR_QUOTA).where(FUSION_PDF_OCR_QUOTA.c.id == 1).values(lots=16))
    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("quota doit précéder OCR"))
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur):
        fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-quota-plein", bundle=moteur_ocr_fictif,
        )


def test_echec_runtime_restitue_octets_mais_garde_entree_historique(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    monkeypatch.setattr(
        fusion_pdf_ocr, "extraire_candidat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(fusion_pdf_ocr.OCRRuntimeErreur("OCR_TIMEOUT")),
    )
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-timeout-fictif", bundle=moteur_ocr_fictif,
    )
    assert run["statut"] == "ERREUR_REPRENABLE" and run["code"] == "OCR_TIMEOUT"
    assert _quota()["lots"] == 1 and _quota()["octets_cipher"] == 0
    assert fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-timeout-fictif", bundle=moteur_ocr_fictif,
    )["ocr_run_id"] == run["ocr_run_id"]


def test_run_dedup_et_commandes_bornees_sans_bloquer_rejeu(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    monkeypatch.setattr(fusion_pdf_ocr, "_COMMANDES_MAX", 1)
    lot = _lot_refuse(acteur_ocr)
    premier = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-premiere-commande", bundle=moteur_ocr_fictif,
    )
    # Une commande connue est relue avant le contrôle de capacité.
    assert fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-premiere-commande", bundle=moteur_ocr_fictif,
    )["ocr_run_id"] == premier["ocr_run_id"]
    # Une nouvelle mutation ne crée pas un alias indéfini vers le run dédupliqué.
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-seconde-commande", bundle=moteur_ocr_fictif,
        )
    assert erreur.value.code == "OCR_COMMANDES_QUOTA_ATTEINT"


def test_source_modifiee_pendant_worker_perime_et_restitue_reservation(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    def runtime_avec_mutation(source, *, lot_id, revision_source, bundle):
        with stockage.transaction() as cnx:
            cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id).values(revision=3))
        return _runtime_fictif(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime_avec_mutation)
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-source-stale", bundle=moteur_ocr_fictif,
    )
    assert run["statut"] == "PERIME" and run["code"] == "OCR_SOURCE_MODIFIEE"
    assert _quota()["lots"] == 1 and _quota()["octets_cipher"] == 0


def test_rechiffrement_identique_source_est_perime(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    source = b"%PDF-1.7\n% FIXTURE OCR FICTIVE\n%%EOF\n"

    def runtime_avec_rechiffrement(contenu, *, lot_id, revision_source, bundle):
        with stockage.transaction() as cnx:
            pdf = cnx.execute(select(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id)).mappings().one()
            nonce, cipher, size = fusion_pdf_ocr.fusion_csv._chiffrer(
                fusion_pdf_ocr.fusion_csv._cle(pdf["cle_reference"]), lot_id, pdf["source_sha256"],
                "pdf-natif-1:source", contenu,
            )
            cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == lot_id).values(
                source_nonce=nonce, source_cipher=cipher, source_cipher_octets=size,
            ))
        return _runtime_fictif(contenu, lot_id=lot_id, revision_source=revision_source, bundle=bundle)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime_avec_rechiffrement)
    lot = _lot_refuse(acteur_ocr, pdf_octets=source)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-reencrypt-fictif", bundle=moteur_ocr_fictif,
    )
    assert run["statut"] == "PERIME" and run["code"] == "OCR_SOURCE_MODIFIEE"
    assert _quota()["lots"] == 1 and _quota()["octets_cipher"] == 0


def test_cas_finalisation_race_conserve_reservation_sans_double_transition(
    acteur_ocr, moteur_ocr_fictif, monkeypatch,
):
    def runtime_cas(source, *, lot_id, revision_source, bundle):
        with stockage.transaction() as cnx:
            cnx.execute(update(FUSION_PDF_OCR_RUNS).values(revision_run=2))
        return _runtime_fictif(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime_cas)
    lot = _lot_refuse(acteur_ocr)
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-cas-race", bundle=moteur_ocr_fictif,
        )
    assert erreur.value.code == "OCR_CONFLIT_REVISION"
    run = fusion_pdf_ocr.lister(stockage.transaction, acteur_ocr)[0]
    assert run["statut"] == "RESERVE" and run["revision_run"] == 2
    assert _quota()["lots"] == 1 and _quota()["octets_cipher"] == 262_160


def test_revocation_pendant_calcul_conserve_run_reserve_sans_contournement(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    def runtime_revoque(source, *, lot_id, revision_source, bundle):
        with stockage.transaction() as cnx:
            cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == acteur_ocr).values(actif=False))
        return _runtime_fictif(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime_revoque)
    lot = _lot_refuse(acteur_ocr)
    with pytest.raises(PermissionError):
        fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-revocation", bundle=moteur_ocr_fictif,
        )
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == acteur_ocr).values(actif=True))
    run = fusion_pdf_ocr.lister(stockage.transaction, acteur_ocr)
    assert len(run) == 1 and run[0]["statut"] == "RESERVE"
    assert _quota()["lots"] == 1 and _quota()["octets_cipher"] == 262_160


@pytest.mark.parametrize("payload", ["alphabet", "blob", "nonce_unicode"])
def test_lire_refuse_ciphertext_corrompu_ou_sqlite_blob(acteur_ocr, moteur_ocr_fictif, payload):
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-cipher-corruption", bundle=moteur_ocr_fictif,
    )
    with stockage.transaction() as cnx:
        stored = cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one()
        cipher = stored["resultat_cipher"]
        if payload == "nonce_unicode":
            cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
                FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
            ).values(resultat_nonce="é" * 16))
        else:
            corrupted = ("!" * len(cipher)) if payload == "alphabet" else b"X" * len(cipher)
            cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
                FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
            ).values(resultat_cipher=corrupted))
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.lire_resultat(stockage.transaction, acteur_ocr, run["ocr_run_id"])
    assert erreur.value.code in {"OCR_RUN_CORROMPU", "OCR_RESULTAT_INDISPONIBLE", "OCR_RESULTAT_CORROMPU"}


def test_aad_lie_run_acteur_et_revision_format_et_rejette_copie(acteur_ocr, moteur_ocr_fictif):
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-aad-fictive", bundle=moteur_ocr_fictif,
    )
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
            FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
        ).values(revision_run=run["revision_run"] + 1))
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.lire_resultat(stockage.transaction, acteur_ocr, run["ocr_run_id"])
    assert erreur.value.code == "OCR_RESULTAT_CORROMPU"


def test_chiffrement_en_erreur_finalise_run_et_restitue_reservation(acteur_ocr, moteur_ocr_fictif, monkeypatch):
    lot = _lot_refuse(acteur_ocr)
    monkeypatch.setattr(
        fusion_pdf_ocr, "_chiffrer_resultat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("erreur crypto fictive")),
    )
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-crypto-failure", bundle=moteur_ocr_fictif,
    )
    assert run["statut"] == "ERREUR_REPRENABLE" and run["code"] == "OCR_CHIFFREMENT_INDISPONIBLE"
    assert _quota()["lots"] == 1 and _quota()["octets_cipher"] == 0


def test_aad_varie_avec_acteur_uuid_version_et_revision():
    row = {
        "ocr_run_id": "00000000-0000-4000-8000-000000000002",
        "pdf_lot_id": "00000000-0000-4000-8000-000000000001",
        "acteur": "admin-aad", "source_sha256": "a" * 64, "revision_pdf_source": 2,
        "profil_id": "ocr-scan-2", "configuration_sha256": "b" * 64,
        "cle_reference": "OPSYS_INGESTION_CLE", "version_format": 1,
    }
    original = fusion_pdf_ocr._aad(row, revision_run=2)
    for key, value in (
        ("acteur", "autre-acteur"), ("ocr_run_id", "00000000-0000-4000-8000-000000000003"),
        ("version_format", 2), ("cle_reference", "OPSYS_INGESTION_CLE_ARCHIVE"),
    ):
        modifie = dict(row, **{key: value})
        assert fusion_pdf_ocr._aad(modifie, revision_run=2) != original
    assert fusion_pdf_ocr._aad(row, revision_run=3) != original


def test_concurrence_meme_mutation_reserve_une_fois_et_second_appel_ne_calcule_pas(
    acteur_ocr, moteur_ocr_fictif, monkeypatch,
):
    lot = _lot_refuse(acteur_ocr)
    demarre = threading.Event()
    liberer = threading.Event()
    verrou = threading.Lock()
    appels = 0

    def worker(source, *, lot_id, revision_source, bundle):
        nonlocal appels
        with verrou:
            appels += 1
        demarre.set()
        if not liberer.wait(8):
            raise TimeoutError("barrière fictive expirée")
        return _runtime_fictif(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", worker)
    arguments = (
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-concurrence-fictive",
    )
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        premiere = executor.submit(
            fusion_pdf_ocr.preparer, *arguments, bundle=moteur_ocr_fictif,
        )
        assert demarre.wait(5), "le premier worker n'a pas atteint la barrière"
        seconde = fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-concurrence-fictive",
            bundle=moteur_ocr_fictif,
        )
        assert seconde["statut"] == "RESERVE"
        assert appels == 1 and _quota()["lots"] == 1
    finally:
        liberer.set()
        premiere_resultat = premiere.result(timeout=10)
        executor.shutdown(wait=True, cancel_futures=True)
    assert premiere_resultat["statut"] == "A_REVOIR"
    assert fusion_pdf_ocr.lire_resultat(
        stockage.transaction, acteur_ocr, premiere_resultat["ocr_run_id"],
    )["statut"] == "CANDIDAT_A_REVOIR"
    assert appels == 1 and _quota()["lots"] == 1


def test_echec_reconciliation_quota_annule_transition_et_garde_reserve(
    acteur_ocr, moteur_ocr_fictif, monkeypatch,
):
    def worker_et_corruption_quota(source, *, lot_id, revision_source, bundle):
        with stockage.transaction() as cnx:
            cnx.execute(update(FUSION_PDF_OCR_QUOTA).where(
                FUSION_PDF_OCR_QUOTA.c.id == 1,
            ).values(octets_cipher=0))
        return _runtime_fictif(source, lot_id=lot_id, revision_source=revision_source, bundle=bundle)

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", worker_et_corruption_quota)
    lot = _lot_refuse(acteur_ocr)
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.preparer(
            stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-quota-final-failure", bundle=moteur_ocr_fictif,
        )
    assert erreur.value.code == "OCR_QUOTA_CORROMPU"
    (run,) = fusion_pdf_ocr.lister(stockage.transaction, acteur_ocr)
    assert run["statut"] == "RESERVE" and run["resultat_cipher_octets"] == 0
    with stockage.transaction() as cnx:
        stored = cnx.execute(select(FUSION_PDF_OCR_RUNS)).mappings().one()
    assert stored["resultat_nonce"] is None and stored["resultat_cipher"] is None


@pytest.mark.parametrize("corruption", ["cipher_surdimensionne", "nonce_unicode"])
def test_source_sql_refuse_payload_malforme_avant_select_du_contenu(
    acteur_ocr, moteur_ocr_fictif, corruption,
):
    lot = _lot_refuse(acteur_ocr)
    with stockage.transaction() as cnx:
        if corruption == "cipher_surdimensionne":
            cnx.execute(update(FUSION_PDF_LOTS).where(
                FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
            ).values(source_cipher="A" * (fusion_pdf.SOURCE_MAX + 128)))
        else:
            cnx.execute(update(FUSION_PDF_LOTS).where(
                FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
            ).values(source_nonce="é" * 16))
    statements: list[str] = []
    moteur = stockage.moteur()
    def capturer(_connexion, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(moteur, "before_cursor_execute", capturer)
    try:
        with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
            fusion_pdf_ocr.preparer(
                stockage.transaction, acteur_ocr, lot["lot_id"], 2,
                f"ocr-source-corrupt-{corruption}", bundle=moteur_ocr_fictif,
            )
    finally:
        event.remove(moteur, "before_cursor_execute", capturer)
    assert erreur.value.code == "OCR_SOURCE_CORROMPUE"
    assert not any(
        "select fusion_pdf_lots.source_nonce, fusion_pdf_lots.source_cipher" in statement
        for statement in statements
    )


@pytest.mark.parametrize("changes", [
    {"statut": "RESERVE", "reserve_octets": 0},
    {"statut": "A_REVOIR", "reserve_octets": 1},
    {"statut": "REFUSE", "reserve_octets": 1, "code": "OCR_STRUCTURE_REFUSEE"},
])
def test_lire_refuse_etat_stockage_corrompu_apres_controles_sqlite(
    acteur_ocr, moteur_ocr_fictif, changes,
):
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-etat-corrompu", bundle=moteur_ocr_fictif,
    )
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
        cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
            FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
        ).values(**changes))
        cnx.exec_driver_sql("PRAGMA ignore_check_constraints = OFF")
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.lire(stockage.transaction, acteur_ocr, run["ocr_run_id"])
    assert erreur.value.code == "OCR_RUN_CORROMPU"


def test_lecture_exige_role_actif_et_lister_limite_fermee(acteur_ocr, moteur_ocr_fictif):
    lot = _lot_refuse(acteur_ocr)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur_ocr, lot["lot_id"], 2, "ocr-role-fictif", bundle=moteur_ocr_fictif,
    )
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "lecteur", "Lecteur fictif", "mot-de-passe-lecture-fictive", ["employee"])
    with pytest.raises(PermissionError):
        fusion_pdf_ocr.lire_resultat(stockage.transaction, "lecteur", run["ocr_run_id"])
    with pytest.raises(fusion_pdf_ocr.FusionPDFOCRErreur) as erreur:
        fusion_pdf_ocr.lister(stockage.transaction, acteur_ocr, limite=True)
    assert erreur.value.code == "LIMITE_INVALIDE"
