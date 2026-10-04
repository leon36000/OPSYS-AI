"""Pilote financier PDF : documents et identités entièrement fictifs."""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import io
import json
import os
import re
import resource
import threading
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from m3_estimation import devis_durable, soumission_pdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import func, inspect, select, text, update

from opsys import etat, fusion_csv, fusion_pdf, identite, stockage
from opsys.stockage.schema import (
    FUSION_COMMANDES,
    FUSION_LOTS,
    FUSION_PDF_COMMANDES,
    FUSION_PDF_LOTS,
    FUSION_PDF_QUOTA,
    FUSION_QUOTA,
    REGISTRES,
)

FICTIF = True


@pytest.fixture(autouse=True)
def sqlite_fictive_uniquement(opsys_home, monkeypatch):
    # Même un DSN hérité ne doit jamais orienter cette qualification vers une autre base.
    opsys_home.mkdir(parents=True)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{opsys_home / 'qualification-pdf.db'}")


@pytest.fixture
def pdf_fictif():
    devis, verdict = devis_durable.creer_devis(
        devis_id="DEVIS-PDF-FICTIF", lead_id="lead-fictif", chantier_id=None,
        lignes=[{"description": "Gouttière fictive — élément canari", "quantite": "2", "unite": "pi_lin",
                 "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        taux_marge="0.25", horodatage="2026-10-02T08:00:00+00:00", registre_cible=[],
    )
    assert verdict is None
    assert isinstance(devis["prix_total"], Decimal)
    raw, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert verdict is None and raw.startswith(b"%PDF-")
    return raw


@pytest.fixture
def base_pdf(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"f" * 32).decode())
    return nathan


def test_pdf_m3_reel_chiffre_et_reprend_sans_parser(base_pdf, pdf_fictif, monkeypatch):
    lot = fusion_pdf.creer(stockage.transaction, base_pdf, mutation_id="pdf-fictif-1", pdf_octets=pdf_fictif)
    assert lot["source_sha256"] == hashlib.sha256(pdf_fictif).hexdigest()
    assert lot["classe"] == "FINANCIAL" and lot["statut"] == "RECU"
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_PDF_LOTS)).one()
        assert saved.source_cipher != base64.b64encode(pdf_fictif).decode()
        assert cnx.execute(select(FUSION_PDF_QUOTA.c.lots)).scalar_one() == 1
    ready = fusion_pdf.preparer(stockage.transaction, base_pdf, lot["lot_id"], lot["revision"])
    assert ready["statut"] == "EXTRAIT_PREPARATOIRE"
    result = fusion_pdf.lire_resultat(stockage.transaction, base_pdf, lot["lot_id"])
    assert result["source_sha256"] == lot["source_sha256"]
    assert result["pages"][0]["numero"] == 1
    text = " ".join(fragment["texte"] for page in result["pages"] for fragment in page["fragments"])
    assert "BROUILLON" in text and "Gouttière fictive" in text
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", lambda *_: pytest.fail("reprise ne doit pas parser"))
    assert fusion_pdf.preparer(stockage.transaction, base_pdf, lot["lot_id"], ready["revision"]) == ready
    assert fusion_pdf.lire_resultat(stockage.transaction, base_pdf, lot["lot_id"]) == result
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()
        assert "Gouttière" not in saved["source_cipher"] + saved["resultat_cipher"]
        assert "Gouttière" not in json.dumps(etat.lire_journal(cnx), ensure_ascii=False)
        assert cnx.execute(select(FUSION_QUOTA.c.octets_cipher)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore"
        )).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(
            (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        )).scalar_one() == 2
        quota = cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one()
        assert quota["octets_cipher"] == saved["source_cipher_octets"] + saved["resultat_cipher_octets"]
    assert "pages" not in fusion_pdf.lire(stockage.transaction, base_pdf, lot["lot_id"])
    assert len(fusion_pdf.lister(stockage.transaction, base_pdf)) == 1


def _pdf(texte="Document entièrement fictif", pages=1, image=False, invisible=False):
    destination = io.BytesIO()
    document = canvas.Canvas(destination, invariant=1)
    for _ in range(pages):
        if texte:
            zone = document.beginText(30, 700)
            if invisible:
                zone.setTextRenderMode(3)
            zone.textLine(texte)
            document.drawText(zone)
        if image:
            from PIL import Image

            document.drawImage(ImageReader(Image.new("RGB", (4, 4), "white")), 30, 600, 20, 20)
        document.showPage()
    document.save()
    return destination.getvalue()


