"""Migration 0049 : capacité « vision » du registre de fournisseurs (M3.3 et M3.5). Aucune table, une CHECK élargie.

Montée, descente, refus de descente avec un fournisseur « vision » configuré, remontée ; SQLite. Données fictives.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from opsys import stockage
from opsys.console import plateforme_ui
from opsys.fournisseurs import catalogue, politique
from opsys.fournisseurs.modele import CAPACITES, Fournisseur, Licence
from opsys.fournisseurs.politique import ProfilClient

FICTIF = True
INSERT = (
    "INSERT INTO fournisseurs_configurations "
    "(identifiant, capacite, definition, actif, revision, modifie_le, modifie_par) "
    "VALUES ('{ident}', '{cap}', '{{}}', 0, 1, 't', 'a')"
)
PME = ProfilClient(True, 100_000, frozenset({"CA"}), False)


def test_0049_est_la_tete_et_ne_cree_aucune_table():
    script = ScriptDirectory.from_config(stockage._config())
    assert len(script.get_heads()) == 1
    revision = script.get_revision("0049")
    assert revision is not None and revision.down_revision == "0046"


def test_montee_descente_refus_avec_donnees_et_remontee(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "m.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0046")
        tables_avant = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        with pytest.raises(IntegrityError):  # avant 0049, « vision » n'est pas une capacité admise
            cnx.exec_driver_sql(INSERT.format(ident="vision.x.local", cap="vision"))
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0049")
        cnx.exec_driver_sql(INSERT.format(ident="vision.x.local", cap="vision"))  # permis maintenant
        with pytest.raises(IntegrityError):
            cnx.exec_driver_sql(INSERT.format(ident="inconnue.x", cap="telepathie"))
        assert {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")} == tables_avant
        with pytest.raises(Exception, match="rétrogradation refusée"):
            command.downgrade(cfg, "0046")  # un fournisseur « vision » est configuré : aucune suppression
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0049"
        cnx.exec_driver_sql("DELETE FROM fournisseurs_configurations")
        command.downgrade(cfg, "0046")
        with pytest.raises(IntegrityError):  # la CHECK d'avant est rétablie
            cnx.exec_driver_sql(INSERT.format(ident="vision.y.local", cap="vision"))
        command.upgrade(cfg, "0049")  # remontable
        cnx.exec_driver_sql(INSERT.format(ident="vision.z.local", cap="vision"))
        assert cnx.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"


def test_la_capacite_vision_est_au_modele_au_catalogue_et_a_la_console():
    assert "vision" in CAPACITES and "vision" in plateforme_ui._LIBELLES_CAPACITES
    assert set(CAPACITES) <= set(plateforme_ui._LIBELLES_CAPACITES)
    vision = {f.identifiant: f for f in catalogue.CATALOGUE if f.capacite == "vision"}
    assert set(vision) == {
        "vision.grounding-dino.local",
        "vision.sam2.local",
        "vision.florence-2.local",
        "vision.owlv2.local",
        "vision.ultralytics-yolo",
    }


def test_aucun_modele_de_vision_n_est_activable_sans_lecture_de_licence_et_aucun_n_est_qualifie():
    vision = [f for f in catalogue.CATALOGUE if f.capacite == "vision"]
    for f in vision:
        assert f.qualification == "a_mesurer" and f.point_acces is None and f.reference_secret is None, f.identifiant
        assert f.licence.verification == "a_lire" and f.licence.source.startswith("hors-recherche"), f.identifiant
        assert politique.LICENCE_A_VERIFIER in politique.evaluer(f, PME).codes, f.identifiant
        assert not politique.evaluer(f, PME).conforme
    yolo = next(f for f in vision if f.identifiant == "vision.ultralytics-yolo")
    assert yolo.statut_catalogue == "ecarte" and yolo.licence.copyleft
    assert {politique.FOURNISSEUR_ECARTE, politique.COPYLEFT_INTEGRE} <= set(politique.evaluer(yolo, PME).codes)
    # lue par un administrateur, la licence permissive d'un modèle adopté devient conforme, mais il reste « à mesurer »
    lue = Fournisseur.depuis_json(
        {
            **next(f for f in vision if f.identifiant == "vision.sam2.local").vers_json(),
            "licence_lue_par": "admin_fictif",
        }
    )
    assert politique.evaluer(lue, PME).conforme and lue.qualification == "a_mesurer"


def test_un_modele_de_vision_declare_a_la_main_suit_la_meme_validation():
    f = Fournisseur(
        identifiant="vision.maison.local",
        capacite="vision",
        mode="local",
        modele="Modèle fictif",
        licence=Licence(
            code="MIT", poids="MIT", usage_commercial="autorise", service_tiers="autorise", source="fictif"
        ),
    )
    assert Fournisseur.depuis_json(f.vers_json()) == f
