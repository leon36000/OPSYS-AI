"""Économie de tokens : comptabilité par département, budgets, troncature des sorties.

Voir docs/architecture/ECONOMIE-TOKENS.md pour la stratégie complète. Ce module fournit
les mécanismes mesurables ; aucun LLM n'y décide d'un chiffre.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from collections.abc import Mapping
from typing import Any

from .departements import Budget

LIMITE_SORTIE_DEFAUT = 6000  # caractères renvoyés tels quels au modèle
_TETE = 0.7  # part de la limite gardée au début ; le reste va à la fin


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
    cnx: sqlite3.Connection,
    departement: str,
    modele: str,
    usage: Mapping[str, Any] | None,
    jour: dt.date | None = None,
) -> dict[str, int]:
    compteurs = normaliser_usage(usage)
    cle_jour = (jour or dt.date.today()).isoformat()
    cnx.execute(
        "INSERT INTO usage_tokens (jour, departement, modele, appels, tokens_entree, tokens_sortie,"
        " tokens_cache_lus) VALUES (?, ?, ?, 1, ?, ?, ?)"
        " ON CONFLICT(jour, departement, modele) DO UPDATE SET appels = appels + 1,"
        " tokens_entree = tokens_entree + excluded.tokens_entree,"
        " tokens_sortie = tokens_sortie + excluded.tokens_sortie,"
        " tokens_cache_lus = tokens_cache_lus + excluded.tokens_cache_lus",
        (cle_jour, departement, modele or "inconnu", compteurs["tokens_entree"],
         compteurs["tokens_sortie"], compteurs["tokens_cache_lus"]),
    )
    return compteurs


def fixer_usage(cnx: sqlite3.Connection, jour: dt.date, departement: str, modele: str,
                appels: int, compteurs: Mapping[str, int]) -> None:
    """Écrit une valeur ABSOLUE (synchronisation idempotente depuis la passerelle)."""
    cnx.execute(
        "INSERT INTO usage_tokens (jour, departement, modele, appels, tokens_entree, tokens_sortie,"
        " tokens_cache_lus) VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(jour, departement, modele) DO UPDATE SET appels = excluded.appels,"
        " tokens_entree = excluded.tokens_entree, tokens_sortie = excluded.tokens_sortie,"
        " tokens_cache_lus = excluded.tokens_cache_lus",
        (jour.isoformat(), departement, modele, appels, compteurs["tokens_entree"],
         compteurs["tokens_sortie"], compteurs["tokens_cache_lus"]),
    )


def consommation(cnx: sqlite3.Connection, departement: str, depuis: dt.date, jusqu_a: dt.date) -> int:
    """Tokens facturables (entrée + sortie) consommés sur la période, bornes incluses."""
    ligne = cnx.execute(
        "SELECT COALESCE(SUM(tokens_entree + tokens_sortie), 0) AS total FROM usage_tokens"
        " WHERE departement = ? AND jour BETWEEN ? AND ?",
        (departement, depuis.isoformat(), jusqu_a.isoformat()),
    ).fetchone()
    return int(ligne["total"])


def etat_budget(
    cnx: sqlite3.Connection, departement: str, budget: Budget, jour: dt.date | None = None
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


def tronquer(cnx: sqlite3.Connection, texte: str, source: str, limite: int = LIMITE_SORTIE_DEFAUT) -> str:
    """Garde début et fin d'une sortie trop longue ; le texte complet reste lisible par artefact.

    Le modèle ne paie que ce qu'il lit : il relit l'artefact par tranches s'il en a besoin.
    """
    if len(texte) <= limite:
        return texte
    ident = hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]
    cnx.execute(
        "INSERT OR IGNORE INTO artefacts (id, cree_le, source, taille, contenu) VALUES (?, ?, ?, ?, ?)",
        (ident, dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), source, len(texte), texte),
    )
    tete = int(limite * _TETE)
    queue = limite - tete
    omis = len(texte) - tete - queue
    return (
        f"{texte[:tete]}\n\n[… {omis} caractères omis — artefact {ident} ; "
        f"lire la suite avec opsys_lire_artefact(id='{ident}', debut={tete})]\n\n{texte[-queue:]}"
    )


def lire_artefact(cnx: sqlite3.Connection, ident: str, debut: int = 0, longueur: int = 4000) -> dict[str, Any]:
    if debut < 0 or not 0 < longueur <= 20000:
        raise ValueError("debut >= 0 et 0 < longueur <= 20000")
    ligne = cnx.execute("SELECT taille, contenu FROM artefacts WHERE id = ?", (ident,)).fetchone()
    if ligne is None:
        raise KeyError(f"artefact inconnu : {ident}")
    fin = min(debut + longueur, ligne["taille"])
    return {"id": ident, "taille": ligne["taille"], "debut": debut, "fin": fin,
            "contenu": ligne["contenu"][debut:fin], "reste": ligne["taille"] - fin}
