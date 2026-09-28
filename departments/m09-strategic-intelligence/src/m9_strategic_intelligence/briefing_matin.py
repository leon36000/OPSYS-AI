"""Briefing du matin — assemblage déterministe, sourcé (PLAN T3.2, DEFINITION-PRODUIT.md M9.5).

Module PUR (ADR-0009) : aucun import d'``opsys``. ``assembler_briefing_matin`` compose, pour un
instant de référence FOURNI (``maintenant``, RFC 3339 — jamais l'horloge : garde HORLOGE_INTERNE
de ``conformite.py``), quatre sections ORDONNÉES à partir de candidats DÉJÀ LUS par l'appelant
(``outils.py``, seul point de contact avec le socle, cf. ``docs/architecture/DEPARTEMENTS.md``) :

1. ``decisions_en_attente`` — la file du propriétaire (``opsys.approbations.file_proprietaire``),
   passée quasi telle quelle : c'est la forme que l'écran mobile admin ``strategy-decisions``
   (T1.4, DEFINITION-PRODUIT.md §9.8) consommera directement, jamais reformatée ici. Aucun filtre
   de date : la file est toujours « ce qui est actuellement en attente ».
2. ``alertes_m8`` — alertes proposées par M8 et reçues du bus (``m8.alerte_proposee``,
   ``outils._recevoir_alerte_proposee``), filtrées au JOUR de ``maintenant`` (boucle M8 → M9 des
   preuves, ADR-0009 §3 : M9 ne lit jamais le registre M8 directement).
3. ``faits_veille`` — derniers faits du bus déjà consolidés par M9 (registre de snapshots,
   alimenté en second ordre par les preuves de M8), filtrés à la VEILLE de ``maintenant``.
4. ``manques_pour_conclure`` — constat déterministe des sections 1 à 3 vides : jamais une
   interprétation, seulement le fait vérifiable qu'une source n'a rien rapporté pour la période
   considérée (P2 DEFINITION-PRODUIT.md : « le système ose dire donnée pas fiable »).

Chaque section porte ``items`` (jamais fabriqué : une section sans donnée reste ``[]``, jamais
remplie) et ``vide`` (bool). Aucun texte libre n'est rédigé ici et aucun chiffre n'y est recalculé
— v1 est un gabarit déterministe, pas une rédaction (PLAN T3.2, point 3).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import encodage

__all__ = ["ORDRE_SECTIONS", "assembler_briefing_matin"]

# Forme attendue de chaque candidat en entrée. Copie locale (jamais un import inter-département,
# DA-M9-04) des champs garantis par leur producteur respectif :
# - décision : `opsys.approbations.CHAMPS_ATTENTE` + `departement`, ajouté par `file_proprietaire`.
# - alerte : propriétés requises du catalogue `opsys.evenement/v1/m8.alerte_proposee`.
# - fait : `contrats.CHAMPS_SNAPSHOT_MODULE` (module_source, horodatage, valeurs) — le maillon du
#   registre M9 porte aussi `index`/`hash_maillon`, non requis ici mais jamais retiré (traçabilité).
_CHAMPS_DECISION = ("type", "id", "resume", "niveau", "depuis", "action_proposee", "departement")
_CHAMPS_ALERTE = (
    "evenement_id", "metric_id", "type_alerte", "quoi", "a_qui", "pourquoi", "preuve", "source",
    "horodatage_reference",
)
_CHAMPS_FAIT = ("module_source", "horodatage", "valeurs")

ORDRE_SECTIONS = ("decisions_en_attente", "alertes_m8", "faits_veille", "manques_pour_conclure")


def _analyser_horodatage(horodatage: str) -> datetime:
    """Parse un horodatage ISO-8601, fuseau compris (copié-adapté de
    ``etat_consolide.py::_analyser_horodatage`` — même règle, patron M8 : sans fuseau explicite,
    traité comme UTC, jamais deviné autrement)."""
    valeur = horodatage[:-1] + "+00:00" if horodatage.endswith("Z") else horodatage
    analyse = datetime.fromisoformat(valeur)
    if analyse.tzinfo is None:
        analyse = analyse.replace(tzinfo=UTC)
    return analyse


def _jour_de(horodatage: str) -> date:
    """Date calendaire d'un horodatage, dans le fuseau où il est exprimé (aucune conversion vers
    un fuseau d'entreprise supposé — non déclaré ailleurs dans ce dépôt)."""
    return _analyser_horodatage(horodatage).date()


