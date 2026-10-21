"""Brouillons AP chiffrés : les fixtures et les personnes restent fictives."""

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import io
import json
import threading

import pytest
from alembic import command
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text, update

from opsys import etat, fusion_ap, fusion_pdf, fusion_pdf_ocr, stockage
from opsys.stockage.schema import (
    FUSION_AP_BROUILLONS,
    FUSION_AP_COMMANDES,
    FUSION_AP_OCR_SOURCES,
    FUSION_COMMANDES,
    FUSION_LOTS,
    FUSION_PDF_LOTS,
    FUSION_PDF_OCR_RUNS,
    FUSION_PDF_QUOTA,
    PERSONNES,
    REGISTRES,
)


def _facture_pdf_fictive(unique: str = "") -> bytes:
    sortie = io.BytesIO()
    pdf = canvas.Canvas(sortie, invariant=1)
    pdf.setTitle(f"Facture fournisseur fictive {unique}")
    pdf.drawString(40, 780, "FOURNISSEUR FICTIF — EXEMPLE UNIQUEMENT")
    pdf.drawString(40, 750, "Facture no: FICTIF-2042")
    pdf.drawString(40, 730, "Date: 2026-10-01")
    pdf.drawString(40, 710, "Bon de commande: PO-FICTIF-7")
    pdf.drawString(40, 670, "Sous-total: 100.00 CAD")
    pdf.drawString(40, 650, "TPS: 5.00 CAD")
    pdf.drawString(40, 630, "TVQ: 9.98 CAD")
    pdf.drawString(40, 610, "Total: 114.98 CAD")
    pdf.showPage()
    pdf.save()
    return sortie.getvalue()


def _pdf_prete(acteur: str, mutation_id: str = "ap-pdf-fictif-1") -> dict:
    lot = fusion_pdf.creer(
        stockage.transaction,
        acteur,
        mutation_id=mutation_id,
        pdf_octets=_facture_pdf_fictive(mutation_id),
    )
    return fusion_pdf.preparer(stockage.transaction, acteur, lot["lot_id"], lot["revision"])


def _creer_brouillon_fictif(acteur: str, suffixe: str) -> dict:
    pdf = _pdf_prete(acteur, f"ap-pdf-fictif-{suffixe}")
    resultat = fusion_pdf.lire_resultat(stockage.transaction, acteur, pdf["lot_id"])
    return fusion_ap.enregistrer(
        stockage.transaction,
        acteur,
        pdf["lot_id"],
        mutation_id=f"ap-brouillon-fictif-{suffixe}",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=_payload(resultat),
    )


def _payload(resultat: dict, *, total: str = "114.98 CAD") -> dict:
    fragment = resultat["pages"][0]["fragments"][0]
    return {
        "schema_version": 1,
        "champs": {
            "fournisseur": "FOURNISSEUR FICTIF",
            "numero": "FICTIF-2042",
            "date": "2026-10-01",
            "po": "PO-FICTIF-7",
            "sous_total_imprime": "100.00 CAD",
            "taxe_imprimee": "TPS: 5.00 CAD; TVQ: 9.98 CAD",
            "total_imprime": total,
            "devise": "CAD",
        },
        "citations": {
            cle: [{"page": 1, "fragment_id": fragment["id"], "fragment_sha256": fragment["sha256"]}]
            for cle in (
                "fournisseur",
                "numero",
                "date",
                "po",
                "sous_total_imprime",
                "taxe_imprimee",
                "total_imprime",
                "devise",
            )
        },
    }


