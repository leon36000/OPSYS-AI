"""Exploitation de la mémoire d'entreprise : `python -m opsys.memoire migrer|purger|etat|completer`.

- La connexion se fait par `OPSYS_DATABASE_URL`.
- `migrer` exige un rôle administrateur (extension vector).
- `purger` est à planifier chaque jour (rétention Loi 25).
- `completer` vectorise les fragments restés en plein texte seul. Les données personnelles ne sont
  incluses que si l'endpoint est local (`OPSYS_EMBEDDINGS_LOCAL=1`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .embeddings import ENV_URL as ENV_EMBEDDINGS_URL
from .embeddings import ClientEmbeddings, ErreurEmbeddings
from .outils import ENV_URL
from .store import MemoireEntreprise, MemoireIndisponible


def _executer(commande: str, *, document_id: str | None = None, sha256: str | None = None,
              limite: int = 8) -> dict[str, Any]:
    if commande != "vectoriser-procedures" and (document_id is not None or sha256 is not None):
        raise ValueError("--document-id et --sha256 sont réservés à vectoriser-procedures")
    memoire = MemoireEntreprise(os.environ.get(ENV_URL, ""))
    if commande == "migrer":
        memoire.migrer()
        return {"migre": True, **memoire.etat()}
    if commande == "purger":
        return {"purges": memoire.purger_expires()}
    if commande == "etat":
        return memoire.etat()
    client = ClientEmbeddings.depuis_env()
    if client is None:
        raise ErreurEmbeddings(f"{ENV_EMBEDDINGS_URL} absente : aucun service pour vectoriser")
    if commande == "vectoriser-procedures":
        if not document_id or not sha256:
            raise ValueError("vectoriser-procedures exige --document-id et --sha256 exacts")
        if not client.local:
            raise ErreurEmbeddings("vectoriser-procedures exige OPSYS_EMBEDDINGS_LOCAL=1")
        return memoire.vectoriser_procedures(document_id, sha256, client, limite=limite)
    if commande == "completer":
        return {"vectorises": memoire.completer_embeddings(client.plonger, inclure_personnelles=client.local)}
    raise ValueError(f"commande mémoire inconnue : {commande}")


def _limite_bornee(brut: str) -> int:
    if len(brut) > 1 or not brut.isascii() or not brut.isdigit():
        raise argparse.ArgumentTypeError("limite doit être un entier canonique entre 1 et 8")
    valeur = int(brut)
    if not 1 <= valeur <= 8 or str(valeur) != brut:
        raise argparse.ArgumentTypeError("limite doit être un entier canonique entre 1 et 8")
    return valeur


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(prog="python -m opsys.memoire",
                                      description="Exploitation de la mémoire d'entreprise OPSYS")
    parseur.add_argument("commande", choices=("migrer", "purger", "etat", "completer", "vectoriser-procedures"))
    parseur.add_argument("--document-id", help="UUID logique exact d'une procédure déjà activée")
    parseur.add_argument("--sha256", help="SHA-256 exact de la version INDEXE active")
    parseur.add_argument("--limite", type=_limite_bornee, default=8, help="fragments maximum (1 à 8)")
    args = parseur.parse_args(argv)
    if not os.environ.get(ENV_URL, "").strip():
        print(f"opsys.memoire : variable {ENV_URL} absente (URL PostgreSQL postgresql://…)", file=sys.stderr)
        return 2
    try:
        resultat = _executer(args.commande, document_id=args.document_id, sha256=args.sha256, limite=args.limite)
    except (MemoireIndisponible, ErreurEmbeddings, ValueError) as exc:
        print(f"opsys.memoire : {exc}", file=sys.stderr)
        return 2
    print(json.dumps(resultat, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