def _creer(acteur, source, mutation="fictif"):
    return fusion_pdf.creer(stockage.transaction, acteur, mutation_id=mutation, pdf_octets=source)


def _preparer(acteur, lot):
    return fusion_pdf.preparer(stockage.transaction, acteur, lot["lot_id"], lot["revision"])


def _compteurs():
    with stockage.transaction() as cnx:
        quota = dict(cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one())
        quota["commandes"] = cnx.execute(select(func.count()).select_from(FUSION_PDF_COMMANDES)).scalar_one()
        return quota


@pytest.mark.parametrize("source", [
    None, "PDF pas UTF-8", bytearray(b"%PDF-"), b"", b"texte", b"%PDF-" + b" " * 1_048_576,
], ids=["absence", "chaine", "mutable", "vide", "entete-invalide", "plus-1mio"])
def test_admission_source_bornee_sans_ecriture(base_pdf, source):
    with pytest.raises(fusion_pdf.FusionPDFErreur, match="opération PDF") as rejet:
        _creer(base_pdf, source)
    assert rejet.value.code == "PDF_SOURCE_INVALIDE"
    assert _compteurs()["lots"] == 0


@pytest.mark.parametrize("mutation", [None, True, "", "secret\ntexte", "a" * 129])
def test_mutation_fermee(base_pdf, pdf_fictif, mutation):
    with pytest.raises(fusion_pdf.FusionPDFErreur) as rejet:
        _creer(base_pdf, pdf_fictif, mutation)
    assert rejet.value.code == "MUTATION_INVALIDE"
    assert _compteurs()["lots"] == 0


def test_cle_obligatoire_et_dedup_sans_nouvelle_reservation(base_pdf, pdf_fictif, monkeypatch):
    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    with pytest.raises(fusion_pdf.FusionPDFErreur) as rejet:
        _creer(base_pdf, pdf_fictif)
    assert rejet.value.code == "CLE_INDISPONIBLE"
    assert _compteurs()["lots"] == 0
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"f" * 32).decode())
    lot = _creer(base_pdf, pdf_fictif)
    compteurs = _compteurs()
    assert _creer(base_pdf, pdf_fictif) == lot
    assert _creer(base_pdf, pdf_fictif, "autre-id") == lot
    assert _compteurs() == {**compteurs, "commandes": 2}
    with pytest.raises(fusion_pdf.FusionPDFErreur) as rejet:
        _creer(base_pdf, _pdf("autre source fictive"))
    assert rejet.value.code == "CONFLIT_MUTATION"


@pytest.mark.parametrize("mot_de_passe", ["", "fictif-seulement"])
def test_pdf_chiffre_refuse_meme_mot_de_passe_vide(base_pdf, pdf_fictif, mot_de_passe, monkeypatch):
    ecrivain = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_fictif)))
    ecrivain.encrypt(mot_de_passe)
    destination = io.BytesIO()
    ecrivain.write(destination)
    lot = _creer(base_pdf, destination.getvalue())
    avant = _compteurs()
    refuse = _preparer(base_pdf, lot)
    assert refuse["statut"] == "REFUSE" and refuse["code"] == "PDF_CHIFFRE"
    assert _compteurs() == avant
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", lambda *_: pytest.fail("refus doit être durable"))
    assert _preparer(base_pdf, refuse) == refuse


@pytest.mark.parametrize("genre,code", [
    ("image", "PDF_IMAGE_OU_MIXTE"), ("mixte", "PDF_IMAGE_OU_MIXTE"),
    ("blanc", "PDF_SANS_TEXTE"), ("invisible", "PDF_AMBIGU"),
    ("pages", "PDF_PAGES_BORNEES"), ("tronque", "PDF_MALFORME"), ("xref", "PDF_AVERTISSEMENT"),
])
def test_refus_reels_du_worker(base_pdf, pdf_fictif, genre, code):
    sources = {
        "image": lambda: _pdf(None, image=True), "mixte": lambda: _pdf(image=True),
        "blanc": lambda: _pdf(None), "invisible": lambda: _pdf(invisible=True),
        "pages": lambda: _pdf(pages=21), "tronque": lambda: pdf_fictif[:-20],
        "xref": lambda: pdf_fictif.replace(b"startxref\n", b"startxref "),
    }
    refuse = _preparer(base_pdf, _creer(base_pdf, sources[genre]()))
    assert refuse["statut"] == "REFUSE" and refuse["code"] == code
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.lire_resultat(stockage.transaction, base_pdf, refuse["lot_id"])
    assert erreur.value.code == "PDF_RESULTAT_INDISPONIBLE"


