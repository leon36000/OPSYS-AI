"""CLI `opsys` : vérifier, générer les profils, piloter approbations, modes, budgets, paliers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from . import __version__, approbations, etat, evenements, jetons, modeles, openclaw, passerelle, stockage
from .capacites import outils_executables
from .departements import charger_departements, dependances_manquantes, tous_les_outils
from .profils import generer_distribution
from .stockage.schema import REGISTRES


def _afficher(donnees: object) -> None:
    print(json.dumps(donnees, ensure_ascii=False, indent=2))


def cmd_departements(args: argparse.Namespace) -> int:
    deps = charger_departements()
    with etat.session() as cnx:
        for dep in deps.values():
            outils = dep.charger_outils()
            mode = approbations.mode_effectif(cnx, dep.id, dep.mode)
            print(f"{dep.code:<4} {dep.id:<28} mode={mode:<9} outils={len(outils):<3} "
                  f"skills={len(dep.skills):<2} {dep.nom}")
    return 0


def cmd_verifier(args: argparse.Namespace) -> int:
    """Contrôle de cohérence utilisé en CI : manifestes, outils, dépendances, événements, paliers."""
    deps = charger_departements()
    index = tous_les_outils(deps.values())
    manquantes = dependances_manquantes(deps)
    if manquantes:
        print(f"ERREUR : dépendances non installées : {manquantes}", file=sys.stderr)
        return 1
    problemes_evenements = evenements.verifier_coherence(deps)
    if problemes_evenements:
        print("ERREUR : bus d'événements incohérent :", file=sys.stderr)
        for probleme in problemes_evenements:
            print(f"  - {probleme}", file=sys.stderr)
        return 1
    print(f"OK : {len(deps)} départements, {len(index)} outils, noms uniques, manifestes valides, "
          "événements cohérents.")
    if args.paliers:
        paliers = modeles.charger_paliers()
        manquants = sorted({d.modeles[u] for d in deps.values() for u in d.modeles} - set(paliers))
        if manquants:
            print(f"ERREUR : paliers non configurés : {', '.join(manquants)}", file=sys.stderr)
            return 1
        print(f"OK : paliers configurés ({', '.join(sorted(paliers))}).")
    return 0


def cmd_profils(args: argparse.Namespace) -> int:
    deps = charger_departements()
    paliers = modeles.charger_paliers(Path(args.paliers)) if args.paliers else modeles.charger_paliers()
    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=True)
    for dep in deps.values():
        if args.departement and dep.id not in args.departement:
            continue
        dossier = generer_distribution(dep, destination, paliers, commande_mcp=args.commande_mcp)
        print(dossier)
    return 0


def cmd_approbations(args: argparse.Namespace) -> int:
    with etat.session() as cnx:
        if args.action == "lister":
            _afficher(approbations.lister(cnx, args.statut))
            return 0
        index = outils_executables(charger_departements(), etat.session)
        _afficher(approbations.decider(cnx, args.id, args.action == "approuver", args.par, index, args.motif))
    return 0


def _url_masquee(url: str) -> str:
    """URL de base affichable : le mot de passe n'apparaît jamais dans une sortie."""
    return make_url(url).render_as_string(hide_password=True)


def cmd_base(args: argparse.Namespace) -> int:
    url = stockage.url_base()
    if args.action == "migrer":
        _afficher({"base": _url_masquee(url), "revision": stockage.migrer(url)})
        return 0
    registres = []
    with stockage.transaction(url) as cnx:
        requete = (select(REGISTRES.c.departement, REGISTRES.c.registre, func.count().label("maillons"))
                   .group_by(REGISTRES.c.departement, REGISTRES.c.registre)
                   .order_by(REGISTRES.c.departement, REGISTRES.c.registre))
        registres = [dict(ligne._mapping) for ligne in cnx.execute(requete)]
    _afficher({"base": _url_masquee(url), "moteur": stockage.moteur(url).dialect.name,
               "revision": stockage.revision_courante(url), "registres": registres})
    return 0


def cmd_evenements(args: argparse.Namespace) -> int:
    """Bus d'événements (ADR-0009 §3) : comptes/quarantaine, ou livraison manuelle immédiate."""
    if args.action == "etat":
        _afficher(evenements.etat())
        return 0
    _afficher(evenements.repartir(charger_departements(), limite=args.limite))
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    deps = charger_departements()
    if args.departement not in deps:
        print(f"département inconnu : {args.departement}", file=sys.stderr)
        return 1
    with etat.session() as cnx:
        approbations.fixer_mode(cnx, args.departement, args.mode, args.par)
    print(f"{args.departement} → {args.mode}")
    return 0


def cmd_budgets(args: argparse.Namespace) -> int:
    deps = charger_departements()
    with etat.session() as cnx:
        _afficher([jetons.etat_budget(cnx, d.id, d.budget) for d in deps.values()])
    return 0


def cmd_paliers(args: argparse.Namespace) -> int:
    paliers = modeles.charger_paliers()
    if args.action == "lister":
        _afficher(paliers)
        return 0
    conf = {"provider": args.provider, "model": args.model}
    if args.base_url:
        conf["base_url"] = args.base_url
    paliers[args.palier] = conf
    print(modeles.enregistrer_paliers(paliers))
    return 0


def cmd_openclaw(args: argparse.Namespace) -> int:
    deps = charger_departements()
    dossier = Path(args.config_dir)
    fichiers = openclaw.generer(deps, dossier, modeles.charger_paliers(), url_mcp=args.url_mcp,
                                url_passerelle=args.url_passerelle, racine_espaces=args.espaces,
                                fuseau=args.fuseau)
    racine = openclaw.racine_si_absente(dossier)
    for nom, chemin in fichiers.items():
        print(f"{nom}: {chemin}")
    print(f"openclaw.json : {'créé avec les $include OPSYS' if racine else 'existant, non modifié'}")
    return 0


