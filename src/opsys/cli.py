"""CLI `opsys` : vérifier, générer les profils, piloter approbations, modes, budgets, paliers, services,
identité."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from . import (
    __version__,
    appareils,
    approbations,
    etat,
    evenements,
    identite,
    jetons,
    modeles,
    openclaw,
    passerelle,
    stockage,
    taxonomie,
)
from .capacites import outils_executables
from .departements import (
    charger_departements,
    dependances_manquantes,
    tous_les_outils,
    verifier_attentes,
    verifier_portees,
)
from .profils import generer_distribution
from .stockage.schema import REGISTRES

ENV_MOT_DE_PASSE_PERSONNE = "OPSYS_PERSONNE_MOT_DE_PASSE"


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
    """Contrôle de cohérence utilisé en CI : manifestes, outils, dépendances, événements, portées
    d'appareil, paliers."""
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
    problemes_attentes = verifier_attentes(deps)
    if problemes_attentes:
        print("ERREUR : attentes() de département invalide :", file=sys.stderr)
        for probleme in problemes_attentes:
            print(f"  - {probleme}", file=sys.stderr)
        return 1
    problemes_portees = verifier_portees(deps)
    if problemes_portees:
        print("ERREUR : portée d'appareil invalide (Outil.roles_appareil) :", file=sys.stderr)
        for probleme in problemes_portees:
            print(f"  - {probleme}", file=sys.stderr)
        return 1
    problemes_taxonomie = taxonomie.verifier_profil() + taxonomie.copies_locales_du_catalogue(
        [Path(__file__).resolve().parent, *(dep.racine / "src" for dep in deps.values())]
    )
    if problemes_taxonomie:
        print("ERREUR : taxonomie métier incohérente (profil d'entreprise, copie locale du catalogue) :",
              file=sys.stderr)
        for probleme in problemes_taxonomie:
            print(f"  - {probleme}", file=sys.stderr)
        return 1
    avec_portee = sum(1 for _dep, outil in index.values() if outil.roles_appareil)
    print(f"OK : {len(deps)} départements, {len(index)} outils, noms uniques, manifestes valides, "
          f"événements cohérents, portées d'appareil valides ({avec_portee} outils déclarés, "
          "les autres fermés aux appareils), taxonomie sans copie locale.")
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


def _attestation_depuis_args(args: argparse.Namespace) -> dict[str, str] | None:
    valeurs = {"nom": args.attestation_nom, "profession": args.attestation_profession,
               "reference_document": args.attestation_document}
    if all(v is None for v in valeurs.values()):
        return None  # aucune option d'attestation fournie : validée (ou pas requise) par `decider`
    return valeurs


def cmd_approbations(args: argparse.Namespace) -> int:
    deps = charger_departements()
    with etat.session() as cnx:
        if args.action == "lister":
            _afficher(approbations.lister(cnx, args.statut))
            return 0
        if args.action == "file":
            _afficher(approbations.file_proprietaire(cnx, deps))
            return 0
        index = outils_executables(deps, etat.session)
        _afficher(approbations.decider(cnx, args.id, args.action == "approuver", args.par, index, deps,
                                       args.motif, _attestation_depuis_args(args)))
    return 0


def _lire_mot_de_passe_personne() -> str:
    """Jamais en argument de ligne de commande (ADR-0009 §5) : `getpass` sans écho, ou la variable
    d'environnement OPSYS_PERSONNE_MOT_DE_PASSE (tests, scripts)."""
    valeur = os.environ.get(ENV_MOT_DE_PASSE_PERSONNE)
    return valeur if valeur is not None else getpass.getpass("Mot de passe : ")


def cmd_personnes(args: argparse.Namespace) -> int:
    if args.action != "lister" and not args.identifiant:
        print("identifiant requis", file=sys.stderr)
        return 2
    with etat.session() as cnx:
        if args.action == "lister":
            _afficher([identite.vers_json(p) for p in identite.lister(cnx)])
            return 0
        if args.action == "creer":
            if not args.nom:
                print("--nom requis", file=sys.stderr)
                return 2
            personne = identite.creer_personne(cnx, args.identifiant, args.nom, _lire_mot_de_passe_personne(),
                                               args.role)
            _afficher(identite.vers_json(personne))
            return 0
        if args.action == "roles":
            for role in args.ajouter_role:
                identite.ajouter_role(cnx, args.identifiant, role)
            for role in args.retirer_role:
                identite.retirer_role(cnx, args.identifiant, role)
            personne = identite.personne(cnx, args.identifiant)
            if personne is None:
                print(f"personne inconnue : {args.identifiant}", file=sys.stderr)
                return 1
            _afficher(identite.vers_json(personne))
            return 0
        if args.action in ("activer", "desactiver"):
            identite.activer(cnx, args.identifiant, args.action == "activer")
            _afficher({"identifiant": args.identifiant, "actif": args.action == "activer"})
            return 0
        identite.changer_mot_de_passe(cnx, args.identifiant, _lire_mot_de_passe_personne())
        _afficher({"identifiant": args.identifiant, "mot_de_passe": "modifié"})
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


