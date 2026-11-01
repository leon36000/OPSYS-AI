"""Fabriques communes aux tests des connecteurs de signaux : horloge, coffre fictif, comptes, masqueur. Données
FICTIVES."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

from m7_marketing.signaux import comptes, modele

from opsys.observabilite.pii import MasqueurMotifs

JETON = "jeton-fictif-SENTINELLE-7f3a9c"
JETON_DEV = "dev-fictif-SENTINELLE-b81d20"
MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class Horloge:
    """Horloge injectée : avance à la main."""

    def __init__(self, depart: datetime = MAINTENANT) -> None:
        self.t = depart

    def __call__(self) -> datetime:
        return self.t

    def avancer(self, **kw) -> None:
        self.t += timedelta(**kw)


def masqueur() -> MasqueurMotifs:
    return MasqueurMotifs(b"\x07" * 32)


class CoffreFictif:
    """Fournisseurs de secrets de test : consigne combien de fois chaque secret a été ouvert et fermé."""

    def __init__(self, valeurs: dict[str, str]) -> None:
        self._valeurs = valeurs
        self.ouvertures = {nom: 0 for nom in valeurs}
        self.ouverts = 0

    def fournisseur(self, role: str):
        @contextlib.contextmanager
        def ouvrir():
            self.ouvertures[role] += 1
            self.ouverts += 1
            try:
                yield self._valeurs[role]
            finally:
                self.ouverts -= 1

        return ouvrir

    def fournisseurs(self) -> dict:
        return {role: self.fournisseur(role) for role in self._valeurs}


def coffre_pour(source: str) -> CoffreFictif:
    valeurs = {"principal": JETON}
    for annexe in modele.SOURCES[source].secrets_annexes:
        valeurs[annexe] = JETON_DEV
    return CoffreFictif(valeurs)


def compte(
    source: str,
    ressource: str,
    *,
    compte_ref: str = "principal",
    fictif: bool = True,
    base_url: str | None = None,
    options: dict | None = None,
) -> comptes.CompteSource:
    annexes = {a: {"nom": f"secret.{a}"} for a in modele.SOURCES[source].secrets_annexes}
    journal: list = []
    ack = comptes.enregistrer(
        journal,
        source,
        compte_ref,
        ressource,
        {"nom": "secret.principal"},
        annexes or None,
        base_url,
        options,
        fictif,
        "nathan",
        "2026-10-01T00:00:00Z",
    )
    assert ack["accepte"], ack
    return comptes.actifs(journal)[(source, compte_ref)]
