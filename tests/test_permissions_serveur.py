"""Permissions Compose : fichiers fictifs ; aucune image ni service Docker lancé."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
FICTIF = True
pytestmark = pytest.mark.skipif(os.name != "posix", reason="préflight de l'image serveur Linux uniquement")


def test_image_independante_garde_10100_et_compose_aligne_core():
    dockerfile = (RACINE / "deploy/Dockerfile").read_text()
    compose = yaml.safe_load((RACINE / "deploy/docker-compose.yml").read_text())
    assert "ARG OPSYS_RUNTIME_UID=10100" in dockerfile
    assert '--uid "$OPSYS_RUNTIME_UID"' in dockerfile
    assert "USER opsys" in dockerfile and "chown -R opsys:opsys" in dockerfile
    assert compose["services"]["opsys"]["build"]["args"] == {"OPSYS_RUNTIME_UID": "1000"}
    assert "user" not in compose["services"]["opsys"]
    assert "user" not in compose["services"]["openclaw-gateway"]
    assert "group_add" not in compose["services"]["openclaw-gateway"]
    assert "USER node" in (RACINE / "core/Dockerfile").read_text()


@pytest.fixture
def volumes(tmp_path):
    roots = [tmp_path / "config", tmp_path / "data", tmp_path / "litellm"]
    for root in roots:
        root.mkdir(mode=0o700)
        (root / "fictif.txt").write_text("contenu-fictif\n")
    return roots


@pytest.fixture
def permissions():
    chemin = RACINE / "deploy/permissions.py"
    spec = importlib.util.spec_from_file_location("permissions_serveur_fictif", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_prive_600_700_ne_change_aucun_octet_ni_mode(permissions, volumes):
    for root in volumes:
        (root / "fictif.txt").chmod(0o600)
    avant = [(root.stat().st_mode, (root / "fictif.txt").stat().st_mode,
              (root / "fictif.txt").read_bytes()) for root in volumes]
    permissions.verifier(volumes)
    assert avant == [(root.stat().st_mode, (root / "fictif.txt").stat().st_mode,
                      (root / "fictif.txt").read_bytes()) for root in volumes]


@pytest.mark.parametrize("cible", ["root", "fichier", "imbrique"])
def test_refus_droits_inaccessibles_sans_reparation(permissions, volumes, cible):
    root = volumes[0]
    path = root
    if cible == "fichier":
        path = root / "opsys" / "models.json"
        path.parent.mkdir()
        path.write_text('{"fictif":true}\n')
    if cible == "imbrique":
        path = root / "opsys" / "espaces" / "m01-fictif"
        path.mkdir(parents=True)
        (path / "SOUL.md").write_text("mandat-fictif\n")
    mode = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0o500 if path.is_dir() else 0o400)
    try:
        with pytest.raises(permissions.RefusPermissions, match="REJ-PERMISSIONS-SERVEUR"):
            permissions.verifier(volumes)
        assert stat.S_IMODE(path.stat().st_mode) == (0o500 if path.is_dir() else 0o400)
        assert (root / "fictif.txt").read_bytes() == b"contenu-fictif\n"
    finally:
        path.chmod(mode)  # uniquement le fichier temporaire du test, pour son nettoyage


def test_objet_git_core_lecture_seule_est_conserve(permissions, volumes):
    objet = volumes[0] / "opsys" / "espaces" / "m01-fictif" / ".git" / "objects" / "ab" / "fictif"
    objet.parent.mkdir(parents=True)
    objet.write_bytes(b"objet-git-fictif\n")
    objet.chmod(0o444)
    permissions.verifier(volumes)
    assert stat.S_IMODE(objet.stat().st_mode) == 0o444
    assert objet.read_bytes() == b"objet-git-fictif\n"


@pytest.mark.parametrize("modification", ["remplacee", "retiree", "supplementaire", "imbriquee", "racine"])
def test_inclusions_bootstrap_refusees_sans_remplacement(tmp_path, modification):
    from opsys.serveur_bootstrap import ErreurBootstrapServeur, preparer

    env = {"OPENCLAW_GATEWAY_TOKEN": "bearer-fictif-gateway-1234567890ABCDE"}
    config = tmp_path / "config"
    preparer(config, "opsys.example.test", environ=env)
    path = config / "openclaw.json"
    root = json.loads(path.read_text())
    if modification == "remplacee":
        root["agents"]["$include"] = ["./autre-fictif.json"]
    elif modification == "retiree":
        del root["agents"]["$include"]
    elif modification == "supplementaire":
        root["agents"]["$include"].append("./autre-fictif.json")
    elif modification == "imbriquee":
        root["agents"]["defaults"] = {"model": {"$include": "./autre-fictif.json"}}
    else:
        root["$include"] = "./autre-fictif.json"
    path.write_text(json.dumps(root, indent=4))
    avant = path.read_bytes()
    with pytest.raises(ErreurBootstrapServeur, match="REJ-BOOTSTRAP-SERVEUR-EXISTANT"):
        preparer(config, "opsys.example.test", environ=env)
    assert path.read_bytes() == avant
    assert not (config / "opsys").exists()


@pytest.mark.parametrize("cible", ["volume", "fragment"])
def test_ancien_uid_metadata_simulee_refuse_meme_si_accessible(permissions, volumes, monkeypatch, cible):
    """Oracle metadata simulé ; le noyau n'est pas exécuté sous UID10100."""
    lstat = permissions.os.lstat
    target = volumes[0]
    if cible == "fragment":
        target = volumes[0] / "opsys" / "models.json"
        target.parent.mkdir()
        target.write_text('{"fictif":true}\n')

    def ancien_uid(path):
        actual = lstat(path)
        if Path(path) != target:
            return actual
        values = list(actual)
        values[4] = 10100 if os.geteuid() != 10100 else 1000
        return os.stat_result(values)

    monkeypatch.setattr(permissions.os, "lstat", ancien_uid)
    with pytest.raises(permissions.RefusPermissions, match="propriétaire"):
        permissions.verifier(volumes)
    assert (volumes[0] / "fictif.txt").read_bytes() == b"contenu-fictif\n"


