"""Sauvegarde chiffrée (`opsys.sauvegarde_chiffree`) : clé hors de la sauvegarde, refus typés, rien de partiel.

Ce que ces tests prouvent : un aller-retour exact ; une mauvaise clé est reconnue avant tout déchiffrement ; un octet
modifié, une archive tronquée (au milieu ou à une frontière de bloc), des blocs permutés, un format inconnu sont refusés
avec leur code ; la clé mal placée (dans la sauvegarde, dans l'instance), trop ouverte ou absente est refusée ;
un disque plein ne laisse aucun fichier partiel ; la restauration d'une archive refusée ne touche pas à
l'instance ; la rétention met de côté sans jamais supprimer. Toutes les données sont fictives.
"""

from __future__ import annotations

import datetime as dt
import errno
import os
import struct
from pathlib import Path

import pytest

from opsys import exportation, identite, stockage
from opsys import sauvegarde_chiffree as sc

pytest.importorskip("cryptography")


@pytest.fixture
def cle_env(tmp_path, monkeypatch) -> Path:
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    chemin = dossier / "sauvegarde.cle"
    sc.generer_cle(chemin)
    monkeypatch.setenv(sc.ENV_CLE_FICHIER, str(chemin))
    return chemin


def _ecrire(chemin: Path, contenu: bytes) -> Path:
    chemin.write_bytes(contenu)
    return chemin


def _chiffrer(tmp_path: Path, contenu: bytes, nom: str = "x.enc") -> Path:
    source = _ecrire(tmp_path / "clair.bin", contenu)
    destination = tmp_path / nom
    sc.chiffrer_fichier(source, destination, sc.lire_cle())
    return destination


def _code(exc: pytest.ExceptionInfo[sc.ErreurSauvegarde]) -> str:
    return exc.value.code


def test_aller_retour_exact_sur_plusieurs_tailles(tmp_path, cle_env, monkeypatch):
    monkeypatch.setattr(sc, "TAILLE_BLOC", 1024)
    for taille in (0, 1, 1023, 1024, 1025, 4096, 5000):
        contenu = os.urandom(taille)
        chiffre = _chiffrer(tmp_path, contenu, f"t{taille}.enc")
        sortie = tmp_path / f"t{taille}.clair"
        resultat = sc.dechiffrer_fichier(chiffre, sortie, sc.lire_cle())
        assert sortie.read_bytes() == contenu
        assert resultat["octets_clairs"] == taille


def test_le_chiffre_ne_contient_pas_le_clair_et_le_fichier_est_prive(tmp_path, cle_env):
    marqueur = b"MARQUEUR-FICTIF-EN-CLAIR-0123456789"
    chiffre = _chiffrer(tmp_path, marqueur * 100)
    assert marqueur not in chiffre.read_bytes()
    assert (chiffre.stat().st_mode & 0o777) == 0o600
    assert not list(tmp_path.glob("*.partiel"))


def test_mauvaise_cle_est_reconnue_avant_tout_dechiffrement(tmp_path, cle_env, monkeypatch):
    chiffre = _chiffrer(tmp_path, b"donnees fictives")
    autre = cle_env.parent / "autre.cle"
    sc.generer_cle(autre)
    monkeypatch.setenv(sc.ENV_CLE_FICHIER, str(autre))
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.verifier(chiffre)
    assert _code(exc) == "REJ-SAUVEGARDE-MAUVAISE-CLE"
    assert sc.CODES_SORTIE[_code(exc)] == 14
    with pytest.raises(sc.ErreurSauvegarde):
        sc.dechiffrer_fichier(chiffre, tmp_path / "sortie.clair", sc.lire_cle())
    assert not (tmp_path / "sortie.clair").exists() and not list(tmp_path.glob("*.partiel"))


@pytest.mark.parametrize("position", ["entete_sel", "milieu", "etiquette"])
def test_un_octet_modifie_est_refuse_et_rien_n_est_ecrit(tmp_path, cle_env, position, monkeypatch):
    monkeypatch.setattr(sc, "TAILLE_BLOC", 1024)
    chiffre = _chiffrer(tmp_path, os.urandom(3000))
    brut = bytearray(chiffre.read_bytes())
    index = {"entete_sel": sc._TAILLE_ENTETE - 1, "milieu": 200, "etiquette": len(brut) - 1}[position]
    brut[index] ^= 0x01
    chiffre.write_bytes(bytes(brut))
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.dechiffrer_fichier(chiffre, tmp_path / "sortie.clair", sc.lire_cle())
    assert _code(exc) == "REJ-SAUVEGARDE-ALTEREE"
    assert not (tmp_path / "sortie.clair").exists() and not list(tmp_path.glob("*.partiel"))