def cmd_services(args: argparse.Namespace) -> int:
    """Profil d'entreprise (PLAN T0.13) : les services que CETTE instance offre.

    `lister` montre le fichier, les services déclarés et le catalogue de référence. `declarer`
    remplace la liste par des codes du catalogue, signée au journal d'audit ; un service propre
    (autre PME) se déclare en éditant `$OPSYS_HOME/entreprise.yaml` (docs/architecture/TAXONOMIE.md).
    """
    if args.action == "declarer":
        try:
            fichier = taxonomie.enregistrer_services(args.codes, par=args.par)
        except taxonomie.ProfilInvalide as exc:
            print(f"ERREUR : {exc}", file=sys.stderr)
            return 1
        print(fichier)
        return 0
    try:
        declares = taxonomie.lire_services()
    except taxonomie.ProfilInvalide as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    _afficher({
        "fichier": str(taxonomie.fichier_profil()),
        "declares": [{"code": s.code, "libelle": s.libelle} for s in declares],
        "catalogue_de_reference": [{"code": s.code, "libelle": s.libelle} for s in taxonomie.CATALOGUE_REFERENCE],
    })
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


def _specification_contexte(texte: str) -> tuple[str, list[str]]:
    """`AGENT` ou `AGENT:OUTIL,OUTIL` (option `--contexte-entreprise`) -> (agent, outils déposés)."""
    agent, _, reste = texte.partition(":")
    if not agent:
        raise argparse.ArgumentTypeError(f"agent manquant dans {texte!r} (attendu AGENT ou AGENT:OUTIL,OUTIL)")
    return agent, [outil for outil in reste.split(",") if outil]


def _contexte_entreprise(specifications: list[tuple[str, list[str]]] | None) -> dict[str, list[str]]:
    contexte: dict[str, list[str]] = {}
    for agent, outils in specifications or []:
        contexte.setdefault(agent, []).extend(outils)
    return contexte


def cmd_openclaw(args: argparse.Namespace) -> int:
    deps = charger_departements()
    dossier = Path(args.config_dir)
    fichiers = openclaw.generer(deps, dossier, modeles.charger_paliers(), url_mcp=args.url_mcp,
                                url_passerelle=args.url_passerelle, racine_espaces=args.espaces,
                                fuseau=args.fuseau,
                                contexte_entreprise=_contexte_entreprise(args.contexte_entreprise) or None)
    racine = openclaw.racine_si_absente(dossier)
    for nom, chemin in fichiers.items():
        print(f"{nom}: {chemin}")
    print(f"openclaw.json : {'créé avec les $include OPSYS' if racine else 'existant, non modifié'}")
    return 0


