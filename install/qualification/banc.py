#!/usr/bin/env python3
"""Banc de qualification d'installation Linux en conteneur : scripté, répétable, sans réseau, sans simulation.

CE QUE C'EST : un substitut honnête d'un VPS tant que la cible de production n'est pas fournie. Il construit l'image du
moteur (install/qualification/Dockerfile : mêmes utilisateur, variables et `deploy/entrypoint.sh` que la production), puis
joue, dans des conteneurs propres sans réseau et sans root, le parcours : installation -> instance fictive ->
`opsys-metier verifier` -> services -> sondes -> entreprise et données fictives -> parcours métier minimal (lead,
soumission, approbation N3 refusée sans humain puis accordée) -> sauvegarde chiffrée -> destruction -> restauration sur un
conteneur neuf -> comparaison des empreintes -> mise à jour depuis la version précédente et retour arrière -> durcissement
-> injections de défauts -> arrêt propre. Chaque étape écrit une preuve horodatée (JSON + Markdown) avec les codes de
sortie RÉELS ; un échec est consigné comme échec. Rien ici ne dit « VPS qualifié » : voir le rapport, rubrique « NON PROUVÉ ».

CE QUE CE N'EST PAS : le Core (TypeScript) n'est pas construit ; ni Caddy/TLS, ni DNS, ni réseau public, ni matériel, ni
charge, ni fournisseur d'hébergement, ni copie hors site. Aucun appel réseau n'est fait par le banc (conteneurs `--network
none`) ; les clés de fournisseur de modèle sont des valeurs fictives que rien n'appelle.

Usage :  python3 install/qualification/banc.py tout [--sortie DOSSIER] [--garder-image]
         python3 install/qualification/banc.py gabarit --memoire 2g          (un parcours complet à ce gabarit)
Prérequis : docker (daemon accessible à l'utilisateur), l'image `python:3.12-slim` en cache local, et un venv Python déjà
installé pour copier les dépendances (`--venv`, défaut : .venv du dépôt ou du worktree principal).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
INTERNE = "/opt/opsys/install/qualification/interne.py"
PEUPLER_ANCIEN = "/opt/opsys/install/qualification/peupler_ancien.py"
IMAGE_BASE = "python:3.12-slim"
REVISION_ANCIENNE = "2ffa4f606^"  # dernier état avant la migration 0039 : base à la révision 0038
PYTHON_VENV = "/opt/opsys-venv/bin/python"
GABARITS_BALAYAGE = ("1g", "768m", "512m", "384m", "256m", "192m", "128m", "96m")


def maintenant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def horodatage_fichier() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def en_octets(texte: str) -> int:
    nombre, unite = re.fullmatch(r"(\d+)([kmg]?)", texte.lower()).groups()  # type: ignore[union-attr]
    return int(nombre) * {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[unite]


# -- secrets : jamais écrits, jamais affichés ---------------------------------------------------------------------

class Masque:
    """Valeurs de secrets du banc : remplacées par *** dans tout ce qui est consigné, et recherchées avant d'écrire."""

    def __init__(self) -> None:
        self.valeurs: set[str] = set()

    def ajouter(self, valeur: str) -> str:
        if len(valeur) >= 8:
            self.valeurs.add(valeur)
        return valeur

    def masquer(self, texte: str) -> str:
        for valeur in sorted(self.valeurs, key=len, reverse=True):
            texte = texte.replace(valeur, "***")
        return texte

    def fuites(self, texte: str) -> list[str]:
        return [f"{v[:3]}…({len(v)})" for v in self.valeurs if v in texte]


# -- preuves ------------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Res:
    code: int
    out: str
    err: str
    duree: float

    def json(self) -> dict | None:
        with contextlib.suppress(ValueError):
            return json.loads(self.out)
        return None


class Etape:
    def __init__(self, identifiant: str, titre: str, attendu: str) -> None:
        self.identifiant, self.titre, self.attendu = identifiant, titre, attendu
        self.debut = maintenant()
        self.t0 = time.monotonic()
        self.fin = ""
        self.duree_s = 0.0
        self.commandes: list[dict] = []
        self.constats: list[dict] = []
        self.mesures: dict = {}
        self.notes: list[str] = []
        self.verdict = "PASSE"

    def constat(self, nom: str, ok: bool, detail: object = None) -> bool:
        self.constats.append({"nom": nom, "ok": bool(ok), "detail": detail})
        if not ok:
            self.verdict = "ECHEC"
        return bool(ok)

    def mesure(self, cle: str, valeur: object) -> None:
        self.mesures[cle] = valeur

    def note(self, texte: str) -> None:
        self.notes.append(texte)

    def clore(self) -> None:
        self.fin = maintenant()
        self.duree_s = round(time.monotonic() - self.t0, 2)

    def en_json(self) -> dict:
        return {"etape": self.identifiant, "titre": self.titre, "attendu": self.attendu, "verdict": self.verdict,
                "debut": self.debut, "fin": self.fin, "duree_s": self.duree_s, "constats": self.constats,
                "mesures": self.mesures, "notes": self.notes, "commandes": self.commandes}

    def en_markdown(self) -> str:
        lignes = [f"# {self.identifiant} — {self.titre}", "", f"- Verdict : **{self.verdict}**",
                  f"- Attendu : {self.attendu}", f"- Début : {self.debut}  ·  Fin : {self.fin}  ·  Durée : {self.duree_s} s", ""]
        if self.constats:
            lignes += ["## Constats", "", "| | Constat | Détail |", "|---|---|---|"]
            for c in self.constats:
                detail = json.dumps(c["detail"], ensure_ascii=False, default=str) if c["detail"] is not None else ""
                lignes.append(f"| {'OK' if c['ok'] else '**ÉCHEC**'} | {c['nom']} | {detail[:300].replace('|', '/')} |")
            lignes.append("")
        if self.mesures:
            lignes += ["## Mesures", "", "```json", json.dumps(self.mesures, indent=2, ensure_ascii=False, default=str),
                       "```", ""]
        if self.notes:
            lignes += ["## Notes", ""] + [f"- {n}" for n in self.notes] + [""]
        if self.commandes:
            lignes += ["## Commandes (code de sortie réel)", "", "| Code | Durée (s) | Commande |", "|---|---|---|"]
            for c in self.commandes:
                lignes.append(f"| {c['code']} | {c['duree_s']} | `{c['commande'][:220].replace('|', '/')}` |")
            lignes.append("")
        return "\n".join(lignes)


