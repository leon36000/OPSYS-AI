"""Erreur bornée du coffre : un code stable et un détail fixe, jamais une valeur de secret ni un jeton."""

from __future__ import annotations


class CoffreErreur(Exception):
    def __init__(self, code: str, detail: str, statut_http: int = 409) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail
        self.statut_http = statut_http

    def publique(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}
