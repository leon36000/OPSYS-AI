"""Maillons d'un registre de département, stockés dans la base de l'instance.

`MaillonsDurables` se comporte comme la liste que chaque `Registre` de département tenait en mémoire
(`len`, index négatif, tranche, itération, `append`, `extend`, copie profonde en liste). Aucun cache :
chaque accès passe par la transaction courante, donc un appel d'outil voit ses propres écritures, un
échec les annule toutes, et deux processus ne divergent jamais.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, func, insert, select
from sqlalchemy.exc import IntegrityError

from . import codec
from .moteur import connexion_courante, transaction
from .schema import REGISTRES


class EcritureConcurrente(RuntimeError):
    """Un autre processus a écrit au même rang : la transaction est annulée, l'appel est à rejouer."""


class MaillonsDurables:
    def __init__(self, departement: str, registre: str = "principal") -> None:
        if not departement or not registre:
            raise ValueError("département et nom de registre obligatoires")
        self.departement = departement
        self.registre = registre

    @contextmanager
    def _cnx(self) -> Iterator[Connection]:
        courante = connexion_courante()
        if courante is not None:
            yield courante
            return
        with transaction() as nouvelle:
            yield nouvelle

    def _filtre(self):
        return (REGISTRES.c.departement == self.departement) & (REGISTRES.c.registre == self.registre)

    def __len__(self) -> int:
        with self._cnx() as cnx:
            return cnx.execute(select(func.count()).select_from(REGISTRES).where(self._filtre())).scalar_one()

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self) -> Iterator[Any]:
        with self._cnx() as cnx:
            lignes = cnx.execute(select(REGISTRES.c.maillon).where(self._filtre()).order_by(REGISTRES.c.rang)).all()
        return iter([codec.decoder(ligne.maillon) for ligne in lignes])

    def __getitem__(self, index: int | slice) -> Any:
        if isinstance(index, slice):
            return list(self)[index]
        taille = len(self)
        rang = index + taille if index < 0 else index
        if not 0 <= rang < taille:
            raise IndexError(f"rang {index} hors du registre {self.departement}/{self.registre} ({taille} maillons)")
        requete = select(REGISTRES.c.maillon).where(self._filtre() & (REGISTRES.c.rang == rang))
        with self._cnx() as cnx:
            texte = cnx.execute(requete).scalar_one()
        return codec.decoder(texte)

    def append(self, maillon: Any) -> None:
        texte = codec.encoder(maillon)
        with self._cnx() as cnx:
            rang = len(self)
            try:
                with cnx.begin_nested():
                    cnx.execute(insert(REGISTRES).values(
                        departement=self.departement, registre=self.registre, rang=rang, maillon=texte))
            except IntegrityError as exc:
                raise EcritureConcurrente(
                    f"rang {rang} déjà écrit dans {self.departement}/{self.registre}") from exc

    def extend(self, maillons: Iterable[Any]) -> None:
        with self._cnx():
            for maillon in maillons:
                self.append(maillon)

    def __deepcopy__(self, memo: dict) -> list[Any]:
        return copy.deepcopy(list(self), memo)

    def __repr__(self) -> str:
        return f"MaillonsDurables({self.departement!r}, {self.registre!r})"


def maillons(departement: str, registre: str = "principal") -> MaillonsDurables:
    return MaillonsDurables(departement, registre)