def _lot_ocr_fictif(acteur: str, suffixe: str, monkeypatch, tmp_path) -> tuple[dict, dict]:
    pdf_octets = f"%PDF-1.7\n% FIXTURE OCR FINANCIERE FICTIVE {suffixe}\n%%EOF\n".encode("ascii")
    lot = fusion_pdf.creer(
        stockage.transaction, acteur, mutation_id=f"ap-ocr-pdf-{suffixe}", pdf_octets=pdf_octets,
    )
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).where(
            FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
        ).values(statut="REFUSE", code="PDF_IMAGE_OU_MIXTE", revision=2))

    bundle = tmp_path / f"bundle-ocr-fictif-{suffixe}"
    bundle.mkdir()
    monkeypatch.setattr(fusion_pdf_ocr, "valider_bundle", lambda _path: {"rasterizer/fictif": "0" * 64})

    def extraire(source: bytes, *, lot_id: str, revision_source: int, bundle):
        from opsys.ocr_runtime import contexte_ocr

        contexte = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
        return {
            "schema_version": 1, "genre": "m5.ocr_scan_candidat", "statut": "CANDIDAT_A_REVOIR",
            "lot_id": contexte.lot_id, "source_sha256": contexte.source_sha256,
            "revision_source": contexte.revision_source,
            "configuration_sha256": contexte.configuration_sha256,
            "profil": {
                "rasteriseur": contexte.rasteriseur, "moteur": contexte.moteur,
                "leptonica": contexte.leptonica, "pdfium_sha256": contexte.pdfium_sha256,
                "modele_sha256": contexte.modele_sha256, "langue": "fra",
            },
            "page": {"numero": 1, "largeur_px": 100, "hauteur_px": 100, "tokens": [
                {"texte": "FOURNISSEUR OCR FICTIF", "x0": 1, "y0": 1, "x1": 40, "y1": 10,
                 "confiance_brute": 91},
                {"texte": "114.98", "x0": 1, "y0": 12, "x1": 20, "y1": 20,
                 "confiance_brute": 82},
            ]},
        }

    monkeypatch.setattr(fusion_pdf_ocr, "extraire_candidat", extraire)
    run = fusion_pdf_ocr.preparer(
        stockage.transaction, acteur, lot["lot_id"], 2, f"ap-ocr-run-{suffixe}", bundle=bundle,
    )
    return {**lot, "revision": 2}, run


