"""Sous-commandes `opsys-metier avatars …` (aussi `opsys metier avatars …` depuis le core), en LECTURE seule.

- `avatars etat [--departement ID] [--json]` : pour chaque avatar, ses canaux (messagerie du manifeste ; voix et
  audiovisuel d'après la politique : prevu, configure, qualifie, disponible ou suspendu) et les refus `REJ-AVATAR-*` qui
  expliquent ce qui manque ;
- `avatars registre [--json]` : le registre des voix et visages du client (moteur, licence, consentements comptés,
  dernière qualification).

Aucune écriture : le registre, les consentements et les déclarations de canal passent par `opsys.avatars_voix.registre`
et `politique` (administration authentifiée, journalisées). Aucun secret, aucune empreinte vocale, aucun nom de
locuteur n'est affiché.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("avatars", help="état des avatars (canaux) et registre des voix et visages")
    actions = p.add_subparsers(dest="action", required=True)
    etat = actions.add_parser("etat", help="canaux de chaque avatar et ce qui manque pour la voix et l'audiovisuel")
    etat.add_argument("--departement", help="identifiant d'un département (ex. m01-front-office)")
    reg = actions.add_parser("registre", help="registre des voix et visages du client")
    for a in (etat, reg):
        a.add_argument("--json", action="store_true", help="sortie JSON complète (métadonnées seulement)")
    p.set_defaults(fn=executer_avatars)


def _ligne_etat(avatar: dict[str, Any]) -> str:
    voix, av = avatar["canaux"]["voix"], avatar["canaux"]["audiovisuel"]
    manque = ",".join(dict.fromkeys(voix["codes"] + av["codes"])) or "-"
    return (f"{avatar['code']:<4} {avatar['nom']:<10} messagerie={avatar['canaux']['messagerie']['etat']:<11} "
            f"voix={voix['etat']:<10} audiovisuel={av['etat']:<10} {manque}")


def executer_avatars(args: argparse.Namespace) -> int:
    from .. import avatars, etat
    from ..departements import charger_departements
    from ..taxonomie import ProfilInvalide
    from . import lecture, registre

    try:
        identites = avatars.identites_effectives(charger_departements())
    except (ProfilInvalide, avatars.AvatarInvalide) as exc:
        print(f"ERREUR : avatars illisibles ou invalides : {exc}", file=sys.stderr)
        return 1
    if args.action == "etat" and args.departement:
        if args.departement not in identites:
            print(f"ERREUR : département inconnu {args.departement!r} ({', '.join(identites)})", file=sys.stderr)
            return 2
        identites = {args.departement: identites[args.departement]}
    with etat.session() as cnx:
        vue = lecture.etat_avatars(cnx, identites)
        entrees = registre.lister_entrees(cnx)
    if args.action == "registre":
        if args.json:
            print(json.dumps(vue["registre"], ensure_ascii=False, indent=2))
        elif not vue["registre"]:
            print(f"aucune entrée voix/visage inscrite ({len(entrees)} au registre)")
        else:
            for e in vue["registre"]:
                moteur = e["fournisseur"]["identifiant"] if e["fournisseur"] else "-"
                print(f"{e['identifiant']:<32} {e['etat_effectif']:<10} {moteur:<36} consentements "
                      f"{e['consentements']['actifs']}/{e['consentements']['total']}")
        return 0
    if args.json:
        print(json.dumps(vue, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_ligne_etat(a) for a in vue["avatars"]))
        print(vue["avertissement"])
    return 0