def cmd_passerelle(args: argparse.Namespace) -> int:
    import os

    import yaml

    paliers = modeles.charger_paliers()
    if args.action == "config":
        contenu = yaml.safe_dump(passerelle.config_litellm(paliers), allow_unicode=True, sort_keys=False)
        Path(args.sortie).write_text(contenu, encoding="utf-8")
        print(args.sortie)
        return 0
    client = passerelle.ClientLiteLLM(args.url, os.environ.get("LITELLM_MASTER_KEY", ""))
    if args.action == "synchroniser":
        import datetime as dt

        fin = dt.date.today()
        with etat.session() as cnx:
            lignes = passerelle.synchroniser_usage(client, cnx, charger_departements().values(),
                                                   fin - dt.timedelta(days=args.jours), fin)
        print(f"{lignes} lignes de consommation synchronisées depuis LiteLLM")
        return 0
    aliases = [passerelle.alias_palier(p) for p in paliers]
    manquantes = []
    for dep in charger_departements().values():
        cle = os.environ.get(f"OPSYS_CLE_{dep.code}", "")
        if not cle:
            manquantes.append(dep.code)
            continue
        print(f"{dep.id}: {client.enregistrer_departement(dep, cle, aliases, args.budget_usd_mois)}")
    if manquantes:
        print(f"ERREUR : clés absentes de l'environnement pour {', '.join(manquantes)}", file=sys.stderr)
        return 1
    return 0


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opsys", description="OPSYS-AI — pilotage des départements")
    p.add_argument("--version", action="version", version=f"opsys {__version__}")
    sous = p.add_subparsers(dest="commande", required=True)

    sous.add_parser("departements", help="lister les départements").set_defaults(fn=cmd_departements)

    v = sous.add_parser("verifier", help="valider manifestes et outils (CI)")
    v.add_argument("--paliers", action="store_true", help="exiger aussi la configuration des paliers")
    v.set_defaults(fn=cmd_verifier)

    g = sous.add_parser("profils", help="générer les distributions de profils Hermes")
    g.add_argument("destination")
    g.add_argument("--departement", action="append", default=[])
    g.add_argument("--paliers", help="fichier paliers.yaml (défaut : $OPSYS_HOME/paliers.yaml)")
    g.add_argument("--commande-mcp", default="opsys-mcp")
    g.set_defaults(fn=cmd_profils)

    a = sous.add_parser("approbations", help="file d'approbation humaine")
    a.add_argument("action", choices=["lister", "approuver", "refuser"])
    a.add_argument("id", nargs="?")
    a.add_argument("--statut")
    a.add_argument("--par", default="")
    a.add_argument("--motif", default="")
    a.set_defaults(fn=cmd_approbations)

    b = sous.add_parser("base", help="base de l'instance : migrations et état (ADR-0009)")
    b.add_argument("action", choices=["migrer", "etat"])
    b.set_defaults(fn=cmd_base)

    ev = sous.add_parser("evenements", help="bus d'événements du socle (ADR-0009 §3)")
    ev.add_argument("action", choices=["etat", "repartir"])
    ev.add_argument("--limite", type=int, default=100, help="repartir : paires (événement, consommateur) max")
    ev.set_defaults(fn=cmd_evenements)

    m = sous.add_parser("mode", help="fixer le mode d'autonomie d'un département")
    m.add_argument("departement")
    m.add_argument("mode", choices=["ombre", "supervise", "autonome"])
    m.add_argument("--par", required=True)
    m.set_defaults(fn=cmd_mode)

    sous.add_parser("budgets", help="consommation de tokens par département").set_defaults(fn=cmd_budgets)

    pa = sous.add_parser("paliers", help="associer les paliers de modèles à des fournisseurs")
    pa.add_argument("action", choices=["lister", "definir"])
    pa.add_argument("palier", nargs="?", choices=["local", "rapide", "standard", "fort"])
    pa.add_argument("--provider")
    pa.add_argument("--model")
    pa.add_argument("--base-url")
    pa.set_defaults(fn=cmd_paliers)
    oc = sous.add_parser("openclaw", help="configuration d'OPSYS-CORE (OpenClaw)")
    oc.add_argument("action", choices=["configurer"])
    oc.add_argument("--config-dir", required=True, help="dossier de openclaw.json (volume partagé)")
    oc.add_argument("--url-mcp", default="http://opsys:8765/mcp")
    oc.add_argument("--url-passerelle", default="http://litellm:4000/v1")
    oc.add_argument("--espaces", default="./opsys/espaces", help="chemin des espaces vu par OpenClaw")
    oc.add_argument("--fuseau", default="America/Toronto")
    oc.set_defaults(fn=cmd_openclaw)

    pg = sous.add_parser("passerelle", help="passerelle LiteLLM : configuration et clés par département")
    pg.add_argument("action", choices=["config", "cles", "synchroniser"])
    pg.add_argument("--sortie", default="litellm.yaml")
    pg.add_argument("--url", default="http://litellm:4000")
    pg.add_argument("--budget-usd-mois", type=float, default=None)
    pg.add_argument("--jours", type=int, default=1, help="synchroniser : jours passés à relire (en plus d'aujourd'hui)")
    pg.set_defaults(fn=cmd_passerelle)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construire_parseur().parse_args(argv)
    if args.commande == "approbations" and args.action != "lister" and not args.id:
        print("id de demande requis", file=sys.stderr)
        return 2
    if args.commande == "paliers" and args.action == "definir" and not (args.palier and args.provider and args.model):
        print("palier, --provider et --model requis", file=sys.stderr)
        return 2
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