def _payload_ocr(candidat: dict, *, altered_hash: bool = False) -> dict:
    token = candidat["page"]["tokens"][0]
    empreinte = hashlib.sha256(json.dumps(
        token, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    champs = {cle: "" for cle in fusion_ap._CHAMPS}
    champs["fournisseur"] = "FOURNISSEUR HUMAIN FICTIF"
    return {
        "schema_version": 1,
        "champs": champs,
        "citations": {"fournisseur": [{
            "page": 1, "token_index": 0, "token_sha256": "0" * 64 if altered_hash else empreinte,
        }]},
    }


def _migration_ap(revision: str, *, descendre: bool = False) -> None:
    cfg = stockage._config()
    with stockage.moteur().begin() as cnx:
        cfg.attributes["connection"] = cnx
        (command.downgrade if descendre else command.upgrade)(cfg, revision)


def test_brouillon_ocr_fictif_vide_puis_saisie_humaine_citee_rejeu_et_aad(
    nathan, monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"z" * 32).decode())
    lot, run = _lot_ocr_fictif(nathan, "parcours", monkeypatch, tmp_path)
    candidat = fusion_pdf_ocr.lire_resultat(stockage.transaction, nathan, run["ocr_run_id"])
    source = {"ocr_run_id": run["ocr_run_id"], "revision_run": run["revision_run"]}

    cree = fusion_ap.creer_brouillon_ocr(
        stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-cree-fictif",
        revision_pdf_attendue=lot["revision"], **source,
    )
    assert cree["source_type"] == "OCR_CANDIDAT" and cree["revision_run"] == run["revision_run"]
    assert fusion_ap.lire_champs(stockage.transaction, nathan, lot["lot_id"]) == {
        "schema_version": 1,
        "champs": {cle: "" for cle in fusion_ap._CHAMPS},
        "citations": {},
    }
    proposition = _payload_ocr(candidat)
    modifie = fusion_ap.enregistrer_ocr(
        stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-saisie-fictive",
        revision_pdf_attendue=lot["revision"], revision_attendue=1, **source, proposition=proposition,
    )
    assert modifie["revision"] == 2 and modifie["source_type"] == "OCR_CANDIDAT"
    assert fusion_ap.lire_revue_privee(stockage.transaction, nathan, lot["lot_id"])["proposition"] == proposition
    assert fusion_ap.creer_brouillon_ocr(
        stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-cree-fictif",
        revision_pdf_attendue=lot["revision"], **source,
    )["revision_appliquee"] == 1

    with stockage.transaction() as cnx:
        source_row = dict(cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one())
        brouillon = dict(cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one())
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 2
        assert "FOURNISSEUR OCR FICTIF" not in brouillon["proposition_cipher"]
    assert source_row["source_type"] == "OCR_CANDIDAT"
    # Même proposition et même lot, mais autre identité OCR: l'AAD ne déchiffre plus.
    mauvais = {**brouillon, **source_row, "ocr_run_id": "00000000-0000-4000-8000-000000000099"}
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap._dechiffrer(mauvais)
    assert erreur.value.code == "CIPHER_INVALIDE"


def test_rejeu_commande_native_heriteree_apres_migration_0026(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"h" * 32).decode())
    pdf = _pdf_prete(nathan, "ap-native-heritage")
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    proposition = fusion_ap._valider_proposition(_payload(resultat), resultat)
    mutation_id = "ap-native-avant-0026"
    cree = fusion_ap.enregistrer(
        stockage.transaction, nathan, pdf["lot_id"], mutation_id=mutation_id,
        revision_pdf_attendue=pdf["revision"], revision_attendue=0, proposition=proposition,
    )
    empreinte_ancienne = hashlib.sha256(json.dumps(
        {"revision_pdf": pdf["revision"], "revision_ap": 0, "proposition": proposition},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    with stockage.transaction() as cnx:
        commande_native = cnx.execute(select(FUSION_AP_COMMANDES).where(
            FUSION_AP_COMMANDES.c.lot_id == pdf["lot_id"],
            FUSION_AP_COMMANDES.c.mutation_id == mutation_id,
        )).mappings().one()
        assert commande_native["empreinte_requete"] == empreinte_ancienne

    _migration_ap("0025", descendre=True)
    _migration_ap("head")
    reprise = fusion_ap.enregistrer(
        stockage.transaction, nathan, pdf["lot_id"], mutation_id=mutation_id,
        revision_pdf_attendue=pdf["revision"], revision_attendue=0, proposition=proposition,
    )
    assert cree["revision_appliquee"] == reprise["revision_appliquee"] == 1


def test_brouillon_ocr_refuse_hash_mauvais_lot_stale_et_quota_sans_mutation(
    nathan, monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"q" * 32).decode())
    lot, run = _lot_ocr_fictif(nathan, "refus", monkeypatch, tmp_path)
    candidat = fusion_pdf_ocr.lire_resultat(stockage.transaction, nathan, run["ocr_run_id"])
    source = {"ocr_run_id": run["ocr_run_id"], "revision_run": run["revision_run"]}
    mauvais_hash = _payload_ocr(candidat, altered_hash=True)
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer_ocr(
            stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-hash-refuse",
            revision_pdf_attendue=lot["revision"], revision_attendue=0, **source, proposition=mauvais_hash,
        )
    assert erreur.value.code == "CITATION_INVALIDE"

    with stockage.transaction() as cnx:
        quota_avant = cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one()
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer_ocr(
            stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-direct-nonvide",
            revision_pdf_attendue=lot["revision"], revision_attendue=0,
            **source, proposition=_payload_ocr(candidat),
        )
    assert erreur.value.code == "BROUILLON_AP_ABSENT"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_OCR_SOURCES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0
        assert cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one() == quota_avant

    autre, autre_run = _lot_ocr_fictif(nathan, "mauvais-lot", monkeypatch, tmp_path)
    assert autre["lot_id"] != lot["lot_id"] and autre_run["ocr_run_id"] != run["ocr_run_id"]
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.creer_brouillon_ocr(
            stockage.transaction, nathan, autre["lot_id"], mutation_id="ap-ocr-mauvais-lot",
            revision_pdf_attendue=autre["revision"], **source,
        )
    assert erreur.value.code == "SOURCE_OCR_OBSOLETE"
    assert autre_run["ocr_run_id"] != run["ocr_run_id"]

    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
            FUSION_PDF_OCR_RUNS.c.ocr_run_id == run["ocr_run_id"],
        ).values(revision_run=run["revision_run"] + 1))
    with pytest.raises(fusion_ap.FusionAPErreur):
        fusion_ap.creer_brouillon_ocr(
            stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-run-obsolete",
            revision_pdf_attendue=lot["revision"], **source,
        )
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_OCR_SOURCES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0