def _valider_champs(item: Any, champs: tuple[str, ...], contexte: str) -> dict[str, Any]:
    """Fail-closed (AGENTS.md) : un candidat sans les champs attendus est un refus nommé, jamais
    un élément ignoré en silence ni complété par une valeur devinée. Vérifie la PRÉSENCE des
    champs, jamais l'exhaustivité (un candidat peut porter des champs en plus, ex. `index` d'un
    maillon de registre — jamais rejeté pour ça, contrairement à `rapport_strategique.py`)."""
    if not isinstance(item, dict):
        raise ValueError(f"{contexte} : élément invalide, dict attendu, reçu {type(item).__name__}")
    manquants = [champ for champ in champs if champ not in item]
    if manquants:
        raise ValueError(f"{contexte} : champ(s) manquant(s) {manquants} dans {item!r}")
    return item


def assembler_briefing_matin(
    maintenant: str,
    decisions_en_attente: list[dict[str, Any]],
    alertes_m8: list[dict[str, Any]],
    faits_bus: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble le briefing du matin pour ``maintenant`` (RFC 3339, fourni — jamais l'horloge).

    Chaque liste d'entrée est une liste de CANDIDATS déjà lus par l'appelant (``outils.py``) :
    cette fonction ne lit rien elle-même, ne filtre que par date et ne trie que pour la
    reproductibilité — elle n'ingère, n'invente ni ne résume aucun contenu.

    Retourne un dict portant, dans l'ordre de ``ORDRE_SECTIONS`` : ``jour``/``veille`` (dates
    calendaires ISO dérivées de ``maintenant``), ``sections`` (les quatre sections ci-dessus) et
    ``briefing_id`` (empreinte déterministe du contenu assemblé, ``encodage.empreinte``).
    """
    jour = _jour_de(maintenant)
    veille = jour - timedelta(days=1)

    decisions = [_valider_champs(item, _CHAMPS_DECISION, "decisions_en_attente") for item in decisions_en_attente]
    decisions = sorted(decisions, key=lambda item: (item["depuis"], item["id"]))

    alertes = [_valider_champs(item, _CHAMPS_ALERTE, "alertes_m8") for item in alertes_m8]
    alertes = [item for item in alertes if _jour_de(item["horodatage_reference"]) == jour]
    alertes = sorted(alertes, key=lambda item: item["evenement_id"])

    faits = [_valider_champs(item, _CHAMPS_FAIT, "faits_bus") for item in faits_bus]
    faits = [item for item in faits if _jour_de(item["horodatage"]) == veille]
    faits = sorted(faits, key=lambda item: (item["module_source"], item["horodatage"]))

    sections: dict[str, Any] = {
        "decisions_en_attente": {"items": decisions, "vide": not decisions},
        "alertes_m8": {"items": alertes, "vide": not alertes},
        "faits_veille": {"items": faits, "vide": not faits},
    }

    manques: list[dict[str, str]] = []
    if sections["decisions_en_attente"]["vide"]:
        manques.append({
            "section": "decisions_en_attente",
            "constat": "aucune décision en attente dans la file du propriétaire",
            "verifie": "opsys.approbations.file_proprietaire",
        })
    if sections["alertes_m8"]["vide"]:
        manques.append({
            "section": "alertes_m8",
            "constat": f"aucune alerte reçue de M8 (m8.alerte_proposee) pour le {jour.isoformat()}",
            "verifie": "registre m09-strategic-intelligence/alertes_m8",
        })
    if sections["faits_veille"]["vide"]:
        manques.append({
            "section": "faits_veille",
            "constat": f"aucun fait consolidé reçu du bus pour la veille ({veille.isoformat()})",
            "verifie": "registre m09-strategic-intelligence/snapshots",
        })
    sections["manques_pour_conclure"] = {"items": manques, "vide": not manques}

    briefing_id = encodage.empreinte("BRIEFING_MATIN", jour.isoformat(), sections)

    return {
        "type": "BRIEFING_MATIN",
        "jour": jour.isoformat(),
        "veille": veille.isoformat(),
        "ordre_sections": list(ORDRE_SECTIONS),
        "sections": sections,
        "briefing_id": briefing_id,
    }
