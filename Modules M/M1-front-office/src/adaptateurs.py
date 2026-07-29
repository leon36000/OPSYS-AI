"""Adaptateurs in‑memory déterministes pour l'approval engine et le bus de notification."""

import hashlib
import json
import verdicts


class _ApprovalEngine:
    def __init__(self, mode_ombre: bool):
        self._mode_ombre = mode_ombre
        self._store: dict[str, str] = {}

    def proposer(self, objet, acteur: str) -> str:
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        serialized = json.dumps(objet, sort_keys=True, ensure_ascii=True)
        raw = f"{serialized}|{acteur}"
        id_ = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self._store[id_] = "proposé"
        return id_

    def statut(self, id_: str) -> str:
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        if id_ in self._store:
            return self._store[id_]
        return "STATUT_INCONNU"


class _NotificationBus:
    def __init__(self, mode_ombre: bool):
        self._mode_ombre = mode_ombre

    def emettre(self, canal: str, message: str) -> str:
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        raw = f"{canal}|{message}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def creer_approval_engine(mode_ombre: bool = True):
    return _ApprovalEngine(mode_ombre)


def creer_bus(mode_ombre: bool = True):
    return _NotificationBus(mode_ombre)