def test_brouillon_ocr_relecture_refuse_source_run_ou_ciphertext_modifies(
    nathan, monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"w" * 32).decode())
    lot, run = _lot_ocr_fictif(nathan, "perime", monkeypatch, tmp_path)
    created = fusion_ap.creer_brouillon_ocr(
        stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-perime-cree",
        revision_pdf_attendue=lot["revision"], ocr_run_id=run["ocr_run_id"],
        revision_run=run["revision_run"],
    )
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).where(
            FUSION_PDF_LOTS.c.lot_id == lot["lot_id"],
        ).values(source_sha256="0" * 64))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.lire_revue_privee(stockage.transaction, nathan, lot["lot_id"])
    assert erreur.value.code == "OCR_RESULTAT_INDISPONIBLE"
    with pytest.raises(fusion_ap.FusionAPErreur):
        fusion_ap.creer_brouillon_ocr(
            stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-perime-nouvelle-tentative",
            revision_pdf_attendue=lot["revision"], ocr_run_id=run["ocr_run_id"],
            revision_run=run["revision_run"],
        )
    with stockage.transaction() as cnx:
        source_row = dict(cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one())
        assert source_row["ocr_run_id"] == run["ocr_run_id"]
        assert source_row["revision_run"] == run["revision_run"]
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 1
    assert created["revision"] == 1


def test_brouillon_ocr_ciphertext_corrompu_refuse_sans_perdre_provenance(
    nathan, monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"z" * 32).decode())
    lot, run = _lot_ocr_fictif(nathan, "cipher-corrompu", monkeypatch, tmp_path)
    fusion_ap.creer_brouillon_ocr(
        stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-cipher-cree",
        revision_pdf_attendue=lot["revision"], ocr_run_id=run["ocr_run_id"],
        revision_run=run["revision_run"],
    )
    with stockage.transaction() as cnx:
        row = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        cipher = row["proposition_cipher"]
        emplacement = 8
        remplacement = "A" if cipher[emplacement] != "A" else "B"
        cnx.execute(update(FUSION_AP_BROUILLONS).where(
            FUSION_AP_BROUILLONS.c.lot_id == lot["lot_id"],
        ).values(proposition_cipher=cipher[:emplacement] + remplacement + cipher[emplacement + 1:]))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.lire_revue_privee(stockage.transaction, nathan, lot["lot_id"])
    assert erreur.value.code == "CIPHER_INVALIDE"
    with stockage.transaction() as cnx:
        source = cnx.execute(select(FUSION_AP_OCR_SOURCES)).mappings().one()
        assert source["ocr_run_id"] == run["ocr_run_id"]
        assert source["revision_run"] == run["revision_run"]


def test_brouillon_ocr_quota_refuse_rollback_sans_modifier_quota_ocr_ou_source(
    nathan, monkeypatch, tmp_path,
):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"r" * 32).decode())
    lot, run = _lot_ocr_fictif(nathan, "quota", monkeypatch, tmp_path)
    with stockage.transaction() as cnx:
        cnx.execute(FUSION_PDF_QUOTA.update().where(FUSION_PDF_QUOTA.c.id == 1).values(
            octets_cipher=fusion_pdf.QUOTA_CIPHER_MAX,
        ))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.creer_brouillon_ocr(
            stockage.transaction, nathan, lot["lot_id"], mutation_id="ap-ocr-quota-refuse",
            revision_pdf_attendue=lot["revision"], ocr_run_id=run["ocr_run_id"],
            revision_run=run["revision_run"],
        )
    assert erreur.value.code == "PDF_QUOTA_ATTEINT"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_OCR_SOURCES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0
        assert cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one() == fusion_pdf.QUOTA_CIPHER_MAX
        assert cnx.execute(select(FUSION_PDF_OCR_RUNS.c.statut)).scalar_one() == "A_REVOIR"