@pytest.mark.parametrize("genre,code", [("decompresse", "PDF_CONTENU_BORNE"), ("texte", "PDF_TEXTE_BORNE")])
def test_bornes_reelles_texte_et_decompression(base_pdf, genre, code):
    ecrivain = PdfWriter()
    page = ecrivain.add_blank_page(width=600, height=800)
    flux = DecodedStreamObject()
    longueur = 2_097_200 if genre == "decompresse" else 262_200
    flux.set_data(b"BT /F1 10 Tf 10 700 Td (" + b"x" * longueur + b") Tj ET")
    page[NameObject("/Contents")] = ecrivain._add_object(flux.flate_encode())
    # Police standard réelle, fournie par le générateur ReportLab de référence.
    page[NameObject("/Resources")] = PdfReader(io.BytesIO(_pdf())).pages[0]["/Resources"].clone(ecrivain)
    destination = io.BytesIO()
    ecrivain.write(destination)
    refuse = _preparer(base_pdf, _creer(base_pdf, destination.getvalue()))
    assert refuse["statut"] == "REFUSE" and refuse["code"] == code


def test_modele_pagine_et_hashs_reels(base_pdf):
    lot = _preparer(base_pdf, _creer(base_pdf, _pdf(pages=2)))
    resultat = fusion_pdf.lire_resultat(stockage.transaction, base_pdf, lot["lot_id"])
    assert resultat["extracteur"] == fusion_pdf.EXTRACTEUR
    assert [page["numero"] for page in resultat["pages"]] == [1, 2]
    for page in resultat["pages"]:
        fragment = page["fragments"][0]
        assert fragment["id"] == f"p{page['numero']}-f1"
        assert fragment["sha256"] == hashlib.sha256(fragment["texte"].encode()).hexdigest()


@pytest.mark.parametrize("revision", [None, True, 0, -1, "1", 1.0])
def test_revision_stricte(base_pdf, pdf_fictif, revision):
    lot = _creer(base_pdf, pdf_fictif)
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.preparer(stockage.transaction, base_pdf, lot["lot_id"], revision)
    assert erreur.value.code == "REVISION_INVALIDE"


def test_source_et_resultat_authentifies(base_pdf, pdf_fictif, monkeypatch):
    lot = _creer(base_pdf, pdf_fictif)
    with stockage.transaction() as cnx:
        saved = dict(cnx.execute(select(FUSION_PDF_LOTS)).mappings().one())
        mauvais = bytearray(base64.b64decode(saved["source_cipher"]))
        mauvais[-1] ^= 1
        cnx.execute(update(FUSION_PDF_LOTS).values(source_cipher=base64.b64encode(mauvais).decode()))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _preparer(base_pdf, lot)
    assert erreur.value.code == "CIPHER_INVALIDE"
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).values(source_cipher=saved["source_cipher"]))
    ready = _preparer(base_pdf, lot)
    with stockage.transaction() as cnx:
        saved = dict(cnx.execute(select(FUSION_PDF_LOTS)).mappings().one())
        with pytest.raises(fusion_csv.FusionErreur):
            fusion_csv._dechiffrer(b"f" * 32, saved, "source", saved["source_nonce"], saved["source_cipher"])
        mauvais = bytearray(base64.b64decode(saved["resultat_cipher"]))
        mauvais[0] ^= 1
        cnx.execute(update(FUSION_PDF_LOTS).values(resultat_cipher=base64.b64encode(mauvais).decode()))
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", lambda *_: pytest.fail("corruption ne doit pas être réparée"))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _preparer(base_pdf, ready)
    assert erreur.value.code == "CIPHER_INVALIDE"