class Banc:
    def __init__(self, sortie: Path, image: str, venv: Path, garder_image: bool) -> None:
        self.run_id = "qualif-" + horodatage_fichier()
        self.suffixe = secrets.token_hex(3)
        self.prefixe = f"qb{self.suffixe}"
        self.etiquette = f"opsys.banc={self.run_id}"
        self.image = image
        self.venv = venv
        self.garder_image = garder_image
        self.dossier = sortie / self.run_id
        self.dossier.mkdir(parents=True, exist_ok=False)
        self.tmp = Path(tempfile.mkdtemp(prefix="banc-", dir=os.environ.get("TMPDIR") or None))
        os.chmod(self.tmp, 0o700)
        self.masque = Masque()
        self.etapes: list[Etape] = []
        self.courante: Etape | None = None
        self.noeuds: dict = {}
        self.jetons = {nom: self.masque.ajouter(secrets.token_hex(24)) for nom in
                       ("OPENCLAW_GATEWAY_TOKEN", "OPSYS_MCP_JETON", "OPSYS_CONTEXT_MCP_JETON", "OPSYS_CONSOLE_SECRET")}
        self.cle_fournisseur = self.masque.ajouter("cle-fictive-" + secrets.token_hex(12))
        self.conteneurs: list[str] = []
        self.volumes: list[str] = []
        self.numero = 0

    # -- journal des étapes --
    @contextlib.contextmanager
    def etape(self, identifiant: str, titre: str, attendu: str):
        e = Etape(identifiant, titre, attendu)
        self.courante = e
        print(f"[banc] {identifiant} {titre} …", flush=True)
        try:
            yield e
        except Exception as exc:  # noqa: BLE001 — une panne du banc est un échec consigné, pas un silence
            e.constat("exception inattendue du banc", False, f"{type(exc).__name__}: {self.masque.masquer(str(exc))[:300]}")
        finally:
            e.clore()
            self.courante = None
            self.etapes.append(e)
            self.ecrire(e)
            print(f"[banc] {identifiant} -> {e.verdict} ({e.duree_s} s)", flush=True)

    def ecrire(self, e: Etape) -> None:
        self.numero += 1
        base = f"{self.numero:02d}-{re.sub(r'[^a-z0-9]+', '-', e.identifiant.lower()).strip('-')}"
        for suffixe, contenu in ((".json", json.dumps(e.en_json(), indent=2, ensure_ascii=False, default=str) + "\n"),
                                 (".md", e.en_markdown() + "\n")):
            contenu = self.masque.masquer(contenu)
            fuites = self.masque.fuites(contenu)
            if fuites:
                raise RuntimeError(f"secret en clair dans la preuve {base}{suffixe} : {fuites}")
            (self.dossier / (base + suffixe)).write_text(contenu, encoding="utf-8")

    # -- docker --
    def docker(self, *args: str, stdin: str | None = None, timeout: int = 600, enregistrer: bool = True) -> Res:
        debut = time.monotonic()
        try:
            p = subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
            res = Res(p.returncode, p.stdout, p.stderr, round(time.monotonic() - debut, 2))
        except subprocess.TimeoutExpired as exc:
            res = Res(124, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                      f"délai de {timeout} s dépassé", round(time.monotonic() - debut, 2))
        if enregistrer and self.courante is not None:
            self.courante.commandes.append({
                "commande": self.masque.masquer("docker " + " ".join(args)), "code": res.code, "duree_s": res.duree,
                "sortie_fin": self.masque.masquer(res.out[-600:]), "erreur_fin": self.masque.masquer(res.err[-600:])})
        return res

    def ecrire_env(self, nom: str, valeurs: dict[str, str]) -> Path:
        chemin = self.tmp / f"{nom}.env"
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            for k, v in valeurs.items():
                f.write(f"{k}={v}\n")
        return chemin

    def env_service(self, omettre: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {"OPSYS_DOMAINE": "localhost", **self.jetons, "OPSYS_CONSOLE_PREFIXE": "",
               "OPSYS_CONSOLE_COOKIE_SECURISE": "1", "ANTHROPIC_API_KEY": self.cle_fournisseur,
               "OPSYS_EMBEDDINGS_URL": "http://embeddings.invalid:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "modele-fictif",
               "OPSYS_SAUVEGARDE_CLE_FICHIER": "/cles/sauvegarde.cle", "TZ": "America/Toronto"}
        for cle in omettre:
            env.pop(cle, None)
        env.update(extra or {})
        return env

    def options(self, memoire: str, extra_tmpfs: tuple[str, ...] = ()) -> list[str]:
        opts = ["--network", "none", "--user", "1000:1000", "--read-only", "--tmpfs", "/tmp:size=64m,mode=1777",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
                "--memory", memoire, "--memory-swap", memoire, "--label", self.etiquette]
        for t in extra_tmpfs:
            opts += ["--tmpfs", t]
        return opts

    def volume(self, pile: str, k: str) -> str:
        return f"{self.prefixe}-{pile}-{k}"

    def creer_volumes(self, pile: str, noms: tuple[str, ...] = ("data", "cfg", "cles", "sauv")) -> None:
        for k in noms:
            nom = self.volume(pile, k)
            self.docker("volume", "create", "--label", self.etiquette, nom)
            self.volumes.append(nom)

    def montages(self, pile: str, *, data: str | None = None, cfg: str | None = None, cles: str | None = None,
                 sauv: str | None = None) -> list[str]:
        """data/cfg/cles/sauv : pile source du volume (ou None = ne pas monter) ; suffixe ':ro' possible."""
        m: list[str] = []
        for cible, k, source in (("/opt/data", "data", data), ("/openclaw-config", "cfg", cfg),
                                 ("/cles", "cles", cles), ("/sauvegardes", "sauv", sauv)):
            if source:
                nom, _, mode = source.partition(":")
                m += ["-v", f"{self.volume(nom, k)}:{cible}" + (f":{mode}" if mode else "")]
        return m

    def demarrer(self, nom: str, pile: str, memoire: str, montages: list[str], env: dict[str, str]) -> str:
        cont = f"{self.prefixe}-{nom}"
        fichier = self.ecrire_env(f"env-{nom}", env)
        res = self.docker("run", "-d", "--init", "--name", cont, *self.options(memoire), "--env-file", str(fichier),
                          *montages, self.image)
        self.conteneurs.append(cont)
        if res.code != 0:
            raise RuntimeError(f"démarrage de {cont} impossible : {res.err.strip()[:300]}")
        return cont

    def une_fois(self, memoire: str, montages: list[str], argv: list[str], *, env: dict[str, str] | None = None,
                 entrypoint: str = PYTHON_VENV, extra_tmpfs: tuple[str, ...] = (), timeout: int = 600,
                 volumes_hote: list[str] | None = None) -> Res:
        """Conteneur jetable (--rm), même durcissement que le service, sans réseau."""
        envopts: list[str] = []
        if env:
            fichier = self.ecrire_env(f"env-un-{secrets.token_hex(2)}", env)
            envopts = ["--env-file", str(fichier)]
        return self.docker("run", "--rm", *self.options(memoire, extra_tmpfs), *envopts, *montages,
                           *(volumes_hote or []), "--entrypoint", entrypoint, self.image, *argv, timeout=timeout)

    def interne(self, cont: str, *args: str, timeout: int = 600, env: dict[str, str] | None = None) -> tuple[Res, dict | None]:
        e = [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
        res = self.docker("exec", *e, cont, PYTHON_VENV, INTERNE, *args, timeout=timeout)
        return res, res.json()

    def attendre_pret(self, cont: str, attendu: tuple[int, ...] = (0,), delai: int = 150) -> tuple[int, float, list[int]]:
        debut = time.monotonic()
        historique: list[int] = []
        code = -1
        while time.monotonic() - debut < delai:
            if self.docker("inspect", "-f", "{{.State.Running}}", cont, enregistrer=False).out.strip() != "true":
                return 255, round(time.monotonic() - debut, 1), historique + [255]
            code = self.docker("exec", cont, PYTHON_VENV, "/opt/opsys/deploy/readiness.py", enregistrer=False).code
            historique.append(code)
            if code in attendu:
                break
            time.sleep(2)
        if self.courante is not None:
            self.courante.commandes.append({"commande": f"readiness.py en boucle sur {cont}", "code": code,
                                            "duree_s": round(time.monotonic() - debut, 2),
                                            "sortie_fin": f"historique des codes : {historique[-8:]}", "erreur_fin": ""})
        return code, round(time.monotonic() - debut, 1), historique

    def arreter(self, cont: str) -> dict:
        debut = time.monotonic()
        self.docker("stop", "-t", "30", cont)
        duree = round(time.monotonic() - debut, 2)
        etat = self.docker("inspect", "-f", "{{.State.ExitCode}}|{{.State.OOMKilled}}", cont, enregistrer=False).out.strip()
        code, _, oom = etat.partition("|")
        journaux = self.docker("logs", cont, enregistrer=False)
        texte = journaux.out + journaux.err
        return {"code_sortie": int(code) if code.isdigit() else None, "oom": oom == "true", "duree_s": duree,
                "message_arret_demande": "arrêt demandé" in texte,
                "message_faux_processus_mort": "un processus longue durée s'est arrêté" in texte}

    def memoire(self, cont: str) -> dict:
        _, d = self.interne(cont, "rss")
        if not d:
            return {}
        gros = sorted(d["processus"], key=lambda p: p["rss_max_ko"], reverse=True)[:4]
        return {"cgroup_pic_mo": round((d["cgroup_pic_octets"] or 0) / 1048576, 1),
                "cgroup_limite": d["cgroup_limite"],
                "rss_max_par_processus_mo": {f"{p['nom']}[{p['pid']}]": round(p["rss_max_ko"] / 1024, 1) for p in gros}}

    def nettoyer(self) -> dict:
        """Retire SEULEMENT ce que ce banc a créé (étiquette du run) ; jamais un autre conteneur ni volume."""
        rapport = {"conteneurs": 0, "volumes": 0, "image": False}
        for cont in sorted(set(self.conteneurs)):
            if self.docker("rm", "-f", cont, enregistrer=False).code == 0:
                rapport["conteneurs"] += 1
        ids = self.docker("ps", "-aq", "--filter", f"label={self.etiquette}", enregistrer=False).out.split()
        if ids:
            self.docker("rm", "-f", *ids, enregistrer=False)
        for vol in sorted(set(self.volumes)):
            if self.docker("volume", "rm", "-f", vol, enregistrer=False).code == 0:
                rapport["volumes"] += 1
        if not self.garder_image:
            rapport["image"] = self.docker("rmi", "-f", self.image, enregistrer=False).code == 0
        shutil.rmtree(self.tmp, ignore_errors=True)
        return rapport


# ======================================================================================================================
# Étapes
# ======================================================================================================================

def etape_prevol(b: Banc) -> None:
    with b.etape("E00-prevol", "Pré-vol : hôte, daemon, images locales, absence de réseau",
                 "daemon Docker joignable, image de base en cache, disque suffisant, conteneurs étrangers intouchés") as e:
        info = b.docker("info", "--format", "{{.ServerVersion}}|{{.Architecture}}|{{.CgroupVersion}}|{{.CgroupDriver}}|"
                        "{{.NCPU}}|{{.MemTotal}}|{{.Driver}}")
        e.constat("daemon Docker joignable", info.code == 0, info.out.strip())
        champs = info.out.strip().split("|")
        if len(champs) == 7:
            e.mesure("hote", {"docker": champs[0], "arch": champs[1], "cgroup": champs[2], "pilote_cgroup": champs[3],
                              "cpus": int(champs[4]), "memoire_totale_go": round(int(champs[5]) / 1024**3, 1),
                              "stockage": champs[6]})
        base = b.docker("image", "inspect", IMAGE_BASE, "--format", "{{index .RepoDigests 0}}|{{.Architecture}}|{{.Os}}")
        e.constat(f"image de base {IMAGE_BASE} déjà en cache local (aucun pull)", base.code == 0, base.out.strip())
        e.mesure("image_base", base.out.strip())
        libre = shutil.disk_usage(tempfile.gettempdir()).free
        e.mesure("disque_libre_go", round(libre / 1024**3, 1))
        e.constat("au moins 10 Go libres (plafond du banc : 8 Go)", libre > 10 * 1024**3)
        e.mesure("depot", {"racine": str(RACINE), "commit": subprocess.run(
            ["git", "-C", str(RACINE), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True).stdout.strip(),
            "modifications_non_commitees": bool(subprocess.run(
                ["git", "-C", str(RACINE), "status", "--porcelain"], capture_output=True, text=True).stdout.strip())})
        avant = b.docker("ps", "-a", "--format", "{{.Names}}|{{.Status}}", enregistrer=False).out.strip().splitlines()
        b.noeuds["conteneurs_etrangers_avant"] = {ligne.split("|")[0]: ligne.split("|")[1].split()[0] for ligne in avant}
        e.mesure("conteneurs_etrangers_avant", len(avant))
        e.note("Les conteneurs étrangers au banc (dont jeuxvideoca-languagetool-1) ne sont ni lus ni modifiés ; leur état est "
               "comparé au pied du rapport.")


def etape_construction(b: Banc, deps: Path) -> bool:
    with b.etape("E01-installation-depuis-le-depot-local", "Installation du moteur depuis le dépôt local (image de qualification)",
                 "dépendances copiées d'un environnement local, paquet opsys-ai installé depuis le dépôt, image construite sans réseau") as e:
        t0 = time.monotonic()
        prep = subprocess.run([str(b.venv / "bin" / "python"), str(RACINE / "install/qualification/preparer_contexte.py"),
                               "--venv", str(b.venv), "--sortie", str(deps), "--verrou", str(RACINE / "requirements-runtime.lock.txt")],
                              capture_output=True, text=True, check=False)
        e.commandes.append({"commande": "preparer_contexte.py (copie hors réseau des dépendances du verrou)", "code": prep.returncode,
                            "duree_s": round(time.monotonic() - t0, 2), "sortie_fin": prep.stdout[-500:], "erreur_fin": prep.stderr[-500:]})
        e.constat("dépendances indispensables toutes présentes", prep.returncode == 0, prep.stderr.strip()[-200:] or "oui")
        rapport = json.loads((deps / "deps.json").read_text()) if (deps / "deps.json").exists() else {}
        e.mesure("dependances", {"copiees": len(rapport.get("copiees", [])), "absentes_du_venv": rapport.get("absentes_du_venv"),
                                 "versions_differentes_du_verrou": rapport.get("versions_differentes"),
                                 "empreintes_du_verrou_verifiees": rapport.get("empreintes_verrou_verifiees")})
        e.note("ÉCART : `pip install --require-hashes -r requirements-runtime.lock.txt` (chemin de production) exige le réseau et n'a "
               "PAS été exécuté ; les dépendances viennent d'un environnement déjà installé (mêmes versions que le verrou, sauf les "
               "distributions listées en « absentes_du_venv » : extra « tournées », PyVRP et numériques).")
        debut = time.monotonic()
        build = b.docker("build", "--progress=plain", "-f", str(RACINE / "install/qualification/Dockerfile"),
                         "--build-context", f"deps={deps}", "--label", b.etiquette, "-t", b.image, str(RACINE), timeout=1200)
        duree = round(time.monotonic() - debut, 1)
        e.mesure("duree_construction_s", duree)
        e.constat("construction de l'image réussie (code 0)", build.code == 0, build.err[-300:] if build.code else "ok")
        if build.code != 0:
            return False
        journal = build.out + build.err
        e.constat("pip a installé opsys-ai depuis le dépôt (--no-deps --no-build-isolation)",
                  "Successfully installed opsys-ai" in journal, re.findall(r"Successfully installed [^\n]+", journal)[:1])
        taille = int(b.docker("image", "inspect", b.image, "--format", "{{.Size}}", enregistrer=False).out.strip() or 0)
        base = int(b.docker("image", "inspect", IMAGE_BASE, "--format", "{{.Size}}", enregistrer=False).out.strip() or 0)
        e.mesure("taille_image_mo", round(taille / 1048576, 1))
        e.mesure("taille_image_de_base_mo", round(base / 1048576, 1))
        v = b.docker("run", "--rm", *b.options("256m"), "--entrypoint", "opsys-metier", b.image, "--version")
        e.constat("`opsys-metier --version` répond (code 0)", v.code == 0, v.out.strip())
        pc = b.docker("run", "--rm", *b.options("256m"), "--entrypoint", PYTHON_VENV, b.image, "-m", "pip", "check")
        e.mesure("pip_check", {"code": pc.code, "sortie": (pc.out + pc.err).strip()[:400]})
        e.constat("`pip check` : aucune dépendance cassée", pc.code == 0, (pc.out + pc.err).strip()[:200])
        du = b.docker("run", "--rm", *b.options("256m"), "--entrypoint", "sh", b.image, "-c",
                      "du -sm /opt/opsys/* /opt/opsys-venv /usr/local/lib/python3.12 2>/dev/null | sort -rn | head -9")
        e.mesure("composition_image_mo", {ligne.split()[1]: int(ligne.split()[0]) for ligne in du.out.strip().splitlines() if ligne.strip()})
        e.note("L'image embarque le dépôt entier hors .dockerignore (mobile/, tests/, docs/) : voir « composition_image_mo ».")
        usr = b.docker("run", "--rm", *b.options("256m"), "--entrypoint", "id", b.image)
        e.constat("l'image tourne par défaut en utilisateur non root (uid 1000)", "uid=1000" in usr.out, usr.out.strip())
        return True
    return False


def etape_installateur_public(b: Banc) -> None:
    with b.etape("E02-installateur-public", "Installateur officiel install/install.sh dans un conteneur propre, sans root, sans réseau",
                 "le résultat réel est consigné ; l'installateur exige Node, uv, pnpm, Docker et le réseau") as e:
        res = b.docker("run", "--rm", "--network", "none", "--user", "1000:1000", "--label", b.etiquette, "-e", "HOME=/home/t",
                       "--tmpfs", "/home/t:uid=1000,mode=700,size=256m", "-v", f"{RACINE}:/src:ro", IMAGE_BASE,
                       "bash", "/src/install/install.sh", "--source", "/src", "--sans-service")
        e.mesure("code_sortie_installateur", res.code)
        e.mesure("sortie", (res.out + res.err).strip()[-600:])
        e.constat("l'installateur public termine avec succès (code 0)", res.code == 0,
                  "NON : " + (res.out + res.err).strip()[-200:])
        e.note("Échec réel et attendu hors réseau : prérequis absents du conteneur (Node 24.16+/26.1+, uv, pnpm, daemon Docker). "
               "Le chemin « installateur » n'est donc NON PROUVÉ ici ; la preuve d'installation de cette qualification est E01 "
               "(moteur Python seul, sans Core). Le manque de mémoire observé sur la VM ARM64 (construction du Core) n'est PAS "
               "reproduit : le Core n'est pas construit par ce banc.")


# -- pile : instance + services --------------------------------------------------------------------------------------

def sondes_formatees(e: Etape, d: dict | None, prefixe: str = "") -> None:
    if not d:
        e.constat(prefixe + "sortie JSON illisible", False)
        return
    for s in d.get("sondes", d.get("constats", [])):
        e.constat(prefixe + s["nom"], s["ok"], s.get("detail"))


def chaine(b: Banc, etiquette: str, memoire: str, *, complet: bool) -> dict:
    """Parcours complet (ou jusqu'à la sauvegarde) à un gabarit mémoire donné. Rend le bilan de viabilité."""
    pile = f"{etiquette}"
    bilan: dict = {"gabarit": memoire, "etapes": {}}
    E = lambda s: f"{etiquette}-{s}"  # noqa: E731
    b.creer_volumes(pile)
    cont = None

    with b.etape(E("init"), f"[{memoire}] Démarrage à vide puis initialisation d'une instance fictive",
                 "services démarrés (entrypoint de production), prêts « en attente de configuration » (3), puis prêts (0) après "
                 "initialisation (personnes, paliers, entreprise, profils de base)") as e:
        t0 = time.monotonic()
        cont = b.demarrer(f"{pile}-s1", pile, memoire, b.montages(pile, data=pile, cfg=pile, cles=pile, sauv=pile), b.env_service())
        code, secs, hist = b.attendre_pret(cont, attendu=(0, 3))
        e.mesure("temps_avant_premier_readiness_s", secs)
        e.constat("premier démarrage : readiness = 3 (en attente de configuration opérateur), pas 0 ni échec", code == 3, hist[-5:])
        res, d = b.interne(cont, "preparer-secrets")
        e.constat("secrets de test créés dans /cles (0600, dossier 0700)", res.code == 0 and bool(d) and
                  all(m == "0o600" for m in d["modes"].values()) and d["dossier_mode"] == "0o700", d and d.get("modes"))
        res, d = b.interne(cont, "initialiser")
        for s in (d or {}).get("etapes", []):
            e.constat(f"initialisation : {s['nom']}", s["ok"], f"code {s['code']} (attendu {s['attendu']})")
        if not d:
            e.constat("initialisation : sortie lisible", False, res.err[-300:])
        b.docker("restart", "-t", "30", cont)
        code, secs2, hist2 = b.attendre_pret(cont, attendu=(0,))
        e.mesure("temps_redemarrage_jusqu_a_pret_s", secs2)
        e.constat("après initialisation et redémarrage : readiness = 0", code == 0, hist2[-5:])
        e.mesure("duree_totale_s", round(time.monotonic() - t0, 1))
        bilan["etapes"]["init"] = e.verdict == "PASSE"
    if cont is None or not bilan["etapes"].get("init"):
        bilan["viable"] = False
        bilan["cause"] = "initialisation en échec"
        with contextlib.suppress(Exception):
            bilan["arret"] = b.arreter(cont) if cont else None
        return bilan

    with b.etape(E("verifier"), f"[{memoire}] `opsys-metier verifier` dans le conteneur",
                 "manifestes, outils et dépendances valides (code 0)") as e:
        res = b.docker("exec", cont, "opsys-metier", "verifier")
        e.constat("`opsys-metier verifier` : code 0", res.code == 0, res.out.strip().splitlines()[-1:] if res.out else res.err[-200:])
        e.constat("10 départements et 415 outils annoncés", "10 départements" in res.out and "outils" in res.out, res.out.strip()[-160:])
        bilan["etapes"]["verifier"] = e.verdict == "PASSE"

    with b.etape(E("sondes"), f"[{memoire}] Sondes de santé, authentification, en-têtes de sécurité",
                 "MCP et console répondent ; jeton exigé ; en-têtes de sécurité ; readiness 0") as e:
        res, d = b.interne(cont, "sondes")
        sondes_formatees(e, d)
        res, d = b.interne(cont, "connexion")
        sondes_formatees(e, d, "console : ")
        bilan["etapes"]["sondes"] = e.verdict == "PASSE"

    with b.etape(E("parcours"), f"[{memoire}] Entreprise fictive et parcours minimal : lead, soumission, N3 refusée puis accordée",
                 "chaque constat vérifié en base ; l'approbation N3 est refusée sans humain habilité et accordée par la CLI humaine") as e:
        res, d = b.interne(cont, "parcours", timeout=900)
        sondes_formatees(e, d)
        bilan["etapes"]["parcours"] = e.verdict == "PASSE"
        e.mesure("memoire_apres_parcours", b.memoire(cont))

    # l'instance est « au repos » avant les empreintes
    time.sleep(3)
    with b.etape(E("empreinte-avant"), f"[{memoire}] Empreintes et comptages AVANT sauvegarde",
                 "base saine (integrity_check), empreinte par table stable entre deux lectures") as e:
        r1, d1 = b.interne(cont, "empreinte")
        time.sleep(1)
        r2, d2 = b.interne(cont, "empreinte")
        ok = bool(d1 and d2)
        e.constat("deux lectures successives identiques (instance au repos)", ok and d1["sha256_global"] == d2["sha256_global"],
                  d1 and d1["sha256_global"][:16])
        if d1:
            e.constat("integrity_check = ok", d1["integrity_check"])
            e.mesure("resume", {k: v for k, v in d1.items() if k != "details"})
            (b.dossier / f"empreinte-avant-{etiquette}.json").write_text(json.dumps(d1, indent=1) + "\n")
        du = b.docker("exec", cont, "du", "-sk", "/opt/data", "/openclaw-config", "/sauvegardes")
        e.mesure("taille_des_donnees_ko", {ligne.split()[1]: int(ligne.split()[0]) for ligne in du.out.strip().splitlines() if ligne.strip()})
        bilan["empreinte_avant"] = d1
        bilan["etapes"]["empreinte_avant"] = e.verdict == "PASSE"

    with b.etape(E("sauvegarde"), f"[{memoire}] Sauvegarde chiffrée (export + AES-256-GCM, clé hors sauvegarde) et vérification",
                 "archive chiffrée dans /sauvegardes, clé dans /cles (hors sauvegarde), vérification de bout en bout, aucun clair") as e:
        res, d = b.interne(cont, "mesurer", "--", PYTHON_VENV, "-m", "opsys.sauvegarde_chiffree", "sauvegarder", "--dossier",
                           "/sauvegardes", "--par", "banc")
        interne = json.loads(d["stdout"]) if d and d["code"] == 0 and d["stdout"].strip().startswith("{") else None
        e.constat("sauvegarde chiffrée réussie (code 0)", bool(d) and d["code"] == 0, d and (d["stderr"][-200:] or "ok"))
        if d:
            e.mesure("sauvegarde", {"duree_s": d["duree_s"], "rss_max_enfant_mo": round(d["rss_max_enfant_ko"] / 1024, 1),
                                    "cgroup_pic_mo": round((d["cgroup_pic_octets"] or 0) / 1048576, 1)})
        if interne:
            archive = interne["chemin"]
            e.mesure("archive", {"fichier": interne["fichier"], "octets_chiffres": interne["octets_chiffres"],
                                 "revision_base": interne["revision_base"], "cle_id": interne["cle_id"]})
            e.constat("verifiee == vrai", interne["verifiee"] is True)
            lu = b.docker("exec", cont, "sh", "-c", f"stat -c '%a %U' {archive}; ls /sauvegardes; ls /cles")
            e.constat("archive en 0600, propriétaire non root", lu.out.startswith("600 opsys"), lu.out.splitlines()[:1])
            e.constat("la clé n'est pas dans le dossier des sauvegardes",
                      not any(n.endswith(".cle") for n in b.docker("exec", cont, "ls", "/sauvegardes", enregistrer=False).out.split()))
            clair = b.docker("exec", cont, "grep", "-c", "-a", "nathan", archive)
            e.constat("aucune donnée lisible dans l'archive (« nathan » absent du fichier chiffré)", clair.out.strip() == "0", clair.out.strip())
            res2, d2 = b.interne(cont, "mesurer", "--", PYTHON_VENV, "-m", "opsys.sauvegarde_chiffree", "verifier", archive)
            e.constat("`verifier` indépendant : archive authentifiée avec la clé", bool(d2) and d2["code"] == 0, d2 and d2["stderr"][-200:])
            bilan["archive"] = interne
        bilan["etapes"]["sauvegarde"] = e.verdict == "PASSE"

    if not complet:
        with b.etape(E("arret"), f"[{memoire}] Arrêt propre (gabarit seul)", "code de sortie 0, pas de message de processus mort") as e:
            bilan["memoire_finale"] = b.memoire(cont)
            a = b.arreter(cont)
            e.mesure("arret", a)
            e.constat("arrêt propre : code 0, sans OOM", a["code_sortie"] == 0 and not a["oom"], a)
            bilan["arret"] = a
        bilan["viable"] = all(bilan["etapes"].values()) and not bilan["arret"]["oom"] and bilan["arret"]["code_sortie"] == 0
        return bilan

    etapes_suite(b, etiquette, memoire, pile, cont, bilan)
    return bilan


def etapes_suite(b: Banc, etiquette: str, memoire: str, pile: str, cont: str, bilan: dict) -> None:
    E = lambda s: f"{etiquette}-{s}"  # noqa: E731
    archive = bilan.get("archive", {})
    nom_archive = archive.get("fichier", "")
    avant = bilan.get("empreinte_avant")

    with b.etape(E("durcissement"), f"[{memoire}] Durcissement vérifié dans le conteneur en service",
                 "non root, racine en lecture seule, secrets 0600, aucune capacité, ports minimaux, aucun secret dans l'image ni les "
                 "journaux, journaux sans PII") as e:
        res, d = b.interne(cont, "durcissement")
        sondes_formatees(e, d)
        h = json.loads(b.docker("inspect", cont, enregistrer=False).out)[0]["HostConfig"]
        e.constat("docker inspect : racine en lecture seule", h["ReadonlyRootfs"] is True)
        e.constat("docker inspect : toutes capacités retirées, no-new-privileges", h["CapDrop"] == ["ALL"] and
                  "no-new-privileges" in " ".join(h["SecurityOpt"] or []), {"CapDrop": h["CapDrop"], "SecurityOpt": h["SecurityOpt"]})
        e.constat("docker inspect : aucun port publié sur l'hôte", not (h.get("PortBindings") or {}), h.get("PortBindings"))
        e.constat("docker inspect : limite mémoire et PID posées", h["Memory"] > 0 and (h["PidsLimit"] or 0) > 0,
                  {"Memory": h["Memory"], "PidsLimit": h["PidsLimit"]})
        exposes = json.loads(b.docker("image", "inspect", b.image, "--format", "{{json .Config.ExposedPorts}}", enregistrer=False).out or "null")
        e.constat("l'image n'expose que 8765 et 8700", sorted((exposes or {}).keys()) == ["8700/tcp", "8765/tcp"], sorted((exposes or {}).keys()))
        journaux = b.docker("logs", cont, enregistrer=False)
        texte = journaux.out + journaux.err
        e.constat("journaux du service : aucune valeur de secret du banc (jetons, secret de console, clé fournisseur)",
                  not b.masque.fuites(texte), {"octets": len(texte), "fuites": b.masque.fuites(texte)})
        res = b.docker("exec", "-i", cont, PYTHON_VENV, INTERNE, "texte-stdin", "--fichiers-secrets", "/cles/mdp-nathan",
                       "/cles/mdp-agent-systeme", "/cles/sauvegarde.cle", "--pii", "+15145550142", "5145550142", "intrus@example.test",
                       "mot-de-passe-faux-du-banc", stdin=texte, enregistrer=False)
        d = res.json() or {}
        e.constat("journaux du service : ni mot de passe, ni clé de sauvegarde, ni téléphone du client, ni identifiant tapé (PII)",
                  res.code == 0, d)
        res, d = b.interne(cont, "balayer", "/opt/data", "/openclaw-config", "/sauvegardes", "--variables",
                           *b.jetons.keys(), "ANTHROPIC_API_KEY", "--fichiers-secrets", "/cles/mdp-nathan", "/cles/mdp-agent-systeme")
        e.constat("volumes de données/config/sauvegardes : aucun secret du banc en clair (jetons, clé fournisseur, mots de passe)",
                  res.code == 0, d and {"fichiers": d["fichiers_balayes"], "trouvailles": d["trouvailles"]})
        res = b.une_fois("512m", [], ["/opt/opsys/install/qualification/interne.py", "balayer", "/", "--variables", *b.jetons.keys(),
                                     "ANTHROPIC_API_KEY", "--motifs", "--exclure", "/proc", "/sys", "/dev", "/tmp",
                                     "/opt/opsys/tests", "/opt/opsys/docs", "/opt/opsys/mobile", "/opt/opsys-venv/lib", "/usr/lib",
                                     "/usr/share"],
                         env=b.env_service())
        d = res.json()
        e.constat("système de fichiers de l'image (code, config, hors tests/docs/bibliothèques) : aucun secret ni clé privée",
                  res.code == 0, d and {"fichiers": d["fichiers_balayes"], "trouvailles": d["trouvailles"][:5]})
        hist = b.docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", b.image, enregistrer=False).out
        cfg = b.docker("image", "inspect", b.image, "--format", "{{json .Config.Env}}", enregistrer=False).out
        e.constat("historique et variables de l'image : aucune valeur de secret du banc", not b.masque.fuites(hist + cfg),
                  b.masque.fuites(hist + cfg))
        env_image = json.loads(cfg or "[]")
        suspects = [x.split("=", 1)[0] for x in env_image if re.search(r"(KEY|TOKEN|SECRET|PASSWORD|JETON)=", x)
                    and not x.startswith("GPG_KEY=")]  # GPG_KEY : empreinte PUBLIQUE de la clé de signature de Python (image de base)
        e.constat("variables d'environnement de l'image : aucun secret (GPG_KEY = empreinte publique de l'image de base)", not suspects,
                  suspects)
        res, d = b.interne(cont, "rss")
        e.mesure("memoire_en_service", b.memoire(cont))
        bilan["etapes"]["durcissement"] = e.verdict == "PASSE"

    with b.etape(E("destruction"), f"[{memoire}] Arrêt propre puis DESTRUCTION de l'instance (conteneur, données, configuration)",
                 "arrêt avec code 0 sans message de processus mort ; volumes data/cfg supprimés ; clés et sauvegardes conservées") as e:
        bilan["memoire_service"] = b.memoire(cont)
        a = b.arreter(cont)
        e.mesure("arret", a)
        e.constat("arrêt propre : code de sortie 0", a["code_sortie"] == 0, a)
        e.constat("arrêt propre : message « arrêt demandé » et pas de « processus mort »",
                  a["message_arret_demande"] and not a["message_faux_processus_mort"])
        e.constat("aucune mise à mort par manque de mémoire (OOM)", not a["oom"])
        b.docker("rm", "-f", cont)
        for k in ("data", "cfg"):
            b.docker("volume", "rm", "-f", b.volume(pile, k))
        gone = b.docker("volume", "ls", "-q", "--filter", f"name={b.volume(pile, 'data')}", enregistrer=False).out.strip()
        e.constat("volume de données détruit", gone == "")
        reste = b.docker("run", "--rm", "--network", "none", "--user", "1000:1000", "-v", f"{b.volume(pile, 'sauv')}:/sauvegardes:ro",
                         "-v", f"{b.volume(pile, 'cles')}:/cles:ro", "--entrypoint", "ls", b.image, "/sauvegardes", "/cles")
        e.constat("sauvegarde et clé ont survécu (volumes distincts)", nom_archive in reste.out and "sauvegarde.cle" in reste.out,
                  reste.out.split())
        bilan["etapes"]["destruction"] = e.verdict == "PASSE"

    pile2 = f"{etiquette}r"
    with b.etape(E("restauration"), f"[{memoire}] RESTAURATION sur un conteneur neuf à partir de la seule sauvegarde chiffrée et de la clé",
                 "restauration réussie (code 0), services démarrés, prêts, connexion avec le mot de passe d'origine") as e:
        b.creer_volumes(pile2, ("data", "cfg"))
        mont = ["-v", f"{b.volume(pile2, 'data')}:/opt/data", "-v", f"{b.volume(pile, 'cles')}:/cles:ro",
                "-v", f"{b.volume(pile, 'sauv')}:/sauvegardes:ro"]
        res = b.une_fois(memoire, mont, [INTERNE, "mesurer", "--", PYTHON_VENV, "-m", "opsys.sauvegarde_chiffree", "restaurer",
                                         f"/sauvegardes/{nom_archive}", "--par", "banc"],
                         env=b.env_service())
        d = res.json()
        e.constat("restauration chiffrée : code 0", bool(d) and d["code"] == 0, d and (d["stderr"][-300:] or "ok"))
        if d:
            e.mesure("restauration", {"duree_s": d["duree_s"], "rss_max_enfant_mo": round(d["rss_max_enfant_ko"] / 1024, 1),
                                      "cgroup_pic_mo": round((d["cgroup_pic_octets"] or 0) / 1048576, 1)})
        t0 = time.monotonic()
        cont2 = b.demarrer(f"{pile}-s2", pile2, memoire,
                           ["-v", f"{b.volume(pile2, 'data')}:/opt/data", "-v", f"{b.volume(pile2, 'cfg')}:/openclaw-config",
                            "-v", f"{b.volume(pile, 'cles')}:/cles", "-v", f"{b.volume(pile, 'sauv')}:/sauvegardes"], b.env_service())
        code, secs, hist = b.attendre_pret(cont2, attendu=(0,))
        e.mesure("temps_jusqu_a_pret_apres_restauration_s", round(time.monotonic() - t0, 1))
        e.constat("services prêts (readiness 0) sur les données restaurées", code == 0, hist[-5:])
        res, d = b.interne(cont2, "connexion")
        sondes_formatees(e, d, "restauré : ")
        res, d = b.interne(cont2, "sondes")
        sondes_formatees(e, d, "restauré : ")
        bilan["cont2"], bilan["pile2"] = cont2, pile2
        bilan["etapes"]["restauration"] = e.verdict == "PASSE"

    with b.etape(E("comparaison"), f"[{memoire}] Comparaison des empreintes et comptages avant / après restauration",
                 "mêmes tables, mêmes comptes, mêmes empreintes de contenu (journal d'audit hors lignes instance.*)") as e:
        cont2 = bilan.get("cont2")
        if not cont2 or not avant:
            e.constat("prérequis (service restauré, empreinte avant)", False)
        else:
            time.sleep(3)
            r, apres = b.interne(cont2, "empreinte")
            (b.dossier / f"empreinte-apres-{etiquette}.json").write_text(json.dumps(apres, indent=1) + "\n")
            e.constat("base restaurée : integrity_check = ok, révision 0040", bool(apres) and apres["integrity_check"] and apres["revision"] == "0040")
            diffs = sorted(t for t in set(avant["details"]) | set(apres["details"]) if avant["details"].get(t) != apres["details"].get(t))
            e.mesure("tables", {"avant": avant["tables"], "apres": apres["tables"]})
            e.mesure("lignes", {"avant": avant["lignes_total"], "apres": apres["lignes_total"]})
            e.constat("toutes les tables identiques (comptes et SHA-256 de contenu)", not diffs, diffs or "aucune différence")
            e.constat("empreinte globale identique", avant["sha256_global"] == apres["sha256_global"],
                      {"avant": avant["sha256_global"][:16], "apres": apres["sha256_global"][:16]})
            res, d = b.interne(cont2, "mesurer", "--", PYTHON_VENV, "-m", "opsys.cli", "approbations", "lister", "--statut", "executee")
            e.constat("l'approbation N3 accordée avant la destruction est présente dans l'instance restaurée",
                      bool(d) and d["code"] == 0 and "m3_marquer_devis_accepte" in d["stdout"], d and d["stdout"][:120])
        bilan["etapes"]["comparaison"] = e.verdict == "PASSE"

    with b.etape(E("arret-propre"), f"[{memoire}] Arrêt propre de l'instance restaurée", "code 0, pas de message de processus mort") as e:
        cont2 = bilan.get("cont2")
        if cont2:
            bilan["memoire_finale"] = b.memoire(cont2)
            a = b.arreter(cont2)
            e.mesure("arret", a)
            e.constat("code de sortie 0", a["code_sortie"] == 0, a)
            e.constat("message « arrêt demandé », pas de « processus mort »", a["message_arret_demande"] and not a["message_faux_processus_mort"])
            e.constat("sans OOM", not a["oom"])
            bilan["arret"] = a
        bilan["etapes"]["arret_propre"] = e.verdict == "PASSE"
    with b.etape(E("mise-a-jour"), f"[{memoire}] Mise à jour depuis la version précédente (0038) vers la tête, et retour arrière",
                 "base écrite par l'ancien logiciel migrée sans perte, services prêts, retour arrière alembic sans perte, reprise") as e:
        mise_a_jour(b, e, pile, memoire)
        bilan["etapes"]["mise_a_jour"] = e.verdict == "PASSE"

    with b.etape(E("injections"), f"[{memoire}] Injections de défauts : échecs propres, codes typés, aucune perte",
                 "chaque défaut refusé avec son code, l'instance existante intacte (empreinte identique)") as e:
        injections(b, e, pile, bilan)
        bilan["etapes"]["injections"] = e.verdict == "PASSE"

    bilan["viable"] = all(bilan["etapes"].values())


def peupler_ancien(b: Banc, pile_ancienne: str, cles_pile: str, arbre: Path) -> Res:
    pp = ["/ancien/src"] + [f"/ancien/departments/{d.name}/src" for d in sorted((arbre / "departments").glob("m*-*"))]
    return b.une_fois("1g", ["-v", f"{b.volume(pile_ancienne, 'data')}:/opt/data", "-v", f"{b.volume(cles_pile, 'cles')}:/cles:ro",
                             "-v", f"{arbre}:/ancien:ro"], [PEUPLER_ANCIEN, "/cles/mdp-nathan"], env={"PYTHONPATH": ":".join(pp)})


def mise_a_jour(b: Banc, e: Etape, pile: str, memoire: str) -> None:
    arbre = Path(tempfile.mkdtemp(prefix="ancien-", dir=b.tmp))
    ar = subprocess.run(f"git -C {RACINE} archive {REVISION_ANCIENNE} src departments pyproject.toml | tar -x -C {arbre}",
                        shell=True, capture_output=True, text=True, check=False)
    e.constat(f"arbre de la version précédente ({REVISION_ANCIENNE}) extrait de git", ar.returncode == 0, ar.stderr[-200:])
    if ar.returncode != 0:
        return
    for p in (arbre,):
        os.chmod(p, 0o755)
    pa = f"{pile}a"
    b.creer_volumes(pa, ("data",))
    res = peupler_ancien(b, pa, pile, arbre)
    d = res.json()
    e.constat("instance peuplée PAR L'ANCIEN logiciel (code source /ancien, révision 0038)",
              res.code == 0 and bool(d) and d["revision"] == "0038" and d["code_source"].startswith("/ancien"), d or res.err[-300:])
    mont = ["-v", f"{b.volume(pa, 'data')}:/opt/data"]
    r, d0 = (lambda x: (x, x.json()))(b.une_fois("512m", mont, [INTERNE, "empreinte"]))
    e.mesure("avant_mise_a_jour", {k: v for k, v in (d0 or {}).items() if k != "details"})
    # instantané de reprise (retour arrière par données) : copie du volume avant la mise à jour
    def copier(source_pile: str, destination: str) -> Res:
        b.creer_volumes(destination, ("data",))
        return b.docker("run", "--rm", "--user", "1000:1000", "-v", f"{b.volume(source_pile, 'data')}:/opt/data:ro", "-v",
                        f"{b.volume(destination, 'data')}:/copie", "--entrypoint", "cp", b.image, "-a", "/opt/data/.", "/copie/")

    cp = copier(pa, pa + "s")
    e.constat("instantané de la base avant mise à jour (volume copié)", cp.code == 0, cp.err[-200:])
    # mise à jour par le logiciel courant
    mig = b.une_fois("512m", mont, [INTERNE, "mesurer", "--", PYTHON_VENV, "-m", "opsys.cli", "base", "migrer"])
    dm = mig.json()
    e.constat("`opsys-metier base migrer` (logiciel courant) : code 0, révision 0040", bool(dm) and dm["code"] == 0 and '"0040"' in dm["stdout"],
              dm and (dm["stdout"][-120:] or dm["stderr"][-200:]))
    if dm:
        e.mesure("migration_0038_vers_0040", {"duree_s": dm["duree_s"], "rss_max_mo": round(dm["rss_max_enfant_ko"] / 1024, 1)
                                              })
    r1 = b.une_fois("512m", mont, [INTERNE, "empreinte"])
    d1 = r1.json()
    if d0 and d1:
        anciennes = [t for t in d0["details"] if t != "alembic_version"]
        perdues = [t for t in anciennes if d1["details"].get(t) != d0["details"][t]]
        e.constat("aucune donnée existante perdue ou modifiée (toutes les tables de 0038 identiques)", not perdues, perdues or "identiques")
        nouvelles = sorted(set(d1["details"]) - set(d0["details"]))
        e.mesure("tables_ajoutees_par_la_mise_a_jour", len(nouvelles))
        e.constat("integrity_check = ok après mise à jour", d1["integrity_check"] and d1["revision"] == "0040")
    copier(pa, pa + "d")  # base migrée, avant tout démarrage de service : pour le retour arrière
    copier(pa, pa + "e")  # idem : pour l'essai du logiciel précédent sur une base à la tête
    # démarrage des services sur la base mise à jour
    pb = f"{pile}u"
    b.creer_volumes(pb, ("cfg",))
    cu = b.demarrer(f"{pile}-su", pb, memoire, ["-v", f"{b.volume(pa, 'data')}:/opt/data", "-v", f"{b.volume(pb, 'cfg')}:/openclaw-config",
                                                 "-v", f"{b.volume(pile, 'cles')}:/cles", "-v", f"{b.volume(pile, 'sauv')}:/sauvegardes"],
                    b.env_service())
    code, secs, hist = b.attendre_pret(cu, attendu=(0, 3))
    e.constat("services démarrés sur la base mise à jour (readiness 0 ou 3 « en attente de configuration »)", code in (0, 3), hist[-4:])
    res, d = b.interne(cu, "sondes")
    e.constat("sondes MCP/console répondent sur la base mise à jour",
              bool(d) and all(s["ok"] for s in d["sondes"] if "readiness" not in s["nom"]), [s["nom"] for s in (d or {}).get("sondes", []) if not s["ok"]])
    ar2 = b.arreter(cu)
    e.constat("arrêt propre après mise à jour (code 0)", ar2["code_sortie"] == 0, ar2)
    # retour arrière alembic (sur la copie)
    md = ["-v", f"{b.volume(pa + 'd', 'data')}:/opt/data"]
    desc = b.une_fois("512m", md, [INTERNE, "migrer-vers", "descendre", "0038"])
    dd = desc.json()
    e.constat("retour arrière alembic 0040 -> 0038 : code 0", bool(dd) and desc.code == 0 and dd["apres"] == "0038", dd)
    rd = b.une_fois("512m", md, [INTERNE, "empreinte"]).json()
    if d0 and rd:
        perdues = [t for t in d0["details"] if t != "alembic_version" and rd["details"].get(t) != d0["details"][t]]
        e.constat("après retour arrière : données identiques à l'état d'avant la mise à jour", not perdues, perdues or "identiques")
        e.constat("après retour arrière : integrity_check ok, révision 0038", rd["integrity_check"] and rd["revision"] == "0038")
    # l'ancien logiciel relit la base rétrogradée
    pp = ["/ancien/src"] + [f"/ancien/departments/{d.name}/src" for d in sorted((arbre / "departments").glob("m*-*"))]
    ancien_lit = b.une_fois("512m", md + ["-v", f"{arbre}:/ancien:ro"], ["-m", "opsys.cli", "base", "etat"],
                            env={"PYTHONPATH": ":".join(pp)})
    e.constat("le logiciel PRÉCÉDENT relit la base rétrogradée (base etat, révision 0038)", ancien_lit.code == 0 and '"0038"' in ancien_lit.out,
              (ancien_lit.out + ancien_lit.err)[-200:])
    # ré-montée : même résultat qu'une première montée
    remonte = b.une_fois("512m", md, [INTERNE, "migrer-vers", "monter", "head"]).json()
    rr = b.une_fois("512m", md, [INTERNE, "empreinte"]).json()
    e.constat("nouvelle montée à la tête : mêmes données, révision 0040", bool(remonte and rr and d1 and d0) and rr["revision"] == "0040" and
              all(rr["details"].get(t) == d1["details"].get(t) for t in d0["details"] if t != "alembic_version"))
    # logiciel précédent sur une base à la tête : refus propre, base intacte
    me = ["-v", f"{b.volume(pa + 'e', 'data')}:/opt/data"]
    refus = b.une_fois("512m", me + ["-v", f"{arbre}:/ancien:ro"], ["-m", "opsys.cli", "base", "migrer"],
                       env={"PYTHONPATH": ":".join(pp)})
    apres = b.une_fois("512m", me, [INTERNE, "empreinte"]).json()
    e.constat("logiciel PRÉCÉDENT sur base à 0040 : refus (code ≠ 0), base intacte",
              refus.code != 0 and bool(apres) and apres["revision"] == "0040" and apres["sha256_global"] == (d1 or {}).get("sha256_global"),
              {"code": refus.code, "stderr": (refus.err or refus.out)[-200:]})
    b.noeuds["pile_ancienne"] = pa
    b.noeuds["arbre_ancien"] = arbre


def injections(b: Banc, e: Etape, pile: str, bilan: dict) -> None:
    """Chaque défaut est injecté EXPLICITEMENT ; on exige : refus, code typé attendu, et instance existante intacte."""
    arch = bilan.get("archive", {}).get("fichier")
    cles = ["-v", f"{b.volume(pile, 'cles')}:/cles:ro"]
    sauv = ["-v", f"{b.volume(pile, 'sauv')}:/sauvegardes"]
    env_cle = {"OPSYS_SAUVEGARDE_CLE_FICHIER": "/cles/sauvegarde.cle"}
    ex = lambda pile_data: ["-v", f"{b.volume(pile_data, 'data')}:/opt/data"]  # noqa: E731
    if not arch:
        e.constat("prérequis : une sauvegarde existe", False)
        return

    # instance « existante » à protéger : une copie de l'instance restaurée, avec ses empreintes
    pe = f"{pile}x"
    b.creer_volumes(pe, ("data",))
    src = f"{b.volume(bilan['pile2'], 'data')}:/opt/data:ro"
    # le service restauré est arrêté (étape précédente) : copie à froid, cohérente
    b.docker("run", "--rm", "--user", "1000:1000", "-v", src, "-v", f"{b.volume(pe, 'data')}:/copie", "--entrypoint", "cp", b.image,
             "-a", "/opt/data/.", "/copie/")
    existante = ex(pe)
    emp0 = b.une_fois("512m", existante, [INTERNE, "empreinte"]).json()

    def intacte(libelle: str) -> bool:
        emp = b.une_fois("512m", existante, [INTERNE, "empreinte"]).json()
        return e.constat(f"{libelle} : instance existante intacte (empreinte identique)",
                         bool(emp and emp0) and emp["sha256_global"] == emp0["sha256_global"] and emp["integrity_check"])

    def sauve(montages, argv, env=None, extra_tmpfs=()):
        r = b.une_fois("512m", montages, [INTERNE, "mesurer", "--", PYTHON_VENV, "-m", "opsys.sauvegarde_chiffree", *argv],
                       env=env if env is not None else env_cle, extra_tmpfs=extra_tmpfs)
        return r.json() or {"code": -1, "stderr": r.err[-300:], "stdout": ""}

    def refus(libelle: str, d: dict, code_texte: str, code_sortie: int) -> None:
        e.constat(f"{libelle} : refusé avec {code_texte} (code de sortie {code_sortie})",
                  d["code"] == code_sortie and code_texte in d["stderr"], {"code": d["code"], "stderr": d["stderr"][-160:]})

    # F1 mauvaise clé -----------------------------------------------------------------------------------------------
    b.docker("run", "--rm", "--user", "1000:1000", "-v", f"{b.volume(pile, 'cles')}:/cles",
             "--entrypoint", PYTHON_VENV, b.image, "-m", "opsys.sauvegarde_chiffree", "generer-cle", "/cles/autre.cle")
    d = sauve(existante + sauv + ["-v", f"{b.volume(pile, 'cles')}:/cles:ro"],
              ["restaurer", f"/sauvegardes/{arch}", "--remplacer", "--par", "banc"],
              env={"OPSYS_SAUVEGARDE_CLE_FICHIER": "/cles/autre.cle"})
    refus("F1 restauration avec une mauvaise clé (sur instance non vide, --remplacer)", d, "REJ-SAUVEGARDE-MAUVAISE-CLE", 14)
    intacte("F1")

    # F2 base corrompue (a) base vivante abîmée, (b) archive scellée contenant une base abîmée --------------------------
    pc = f"{pile}c"
    b.creer_volumes(pc, ("data",))
    b.docker("run", "--rm", "--user", "1000:1000", "-v", f"{b.volume(pe, 'data')}:/opt/data:ro", "-v", f"{b.volume(pc, 'data')}:/copie",
             "--entrypoint", "cp", b.image, "-a", "/opt/data/.", "/copie/")
    b.une_fois("256m", ex(pc), [INTERNE, "corrompre", "/opt/data/opsys.db", "pages"])
    d = sauve(ex(pc) + sauv + cles, ["sauvegarder", "--dossier", "/sauvegardes/corrompue", "--par", "banc"])
    refus("F2a export d'une base vivante corrompue (pages écrasées)", d, "REJ-SAUVEGARDE-BASE-CORROMPUE", 26)
    seuls = b.une_fois("256m", sauv + cles, ["-c", "import os;d='/sauvegardes/corrompue';print([f for f in (os.listdir(d) if "
                                                  "os.path.isdir(d) else []) if f.endswith(('.enc','.partiel')) or f.startswith('opsys-sauv')])"])
    e.constat("F2a aucune sauvegarde (ni partielle ni dossier temporaire) n'a été laissée", seuls.out.strip() == "[]", seuls.out.strip()[-200:])
    pk = f"{pile}k"
    b.creer_volumes(pk, ("data",))
    fab = b.une_fois("512m", existante + sauv + cles,
                     [INTERNE, "fabriquer-archive", "base-corrompue", "/sauvegardes/piegee-base.tar.gz.enc"], env=env_cle)
    e.constat("F2b archive piégée fabriquée (manifeste cohérent, base abîmée)", fab.code == 0, fab.err[-200:])
    d = sauve(ex(pk) + sauv + cles, ["restaurer", "/sauvegardes/piegee-base.tar.gz.enc", "--par", "banc"])
    refus("F2b restauration d'une archive authentique contenant une base corrompue", d, "REJ-SAUVEGARDE-BASE-CORROMPUE", 26)
    absent = b.une_fois("256m", ex(pk), ["-c", "import os;print(os.listdir('/opt/data'))"])
    e.constat("F2b la cible n'a reçu aucun fichier (rien de partiel)", absent.out.strip() == "[]", absent.out.strip())

    # F3 migration interrompue (SIGKILL à mi-chemin) ------------------------------------------------------------------
    pa = b.noeuds.get("pile_ancienne")
    if pa:
        b.creer_volumes(pa + "m", ("data",))
        ref = f"{b.volume(pa + 's', 'data')}:/ref:ro"
        r = b.une_fois("512m", ["-v", f"{b.volume(pa + 'm', 'data')}:/opt/data", "-v", ref],
                       [INTERNE, "migration-interrompue", "/ref/opsys.db"], timeout=900)
        d = r.json()
        e.constat("F3 migration 0038->0040 tuée (SIGKILL) à 6 stades : base saine, atomique, reprise sans perte", r.code == 0 and bool(d), d and {
            "instructions": d["instructions_totales"], "revisions_apres_kill": [x["revision"] for x in d["essais"]],
            "reprise": d["reprise"]})
        e.mesure("F3_detail", d)
    else:
        e.constat("F3 prérequis (instance ancienne)", False)

    # F4 disque plein -------------------------------------------------------------------------------------------------
    d = sauve(existante + cles, ["sauvegarder", "--dossier", "/plein", "--par", "banc"], extra_tmpfs=("/plein:size=96k,mode=1777",))
    refus("F4 disque plein (destination de 96 Ko)", d, "REJ-SAUVEGARDE-DISQUE-PLEIN", 19)
    intacte("F4")
    e.note("F4 : le conteneur de test n'a pas de fichier résiduel visible dans /plein (le tmpfs est éphémère) ; la preuve de nettoyage "
           "des `.partiel` est dans les tests unitaires tests/test_sauvegarde_chiffree.py::test_disque_plein_ne_laisse_aucun_fichier_partiel.")

    # F5 secret manquant ---------------------------------------------------------------------------------------------
    d = sauve(existante + sauv, ["sauvegarder", "--dossier", "/sauvegardes/sanscle", "--par", "banc"], env={})
    refus("F5a clé de sauvegarde absente (variable non définie)", d, "REJ-SAUVEGARDE-CLE-ABSENTE", 10)
    for variable, attendu_sortie in (("OPSYS_CONSOLE_SECRET", "OPSYS_CONSOLE_SECRET requis"), ("OPSYS_MCP_JETON", "au moins 24 caractères")):
        pf = f"{pile}f"
        nom = f"{variable.lower().replace('_', '-')}"
        b.creer_volumes(pf + nom[-4:], ("cfg",))
        cont = b.demarrer(f"{pile}-f-{nom}", pf, "512m", existante + ["-v", f"{b.volume(pf + nom[-4:], 'cfg')}:/openclaw-config"],
                          b.env_service(omettre=(variable,)))
        debut = time.monotonic()
        while time.monotonic() - debut < 60:
            if b.docker("inspect", "-f", "{{.State.Running}}", cont, enregistrer=False).out.strip() == "false":
                break
            time.sleep(1)
        etat = b.docker("inspect", "-f", "{{.State.Running}}|{{.State.ExitCode}}", cont, enregistrer=False).out.strip()
        journaux = b.docker("logs", cont, enregistrer=False)
        texte = journaux.out + journaux.err
        e.constat(f"F5b {variable} manquant : le service s'arrête avec un code non nul et le dit", etat.startswith("false|") and
                  etat != "false|0" and (attendu_sortie in texte or "ValueError" in texte or "doit faire" in texte),
                  {"etat": etat, "extrait": texte.strip()[-200:]})
        b.docker("rm", "-f", cont)
    intacte("F5")
    b.creer_volumes(pile + "g", ("cfg",))
    cg = b.demarrer(f"{pile}-g", pile + "g", "512m", existante + ["-v", f"{b.volume(pile + 'g', 'cfg')}:/openclaw-config"],
                    b.env_service(omettre=("ANTHROPIC_API_KEY",)))
    code, _, hist = b.attendre_pret(cg, attendu=(0, 3))
    pret = b.docker("exec", cg, PYTHON_VENV, "/opt/opsys/deploy/readiness.py")
    e.constat("F5c clé de fournisseur de modèle absente : le service RESTE UP et dit « en attente de configuration » (readiness 3)",
              pret.code == 3 and "variables requises absentes (ANTHROPIC_API_KEY)" in pret.err,
              {"code": pret.code, "stderr": pret.err.strip()[-200:]})
    b.docker("rm", "-f", cg)

    # F6 version incompatible ----------------------------------------------------------------------------------------
    pv = f"{pile}v"
    b.creer_volumes(pv, ("data",))
    fab = b.une_fois("512m", existante + sauv + cles,
                     [INTERNE, "fabriquer-archive", "revision-future", "/sauvegardes/future.tar.gz.enc"], env=env_cle)
    e.constat("F6a archive d'une version PLUS RÉCENTE fabriquée (révision 9999, manifeste cohérent)", fab.code == 0, fab.err[-200:])
    d = sauve(ex(pv) + sauv + cles, ["restaurer", "/sauvegardes/future.tar.gz.enc", "--par", "banc"])
    refus("F6a restauration d'une archive de version plus récente", d, "REJ-SAUVEGARDE-VERSION-LOGICIEL", 25)
    b.une_fois("256m", sauv, ["-c", "import sys;p='/sauvegardes/"+arch+"';d=bytearray(open(p,'rb').read());d[8]=99;"
                                      "open('/sauvegardes/format-futur.tar.gz.enc','wb').write(bytes(d))"])
    d = sauve(ex(pv) + sauv + cles, ["verifier", "/sauvegardes/format-futur.tar.gz.enc"])
    refus("F6b format de sauvegarde chiffrée de version inconnue (v99)", d, "REJ-SAUVEGARDE-VERSION-FORMAT", 18)
    intacte("F6")

    # F7 restauration partielle corrompue (troncature, octet modifié) ------------------------------------------------
    for mode, code_texte, code_sortie, libelle in (("tronquer", "REJ-SAUVEGARDE-TRONQUEE", 16, "F7a archive tronquée à 50 %"),
                                                    ("bit", "REJ-SAUVEGARDE-ALTEREE", 15, "F7b un seul bit modifié au milieu")):
        b.une_fois("256m", sauv, ["-c", "import shutil;shutil.copyfile('/sauvegardes/" + arch + "','/sauvegardes/abimee-" + mode + ".tar.gz.enc')"])
        b.une_fois("256m", sauv, [INTERNE, "corrompre", f"/sauvegardes/abimee-{mode}.tar.gz.enc", mode])
        cible = f"{pile}{mode[0]}"
        b.creer_volumes(cible, ("data",))
        d = sauve(ex(cible) + sauv + cles, ["restaurer", f"/sauvegardes/abimee-{mode}.tar.gz.enc", "--par", "banc"])
        refus(libelle + " (restauration sur cible vierge)", d, code_texte, code_sortie)
        vide = b.une_fois("256m", ex(cible), ["-c", "import os;print(os.listdir('/opt/data'))"])
        e.constat(f"{libelle} : la cible reste vide (rien d'écrit, ni .partiel)", vide.out.strip() == "[]", vide.out.strip())
        d = sauve(existante + sauv + cles, ["restaurer", f"/sauvegardes/abimee-{mode}.tar.gz.enc", "--remplacer", "--par", "banc"])
        refus(libelle + " (sur instance non vide, --remplacer)", d, code_texte, code_sortie)
    intacte("F7")

    # F8 clé placée dans le dossier des sauvegardes -------------------------------------------------------------------
    b.une_fois("256m", sauv + cles, ["-c", "import shutil,os;shutil.copyfile('/cles/sauvegarde.cle','/sauvegardes/sauvegarde.cle');"
                                           "os.chmod('/sauvegardes/sauvegarde.cle',0o600)"])
    d = b.une_fois("512m", existante + sauv + cles, [INTERNE, "mesurer", "--", PYTHON_VENV, "-m", "opsys.sauvegarde_chiffree",
                                                      "sauvegarder", "--dossier", "/sauvegardes", "--par", "banc"],
                   env={"OPSYS_SAUVEGARDE_CLE_FICHIER": "/sauvegardes/sauvegarde.cle"}).json()
    refus("F8 clé de sauvegarde rangée dans le dossier des sauvegardes", d, "REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE", 13)
    intacte("F8")


def etape_gabarits(b: Banc, gabarits: tuple[str, ...] = GABARITS_BALAYAGE) -> list[dict]:
    """Descend de gabarit en gabarit jusqu'au premier qui ne tient plus (le plus petit viable est le dernier avant lui)."""
    resultats = []
    for g in gabarits:
        bilan = chaine(b, f"g{g}", g, complet=False)
        resultats.append(bilan)
        if not bilan.get("viable"):
            break
    return resultats


def ecrire_rapport(b: Banc, extra: dict) -> None:
    resume = [{"etape": e.identifiant, "verdict": e.verdict, "duree_s": e.duree_s,
               "constats_en_echec": [c["nom"] for c in e.constats if not c["ok"]]} for e in b.etapes]
    corps = {"run_id": b.run_id, "fin": maintenant(), "etapes": resume,
             "passes": sum(1 for e in b.etapes if e.verdict == "PASSE"), "echecs": sum(1 for e in b.etapes if e.verdict != "PASSE"),
             **extra}
    texte = b.masque.masquer(json.dumps(corps, indent=2, ensure_ascii=False, default=str)) + "\n"
    if b.masque.fuites(texte):
        raise RuntimeError("secret en clair dans le rapport")
    (b.dossier / "RAPPORT.json").write_text(texte, encoding="utf-8")
    lignes = [f"# Rapport du banc {b.run_id}", "", f"Fin : {corps['fin']}  ·  étapes PASSE : {corps['passes']}  ·  ÉCHEC : {corps['echecs']}", "",
              "| Étape | Verdict | Durée (s) | Constats en échec |", "|---|---|---|---|"]
    for r in resume:
        lignes.append(f"| {r['etape']} | {r['verdict']} | {r['duree_s']} | {'; '.join(r['constats_en_echec'])[:240]} |")
    lignes += ["", "Ce rapport ne qualifie PAS un VPS : voir docs/qualification/QUALIFICATION-CONTENEUR.md, rubrique « NON PROUVÉ ».", ""]
    (b.dossier / "RAPPORT.md").write_text(b.masque.masquer("\n".join(lignes)), encoding="utf-8")


def principal(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("commande", choices=["tout", "gabarit", "balayage"])
    p.add_argument("--sortie", type=Path, default=RACINE / "docs/qualification/preuves")
    p.add_argument("--memoire", default="4g")
    p.add_argument("--venv", type=Path, default=None)
    p.add_argument("--garder-image", action="store_true")
    p.add_argument("--image", default="opsys-qualif:banc")
    p.add_argument("--gabarits", nargs="*", default=None, help="balayage : liste de gabarits (défaut : 1g … 96m)")
    args = p.parse_args(argv)
    venv = args.venv or next((v for v in (RACINE / ".venv", Path(os.environ.get("QUALIF_VENV", "/nonexistent"))) if (v / "bin/python").exists()), None)
    if venv is None:
        print("venv Python introuvable : donner --venv (environnement déjà installé, copié sans réseau)", file=sys.stderr)
        return 2
    b = Banc(args.sortie, args.image, venv, args.garder_image)
    resultats: dict = {}
    try:
        etape_prevol(b)
        deps = b.tmp / "deps"
        if not etape_construction(b, deps):
            ecrire_rapport(b, {"abandon": "construction de l'image en échec"})
            return 1
        etape_installateur_public(b)
        if args.commande in ("tout", "gabarit"):
            gabarits = ["4g", "2g"] if args.commande == "tout" else [args.memoire]
            for g in gabarits:
                resultats[f"complet_{g}"] = chaine(b, f"c{g}", g, complet=True)
        if args.commande in ("tout", "balayage"):
            resultats["balayage"] = etape_gabarits(b, tuple(args.gabarits) if args.gabarits else GABARITS_BALAYAGE)
        with b.etape("E90-etat-final", "Conteneurs étrangers intacts, disque, nettoyage", "aucun conteneur étranger modifié") as e:
            apres = {ligne.split("|")[0]: ligne.split("|")[1].split()[0] for ligne in
                     b.docker("ps", "-a", "--format", "{{.Names}}|{{.Status}}", enregistrer=False).out.strip().splitlines()
                     if not ligne.startswith(b.prefixe)}
            avant = b.noeuds.get("conteneurs_etrangers_avant", {})
            e.constat("les conteneurs étrangers existent encore, même état (Up/Exited)", all(apres.get(k) == v for k, v in avant.items()),
                      {k: (v, apres.get(k)) for k, v in avant.items() if apres.get(k) != v})
            e.mesure("docker_system_df", b.docker("system", "df", "--format", "{{.Type}}: {{.Size}} (récupérable {{.Reclaimable}})",
                                                  enregistrer=False).out.strip().splitlines())
    finally:
        rapport = b.nettoyer()
        def allege(bilan):
            if isinstance(bilan, list):
                return [allege(x) for x in bilan]
            return {k: v for k, v in bilan.items() if k not in ("empreinte_avant", "cont2", "pile2")}

        mesures = {"nettoyage": rapport, "bilans": {k: allege(v) for k, v in resultats.items()}}
        ecrire_rapport(b, mesures)
    print(f"[banc] preuves : {b.dossier}")
    # E02 (installateur public) est un échec documenté ; les étapes `g…` du balayage sont des MESURES (le premier gabarit
    # qui ne tient plus échoue par construction) : ni l'un ni l'autre ne fait échouer le banc.
    return 0 if all(e.verdict == "PASSE" for e in b.etapes
                    if e.identifiant != "E02-installateur-public" and not e.identifiant.startswith("g")) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
