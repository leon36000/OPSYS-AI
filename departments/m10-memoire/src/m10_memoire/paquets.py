"""Paquets de contexte en couches pour une affaire (PLAN T3.3, P11 — économie de tokens).

Assemble un paquet en QUATRE couches ORDONNÉES pour une affaire (``lead_id``) :

1. ``regles_entreprise``   — décisions M10 de portée générale actuellement ``validee`` (dernier
                              statut connu, ``decisions.decisions_par_statut``) ;
2. ``faits_affaire``       — faits durables de l'affaire, produits par la consolidation nocturne
                              (``consolidation.py``) ;
3. ``evenements_recents``  — événements bruts de l'affaire (WCT, variance) au registre Événements ;
4. ``signaux_non_resolus`` — variances matériaux critiques (``signal_critique``) de l'affaire ; ce
                              module ne porte aucun mécanisme de résolution : TOUT signal critique
                              reste listé tant qu'aucune phase ultérieure n'en trace la clôture.

Chaque couche est bornée par un budget de CARACTÈRES calculé par le code (jamais estimé par un
modèle, AGENTS.md) ; une couche qui dépasse son budget ou son nombre maximal de faits est tronquée
et le DIT explicitement (``tronque``, ``nb_omis``). Une couche sans fait est déclarée VIDE
(``vide: true``), jamais silencieusement absente. Chaque fait porte sa provenance : ``source``,
``horodatage``, ``identifiant`` — rien n'est inventé.

Module pur (DA-M10-08) : aucun import d'``opsys``. Les deux registres sont injectés par
l'appelant (``outils.py``), comme partout ailleurs dans ce paquet.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import classification, consolidation, decisions

BUDGET_CARACTERES_DEFAUT = 4000
NB_FAITS_MAX_PAR_COUCHE_DEFAUT = 5
RESUME_MAX_CARACTERES = 200

COUCHE_REGLES_ENTREPRISE = "regles_entreprise"
COUCHE_FAITS_AFFAIRE = "faits_affaire"
COUCHE_EVENEMENTS_RECENTS = "evenements_recents"
COUCHE_SIGNAUX_NON_RESOLUS = "signaux_non_resolus"

_COUCHES_ORDRE = (COUCHE_REGLES_ENTREPRISE, COUCHE_FAITS_AFFAIRE, COUCHE_EVENEMENTS_RECENTS, COUCHE_SIGNAUX_NON_RESOLUS)


def _resume_borne(texte: Any) -> str:
    texte = "" if texte is None else str(texte)
    if len(texte) <= RESUME_MAX_CARACTERES:
        return texte
    return texte[: RESUME_MAX_CARACTERES - 1] + "…"


def _fait(identifiant: str, horodatage: str, source: str, resume: Any) -> dict[str, str]:
    return {
        "identifiant": identifiant,
        "horodatage": horodatage,
        "source": source,
        "resume": _resume_borne(resume),
    }


def _tri_recent_dabord(maillons: list[dict]) -> list[dict]:
    """Plus récent d'abord. Comparaison par datetime PARSÉ (pas par tri lexicographique du texte
    ISO) : deux horodatages à décalages horaires différents (ex. EDT/EST) ne se comparent pas
    correctement en texte brut."""
    return sorted(maillons, key=lambda m: datetime.fromisoformat(m["horodatage"]), reverse=True)


def _tronquer_couche(nom: str, faits: list[dict], budget_caracteres: int, n_max: int) -> dict[str, Any]:
    """Coupe ``faits`` (déjà triés) pour tenir dans ``budget_caracteres`` ET au plus ``n_max`` —
    dit TOUJOURS ce qu'elle a coupé (``nb_omis``), jamais un silence sur la troncature."""
    total_avant = len(faits)
    retenus: list[dict] = []
    caracteres = 0
    for fait in faits[:n_max]:
        taille = len(json.dumps(fait, ensure_ascii=False, sort_keys=True))
        if retenus and caracteres + taille > budget_caracteres:
            break
        retenus.append(fait)
        caracteres += taille
    nb_omis = total_avant - len(retenus)
    return {
        "nom": nom,
        "vide": len(retenus) == 0,
        "tronque": nb_omis > 0,
        "nb_total": total_avant,
        "nb_inclus": len(retenus),
        "nb_omis": nb_omis,
        "caracteres": caracteres,
        "faits": retenus,
    }


def _couche_regles_entreprise(registre_affaires: Any, budget: int, n_max: int) -> dict[str, Any]:
    decisions_validees = _tri_recent_dabord(decisions.decisions_par_statut(registre_affaires, "validee"))
    faits = [_fait(m["ligne_id"], m["horodatage"], "m10:decision", m.get("raison")) for m in decisions_validees]
    return _tronquer_couche(COUCHE_REGLES_ENTREPRISE, faits, budget, n_max)


