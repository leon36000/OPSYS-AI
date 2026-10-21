"""Contrat strict de provenance PDF; contenu et identités fictifs."""
from __future__ import annotations

import copy

import pytest
from m10_memoire import provenance_documentaire

LOT = "12345678-1234-4234-8234-1234567890ab"
SHA = "a" * 64
DATE = "2026-10-04T12:00:00+00:00"


def _pdf(**modifications):
    document = {
        "type_entree": "provenance_documentaire", "genre": "m5.document_pdf_natif", "lot_id": LOT,
        "reference_locale": f"opsys-ingestion://m05-financecore/pdf/lots/{LOT}", "source_sha256": SHA,
        "classe": "FINANCIAL", "auteur": "admin.fictif", "acteur_transition": "nathan",
        "extracteur": "pypdf-6.19.0/pdf-natif-1", "configuration_sha256": "b" * 64,
        "source_revision": 1, "revision": 1, "statut": "RECU", "total_pages": 0,
        "code": None, "horodatage": DATE,
    }
    return document | modifications


def _csv():
    return {
        "type_entree": "provenance_documentaire", "genre": "m5.releve_bancaire_csv", "lot_id": LOT,
        "reference_locale": f"opsys-ingestion://m05-financecore/lots/{LOT}", "source_sha256": SHA,
        "classe": "FINANCIAL", "auteur": "admin.fictif", "snapshot_version": 0,
        "snapshot_empreinte": None, "compte_interne_id": "COMPTE-FICTIF", "total_lignes": 0,
        "nombre_propositions": 0, "revision": 1, "statut": "AUCUNE_PROPOSITION", "horodatage": DATE,
    }


class _RegistreCAS(list):
    def append(self, maillon, *, rang_attendu=None):
        assert rang_attendu == len(self)
        super().append(maillon)


def test_dispatch_strict_pdf_preserve_champs_et_validation_csv():
    assert provenance_documentaire.valider(_pdf()) == _pdf()
    assert frozenset(_pdf()) == provenance_documentaire.CHAMPS_PDF
    assert frozenset(_csv()) == provenance_documentaire.CHAMPS
    assert provenance_documentaire.valider(_csv()) == _csv()


@pytest.mark.parametrize("modifications", [
    {"pii": "email@example.invalid"}, {"source_sha256": "A" * 64}, {"source_revision": True},
    {"revision": 0}, {"total_pages": True}, {"total_pages": 21}, {"statut": []}, {"code": []},
    {"extracteur": "courriel@example.invalid"}, {"reference_locale": "opsys-ingestion://autre"},
    {"lot_id": "pas-un-uuid"}, {"auteur": "NOM-CONFIDENTIEL"}, {"horodatage": "2026-10-04T12:00:00"},
    {"statut": "EXTRAIT_PREPARATOIRE"}, {"statut": "REFUSE", "code": "PDF_TIMEOUT"},
    {"statut": "ERREUR_REPRENABLE", "code": "PDF_MALFORME"},
])
def test_pdf_refuse_forme_incoherente_ou_champ_libre(modifications):
    with pytest.raises(ValueError):
        provenance_documentaire.valider(_pdf(**modifications))


def test_pdf_valide_codes_fermes_et_pages_extraites():
    extrait = _pdf(statut="EXTRAIT_PREPARATOIRE", total_pages=20)
    refuse = _pdf(statut="REFUSE", code="PDF_MALFORME")
    reprenable = _pdf(statut="ERREUR_REPRENABLE", code="PDF_TIMEOUT")
    assert provenance_documentaire.valider(extrait)["total_pages"] == 20
    assert provenance_documentaire.valider(refuse)["code"] == "PDF_MALFORME"
    assert provenance_documentaire.valider(reprenable)["code"] == "PDF_TIMEOUT"


def test_pdf_enregistrer_est_idempotent_et_revision_source_doit_suivre():
    registre = _RegistreCAS()
    original = _pdf(source_revision=3)
    premier = provenance_documentaire.enregistrer(registre, original)
    assert provenance_documentaire.enregistrer(registre, original) == premier
    second = _pdf(source_revision=4, revision=2, statut="ERREUR_REPRENABLE", code="PDF_TIMEOUT")
    provenance_documentaire.enregistrer(registre, second)
    assert provenance_documentaire.lire(registre, LOT) == second
    saut = _pdf(source_revision=6, revision=3)
    with pytest.raises(ValueError, match="source ou version"):
        provenance_documentaire.enregistrer(registre, saut)
    autre_source = _pdf(source_sha256="c" * 64, source_revision=5, revision=3)
    with pytest.raises(ValueError, match="source ou version"):
        provenance_documentaire.enregistrer(registre, autre_source)
    conflict = _pdf(source_revision=3, acteur_transition="admin.fictif")
    with pytest.raises(ValueError, match="différent"):
        provenance_documentaire.enregistrer(registre, conflict)


def test_pdf_et_csv_ne_peuvent_pas_reutiliser_le_meme_lot_id():
    registre = _RegistreCAS()
    provenance_documentaire.enregistrer(registre, _csv())
    with pytest.raises(ValueError, match="collision de genre"):
        provenance_documentaire.enregistrer(registre, _pdf())
    assert len(registre) == 1


def test_pdf_donnees_additionnelles_sont_refusees():
    mauvais = copy.deepcopy(_pdf())
    mauvais["nom_fichier"] = "confidentiel.pdf"
    with pytest.raises(ValueError, match="provenance PDF"):
        provenance_documentaire.valider(mauvais)
