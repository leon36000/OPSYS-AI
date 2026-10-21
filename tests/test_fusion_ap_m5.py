"""Vérification AP privée sur PDF natif et SQLite réels; toutes les données sont fictives."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer, outils, registre, taux_fiscaux
from sqlalchemy import select, update

from opsys import fusion_ap, fusion_pdf, identite, stockage
from opsys.console import fusion_ap_m5
from opsys.stockage.schema import FUSION_AP_BROUILLONS, FUSION_PDF_LOTS, META, REGISTRES

FICTIF = True
_SPEC = importlib.util.spec_from_file_location("fixture_ap_source_m5", Path(__file__).with_name("test_fusion_ap.py"))
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
_facture_pdf_fictive, _payload = _FIXTURE._facture_pdf_fictive, _FIXTURE._payload


def _tables() -> dict:
    with stockage.transaction() as cnx:
        return {nom: [dict(row) for row in cnx.execute(select(table)).mappings()]
                for nom, table in META.tables.items()}


@pytest.fixture
def ap_m5(nathan, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"v" * 32).decode())
    taux = tmp_path / "taux-fictif.yaml"
    taux.write_bytes(Path(outils._CHEMIN_TAUX_FISCAUX).read_bytes())
    monkeypatch.setattr(outils, "_CHEMIN_TAUX_FISCAUX", taux)
    pdf = fusion_pdf.creer(stockage.transaction, nathan, mutation_id="ap-m5-fictif",
                           pdf_octets=_facture_pdf_fictive())
    pdf = fusion_pdf.preparer(stockage.transaction, nathan, pdf["lot_id"], pdf["revision"])
    assert pdf["statut"] == "EXTRAIT_PREPARATOIRE"
    extrait = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    payload = _payload(extrait)
    payload["champs"].update(sous_total_imprime="100.00", taxe_imprimee="14.98", total_imprime="114.98")
    brouillon = fusion_ap.enregistrer(
        stockage.transaction, nathan, pdf["lot_id"], mutation_id="ap-m5-brouillon-fictif",
        revision_pdf_attendue=pdf["revision"], revision_attendue=0, proposition=payload,
    )
    reception, verdict = comptes_a_payer.construire_reception({
        "evenement_id": "reception-fictive", "po_id": "PO-FICTIF-7", "fournisseur_id": "fournisseur-fictif",
        "chantier_id": "CHANTIER-FICTIF", "horodatage_reception": "2026-10-01T10:00:00-04:00",
        "verdict_reception": "CONFORME", "statut_po": "received", "hash_maillon": "a" * 64,
        "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{
            "materiau_id": "article-fictif", "quantite_demandee": "1", "quantite_recue": "1",
            "prix_unitaire_prevu": "100.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
            "prix_unitaire_reception": "100.00", "verdict_prix_reception": "PRIX_CATALOGUE",
            "ecart_prix_critique": False,
        }],
    })
    assert verdict is None
    with stockage.transaction():
        reg = registre.Registre(maillons=stockage.maillons("m05-financecore", "comptes_a_payer"))
        assert comptes_a_payer.enregistrer_reception(reception, reg)[1] is None
    return {"pdf": pdf, "brouillon": brouillon, "payload": payload, "taux": taux, "acteur": nathan}


def _verifier(contexte, **options):
    args = {"revision_pdf": contexte["pdf"]["revision"], "revision_ap": contexte["brouillon"]["revision"],
            "po_id": "PO-FICTIF-7", "fournisseur_id": "fournisseur-fictif", "correspondance_confirmee": True}
    args.update(options)
    return fusion_ap_m5.verifier(stockage.transaction, contexte["acteur"], contexte["pdf"]["lot_id"], **args)


def test_controle_et_garde_terminale_ne_modifient_aucune_table(ap_m5):
    before = _tables()
    resultat = _verifier(ap_m5)
    assert resultat["statut"] == "CONTROLES_M5_COMPATIBLES"
    assert resultat["calcul"]["montant_apres_taxes"] == "114.98"
    assert resultat["source"]["taux_sha256"] == hashlib.sha256(ap_m5["taux"].read_bytes()).hexdigest()
    assert all(taxe["version"] == "2026-v1" and taxe["source"] for taxe in resultat["calcul"]["taxes"])
    fusion_ap_m5.confirmer_sources(stockage.transaction, ap_m5["acteur"], ap_m5["pdf"]["lot_id"], resultat)
    assert _tables() == before
    assert _verifier(ap_m5)["snapshot_id"] == resultat["snapshot_id"]
    assert _tables() == before


@pytest.mark.parametrize("cible", ["source", "ap", "registre"])
def test_corruption_source_ap_ou_chaine_refuse_sans_ecriture(ap_m5, cible):
    with stockage.transaction() as cnx:
        if cible == "source":
            cnx.execute(update(FUSION_PDF_LOTS).where(FUSION_PDF_LOTS.c.lot_id == ap_m5["pdf"]["lot_id"])
                        .values(source_cipher="!"))
        elif cible == "ap":
            cnx.execute(update(FUSION_AP_BROUILLONS).where(
                FUSION_AP_BROUILLONS.c.lot_id == ap_m5["pdf"]["lot_id"]).values(revision=99))
        else:
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == "m05-financecore").values(maillon="{}"))
    before = _tables()
    with pytest.raises(fusion_ap.FusionAPErreur):
        _verifier(ap_m5)
    assert _tables() == before


def test_changement_fichier_taux_durant_calcul_refuse(ap_m5, monkeypatch):
    original = comptes_a_payer.verifier_facture_fournisseur

    def calcul(**kwargs):
        result = original(**kwargs)
        ap_m5["taux"].write_bytes(ap_m5["taux"].read_bytes() + b"\n# changement fictif\n")
        return result

    monkeypatch.setattr(comptes_a_payer, "verifier_facture_fournisseur", calcul)
    before = _tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        _verifier(ap_m5)
    assert refus.value.code == "AP_SOURCES_MODIFIEES"
    assert _tables() == before


def test_revision_ap_changee_avant_rendu_refuse_la_garde_terminale(ap_m5):
    resultat = _verifier(ap_m5)
    payload = copy.deepcopy(ap_m5["payload"])
    payload["champs"]["numero"] = "FICTIF-2043"
    fusion_ap.enregistrer(
        stockage.transaction, ap_m5["acteur"], ap_m5["pdf"]["lot_id"], mutation_id="changement-fictif",
        revision_pdf_attendue=ap_m5["pdf"]["revision"], revision_attendue=ap_m5["brouillon"]["revision"],
        proposition=payload,
    )
    before = _tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        fusion_ap_m5.confirmer_sources(stockage.transaction, ap_m5["acteur"], ap_m5["pdf"]["lot_id"], resultat)
    assert refus.value.code == "CONFLIT_REVISION"
    assert _tables() == before


def test_admin_sans_role_finance_est_refuse_meme_si_pdf_autorise(ap_m5):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin-fictif", "Admin fictif", "phrase-fictive-de-qualification", ["admin"])
    ap_m5["acteur"] = "admin-fictif"
    before = _tables()
    with pytest.raises(PermissionError):
        _verifier(ap_m5)
    assert _tables() == before


@pytest.mark.parametrize("raw", [b"schema_version: [", b"schema_version: 1\ntaux: []\n", b"\xff"])
def test_fichier_taux_invalide_reste_indisponible_sans_detail(ap_m5, raw):
    ap_m5["taux"].write_bytes(raw)
    before = _tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        _verifier(ap_m5)
    assert refus.value.statut_http == 503 or refus.value.code == "REJ-TAUX-INCONNU"
    assert "schema_version" not in str(refus.value)
    assert _tables() == before


def test_loader_fiscal_valide_les_octets_epingles_sans_relire_le_fichier(tmp_path):
    raw = Path(outils._CHEMIN_TAUX_FISCAUX).read_bytes()
    resultat, erreurs = taux_fiscaux.charger_taux_fiscaux(tmp_path / "absent", contenu_octets=raw)
    assert not erreurs and resultat["tvq_quebec"]["version"] == "2026-v1"
    with pytest.raises(TypeError):
        taux_fiscaux.charger_taux_fiscaux(tmp_path / "absent", contenu_octets="pas-des-bytes")


@pytest.mark.parametrize("borne", ["_MAX_BYTES", "_MAX_ROW_BYTES"])
def test_source_ap_hors_borne_est_refusee_avant_decodage(ap_m5, monkeypatch, borne):
    monkeypatch.setattr(fusion_ap_m5, borne, 1)
    monkeypatch.setattr(fusion_ap_m5.codec, "decoder", lambda _: pytest.fail("aucun décodage hors borne"))
    before = _tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        _verifier(ap_m5)
    assert refus.value.code == "M5_REGISTRE_INDISPONIBLE" and refus.value.statut_http == 503
    assert _tables() == before
