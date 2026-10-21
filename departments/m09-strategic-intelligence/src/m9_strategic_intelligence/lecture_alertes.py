"""Lecture BORNÉE des alertes de M8 déjà reçues (PLAN T1.5-d ; DEFINITION-PRODUIT.md §9 : l'app du
propriétaire lit ce que l'écran et le modèle peuvent porter).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. ``m9_lire_alertes_m8`` rendait TOUTES
les alertes reçues (``m8.alerte_proposee``), sans limite : la réponse finissait par dépasser la limite de
sortie de ``Capacites`` (6 000 caractères) et l'app recevait un aperçu coupé. ``lire_alertes_m8`` applique le
MÊME mécanisme que ``briefing_matin.lire_suite_section`` (``m9_lire_suite_briefing``) : ``depart`` reprend la
lecture, autant d'alertes que ``budget_caracteres`` en laisse tenir (taille sérialisée mesurée par le code,
jamais estimée), ``prochain_depart`` est nul à la fin. Ce qui ne tient pas est compté (``reste``), jamais
perdu en silence.

ORDRE, stable et total : le plus récent d'abord (``horodatage_reference`` comparé en instant, fuseaux
compris, jamais alphabétiquement), puis, à instant égal, ``evenement_id`` croissant. Les alertes ne sont
jamais retirées du registre : une alerte reçue entre deux pages s'insère dans l'ordre, donc peut décaler
les suivantes. ``total`` change alors : l'appelant relit depuis 0.

Aucun filtre : la fenêtre de jours du briefing ne s'applique pas ici, et les rappels « seuil à configurer »
y figurent comme les autres alertes (le briefing, lui, les range dans ses manques).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .briefing_matin import _CHAMPS_ALERTE, _analyser_horodatage, _taille, _valider_champs

__all__ = ["ORDRE_ALERTES", "lire_alertes_m8"]

ORDRE_ALERTES = "horodatage_reference décroissant (le plus récent d'abord), puis evenement_id croissant"
_SOURCE = "m8.alerte_proposee (registre m09-strategic-intelligence/alertes_m8)"


def _instant(alerte: dict[str, Any]) -> datetime:
    """Instant de référence de l'alerte ; illisible : refus qui nomme l'alerte (jamais une date devinée)."""
    valeur = alerte["horodatage_reference"]
    try:
        return _analyser_horodatage(valeur)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            f"alertes_m8 : horodatage_reference illisible pour {alerte['evenement_id']} : {valeur!r}"
        ) from exc


def _ordonner(alertes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Le plus récent d'abord, départage par identifiant. Deux tris stables : d'abord l'identifiant
    croissant, puis l'instant décroissant (``reverse=True`` conserve l'ordre des instants égaux)."""
    par_identifiant = sorted(alertes, key=lambda alerte: str(alerte["evenement_id"]))
    return sorted(par_identifiant, key=_instant, reverse=True)


def lire_alertes_m8(
    alertes_m8: list[dict[str, Any]], depart: int = 0, *, budget_caracteres: int,
) -> dict[str, Any]:
    """Une page des alertes de M8 reçues, dans l'ordre de ``ORDRE_ALERTES``, à partir de ``depart`` (rang
    dans la liste complète), autant que ``budget_caracteres`` en laisse tenir (au moins une : une page vide
    ne ferait jamais progresser la lecture).

    Rend ``total`` (toutes les alertes reçues), ``depart``, ``affichees``, ``reste`` (ce qui vient APRÈS la
    page) et ``prochain_depart`` (le ``depart`` à demander ensuite, ``None`` à la fin). Un ``depart`` égal à
    ``total`` rend une page vide et ``prochain_depart: None``.

    Fail-closed, en ``ValueError`` qui dit quoi corriger : ``depart`` qui n'est pas un entier ≥ 0 ou qui
    dépasse la fin (``total`` en cause : reprendre à 0), budget invalide, alerte sans ses champs ou à
    l'horodatage illisible, une seule alerte plus grosse que le budget."""
    if isinstance(depart, bool) or not isinstance(depart, int) or depart < 0:
        raise ValueError(f"depart : entier supérieur ou égal à 0 attendu, reçu {depart!r}")
    if isinstance(budget_caracteres, bool) or not isinstance(budget_caracteres, int) or budget_caracteres < 1:
        raise ValueError(f"budget_caracteres : entier strictement positif attendu, reçu {budget_caracteres!r}")
    valides = [_valider_champs(alerte, _CHAMPS_ALERTE, "alertes_m8") for alerte in alertes_m8]
    alertes = _ordonner(valides)
    total = len(alertes)
    if depart > total:
        raise ValueError(
            f"depart {depart} au-delà de la fin des alertes ({total} alerte(s) reçue(s)) : "
            "reprendre à depart=0 (le total a pu changer depuis la page précédente)"
        )

    def page(nombre: int) -> dict[str, Any]:
        fin = depart + nombre
        reste = total - fin
        return {
            "type": "ALERTES_M8",
            "source": _SOURCE,
            "ordre": ORDRE_ALERTES,
            "total": total,
            "depart": depart,
            "affichees": nombre,
            "reste": reste,
            "prochain_depart": fin if reste else None,
            "message": (
                None if not reste else
                (f"{reste} autres alertes non affichées : poursuivre avec depart={fin}." if reste > 1
                 else f"1 autre alerte non affichée : poursuivre avec depart={fin}.")
            ),
            "alertes": [dict(alerte) for alerte in alertes[depart:fin]],
        }

    nombre = 0
    while depart + nombre < total and _taille(page(nombre + 1)) <= budget_caracteres:
        nombre += 1
    if depart < total and nombre == 0:
        raise ValueError(
            f"l'alerte {alertes[depart]['evenement_id']} dépasse à elle seule la borne de {budget_caracteres} "
            "caractères : impossible de la lire par page"
        )
    return page(nombre)
