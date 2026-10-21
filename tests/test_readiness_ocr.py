"""Contrat CLI du prévol OCR; doubles du runtime explicitement synthétiques."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DEPLOY = ROOT / "deploy"
FIXTURE = DEPLOY / "fixtures" / "ocr-image-fictive.pdf"
SPEC = importlib.util.spec_from_file_location("opsys_readiness_ocr_test", DEPLOY / "readiness_ocr.py")
assert SPEC is not None and SPEC.loader is not None
readiness_ocr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness_ocr)


def _candidat(source: bytes, *, lot_id: str, revision_source: int) -> dict:
    from opsys.ocr_runtime import contexte_ocr

    contexte = contexte_ocr(source, lot_id=lot_id, revision_source=revision_source)
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
            "largeur_px": 1275,
            "hauteur_px": 1651,
            "tokens": [
                {"texte": word, "x0": index * 100, "y0": 10, "x1": index * 100 + 50,
                 "y1": 30, "confiance_brute": 90.0}
                for index, word in enumerate(("FACTURE", "FICTIVE", "TEST"))
            ],
        },
    }


def test_cli_exige_exactement_ocr_only_et_n_echo_pas_arguments(monkeypatch, capsys):
    monkeypatch.setattr(readiness_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("worker interdit"))
    assert readiness_ocr.main([]) == 2
    sortie = capsys.readouterr()
    assert "usage:" in sortie.err and "--ocr-only" in sortie.err
    assert readiness_ocr.main(["--ocr-only", "/secret/bundle/path"]) == 2
    sortie = capsys.readouterr()
    assert "/secret/bundle/path" not in sortie.out + sortie.err


@pytest.mark.parametrize("valeur", [None, "", " \t "])
def test_optin_absent_ou_vide_retourne_attente_sans_worker(monkeypatch, capsys, valeur):
    monkeypatch.setattr(readiness_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("worker interdit"))
    env = {} if valeur is None else {"OPSYS_INGESTION_OCR_BUNDLE": valeur}
    assert readiness_ocr.main(["--ocr-only"], environ=env) == 3
    sortie = capsys.readouterr()
    assert "non activé" in sortie.err and "ready OCR" not in sortie.out


def test_succes_valide_entree_contexte_et_oracle_sans_texte_ni_chemin(monkeypatch, capsys, tmp_path):
    bundle = tmp_path / "bundle-private"
    vu = {}

    def worker(source, *, lot_id, revision_source, bundle: Path):
        vu.update(source=source, lot_id=lot_id, revision=revision_source, bundle=bundle)
        return _candidat(source, lot_id=lot_id, revision_source=revision_source)

    monkeypatch.setattr(readiness_ocr, "extraire_candidat", worker)
    assert readiness_ocr.main(
        ["--ocr-only"], environ={"OPSYS_INGESTION_OCR_BUNDLE": str(bundle)},
    ) == 0
    sortie = capsys.readouterr()
    assert "ready OCR" in sortie.out
    assert str(bundle) not in sortie.out + sortie.err
    assert all(token not in sortie.out + sortie.err for token in ("FACTURE", "FICTIVE", "TEST"))
    assert len(vu["source"]) == 12_194
    assert hashlib.sha256(vu["source"]).hexdigest() == readiness_ocr._FIXTURE_SHA256
    assert vu["lot_id"] == readiness_ocr._FIXTURE_LOT_ID and vu["revision"] == 1 and vu["bundle"] == bundle


@pytest.mark.parametrize("kind", [
    "runtime", "candidate", "context", "profile", "configuration", "oracle", "dimensions", "source", "lot",
])
def test_echec_ferme_et_sans_details(monkeypatch, capsys, tmp_path, kind):
    bundle = tmp_path / "hidden-bundle"
    if kind == "runtime":
        def worker(*_args, **_kwargs):
            raise RuntimeError("FACTURE FICTIVE TEST /secret/path")
    else:
        def worker(source, *, lot_id, revision_source, **_kwargs):
            candidate = _candidat(source, lot_id=lot_id, revision_source=revision_source)
            if kind == "candidate":
                candidate["statut"] = "A_FACTURER"
            elif kind == "context":
                candidate["revision_source"] = 9
            elif kind == "profile":
                candidate["profil"]["moteur"] = "tesseract-version-inattendue"
            elif kind == "configuration":
                candidate["configuration_sha256"] = "0" * 64
            elif kind == "oracle":
                candidate["page"]["tokens"][0]["texte"] = "TEXTE-INATTENDU-FICTIF"
            elif kind == "dimensions":
                candidate["page"]["largeur_px"] += 1
            elif kind == "source":
                candidate["source_sha256"] = "0" * 64
            else:
                candidate["lot_id"] = "12345678-1234-4234-8234-123456789abd"
            return candidate
    monkeypatch.setattr(readiness_ocr, "extraire_candidat", worker)
    assert readiness_ocr.main(
        ["--ocr-only"], environ={"OPSYS_INGESTION_OCR_BUNDLE": str(bundle)},
    ) == 1
    sortie = capsys.readouterr()
    assert "not ready OCR" in sortie.err
    secrets = ("FACTURE", "FICTIVE", "TEST", str(bundle), "/secret/path")
    assert all(secret not in sortie.out + sortie.err for secret in secrets)


def test_chemin_bundle_invalide_refuse_sans_afficher_valeur(monkeypatch, capsys):
    monkeypatch.setattr(readiness_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("worker interdit"))
    chemin = "chemin relatif confidentiel"
    assert readiness_ocr.main(["--ocr-only"], environ={
        "OPSYS_INGESTION_OCR_BUNDLE": chemin,
    }) == 1
    sortie = capsys.readouterr()
    assert "not ready OCR" in sortie.err and chemin not in sortie.out + sortie.err


def test_fixture_fixe_sha_borne_avant_worker(monkeypatch, capsys, tmp_path):
    fixture = tmp_path / "fixture-corrompue.pdf"
    fixture.write_bytes(b"%PDF-1.7\nfixture differente\n")
    monkeypatch.setattr(readiness_ocr, "_FIXTURE", fixture)
    monkeypatch.setattr(readiness_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("worker interdit"))
    assert readiness_ocr.main(
        ["--ocr-only"], environ={"OPSYS_INGESTION_OCR_BUNDLE": str(tmp_path / "bundle")},
    ) == 1
    sortie = capsys.readouterr()
    assert "not ready OCR" in sortie.err and str(fixture) not in sortie.out + sortie.err



def test_fixture_meme_taille_hash_altere_refuse_avant_worker(monkeypatch, capsys, tmp_path):
    source = bytearray(FIXTURE.read_bytes())
    source[100] ^= 1
    fixture = tmp_path / "fixture-fictive-corrompue.pdf"
    fixture.write_bytes(source)
    monkeypatch.setattr(readiness_ocr, "_FIXTURE", fixture)
    monkeypatch.setattr(readiness_ocr, "extraire_candidat", lambda *_a, **_k: pytest.fail("worker interdit"))
    assert readiness_ocr.main(["--ocr-only"], environ={
        "OPSYS_INGESTION_OCR_BUNDLE": str(tmp_path / "bundle-fictif"),
    }) == 1
    assert str(fixture) not in capsys.readouterr().err


def test_fixture_fifo_refuse_sans_blocage_ni_worker(tmp_path):
    import os
    import subprocess

    fifo = tmp_path / "fixture-fictive-fifo"
    os.mkfifo(fifo)
    code = (
        "import readiness_ocr; from pathlib import Path; "
        "readiness_ocr._FIXTURE = Path(" + repr(str(fifo)) + "); "
        "readiness_ocr.extraire_candidat = lambda *a, **k: (_ for _ in ()).throw(AssertionError('worker interdit')); "
        "raise SystemExit(readiness_ocr.main(['--ocr-only'], environ={'OPSYS_INGESTION_OCR_BUNDLE':'/bundle-fictif'}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(DEPLOY), env.get("PYTHONPATH", "")])
    resultat = subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, timeout=5)
    assert resultat.returncode == 1
    assert b"not ready OCR" in resultat.stderr and str(fifo).encode() not in resultat.stderr
