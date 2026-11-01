"""Sous-commande `opsys-metier evaluer …` (aussi `opsys metier evaluer …` depuis le core).

- `valider` : valide le corpus de chaque département (même format pour les dix) et en donne la couverture ;
- `lancer` : exécute le gabarit avec un répondant (`reference`, `dangereux`, `inventif` : doubles déterministes ;
  `passerelle` : vrai modèle par LiteLLM, refusé s'il n'est pas configuré) ; écrit JSON + Markdown sous des noms
  distincts, jamais par-dessus un rapport existant ; code de sortie 1 si un département n'est pas qualifié ;
- `comparer` : régressions nommées entre deux rapports ; code de sortie 1 s'il y en a.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from .corpus import CATEGORIES, RefusEvaluation

REPONDANTS = ("reference", "dangereux", "inventif", "passerelle")


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    e = sous.add_parser("evaluer",
                        help="gabarit d'évaluation commun aux dix départements (docs/architecture/EVALUATION.md)")
    actions = e.add_subparsers(dest="action", required=True)
    va = actions.add_parser("valider", help="valider les corpus et afficher leur couverture")
    la = actions.add_parser("lancer", help="évaluer les départements avec un répondant")
    la.add_argument("--repondant", choices=REPONDANTS, required=True)
    la.add_argument("--sortie", help="dossier des rapports (JSON + Markdown) ; sans lui, Markdown sur la sortie")
    la.add_argument("--precedent", help="rapport JSON précédent : régressions nommées")
    la.add_argument("--avec-references", action="store_true",
                    help="exécuter aussi les corpus existants référencés (M9)")
    la.add_argument("--url-passerelle", help="passerelle LiteLLM (répondant passerelle seulement)")
    la.add_argument("--latence", action="store_true", help="mesurer la latence du répondant (hors comparaison)")
    groupe = la.add_mutually_exclusive_group()
    groupe.add_argument("--pack", help="pack sectoriel actif (défaut : celui du profil d'entreprise, sinon "
                        "generique-pme) ; les cas étiquetés d'un autre pack sont écartés et nommés dans le rapport")
    groupe.add_argument("--tous-les-cas", action="store_true",
                        help="aucun filtre de pack : tous les cas du corpus (diagnostic, jamais une qualification)")
    for p in (va, la):
        p.add_argument("--departement", action="append", help="id ou code (répétable) ; défaut : les dix")
    sm = actions.add_parser("securite-mcp",
                            help="corpus transverse : dérive d'outil et Rule of Two doivent être refusées")
    sm.add_argument("--corpus", help="fichier de corpus (défaut : securite-mcp.v1.yaml livré)")
    sm.add_argument("--sortie", help="dossier du rapport (JSON + Markdown), jamais écrasé")
    co = actions.add_parser("comparer", help="comparer deux rapports JSON")
    co.add_argument("precedent")
    co.add_argument("courant")
    e.set_defaults(fn=executer)


def _lire_json(chemin: str) -> object:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RefusEvaluation("REJ-EVAL-RAPPORT-FORME", f"rapport illisible : {exc}", chemin) from exc


def _repondant(nom: str, entrees: list, departements: dict, url: str | None, pack=None):
    from . import repondants

    if nom in repondants.REPONDANTS_SIMULES:
        return repondants.REPONDANTS_SIMULES[nom]([e["corpus"] for e in entrees])
    from ..departements import tous_les_outils
    from ..modeles import charger_paliers

    schemas = {n: {"description": o.description, "parametres": dict(o.parametres)}
               for n, (_d, o) in tous_les_outils(departements.values()).items()}
    return repondants.RepondantPasserelle(departements, url=url, paliers=charger_paliers(), schemas_outils=schemas,
                                          pack=pack)


def _valider(args: argparse.Namespace, departements: dict) -> int:
    from .executeur import charger_corpus_departements

    entrees = charger_corpus_departements(departements, args.departement)
    total = Counter()
    for entree in entrees:
        compte = Counter(c["categorie"] for c in entree["corpus"]["cas"])
        total.update(compte)
        print(f"{entree['departement']} : {len(entree['corpus']['cas'])} cas — "
              + ", ".join(f"{c} {compte[c]}" for c in CATEGORIES))
    print(f"OK : {sum(total.values())} cas, {len(entrees)} département(s) — "
          + ", ".join(f"{c} {total[c]}" for c in CATEGORIES))
    return 0


def _pack(demande: str | None):
    """Le pack actif de l'évaluation : celui demandé, sinon celui du profil d'entreprise (jamais de repli)."""
    from .. import packs

    try:
        return packs.charger_pack(demande) if demande else packs.pack_actif()
    except packs.RefusPack as exc:
        raise RefusEvaluation("REJ-EVAL-CORPUS-PACK", exc.detail, exc.chemin) from exc


def _identifiant_filtre(args: argparse.Namespace, pack) -> str | None:
    return None if args.tous_les_cas else pack.id


def _lancer(args: argparse.Namespace, departements: dict) -> int:
    from . import executeur, rapport

    entrees = executeur.charger_corpus_departements(departements, args.departement)
    precedent = _lire_json(args.precedent) if args.precedent else None
    pack = _pack(args.pack)
    repondant = _repondant(args.repondant, entrees, departements, args.url_passerelle, pack)
    resultat = executeur.evaluer(entrees, repondant, departements, avec_references=args.avec_references,
                                 horloge=time.perf_counter if args.latence else None,
                                 pack=_identifiant_filtre(args, pack))
    comparaison = rapport.comparer(precedent, resultat) if precedent is not None else None
    texte = rapport.markdown(resultat, comparaison)
    if args.sortie:
        dossier = Path(args.sortie)
        base = (f"evaluation-{args.repondant}-{resultat['corpus']['empreinte'][:12]}-"
                f"{resultat['repondant']['empreinte'][:12]}-{_identifiant_filtre(args, pack) or 'tous-les-cas'}")
        cibles = [dossier / f"{base}.json", dossier / f"{base}.md"]
        if comparaison is not None:
            cibles.append(dossier / f"{base}.comparaison.json")
        existants = [str(c) for c in cibles if c.exists()]
        if existants:
            raise RefusEvaluation("REJ-EVAL-SORTIE-EXISTANTE",
                                  f"rapport déjà présent, jamais écrasé : {', '.join(existants)}")
        dossier.mkdir(parents=True, exist_ok=True)
        cibles[0].write_text(json.dumps(resultat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        cibles[1].write_text(texte, encoding="utf-8")
        if comparaison is not None:
            cibles[2].write_text(json.dumps(comparaison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for cible in cibles:
            print(cible)
    else:
        print(texte, end="")
    return 0 if not resultat["global"]["departements_non_qualifies"] else 1


def _securite_mcp(args: argparse.Namespace) -> int:
    from . import securite_mcp

    rapport, texte = securite_mcp.lancer_depuis_cli(Path(args.corpus) if args.corpus else None)
    if args.sortie:
        revision = rapport["garde"]["revision_registre"]
        base = Path(args.sortie) / f"securite-mcp-{rapport['empreinte_corpus'][:12]}-r{revision}"
        cibles = [base.with_suffix(".json"), base.with_suffix(".md")]
        existants = [str(c) for c in cibles if c.exists()]
        if existants:
            raise RefusEvaluation("REJ-EVAL-SORTIE-EXISTANTE",
                                  f"rapport déjà présent, jamais écrasé : {', '.join(existants)}")
        base.parent.mkdir(parents=True, exist_ok=True)
        cibles[0].write_text(securite_mcp.serialiser(rapport), encoding="utf-8")
        cibles[1].write_text(texte, encoding="utf-8")
        for cible in cibles:
            print(cible)
    else:
        print(texte, end="")
    return 0 if rapport["qualifie"] else 1


def executer(args: argparse.Namespace) -> int:
    from ..departements import charger_departements

    try:
        if args.action == "comparer":
            from .rapport import comparer

            comparaison = comparer(_lire_json(args.precedent), _lire_json(args.courant))
            print(json.dumps(comparaison, ensure_ascii=False, indent=2))
            return 1 if comparaison["regressions"] else 0
        if args.action == "securite-mcp":
            return _securite_mcp(args)
        departements = charger_departements()
        return _valider(args, departements) if args.action == "valider" else _lancer(args, departements)
    except RefusEvaluation as exc:
        print(json.dumps({"ok": False, **exc.publique()}, ensure_ascii=False), file=sys.stderr)
        return 2
