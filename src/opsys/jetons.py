"""Économie de tokens : comptabilité par département, budgets, troncature des sorties.

Voir docs/architecture/ECONOMIE-TOKENS.md pour la stratégie complète. Ce module fournit
les mécanismes mesurables ; aucun LLM n'y décide d'un chiffre.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, func, select

from .departements import Budget
from .stockage.moteur import inserer
from .stockage.schema import ARTEFACTS, USAGE_TOKENS

LIMITE_SORTIE_DEFAUT = 6000  # caractères renvoyés tels quels au modèle
_TETE = 0.7  # part de la limite gardée au début ; le reste va à la fin

_CLES_USAGE_TOKENS = (USAGE_TOKENS.c.jour, USAGE_TOKENS.c.departement, USAGE_TOKENS.c.modele)


def _entier(usage: Mapping[str, Any], *cles: str) -> int:
    for cle in cles:
        valeur = usage.get(cle)
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) and valeur > 0:
            return int(valeur)
    return 0


def normaliser_usage(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Ramène les compteurs des fournisseurs (OpenAI, Anthropic, Hermes) à 3 cases."""
    usage = usage or {}
    entree = _entier(usage, "input_tokens", "prompt_tokens")
    sortie = _entier(usage, "output_tokens", "completion_tokens")
    cache = _entier(usage, "cache_read_tokens", "cache_read_input_tokens", "cached_tokens")
    return {"tokens_entree": entree, "tokens_sortie": sortie, "tokens_cache_lus": cache}


def enregistrer_usage(
    cnx: Connection,
    departement: str,
    modele: str,
    usage: Mapping[str, Any] | None,
    jour: dt.date | None = None,
) -> dict[str, int]:
    compteurs = normaliser_usage(usage)
    cle_jour = (jour or dt.date.today()).isoformat()
    insertion = inserer(cnx)(USAGE_TOKENS).values(
        jour=cle_jour, departement=departement, modele=modele or "inconnu", appels=1,
        tokens_entree=compteurs["tokens_entree"], tokens_sortie=compteurs["tokens_sortie"],
        tokens_cache_lus=compteurs["tokens_cache_lus"],
    )
    cnx.execute(insertion.on_conflict_do_update(
        index_elements=_CLES_USAGE_TOKENS,
        set_={
            "appels": USAGE_TOKENS.c.appels + 1,
            "tokens_entree": USAGE_TOKENS.c.tokens_entree + insertion.excluded.tokens_entree,
            "tokens_sortie": USAGE_TOKENS.c.tokens_sortie + insertion.excluded.tokens_sortie,
            "tokens_cache_lus": USAGE_TOKENS.c.tokens_cache_lus + insertion.excluded.tokens_cache_lus,
        },
    ))
    return compteurs


def fixer_usage(cnx: Connection, jour: dt.date, departement: str, modele: str,
                appels: int, compteurs: Mapping[str, int]) -> None:
    """Écrit une valeur ABSOLUE (synchronisation idempotente depuis la passerelle)."""
    insertion = inserer(cnx)(USAGE_TOKENS).values(
        jour=jour.isoformat(), departement=departement, modele=modele, appels=appels,
        tokens_entree=compteurs["tokens_entree"], tokens_sortie=compteurs["tokens_sortie"],
        tokens_cache_lus=compteurs["tokens_cache_lus"],
    )
    cnx.execute(insertion.on_conflict_do_update(
        index_elements=_CLES_USAGE_TOKENS,
        set_={
            "appels": insertion.excluded.appels,
            "tokens_entree": insertion.excluded.tokens_entree,
            "tokens_sortie": insertion.excluded.tokens_sortie,
            "tokens_cache_lus": insertion.excluded.tokens_cache_lus,
        },
    ))


def consommation(cnx: Connection, departement: str, depuis: dt.date, jusqu_a: dt.date) -> int:
    """Tokens facturables (entrée + sortie) consommés sur la période, bornes incluses."""
    total = cnx.execute(
        select(func.coalesce(func.sum(USAGE_TOKENS.c.tokens_entree + USAGE_TOKENS.c.tokens_sortie), 0))
        .where(USAGE_TOKENS.c.departement == departement,
               USAGE_TOKENS.c.jour.between(depuis.isoformat(), jusqu_a.isoformat()))
    ).scalar_one()
    return int(total)


def etat_budget(
    cnx: Connection, departement: str, budget: Budget, jour: dt.date | None = None
) -> dict[str, Any]:
    """Niveau 'ok' / 'alerte' / 'epuise' sur le jour et le mois en cours."""
    aujourd_hui = jour or dt.date.today()
    jour_utilise = consommation(cnx, departement, aujourd_hui, aujourd_hui)
    mois_utilise = consommation(cnx, departement, aujourd_hui.replace(day=1), aujourd_hui)
    pct_jour = 100 * jour_utilise / budget.tokens_jour
    pct_mois = 100 * mois_utilise / budget.tokens_mois
    pire = max(pct_jour, pct_mois)
    niveau = "epuise" if pire >= 100 else "alerte" if pire >= budget.alerte_pct else "ok"
    return {
        "departement": departement,
        "niveau": niveau,
        "jour": {"utilise": jour_utilise, "limite": budget.tokens_jour, "pct": round(pct_jour, 1)},
        "mois": {"utilise": mois_utilise, "limite": budget.tokens_mois, "pct": round(pct_mois, 1)},
    }


def tronquer(cnx: Connection, texte: str, source: str, limite: int = LIMITE_SORTIE_DEFAUT) -> str:
    """Garde début et fin d'une sortie trop longue ; le texte complet reste lisible par artefact.

    Le modèle ne paie que ce qu'il lit : il relit l'artefact par tranches s'il en a besoin.
    """
    if len(texte) <= limite:
        return texte
    ident = hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]
    insertion = inserer(cnx)(ARTEFACTS).values(
        id=ident, cree_le=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        source=source, taille=len(texte), contenu=texte,
    )
    cnx.execute(insertion.on_conflict_do_nothing(index_elements=[ARTEFACTS.c.id]))
    tete = int(limite * _TETE)
    queue = limite - tete
    omis = len(texte) - tete - queue
    return (
        f"{texte[:tete]}\n\n[… {omis} caractères omis — artefact {ident} ; "
        f"lire la suite avec opsys_lire_artefact(id='{ident}', debut={tete})]\n\n{texte[-queue:]}"
    )


def lire_artefact(cnx: Connection, ident: str, debut: int = 0, longueur: int = 4000) -> dict[str, Any]:
    if debut < 0 or not 0 < longueur <= 20000:
        raise ValueError("debut >= 0 et 0 < longueur <= 20000")
    ligne = cnx.execute(
        select(ARTEFACTS.c.taille, ARTEFACTS.c.contenu).where(ARTEFACTS.c.id == ident)
    ).mappings().fetchone()
    if ligne is None:
        raise KeyError(f"artefact inconnu : {ident}")
    fin = min(debut + longueur, ligne["taille"])
    return {"id": ident, "taille": ligne["taille"], "debut": debut, "fin": fin,
            "contenu": ligne["contenu"][debut:fin], "reste": ligne["taille"] - fin}
