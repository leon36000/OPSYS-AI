"""Économie de tokens : comptabilité par département, budgets, troncature des sorties.

Voir docs/architecture/ECONOMIE-TOKENS.md pour la stratégie complète. Ce module fournit
les mécanismes mesurables ; aucun LLM n'y décide d'un chiffre.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, and_, select

from .departements import Budget
from .stockage.moteur import inserer
from .stockage.schema import ARTEFACTS, USAGE_TOKENS

LIMITE_SORTIE_DEFAUT = 6000  # caractères renvoyés tels quels au modèle
MAX_I64 = (1 << 63) - 1
_TETE = 0.7  # part de la limite gardée au début ; le reste va à la fin

_CLES_USAGE_TOKENS = (USAGE_TOKENS.c.jour, USAGE_TOKENS.c.departement, USAGE_TOKENS.c.modele)


def _compteur_i64(valeur: Any, champ: str) -> int:
    """Valide un compte exact compatible avec une colonne INTEGER signée sur 64 bits."""
    if type(valeur) is not int or not 0 <= valeur <= MAX_I64:
        raise ValueError(f"{champ} doit être un entier 64 bits entre 0 et {MAX_I64} inclus")
    return valeur


def _entier(usage: Mapping[str, Any], *cles: str) -> int:
    """Valide tous les alias présents et garde la priorité historique du premier compte positif."""
    valeurs = [(_compteur_i64(usage[cle], cle)) for cle in cles if cle in usage]
    return next((valeur for valeur in valeurs if valeur > 0), 0)


def normaliser_usage(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Normalise les alias fournisseur dont les valeurs sont des entiers JSON exacts.

    Une clé absente vaut zéro. Les `int` dans [0, 2^63-1] sont acceptés; booléens, flottants,
    valeurs non finies, chaînes et comptes hors borne sont refusés sans troncature ni substitution.
    Les alias restent dans leur priorité historique; chaque alias effectivement fourni est validé.
    """
    if usage is None:
        usage = {}
    if not isinstance(usage, Mapping):
        raise ValueError("usage fournisseur doit être un objet de compteurs")
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
    """Compte l'usage au jour UTC par défaut, comme l'admission des agents.

    Un jour explicite reste inchangé ; aucune ligne historique n'est reclassée.
    """
    compteurs = normaliser_usage(usage)
    cle_jour = (jour or dt.datetime.now(dt.UTC).date()).isoformat()
    insertion = inserer(cnx)(USAGE_TOKENS).values(
        jour=cle_jour, departement=departement, modele=modele or "inconnu", appels=1,
        tokens_entree=compteurs["tokens_entree"], tokens_sortie=compteurs["tokens_sortie"],
        tokens_cache_lus=compteurs["tokens_cache_lus"],
    )
    resultat = cnx.execute(insertion.on_conflict_do_update(
        index_elements=_CLES_USAGE_TOKENS,
        set_={
            "appels": USAGE_TOKENS.c.appels + 1,
            "tokens_entree": USAGE_TOKENS.c.tokens_entree + insertion.excluded.tokens_entree,
            "tokens_sortie": USAGE_TOKENS.c.tokens_sortie + insertion.excluded.tokens_sortie,
            "tokens_cache_lus": USAGE_TOKENS.c.tokens_cache_lus + insertion.excluded.tokens_cache_lus,
        },
        where=and_(
            USAGE_TOKENS.c.appels <= MAX_I64 - 1,
            USAGE_TOKENS.c.tokens_entree <= MAX_I64 - compteurs["tokens_entree"],
            USAGE_TOKENS.c.tokens_sortie <= MAX_I64 - compteurs["tokens_sortie"],
            USAGE_TOKENS.c.tokens_cache_lus <= MAX_I64 - compteurs["tokens_cache_lus"],
        ),
    ).returning(USAGE_TOKENS.c.appels))
    if resultat.first() is None:
        raise ValueError("l'accumulation de l'usage dépasse la borne signée 64 bits")
    return compteurs


