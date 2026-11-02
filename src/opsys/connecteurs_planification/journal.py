"""Journal append-only du planificateur : identifiants, modes, codes, compteurs ; jamais un contenu de courriel, une
adresse de correspondant, un jeton ni un secret (liste blanche de clés scalaires courtes, valeurs masquées)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert, select

from ..secrets_coffre import masquage
from ..stockage.schema import PLANIFICATEUR_JOURNAL

DETAILS_PERMIS = frozenset({
    "ressources", "traites", "ignores", "refuses", "erreurs", "messages", "pages", "envoyes", "publies", "transmis",
    "reconcilies", "expires", "aurait", "duree_ms", "revision", "intervalle_s", "ancien_mode", "expire_le", "raison",
    "brouillon_id", "publication_id", "demande_id", "jeton", "porteur", "reseau", "attente_s", "quota", "motif",
    "appels", "etapes", "purges", "elements", "empreinte", "transport", "plafond", "inchanges", "documents", "archives",
    "notices", "affaires", "oublis", "rapports",
})


def instant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def journaliser(cnx: Connection, executeur: str, evenement: str, acteur: str, *, ressource: str | None = None,
                mode: str | None = None, statut: str | None = None, code: str | None = None,
                details: Mapping[str, Any] | None = None) -> None:
    details = dict(details or {})
    for cle, valeur in details.items():
        if cle not in DETAILS_PERMIS or not (valeur is None or isinstance(valeur, (bool, int))
                                             or (isinstance(valeur, str) and len(valeur) <= 64)):
            raise ValueError(f"détail de journal du planificateur non permis : {cle!r}")
    cnx.execute(insert(PLANIFICATEUR_JOURNAL).values(
        quand=instant(), executeur=executeur[:40], ressource=None if ressource is None else ressource[:160],
        evenement=evenement[:32], mode=mode, statut=None if statut is None else statut[:24],
        code=None if code is None else code[:64], acteur=str(acteur)[:200],
        details=masquage.masquer_texte(json.dumps(details, sort_keys=True, ensure_ascii=False))))


def lire(cnx: Connection, executeur: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    requete = select(PLANIFICATEUR_JOURNAL).order_by(PLANIFICATEUR_JOURNAL.c.id.desc()).limit(max(1, min(limite, 500)))
    if executeur is not None:
        requete = requete.where(PLANIFICATEUR_JOURNAL.c.executeur == executeur)
    return [{**dict(r), "details": json.loads(r["details"])} for r in cnx.execute(requete).mappings()]
