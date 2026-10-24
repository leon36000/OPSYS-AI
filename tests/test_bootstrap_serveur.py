"""Bootstrap Compose réel, sans Docker ni appel à un fournisseur (données fictives)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from agents_base_qa import provisionner_base_qa

from opsys import cli, instance, modeles, openclaw, stockage
from opsys.departements import charger_departements

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
DOMAINE = "opsys.example.test"
JETON_FICTIF = "bearer-fictif-gateway-1234567890ABCDE"
EMBEDDINGS = {
    "OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:9/v1",
    "OPSYS_EMBEDDINGS_MODELE": "embeddings-fictif",
    "OPSYS_EMBEDDINGS_LOCAL": "1",
}


@pytest.fixture
def environnement(opsys_home, monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", JETON_FICTIF)
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    stockage.migrer()
    modeles.enregistrer_paliers({
        palier: {"provider": "custom", "model": "modele-fictif", "base_url": "http://127.0.0.1:9/v1"}
        for palier in ("local", "rapide", "standard", "fort")
    })
    yield
    stockage.liberer()


def _bootstrap(dossier, domaine=DOMAINE):
    return cli.main([
        "openclaw", "bootstrap-serveur", "--config-dir", str(dossier), f"--domaine={domaine}",
    ])


def test_bootstrap_frais_reference_auth_et_generation_reelle(environnement, tmp_path, capsys):
    profils = provisionner_base_qa(stockage.transaction, charger_departements())
    dossier = tmp_path / "config"
    assert _bootstrap(dossier) == 0
    contenu = (dossier / "openclaw.json").read_bytes()
    racine = json.loads(contenu)
    assert racine["gateway"] == {
        "mode": "local", "port": 18789, "bind": "lan",
        "auth": {"mode": "token", "token": "${OPENCLAW_GATEWAY_TOKEN}"},
        "controlUi": {"allowedOrigins": [f"https://{DOMAINE}", f"http://{DOMAINE}"]},
        "nodes": {"pairing": {"autoApproveLocal": False}},
    }
    assert JETON_FICTIF.encode() not in contenu
    assert cli.main(["openclaw", "configurer", "--config-dir", str(dossier)]) == 0
    assert (dossier / "openclaw.json").read_bytes() == contenu
    serveurs = json.loads((dossier / "opsys/mcp.json").read_text())["servers"]
    assert set(serveurs) == {f"opsys_m{numero}" for numero in range(1, 11)} | {
        f"opsys_runtime_{profil['id']}" for profil in profils.values()
    }
    assert _bootstrap(dossier) == 0
    assert (dossier / "openclaw.json").read_bytes() == contenu
    sorties = capsys.readouterr()
    assert JETON_FICTIF not in sorties.out + sorties.err


def test_configurer_sans_profils_base_refuse_sans_fragment(environnement, tmp_path, capsys):
    dossier = tmp_path / "config"
    assert _bootstrap(dossier) == 0
    avant = (dossier / "openclaw.json").read_bytes()
    assert cli.main(["openclaw", "configurer", "--config-dir", str(dossier)]) == 2
    assert "profils de base" in capsys.readouterr().err
    assert (dossier / "openclaw.json").read_bytes() == avant
    assert not (dossier / "opsys/mcp.json").exists()


@pytest.mark.parametrize("domaine", ["https://opsys.example.test", "a/b", "a;id", "a@b", "a\nb", "", "-a.test"])
def test_domaine_invalide_refuse_sans_creation(environnement, tmp_path, domaine, capsys):
    dossier = tmp_path / "config"
    assert _bootstrap(dossier, domaine) == 2
    assert not dossier.exists()
    assert "REJ-BOOTSTRAP-SERVEUR-DOMAINE" in capsys.readouterr().err


@pytest.mark.parametrize("jeton", ["", "court", "x" * 31, "x" * 32 + "\n"])
def test_bearer_absent_ou_invalide_refuse_sans_creation(environnement, tmp_path, monkeypatch, jeton, capsys):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", jeton)
    dossier = tmp_path / "config"
    assert _bootstrap(dossier) == 2
    assert not dossier.exists()
    assert "REJ-BOOTSTRAP-SERVEUR-AUTH" in capsys.readouterr().err


@pytest.mark.parametrize("modification", [
    {"mode": "remote"}, {"mode": None}, {"port": 9999}, {"bind": "loopback"},
    {"auth": {"mode": "none"}}, {"auth": {"mode": "token", "token": "un-autre-bearer-fictif-1234567890ABC"}},
    {"auth": {"mode": "token", "token": "jeton-incompatible-é"}},
    {"controlUi": {"allowedOrigins": ["https://autre.example.test"]}},
    {"nodes": {"pairing": {"autoApproveLocal": True}}},
])
def test_racine_existante_incoherente_conservee(environnement, tmp_path, modification, capsys):
    dossier = tmp_path / "config"
    assert _bootstrap(dossier) == 0
    chemin = dossier / "openclaw.json"
    racine = json.loads(chemin.read_text())
    racine["gateway"].update(modification)
    chemin.write_text(json.dumps(racine, indent=3) + "\n")
    avant = {str(p.relative_to(dossier)): p.read_bytes() for p in dossier.rglob("*") if p.is_file()}
    assert _bootstrap(dossier) == 2
    assert avant == {str(p.relative_to(dossier)): p.read_bytes() for p in dossier.rglob("*") if p.is_file()}
    assert "REJ-BOOTSTRAP-SERVEUR-EXISTANT" in capsys.readouterr().err


def test_ancienne_racine_opsys_sans_mode_exige_reprise_assistee(environnement, tmp_path, capsys):
    dossier = tmp_path / "config"
    dossier.mkdir()
    chemin = openclaw.racine_si_absente(dossier)
    contenu = chemin.read_bytes()
    assert _bootstrap(dossier) == 2
    assert chemin.read_bytes() == contenu
    assert not (dossier / "opsys").exists()
    erreur = capsys.readouterr().err
    assert "REJ-BOOTSTRAP-SERVEUR-EXISTANT" in erreur
    assert "snapshot" in erreur and "assistée" in erreur


def test_reprise_preserve_format_champs_et_ancien_bearer(environnement, tmp_path, capsys):
    dossier = tmp_path / "config"
    assert _bootstrap(dossier) == 0
    chemin = dossier / "openclaw.json"
    racine = json.loads(chemin.read_text())
    racine["gateway"]["auth"]["token"] = JETON_FICTIF
    racine["gateway"]["controlUi"]["allowedOrigins"].reverse()
    racine["gateway"]["controlUi"]["basePath"] = "/controle"
    chemin.write_text(json.dumps(racine, indent=4) + "\n\n")
    contenu = chemin.read_bytes()
    assert _bootstrap(dossier) == 0
    assert chemin.read_bytes() == contenu
    assert JETON_FICTIF not in capsys.readouterr().out


def test_arguments_bootstrap_fermes(environnement, tmp_path):
    dossier = tmp_path / "config"
    with pytest.raises(SystemExit) as erreur:
        cli.main(["openclaw", "bootstrap-serveur", "--config-dir", str(dossier),
                  "--domaine", DOMAINE, "--url-mcp", "http://autre.example.test/mcp"])
    assert erreur.value.code == 2
    assert not dossier.exists()


@pytest.mark.parametrize("ready,remote,attendu", [("0", False, 0), ("1", False, 0), ("1", True, 1)])
def test_installateur_valide_avant_lancement_et_garde_readiness(environnement, tmp_path, ready, remote, attendu):
    """Bash réel + CLI réelle ; Compose/up et attente santé sont simulés, aucun service."""
    dossier = tmp_path / "config"
    assert _bootstrap(dossier) == 0
    chemin = dossier / "openclaw.json"
    if remote:
        racine = json.loads(chemin.read_text())
        racine["gateway"]["mode"] = "remote"
        chemin.write_text(json.dumps(racine))
    avant = chemin.read_bytes()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commande = bin_dir / "opsys-metier"
    commande.write_text('#!/bin/sh\nexec "$AUDIT_PYTHON" -m opsys.cli "$@"\n')
    commande.chmod(0o755)
    source = (RACINE / "deploy/install.sh").read_text()
    fonction = source[source.index("bootstrap_openclaw() {"):source.index("start_edge() {")]
    script = tmp_path / "bootstrap.sh"
    script.write_text("""set -eu
