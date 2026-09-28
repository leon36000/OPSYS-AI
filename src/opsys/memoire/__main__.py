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


def _executer(commande: str) -> dict[str, Any]:
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
    return {"vectorises": memoire.completer_embeddings(client.plonger, inclure_personnelles=client.local)}


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(prog="python -m opsys.memoire",
                                      description="Exploitation de la mémoire d'entreprise OPSYS")
    parseur.add_argument("commande", choices=("migrer", "purger", "etat", "completer"))
    args = parseur.parse_args(argv)
    if not os.environ.get(ENV_URL, "").strip():
        print(f"opsys.memoire : variable {ENV_URL} absente (URL PostgreSQL postgresql://…)", file=sys.stderr)
        return 2
    try:
        resultat = _executer(args.commande)
    except (MemoireIndisponible, ErreurEmbeddings) as exc:
        print(f"opsys.memoire : {exc}", file=sys.stderr)
        return 2
    print(json.dumps(resultat, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
