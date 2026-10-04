"""Parcours HTTP privé de vérification AP préparatoire avec les contrôles M5 réels."""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from m5_financecore import comptes_a_payer, taux_fiscaux
from m5_financecore import outils as m5_outils
from reportlab.pdfgen import canvas
from sqlalchemy import MetaData, Table, inspect, select

from opsys import fusion_pdf, identite, stockage
from opsys.console import application, fusion_ap_m5, securite
from opsys.console.securite import Configuration

_PREFIXE = "/opsys"
_SECRET = "secret-console-ap-m5-fictif-" + "x" * 32
_CLE = base64.b64encode(b"m" * 32).decode("ascii")
_MOT_DE_PASSE = "mot-de-passe-ap-m5-fictif-1234"
_ADMIN = "admin-ap-m5-fictif"
_MARQUEUR = "<img src=x onerror=alert(1)>"
_RACINE_M5 = Path(__file__).resolve().parents[1] / "departments" / "m05-financecore"
_LOT_URL = "/fusion/pdf/lots/{}/ap/verifier-m5"


def _pdf() -> bytes:
    sortie = io.BytesIO()
    document = canvas.Canvas(sortie, invariant=1)
    for y, text in zip(
        (760, 735, 710, 685, 660, 635, 610, 585),
        ("FOURNISSEUR EXEMPLE FICTIF", "Facture: AP-M5-2042", "Date: 2026-10-01", "PO-1",
         "Sous-total: 100.00", "Taxes: 14.98", "Total: 114.98", "CAD"),
        strict=True,
    ):
        document.drawString(40, y, text)
    document.showPage()
    document.save()
    return sortie.getvalue()


@pytest.fixture
def client_ap_m5(session, nathan, monkeypatch):
    monkeypatch.delenv("OPSYS_DATABASE_URL", raising=False)
    monkeypatch.setenv("OPSYS_INGESTION_CLE", _CLE)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, _ADMIN, "Admin fictif", _MOT_DE_PASSE, ["admin"])
    app = application.creer_application(
        Configuration(_SECRET, cookie_securise=False), cnx_factory=stockage.transaction
    )
    with TestClient(app, base_url=f"http://testserver{_PREFIXE}", raise_server_exceptions=False) as client:
        _connecter(client, nathan)
        yield client


def _connecter(client: TestClient, utilisateur: str) -> str:
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, utilisateur)
    assert personne is not None
    session = securite.ouvrir_session(utilisateur, personne.roles, 3600)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, _SECRET), path=_PREFIXE)
    return session.csrf


def _csrf(html: str) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', html)
    assert found
    return found.group(1)


def _donnees_brouillon(html: str, revision_pdf: int, *, revision_ap: int = 0,
                       mutation: str = "ap-m5-save-1", changements: dict[str, str] | None = None) -> dict[str, str]:
    fields = {"csrf": _csrf(html), "mutation_id": mutation, "revision_pdf": str(revision_pdf),
              "revision_ap": str(revision_ap)}
    champs = {
        "fournisseur": "FOURNISSEUR EXEMPLE FICTIF", "numero": "AP-M5-2042", "date": "2026-10-01",
        "po": "PO-1", "sous_total_imprime": "100.00", "taxe_imprimee": "14.98",
        "total_imprime": "114.98", "devise": "CAD",
    }
    for cle, valeur in champs.items():
        fields[f"champ.{cle}"] = valeur
        for index in range(1, 4):
            fields[f"citation.{cle}.{index}"] = ""
    refs = re.findall(r'<option value="([0-9]+:[^"]+)"', html)
    assert refs
    for cle in champs:
        fields[f"citation.{cle}.1"] = refs[0]
    for cle, valeur in (changements or {}).items():
        fields[f"champ.{cle}"] = valeur
    return fields


def _reception_m5() -> None:
    charge = {
        "evenement_id": "evt-fusion-ap-m5-reception", "po_id": "PO-1", "fournisseur_id": "gentek",
        "chantier_id": "CH-1", "horodatage_reception": "2026-09-29T09:15:00-04:00",
        "verdict_reception": "CONFORME", "statut_po": "received", "hash_maillon": "a" * 64,
        "seuil_ecart_prix_pourcentage": None,
        "lignes": [{
            "materiau_id": "gouttiere-5po", "quantite_demandee": "60", "quantite_recue": "60",
            "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
            "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
            "ecart_prix_critique": None,
        }],
    }
    entree, verdict = comptes_a_payer.construire_reception(charge)
    assert verdict is None
    with stockage.transaction():
        assert comptes_a_payer.enregistrer_reception(entree, m5_outils._registre_comptes_a_payer())[1] is None


