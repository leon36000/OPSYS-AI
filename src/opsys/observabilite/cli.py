"""Sous-commande `opsys-metier traces …` (aussi `opsys metier traces …` depuis le core).

- `tableau [--jours N] [--json]` : coût et latence par département, refus les plus fréquents (lecture seule) ;
- `verifier` : relit la chaîne d'intégrité du journal de traces ;
- `exporter --destination langfuse [--url U] [--a-blanc]` : export incrémental derrière le port `DestinationTraces`.
  Aucun transport HTTP n'est branché dans cette livraison : sans `--a-blanc`, la commande refuse
  (`REJ-OBS-DESTINATION-NON-CONFIGUREE`) ; avec `--a-blanc`, elle compte ce qui partirait et ce que la garde de sortie
  retiendrait (renseignement personnel détecté) ;
- `purger [--confirmer]` : applique la rétention (à blanc sans `--confirmer`) ;
- `masquer [--texte T] [--mesurer]` : masque un texte (entrée standard par défaut) ; `--mesurer` donne précision,
rappel,
  faux positifs et limites sur le corpus fictif.

Code de sortie : 0 réussi, 1 constat négatif (chaîne rompue, fuite détectée), 2 refus typé (JSON sur la sortie
d'erreur).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import cle_locale, tableaux
from .erreurs import ErreurObservabilite
from .traces import JournalTraces, lire_spans


def ajouter_commandes(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser("traces",
                        help="traces d'exécution des agents, masquage PII (docs/architecture/OBSERVABILITE-MCP.md)")
    p.add_argument("--dossier", help="dossier du journal (défaut : <OPSYS_HOME>/traces)")
    actions = p.add_subparsers(dest="action", required=True)
    ta = actions.add_parser("tableau", help="coût et latence par département (lecture seule)")
    ta.add_argument("--jours", type=int, default=7)
    ta.add_argument("--json", action="store_true")
    actions.add_parser("verifier", help="vérifier la chaîne d'intégrité du journal")
    ex = actions.add_parser("exporter", help="exporter vers une destination (aucun transport réseau livré ici)")
    ex.add_argument("--destination", choices=["langfuse"], required=True)
    ex.add_argument("--url", default="http://langfuse:3000")
    ex.add_argument("--a-blanc", action="store_true")
    pu = actions.add_parser("purger", help="appliquer la rétention (à blanc sans --confirmer)")
    pu.add_argument("--confirmer", action="store_true")
    ma = actions.add_parser("masquer", help="masquer un texte ; --mesurer : mesure sur le corpus fictif")
    ma.add_argument("--texte")
    ma.add_argument("--mesurer", action="store_true")
    p.set_defaults(fn=executer)


def _dossier(args: argparse.Namespace) -> Path:
    from ..stockage.moteur import dossier_opsys

    return Path(args.dossier) if args.dossier else dossier_opsys() / "traces"


def _journal_ecriture(args: argparse.Namespace) -> JournalTraces:
    return JournalTraces(_dossier(args), cle_locale.deriver(cle_locale.charger(), "traces/chaine/v1"))


def _masqueur():
    from .pii import MasqueurMotifs

    return MasqueurMotifs(cle_locale.deriver(cle_locale.charger(creer=True), "pii/v1"))


def executer(args: argparse.Namespace) -> int:
    try:
        if args.action == "tableau":
            depuis = (dt.datetime.now(dt.UTC) - dt.timedelta(days=max(1,
                                                                      args.jours))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            spans = lire_spans(JournalTraces.lecture_seule(_dossier(args)), depuis=depuis)
            lignes, refus = tableaux.agreger(spans), tableaux.refus_par_code(spans)
            print(json.dumps(tableaux.vers_json(lignes, refus), ensure_ascii=False, indent=2) if args.json
                  else tableaux.rendre_texte(lignes, refus))
            return 0
        if args.action == "verifier":
            rapport = _journal_ecriture(args).verifier()
            print(json.dumps({"ok": rapport.ok, "segments": rapport.segments,
                              "enregistrements": rapport.enregistrements,
                              "problemes": list(rapport.problemes)}, ensure_ascii=False, indent=2))
            return 0 if rapport.ok else 1
        if args.action == "exporter":
            from . import destinations

            destination = destinations.DestinationLangfuse(args.url, _cles_langfuse)
            if not args.a_blanc:
                destination.envoyer([])  # lève REJ-OBS-DESTINATION-NON-CONFIGUREE : aucun transport livré
            rapport = destinations.exporter(JournalTraces.lecture_seule(_dossier(args)), destination, _masqueur(),
                                            a_blanc=True)
            print(json.dumps({"destination": rapport.destination, "a_envoyer": rapport.envoyes,
                              "retenus_pii": rapport.refuses_pii}, ensure_ascii=False))
            return 1 if rapport.refuses_pii else 0
        if args.action == "purger":
            journal = _journal_ecriture(args)
            noms = journal.appliquer_retention(a_blanc=not args.confirmer)
            print(json.dumps({"confirme": args.confirmer, "segments": noms}, ensure_ascii=False))
            return 0
        if args.action == "masquer":
            if args.mesurer:
                from .pii_mesure import mesurer

                print(json.dumps(mesurer(_masqueur()), ensure_ascii=False, indent=2))
                return 0
            texte = args.texte if args.texte is not None else sys.stdin.read()
            resultat = _masqueur().masquer(texte)
            print(resultat.texte)
            return 0
        return 2  # pragma: no cover — argparse impose l'action
    except ErreurObservabilite as exc:
        print(json.dumps({"ok": False, **exc.publique()}, ensure_ascii=False), file=sys.stderr)
        return 2


def _cles_langfuse() -> tuple[str, str]:
    """Clés Langfuse lues dans le coffre au moment de l'envoi (jamais en variable d'environnement ni en base de
    traces)."""
    from ..secrets_coffre import coffre

    with coffre.utiliser(usage="traces:langfuse", acteur="opsys-systeme", nom="langfuse.cle-publique") as publique, \
            coffre.utiliser(usage="traces:langfuse", acteur="opsys-systeme", nom="langfuse.cle-secrete") as secrete:
        return str(publique), str(secrete)