def test_archive_tronquee_au_milieu_ou_a_une_frontiere_de_bloc(tmp_path, cle_env, monkeypatch):
    monkeypatch.setattr(sc, "TAILLE_BLOC", 1024)
    chiffre = _chiffrer(tmp_path, os.urandom(3000))
    brut = chiffre.read_bytes()
    # frontière exacte : l'en-tête + le premier bloc complet seulement (le drapeau « dernier bloc » manque)
    (taille,) = struct.unpack(">I", brut[sc._TAILLE_ENTETE: sc._TAILLE_ENTETE + 4])
    frontiere = sc._TAILLE_ENTETE + 4 + taille
    for coupe, attendu in ((frontiere, "REJ-SAUVEGARDE-TRONQUEE"), (frontiere + 10, "REJ-SAUVEGARDE-TRONQUEE"),
                           (len(brut) - 1, "REJ-SAUVEGARDE-TRONQUEE"), (20, "REJ-SAUVEGARDE-TRONQUEE")):
        _ecrire(tmp_path / "coupe.enc", brut[:coupe])
        with pytest.raises(sc.ErreurSauvegarde) as exc:
            sc.verifier(tmp_path / "coupe.enc")
        assert _code(exc) == attendu, coupe


def test_blocs_permutes_ou_octets_ajoutes_sont_refuses(tmp_path, cle_env, monkeypatch):
    monkeypatch.setattr(sc, "TAILLE_BLOC", 1024)
    chiffre = _chiffrer(tmp_path, os.urandom(3500))
    brut = chiffre.read_bytes()
    entete, reste = brut[: sc._TAILLE_ENTETE], brut[sc._TAILLE_ENTETE:]
    blocs = []
    while reste:
        (n,) = struct.unpack(">I", reste[:4])
        blocs.append(reste[: 4 + n])
        reste = reste[4 + n:]
    assert len(blocs) == 4
    _ecrire(tmp_path / "perm.enc", entete + blocs[1] + blocs[0] + blocs[2] + blocs[3])
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.verifier(tmp_path / "perm.enc")
    assert _code(exc) == "REJ-SAUVEGARDE-ALTEREE"
    _ecrire(tmp_path / "ajout.enc", brut + b"\x00")
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.verifier(tmp_path / "ajout.enc")
    assert _code(exc) in {"REJ-SAUVEGARDE-ALTEREE", "REJ-SAUVEGARDE-TRONQUEE"}


def test_format_inconnu_et_version_future(tmp_path, cle_env):
    _ecrire(tmp_path / "pas.enc", b"ceci n'est pas une sauvegarde" * 5)
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.verifier(tmp_path / "pas.enc")
    assert _code(exc) == "REJ-SAUVEGARDE-FORMAT"
    brut = bytearray(_chiffrer(tmp_path, b"abc").read_bytes())
    brut[len(sc.MAGIC)] = 99
    _ecrire(tmp_path / "future.enc", bytes(brut))
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.verifier(tmp_path / "future.enc")
    assert _code(exc) == "REJ-SAUVEGARDE-VERSION-FORMAT"


def test_cle_absente_trop_ouverte_invalide_ou_lien(tmp_path, monkeypatch, cle_env):
    monkeypatch.delenv(sc.ENV_CLE_FICHIER)
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.lire_cle()
    assert _code(exc) == "REJ-SAUVEGARDE-CLE-ABSENTE"
    monkeypatch.setenv(sc.ENV_CLE_FICHIER, str(cle_env))
    cle_env.chmod(0o640)
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.lire_cle()
    assert _code(exc) == "REJ-SAUVEGARDE-CLE-PERMISSIONS"
    cle_env.chmod(0o600)
    cle_env.write_text("pas-du-base64-valide\n")
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.lire_cle()
    assert _code(exc) == "REJ-SAUVEGARDE-CLE-INVALIDE"
    lien = cle_env.parent / "lien.cle"
    lien.symlink_to(cle_env)
    monkeypatch.setenv(sc.ENV_CLE_FICHIER, str(lien))
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.lire_cle()
    assert _code(exc) == "REJ-SAUVEGARDE-CLE-INVALIDE"
    with pytest.raises(sc.ErreurSauvegarde):
        sc.generer_cle(cle_env)  # jamais d'écrasement


