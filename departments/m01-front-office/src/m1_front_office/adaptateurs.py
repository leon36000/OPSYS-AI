"""Adaptateurs in‑memory déterministes pour l'approval engine et le bus de notification."""

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from . import verdicts


def _derive_id(*parts: str) -> str:
    """Encode injectivement les parties avec préfixe de longueur, puis hachure SHA-256."""
    encoded = "|".join(f"{len(p)}:{p}" for p in parts)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normaliser_objet_deterministe(obj):
    """Retourne une représentation normalisée déterministe de l'objet, prête pour sérialisation JSON."""
    if isinstance(obj, (set, frozenset)):
        elems = sorted(_normaliser_objet_deterministe(e) for e in obj)
        return {"__set__": elems}
    if isinstance(obj, dict):
        return {k: _normaliser_objet_deterministe(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normaliser_objet_deterministe(e) for e in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    # Types supplémentaires avec balises explicites, testés dans un ordre garantissant l'injectivité
    if isinstance(obj, datetime):          # datetime avant date (piège d'héritage)
        return {"__datetime__": obj.isoformat()}
    if isinstance(obj, date):
        return {"__date__": obj.isoformat()}
    if isinstance(obj, time):
        return {"__time__": obj.isoformat()}
    if isinstance(obj, Decimal):
        return {"__decimal__": str(obj)}
    if isinstance(obj, UUID):
        return {"__uuid__": str(obj)}
    if isinstance(obj, bytes):
        return {"__bytes__": obj.hex()}
    if isinstance(obj, bytearray):
        return {"__bytearray__": bytes(obj).hex()}
    if isinstance(obj, complex):
        return {"__complex__": [repr(obj.real), repr(obj.imag)]}
    raise TypeError(
        f"Type non supporté : {type(obj).__name__}. "
        f"Types supportés : dict, set, frozenset, list, tuple, str, int, float, bool, None, "
        f"Decimal, datetime, date, time, UUID, bytes, bytearray, complex. "
        f"L'appelant doit sérialiser la valeur avant de l'incorporer."
    )


class _ApprovalEngine:
    def __init__(self, mode_ombre: bool):
        self._mode_ombre = mode_ombre
        self._store: dict[str, str] = {}

    def proposer(self, objet, acteur: str) -> str | dict:
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        normalise = _normaliser_objet_deterministe(objet)
        serialized = json.dumps(normalise, sort_keys=True, ensure_ascii=False)
        id_ = _derive_id(serialized, acteur)
        self._store[id_] = "proposé"
        return id_

    def statut(self, id_: str) -> str | dict:
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        if id_ in self._store:
            return self._store[id_]
        return "STATUT_INCONNU"


class _NotificationBus:
    def __init__(self, mode_ombre: bool):
        self._mode_ombre = mode_ombre

    def emettre(self, canal: str, message: str) -> str | dict:
        if not self._mode_ombre:
            return verdicts.construire_verdict("REJ-ADAPTATEUR-INDISPONIBLE")
        return _derive_id(canal, message)


def creer_approval_engine(mode_ombre: bool = True):
    return _ApprovalEngine(mode_ombre)


def creer_bus(mode_ombre: bool = True):
    return _NotificationBus(mode_ombre)
