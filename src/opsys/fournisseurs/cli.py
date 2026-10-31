"""Sous-commandes `opsys-metier fournisseurs …` et `opsys-metier coffre …` (aussi `opsys metier …` depuis le core).

`coffre` et non `secrets` : `secrets` est déjà une commande du core (`core/src/cli/program/subcli-descriptors.ts`)
et `tests/test_commande_metier.py` interdit qu'une sous-commande du moteur porte le nom d'une commande du core.

Aucune commande n'affiche une valeur de secret : `coffre definir`/`rotation` lisent la valeur au clavier sans
écho (deux fois, comparées), jamais en argument (historique du shell) ni depuis l'environnement ; les sorties ne
portent que des métadonnées, masquées par précaution. Chaque écriture exige l'authentification personnelle
interactive d'un `nathan_owner`/`admin` (même règle que les autres mutations opérateur de la CLI).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from ..secrets_coffre import cle_maitresse, coffre, masquage
from ..secrets_coffre.erreurs import CoffreErreur
from .modele import CAPACITES, TERRITOIRES
from .registre import RegistreErreur

ROLES_ADMIN = {"nathan_owner", "admin"}


def _afficher(donnees: Any) -> None:
    print(masquage.masquer_texte(json.dumps(donnees, ensure_ascii=False, indent=2)))


def _erreur(exc: RegistreErreur | CoffreErreur) -> int:
    print(masquage.masquer_texte(json.dumps({"ok": False, **exc.publique()}, ensure_ascii=False)), file=sys.stderr)
    return 1


def _lire_valeur() -> str:
    """Saisie sans écho, confirmée ; jamais lue depuis argv ni l'environnement hérité des agents."""
    premiere = getpass.getpass("Valeur du secret (saisie masquée) : ")
    seconde = getpass.getpass("Confirmer la valeur : ")
    if premiere != seconde:
        raise CoffreErreur("COFFRE_CONFIRMATION_DIFFERENTE", "les deux saisies diffèrent ; rien n'est enregistré", 422)
    return premiere


class _RefusValeur(argparse.Action):
    """Une valeur passée en argument est refusée SANS être recopiée dans le message d'erreur."""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001 — signature argparse
        if values:
            parser.error("valeur de secret refusée en argument : elle est lue au clavier, sans écho")


