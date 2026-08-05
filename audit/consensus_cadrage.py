#!/usr/bin/env python3
"""Distribution du cadrage BMAD de l'audit au panel élargi, sans toucher à l'instrument.

`scripts/consensus_run.py` porte son pack en dur (`PACK_CONSENSUS_GRS_v2.md`) et n'expose
aucune option `--pack`. L'audit ne corrige rien (DA-AUD-04) : au lieu d'ajouter l'option,
on IMPORTE `live()` et on lui passe le chemin voulu — l'instrument reste byte-identique et
c'est bien LUI qui est exercé, pas une réimplémentation.

Le chemin-en-dur est par ailleurs un constat candidat du lot A6, consigné là-bas et non ici :
un audit ne doit pas se réparer un instrument en passant, sinon il mesure sa propre rustine.

Usage : exporter d'abord la clé de passerelle dans l'environnement (jamais en ligne de
commande, où elle resterait dans l'historique du shell), puis :

  python3 audit/consensus_cadrage.py --pack <fichier> --outdir <dossier>
"""
import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

import consensus_run  # noqa: E402  (import après ajustement du chemin)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--models", default=None)
    parser.add_argument("--vendor-auteur", default="anthropic")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-tokens", type=int, default=16000)
    args = parser.parse_args()

    if args.models:
        modeles = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        modeles = list(consensus_run.DEFAULT_MODELS)

    cle = os.environ.get("LITELLM_API_KEY")  # proof:allow — lecture d'environnement
    if not cle:  # proof:allow — nom de variable, aucun secret littéral
        print("BLOCKED: LITELLM_API_KEY manquante.", file=sys.stderr)
        return 2

    transport = consensus_run.make_real_transport(args.timeout, args.max_tokens)
    return consensus_run.live(
        modeles, transport, args.outdir, args.vendor_auteur, args.pack
    )


if __name__ == "__main__":
    sys.exit(main())