def test_disque_plein_ne_laisse_aucun_fichier_partiel(tmp_path, cle_env, monkeypatch):
    source = _ecrire(tmp_path / "clair.bin", os.urandom(5000))

    def plein(*_args, **_kw):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", plein)
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.chiffrer_fichier(source, tmp_path / "x.enc", sc.lire_cle())
    assert _code(exc) == "REJ-SAUVEGARDE-DISQUE-PLEIN"
    assert not (tmp_path / "x.enc").exists() and not list(tmp_path.glob("*.partiel"))


def test_la_cle_ne_peut_pas_vivre_dans_la_sauvegarde_ni_dans_l_instance(tmp_path, opsys_home, monkeypatch):
    dossier = tmp_path / "sauvegardes"
    dossier.mkdir()
    for lieu in (dossier, opsys_home):
        lieu.mkdir(exist_ok=True)
        os.chmod(lieu, 0o700)
        chemin = lieu / "sauvegarde.cle"
        sc.generer_cle(chemin)
        monkeypatch.setenv(sc.ENV_CLE_FICHIER, str(chemin))
        with pytest.raises(sc.ErreurSauvegarde) as exc:
            sc.sauvegarder(opsys_home, dossier, par="test")
        assert _code(exc) == "REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE"
        with pytest.raises(sc.ErreurSauvegarde) as exc:
            sc.restaurer(dossier / "inexistante.enc", opsys_home, par="test")
        assert _code(exc) == "REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE"


def _instance_peuplee(home: Path) -> None:
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "sylvie-fictif", "Sylvie Tremblay (fictif)", "un-mot-de-passe-solide-123",
                                ["employee"])
    (home / "paliers.yaml").write_text("paliers: {standard: {provider: anthropic, model: claude-sonnet-5}}\n",
                                       encoding="utf-8")


def _personnes() -> list[str]:
    with stockage.transaction() as cnx:
        return [p.identifiant for p in identite.lister(cnx)]