def _authentifier(cnx, par: str) -> bool:
    from .. import cli as cli_principal

    return cli_principal._authentifier_action_humaine(cnx, par, ROLES_ADMIN) is not None


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    f = sous.add_parser("fournisseurs", help="registre de fournisseurs (LLM, OCR, STT, TTS, image…) et politique")
    actions = f.add_subparsers(dest="action", required=True)
    lister = actions.add_parser("lister", help="catalogue, licences, politique et état")
    lister.add_argument("--capacite", choices=CAPACITES)
    lister.add_argument("--json", action="store_true", help="sortie JSON complète (métadonnées seulement)")
    conf = actions.add_parser("configurer", help="configurer un fournisseur du catalogue (licence immuable)")
    conf.add_argument("identifiant")
    conf.add_argument("--point-acces")
    conf.add_argument("--secret", metavar="coffre:NOM", help="référence au coffre, jamais une valeur")
    conf.add_argument("--efvp-ref")
    conf.add_argument("--contrat-ref")
    conf.add_argument("--confirmer-mention", action="store_true", help="la mention obligatoire sera affichée")
    conf.add_argument("--licence-lue", action="store_true", help="consigner la lecture du texte intégral")
    for nom in ("activer", "desactiver", "tester"):
        p = actions.add_parser(nom)
        p.add_argument("identifiant")
        if nom == "tester":
            p.add_argument("--delai", type=float, default=5.0, help="secondes (10 au plus)")
    sel = actions.add_parser("selectionner", help="choisir le fournisseur d'une capacité (département ou global)")
    sel.add_argument("capacite", choices=CAPACITES)
    sel.add_argument("identifiant")
    sel.add_argument("--departement", default="*", help="code de département (défaut : global)")
    prof = actions.add_parser("profil", help="déclarer le profil de licence du client")
    prof.add_argument("--usage-commercial", choices=["oui", "non"], required=True)
    prof.add_argument("--revenu-usd", required=True, help="revenu annuel en USD, affiliés compris, ou « inconnu »")
    prof.add_argument("--territoire", action="append", default=[], choices=TERRITOIRES)
    prof.add_argument("--heberge-pour-tiers", choices=["oui", "non"], required=True)
    for p in (conf, sel, prof, *(actions.choices[n] for n in ("activer", "desactiver", "tester"))):
        p.add_argument("--par", required=True, help="personne active admin ou propriétaire, authentifiée")
    f.set_defaults(fn=executer_fournisseurs)

    s = sous.add_parser("coffre", help="coffre de secrets chiffré (aucune valeur n'est jamais affichée)")
    actions = s.add_subparsers(dest="action", required=True)
    actions.add_parser("lister", help="métadonnées des secrets")
    jr = actions.add_parser("journal", help="journal d'accès du coffre")
    jr.add_argument("nom", nargs="?")
    df = actions.add_parser("definir", help="nouveau secret (valeur lue au clavier, sans écho)")
    df.add_argument("nom")
    df.add_argument("--service", required=True, choices=coffre.SERVICES)
    rt = actions.add_parser("rotation", help="nouvelle valeur ; l'ancienne est détruite")
    rt.add_argument("nom")
    rv = actions.add_parser("revoquer", help="révocation immédiate et définitive")
    rv.add_argument("nom")
    rv.add_argument("--confirmer", action="store_true", required=True)
    jt = actions.add_parser("jeton", help="jeton opaque pour un agent (affiché une fois ; pas la valeur)")
    jt.add_argument("nom")
    jt.add_argument("--porteur", required=True)
    jt.add_argument("--usage", required=True, help="ex. fournisseur:ocr.mistral-ocr-3.api")
    jt.add_argument("--duree-s", type=int, default=3600)
    gen = actions.add_parser("generer-cle-maitresse", help="crée un fichier de clé maîtresse 0600 (hors dépôt)")
    gen.add_argument("--fichier", required=True, type=Path)
    rc = actions.add_parser("rechiffrer", help="rotation de la clé maîtresse (ré-enveloppe sans déchiffrer)")
    rc.add_argument("--nouvelle-cle-fichier", required=True, type=Path)
    for p in (df, rt):
        p.add_argument("--valeur", action=_RefusValeur, help=argparse.SUPPRESS)
        p.add_argument("superflu", nargs="*", action=_RefusValeur, help=argparse.SUPPRESS)
    for p in (df, rt, rv, jt, rc):
        p.add_argument("--par", required=True, help="personne active admin ou propriétaire, authentifiée")
    s.set_defaults(fn=executer_secrets)


def _ligne(vue: dict[str, Any]) -> str:
    politique = "conforme" if vue["politique"]["conforme"] else "refus " + ",".join(
        r["code"] for r in vue["politique"]["refus"])
    etat = "actif" if vue["actif"] else ("inactif" if vue["configure"] else "non configuré")
    return f"{vue['identifiant']:<40} {vue['capacite']:<13} {vue['statut_catalogue']:<12} {etat:<14} {politique}"


