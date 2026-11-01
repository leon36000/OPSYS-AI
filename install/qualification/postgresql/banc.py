#!/usr/bin/env python3
"""Banc de qualification PostgreSQL : rejoue la suite d'OPSYS-AI contre un vrai PostgreSQL éphémère (Docker).

CE QUE C'EST : un conteneur `pgvector/pgvector:pg17` (image DÉJÀ présente localement, `--pull=never`, aucun réseau
requis) nommé `opsys-pg-test-qualif-<hex>`, sur un port local aléatoire, en mémoire (tmpfs) et SANS durabilité disque
(`fsync=off` : banc de test jetable, jamais une configuration d'exploitation). Le plugiciel `plugin_pg.py` donne à
chaque test sa propre base migrée (0001 -> tête) et y fait pointer `OPSYS_BASE_URL`. Les cibles de test sont lancées
en parallèle (un processus pytest par fichier). Chaque exécution écrit un dossier horodaté (journaux bruts, JSONL par
test, `resume.json`) : rien n'est écrasé.

CE QUE CE N'EST PAS : une preuve de charge, de haute disponibilité, de réplication ni de durabilité PostgreSQL (fsync
coupé). Les tests qui fabriquent eux-mêmes une base SQLite (`sqlite:///…` explicite) ne touchent pas PostgreSQL : le
résumé les compte à part (« n'ont pas touché PG »).

Usage :
  python3 install/qualification/postgresql/banc.py demarrer
  python3 install/qualification/postgresql/banc.py suites [--cibles tests departments] [--travailleurs 10] [--redirige]
  python3 install/qualification/postgresql/banc.py sqlite [...]       (mêmes cibles, SANS PostgreSQL : référence)
  python3 install/qualification/postgresql/banc.py arreter
  python3 install/qualification/postgresql/banc.py tout [...]         (démarrer + suites + arrêter, même en cas d'échec)
Prérequis : docker accessible, image `pgvector/pgvector:pg17` en cache, venv Python du dépôt (`--python`).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
ICI = Path(__file__).resolve().parent
IMAGE = "pgvector/pgvector:pg17"
PREFIXE = "opsys-pg-test-qualif-"
ETAT = Path(os.environ.get("TMPDIR", "/tmp")) / "opsys-pg-qualif-etat.json"


def _sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def demarrer() -> dict:
    if ETAT.exists():
        raise SystemExit(f"un banc est déjà démarré ({ETAT}) : `arreter` d'abord")
    nom = PREFIXE + secrets.token_hex(6)
    mdp = secrets.token_hex(12)
    r = _sh(["docker", "run", "-d", "--name", nom, "--pull=never", "-e", f"POSTGRES_PASSWORD={mdp}",
             "-p", "127.0.0.1::5432", "--shm-size=512m", "--tmpfs", "/var/lib/postgresql/data:rw,size=2g", IMAGE,
             "-c", "fsync=off", "-c", "synchronous_commit=off", "-c", "full_page_writes=off",
             "-c", "max_connections=500"])
    if r.returncode != 0:
        raise SystemExit(f"docker run a échoué : {r.stderr.strip()[-300:]}")
    port = None
    limite = time.monotonic() + 90
    while time.monotonic() < limite:
        p = _sh(["docker", "port", nom, "5432/tcp"])
        if p.returncode == 0 and p.stdout.strip():
            port = int(p.stdout.strip().splitlines()[0].rsplit(":", 1)[1])
            # pg_isready répond aussi pendant l'initialisation : on exige une vraie requête
            requete = _sh(["docker", "exec", nom, "psql", "-U", "postgres", "-h", "127.0.0.1", "-tAc", "select 1"])
            if requete.returncode == 0 and requete.stdout.strip() == "1":
                break
        time.sleep(0.5)
    else:
        _sh(["docker", "rm", "-f", "-v", nom])
        raise SystemExit("PostgreSQL pas prêt après 90 s")
    etat = {"conteneur": nom, "port": port,
            "admin_url": f"postgresql+psycopg://postgres:{mdp}@127.0.0.1:{port}/postgres"}
    ETAT.write_text(json.dumps(etat), encoding="utf-8")
    ETAT.chmod(0o600)
    version = _sh(["docker", "exec", nom, "psql", "-U", "postgres", "-tAc", "show server_version"]).stdout.strip()
    print(f"PostgreSQL {version} prêt : conteneur {nom}, port local {port}")
    return etat


def arreter() -> None:
    if not ETAT.exists():
        print("aucun banc démarré")
        return
    etat = json.loads(ETAT.read_text(encoding="utf-8"))
    r = _sh(["docker", "rm", "-f", "-v", etat["conteneur"]])
    ETAT.unlink(missing_ok=True)
    print(f"conteneur {etat['conteneur']} supprimé" if r.returncode == 0 else f"suppression : {r.stderr.strip()}")


def _cibles(racines: list[str]) -> list[str]:
    cibles: list[str] = []
    for racine in racines:
        p = RACINE / racine
        if racine == "departments":
            for d in sorted(p.glob("*/tests")):
                cibles += sorted(str(f.relative_to(RACINE)) for f in d.glob("test_*.py"))
        elif racine == "tests":
            cibles += sorted(str(f.relative_to(RACINE)) for f in p.glob("test_*.py"))
            cibles += sorted(str(f.relative_to(RACINE)) for f in (p / "e2e").glob("test_*.py"))
        elif p.is_dir():
            cibles += sorted(str(f.relative_to(RACINE)) for f in p.rglob("test_*.py"))
        else:
            cibles.append(racine)
    return cibles


def _pythonpath() -> str:
    morceaux = [str(RACINE / "src"), *[str(d) for d in sorted((RACINE / "departments").glob("*/src"))], str(ICI)]
    return os.pathsep.join(morceaux)


def _lancer_un(cible: str, python: str, sortie: Path, env_base: dict, pg: bool, delai: int,
               redirige: bool = False) -> dict:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", cible)
    log = sortie / f"{slug}.log"
    jsonl = sortie / f"{slug}.jsonl"
    env = dict(env_base)
    home = sortie / "home" / slug
    tmp = sortie / "tmp" / slug
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env.update({"HOME": str(home), "TMPDIR": str(tmp)})
    cmd = [python, "-m", "pytest", "-p", "no:cacheprovider", "--import-mode=importlib", "-rfE", cible]
    if pg:
        cmd[3:3] = ["-p", "plugin_pg"]
        env["OPSYS_QUALIF_PG_SORTIE"] = str(jsonl)
        if redirige:
            env["OPSYS_QUALIF_PG_REDIRIGER"] = "1"
    debut = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=RACINE, env=env, capture_output=True, text=True, timeout=delai, check=False)
        sortie_txt, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as exc:
        brut = exc.stdout or b""
        sortie_txt = brut.decode(errors="replace") if isinstance(brut, bytes) else brut
        code = 124
    log.write_text(sortie_txt, encoding="utf-8")
    fin = [ligne for ligne in sortie_txt.strip().splitlines()[-1:]]
    return {"cible": cible, "code": code, "duree_s": round(time.monotonic() - debut, 1),
            "derniere_ligne": fin[0] if fin else "", "journal": str(log)}


def suites(racines: list[str], travailleurs: int, python: str, pg: bool, delai: int, etiquette: str,
           redirige: bool = False) -> Path:
    horodatage = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    sortie = Path(os.environ.get("OPSYS_QUALIF_PG_DOSSIER", Path(os.environ.get("TMPDIR", "/tmp")) / "qualif-pg")) \
        / f"{etiquette}-{horodatage}"
    sortie.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = _pythonpath()
    env.pop("OPSYS_BASE_URL", None)
    if pg:
        if not ETAT.exists():
            raise SystemExit("banc non démarré : `demarrer` d'abord")
        env["OPSYS_QUALIF_PG_ADMIN_URL"] = json.loads(ETAT.read_text(encoding="utf-8"))["admin_url"]
    else:
        env.pop("OPSYS_QUALIF_PG_ADMIN_URL", None)
    cibles = _cibles(racines)
    print(f"{len(cibles)} fichiers de test, {travailleurs} travailleurs, sortie {sortie}", flush=True)
    resultats: list[dict] = []
    with cf.ThreadPoolExecutor(travailleurs) as pool:
        futurs = [pool.submit(_lancer_un, c, python, sortie, env, pg, delai, redirige) for c in cibles]
        for i, f in enumerate(cf.as_completed(futurs), 1):
            r = f.result()
            resultats.append(r)
            if r["code"] not in (0, 5):
                print(f"[{i}/{len(cibles)}] ROUGE {r['cible']} : {r['derniere_ligne']}", flush=True)
    resultats.sort(key=lambda r: r["cible"])
    (sortie / "resume.json").write_text(json.dumps(resultats, ensure_ascii=False, indent=1), encoding="utf-8")
    rouges = [r for r in resultats if r["code"] not in (0, 5)]
    verts = len(resultats) - len(rouges)
    print(f"terminé : {verts} fichiers verts, {len(rouges)} rouges ; résumé {sortie / 'resume.json'}")
    return sortie


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("commande", choices=["demarrer", "arreter", "suites", "sqlite", "tout"])
    ap.add_argument("--cibles", nargs="+", default=["tests", "departments"])
    ap.add_argument("--travailleurs", type=int, default=10)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--delai", type=int, default=3600, help="délai par fichier de test (s)")
    ap.add_argument("--redirige", action="store_true",
                    help="redirige aussi les URL sqlite:/// explicites des tests vers des bases PostgreSQL vides")
    a = ap.parse_args()
    if a.commande == "demarrer":
        demarrer()
    elif a.commande == "arreter":
        arreter()
    elif a.commande == "sqlite":
        suites(a.cibles, a.travailleurs, a.python, False, a.delai, "sqlite")
    elif a.commande == "suites":
        suites(a.cibles, a.travailleurs, a.python, True, a.delai, "pgr" if a.redirige else "pg", a.redirige)
    else:
        demarrer()
        try:
            suites(a.cibles, a.travailleurs, a.python, True, a.delai, "pgr" if a.redirige else "pg", a.redirige)
        finally:
            arreter()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
