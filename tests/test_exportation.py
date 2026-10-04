"""Export et restauration de l'instance locale (PLAN T0.11) : `opsys.exportation`,
`opsys-metier instance exporter|restaurer`.

Ce que ces tests prouvent : l'archive ne contient que la liste blanche (jamais le `.env`), la copie de la base est
cohérente même avec un journal WAL non recopié dans le fichier, l'empreinte est exigée, une archive altérée ou
piégée est refusée AVANT toute écriture, et rien n'est écrasé ni supprimé sans `--remplacer` (les fichiers actuels
sont alors mis de côté).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

from opsys import cli, exportation, identite, instance, stockage

FICTIF = True  # personnes et secrets ci-dessous sont fictifs (AGENTS.md)

MARQUEUR_SECRET = "MARQUEUR-SECRET-DU-ENV-FICTIF-0123456789"
MOT_DE_PASSE = "un-mot-de-passe-solide-123"


@pytest.fixture(autouse=True)
def hote(tmp_path, monkeypatch) -> Path:
    """Le dossier personnel du poste fictif, où vit l'état du core (`~/.opsys/core`, PLAN T0.11-b et T0.7 lot 3)."""
    dossier = tmp_path / "hote"
    monkeypatch.setenv("HOME", str(dossier))
    return dossier


def _etat_core() -> Path:
    return Path(os.environ["HOME"]) / ".opsys" / "core"


def _etat_d_avant_le_lot_3() -> Path:
    return Path(os.environ["HOME"]) / ".openclaw-opsys"


def _peupler(home: Path) -> None:
    """Une instance : base migrée avec une personne, réglages de l'instance, et trois endroits qui portent un secret :
    l'état du core (`~/.opsys/core`, dossier du profil `opsys`), son emplacement d'avant T0.7 lot 3
    (`~/.openclaw-opsys`) et `home/core` (avant T0.11-b ; ailleurs que dans `~/.opsys`, c'est un ancien état)."""
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "sylvie-fictif", "Sylvie Tremblay (fictif)", MOT_DE_PASSE, ["employee"])
    (home / "paliers.yaml").write_text("paliers: {standard: {provider: anthropic, model: claude-sonnet-5}}\n",
                                       encoding="utf-8")
    (home / "core").mkdir(exist_ok=True)
    (home / "core" / ".env").write_text(f"OPSYS_MCP_JETON={MARQUEUR_SECRET}\n", encoding="utf-8")
    (home / "core" / "etat-du-gateway.json").write_text(f'{{"jeton": "{MARQUEUR_SECRET}"}}', encoding="utf-8")
    _etat_core().mkdir(parents=True, exist_ok=True)
    (_etat_core() / ".env").write_text(f"OPSYS_MCP_JETON={MARQUEUR_SECRET}\n", encoding="utf-8")
    (_etat_core() / "etat-du-gateway.json").write_text(f'{{"jeton": "{MARQUEUR_SECRET}"}}', encoding="utf-8")
    _etat_d_avant_le_lot_3().mkdir(parents=True, exist_ok=True)
    (_etat_d_avant_le_lot_3() / ".env").write_text(f"OPSYS_MCP_JETON={MARQUEUR_SECRET}\n", encoding="utf-8")


def _personnes() -> list[str]:
    with stockage.transaction() as cnx:
        return [p.identifiant for p in identite.lister(cnx)]


def _autre_instance(monkeypatch, tmp_path: Path, nom: str) -> Path:
    stockage.liberer()
    home = tmp_path / nom
    monkeypatch.setenv("OPSYS_HOME", str(home))
    return home


