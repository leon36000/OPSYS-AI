"""Adaptateurs in‑memory déterministes pour l'approval engine et le bus de notification."""

import hashlib
import json
import verdicts
from typing import Union


def _derive_id(*parts: str) -> str:
    """Encode injectivement les parties avec préfixe de longueur, puis hachure SHA-256."""
    encoded = "|".join(f"{len(p)}:{p}" for p in parts)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _ApprovalEngine:
    def __init__(self, mode_ombre: bool):
        self._mode_ombre = mode_ombre
        self._store: dict[str, str] = {}

    def proposer(self, objet, acteur: str) -> Union[str, dict]:
        """Propose un objet pour approbation.

        En mode ombre : retourne un identifiant (str) déterministe.
        Hors mode ombre : retourne un verdict de rejet (dict).
        Tous les types d'objets sont acceptés via sérialisation robuste.
        """
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        serialized = json.dumps(objet, sort_keys=True, ensure_ascii=True, default=repr)
        id_ = _derive_id(serialized, acteur)
        self._store[id_] = "proposé"
        return id_

    def statut(self, id_: str) -> Union[str, dict]:
        """Retourne le statut d'une proposition.

        En mode ombre : retourne le statut stocké ou 'STATUT_INCONNU' (str).
        Hors mode ombre : retourne un verdict de rejet (dict).
        """
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        if id_ in self._store:
            return self._store[id_]
        return "STATUT_INCONNU"


class _NotificationBus:
    def __init__(self, mode_ombre: bool):
        self._mode_ombre = mode_ombre

    def emettre(self, canal: str, message: str) -> Union[str, dict]:
        """Émet une notification.

        En mode ombre : retourne un identifiant (str) de l'émission.
        Hors mode ombre : retourne un verdict de rejet (dict).
        """
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        return _derive_id(canal, message)


def creer_approval_engine(mode_ombre: bool = True):
    return _ApprovalEngine(mode_ombre)


def creer_bus(mode_ombre: bool = True):
    return _NotificationBus(mode_ombre)
