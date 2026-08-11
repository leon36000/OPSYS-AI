"""Registre de providers, injection explicite (C04-004).

`ProviderSet` associe chaque `CorePlane` (opsys_core.planes, C03-001) à
UN SEUL provider concret — « une capacité n'a qu'une implémentation
active » (cas RED obligatoire). Choix de `CorePlane` comme vocabulaire
de « capacité » ici (et non `opsys_core.status.model.CapabilityStatus.
capability_id`, notion distincte et pré-existante, C03-003) : c'est le
seul porteur d'exigence de la signature imposée
`build_core(config: CoreConfig, ...)` via `CoreConfig.required_planes`
(opsys_core.kernel) — documenté en clair pour éviter la collision de
vocabulaire (même discipline que ports/contracts.py sur `read_port`).

Construction depuis une SÉQUENCE de paires (jamais un dict littéral :
`{A: p1, A: p2}` vaudrait déjà `{A: p2}` avant même d'atteindre ce
module — l'invariant deviendrait infalsifiable). Aucun état au niveau
module : tout vit dans l'instance retournée par `depuis_paires`.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable

from .planes import CorePlane


class CapaciteDejaFournie(LookupError):
    """Levée par `ProviderSet.depuis_paires` quand la même `CorePlane`
    apparaît deux fois dans la séquence de paires fournie — refusée
    quelle que soit l'identité des objets (règle unique, sans exception
    pour un même provider réenregistré deux fois)."""

    def __init__(self, plane: CorePlane, provider_existant: object, provider_refuse: object) -> None:
        super().__init__(
            f"capacité déjà fournie: {plane.name} a déjà un provider "
            f"({provider_existant!r}) — {provider_refuse!r} refusé"
        )
        self.plane = plane


@dataclass(frozen=True)
class ProviderSet:
    """Ensemble immuable de providers, un par `CorePlane` au maximum.
    Ne JAMAIS construire directement (`ProviderSet(...)`) — utiliser
    `depuis_paires`, seul point d'entrée qui applique l'invariant
    d'unicité."""

    _mapping: "MappingProxyType[CorePlane, object]"

    @staticmethod
    def depuis_paires(paires: Iterable[tuple[CorePlane, object]]) -> "ProviderSet":
        construit: dict[CorePlane, object] = {}
        for plane, provider in paires:
            if plane in construit:
                raise CapaciteDejaFournie(plane, construit[plane], provider)
            construit[plane] = provider
        return ProviderSet(MappingProxyType(construit))

    def planes(self) -> frozenset[CorePlane]:
        return frozenset(self._mapping.keys())

    def provider_pour(self, plane: CorePlane) -> object | None:
        return self._mapping.get(plane)
