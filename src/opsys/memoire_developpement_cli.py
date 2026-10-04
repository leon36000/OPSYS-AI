"""Adaptateur CLI autonome de la mémoire de développement M10.

`ajouter_commandes` est le seam destiné à `opsys.cli` ; `main` garde un point d'entrée isolé pour
les tests et les installations sans le routeur général. L'identité ne vient jamais des options.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from m10_memoire import consolidation_developpement as consolidation
from m10_memoire import developpement as memoire

from opsys import contexte, identite, stockage


def _authentifier_interactif() -> contexte.IdentiteAppelante:
    if not sys.stdin.isatty():
        raise memoire.AccesDeveloppementRefuse("connexion interactive requise")
    identifiant = input("Identifiant OPSYS : ").strip()
    mot_de_passe = getpass.getpass("Mot de passe OPSYS : ")
    with stockage.transaction() as cnx:
        personne = identite.authentifier(cnx, identifiant, mot_de_passe)
    if personne is None:
        raise memoire.AccesDeveloppementRefuse("identifiant ou mot de passe invalide")
    role = next((role for role in ("nathan_owner", "admin") if role in personne.roles), None)
    if role is None:
        raise memoire.AccesDeveloppementRefuse("accès mémoire développement refusé")
    return contexte.IdentiteAppelante(personne.identifiant, role)


def _afficher(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _horodatage_serveur() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _limite_audit(value: str) -> int:
    try:
        limite = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limite doit être un entier de 1 à 500") from exc
    if not 1 <= limite <= 500:
        raise argparse.ArgumentTypeError("limite doit être un entier de 1 à 500")
    return limite


def _lire_charge(path: str) -> dict[str, Any]:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file() or candidate.suffix.lower() != ".json":
        raise ValueError("fournir un fichier JSON de registre local")
    value = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("la charge de registre doit être un objet JSON")
    return value


def _commande_scanner(args: argparse.Namespace) -> int:
    _afficher(
        memoire.scanner_depot(
            args.depot,
            max_files=args.max_files,
            max_bytes=args.max_bytes,
            max_total_bytes=args.max_total_bytes,
            horodatage=_horodatage_serveur(),
        )
    )
    return 0


def _commande_preflight(args: argparse.Namespace) -> int:
    _afficher(memoire.preflight(args.module, args.tache, files=args.fichier or [], repository=args.depot))
    return 0


def _commande_verifier(args: argparse.Namespace) -> int:
    resultat = memoire.verifier_chaine()
    _afficher(resultat)
    return 0 if resultat["status"] == "valid" else 1


def _commande_auditer(args: argparse.Namespace) -> int:
    resultat = memoire.auditer_developpement(repository=args.depot, limite=args.limite)
    _afficher(resultat)
    return 1 if resultat.get("status") == "partial" else 0


def _commande_job(args: argparse.Namespace) -> int:
    if args.action == "autoriser-job":
        limites = {key: getattr(args, key) for key in consolidation.LIMITES if getattr(args, key) is not None}
        resultat = consolidation.autoriser(
            args.job_id,
            args.depot,
            args.credential_file,
            fuseau=args.fuseau,
            premier_jour=args.premier_jour,
            limites=limites,
        )
    elif args.action == "revoquer-job":
        resultat = consolidation.revoquer(args.job_id)
    else:
        resultat = consolidation.lire_statut(args.job_id)
    _afficher(resultat)
    return 0


def _commande_configurer_cron(args: argparse.Namespace) -> int:
    from .openclaw import configuration_cron_memoire_developpement

    _afficher(configuration_cron_memoire_developpement(args.job_id))
    return 0


def _commande_registre(args: argparse.Namespace) -> int:
    data = _lire_charge(args.entree)
    common = {"version": data.get("version"), "module": data.get("module")}
    schema = {
        "prompt": ({"prompt_id", "content", "version", "module", "purpose"}, {"source_refs", "status"}),
        "plan": (
            {"plan_id", "version", "module", "prompt_id", "prompt_version", "objective", "steps", "files"},
            {"risks", "gaps", "owners", "status"},
        ),
        "decision": (
            {
                "decision_id",
                "version",
                "module",
                "context",
                "options",
                "reasons",
                "consequences",
                "authority",
                "source_refs",
            },
            {"status"},
        ),
        "postflight": (
            {"operation_id", "version", "module", "plan_id", "status", "summary", "changes", "tests", "report_refs"},
            {"claim_key"},
        ),
    }
    required, optional = schema[args.type]
    if not required <= set(data) or set(data) - required - optional:
        raise ValueError("champs de charge mémoire invalides")
    if args.type == "prompt":
        resultat = memoire.enregistrer_prompt(
            data["prompt_id"],
            data["content"],
            version=common["version"],
            module=common["module"],
            objectif=data["purpose"],
            source_refs=data.get("source_refs", []),
            statut=data.get("status", "active"),
            horodatage=_horodatage_serveur(),
        )
    elif args.type == "plan":
        resultat = memoire.enregistrer_plan(
            data["plan_id"],
            version=common["version"],
            module=common["module"],
            prompt_id=data["prompt_id"],
            prompt_version=data["prompt_version"],
            objectif=data["objective"],
            etapes=data["steps"],
            fichiers=data["files"],
            risques=data.get("risks", []),
            ecarts=data.get("gaps", []),
            responsables=data.get("owners", []),
            statut=data.get("status", "active"),
            horodatage=_horodatage_serveur(),
        )
    elif args.type == "decision":
        resultat = memoire.enregistrer_decision(
            data["decision_id"],
            version=common["version"],
            module=common["module"],
            contexte_decision=data["context"],
            options=data["options"],
            raisons=data["reasons"],
            consequences=data["consequences"],
            autorite=data["authority"],
            source_refs=data["source_refs"],
            statut=data.get("status", "active"),
            horodatage=_horodatage_serveur(),
        )
    else:
        resultat = memoire.enregistrer_postflight(
            data["operation_id"],
            module=common["module"],
            plan_id=data["plan_id"],
            statut=data["status"],
            resume=data["summary"],
            changements=data["changes"],
            tests=data["tests"],
            rapport_refs=data["report_refs"],
            claim_key=data.get("claim_key"),
            version=common["version"],
            horodatage=_horodatage_serveur(),
        )
    _afficher(resultat)
    return 0


def ajouter_commandes(sous_commandes: Any) -> None:
    """Ajoute `memoire-developpement` à un groupe argparse existant (aucune identité en argument)."""
    parent = sous_commandes.add_parser("memoire-developpement", help="registre local et sourcé M10 développement")
    actions = parent.add_subparsers(dest="action", required=True)
    scanner = actions.add_parser("scanner", help="indexer en lecture seule les fichiers suivis par Git")
    scanner.add_argument("--depot", required=True, help="racine du dépôt Git autorisé à lire")
    scanner.add_argument("--max-files", type=int, default=500)
    scanner.add_argument("--max-bytes", type=int, default=256_000)
    scanner.add_argument("--max-total-bytes", type=int, default=8_000_000)
    scanner.set_defaults(fn=_commande_scanner)
    pre = actions.add_parser("preflight", help="récupérer le contexte sourcé avant un changement")
    pre.add_argument("--module", required=True)
    pre.add_argument("--tache", required=True)
    pre.add_argument("--fichier", action="append", default=[])
    pre.add_argument("--depot", help="dépôt local pour vérifier la fraîcheur des sources")
    pre.set_defaults(fn=_commande_preflight)
    register = actions.add_parser("enregistrer", help="ajouter un prompt, plan, décision ou postflight versionné")
    register.add_argument("type", choices=["prompt", "plan", "decision", "postflight"])
    register.add_argument("--entree", required=True, help="fichier JSON local avec l'objet à enregistrer")
    register.set_defaults(fn=_commande_registre)
    verify = actions.add_parser("verifier", help="vérifier la chaîne hashée du domaine développement")
    verify.set_defaults(fn=_commande_verifier)
    audit = actions.add_parser("auditer", help="examiner liens incomplets, contradictions et fraîcheur des sources")
    audit.add_argument("--depot", help="dépôt local utilisé pour vérifier la fraîcheur des sources")
    audit.add_argument(
        "--limite", type=_limite_audit, default=100, help="nombre maximal de constats retournés (1 à 500)"
    )
    audit.set_defaults(fn=_commande_auditer)
    autoriser = actions.add_parser("autoriser-job", help="autoriser le seul job développement avec capacité privée")
    autoriser.add_argument("--job-id", required=True)
    autoriser.add_argument("--depot", required=True)
    autoriser.add_argument("--credential-file", required=True, help="fichier privé neuf, jamais affiché")
    autoriser.add_argument("--fuseau", default="America/Toronto")
    autoriser.add_argument("--premier-jour", help="première date locale à rattraper, AAAA-MM-JJ")
    for key in consolidation.LIMITES:
        autoriser.add_argument("--" + key.replace("_", "-"), type=int, default=None)
    autoriser.set_defaults(fn=_commande_job)
    for commande in ("revoquer-job", "statut-job"):
        action = actions.add_parser(commande, help="révoquer ou lire l'état canonique du job")
        action.add_argument("--job-id", required=True)
        action.set_defaults(fn=_commande_job)
    cron = actions.add_parser("configurer-cron", help="préparer une commande cron native sous grant autorisé")
    cron.add_argument("--job-id", required=True)
    cron.set_defaults(fn=_commande_configurer_cron)


def construire_parseur() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsys-memoire-developpement")
    sous = parser.add_subparsers(required=True)
    ajouter_commandes(sous)
    return parser


def executer(args: argparse.Namespace) -> int:
    """Même frontière d'authentification pour le CLI autonome et le routeur principal."""
    try:
        appelant = _authentifier_interactif()
        with contexte.appele_par_appareil(appelant):
            return int(args.fn(args))
    except (
        memoire.AccesDeveloppementRefuse,
        consolidation.AccesConsolidationRefuse,
        consolidation.ConflitJob,
        memoire.ConflitIdempotence,
        memoire.SourceDeveloppementRefusee,
        ValueError,
        OSError,
        KeyError,
        json.JSONDecodeError,
        EOFError,
    ) as exc:
        # Les erreurs n'incluent jamais les valeurs d'identité, prompts complets ni secrets.
        print(str(exc), file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    return executer(construire_parseur().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
