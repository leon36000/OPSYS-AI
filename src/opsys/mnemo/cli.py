"""Sous-commandes `opsys-metier mnemo …` (aussi `opsys metier mnemo …` depuis le core).

- `mnemo etat [--json]` : le modèle de soi (énoncés par état, révisions en attente, dimensions inconnues), le graphe
  (nœuds par type, arêtes par état, arêtes sensibles en attente) et les leçons (par état), en LECTURE seule ;
- `mnemo mesurer --corpus FICHIER [--sortie DOSSIER] [--json] [--avec-gabarit]` : le banc de mesure (questions multi-
  sauts sur un graphe fictif, cas de garde des leçons) dans une base TEMPORAIRE jetable. Ne touche jamais la base de
  l'instance. Le rapport est écrit sous un nom distinct, jamais par-dessus un rapport existant ;
- `mnemo garde-lecon --lecon ID --par NOM` : la garde du gabarit d'évaluation commun pour une leçon (son texte, ajouté
  aux réponses de référence du département visé, ne doit faire régresser aucun cas). Elle monte une instance fictive,
  donc elle ne peut pas tourner dans un appel d'outil ; elle ÉCRIT son verdict au registre des leçons de l'instance
  (append-only).

Aucune de ces commandes ne confirme, ne promeut ni ne retire quoi que ce soit : les décisions passent par les outils
M10 (niveau N3, une personne).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .codes import ErreurMnemo


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("mnemo", help="modèle de soi, graphe de connaissances et leçons apprises (M10)")
    actions = p.add_subparsers(dest="action", required=True)
    etat = actions.add_parser("etat", help="état du modèle de soi, du graphe et des leçons (lecture seule)")
    etat.add_argument("--json", action="store_true")
    mes = actions.add_parser("mesurer", help="banc de mesure sur une base temporaire jetable")
    mes.add_argument("--corpus", required=True, type=Path, help="fichier YAML opsys.mnemo.corpus/v1")
    mes.add_argument("--sortie", type=Path, help="dossier du rapport (JSON + Markdown), jamais écrasé")
    mes.add_argument(
        "--avec-gabarit",
        action="store_true",
        help="exécuter aussi la vraie garde du gabarit pour les leçons (lent) ; sinon elle est simulée sans régression",
    )
    mes.add_argument("--json", action="store_true")
    garde = actions.add_parser("garde-lecon", help="garde du gabarit commun pour une leçon, verdict écrit au registre")
    garde.add_argument("--lecon", required=True)
    garde.add_argument("--par", required=True, help="nom de la personne ou de l'opérateur qui lance la garde")
    p.set_defaults(fn=executer)


def executer(args: argparse.Namespace) -> int:
    try:
        if args.action == "etat":
            return _etat(args)
        if args.action == "mesurer":
            return _mesurer(args)
        return _garde(args)
    except ErreurMnemo as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1


def _etat(args: argparse.Namespace) -> int:
    from .. import etat as etat_instance
    from . import lecons, registres, service, soi
    from .graphe import GrapheSql

    with etat_instance.session() as cnx:
        vue_soi = soi.vue(
            registres.soi(),
            lecteur=soi.LECTEUR_ADMIN,
            maintenant=service.maintenant(),
            etats_voulus=("confirme", "propose", "obsolete"),
        )
        graphe = dict(GrapheSql(cnx).etat())
        vue_lecons = lecons.vue(registres.lecons())
    resume = {
        "soi": {
            "enonces": len(vue_soi["enonces"]),
            "revisions_en_attente": len(vue_soi["revisions_en_attente"]),
            "derives_ouvertes": len(vue_soi["derives_ouvertes"]),
            "dimensions_inconnues": [c["dimension"] for c in vue_soi["couverture"] if c["statut"] == "inconnu"],
        },
        "graphe": graphe,
        "lecons": {"par_etat": vue_lecons["par_etat"], "actives": len(vue_lecons["actives"])},
    }
    if args.json:
        print(json.dumps(resume, ensure_ascii=False, indent=2))
        return 0
    s = resume["soi"]
    print(
        f"modèle de soi : {s['enonces']} énoncé(s), {s['revisions_en_attente']} révision(s) en attente, "
        f"{s['derives_ouvertes']} dérive(s) ouverte(s) ; dimensions inconnues : "
        f"{', '.join(s['dimensions_inconnues']) or '—'}"
    )
    print(
        f"graphe : {sum(graphe['noeuds_par_type'].values())} nœud(s), arêtes {graphe['aretes_par_etat']} ; "
        f"{graphe['aretes_sensibles_en_attente']} sensible(s) en attente d'une personne"
    )
    print(f"leçons : {resume['lecons']['par_etat'] or 'aucune'} ; {resume['lecons']['actives']} promue(s)")
    return 0


def _mesurer(args: argparse.Namespace) -> int:
    from .. import stockage
    from . import mesure
    from .graphe import GrapheSql

    try:
        corpus = mesure.charger_corpus(args.corpus.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERREUR : corpus illisible : {exc}", file=sys.stderr)
        return 2

    def registre_factory() -> Any:
        from m10_memoire.registre import Registre

        return Registre()

    garde = _garde_simulee
    if args.avec_gabarit:
        from ..departements import charger_departements, racine_departements
        from . import garde_gabarit

        deps = charger_departements(racine_departements())

        def garde(cible: str, texte: str) -> dict[str, Any]:  # noqa: F811 — la vraie garde remplace la simulée
            return garde_gabarit.comparer_au_gabarit(deps, cible, texte)

    with tempfile.TemporaryDirectory(prefix="opsys-mnemo-") as dossier:
        url = f"sqlite:///{dossier}/mesure.db"
        stockage.migrer(url)
        try:
            with stockage.moteur(url).begin() as cnx:
                rapport = mesure.executer(corpus, GrapheSql(cnx), garde=garde, registre_factory=registre_factory)
        finally:
            stockage.moteur(url).dispose()
    rapport["garde_gabarit"] = (
        "executee" if args.avec_gabarit else "simulee (sans regression) : non executee dans ce banc"
    )
    texte = mesure.markdown(rapport)
    if args.sortie:
        args.sortie.mkdir(parents=True, exist_ok=True)
        empreinte = hashlib.sha256(
            json.dumps(rapport, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()[:12]
        cibles = [
            args.sortie / f"mnemo-mesure-{corpus['version']}-{empreinte}.json",
            args.sortie / f"mnemo-mesure-{corpus['version']}-{empreinte}.md",
        ]
        if any(c.exists() for c in cibles):
            print(
                f"ERREUR : REJ-MNEMO-SORTIE-EXISTANTE : {[c.name for c in cibles if c.exists()]} existe déjà ; "
                "un rapport n'est jamais écrasé",
                file=sys.stderr,
            )
            return 2
        cibles[0].write_text(json.dumps(rapport, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        cibles[1].write_text(texte, encoding="utf-8")
        print(f"rapports écrits : {cibles[0]} et {cibles[1]}")
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2, default=str))
    elif not args.sortie:
        print(texte)
    g = rapport["graphe"]["modes"]["graphe"]["global"]
    ok = (
        g["exactes"] == g["questions"]
        and rapport["graphe"]["moteurs_concordent"]
        and rapport["lecons"]["conformes"] == rapport["lecons"]["cas"]
    )
    return 0 if ok else 1


def _garde_simulee(_cible: str, _texte: str) -> dict[str, Any]:
    return {"regressions": [], "bloquants_nouveaux": [], "simulee": True}


def garde_lecon(ident: str, par: str) -> dict[str, Any]:
    """La garde du gabarit pour une leçon de l'instance, hors de toute transaction, puis l'écriture du verdict."""
    from .. import etat as etat_instance
    from ..departements import charger_departements, racine_departements
    from . import codes, garde_gabarit, lecons, registres, service

    with etat_instance.session():
        lc = lecons.etat(registres.lecons()).lecons.get(ident)
    if lc is None:
        raise ErreurMnemo(codes.LECON_INCONNUE, "leçon introuvable")
    deps = charger_departements(racine_departements())
    verdict = garde_gabarit.comparer_au_gabarit(deps, lc["cible"], lc["texte_agent"])
    empreinte = garde_gabarit.empreinte_garde(deps, lc["cible"])
    with etat_instance.session():
        lecons.enregistrer_garde(
            registres.lecons(),
            ident,
            verdict,
            empreinte_garde=empreinte,
            horodatage=service.instant_iso(service.maintenant()),
            par=par,
        )
    return verdict


def _garde(args: argparse.Namespace) -> int:
    verdict = garde_lecon(args.lecon, args.par)
    print(
        f"garde du gabarit ({verdict['departement']}, {verdict['effectif']} cas) : score "
        f"{verdict['score_sans_lecon']} → "
        f"{verdict['score_avec_lecon']}, {len(verdict['regressions'])} régression(s), "
        f"{len(verdict['bloquants_nouveaux'])} cas bloquant(s) échoué(s) en plus"
    )
    for r in verdict["regressions"]:
        print(f"  - {r['cas']} ({r['categorie']}, {r['gravite']}) : {', '.join(r['ecarts'])}")
    print("(répondant : double déterministe, aucun modèle réel)")
    return 1 if verdict["regressions"] else 0
