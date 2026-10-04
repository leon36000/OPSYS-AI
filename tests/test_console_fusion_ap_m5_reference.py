"""Consultation HTTP privée de la référence durable de saisie Fusion dans M5."""

from __future__ import annotations

import html
import importlib.util
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from m5_financecore import comptes_a_payer, taux_fiscaux
from m5_financecore import outils as m5_outils
from sqlalchemy import update

from opsys import identite, stockage
from opsys.console import fusion_ap_ui
from opsys.stockage.schema import FUSION_AP_SAISIES

_BASE_PATH = Path(__file__).with_name("test_console_fusion_ap_m5.py")
_BASE_SPEC = importlib.util.spec_from_file_location("_fusion_ap_m5_reference_base", _BASE_PATH)
assert _BASE_SPEC is not None and _BASE_SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = _BASE
_BASE_SPEC.loader.exec_module(_BASE)

_PREFIXE = "/opsys"


@pytest.fixture
def client_ap_m5(session, nathan, monkeypatch):
    yield from _BASE.client_ap_m5.__wrapped__(session, nathan, monkeypatch)


def _chemin_console(action: str) -> str:
    path = urlsplit(action).path
    assert path.startswith(_PREFIXE + "/")
    return path[len(_PREFIXE):]


def _confirmation(client: TestClient) -> tuple[str, str, str]:
    _BASE._reception_m5()
    lot_id, revision_pdf = _BASE._lot_avec_brouillon(client)
    page = client.get(f"/fusion/pdf/lots/{lot_id}/ap")
    observation = client.post(
        _BASE._LOT_URL.format(lot_id), data=_BASE._formulaire(page.text, revision_pdf)
    )
    assert observation.status_code == 200, observation.text
    form = re.search(
        r'<form method="post" action="([^"]+/ap/saisir-m5)" class="pile">(.*?)</form>', observation.text
    )
    assert form
    fields = {
        html.unescape(key): html.unescape(value)
        for key, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', form.group(2))
    }
    fields["saisie_confirmee"] = "oui"
    saved = client.post(_chemin_console(form.group(1)), data=fields)
    assert saved.status_code == 200, saved.text
    fact = re.search(r"Référence de facture : ([^<]+)\.</p>", saved.text)
    assert fact
    return lot_id, html.unescape(fact.group(1)), saved.text


def _reference_backend():
    from opsys.console import fusion_ap_m5_reference

    return fusion_ap_m5_reference


def _codes(html_body: str) -> tuple[str, str, str, int]:
    fact = re.search(r"<p>Facture : ([^<]+)\.</p>", html_body)
    approbation = re.search(r"<p>Approbation N3 : ([^<]+)\.</p>", html_body)
    statut = re.search(r"<p>État courant M5 : ([^<]+)\.</p>", html_body)
    corrections = re.search(r"<p>Corrections enregistrées : ([0-9]+)\.</p>", html_body)
    assert fact and approbation and statut and corrections
    return tuple(html.unescape(x.group(1)) for x in (fact, approbation, statut)) + (int(corrections.group(1)),)


def test_reference_retrouvee_apres_reconnexion_get_sans_post_ni_ecriture(client_ap_m5):
    lot_id, facture_id, receipt = _confirmation(client_ap_m5)
    approbation_match = re.search(r"Référence d’approbation : ([^<]+)\.</p>", receipt)
    assert approbation_match
    approbation_id = html.unescape(approbation_match.group(1))

    client_ap_m5.cookies.clear()
    _BASE._connecter(client_ap_m5, "nathan")
    before = _BASE._snapshot_tables()
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store, max-age=0"
    assert _codes(page.text) == (facture_id, approbation_id, "SAISIE", 0)
    assert "verifier-m5" not in page.text
    assert "Aucun brouillon AP" not in page.text and "A_REVOIR — révision 1" in page.text
    assert _BASE._snapshot_tables() == before

    ref_link = re.search(r'href="([^"]+/fusion/pdf/lots/[^\"]+/ap)">Retrouver la référence', receipt)
    finance_link = re.search(r'href="([^"]+/finance)">Finance', receipt)
    assert ref_link and finance_link
    assert client_ap_m5.get(_chemin_console(ref_link.group(1))).status_code == 200
    assert client_ap_m5.get(_chemin_console(finance_link.group(1))).status_code == 200


