"""Configuration rootless et préflight en lecture seule ; aucun provisionnement Docker."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from pathlib import Path

CHAMPS = {
    "version", "racine", "ssh_dir", "daemon_id", "controleur", "utilisateur", "uid", "gid",
    "ssh_port", "port_http", "port_https", "host_key_sha256",
}
LIMITE = 1024 * 1024
ALIAS = "opsys-rootless-control"

# Ces helpers n'acceptent aucun chemin/commande fourni par l'appelant du préflight.
# Les fonctions sont séparées du main fixe pour les oracles fichiers temporaires.
NODE_HELPERS = r'''
const fs = require("node:fs"), path = require("node:path"), cp = require("node:child_process");
function readPublic(file, privateFile = false) {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const s = fs.fstatSync(fd);
    if (!s.isFile() || (privateFile && (s.uid !== 1000 || s.gid !== 1000 ||
        (s.mode & 0o7777) !== 0o600 || s.nlink !== 1 || s.size <= 0 || s.size > 16384)))
      throw Error("public-file");
    const buf = Buffer.alloc(16385); let n = 0, count;
    while (n < buf.length && (count = fs.readSync(fd, buf, n, buf.length - n, null)) > 0) n += count;
    if (n > 16384) throw Error("public-file-size");
    return buf.subarray(0, n).toString("utf8");
  } finally { fs.closeSync(fd); }
}
function metadata(file, directory, writable = true) {
  for (let p = file; ; p = path.dirname(p)) {
    if (fs.lstatSync(p).isSymbolicLink()) throw Error("symlink");
    if (p === "/") break;
  }
  const s = fs.lstatSync(file, {bigint: true});
  if ((directory ? !s.isDirectory() : !s.isFile()) || s.uid !== 1000n || s.gid !== 1000n ||
      Number(s.mode & 0o7777n) !== (directory ? 0o700 : 0o600)) throw Error("private-mode-owner");
  const access = directory ? fs.constants.R_OK | fs.constants.X_OK |
                            (writable ? fs.constants.W_OK : 0) : fs.constants.R_OK;
  fs.accessSync(file, access);
  if (!directory) {
    if (s.nlink !== 1n || s.size <= 0n || s.size > 16384n) throw Error("private-file");
    // Contrôle noyau de lecture, sans ingérer la clé.
    const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW); fs.closeSync(fd);
  }
  return {uid:Number(s.uid), gid:Number(s.gid), mode:Number(s.mode & 0o7777n),
          kind:directory ? "dir" : "file", nlink:Number(s.nlink), size:String(s.size),
          dev:String(s.dev), ino:String(s.ino)};
}
function cgroupLimits() {
  const rows = readPublic("/proc/self/cgroup").trim().split("\n").map(x => x.split(":"));
  if (rows.length !== 1 || rows[0].length !== 3 || rows[0][0] !== "0" || rows[0][1] !== "" ||
      !rows[0][2].startsWith("/") || rows[0][2].split("/").includes("..")) throw Error("cgroup");
  const root = "/sys/fs/cgroup" + (rows[0][2] === "/" ? "" : rows[0][2]);
  return Object.fromEntries(["memory.max", "pids.max", "cpu.max"].map(name => [name,readPublic(root+"/"+name).trim()]));
}
function dockerInfo(runner = cp.spawnSync) {
  const env = {PATH:"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", HOME:"/home/node",
    LANG:"C.UTF-8", DOCKER_HOST:"ssh://opsys-rootless-control", DOCKER_CONTEXT:"",
    DOCKER_TLS_VERIFY:"", DOCKER_CERT_PATH:"", SSH_AUTH_SOCK:""};
  const r = runner("/usr/bin/docker", ["--host", "ssh://opsys-rootless-control", "info", "--format", "{{json .}}"],
                   {env,encoding:"utf8",timeout:15000,maxBuffer:1024*1024});
  if (r.status !== 0 || r.error) throw Error("docker-ssh");
  return JSON.parse(r.stdout);
}
function dockerInfoVerified(expected, config, known, runner = cp.spawnSync) {
  if (!expected || Array.isArray(expected) || expected.version !== 2 ||
      Object.keys(expected).sort().join(",") !== "config,host_key_sha256,known_host,version" ||
      typeof expected.config !== "string" || expected.config.length > 4096 ||
      !expected.config.startsWith("Host opsys-rootless-control\n") ||
      /^\s*(ProxyCommand|ProxyJump|Include|Match|LocalCommand|PermitLocalCommand|KnownHostsCommand)\s/im
        .test(expected.config) ||
      typeof expected.known_host !== "string" || expected.known_host.length > 265 ||
      typeof expected.host_key_sha256 !== "string" || !/^SHA256:[A-Za-z0-9+/]{43}$/.test(expected.host_key_sha256))
    throw Error("expected-data");
  if (config !== expected.config || typeof known !== "string" || known.length > 16384)
    throw Error("ssh-config-divergent");
  const fields = known.trim().split(/\s+/);
  if (fields.length !== 3 || fields[0] !== expected.known_host || fields[1] !== "ssh-ed25519" ||
      !/^[A-Za-z0-9+/]{68}$/.test(fields[2])) throw Error("ssh-known-host");
  const data = Buffer.from(fields[2],"base64");
  if (data.length !== 51 || !data.subarray(0,19).equals(Buffer.from("0000000b7373682d6564323535313900000020","hex")))
    throw Error("ssh-public-key");
  const pin = "SHA256:" + require("node:crypto").createHash("sha256").update(data).digest("base64").replace(/=+$/,"");
  if (pin !== expected.host_key_sha256) throw Error("ssh-fingerprint");
  return dockerInfo(runner);  // exclusivement après les trois comparaisons
}
function principal() {
  const result = {};
  for (const row of readPublic("/proc/1/status").split("\n")) {
    const fields = row.trim().split(/\s+/);
    if (fields[0] === "Uid:" || fields[0] === "Gid:") {
      if (fields.length !== 5 || !fields.slice(1).every(x => /^\d+$/.test(x))) throw Error("pid1");
      result[fields[0] === "Uid:" ? "uid" : "gid"] = fields.slice(1).map(Number);
    }
  }
  return result;
}
'''

GATEWAY_PROBE = NODE_HELPERS + r'''
try {
  if (process.argv.length !== 2 || Buffer.byteLength(process.argv[1],"utf8") > 8192)
    throw Error("expected-data-size");
  const expected = JSON.parse(process.argv[1]);
  if (process.geteuid() !== 1000 || process.getegid() !== 1000 ||
      require("node:os").userInfo().homedir !== "/home/node" || process.env.HOME !== "/home/node")
    throw Error("gateway-user-home");
  const mounts = Object.fromEntries(["/home/node/.openclaw", "/home/node/.config/openclaw", "/home/node/.ssh"]
                                    .map(file => [file, metadata(file,true,file !== "/home/node/.ssh")]));
  const ssh = Object.fromEntries(["id_ed25519", "known_hosts", "config"]
                                 .map(name => [name, metadata("/home/node/.ssh/"+name,false)]));
  const config = readPublic("/home/node/.ssh/config",true);
  const known_hosts = readPublic("/home/node/.ssh/known_hosts",true);
  const daemon_ssh = dockerInfoVerified(expected,config,known_hosts);
  process.stdout.write(JSON.stringify({euid:process.geteuid(), egid:process.getegid(), home:"/home/node",
    uid_map:readPublic("/proc/self/uid_map"), gid_map:readPublic("/proc/self/gid_map"), mounts, ssh,
    limites:cgroupLimits(), principal:principal(), config, known_hosts, daemon_ssh}));
} catch (_) { process.stderr.write("REJ-SERVEUR-ROOTLESS namespace Gateway inaccessible\n"); process.exit(2); }
'''

PYTHON_HELPERS = r'''
import json, os, stat, sys
from pathlib import Path
def read_public(file):
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("public-file")
        data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError("public-file-size")
        return data.decode()
def metadata(file, directory=True):
    file = Path(file)
    for part in [file, *file.parents]:
        if stat.S_ISLNK(os.lstat(part).st_mode):
            raise ValueError("symlink")
    s = os.lstat(file)
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != 1000 or s.st_gid != 1000 or stat.S_IMODE(s.st_mode) != 0o700:
        raise ValueError("private-mode-owner")
    if not os.access(file, os.R_OK | os.W_OK | os.X_OK, effective_ids=True):
        raise ValueError("kernel-access")
    return dict(uid=s.st_uid, gid=s.st_gid, mode=stat.S_IMODE(s.st_mode), kind="dir",
                dev=str(s.st_dev), ino=str(s.st_ino))
def principal():
    result = {}
    for row in read_public("/proc/1/status").splitlines():
        fields = row.split()
        if fields and fields[0] in ("Uid:", "Gid:"):
            if len(fields) != 5 or any(not x.isdecimal() for x in fields[1:]):
                raise ValueError("pid1")
            result["uid" if fields[0] == "Uid:" else "gid"] = [int(x) for x in fields[1:]]
    return result
def cgroup_limits():
    rows = [row.split(":") for row in read_public("/proc/self/cgroup").strip().splitlines()]
    if len(rows) != 1 or len(rows[0]) != 3 or rows[0][:2] != ["0", ""]:
        raise ValueError("cgroup")
    relative = Path(rows[0][2])
    if not relative.is_absolute() or ".." in relative.parts:
        raise ValueError("cgroup")
    root = Path("/sys/fs/cgroup") / str(relative).lstrip("/")
    return {name: read_public(root / name).strip() for name in ["memory.max", "pids.max", "cpu.max"]}
'''

PYTHON_PROBE = PYTHON_HELPERS + r'''
try:
    if os.geteuid() != 1000 or os.getegid() != 1000:
        raise ValueError("python-user")
    mounts = {file: metadata(file) for file in ["/opt/data", "/openclaw-config", "/shared/litellm-config"]}
    print(json.dumps(dict(euid=os.geteuid(), egid=os.getegid(), mounts=mounts,
        limites=cgroup_limits(), principal=principal(),
        uid_map=read_public("/proc/self/uid_map"), gid_map=read_public("/proc/self/gid_map"))))
except Exception:
    print("REJ-SERVEUR-ROOTLESS namespace Python inaccessible", file=sys.stderr)
    raise SystemExit(2)
'''


class RefusRootless(ValueError):
    """Le profil ne peut pas être validé sans intervention explicite de l'opérateur."""


