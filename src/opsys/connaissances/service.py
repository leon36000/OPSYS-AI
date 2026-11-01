"""Couche d'adaptation des outils : connexion ambiante, horloge, droits de lecture, sortie bornée.

Les outils (communs `opsys_connaissances_*` et `m10_*_connaissance*`) restent minces : ils appellent le service ici.

**Droits de lecture.** Aucun droit nouveau. Un département lit la base de connaissances de :
  - lui-même ;
  - chaque département que son manifeste déclare dans `dependances` (la relation de lecture inter-départements qui
    existe déjà : celui dont il consomme le travail). M7 (qui dépend de M5) lit donc la base de M5 ; M3 ne lit pas
    celle de M7.
Le département appelant est celui que la plateforme fixe (`contexte.DEPARTEMENT_APPELANT`), jamais un argument. Aucune
lecture n'est ouverte à un appareil (`roles_appareil` vide sur tous ces outils). L'administration (M10) lit et écrit
toutes
les bases, mais ne rend, comme tout le monde, que du contenu neutralisé.

**Sortie bornée.** Le répartiteur tronque au-delà de 6 000 caractères et range le reste en artefact : on borne ici, par
résultat entier, pour ne jamais couper une provenance en deux. `omis_budget` dit combien de résultats manquent.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, select

from .. import stockage
from ..contexte import DEPARTEMENT_APPELANT, identite_appelante
from ..departements import Departement
from ..stockage.schema import CONNAISSANCES_BASES
from . import lecture, ports, recherche
from .codes import APPAREIL_FERME, APPELANT_INCONNU, ErreurConnaissances
from .modele import DEPARTEMENT

SORTIE_MAX = 5700
K_DEFAUT = 3
K_MAX_OUTIL = 8


def maintenant() -> dt.datetime:
    """L'horloge du serveur (jamais une date fournie par le modèle). Les tests la remplacent."""
    return dt.datetime.now(dt.UTC)


def connexion() -> Connection:
    refuser_appareil()
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ErreurConnaissances(APPELANT_INCONNU, "aucune transaction de l'instance : appel hors répartiteur refusé")
    return cnx


def refuser_appareil() -> None:
    """Défense en profondeur : ces outils ne sont déclarés à AUCUN rôle d'appareil (le core les refuse déjà) ; si un
    appel
    arrive tout de même avec une identité d'appareil, il est refusé ici (même règle que `opsys_memoire_rechercher`)."""
    if identite_appelante() is not None:
        raise ErreurConnaissances(APPAREIL_FERME, "la base de connaissances n'est pas ouverte aux appareils")


def departement_appelant() -> str:
    ident = DEPARTEMENT_APPELANT.get()
    if not ident or not DEPARTEMENT.fullmatch(ident):
        raise ErreurConnaissances(
            APPELANT_INCONNU, "département appelant inconnu : cet outil passe par le point d'accès MCP d'un "
                              "département")
    return ident


def bases_lisibles(appelant: str, departements: Mapping[str, Departement]) -> tuple[str, ...]:
    """Bases que `appelant` a le droit de lire : la sienne et celles de ses dépendances déclarées."""
    dep = departements.get(appelant)
    if dep is None:
        raise ErreurConnaissances(APPELANT_INCONNU, f"département appelant inconnu : {appelant}")
    return tuple(dict.fromkeys((dep.id, *(d for d in dep.dependances if d in departements))))


def toutes_les_bases(cnx: Connection) -> tuple[str, ...]:
    return tuple(r[0] for r in cnx.execute(select(CONNAISSANCES_BASES.c.departement).order_by(
        CONNAISSANCES_BASES.c.departement)))


def _sans_vides(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        return {k: _sans_vides(v) for k, v in valeur.items() if v is not None}
    if isinstance(valeur, list):
        return [_sans_vides(v) for v in valeur]
    return valeur


def borner(reponse: dict[str, Any], maximum: int = SORTIE_MAX, cle: str = "resultats") -> dict[str, Any]:
    """Retire les valeurs nulles puis des éléments ENTIERS de `cle` (les derniers) jusqu'à tenir sous `maximum`."""
    reponse = _sans_vides(reponse)
    elements = list(reponse.get(cle) or [])
    omis = 0
    while elements and len(json.dumps({**reponse, cle: elements, "omis_budget": omis}, ensure_ascii=False)) > maximum:
        elements.pop()
        omis += 1
    if cle in reponse:
        reponse[cle] = elements
    if omis:
        reponse["omis_budget"] = omis
    if not elements and cle in reponse and reponse.get("statut", "ok") == "ok" and omis:
        # Même le premier élément dépasse : on le dit, on ne le coupe pas en deux.
        reponse["avertissements"] = [*reponse.get("avertissements", []), {
            "code": "SORTIE_TROP_VOLUMINEUSE", "detail": "le premier élément dépasse le budget de sortie ; "
            "demande-le par fragments plus petits (limite 1)"}]
    return reponse


def rechercher_pour(cnx: Connection, *, appelant: str, bases: tuple[str, ...], requete: str, k: int,
                    a_la_date: str | None) -> dict[str, Any]:
    """Recherche hybride pour `appelant` dans `bases`, avec les ports que le registre retient pour `appelant`."""
    if type(k) is not int or not 1 <= k <= K_MAX_OUTIL:
        raise ErreurConnaissances("REJ-CONN-REQUETE-INVALIDE", f"k : entier de 1 à {K_MAX_OUTIL}")
    embeddeur, raison_emb = ports.embeddeur_disponible(cnx, appelant)
    reranker, raison_rer = ports.reranker_disponible(cnx, appelant)
    reponse = recherche.rechercher(
        cnx, requete=requete, departements=bases, maintenant=maintenant(), k=k, a_la_date=a_la_date,
        embeddeur=embeddeur, raison_sans_embeddeur=raison_emb, reranker=reranker, raison_sans_reranker=raison_rer)
    return borner(reponse)


def lire_pour(cnx: Connection, *, version_id: str, bases: tuple[str, ...] | None, publie_seulement: bool,
              decalage: int, limite: int) -> dict[str, Any]:
    reponse = lecture.lire_version(cnx, version_id, bases_lisibles=bases, publie_seulement=publie_seulement,
                                   maintenant=maintenant(), decalage=decalage, limite=limite)
    borne = borner(reponse, cle="fragments")
    if borne.get("omis_budget"):  # la page suivante recommence au premier fragment omis, jamais après un trou
        borne["suivant"] = decalage + len(borne["fragments"])
    return borne