def test_reference_reflète_correction_et_annulation_m5_sans_effacer_l_origine(client_ap_m5, monkeypatch):
    lot_id, facture_id, _ = _confirmation(client_ap_m5)
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert not erreurs
    with stockage.transaction():
        registre = m5_outils._registre_comptes_a_payer()
        corrigee, refus = comptes_a_payer.corriger_facture_fournisseur(
            facture_fournisseur_id=facture_id,
            motif="montant ajusté fictif",
            numero_facture=None,
            date_facture=None,
            montant_avant_taxes="101.00",
            total_facture=None,
            corrige_par="nathan",
            role="nathan_owner",
            voie="approbation",
            horodatage="2026-10-04T13:00:00+00:00",
            dictionnaire_taux=taux,
            registre_cible=registre,
        )
        assert corrigee is not None and refus is None
    after_correction = _BASE._snapshot_tables()
    corrected = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    corrected_ref = _codes(corrected.text)
    assert corrected.status_code == 200
    assert (corrected_ref[0], corrected_ref[2], corrected_ref[3]) == (facture_id, "CORRIGEE", 1)
    assert _BASE._snapshot_tables() == after_correction
    monkeypatch.setattr(
        taux_fiscaux,
        "charger_taux_fiscaux",
        lambda *_args, **_kwargs: pytest.fail("la consultation historique ne recalcule pas les taxes"),
    )

    with stockage.transaction():
        annulee, refus = comptes_a_payer.annuler_facture_fournisseur(
            facture_fournisseur_id=facture_id,
            motif="annulation fictive",
            annule_par="nathan",
            role="nathan_owner",
            voie="approbation",
            horodatage="2026-10-04T14:00:00+00:00",
            registre_cible=m5_outils._registre_comptes_a_payer(),
        )
        assert annulee is not None and refus is None
    after_cancellation = _BASE._snapshot_tables()
    cancelled = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert cancelled.status_code == 200
    fact, approbation, statut, count = _codes(cancelled.text)
    assert (fact, statut, count) == (facture_id, "ANNULEE", 1)
    assert approbation == _codes(corrected.text)[1]
    assert _BASE._snapshot_tables() == after_cancellation


def test_admin_sans_finance_ne_lit_pas_et_n_affiche_pas_la_reference(client_ap_m5, monkeypatch):
    _BASE._reception_m5()
    lot_id, _ = _BASE._lot_avec_brouillon(client_ap_m5)
    backend = _reference_backend()
    monkeypatch.setattr(backend, "lire", lambda *_args: pytest.fail("lecture référence sans finance"))
    _BASE._connecter(client_ap_m5, _BASE._ADMIN)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200
    assert "Référence de saisie M5" not in page.text and "verifier-m5" not in page.text


def test_ids_de_reference_sont_echappes_et_aucun_detail_m5_n_est_rendu(client_ap_m5, monkeypatch):
    lot_id, _, _ = _confirmation(client_ap_m5)
    poison = _BASE._MARQUEUR
    monkeypatch.setattr(
        _reference_backend(),
        "lire",
        lambda *_args: {
            "facture_id": poison,
            "approbation_id": "approval-fictif",
            "statut_m5": "SAISIE",
            "corrections": 0,
        },
    )
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200
    assert poison not in page.text and "&lt;img src=x onerror=alert(1)&gt;" in page.text
    assert "total_facture" not in page.text and "montant_avant_taxes" not in page.text


@pytest.mark.parametrize("etape", ["lecture", "rendu"])
def test_retrait_finance_en_lecture_ou_rendu_refuse_le_html_prive(client_ap_m5, monkeypatch, etape):
    lot_id, facture_id, _ = _confirmation(client_ap_m5)
    with stockage.transaction() as cnx:
        identite.ajouter_role(cnx, _BASE._ADMIN, "finance")
    _BASE._connecter(client_ap_m5, _BASE._ADMIN)
    original_lire = _reference_backend().lire

    def retirer_role():
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, _BASE._ADMIN, "finance")

    if etape == "lecture":
        def lire_puis_retirer(*args, **kwargs):
            reference = original_lire(*args, **kwargs)
            retirer_role()
            return reference

        monkeypatch.setattr(_reference_backend(), "lire", lire_puis_retirer)
    else:
        original_rendu = fusion_ap_ui._reference_saisie_m5

        def rendre_puis_retirer(resultat):
            contenu = original_rendu(resultat)
            retirer_role()
            return contenu

        monkeypatch.setattr(fusion_ap_ui, "_reference_saisie_m5", rendre_puis_retirer)

    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 403
    assert facture_id not in page.text and "Référence de saisie M5" not in page.text


def test_corruption_de_la_reference_est_503_et_ne_devient_pas_une_absence(client_ap_m5):
    lot_id, facture_id, _ = _confirmation(client_ap_m5)
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FUSION_AP_SAISIES)
            .where(FUSION_AP_SAISIES.c.lot_id == lot_id)
            .values(commande_sha256="0" * 64)
        )
    before = _BASE._snapshot_tables()
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 503
    assert "REFERENCE_SAISIE_M5_INDISPONIBLE" in page.text
    assert facture_id not in page.text
    assert "aucune saisie" not in page.text.lower()
    assert _BASE._snapshot_tables() == before
