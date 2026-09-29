"""Faits candidats à la consolidation (PLAN T3.3-suite, POSTFLIGHT du moteur de contexte du core).

Après un tour d'agent de département, OPSYS-CORE (``afterTurn`` du moteur de contexte) transmet à M10
ce que les OUTILS ont fait pendant le tour : « tel outil, appelé pour telle affaire, a réussi ou a
été refusé, avec tel code ». Jamais ce que le modèle a écrit : un texte de modèle n'est pas une source
(AGENTS.md, « le code calcule, le LLM orchestre »). Le core lit ces trois éléments dans la réponse
structurée de l'outil, sans jamais les recomposer.

Un fait candidat est un maillon ``fait_candidat`` du registre Affaires, en statut ``candidat`` :
- ce n'est PAS une vérité. Il n'entre dans aucune des quatre couches du paquet de contexte
  (``paquets.py``) et la consolidation nocturne (``consolidation.py``) ne le lit pas encore : il
  attend une phase ultérieure qui le valide ;
- il porte sa provenance complète : affaire, département source, clé de dépôt, outil, résultat, code ;
- il est append-only comme tout le registre : aucun maillon existant n'est modifié.

Idempotent par ``cle`` (clé de dépôt calculée par le core, stable pour un même appel d'outil) :
rejouer un dépôt ne crée rien de plus. Une clé réutilisée pour une autre affaire ou avec un contenu
différent est un conflit nommé, jamais écrasé. Un lot est validé EN ENTIER avant la première
écriture : un seul élément invalide refuse tout le lot.

``horodatage`` est TOUJOURS fourni par l'appelant (aucune horloge n'est lue ici,
``conformite.py::HORLOGE_INTERNE`` le détecterait).

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

TYPE_ENTREE_FAIT_CANDIDAT = "fait_candidat"
STATUT_FAIT_CANDIDAT = "candidat"
NB_FAITS_MAX_PAR_DEPOT = 20

CHAMPS_FAIT_CANDIDAT = frozenset({"cle", "outil", "resultat", "code"})

REJ_CANDIDAT_AFFAIRE_INVALIDE = "REJ-CANDIDAT-AFFAIRE-INVALIDE"
REJ_CANDIDAT_DEPARTEMENT_INVALIDE = "REJ-CANDIDAT-DEPARTEMENT-INVALIDE"
REJ_CANDIDAT_LISTE_INVALIDE = "REJ-CANDIDAT-LISTE-INVALIDE"
REJ_CANDIDAT_HORODATAGE_INVALIDE = "REJ-CANDIDAT-HORODATAGE-INVALIDE"
REJ_CANDIDAT_FAIT_INVALIDE = "REJ-CANDIDAT-FAIT-INVALIDE"
REJ_CANDIDAT_CLE_EN_DOUBLE = "REJ-CANDIDAT-CLE-EN-DOUBLE"
REJ_CANDIDAT_CLE_DEJA_UTILISEE = "REJ-CANDIDAT-CLE-DEJA-UTILISEE"

# Formes fermées : ce qui entre au registre ne peut pas porter de texte libre.
_AFFAIRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]*$")
_CLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OUTIL_DEPARTEMENT = re.compile(r"^m(10|[1-9])_[a-z][a-z0-9_]{1,60}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_RESULTATS = ("ok", "refus")


def _texte_conforme(valeur: Any, forme: re.Pattern[str]) -> bool:
    return isinstance(valeur, str) and forme.fullmatch(valeur) is not None


def _horodatage_valide(horodatage: Any) -> bool:
    if not isinstance(horodatage, str) or not horodatage:
        return False
    try:
        instant = datetime.fromisoformat(horodatage)
    except ValueError:
        return False
    return instant.tzinfo is not None


def _fait_valide(fait: Any) -> bool:
    if not isinstance(fait, dict) or set(fait) != CHAMPS_FAIT_CANDIDAT:
        return False
    code = fait["code"]
    return (
        _texte_conforme(fait["cle"], _CLE)
        and _texte_conforme(fait["outil"], _OUTIL_DEPARTEMENT)
        and fait["resultat"] in _RESULTATS
        and (code is None or _texte_conforme(code, _CODE))
    )


def _valider_depot(affaire_id: Any, departement_source: Any, faits: Any, horodatage: Any) -> str | None:
    """Code du premier défaut, ou ``None`` si le lot est entièrement valide."""
    if not _texte_conforme(affaire_id, _AFFAIRE):
        return REJ_CANDIDAT_AFFAIRE_INVALIDE
    if not _texte_conforme(departement_source, _DEPARTEMENT):
        return REJ_CANDIDAT_DEPARTEMENT_INVALIDE
    if not isinstance(faits, list) or not 1 <= len(faits) <= NB_FAITS_MAX_PAR_DEPOT:
        return REJ_CANDIDAT_LISTE_INVALIDE
    if not _horodatage_valide(horodatage):
        return REJ_CANDIDAT_HORODATAGE_INVALIDE
    if not all(_fait_valide(fait) for fait in faits):
        return REJ_CANDIDAT_FAIT_INVALIDE
    cles = [fait["cle"] for fait in faits]
    if len(set(cles)) != len(cles):
        return REJ_CANDIDAT_CLE_EN_DOUBLE
    return None


def _contenu(affaire_id: str, departement_source: str, fait: dict[str, Any]) -> tuple[Any, ...]:
    return (affaire_id, departement_source, fait["outil"], fait["resultat"], fait["code"])


def deposer_faits_candidats(
    affaire_id: str,
    departement_source: str,
    faits: list[dict[str, Any]],
    horodatage: str,
    registre_affaires: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Dépose un lot de faits candidats ; rend ``(resultat, None)`` ou ``(None, verdict)``.

    ``resultat`` : ``{"ecrits": n, "deja_deposes": m, "lignes": [ligne_id, ...]}``. Le lot est
    validé et confronté aux dépôts existants AVANT toute écriture : un refus n'écrit rien.
    """
    verdict = _valider_depot(affaire_id, departement_source, faits, horodatage)
    if verdict is not None:
        return None, verdict

    existants = {
        maillon["cle_depot"]: maillon
        for maillon in registre_affaires.lire()
        if maillon.get("type_entree") == TYPE_ENTREE_FAIT_CANDIDAT
    }
    nouveaux: list[dict[str, Any]] = []
    deja_deposes = 0
    for fait in faits:
        precedent = existants.get(fait["cle"])
        if precedent is None:
            nouveaux.append(fait)
            continue
        contenu_precedent = (
            precedent["affaire_id"],
            precedent["departement_source"],
            precedent["outil"],
            precedent["resultat"],
            precedent["code"],
        )
        if contenu_precedent != _contenu(affaire_id, departement_source, fait):
            return None, REJ_CANDIDAT_CLE_DEJA_UTILISEE
        deja_deposes += 1

    lignes = [
        registre_affaires.ajouter(
            {
                "type_entree": TYPE_ENTREE_FAIT_CANDIDAT,
                "horodatage": horodatage,
                "affaire_id": affaire_id,
                "departement_source": departement_source,
                "cle_depot": fait["cle"],
                "outil": fait["outil"],
                "resultat": fait["resultat"],
                "code": fait["code"],
                "statut": STATUT_FAIT_CANDIDAT,
            }
        )
        for fait in nouveaux
    ]
    return {"ecrits": len(lignes), "deja_deposes": deja_deposes, "lignes": lignes}, None
