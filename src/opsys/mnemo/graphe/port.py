"""Port `MoteurGraphe` : ce qu'un moteur de graphe de connaissances sait faire, quel que soit son stockage.

Le moteur de référence est l'adaptateur SQL natif (`sql.GrapheSql`, tables de la migration 0052, SQLite et PostgreSQL)
; `double.GrapheMemoire` est le double de test, qui obéit aux mêmes règles (`regles.py`) sur des listes en mémoire. Un
moteur externe (LightRAG, MIT, ou une base de graphe) ne se branche QUE derrière ce port, et seulement après avoir
rejoué le harnais de mesure (`mesure.py`) et le test de parité : voir `docs/architecture/M10-SOI-GRAPHE.md`, § plan
LightRAG (non exécuté).

Toutes les méthodes reçoivent l'instant (`quand`) : aucun moteur ne lit d'horloge.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .schema import NoeudRef

K_MAX = 4
NOEUDS_MAX = 200
ARETES_MAX = 400


@dataclasses.dataclass(frozen=True)
class Noeud:
    noeud_id: str
    type: str
    cle: str
    libelle: str
    cree_le: str

    def ref(self) -> NoeudRef:
        return NoeudRef(self.type, self.cle)

    def vers_json(self) -> dict[str, Any]:
        return {"noeud_id": self.noeud_id, "type": self.type, "cle": self.cle, "libelle": self.libelle}


@dataclasses.dataclass(frozen=True)
class Arete:
    arete_id: str
    type: str
    de: Noeud
    vers: Noeud
    valide_de: str
    valide_a: str | None
    etat: str
    sensible: bool
    origine: str
    source_type: str
    source_ref: str
    confiance: str

    def vers_json(self) -> dict[str, Any]:
        return {
            "arete_id": self.arete_id,
            "type": self.type,
            "de": self.de.vers_json(),
            "vers": self.vers.vers_json(),
            "valide_de": self.valide_de,
            "valide_a": self.valide_a,
            "etat": self.etat,
            "sensible": self.sensible,
            "origine": self.origine,
            "source": {"type": self.source_type, "ref": self.source_ref},
            "confiance": self.confiance,
        }


@dataclasses.dataclass(frozen=True)
class DemandeArete:
    """Une arête proposée. Les deux extrémités sont posées au besoin (idempotent) ; leurs libellés ne servent qu'aux
    nœuds non personnels."""

    type: str
    de: NoeudRef
    vers: NoeudRef
    valide_de: str
    origine: str
    source_type: str
    source_ref: str
    confiance: str = "moyenne"
    de_libelle: str | None = None
    vers_libelle: str | None = None


@dataclasses.dataclass(frozen=True)
class Proposition:
    arete: Arete
    creee: bool  # faux : l'arête existait déjà (rejeu), rien n'a été écrit


@dataclasses.dataclass(frozen=True)
class Voisinage:
    depart: Noeud
    k: int
    a_la_date: str
    noeuds: tuple[tuple[Noeud, int], ...]  # (nœud, distance), le départ à 0
    aretes: tuple[Arete, ...]
    tronque: bool

    def vers_json(self) -> dict[str, Any]:
        return {
            "depart": self.depart.vers_json(),
            "k": self.k,
            "a_la_date": self.a_la_date,
            "noeuds": [{**n.vers_json(), "distance": d} for n, d in self.noeuds],
            "aretes": [a.vers_json() for a in self.aretes],
            "tronque": self.tronque,
        }


@dataclasses.dataclass(frozen=True)
class Chemin:
    noeuds: tuple[Noeud, ...]
    aretes: tuple[Arete, ...]

    @property
    def longueur(self) -> int:
        return len(self.aretes)

    def vers_json(self) -> dict[str, Any]:
        return {
            "longueur": self.longueur,
            "noeuds": [n.vers_json() for n in self.noeuds],
            "aretes": [a.vers_json() for a in self.aretes],
        }


class MoteurGraphe(Protocol):
    def poser_noeud(
        self, type_noeud: str, cle: str, libelle: str | None, *, source_ref: str, par: str, quand: str
    ) -> Noeud: ...

    def proposer_arete(self, demande: DemandeArete, *, par: str, quand: str) -> Proposition: ...

    def confirmer_arete(
        self, arete_id: str, *, par: str, mode: str, role: str | None, raison: str | None, quand: str
    ) -> Arete: ...

    def rejeter_arete(
        self, arete_id: str, *, par: str, mode: str, role: str | None, raison: str, quand: str
    ) -> Arete: ...

    def fermer_arete(
        self, arete_id: str, valide_a: str, *, par: str, mode: str, role: str | None, raison: str, quand: str
    ) -> Arete: ...

    def noeud(self, type_noeud: str, cle: str) -> Noeud | None: ...

    def arete(self, arete_id: str) -> Arete | None: ...

    def voisinage(
        self,
        depart: NoeudRef,
        k: int,
        *,
        a_la_date: str,
        types_arete: Sequence[str] | None = None,
        inclure_brouillons: bool = False,
        noeuds_max: int = NOEUDS_MAX,
    ) -> Voisinage: ...

    def chemin(
        self, de: NoeudRef, vers: NoeudRef, *, a_la_date: str, k_max: int = K_MAX, inclure_brouillons: bool = False
    ) -> Chemin | None: ...

    def pourquoi(self, arete_id: str) -> dict[str, Any]: ...

    def en_attente(self, limite: int = 50) -> tuple[Arete, ...]: ...

    def etat(self) -> Mapping[str, Any]: ...