def executer_fournisseurs(args: argparse.Namespace) -> int:
    from .. import etat
    from . import registre

    if args.action == "lister":
        with etat.session() as cnx:
            vues = registre.lister(cnx, args.capacite)
            profil = registre.profil_brut(cnx)
        if args.json:
            _afficher({"profil": profil, "fournisseurs": vues})
        else:
            if profil is None:
                print("profil de licence du client non déclaré : toute activation est refusée (PROFIL_CLIENT_ABSENT)")
            print("\n".join(masquage.masquer_texte(_ligne(v)) for v in vues))
        return 0
    try:
        if args.action == "tester":
            with etat.session() as cnx:
                if not _authentifier(cnx, args.par):
                    return 1
            _afficher(registre.tester(etat.session, acteur=args.par, identifiant=args.identifiant,
                                      delai_s=min(max(args.delai, 0.1), 10.0)))
            return 0
        with etat.session() as cnx:
            if not _authentifier(cnx, args.par):
                return 1
            if args.action == "configurer":
                modifications: dict[str, Any] = {}
                for cle, valeur in (("point_acces", args.point_acces), ("reference_secret", args.secret),
                                    ("efvp_ref", args.efvp_ref), ("contrat_ref", args.contrat_ref)):
                    if valeur is not None:
                        modifications[cle] = valeur
                if args.confirmer_mention:
                    modifications["mention_confirmee"] = True
                if args.licence_lue:
                    modifications["licence_lue"] = True
                revision = registre.vue(cnx, args.identifiant)["revision"]
                _afficher(registre.configurer(cnx, acteur=args.par, identifiant=args.identifiant,
                                              modifications=modifications, revision_attendue=revision))
            elif args.action == "activer":
                decision = registre.activer(cnx, acteur=args.par, identifiant=args.identifiant)
                _afficher(decision.vers_json())
                if not decision.conforme:
                    return 1
            elif args.action == "desactiver":
                _afficher(registre.desactiver(cnx, acteur=args.par, identifiant=args.identifiant))
            elif args.action == "selectionner":
                _afficher(registre.selectionner(cnx, acteur=args.par, capacite=args.capacite,
                                                identifiant=args.identifiant, departement=args.departement))
            elif args.action == "profil":
                revenu = None if args.revenu_usd == "inconnu" else args.revenu_usd
                if revenu is not None and not revenu.isdigit():
                    print("--revenu-usd : entier en USD ou « inconnu »", file=sys.stderr)
                    return 2
                courant = registre.profil_brut(cnx)
                _afficher(registre.declarer_profil(
                    cnx, acteur=args.par, usage_commercial=args.usage_commercial == "oui",
                    revenu_annuel_usd=int(revenu) if revenu is not None else None, territoires=args.territoire,
                    heberge_pour_tiers=args.heberge_pour_tiers == "oui",
                    revision_attendue=0 if courant is None else courant["revision"]))
    except RegistreErreur as exc:
        return _erreur(exc)
    return 0


def executer_secrets(args: argparse.Namespace) -> int:
    from .. import etat

    try:
        if args.action == "lister":
            with etat.session() as cnx:
                _afficher(coffre.lister(cnx))
            return 0
        if args.action == "journal":
            with etat.session() as cnx:
                _afficher(coffre.journal(cnx, args.nom))
            return 0
        if args.action == "generer-cle-maitresse":
            cle = cle_maitresse.generer_fichier(args.fichier.expanduser().absolute())
            _afficher({"ok": True, "fichier": str(args.fichier), "empreinte": cle.empreinte,
                       "a_faire": f"exporter {cle_maitresse.ENV_FICHIER} vers ce fichier pour le serveur seulement"})
            return 0
        with etat.session() as cnx:
            if not _authentifier(cnx, args.par):
                return 1
        if args.action == "definir":
            _afficher(coffre.avec_journal(etat.session, coffre.definir, acteur=args.par, nom=args.nom,
                                          service=args.service, valeur=_lire_valeur()))
        elif args.action == "rotation":
            _afficher(coffre.avec_journal(etat.session, coffre.rotation, acteur=args.par, nom=args.nom,
                                          valeur=_lire_valeur()))
        elif args.action == "revoquer":
            _afficher(coffre.avec_journal(etat.session, coffre.revoquer, acteur=args.par, nom=args.nom))
        elif args.action == "jeton":
            jeton = coffre.avec_journal(etat.session, coffre.emettre_jeton, acteur=args.par, nom=args.nom,
                                        porteur=args.porteur, usage=args.usage, duree_s=args.duree_s)
            # Le jeton (pas la valeur) est remis une seule fois à l'opérateur pour la configuration de l'agent.
            print(json.dumps({"ok": True, "jeton": jeton, "porteur": args.porteur, "usage": args.usage},
                             ensure_ascii=False))
        elif args.action == "rechiffrer":
            ancienne = cle_maitresse.charger()
            nouvelle = cle_maitresse.charger({cle_maitresse.ENV_FICHIER: str(args.nouvelle_cle_fichier.absolute())})
            nombre = coffre.avec_journal(etat.session, coffre.rechiffrer, acteur=args.par, ancienne=ancienne,
                                         nouvelle=nouvelle)
            _afficher({"ok": True, "versions_reenveloppees": nombre, "empreinte": nouvelle.empreinte,
                       "a_faire": f"pointer {cle_maitresse.ENV_FICHIER} vers la nouvelle clé, "
                                  "puis détruire l'ancienne"})
    except CoffreErreur as exc:
        return _erreur(exc)
    return 0
