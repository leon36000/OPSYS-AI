#!/usr/bin/env python3
"""Banc de parcours navigateur de la console OPSYS : instance FICTIVE + Chromium réel + preuves horodatées.

Usage :
  lancer.py verifier                      inventaire des moyens (navigateur, playwright-core, node) ; code 3 si inutilisable
  lancer.py parcours [--groupes a,b]      démarre l'instance fictive, joue les parcours, écrit les preuves
  lancer.py mutations [--seulement x,y]   rejoue les groupes concernés contre chaque injection de défaut (injections.py)
  lancer.py webp --sortie DOSSIER         convertit les captures PNG en WebP (ImageMagick) ; option --webp sur « parcours »

Prérequis (rien n'est installé par le banc, aucun réseau) :
  - Python du dépôt (venv) avec les dépendances de la console ; PYTHONPATH = src + departments/*/src (le banc le complète) ;
  - node >= 20 ; `playwright-core` trouvé dans $OPSYS_PLAYWRIGHT_CORE, ou dans un node_modules voisin (voir `trouver_playwright`) ;
  - un Chromium : $OPSYS_CHROMIUM, ou le cache de Playwright ($PLAYWRIGHT_BROWSERS_PATH, ~/.cache/ms-playwright), ou /opt/pw-browsers.
Sans navigateur utilisable le banc dit « prêt mais NON EXÉCUTÉ », écrit ce qui manque et sort en code 3 : il n'invente aucun verdict.

Sorties : docs/qualification/navigateur/ (ou --sortie) : resultats-<horodatage>.json et .md, captures PNG horodatées.
Un HOME/TMPDIR privé est recommandé (les instances n'écrivent que sous leur dossier jetable).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[2]
FRAIS = "2026-10-30T20:00:00-04:00"
PERIME = "2026-11-12T09:00:00-04:00"
DUREE_COURTE = 5


def horodatage() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


# -- inventaire des moyens ---------------------------------------------------------------------------------------------

def trouver_playwright() -> str | None:
    candidats = [os.environ.get("OPSYS_PLAYWRIGHT_CORE", "")]
    for racine in (RACINE, RACINE.parent, Path.home(), Path.home() / "Desktop", Path("/usr/lib/node_modules"), Path("/usr/local/lib/node_modules")):
        candidats.append(str(racine / "node_modules" / "playwright-core"))
    candidats += [str(p.parent) for base in (Path.home() / "Desktop", Path.home() / "Documents")
                  if base.is_dir() for p in base.glob("*/node_modules/playwright-core/package.json")]
    for c in candidats:
        if c and (Path(c) / "package.json").is_file():
            return str(Path(c))
    return None


def trouver_firefox() -> str | None:
    for r in (os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), str(Path.home() / ".cache" / "ms-playwright"), "/home/pc6/.cache/ms-playwright"):
        if r and Path(r).is_dir():
            for f in sorted(Path(r).glob("firefox-*/firefox/firefox"), reverse=True):
                return str(f)
    return None


def trouver_chromium() -> tuple[str | None, str]:
    """Chemin d'un exécutable Chromium, ou None ; renvoie aussi d'où il vient."""
    explicite = os.environ.get("OPSYS_CHROMIUM")
    if explicite and Path(explicite).is_file():
        return explicite, "OPSYS_CHROMIUM"
    racines = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), str(Path.home() / ".cache" / "ms-playwright"), "/opt/pw-browsers",
               "/home/pc6/.cache/ms-playwright"]
    for r in racines:
        if r and Path(r).is_dir():
            for chrome in sorted(Path(r).glob("chromium-*/chrome-linux*/chrome"), reverse=True):
                return str(chrome), f"cache Playwright {r}"
    for nom in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        chemin = shutil.which(nom)
        if chemin:
            return chemin, "PATH"
    return None, ""


def inventaire() -> dict:
    node = shutil.which("node")
    pw = trouver_playwright()
    chromium, origine = trouver_chromium()
    manque = []
    if not node:
        manque.append("node (>= 20)")
    if not pw:
        manque.append("playwright-core (variable OPSYS_PLAYWRIGHT_CORE ou node_modules voisin)")
    if not chromium:
        manque.append("un Chromium (OPSYS_CHROMIUM, cache Playwright, /opt/pw-browsers)")
    version = ""
    if node and pw:
        with_pw = subprocess.run([node, "-e", f"console.log(require({json.dumps(pw)}+'/package.json').version)"], capture_output=True, text=True)
        version = with_pw.stdout.strip()
    return {"node": node, "playwright_core": pw, "playwright_core_version": version, "chromium": chromium, "chromium_origine": origine,
            "moyens_suffisants": not manque, "manque": manque}


# -- instances ---------------------------------------------------------------------------------------------------------

def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Instance:
    def __init__(self, dossier: Path, prefixe: str = "/opsys", duree_session: int | None = None, injection: str | None = None, nom: str = "principale"):
        self.dossier, self.prefixe, self.port = dossier, prefixe, port_libre()
        journal = dossier / f"serveur-{nom}.log"
        dossier.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        commande = [sys.executable, str(ICI / "instance.py"), "--dossier", str(dossier), "--port", str(self.port), "--prefixe", prefixe]
        if duree_session:
            commande += ["--duree-session", str(duree_session)]
        if injection:
            commande += ["--injection", injection]
        self.proc = subprocess.Popen(commande, stdout=journal.open("wb"), stderr=subprocess.STDOUT, start_new_session=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.prefixe}"

    def attendre(self, delai: float = 90.0) -> None:
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.proc.poll() is not None:
                raise RuntimeError(f"l'instance s'est arrêtée (code {self.proc.returncode}) : {self.journal.read_text(errors='replace')[-800:]}")
            try:
                with urllib.request.urlopen(self.base + "/connexion", timeout=2) as r:
                    if r.status == 200:
                        return
            except OSError:
                time.sleep(0.4)
        raise RuntimeError("l'instance n'a pas répondu à temps")

    def arreter(self) -> None:
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


def cookies_forges(dossier: Path) -> tuple[str, str]:
    """Cookie signé valide mais déjà échu, et cookie falsifié (charge modifiée, signature ancienne)."""
    from opsys.console import securite

    secret = (dossier / "cles" / "console.secret").read_text().strip()
    echu = securite.signer_session(securite.ouvrir_session("proprio-fictif", ["nathan_owner"], 60, maintenant=time.time() - 3600), secret)
    valide = securite.signer_session(securite.ouvrir_session("employe-fictif", ["employee"], 600), secret)
    donnees, signature = valide.split(".")
    import base64

    charge = json.loads(base64.urlsafe_b64decode(donnees + "=" * (-len(donnees) % 4)))
    charge["r"] = ["nathan_owner"]  # élévation de privilège
    nouveau = base64.urlsafe_b64encode(json.dumps(charge, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return echu, f"{nouveau}.{signature}"


# -- exécution ---------------------------------------------------------------------------------------------------------

def executer(sortie: Path, groupes: list[str] | None, injection: str | None, etiquette: str, moteur: str = "chromium") -> dict:
    inv = inventaire()
    if moteur == "firefox":
        firefox = trouver_firefox()
        inv = dict(inv, chromium=firefox, chromium_origine="Firefox (cache Playwright)")
        if not firefox and "un Chromium" not in " ".join(inv["manque"]):
            inv["manque"] = [*inv["manque"], "un Firefox"]
        inv["moyens_suffisants"] = bool(firefox and inv["node"] and inv["playwright_core"])
    ts = horodatage()
    sortie.mkdir(parents=True, exist_ok=True)
    if not inv["moyens_suffisants"]:
        return {"verdict": "NON_EXECUTE", "inventaire": inv, "horodatage": ts, "constats": []}
    travail = Path(tempfile.mkdtemp(prefix="opsys-nav-"))
    principale = courte = sans_prefixe = None
    try:
        dossier = travail / "instance"
        principale = Instance(dossier, injection=injection)
        principale.attendre()
        courte = Instance(dossier, duree_session=DUREE_COURTE, nom="courte")
        sans_prefixe = Instance(dossier, prefixe="", nom="sans-prefixe")
        courte.attendre()
        sans_prefixe.attendre()
        echu, falsifie = cookies_forges(dossier)
        cfg = {"playwrightCore": inv["playwright_core"], "chromium": inv["chromium"], "base": principale.base, "baseCourte": courte.base,
               "baseSansPrefixe": sans_prefixe.base, "origines": [f"http://127.0.0.1:{courte.port}", f"http://127.0.0.1:{sans_prefixe.port}"], "dureeCourte": DUREE_COURTE, "dossier": str(dossier), "horloge": str(dossier / "horloge.txt"),
               "horlogeFrais": FRAIS, "horlogePerime": PERIME, "effets": str(dossier / "effets.jsonl"), "captures": str(sortie), "horodatage": ts,
               "resultats": str(travail / "resultats-navigateur.json"), "groupes": groupes or [], "cookieEchu": echu, "cookieFalsifie": falsifie, "moteur": moteur}
        (travail / "cfg.json").write_text(json.dumps(cfg))
        # Chromium crée un socket Unix dans TMPDIR (limite ~108 caractères) : un TMPDIR privé trop long le fait planter.
        court = Path(tempfile.mkdtemp(prefix="nv-", dir="/tmp")) if len(str(travail)) > 60 else travail
        env = dict(os.environ, TMPDIR=str(court), PLAYWRIGHT_BROWSERS_PATH=os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path(inv["chromium"]).parents[2])))
        debut = time.monotonic()
        proc = subprocess.run([inv["node"], str(ICI / "parcours.js"), str(travail / "cfg.json")], capture_output=True, text=True, env=env, timeout=900)
        duree = round(time.monotonic() - debut, 1)
        if court != travail:
            shutil.rmtree(court, ignore_errors=True)
        (sortie / f"journal-{etiquette}-{ts}.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        try:
            brut = json.loads((travail / "resultats-navigateur.json").read_text())
        except (OSError, ValueError):
            brut = {"navigateur": "inconnu", "constats": [{"groupe": "global", "id": "node", "nom": "le script de parcours n'a pas produit de résultats", "ok": False, "niveau": "bloquant", "detail": (proc.stdout + proc.stderr)[-800:]}]}
        constats = list(brut["constats"])
        # Contrôles côté serveur (fichiers, journaux) : ce que le navigateur ne peut pas voir.
        if not injection and (not groupes or {"plateforme", "approbations"} & set(groupes)):
            constats += controles_serveur(dossier, principale, courte, sans_prefixe)
        return {"verdict": "ECHEC" if any(not c["ok"] and c["niveau"] == "bloquant" for c in constats) else "PASSE", "inventaire": inv, "horodatage": ts,
                "navigateur": brut.get("navigateur"), "duree_s": duree, "captures_octets": brut.get("captures_octets"), "constats": constats,
                "injection": injection}
    finally:
        for i in (principale, courte, sans_prefixe):
            if i:
                i.arreter()
        shutil.rmtree(travail, ignore_errors=True)


def controles_serveur(dossier: Path, *instances: Instance) -> list[dict]:
    """Journaux du serveur, base et fichier d'effets : aucune fuite de secret, effets exacts, filtre fail2ban."""
    constats: list[dict] = []

    def c(nom: str, ok: bool, detail: object = None, niveau: str = "bloquant", id_: str = "") -> None:
        constats.append({"groupe": "serveur", "id": id_ or nom[:30], "nom": nom, "ok": bool(ok), "niveau": niveau, "detail": detail})

    journaux = "\n".join(i.journal.read_text(errors="replace") for i in instances if i and i.journal.exists())
    ids = json.loads((dossier / "identifiants.json").read_text())
    secret_console = (dossier / "cles" / "console.secret").read_text().strip()
    secret_fictif_f = dossier / "secret-fictif.txt"
    secret_fictif = secret_fictif_f.read_text() if secret_fictif_f.exists() else ""
    valeurs = {"mot de passe d'une personne": list(ids.values()), "secret de session": [secret_console], "valeur du secret saisi": [secret_fictif] if secret_fictif else []}
    for nom, vs in valeurs.items():
        c(f"journaux du serveur : aucune trace du {nom}", not any(v and v in journaux for v in vs), None, id_="journal-" + nom.split()[0])
    base_octets = (dossier / "instance.db").read_bytes() if (dossier / "instance.db").exists() else b""
    for p in (dossier / "instance.db-wal",):
        if p.exists():
            base_octets += p.read_bytes()
    if secret_fictif:
        c("base de données : la valeur du secret n'y est PAS en clair (chiffrée au repos)", secret_fictif.encode() not in base_octets, None, id_="base-chiffree")
    c("base de données : aucun mot de passe en clair (empreintes scrypt)", not any(v.encode() in base_octets for v in ids.values()), None, id_="base-mots-de-passe")
    c("journaux du serveur : aucune trace d'exécution (Traceback) ni erreur 500", "Traceback" not in journaux and '" 500 ' not in journaux, journaux.count("Traceback"), id_="journal-erreurs")
    effets = [json.loads(ligne) for ligne in (dossier / "effets.jsonl").read_text().splitlines()] if (dossier / "effets.jsonl").exists() else []
    attendu = [{"publie": "Note fictive A du banc", "fictif": True}, {"publie": "Note fictive C du banc", "fictif": True}]
    c("fichier d'effets : exactement la demande approuvée et celle de la double soumission (une fois chacune) ; la refusée n'a rien produit", effets == attendu, effets, id_="effets-exacts")
    # filtre fail2ban de production contre la ligne réelle d'un échec de connexion (console servie sans préfixe, comme derrière Caddy)
    filtre = (RACINE / "deploy" / "fail2ban" / "opsys-console.filter.conf").read_text()
    brut = re.search(r"^failregex\s*=\s*(.+)$", filtre, re.M).group(1)
    regex = brut.replace("%(__prefix_line)s", r"(?:\S+ opsys\[\d+\]: )?").replace("<ADDR>", r"(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]+)")
    sans = [i for i in instances if i and i.prefixe == ""]
    lignes = sans[0].journal.read_text(errors="replace").splitlines() if sans else []
    correspond = [ln for ln in lignes if re.search(regex, ln)]
    c("filtre fail2ban de production : reconnaît une ligne RÉELLE d'échec de connexion émise par le serveur (console sans préfixe)", len(correspond) >= 1, correspond[:1] or [ln for ln in lignes if "POST" in ln][:2], niveau="bloquant", id_="fail2ban-regex")
    return constats


