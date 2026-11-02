"""Sous-commande `opsys-metier pack …` (aussi `opsys metier pack …` depuis le core).

- `lister` : les packs installés, le pack du profil d'entreprise et le pack effectif ;
- `valider [--pack ID]` : charge (donc valide strictement, empreinte comprise) un pack ou tous ;
- `afficher ID --departement M3` : le bloc sectoriel EXACT que ce pack ajoute au prompt du département ;
- `empreinte ID [--ecrire]` : l'empreinte du contenu actuel ; `--ecrire` la régénère APRÈS revue du changement ;
- `propositions [--pack ID]` : ce que le pack choisi propose au profil de réception et l'état de chaque élément ;
- `adopter ELEMENT --par NOM` : écrit UN élément proposé dans le profil (signé ; n'écrase jamais la valeur du
  propriétaire) ;
- `choisir ID --par NOM` : écrit `pack: ID` dans le profil d'entreprise (signé au journal d'audit). C'est le geste que
  l'onboarding propose et qu'un humain confirme : l'ingestion ne choisit jamais un pack à la place de l'entreprise.

Code de sortie : 0 réussi, 2 refus typé (`REJ-PACK-…` sur la sortie d'erreur, en JSON).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import adoption, resolution
from .codes import RefusPack
from .manifeste import ID_PACK, NOM_EMPREINTE, calculer_empreinte, charger_dossier
from .rendu import bloc_sectoriel


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("pack", help="packs sectoriels (docs/architecture/PACKS-SECTORIELS.md)")
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("lister", help="packs installés, pack du profil et pack effectif")
    va = actions.add_parser("valider", help="valider un pack (ou tous) : schéma fermé, fichiers, empreinte")
    va.add_argument("--pack", help="identifiant ; défaut : tous les packs installés")
    af = actions.add_parser("afficher", help="le bloc sectoriel ajouté au prompt d'un département")
    af.add_argument("id")
    af.add_argument("--departement", required=True, help="M1 à M10")
    em = actions.add_parser("empreinte", help="empreinte du contenu d'un pack ; --ecrire la régénère après revue")
    em.add_argument("id")
    em.add_argument("--ecrire", action="store_true")
    ch = actions.add_parser("choisir", help="déclarer le pack de l'entreprise dans entreprise.yaml")
    ch.add_argument("id")
    ch.add_argument("--par", required=True, help="personne qui confirme le choix (journal d'audit)")
    pr = actions.add_parser("propositions", help="propositions de profil du pack choisi et leur état (lecture seule)")
    pr.add_argument("--pack", help="identifiant ; défaut : le pack du profil")
    ad = actions.add_parser("adopter", help="adopter UN élément proposé par le pack choisi (signé, sans écraser)")
    ad.add_argument("element", help="élément du profil : " + ", ".join(adoption.ELEMENTS))
    ad.add_argument("--par", required=True, help="personne qui adopte (journal d'audit)")
    ad.add_argument("--pack", help="identifiant ; doit être le pack du profil")
    p.set_defaults(fn=executer)


def _dossier(identifiant: str) -> Path:
    """Dossier d'un pack, après le même contrôle de forme que `charger_pack` (aucun chemin depuis une entrée libre)."""
    if not ID_PACK.fullmatch(identifiant) or len(identifiant) > 64:
        raise RefusPack("REJ-PACK-ID-INVALIDE", "identifiant de pack attendu : minuscules, chiffres et tirets", "id")
    return resolution.racine_packs() / identifiant


def _lister() -> int:
    declare = None
    erreur = None
    try:
        declare = resolution.pack_declare()
        effectif = resolution.pack_actif()
        identite = {"id": effectif.id, "version": effectif.version, "empreinte": effectif.empreinte}
    except RefusPack as exc:
        identite, erreur = None, exc.publique()
    print(json.dumps({
        "dossier": str(resolution.racine_packs()),
        "installes": list(resolution.ids_installes()),
        "declare_dans_le_profil": declare,
        "defaut": resolution.PACK_PAR_DEFAUT,
        "effectif": identite,
        "refus": erreur,
    }, ensure_ascii=False, indent=2))
    return 0 if erreur is None else 2


def executer(args: argparse.Namespace) -> int:
    try:
        if args.action == "lister":
            return _lister()
        if args.action == "valider":
            ids = [args.pack] if args.pack else list(resolution.ids_installes())
            if not ids:
                raise RefusPack("REJ-PACK-INTROUVABLE", "aucun pack installé", str(resolution.racine_packs()))
            for identifiant in ids:
                pack = resolution.charger_pack(identifiant)
                print(f"OK : {pack.id} v{pack.version} ({'sectoriel' if pack.sectoriel else 'générique'}), "
                      f"{len(pack.services)} service(s), {len(pack.glossaire)} terme(s), "
                      f"{len(pack.gabarits)} gabarit(s), {len(pack.baremes)} barème(s) à fournir, "
                      f"empreinte {pack.empreinte[:19]}")
            return 0
        if args.action == "afficher":
            print(bloc_sectoriel(resolution.charger_pack(args.id), args.departement))
            return 0
        if args.action == "empreinte":
            dossier = _dossier(args.id)
            if args.ecrire:
                charger_dossier(dossier, verifier_empreinte=False)  # tout le reste doit être valide avant de sceller
                empreinte = calculer_empreinte(dossier)
                (dossier / NOM_EMPREINTE).write_text(empreinte + "\n", encoding="utf-8")
                print(f"{empreinte}  ({dossier / NOM_EMPREINTE})")
            else:
                print(calculer_empreinte(dossier))
            return 0
        if args.action == "propositions":
            pack = resolution.charger_pack(args.pack or resolution.pack_declare() or resolution.PACK_PAR_DEFAUT)
            print(json.dumps({
                "pack": pack.id, "version": pack.version, "empreinte": pack.empreinte,
                "source": pack.propositions_profil.source if pack.propositions_profil else None,
                "elements": adoption.etat_des_propositions(args.pack),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.action == "adopter":
            print(json.dumps(adoption.adopter_proposition(args.element, par=args.par, pack_id=args.pack),
                             ensure_ascii=False, indent=2))
            return 0
        if args.action == "choisir":
            fichier = resolution.enregistrer_pack(args.id, par=args.par)
            print(fichier)
            return 0
    except RefusPack as exc:
        print(json.dumps({"ok": False, **exc.publique()}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2