def _membres(archive: Path) -> dict[str, bytes]:
    with tarfile.open(archive, "r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}  # type: ignore[union-attr]


def _archive_sur_mesure(dest: Path, base: bytes, *, revision: str = "0008", extras: dict[str, bytes] | None = None,
                        symlink: bool = False) -> Path:
    """Une archive au bon format, avec une base et un manifeste fournis : pour les refus. Écrit aussi `.sha256`."""
    manifeste = {"format": exportation.FORMAT, "base": {"moteur": "sqlite", "revision": revision},
                 "fichiers": [{"chemin": "opsys.db", "sha256": hashlib.sha256(base).hexdigest(), "octets": len(base)}]}
    membres = {"manifeste.json": json.dumps(manifeste).encode(), "opsys.db": base, **(extras or {})}
    with tarfile.open(dest, "w:gz") as tar:
        for nom, contenu in membres.items():
            info = tarfile.TarInfo(nom if nom.startswith(("..", "/")) else f"opsys-export/{nom}")
            info.size = len(contenu)
            tar.addfile(info, io.BytesIO(contenu))
        if symlink:
            lien = tarfile.TarInfo("opsys-export/paliers.yaml")
            lien.type, lien.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(lien)
    dest.with_name(dest.name + ".sha256").write_text(
        f"{hashlib.sha256(dest.read_bytes()).hexdigest()}  {dest.name}\n", encoding="utf-8")
    return dest


def _base_valide(tmp_path: Path) -> bytes:
    chemin = tmp_path / "modele.db"
    connexion = sqlite3.connect(chemin)
    connexion.execute("CREATE TABLE alembic_version (version_num TEXT)")
    connexion.commit()
    connexion.close()
    return chemin.read_bytes()


# -- export ------------------------------------------------------------------------------------------------------------
def test_l_archive_ne_contient_que_la_liste_blanche_et_jamais_un_secret(opsys_home, tmp_path):
    _peupler(opsys_home)

    resultat = exportation.exporter(opsys_home, tmp_path / "sortie" / "export.tar.gz", par="test")

    membres = _membres(resultat.archive)
    assert sorted(membres) == ["opsys-export/manifeste.json", "opsys-export/opsys.db", "opsys-export/paliers.yaml"]
    assert all(MARQUEUR_SECRET.encode() not in contenu for contenu in membres.values())
    manifeste = json.loads(membres["opsys-export/manifeste.json"])
    assert manifeste["format"] == exportation.FORMAT and manifeste["base"]["moteur"] == "sqlite"
    assert {e["chemin"] for e in manifeste["exclus"]} >= {
        "~/.opsys/core/.env", "~/.opsys/core/", "~/.openclaw-opsys/"}
    assert os.environ["HOME"] not in json.dumps(manifeste)  # aucun nom de compte du poste dans l'archive
    assert any("clés de chiffrement" in ligne for ligne in manifeste["avertissements"])
    for f in manifeste["fichiers"]:
        contenu = membres[f"opsys-export/{f['chemin']}"]
        assert (f["sha256"], f["octets"]) == (hashlib.sha256(contenu).hexdigest(), len(contenu))


def test_les_exclusions_nomment_le_dossier_du_profil_du_core_et_jamais_un_secret_n_en_sort(opsys_home, tmp_path):
    _peupler(opsys_home)
    etat = f"{instance.DOSSIER_INSTANCE}/{instance.SOUS_DOSSIER_CORE}"
    ancien = instance.ANCIEN_DOSSIER_PROFIL

    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    assert [e["chemin"] for e in exportation.EXCLUS] == [f"~/{etat}/.env", f"~/{etat}/", f"~/{ancien}/", "rqa/"]
    for nom, contenu in _membres(resultat.archive).items():
        assert MARQUEUR_SECRET.encode() not in contenu, nom
        assert b"etat-du-gateway" not in contenu, nom
    assert resultat.en_json()["exclus"] == [dict(e) for e in exportation.EXCLUS]


def test_archive_et_empreinte_sont_privees_et_l_empreinte_sha256_se_verifie(
        opsys_home, tmp_path, verifier_acces_prive):
    _peupler(opsys_home)

    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    verifier_acces_prive(resultat.archive, mode=0o600)
    verifier_acces_prive(resultat.empreinte, mode=0o600)
    assert resultat.empreinte.read_text(encoding="utf-8") == f"{resultat.sha256}  export.tar.gz\n"
    assert resultat.sha256 == hashlib.sha256(resultat.archive.read_bytes()).hexdigest()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".opsys-export-")]  # aucun résidu