def _facture_existante_m5() -> None:
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert not erreurs
    with stockage.transaction():
        resultat, verdict = comptes_a_payer.saisir_facture_fournisseur(
            po_id="PO-1", fournisseur_id="gentek", numero_facture="AP-M5-2042", date_facture="2026-10-01",
            montant_avant_taxes="100.00", total_facture="114.98", saisi_par="nathan", voie="appareil",
            horodatage="2026-10-04T12:00:00+00:00", dictionnaire_taux=dictionnaire,
            registre_cible=m5_outils._registre_comptes_a_payer(),
        )
    assert resultat is not None and verdict is None


def _lot_avec_brouillon(client: TestClient, *, changements: dict[str, str] | None = None) -> tuple[str, int]:
    lot = fusion_pdf.creer(stockage.transaction, "nathan", mutation_id="ap-m5-pdf-fictif-1", pdf_octets=_pdf())
    extrait = fusion_pdf.preparer(stockage.transaction, "nathan", lot["lot_id"], lot["revision"])
    assert extrait["statut"] == "EXTRAIT_PREPARATOIRE"
    page = client.get(f"/fusion/pdf/lots/{lot['lot_id']}/ap")
    assert page.status_code == 200
    saved = client.post(f"/fusion/pdf/lots/{lot['lot_id']}/ap/enregistrer",
                        data=_donnees_brouillon(page.text, extrait["revision"], changements=changements),
                        follow_redirects=False)
    assert saved.status_code == 303
    return lot["lot_id"], extrait["revision"]


def _snapshot_tables() -> dict[str, tuple[dict, ...]]:
    with stockage.transaction() as cnx:
        names = inspect(cnx).get_table_names()
        meta = MetaData()
        snapshot = {}
        for name in names:
            table = Table(name, meta, autoload_with=cnx)
            rows = [dict(row) for row in cnx.execute(select(table)).mappings()]
            snapshot[name] = tuple(sorted(rows, key=repr))
        return snapshot


def _formulaire(html: str, revision_pdf: int, **overrides: str) -> dict[str, str]:
    fields = {"csrf": _csrf(html), "revision_pdf": str(revision_pdf), "revision_ap": "1",
              "po_id": "PO-1", "fournisseur_id": "gentek", "correspondance_confirmee": "oui"}
    fields.update(overrides)
    return fields


def test_verification_m5_http_privee_observe_sans_aucun_effet_metier(client_ap_m5):
    _reception_m5()  # Établie avant la comparaison de toutes les tables.
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200 and "verifier-m5" in page.text
    avant = _snapshot_tables()

    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert "CONTROLES_M5_COMPATIBLES" in response.text
    assert "114.98 CAD" in response.text and "14.98 CAD" in response.text
    assert "Observation préparatoire" in response.text and "A_REVOIR conservé" in response.text
    for private in ("source_sha256", "proposition_sha256", "taux_sha256", "FOURNISSEUR EXEMPLE", _CLE):
        assert private not in response.text
    assert _snapshot_tables() == avant
    reprise = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert reprise.status_code == 200 and "114.98 CAD" in reprise.text
    assert re.search(r"Snapshot ([a-f0-9]{64})", reprise.text).group(1) == re.search(
        r"Snapshot ([a-f0-9]{64})", response.text).group(1)
    assert _snapshot_tables() == avant


@pytest.mark.parametrize("overrides,code,status", [
    ({"csrf": "bad"}, "jeton CSRF absent ou invalide", 403),
    ({"correspondance_confirmee": "non"}, "CORRESPONDANCE_NON_ATTESTEE", 400),
    ({"po_id": "PO-ABSENT"}, "REJ-AP-FACTURE-PO-SANS-RECEPTION", 409),
    ({"fournisseur_id": "autre"}, "REJ-AP-FACTURE-FOURNISSEUR-DIFFERENT-DU-PO", 409),
])
def test_verification_m5_refus_et_formulaires_invalides_sans_ecriture(client_ap_m5, overrides, code, status):
    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    avant = _snapshot_tables()
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf, **overrides))
    assert response.status_code == status
    assert code in response.text
    assert _MARQUEUR not in response.text and _CLE not in response.text
    assert _snapshot_tables() == avant


def test_verification_m5_refuse_admin_sans_finance_et_revisions_perimees(client_ap_m5):
    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    _connecter(client_ap_m5, _ADMIN)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    assert page.status_code == 200 and "verifier-m5" not in page.text
    denied = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert denied.status_code == 403 and "ACCES_FINANCE_REFUSE" in denied.text

    _connecter(client_ap_m5, "nathan")
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    stale = _formulaire(page.text, revision_pdf + 1)
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=stale)
    assert response.status_code == 409 and "CONFLIT_REVISION_PDF" in response.text
    stale_ap = _formulaire(page.text, revision_pdf, revision_ap="2")
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=stale_ap)
    assert response.status_code == 409 and "CONFLIT_REVISION" in response.text