def _couche_faits_affaire(affaire_id: str, registre_affaires: Any, budget: int, n_max: int) -> dict[str, Any]:
    bruts = [
        m
        for m in registre_affaires.lire()
        if m.get("type_entree") == consolidation.TYPE_ENTREE_FAIT and m.get("affaire_id") == affaire_id
    ]
    faits = [
        _fait(m["ligne_id"], m["horodatage"], "m10:consolidation", f"{m.get('jour')} : {m.get('resume')}")
        for m in _tri_recent_dabord(bruts)
    ]
    return _tronquer_couche(COUCHE_FAITS_AFFAIRE, faits, budget, n_max)


def _resume_evenement(maillon: dict, type_evenement: str | None, identifiant: str | None) -> str:
    if type_evenement == classification.TYPE_WCT:
        resume = f"WCT {identifiant} : durée réelle {maillon.get('duree_reelle_minutes')} min"
        if maillon.get("ecart_signale"):
            resume += ", écart signalé"
        return resume
    if type_evenement == classification.TYPE_VARIANCE:
        resume = f"Variance {identifiant} : {maillon.get('statut_variance')}"
        if maillon.get("signal_critique"):
            resume += ", signal critique"
        return resume
    return "événement non classifié"


def _fait_evenement(maillon: dict) -> dict[str, str]:
    type_evenement = classification.type_evenement(maillon)
    # L'identifiant PUBLIC (wct_id / evenement_id), pas ligne_id (interne au registre) — même
    # convention que classification.py et audit.py. Repli sur ligne_id seulement si le maillon
    # n'a pas pu être classifié (defensive, ne devrait pas arriver ici : le registre Événements
    # ne contient que des WCT et des variances).
    identifiant = classification.identifiant(maillon) or maillon["ligne_id"]
    source = type_evenement or "inconnu"
    return _fait(identifiant, maillon["horodatage"], source, _resume_evenement(maillon, type_evenement, identifiant))


def _couche_evenements_recents(affaire_id: str, registre_evenements: Any, budget: int, n_max: int) -> dict[str, Any]:
    evenements = _tri_recent_dabord(classification.evenements_de_laffaire(affaire_id, registre_evenements.lire()))
    faits = [_fait_evenement(m) for m in evenements]
    return _tronquer_couche(COUCHE_EVENEMENTS_RECENTS, faits, budget, n_max)


def _couche_signaux_non_resolus(affaire_id: str, registre_evenements: Any, budget: int, n_max: int) -> dict[str, Any]:
    evenements = classification.evenements_de_laffaire(affaire_id, registre_evenements.lire())
    critiques = _tri_recent_dabord(
        [
            m
            for m in evenements
            if classification.type_evenement(m) == classification.TYPE_VARIANCE and m.get("signal_critique") is True
        ]
    )
    faits = [_fait_evenement(m) for m in critiques]
    return _tronquer_couche(COUCHE_SIGNAUX_NON_RESOLUS, faits, budget, n_max)


def assembler_paquet_contexte(
    affaire_id: str,
    horodatage: str,
    registre_evenements: Any,
    registre_affaires: Any,
    *,
    budget_caracteres: int = BUDGET_CARACTERES_DEFAUT,
    n_faits_max_par_couche: int = NB_FAITS_MAX_PAR_COUCHE_DEFAUT,
) -> dict[str, Any]:
    """Rend le paquet complet : ``{affaire_id, horodatage, budget_caracteres,
    caracteres_utilises, couches: [4 couches ordonnées]}``. Lève ``ValueError`` (refus_metier, via
    ``outils.executer``) sur une entrée structurellement invalide — jamais une valeur inventée."""
    if not affaire_id or not isinstance(affaire_id, str):
        raise ValueError("affaire_id requis (chaîne non vide)")
    if not horodatage or not isinstance(horodatage, str):
        raise ValueError("horodatage requis (chaîne non vide)")
    if not isinstance(budget_caracteres, int) or isinstance(budget_caracteres, bool) or budget_caracteres <= 0:
        raise ValueError("budget_caracteres doit être un entier strictement positif")
    if (
        not isinstance(n_faits_max_par_couche, int)
        or isinstance(n_faits_max_par_couche, bool)
        or n_faits_max_par_couche <= 0
    ):
        raise ValueError("n_faits_max_par_couche doit être un entier strictement positif")

    budget_par_couche = budget_caracteres // len(_COUCHES_ORDRE)
    couches = [
        _couche_regles_entreprise(registre_affaires, budget_par_couche, n_faits_max_par_couche),
        _couche_faits_affaire(affaire_id, registre_affaires, budget_par_couche, n_faits_max_par_couche),
        _couche_evenements_recents(affaire_id, registre_evenements, budget_par_couche, n_faits_max_par_couche),
        _couche_signaux_non_resolus(affaire_id, registre_evenements, budget_par_couche, n_faits_max_par_couche),
    ]
    return {
        "affaire_id": affaire_id,
        "horodatage": horodatage,
        "budget_caracteres": budget_caracteres,
        "caracteres_utilises": sum(c["caracteres"] for c in couches),
        "couches": couches,
    }