def _faux_powershell_acl(monkeypatch, *, code: int = 0, erreur: str = "") -> list[tuple[list[str], dict[str, str]]]:
    """Enregistre les appels de protection ; ce double ne qualifie pas les ACL Windows natives."""
    appels: list[tuple[list[str], dict[str, str]]] = []

    def faux(commande, **options):
        appels.append((list(commande), options["env"]))
        return subprocess.CompletedProcess(commande, code, "", erreur)

    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.shutil, "which", lambda executable: "powershell.exe")
    monkeypatch.setattr(instance.subprocess, "run", faux)
    return appels


def test_sous_windows_l_archive_et_son_empreinte_ont_une_acl_reduite_a_l_utilisateur(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    appels = _faux_powershell_acl(monkeypatch)

    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    # une fois pour l'archive (avant sa première donnée), une fois pour son empreinte : jamais lisibles par un autre
    # compte
    assert [env["OPSYS_INSTANCE_ACL_PATH"] for _, env in appels] == [str(resultat.archive), str(resultat.empreinte)]
    assert [env["OPSYS_INSTANCE_ACL_DIRECTORY"] for _, env in appels] == ["0", "0"]
    assert all(cmd == ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                       instance._SCRIPT_ACL_WINDOWS] for cmd, _ in appels)
    assert resultat.sha256 == hashlib.sha256(resultat.archive.read_bytes()).hexdigest()


def test_sous_windows_un_refus_d_acl_arrete_l_export_sans_laisser_de_fichier(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    _faux_powershell_acl(monkeypatch, code=5, erreur="Access is denied.")

    with pytest.raises(instance.ErreurInstance, match="PowerShell a refusé de restreindre l'accès"):
        exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    assert not (tmp_path / "export.tar.gz").exists() and not (tmp_path / "export.tar.gz.sha256").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".opsys-export-")]  # ni archive, ni résidu


@pytest.mark.parametrize("erreur", [PermissionError("refus fictif"), subprocess.TimeoutExpired("powershell", 30)])
def test_sous_windows_une_protection_inexecutable_ou_expiree_ne_laisse_aucun_export(
        opsys_home, tmp_path, monkeypatch, erreur):
    _peupler(opsys_home)
    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.shutil, "which", lambda executable: "powershell.exe")

    def echec(commande, **options):
        raise erreur

    monkeypatch.setattr(instance.subprocess, "run", echec)
    with pytest.raises(instance.ErreurInstance, match="PowerShell n'a pas pu restreindre l'accès"):
        exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    assert not (tmp_path / "export.tar.gz").exists() and not (tmp_path / "export.tar.gz.sha256").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".opsys-export-")]


def test_la_copie_est_coherente_meme_quand_les_ecritures_sont_dans_le_journal_wal(opsys_home, tmp_path):
    _peupler(opsys_home)
    wal = opsys_home / "opsys.db-wal"
    assert wal.is_file() and wal.stat().st_size > 0  # précondition : une copie du seul fichier .db perdrait ces lignes

    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    copie = tmp_path / "copie.db"
    copie.write_bytes(_membres(resultat.archive)["opsys-export/opsys.db"])
    lignes = sqlite3.connect(copie).execute("SELECT identifiant FROM personnes").fetchall()
    assert lignes == [("sylvie-fictif",)]
    assert sqlite3.connect(copie).execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_l_export_est_inscrit_au_journal_d_audit_avec_l_empreinte(opsys_home, tmp_path):
    _peupler(opsys_home)

    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="poste:administrateur")

    from opsys import etat

    with etat.session() as cnx:
        entrees = [e for e in etat.lire_journal(cnx) if e["action"] == "instance.export"]
    assert len(entrees) == 1
    assert entrees[0]["par"] == "poste:administrateur" and entrees[0]["cible"] == "export.tar.gz"
    assert entrees[0]["details"]["sha256"] == resultat.sha256


def test_un_export_n_ecrase_jamais_un_fichier(opsys_home, tmp_path):
    _peupler(opsys_home)
    sortie = tmp_path / "export.tar.gz"
    exportation.exporter(opsys_home, sortie, par="test")
    octets = sortie.read_bytes()

    with pytest.raises(exportation.ErreurExportation, match="existe déjà"):
        exportation.exporter(opsys_home, sortie, par="test")

    assert sortie.read_bytes() == octets


