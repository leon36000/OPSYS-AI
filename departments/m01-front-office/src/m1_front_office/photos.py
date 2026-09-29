"""Garde Loi 25 « photos » de M1 (PLAN T4.4) : demander des photos à un client, c'est en collecter ; tant que la
politique `POLITIQUE-photos-non-contractuelles.md` n'est pas validée par Nathan ou un juriste (T3), M1 ne propose
JAMAIS de demande de photos, même quand le profil d'entreprise en déclare une pour le service.

Même règle que M3 (`m3_estimation.politique_photos`, un département ne lit pas le code d'un autre) : le document porte
une ligne EXACTE `STATUT_VALIDATION: valide` pour ouvrir la garde ; toute autre valeur (`proposition`, l'état de
livraison), un marqueur absent ou dupliqué, un fichier illisible : fermée. Jamais une valeur par défaut qui ouvrirait
la demande par erreur. Un test du socle (`tests/test_politique_photos_derive.py`) confronte cette lecture à celle de
M3 sur les mêmes textes, pour qu'elles ne divergent pas.

Module pur : le TEXTE de la politique est fourni par l'appelant (`outils.py` lit le fichier réel). Aucune horloge.
"""

from __future__ import annotations

import re
from typing import Any

from . import verdicts

STATUT_VALIDE = "valide"
_MOTIF_STATUT = re.compile(r"^STATUT_VALIDATION:\s*(\S+)\s*$", re.MULTILINE)


def lire_statut_validation(texte_politique: Any) -> str | None:
    """Le marqueur `STATUT_VALIDATION: <valeur>` du texte, ou `None` s'il est absent, dupliqué, ou si l'entrée n'est
    pas une chaîne : fail-closed sur toute forme inattendue."""
    if not isinstance(texte_politique, str):
        return None
    correspondances = _MOTIF_STATUT.findall(texte_politique)
    return correspondances[0] if len(correspondances) == 1 else None


def politique_validee(texte_politique: Any) -> bool:
    """Vrai SEULEMENT si le marqueur vaut exactement `valide`."""
    return lire_statut_validation(texte_politique) == STATUT_VALIDE


def verifier_demande_autorisee(texte_politique: Any) -> dict[str, Any] | None:
    """`None` (demande de photos AUTORISÉE) si la politique est validée, sinon le verdict
    `REJ-PHOTO-POLITIQUE-NON-VALIDEE` qui dit quoi faire."""
    if politique_validee(texte_politique):
        return None
    statut = lire_statut_validation(texte_politique) or "absent"
    return verdicts.construire_verdict(
        "REJ-PHOTO-POLITIQUE-NON-VALIDEE",
        detail=(
            f"statut de validation actuel : {statut!r} ; la politique "
            "docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md doit être marquée 'valide' par "
            "Nathan ou un juriste avant toute demande de photos à un client (Loi 25, fermée par défaut)"
        ),
    )