def test_brouillon_ap_chiffre_cite_idempotent_et_sans_ecriture_comptable(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"a" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    payload = _payload(resultat)

    meta = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-1",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=payload,
    )
    assert meta["statut"] == "A_REVOIR" and meta["revision"] == 1
    assert "champs" not in meta and "citations" not in meta and "cipher" not in meta
    assert (
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-1",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=payload,
        )
        == meta
    )

    modifie = _payload(resultat, total="114.98 CAD — corrigé par humain")
    courant = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-1b",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=1,
        proposition=modifie,
    )
    reprise = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-1",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=payload,
    )
    assert courant["revision"] == 2
    assert reprise["revision"] == 2 and reprise["revision_appliquee"] == 1

    prive = fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])
    assert prive["champs"] == modifie["champs"]
    assert prive["citations"] == modifie["citations"]
    with stockage.transaction() as cnx:
        lot = cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        quota = cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one()
        journal = etat.lire_journal(cnx)
        assert (
            brouillon["proposition_cipher"]
            != base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        )
        assert "FICTIF-2042" not in brouillon["proposition_cipher"]
        assert quota["octets_cipher"] == (
            lot["source_cipher_octets"] + lot["resultat_cipher_octets"] + brouillon["proposition_cipher_octets"]
        )
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 2
        assert all("FICTIF-2042" not in row["details"] and "114.98" not in row["details"] for row in journal)


def test_liste_a_revoir_bornee_metadonnees_seulement_et_sans_ecriture(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"l" * 32).decode())
    premiers = [_creer_brouillon_fictif(nathan, suffixe) for suffixe in ("liste-a", "liste-b")]
    avant = None
    with stockage.transaction() as cnx:
        avant = (
            cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
        )

    monkeypatch.setattr(fusion_ap, "_dechiffrer", lambda *_: pytest.fail("liste a déchiffré un brouillon"))
    rows = fusion_ap.lister_a_revoir(stockage.transaction, nathan)
    assert len(rows) == 2
    assert {row["lot_id"] for row in rows} == {row["lot_id"] for row in premiers}
    assert all(row["etat_source"] == "A_REVALIDER" and row["statut"] == "A_REVOIR" for row in rows)
    assert all(
        set(row) == {"lot_id", "revision", "statut", "cree_le", "modifie_le", "etat_source"}
        for row in rows
    )
    assert all("fournisseur" not in row and "source_sha256" not in row and "cipher" not in row for row in rows)
    with stockage.transaction() as cnx:
        apres = (
            cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
        )
    assert apres == avant
    with pytest.raises(fusion_ap.FusionAPErreur) as depassement:
        fusion_ap.lister_a_revoir(stockage.transaction, nathan, limite=1)
    assert depassement.value.code == "LISTE_AP_DEPASSE_QUOTA"
    with pytest.raises(fusion_ap.FusionAPErreur) as invalide:
        fusion_ap.lister_a_revoir(stockage.transaction, nathan, limite=fusion_pdf.NB_LOTS_MAX + 1)
    assert invalide.value.code == "LIMITE_INVALIDE"


