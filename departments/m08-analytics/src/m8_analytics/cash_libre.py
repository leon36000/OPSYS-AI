"""Le cash libre que M5 a constaté, repris tel quel par M8 (PLAN T4.19-b ; DEFINITION-PRODUIT §7 M5 « source de
vérité financière », §7 M8 « pour la finance, M8 consomme M5 et ne recalcule pas », §8, P13).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (« aujourd'hui » vient de l'appelant, quand il le
donne). ``outils.py``, seul point de contact avec le socle, reçoit l'événement ``m5.cash_libre_constate``, range le fait
au registre ``faits_cash_libre`` et lit ce registre pour la vue exécutive.

M8 ne calcule AUCUN montant de M5 : ni somme, ni écart, ni arrondi, ni comparaison. Un montant passe du fait reçu à la
réponse par un simple ``.get()``, en texte, tel que M5 l'a publié. Le garde statique de ``test_cash_libre.py`` le
verrouille : aucun ``Decimal``, ``float``, ``round`` ni ``sum``, et une seule opération arithmétique dans tout le
module, la soustraction de deux DATES qui donne l'âge du constat (``age_en_jours``).

Le DERNIER constat est celui de plus grand ``sequence`` (le rang que M5 lui a donné à sa publication), quel que soit
l'ordre de livraison du bus ; à égalité, le dernier reçu. Sans aucun constat, la vue dit « manque », comme avant
T4.19-b : M8 n'a rien à montrer et ne le remplace par aucun chiffre. Un constat « non calculable, manque X » est montré
tel quel (statut, codes de manque, repère ``au_plus_cad`` et la phrase de M5 qui dit que ce n'est pas de l'argent
disponible) : jamais un zéro, jamais un cash libre que M5 n'a pas calculé.

La vue reprend l'essentiel du constat (statut, montants, ce qui manque, réserves, la phrase de M5, la mention
obligatoire, le montant de chaque composante : ``null`` quand M5 n'a pas pu la chiffrer, jamais zéro) et DIT ce qu'elle
ne reprend pas (la source et la fraîcheur de chaque composante, les hypothèses : ``m5_etat_tresorerie`` les rend), à
cause de la borne de sortie du socle. Le fait rangé, lui, garde tout ce que M5 a publié.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

TYPE_CONSTAT = "cash_libre_constate"
EVENEMENT = "m5.cash_libre_constate"
SOURCE = "M5 (m5.cash_libre_constate)"

_JOUR = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_STATUT_CALCULE = "CALCULE"
_RAISON_MANQUE = (
    "M5 n'a publié aucun constat du cash libre (m5.cash_libre_constate) : M8 ne peut ni le lire ni le recalculer, il "
    "ne fait pas la comptabilité ; l'admin le fait constater par m5_constater_cash_libre"
)
_A_LIRE_SANS_CONSTAT = (
    "m5_etat_tresorerie (admin), avec la décomposition du cash libre ; m5_constater_cash_libre (admin) le publie à M8"
)
_NON_REPRIS = "source et fraîcheur de chaque composante, hypothèses"
_NON_REPRIS_SANS_COMPOSANTES = "décomposition, source et fraîcheur de chaque composante, hypothèses"
_A_LIRE_AVEC_CONSTAT = "m5_etat_tresorerie (admin)"


# ---------------------------------------------------------------------------
# Le fait : ce que M5 a publié, rangé tel quel
# ---------------------------------------------------------------------------
def fait_constat(charge: dict[str, Any]) -> dict[str, Any]:
    """Fait tiré de ``m5.cash_libre_constate`` : la charge TELLE QUE M5 l'a publiée (le catalogue du socle l'a validée :
    schéma fermé, montants en texte, aucun renseignement personnel), avec son type d'entrée. Rien n'est retiré, rien
    n'est calculé."""
    return {"type_entree": TYPE_CONSTAT, **charge}


def cles_unicite() -> tuple[str, ...]:
    """La clé qui fait un fait unique : l'identifiant de l'événement (un par constat de M5). Une relivraison de
    l'événement, ou un rejeu du répartiteur, n'ajoute jamais un second fait."""
    return ("evenement_id",)


