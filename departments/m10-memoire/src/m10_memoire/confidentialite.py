"""Confidentialité des éléments d'un paquet de contexte (PLAN T3.3-suite-b, ADR-0010 décisions 5 et 6).

Les sept niveaux de la définition produit (§7 M10) sont la taxonomie canonique. Un paquet de contexte
part vers le prompt d'un agent : il ne doit contenir que ce que CET agent a besoin de savoir, jamais tout
ce que M10 sait. La règle, écrite ici et épinglée par ``tests/test_confidentialite.py`` :

1. Un élément non marqué est ``INTERNAL`` : c'est ce que tout le registre porte avant ce marquage. Un
   marquage inconnu est traité comme ``LEGAL_LOCKED`` (le plus fermé), jamais comme ``INTERNAL``.
2. ``SENSITIVE``, ``FINANCIAL``, ``SECRET_REF`` et ``LEGAL_LOCKED`` ne sortent JAMAIS dans un paquet, pour
   aucun agent : ils se lisent dans leur département, avec ses outils et ses rôles.
3. ``CLIENT_PRIVATE`` (donnée personnelle du client, Loi 25) ne sort que dans les couches et vers les agents
   de ``AGENTS_CLIENT_PRIVE_PAR_COUCHE``. Absent de la table, ou agent inconnu : il ne sort pas.
4. Sans agent nommé, la vue est la plus restrictive : ``PUBLIC_INTERNAL`` et ``INTERNAL`` seulement.

Ce qui est retenu n'est jamais listé : le paquet dit seulement COMBIEN d'éléments ont été retenus
(``confidentialite.nb_retenus``), pour que l'agent sache qu'il travaille avec une vue partielle sans rien
apprendre du contenu.

Qui reçoit ``CLIENT_PRIVATE``. Seuls les deux départements qui tiennent la relation avec le client dans
l'affaire : M1 (conversation) et M2 (CRM), et seulement dans les couches qui parlent de l'affaire (faits
durables, événements récents). Les règles de l'entreprise et les signaux critiques ne portent jamais de
donnée du client. C'est le choix par défaut, à élargir seulement par un changement de cette table, de ses
tests et de l'ADR-0010 : un agent de plus, ou une couche de plus, est une décision de confidentialité.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from typing import Any

NIVEAU_PUBLIC_INTERNE = "PUBLIC_INTERNAL"
NIVEAU_INTERNE = "INTERNAL"
NIVEAU_SENSIBLE = "SENSITIVE"
NIVEAU_FINANCIER = "FINANCIAL"
NIVEAU_CLIENT_PRIVE = "CLIENT_PRIVATE"
NIVEAU_REFERENCE_SECRETE = "SECRET_REF"
NIVEAU_VERROUILLE_LEGAL = "LEGAL_LOCKED"

REGLE_VERSION = "v1"

REJ_CONFIDENTIALITE_NIVEAU_INCONNU = "REJ-CONFIDENTIALITE-NIVEAU-INCONNU"
REJ_CONFIDENTIALITE_AGENT_INVALIDE = "REJ-CONFIDENTIALITE-AGENT-INVALIDE"

_NIVEAUX_CONNUS = frozenset(
    {
        NIVEAU_PUBLIC_INTERNE,
        NIVEAU_INTERNE,
        NIVEAU_SENSIBLE,
        NIVEAU_FINANCIER,
        NIVEAU_CLIENT_PRIVE,
        NIVEAU_REFERENCE_SECRETE,
        NIVEAU_VERROUILLE_LEGAL,
    }
)
_NIVEAUX_DE_BASE = frozenset({NIVEAU_PUBLIC_INTERNE, NIVEAU_INTERNE})
# Même forme qu'un identifiant de département (`faits_candidats.py`, `department.yaml`).
_AGENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]*$")

# Couche du paquet -> agents (départements) qui y reçoivent des éléments CLIENT_PRIVATE. Les noms de
# couche sont ceux de `paquets.py` ; une couche absente de cette table n'en reçoit aucun.
AGENTS_CLIENT_PRIVE_PAR_COUCHE: dict[str, frozenset[str]] = {
    "regles_entreprise": frozenset(),
    "faits_affaire": frozenset({"m01-front-office", "m02-revenue-crm"}),
    "evenements_recents": frozenset({"m01-front-office", "m02-revenue-crm"}),
    "signaux_non_resolus": frozenset(),
}


def niveaux_connus() -> frozenset[str]:
    return _NIVEAUX_CONNUS


def niveau_connu(niveau: Any) -> bool:
    return isinstance(niveau, str) and niveau in _NIVEAUX_CONNUS


def agent_valide(agent: Any) -> bool:
    return isinstance(agent, str) and _AGENT.fullmatch(agent) is not None


def niveau_de(maillon: dict[str, Any]) -> str:
    """Niveau EFFECTIF d'un maillon : ``INTERNAL`` sans marquage, le marquage s'il est connu, sinon le plus
    fermé (jamais une valeur inventée plus ouverte que ce que le maillon dit)."""
    marque = maillon.get("confidentialite")
    if marque is None:
        return NIVEAU_INTERNE
    return marque if niveau_connu(marque) else NIVEAU_VERROUILLE_LEGAL


def niveaux_admis(couche: str, agent: str | None) -> frozenset[str]:
    """Niveaux qu'un paquet peut porter dans cette couche pour cet agent (règle 2 à 4 du module)."""
    if agent is not None and agent in AGENTS_CLIENT_PRIVE_PAR_COUCHE.get(couche, frozenset()):
        return _NIVEAUX_DE_BASE | {NIVEAU_CLIENT_PRIVE}
    return _NIVEAUX_DE_BASE


def filtrer(
    couche: str, agent: str | None, candidats: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """``(retenus_pour_l_agent, nb_retenus)`` : chaque candidat porte son niveau dans ``confidentialite``.

    Un candidat dont le niveau n'est pas admis n'est PAS rendu, ni son contenu, ni son identifiant : il est
    seulement compté.
    """
    admis = niveaux_admis(couche, agent)
    gardes = [fait for fait in candidats if fait["confidentialite"] in admis]
    return gardes, len(candidats) - len(gardes)