def test_scan_borne_refuse_sans_ecrire(permissions, volumes, monkeypatch):
    skills = volumes[0] / "opsys" / "espaces" / "m01-fictif" / "skills" / "fictif"
    skills.mkdir(parents=True)
    for number in range(25):
        (skills / f"cible-fictive-{number}.txt").write_text("fictif\n")
    monkeypatch.setattr(permissions, "MAX_ENTREES", 20)
    with pytest.raises(permissions.RefusPermissions, match="plafond"):
        permissions.verifier(volumes)
    assert len(list(skills.iterdir())) == 25


def test_lien_symbolique_refuse_sans_toucher_sa_cible(permissions, volumes, tmp_path):
    cible = tmp_path / "hors-volume"
    cible.write_text("fictif-hors-volume\n")
    (volumes[0] / "opsys").mkdir()
    (volumes[0] / "opsys" / "models.json").symlink_to(cible)
    with pytest.raises(permissions.RefusPermissions, match="lien"):
        permissions.verifier(volumes)
    assert cible.read_text() == "fictif-hors-volume\n"


def test_plus_de_10000_annexes_et_lien_hors_cibles_sans_parcours(permissions, volumes, tmp_path, monkeypatch):
    """Assets Core fictifs : aucune cible Python dans cette arborescence."""
    annexes = volumes[0] / "workspace" / ".git" / "objects"
    annexes.mkdir(parents=True)
    for number in range(10001):
        (annexes / f"annexe-fictive-{number}").touch()
    assert len(list(annexes.iterdir())) == 10001
    (volumes[0] / "transcripts-fictifs").symlink_to(tmp_path / "cible-annexe-absente")
    lstat = permissions.os.lstat

    def sans_annexes(path):
        assert not Path(path).is_relative_to(volumes[0] / "workspace"), "annexe hors cibles parcourue"
        assert Path(path) != volumes[0] / "transcripts-fictifs", "lien annexe hors cibles inspecté"
        return lstat(path)

    monkeypatch.setattr(permissions.os, "lstat", sans_annexes)
    permissions.verifier(volumes)
    assert (volumes[0] / "transcripts-fictifs").is_symlink()


def test_mode_natif_ignore_volume_litellm_absent(volumes):
    env = {**os.environ, "OPSYS_HOME": str(volumes[1]), "OPENCLAW_CONFIG_DIR": str(volumes[0]),
           "LITELLM_CONFIG_DIR": str(volumes[2] / "absent"), "OPSYS_MODE_FOURNISSEUR": "natif"}
    resultat = subprocess.run([os.sys.executable, str(RACINE / "deploy/permissions.py")],
                              env=env, capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 0, resultat.stderr


@pytest.mark.parametrize("volume", ["config", "data", "litellm"])
def test_entrypoint_refuse_avant_bootstrap_migration_et_generation(volumes, tmp_path, volume):
    config, data, litellm = volumes
    path = {"config": config, "data": data, "litellm": litellm}[volume]
    path.chmod(0o500)
    marker = tmp_path / "appel-metier"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "opsys-metier"
    cli.write_text('#!/bin/sh\nprintf "appel\n" >>"$MARKER"\nexit 99\n')
    cli.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "OPSYS_HOME": str(data), "OPENCLAW_CONFIG_DIR": str(config),
           "LITELLM_CONFIG_DIR": str(litellm), "OPSYS_MODE_FOURNISSEUR": "litellm",
           "OPSYS_PASSERELLE_URL": "http://127.0.0.1:9", "MARKER": str(marker)}
    try:
        resultat = subprocess.run(["sh", str(RACINE / "deploy/entrypoint.sh")],
                                  env=env, capture_output=True, text=True, timeout=10)
        assert resultat.returncode == 2
        assert not marker.exists(), "aucun appel bootstrap/base/génération après refus"
        assert "REJ-PERMISSIONS-SERVEUR" in resultat.stderr
        assert stat.S_IMODE(path.stat().st_mode) == 0o500
    finally:
        path.chmod(0o700)


