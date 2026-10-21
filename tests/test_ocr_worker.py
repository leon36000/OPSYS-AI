"""Worker OCR : refus avant rendu et pipes sur processus exclusivement fictifs."""

from __future__ import annotations

import builtins
import hashlib
import sys
from types import SimpleNamespace

import pytest

from opsys import ocr_candidat, ocr_worker

FICTIF = True
SOURCE = b"%PDF-1.4\nFICTIF\n%%EOF"
LOT = "12345678-1234-4234-8234-123456789abc"


def test_structure_refusee_avant_chargement_renderer_et_ocr(monkeypatch):
    profil = SimpleNamespace(PDFIUM_SHA256="a" * 64, MODELE_SHA256="b" * 64)
    modules = {
        "/profile.py": profil,
        "/contract.py": ocr_candidat,
        "/structure.py": SimpleNamespace(
            classer_page_image=lambda reader: SimpleNamespace(code="PDF_STRUCTURE_REFUSEE"),
        ),
    }
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", lambda source, strict: object())
    monkeypatch.setattr(ocr_worker, "_parser", lambda: pypdf)
    monkeypatch.setattr(ocr_worker, "_charger", lambda name, path: modules[path])
    appels = []
    monkeypatch.setattr(ocr_worker, "_dependances", lambda profile: appels.append("runtime"))
    monkeypatch.setattr(ocr_worker, "_pomper", lambda *args: appels.append("OCR"))
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._traiter(SOURCE, [LOT, "2", hashlib.sha256(SOURCE).hexdigest()])
    assert erreur.value.code == "OCR_STRUCTURE_REFUSEE" and appels == []


def test_sha_source_incorrect_refuse_avant_parser(monkeypatch):
    profil = SimpleNamespace(PDFIUM_SHA256="a" * 64, MODELE_SHA256="b" * 64)
    modules = {"/profile.py": profil, "/contract.py": ocr_candidat, "/structure.py": object()}
    monkeypatch.setattr(ocr_worker, "_charger", lambda name, path: modules[path])
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._traiter(SOURCE, [LOT, "2", "f" * 64])
    assert erreur.value.code == "OCR_SOURCE_INVALIDE"


def test_pipe_multiplexe_lit_sortie_avant_fin_entree_sans_blocage():
    # Le faux moteur remplit son pipe avant de lire une entrée supérieure à un pipe.
    script = "import sys; sys.stdout.buffer.write(b'F'*100000); sys.stdout.flush(); sys.stdin.buffer.read()"
    resultat = ocr_worker._pomper([sys.executable, "-I", "-c", script], b"FICTIF" * 50000, 100000)
    assert resultat == b"F" * 100000


@pytest.mark.parametrize("script,plafond", [
    ("import sys; sys.stdout.buffer.write(b'F'*10000); sys.stdout.flush()", 100),
    ("import sys; sys.stderr.buffer.write(b'F'*10000); sys.stderr.flush()", 10000),
    ("import sys; sys.stderr.write('CANARI'); sys.stderr.flush()", 100),
    ("import sys; sys.exit(3)", 100),
])
def test_sorties_bornees_et_processus_recolte(monkeypatch, script, plafond):
    enfants = []
    popen = ocr_worker.subprocess.Popen

    def creer(*args, **kwargs):
        enfant = popen(*args, **kwargs)
        enfants.append(enfant)
        return enfant

    monkeypatch.setattr(ocr_worker.subprocess, "Popen", creer)
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._pomper([sys.executable, "-I", "-c", script], b"FICTIF", plafond)
    assert erreur.value.code in {"OCR_RESULTAT_INVALIDE", "OCR_RUNTIME_INDISPONIBLE"}
    assert len(enfants) == 1 and enfants[0].returncode is not None