def test_sauvegarde_restauration_et_refus_sans_toucher_a_l_instance(tmp_path, opsys_home, cle_env, monkeypatch):
    _instance_peuplee(opsys_home)
    dossier = tmp_path / "sauvegardes"
    decrit = sc.sauvegarder(opsys_home, dossier, par="test")
    archive = Path(str(decrit["chemin"]))
    assert decrit["verifiee"] is True and archive.name.endswith(".tar.gz.enc")
    assert b"sylvie" not in archive.read_bytes()  # chiffré : aucune donnée lisible
    assert not [p for p in dossier.iterdir() if p.name.startswith("opsys-sauvegarde-") and p.is_dir()]  # temp retiré

    # une archive altérée est refusée AVANT toute écriture : l'instance courante reste intacte
    corrompue = dossier / "corrompue.tar.gz.enc"
    brut = bytearray(archive.read_bytes())
    brut[len(brut) // 2] ^= 0xFF
    corrompue.write_bytes(bytes(brut))
    avant = (opsys_home / "opsys.db").read_bytes()
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.restaurer(corrompue, opsys_home, par="test", remplacer=True)
    assert _code(exc) == "REJ-SAUVEGARDE-ALTEREE"
    assert (opsys_home / "opsys.db").read_bytes() == avant and _personnes() == ["sylvie-fictif"]

    # sur une instance neuve : la restauration retrouve les données ; sur une instance non vide sans --remplacer : refus
    stockage.liberer()
    neuve = tmp_path / "neuve"
    monkeypatch.setenv("OPSYS_HOME", str(neuve))
    sc.restaurer(archive, neuve, par="test")
    assert _personnes() == ["sylvie-fictif"]
    stockage.liberer()
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.restaurer(archive, neuve, par="test")
    assert _code(exc) == "REJ-SAUVEGARDE-RESTAURATION" and "rien n'est écrasé" in exc.value.message


def test_base_corrompue_et_version_plus_recente_ont_leur_code(tmp_path, opsys_home, cle_env, monkeypatch):
    _instance_peuplee(opsys_home)
    base = opsys_home / "opsys.db"
    # revision inconnue de ce logiciel (archive d'une version plus récente)
    import sqlite3

    connexion = sqlite3.connect(base)
    connexion.execute("UPDATE alembic_version SET version_num = '9999'")
    connexion.commit()
    connexion.close()
    stockage.liberer()
    decrit = sc.sauvegarder(opsys_home, tmp_path / "s", par="test")
    neuve = tmp_path / "neuve"
    monkeypatch.setenv("OPSYS_HOME", str(neuve))
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.restaurer(Path(str(decrit["chemin"])), neuve, par="test")
    assert _code(exc) == "REJ-SAUVEGARDE-VERSION-LOGICIEL"
    assert not (neuve / "opsys.db").exists()


def test_export_d_une_base_corrompue_est_refuse_avec_son_code(tmp_path, opsys_home, cle_env):
    _instance_peuplee(opsys_home)
    stockage.liberer()
    base = opsys_home / "opsys.db"
    octets = bytearray(base.read_bytes())
    for i in range(8192, min(len(octets), 8192 + 4096)):
        octets[i] = 0xAB
    base.write_bytes(bytes(octets))
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.sauvegarder(opsys_home, tmp_path / "s", par="test")
    assert _code(exc) in {"REJ-SAUVEGARDE-BASE-CORROMPUE", "REJ-SAUVEGARDE-EXPORT"}
    assert not list((tmp_path / "s").glob("*.enc"))


def test_exportation_type_ses_refus():
    erreur = exportation.ErreurExportation("x", code="REJ-EXPORT-EMPREINTE")
    assert erreur.code == "REJ-EXPORT-EMPREINTE" and exportation.ErreurExportation("y").code is None


def test_retention_met_de_cote_sans_jamais_supprimer(tmp_path):
    dossier = tmp_path / "s"
    dossier.mkdir()
    maintenant = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
    noms = []
    for jours in (0, 1, 5, 40, 60, 90):
        date = (maintenant - dt.timedelta(days=jours)).strftime("%Y%m%dT%H%M%SZ")
        nom = f"opsys-sauvegarde-{date}-abcd.tar.gz.enc"
        (dossier / nom).write_bytes(b"x")
        (dossier / (nom + ".meta.json")).write_text("{}")
        noms.append(nom)
    (dossier / "autre-fichier.txt").write_text("pas une sauvegarde")
    plan = sc.plan_retention(dossier, garder=2, jours=30, maintenant=maintenant)
    assert plan["gardees"] == noms[:3]  # 2 plus récentes + celle de 5 jours (< 30 j)
    assert plan["a_mettre_de_cote"] == noms[3:]
    assert len(list(dossier.glob("*.enc"))) == 6  # le plan seul ne bouge rien
    resultat = sc.appliquer_retention(dossier, garder=2, jours=30, maintenant=maintenant)
    assert sorted(resultat["mises_de_cote"]) == sorted(noms[3:])
    assert len(list((dossier / sc.DOSSIER_A_DETRUIRE).glob("*.enc"))) == 3  # déplacées, pas supprimées
    assert (dossier / "autre-fichier.txt").exists()
    with pytest.raises(sc.ErreurSauvegarde) as exc:
        sc.plan_retention(dossier, garder=0, jours=30)
    assert _code(exc) == "REJ-SAUVEGARDE-RETENTION"


def test_la_base_de_l_instance_n_est_lisible_que_par_son_proprietaire(tmp_path, opsys_home):
    """Relevé par la qualification en conteneur : opsys.db, -wal et -shm naissaient en 0644 (umask 022)."""
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "sylvie-fictif", "Sylvie Tremblay (fictif)", "un-mot-de-passe-solide-123",
                                ["employee"])
    for nom in ("opsys.db", "opsys.db-wal"):
        chemin = opsys_home / nom
        if chemin.exists():
            assert (chemin.stat().st_mode & 0o077) == 0, f"{nom} : {oct(chemin.stat().st_mode & 0o777)}"
    # une base préexistante en 0644 est resserrée à la prochaine connexion, jamais élargie
    stockage.liberer()
    (opsys_home / "opsys.db").chmod(0o644)
    with stockage.transaction() as cnx:
        assert cnx is not None
    assert ((opsys_home / "opsys.db").stat().st_mode & 0o777) == 0o600
