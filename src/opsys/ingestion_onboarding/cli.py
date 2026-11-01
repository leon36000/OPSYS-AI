"""Sous-commandes `opsys-metier onboarding …` (aussi `opsys metier onboarding …` depuis le core).

`onboarding` et non `onboard` : `onboard` est une commande du core (`core-command-descriptors.ts`). Déposer et avancer
exigent l'authentification personnelle interactive d'une personne `nathan_owner`, `admin` ou `finance` (même règle que
les autres mutations opérateur de la CLI) ; elles ne créent que des brouillons. La lecture des métadonnées est libre ;
le CONTENU d'un brouillon (montants, noms) exige la même authentification. La validation définitive n'est PAS ici :
elle passe par les outils `m5_valider_brouillon_onboarding_ap` et `m2_valider_brouillon_onboarding_client` (file
d'approbation). La CLI est le chemin conseillé pour un gros lot : chaque tâche y est validée dans sa propre
transaction (dans un appel d'outil, tout l'avancement tient dans la transaction de l'outil).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .codes import IngestionErreur

ROLES = {"nathan_owner", "admin", "finance"}


def _afficher(donnees: Any) -> None:
    print(json.dumps(donnees, ensure_ascii=False, indent=2, default=str))


def _erreur(exc: IngestionErreur) -> int:
    print(json.dumps({"ok": False, **exc.publique()}, ensure_ascii=False), file=sys.stderr)
    return 1


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    o = sous.add_parser("onboarding", help="ingestion d'onboarding : dépôt, tâches, brouillons (jamais définitif)")
    actions = o.add_subparsers(dest="action", required=True)
    dep = actions.add_parser("deposer", help="créer le lot d'un fichier de <OPSYS_HOME>/imports/onboarding/")
    dep.add_argument("fichier", help="nom du fichier déposé (sans chemin)")
    dep.add_argument("--mutation-id", required=True, help="clé d'idempotence ; la même clé rejoue le lot")
    av = actions.add_parser("avancer", help="exécuter les tâches d'un lot (une transaction par tâche)")
    av.add_argument("lot_id")
    av.add_argument("--budget", type=int, default=200)
    li = actions.add_parser("lire", help="lot, documents et brouillons ; --brouillon pour un contenu")
    li.add_argument("lot_id")
    li.add_argument("--brouillon")
    li.add_argument("--vue", choices=["resume", "documents", "brouillons"], default="resume")
    li.add_argument("--depart", type=int, default=0)
    li.add_argument("--limite", type=int, default=20)
    actions.add_parser("lots", help="les lots récents")
    jr = actions.add_parser("journal", help="journal du pipeline d'un lot (identifiants et codes seulement)")
    jr.add_argument("lot_id")
    for p in (dep, av):
        p.add_argument("--par", required=True, help="personne active admin, finance ou propriétaire, authentifiée")
    li.add_argument("--par", help="requis avec --brouillon (contenu financier ou personnel)")
    o.set_defaults(fn=executer)


def _authentifier(cnx, par: str) -> bool:
    from .. import cli as cli_principal

    return cli_principal._authentifier_action_humaine(cnx, par, ROLES) is not None


def executer(args: argparse.Namespace) -> int:
    from .. import stockage
    from . import service

    try:
        if args.action == "lots":
            with stockage.transaction() as cnx:
                _afficher(service.lister_lots(cnx))
            return 0
        if args.action == "journal":
            with stockage.transaction() as cnx:
                _afficher(service.journal(cnx, args.lot_id))
            return 0
        if args.action == "lire":
            with stockage.transaction() as cnx:
                if args.brouillon:
                    if not args.par or not _authentifier(cnx, args.par):
                        return 1
                    _afficher(service.lire_brouillon(cnx, args.brouillon))
                else:
                    _afficher(service.lire_lot(cnx, args.lot_id, vue=args.vue, depart=args.depart,
                                               limite=args.limite))
            return 0
        with stockage.transaction() as cnx:
            if not _authentifier(cnx, args.par):
                return 1
        if args.action == "deposer":
            with stockage.transaction() as cnx:
                _afficher(service.deposer(cnx, args.par, nom=args.fichier, mutation_id=args.mutation_id))
            return 0
        _afficher(service.avancer(stockage.transaction, args.par, args.lot_id, budget=args.budget))
        return 0
    except IngestionErreur as exc:
        return _erreur(exc)