log() { :; }
warn() { :; }
die() { exit 1; }
compose() {
    case "$1" in
        exec) shift 5; sh -c "$1" ;;
        up) printf 'up\n' >"$LANCEMENT" ;;
        *) exit 98 ;;
    esac
}
wait_healthy() { return 0; }
""" + fonction + "\nbootstrap_openclaw\n")
    lancement = tmp_path / "lancement"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "AUDIT_PYTHON": os.sys.executable, "CORE_READY": ready, "COMPOSE_PROFILE": "",
           "OPENCLAW_CONFIG_DIR": str(dossier), "OPSYS_DOMAINE": DOMAINE, "LANCEMENT": str(lancement)}
    resultat = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=15)
    assert resultat.returncode == attendu
    assert lancement.exists() is (ready == "1" and not remote)
    assert chemin.read_bytes() == avant
    assert JETON_FICTIF not in resultat.stdout + resultat.stderr


def test_profil_natif_et_root_invalide_refuses_sans_reparation(environnement, tmp_path, capsys):
    dossier = tmp_path / "config"
    dossier.mkdir()
    chemin = dossier / "opsys.json"
    chemin.write_text('{"gateway":{"mode":"local"}}\n')
    avant = chemin.read_bytes()
    assert _bootstrap(dossier) == 2
    assert chemin.read_bytes() == avant and not (dossier / "openclaw.json").exists()
    chemin.unlink()
    chemin = dossier / "openclaw.json"
    chemin.write_text("{fichier-json-invalide\n")
    avant = chemin.read_bytes()
    assert _bootstrap(dossier) == 2
    assert chemin.read_bytes() == avant
    assert "REJ-BOOTSTRAP-SERVEUR-EXISTANT" in capsys.readouterr().err


def test_core_schema_resolution_env_et_garde_native(environnement, tmp_path, monkeypatch, capsys):
    core = RACINE / "core"
    if not shutil.which("node") or not (core / "node_modules/tsx").exists():
        pytest.skip("validation native Core : Node et les dépendances Core sont nécessaires")
    provisionner_base_qa(stockage.transaction, charger_departements())
    dossier = tmp_path / "serveur"
    assert _bootstrap(dossier) == 0
    assert cli.main(["openclaw", "configurer", "--config-dir", str(dossier)]) == 0
    hote = tmp_path / "home"
    hote.mkdir()
    monkeypatch.setenv("HOME", str(hote))
    for nom in instance.VARIABLES_ECARTEES:
        monkeypatch.delenv(nom, raising=False)
    natif = instance.initialiser(
        tmp_path / "instance", source=RACINE, python=Path(os.sys.executable),
        port_gateway=19991, port_moteur=19992, environ={"HOME": str(hote), **EMBEDDINGS},
    )
    assert natif.etat == "pret"
    racine_native = instance.fichier_config(natif.dossier_core)
    assert json.loads(racine_native.read_text())["gateway"] == {
        "mode": "local", "port": 19991, "bind": "loopback", "auth": {"mode": "token"},
        "nodes": {"pairing": {"autoApproveLocal": False}},
    }
    harness = tmp_path / "schema.mjs"
    harness.write_text(CORE_PROBE)
    env = {"PATH": os.environ["PATH"], "HOME": str(hote), "TMPDIR": str(tmp_path),
           "OPENCLAW_GATEWAY_TOKEN": JETON_FICTIF,
           "OPSYS_MCP_JETON": "bearer-fictif-mcp-1234567890ABCDEF",
           "OPSYS_CONTEXT_MCP_JETON": "bearer-fictif-contexte-1234567890ABC"}
    resultat = subprocess.run([
        "node", "--import", str(core / "scripts/tsx.mjs"), str(harness),
        str(core), str(dossier / "openclaw.json"), str(racine_native),
    ], cwd=core, env=env, capture_output=True, text=True, timeout=40, check=True)
    verdicts = json.loads(resultat.stdout)
    assert len(verdicts) == 2
    assert all(v["schema_valid"] and v["guard_accepted"] and v["mode"] == "local" for v in verdicts)
    assert verdicts[0]["auth_resolved"] is True
    assert JETON_FICTIF not in resultat.stdout + resultat.stderr + capsys.readouterr().out


CORE_PROBE = """
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root=process.argv[2];
const { createConfigIO }=await import(pathToFileURL(path.join(root,'src/config/io.factory.ts')).href);
const guardPath=path.join(root,'src/cli/gateway-cli/pre-bootstrap.ts');
const { getGatewayStartGuardErrors }=await import(pathToFileURL(guardPath).href);
const results=[];
for (const configPath of process.argv.slice(3)) {
 const io=createConfigIO({configPath,env:process.env,homedir:()=>process.env.HOME,
   observe:false,shellEnvFallback:'defer'});
 const snapshot=await io.readConfigFileSnapshot({observe:false,isolateEnv:true});
 const errors=getGatewayStartGuardErrors({configExists:snapshot.exists,mode:snapshot.config?.gateway?.mode});
 results.push({file:path.basename(configPath),schema_valid:snapshot.valid,mode:snapshot.config?.gateway?.mode??null,
   guard_accepted:errors.length===0,auth_resolved:snapshot.config?.gateway?.auth?.token===process.env.OPENCLAW_GATEWAY_TOKEN});
}
console.log(JSON.stringify(results));
"""
