"""CLI du moteur métier, `opsys-metier` : vérifier, générer les profils, piloter approbations, modes, budgets, paliers,
services, équipes, météo, identité.

Depuis T0.7 lot 2, `opsys` est la commande du core : celle-ci se lance par `opsys metier <commande>` (le core lit
`opsys/metier.json`, clé `commande_cli`, que `instance initialiser` écrit) ou directement par `opsys-metier` (Docker,
développement). Ce module reste le même : `python -m opsys.cli` aussi."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from . import (
    __version__,
    appareils,
    approbations,
    canaux,
    equipes,
    etat,
    evenements,
    exportation,
    identite,
    instance,
    jetons,
    meteo,
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
    problemes_canaux = canaux.verifier_declarations(deps)
    if problemes_canaux:
        print("ERREUR : canaux du public invalides (department.yaml, clé canaux) :", file=sys.stderr)
        for probleme in problemes_canaux:
            print(f"  - {probleme}", file=sys.stderr)
        return 1
    # Un fichier illisible échoue à chaque lecture du profil : le même message ne s'affiche qu'une fois.
    problemes_taxonomie = list(dict.fromkeys(
        taxonomie.verifier_profil()
        + equipes.verifier_profil()
        + meteo.verifier_profil()
        + taxonomie.copies_locales_du_catalogue(
            [Path(__file__).resolve().parent, *(dep.racine / "src" for dep in deps.values())]
        )
    ))
    if problemes_taxonomie:
        print(
            "ERREUR : taxonomie métier incohérente (profil d'entreprise, équipes, météo, copie locale du catalogue) :",
            file=sys.stderr,
        )
        for probleme in problemes_taxonomie:
            print(f"  - {probleme}", file=sys.stderr)
        return 1
    etat_canaux = canaux.configuration(deps, os.environ).etat
    for ligne in canaux.lignes_d_etat(etat_canaux):
        print(ligne)
    if args.config_dir:
        problemes_config = _verifier_config_canaux(deps, Path(args.config_dir), bool(etat_canaux))
        if problemes_config:
            print("ERREUR : la configuration OpenClaw ne suit pas les canaux du public :", file=sys.stderr)
            for probleme in problemes_config:
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


def _verifier_config_canaux(deps: dict, dossier: Path, avec_canaux: bool) -> list[str]:
    """`opsys-metier verifier --config-dir` : les fragments écrits par `opsys-metier openclaw configurer` suivent
    l'environnement (canal actif ou non) et `openclaw.json` les inclut. Sans canal déclaré, il n'y a rien à suivre."""
    if not avec_canaux:
        return []
    fichier = dossier / "opsys" / "channels.json"
    ecrit = None
    if fichier.is_file():
        try:
            ecrit = {"channels": json.loads(fichier.read_text(encoding="utf-8"))}
        except (OSError, ValueError) as exc:
            return [f"{fichier} illisible : {exc}"]
    manquants = openclaw.includes_de_canaux_manquants(dossier)
    problemes = canaux.verifier_configuration(deps, os.environ, ecrit, manquants)
    if manquants:
        problemes.append(
            f"openclaw.json n'inclut pas {', '.join(manquants)} : ajoute "
            + ", ".join(f'"{cle}": {json.dumps(openclaw.FICHIER_RACINE_MODELE[cle])}' for cle in manquants)
        )
    return problemes


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


def _source_du_logiciel(source: str | None) -> Path:
    """Le dépôt du logiciel : `--source`, sinon celui du paquet installé en mode éditable (racine du dépôt)."""
    if source:
        return Path(source).resolve()
    return Path(__file__).resolve().parents[2]


def cmd_instance(args: argparse.Namespace) -> int:
    """Instance locale (PLAN T0.11) : préparation par l'installateur, export et restauration. Voir `opsys.instance`
    et `opsys.exportation`. Le code de sortie 3 de `initialiser` veut dire : installé, mais il manque une décision.
    `dossier` écrit le dossier d'état du core (profil `opsys`, PLAN T0.11-b) : un chemin, sans rien d'autre."""
    home = stockage.dossier_opsys()
    par = args.par or f"poste:{getpass.getuser()}"
    try:
        if args.action == "dossier":
            print(instance.dossier_core())
            return 0
        if args.action == "initialiser":
            resultat = instance.initialiser(
                home, source=_source_du_logiciel(args.source), python=Path(sys.executable),
                port_gateway=args.port_gateway, port_moteur=args.port_moteur)
            _afficher(resultat.en_json())
            for ligne in resultat.manque:
                print(f"À FAIRE : {ligne}", file=sys.stderr)
            for ligne in resultat.avertissements:
                print(f"AVERTISSEMENT : {ligne}", file=sys.stderr)
            return 0 if resultat.etat == "pret" else instance.CODE_EN_ATTENTE
        if args.action == "exporter":
            sortie = Path(args.sortie) if args.sortie else Path(f"opsys-export-{exportation.horodatage()}.tar.gz")
            _afficher(exportation.exporter(home, sortie, par=par).en_json())
            return 0
        _afficher(exportation.restaurer(
            Path(args.archive), home, par=par, remplacer=args.remplacer, empreinte=args.empreinte).en_json())
        return 0
    except (instance.ErreurInstance, exportation.ErreurExportation, ValueError) as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1


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
    refus = canaux.mode_refuse(deps[args.departement], args.mode)
    if refus:
        print(refus, file=sys.stderr)
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


def _lire_declaration_equipes(chemin: str) -> object:
    """Contenu YAML (ou JSON, qui en est un sous-ensemble) du fichier à déclarer ; lève `OSError` ou `ValueError`."""
    import yaml

    try:
        return yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{chemin} illisible : {exc}") from exc


def cmd_equipes(args: argparse.Namespace) -> int:
    """Profil d'entreprise (PLAN T4.12) : les équipes, le dépôt, les quarts et les durées que M4 utilise pour céduler.

    `lister` montre le fichier, le profil déclaré et ce qui reste à déclarer. `declarer --depuis FICHIER --par NOM`
    REMPLACE la clé `equipes` par le contenu validé du fichier, signée au journal d'audit ; les membres doivent être des
    personnes OPSYS existantes et actives (`opsys-metier personnes lister`). Aucune donnée de ressources humaines.
    """
    if args.action == "declarer":
        try:
            propre = equipes.normaliser_equipes(_lire_declaration_equipes(args.depuis))
            with etat.session() as cnx:
                problemes = equipes.verifier_personnes(propre, cnx)
            if problemes:
                for probleme in problemes:
                    print(f"ERREUR : {probleme}", file=sys.stderr)
                return 1
            fichier = equipes.enregistrer_equipes(propre, par=args.par)
        except (OSError, ValueError) as exc:  # `ProfilInvalide` est une `ValueError`
            print(f"ERREUR : {exc}", file=sys.stderr)
            return 1
        except SQLAlchemyError as exc:
            print(f"ERREUR : base de l'instance inaccessible ({type(exc).__name__}) : `opsys-metier base migrer` ?",
                  file=sys.stderr)
            return 1
        print(fichier)
        return 0
    try:
        profil = equipes.lire_equipes()
        declares = [service.code for service in taxonomie.lire_services()]
    except taxonomie.ProfilInvalide as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    _afficher({
        "fichier": str(taxonomie.fichier_profil()),
        "declare": profil is not None,
        "profil": profil,
        "a_declarer": equipes.a_declarer(profil, declares),
    })
    return 0


def cmd_meteo(args: argparse.Namespace) -> int:
    """Profil d'entreprise (PLAN T4.13) : les seuils météo par service que M4 utilise pour juger un créneau, et le
    fournisseur de prévisions que l'entreprise ouvre (aucun par défaut : la prévision se saisit à la main).

    `lister` montre le fichier, le profil déclaré et ce qui reste à décider. `declarer --depuis FICHIER --par NOM`
    REMPLACE la clé `meteo` par le contenu validé du fichier, signée au journal d'audit. L'API gratuite d'Open-Meteo est
    non commerciale : le forfait `commercial` est le seul accepté, et la clé d'API reste dans l'environnement.
    """
    if args.action == "declarer":
        try:
            fichier = meteo.enregistrer_meteo(_lire_declaration_equipes(args.depuis), par=args.par)
        except (OSError, ValueError) as exc:  # `ProfilInvalide` est une `ValueError`
            print(f"ERREUR : {exc}", file=sys.stderr)
            return 1
        except SQLAlchemyError as exc:
            print(f"ERREUR : base de l'instance inaccessible ({type(exc).__name__}) : `opsys base migrer` ?",
                  file=sys.stderr)
            return 1
        print(fichier)
        return 0
    try:
        profil = meteo.lire_meteo()
        declares = [service.code for service in taxonomie.lire_services()]
    except taxonomie.ProfilInvalide as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    _afficher({
        "fichier": str(taxonomie.fichier_profil()),
        "declare": profil is not None,
        "profil": profil,
        "a_declarer": meteo.a_declarer(profil, declares),
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
                                contexte_entreprise=_contexte_entreprise(args.contexte_entreprise) or None,
                                affaire_par_session=args.affaire_par_session or ())
    racine = openclaw.racine_si_absente(dossier)
    for nom, chemin in fichiers.items():
        print(f"{nom}: {chemin}")
    print(f"openclaw.json : {'créé avec les $include OPSYS' if racine else 'existant, non modifié'}")
    manquants = openclaw.includes_de_canaux_manquants(dossier)
    etat_canaux = canaux.configuration(deps, os.environ, manquants).etat
    for ligne in canaux.lignes_d_etat(etat_canaux):
        print(ligne)
    if etat_canaux and manquants:
        print(f"ATTENTION : openclaw.json n'inclut pas {', '.join(manquants)} : le core ignore ces fragments, "
              "les canaux restent inactifs (voir `opsys-metier verifier --config-dir`)", file=sys.stderr)
    return 0


def cmd_appareils(args: argparse.Namespace) -> int:
    """Attribution personne/rôle d'un appareil déjà approuvé côté core (ADR-0009 §5, PLAN T1.4-c4).

    Deux temps distincts, jamais fusionnés ici : (1) l'approbation NATIVE de l'appairage, faite par
    le propriétaire côté OPSYS-CORE — le jeton d'appareil scellé n'existe qu'après cette étape,
    hors de portée du moteur (R12 §1.3) ; (2) CETTE commande, qui attribue une personne et un rôle
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
    p = argparse.ArgumentParser(prog="opsys-metier", description="OPSYS-AI — pilotage des départements (moteur métier)")
    p.add_argument("--version", action="version", version=f"opsys-metier {__version__}")
    sous = p.add_subparsers(dest="commande", required=True)

    sous.add_parser("departements", help="lister les départements").set_defaults(fn=cmd_departements)

    v = sous.add_parser("verifier", help="valider manifestes et outils (CI)")
    v.add_argument("--paliers", action="store_true", help="exiger aussi la configuration des paliers")
    v.add_argument("--config-dir", help="dossier de openclaw.json : vérifier aussi que les canaux du public y sont "
                                        "configurés comme l'environnement le dit")
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
    eq = sous.add_parser(
        "equipes", help="profil d'entreprise : équipes, dépôt, quarts et durées que M4 utilise pour céduler")
    eq.add_argument("action", choices=["lister", "declarer"])
    eq.add_argument("--depuis", help="declarer : fichier YAML ou JSON du profil (clés liste, services, cedule, ...)")
    eq.add_argument("--par", help="declarer : qui déclare (journal d'audit)")
    eq.set_defaults(fn=cmd_equipes)
    me = sous.add_parser(
        "meteo", help="profil d'entreprise : seuils météo par service et fournisseur de prévisions (M4, créneaux)")
    me.add_argument("action", choices=["lister", "declarer"])
    me.add_argument(
        "--depuis", help="declarer : fichier YAML ou JSON du profil (clés fuseau, fournisseur, services, ...)"
    )
    me.add_argument("--par", help="declarer : qui déclare (journal d'audit)")
    me.set_defaults(fn=cmd_meteo)
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
    oc.add_argument(
        "--affaire-par-session", action="append", metavar="AGENT",
        help="cet agent (déjà nommé par --contexte-entreprise) lit son affaire dans la clé de session, liée par un "
             "humain, et jamais dans la demande : pour un agent d'un canal client (répétable)")
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

    ins = sous.add_parser(
        "instance", help="instance locale : initialisation (installateur), export et restauration (PLAN T0.11)")
    ins.add_argument("action", choices=["initialiser", "exporter", "restaurer", "dossier"],
                     help="dossier : écrit le dossier d'état du core (profil opsys), pour --config-dir")
    ins.add_argument("archive", nargs="?", help="restaurer : archive produite par `exporter`")
    ins.add_argument("--sortie", help="exporter : archive à écrire (défaut : ./opsys-export-<horodatage>.tar.gz)")
    ins.add_argument("--par", help="exporter, restaurer : qui agit, pour le journal d'audit (défaut : poste:<compte>)")
    ins.add_argument("--remplacer", action="store_true",
                     help="restaurer : mettre de côté les fichiers actuels (jamais supprimés) et les remplacer")
    ins.add_argument("--empreinte", help="restaurer : SHA-256 attendu de l'archive (défaut : <archive>.sha256)")
    ins.add_argument("--source", help="initialiser : dépôt du logiciel (défaut : celui du paquet installé)")
    ins.add_argument("--port-gateway", type=int, help="initialiser : port du Gateway (défaut : 18789)")
    ins.add_argument("--port-moteur", type=int, help="initialiser : port du moteur métier (défaut : 8765)")
    ins.set_defaults(fn=cmd_instance)

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
    if args.commande == "equipes" and args.action == "declarer" and not (args.depuis and args.par):
        print("--depuis (fichier du profil) et --par requis", file=sys.stderr)
        return 2
    if args.commande == "meteo" and args.action == "declarer" and not (args.depuis and args.par):
        print("--depuis (fichier du profil) et --par requis", file=sys.stderr)
        return 2
    if args.commande == "instance" and args.action == "restaurer" and not args.archive:
        print("archive requise : opsys-metier instance restaurer <archive.tar.gz>", file=sys.stderr)
        return 2
    if args.commande == "paliers" and args.action == "definir" and not (args.palier and args.provider and args.model):
        print("palier, --provider et --model requis", file=sys.stderr)
        return 2
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