def test_liste_a_revoir_marque_source_changee_et_etat_malforme_indisponibles(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"m" * 32).decode())
    draft = _creer_brouillon_fictif(nathan, "liste-stale")
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FUSION_PDF_LOTS)
            .where(FUSION_PDF_LOTS.c.lot_id == draft["lot_id"])
            .values(source_sha256="0" * 64)
        )
    row = fusion_ap.lister_a_revoir(stockage.transaction, nathan)[0]
    assert row["lot_id"] == draft["lot_id"]
    assert row["etat_source"] == "INDISPONIBLE"
    assert set(row) == {"lot_id", "revision", "statut", "cree_le", "modifie_le", "etat_source"}

    base = {
        "ap_lot_id": draft["lot_id"], "ap_statut": "A_REVOIR", "ap_revision": 1,
        "ap_revision_pdf": 1, "ap_version_format": 1, "ap_source_sha256": "a" * 64,
        "ap_configuration_sha256": "b" * 64, "ap_extracteur": fusion_pdf.EXTRACTEUR,
        "ap_cree_le": "2026-10-03T00:00:00+00:00", "ap_modifie_le": "2026-10-03T00:00:00+00:00",
        "pdf_lot_id": draft["lot_id"], "pdf_statut": "EXTRAIT_PREPARATOIRE", "pdf_revision": 1,
        "pdf_version_format": 1, "pdf_type_source": "pdf_natif", "pdf_classe": "FINANCIAL",
        "pdf_source_sha256": "a" * 64, "pdf_configuration_sha256": "b" * 64,
        "pdf_extracteur": fusion_pdf.EXTRACTEUR, "pdf_modifie_le": "2026-10-03T00:00:00+00:00",
    }
    base["ap_statut"] = "ETAT_INCONNU"
    assert fusion_ap._projection_liste_ap(base)["etat_source"] == "INDISPONIBLE"
    base["ap_statut"] = "A_REVOIR"
    base["pdf_lot_id"] = None
    assert fusion_ap._projection_liste_ap(base)["etat_source"] == "INDISPONIBLE"


def test_brouillon_ap_cas_citation_invalide_rejeu_mutation_et_quota_rollback(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"b" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    payload = _payload(resultat)
    trop_long = json.loads(json.dumps(payload))
    trop_long["champs"]["numero"] = "x" * 129
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-long",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=trop_long,
        )
    assert erreur.value.code == "PROPOSITION_INVALIDE"
    cite_fausse = json.loads(json.dumps(payload))
    cite_fausse["citations"]["total_imprime"][0]["fragment_sha256"] = "0" * 64
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-2",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=cite_fausse,
        )
    assert erreur.value.code == "CITATION_INVALIDE"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0

    meta = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-2",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=payload,
    )
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-2",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=_payload(resultat, total="999999.00 CAD"),
        )
    assert erreur.value.code == "CONFLIT_MUTATION"

    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-stale",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=_payload(resultat, total="114.99 CAD"),
        )
    assert erreur.value.code == "CONFLIT_REVISION"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 1
        assert cnx.execute(select(FUSION_AP_BROUILLONS.c.revision)).scalar_one() == 1

    with stockage.transaction() as cnx:
        octets_apres_creation = cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one()
        cnx.execute(FUSION_PDF_QUOTA.update().values(octets_cipher=fusion_pdf.QUOTA_CIPHER_MAX))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-3",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=meta["revision"],
            proposition=_payload(resultat, total="114.98 CAD revised"),
        )
    assert erreur.value.code == "PDF_QUOTA_ATTEINT"
    with stockage.transaction() as cnx:
        quota = cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one()
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        assert octets_apres_creation < quota["octets_cipher"] == fusion_pdf.QUOTA_CIPHER_MAX
        assert brouillon["revision"] == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0


