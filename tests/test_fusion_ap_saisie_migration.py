"""Migration SQLite de provenance AP, avec données fictives conservées et rollback."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic import command, op
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from opsys import approbations, stockage
from opsys.outils import Niveau
from opsys.stockage.schema import (
    EFFACEMENTS_CLES,
    FUSION_AP_OCR_SOURCES,
    FUSION_AP_SAISIES,
    FUSION_PDF_OCR_COMMANDES,
    FUSION_PDF_OCR_QUOTA,
    FUSION_PDF_OCR_RUNS,
    META,
    PIECES_CLASSEMENTS,
    PIECES_PROJET,
    RECEPTIONS_COURRIEL,
)

FICTIF = True
_SPEC = importlib.util.spec_from_file_location(
    "fixtures_migration_ap", Path(__file__).with_name("test_fusion_ap_m5.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
ap_m5 = _FIXTURE.ap_m5


def _migration(revision: str, *, descendre: bool = False):
    cfg = stockage._config()
    with stockage.moteur().begin() as cnx:
        cfg.attributes["connection"] = cnx
        (command.downgrade if descendre else command.upgrade)(cfg, revision)


def _anciennes():
    # Ce scénario compare les tables antérieures à 0024, y compris lors du
    # retour à 0023. Les compartiments OCR/AP OCR ajoutés après 0024 ont des
    # scénarios distincts de conservation et de rollback. La file de nettoyage
    # 0027, les pièces/leurs classements 0028/0029 et les originaux courriel 0030 sont absents
    # du schéma historique 0023. Ne pas ignorer dynamiquement une table manquante :
    # toute table réellement attendue en 0023 doit encore être lue et comparée.
    nouvelles = {t.name for t in (
        FUSION_AP_SAISIES, FUSION_AP_OCR_SOURCES, EFFACEMENTS_CLES,
        FUSION_PDF_OCR_RUNS, FUSION_PDF_OCR_COMMANDES, FUSION_PDF_OCR_QUOTA,
        PIECES_PROJET, PIECES_CLASSEMENTS, RECEPTIONS_COURRIEL,
    )}
    with stockage.transaction() as cnx:
        return {nom: [dict(r) for r in cnx.execute(select(t)).mappings()]
                for nom, t in META.tables.items() if nom not in nouvelles}


def _ligne(contexte):
    with stockage.transaction() as cnx:
        approval = approbations.creer_demande(
            cnx, "m05-financecore", "m5_saisir_facture_fournisseur", {"fictif": True}, niveau=Niveau.N3,
        )
    return {"lot_id": contexte["pdf"]["lot_id"], "acteur": contexte["acteur"],
            "mutation_id": "migration-fictive", "commande_sha256": "a" * 64, "preuve_json": "{}",
            "approbation_id": approval, "facture_id": "facture-fictive", "maillon_id": "b" * 64,
            "rang_maillon": 1, "cree_le": "2026-10-04T00:00:00+00:00"}


def test_migration_0023_0024_preserve_donnees_et_contraintes(ap_m5):
    before = _anciennes()
    _migration("0023", descendre=True)
    assert stockage.revision_courante() == "0023"
    assert _anciennes() == before
    _migration("0024")
    assert stockage.revision_courante() == "0024"
    assert _anciennes() == before
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_AP_SAISIES)).all() == []
        assert {c["name"] for c in inspect(cnx).get_columns(FUSION_AP_SAISIES.name)} == set(FUSION_AP_SAISIES.c.keys())
        assert {fk["referred_table"] for fk in inspect(cnx).get_foreign_keys(FUSION_AP_SAISIES.name)} == {
            "fusion_ap_brouillons", "approbations",
        }
    _migration("head")
    assert _anciennes() == before


def test_downgrade_refuse_provenance_existante_sans_perte(ap_m5):
    row = _ligne(ap_m5)
    with stockage.transaction() as cnx:
        cnx.execute(FUSION_AP_SAISIES.insert().values(**row))
    before = _anciennes()
    revision_avant = stockage.revision_courante()
    with pytest.raises(RuntimeError, match="provenances de saisie"):
        _migration("0023", descendre=True)
    assert stockage.revision_courante() == revision_avant
    assert _anciennes() == before
    with stockage.transaction() as cnx:
        assert dict(cnx.execute(select(FUSION_AP_SAISIES)).mappings().one()) == row


def test_panne_creation_table_annule_migration_et_revision(ap_m5, monkeypatch):
    _migration("0023", descendre=True)
    before = _anciennes()
    initial = op.create_table

    def panne(nom, *args, **kwargs):
        resultat = initial(nom, *args, **kwargs)
        if nom == FUSION_AP_SAISIES.name:
            raise RuntimeError("panne DDL fictive")
        return resultat

    monkeypatch.setattr(op, "create_table", panne)
    with pytest.raises(RuntimeError, match="panne DDL fictive"):
        _migration("0024")
    assert stockage.revision_courante() == "0023"
    with stockage.transaction() as cnx:
        assert FUSION_AP_SAISIES.name not in inspect(cnx).get_table_names()
    assert _anciennes() == before


@pytest.mark.parametrize("champ,valeur", [("maillon_id", "court"), ("rang_maillon", -1),
                                        ("preuve_json", "x" * 4097), ("approbation_id", "absente")])
def test_contraintes_refusent_liaison_invalide(ap_m5, champ, valeur):
    row = _ligne(ap_m5)
    before = _anciennes()
    row[champ] = valeur
    with pytest.raises(IntegrityError), stockage.transaction() as cnx:
        cnx.execute(FUSION_AP_SAISIES.insert().values(**row))
    assert _anciennes() == before
    with stockage.transaction() as cnx:
        assert cnx.execute(select(FUSION_AP_SAISIES)).all() == []


def test_snapshot_historique_0023_sans_parseur(session):
    """Le comparateur historique ne sélectionne pas les futures tables du logiciel."""
    from opsys.stockage.schema import JOURNAL

    with stockage.transaction() as cnx:
        cnx.execute(JOURNAL.insert().values(
            quand="2026-10-28T00:00:00+00:00", par="admin-fictif", action="qa.migration",
            cible="historique-fictif", details="{}",
        ))
    avant = _anciennes()
    _migration("0023", descendre=True)
    assert stockage.revision_courante() == "0023"
    apres = _anciennes()
    with stockage.transaction() as cnx:
        assert set(apres) == set(inspect(cnx).get_table_names()) - {"alembic_version"}
    assert apres == avant
    assert len(apres["journal"]) == 1
    _migration("0024")
    assert _anciennes() == avant
    _migration("head")
    assert _anciennes() == avant
