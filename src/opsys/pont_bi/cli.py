"""Sous-commandes `opsys-metier pont-bi …` (aussi `opsys metier pont-bi …` depuis le core).

- `pont-bi jeux [--json]` : les jeux exportables et leurs colonnes (lecture seule) ;
- `pont-bi jetons [--json]` : les jetons (métadonnées : jamais le secret) et leur état ;
- `pont-bi journal [--limite N] [--json]` : le journal d'accès (jamais le contenu exporté) ;
- `pont-bi jeton-emettre --par PERSONNE --libelle … --jeux a,b [--financier] [--duree-jours N] [--quota-requetes N]
  [--quota-lignes N]` : émet un jeton de LECTURE dédié, rendu UNE seule fois sur la sortie standard. Geste HUMAIN (N3) :
  la personne est authentifiée (admin ou propriétaire) ; aucun outil d'agent ne l'expose ;
- `pont-bi jeton-revoquer --par PERSONNE JETON_ID` : révoque un jeton (immédiat) ; humain aussi.

Aucune commande n'écrit dans l'entrepôt ni dans un registre de département.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import service
from .jeux import JEUX

ROLES_ADMIN = frozenset({"nathan_owner", "admin"})


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("pont-bi", help="pont vers les outils BI externes : exports en lecture seule, jetons, journal")
    actions = p.add_subparsers(dest="action", required=True)
    for nom in ("jeux", "jetons"):
        actions.add_parser(nom).add_argument("--json", action="store_true")
    journal = actions.add_parser("journal", help="journal d'accès (jamais le contenu exporté)")
    journal.add_argument("--limite", type=int, default=50)
    journal.add_argument("--json", action="store_true")
    emettre = actions.add_parser("jeton-emettre", help="émettre un jeton de lecture dédié (geste humain)")
    emettre.add_argument("--par", required=True, help="personne active admin ou propriétaire, authentifiée")
    emettre.add_argument("--libelle", required=True)
    emettre.add_argument("--jeux", required=True, help=f"liste séparée par des virgules parmi {','.join(sorted(JEUX))}")
    emettre.add_argument(
        "--financier", action="store_true", help="accorder la portée financière (marges, prix, cash libre)"
    )
    emettre.add_argument("--duree-jours", type=int, default=30)
    emettre.add_argument("--quota-requetes", type=int, default=60, help="requêtes par heure")
    emettre.add_argument("--quota-lignes", type=int, default=100_000, help="lignes par jour")
    revoquer = actions.add_parser("jeton-revoquer", help="révoquer un jeton (geste humain)")
    revoquer.add_argument("--par", required=True)
    revoquer.add_argument("jeton_id")
    p.set_defaults(fn=executer)


def _afficher(donnees: Any) -> None:
    print(json.dumps(donnees, ensure_ascii=False, indent=2, default=str))


def executer(args: argparse.Namespace) -> int:
    from .. import cli as cli_principal
    from .. import etat

    try:
        if args.action == "jeux":
            _afficher(
                [
                    {
                        "jeu": j.nom,
                        "entite_odata": j.entite,
                        "description": j.description,
                        "colonnes": [{"nom": c.nom, "type": c.edm, "financiere": c.financiere} for c in j.colonnes],
                    }
                    for j in JEUX.values()
                ]
            )
            return 0
        if args.action == "jetons":
            with etat.session() as cnx:
                _afficher(service.lister(cnx))
            return 0
        if args.action == "journal":
            with etat.session() as cnx:
                _afficher(service.acces_recents(cnx, args.limite))
            return 0
        with etat.session() as cnx:
            if cli_principal._authentifier_action_humaine(cnx, args.par, ROLES_ADMIN) is None:
                return 1
        if args.action == "jeton-emettre":
            with etat.session() as cnx:
                resultat = service.emettre(
                    cnx,
                    acteur=args.par,
                    libelle=args.libelle,
                    jeux=[j.strip() for j in args.jeux.split(",") if j.strip()],
                    financier=args.financier,
                    quota_requetes_heure=args.quota_requetes,
                    quota_lignes_jour=args.quota_lignes,
                    duree_s=args.duree_jours * 86400,
                )
            print(
                "Le jeton ci-dessous n'est rendu qu'UNE fois : conservez-le dans le gestionnaire de secrets de votre "
                "outil BI.",
                file=sys.stderr,
            )
            _afficher(resultat)
        elif args.action == "jeton-revoquer":
            with etat.session() as cnx:
                _afficher(service.revoquer(cnx, acteur=args.par, jeton_id=args.jeton_id))
    except service.RefusPontBI as refus:
        print(f"{refus.code} : {refus.message}", file=sys.stderr)
        return 2
    return 0