def test_source_sha_et_configuration_revalidees(base_pdf, pdf_fictif):
    lot = _creer(base_pdf, pdf_fictif)
    with stockage.transaction() as cnx:
        nonce, chiffre, _ = fusion_csv._chiffrer(b"f" * 32, lot["lot_id"], lot["source_sha256"],
                                               fusion_pdf._SOURCE_AAD, b"x" * len(pdf_fictif))
        cnx.execute(update(FUSION_PDF_LOTS).values(source_nonce=nonce, source_cipher=chiffre))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _preparer(base_pdf, lot)
    assert erreur.value.code == "SOURCE_CORROMPUE"
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).values(configuration_sha256="0" * 64))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _preparer(base_pdf, lot)
    assert erreur.value.code == "PDF_VERSION_INCOMPATIBLE"


def test_autorite_admin_et_revocation_pendant_worker(base_pdf, pdf_fictif, monkeypatch):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "finance-fictive", "Finance fictive", "mot-de-passe-fictif-1234", ["finance"])
    with pytest.raises(PermissionError):
        _creer("finance-fictive", pdf_fictif)
    lot = _creer(base_pdf, pdf_fictif)
    original = fusion_pdf._extraire_isole

    def revoquer(source):
        assert stockage.connexion_courante() is None
        resultat = original(source)
        with stockage.transaction() as cnx:
            identite.activer(cnx, base_pdf, False)
        return resultat

    monkeypatch.setattr(fusion_pdf, "_extraire_isole", revoquer)
    with pytest.raises(PermissionError):
        _preparer(base_pdf, lot)
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()
        assert saved["statut"] == "RECU" and saved["resultat_cipher"] is None
    with pytest.raises(PermissionError):
        fusion_pdf.lire(stockage.transaction, base_pdf, lot["lot_id"])


def test_parser_hors_transaction_et_cas_concurrent_reel(base_pdf, pdf_fictif, monkeypatch):
    lot = _creer(base_pdf, pdf_fictif)
    original = fusion_pdf._extraire_isole
    barriere = threading.Barrier(2, timeout=10)

    def synchroniser(source):
        assert stockage.connexion_courante() is None
        resultat = original(source)
        barriere.wait()
        return resultat

    monkeypatch.setattr(fusion_pdf, "_extraire_isole", synchroniser)

    def candidat():
        try:
            return _preparer(base_pdf, lot)["statut"]
        except fusion_pdf.FusionPDFErreur as exc:
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(lambda _: candidat(), range(2)))
    assert sorted(resultats) == ["CONFLIT_REVISION", "EXTRAIT_PREPARATOIRE"]
    with stockage.transaction() as cnx:
        saved = cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()
        quota = cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one()
        assert saved["revision"] == 2
        assert quota["octets_cipher"] == saved["source_cipher_octets"] + saved["resultat_cipher_octets"]
        assert len([r for r in etat.lire_journal(cnx) if r["action"] == "fusion.pdf.extrait_preparatoire"]) == 1


def test_aucune_transaction_imbrquee(base_pdf, pdf_fictif):
    with stockage.transaction(), pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _creer(base_pdf, pdf_fictif)
    assert erreur.value.code == "PDF_TRANSACTION_IMBRIQUEE"


def test_quota_16_lots_conserves(base_pdf):
    for i in range(16):
        _creer(base_pdf, _pdf(f"Lot fictif {i}"), f"lot-{i}")
    avant = _compteurs()
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _creer(base_pdf, _pdf("dix-septième lot fictif"), "lot-17")
    assert erreur.value.code == "PDF_QUOTA_ATTEINT" and _compteurs() == avant


def test_reservation_source_et_resultat_atomiques(base_pdf, pdf_fictif, monkeypatch):
    lot = _creer(base_pdf, pdf_fictif)
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_QUOTA).values(octets_cipher=fusion_pdf.QUOTA_CIPHER_MAX - 1))
    avant = _compteurs()
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _preparer(base_pdf, lot)
    assert erreur.value.code == "PDF_QUOTA_ATTEINT"
    assert _compteurs() == avant
    assert fusion_pdf.lire(stockage.transaction, base_pdf, lot["lot_id"])["revision"] == 1
    with pytest.raises(fusion_pdf.FusionPDFErreur):
        _creer(base_pdf, _pdf("source supplémentaire fictive"), "source-2")
    assert _compteurs() == avant


