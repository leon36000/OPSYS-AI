"""Entrée de service M10 sans modèle ; l'identité/racine/plafonds viennent uniquement du grant."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets


def horloge_serveur() -> dt.datetime:
    """Fournisseur système du runner ; le domaine reçoit son instant explicitement."""
    return dt.datetime.now(dt.UTC)


def creer_capacite() -> str:
    """Entropie d'authentification, jamais pseudo-aléa de simulation métier."""
    return secrets.token_urlsafe(32)


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(prog="python -m opsys.memoire_consolidation")
    commandes = parseur.add_subparsers(dest="action", required=True)
    executer = commandes.add_parser("executer", help="exécuter un créneau développement autorisé")
    executer.add_argument("--job-id", required=True)
    executer.add_argument("--credential-file", required=True)
    return parseur


def main(argv: list[str] | None = None) -> int:
    from m10_memoire import consolidation_developpement as consolidation

    args = construire_parseur().parse_args(argv)
    try:
        resultat = consolidation.executer(args.job_id, args.credential_file)
    except Exception as exc:  # noqa: BLE001 — la frontière worker n'affiche aucune exception/charge sensible
        erreur = (
            "backend_not_supported"
            if isinstance(exc, consolidation.BackendConsolidationNonPrisEnCharge)
            else "execution_refused"
        )
        print(
            json.dumps(
                {
                    "job_id": args.job_id,
                    "status": "blocked",
                    "report_id": None,
                    "slot": None,
                    "backlog": None,
                    "replayed": False,
                    "error": erreur,
                }
            )
        )
        return 1
    print(json.dumps(resultat, ensure_ascii=False))
    return 2 if resultat["status"] == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
