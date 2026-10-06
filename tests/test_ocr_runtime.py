"""Lanceur OCR : sources fictives, doubles de moteur, aucun appel comptable."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

FICTIF = True
LOT = "12345678-1234-4234-8234-123456789abc"
SOURCE = b"%PDF-1.4\nFICTIF\n%%EOF"


def _module():
    assert importlib.util.find_spec("opsys.ocr_runtime") is not None, "lanceur OCR absent"
    return importlib.import_module("opsys.ocr_runtime")


def _candidat(module):
    contexte = module.contexte_ocr(SOURCE, lot_id=LOT, revision_source=2)
    from opsys.ocr_candidat import candidat_depuis_tsv

    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t\n"
        b"2\t1\t1\t0\t0\t0\t0\t0\t100\t100\t-1\t\n"
        b"3\t1\t1\t1\t0\t0\t0\t0\t100\t100\t-1\t\n"
        b"4\t1\t1\t1\t1\t0\t0\t0\t100\t100\t-1\t\n"
        b"5\t1\t1\t1\t1\t1\t10\t10\t40\t10\t90\tFICTIF<texte>\n"
    )
    return candidat_depuis_tsv(tsv, contexte=contexte, largeur_px=100, hauteur_px=100)


@pytest.mark.parametrize("source", [b"", b"FICTIF", b"%PDF-" + b"x" * 1048576, SOURCE + b"CANARI", "CANARI"])
def test_source_invalide_refusee_avant_bundle_ou_execution(monkeypatch, source):
    module = _module()
    appels = []
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: appels.append(bundle))
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module.extraire_candidat(source, lot_id=LOT, revision_source=2, bundle=Path("/bundle-fictif"))
    assert erreur.value.code == "OCR_SOURCE_INVALIDE"
    assert appels == [] and "CANARI" not in str(erreur.value)


@pytest.mark.parametrize("lot,revision", [("CANARI", 2), (LOT, True), (LOT, 0), (LOT, 2.0)])
def test_contexte_invalide_refuse_avant_execution(monkeypatch, lot, revision):
    module = _module()
    appels = []
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: appels.append(bundle))
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module.extraire_candidat(SOURCE, lot_id=lot, revision_source=revision, bundle=Path("/bundle-fictif"))
    assert erreur.value.code == "OCR_CONTEXTE_INVALIDE" and appels == []


def test_candidat_lie_source_revision_et_profil_sans_corriger_texte(monkeypatch):
    module = _module()
    attendu = _candidat(module)
    appels = []
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: ["BWRAP_FICTIF"])

    def moteur(cmd, source):
        appels.append((cmd, source))
        return json.dumps(attendu).encode()

    monkeypatch.setattr(module.fusion_pdf, "_executer_borne", moteur)
    candidat = module.extraire_candidat(SOURCE, lot_id=LOT, revision_source=2, bundle=Path("/bundle-fictif"))
    assert candidat == attendu and candidat["statut"] == "CANDIDAT_A_REVOIR"
    assert candidat["page"]["tokens"][0]["texte"] == "FICTIF<texte>"
    assert appels[0][1] == SOURCE and appels[0][0][-3:] == [LOT, "2", hashlib.sha256(SOURCE).hexdigest()]


@pytest.mark.parametrize("mutation", ["source", "revision", "profil", "statut", "surplus"])
def test_resultat_moteur_incoherent_refuse_sans_fuite(monkeypatch, mutation):
    module = _module()
    candidat = _candidat(module)
    if mutation == "source":
        candidat["source_sha256"] = "a" * 64
    elif mutation == "revision":
        candidat["revision_source"] = 3
    elif mutation == "profil":
        candidat["profil"]["langue"] = "eng"
    elif mutation == "statut":
        candidat["statut"] = "VALIDE"
    else:
        candidat["CANARI"] = "texte privé fictif"
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: ["BWRAP_FICTIF"])
    monkeypatch.setattr(module.fusion_pdf, "_executer_borne", lambda cmd, source: json.dumps(candidat).encode())
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module.extraire_candidat(SOURCE, lot_id=LOT, revision_source=2, bundle=Path("/bundle-fictif"))
    assert erreur.value.code == "OCR_RESULTAT_INVALIDE" and "CANARI" not in str(erreur.value)


@pytest.mark.parametrize("raw", [b"", b"CANARI", b'{"ok":false,"code":"CANARI"}',
                                 b'{"ok":false,"code":"OCR_STRUCTURE_REFUSEE","CANARI":1}'])
def test_protocole_invalide_ferme(monkeypatch, raw):
    module = _module()
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: ["BWRAP_FICTIF"])
    monkeypatch.setattr(module.fusion_pdf, "_executer_borne", lambda cmd, source: raw)
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module.extraire_candidat(SOURCE, lot_id=LOT, revision_source=2, bundle=Path("/bundle-fictif"))
    assert erreur.value.code == "OCR_RESULTAT_INVALIDE" and "CANARI" not in str(erreur.value)


def test_refus_structure_propage_sans_autre_execution(monkeypatch):
    module = _module()
    appels = []
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: ["BWRAP_FICTIF"])

    def moteur(cmd, source):
        appels.append(cmd)
        return b'{"ok":false,"code":"OCR_STRUCTURE_REFUSEE"}'

    monkeypatch.setattr(module.fusion_pdf, "_executer_borne", moteur)
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module.extraire_candidat(SOURCE, lot_id=LOT, revision_source=2, bundle=Path("/bundle-fictif"))
    assert erreur.value.code == "OCR_STRUCTURE_REFUSEE" and len(appels) == 1


def test_echec_confinement_ne_declenche_aucun_repli(monkeypatch):
    module = _module()
    appels = []
    monkeypatch.setattr(module, "_commande_ocr", lambda bundle: ["BWRAP_FICTIF"])

    def moteur(cmd, source):
        appels.append(cmd)
        raise module.fusion_pdf._erreur("PDF_TIMEOUT", 503)

    monkeypatch.setattr(module.fusion_pdf, "_executer_borne", moteur)
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module.extraire_candidat(SOURCE, lot_id=LOT, revision_source=2, bundle=Path("/bundle-fictif"))
    assert erreur.value.code == "OCR_ISOLATION_INDISPONIBLE" and len(appels) == 1


def test_commande_preserve_confinement_et_monte_seulement_fichiers_valides(monkeypatch, tmp_path):
    module = _module()
    fichier = "rasterizer/pypdfium2/__init__.py"
    monkeypatch.setattr(module, "valider_bundle", lambda bundle: {fichier: "a" * 64})
    commande = module._commande_ocr(tmp_path)
    assert "--unshare-all" in commande and "--clearenv" in commande and "--tmpfs" in commande
    assert "--bind" not in commande and "--share-net" not in commande
    montages = [commande[i + 1:i + 3] for i, value in enumerate(commande) if value == "--ro-bind"]
    assert [str(tmp_path / fichier), "/bundle/" + fichier] in montages
    assert [str(tmp_path / "wheel.whl"), "/bundle/wheel.whl"] in montages
    assert [str(tmp_path), "/bundle"] not in montages
    assert [str(module._WORKER.resolve()), "/worker.py"] in montages
    assert commande[-2:] == ["-I", "/worker.py"]


def test_bundle_invalide_refuse_avant_construction_sandbox(monkeypatch, tmp_path):
    module = _module()
    appels = []

    def profil(bundle):
        raise module.OCRProfilErreur()

    monkeypatch.setattr(module, "valider_bundle", profil)
    monkeypatch.setattr(module.fusion_pdf, "_commande_isolee", lambda: appels.append("sandbox"))
    with pytest.raises(module.OCRRuntimeErreur) as erreur:
        module._commande_ocr(tmp_path)
    assert erreur.value.code == "OCR_PROFIL_INDISPONIBLE" and appels == []