def test_brouillon_ap_cle_historique_et_autorisation_active(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"c" * 32).decode())
    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_CLE_PDF_OLD")
    monkeypatch.setenv("OPSYS_CLE_PDF_OLD", base64.b64encode(b"d" * 32).decode())
    monkeypatch.setenv("OPSYS_CLE_PDF_NEW", base64.b64encode(b"e" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    meta = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-4",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=_payload(resultat),
    )
    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_CLE_PDF_NEW")
    assert fusion_ap.lire(stockage.transaction, nathan, pdf["lot_id"]) == {
        cle: valeur for cle, valeur in meta.items() if cle != "revision_appliquee"
    }
    assert fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])["champs"]["numero"] == "FICTIF-2042"
    monkeypatch.setenv("OPSYS_CLE_PDF_OLD", base64.b64encode(b"x" * 32).decode())
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])
    assert erreur.value.code == "CIPHER_INVALIDE" and "FICTIF-2042" not in str(erreur.value)
    monkeypatch.setenv("OPSYS_CLE_PDF_OLD", base64.b64encode(b"d" * 32).decode())
    with stockage.transaction() as cnx:
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        assert brouillon["cle_reference"] == "OPSYS_CLE_PDF_OLD"
        from opsys import identite

        identite.creer_personne(cnx, "lecteur-fictif", "Lecteur fictif", "long-test-password-123", ["employee"])
    with pytest.raises(PermissionError):
        fusion_ap.lire_champs(stockage.transaction, "lecteur-fictif", pdf["lot_id"])
    with stockage.transaction() as cnx:
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        cnx.execute(FUSION_AP_BROUILLONS.update().values(proposition_cipher="!" + brouillon["proposition_cipher"][1:]))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])
    assert erreur.value.code == "CIPHER_INVALIDE"


