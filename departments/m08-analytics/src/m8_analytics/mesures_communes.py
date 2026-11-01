"""Petits outils communs aux modules de mesures interdépartements (``mesures_interdepartements``, ``mesures_constats``).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. Les helpers que les deux modules partagent : la forme
d'un
« manque », d'un résultat non calculable, l'empreinte des faits utilisés (indépendante de l'ordre de livraison),
l'unicité
par identifiant, la couverture partielle. Une seule définition, jamais deux copies qui divergent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from . import encodage, entonnoir

_CITES = 3
# Canal de dépense (M7 `depenses_marketing_constatees`) -> source de signaux de M7 qui dit sa fraîcheur.
SOURCE_DU_CANAL = {"google_ads": "google_ads", "meta": "meta_ads"}
_PLUS_ANCIEN = datetime.min.replace(tzinfo=UTC)

Resultat = tuple[str | None, dict[str, Any], list[dict[str, str]], str | None, dict[str, Any] | None, int | None]


def manque(champ: str, source: str, raison: str) -> dict[str, str]:
    return {"champ": champ, "source": source, "raison": raison}


def non_calculable(
    manque: list[dict[str, str]], entrees: dict[str, Any] | None = None, instant: str | None = None
) -> Resultat:
    return None, entrees or {}, manque, instant, None, None


def empreinte_faits(faits: list[dict[str, Any]]) -> str:
    """Empreinte des faits utilisés, indépendante de l'ordre de livraison : chaque fait est mis en forme canonique,
    puis les
    formes sont triées."""
    return encodage.empreinte(sorted(encodage.encoder_canonique(fait) for fait in faits))


def de_type(faits: list[dict[str, Any]], type_entree: str) -> list[dict[str, Any]]:
    return [fait for fait in faits if fait.get("type_entree") == type_entree]


def uniques(faits: list[dict[str, Any]], cle: str) -> list[dict[str, Any]]:
    """Le premier fait de chaque valeur de ``cle`` (une relivraison n'ajoute rien) ; un fait sans identifiant lisible
    n'est
    pas un fait."""
    vus: set[str] = set()
    uniques = []
    for fait in faits:
        identifiant = fait.get(cle)
        if isinstance(identifiant, str) and identifiant and identifiant not in vus:
            vus.add(identifiant)
            uniques.append(fait)
    return uniques


def plus_recent(instants: list[Any]) -> str | None:
    lus = [(entonnoir.instant_lu(texte), texte) for texte in instants]
    lisibles = [(instant, texte) for instant, texte in lus if instant is not None]
    return max(lisibles, key=lambda paire: paire[0])[1] if lisibles else None


def cites(identifiants: list[str]) -> str:
    cites = ", ".join(identifiants[:_CITES])
    reste = len(identifiants) - _CITES
    return f"{cites} et {reste} autre(s)" if reste > 0 else cites


def partielle(couverts: int, attendus: int, raison: str) -> dict[str, Any]:
    return {
        "etat": "partielle",
        "couverts": couverts,
        "attendus": attendus,
        "manquants": attendus - couverts,
        "raison": raison,
    }


def jour(texte: Any) -> date | None:
    if not isinstance(texte, str) or len(texte) != 10:
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


def fenetre_source_s(canaux: set[str], signaux: list[dict[str, Any]]) -> tuple[int | None, list[str]]:
    """La fenêtre (secondes) que M7 déclare pour les sources publicitaires des canaux présents : la plus stricte,
    d'après
    la dernière lecture de chaque source. Les canaux dont M7 n'a donné aucun signal sont dits, jamais devinés."""
    derniers: dict[str, tuple[Any, dict[str, Any]]] = {}
    for signal in signaux:
        instant = entonnoir.instant_lu(signal.get("derniere_lecture_reussie_le"))
        if instant is None or signal.get("fictif") is True:
            continue
        actuel = derniers.get(signal.get("source"))
        if actuel is None or instant >= actuel[0]:
            derniers[signal.get("source")] = (instant, signal)
    fenetres = []
    sans_fenetre = []
    for canal in sorted(canaux):
        signal = derniers.get(SOURCE_DU_CANAL.get(canal, ""))
        heures = signal[1].get("fraicheur_fenetre_h") if signal is not None else None
        if type(heures) is int and heures >= 1:
            fenetres.append(heures * 3600)
        else:
            sans_fenetre.append(canal)
    return (min(fenetres) if fenetres else None), sans_fenetre


def ordre_publication(fait: dict[str, Any], indice: int) -> tuple[datetime, int]:
    """Le rang d'un fait parmi ses versions : l'instant de PUBLICATION donné par le bus (`publie_le`), puis l'ordre de
    réception pour départager. L'ordre de livraison du bus n'est pas garanti ; `publie_le` l'est."""
    return entonnoir.instant_lu(fait.get("publie_le")) or _PLUS_ANCIEN, indice


def dernier_par_publication(faits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le fait le plus récemment PUBLIÉ de la liste (`publie_le`, puis l'ordre de réception), ``None`` si vide."""
    if not faits:
        return None
    indice = max(range(len(faits)), key=lambda i: ordre_publication(faits[i], i))
    return faits[indice]


__all__ = [
    "SOURCE_DU_CANAL",
    "Resultat",
    "cites",
    "de_type",
    "dernier_par_publication",
    "empreinte_faits",
    "fenetre_source_s",
    "jour",
    "manque",
    "non_calculable",
    "ordre_publication",
    "partielle",
    "plus_recent",
    "uniques",
]