def cmd_appareils(args: argparse.Namespace) -> int:
    """Attribution personne/rôle d'un appareil déjà approuvé côté core (ADR-0009 §5, PLAN T1.4-c4).

    Deux temps distincts, jamais fusionnés ici : (1) l'approbation NATIVE de l'appairage, faite par
    le propriétaire côté OPSYS-CORE — le jeton d'appareil scellé n'existe qu'après cette étape,
    hors de portée d'`opsys` (R12 §1.3) ; (2) CETTE commande, qui attribue une personne et un rôle
    OPSYS au `deviceId` déjà approuvé et régénère `opsys/appareils.json`
    (`openclaw.ecrire_appareils`), le fragment que `/tools/invoke` lit directement
    (docs/architecture/IDEMPOTENCE.md §7 bis). Une entrée ici pour un `deviceId` jamais approuvé
    côté core est sans effet concret : `/tools/invoke` exige de toute façon un jeton d'appareil
    valide, émis uniquement par une approbation native — attribuer une personne à un `deviceId`
    fictif n'ouvre donc aucun accès par lui-même.
    """
    if args.action != "lister" and not args.identifiant:
        print("identifiant (deviceId) requis", file=sys.stderr)
        return 2
    dossier = Path(args.config_dir)
    with etat.session() as cnx:
        if args.action == "lister":
            _afficher([appareils.vers_json(a) for a in appareils.lister(cnx)])
            return 0
        if args.action == "appairer":
            if not args.personne or not args.role:
                print("--personne et --role requis", file=sys.stderr)
                return 2
            appareil = appareils.appairer(cnx, args.identifiant, args.personne, args.role)
            chemin = openclaw.ecrire_appareils(cnx, dossier)
            print(f"opsys/appareils.json régénéré : {chemin}")
            _afficher(appareils.vers_json(appareil))
            return 0
        appareils.revoquer(cnx, args.identifiant)
        chemin = openclaw.ecrire_appareils(cnx, dossier)
        print(f"opsys/appareils.json régénéré : {chemin}")
        _afficher({"identifiant": args.identifiant, "appareil": "revoque"})
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
    a.add_argument("action", choices=["lister", "approuver", "refuser", "file"])
    a.add_argument("id", nargs="?")
    a.add_argument("--statut")
    a.add_argument("--par", default="", help="identifiant de la personne qui décide (ADR-0009 §5)")
    a.add_argument("--motif", default="")
    a.add_argument("--attestation-nom", help="N5 seulement : nom du professionnel (ADR-0009 §5)")
    a.add_argument("--attestation-profession", help="N5 seulement : profession du professionnel")
    a.add_argument("--attestation-document", help="N5 seulement : référence du document joint")
    a.set_defaults(fn=cmd_approbations)

    pe = sous.add_parser("personnes", help="identité : personnes et rôles (ADR-0009 §5)")
    pe.add_argument("action", choices=["creer", "lister", "roles", "activer", "desactiver", "mot-de-passe"])
    pe.add_argument("identifiant", nargs="?")
    pe.add_argument("--nom", help="creer : nom de la personne")
    pe.add_argument("--role", action="append", default=[], choices=sorted(identite.ROLES),
                    help="creer : rôle initial (répétable)")
    pe.add_argument("--ajouter-role", action="append", default=[], choices=sorted(identite.ROLES))
    pe.add_argument("--retirer-role", action="append", default=[], choices=sorted(identite.ROLES))
    pe.set_defaults(fn=cmd_personnes)

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

    sv = sous.add_parser("services", help="profil d'entreprise : les services offerts (taxonomie métier)")
    sv.add_argument("action", choices=["lister", "declarer"])
    sv.add_argument("codes", nargs="*", help="codes du catalogue de référence à déclarer")
    sv.add_argument("--par", help="qui déclare (journal d'audit)")
    sv.set_defaults(fn=cmd_services)
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
    oc.add_argument(
        "--contexte-entreprise", action="append", metavar="AGENT[:OUTIL,OUTIL]", type=_specification_contexte,
        help="active le moteur de contexte du core pour cet agent : paquet de M10 avant le tour, et dépôt "
             "des résultats des outils listés après (répétable ; absent : désactivé, comportement inchangé)")
    oc.set_defaults(fn=cmd_openclaw)

    ap = sous.add_parser(
        "appareils",
        help="attribution personne/rôle des appareils appairés côté core (ADR-0009 §5, T1.4-c4)",
    )
    ap.add_argument("action", choices=["appairer", "lister", "revoquer"])
    ap.add_argument("identifiant", nargs="?", help="deviceId (hex sha256 de la clé publique, R12 §1.3)")
    ap.add_argument("--personne", help="appairer : identifiant de la personne OPSYS")
    ap.add_argument("--role", choices=sorted(appareils.ROLES_APPAREIL),
                    help="appairer : rôle du jeton d'appareil (la personne doit déjà le porter)")
    ap.add_argument("--config-dir", required=True,
                    help="dossier de openclaw.json (volume partagé) : où régénérer opsys/appareils.json")
    ap.set_defaults(fn=cmd_appareils)

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
    if args.commande == "approbations" and args.action not in ("lister", "file") and not args.id:
        print("id de demande requis", file=sys.stderr)
        return 2
    if args.commande == "services" and args.action == "declarer" and not (args.codes and args.par):
        print("au moins un code de service et --par requis", file=sys.stderr)
        return 2
    if args.commande == "paliers" and args.action == "definir" and not (args.palier and args.provider and args.model):
        print("palier, --provider et --model requis", file=sys.stderr)
        return 2
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