def test_migration_0020_additive_conserve_csv_et_pdf(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration-ap-fictive.db'}"
    try:
        with stockage.moteur(url).begin() as cnx:
            configuration = stockage._config()
            configuration.attributes["connection"] = cnx
            from alembic import command

            command.upgrade(configuration, "0019")
            cnx.execute(text("UPDATE fusion_quota SET lots=3,octets_cipher=321 WHERE id=1"))
            cnx.execute(text("UPDATE fusion_pdf_quota SET lots=1,octets_cipher=432 WHERE id=1"))
            cnx.execute(
                FUSION_LOTS.insert().values(
                    lot_id="csv-fictif-conserve",
                    acteur="admin-fictif",
                    mutation_id="csv-ancien",
                    empreinte_requete="e" * 64,
                    cle_deduplication="f" * 64,
                    compte_interne_id="compte-fictif",
                    devise="CAD",
                    mapping_colonnes="{}",
                    source_sha256="a" * 64,
                    source_octets=1,
                    source_nonce="nonce-fictif",
                    source_cipher="cipher-fictif",
                    source_cipher_octets=17,
                    resultat_nonce=None,
                    resultat_cipher=None,
                    resultat_cipher_octets=0,
                    cle_reference="OPSYS_INGESTION_CLE",
                    version_format=1,
                    snapshot_version=0,
                    snapshot_empreinte=None,
                    statut="RECU",
                    revision=1,
                    curseur=0,
                    total_lignes=None,
                    nombre_propositions=0,
                    verdict=None,
                    cree_le="fictif",
                    modifie_le="fictif",
                )
            )
            cnx.execute(
                FUSION_COMMANDES.insert().values(
                    acteur="admin-fictif",
                    mutation_id="csv-ancien",
                    empreinte_requete="e" * 64,
                    lot_id="csv-fictif-conserve",
                    cree_le="fictif",
                )
            )
            cnx.execute(
                FUSION_PDF_LOTS.insert().values(
                    lot_id="00000000-0000-4000-8000-000000000020",
                    acteur="admin-fictif",
                    mutation_id="pdf-ancien",
                    empreinte_requete="a" * 64,
                    cle_deduplication="b" * 64,
                    type_source="pdf_natif",
                    classe="FINANCIAL",
                    extracteur="pypdf-6.19.0/pdf-natif-1",
                    configuration_sha256="c" * 64,
                    source_sha256="d" * 64,
                    source_octets=1,
                    source_nonce="nonce-fictif",
                    source_cipher="cipher-fictif",
                    source_cipher_octets=17,
                    resultat_nonce=None,
                    resultat_cipher=None,
                    resultat_cipher_octets=0,
                    cle_reference="OPSYS_INGESTION_CLE",
                    version_format=1,
                    statut="RECU",
                    revision=1,
                    total_pages=0,
                    code=None,
                    cree_le="fictif",
                    modifie_le="fictif",
                )
            )
        stockage.migrer(url)
        from alembic.script import ScriptDirectory

        revision_tete = ScriptDirectory.from_config(stockage._config()).get_current_head()
        assert stockage.revision_courante(url) == revision_tete
        with stockage.moteur(url).connect() as cnx:
            assert tuple(cnx.execute(text("SELECT lots,octets_cipher FROM fusion_quota")).one()) == (3, 321)
            assert tuple(cnx.execute(text("SELECT lots,octets_cipher FROM fusion_pdf_quota")).one()) == (1, 432)
            assert cnx.execute(text("SELECT mutation_id FROM fusion_pdf_lots")).scalar_one() == "pdf-ancien"
            assert cnx.execute(text("SELECT mutation_id FROM fusion_lots")).scalar_one() == "csv-ancien"
            assert cnx.execute(text("SELECT mutation_id FROM fusion_commandes")).scalar_one() == "csv-ancien"
            assert cnx.execute(text("SELECT count(*) FROM fusion_ap_brouillons")).scalar_one() == 0
    finally:
        stockage.liberer()


def test_deux_admins_concurrents_gagnent_un_seul_cas(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"g" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    barriere = threading.Barrier(2)
    with stockage.transaction() as cnx:
        from opsys import identite

        identite.creer_personne(cnx, "admin-fictif-2", "Admin fictif 2", "mot-de-passe-admin-2-long", ["admin"])

    def ecrire(acteur, mutation, proposition):
        try:
            barriere.wait(timeout=2)
            return fusion_ap.enregistrer(
                stockage.transaction,
                acteur,
                pdf["lot_id"],
                mutation_id=mutation,
                revision_pdf_attendue=pdf["revision"],
                revision_attendue=0,
                proposition=proposition,
            )
        except fusion_ap.FusionAPErreur as exc:
            return exc.code

    propositions = [_payload(resultat), _payload(resultat, total="114.98 CAD revu")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(ecrire, acteur, f"concurrent-{i}", value)
            for i, (acteur, value) in enumerate(zip((nathan, "admin-fictif-2"), propositions, strict=True))
        ]
        resultats = [future.result(timeout=5) for future in futures]
    assert sum(isinstance(item, dict) for item in resultats) == 1
    assert sum(isinstance(item, str) and item in {"CONFLIT_REVISION", "STOCKAGE_OCCUPE"} for item in resultats) == 1
    with stockage.transaction() as cnx:
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        assert brouillon["revision"] == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0


def test_revocation_apres_ecriture_annule_brouillon_et_quota(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"h" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    from opsys import identite as personne

    original = personne.personne_active

    def revoquer_apres_journal(cnx, acteur):
        active = original(cnx, acteur)
        if cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one():
            cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == acteur).values(actif=False))
            return None
        return active

    monkeypatch.setattr(personne, "personne_active", revoquer_apres_journal)
    with pytest.raises(PermissionError):
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-revoque-commit",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=_payload(resultat),
        )
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0
        assert cnx.execute(select(PERSONNES.c.actif).where(PERSONNES.c.identifiant == nathan)).scalar_one() is True


def test_quota_commandes_ferme_apres_128_mutations(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"i" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="commande-initiale",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=_payload(resultat),
    )
    with stockage.transaction() as cnx:
        cnx.execute(
            FUSION_AP_COMMANDES.insert(),
            [
                {
                    "lot_id": pdf["lot_id"],
                    "acteur": nathan,
                    "mutation_id": f"commande-{index:03d}",
                    "empreinte_requete": f"{index:064x}",
                    "revision_resultat": 1,
                    "cree_le": "fictif",
                }
                for index in range(fusion_ap.MAX_COMMANDES_PAR_LOT - 1)
            ],
        )
        avant_quota = cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one()
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="commande-128",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=1,
            proposition=_payload(resultat),
        )
    assert erreur.value.code == "AP_COMMANDES_QUOTA_ATTEINT"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 1
        assert cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one() == avant_quota
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 128