def test_deadline_interne_tue_et_recolte_enfant(monkeypatch):
    enfants = []
    popen = ocr_worker.subprocess.Popen

    def creer(*args, **kwargs):
        enfant = popen(*args, **kwargs)
        enfants.append(enfant)
        return enfant

    ticks = iter([0.0, 9.0])
    monkeypatch.setattr(ocr_worker, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(ocr_worker.subprocess, "Popen", creer)
    script = "import time; time.sleep(20)"
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._pomper([sys.executable, "-I", "-c", script], b"FICTIF", 100)
    assert erreur.value.code == "OCR_RUNTIME_INDISPONIBLE"
    assert len(enfants) == 1 and enfants[0].returncode is not None


def test_geometrie_differente_refuse_avant_rendu():
    fermetures = []

    class FauxObjet:
        def close(self):
            fermetures.append("fermé")

        def __len__(self):
            return 1

        def __getitem__(self, item):
            return self

        def get_size(self):
            return 610.0, 792.0

        def render(self, **kwargs):
            pytest.fail("géométrie divergente ne doit pas rendre")

    verdict = SimpleNamespace(largeur_pt=612.0, hauteur_pt=792.0)
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._raster(SOURCE, verdict, SimpleNamespace(PdfDocument=lambda source: FauxObjet()))
    assert erreur.value.code == "OCR_STRUCTURE_REFUSEE"
    assert fermetures == ["fermé", "fermé"]


def test_resolution_tesseract_explicitement_identique_au_raster(monkeypatch):
    from opsys.ocr_profil import OCRProfilErreur

    profil = SimpleNamespace(PDFIUM_SHA256="a" * 64, MODELE_SHA256="b" * 64, OCRProfilErreur=OCRProfilErreur)
    contrat = SimpleNamespace(
        ContexteOCR=ocr_candidat.ContexteOCR, OCRContratErreur=ocr_candidat.OCRContratErreur,
        candidat_depuis_tsv=lambda *args, **kwargs: {"fictif": True},
    )
    structure = SimpleNamespace(classer_page_image=lambda reader: SimpleNamespace(
        code="IMAGE_SEULE_CANDIDATE", largeur_px_150dpi=100, hauteur_px_150dpi=100,
    ))
    modules = {"/profile.py": profil, "/contract.py": contrat, "/structure.py": structure}
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: object())
    monkeypatch.setattr(ocr_worker, "_charger", lambda name, path: modules[path])
    # Seam de parsing pour ce seul oracle d'argv, pas preuve d'identité de dépendance.
    monkeypatch.setattr(ocr_worker, "_parser", lambda: pypdf, raising=False)
    monkeypatch.setattr(ocr_worker, "_dependances", lambda profile: object())
    monkeypatch.setattr(ocr_worker, "_raster", lambda *args: b"PNG_FICTIF")
    appels = []

    def moteur(cmd, entree, plafond):
        appels.append((cmd, entree, plafond))
        return b"TSV_FICTIF"

    monkeypatch.setattr(ocr_worker, "_pomper", moteur)
    ocr_worker._traiter(SOURCE, [LOT, "2", hashlib.sha256(SOURCE).hexdigest()])
    assert len(appels) == 1 and appels[0][0] == [
        "/usr/bin/tesseract", "stdin", "stdout", "--tessdata-dir", "/bundle/tessdata",
        "-l", "fra", "--psm", "6", "--dpi", "150", "-c", "tessedit_create_tsv=1",
    ]
    assert appels[0][1:] == (b"PNG_FICTIF", 262144)


def test_distribution_pypdf_incorrecte_refuse_avant_import(monkeypatch):
    assert hasattr(ocr_worker, "_parser"), "contrôle pré-import absent"
    monkeypatch.setattr(ocr_worker, "distribution", lambda name: SimpleNamespace(version="0.0.0"))
    importer = builtins.__import__
    vus = []

    def surveiller(name, *args, **kwargs):
        if name == "pypdf":
            vus.append(name)
        return importer(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", surveiller)
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._parser()
    assert erreur.value.code == "OCR_RUNTIME_INDISPONIBLE" and vus == []


@pytest.mark.parametrize("attribut,valeur", [
    ("__file__", "/CANARI/pypdf.py"), ("__version__", "0.0.0"), ("PdfReader", lambda *args: object()),
])
def test_module_pypdf_charge_divergent_refuse(monkeypatch, attribut, valeur):
    assert hasattr(ocr_worker, "_parser"), "identité du module absente"
    import pypdf

    monkeypatch.setattr(pypdf, attribut, valeur)
    with pytest.raises(ocr_worker.RefusOCR) as erreur:
        ocr_worker._parser()
    assert erreur.value.code == "OCR_RUNTIME_INDISPONIBLE" and "CANARI" not in str(erreur.value)


def test_provenance_pillow_du_worker_correspond_au_verrou_runtime():
    from pathlib import Path

    verrou = Path(__file__).resolve().parents[1] / "requirements-runtime.lock.txt"
    version_verrouillee = next(ligne.split("==", 1)[1].split()[0] for ligne in verrou.read_text().splitlines()
                              if ligne.startswith("pillow=="))
    assert f"pillow={version_verrouillee};" in ocr_worker.CONFIGURATION