def _refus(raison: str) -> None:
    raise RefusRootless(f"REJ-SERVEUR-ROOTLESS : {raison}")


def valider_profil(profil: dict) -> dict:
    if (
        not isinstance(profil, dict) or set(profil) != CHAMPS
        or type(profil["version"]) is not int or profil["version"] != 2
    ):
        _refus("schéma de profil inconnu")
    pin = profil["host_key_sha256"]
    if not isinstance(pin, str) or not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", pin):
        _refus("empreinte publique hôte OpenSSH SHA256 requise")
    digest = base64.b64decode(pin[7:] + "=", validate=True)
    if len(digest) != 32 or base64.b64encode(digest).decode().rstrip("=") != pin[7:]:
        _refus("empreinte publique hôte non canonique")
    for name in ("uid", "gid", "ssh_port", "port_http", "port_https"):
        value = profil[name]
        maximum = 2**31 - 1 if name in {"uid", "gid"} else 65535
        minimum = 1024 if name in {"port_http", "port_https"} else 1
        if type(value) is not int or not minimum <= value <= maximum:
            _refus("identité ou port invalide")
    if profil["port_http"] == profil["port_https"]:
        _refus("ports distincts requis")
    if not isinstance(profil["daemon_id"], str) or not re.fullmatch(r"[A-Za-z0-9:_-]{12,128}", profil["daemon_id"]):
        _refus("identité daemon invalide")
    host = profil["controleur"]
    if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(
        r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host
    ) or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split(".")):
        _refus("hôte contrôleur attendu, sans URL ni commande")
    if not isinstance(profil["utilisateur"], str) or profil["utilisateur"] == "root" or not re.fullmatch(
        r"[a-z_][a-z0-9_-]{0,31}", profil["utilisateur"]
    ):
        _refus("utilisateur SSH invalide")
    for name in ("racine", "ssh_dir"):
        value = profil[name]
        if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            _refus("chemin absolu simple requis")
        path = Path(value)
        if value != str(path) or ".." in path.parts or len(path.parts) < 3:
            _refus("chemin non canonique ou trop large")
    left, right = Path(profil["racine"]), Path(profil["ssh_dir"])
    if left == right or left in right.parents or right in left.parents:
        _refus("state et credentials SSH doivent être séparés")
    return dict(profil)