def test_sans_base_ou_avec_une_base_non_migree_l_export_est_refuse(opsys_home, tmp_path):
    with pytest.raises(exportation.ErreurExportation, match="aucune base"):
        exportation.exporter(opsys_home, tmp_path / "a.tar.gz", par="test")
    assert not (tmp_path / "a.tar.gz").exists()

    opsys_home.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(opsys_home / "opsys.db").close()
    with pytest.raises(exportation.ErreurExportation, match="pas migrée"):
        exportation.exporter(opsys_home, tmp_path / "b.tar.gz", par="test")
    assert not (tmp_path / "b.tar.gz").exists() and not (tmp_path / "b.tar.gz.sha256").exists()


def test_postgresql_est_refuse_avec_la_voie_docker_et_sans_le_mot_de_passe(opsys_home, tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_BASE_URL", "postgresql+psycopg://opsys:mot-de-passe-pg-fictif@hote/opsys")

    with pytest.raises(exportation.ErreurExportation) as refus:
        exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")

    assert "deploy/backup.sh" in str(refus.value) and "mot-de-passe-pg-fictif" not in str(refus.value)


# -- restauration ------------------------------------------------------------------------------------------------------
def test_restaurer_dans_une_instance_neuve_redonne_les_donnees(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")
    neuve = _autre_instance(monkeypatch, tmp_path, "neuve")

    restauration = exportation.restaurer(resultat.archive, neuve, par="poste:admin")

    assert restauration.restaures == ("opsys.db", "paliers.yaml") and restauration.mis_de_cote == ()
    assert _personnes() == ["sylvie-fictif"]
    assert (neuve / "paliers.yaml").read_text(encoding="utf-8").startswith("paliers:")
    assert not (neuve / "core").exists()  # ni `.env` ni état du Gateway : l'installateur les régénère
    assert (_etat_core() / ".env").read_text(encoding="utf-8") == f"OPSYS_MCP_JETON={MARQUEUR_SECRET}\n"  # intact
    from opsys import etat

    with etat.session() as cnx:
        actions = [e["action"] for e in etat.lire_journal(cnx)]
    # l'export est inscrit dans l'instance d'origine APRÈS l'archive : l'archive ne porte pas sa propre entrée
    assert actions == ["instance.restauration"]


def test_restaurer_sur_une_instance_existante_exige_remplacer_puis_met_de_cote(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    archive = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test").archive
    autre = _autre_instance(monkeypatch, tmp_path, "autre")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc-fictif", "Marc (fictif)", MOT_DE_PASSE, ["employee"])
    actuel = (autre / "opsys.db").read_bytes()

    with pytest.raises(exportation.ErreurExportation, match="--remplacer"):
        exportation.restaurer(archive, autre, par="test")
    assert _personnes() == ["marc-fictif"]  # rien n'a bougé

    restauration = exportation.restaurer(archive, autre, par="test", remplacer=True)

    assert _personnes() == ["sylvie-fictif"]
    assert len(restauration.mis_de_cote) >= 1
    ecartes = [Path(p) for p in restauration.mis_de_cote if Path(p).name.startswith("opsys.db.avant-restauration-")]
    assert len(ecartes) == 1 and ecartes[0].is_file()
    copie = tmp_path / "ancienne.db"
    copie.write_bytes(ecartes[0].read_bytes())
    assert sqlite3.connect(copie).execute("SELECT identifiant FROM personnes").fetchall() == [("marc-fictif",)]
    assert actuel  # la base d'avant existait bel et bien


def test_une_archive_sans_empreinte_n_est_jamais_restauree(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")
    resultat.empreinte.unlink()
    neuve = _autre_instance(monkeypatch, tmp_path, "neuve")

    with pytest.raises(exportation.ErreurExportation, match="aucune empreinte"):
        exportation.restaurer(resultat.archive, neuve, par="test")
    assert not (neuve / "opsys.db").exists()

    exportation.restaurer(resultat.archive, neuve, par="test", empreinte=resultat.sha256.upper())  # explicite : ok
    assert _personnes() == ["sylvie-fictif"]


def test_une_archive_alteree_est_refusee_avant_toute_ecriture(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    resultat = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test")
    octets = bytearray(resultat.archive.read_bytes())
    octets[len(octets) // 2] ^= 0xFF
    resultat.archive.write_bytes(bytes(octets))
    neuve = _autre_instance(monkeypatch, tmp_path, "neuve")

    with pytest.raises(exportation.ErreurExportation, match="empreinte"):
        exportation.restaurer(resultat.archive, neuve, par="test")

    assert not (neuve / "opsys.db").exists()


def test_un_membre_hors_liste_blanche_ou_un_lien_est_refuse(opsys_home, tmp_path, monkeypatch):
    base = _base_valide(tmp_path)
    neuve = _autre_instance(monkeypatch, tmp_path, "neuve")
    piege = _archive_sur_mesure(tmp_path / "piege.tar.gz", base, extras={"../evasion.txt": b"x"})
    lien = _archive_sur_mesure(tmp_path / "lien.tar.gz", base, symlink=True)
    ajout = _archive_sur_mesure(tmp_path / "ajout.tar.gz", base, extras={"core/.env": b"OPSYS_MCP_JETON=x"})

    for archive in (piege, lien, ajout):
        with pytest.raises(exportation.ErreurExportation, match="membre inattendu"):
            exportation.restaurer(archive, neuve, par="test")

    assert not (tmp_path / "evasion.txt").exists() and not (neuve / "opsys.db").exists()


def test_une_base_illisible_ou_d_une_version_plus_recente_est_refusee(opsys_home, tmp_path, monkeypatch):
    neuve = _autre_instance(monkeypatch, tmp_path, "neuve")
    illisible = _archive_sur_mesure(tmp_path / "illisible.tar.gz", b"ceci n'est pas une base SQLite" * 50)
    future = _archive_sur_mesure(tmp_path / "future.tar.gz", _base_valide(tmp_path), revision="9999")

    with pytest.raises(exportation.ErreurExportation, match="illisible|integrity_check"):
        exportation.restaurer(illisible, neuve, par="test")
    with pytest.raises(exportation.ErreurExportation, match="version plus récente"):
        exportation.restaurer(future, neuve, par="test")

    assert not (neuve / "opsys.db").exists()


def test_un_manifeste_qui_ment_est_refuse(opsys_home, tmp_path, monkeypatch):
    base = _base_valide(tmp_path)
    archive = tmp_path / "menteuse.tar.gz"
    manifeste = {"format": exportation.FORMAT, "base": {"moteur": "sqlite", "revision": "0008"},
                 "fichiers": [{"chemin": "opsys.db", "sha256": "0" * 64, "octets": len(base)}]}
    with tarfile.open(archive, "w:gz") as tar:
        for nom, contenu in {"manifeste.json": json.dumps(manifeste).encode(), "opsys.db": base}.items():
            info = tarfile.TarInfo(f"opsys-export/{nom}")
            info.size = len(contenu)
            tar.addfile(info, io.BytesIO(contenu))
    archive.with_name(archive.name + ".sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
    neuve = _autre_instance(monkeypatch, tmp_path, "neuve")

    with pytest.raises(exportation.ErreurExportation, match="SHA-256 du manifeste"):
        exportation.restaurer(archive, neuve, par="test")


# -- la CLI ------------------------------------------------------------------------------------------------------------
def test_la_cli_exporte_puis_restaure(opsys_home, tmp_path, monkeypatch, capsys):
    _peupler(opsys_home)
    sortie = tmp_path / "cli.tar.gz"

    assert cli.main(["instance", "exporter", "--sortie", str(sortie), "--par", "poste:test"]) == 0
    export = json.loads(capsys.readouterr().out)
    assert export["sha256"] == hashlib.sha256(sortie.read_bytes()).hexdigest()
    assert export["avertissements"] and {e["chemin"] for e in export["exclus"]} >= {"~/.opsys/core/.env"}

    _autre_instance(monkeypatch, tmp_path, "neuve")
    assert cli.main(["instance", "restaurer", str(sortie)]) == 0
    assert json.loads(capsys.readouterr().out)["restaures"] == ["opsys.db", "paliers.yaml"]
    assert _personnes() == ["sylvie-fictif"]


def test_la_cli_refuse_sans_archive_et_traduit_un_refus_en_code_1(opsys_home, tmp_path, capsys):
    assert cli.main(["instance", "restaurer"]) == 2
    assert "archive requise" in capsys.readouterr().err

    assert cli.main(["instance", "exporter", "--sortie", str(tmp_path / "x.tar.gz")]) == 1
    assert "ERREUR : aucune base à exporter" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir() if p.name != "opsys-home"] == []  # ni archive ni résidu


@pytest.mark.parametrize("revisions", [("9999",), ("0008", "0007"), ()])
def test_revision_sqlite_differente_du_manifeste_refuse_avant_toucher_instance(
        opsys_home, tmp_path, monkeypatch, revisions):
    base = tmp_path / "base-incoherente.db"
    connexion = sqlite3.connect(base)
    connexion.execute("CREATE TABLE alembic_version (version_num TEXT)")
    connexion.executemany("INSERT INTO alembic_version VALUES (?)", [(rev,) for rev in revisions])
    connexion.commit()
    connexion.close()
    archive = _archive_sur_mesure(tmp_path / "revision-incoherente.tar.gz", base.read_bytes(), revision="0008")
    cible = _autre_instance(monkeypatch, tmp_path, "cible")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "ancienne-fictive", "Ancienne", MOT_DE_PASSE, ["employee"])
    ancienne_base = (cible / "opsys.db").read_bytes()

    with pytest.raises(exportation.ErreurExportation, match="ne correspond pas"):
        exportation.restaurer(archive, cible, par="test", remplacer=True)

    assert (cible / "opsys.db").read_bytes() == ancienne_base
    assert _personnes() == ["ancienne-fictive"]


def test_echec_pose_deuxieme_fichier_retablit_base_et_reglages(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    archive = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test").archive
    cible = _autre_instance(monkeypatch, tmp_path, "cible")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "ancienne-fictive", "Ancienne", MOT_DE_PASSE, ["employee"])
    (cible / "paliers.yaml").write_text("generation: ancienne\n", encoding="utf-8")
    remplacer = os.replace

    def echec_de_pose(source, destination):
        if Path(source).name == "paliers.yaml" and Path(destination) == cible / "paliers.yaml":
            raise OSError("panne de pose déterministe")
        return remplacer(source, destination)

    monkeypatch.setattr(exportation.os, "replace", echec_de_pose)
    with pytest.raises(OSError, match="panne de pose déterministe"):
        exportation.restaurer(archive, cible, par="test", remplacer=True)

    stockage.liberer()
    assert (cible / "paliers.yaml").read_text(encoding="utf-8") == "generation: ancienne\n"
    monkeypatch.setenv("OPSYS_HOME", str(cible))
    assert _personnes() == ["ancienne-fictive"]
    assert not list(cible.glob("*.avant-restauration-*"))


def test_echec_migration_copie_ne_bascule_aucun_fichier(opsys_home, tmp_path, monkeypatch):
    _peupler(opsys_home)
    archive = exportation.exporter(opsys_home, tmp_path / "export.tar.gz", par="test").archive
    cible = _autre_instance(monkeypatch, tmp_path, "cible")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "ancienne-fictive", "Ancienne", MOT_DE_PASSE, ["employee"])
    (cible / "paliers.yaml").write_text("generation: ancienne\n", encoding="utf-8")
    ancienne_base = (cible / "opsys.db").read_bytes()

    def echec_migration(*_args, **_kwargs):
        raise RuntimeError("migration refusée déterministement")

    monkeypatch.setattr(exportation.command, "upgrade", echec_migration)
    with pytest.raises(RuntimeError, match="migration refusée déterministement"):
        exportation.restaurer(archive, cible, par="test", remplacer=True)

    assert (cible / "opsys.db").read_bytes() == ancienne_base
    assert (cible / "paliers.yaml").read_text(encoding="utf-8") == "generation: ancienne\n"
    assert _personnes() == ["ancienne-fictive"]
    assert not list(cible.glob("*.avant-restauration-*"))