def _constats(faits: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [
        (indice, fait) for indice, fait in enumerate(faits)
        if fait.get("type_entree") == TYPE_CONSTAT and isinstance(fait.get("evenement_id"), str)
    ]


def _rang(paire: tuple[int, dict[str, Any]]) -> tuple[int, int]:
    """Le rang de M5 (``sequence``, 0 s'il est illisible), puis l'ordre de réception pour départager."""
    indice, fait = paire
    sequence = fait.get("sequence")
    lisible = isinstance(sequence, int) and not isinstance(sequence, bool)
    return (sequence if lisible else 0, indice)


def constat_courant(faits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le DERNIER constat de M5 parmi les faits reçus : le plus grand ``sequence`` (l'ordre de livraison du bus n'est
    pas garanti), à égalité le dernier reçu. ``None`` si M8 n'en a reçu aucun."""
    constats = _constats(faits)
    return max(constats, key=_rang)[1] if constats else None


def nombre_de_constats(faits: list[dict[str, Any]]) -> int:
    """Combien de constats DISTINCTS M8 a reçus (un par identifiant d'événement)."""
    return len({fait["evenement_id"] for _, fait in _constats(faits)})


# ---------------------------------------------------------------------------
# L'âge : la seule arithmétique du module, sur des dates
# ---------------------------------------------------------------------------
def _jour(texte: Any) -> date | None:
    if not isinstance(texte, str) or _JOUR.fullmatch(texte) is None:
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


def lire_aujourd_hui(brut: Any) -> str | None:
    """``aujourd_hui`` de l'appelant : ``None`` s'il n'est pas donné, sinon le texte ``AAAA-MM-JJ`` (un jour du
    calendrier). Illisible : refus nommé, jamais corrigé ni deviné (M8 n'a pas d'horloge)."""
    if brut is None:
        return None
    if _jour(brut) is None:
        raise ValueError(
            f"REJ-VUE-AUJOURD-HUI-INVALIDE : aujourd_hui doit être une date AAAA-MM-JJ, ou absent (reçu {brut!r})"
        )
    return brut


def age_en_jours(date_reference: Any, aujourd_hui: Any) -> int | None:
    """Le nombre de jours entiers de la date de référence du constat à ``aujourd_hui`` ; ``None`` si l'une des deux
    dates est illisible. Négatif si le constat est daté d'après ``aujourd_hui`` (l'appelant tranche). C'est la SEULE
    opération arithmétique de ce module : une soustraction de deux dates, jamais d'un montant."""
    debut, fin = _jour(date_reference), _jour(aujourd_hui)
    return None if debut is None or fin is None else (fin - debut).days


def age(date_reference: Any, aujourd_hui: str | None) -> dict[str, Any]:
    """L'âge du constat, dit avec ce qui manque quand il ne se calcule pas : sans ``aujourd_hui``, « non calculable »
    (M8 n'a pas d'horloge, il ne devine jamais la date) ; une date de référence illisible ou postérieure à
    ``aujourd_hui`` aussi, avec la raison, jamais un âge négatif ni ramené à zéro."""
    if aujourd_hui is None:
        return {"jours": None, "raison": "aujourd_hui non fourni : M8 n'a pas d'horloge"}
    jours = age_en_jours(date_reference, aujourd_hui)
    if jours is None:
        return {"jours": None, "aujourd_hui": aujourd_hui, "raison": "la date de référence du constat est illisible"}
    if jours < 0:
        return {
            "jours": None, "aujourd_hui": aujourd_hui,
            "raison": f"la date de référence du constat ({date_reference}) est postérieure à aujourd_hui",
        }
    return {"jours": jours, "aujourd_hui": aujourd_hui}


# ---------------------------------------------------------------------------
# La section de la vue exécutive
# ---------------------------------------------------------------------------
def _ajouter_manque(manques: list[dict[str, str]], manque: dict[str, str]) -> None:
    if manque not in manques:
        manques.append(dict(manque))


def _listes(valeur: Any) -> list[Any]:
    return list(valeur) if isinstance(valeur, list) else []


def _nommees(composantes: list[Any]) -> list[dict[str, Any]]:
    return [c for c in composantes if isinstance(c, dict) and isinstance(c.get("id"), str)]


def _manques(fait: dict[str, Any]) -> list[str]:
    """Ce que M5 dit qu'il manque, une entrée « composante : code » par manque (la forme compacte que M5 emploie luimême
    dans sa trace) : une composante qui manque pour deux raisons donne deux entrées, rien n'est fusionné."""
    return [f"{m.get('composante')} : {m.get('code')}" for m in _listes(fait.get("manque")) if isinstance(m, dict)]


def _montants(composantes: list[Any]) -> dict[str, Any]:
    """``id`` -> montant en texte, dans l'ordre de M5 (le solde, puis les six obligations). ``None`` : M5 n'a pas pu
    chiffrer cette composante (jamais zéro) ; son statut se lit là, car M5 ne rend un montant que pour une composante
    « calculée » (le catalogue le verrouille)."""
    return {c["id"]: c.get("montant_cad") for c in _nommees(composantes)}


def _planchers(composantes: list[Any]) -> dict[str, Any]:
    """``id`` -> plancher en texte, pour les seules composantes non calculées dont M5 connaît un plancher."""
    return {c["id"]: c["plancher_cad"] for c in _nommees(composantes) if c.get("plancher_cad") is not None}


def _projection(fait: dict[str, Any]) -> dict[str, Any]:
    """L'essentiel du constat, valeur pour valeur, dans l'ordre de la définition (le solde, puis les six obligations).
    Rien n'est calculé, arrondi ni réécrit : chaque texte est celui de M5."""
    composantes = [fait.get("solde"), *_listes(fait.get("composantes"))]
    projection = {
        "sequence": fait.get("sequence"), "date_reference": fait.get("date_reference"), "statut": fait.get("statut"),
        "cash_libre_cad": fait.get("cash_libre_cad"), "au_plus_cad": fait.get("au_plus_cad"),
        "en_deficit": fait.get("en_deficit"), "lecture": fait.get("lecture"),
        "composantes": _montants(composantes),
    }
    planchers = _planchers(composantes)
    if planchers:
        projection["planchers_cad"] = planchers
    projection["manque"] = _manques(fait)
    projection["reserves"] = _listes(fait.get("reserves"))
    projection["mention"] = fait.get("mention")
    return projection


def _raison_non_calculable(fait: dict[str, Any]) -> str:
    return (
        f"M5 a constaté le cash libre « non calculable » le {fait.get('date_reference')} : "
        "voir cash_libre.constat.manque"
    )


def section(faits: list[dict[str, Any]], aujourd_hui: str | None, manques: list[dict[str, str]]) -> dict[str, Any]:
    """Section « cash libre » de la vue exécutive : le DERNIER constat que M5 a publié, tel quel, avec son âge, ou
    « manque » si M8 n'en a reçu aucun. Un constat qui n'est pas « calculé » (M5 dit « non calculable ») ajoute un
    manque nommé, dit une fois, avec les codes de M5 : jamais un zéro, jamais un cash libre inventé."""
    courant = constat_courant(faits)
    if courant is None:
        _ajouter_manque(manques, {"champ": "cash_libre", "source": SOURCE, "raison": _RAISON_MANQUE})
        return {"source": SOURCE, "statut": "manque", "manque": ["cash_libre"], "a_lire": _A_LIRE_SANS_CONSTAT}
    if courant.get("statut") != _STATUT_CALCULE:
        _ajouter_manque(manques, {"champ": "cash_libre", "source": SOURCE, "raison": _raison_non_calculable(courant)})
    return {
        "source": SOURCE, "statut": "lu",
        "n_constats_recus": nombre_de_constats(faits),
        "constat": _projection(courant),
        "age": age(courant.get("date_reference"), aujourd_hui),
        "non_repris": _NON_REPRIS, "a_lire": _A_LIRE_AVEC_CONSTAT,
    }


def reduire(section_lue: dict[str, Any]) -> bool:
    """Dernier recours de la borne de sortie du socle, quand il ne reste plus aucune liste à raccourcir : retire la
    décomposition du constat (les montants par composante et leurs planchers), la COMPTE (``composantes_omises``) et le
    dit (``non_repris``). Ne touche jamais aux montants du constat, à son statut, à ce qui manque, aux réserves ni à la
    mention. Rend faux quand il n'y a plus rien à retirer (section « manque », ou décomposition déjà retirée)."""
    constat = section_lue.get("constat")
    if section_lue.get("statut") != "lu" or not isinstance(constat, dict) or "composantes" not in constat:
        return False
    constat["composantes_omises"] = len(constat.pop("composantes"))
    constat.pop("planchers_cad", None)
    section_lue["non_repris"] = _NON_REPRIS_SANS_COMPOSANTES
    return True