def test_ecrivains_python_core_prive_python_uid_aligne(permissions, opsys_home, tmp_path, monkeypatch, capsys):
    """Vrais écrivains de sources TS présentes ; même UID hôte, pas une preuve d'image."""
    from opsys import cli, modeles, stockage

    core = RACINE / "core"
    if not shutil.which("node") or not (core / "node_modules/tsx").exists():
        pytest.skip("writer natif Core : Node et les dépendances Core sont nécessaires")
    token = "bearer-fictif-gateway-1234567890ABCDE"
    config = tmp_path / "config"
    data = opsys_home
    hote = tmp_path / "home"
    config.mkdir(mode=0o755)
    hote.mkdir()
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", token)
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "embeddings-fictif")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_LOCAL", "1")
    stockage.migrer()
    try:
        modeles.enregistrer_paliers({
            p: {"provider": "custom", "model": "modele-fictif", "base_url": "http://127.0.0.1:9/v1"}
            for p in ("local", "rapide", "standard", "fort")
        })
        bootstrap = ["openclaw", "bootstrap-serveur", "--config-dir", str(config),
                     "--domaine", "opsys.example.test"]
        generation = ["openclaw", "configurer", "--config-dir", str(config)]
        assert cli.main(bootstrap) == 0
        assert cli.main(generation) == 0
        avant_fragments = {p.name: p.read_bytes() for p in (config / "opsys").glob("*.json")}
        harness = tmp_path / "writer-core.mjs"
        harness.write_text(CORE_WRITER)
        env = {"PATH": os.environ["PATH"], "HOME": str(hote), "TMPDIR": str(tmp_path),
               "OPENCLAW_STATE_DIR": str(config), "OPENCLAW_CONFIG_PATH": str(config / "openclaw.json"),
               "OPENCLAW_GATEWAY_TOKEN": token, "OPSYS_MCP_JETON": "bearer-fictif-mcp-1234567890ABCDEF",
               "OPSYS_CONTEXT_MCP_JETON": "bearer-fictif-contexte-1234567890ABC"}
        resultat = subprocess.run([
            "node", "--import", str(core / "scripts/tsx.mjs"), str(harness), str(core),
            str(config / "openclaw.json"),
        ], cwd=core, env=env, capture_output=True, text=True, timeout=40)
        (tmp_path / "writer-core.stdout.log").write_text(resultat.stdout)
        (tmp_path / "writer-core.stderr.log").write_text(resultat.stderr)
        assert resultat.returncode == 0, resultat.stderr
        verdict = json.loads(resultat.stdout.strip().splitlines()[-1])
        assert verdict == {"schema_valid": True, "auth_resolved": True, "dir_mode": "700",
                           "root_mode": "600", "uid": os.geteuid(), "base_path": "/preuve-fictive"}
        root_prive = (config / "openclaw.json").read_bytes()
        assert token.encode() not in root_prive
        permissions.verifier([config, data])
        assert cli.main(bootstrap) == 0
        assert cli.main(generation) == 0
        assert (config / "openclaw.json").read_bytes() == root_prive
        assert {p.name: p.read_bytes() for p in (config / "opsys").glob("*.json")} == avant_fragments
        assert len(json.loads((config / "opsys/mcp.json").read_text())["servers"]) == 10
        assert stat.S_IMODE(config.stat().st_mode) == 0o700
        assert stat.S_IMODE((config / "openclaw.json").stat().st_mode) == 0o600
        assert token not in resultat.stdout + resultat.stderr + capsys.readouterr().out
        (tmp_path / "writer-core-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    finally:
        stockage.liberer()


CORE_WRITER = """
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root=process.argv[2];
const configPath=process.argv[3];
const { createConfigIO }=await import(pathToFileURL(path.join(root,'src/config/io.factory.ts')).href);
const io=createConfigIO({configPath,env:process.env,homedir:()=>process.env.HOME,
  observe:false,shellEnvFallback:'defer'});
const { snapshot, writeOptions }=await io.readConfigFileSnapshotForWrite({observe:false});
if(!snapshot.valid) throw new Error('configuration fictive native invalide');
// Même contrat que config-cli-runner : resolved, sans les defaults de runtime.
const candidate=structuredClone(snapshot.resolved);
candidate.gateway.controlUi.basePath='/preuve-fictive';
await io.writeConfigFile(candidate,{...writeOptions,observe:false});
const current=await io.readConfigFileSnapshot({observe:false,isolateEnv:true});
console.log(JSON.stringify({schema_valid:current.valid,
  auth_resolved:current.config.gateway.auth.token===process.env.OPENCLAW_GATEWAY_TOKEN,
  dir_mode:(fs.statSync(path.dirname(configPath)).mode & 0o777).toString(8),
  root_mode:(fs.statSync(configPath).mode & 0o777).toString(8),uid:process.getuid(),
  base_path:current.config.gateway.controlUi.basePath}));
"""