def test_interruption_avant_commit_et_reprise(base_pdf, pdf_fictif, monkeypatch):
    lot = _creer(base_pdf, pdf_fictif)
    compteurs = _compteurs()
    original = fusion_pdf._journal
    monkeypatch.setattr(fusion_pdf, "_journal", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _preparer(base_pdf, lot)
    assert _compteurs() == compteurs
    assert fusion_pdf.lire(stockage.transaction, base_pdf, lot["lot_id"]) == lot
    monkeypatch.setattr(fusion_pdf, "_journal", original)
    assert _preparer(base_pdf, lot)["statut"] == "EXTRAIT_PREPARATOIRE"


def _worker_temporaire(tmp_path, monkeypatch, contenu):
    chemin = tmp_path / "worker-probe-fictif.py"
    chemin.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(fusion_pdf, "_CHEMIN_WORKER", chemin)


@pytest.mark.parametrize("genre,code", [("temps", "PDF_TIMEOUT"), ("stdout", "PDF_SORTIE_EXCESSIVE"),
                                       ("stderr", "PDF_SORTIE_EXCESSIVE")])
def test_arret_et_wait_reels_du_worker(base_pdf, pdf_fictif, tmp_path, monkeypatch, genre, code):
    sources = {"temps": "import time; time.sleep(30)", "stdout": "import os; os.write(1,b'x'*600000)",
               "stderr": "import os; os.write(2,b'x'*10000)"}
    _worker_temporaire(tmp_path, monkeypatch, sources[genre])
    if genre == "temps":
        monkeypatch.setattr(fusion_pdf, "WALL_SECONDES", 0.2)
    processus = []
    original = fusion_pdf.subprocess.Popen

    def enregistrer(*args, **kwargs):
        p = original(*args, **kwargs)
        processus.append(p)
        return p

    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", enregistrer)
    lot = _preparer(base_pdf, _creer(base_pdf, pdf_fictif))
    assert lot["statut"] == "ERREUR_REPRENABLE" and lot["code"] == code
    assert len(processus) == 1 and processus[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processus[0].pid, 0)


def test_sandbox_reel_sans_reseau_env_vide_et_mounts_readonly(base_pdf, pdf_fictif, tmp_path, monkeypatch):
    secret = tmp_path / "secret-fictif-ne-pas-monter"
    secret.write_text("CANARI-CONFIDENTIEL-FICTIF")
    monkeypatch.setenv("OPSYS_PDF_CANARI_SECRET", "CANARI-CONFIDENTIEL-FICTIF")
    script = f'''
import os,sys,socket,json,hashlib
source=sys.stdin.buffer.read(1048577)
assert 'OPSYS_INGESTION_CLE' not in os.environ and 'OPSYS_PDF_CANARI_SECRET' not in os.environ
assert not os.path.exists({str(secret)!r})
s=socket.socket(); s.settimeout(0.2)
assert s.connect_ex(('192.0.2.1',9)) == 101
try:
    open('/worker.py','wb')
except OSError:
    pass
else:
    raise AssertionError('worker writable')
print(json.dumps({{'ok':False,'code':'PDF_SANS_TEXTE'}}))
'''
    _worker_temporaire(tmp_path, monkeypatch, script)
    refuse = _preparer(base_pdf, _creer(base_pdf, pdf_fictif))
    assert refuse["code"] == "PDF_SANS_TEXTE" and refuse["statut"] == "REFUSE"


def test_limites_kernel_reelles_avant_envoi_source(pdf_fictif, monkeypatch):
    original = fusion_pdf.subprocess.Popen
    observations = []
    plafonds = {
        resource.RLIMIT_AS: 536_870_912, resource.RLIMIT_CPU: 10, resource.RLIMIT_CORE: 0,
        resource.RLIMIT_FSIZE: 0, resource.RLIMIT_NOFILE: 64,
    }
    libelles = {
        resource.RLIMIT_AS: "Max address space", resource.RLIMIT_CPU: "Max cpu time",
        resource.RLIMIT_CORE: "Max core file size", resource.RLIMIT_FSIZE: "Max file size",
        resource.RLIMIT_NOFILE: "Max open files",
    }

    def observer(*args, **kwargs):
        processus = original(*args, **kwargs)
        fin = fusion_pdf.monotonic() + 2
        try:
            # Stdin reste vide ici : le vrai worker n'a pas encore reçu le PDF.
            while fusion_pdf.monotonic() < fin:
                enfants = {}
                # Certains procfs n'exposent pas task/<tid>/children : PPid dans stat est disponible.
                for index, dossier in enumerate(Path("/proc").iterdir()):
                    if index >= 16_384:
                        break
                    if not dossier.name.isdecimal():
                        continue
                    try:
                        champs = (dossier / "stat").read_text().rpartition(")")[2].split()
                        enfants.setdefault(int(champs[1]), []).append(int(dossier.name))
                    except (OSError, ValueError, IndexError):
                        continue
                candidats = [processus.pid]
                vus = set()
                while candidats and len(vus) < 32:
                    pid = candidats.pop()
                    if pid in vus:
                        continue
                    vus.add(pid)
                    try:
                        dossier = Path(f"/proc/{pid}")
                        candidats.extend(enfants.get(pid, []))
                        if not (dossier / "comm").read_text().strip().startswith("python"):
                            continue
                        texte_limites = (dossier / "limits").read_text()
                        limites = {}
                        for nom, libelle in libelles.items():
                            ligne = re.search(r"(?m)^" + re.escape(libelle) + r"\s+(\w+)\s+(\w+)", texte_limites)
                            limites[nom] = tuple(-1 if n == "unlimited" else int(n) for n in ligne.groups())
                        if all(0 <= souple <= dur <= plafonds[nom] for nom, (souple, dur) in limites.items()):
                            observations.append(limites)
                            return processus
                    except (OSError, ValueError):
                        continue
                threading.Event().wait(0.01)
            raise AssertionError("limites kernel du worker non observées")
        except BaseException:
            processus.kill()
            processus.wait()
            raise

    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", observer)
    assert fusion_pdf._extraire_isole(pdf_fictif)["ok"] is True
    assert len(observations) == 1


def test_isolation_absente_aucun_fallback_et_reprise(base_pdf, pdf_fictif, monkeypatch):
    lot = _creer(base_pdf, pdf_fictif)
    with monkeypatch.context() as m:
        m.setattr(fusion_pdf.shutil, "which", lambda _: None)
        bloque = _preparer(base_pdf, lot)
    assert bloque["statut"] == "ERREUR_REPRENABLE" and bloque["code"] == "PDF_ISOLATION_INDISPONIBLE"
    assert _preparer(base_pdf, bloque)["statut"] == "EXTRAIT_PREPARATOIRE"


def test_cle_referencee_survit_rotation_explicite(base_pdf, pdf_fictif, monkeypatch):
    ancien = _creer(base_pdf, pdf_fictif)
    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_CLE_PDF_FICTIVE_V2")
    monkeypatch.setenv("OPSYS_CLE_PDF_FICTIVE_V2", base64.b64encode(b"v" * 32).decode())
    nouveau = _creer(base_pdf, _pdf("autre document fictif"), "nouvelle-cle")
    _preparer(base_pdf, ancien)
    _preparer(base_pdf, nouveau)
    assert fusion_pdf.lire_resultat(stockage.transaction, base_pdf, ancien["lot_id"])["pages"]
    monkeypatch.delenv("OPSYS_INGESTION_CLE")
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.lire_resultat(stockage.transaction, base_pdf, ancien["lot_id"])
    assert erreur.value.code == "CLE_INDISPONIBLE"
    assert fusion_pdf.lire_resultat(stockage.transaction, base_pdf, nouveau["lot_id"])["pages"]


def test_isolation_namespace_refusee_sans_fallback(base_pdf, pdf_fictif, tmp_path, monkeypatch):
    executable = tmp_path / "bwrap-refus-fictif"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    monkeypatch.setattr(fusion_pdf.shutil, "which", lambda _: str(executable))
    bloque = _preparer(base_pdf, _creer(base_pdf, pdf_fictif))
    assert bloque["statut"] == "ERREUR_REPRENABLE" and bloque["code"] == "PDF_ISOLATION_INDISPONIBLE"


@pytest.mark.parametrize("prefixe", ["/", "/etc", "/workspace"])
def test_mount_prefixe_non_qualifie_bloque(base_pdf, pdf_fictif, monkeypatch, prefixe):
    lot = _creer(base_pdf, pdf_fictif)
    with monkeypatch.context() as m:
        m.setattr(fusion_pdf.sys, "prefix", prefixe)
        bloque = _preparer(base_pdf, lot)
    assert bloque["code"] == "PDF_ISOLATION_INDISPONIBLE"


def test_plateforme_non_linux_bloque_sans_admission(base_pdf, pdf_fictif, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(fusion_pdf.sys, "platform", "darwin")
        with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
            _creer(base_pdf, pdf_fictif)
    assert erreur.value.code == "PDF_ISOLATION_INDISPONIBLE"
    assert _compteurs()["lots"] == 0


@pytest.mark.parametrize("genre", ["selecteur", "annulation"])
def test_wait_garanti_si_initialisation_ou_annulation(base_pdf, pdf_fictif, monkeypatch, genre):
    lot = _creer(base_pdf, pdf_fictif)
    processus = []
    original = fusion_pdf.subprocess.Popen

    def enregistrer(*args, **kwargs):
        p = original(*args, **kwargs)
        processus.append(p)
        return p

    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", enregistrer)
    if genre == "selecteur":
        monkeypatch.setattr(fusion_pdf.selectors, "DefaultSelector", lambda: (_ for _ in ()).throw(OSError()))
        assert _preparer(base_pdf, lot)["code"] == "PDF_ISOLATION_INDISPONIBLE"
    else:
        monkeypatch.setattr(fusion_pdf.selectors.DefaultSelector, "select",
                            lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            _preparer(base_pdf, lot)
        assert fusion_pdf.lire(stockage.transaction, base_pdf, lot["lot_id"]) == lot
    assert len(processus) == 1 and processus[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processus[0].pid, 0)


def test_quota_binaire_reel_par_cumul_sources_synthetiques(base_pdf):
    # Sources volontairement non parsées : cette preuve mesure les réservations AES-GCM.
    for i in range(15):
        source = b"%PDF-1.4\n%lot-fictif-" + str(i).encode()
        source += b" " * (fusion_pdf.SOURCE_MAX - len(source))
        _creer(base_pdf, source, f"volume-{i}")
    avant = _compteurs()
    assert avant["octets_cipher"] == 15 * (fusion_pdf.SOURCE_MAX + 16)
    source = b"%PDF-1.4\n%seizieme-fictif"
    source += b" " * (fusion_pdf.SOURCE_MAX - len(source))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        _creer(base_pdf, source, "volume-16")
    assert erreur.value.code == "PDF_QUOTA_ATTEINT" and _compteurs() == avant


def test_rollback_admission_si_journal_echoue(base_pdf, pdf_fictif, monkeypatch):
    monkeypatch.setattr(fusion_pdf, "_journal", lambda *_: (_ for _ in ()).throw(RuntimeError("arrêt fictif")))
    with pytest.raises(RuntimeError, match="arrêt fictif"):
        _creer(base_pdf, pdf_fictif)
    assert _compteurs() == {"id": 1, "lots": 0, "octets_cipher": 0, "commandes": 0}
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_PDF_LOTS)).scalar_one() == 0


@pytest.mark.parametrize("genre", ["javascript", "inline-image"])
def test_contenu_actif_et_image_inline_reellement_refuses(base_pdf, pdf_fictif, genre):
    destination = io.BytesIO()
    if genre == "javascript":
        ecrivain = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_fictif)))
        ecrivain.add_js("app.alert('fictif');")
        ecrivain.write(destination)
    else:
        from PIL import Image

        document = canvas.Canvas(destination, invariant=1)
        document.drawString(30, 700, "Texte fictif avec image inline")
        document.drawInlineImage(Image.new("RGB", (3, 3), "white"), 30, 600, 20, 20)
        document.save()
    refuse = _preparer(base_pdf, _creer(base_pdf, destination.getvalue()))
    assert refuse["statut"] == "REFUSE"
    assert refuse["code"] == ("PDF_ACTIF" if genre == "javascript" else "PDF_IMAGE_OU_MIXTE")


