#!/usr/bin/env python3
"""Sous-commandes exécutées DANS le conteneur de qualification (utilisateur non root, venv de l'image).

Pilotées par `banc.py` (hôte). Chacune écrit UN objet JSON sur stdout (et rien d'autre) et sort avec un code qui dit la
vérité : 0 seulement si ce qu'elle affirme est vérifié. Aucun mot de passe, jeton ou clé n'est jamais écrit : les mots de
passe de test sont des fichiers 0600 de /cles créés ici (`preparer-secrets`), lus ici, invisibles de l'hôte.

Les actions « humaines » (créer une personne, approuver) passent par la VRAIE CLI `opsys-metier` sous un pseudo-terminal :
la CLI exige un terminal et un mot de passe tapé, `--par` seul n'est pas une preuve.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import http.client
import json
import os
import pty
import re
import resource
import secrets
import select
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

CLES = Path(os.environ.get("QUALIF_CLES", "/cles"))
MDP_PROPRIETAIRE = CLES / "mdp-nathan"
MDP_AGENT = CLES / "mdp-agent-systeme"
CLE_SAUVEGARDE = CLES / "sauvegarde.cle"
HOME_DONNEES = Path(os.environ.get("OPSYS_HOME", "/opt/data"))
VENV_PYTHON = sys.executable
SMS_FICTIF = {"canal": "sms", "expediteur": "+15145550142", "message_id": "SMfictif-banc-0001",
              "recu_le": "2026-11-01T09:15:00-04:00",
              "texte": "Bonjour, je voudrais une soumission pour un entretien fictif à Laval."}
HORODATAGE = "2026-11-01T11:00:00-04:00"


def sortie(objet: object, code: int = 0) -> int:
    print(json.dumps(objet, ensure_ascii=False, indent=2, default=str))
    return code


# -- outils communs -----------------------------------------------------------------------------------------------

def cli_humain(arguments: list[str], mdp_fichier: Path | None, delai: float = 180.0) -> dict:
    """Lance `opsys-metier <arguments>` sous un pty ; tape le mot de passe quand la CLI le demande."""
    mdp = mdp_fichier.read_text(encoding="utf-8").strip() if mdp_fichier else None
    debut = time.monotonic()
    pid, fd = pty.fork()
    if pid == 0:  # enfant
        os.execv(VENV_PYTHON, [VENV_PYTHON, "-m", "opsys.cli", *arguments])
    brut = b""
    envoye = False
    while time.monotonic() - debut < delai:
        pret, _, _ = select.select([fd], [], [], 0.5)
        if not pret:
            continue
        try:
            morceau = os.read(fd, 4096)
        except OSError:
            break
        if not morceau:
            break
        brut += morceau
        if mdp is not None and not envoye and b"Mot de passe" in brut:
            os.write(fd, (mdp + "\n").encode())
            envoye = True
    else:
        os.kill(pid, 9)
    _, statut = os.waitpid(pid, 0)
    texte = brut.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if mdp and mdp in texte:  # ne devrait jamais arriver (echo coupé) : on refuse de le propager
        texte = texte.replace(mdp, "***")
    return {"code": os.waitstatus_to_exitcode(statut), "sortie": texte.strip()[-2500:],
            "mot_de_passe_demande": envoye, "duree_s": round(time.monotonic() - debut, 2)}


def cli(arguments: list[str], delai: float = 180.0) -> dict:
    debut = time.monotonic()
    p = subprocess.run([VENV_PYTHON, "-m", "opsys.cli", *arguments], capture_output=True, text=True, timeout=delai,
                       stdin=subprocess.DEVNULL, check=False)
    return {"code": p.returncode, "stdout": p.stdout[-2500:], "stderr": p.stderr[-2500:],
            "duree_s": round(time.monotonic() - debut, 2)}


def http_obtenir(port: int, chemin: str, methode: str = "GET", entetes: dict | None = None,
                 corps: bytes | None = None) -> dict:
    cnx = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        cnx.request(methode, chemin, body=corps, headers=entetes or {})
        r = cnx.getresponse()
        donnees = r.read(4096)
        return {"statut": r.status, "entetes": {k.lower(): v for k, v in r.getheaders()},
                "corps_debut": donnees[:300].decode("utf-8", errors="replace")}
    except OSError as erreur:
        return {"statut": None, "erreur": type(erreur).__name__}
    finally:
        cnx.close()


# -- preparer-secrets ----------------------------------------------------------------------------------------------

def commande_preparer_secrets(_args) -> int:
    from opsys import sauvegarde_chiffree

    os.chmod(CLES, 0o700)
    cree = []
    for chemin in (MDP_PROPRIETAIRE, MDP_AGENT):
        if not chemin.exists():
            fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, (secrets.token_urlsafe(24) + "\n").encode())
            os.close(fd)
            cree.append(chemin.name)
    if not CLE_SAUVEGARDE.exists():
        sauvegarde_chiffree.generer_cle(CLE_SAUVEGARDE)
        cree.append(CLE_SAUVEGARDE.name)
    modes = {p.name: oct(p.stat().st_mode & 0o777) for p in sorted(CLES.iterdir())}
    return sortie({"crees": cree, "modes": modes, "dossier_mode": oct(CLES.stat().st_mode & 0o777)})


# -- initialiser ---------------------------------------------------------------------------------------------------

def commande_initialiser(_args) -> int:
    """Instance fictive : personnes, paliers, entreprise, profils de base. Chaque sous-étape garde son code réel."""
    etapes: list[dict] = []

    def etape(nom: str, resultat: dict, attendu: int = 0) -> None:
        etapes.append({"nom": nom, "code": resultat["code"], "attendu": attendu, "ok": resultat["code"] == attendu,
                       "extrait": (resultat.get("sortie") or resultat.get("stderr") or resultat.get("stdout") or "")[-300:]})

    etape("verifier", cli(["verifier"]))
    etape("personnes creer nathan (nathan_owner)",
          cli_humain(["personnes", "creer", "nathan", "--nom", "Nathan Propriétaire (fictif)", "--role", "nathan_owner"],
                     MDP_PROPRIETAIRE))
    etape("personnes creer agent-systeme (system_agent)",
          cli_humain(["personnes", "creer", "agent-systeme", "--nom", "Agent système (fictif)", "--role",
                      "system_agent"], MDP_AGENT))
    etape("paliers definir standard", cli(["paliers", "definir", "standard", "--provider", "anthropic", "--model",
                                          "claude-sonnet-5"]))
    etape("paliers definir rapide", cli(["paliers", "definir", "rapide", "--provider", "anthropic", "--model",
                                        "claude-haiku-5"]))
    from opsys import taxonomie

    taxonomie.enregistrer_services([{"code": "entretien_fictif", "libelle": "Entretien fictif",
                                     "mots_cles": ["entretien", "soumission", "service de test"]}], par="banc")
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"], par="banc")
    etape("entreprise fictive (services + zone)", {"code": 0, "sortie": "entreprise.yaml écrit"})
    etape("agents-base provisionner",
          cli_humain(["agents-base", "provisionner", "--par", "nathan", "--limite-tours", "8", "--limite-reessais", "2",
                      "--limite-concurrence", "2", "--budget-entreprise-jour", "200000",
                      "--budget-entreprise-mois", "4000000"], MDP_PROPRIETAIRE))
    ok = all(e["ok"] for e in etapes)
    return sortie({"etapes": etapes}, 0 if ok else 1)


# -- sondes --------------------------------------------------------------------------------------------------------

ENTETES_ATTENDUS = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
                    "cache-control": "no-store"}


def commande_sondes(_args) -> int:
    jeton = os.environ.get("OPSYS_MCP_JETON", "")
    sondes: list[dict] = []

    def sonde(nom: str, ok: bool, detail: object) -> None:
        sondes.append({"nom": nom, "ok": bool(ok), "detail": detail})

    r = http_obtenir(8765, "/sante")
    sonde("MCP GET /sante = 200 + JSON ok", r["statut"] == 200 and '"ok"' in r.get("corps_debut", ""),
          {"statut": r["statut"], "corps": r.get("corps_debut")})
    r = http_obtenir(8765, "/sante", "POST", {"Content-Length": "0"})
    sonde("MCP POST /sante = 405", r["statut"] == 405, r["statut"])
    r = http_obtenir(8765, "/mcp/m01-front-office", "POST", {"Content-Type": "application/json"}, b"{}")
    sonde("MCP sans jeton = 401", r["statut"] == 401, r["statut"])
    r = http_obtenir(8765, "/mcp/m01-front-office", "POST",
                     {"Content-Type": "application/json", "Authorization": "Bearer " + "x" * 40}, b"{}")
    sonde("MCP mauvais jeton = 401", r["statut"] == 401, r["statut"])
    r = http_obtenir(8765, "/mcp/m01-front-office", "POST",
                     {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                      "Authorization": f"Bearer {jeton}"},
                     json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                         "protocolVersion": "2025-03-26", "capabilities": {},
                         "clientInfo": {"name": "banc", "version": "1"}}}).encode())
    sonde("MCP bon jeton : initialize accepté (200)", r["statut"] == 200, r["statut"])
    r = http_obtenir(8700, "/connexion")
    manquants = {k: v for k, v in ENTETES_ATTENDUS.items() if r.get("entetes", {}).get(k, "").lower() != v.lower()}
    sonde("console GET /connexion = 200", r["statut"] == 200, r["statut"])
    sonde("console : en-têtes de sécurité (nosniff, DENY, no-referrer, no-store)", not manquants and
          "content-security-policy" in r.get("entetes", {}), {"manquants": manquants,
                                                              "csp": r.get("entetes", {}).get("content-security-policy")})
    r2 = http_obtenir(8700, "/page-qui-n-existe-pas")
    sonde("console 404 sans trace d'exécution", r2["statut"] == 404 and "Traceback" not in r2.get("corps_debut", ""),
          r2["statut"])
    r3 = http_obtenir(8700, "/departements")
    sonde("console /departements sans session : redirigé vers la connexion", r3["statut"] in (302, 303, 307) and
          "connexion" in r3.get("entetes", {}).get("location", ""), {"statut": r3["statut"],
                                                                      "location": r3.get("entetes", {}).get("location")})
    p = subprocess.run([VENV_PYTHON, "/opt/opsys/deploy/readiness.py"], capture_output=True, text=True, timeout=30,
                       check=False)
    sonde("readiness.py = 0 (prêt)", p.returncode == 0, {"code": p.returncode, "stdout": p.stdout[-400:],
                                                         "stderr": p.stderr[-400:]})
    return sortie({"sondes": sondes, "headers_console": r.get("entetes")}, 0 if all(s["ok"] for s in sondes) else 1)


# -- parcours ------------------------------------------------------------------------------------------------------

async def _appel_mcp(departement: str, outil: str, arguments: dict) -> tuple[dict, bool]:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {os.environ['OPSYS_MCP_JETON']}"})
    async with http_client, streamable_http_client(f"http://127.0.0.1:8765/mcp/{departement}",
                                                   http_client=http_client) as flux, \
            ClientSession(flux[0], flux[1]) as client:
        await client.initialize()
        reponse = await client.call_tool(outil, arguments)
        return json.loads(reponse.content[0].text), bool(reponse.is_error)


def commande_parcours(_args) -> int:
    """Un lead, une soumission, une approbation N3 refusée sans humain puis accordée. Tout est vérifié en base."""
    from m1_front_office import outils as m1_outils
    from m2_revenue_crm import outils as m2_outils
    from sqlalchemy import select

    from opsys import approbations, evenements, stockage
    from opsys.departements import charger_departements
    from opsys.outils import Niveau, executer_atomique
    from opsys.stockage.schema import APPROBATIONS

    deps = charger_departements()
    m1_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    constats: list[dict] = []

    def constat(nom: str, ok: bool, detail: object = None) -> None:
        constats.append({"nom": nom, "ok": bool(ok), "detail": detail})

    def outil(dep: str, nom: str):
        return {o.nom: o for o in deps[dep].charger_outils()}[nom]

    def drainer() -> dict:
        total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0}
        for _ in range(12):
            r = evenements.repartir(deps, maintenant=dt.datetime.now(dt.UTC).isoformat())
            for k in total:
                total[k] += r[k]
            if r["livres"] == 0:
                break
            time.sleep(0.3)
        return total

    # 1. Le lead arrive par la vraie route MCP HTTP (service démarré), jeton exigé.
    reponse, erreur = asyncio.run(_appel_mcp("m01-front-office", "m1_recevoir_message_canal", SMS_FICTIF))
    resultat = reponse.get("resultat", {})
    lead_id = (resultat.get("lead") or {}).get("lead_id")
    constat("M1 reçoit le message et transmet à M2 (route MCP HTTP)",
            not erreur and resultat.get("decision") == "TRANSMETTRE_M2" and bool(lead_id),
            {"decision": resultat.get("decision"), "erreur": reponse.get("erreur")})
    if not lead_id:
        return sortie({"constats": constats}, 1)
    bilan_bus = drainer()
    constat("bus : le lead est livré à M2 sans échec ni quarantaine", bilan_bus["echecs"] == 0 and
            bilan_bus["quarantaines"] == 0, bilan_bus)

    # 2. M2 qualifie ; M3 crée la soumission (brouillon).
    r = executer_atomique(outil("m02-revenue-crm", "m2_transitionner_statut"), {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": HORODATAGE, "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {"description": "Préparer la soumission (fictif)", "echeance": "2026-11-03T09:00:00-04:00"}})
    constat("M2 : lead qualifié", r.get("ok") is True and r["resultat"].get("accepte") is True, r.get("erreur"))
    devis = {"devis_id": "DEVIS-BANC-1", "lead_id": lead_id, "chantier_id": None,
             "lignes": [{"description": "Service d'entretien (fictif)", "quantite": "10", "unite": "h",
                         "cout_unitaire": "50.00", "reference_besoin_materiau": None}],
             "taux_marge": "0.25", "horodatage": "2026-11-01T15:00:00-04:00", "prix_total": "625.00"}
    r = executer_atomique(outil("m03-estimation", "m3_creer_devis"), devis)
    constat("M3 : soumission créée (brouillon, 625.00 $ calculé par l'outil)",
            r.get("ok") is True and r["resultat"]["resultat"]["statut"] == "brouillon" and
            r["resultat"]["resultat"]["prix_total"] == "625.00", r.get("erreur"))

    # 3. N3 sans humain : un agent (route MCP) ne peut pas marquer la soumission acceptée.
    args_n3 = {"devis_id": "DEVIS-BANC-1", "approbateur": "nathan", "horodatage": "2026-11-01T16:00:00-04:00"}
    reponse, erreur = asyncio.run(_appel_mcp("m03-estimation", "m3_marquer_devis_accepte", args_n3))
    constat("N3 par un agent (route MCP) : refusé, rien exécuté",
            erreur and reponse.get("erreur") == "ticket_cible_requis", reponse.get("erreur"))
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, "m03-estimation", "m3_marquer_devis_accepte", args_n3,
                                           niveau=Niveau.N3, motif="banc de qualification")
    index = {o.nom: o for d in deps.values() for o in d.charger_outils()}

    def statut_demande() -> str:
        with stockage.transaction() as cnx:
            return cnx.execute(select(APPROBATIONS.c.statut).where(APPROBATIONS.c.id == ident)).scalar_one()

    refus: list[str] = []
    for qui in ("", "inconnu-fictif", "agent-systeme"):
        try:
            with stockage.transaction() as cnx:
                approbations.decider(cnx, ident, True, qui, index, deps)
            refus.append(f"{qui or '(vide)'}: ACCEPTÉ (anormal)")
        except (ValueError, KeyError) as exc:
            refus.append(f"{qui or '(vide)'}: refusé ({str(exc)[:70]})")
    constat("décision sans humain habilité (identité vide, inconnue, agent système) : refusée, demande en attente",
            all("refusé" in x for x in refus) and statut_demande() == "en_attente", refus)
    sans_tty = cli(["approbations", "approuver", ident, "--par", "nathan"])
    constat("CLI sans terminal : refusée (code 1), demande en attente",
            sans_tty["code"] == 1 and statut_demande() == "en_attente", {"code": sans_tty["code"]})
    mauvais = Path("/tmp/mauvais-mdp")
    mauvais.write_text(secrets.token_urlsafe(12) + "\n")
    os.chmod(mauvais, 0o600)
    faux = cli_humain(["approbations", "approuver", ident, "--par", "nathan"], mauvais)
    mauvais.unlink()
    constat("CLI humain avec un mauvais mot de passe : refusée (code 1), demande en attente",
            faux["code"] == 1 and statut_demande() == "en_attente", {"code": faux["code"]})
    bon = cli_humain(["approbations", "approuver", ident, "--par", "nathan", "--motif", "banc de qualification"],
                     MDP_PROPRIETAIRE)
    constat("CLI humain authentifié (nathan_owner) : accordée (code 0), exécutée",
            bon["code"] == 0 and statut_demande() == "executee", {"code": bon["code"], "statut": statut_demande()})
    double = cli_humain(["approbations", "approuver", ident, "--par", "nathan"], MDP_PROPRIETAIRE)
    constat("double décision : refusée, pas de seconde exécution", double["code"] != 0, {"code": double["code"]})

    # 4. L'effet métier : le devis est accepté et le bus propage (M2 converti, M4 à planifier).
    bilan_bus2 = drainer()
    constat("bus après acceptation : sans échec ni quarantaine", bilan_bus2["echecs"] == 0 and
            bilan_bus2["quarantaines"] == 0, bilan_bus2)
    lu = executer_atomique(outil("m03-estimation", "m3_lire_devis"), {"devis_id": "DEVIS-BANC-1"})
    fiche = (lu.get("resultat") or {}).get("resultat") or {}
    constat("la soumission est acceptée en base (statut « accepte », approbateur nathan)",
            fiche.get("statut") == "accepte" and fiche.get("approbateur") == "nathan",
            {"statut": fiche.get("statut"), "approbateur": fiche.get("approbateur")})
    interv = executer_atomique(outil("m04-field-ops", "m4_lister_interventions"), {})
    constat("M4 : une intervention « a_planifier » est née de l'acceptation",
            interv.get("ok") is True and any(i.get("statut") == "a_planifier" for i in interv["resultat"]),
            len(interv.get("resultat") or []))
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(APPROBATIONS.c.statut, APPROBATIONS.c.decide_par, APPROBATIONS.c.decide_role)
                             .where(APPROBATIONS.c.id == ident)).mappings().all()
    constat("la décision porte la personne et son rôle", lignes[0]["decide_par"] == "nathan" and
            lignes[0]["decide_role"] == "nathan_owner", dict(lignes[0]))
    return sortie({"constats": constats, "lead_id": lead_id, "demande_id": ident},
                  0 if all(c["ok"] for c in constats) else 1)


# -- empreinte -----------------------------------------------------------------------------------------------------

TABLES_VOLATILES = {"alembic_version"}


def empreinte_base(chemin: Path) -> dict:
    """Comptes et SHA-256 de contenu par table (lecture seule). `journal*` : on écarte les lignes `instance.*`."""
    cnx = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=30)
    try:
        tables = [r[0] for r in cnx.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        details = {}
        for t in tables:
            colonnes = [c[1] for c in cnx.execute(f'PRAGMA table_info("{t}")')]
            requete = f'SELECT * FROM "{t}"'
            if t == "journal_audit" or ("action" in colonnes and t.startswith("journal")):
                requete += " WHERE action NOT LIKE 'instance.%'"
            lignes = sorted(json.dumps(list(r), default=str, ensure_ascii=False) for r in cnx.execute(requete))
            h = hashlib.sha256()
            for ligne in lignes:
                h.update(ligne.encode())
                h.update(b"\n")
            details[t] = {"lignes": len(lignes), "sha256": h.hexdigest()}
        revision = cnx.execute("SELECT version_num FROM alembic_version").fetchone()
        integrite = cnx.execute("PRAGMA integrity_check").fetchall()
        global_h = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()
        return {"revision": revision[0] if revision else None, "integrity_check": integrite == [("ok",)],
                "tables": len(details), "lignes_total": sum(d["lignes"] for d in details.values()),
                "sha256_global": global_h, "details": details}
    finally:
        cnx.close()


def commande_empreinte(args) -> int:
    base = Path(args.base) if args.base else HOME_DONNEES / "opsys.db"
    if not base.is_file():
        return sortie({"erreur": f"{base} absent"}, 1)
    resultat = empreinte_base(base)
    if args.compact:
        resultat = {k: v for k, v in resultat.items() if k != "details"}
    return sortie(resultat, 0 if resultat["integrity_check"] else 1)


def commande_comparer(args) -> int:
    a, b = json.loads(Path(args.a).read_text()), json.loads(Path(args.b).read_text())
    diffs = sorted(t for t in set(a["details"]) | set(b["details"]) if a["details"].get(t) != b["details"].get(t))
    return sortie({"identiques": not diffs, "tables_differentes": diffs,
                   "lignes_a": a["lignes_total"], "lignes_b": b["lignes_total"]}, 0 if not diffs else 1)


# -- mesures -------------------------------------------------------------------------------------------------------

def _lire(chemin: str) -> str | None:
    with contextlib.suppress(OSError):
        return Path(chemin).read_text().strip()
    return None


def commande_rss(_args) -> int:
    processus = []
    for dossier in sorted(Path("/proc").glob("[0-9]*"), key=lambda p: int(p.name)):
        statut = _lire(str(dossier / "status")) or ""
        nom = re.search(r"^Name:\s*(.+)$", statut, re.M)
        hwm = re.search(r"^VmHWM:\s*(\d+) kB", statut, re.M)
        rss = re.search(r"^VmRSS:\s*(\d+) kB", statut, re.M)
        if nom and hwm:
            processus.append({"pid": int(dossier.name), "nom": nom.group(1), "rss_max_ko": int(hwm.group(1)),
                              "rss_ko": int(rss.group(1)) if rss else None})
    pic = _lire("/sys/fs/cgroup/memory.peak")
    courant = _lire("/sys/fs/cgroup/memory.current")
    limite = _lire("/sys/fs/cgroup/memory.max")
    evenements = _lire("/sys/fs/cgroup/memory.events")
    return sortie({"processus": processus, "cgroup_pic_octets": int(pic) if pic else None,
                   "cgroup_courant_octets": int(courant) if courant else None, "cgroup_limite": limite,
                   "cgroup_evenements": evenements})


def commande_mesurer(args) -> int:
    """Exécute une commande, rend son code, sa durée, le RSS maximal de ses processus et le pic cgroup."""
    debut = time.monotonic()
    p = subprocess.run(args.commande, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL)
    duree = time.monotonic() - debut
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    pic = _lire("/sys/fs/cgroup/memory.peak")
    return sortie({"code": p.returncode, "duree_s": round(duree, 2), "rss_max_enfant_ko": usage.ru_maxrss,
                   "cgroup_pic_octets": int(pic) if pic else None,
                   "stdout": p.stdout[-3000:], "stderr": p.stderr[-3000:]}, 0)


# -- durcissement --------------------------------------------------------------------------------------------------

MOTIFS_SECRETS = [
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "clé privée PEM"),
    (r"\bAKIA[0-9A-Z]{16}\b", "clé d'accès AWS"), (r"\bsk-ant-[A-Za-z0-9_-]{20,}", "clé Anthropic"),
    (r"\bsk-[A-Za-z0-9]{32,}\b", "clé de type sk-"), (r"\bghp_[A-Za-z0-9]{30,}\b", "jeton GitHub"),
    (r"\bxox[abp]-[A-Za-z0-9-]{20,}", "jeton Slack"),
]


def _balayer(racines: list[str], secrets_exacts: list[str], motifs: bool, exclure: tuple[str, ...] = ()) -> dict:
    trouves: list[dict] = []
    nb = 0
    regex = [(re.compile(m.encode()), n) for m, n in MOTIFS_SECRETS]
    exacts = [s.encode() for s in secrets_exacts if s]
    for racine in racines:
        for dossier, sous, fichiers in os.walk(racine, followlinks=False):
            sous[:] = [d for d in sous if not any(os.path.join(dossier, d).startswith(x) for x in exclure)]
            for nom in fichiers:
                chemin = os.path.join(dossier, nom)
                try:
                    if os.path.islink(chemin) or os.path.getsize(chemin) > 40_000_000:
                        continue
                    with open(chemin, "rb") as f:
                        contenu = f.read()
                except OSError:
                    continue
                nb += 1
                for s in exacts:
                    if s in contenu:
                        trouves.append({"fichier": chemin, "type": "valeur de secret du banc"})
                if motifs:
                    for r, n in regex:
                        if r.search(contenu):
                            trouves.append({"fichier": chemin, "type": n})
    return {"fichiers_balayes": nb, "trouvailles": trouves}


def commande_balayer(args) -> int:
    """Cherche dans des dossiers : valeurs exactes de secrets (lues des variables d'environnement nommées) + motifs."""
    valeurs = [os.environ.get(nom, "") for nom in args.variables]
    for fichier in args.fichiers_secrets:
        with contextlib.suppress(OSError):
            valeurs.append(Path(fichier).read_text().strip())
    r = _balayer(args.racines, [v for v in valeurs if len(v) >= 8], args.motifs, tuple(args.exclure))
    return sortie(r, 0 if not r["trouvailles"] else 1)


def commande_texte_stdin(args) -> int:
    """Cherche dans stdin (journaux) les valeurs de secrets des variables nommées et des marqueurs de PII donnés."""
    texte = sys.stdin.read()
    valeurs = {nom: os.environ.get(nom, "") for nom in args.variables}
    for fichier in args.fichiers_secrets:
        with contextlib.suppress(OSError):
            valeurs[Path(fichier).name] = Path(fichier).read_text().strip()
    secrets_trouves = [nom for nom, v in valeurs.items() if v and v in texte]
    pii = [m for m in args.pii if m in texte]
    return sortie({"octets_examines": len(texte), "secrets_en_clair": secrets_trouves, "pii_trouvees": pii},
                  0 if not secrets_trouves and not pii else 1)


def commande_durcissement(_args) -> int:
    constats: list[dict] = []

    def c(nom: str, ok: bool, detail: object = None) -> None:
        constats.append({"nom": nom, "ok": bool(ok), "detail": detail})

    c("processus non root (uid/gid)", os.geteuid() != 0 and os.getegid() != 0, {"uid": os.geteuid(), "gid": os.getegid()})
    pids_root = [d.name for d in Path("/proc").glob("[0-9]*") if (_lire(str(d / "status")) or "").find("Uid:\t0") >= 0]
    c("aucun processus du conteneur ne tourne en root", not pids_root, pids_root)
    ecritures = {}
    for chemin in ("/opt/opsys/probe", "/usr/local/probe", "/etc/probe", "/opt/opsys-venv/probe"):
        try:
            Path(chemin).write_text("x")
            Path(chemin).unlink()
            ecritures[chemin] = "ÉCRITURE POSSIBLE"
        except OSError as exc:
            ecritures[chemin] = type(exc).__name__
    c("système de fichiers racine en lecture seule (code, venv, /etc, /usr)",
      all(v != "ÉCRITURE POSSIBLE" for v in ecritures.values()), ecritures)
    inscriptibles = {}
    for chemin in ("/tmp", "/opt/data", "/openclaw-config"):
        try:
            sonde = Path(chemin) / f".sonde-{secrets.token_hex(3)}"
            sonde.write_text("x")
            sonde.unlink()
            inscriptibles[chemin] = True
        except OSError as exc:
            inscriptibles[chemin] = type(exc).__name__
    c("seuls /tmp (tmpfs) et les volumes de données sont inscriptibles", all(v is True for v in inscriptibles.values()),
      inscriptibles)
    statut = _lire("/proc/self/status") or ""
    nnp = re.search(r"NoNewPrivs:\s*(\d)", statut)
    capeff = re.search(r"CapEff:\s*([0-9a-f]+)", statut)
    c("no-new-privileges actif", bool(nnp) and nnp.group(1) == "1", nnp.group(1) if nnp else None)
    c("aucune capacité effective", bool(capeff) and int(capeff.group(1), 16) == 0, capeff.group(1) if capeff else None)
    modes = {}
    permissif = []
    for racine in ("/opt/data", "/openclaw-config", "/cles"):
        for dossier, _s, fichiers in os.walk(racine):
            for nom in fichiers:
                chemin = os.path.join(dossier, nom)
                mode = os.lstat(chemin).st_mode & 0o777
                modes[chemin] = oct(mode)
                if mode & 0o077 and (racine == "/cles" or nom in ("opsys.db", "opsys.db-wal", "opsys.db-shm")
                                     or nom.endswith(".enc") or "mdp" in nom or nom.endswith(".cle")):
                    permissif.append((chemin, oct(mode)))
    c("fichiers de secrets et base : aucun accès groupe/autres (0600)", not permissif, permissif)
    c("dossier des clés en 0700", (os.stat("/cles").st_mode & 0o777) == 0o700, oct(os.stat("/cles").st_mode & 0o777))
    ecoute = set()
    for fichier in ("/proc/net/tcp", "/proc/net/tcp6"):
        for ligne in (_lire(fichier) or "").splitlines()[1:]:
            champs = ligne.split()
            if len(champs) > 3 and champs[3] == "0A":
                ecoute.add(int(champs[1].split(":")[1], 16))
    c("ports en écoute minimaux : exactement 8765 (MCP) et 8700 (console)", ecoute == {8765, 8700}, sorted(ecoute))
    return sortie({"constats": constats, "modes_fichiers": modes},
                  0 if all(x["ok"] for x in constats) else 1)


# -- injections de défauts : archives piégées ----------------------------------------------------------------------

def commande_fabriquer_archive(args) -> int:
    """Fabrique une archive d'export COHÉRENTE (manifeste à jour) mais piégée, puis la chiffre : `base-corrompue` ou
    `revision-future`. Sert à atteindre les refus de contenu que l'empreinte du manifeste ne couvre pas."""
    import io
    import tarfile
    import tempfile

    from opsys import exportation, sauvegarde_chiffree

    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        tmp = Path(tmp)
        export = exportation.exporter(HOME_DONNEES, tmp / "e.tar.gz", par="banc")
        with tarfile.open(export.archive) as tar:
            membres = {m.name.split("/", 1)[1]: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
        base = bytearray(membres["opsys.db"])
        manifeste = json.loads(membres["manifeste.json"])
        if args.mode == "base-corrompue":
            for i in range(8192, min(len(base), 8192 + 8192)):
                base[i] = 0xAB
        else:
            cnx_tmp = tmp / "b.db"
            cnx_tmp.write_bytes(bytes(base))
            c = sqlite3.connect(cnx_tmp)
            c.execute("UPDATE alembic_version SET version_num='9999'")
            c.commit()
            c.close()
            base = bytearray(cnx_tmp.read_bytes())
            manifeste["base"]["revision"] = "9999"
        membres["opsys.db"] = bytes(base)
        for f in manifeste["fichiers"]:
            if f["chemin"] == "opsys.db":
                f["sha256"], f["octets"] = hashlib.sha256(bytes(base)).hexdigest(), len(base)
        membres["manifeste.json"] = json.dumps(manifeste).encode()
        piegee = tmp / "piegee.tar.gz"
        with tarfile.open(piegee, "w:gz") as tar:
            for nom, contenu in membres.items():
                info = tarfile.TarInfo(f"opsys-export/{nom}")
                info.size = len(contenu)
                tar.addfile(info, io.BytesIO(contenu))
        sortie_chiffree = Path(args.sortie)
        sauvegarde_chiffree.chiffrer_fichier(piegee, sortie_chiffree, sauvegarde_chiffree.lire_cle())
    return sortie({"archive": str(sortie_chiffree), "mode": args.mode})


def commande_corrompre(args) -> int:
    """Abîme des octets d'un fichier (page de base SQLite, ou archive) en place : injection de défaut explicite."""
    chemin = Path(args.fichier)
    contenu = bytearray(chemin.read_bytes())
    if args.mode == "pages":
        for i in range(8192, min(len(contenu), 8192 + 16384)):
            contenu[i] = 0xAB
    elif args.mode == "bit":
        contenu[len(contenu) // 2] ^= 0x01
    elif args.mode == "tronquer":
        contenu = contenu[: len(contenu) // 2]
    chemin.write_bytes(bytes(contenu))
    return sortie({"fichier": str(chemin), "mode": args.mode, "octets": len(contenu)})


# -- migrations ----------------------------------------------------------------------------------------------------

def commande_migrer_vers(args) -> int:
    """Monte ou descend la base à une révision donnée (alembic), par la connexion que fournit `opsys.stockage`."""
    from alembic import command

    from opsys import stockage

    avant = stockage.revision_courante()
    try:
        configuration = stockage._config()
        with stockage.moteur().begin() as connexion:
            configuration.attributes["connection"] = connexion
            (command.upgrade if args.sens == "monter" else command.downgrade)(configuration, args.cible)
    except Exception as exc:  # noqa: BLE001 — le refus (typé ou non) EST le résultat qu'on consigne
        return sortie({"avant": avant, "apres": stockage.revision_courante(), "erreur": type(exc).__name__,
                       "message": str(exc)[:400]}, 1)
    return sortie({"avant": avant, "apres": stockage.revision_courante()})


def commande_migrer_avec_crash(args) -> int:
    """Enfant de `migration-interrompue` : `base migrer` réel, mais le processus se tue (SIGKILL) à la N-ième instruction
    SQL (N = 0 : ne tue pas, compte seulement et l'écrit sur stdout)."""
    import signal

    from sqlalchemy import event

    from opsys import stockage

    compteur = {"n": 0}

    def surveiller(*_a, **_k) -> None:
        compteur["n"] += 1
        if args.apres and compteur["n"] >= args.apres:
            os.kill(os.getpid(), signal.SIGKILL)

    event.listen(stockage.moteur(), "before_cursor_execute", surveiller)
    revision = stockage.migrer()
    print(json.dumps({"instructions": compteur["n"], "revision": revision}))
    return 0


def commande_migration_interrompue(args) -> int:
    """Tue le processus de migration à N % de ses instructions SQL (SIGKILL réel), depuis la base de référence ; vérifie
    que la base reste saine et à sa révision d'origine (migration atomique), puis qu'une reprise aboutit sans perte."""
    import shutil

    reference = Path(args.reference)
    base = HOME_DONNEES / "opsys.db"
    attendu = empreinte_base(reference)

    def repartir_de_la_reference() -> None:
        for suffixe in ("", "-wal", "-shm"):
            Path(str(base) + suffixe).unlink(missing_ok=True)
        shutil.copyfile(reference, base)

    repartir_de_la_reference()
    comptage = subprocess.run([VENV_PYTHON, __file__, "migrer-avec-crash", "--apres", "0"], capture_output=True,
                              text=True, check=False, stdin=subprocess.DEVNULL)
    try:
        total = json.loads(comptage.stdout.strip().splitlines()[-1])["instructions"]
    except (ValueError, IndexError, KeyError):
        return sortie({"erreur": "comptage des instructions impossible", "stderr": comptage.stderr[-400:]}, 1)
    essais = []
    for fraction in args.fractions:
        repartir_de_la_reference()
        n = max(1, int(total * fraction))
        enfant = subprocess.run([VENV_PYTHON, __file__, "migrer-avec-crash", "--apres", str(n)], capture_output=True,
                                text=True, check=False, stdin=subprocess.DEVNULL)
        etat = empreinte_base(base)
        essais.append({"fraction": fraction, "tue_a_l_instruction": n, "code_enfant": enfant.returncode,
                       "integrity_check": etat["integrity_check"], "revision": etat["revision"],
                       "donnees_anciennes_intactes": all(etat["details"].get(t) == d
                                                         for t, d in attendu["details"].items() if t != "alembic_version")})
    final = cli(["base", "migrer"])
    apres = empreinte_base(base)
    intacte = all(apres["details"].get(t) == d for t, d in attendu["details"].items() if t != "alembic_version")
    # Atomicité : après un SIGKILL la base est soit à sa révision d'origine (retour en arrière, la plupart des cas), soit à
    # la tête (kill APRÈS la validation) — jamais entre les deux. Au moins trois kills doivent être tombés AVANT la validation.
    ok = (all(e["code_enfant"] == -9 and e["integrity_check"] and e["revision"] in {attendu["revision"], "0040"}
              and e["donnees_anciennes_intactes"] for e in essais)
          and sum(1 for e in essais if e["revision"] == attendu["revision"]) >= 3
          and final["code"] == 0 and apres["revision"] == "0040" and intacte and apres["integrity_check"])
    return sortie({"instructions_totales": total, "essais": essais,
                   "reprise": {"code": final["code"], "revision": apres["revision"], "donnees_anciennes_intactes": intacte,
                               "integrity_check": apres["integrity_check"]}}, 0 if ok else 1)


def commande_connexion(_args) -> int:
    """Connexion à la console : un mauvais identifiant/mot de passe est refusé (et tracé sans PII) ; le bon ouvre une
    session dont le cookie est HttpOnly, Secure et SameSite ; la page protégée répond avec le cookie, jamais sans."""
    from urllib.parse import urlencode

    constats: list[dict] = []

    def c(nom: str, ok: bool, detail: object = None) -> None:
        constats.append({"nom": nom, "ok": bool(ok), "detail": detail})

    formulaire = {"Content-Type": "application/x-www-form-urlencoded"}
    faux = http_obtenir(8700, "/connexion", "POST", formulaire,
                        urlencode({"identifiant": "intrus@example.test", "mot_de_passe": "mot-de-passe-faux-du-banc"}).encode())
    c("mauvais identifiant : pas de session (aucun Set-Cookie de session)", "set-cookie" not in faux.get("entetes", {}) and
      faux["statut"] in (200, 400, 401, 403), {"statut": faux["statut"]})
    bon = http_obtenir(8700, "/connexion", "POST", formulaire, urlencode(
        {"identifiant": "nathan", "mot_de_passe": MDP_PROPRIETAIRE.read_text().strip()}).encode())
    cookie = bon.get("entetes", {}).get("set-cookie", "")
    c("bon identifiant : redirection (303) avec cookie de session", bon["statut"] in (302, 303) and "opsys_session=" in cookie,
      {"statut": bon["statut"]})
    drapeaux = cookie.lower()
    c("cookie de session : HttpOnly, Secure, SameSite", all(x in drapeaux for x in ("httponly", "secure", "samesite")),
      [x for x in ("httponly", "secure", "samesite") if x not in drapeaux])
    jeton = cookie.split(";", 1)[0]
    protege = http_obtenir(8700, "/departements", "GET", {"Cookie": jeton})
    c("page protégée avec le cookie : 200", protege["statut"] == 200, protege["statut"])
    sans = http_obtenir(8700, "/departements")
    c("page protégée sans cookie : redirigée", sans["statut"] in (302, 303, 307), sans["statut"])
    c("page protégée : en-têtes de sécurité présents", all(
        k in protege.get("entetes", {}) for k in ("content-security-policy", "x-frame-options", "x-content-type-options")),
      sorted(protege.get("entetes", {})))
    return sortie({"constats": constats}, 0 if all(x["ok"] for x in constats) else 1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="cmd", required=True)
    for nom, fn in (("preparer-secrets", commande_preparer_secrets), ("initialiser", commande_initialiser),
                    ("sondes", commande_sondes), ("parcours", commande_parcours), ("connexion", commande_connexion), ("rss", commande_rss),
                    ("durcissement", commande_durcissement)):
        sous.add_parser(nom).set_defaults(fn=fn)
    e = sous.add_parser("empreinte")
    e.add_argument("--base")
    e.add_argument("--compact", action="store_true")
    e.set_defaults(fn=commande_empreinte)
    cp = sous.add_parser("comparer")
    cp.add_argument("a")
    cp.add_argument("b")
    cp.set_defaults(fn=commande_comparer)
    m = sous.add_parser("mesurer")
    m.add_argument("commande", nargs=argparse.REMAINDER)
    m.set_defaults(fn=commande_mesurer)
    b = sous.add_parser("balayer")
    b.add_argument("racines", nargs="+")
    b.add_argument("--variables", nargs="*", default=[])
    b.add_argument("--fichiers-secrets", nargs="*", default=[])
    b.add_argument("--motifs", action="store_true")
    b.add_argument("--exclure", nargs="*", default=[])
    b.set_defaults(fn=commande_balayer)
    t = sous.add_parser("texte-stdin")
    t.add_argument("--variables", nargs="*", default=[])
    t.add_argument("--fichiers-secrets", nargs="*", default=[])
    t.add_argument("--pii", nargs="*", default=[])
    t.set_defaults(fn=commande_texte_stdin)
    f = sous.add_parser("fabriquer-archive")
    f.add_argument("mode", choices=["base-corrompue", "revision-future"])
    f.add_argument("sortie")
    f.set_defaults(fn=commande_fabriquer_archive)
    mv = sous.add_parser("migrer-vers")
    mv.add_argument("sens", choices=["monter", "descendre"])
    mv.add_argument("cible")
    mv.set_defaults(fn=commande_migrer_vers)
    mi = sous.add_parser("migration-interrompue")
    mi.add_argument("reference")
    mi.add_argument("--fractions", type=float, nargs="*", default=[0.05, 0.25, 0.5, 0.75, 0.95, 0.999])
    mi.set_defaults(fn=commande_migration_interrompue)
    mc = sous.add_parser("migrer-avec-crash")
    mc.add_argument("--apres", type=int, default=0)
    mc.set_defaults(fn=commande_migrer_avec_crash)
    k = sous.add_parser("corrompre")
    k.add_argument("fichier")
    k.add_argument("mode", choices=["pages", "bit", "tronquer"])
    k.set_defaults(fn=commande_corrompre)
    args = p.parse_args(argv)
    if getattr(args, "commande", None) and args.commande and args.commande[:1] == ["--"]:
        args.commande = args.commande[1:]
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
