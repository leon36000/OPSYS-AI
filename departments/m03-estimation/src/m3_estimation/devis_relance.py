"""Relance devis sans réponse (PLAN T2.3, audit M3 §2.3 : « aucun lead ne reçoit aujourd'hui de
SignalRelanceM2 réel »).

Un devis DURABLE (``devis_durable.py``) reste « sans réponse » quand il n'a jamais atteint le
statut ``accepte`` (donc ``brouillon`` ou ``envoye``, cf. ``devis_durable.STATUTS_DEVIS``) et que
le temps écoulé depuis son dernier état connu (``horodatage`` de l'état courant — celui de la
création ou de la dernière transition, cf. ``devis_durable._etats_courants``) atteint ou dépasse
un délai FOURNI par l'appelant. Ni le délai ni l'instant de référence ne sont déduits ici :

- ``delai_relance_jours`` est un PARAMÈTRE (ou une configuration lue par l'appelant en amont),
  jamais un nombre codé en dur — même discipline que ``plancher_rentable``/``taux_marge`` ailleurs
  dans ce département (AGENTS.md : « fail-closed... jamais une valeur par défaut inventée »).
- ``horodatage_reference`` (le « maintenant » du constat) est également fourni par l'appelant :
  ce module ne consulte AUCUNE horloge — même discipline que ``estime_vs_reel.py``
  (``datetime.fromisoformat`` PARSE une date fournie, il ne LIT jamais l'horloge).

Module pur (ADR-0009, même règle que ``devis_durable.py``/``estime_vs_reel.py``) : aucun import
``opsys``, aucune horloge interne, aucun accès réseau. Ne publie rien elle-même : c'est
``outils.py``, seul, qui appelle ``opsys.evenements.publier`` avec la charge que
``construire_fait_devis_sans_reponse`` produit (catalogue ``m3.devis_sans_reponse``) — même patron
que ``devis_durable.charge_evenement_devis_accepte``/``opsys.evenements.publier``.

Le FAIT publié est strictement descriptif — des horodatages et le délai APPLIQUÉ, jamais une
échéance inventée ou un jugement : « ce devis est au statut X depuis l'horodatage Y, et Y précède
de plus de N jours l'instant Z fourni au contrôle ». Nommer une cause de retard, deviner une
prochaine action ou fixer une échéance future n'est PAS le rôle de ce module (ni de M3) ; c'est un
consommateur (M2, PLAN futur) qui en tirera une action commerciale.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import verdicts

__all__ = ["STATUTS_SANS_REPONSE", "est_sans_reponse", "construire_fait_devis_sans_reponse"]

# Un devis ACCEPTE a reçu sa réponse par définition (devis_durable.STATUTS_DEVIS = "brouillon",
# "envoye", "accepte") : seuls les deux premiers statuts peuvent rester « sans réponse ». Copie
# épinglée, jamais importée (décision #109, même règle que le reste du paquet) : un test de
# non-dérive confronte cette liste à devis_durable.STATUTS_DEVIS.
STATUTS_SANS_REPONSE = ("brouillon", "envoye")


def _horodatage_valide(valeur: Any, nom_champ: str) -> tuple[datetime | None, dict | None]:
    """Garde blanche d'un horodatage ISO-8601 À FUSEAU — même règle que
    ``estime_vs_reel._dans_periode``/``validation._est_horodatage_avec_fuseau``."""
    if not isinstance(valeur, str) or not valeur.strip():
        return None, verdicts.construire_verdict(
            "REJ-RELANCE-HORODATAGE-INVALIDE",
            detail=f"{nom_champ} requis, chaîne ISO-8601 non vide",
        )
    try:
        instant = datetime.fromisoformat(valeur)
    except ValueError:
        return None, verdicts.construire_verdict(
            "REJ-RELANCE-HORODATAGE-INVALIDE", detail=f"{nom_champ} non ISO-8601 : {valeur!r}"
        )
    if instant.tzinfo is None:
        return None, verdicts.construire_verdict(
            "REJ-RELANCE-HORODATAGE-INVALIDE", detail=f"{nom_champ} sans fuseau : {valeur!r}"
        )
    return instant, None


def _delai_valide(delai_relance_jours: Any) -> dict | None:
    if isinstance(delai_relance_jours, bool) or not isinstance(delai_relance_jours, int) or delai_relance_jours <= 0:
        return verdicts.construire_verdict(
            "REJ-RELANCE-DELAI-INVALIDE",
            detail=f"delai_relance_jours doit être un entier strictement positif (reçu {delai_relance_jours!r})",
        )
    return None


def est_sans_reponse(
    devis: dict[str, Any], horodatage_reference: str, delai_relance_jours: int
) -> tuple[bool | None, dict | None]:
    """Règle déterministe : rend ``(True, None)`` si ``devis`` reste sans réponse (statut dans
    ``STATUTS_SANS_REPONSE`` ET ``horodatage_reference - devis["horodatage"] >=
    delai_relance_jours`` jours), ``(False, None)`` sinon (déjà accepté, ou délai non atteint) —
    et ``(None, verdict)`` fail-closed sur toute entrée malformée."""
    if not isinstance(devis, dict) or "statut" not in devis or "horodatage" not in devis:
        return None, verdicts.construire_verdict(
            "REJ-RELANCE-HORODATAGE-INVALIDE",
            detail="devis doit être un dictionnaire portant au moins 'statut' et 'horodatage'",
        )
    verdict = _delai_valide(delai_relance_jours)
    if verdict is not None:
        return None, verdict
    reference, verdict = _horodatage_valide(horodatage_reference, "horodatage_reference")
    if verdict is not None:
        return None, verdict
    instant_devis, verdict = _horodatage_valide(devis["horodatage"], "devis['horodatage']")
    if verdict is not None:
        return None, verdict

    if devis["statut"] not in STATUTS_SANS_REPONSE:
        return False, None
    return (reference - instant_devis) >= timedelta(days=delai_relance_jours), None


def construire_fait_devis_sans_reponse(
    devis: dict[str, Any], horodatage_reference: str, delai_relance_jours: int
) -> tuple[dict[str, Any] | None, dict | None]:
    """Rend ``(fait, None)`` si le devis est SANS RÉPONSE selon la règle, ``(None, None)`` si la
    règle ne s'applique pas (déjà accepté, ou délai non atteint — un NON-événement, pas un rejet),
    et ``(None, verdict)`` si une entrée est malformée. ``fait`` porte exactement les clés
    factuelles de l'événement ``m3.devis_sans_reponse`` (catalogue) — voir la docstring du module
    pour ce qu'il NE contient jamais (aucune échéance inventée, aucun jugement)."""
    sans_reponse, verdict = est_sans_reponse(devis, horodatage_reference, delai_relance_jours)
    if verdict is not None:
        return None, verdict
    if not sans_reponse:
        return None, None
    fait = {
        "devis_id": devis["devis_id"],
        "lead_id": devis["lead_id"],
        "chantier_id": devis.get("chantier_id"),
        "statut": devis["statut"],
        "horodatage_devis": devis["horodatage"],
        "horodatage_reference": horodatage_reference,
        "delai_relance_jours": delai_relance_jours,
    }
    return fait, None