def creer_profil(*, racine: str, ssh_dir: str, daemon_id: str, controleur: str,
                 utilisateur: str, uid: int, gid: int, host_key_sha256: str, ssh_port: int = 22,
                 port_http: int = 8080, port_https: int = 8443) -> dict:
    return valider_profil({
        "version": 2, "racine": racine, "ssh_dir": ssh_dir, "daemon_id": daemon_id,
        "controleur": controleur, "utilisateur": utilisateur, "uid": uid, "gid": gid,
        "ssh_port": ssh_port, "port_http": port_http, "port_https": port_https,
        "host_key_sha256": host_key_sha256,
    })


def binds(profil: dict) -> dict[str, str]:
    return {name: str(Path(profil["racine"]) / name)
            for name in ("core-state", "core-auth", "opsys-data", "litellm-config")}


def configuration_ssh(profil: dict) -> str:
    valider_profil(profil)
    return (
        f"Host {ALIAS}\n    HostName {profil['controleur']}\n    User {profil['utilisateur']}\n"
        f"    Port {profil['ssh_port']}\n    IdentityFile /home/node/.ssh/id_ed25519\n"
        "    UserKnownHostsFile /home/node/.ssh/known_hosts\n    StrictHostKeyChecking yes\n"
        "    HostKeyAlgorithms ssh-ed25519\n    ControlMaster no\n    ControlPath none\n"
        "    IdentitiesOnly yes\n    IdentityAgent none\n    ForwardAgent no\n    ForwardX11 no\n"
        "    ClearAllForwardings yes\n    RequestTTY no\n    BatchMode yes\n"
        "    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n    ConnectTimeout 5\n"
    )