@pytest.mark.parametrize("reponse", [b'{}', b'{"ok":true,"ok":false}', b'{"ok":false,"code":[]}',
                                     b'{"ok":false,"code":"texte prive"}', b'{"ok":true,"resultat":{}}'])
def test_protocole_ferme_du_worker(base_pdf, pdf_fictif, tmp_path, monkeypatch, reponse):
    _worker_temporaire(tmp_path, monkeypatch, f"import os; os.write(1,{reponse!r})")
    bloque = _preparer(base_pdf, _creer(base_pdf, pdf_fictif))
    assert bloque["statut"] == "ERREUR_REPRENABLE"
    assert bloque["code"] in {"PDF_PROTOCOLE_INVALIDE", "PDF_RESULTAT_INVALIDE"}


def test_migration_0018_additive_preserve_csv_et_quota(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'avant-0018.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    try:
        with stockage.moteur(url).begin() as cnx:
            configuration = stockage._config()
            configuration.attributes["connection"] = cnx
            command.upgrade(configuration, "0017")
            cnx.execute(text("UPDATE fusion_quota SET lots=7,octets_cipher=1234 WHERE id=1"))
            cnx.execute(FUSION_LOTS.insert().values(
                lot_id="csv-fictif-conserve", acteur="admin-fictif", mutation_id="csv-1",
                empreinte_requete="h" * 64, cle_deduplication="d" * 64,
                compte_interne_id="compte-fictif", devise="CAD", mapping_colonnes="{}",
                source_sha256="s" * 64, source_octets=1, source_nonce="nonce-fictif",
                source_cipher="cipher-fictif-conserve", source_cipher_octets=17,
                resultat_nonce=None, resultat_cipher=None, resultat_cipher_octets=0,
                cle_reference="OPSYS_INGESTION_CLE", version_format=1,
                snapshot_version=0, snapshot_empreinte=None, statut="RECU", revision=1,
                curseur=0, total_lignes=None, nombre_propositions=0, verdict=None,
                cree_le="fictif", modifie_le="fictif",
            ))
            cnx.execute(FUSION_COMMANDES.insert().values(
                acteur="admin-fictif", mutation_id="csv-1", empreinte_requete="h" * 64,
                lot_id="csv-fictif-conserve", cree_le="fictif",
            ))
            lot_csv = cnx.execute(select(FUSION_LOTS)).one()
            commande_csv = cnx.execute(select(FUSION_COMMANDES)).one()
            schema_csv = cnx.execute(text(
                "SELECT sql FROM sqlite_master WHERE name LIKE 'fusion_%' ORDER BY name"
            )).all()
        with stockage.moteur(url).begin() as cnx:
            configuration = stockage._config()
            configuration.attributes["connection"] = cnx
            command.upgrade(configuration, "0018")
        assert stockage.revision_courante(url) == "0018"
        with stockage.moteur(url).begin() as cnx:
            assert tuple(cnx.execute(text("SELECT lots,octets_cipher FROM fusion_quota")).one()) == (7, 1234)
            apres_csv = cnx.execute(text(
                "SELECT sql FROM sqlite_master WHERE name LIKE 'fusion_%' "
                "AND name NOT LIKE 'fusion_pdf_%' ORDER BY name"
            )).all()
            assert apres_csv == schema_csv
            assert cnx.execute(select(FUSION_LOTS)).one() == lot_csv
            assert cnx.execute(select(FUSION_COMMANDES)).one() == commande_csv
            assert tuple(cnx.execute(select(FUSION_PDF_QUOTA.c.lots, FUSION_PDF_QUOTA.c.octets_cipher)).one()) == (0, 0)
            colonnes = {c["name"] for c in inspect(cnx).get_columns("fusion_pdf_lots")}
            assert colonnes == set(FUSION_PDF_LOTS.c.keys())
            configuration = stockage._config()
            configuration.attributes["connection"] = cnx
            with pytest.raises(RuntimeError, match="rétrogradation refusée"):
                command.downgrade(configuration, "0017")
        assert stockage.revision_courante(url) == "0018"
        from alembic.script import ScriptDirectory

        tete = ScriptDirectory.from_config(stockage._config()).get_current_head()
        assert stockage.migrer(url) == tete
        assert stockage.migrer(url) == tete
        with stockage.moteur(url).begin() as cnx:
            assert cnx.execute(select(FUSION_LOTS)).one() == lot_csv
            assert cnx.execute(select(FUSION_COMMANDES)).one() == commande_csv
            assert tuple(cnx.execute(text("SELECT lots,octets_cipher FROM fusion_quota")).one()) == (7, 1234)
    finally:
        stockage.liberer()
