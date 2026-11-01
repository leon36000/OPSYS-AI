"""Sous-commandes `opsys-metier connaissances …` (aussi `opsys metier connaissances …` depuis le core), en LECTURE
seule.

- `connaissances etat [--departement ID] [--json]` : pour chaque base, le nombre de sources par état, les sources
périmées
  ou à réviser, la date du dernier index, le fournisseur d'embeddings actif (et s'il est raccordé), la couverture
  vectorielle et la réindexation requise ;
- `connaissances sources --departement ID [--etat E] [--json]` : les sources d'une base et l'état de leur dernière
version ;
- `connaissances mesurer --corpus FICHIER [--json]` : le harnais recall@k et MRR (lexical, vectoriel, hybride) sur un
corpus
  de mesure, dans une base TEMPORAIRE jetable avec le double d'embeddings. Ne touche jamais la base de l'instance.

Aucune écriture dans l'instance : l'ingestion, la revue, la publication et le retrait passent par les outils M10
(niveaux
N2/N3, journalisés). Aucun contenu de source n'est affiché, seulement des métadonnées.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .codes import ErreurConnaissances
from .modele import ETATS


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("connaissances", help="état des bases de connaissances par département (lecture seule)")
    actions = p.add_subparsers(dest="action", required=True)
    etat = actions.add_parser("etat", help="sources par état, périmées, dernier index, fournisseur d'embeddings")
    etat.add_argument("--departement", help="identifiant d'un département (ex. m05-financecore)")
    src = actions.add_parser("sources", help="sources d'une base et l'état de leur dernière version")
    src.add_argument("--departement", required=True)
    src.add_argument("--etat", choices=ETATS)
    mes = actions.add_parser("mesurer", help="recall@k et MRR sur un corpus de mesure, base temporaire jetable")
    mes.add_argument("--corpus", required=True, type=Path, help="fichier YAML opsys.connaissances.corpus/v1")
    for a in (etat, src, mes):
        a.add_argument("--json", action="store_true", help="sortie JSON complète (métadonnées seulement)")
    p.set_defaults(fn=executer)


def _ligne_base(b: dict[str, Any]) -> str:
    s = b["sources_par_etat"]
    emb = b["embeddings"]
    fournisseur = emb["identifiant"] + (" (raccordé)" if emb.get("raccorde") else " (NON raccordé)") \
        if emb["statut"] == "selectionne" else f"aucun ({emb['code']})"
    return (f"{b['departement']:<22} sources {b['sources']:>3} : brouillon {s['brouillon']} · revu {s['revu']} · "
            f"publié {s['publie']} · retiré {s['retire']} | périmées {len(b['sources_perimees'])} · "
            f"index lexical {b['derniere_indexation']['lexical'] or '-'} | embeddings {fournisseur}"
            + (" | RÉINDEXATION REQUISE" if b["reindexation_requise"] else ""))


def executer(args: argparse.Namespace) -> int:
    from .. import etat as etat_instance
    from . import lecture, service

    try:
        if args.action == "mesurer":
            return _mesurer(args)
        with etat_instance.session() as cnx:
            if args.action == "sources":
                vue = lecture.lister_sources(cnx, departement=args.departement, etat=args.etat,
                                             maintenant=service.maintenant())
                if args.json:
                    print(json.dumps(vue, ensure_ascii=False, indent=2))
                else:
                    for s in vue["sources"]:
                        drapeaux = ("PÉRIMÉE " if s["perime"] else "") + ("SUSPECTE" if s["suspect"] else "")
                        print(f"{s['cle']:<34} v{s['version']:<3} {s['etat']:<9} {s['domaine']:<13} "
                              f"{drapeaux}".rstrip())
                    print(f"{vue['total']} source(s)")
                return 0
            deps = [args.departement] if args.departement else None
            vue = lecture.etat_bases(cnx, maintenant=service.maintenant(), departements=deps)
    except ErreurConnaissances as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(vue, ensure_ascii=False, indent=2))
    elif not vue["bases"]:
        print("aucune base de connaissances (aucune source ingérée)")
    else:
        print("\n".join(_ligne_base(b) for b in vue["bases"]))
        print(vue["mention_professionnelle"])
    return 0


def _mesurer(args: argparse.Namespace) -> int:
    from .. import stockage
    from . import doubles, mesure

    try:
        corpus = mesure.charger_corpus(args.corpus.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERREUR : corpus illisible : {exc}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="opsys-mesure-") as dossier:
        url = f"sqlite:///{dossier}/mesure.db"
        stockage.migrer(url)
        try:
            with stockage.moteur(url).begin() as cnx:
                rapport = mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe())
        finally:
            stockage.moteur(url).dispose()
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0
    print(rapport["avertissement"])
    for mode, bloc in rapport["modes"].items():
        g = bloc["global"]
        print(f"{mode:<10} recall@1 {g['recall@1']} · @3 {g['recall@3']} · @5 {g['recall@5']} · MRR@10 {g['mrr@10']} · "
              f"abstentions correctes {g['abstentions_correctes']}/{g['questions_sans_reponse']} · "
              f"fausses « aucune source » {g['faux_aucune_source']}")
    return 0
