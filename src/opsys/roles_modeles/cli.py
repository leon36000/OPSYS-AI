"""Sous-commande `opsys-metier modeles …` : rôles de modèles, passerelle LiteLLM intégrée, politique d'économie.

Aucune commande n'affiche ni ne lit une valeur de secret au clavier ou en argument : les clés passent par `coffre
definir` (saisie sans écho) ; `modeles passerelle importer-cle` copie, côté serveur, une variable d'environnement
AUTORISÉE
(la clé maîtresse que l'installateur a générée) dans le coffre, sans jamais l'afficher. Toute écriture exige
l'authentification personnelle d'un `nathan_owner`/`admin` ; les gestes N3 exigent en plus `--confirmer-n3`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ..fournisseurs.registre import RegistreErreur
from ..passerelle import _CLE_ENV_FOURNISSEUR
from ..secrets_coffre import coffre, masquage
from ..secrets_coffre.erreurs import CoffreErreur
from . import appel, decouverte, economie, generation, passerelle_fournisseur, service
from . import roles as lex
from .codes import ModelesErreur

ROLES_ADMIN = {"nathan_owner", "admin"}
ENV_IMPORTABLES = frozenset({"LITELLM_MASTER_KEY", *_CLE_ENV_FOURNISSEUR.values()})


def _afficher(donnees: Any) -> None:
    print(masquage.masquer_texte(json.dumps(donnees, ensure_ascii=False, indent=2, default=str)))


def _erreur(exc: ModelesErreur | RegistreErreur | CoffreErreur) -> int:
    print(masquage.masquer_texte(json.dumps({"ok": False, **exc.publique()}, ensure_ascii=False)), file=sys.stderr)
    return 1


def _authentifier(cnx: Any, par: str) -> bool:
    from .. import cli as cli_principal

    return cli_principal._authentifier_action_humaine(cnx, par, ROLES_ADMIN) is not None  # noqa: SLF001


def _paire(texte: str) -> tuple[str, str]:
    cle, sep, valeur = texte.partition("=")
    if not sep or not cle or not valeur:
        raise argparse.ArgumentTypeError("forme attendue : CLE=VALEUR")
    return cle, valeur


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    m = sous.add_parser("modeles", help="rôles de modèles, passerelle LiteLLM intégrée et politique d'économie")
    actions = m.add_subparsers(dest="action", required=True)
    et = actions.add_parser("etat", help="état des rôles, de la passerelle et de l'historique (aucun secret)")
    et.add_argument("--json", action="store_true")
    actions.add_parser("economie", help="politique d'économie : classe de tâche → rôle (recommandation non validée)")

    pg = actions.add_parser("passerelle", help="passerelle LiteLLM : connexion, test, clés, configuration")
    sp = pg.add_subparsers(dest="sous_action", required=True)
    co = sp.add_parser("connecter", help="enregistrer la passerelle (intégrée ou LiteLLM existant) — geste N3")
    co.add_argument("--mode", choices=service.MODES_PASSERELLE, required=True)
    co.add_argument("--url", required=True)
    co.add_argument("--secret-cle", required=True, metavar="NOM", help="nom du secret du coffre (clé de la passerelle)")
    co.add_argument(
        "--secret-amont",
        action="append",
        default=[],
        type=_paire,
        metavar="FOURNISSEUR=NOM",
        help="ex. openrouter=passerelle.openrouter",
    )
    co.add_argument("--reseau-prive", action="store_true", help="http:// tolérée sur un réseau privé confirmé")
    sp.add_parser("retirer", help="déconnecter la passerelle (refusé si un rôle en dépend) — geste N3")
    sp.add_parser("tester", help="test de connexion + découverte du catalogue (/v1/models, /model/info)")
    ic = sp.add_parser("importer-cle", help="copier une variable d'environnement autorisée du serveur vers le coffre")
    ic.add_argument("--depuis-env", required=True, choices=sorted(ENV_IMPORTABLES))
    ic.add_argument("--nom", required=True, help="nom du secret du coffre à créer")
    cf = sp.add_parser("config", help="générer la configuration LiteLLM (rôles + paliers) — aucune clé dedans")
    cf.add_argument("--sortie", required=True, type=Path)
    ev = sp.add_parser("ecrire-env", help="matérialiser depuis le coffre le fichier d'environnement 0600 de LiteLLM")
    ev.add_argument("--fichier", required=True, type=Path)

    ro = actions.add_parser("role", help="affecter, régler, tester ou retirer un rôle")
    sr = ro.add_subparsers(dest="sous_action", required=True)
    cn = sr.add_parser("connecter", help="déclarer l'alias de passerelle comme fournisseur, l'activer et l'affecter")
    cn.add_argument("role", choices=lex.ROLES)
    cn.add_argument("--alias", required=True, help="nom du modèle exposé par la passerelle")
    cn.add_argument("--amont", metavar="FOURNISSEUR/MODELE", help="ex. openrouter/anthropic/claude-haiku-5.5")
    cn.add_argument("--efvp-ref", required=True)
    cn.add_argument("--contrat-ref", required=True)
    af = sr.add_parser("affecter", help="affecter un fournisseur du registre (déjà actif et conforme) à un rôle")
    af.add_argument("role", choices=lex.ROLES)
    af.add_argument("--fournisseur", required=True)
    af.add_argument("--modele", required=True, help="nom du modèle à appeler")
    af.add_argument("--repli", action="append", default=[], type=_paire, metavar="FOURNISSEUR=MODELE")
    for p in (cn, af):
        p.add_argument("--plafond-jetons-jour", type=int)
        p.add_argument("--budget-usd-mois")
    sr.add_parser("retirer", help="retirer l'affectation (le rôle redevient inerte) — N3").add_argument(
        "role", choices=lex.ROLES
    )
    pl = sr.add_parser("plafonds", help="régler les plafonds (N2)")
    pl.add_argument("role", choices=lex.ROLES)
    pl.add_argument("--plafond-jetons-jour", type=int)
    pl.add_argument("--budget-usd-mois")
    te = sr.add_parser("tester", help="test de connexion borné (un appel minuscule) et mesure")
    te.add_argument("role", choices=lex.ROLES)
    rv = sr.add_parser("revenir", help="retour arrière : rétablir l'état d'avant le dernier changement — N3")
    rv.add_argument("cible", help="role:<rôle>, passerelle ou raisonnement")

    ra = actions.add_parser("raisonnement", help="activer (N3, motif) ou désactiver l'escalade vers llm_raisonnement")
    ra.add_argument("sous_action", choices=["activer", "desactiver"])
    ra.add_argument("--motif", help="obligatoire pour activer (10 à 300 caractères)")

    for nom, p in (
        ("passerelle.connecter", co),
        ("passerelle.retirer", sp.choices["retirer"]),
        ("passerelle.tester", sp.choices["tester"]),
        ("passerelle.importer-cle", ic),
        ("passerelle.ecrire-env", ev),
        ("role.connecter", cn),
        ("role.affecter", af),
        ("role.retirer", sr.choices["retirer"]),
        ("role.plafonds", pl),
        ("role.tester", te),
        ("role.revenir", rv),
        ("raisonnement", ra),
    ):
        p.add_argument("--par", required=True, help="personne active admin ou propriétaire, authentifiée")
        if nom not in ("passerelle.tester", "role.plafonds", "role.tester", "passerelle.ecrire-env"):
            p.add_argument("--confirmer-n3", action="store_true", help="confirmation explicite du geste N3")
    m.set_defaults(fn=executer)


def _niveau(args: argparse.Namespace) -> str | None:
    return "N3" if getattr(args, "confirmer_n3", False) else None


def executer(args: argparse.Namespace) -> int:
    from .. import etat

    try:
        if args.action == "etat":
            with etat.session() as cnx:
                vue = service.vue_complete(cnx)
            if args.json:
                _afficher(vue)
            else:
                p = vue["passerelle"]
                print("passerelle : " + (f"{p['mode']} {p['url_base']}" if p["configuree"] else "non configurée"))
                print("raisonnement : " + ("ACTIF" if vue["raisonnement"]["actif"] else "inactif (escalade refusée)"))
                for r in vue["roles"]:
                    ligne = f"{r['role']:<17} {r['etat']:<7}" + (
                        f" {r['fournisseur']['identifiant']} → {r['modele_appel']}" if r["configure"] else ""
                    )
                    print(masquage.masquer_texte(ligne))
            return 0
        if args.action == "economie":
            _afficher(economie.vue())
            return 0
        return _ecritures(args, etat)
    except (ModelesErreur, RegistreErreur, CoffreErreur) as exc:
        return _erreur(exc)


def _ecritures(args: argparse.Namespace, etat: Any) -> int:
    with etat.session() as cnx:
        if not _authentifier(cnx, args.par):
            return 1
    sous = getattr(args, "sous_action", None)
    if args.action == "passerelle":
        if sous == "tester":
            resultat = decouverte.decouvrir(etat.session, acteur=args.par)
            _afficher(
                {k: v for k, v in resultat.items() if k != "entrees"}
                | {"alias": [e["nom"] for e in resultat.get("entrees", [])]}
            )
            return 0 if resultat["statut"] == "succes" else 1
        if sous == "config":
            import yaml

            from .. import modeles as paliers_config

            with etat.session() as cnx:
                config = generation.config_depuis_roles(cnx, paliers_config.charger_paliers())
            args.sortie.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(args.sortie)
            return 0
        if sous == "ecrire-env":
            _afficher({"ok": True, "variables": generation.ecrire_env(etat.session, args.fichier)})
            return 0
        if sous == "importer-cle":
            valeur = os.environ.get(args.depuis_env, "")
            if not valeur:
                print(f"{args.depuis_env} est vide ou absente de l'environnement du serveur", file=sys.stderr)
                return 1
            try:
                _afficher(
                    coffre.avec_journal(
                        etat.session,
                        coffre.definir,
                        acteur=args.par,
                        nom=args.nom,
                        service="fournisseur_modele",
                        valeur=valeur,
                    )
                )
            finally:
                valeur = ""
            return 0
        with etat.session() as cnx:
            if sous == "connecter":
                _afficher(
                    service.appliquer(
                        cnx,
                        acteur=args.par,
                        operation=service.OP_PASSERELLE_CONFIGURER,
                        parametres={
                            "mode": args.mode,
                            "url_base": args.url,
                            "secret_cle": args.secret_cle,
                            "secrets_amont": dict(args.secret_amont),
                            "reseau_prive_confirme": args.reseau_prive,
                        },
                        niveau_confirme=_niveau(args),
                    )
                )
            else:
                _afficher(
                    service.appliquer(
                        cnx,
                        acteur=args.par,
                        operation=service.OP_PASSERELLE_RETIRER,
                        parametres={},
                        niveau_confirme=_niveau(args),
                    )
                )
        return 0
    if args.action == "raisonnement":
        with etat.session() as cnx:
            operation = (
                service.OP_RAISONNEMENT_ACTIVER if args.sous_action == "activer" else service.OP_RAISONNEMENT_DESACTIVER
            )
            _afficher(
                service.appliquer(
                    cnx,
                    acteur=args.par,
                    operation=operation,
                    parametres={},
                    niveau_confirme=_niveau(args),
                    motif=args.motif,
                )
            )
        return 0
    if sous == "tester":
        _afficher(appel.tester_role(etat.session, acteur=args.par, role=args.role))
        return 0
    with etat.session() as cnx:
        if sous == "connecter":
            amont = None
            if args.amont:
                fournisseur, _, modele = args.amont.partition("/")
                amont = {"fournisseur": fournisseur, "modele": modele}
            with etat.session() as cnx2:
                reglage = service.passerelle(cnx2)
            if reglage is None:
                raise ModelesErreur("REJ-MODELES-PASSERELLE-ABSENTE", "connecter la passerelle d'abord", 409)
            declare = passerelle_fournisseur.declarer(
                cnx,
                acteur=args.par,
                role=args.role,
                alias=args.alias,
                secret_cle=reglage["secret_cle"],
                efvp_ref=args.efvp_ref,
                contrat_ref=args.contrat_ref,
            )
            if not declare["active"]:
                _afficher({"ok": False, **declare})
                return 1
            parametres = {
                "role": args.role,
                "fournisseur_id": declare["identifiant"],
                "modele_appel": args.alias,
                "amont": amont,
            }
            parametres.update(_plafonds(args))
            _afficher(
                service.appliquer(
                    cnx,
                    acteur=args.par,
                    operation=service.OP_ROLE_AFFECTER,
                    parametres=parametres,
                    niveau_confirme=_niveau(args),
                )
            )
        elif sous == "affecter":
            parametres = {
                "role": args.role,
                "fournisseur_id": args.fournisseur,
                "modele_appel": args.modele,
                "replis": [{"fournisseur": f, "modele": mo} for f, mo in args.repli],
                **_plafonds(args),
            }
            _afficher(
                service.appliquer(
                    cnx,
                    acteur=args.par,
                    operation=service.OP_ROLE_AFFECTER,
                    parametres=parametres,
                    niveau_confirme=_niveau(args),
                )
            )
        elif sous == "retirer":
            _afficher(
                service.appliquer(
                    cnx,
                    acteur=args.par,
                    operation=service.OP_ROLE_RETIRER,
                    parametres={"role": args.role},
                    niveau_confirme=_niveau(args),
                )
            )
        elif sous == "plafonds":
            _afficher(
                service.appliquer(
                    cnx,
                    acteur=args.par,
                    operation=service.OP_ROLE_PLAFONDS,
                    parametres={"role": args.role, **_plafonds(args)},
                )
            )
        else:
            _afficher(
                service.appliquer(
                    cnx,
                    acteur=args.par,
                    operation=service.OP_REVENIR,
                    parametres={"cible": args.cible},
                    niveau_confirme=_niveau(args),
                )
            )
    return 0


def _plafonds(args: argparse.Namespace) -> dict[str, Any]:
    sortie: dict[str, Any] = {}
    if getattr(args, "plafond_jetons_jour", None) is not None:
        sortie["plafond_jetons_jour"] = args.plafond_jetons_jour
    if getattr(args, "budget_usd_mois", None) is not None:
        sortie["budget_usd_mois"] = args.budget_usd_mois
    return sortie
