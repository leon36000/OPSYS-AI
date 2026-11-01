"""Sous-commande `opsys-metier registre-mcp …` (aussi `opsys metier registre-mcp …` depuis le core).

- `lister [--registre F]` : outils scellés, leur niveau, leur version et le début de leur empreinte ;
- `sceller --par PERSONNE [--registre F] [--retirer] [--hmac] [--a-blanc]` : nouvelle révision du registre à partir des
  outils réellement exposés, après revue humaine. Montre ce qui change (ajoutés, modifiés, niveaux, retirés). Sans
  changement, ne fait rien. Une description suspecte bloque le scellement ;
- `verifier [--registre F] [--hmac] [--json]` : compare les outils exposés maintenant au registre scellé (code de sortie
  1 sur une dérive, un outil inconnu ou un niveau changé ; 2 si le registre lui-même est altéré) ;
- `rule-of-two [--surface S] [--json]` : ce qu'une session exposée à du contenu non fiable peut appeler sans
approbation,
  et ce qui lui est refusé ; valide la table contre le catalogue réel (code 1 si elle est fautive).

Le registre par défaut est celui livré avec le logiciel (`registre.v1.json`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from . import registre as reg
from . import rule_of_two
from .garde import REGISTRE_LIVRE
from .inventaire import inventaire
from .registre import RefusMCP


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("registre-mcp",
                        help="registre MCP en liste blanche et Rule of Two (docs/architecture/OBSERVABILITE-MCP.md)")
    actions = p.add_subparsers(dest="action", required=True)
    for nom, aide in (("lister", "outils scellés"), ("sceller", "sceller une révision après revue humaine"),
                      ("verifier", "comparer les outils exposés au registre scellé"),
                      ("rule-of-two", "table de la Rule of Two par surface non fiable")):
        a = actions.add_parser(nom, help=aide)
        if nom != "rule-of-two":
            a.add_argument("--registre", help=f"fichier du registre (défaut : {REGISTRE_LIVRE.name} livré)")
        if nom in ("sceller", "verifier"):
            a.add_argument("--hmac", action="store_true", help="sceau HMAC avec la clé locale d'observabilité")
        if nom in ("verifier", "rule-of-two"):
            a.add_argument("--json", action="store_true")
        if nom == "sceller":
            a.add_argument("--par", required=True, help="personne qui approuve la révision")
            a.add_argument("--retirer", action="store_true", help="approuver aussi le retrait des outils disparus")
            a.add_argument("--a-blanc", action="store_true", help="montrer les changements sans écrire")
        if nom == "rule-of-two":
            a.add_argument("--surface", choices=rule_of_two.SURFACES_NON_FIABLES)
    p.set_defaults(fn=executer)


def _cle(args: argparse.Namespace) -> bytes | None:
    if not getattr(args, "hmac", False):
        return None
    from ..observabilite import cle_locale

    return cle_locale.deriver(cle_locale.charger(creer=args.action == "sceller"), "mcp/registre/v1")


def _chemin(args: argparse.Namespace) -> Path:
    return Path(args.registre) if getattr(args, "registre", None) else REGISTRE_LIVRE


def _definitions() -> list[reg.DefinitionOutil]:
    from .. import etat
    from ..departements import charger_departements

    return inventaire(charger_departements(), etat.session)


def _rapport_texte(rapport: reg.RapportVerification) -> str:
    lignes = [f"Registre révision {rapport.revision} : {rapport.outils_courants} outil(s) exposé(s)."]
    for d in rapport.derives:
        lignes.append(f"  DÉRIVE   {d.nom} ({', '.join(d.parties)}) : {d.attendue[:19]}… -> {d.obtenue[:19]}…")
    for nom, scelle, courant in rapport.niveaux:
        lignes.append(f"  NIVEAU   {nom} : {scelle} scellé, {courant} exposé")
    for nom in rapport.inconnus:
        lignes.append(f"  INCONNU  {nom} : absent du registre")
    if rapport.absents:
        extrait = ", ".join(rapport.absents[:5])
        lignes.append(f"  ({len(rapport.absents)} outil(s) scellé(s) non exposé(s) ici : {extrait}…)")
    lignes.append("OK : tous les outils exposés correspondent au registre scellé." if rapport.ok
                  else "REFUS : voir les lignes ci-dessus ; revoir puis `opsys-metier registre-mcp sceller --par …`.")
    return "\n".join(lignes)


def _sceller(args: argparse.Namespace) -> int:
    chemin = _chemin(args)
    cle = _cle(args)
    try:
        ancien = reg.charger(chemin, cle=cle)
    except RefusMCP as exc:
        if exc.code != "REJ-MCP-REGISTRE-ABSENT":
            raise
        ancien = None
    nouveau = reg.sceller(_definitions(), ancien, par=args.par, maintenant=dt.datetime.now(dt.UTC), cle=cle,
                          autoriser_retraits=args.retirer)
    if nouveau is ancien:
        print(f"Aucun changement : le registre (révision {ancien.revision}) correspond déjà aux outils exposés.")  # type: ignore[union-attr]
        return 0
    fiche = nouveau.historique[-1]
    print(f"Révision {nouveau.revision} : {len(fiche['ajoutes'])} ajouté(s), {len(fiche['modifies'])} modifié(s), "
          f"{len(fiche['niveaux_changes'])} niveau(x) changé(s), {len(fiche['retires'])} retiré(s).")
    for cle_fiche in ("ajoutes", "modifies", "niveaux_changes", "retires"):
        for nom in fiche[cle_fiche][:50]:
            print(f"  {cle_fiche:<16} {nom}")
    if args.a_blanc:
        print("À blanc : rien n'a été écrit.")
        return 0
    reg.ecrire(chemin, nouveau)
    print(f"Écrit : {chemin} (approuvé par {args.par}). À relire dans la revue de code avant fusion.")
    return 0


def executer(args: argparse.Namespace) -> int:
    try:
        if args.action == "sceller":
            return _sceller(args)
        if args.action == "lister":
            registre = reg.charger(_chemin(args))
            for nom, e in sorted(registre.entrees.items()):
                print(f"{nom:<48} {e.niveau}  v{e.version:<3} {e.surface:<12} {e.empreinte[:19]}…")
            print(f"{len(registre.entrees)} outil(s), révision {registre.revision}, scellé par {registre.scelle_par} "
                  f"le {registre.scelle_le}")
            return 0
        if args.action == "verifier":
            registre = reg.charger(_chemin(args), cle=_cle(args))
            rapport = reg.comparer(registre, _definitions())
            if args.json:
                print(json.dumps({"ok": rapport.ok, "revision": rapport.revision,
                                  "derives": [d.nom for d in rapport.derives],
                                  "niveaux": [n for n, _, _ in rapport.niveaux], "inconnus": list(rapport.inconnus),
                                  "absents": list(rapport.absents)}, ensure_ascii=False))
            else:
                print(_rapport_texte(rapport))
            return 0 if rapport.ok else 1
        definitions = _definitions()
        problemes = rule_of_two.valider_table(definitions)
        surfaces = [args.surface] if args.surface else list(rule_of_two.SURFACES_NON_FIABLES)
        analyses: list[dict[str, Any]] = [rule_of_two.analyser(definitions, s) for s in surfaces]
        if args.json:
            print(json.dumps({"table_valide": not problemes, "problemes": problemes, "surfaces": analyses},
                             ensure_ascii=False, indent=2))
        else:
            for a in analyses:
                print(f"{a['surface']} : {len(a['permis_sans_approbation'])} outil(s) sans approbation, "
                      f"{len(a['refuses_rule_of_two'])} refusé(s) par la Rule of Two, "
                      f"{len(a['refuses_hors_table'])} hors table (approbation requise)")
            print("Table valide." if not problemes else "TABLE FAUTIVE :\n  " + "\n  ".join(problemes))
        return 0 if not problemes else 1
    except RefusMCP as exc:
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail, "outil": exc.outil}, ensure_ascii=False),
              file=sys.stderr)
        return 2
