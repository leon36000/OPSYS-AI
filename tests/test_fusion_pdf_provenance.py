"""Oracles de provenance documentaire, données et identités entièrement fictives."""
from __future__ import annotations

import base64
import hashlib

import pytest
from sqlalchemy import LargeBinary, cast, delete, func, insert, select, update

from opsys import etat, fusion_pdf, stockage


@pytest.fixture(autouse=True)
def sqlite_fictive_uniquement(opsys_home, monkeypatch):
    opsys_home.mkdir(parents=True)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{opsys_home / 'qualification-provenance-pdf.db'}")


@pytest.fixture
def base_documentaire_pdf(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"f" * 32).decode())
    return nathan


def test_admission_pdf_inscrit_provenance_candidate_sans_corps(base_documentaire_pdf):
    source = b"%PDF-1.7\n% DOCUMENT-CANARI-ENTIEREMENT-FICTIF\n"
    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="provenance-pdf-admission-fictive", pdf_octets=source,
    )
    assert lot["statut"] == "RECU"
    with stockage.transaction():
        maillons = list(stockage.maillons("m10-memoire", "documents"))
    assert len(maillons) == 1
    trace = maillons[0]
    assert trace["genre"] == "m5.document_pdf_natif"
    assert trace["lot_id"] == lot["lot_id"]
    assert trace["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert trace["statut"] == "RECU" and trace["source_revision"] == 1
    assert trace["classe"] == "FINANCIAL"
    assert "DOCUMENT-CANARI" not in str(trace) and "texte" not in trace and "pages" not in trace


def _extraire_ok(source):
    texte = "Extrait fictif sans donnée comptable"
    return {"ok": True, "resultat": {
        "schema_version": 1, "source_sha256": hashlib.sha256(source).hexdigest(),
        "extracteur": fusion_pdf.EXTRACTEUR, "configuration_sha256": fusion_pdf.CONFIGURATION_SHA256,
        "pages": [{"numero": 1, "fragments": [{
            "id": "p1-f1", "texte": texte, "sha256": hashlib.sha256(texte.encode()).hexdigest(),
        }]}],
    }}


def _traces():
    with stockage.transaction():
        return list(stockage.maillons("m10-memoire", "documents"))


def test_transition_pdf_met_a_jour_provenance_et_lecture_jointe_sans_backfill(
    base_documentaire_pdf, monkeypatch,
):
    source = b"%PDF-1.7\n% FICTIF-SANS-CORPS-M10\n"
    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="transition-pdf-fictive", pdf_octets=source,
    )
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", _extraire_ok)
    extrait = fusion_pdf.preparer(stockage.transaction, base_documentaire_pdf, lot["lot_id"], lot["revision"])

    traces = _traces()
    assert [trace["source_revision"] for trace in traces] == [1, 2]
    assert [trace["revision"] for trace in traces] == [1, 2]
    assert traces[-1]["statut"] == "EXTRAIT_PREPARATOIRE" and traces[-1]["total_pages"] == 1
    assert traces[-1]["acteur_transition"] == base_documentaire_pdf
    assert "FICTIF-SANS-CORPS-M10" not in str(traces)
    joined = fusion_pdf.lire_avec_provenance(stockage.transaction, base_documentaire_pdf, lot["lot_id"])
    provenance_publique = {
        key: value for key, value in traces[-1].items() if key not in {"ligne_id", "precedent_ligne_id"}
    }
    assert joined == {"lot": extrait, "provenance": provenance_publique}
    avant_rejeu = len(_traces())
    assert fusion_pdf.preparer(
        stockage.transaction, base_documentaire_pdf, lot["lot_id"], extrait["revision"],
    ) == extrait
    assert len(_traces()) == avant_rejeu


def test_erreur_reprenable_puis_reprise_suit_revision_source_et_revision_m10(
    base_documentaire_pdf, monkeypatch,
):
    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="reprise-pdf-fictive", pdf_octets=b"%PDF-1.7\n",
    )
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", lambda _source: {"ok": False, "code": "PDF_TIMEOUT"})
    erreur = fusion_pdf.preparer(stockage.transaction, base_documentaire_pdf, lot["lot_id"], lot["revision"])
    assert erreur["statut"] == "ERREUR_REPRENABLE" and erreur["code"] == "PDF_TIMEOUT"
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", _extraire_ok)
    extrait = fusion_pdf.preparer(
        stockage.transaction, base_documentaire_pdf, lot["lot_id"], erreur["revision"],
    )
    traces = _traces()
    assert [trace["source_revision"] for trace in traces] == [1, 2, 3]
    assert [trace["revision"] for trace in traces] == [1, 2, 3]
    assert [trace["statut"] for trace in traces] == ["RECU", "ERREUR_REPRENABLE", "EXTRAIT_PREPARATOIRE"]
    assert traces[-1]["total_pages"] == extrait["total_pages"] == 1


