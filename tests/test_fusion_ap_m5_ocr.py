"""Parcours fictif OCR vers contrôles M5; SQLite et valeurs de test uniquement."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select, update

from opsys import fusion_ap, fusion_pdf, fusion_pdf_ocr, identite, stockage
from opsys.console import fusion_ap_m5, fusion_ap_m5_reference
from opsys.stockage.schema import FUSION_AP_BROUILLONS, FUSION_AP_SAISIES, FUSION_PDF_OCR_RUNS

_BASE_SPEC = importlib.util.spec_from_file_location(
    "fixture_ap_source_m5_ocr", Path(__file__).with_name("test_fusion_ap_m5.py"),
)
assert _BASE_SPEC is not None and _BASE_SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE)
_SAISIE_SPEC = importlib.util.spec_from_file_location(
    "fixture_ap_saisie_m5_ocr", Path(__file__).with_name("test_fusion_ap_m5_saisie.py"),
)
assert _SAISIE_SPEC is not None and _SAISIE_SPEC.loader is not None
_SAISIE = importlib.util.module_from_spec(_SAISIE_SPEC)
_SAISIE_SPEC.loader.exec_module(_SAISIE)


@pytest.fixture(autouse=True)
def sqlite_fictive_uniquement(opsys_home, monkeypatch):
    opsys_home.mkdir(parents=True)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{opsys_home / 'qualification-m5-ocr.db'}")


@pytest.fixture
def m5_ocr(request, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"v" * 32).decode())
    ctx = _BASE.ap_m5.__wrapped__(request.getfixturevalue("nathan"), monkeypatch, tmp_path)
    lot = fusion_pdf.creer(
        stockage.transaction, ctx["acteur"], mutation_id="ap-m5-ocr-fictif",
        pdf_octets=b"%PDF-1.7\n% FICTIF IMAGE AP OCR\n%%EOF\n",
    )
    with stockage.transaction() as cnx:
        cnx.execute(update(fusion_pdf.FUSION_PDF_LOTS).where(
            fusion_pdf.FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
        ).values(statut="REFUSE", code="PDF_IMAGE_OU_MIXTE", revision=2))
    bundle = tmp_path / "bundle-ocr-fictif"
    bundle.mkdir()
    monkeypatch.setattr(fusion_pdf_ocr, "valider_bundle", lambda _path: {"rasterizer/fictif": "0" * 64})

    def runtime(source, *, lot_id, revision_source, bundle):
        from opsys.ocr_runtime import contexte_ocr

        ctx_ocr = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
        textes = ["fournisseur-fictif", "FICTIF-2042", "2026-10-01", "PO-FICTIF-7",
                  "100.00", "14.98", "114.98", "CAD"]
        tokens = [{"texte": texte, "x0": 1 + index * 10, "y0": 1,
                   "x1": 9 + index * 10, "y1": 10, "confiance_brute": 91}
                  for index, texte in enumerate(textes)]
        return {
            "schema_version": 1, "genre": "m5.ocr_scan_candidat", "statut": "CANDIDAT_A_REVOIR",
            "lot_id": ctx_ocr.lot_id, "source_sha256": ctx_ocr.source_sha256,
            "revision_source": ctx_ocr.revision_source,
            "configuration_sha256": ctx_ocr.configuration_sha256,
            "profil": {"rasteriseur": ctx_ocr.rasteriseur, "moteur": ctx_ocr.moteur,
                       "leptonica": ctx_ocr.leptonica, "pdfium_sha256": ctx_ocr.pdfium_sha256,
                       "modele_sha256": ctx_ocr.modele_sha256, "langue": "fra"},
            "page": {"numero": 1, "largeur_px": 100, "hauteur_px": 100, "tokens": tokens},
        }

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", runtime)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, ctx["acteur"], lot["lot_id"], 2,
        "ap-m5-ocr-run-fictif", bundle=bundle,
    )
    assert run["statut"] == "A_REVOIR"
    vide = fusion_ap.creer_brouillon_ocr(
        stockage.transaction, ctx["acteur"], lot["lot_id"], mutation_id="ap-m5-ocr-vide-fictif",
        revision_pdf_attendue=2, ocr_run_id=run["ocr_run_id"], revision_run=run["revision_run"],
    )
    with stockage.transaction() as cnx:
        lot_courant = fusion_pdf._lot(cnx, lot["lot_id"])
        brouillon_vide, proposition_vide = fusion_ap._lire_brouillon(
            cnx, lot_courant, dechiffrer_ocr=True,
        )
    assert proposition_vide["champs"] == {cle: "" for cle in fusion_ap._CHAMPS}
    assert proposition_vide["citations"] == {}
    candidat = fusion_pdf_ocr.lire_resultat(stockage.transaction, ctx["acteur"], run["ocr_run_id"])
    index_champ = {"fournisseur": 0, "numero": 1, "date": 2, "po": 3,
                   "sous_total_imprime": 4, "taxe_imprimee": 5, "total_imprime": 6, "devise": 7}
    champs = {"fournisseur": "fournisseur-fictif", "numero": "FICTIF-2042",
              "date": "2026-10-01", "po": "PO-FICTIF-7", "sous_total_imprime": "100.00",
              "taxe_imprimee": "14.98", "total_imprime": "114.98", "devise": "CAD"}
    proposition = {"schema_version": 1, "champs": champs,
                   "citations": {cle: [{"page": 1, "token_index": index_champ[cle],
                                        "token_sha256": fusion_ap._empreinte_token(
                                            candidat["page"]["tokens"][index_champ[cle]])}]
                                 for cle in champs}}
    brouillon = fusion_ap.enregistrer_ocr(
        stockage.transaction, ctx["acteur"], lot["lot_id"], mutation_id="ap-m5-ocr-correction-fictive",
        revision_pdf_attendue=2, revision_attendue=vide["revision"], ocr_run_id=run["ocr_run_id"],
        revision_run=run["revision_run"], proposition=proposition,
    )
    ctx.update({"pdf": {"lot_id": lot["lot_id"], "revision": 2}, "run": run,
                "brouillon": brouillon, "proposition": proposition,
                "brouillon_vide": brouillon_vide, "proposition_vide": proposition_vide})
    return ctx


def _verifier(ctx, lot_id=None, **options):
    args = {"revision_pdf": ctx["pdf"]["revision"], "revision_ap": ctx["brouillon"]["revision"],
            "po_id": "PO-FICTIF-7", "fournisseur_id": "fournisseur-fictif",
            "correspondance_confirmee": True}
    args.update(options)
    return fusion_ap_m5.verifier(stockage.transaction, ctx["acteur"], lot_id or ctx["pdf"]["lot_id"], **args)


def test_candidat_huit_champs_vides_correction_citee_et_verification_pure(m5_ocr):
    before = _BASE._tables()
    assert m5_ocr["proposition_vide"]["champs"] == {cle: "" for cle in fusion_ap._CHAMPS}
    assert m5_ocr["proposition_vide"]["citations"] == {}
    assert m5_ocr["brouillon_vide"]["source_type"] == "OCR_CANDIDAT"
    assert m5_ocr["proposition"]["champs"] == {
        "fournisseur": "fournisseur-fictif", "numero": "FICTIF-2042", "date": "2026-10-01",
        "po": "PO-FICTIF-7", "sous_total_imprime": "100.00", "taxe_imprimee": "14.98",
        "total_imprime": "114.98", "devise": "CAD",
    }
    assert set(m5_ocr["proposition"]["citations"]) == fusion_ap._CHAMPS

    resultat = _verifier(m5_ocr)
    assert resultat["statut"] == "CONTROLES_M5_COMPATIBLES"
    assert resultat["calcul"]["montant_apres_taxes"] == "114.98"
    assert resultat["source"] == {
        "revision_pdf": 2, "revision_ap": m5_ocr["brouillon"]["revision"],
        "source_sha256": m5_ocr["brouillon"]["source_sha256"],
        "configuration_sha256": m5_ocr["brouillon"]["configuration_sha256"],
        "proposition_sha256": hashlib.sha256(json.dumps(
            m5_ocr["proposition"], sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest(),
        "registre": resultat["source"]["registre"],
        "taux_sha256": resultat["source"]["taux_sha256"],
        "source_type": "OCR_CANDIDAT", "ocr_run_id": m5_ocr["run"]["ocr_run_id"],
        "revision_run": m5_ocr["run"]["revision_run"],
        "ocr_configuration_sha256": m5_ocr["run"]["configuration_sha256"],
        "ocr_profil_id": m5_ocr["run"]["profil_id"],
    }
    fusion_ap_m5.confirmer_sources(stockage.transaction, m5_ocr["acteur"], m5_ocr["pdf"]["lot_id"], resultat)
    assert _BASE._tables() == before


def test_saisie_n3_ocr_reference_et_rejeu_sans_second_append(m5_ocr):
    before = len(_SAISIE._compter_registre())
    resultat = _verifier(m5_ocr)
    recu = _SAISIE._saisir(m5_ocr, resultat, mutation_id="m5-ocr-saisie-fictive")
    assert recu["statut"] == "SAISIE_M5_REFERENCEE" and recu["rejoue"] is False
    assert len(_SAISIE._compter_registre()) == before + 1
    reference = fusion_ap_m5_reference.lire(
        stockage.transaction, m5_ocr["acteur"], m5_ocr["pdf"]["lot_id"],
    )
    assert reference is not None and reference["statut_m5"] in {"SAISIE", "CORRIGEE"}
    with stockage.transaction() as cnx:
        preuve = json.loads(cnx.execute(select(FUSION_AP_SAISIES.c.preuve_json).where(
            FUSION_AP_SAISIES.c.lot_id == m5_ocr["pdf"]["lot_id"],
        )).scalar_one())
    assert preuve["source"]["source_type"] == "OCR_CANDIDAT"
    rejoue = _SAISIE._saisir(m5_ocr, resultat, mutation_id="m5-ocr-saisie-fictive")
    assert rejoue == {**recu, "rejoue": True}
    assert len(_SAISIE._compter_registre()) == before + 1


@pytest.mark.parametrize("cas", ["wrong_lot", "stale_run", "cipher", "role"])
def test_sources_ocr_invalides_ou_autre_lot_refuses_sans_saisie(m5_ocr, cas):
    lot_id = m5_ocr["pdf"]["lot_id"]
    if cas == "wrong_lot":
        other = fusion_pdf.creer(
            stockage.transaction, m5_ocr["acteur"], mutation_id="m5-ocr-autre-lot-fictif",
            pdf_octets=b"%PDF-1.7\n% AUTRE LOT FICTIF\n%%EOF\n",
        )
        lot_id = other["lot_id"]
    elif cas == "stale_run":
        with stockage.transaction() as cnx:
            cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
                FUSION_PDF_OCR_RUNS.c.ocr_run_id == m5_ocr["run"]["ocr_run_id"],
            ).values(revision_run=FUSION_PDF_OCR_RUNS.c.revision_run + 1))
    elif cas == "cipher":
        with stockage.transaction() as cnx:
            cipher = cnx.execute(select(FUSION_AP_BROUILLONS.c.proposition_cipher).where(
                FUSION_AP_BROUILLONS.c.lot_id == lot_id,
            )).scalar_one()
            alt = ("A" if cipher[0] != "A" else "B") + cipher[1:]
            cnx.execute(update(FUSION_AP_BROUILLONS).where(
                FUSION_AP_BROUILLONS.c.lot_id == lot_id,
            ).values(proposition_cipher=alt))
    else:
        with stockage.transaction() as cnx:
            identite.creer_personne(cnx, "admin-m5-ocr-fictif", "Admin fictif",
                                    "phrase-fictive-de-qualification", ["admin"])
        m5_ocr["acteur"] = "admin-m5-ocr-fictif"
    before = _BASE._tables()
    with pytest.raises((fusion_ap.FusionAPErreur, PermissionError)):
        _verifier(m5_ocr, lot_id=lot_id)
    assert _BASE._tables() == before


def test_source_run_modifie_apres_verification_perime_terminal_et_n3(m5_ocr):
    resultat = _verifier(m5_ocr)
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
            FUSION_PDF_OCR_RUNS.c.ocr_run_id == m5_ocr["run"]["ocr_run_id"],
        ).values(revision_run=FUSION_PDF_OCR_RUNS.c.revision_run + 1))
    before = _BASE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur):
        fusion_ap_m5.confirmer_sources(
            stockage.transaction, m5_ocr["acteur"], m5_ocr["pdf"]["lot_id"], resultat,
        )
    with pytest.raises(fusion_ap.FusionAPErreur):
        _SAISIE._saisir(m5_ocr, resultat, mutation_id="m5-ocr-expire-fictif")
    assert _BASE._tables() == before
