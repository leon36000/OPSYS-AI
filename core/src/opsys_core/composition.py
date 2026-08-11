"""Composition root du Core OPSYS-AI (C04-004).

Point UNIQUE où `CoreConfig` (déclaration : quelles planes sont
requises/enregistrées, opsys_core.kernel, C03-001) et `ProviderSet`
(réalité : quels providers concrets existent, opsys_core.
provider_registry, C04-004) se rencontrent pour produire un
`CoreKernel`. « Injection explicite » : l'appelant fournit `providers`
en paramètre — ce module ne construit, ne devine, ni n'importe aucun
adapter concret (aucun `opsys_core.compat.*`, aucun SDK fournisseur) ;
c'est précisément le sens de « injection », pas « résolution ».

`build_core` ne fait AUCUN calcul de statut par lui-même — il délègue
intégralement à `diagnostiquer`, source UNIQUE de vérité (jamais deux
calculs séparés qui pourraient diverger silencieusement).

Aucun état au niveau module : chaque appel est indépendant, un même
couple (config, providers) équivalent produit toujours un `CoreKernel`
équivalent mais JAMAIS le même objet (pas de cache/singleton).
"""
from __future__ import annotations

from dataclasses import dataclass

from .kernel import CoreConfig, CoreKernel, CoreStatus
from .planes import CorePlane
from .provider_registry import ProviderSet


@dataclass(frozen=True)
class DiagnosticComposition:
    """Diagnostic de composition (implémentation strictement bornée au
    mot « diagnostic » du spec — pas de tri topologique, pas de
    résolution de dépendances entre providers, pas de health-check)."""

    planes_requises: frozenset[CorePlane]
    planes_pourvues: frozenset[CorePlane]
    planes_manquantes: frozenset[CorePlane]
    status: CoreStatus


def diagnostiquer(config: CoreConfig, providers: ProviderSet) -> DiagnosticComposition:
    """Calcule le diagnostic complet — SEULE fonction qui décide du
    statut résultant. `build_core` lit ce résultat, ne le recalcule
    jamais.

    Ordre des vérifications : (1) chaque plane REQUISE a-t-elle un
    provider concret ? Si non, BLOCKED_MISSING_PREREQUISITE — c'est la
    vérification NOUVELLE apportée par cette tâche, distincte de (2)
    la vérification déjà existante de CoreKernel.boot (planes requises
    ⊆ planes enregistrées dans le CoreConfig lui-même), déléguée
    seulement si (1) est satisfaite."""
    planes_pourvues = providers.planes()
    planes_manquantes = config.required_planes - planes_pourvues
    if planes_manquantes:
        status = CoreStatus.BLOCKED_MISSING_PREREQUISITE
    else:
        status = CoreKernel.boot(config)
    return DiagnosticComposition(
        planes_requises=config.required_planes,
        planes_pourvues=planes_pourvues,
        planes_manquantes=planes_manquantes,
        status=status,
    )


def build_core(config: CoreConfig, providers: ProviderSet) -> CoreKernel:
    """Construit le `CoreKernel` — délègue intégralement son statut à
    `diagnostiquer` (source unique de vérité)."""
    diagnostic = diagnostiquer(config, providers)
    return CoreKernel(status=diagnostic.status)