def test_echec_validation_apres_append_annule_admission_quota_commande_et_journal(
    base_documentaire_pdf, monkeypatch,
):
    monkeypatch.setattr(
        fusion_pdf, "_lire_provenance_pdf_cnx",
        lambda *_args: (_ for _ in ()).throw(fusion_pdf._erreur("PDF_PROVENANCE_INDISPONIBLE", 503)),
    )
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.creer(
            stockage.transaction, base_documentaire_pdf, mutation_id="rollback-pdf-fictif", pdf_octets=b"%PDF-1.7\n",
        )
    assert erreur.value.code == "PDF_PROVENANCE_INDISPONIBLE"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(fusion_pdf.FUSION_PDF_LOTS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(fusion_pdf.FUSION_PDF_COMMANDES)).scalar_one() == 0
        quota = cnx.execute(select(fusion_pdf.FUSION_PDF_QUOTA)).mappings().one()
        assert quota["lots"] == 0 and quota["octets_cipher"] == 0
        assert list(stockage.maillons("m10-memoire", "documents")) == []
        assert etat.lire_journal(cnx) == []


def test_ancienne_admission_sans_provenance_reste_absente_en_lecture_et_rejeu(
    base_documentaire_pdf, monkeypatch,
):
    source = b"%PDF-1.7\n% ANCIEN-LOT-FICTIF\n"
    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="ancien-pdf-fictif", pdf_octets=source,
    )
    with stockage.transaction() as cnx:
        cnx.execute(delete(fusion_pdf.REGISTRES).where(
            (fusion_pdf.REGISTRES.c.departement == "m10-memoire")
            & (fusion_pdf.REGISTRES.c.registre == "documents")
        ))
    joined = fusion_pdf.lire_avec_provenance(stockage.transaction, base_documentaire_pdf, lot["lot_id"])
    assert joined == {"lot": lot, "provenance": None}
    rejoue = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="ancien-pdf-rejeu-fictif", pdf_octets=source,
    )
    assert rejoue == lot
    assert _traces() == []
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", _extraire_ok)
    transition = fusion_pdf.preparer(
        stockage.transaction, base_documentaire_pdf, lot["lot_id"], lot["revision"],
    )
    assert transition["revision"] == 2
    (trace,) = _traces()
    assert trace["source_revision"] == 2 and trace["revision"] == 1


def test_registre_hors_borne_est_refuse_avant_decodeur(base_documentaire_pdf, monkeypatch):
    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="borne-pdf-fictive", pdf_octets=b"%PDF-1.7\n",
    )
    with stockage.transaction() as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement="m10-memoire", registre="documents", rang=1,
            maillon="x" * (fusion_pdf._M10_LIGNE_MAX + 1),
        ))
    monkeypatch.setattr(codec, "decoder", lambda *_args: pytest.fail("maillon décodé avant contrôle SQL"))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.lire_avec_provenance(stockage.transaction, base_documentaire_pdf, lot["lot_id"])
    assert erreur.value.code == "PDF_PROVENANCE_INDISPONIBLE" and erreur.value.statut_http == 503


def test_borne_post_append_annule_transition_et_toutes_les_metadonnees(base_documentaire_pdf, monkeypatch):
    from opsys.stockage.schema import REGISTRES

    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="rollback-transition-fictif", pdf_octets=b"%PDF-1.7\n",
    )
    traces_avant = _traces()
    with stockage.transaction() as cnx:
        quota_avant = dict(cnx.execute(select(fusion_pdf.FUSION_PDF_QUOTA)).mappings().one())
        journal_avant = etat.lire_journal(cnx)
        total = cnx.execute(select(func.sum(func.length(cast(
            REGISTRES.c.maillon, LargeBinary,
        )))).where(
            (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        )).scalar_one()
    monkeypatch.setattr(fusion_pdf, "_M10_TOTAL_MAX", total)
    monkeypatch.setattr(fusion_pdf, "_extraire_isole", _extraire_ok)
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.preparer(stockage.transaction, base_documentaire_pdf, lot["lot_id"], lot["revision"])
    assert erreur.value.code == "PDF_PROVENANCE_INDISPONIBLE"
    with stockage.transaction() as cnx:
        courant = dict(cnx.execute(select(fusion_pdf.FUSION_PDF_LOTS)).mappings().one())
        assert courant["revision"] == 1 and courant["statut"] == "RECU"
        assert courant["resultat_cipher"] is None and courant["resultat_cipher_octets"] == 0
        assert dict(cnx.execute(select(fusion_pdf.FUSION_PDF_QUOTA)).mappings().one()) == quota_avant
        assert etat.lire_journal(cnx) == journal_avant
        assert cnx.execute(select(func.count()).select_from(fusion_pdf.FUSION_PDF_COMMANDES)).scalar_one() == 1
    assert _traces() == traces_avant


def test_maillon_m10_corrompu_refuse_lecture_jointe_sans_detail_interne(base_documentaire_pdf):
    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    lot = fusion_pdf.creer(
        stockage.transaction, base_documentaire_pdf, mutation_id="corruption-pdf-fictive", pdf_octets=b"%PDF-1.7\n",
    )
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        )).scalar_one()
        maillon = codec.decoder(ligne)
        maillon["statut"] = "REFUSE"
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
            & (REGISTRES.c.rang == 0)
        ).values(maillon=codec.encoder(maillon)))
    with pytest.raises(fusion_pdf.FusionPDFErreur) as erreur:
        fusion_pdf.lire_avec_provenance(stockage.transaction, base_documentaire_pdf, lot["lot_id"])
    assert erreur.value.code == "PDF_PROVENANCE_INDISPONIBLE" and erreur.value.statut_http == 503
    assert str(erreur.value) == "opération PDF refusée ou temporairement indisponible"
