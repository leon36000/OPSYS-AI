"""Garde Loi 25 « photos » de M3 (PLAN T2.3, `docs/departements/M3-audit.md` §5 point 2 : « tant
qu'elle n'est pas écrite et validée par Nathan (T3), toute collecte réelle de photos en production
expose l'entreprise sans cadre documenté »).

Ce paquet ne lit ni ne stocke AUJOURD'HUI aucun octet d'image — seulement des MÉTADONNÉES
déclarées par l'appelant (résolution, éclairage, angle, référence d'échelle :
``contrats.CHAMPS_PHOTO``, consommées par ``qualite_photos.py``/``hierarchie_echelle.py``),
confirmé par l'audit M3 (§2.7, DA-M3-04) et par DEFINITION-PRODUIT.md §8 (minimisation). Ce module
est donc une garde PRÉVENTIVE pour toute future capacité qui lirait ou stockerait un octet d'image
réel (Phase 2 : SAM2, Grounding DINO, OpenCV — audit M3 §3.1, §4 Plan par phases), pas un correctif
d'un chemin d'exécution existant : AUCUN appel de ce module n'existe encore ailleurs dans
``src/m3_estimation``. Tout code qui accepterait un jour un octet d'image réel (upload, lecture
disque, appel à un modèle de vision) DOIT appeler ``verifier_collecte_photo_autorisee`` avant
d'agir, et respecter son refus — fail-closed (AGENTS.md) : par défaut, refusé.

Module pur (ADR-0009) : aucun accès disque ici — le TEXTE du document de politique est fourni par
l'appelant (même discipline que le barème ou les seuils : « fourni, jamais deviné »). C'est
``outils.py``, seul, qui lit le fichier réel sur disque
(``docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md``) et transmet son texte ici
— même patron que ``registre_production()``/``registre_devis_production()`` pour le stockage
durable : ce module ignore d'où vient le texte.

Marqueur de validation : une ligne EXACTE ``STATUT_VALIDATION: valide`` dans le document autorise
la collecte ; toute autre valeur (notamment ``STATUT_VALIDATION: proposition``, l'état de
livraison de cette politique à la fin de cette tranche), ou son absence, REFUSE — fail-closed,
jamais une valeur par défaut inventée qui autoriserait par erreur une collecte réelle avant
validation humaine par Nathan ou un juriste (T3, AGENTS.md : « engagements externes : humain
seul »)."""

from __future__ import annotations

import re
from typing import Any

from . import verdicts

__all__ = [
    "STATUT_VALIDE",
    "lire_statut_validation",
    "politique_est_validee",
    "verifier_collecte_photo_autorisee",
]

STATUT_VALIDE = "valide"
_MOTIF_STATUT = re.compile(r"^STATUT_VALIDATION:\s*(\S+)\s*$", re.MULTILINE)


def lire_statut_validation(texte_politique: Any) -> str | None:
    """Extrait le marqueur ``STATUT_VALIDATION: <valeur>`` du texte fourni, ou ``None`` si
    absent, dupliqué ou si l'entrée n'est pas une chaîne — fail-closed sur toute forme
    inattendue, jamais une valeur devinée."""
    if not isinstance(texte_politique, str):
        return None
    correspondances = _MOTIF_STATUT.findall(texte_politique)
    if len(correspondances) != 1:
        return None
    return correspondances[0]


def politique_est_validee(texte_politique: Any) -> bool:
    """``True`` SEULEMENT si le marqueur vaut EXACTEMENT ``valide`` — fail-closed sur tout le
    reste (absent, dupliqué, ``proposition``, ou toute autre valeur)."""
    return lire_statut_validation(texte_politique) == STATUT_VALIDE


def verifier_collecte_photo_autorisee(texte_politique: Any) -> dict[str, Any] | None:
    """Rend ``None`` (collecte AUTORISÉE) si la politique est validée, sinon un verdict nommé
    ``REJ-PHOTO-POLITIQUE-NON-VALIDEE`` qui dit quoi faire : faire valider la politique par Nathan
    ou un juriste avant toute collecte réelle de photo (Loi 25)."""
    if politique_est_validee(texte_politique):
        return None
    statut = lire_statut_validation(texte_politique) or "absent"
    return verdicts.construire_verdict(
        "REJ-PHOTO-POLITIQUE-NON-VALIDEE",
        detail=(
            f"statut de validation actuel : {statut!r} — la politique "
            "docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md doit être "
            "marquée 'valide' par Nathan ou un juriste avant toute collecte réelle de photo "
            "(Loi 25, fail-closed par défaut)."
        ),
    )
