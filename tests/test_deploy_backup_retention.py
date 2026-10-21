"""Rétention locale de deploy/backup.sh : ne purger que des sauvegardes OPSYS positivement identifiées."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from tests.test_deploy_backup_restore import _run, banc_docker  # noqa: F401

VIEUX = 40 * 86400
RECENT = 5 * 86400


def _vieillir(chemin: Path, age: int) -> None:
    instant = time.time() - age
    os.utime(chemin, (instant, instant), follow_symlinks=False)


def _dossier(racine: Path, nom: str, fichiers: dict[str, str], age: int = VIEUX) -> Path:
    dossier = racine / nom
    dossier.mkdir(parents=True)
    for fichier, contenu in fichiers.items():
        (dossier / fichier).write_text(contenu, encoding="utf-8")
    _vieillir(dossier, age)
    return dossier


def _historique(racine: Path, nom: str, version: int, age: int = VIEUX) -> Path:
    archives = ["postgres-opsys.sql.gz", "volume-opsys_data.tar.gz"]
    entetes = {
        1: [nom, "bases: opsys litellm", "volumes: opsys_data"],
        2: ["format=opsys-backup/2", "mode=legacy", *(f"archive={a}" for a in archives)],
        3: ["format=opsys-backup/3", "mode=natif", "database=sqlite", f"stamp={nom}",
            *(f"archive={a}" for a in archives)],
    }
    contenu = {"MANIFEST.txt": "\n".join(entetes[version]) + "\n"}
    contenu.update({a: "contenu fictif\n" for a in archives})
    return _dossier(racine, nom, contenu, age)


def _sauvegarde_v4_vieillie(deploy: Path, env: dict[str, str], racine: Path) -> Path:
    resultat = _run(deploy / "backup.sh", "--out", str(racine), env=env)
    assert resultat.returncode == 0, resultat.stderr
    [dossier] = [p for p in racine.iterdir() if p.is_dir()]
    _vieillir(dossier, VIEUX)
    seconde = int(time.time())
    while int(time.time()) == seconde:  # le prochain STAMP doit différer de celui-ci
        time.sleep(0.05)
    return dossier


def _etrangers(racine: Path, externe: Path) -> dict[str, Path]:
    """Données sans lien avec OPSYS, ou formes OPSYS non prouvées, toutes plus vieilles que la rétention."""
    stamp_v4 = "20200105T000000Z"
    v4_valide = f"format=opsys-backup/4\nmode=natif\ndatabase=sqlite\nstamp={stamp_v4}\n"
    cibles = {
        "nom_arbitraire": _dossier(racine, "photos-chantier-client", {"toit.jpg": "image fictive\n"}),
        "horodatage_sans_manifeste": _dossier(racine, "20200101T000000Z", {"notes.txt": "fictif\n"}),
        "manifeste_malforme": _dossier(racine, "20200102T000000Z", {"MANIFEST.txt": "pas un manifeste\n"}),
        "manifeste_vide": _dossier(racine, "20200103T000000Z", {"MANIFEST.txt": ""}),
        "format_futur": _dossier(racine, "20200104T000000Z", {
            "MANIFEST.txt": "format=opsys-backup/5\nstamp=20200104T000000Z\n", "INTEGRITE.json": "{}\n"}),
        "fichier_etranger_dans_v4": _dossier(racine, stamp_v4, {
            "MANIFEST.txt": v4_valide, "INTEGRITE.json": "{}\n", "rapport-impots.pdf": "fictif\n"}),
        "stamp_discordant_v4": _dossier(racine, "20200106T000000Z", {
            "MANIFEST.txt": v4_valide, "INTEGRITE.json": "{}\n"}),
        "v4_sans_integrite": _dossier(racine, "20200107T000000Z", {
            "MANIFEST.txt": v4_valide.replace(stamp_v4, "20200107T000000Z")}),
        "archive_non_declaree_v3": _dossier(racine, "20200108T000000Z", {
            "MANIFEST.txt": "format=opsys-backup/3\nmode=natif\ndatabase=sqlite\n",
            "volume-autre.tar.gz": "fictif\n"}),
    }
    sous_dossier = _dossier(racine, "20200109T000000Z", {"MANIFEST.txt": "20200109T000000Z\n"})
    (sous_dossier / "volume-x.tar.gz").mkdir()
    (sous_dossier / "volume-x.tar.gz" / "donnee.txt").write_text("fictif\n", encoding="utf-8")
    _vieillir(sous_dossier, VIEUX)
    cibles["sous_dossier_imbrique"] = sous_dossier
    externe.mkdir()
    (externe / "MANIFEST.txt").write_text("20200110T000000Z\n", encoding="utf-8")
    _vieillir(externe, VIEUX)
    lien = racine / "20200110T000000Z"
    lien.symlink_to(externe, target_is_directory=True)
    _vieillir(lien, VIEUX)
    cibles["lien_symbolique"] = lien
    return cibles


def test_retention_conserve_tout_dossier_non_identifie_comme_sauvegarde_opsys(banc_docker):  # noqa: F811
    deploy, _, env, tmp_path = banc_docker
    racine = tmp_path / "backups"
    racine.mkdir()
    externe = tmp_path / "hors-sauvegardes"
    etrangers = _etrangers(racine, externe)
    contenus = {
        cle: sorted(p.relative_to(chemin).as_posix() for p in chemin.rglob("*"))
        for cle, chemin in etrangers.items() if cle != "lien_symbolique"
    }

    resultat = _run(deploy / "backup.sh", "--out", str(racine), "--retention-days", "14", env=env)

    assert resultat.returncode == 0, resultat.stderr
    disparus = [cle for cle, chemin in etrangers.items() if not os.path.lexists(chemin)]
    assert disparus == [], f"rétention a supprimé des données non OPSYS : {disparus}"
    for cle, attendu in contenus.items():
        chemin = etrangers[cle]
        assert sorted(p.relative_to(chemin).as_posix() for p in chemin.rglob("*")) == attendu, cle
    assert etrangers["lien_symbolique"].is_symlink()
    assert (externe / "MANIFEST.txt").read_text(encoding="utf-8") == "20200110T000000Z\n"
    assert "conservé" in resultat.stderr


def test_retention_purge_sauvegardes_opsys_v1_a_v4_eligibles_et_garde_recentes(banc_docker):  # noqa: F811
    deploy, _, env, tmp_path = banc_docker
    racine = tmp_path / "backups"
    ancienne_v4 = _sauvegarde_v4_vieillie(deploy, env, racine)
    anciennes = [ancienne_v4, *(_historique(racine, f"2020020{v}T000000Z", v) for v in (1, 2, 3))]
    recentes = [_historique(racine, f"2020030{v}T000000Z", v, age=RECENT) for v in (1, 2, 3)]

    resultat = _run(deploy / "backup.sh", "--out", str(racine), "--retention-days", "14", env=env)

    assert resultat.returncode == 0, resultat.stderr
    assert [p.name for p in anciennes if p.exists()] == []
    assert all(p.is_dir() for p in recentes)
    courantes = [p for p in racine.iterdir() if p.is_dir() and p not in recentes]
    assert len(courantes) == 1 and (courantes[0] / "INTEGRITE.json").is_file()
    assert all(str(p) in resultat.stdout for p in anciennes)


@pytest.mark.parametrize("valeur", ["abc", "-1", "14j", ""])
def test_retention_jours_invalides_refuses_avant_tout_effet_docker(banc_docker, valeur):  # noqa: F811
    deploy, _, env, tmp_path = banc_docker
    racine = tmp_path / "backups"

    resultat = _run(deploy / "backup.sh", "--out", str(racine), "--retention-days", valeur, env=env)

    assert resultat.returncode == 2
    assert "--retention-days" in resultat.stderr
    assert not Path(env["FAKE_DOCKER_LOG"]).exists()
    assert not racine.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignore les permissions de répertoire")
def test_retention_echec_de_suppression_rend_la_sauvegarde_non_zero(banc_docker):  # noqa: F811
    deploy, _, env, tmp_path = banc_docker
    racine = tmp_path / "backups"
    bloquee = _historique(racine, "20200201T000000Z", 1)
    bloquee.chmod(0o500)
    _vieillir(bloquee, VIEUX)
    try:
        resultat = _run(deploy / "backup.sh", "--out", str(racine), "--retention-days", "14", env=env)
    finally:
        bloquee.chmod(0o700)

    assert resultat.returncode == 1
    assert "rétention" in resultat.stderr
    assert (bloquee / "MANIFEST.txt").is_file()
    journal = [json.loads(ligne) for ligne in Path(env["FAKE_DOCKER_LOG"]).read_text().splitlines()]
    assert any(appel[:1] == ["run"] for appel in journal)  # la sauvegarde courante a bien été produite


@pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="injection POSIX via descripteur")
def test_retention_ne_supprime_pas_un_fichier_etranger_apparu_apres_identification(tmp_path, monkeypatch):
    """Injection déterministe entre identification et suppression, sans minuterie ni données réelles."""
    from tests.test_deploy_backup_restore import ROOT

    racine = tmp_path / "backups-fictifs"
    ancien = _historique(racine, "20200201T000000Z", 1)
    etranger = ancien / "rapport-client-fictif.txt"
    original_close = os.close

    def fermer_apres_lecture(fd):
        cible = os.readlink(f"/proc/self/fd/{fd}")
        original_close(fd)
        if cible == str(ancien / "MANIFEST.txt"):
            etranger.write_text("donnée fictive hors sauvegarde", encoding="utf-8")

    monkeypatch.setattr(os, "close", fermer_apres_lecture)
    monkeypatch.setattr("sys.argv", ["retention", str(racine), "20990101T000000Z", "14"])
    script = (ROOT / "deploy/backup.sh").read_text().split("<<'PY_RETENTION'\n", 1)[1].split("\nPY_RETENTION", 1)[0]
    with pytest.raises(SystemExit):
        exec(compile(script, "deploy/backup.sh:retention", "exec"), {})
    assert etranger.is_file(), "un fichier non identifié apparu pendant la purge ne doit pas être supprimé"