def fixer_usage(cnx: Connection, jour: dt.date, departement: str, modele: str,
                appels: int, compteurs: Mapping[str, int]) -> None:
    """Écrit une valeur ABSOLUE (synchronisation idempotente depuis la passerelle)."""
    appels = _compteur_i64(appels, "appels")
    if not isinstance(compteurs, Mapping):
        raise ValueError("compteurs doit être un objet")
    requis = ("tokens_entree", "tokens_sortie", "tokens_cache_lus")
    manquants = [nom for nom in requis if nom not in compteurs]
    if manquants:
        raise ValueError(f"compteur(s) manquant(s) : {', '.join(manquants)}")
    valeurs = {
        nom: _compteur_i64(compteurs[nom], nom) for nom in requis
    }
    insertion = inserer(cnx)(USAGE_TOKENS).values(
        jour=jour.isoformat(), departement=departement, modele=modele, appels=appels,
        tokens_entree=valeurs["tokens_entree"], tokens_sortie=valeurs["tokens_sortie"],
        tokens_cache_lus=valeurs["tokens_cache_lus"],
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
    """Retourne l'agrégat exact (entrée + sortie), sans borne de cellule sur le total période."""
    lignes = cnx.execute(
        select(USAGE_TOKENS.c.tokens_entree, USAGE_TOKENS.c.tokens_sortie)
        .where(USAGE_TOKENS.c.departement == departement,
               USAGE_TOKENS.c.jour.between(depuis.isoformat(), jusqu_a.isoformat()))
    )
    total = 0
    for ligne in lignes:
        entree = _compteur_i64(ligne.tokens_entree, "tokens_entree stocké")
        sortie = _compteur_i64(ligne.tokens_sortie, "tokens_sortie stocké")
        somme_ligne = entree + sortie  # l'addition Python ne déborde pas
        total += somme_ligne
    return total


def etat_budget(
    cnx: Connection, departement: str, budget: Budget, jour: dt.date | None = None
) -> dict[str, Any]:
    """Niveau 'ok' / 'alerte' / 'epuise' sur le jour/mois UTC, ou le jour explicite fourni."""
    aujourd_hui = jour or dt.datetime.now(dt.UTC).date()
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


def tronquer(
    cnx: Connection, texte: str, source: str, limite: int = LIMITE_SORTIE_DEFAUT, *,
    departement: str | None = None, origine: str | None = None,
) -> str:
    """Garde début et fin d'une sortie trop longue ; le texte complet reste lisible par artefact.

    Le modèle ne paie que ce qu'il lit : il relit l'artefact par tranches s'il en a besoin.
    """
    if len(texte) <= limite:
        return texte
    from . import contexte

    departement = departement or contexte.DEPARTEMENT_APPELANT.get()
    origine = origine or contexte.departement_origine_appelante()
    tete = int(limite * _TETE)
    queue = limite - tete
    omis = len(texte) - tete - queue
    if (
        not isinstance(departement, str) or not departement.strip()
        or not isinstance(origine, str) or not origine.strip()
    ):
        return (
            f"{texte[:tete]}\n\n[… {omis} caractères omis — reprise non conservée : origine authentifiée absente]\n\n"
            f"{texte[-queue:]}"
        )
    ident = hashlib.sha256(f"{departement}\0{origine}\0{source}\0{texte}".encode()).hexdigest()[:16]
    insertion = inserer(cnx)(ARTEFACTS).values(
        id=ident, cree_le=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        source=source, departement=departement, origine=origine, taille=len(texte), contenu=texte,
    )
    cnx.execute(insertion.on_conflict_do_nothing(index_elements=[ARTEFACTS.c.id]))
    return (
        f"{texte[:tete]}\n\n[… {omis} caractères omis — artefact {ident} ; "
        f"lire la suite avec opsys_lire_artefact(id='{ident}', debut={tete})]\n\n{texte[-queue:]}"
    )


def lire_artefact(cnx: Connection, ident: str, debut: int = 0, longueur: int = 4000) -> dict[str, Any]:
    if debut < 0 or not 0 < longueur <= 20000:
        raise ValueError("debut >= 0 et 0 < longueur <= 20000")
    from .contexte import departement_origine_appelante

    origine = departement_origine_appelante()
    if not isinstance(origine, str) or not origine.strip():
        raise KeyError("artefact inconnu")
    ligne = cnx.execute(
        select(ARTEFACTS.c.taille, ARTEFACTS.c.contenu).where(
            ARTEFACTS.c.id == ident, ARTEFACTS.c.origine == origine
        )
    ).mappings().fetchone()
    if ligne is None:
        raise KeyError("artefact inconnu")
    fin = min(debut + longueur, ligne["taille"])
    return {"id": ident, "taille": ligne["taille"], "debut": debut, "fin": fin,
            "contenu": ligne["contenu"][debut:fin], "reste": ligne["taille"] - fin}