def generer(profil: dict, sortie: Path) -> dict:
    profil = valider_profil(profil)
    paths = binds(profil)
    if sortie.exists() or sortie.is_symlink():
        _refus("sortie existante ; aucune réécriture")
    # Seuls les trois fichiers explicitement demandés, jamais les binds ni les clés.
    sortie.mkdir(mode=0o700, parents=False)
    contenus = {
        "profil.json": json.dumps(profil, indent=2, ensure_ascii=False) + "\n",
        "rootless.env": "\n".join([
            f"OPSYS_ROOTLESS_STATE={paths['core-state']}", f"OPSYS_ROOTLESS_AUTH={paths['core-auth']}",
            f"OPSYS_ROOTLESS_DATA={paths['opsys-data']}", f"OPSYS_ROOTLESS_LITELLM={paths['litellm-config']}",
            f"OPSYS_ROOTLESS_SSH={profil['ssh_dir']}", f"OPSYS_ROOTLESS_HTTP_PORT={profil['port_http']}",
            f"OPSYS_ROOTLESS_HTTPS_PORT={profil['port_https']}", "",
        ]),
        "ssh-config": configuration_ssh(profil),
    }
    for name, contenu in contenus.items():
        with os.fdopen(os.open(sortie / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            file.write(contenu)
    return {"generation": "disponible", "runtime_verifie": False, "fichiers": list(contenus)}


def verifier_version_compose(version: str) -> None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?", version)
    if not match or tuple(int(n) for n in match.groups()) < (2, 24, 4):
        _refus("Compose >= 2.24.4 requis pour !override")


def _version_compose() -> str:
    return _commande(["docker", "compose", "version", "--short"], limite=1024).decode().strip()


def _commande(argv: list[str], *, entree: bytes | None = None, limite: int = LIMITE, delai: int = 15) -> bytes:
    """Capture bornée ; ne restitue jamais la sortie brute d'un échec."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCKER_") and k != "SSH_AUTH_SOCK"}
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if entree is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    try:
        if entree is not None:
            process.stdin.write(entree)
            process.stdin.close()
        deadline = time.monotonic() + delai
        result = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                left = deadline - time.monotonic()
                if left <= 0:
                    _refus("délai de lecture dépassé")
                for key, _ in selector.select(left):
                    block = os.read(key.fd, min(65536, limite + 1 - len(result)))
                    result.extend(block)
                    if len(result) > limite:
                        _refus("sortie de contrôle trop grande")
                    if not block:
                        selector.unregister(key.fileobj)
        if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
            _refus("commande de lecture refusée ou inaccessible")
        return bytes(result)
    finally:
        if process.poll() is None:
            process.kill()  # seulement le client de lecture lancé ici, jamais un service
        process.wait()
        process.stdout.close()


def _daemon(profil: dict) -> dict:
    socket = Path(f"/run/user/{profil['uid']}/docker.sock")
    _sans_liens(socket)
    runtime = _metadata(socket.parent)
    if not stat.S_ISDIR(runtime.st_mode) or runtime.st_uid != profil["uid"] or stat.S_IMODE(runtime.st_mode) != 0o700:
        _refus("répertoire runtime rootless privé700 attendu")
    info = _metadata(socket)
    if not stat.S_ISSOCK(info.st_mode) or (info.st_uid, info.st_gid) != (profil["uid"], profil["gid"]) or (
        stat.S_IMODE(info.st_mode) not in (0o600, 0o660)
    ):
        _refus("socket rootless privé attendu")
    return json.loads(_commande(["docker", "--host", f"unix://{socket}", "info", "--format", "{{json .}}"] ))


def _inspect(profil: dict, identity: str) -> dict:
    data = json.loads(_commande([
        "docker", "--host", f"unix:///run/user/{profil['uid']}/docker.sock", "inspect",
        "--type", "container", identity,
    ]))
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        _refus("inspection de conteneur inconnue")
    return data[0]


def commande_probe(profil: dict, identity: str, service: str) -> list[str]:
    profil = valider_profil(profil)
    if not re.fullmatch(r"[a-f0-9]{64}", identity):
        _refus("identité de probe invalide")
    if service == "openclaw-gateway":
        runtime, flag, script = "node", "-e", GATEWAY_PROBE
    elif service == "opsys":
        runtime, flag, script = "python3", "-c", PYTHON_PROBE
    else:
        _refus("probe de service inconnu")
    argv = ["docker", "--host", f"unix:///run/user/{profil['uid']}/docker.sock", "exec",
            "--user", "1000:1000", identity, runtime, flag, script]
    if service == "openclaw-gateway":
        host = profil["controleur"] if profil["ssh_port"] == 22 else f"[{profil['controleur']}]:{profil['ssh_port']}"
        expected = json.dumps({"version": 2, "config": configuration_ssh(profil), "known_host": host,
                               "host_key_sha256": profil["host_key_sha256"]}, separators=(",", ":"))
        if len(expected.encode()) > 8192:
            _refus("données de comparaison trop grandes")
        argv.append(expected)
    return argv


def _probe(profil: dict, identity: str, service: str) -> dict:
    result = json.loads(_commande(commande_probe(profil, identity, service), delai=20))
    if not isinstance(result, dict):
        _refus("observation de namespace inconnue")
    return result


def _metadata(path: Path) -> os.stat_result:
    return os.lstat(path)


def _sans_liens(path: Path) -> None:
    for parent in reversed([path, *path.parents]):
        if stat.S_ISLNK(_metadata(parent).st_mode):
            _refus("lien sur un chemin de contrôle")


def _lire_public(path: Path, limite: int = 16384) -> str:
    # Ne sert jamais à lire id_ed25519 ; ces fichiers sont profils/config/known_hosts/proc.
    with path.open("rb") as file:
        data = file.read(limite + 1)
    if len(data) > limite:
        _refus("fichier public trop grand")
    return data.decode("utf-8")


def _mapper(data: str, inside: int) -> int:
    ranges = []
    for line in data.splitlines():
        row = line.split()
        if len(row) != 3 or any(not v.isdecimal() for v in row):
            _refus("mapping UID/GID illisible")
        start, outside, count = (int(v) for v in row)
        if count <= 0 or any(
            (start < s + n and s < start + count) or (outside < o + n and o < outside + count)
            for s, o, n in ranges
        ):
            _refus("mapping UID/GID ambigu")
        ranges.append((start, outside, count))
    matches = [outside + inside - start for start, outside, count in ranges if start <= inside < start + count]
    if len(matches) != 1:
        _refus("UID/GID1000 non mappé")
    return matches[0]


def _verifier_daemon(profil: dict, info: dict) -> None:
    if not isinstance(info, dict) or info.get("ID") != profil["daemon_id"]:
        _refus("daemon différent du profil autorisé")
    if "name=rootless" not in info.get("SecurityOptions", []):
        _refus("daemon rootful ou rootless non prouvé")
    if info.get("CgroupVersion") != "2" or info.get("CgroupDriver") != "systemd" or any(
        info.get(name) is not True for name in ("MemoryLimit", "PidsLimit", "CpuCfsQuota")
    ):
        _refus("cgroup2/systemd et limites mémoire/CPU/PID requis")


def _prive(path: Path, uid: int, gid: int, *, dossier: bool) -> None:
    _sans_liens(path)
    info = _metadata(path)
    kind = stat.S_ISDIR if dossier else stat.S_ISREG
    if not kind(info.st_mode) or (info.st_uid, info.st_gid) != (uid, gid):
        _refus("propriétaire ou type d'un bind/credential incompatible avec UID1000 mappé")
    if stat.S_IMODE(info.st_mode) != (0o700 if dossier else 0o600):
        _refus("modes privés700/600 requis, aucune réparation automatique")
    if not dossier and (info.st_nlink != 1 or not 0 < info.st_size <= 16384):
        _refus("credential/config non exclusif ou non borné")


def verifier(profil: dict, gateway_id: str, python_id: str) -> dict:
    """Préflight : info/inspect hôte puis deux exec fixes en lecture, sans écriture durable."""
    profil = valider_profil(profil)
    if sys.platform != "linux":
        _refus("préflight serveur rootless Linux uniquement")
    if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in (gateway_id, python_id)) or gateway_id == python_id:
        _refus("deux identifiants complets de conteneurs vivants requis")
    if (os.geteuid(), os.getegid()) != (profil["uid"], profil["gid"]):
        _refus("opérateur rootless UID/GID du profil requis ; aucune élévation")
    verifier_version_compose(_version_compose())
    _verifier_daemon(profil, _daemon(profil))
    paths = binds(profil)
    attendus = {
        "openclaw-gateway": {
            "/home/node/.openclaw": (paths["core-state"], True),
            "/home/node/.config/openclaw": (paths["core-auth"], True),
            "/home/node/.ssh": (profil["ssh_dir"], False),
        },
        "opsys": {
            "/opt/data": (paths["opsys-data"], True), "/openclaw-config": (paths["core-state"], True),
            "/shared/litellm-config": (paths["litellm-config"], True),
        },
    }
    mapped = []
    projects = []
    etats = {}
    probes = {}
    for identity, service in ((gateway_id, "openclaw-gateway"), (python_id, "opsys")):
        container = _inspect(profil, identity)
        state, config, host = (container.get(name, {}) for name in ("State", "Config", "HostConfig"))
        pid = state.get("Pid")
        if container.get("Id") != identity or state.get("Running") is not True or type(pid) is not int or pid <= 0:
            _refus("conteneur non vivant ou identité différente")
        if config.get("Labels", {}).get("com.docker.compose.service") != service:
            _refus("service Compose inattendu")
        if config.get("User") != "1000:1000":
            _refus("Config.User1000:1000 requis")
        project = config.get("Labels", {}).get("com.docker.compose.project")
        if not isinstance(project, str) or not project:
            _refus("projet Compose absent")
        projects.append(project)
        if not isinstance(state.get("StartedAt"), str) or not state["StartedAt"]:
            _refus("instant de démarrage absent")
        etats[identity] = (pid, state["StartedAt"])
        if host.get("Privileged") is not False or host.get("NetworkMode") == "host" or host.get("UsernsMode") == "host":
            _refus("mode privilégié/host incompatible")
        memory = 2 * 1024**3 if service == "openclaw-gateway" else 512 * 1024**2
        if host.get("Memory") != memory or host.get("PidsLimit") != 256 or host.get("NanoCpus") != 2_000_000_000:
            _refus("limites du profil non appliquées")
        if not any(v in host.get("SecurityOpt", []) for v in ("no-new-privileges", "no-new-privileges:true")):
            _refus("no-new-privileges absent")
        if host.get("Tmpfs"):
            _refus("tmpfs non déclaré pouvant masquer une cible")
        if service == "openclaw-gateway":
            env = dict(row.split("=", 1) for row in config.get("Env", []) if "=" in row)
            if env.get("HOME") != "/home/node":
                _refus("HOME Gateway distinct du contrôleur SSH privé")
            if env.get("DOCKER_HOST") != f"ssh://{ALIAS}" or any(
                env.get(key) != "" for key in (
                    "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SSH_AUTH_SOCK",
                )
            ):
                _refus("transport Docker/SSH différent du profil")
        actual = {}
        for mount in container.get("Mounts", []):
            dest = mount.get("Destination")
            if mount.get("Type") != "bind" or dest in actual or type(mount.get("RW")) is not bool:
                _refus("binds privés exacts requis")
            actual[dest] = (mount.get("Source"), mount["RW"])
        if actual != attendus[service]:
            _refus("bind supplémentaire, volume nommé ou source inattendue")
        process = _probe(profil, identity, service)
        probes[service] = process
        if process.get("principal") != {"uid": [1000] * 4, "gid": [1000] * 4}:
            _refus("UID/GID réels/effectifs/sauvegardés/fs de PID1 différents de1000")
        limits = process.get("limites", {})
        cpu = limits.get("cpu.max", "").split()
        if limits.get("memory.max") != str(memory) or limits.get("pids.max") != "256" or (
            len(cpu) != 2 or any(not value.isdecimal() for value in cpu)
            or int(cpu[1]) <= 0 or int(cpu[0]) != 2 * int(cpu[1])
        ):
            _refus("limites cgroup2 réelles différentes du profil")
        uid, gid = _mapper(process["uid_map"], 1000), _mapper(process["gid_map"], 1000)
        if _mapper(process["uid_map"], 0) != profil["uid"] or _mapper(process["gid_map"], 0) != profil["gid"]:
            _refus("namespace étranger au compte rootless")
        if uid in (0, profil["uid"]) or gid in (0, profil["gid"]) or (process["euid"], process["egid"]) != (1000, 1000):
            _refus("écrivain différent de UID/GID1000 mappé")
        mapped.append((uid, gid))
        for dest, (source, _) in actual.items():
            path = Path(source)
            _prive(path, uid, gid, dossier=True)
            info = _metadata(path)
            inside = process["mounts"].get(dest, {})
            if (inside.get("uid"), inside.get("gid"), inside.get("mode"), inside.get("kind")) != (
                1000, 1000, 0o700, "dir"
            ):
                _refus("bind non privé dans le namespace de son écrivain")
            if (inside.get("dev"), inside.get("ino")) != (str(info.st_dev), str(info.st_ino)):
                _refus("bind du processus différent de Docker inspect")
    if mapped[0] != mapped[1]:
        _refus("Python et Core ne partagent pas le mapping UID/GID1000")
    if projects[0] != projects[1]:
        _refus("Python et Core appartiennent à des projets Compose différents")
    gateway = probes["openclaw-gateway"]
    if gateway.get("home") != "/home/node":
        _refus("HOME effectif du contrôleur différent")
    for name in ("id_ed25519", "known_hosts", "config"):
        info = gateway.get("ssh", {}).get(name, {})
        if (info.get("uid"), info.get("gid"), info.get("mode"), info.get("kind"), info.get("nlink")) != (
            1000, 1000, 0o600, "file", 1
        ) or not str(info.get("size", "")).isdecimal() or not 0 < int(info["size"]) <= 16384:
            _refus("credential/config non privé dans le Gateway")
    if gateway.get("config") != configuration_ssh(profil):
        _refus("configuration SSH modifiée ; aucun forwarding permis")
    known = gateway.get("known_hosts", "").split()
    host = profil["controleur"] if profil["ssh_port"] == 22 else f"[{profil['controleur']}]:{profil['ssh_port']}"
    if len(known) != 3 or known[:2] != [host, "ssh-ed25519"]:
        _refus("clé hôte contrôleur unique et connue requise")
    data = base64.b64decode(known[2], validate=True)
    if len(data) != 51 or data[:19] != b"\0\0\0\x0bssh-ed25519\0\0\0\x20":
        _refus("clé hôte ed25519 invalide")
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
    if fingerprint != profil["host_key_sha256"]:
        _refus("empreinte publique hôte différente du profil épinglé")
    _verifier_daemon(profil, gateway.get("daemon_ssh"))
    for identity, expected in etats.items():
        latest = _inspect(profil, identity)
        state = latest.get("State", {})
        if latest.get("Id") != identity or state.get("Running") is not True or (
            state.get("Pid"), state.get("StartedAt")
        ) != expected:
            _refus("conteneur remplacé/redémarré pendant le préflight")
    return {
        "preflight_verifie": True, "runtime_sandbox_verifie": False, "vps_qualifie": False,
        "daemon_id": profil["daemon_id"], "services_verifies": list(attendus),
        "observation": "deux exec transitoires fixes sous UID1000",
        "uid_hote": mapped[0][0], "gid_hote": mapped[0][1],
        "limite": "observation en lecture seule ; Core revérifie son namespace avant création sandbox",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    gen = actions.add_parser("generer")
    for name in ("racine", "ssh-dir", "daemon-id", "controleur", "utilisateur", "sortie", "host-key-sha256"):
        gen.add_argument("--" + name, required=True)
    for name, default in (("uid", None), ("gid", None), ("ssh-port", 22), ("port-http", 8080), ("port-https", 8443)):
        gen.add_argument("--" + name, type=int, default=default, required=default is None)
    check = actions.add_parser("verifier")
    for name in ("profil", "gateway-id", "python-id"):
        check.add_argument("--" + name, required=True)
    args = vars(parser.parse_args(argv))
    try:
        action = args.pop("action")
        if action == "generer":
            sortie = Path(args.pop("sortie"))
            result = generer(creer_profil(**args), sortie)
        else:
            file = Path(args["profil"])
            _sans_liens(file)
            if not stat.S_ISREG(_metadata(file).st_mode):
                _refus("profil régulier requis")
            result = verifier(json.loads(_lire_public(file)), args["gateway_id"], args["python_id"])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except RefusRootless as exc:
        print(str(exc), file=sys.stderr)  # raisons internes fixes, sans contenu d'observation
        return 2
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Pas de stdout/stderr de Docker/SSH, JSON brut, secret ou traceback.
        print(
            "REJ-SERVEUR-ROOTLESS : profil, accès ou observation incohérent ; consulter les prérequis",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
