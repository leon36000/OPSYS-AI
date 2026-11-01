"""Refus typés de l'observabilité (`REJ-OBS-*`) : un code stable et un détail qui ne contient jamais de valeur brute.

Le détail dit quoi corriger ; il ne recopie ni une donnée masquée, ni une clé, ni un en-tête d'autorisation.
"""

from __future__ import annotations

CODES_OBS: tuple[str, ...] = (
    "REJ-OBS-CLE-ABSENTE",
    "REJ-OBS-CLE-INVALIDE",
    "REJ-OBS-CLE-PERMISSIONS",
    "REJ-OBS-MASQUEUR",
    "REJ-OBS-COFFRE-PII-REFUSE",
    "REJ-OBS-COFFRE-PII-INCONNU",
    "REJ-OBS-COFFRE-PII-SECRET",
    "REJ-OBS-TRACE-INVALIDE",
    "REJ-OBS-JOURNAL-ALTERE",
    "REJ-OBS-JOURNAL-RETENTION",
    "REJ-OBS-DESTINATION-NON-CONFIGUREE",
    "REJ-OBS-DESTINATION-REFUSEE",
    "REJ-OBS-EXPORT-PII",
    "REJ-OBS-ARGUMENT-INVALIDE",
)


class ErreurObservabilite(ValueError):
    """Refus typé : `code` (catalogue fermé `CODES_OBS`) et `detail` lisible, sans valeur brute."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in CODES_OBS:
            raise ValueError(f"code d'observabilité hors catalogue : {code!r}")
        self.code, self.detail = code, detail
        super().__init__(f"{code} : {detail}")

    def publique(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}
