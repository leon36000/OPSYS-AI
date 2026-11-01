"""Interfaces de l'ingestion d'onboarding : CLI `opsys-metier onboarding`, console en lecture, extracteur PDF isolé.
Corpus et personnes fictifs."""

from __future__ import annotations

import json

import ingestion_onboarding_qa as qa
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from opsys import cli, fusion_pdf, stockage
from opsys.console import onboarding_ui
from opsys.console.securite import Session
from opsys.ingestion_onboarding import extraction_texte, service
from opsys.ingestion_onboarding.codes import EchecEtape

FICTIF = True


@pytest.fixture
def lot(tmp_path, monkeypatch):
    qa.preparer_instance(tmp_path, monkeypatch)
    qa.deposer_fichier("f1.txt", qa.texte_corpus("factures/F1-quincaillerie.txt").encode("utf-8"))
    with stockage.transaction() as cnx:
        depose = service.deposer(cnx, "nathan", nom="f1.txt", mutation_id="m-1")
    service.avancer(stockage.transaction, "nathan", depose["lot_id"])
    return depose


def test_la_cli_lit_sans_authentification_mais_ne_mute_ni_ne_montre_de_contenu_sans_elle(lot, capsys):
    assert cli.main(["onboarding", "lots"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["lot_id"] == lot["lot_id"]
    assert cli.main(["onboarding", "lire", lot["lot_id"], "--vue", "brouillons"]) == 0
    [brouillon] = json.loads(capsys.readouterr().out)["brouillons"]
    assert brouillon["statut"] == "PRET"
    assert cli.main(["onboarding", "journal", lot["lot_id"]]) == 0
    assert "Quincaillerie" not in capsys.readouterr().out
    # stdin n'est pas un terminal : aucune authentification possible, donc ni contenu ni mutation.
    assert cli.main(["onboarding", "lire", lot["lot_id"], "--brouillon", brouillon["brouillon_id"],
                     "--par", "nathan"]) == 1
    assert "Quincaillerie" not in capsys.readouterr().out
    assert cli.main(["onboarding", "avancer", lot["lot_id"], "--par", "nathan"]) == 1
    assert "authentification personnelle requise" in capsys.readouterr().err
    assert cli.main(["onboarding", "lire", "pas-un-lot"]) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "REJ-ING-ARGUMENT-INVALIDE"


def _application(administrateur: bool):
    session = Session(utilisateur="nathan", roles=frozenset({"nathan_owner"}), csrf="c" * 32, expire=2**40)

    def session_page(_request, **_):
        if not administrateur:
            raise HTTPException(403, "administration requise")
        return session

    app = FastAPI()
    app.include_router(onboarding_ui.creer_router(session_page=session_page, session_api=session_page,
                                                  cnx_factory=stockage.transaction, prefixe=""))
    return TestClient(app)


def test_la_console_montre_les_metadonnees_sans_contenu_et_refuse_sans_administration(lot):
    client = _application(True)
    page = client.get("/onboarding")
    assert page.status_code == 200 and "f1.txt" in page.text and page.headers["cache-control"] == "no-store"
    detail = client.get(f"/onboarding/lots/{lot['lot_id']}")
    assert detail.status_code == 200 and "ap_facture_fournisseur" in detail.text and "PRET" in detail.text
    assert "Quincaillerie" not in detail.text and "349.52" not in detail.text
    api = client.get(f"/api/onboarding/lots/{lot['lot_id']}").json()
    assert api["brouillons"][0]["genre"] == "ap_facture_fournisseur" and "contenu" not in api["brouillons"][0]
    assert client.get("/api/onboarding/lots").json()["lots"][0]["lot_id"] == lot["lot_id"]
    assert client.get("/onboarding/lots/" + "0" * 32).status_code == 404
    assert client.get("/onboarding/lots/inconnu").status_code == 422
    refuse = _application(False)
    assert refuse.get("/onboarding").status_code == 403
    assert refuse.get(f"/api/onboarding/lots/{lot['lot_id']}").status_code == 403


def test_l_extracteur_isole_par_defaut_rend_une_panne_d_isolation_reprenable(monkeypatch):
    def isolation_absente(_source):
        raise fusion_pdf._erreur("PDF_ISOLATION_INDISPONIBLE", 503)

    monkeypatch.setattr(fusion_pdf, "_extraire_isole", isolation_absente)
    with pytest.raises(EchecEtape) as exc:
        extraction_texte.extraire("pdf", qa.pdf_texte("x"), document_id="0" * 32)
    assert exc.value.code == "REJ-ING-ISOLATION-INDISPONIBLE" and exc.value.reprenable is True
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", lambda _s: {"ok": False, "code": "PDF_TIMEOUT"})
    with pytest.raises(EchecEtape) as exc:
        extraction_texte.extraire("pdf", qa.pdf_texte("x"), document_id="0" * 32)
    assert exc.value.reprenable is True


@pytest.mark.parametrize(("octets", "code"), [(b"\xff\xfeA\x00\x00\xd8", "REJ-ING-TEXTE-ILLISIBLE"),
                                              (b"pas,un\n\"tableau", "REJ-ING-TABLEAU-ILLISIBLE")])
def test_texte_et_tableau_illisibles(octets, code):
    genre = "txt" if code == "REJ-ING-TEXTE-ILLISIBLE" else "csv"
    with pytest.raises(EchecEtape) as exc:
        extraction_texte.extraire(genre, octets, document_id="0" * 32)
    assert exc.value.code == code and exc.value.reprenable is False
