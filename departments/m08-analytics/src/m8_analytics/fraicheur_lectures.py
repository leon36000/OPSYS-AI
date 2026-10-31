"""Fraîcheur attendue d'une LECTURE de M8, déclarée par le propriétaire (M8), pour les consommateurs (M9).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. M8 ne juge jamais qu'une lecture est « périmée » : il
ne fait que DIRE, quand le propriétaire l'a déclarée, la fenêtre (en secondes) dans laquelle il attend le dernier fait
qu'une lecture porte. C'est le consommateur (M9) qui compare cette fenêtre à l'âge qu'il calcule lui-même.

Règles :

* ``fraicheur_attendue_s`` est OPTIONNEL et ABSENT par défaut (``department.yaml``,
  ``configuration.fraicheur_lectures_s``, vide à dessein) : aucune fenêtre n'est inventée, aucune n'est dérivée d'une
  autre (ni des ``fraicheur_attendue_jours`` du registre de métriques, qui datent une VALEUR de métrique, ni du
  minimum de plusieurs métriques). Sans déclaration, la réponse de la lecture est exactement celle d'avant ce module :
  aucune clé de plus.
* Une valeur est un entier strictement positif, au plus ``BORNE_MAX_S`` (3650 jours, la borne que M9 applique déjà à
  ses propres péremptions). Un booléen, un flottant, un texte, zéro, un négatif ou un dépassement est REFUSÉ : la
  fenêtre n'est pas exposée et le refus est dit (``fraicheur_attendue_refusee``), jamais corrigé en silence ni remplacé
  par un zéro ou une valeur par défaut.
* Seules les lectures de ``LECTURES_DECLARABLES`` portent un instant métier que le consommateur peut dater ; une autre
  clé de la configuration est dite (``fraicheur_attendue_ignorees``), pas ignorée en silence : le propriétaire croirait
  sa fenêtre en place.
* ``version_definition_fraicheur`` est l'empreinte (SHA-256 de la forme canonique, comme ``version_definition`` des
  métriques) de la déclaration ``{lecture, fraicheur_attendue_s}`` : elle change si et seulement si la lecture ou la
  fenêtre change, et se recalcule à l'identique. Elle ne touche aucune ``version_definition`` de métrique.
"""

from __future__ import annotations

from typing import Any

from . import encodage

CLE_CONFIGURATION = "fraicheur_lectures_s"
SOURCE = f"department.yaml de m08-analytics, configuration.{CLE_CONFIGURATION}"
BORNE_MAX_S = 3650 * 86400  # 3650 jours : la borne des péremptions de M9 (outils_tissu, perime_apres_jours)

LECTURE_VUE_EXECUTIVE = "m8_lire_vue_executive"
LECTURE_MESURES_CHANTIER = "m8_lire_mesures_chantier"
# Les lectures de M8 que M9 capture ET dont la réponse déclare un instant métier à dater
# (catalogue_producteurs : ``entonnoir.sources[*].dernier_fait_le``, ``horodatage_completion``). Allow-list technique
# (frozenset, comme ``dictionnaire._DEVISES_AUTORISEES``) : des noms d'outils, pas un énuméré de domaine.
LECTURES_DECLARABLES = frozenset({LECTURE_VUE_EXECUTIVE, LECTURE_MESURES_CHANTIER})

CLE_FENETRE = "fraicheur_attendue_s"
CLE_VERSION = "version_definition_fraicheur"
CLE_REFUS = "fraicheur_attendue_refusee"
CLE_IGNOREES = "fraicheur_attendue_ignorees"
CLES_REPONSE = frozenset({CLE_FENETRE, CLE_VERSION, CLE_REFUS, CLE_IGNOREES})


def raison_invalide(brut: Any) -> str | None:
    """``None`` si ``brut`` est une fenêtre valide, sinon la raison du refus (jamais de correction)."""
    if isinstance(brut, bool) or not isinstance(brut, int):
        return "un entier de secondes est attendu (ni booléen, ni nombre à virgule, ni texte)"
    if brut <= 0:
        return "un entier strictement positif est attendu (zéro et négatif refusés)"
    if brut > BORNE_MAX_S:
        return f"au plus {BORNE_MAX_S} secondes (3650 jours)"
    return None


def version_definition(lecture: str, secondes: int) -> str:
    """Empreinte déterministe de la déclaration d'une lecture ; la même entrée donne la même empreinte."""
    return encodage.empreinte({"lecture": lecture, CLE_FENETRE: secondes})


def _refus(raison: str) -> dict[str, Any]:
    return {CLE_REFUS: {"raison": raison, "source": SOURCE}}


def ignorees(configuration: Any) -> list[str]:
    """Clés déclarées qui ne sont pas une lecture déclarable (faute de frappe, lecture sans instant à dater)."""
    if not isinstance(configuration, dict):
        return []
    return sorted(str(cle) for cle in configuration if cle not in LECTURES_DECLARABLES)


def declarer(lecture: str, configuration: Any) -> dict[str, Any]:
    """Les clés à ajouter à la réponse de ``lecture`` : ``{}`` tant que rien n'est déclaré (réponse inchangée),
    ``{fraicheur_attendue_s, version_definition_fraicheur}`` pour une fenêtre valide, ``{fraicheur_attendue_refusee}``
    pour une déclaration illisible ou invalide (aucune fenêtre n'est alors exposée). ``fraicheur_attendue_ignorees``
    s'y ajoute quand la configuration porte des clés qui ne surveillent aucune lecture."""
    if lecture not in LECTURES_DECLARABLES:
        raise ValueError(f"lecture non déclarable : {lecture!r}")
    if configuration is None:
        return {}
    if not isinstance(configuration, dict):
        return _refus("un dictionnaire {lecture: secondes} est attendu")
    reponse: dict[str, Any]
    if lecture not in configuration:
        reponse = {}
    else:
        brut = configuration[lecture]
        raison = raison_invalide(brut)
        if raison is not None:
            reponse = _refus(raison)
        else:
            reponse = {CLE_FENETRE: brut, CLE_VERSION: version_definition(lecture, brut)}
    inutiles = ignorees(configuration)
    if inutiles:
        reponse[CLE_IGNOREES] = inutiles
    return reponse


__all__ = [
    "BORNE_MAX_S",
    "CLES_REPONSE",
    "CLE_CONFIGURATION",
    "LECTURES_DECLARABLES",
    "LECTURE_MESURES_CHANTIER",
    "LECTURE_VUE_EXECUTIVE",
    "declarer",
    "ignorees",
    "raison_invalide",
    "version_definition",
]
