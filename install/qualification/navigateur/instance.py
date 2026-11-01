#!/usr/bin/env python3
"""Instance FICTIVE de la console pour le banc de parcours navigateur : base SQLite jetable, personnes et entreprise
fictives, secrets générés au démarrage (jamais écrits ailleurs que dans le dossier jetable, mode 0600), aucun réseau.

CE QUE C'EST : la VRAIE application de la console (`opsys.console.application.creer_application`), les VRAIS départements
(manifestes de `departments/`) plus un département FICTIF (`departement_fictif/m09-qualif`, un outil N3 à effet local),
servie par uvicorn sur 127.0.0.1 — exactement le serveur du dépôt, sans proxy ni TLS.

Accommodements du banc (dits dans le rapport, aucun ne touche une garde de sécurité) :
- l'horloge des wallboards est lue dans un fichier (`horloge.txt`, instant RFC 3339) pour pouvoir faire « vieillir » les
  mesures sans attendre ; le délai entre deux envois SSE est ramené à 1 s (le contrat 5–3600 s de M8 reste celui de la
  définition : seul le `sleep` du serveur est raccourci) ;
- `--duree-session` permet de démarrer une seconde instance à session courte pour l'expiration de session ;
- cookie `Secure` conservé (défaut de production) : Chromium l'accepte sur http://127.0.0.1.

Usage : instance.py --dossier DOSSIER --port PORT [--duree-session SECONDES]
Écrit DOSSIER/identifiants.json (0600) au premier démarrage ; une instance à session courte réutilise la base du dossier.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[2]
FRAIS = "2026-10-30T20:00:00-04:00"  # instant de référence des faits fictifs de M8 (les mesures sont fraîches)
REGISTRES = {"chantier": "faits_chantier", "entonnoir": "faits_entonnoir", "contenus": "faits_contenus",
             "cash_libre": "faits_cash_libre"}
PERSONNES = (("proprio-fictif", "Propriétaire fictif", ["nathan_owner"]),
             ("admin-fictif", "Administratrice fictive", ["admin"]),
             ("employe-fictif", "Employé fictif", ["employee"]))


def preparer_environnement(dossier: Path) -> dict[str, str]:
    """Variables d'environnement de l'instance : tout vit sous `dossier`, rien dans le HOME de l'hôte."""
    dossier.mkdir(parents=True, exist_ok=True)
    cles = dossier / "cles"
    cles.mkdir(mode=0o700, exist_ok=True)
    env = {
        "OPSYS_HOME": str(dossier / "opsys-home"),
        "OPSYS_BASE_URL": f"sqlite:///{dossier / 'instance.db'}",
        "OPSYS_COFFRE_CLE_FICHIER": str(cles / "coffre.cle"),
        "OPSYS_QUALIF_EFFETS": str(dossier / "effets.jsonl"),
        "OPENCLAW_CONFIG_DIR": str(dossier / "opsys-home" / "core"),
        "OPSYS_CONSOLE_SECRET": "",
    }
    secret = dossier / "cles" / "console.secret"
    if not secret.exists():
        secret.write_text(secrets.token_hex(32), encoding="utf-8")
        secret.chmod(0o600)
    env["OPSYS_CONSOLE_SECRET"] = secret.read_text(encoding="utf-8").strip()
    os.environ.update(env)
    return env


def initialiser(dossier: Path) -> dict[str, str]:
    """Migre la base, crée les personnes fictives (une fois), amorce les registres de M8 et une demande N3 en attente."""
    from m8_analytics import jeux_fictifs

    from opsys import identite, stockage
    from opsys.capacites import Capacites
    from opsys.secrets_coffre import cle_maitresse

    fichier = Path(os.environ["OPSYS_COFFRE_CLE_FICHIER"])
    if not fichier.exists():
        cle_maitresse.generer_fichier(fichier)
    stockage.migrer()
    # Politique d'autorité mémoire (fictive) : sans elle une intention cron est refusée (CRON-CLASSIFICATION-MEMOIRE-INDISPONIBLE).
    politique = Path(os.environ["OPENCLAW_CONFIG_DIR"]) / "opsys"
    politique.mkdir(parents=True, exist_ok=True)
    (politique / "memoire-autorites.json").write_text(json.dumps({
        "version": 1, "departements": {"m03-estimation": "global"},
        "agents": {"opsys-agent-agent-qualif-navigateur": {"departement": "m03-estimation", "mode": "global"}},
        "procedures_globales": ["procedures"]}), encoding="utf-8")
    chemin_ids = dossier / "identifiants.json"
    if chemin_ids.exists():
        return json.loads(chemin_ids.read_text(encoding="utf-8"))
    identifiants = {ident: secrets.token_urlsafe(18) for ident, _, _ in PERSONNES}
    deps = deps_instance()
    with stockage.transaction() as cnx:
        for ident, nom, roles in PERSONNES:
            identite.creer_personne(cnx, ident, nom, identifiants[ident], roles)
        registres = jeux_fictifs.registres_fictifs()
        for cle, nom in REGISTRES.items():
            cible = stockage.maillons("m08-analytics", nom)
            for fait in registres[cle]:
                cible.append(fait)
    # Demande N3 en attente (mode « ombre » : tout outil N3 attend une décision humaine).
    for titre in ("Note fictive A du banc", "Note fictive B du banc", "Note fictive C du banc", "Note fictive D du banc (reste en attente)"):
        reponse = Capacites(deps, stockage.transaction).appeler("m9_qualif_publier_note", {"titre": titre})
        if reponse.get("statut") != "en_attente_approbation":
            raise SystemExit(f"amorçage : la demande N3 devait être en attente, reçu {reponse!r}")
    chemin_ids.write_text(json.dumps(identifiants, indent=2), encoding="utf-8")
    chemin_ids.chmod(0o600)
    (dossier / "horloge.txt").write_text(FRAIS, encoding="utf-8")
    return identifiants


def deps_instance():
    from opsys.departements import charger_departements

    deps = dict(charger_departements())
    deps.update(charger_departements(ICI / "departement_fictif"))
    return deps


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dossier", required=True, type=Path)
    p.add_argument("--port", required=True, type=int)
    p.add_argument("--duree-session", type=int, default=None)
    p.add_argument("--prefixe", default="/opsys", help="préfixe de la console (vide = comme derrière Caddy en production)")
    p.add_argument("--injection", default=None, help="défaut simulé (injections.py) : sert à vérifier que le banc le détecte")
    args = p.parse_args(argv)
    dossier = args.dossier.resolve()
    preparer_environnement(dossier)
    sys.path[:0] = [str(ICI / "departement_fictif"), str(RACINE / "src"), *map(str, sorted((RACINE / "departments").glob("*/src")))]
    initialiser(dossier)
    if args.injection:
        import injections

        injections.INJECTIONS[args.injection][0]()

    import uvicorn

    from opsys.console import application, wallboards_ui
    from opsys.console.securite import Configuration
    from opsys.stockage import transaction

    horloge = dossier / "horloge.txt"
    wallboards_ui._maintenant = lambda: horloge.read_text(encoding="utf-8").strip()  # noqa: SLF001
    wallboards_ui._dormir = lambda secondes: time.sleep(min(secondes, 1.0))  # noqa: SLF001
    configuration = Configuration(os.environ["OPSYS_CONSOLE_SECRET"], cookie_securise=True, prefixe=args.prefixe,
                                  **({"duree_session": args.duree_session} if args.duree_session else {}))
    app = application.creer_application(configuration, deps_instance(), transaction)
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    from opsys.console.journaux_http import configuration_journaux

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=configuration_journaux())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
