"""Venv exécuté via un alias : mêmes racines RO et worker PDF réel."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from opsys import fusion_pdf


def _pdf_fictif() -> bytes:
    sortie = io.BytesIO()
    document = canvas.Canvas(sortie, invariant=1)
    document.drawString(40, 760, "FOURNISSEUR DE TEST FICTIF")
    document.showPage()
    document.save()
    return sortie.getvalue()


def test_venv_symbolique_utilise_le_prefixe_canonique_et_le_worker_reel(tmp_path, monkeypatch):
    prefixe = Path(sys.prefix).resolve(strict=True)
    executable_relatif = Path(sys.executable).relative_to(Path(sys.prefix))
    alias = tmp_path / "venv-alias"
    alias.symlink_to(prefixe, target_is_directory=True)
    monkeypatch.setattr(sys, "prefix", str(alias))
    monkeypatch.setattr(sys, "executable", str(alias / executable_relatif))

    commande = fusion_pdf._commande_isolee()
    assert ["--ro-bind", str(prefixe), str(prefixe)] in [
        commande[index : index + 3] for index in range(len(commande) - 2)
    ]
    assert str(alias) not in commande
    assert commande[-3] == str(prefixe / executable_relatif)

    resultat = fusion_pdf._extraire_isole(_pdf_fictif())

    assert resultat["ok"] is True
    assert "FOURNISSEUR DE TEST FICTIF" in resultat["resultat"]["pages"][0]["fragments"][0]["texte"]


def test_venv_symbolique_vers_racine_interdite_refuse_avant_spawn(tmp_path, monkeypatch):
    alias = tmp_path / "tmp-alias"
    alias.symlink_to("/tmp", target_is_directory=True)
    relatif_tmp = Path(os.path.relpath(tmp_path, "/tmp"))
    executable = tmp_path / "python-alias"
    executable.symlink_to(Path(sys.base_prefix) / "bin/python3")
    monkeypatch.setattr(sys, "prefix", str(alias))
    monkeypatch.setattr(sys, "executable", str(alias / relatif_tmp / executable.name))
    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawn interdit"))

    with pytest.raises(fusion_pdf.FusionPDFErreur) as exc:
        fusion_pdf._commande_isolee()

    assert exc.value.code == "PDF_ISOLATION_INDISPONIBLE"


def test_prefixe_interdit_est_refuse_meme_si_pyvenv_cfg_est_present(tmp_path, monkeypatch):
    alias = tmp_path / "tmp-alias"
    alias.symlink_to("/tmp", target_is_directory=True)
    executable_relatif = Path(os.path.relpath(tmp_path, "/tmp")) / "python"
    executable = tmp_path / "python"
    executable.symlink_to(Path(sys.base_prefix) / "bin/python3")
    monkeypatch.setattr(sys, "prefix", str(alias))
    monkeypatch.setattr(sys, "executable", str(alias / executable_relatif))
    monkeypatch.setattr(
        fusion_pdf,
        "_geometrie_lecture_isolee",
        lambda: (
            Path("/usr"),
            frozenset({Path("/tmp"), Path(sys.base_prefix).resolve(strict=True)}),
            fusion_pdf._CHEMIN_WORKER,
            (),
        ),
    )
    is_file_orig = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda chemin: True if chemin == Path("/tmp/pyvenv.cfg") else is_file_orig(chemin),
    )
    is_relative_to_orig = Path.is_relative_to
    parent_tmp = tmp_path.resolve(strict=True)
    monkeypatch.setattr(
        Path,
        "is_relative_to",
        lambda chemin, autre: True
        if chemin == parent_tmp and autre == Path("/tmp")
        else is_relative_to_orig(chemin, autre),
    )
    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawn interdit"))

    with pytest.raises(fusion_pdf.FusionPDFErreur) as exc:
        fusion_pdf._commande_isolee()

    assert exc.value.code == "PDF_ISOLATION_INDISPONIBLE"


def test_interpreteur_symbolique_hors_du_venv_refuse(tmp_path, monkeypatch):
    alias = tmp_path / "python-externe"
    alias.symlink_to(Path(sys.base_prefix) / "bin/python3")
    monkeypatch.setattr(sys, "executable", str(alias))
    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawn interdit"))

    with pytest.raises(fusion_pdf.FusionPDFErreur) as exc:
        fusion_pdf._commande_isolee()

    assert exc.value.code == "PDF_ISOLATION_INDISPONIBLE"


def test_cible_interpreteur_hors_des_racines_refuse(tmp_path, monkeypatch):
    base = Path(sys.base_prefix).resolve(strict=True)
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = fictif\n", encoding="utf-8")
    cible_externe = tmp_path / "cible-externe"
    cible_externe.write_text("executable fictif\n", encoding="utf-8")
    (venv / "bin/python").symlink_to(cible_externe)
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "executable", str(venv / "bin/python"))
    monkeypatch.setattr(
        fusion_pdf,
        "_geometrie_lecture_isolee",
        lambda: (Path("/usr"), frozenset({base, venv}), fusion_pdf._CHEMIN_WORKER, ()),
    )
    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawn interdit"))

    with pytest.raises(fusion_pdf.FusionPDFErreur) as exc:
        fusion_pdf._commande_isolee()

    assert exc.value.code == "PDF_ISOLATION_INDISPONIBLE"