def convertir_webp(dossier: Path, horodatage_: str | None = None) -> int:
    """Convertit les captures PNG (d'une exécution, ou toutes) en WebP avec ImageMagick pour tenir sous le budget d'espace du
    dépôt (< 3 Mo) ; sans `convert`, les PNG sont laissés tels quels. Renvoie le nombre de fichiers convertis."""
    convert = shutil.which("convert")
    if not convert:
        return 0
    n = 0
    for png in sorted(dossier.rglob("*.png")):
        if horodatage_ and not png.name.startswith(horodatage_):
            continue
        webp = png.with_suffix(".webp")
        if subprocess.run([convert, str(png), "-quality", "80", str(webp)], capture_output=True).returncode == 0 and webp.exists():
            png.unlink()
            n += 1
    return n


def ecrire_preuves(sortie: Path, res: dict, etiquette: str) -> Path:
    ts = res["horodatage"]
    chemin = sortie / f"resultats-{etiquette}-{ts}.json"
    chemin.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    lignes = [f"# Résultats du banc navigateur — {etiquette} — {ts}", "", f"- Verdict : **{res['verdict']}**",
              f"- Navigateur : {res.get('navigateur', 'aucun')} (Playwright {res['inventaire'].get('playwright_core_version', '?')}, headless)",
              f"- Durée : {res.get('duree_s', '?')} s ; captures : {round((res.get('captures_octets') or 0) / 1024)} Ko", ""]
    if res["verdict"] == "NON_EXECUTE":
        lignes += ["**Prêt mais NON EXÉCUTÉ** — il manque : " + ", ".join(res["inventaire"]["manque"]), ""]
    else:
        lignes += ["| Groupe | Constat | Verdict | Niveau |", "|---|---|---|---|"]
        for k in res["constats"]:
            lignes.append(f"| {k['groupe']} | {k['nom'].replace('|', '/')} | {'OK' if k['ok'] else ('info' if k['niveau'] == 'info' else '**ÉCHEC**')} | {k['niveau']} |")
    chemin.with_suffix(".md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def mutations(sortie: Path, seulement: list[str] | None) -> int:
    sys.path.insert(0, str(ICI))
    import injections

    inv = inventaire()
    if not inv["moyens_suffisants"]:
        print("NON EXÉCUTÉ : " + ", ".join(inv["manque"]))
        return 3
    bilan = []
    for nom, (_, groupes, attendus) in injections.INJECTIONS.items():
        if seulement and nom not in seulement:
            continue
        res = executer(sortie, groupes, nom, "injection-" + nom)
        echecs = {f"{k['groupe']}/{k['id']}" for k in res["constats"] if not k["ok"] and k["niveau"] == "bloquant"}
        tuee = bool(echecs & set(attendus))
        bilan.append({"injection": nom, "groupes": groupes, "attendus": attendus, "echecs_observes": sorted(echecs), "detectee": tuee})
        print(f"[{'TUÉE ' if tuee else 'SURVIT'}] {nom} : {sorted(echecs & set(attendus)) or sorted(echecs)[:4]}")
    chemin = sortie / f"mutations-{horodatage()}.json"
    chemin.write_text(json.dumps(bilan, indent=2, ensure_ascii=False), encoding="utf-8")
    survivantes = [b["injection"] for b in bilan if not b["detectee"]]
    print(f"{len(bilan)} injections, {len(bilan) - len(survivantes)} détectées, survivantes : {survivantes or 'aucune'} -> {chemin}")
    return 1 if survivantes else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=["verifier", "parcours", "mutations", "webp"])
    p.add_argument("--sortie", type=Path, default=RACINE / "docs" / "qualification" / "navigateur")
    p.add_argument("--groupes", default="")
    p.add_argument("--seulement", default="")
    p.add_argument("--moteur", choices=["chromium", "firefox"], default="chromium")
    p.add_argument("--webp", action="store_true", help="convertit les captures PNG en WebP (ImageMagick) pour économiser l'espace")
    args = p.parse_args(argv)
    if args.action == "verifier":
        inv = inventaire()
        print(json.dumps(inv, indent=2, ensure_ascii=False))
        return 0 if inv["moyens_suffisants"] else 3
    if args.action == "webp":
        print(f"{convertir_webp(args.sortie)} capture(s) converties en WebP")
        return 0
    if args.action == "mutations":
        return mutations(args.sortie, [x for x in args.seulement.split(",") if x] or None)
    etiquette = "parcours" if args.moteur == "chromium" else "parcours-" + args.moteur
    res = executer(args.sortie, [g for g in args.groupes.split(",") if g] or None, None, etiquette, args.moteur)
    chemin = ecrire_preuves(args.sortie, res, etiquette if res["verdict"] != "NON_EXECUTE" else etiquette + "-NON-EXECUTE")
    if args.webp and res["verdict"] != "NON_EXECUTE":
        convertir_webp(args.sortie, res["horodatage"])
    print(f"verdict : {res['verdict']} -> {chemin}")
    if res["verdict"] == "NON_EXECUTE":
        print("Prêt mais NON EXÉCUTÉ, il manque : " + ", ".join(res["inventaire"]["manque"]))
        return 3
    return 0 if res["verdict"] == "PASSE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
