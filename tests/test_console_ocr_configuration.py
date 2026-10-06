"""Choix OCR exclusivement opérateur ; chemins et clés entièrement fictifs."""
from pathlib import Path

import pytest

from opsys.console import application


@pytest.mark.parametrize("valeur", [None, "", "  "])
def test_ocr_absent_ou_vide_reste_desactive(valeur):
    from opsys.console.ocr_configuration import chemin_bundle

    environ = {} if valeur is None else {"OPSYS_INGESTION_OCR_BUNDLE": valeur}
    assert chemin_bundle(environ) is None


@pytest.mark.parametrize("valeur", [
    True, 42, "relatif/bundle", "/tmp/../prive", "/tmp/bundle\nsecret-fictif",
    "/tmp/bundle\x00", "/" + "x" * 1024, "C:\\bundle-fictif",
])
def test_choix_invalide_refuse_sans_recopier_chemin(valeur):
    from opsys.console.ocr_configuration import chemin_bundle

    with pytest.raises(ValueError) as erreur:
        chemin_bundle({"OPSYS_INGESTION_OCR_BUNDLE": valeur})
    assert str(erreur.value) == "configuration OCR invalide : chemin absolu administré requis"


def test_chemin_absolu_est_transmis_sans_acces_ou_installation(tmp_path):
    from opsys.console.ocr_configuration import chemin_bundle

    absent = tmp_path / "bundle-fictif-absent"
    assert not absent.exists()
    assert chemin_bundle({"OPSYS_INGESTION_OCR_BUNDLE": str(absent)}) == absent
    assert not absent.exists()


def test_lanceur_transmet_uniquement_choix_operateur(monkeypatch, tmp_path):
    observations = {}
    sentinelle = object()

    def creer(configuration, *, bundle_ocr=None):
        observations["configuration"] = configuration
        observations["bundle_ocr"] = bundle_ocr
        return sentinelle

    monkeypatch.setattr(application.stockage, "migrer", lambda: "0025")
    monkeypatch.setattr(application, "creer_application", creer)
    monkeypatch.setattr(application.uvicorn, "run", lambda app, **kwargs: observations.update(app=app))
    choisi = tmp_path / "bundle-fictif"
    assert application.lancer([], environ={
        "OPSYS_CONSOLE_SECRET": "secret-console-ocr-fictif-" + "x" * 32,
        "OPSYS_INGESTION_OCR_BUNDLE": str(choisi),
    }) == 0
    assert observations["app"] is sentinelle and observations["bundle_ocr"] == choisi


def test_lanceur_refuse_choix_invalide_avant_demarrage(monkeypatch, capsys):
    appels = []
    monkeypatch.setattr(application.stockage, "migrer", lambda: "0025")
    monkeypatch.setattr(application.uvicorn, "run", lambda *_args, **_kwargs: appels.append("run"))
    assert application.lancer([], environ={
        "OPSYS_CONSOLE_SECRET": "secret-console-ocr-fictif-" + "x" * 32,
        "OPSYS_INGESTION_OCR_BUNDLE": "chemin-prive-relatif-fictif",
    }) == 2
    assert appels == []
    assert "chemin-prive-relatif-fictif" not in capsys.readouterr().err


def test_factory_refuse_type_configuration_ocr_incorrect():
    from opsys.console.securite import Configuration

    configuration = Configuration("secret-console-ocr-fictif-" + "x" * 32, cookie_securise=False)
    with pytest.raises(ValueError, match="configuration OCR invalide"):
        application.creer_application(configuration, bundle_ocr="/tmp/bundle-fictif")
    with pytest.raises(ValueError, match="configuration OCR invalide"):
        application.creer_application(configuration, bundle_ocr=Path("bundle-fictif-relatif"))
