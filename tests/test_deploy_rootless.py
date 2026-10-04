"""Profil rootless : observations fictives, jamais un daemon ou une image lancé."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FICTIF = True
pytestmark = pytest.mark.skipif(os.sys.platform != "linux", reason="profil serveur Docker rootless Linux uniquement")
GATEWAY = "a" * 64
PYTHON = "b" * 64
PUBLIC_KEY = b"\0\0\0\x0bssh-ed25519\0\0\0\x20" + b"f" * 32
HOST_KEY_SHA256 = "SHA256:" + base64.b64encode(hashlib.sha256(PUBLIC_KEY).digest()).decode().rstrip("=")


@pytest.fixture
def api():
    spec = importlib.util.spec_from_file_location("rootless_fictif", ROOT / "deploy/rootless.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def profil(api, tmp_path):
    return api.creer_profil(
        racine=str(tmp_path / "state"), ssh_dir=str(tmp_path / "controller"),
        daemon_id="daemon-rootless-fictif-2026", controleur="controller.example.test",
        utilisateur="opsys-rootless", uid=os.geteuid(), gid=os.getegid(),
        host_key_sha256=HOST_KEY_SHA256,
    )


def test_generation_ne_cree_ni_bind_ni_cle_et_ne_promet_pas_runtime(api, profil, tmp_path):
    output = tmp_path / "generated"
    result = api.generer(profil, output)
    assert result["runtime_verifie"] is False
    assert not Path(profil["racine"]).exists() and not Path(profil["ssh_dir"]).exists()
    assert {p.name for p in output.iterdir()} == {"profil.json", "rootless.env", "ssh-config"}
    env = (output / "rootless.env").read_text()
    assert "OPSYS_ROOTLESS_HTTP_PORT=8080" in env and "OPSYS_ROOTLESS_HTTPS_PORT=8443" in env
    assert "API_KEY" not in env and "TOKEN" not in env
    assert "ForwardAgent no" in (output / "ssh-config").read_text()
    with pytest.raises(api.RefusRootless, match="sortie existante"):
        api.generer(profil, output)


@pytest.mark.parametrize("change", [
    {"controleur": "https://controller.example.test"}, {"controleur": "bad;commande"},
    {"utilisateur": "-oProxyCommand=bad"}, {"utilisateur": "root"}, {"uid": 0}, {"port_http": 80},
    {"port_https": 8080}, {"ssh_port": True}, {"racine": "/tmp/a/../b"},
])
def test_entrees_fermees_avant_toute_sortie(api, profil, change, tmp_path):
    with pytest.raises(api.RefusRootless):
        api.valider_profil({**profil, **change})
    assert not (tmp_path / "state").exists()


def test_ssh_hors_tous_les_workspaces_et_cle_jamais_en_argv(api, profil):
    with pytest.raises(api.RefusRootless, match="séparés"):
        api.valider_profil({**profil, "ssh_dir": profil["racine"] + "/core-state/workspace/ssh"})
    config = api.configuration_ssh(profil)
    assert "StrictHostKeyChecking yes" in config and "IdentityAgent none" in config
    assert "/home/node/.ssh/id_ed25519" in config
    argv = api.commande_probe(profil, GATEWAY, "openclaw-gateway")
    assert argv[3:6] == ["exec", "--user", "1000:1000"]
    assert argv[7:9] == ["node", "-e"]
    assert profil["ssh_dir"] not in argv[-2]
    assert "CLE-FICTIVE" not in argv[-2]
    assert json.loads(argv[-1])["host_key_sha256"] == HOST_KEY_SHA256


@pytest.fixture
def observations(api, profil, monkeypatch):
    paths = api.binds(profil)
    for path in paths.values():
        Path(path).mkdir(parents=True, mode=0o700, exist_ok=True)
    ssh = Path(profil["ssh_dir"])
    ssh.mkdir(mode=0o700)
    (ssh / "id_ed25519").write_text("CLE-FICTIVE-JAMAIS-LUE")
    key = b"\0\0\0\x0bssh-ed25519\0\0\0\x20" + b"f" * 32
    (ssh / "known_hosts").write_text(
        "controller.example.test ssh-ed25519 " + base64.b64encode(key).decode() + "\n"
    )
    (ssh / "config").write_text(api.configuration_ssh(profil))
    for file in ssh.iterdir():
        file.chmod(0o600)
    metadata = api._metadata

    def mapped_metadata(path):
        info = metadata(path)
        values = list(info)
        values[4:6] = [101999, 201999]
        return os.stat_result(values)

    monkeypatch.setattr(api, "_metadata", mapped_metadata)
    daemon = {
        "ID": profil["daemon_id"], "SecurityOptions": ["name=rootless", "name=seccomp,profile=builtin"],
        "CgroupVersion": "2", "CgroupDriver": "systemd", "MemoryLimit": True,
        "PidsLimit": True, "CpuCfsQuota": True,
    }
    target_mounts = {
        "openclaw-gateway": {
            "/home/node/.openclaw": (paths["core-state"], True),
            "/home/node/.config/openclaw": (paths["core-auth"], True),
            "/home/node/.ssh": (profil["ssh_dir"], False),
        },
        "opsys": {
            "/opt/data": (paths["opsys-data"], True),
            "/openclaw-config": (paths["core-state"], True),
            "/shared/litellm-config": (paths["litellm-config"], True),
        },
    }
    containers = {}
    processes = {}
    for number, (identity, service) in enumerate([(GATEWAY, "openclaw-gateway"), (PYTHON, "opsys")], 10):
        containers[identity] = {
            "Id": identity, "State": {"Running": True, "Pid": number, "StartedAt": "2026-10-01T12:00:00Z"},
            "Config": {"Labels": {"com.docker.compose.service": service,
                                  "com.docker.compose.project": "opsys-fictif"}, "Env": (
                ["DOCKER_HOST=ssh://opsys-rootless-control", "DOCKER_CONTEXT=", "SSH_AUTH_SOCK=",
                 "DOCKER_TLS_VERIFY=", "DOCKER_CERT_PATH=", "HOME=/home/node"]
                if service == "openclaw-gateway" else []
            ), "User": "1000:1000"},
            "HostConfig": {"Privileged": False, "NetworkMode": "bridge", "UsernsMode": "",
                           "Memory": 2 * 1024**3 if service == "openclaw-gateway" else 512 * 1024**2,
                           "PidsLimit": 256, "NanoCpus": 2_000_000_000,
                           "SecurityOpt": ["no-new-privileges:true"], "Tmpfs": {}},
            "Mounts": [{"Type": "bind", "Source": source, "Destination": dest, "RW": rw}
                       for dest, (source, rw) in target_mounts[service].items()],
        }
        processes[number] = {
            "uid_map": f"0 {profil['uid']} 1\n1 101000 65536\n",
            "gid_map": f"0 {profil['gid']} 1\n1 201000 65536\n",
            "euid": 1000, "egid": 1000,
            "principal": {"uid": [1000] * 4, "gid": [1000] * 4},
            "mounts": {dest: {"dev": str(Path(source).stat().st_dev),
                              "ino": str(Path(source).stat().st_ino), "uid": 1000, "gid": 1000,
                              "mode": 0o700, "kind": "dir"}
                       for dest, (source, _) in target_mounts[service].items()},
            "limites": {"memory.max": str(containers[identity]["HostConfig"]["Memory"]),
                        "pids.max": "256", "cpu.max": "200000 100000"},
        }
    monkeypatch.setattr(api, "_daemon", lambda p: daemon)
    monkeypatch.setattr(api, "_inspect", lambda p, identity: containers[identity])
    processes[10]["ssh"] = {name: {"uid": 1000, "gid": 1000, "mode": 0o600, "kind": "file",
                                       "nlink": 1, "size": str((ssh / name).stat().st_size)}
                             for name in ["id_ed25519", "known_hosts", "config"]}
    processes[10]["config"] = (ssh / "config").read_text()
    processes[10]["known_hosts"] = (ssh / "known_hosts").read_text()
    processes[10]["daemon_ssh"] = dict(daemon)
    processes[10]["home"] = "/home/node"
    monkeypatch.setattr(api, "_probe", lambda p, identity, service: processes[containers[identity]["State"]["Pid"]])
    monkeypatch.setattr(api, "_version_compose", lambda: "2.40.3")
    return daemon, containers, processes


def test_dryrun_identity_maps_deux_ecrivains_et_ne_lit_pas_cle(api, profil, observations, monkeypatch):
    original = api._lire_public

    def no_secret(path, *args):
        assert Path(path).name != "id_ed25519"
        return original(path, *args)

    monkeypatch.setattr(api, "_lire_public", no_secret)
    result = api.verifier(profil, GATEWAY, PYTHON)
    assert result["preflight_verifie"] is True and result["runtime_sandbox_verifie"] is False
    assert result["uid_hote"] == 101999 and result["gid_hote"] == 201999
    assert result["services_verifies"] == ["openclaw-gateway", "opsys"]
    assert "CLE-FICTIVE" not in json.dumps(result)


@pytest.mark.parametrize("change", [
    {"SecurityOptions": ["name=seccomp"]}, {"ID": "daemon-etranger-fictif"},
    {"CgroupVersion": "1"}, {"CgroupDriver": "none"}, {"MemoryLimit": False},
    {"PidsLimit": False}, {"CpuCfsQuota": False},
])
def test_daemon_incoherent_refuse_avant_ssh(api, profil, observations, monkeypatch, change):
    observations[0].update(change)
    monkeypatch.setattr(api, "_probe", lambda *args: pytest.fail("namespace ne doit pas être sondé"))
    with pytest.raises(api.RefusRootless):
        api.verifier(profil, GATEWAY, PYTHON)


def test_autre_daemon_ssh_refuse(api, profil, observations, monkeypatch):
    observations[2][10]["daemon_ssh"]["ID"] = "autre-daemon-fictif"
    with pytest.raises(api.RefusRootless, match="daemon"):
        api.verifier(profil, GATEWAY, PYTHON)


@pytest.mark.parametrize("limite", ["memory.max", "pids.max", "cpu.max"])
def test_flags_docker_sans_limite_kernel_refuses(api, profil, observations, limite):
    observations[2][10]["limites"][limite] = "max" if limite != "cpu.max" else "max 100000"
    with pytest.raises(api.RefusRootless, match="cgroup"):
        api.verifier(profil, GATEWAY, PYTHON)


@pytest.mark.parametrize("change", [
    "uid_python", "inode", "socket", "cle", "forward", "limites", "tmpfs", "tls", "projet",
])
def test_incoherence_refuse_sans_reparer(api, profil, observations, change):
    _, containers, processes = observations
    if change == "uid_python":
        processes[11]["uid_map"] = f"0 {profil['uid']} 1\n1 301000 65536\n"
    elif change == "inode":
        processes[10]["mounts"]["/home/node/.openclaw"]["ino"] = "456"
    elif change == "socket":
        containers[GATEWAY]["Mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock",
                                            "Destination": "/var/run/docker.sock", "RW": True})
    elif change == "cle":
        processes[10]["ssh"]["id_ed25519"]["mode"] = 0o644
    elif change == "forward":
        processes[10]["config"] += "ForwardAgent yes\n"
    elif change == "limites":
        containers[PYTHON]["HostConfig"]["PidsLimit"] = 0
    elif change == "tls":
        containers[GATEWAY]["Config"]["Env"].remove("DOCKER_TLS_VERIFY=")
        containers[GATEWAY]["Config"]["Env"].append("DOCKER_TLS_VERIFY=1")
    elif change == "projet":
        containers[PYTHON]["Config"]["Labels"]["com.docker.compose.project"] = "autre-projet-fictif"
    else:
        containers[GATEWAY]["HostConfig"]["Tmpfs"] = {"/home/node/.ssh": "rw"}
    before = {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in Path(profil["ssh_dir"]).iterdir()}
    with pytest.raises(api.RefusRootless):
        api.verifier(profil, GATEWAY, PYTHON)
    assert before == {p: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in before}


def test_identifiant_absent_refuse_avant_docker(api, profil, monkeypatch):
    monkeypatch.setattr(api, "_daemon", lambda p: pytest.fail("pas d'appel API"))
    with pytest.raises(api.RefusRootless, match="identifiants"):
        api.verifier(profil, "", PYTHON)


def test_commande_bornee_et_refus_sans_sortie_brute(api, tmp_path):
    script = tmp_path / "fictif.py"
    script.write_text("print('SECRET-FICTIF-' * 10000)\n")
    with pytest.raises(api.RefusRootless, match="sortie") as caught:
        api._commande([os.sys.executable, str(script)], limite=100)
    assert "SECRET-FICTIF" not in str(caught.value)


@pytest.mark.parametrize("cible", ["runtime", "socket"])
def test_socket_rootless_publique_refuse_avant_api(api, profil, monkeypatch, cible):
    """Métadonnées synthétiques ; pas de socket ni daemon créé."""
    monkeypatch.setattr(api, "_sans_liens", lambda p: None)

    def infos(path):
        dossier = str(path) == "/run/user/500"
        mode = stat.S_IFDIR | 0o700 if dossier else stat.S_IFSOCK | 0o600
        if (cible == "runtime" and dossier) or (cible == "socket" and not dossier):
            mode |= 0o007
        return os.stat_result([mode, 10, 20, 1, 500, 600, 0, 0, 0, 0])

    monkeypatch.setattr(api, "_metadata", infos)
    monkeypatch.setattr(api, "_commande", lambda *a, **kw: pytest.fail("aucune API"))
    with pytest.raises(api.RefusRootless):
        api._daemon({**profil, "uid": 500, "gid": 600})


def test_compose_reel_parse_overlay_sans_daemon(api, profil, tmp_path):
    import shutil

    if not shutil.which("docker"):
        pytest.skip("Docker CLI/Compose absent : aucune installation")
    version = subprocess.run(["docker", "compose", "version", "--short"], capture_output=True, text=True, check=False)
    if version.returncode:
        pytest.skip("Compose absent : aucune installation")
    api.verifier_version_compose(version.stdout.strip())
    api.generer(profil, tmp_path / "generated")
    fictif = tmp_path / "fictif.env"
    fictif.write_text("\n".join(f"{name}=secret-fictif-123456789012345678901234567890" for name in (
        "OPENCLAW_GATEWAY_TOKEN", "OPSYS_MCP_JETON", "OPSYS_CONTEXT_MCP_JETON", "OPSYS_CONSOLE_SECRET",
    )))
    run = subprocess.run([
        "docker", "compose", "--env-file", str(fictif), "--env-file", str(tmp_path / "generated/rootless.env"),
        "-f", str(ROOT / "deploy/docker-compose.yml"), "-f", str(ROOT / "deploy/docker-compose.rootless.yml"),
        "config", "--format", "json",
    ], capture_output=True, text=True, timeout=15, check=False)
    assert run.returncode == 0, run.stderr
    services = json.loads(run.stdout)["services"]
    gateway, python, caddy = (services[name] for name in ["openclaw-gateway", "opsys", "caddy"])
    assert gateway["build"]["args"]["OPENCLAW_INSTALL_DOCKER_CLI"] == "1"
    assert gateway["environment"]["DOCKER_HOST"] == "ssh://opsys-rootless-control"
    assert gateway["depends_on"]["opsys"]["condition"] == "service_healthy"
    assert {m["target"] for m in gateway["volumes"]} == {
        "/home/node/.openclaw", "/home/node/.config/openclaw", "/home/node/.ssh",
    }
    # Compose sérialise ce booléen false par omission ; l'overlay l'explicite sur chaque bind.
    assert (ROOT / "deploy/docker-compose.rootless.yml").read_text().count("create_host_path: false") == 6
    assert all(m["type"] == "bind" and m["bind"].get("create_host_path", False) is False for m in gateway["volumes"])
    assert next(m for m in gateway["volumes"] if m["target"] == "/home/node/.ssh")["read_only"]
    assert {p["published"] for p in caddy["ports"]} == {"8080", "8443"}
    assert all(p["host_ip"] == "127.0.0.1" for p in caddy["ports"])
    assert python["logging"]["driver"] == "local" and "options" not in python["logging"]
    assert python["build"]["args"]["OPSYS_RUNTIME_UID"] == "1000"
    assert python["healthcheck"] and gateway["healthcheck"]
    assert python.get("user") == gateway.get("user") == "1000:1000"
    assert python.get("security_opt") == gateway.get("security_opt") == ["no-new-privileges:true"]


@pytest.mark.parametrize("version", ["2.24.3", "1.29.2", "2.24", "unknown"])
def test_ancien_compose_refuse_remplacement_ambigu(api, version):
    with pytest.raises(api.RefusRootless, match="Compose"):
        api.verifier_version_compose(version)


def test_preflight_compose_ancien_refuse_avant_daemon(api, profil, monkeypatch):
    monkeypatch.setattr(api, "_version_compose", lambda: "2.24.3")
    monkeypatch.setattr(api, "_daemon", lambda p: pytest.fail("aucun appel API"))
    with pytest.raises(api.RefusRootless, match="Compose"):
        api.verifier(profil, GATEWAY, PYTHON)


@pytest.mark.parametrize("change", ["owner", "hardlink", "knownhost"])
def test_credential_namespace_prive_refuse(api, profil, observations, change):
    gateway = observations[2][10]
    if change == "owner":
        gateway["ssh"]["id_ed25519"]["uid"] = 0
    elif change == "hardlink":
        gateway["ssh"]["id_ed25519"]["nlink"] = 2
    else:
        gateway["known_hosts"] = "autre.example.test ssh-ed25519 AAAA\n"
    with pytest.raises(api.RefusRootless):
        api.verifier(profil, GATEWAY, PYTHON)



def test_cli_generation_et_refus_ne_dumpent_pas_observation(api, profil, tmp_path, monkeypatch, capsys):
    out = tmp_path / "cli"
    args = ["generer", "--sortie", str(out)]
    for name in ["racine", "ssh_dir", "daemon_id", "controleur", "utilisateur", "uid", "gid", "host_key_sha256"]:
        args.extend(["--" + name.replace("_", "-"), str(profil[name])])
    assert api.main(args) == 0
    assert json.loads(capsys.readouterr().out)["runtime_verifie"] is False

    def secret_error(*args):
        raise ValueError("SECRET-FICTIF-DU-DAEMON")

    monkeypatch.setattr(api, "_daemon", secret_error)
    assert api.main(["verifier", "--profil", str(out / "profil.json"),
                     "--gateway-id", GATEWAY, "--python-id", PYTHON]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "REJ-SERVEUR-ROOTLESS" in captured.err
    assert "SECRET-FICTIF" not in captured.err


def test_hote_ne_lit_jamais_credentials_ni_proc_pid(api, profil, observations, monkeypatch):
    old = api._lire_public
    def lecture(path, *args):
        assert Path(path).name not in {"id_ed25519", "config", "known_hosts"}
        assert not str(path).startswith("/proc/")
        return old(path, *args)
    monkeypatch.setattr(api, "_lire_public", lecture)
    result = api.verifier(profil, GATEWAY, PYTHON)
    assert result["preflight_verifie"] is True
    assert result["observation"] == "deux exec transitoires fixes sous UID1000"


@pytest.mark.parametrize("change", ["pid", "start", "identity"])
def test_recheck_conteneur_remplace_refuse(api, profil, observations, monkeypatch, change):
    original = api._inspect
    calls = 0

    def inspect(p, identity):
        nonlocal calls
        calls += 1
        result = json.loads(json.dumps(original(p, identity)))
        if calls == 3:
            if change == "pid":
                result["State"]["Pid"] += 1
            elif change == "start":
                result["State"]["StartedAt"] = "2026-10-02T00:00:00Z"
            else:
                result["Id"] = "f" * 64
        return result

    monkeypatch.setattr(api, "_inspect", inspect)
    with pytest.raises(api.RefusRootless, match="remplacé/redémarré"):
        api.verifier(profil, GATEWAY, PYTHON)
    assert calls == 3


def test_commande_native_fixe_sans_shell_sans_paths_credentials(api, profil, monkeypatch):
    recorded = []
    def run(argv, **kwargs):
        recorded.append(argv)
        return b'{"fictif":true}'
    monkeypatch.setattr(api, "_commande", run)
    assert api._probe(profil, GATEWAY, "openclaw-gateway") == {"fictif": True}
    assert api._probe(profil, PYTHON, "opsys") == {"fictif": True}
    assert [argv[7:9] for argv in recorded] == [["node", "-e"], ["python3", "-c"]]
    assert recorded[0][-2] == api.GATEWAY_PROBE and recorded[1][-1] == api.PYTHON_PROBE
    assert all(argv[4:6] == ["--user", "1000:1000"] for argv in recorded)
    assert all(profil["ssh_dir"] not in argv[-1] and "--privileged" not in argv for argv in recorded)


@pytest.mark.parametrize("change", ["proxy", "hostname", "fingerprint"])
def test_native_ssh_divergent_refuse_avant_runner(api, profil, change):
    expected = {"version": 2, "config": api.configuration_ssh(profil),
                "known_host": "controller.example.test", "host_key_sha256": HOST_KEY_SHA256}
    config = expected["config"]
    known = "controller.example.test ssh-ed25519 " + base64.b64encode(PUBLIC_KEY).decode() + "\n"
    if change == "proxy":
        config += "    ProxyCommand commande-fictive-interdite\n"
    elif change == "hostname":
        known = known.replace("controller.example.test", "etranger.example.test")
    else:
        different = PUBLIC_KEY[:-32] + b"x" * 32
        known = "controller.example.test ssh-ed25519 " + base64.b64encode(different).decode() + "\n"
    script = api.NODE_HELPERS + (
        "if(typeof dockerInfoVerified!=='function')process.exit(3);"
        "let calls=0, refused=false; const runner=()=>{calls++;throw Error('runner-interdit')};"
        "try{dockerInfoVerified(" + json.dumps(expected) + "," + json.dumps(config) + ","
        + json.dumps(known) + ",runner)}catch(_){refused=true}"
        "process.stdout.write(JSON.stringify({calls,refused}));"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"calls": 0, "refused": True}


def test_native_ssh_conforme_autorise_un_runner(api, profil):
    expected = {"version": 2, "config": api.configuration_ssh(profil),
                "known_host": "controller.example.test", "host_key_sha256": HOST_KEY_SHA256}
    known = "controller.example.test ssh-ed25519 " + base64.b64encode(PUBLIC_KEY).decode() + "\n"
    script = api.NODE_HELPERS + (
        "if(typeof dockerInfoVerified!=='function')process.exit(3); let calls=0;"
        "const runner=()=>{calls++;return {status:0,stdout:JSON.stringify({ID:'fictif-conforme'})}};"
        "const result=dockerInfoVerified(" + json.dumps(expected) + "," + json.dumps(expected["config"])
        + "," + json.dumps(known) + ",runner); process.stdout.write(JSON.stringify({calls,result}));"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"calls": 1, "result": {"ID": "fictif-conforme"}}


def test_profil_invalide_refuse_avant_construction_argv(api, profil):
    with pytest.raises(api.RefusRootless):
        api.commande_probe({**profil, "utilisateur": "root"}, GATEWAY, "openclaw-gateway")
    ancien = {key: value for key, value in profil.items() if key != "host_key_sha256"}
    ancien["version"] = 1
    with pytest.raises(api.RefusRootless, match="schéma"):
        api.valider_profil(ancien)


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() != 1000 or getattr(os, "getegid", lambda: -1)() != 1000,
    reason="oracle réel Linux UID/GID1000",
)
def test_helper_node_reel_ouvre_cle600_sans_lire_contenu(api, tmp_path):
    """Node réel UID1000, sans Docker : preuve d'accès noyau dans son namespace actuel."""
    ssh = tmp_path / "controller"
    ssh.mkdir(mode=0o700)
    key = ssh / "id_ed25519"
    key.write_text("SECRET-FICTIF-NE-PAS-INGERER")
    key.chmod(0o600)
    script = api.NODE_HELPERS + (
        "const key=" + json.dumps(str(key)) + "; const read=fs.readSync;"
        "fs.readSync=(fd,...args)=>{if(fs.readlinkSync('/proc/self/fd/'+fd)===key)"
        "throw Error('cle-ingeree');return read(fd,...args)};"
        "process.stdout.write(JSON.stringify({euid:process.geteuid(),root:metadata("
        + json.dumps(str(ssh)) + ",true),key:metadata(key,false)}));"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["euid"] == 1000 and result["key"]["uid"] == 1000
    assert result["key"]["mode"] == 0o600 and result["root"]["mode"] == 0o700
    assert "SECRET-FICTIF" not in run.stdout


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() != 1000 or getattr(os, "getegid", lambda: -1)() != 1000,
    reason="oracle réel Linux UID/GID1000",
)
@pytest.mark.parametrize("runtime", ["node", "python"])
def test_helper_reel_refuse_dossier000_sans_reparation(api, tmp_path, runtime):
    path = tmp_path / "interdit"
    path.mkdir(mode=0o700)
    path.chmod(0o000)
    try:
        if runtime == "node":
            argv = ["node", "-e", api.NODE_HELPERS + "metadata(" + json.dumps(str(path)) + ",true)"]
        else:
            argv = [os.sys.executable, "-c", api.PYTHON_HELPERS + "\nmetadata(" + repr(str(path)) + ")"]
        run = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
        assert run.returncode != 0 and stat.S_IMODE(path.stat().st_mode) == 0o000
    finally:
        path.chmod(0o700)  # fixture seulement, pour son nettoyage


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() != 1000 or getattr(os, "getegid", lambda: -1)() != 1000,
    reason="oracle réel Linux UID/GID1000",
)
def test_helper_python_reel_metadata700(api, tmp_path):
    path = tmp_path / "data"
    path.mkdir(mode=0o700)
    run = subprocess.run([
        os.sys.executable, "-c", api.PYTHON_HELPERS + "\nprint(json.dumps(metadata(" + repr(str(path)) + ")))",
    ], capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["uid"] == result["gid"] == 1000 and result["mode"] == 0o700


def test_helper_docker_cli_env_borne_depuis_gateway_fictif(api, tmp_path):
    """Node/helper réels ; binaire Docker remplacé par processus factice, aucun SSH/Docker."""
    fake = tmp_path / "docker-fictif.cjs"
    fake.write_text("process.stdout.write(JSON.stringify({ID:'daemon-fictif',argv:process.argv.slice(2),env:process.env}));")
    script = api.NODE_HELPERS + (
        "const runner=(cmd,args,opts)=>{if(cmd!=='/usr/bin/docker')throw Error('command');"
        "return cp.spawnSync(process.execPath,[" + json.dumps(str(fake)) + ",...args],opts)};"
        "process.stdout.write(JSON.stringify(dockerInfo(runner)));"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["argv"] == ["--host", "ssh://opsys-rootless-control", "info", "--format", "{{json .}}"]
    assert result["env"]["HOME"] == "/home/node" and result["env"]["DOCKER_HOST"] == "ssh://opsys-rootless-control"
    assert result["env"]["DOCKER_CONTEXT"] == result["env"]["SSH_AUTH_SOCK"] == ""
    assert "OPENAI_API_KEY" not in result["env"]


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: -1)() != 1000 or getattr(os, "getegid", lambda: -1)() != 1000,
    reason="oracle réel Linux UID/GID1000",
)
def test_helper_bind_ssh_ro_demande_rx_seulement(api, tmp_path):
    path = tmp_path / "controller"
    path.mkdir(mode=0o700)
    script = api.NODE_HELPERS + (
        "const access=fs.accessSync; const modes=[]; fs.accessSync=(file,mode)=>{modes.push(mode);access(file,mode)};"
        "metadata(" + json.dumps(str(path)) + ",true,false); process.stdout.write(JSON.stringify(modes));"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [os.R_OK | os.X_OK]  # RO conservé, pas de demande W_OK
    assert 'metadata(file,true,file !== "/home/node/.ssh")' in api.GATEWAY_PROBE


@pytest.mark.parametrize("service", [GATEWAY, PYTHON])
def test_init_root_refuse_meme_si_helper_uid1000(api, profil, observations, service):
    pid = observations[1][service]["State"]["Pid"]
    observations[2][pid]["principal"] = {"uid": [0] * 4, "gid": [0] * 4}
    with pytest.raises(api.RefusRootless, match="PID1"):
        api.verifier(profil, GATEWAY, PYTHON)


@pytest.mark.parametrize("service", [GATEWAY, PYTHON])
def test_image_user_different_refuse_avant_probe(api, profil, observations, service):
    observations[1][service]["Config"]["User"] = "root"
    with pytest.raises(api.RefusRootless, match="User"):
        api.verifier(profil, GATEWAY, PYTHON)


def test_scripts_probes_complets_syntaxe_native(api):
    run = subprocess.run(["node", "--check", "-"], input=api.GATEWAY_PROBE,
                         capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    assert compile(api.PYTHON_PROBE, "probe-python-fixe", "exec")


@pytest.mark.parametrize("runtime", ["node", "python"])
def test_helpers_lisent_pid1_et_cgroup_propre_namespace(api, runtime):
    """Lectures noyau réelles ici, sans certifier ce namespace comme rootless."""
    status = Path("/proc/1/status").read_text()
    expected = {"uid" if row.startswith("Uid:") else "gid": [int(x) for x in row.split()[1:]]
                for row in status.splitlines() if row.startswith(("Uid:", "Gid:"))}
    row = Path("/proc/self/cgroup").read_text().strip().split(":", 2)
    assert row[:2] == ["0", ""]
    root = Path("/sys/fs/cgroup") / row[2].lstrip("/")
    limits = {name: (root / name).read_text().strip() for name in ["memory.max", "pids.max", "cpu.max"]}
    if runtime == "node":
        argv = ["node", "-e", api.NODE_HELPERS +
                "process.stdout.write(JSON.stringify({principal:principal(),limites:cgroupLimits()}));"]
    else:
        argv = [os.sys.executable, "-c", api.PYTHON_HELPERS +
                "\nprint(json.dumps(dict(principal=principal(),limites=cgroup_limits())))"]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"principal": expected, "limites": limits}
