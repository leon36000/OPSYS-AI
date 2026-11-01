"""Journal append-only à chaîne de hachage, commun aux registres WordPress et réseaux sociaux de M7.

Un maillon n'est jamais modifié : un état est le PLIAGE des maillons. Chaque maillon porte le hachage du précédent
(`chaine`), donc retoucher, retirer ou réordonner un maillon passé se voit (`verifier`). Le journal est n'importe quelle
séquence qui sait `append`, `len` et s'itérer : une liste (tests purs) ou `opsys.stockage.maillons(...)` (durable) ;
ce module n'importe rien d'`opsys`.

Les maillons ne portent que du JSON natif (texte, entier, booléen, liste, dictionnaire) : aucun secret, aucun jeton,
aucune
valeur monétaire décimale (les montants sont en cents entiers).

Module pur : aucune entrée-sortie, aucune horloge (l'horodatage est fourni par l'appelant, de la réception serveur).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

GENESE = "0" * 64
CLES_RESERVEES = frozenset({"rang", "type", "horodatage", "chaine"})


class Journal(Protocol):
    def append(self, maillon: Any) -> None:
        """Ajoute un maillon à la fin ; aucune autre mutation n'existe."""

    def __len__(self) -> int:
        """Nombre de maillons."""

    def __iter__(self):
        """Parcourt les maillons du plus ancien au plus récent."""


class ConcurrenceJournal(RuntimeError):
    """Le journal a changé depuis la lecture sur laquelle repose l'écriture (`rang_attendu` périmé) : rien n'est
    écrit."""


def _json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _chaine(precedent: str, corps: Mapping[str, Any]) -> str:
    return hashlib.sha256((precedent + "\n" + _json(corps)).encode("utf-8")).hexdigest()


def maillons(journal: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(m) for m in journal]


def ajouter(
    journal: Journal, type_maillon: str, donnees: Mapping[str, Any], horodatage: str, *, rang_attendu: int | None = None
) -> dict[str, Any]:
    """Écrit un maillon et le rend. `donnees` ne peut pas redéfinir `rang`, `type`, `horodatage` ni `chaine`.

    `rang_attendu` (comparaison-échange) : le nombre de maillons que l'appelant a LU AVANT de décider d'écrire.
    Une écriture qui consomme quelque chose (jeton d'approbation, tentative d'envoi) le donne : si un autre exécuteur
    a écrit entre la lecture et ici, `ConcurrenceJournal` est levée (aussi pour un journal durable) et rien n'est
    écrit. Sans lui, le rang est celui du journal au moment de l'écriture et deux exécuteurs qui ont lu le même état
    écrivent chacun le leur."""
    collision = CLES_RESERVEES & set(donnees)
    if collision:
        raise ValueError(f"clés réservées du journal : {sorted(collision)}")
    taille = len(journal)
    if rang_attendu is not None and taille != rang_attendu:
        raise ConcurrenceJournal(f"rang attendu {rang_attendu} devenu {taille}")
    precedent = journal[-1]["chaine"] if taille else GENESE
    corps = {"rang": taille, "type": type_maillon, "horodatage": horodatage, **donnees}
    maillon = {**corps, "chaine": _chaine(precedent, corps)}
    if rang_attendu is None or isinstance(journal, list):
        journal.append(maillon)  # liste pure (tests) : un seul fil, la comparaison ci-dessus a suffi
    else:
        try:
            journal.append(maillon, rang_attendu=rang_attendu)  # journal durable : la vérification est refaite en base
        except RuntimeError as exc:
            if type(exc).__name__ == "EcritureConcurrente":  # opsys.stockage : ce module n'importe rien d'opsys
                raise ConcurrenceJournal(str(exc)) from exc
            raise
    return maillon


def verifier(journal: Iterable[Any]) -> list[str]:
    """Les anomalies de la chaîne (vide si intègre) : rang discontinu, hachage qui ne correspond pas."""
    problemes: list[str] = []
    precedent = GENESE
    for rang, brut in enumerate(journal):
        if not isinstance(brut, Mapping) or "chaine" not in brut:
            problemes.append(f"rang {rang} : maillon illisible")
            break
        corps = {cle: valeur for cle, valeur in brut.items() if cle != "chaine"}
        if corps.get("rang") != rang:
            problemes.append(f"rang {rang} : numéro {corps.get('rang')!r} au lieu de {rang}")
        if brut["chaine"] != _chaine(precedent, corps):
            problemes.append(f"rang {rang} : le hachage ne correspond plus (maillon modifié ou retiré)")
        precedent = brut["chaine"]
    return problemes


def integre(journal: Iterable[Any]) -> bool:
    return not verifier(journal)


def de_type(journal: Iterable[Any], *types: str) -> Sequence[dict[str, Any]]:
    return [m for m in maillons(journal) if m["type"] in types]