@pytest.mark.parametrize("changements,code", [
    ({"taxe_imprimee": "14.99"}, "AP_TAXES_IMPRIMEES_INCOHERENTES"),
    ({"total_imprime": "114.99"}, "REJ-AP-FACTURE-TOTAL-INCOHERENT"),
    ({"devise": "USD"}, "REJ-AP-DEVISE-NON-CAD"),
    ({"sous_total_imprime": "100.00 CAD"}, "AP_MONTANTS_A_REVOIR"),
    ({"taxe_imprimee": "14,98"}, "AP_MONTANTS_A_REVOIR"),
    ({"total_imprime": "1e3"}, "AP_MONTANTS_A_REVOIR"),
])
def test_verification_m5_refuse_taxes_et_total_imprimes_incoherents(client_ap_m5, changements, code):
    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5, changements=changements)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    avant = _snapshot_tables()
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert response.status_code == 409 and code in response.text
    assert _snapshot_tables() == avant


def test_verification_m5_refuse_une_facture_deja_saisie_sans_effet(client_ap_m5):
    _reception_m5()
    _facture_existante_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    avant = _snapshot_tables()
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert response.status_code == 409 and "REJ-AP-FACTURE-DOUBLON" in response.text
    assert _snapshot_tables() == avant


def test_verification_m5_rejette_query_champs_dupliques_et_injection_html(client_ap_m5):
    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    action = _LOT_URL.format(lot_id)
    assert client_ap_m5.post(action + "?q=1", data=_formulaire(page.text, revision_pdf)).status_code == 400
    duplicate = list(_formulaire(page.text, revision_pdf).items()) + [("po_id", "PO-1")]
    response = client_ap_m5.post(action, content=urlencode(duplicate),
                                 headers={"content-type": "application/x-www-form-urlencoded"})
    assert response.status_code == 400
    assert _MARQUEUR not in response.text

    unknown = _formulaire(page.text, revision_pdf) | {"acteur": "admin", "montant": "999999.00"}
    response = client_ap_m5.post(action, data=unknown)
    assert response.status_code == 400
    escaped = _formulaire(page.text, revision_pdf, po_id=_MARQUEUR)
    response = client_ap_m5.post(action, data=escaped)
    assert response.status_code == 409 and _MARQUEUR not in response.text
    assert "secret" not in response.text.lower() and "traceback" not in response.text.lower()


def test_verification_m5_revalide_identite_apres_appel_bloquant(client_ap_m5, monkeypatch):
    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    original = fusion_ap_m5.verifier

    def verifier_puis_revoquer(*args, **kwargs):
        result = original(*args, **kwargs)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        return result

    monkeypatch.setattr(fusion_ap_m5, "verifier", verifier_puis_revoquer)
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert response.status_code == 403
    assert "CONTROLES_M5_COMPATIBLES" not in response.text and "source_sha256" not in response.text


def test_verification_m5_ne_rend_pas_les_details_d_une_exception_inattendue(client_ap_m5, monkeypatch):
    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    monkeypatch.setattr(fusion_ap_m5, "verifier", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("texte OCR privé et ciphertext fictif")))
    response = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert response.status_code == 503
    assert "VERIFICATION_M5_INDISPONIBLE" in response.text
    assert "texte OCR privé" not in response.text and "ciphertext" not in response.text


def test_role_finance_revoque_pendant_rendu_html_masque_le_resultat(client_ap_m5, monkeypatch):
    from opsys.console import pages

    _reception_m5()
    lot_id, revision_pdf = _lot_avec_brouillon(client_ap_m5)
    # Cet admin conserve l'accès AP quand son rôle finance est retiré.
    with stockage.transaction() as cnx:
        identite.ajouter_role(cnx, _ADMIN, "finance")
    _connecter(client_ap_m5, _ADMIN)
    page = client_ap_m5.get(f"/fusion/pdf/lots/{lot_id}/ap")
    original = pages.gabarit

    def rendre_et_revoquer(*args, **kwargs):
        html = original(*args, **kwargs)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, _ADMIN, "finance")
        return html

    monkeypatch.setattr(pages, "gabarit", rendre_et_revoquer)
    reponse = client_ap_m5.post(_LOT_URL.format(lot_id), data=_formulaire(page.text, revision_pdf))
    assert reponse.status_code == 403
    assert "CONTROLES_M5_COMPATIBLES" not in reponse.text
