"""Coffre de secrets : chiffrement réel au repos, résolution serveur, rotation, révocation, journal, masquage.

Toutes les valeurs sont fictives (aucune vraie clé). La clé maîtresse est générée dans le dossier temporaire du test.
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from opsys import identite, stockage
from opsys.secrets_coffre import cle_maitresse, coffre, masquage
from opsys.secrets_coffre.erreurs import CoffreErreur
from opsys.stockage.schema import COFFRE_ACCES, COFFRE_VERSIONS

FICTIF = True
VALEUR = "valeur-fictive-cle-api-0123456789-XYZ"
VALEUR_2 = "valeur-fictive-rotation-9876543210-ABC"
MOT_DE_PASSE = "mot-de-passe-coffre-fictif-2026"


@pytest.fixture
def cle_fichier(tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    chemin = dossier / "coffre.cle"
    cle = cle_maitresse.generer_fichier(chemin)
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(chemin))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    return chemin, cle


@pytest.fixture
def admin(session):
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employe_fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
    return "admin_fictif"


def _definir(session, nom="google.ads", valeur=VALEUR, acteur="admin_fictif"):
    with session() as cnx:
        return coffre.definir(cnx, acteur=acteur, nom=nom, service="google_ads", valeur=valeur)


def _octets_base(opsys_home: Path) -> bytes:
    stockage.liberer()
    contenu = b""
    for chemin in opsys_home.rglob("*"):
        if chemin.is_file():
            contenu += chemin.read_bytes()
    return contenu


def test_chiffrement_reel_la_base_ne_contient_pas_la_valeur(session, admin, cle_fichier, opsys_home):
    meta = _definir(session)
    assert meta["etat"] == "actif" and meta["version"] == 1 and meta["valeur"] == "non affichable"
    assert VALEUR not in repr(meta)
    with session() as cnx:
        ligne = cnx.execute(select(COFFRE_VERSIONS)).mappings().one()
    assert len(ligne["nonce_valeur"]) == 12 and len(ligne["valeur_chiffree"]) == len(VALEUR) + 16
    assert ligne["empreinte_cle_maitresse"] == cle_fichier[1].empreinte
    brut = _octets_base(opsys_home)
    assert VALEUR.encode() not in brut and base64.b64encode(VALEUR.encode()) not in brut
    assert cle_fichier[0].read_bytes().strip() not in brut  # la clé maîtresse n'entre jamais en base
    with session() as cnx:
        assert all(VALEUR not in str(r) for r in coffre.journal(cnx))


def test_dechiffrement_cote_serveur_seulement(session, admin, cle_fichier):
    _definir(session)
    with coffre.utiliser(nom="google.ads", usage="connecteur:google-ads", acteur="opsys-systeme") as valeur:
        assert valeur == VALEUR
    with session() as cnx:
        dernier = coffre.journal(cnx, "google.ads")[0]
    assert (dernier["action"], dernier["resultat"], dernier["usage"]) == ("resolution", "ok", "connecteur:google-ads")


def test_resolution_interdite_dans_une_transaction_metier(session, admin, cle_fichier):
    _definir(session)
    with stockage.transaction(), pytest.raises(CoffreErreur) as exc, \
            coffre.utiliser(nom="google.ads", usage="connecteur:google-ads", acteur="opsys-systeme"):
        pass
    assert exc.value.code == "COFFRE_TRANSACTION_METIER"


def test_jeton_opaque_porteur_usage_expiration(session, admin, cle_fichier):
    _definir(session)
    with session() as cnx:
        jeton = coffre.emettre_jeton(cnx, acteur=admin, nom="google.ads", porteur="m07-marketing",
                                     usage="connecteur:google-ads", duree_s=3600)
    assert jeton.startswith(coffre.PREFIXE_JETON) and VALEUR not in jeton
    with coffre.utiliser(jeton=jeton, usage="connecteur:google-ads", acteur="m07-marketing") as valeur:
        assert valeur == VALEUR
    for kwargs, code in [
        ({"acteur": "m05-financecore", "usage": "connecteur:google-ads"}, "COFFRE_PORTEUR_REFUSE"),
        ({"acteur": "m07-marketing", "usage": "connecteur:meta-ads"}, "COFFRE_USAGE_REFUSE"),
        ({"acteur": "m07-marketing", "usage": "connecteur:google-ads", "maintenant": 4_000_000_000},
         "COFFRE_JETON_EXPIRE"),
    ]:
        with pytest.raises(CoffreErreur) as exc, coffre.utiliser(jeton=jeton, **kwargs):
            pass
        assert exc.value.code == code
    with pytest.raises(CoffreErreur) as exc, coffre.utiliser(jeton=coffre.PREFIXE_JETON + "A" * 43,
                                                             usage="connecteur:google-ads", acteur="m07-marketing"):
        pass
    assert exc.value.code == "COFFRE_JETON_INVALIDE"
    with session() as cnx:
        refus = [r for r in coffre.journal(cnx) if r["resultat"] == "refus"]
        empreintes = cnx.execute(text("SELECT empreinte FROM coffre_jetons")).scalars().all()
    assert {r["code"] for r in refus} >= {"COFFRE_PORTEUR_REFUSE", "COFFRE_USAGE_REFUSE", "COFFRE_JETON_EXPIRE",
                                          "COFFRE_JETON_INVALIDE"}
    assert jeton not in str(refus) and jeton not in empreintes  # seule l'empreinte est conservée


def test_rotation_remplace_et_detruit_l_ancienne_version(session, admin, cle_fichier, opsys_home):
    _definir(session)
    with session() as cnx:
        jeton = coffre.emettre_jeton(cnx, acteur=admin, nom="google.ads", porteur="m07-marketing",
                                     usage="connecteur:google-ads", duree_s=3600)
        meta = coffre.rotation(cnx, acteur=admin, nom="google.ads", valeur=VALEUR_2)
    assert meta["version"] == 2
    with session() as cnx:
        versions = {r["version"]: r for r in cnx.execute(select(COFFRE_VERSIONS)).mappings()}
    assert versions[1]["etat"] == "remplacee" and versions[1]["valeur_chiffree"] is None
    assert versions[1]["cle_enveloppee"] is None and versions[1]["purge_le"]
    with coffre.utiliser(jeton=jeton, usage="connecteur:google-ads", acteur="m07-marketing") as valeur:
        assert valeur == VALEUR_2  # le jeton suit le nom, donc la nouvelle valeur
    assert VALEUR_2.encode() not in _octets_base(opsys_home)


def test_revocation_immediate(session, admin, cle_fichier):
    _definir(session)
    with session() as cnx:
        jeton = coffre.emettre_jeton(cnx, acteur=admin, nom="google.ads", porteur="m07-marketing",
                                     usage="connecteur:google-ads", duree_s=3600)
        meta = coffre.revoquer(cnx, acteur=admin, nom="google.ads")
    assert meta["etat"] == "revoque" and meta["version"] is None and meta["jetons_actifs"] == 0
    with session() as cnx:
        ligne = cnx.execute(select(COFFRE_VERSIONS)).mappings().one()
    assert ligne["etat"] == "revoquee" and ligne["valeur_chiffree"] is None and ligne["nonce_valeur"] is None
    for kwargs in ({"nom": "google.ads", "acteur": "opsys-systeme"}, {"jeton": jeton, "acteur": "m07-marketing"}):
        with pytest.raises(CoffreErreur) as exc, coffre.utiliser(usage="connecteur:google-ads", **kwargs):
            pass
        assert exc.value.code in {"COFFRE_SECRET_REVOQUE", "COFFRE_JETON_REVOQUE"}
    with session() as cnx, pytest.raises(CoffreErreur) as exc:
        coffre.definir(cnx, acteur=admin, nom="google.ads", service="google_ads", valeur=VALEUR_2)
    assert exc.value.code == "COFFRE_SECRET_REVOQUE"  # un nom révoqué n'est jamais réutilisé


def test_journal_d_acces_append_only(session, admin, cle_fichier):
    _definir(session)
    with session() as cnx:
        coffre.rotation(cnx, acteur=admin, nom="google.ads", valeur=VALEUR_2)
        coffre.revoquer(cnx, acteur=admin, nom="google.ads")
        actions = [r["action"] for r in reversed(coffre.journal(cnx, "google.ads"))]
    assert actions == ["definir", "rotation", "revocation"]
    for sql in ("UPDATE coffre_acces SET code='x'", "DELETE FROM coffre_acces"):
        with pytest.raises(DBAPIError, match="journal du coffre immuable"), session() as cnx:
            cnx.execute(text(sql))


def test_refus_administration_journalise_et_conserve(session, admin, cle_fichier):
    with pytest.raises(CoffreErreur) as exc:
        coffre.avec_journal(session, coffre.definir, acteur="employe_fictif", nom="meta.ads", service="meta",
                            valeur=VALEUR)
    assert exc.value.code == "COFFRE_ADMIN_REQUIS"
    with session() as cnx:
        assert coffre.lister(cnx) == []
        [ligne] = coffre.journal(cnx, "meta.ads")
    assert (ligne["resultat"], ligne["code"], ligne["acteur"]) == ("refus", "COFFRE_ADMIN_REQUIS", "employe_fictif")


def test_export_toujours_refuse(session, admin, cle_fichier):
    _definir(session)
    with pytest.raises(CoffreErreur) as exc, session() as cnx:
        coffre.exporter(cnx, acteur=admin, nom="google.ads")
    assert exc.value.code == "COFFRE_EXPORT_INTERDIT"
    assert not hasattr(coffre, "lire_valeur") and not hasattr(coffre, "dechiffrer")


def test_masquage_journaux_et_reponses(session, admin, cle_fichier, caplog):
    _definir(session)
    journal = logging.getLogger("opsys.test.coffre")
    with coffre.utiliser(nom="google.ads", usage="connecteur:google-ads", acteur="opsys-systeme") as valeur, \
            caplog.at_level(logging.INFO, logger="opsys.test.coffre"):
        journal.info("appel avec %s et Bearer %s", valeur, valeur)
        reponse = masquage.masquer({"erreur": f"refus pour {valeur}", "liste": [valeur]})
    assert VALEUR not in caplog.text and masquage.MASQUE in caplog.text
    assert VALEUR not in str(reponse)
    jeton = coffre.PREFIXE_JETON + "B" * 43
    assert masquage.masquer_texte(f"jeton {jeton}") == f"jeton {masquage.MASQUE}"
    assert masquage.masquer_texte("Authorization: Bearer abcdefgh12345678") == f"Authorization: {masquage.MASQUE}"


@pytest.mark.parametrize(("environ", "code"), [
    ({}, "COFFRE_CLE_MAITRESSE_ABSENTE"),
    ({cle_maitresse.ENV_CLE: "trop-courte"}, "COFFRE_CLE_MAITRESSE_INVALIDE"),
    ({cle_maitresse.ENV_CLE: base64.b64encode(b"x" * 32).decode(), cle_maitresse.ENV_FICHIER: "/x"},
     "COFFRE_CLE_CONFLIT"),
    ({cle_maitresse.ENV_FICHIER: "relatif/coffre.cle"}, "COFFRE_FICHIER_CLE_INVALIDE"),
])
def test_cle_maitresse_absente_ou_invalide_refus_explicite(environ, code):
    with pytest.raises(CoffreErreur) as exc:
        cle_maitresse.charger(environ)
    assert exc.value.code == code


def test_cle_absente_aucune_ecriture(session, admin, monkeypatch):
    monkeypatch.delenv(cle_maitresse.ENV_FICHIER, raising=False)
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    with pytest.raises(CoffreErreur) as exc:
        coffre.avec_journal(session, coffre.definir, acteur=admin, nom="google.ads", service="google_ads",
                            valeur=VALEUR)
    assert exc.value.code == "COFFRE_CLE_MAITRESSE_ABSENTE"
    with session() as cnx:
        assert coffre.lister(cnx) == []


def test_fichier_de_cle_permissions_et_depot(tmp_path):
    dossier = tmp_path / "prive"
    dossier.mkdir(mode=0o700)
    chemin = dossier / "coffre.cle"
    cle_maitresse.generer_fichier(chemin)
    assert oct(chemin.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(CoffreErreur) as exc:
        cle_maitresse.generer_fichier(chemin)
    assert exc.value.code == "COFFRE_FICHIER_CLE_EXISTE"
    os.chmod(chemin, 0o644)
    with pytest.raises(CoffreErreur) as exc:
        cle_maitresse.charger({cle_maitresse.ENV_FICHIER: str(chemin)})
    assert exc.value.code == "COFFRE_FICHIER_CLE_PERMISSIONS"
    lien = dossier / "lien.cle"
    lien.symlink_to(chemin)
    with pytest.raises(CoffreErreur) as exc:
        cle_maitresse.charger({cle_maitresse.ENV_FICHIER: str(lien)})
    assert exc.value.code == "COFFRE_FICHIER_CLE_INVALIDE"
    depot = tmp_path / "depot"
    (depot / ".git").mkdir(parents=True)
    with pytest.raises(CoffreErreur) as exc:
        cle_maitresse.generer_fichier(depot / "coffre.cle")
    assert exc.value.code == "COFFRE_CLE_DANS_DEPOT"
    assert "kek" not in repr(cle_maitresse.decoder(base64.b64encode(b"k" * 32).decode()))


def test_autre_cle_maitresse_refusee_puis_rechiffrement(session, admin, cle_fichier, tmp_path, monkeypatch):
    _definir(session)
    dossier = tmp_path / "nouvelle"
    dossier.mkdir(mode=0o700)
    nouvelle = cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    with pytest.raises(CoffreErreur) as exc, coffre.utiliser(nom="google.ads", usage="connecteur:google-ads",
                                                             acteur="opsys-systeme"):
        pass
    assert exc.value.code == "COFFRE_CLE_MAITRESSE_DIFFERENTE"
    with session() as cnx:
        assert coffre.rechiffrer(cnx, acteur=admin, ancienne=cle_fichier[1], nouvelle=nouvelle) == 1
    with coffre.utiliser(nom="google.ads", usage="connecteur:google-ads", acteur="opsys-systeme") as valeur:
        assert valeur == VALEUR


def test_chiffre_deplace_ne_se_dechiffre_pas(session, admin, cle_fichier):
    """AAD : un chiffré recopié sous un autre nom est refusé (aucune valeur rendue)."""
    _definir(session, nom="google.ads")
    _definir(session, nom="meta.ads", valeur=VALEUR_2)
    with session() as cnx:
        source = cnx.execute(select(COFFRE_VERSIONS).where(COFFRE_VERSIONS.c.nom == "google.ads")).mappings().one()
        cnx.execute(COFFRE_VERSIONS.update().where(COFFRE_VERSIONS.c.nom == "meta.ads").values(
            nonce_cle=source["nonce_cle"], cle_enveloppee=source["cle_enveloppee"],
            nonce_valeur=source["nonce_valeur"], valeur_chiffree=source["valeur_chiffree"]))
    with pytest.raises(CoffreErreur) as exc, coffre.utiliser(nom="meta.ads", usage="connecteur:meta-ads",
                                                             acteur="opsys-systeme"):
        pass
    assert exc.value.code == "COFFRE_CHIFFRE_CORROMPU"


def test_migration_0036_descente_sure(tmp_path):
    url = "sqlite:///" + str(tmp_path / "migration.db")
    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0036")
        cnx.execute(COFFRE_ACCES.insert().values(quand="2026-10-31T00:00:00+00:00", nom="fictif", action="export",
                                                 acteur="fictif", resultat="refus", code="COFFRE_EXPORT_INTERDIT"))
        with pytest.raises(RuntimeError, match="rétrogradation refusée"):
            command.downgrade(cfg, "0035")
    with stockage.moteur(url).begin() as cnx:
        assert cnx.execute(text("SELECT count(*) FROM coffre_acces")).scalar_one() == 1
    vide = "sqlite:///" + str(tmp_path / "vide.db")
    with stockage.moteur(vide).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0036")
        command.downgrade(cfg, "0035")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0035"
    noms = {r[0] for r in sqlite3.connect(str(tmp_path / "vide.db")).execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'coffre_%' OR name LIKE 'fournisseurs_%'")}
    assert noms == set()


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_postgresql_coffre_chiffre_append_only_et_descente(monkeypatch, tmp_path):
    from memoire.doubles import postgres_ephemere

    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            assert stockage.moteur(url).dialect.name == "postgresql"
            assert stockage.revision_courante(url) == "0036"
            with stockage.transaction() as cnx:
                identite.creer_personne(cnx, "admin_fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
                coffre.definir(cnx, acteur="admin_fictif", nom="google.ads", service="google_ads", valeur=VALEUR)
            with coffre.utiliser(nom="google.ads", usage="connecteur:google-ads", acteur="opsys-systeme") as valeur:
                assert valeur == VALEUR
            with stockage.transaction() as cnx:
                brut = cnx.execute(text("SELECT valeur_chiffree FROM coffre_versions")).scalar_one()
                assert VALEUR.encode() not in bytes(brut)
            with pytest.raises(DBAPIError, match="journal du coffre immuable"), stockage.transaction() as cnx:
                cnx.execute(text("DELETE FROM coffre_acces"))
            cfg = stockage._config()
            with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
                cfg.attributes["connection"] = cnx
                command.downgrade(cfg, "0035")
        finally:
            stockage.liberer()
