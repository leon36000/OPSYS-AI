"""Pont vers le contrat des ORIGINAUX courriel internes (`opsys.reception_courriel_contrat` /
`reception_courriel_stockage`).

Ce contrat décrit un original IMAP par ses coordonnées (instance, source, compte, boîte, `UIDVALIDITY`, `UID`) et
n'accorde aucune autorité : le stockage chiffré n'écrit qu'avec les rappels `autoriser` / `obtenir_cle` du futur hôte.
Ce module ne fait que construire des arguments VALIDES à partir d'un message IMAP lu par `FournisseurImap` ; il ne
stocke rien, ne décide rien et ne raccorde aucune autorité. Gmail et Graph n'ont pas de coordonnées `UID` : ils
n'entrent pas dans ce contrat. Limite du contrat : 1 Mio par original (au-delà, refus typé).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from ..reception_courriel_contrat import OriginalCourriel, valider_original
from .erreurs import ErreurCourriel
from .modele import MessageBrut

_REF_IMAP = re.compile(r"^([1-9][0-9]{0,9}):([1-9][0-9]{0,9})$")


def source_id_imap(hote: str, utilisateur: str) -> str:
    """Identifiant stable d'une source IMAP (empreinte, jamais l'hôte ni l'utilisateur en clair)."""
    return hashlib.sha256(f"opsys:courriel:source:v1:{hote.lower()}|{utilisateur.lower()}".encode()).hexdigest()


def arguments_original_imap(
    brut: MessageBrut,
    *,
    instance_id: str,
    compte_id: str,
    source_id: str,
    message_id: str | None = None,
    recu_le: datetime | None = None,
) -> dict:
    """Les arguments de `reception_courriel_stockage.recevoir` pour un message lu par IMAP (ref `UIDVALIDITY:UID`)."""
    trouve = _REF_IMAP.fullmatch(brut.ref)
    if trouve is None:
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "référence IMAP `UIDVALIDITY:UID` attendue", 422)
    instant = (recu_le or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "version": 1,
        "instance_id": instance_id,
        "source_id": source_id,
        "compte_id": compte_id,
        "boite": brut.dossier,
        "uid_validity": trouve.group(1),
        "uid": int(trouve.group(2)),
        "taille_annoncee": len(brut.octets),
        "recu_le": instant,
        "date_interne": None,
        "message_id": f"<{message_id}>" if message_id else None,
    }


def original_imap(brut: MessageBrut, **options: object) -> OriginalCourriel:
    """Valide l'original IMAP contre le contrat existant ; `ErreurCourriel` typée en cas de refus."""
    arguments = arguments_original_imap(brut, **options)  # type: ignore[arg-type]
    try:
        return valider_original(arguments, source=brut.octets)
    except ValueError:
        raise ErreurCourriel(
            "REJ-COURRIEL-MESSAGE-INVALIDE",
            "original refusé par le contrat des originaux courriel (taille 1 Mio, coordonnées)",
            422,
        ) from None
