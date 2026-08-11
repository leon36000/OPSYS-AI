"""Ports provider-neutral du Core OPSYS-AI (C04-001).

Modular monolith : kernel/domain n'appellent jamais un SDK fournisseur ni
un autre module directement — uniquement des ports (contrats abstraits),
implémentés par des adapters (RF01-W7-ANTI-FRANKENSTACK-RULES.csv, AF-05 :
« Adapters call ports/adapters, not vendor SDKs directly »).

COLLISION DE VOCABULAIRE À NE PAS CONFONDRE (revue d'architecture AVANT
code) : `opsys_core.authority.model.AuthorityRecord.read_port`/`write_port`
(C03-002) sont des CHEMINS de fichiers dans le dépôt (ex. « Modules M/
M5-financecore/src ») — un sens totalement différent des `Protocol` de ce
module, qui sont des CONTRATS D'INTERFACE. Même mot, deux concepts.

Contrats de FORME minimaux (identifiant nommé) : aucune méthode métier
n'est sourcée par tasks/C04-001.md ni par les 4 sources citées — les
peupler aujourd'hui serait une sur-spécification non fondée (même
discipline anti-sur-ingénierie déjà appliquée en C03-003, cf. revue
d'architecture AVANT code de C03-003 sur evidence_hash/timeout). Les
méthodes métier réelles seront ajoutées par les tâches futures qui
implémentent chaque port pour un besoin sourcé (C04-004 et suivantes),
jamais devinées ici.

Chaque Protocol hérite EXPLICITEMENT de `Protocol` sur sa ligne de
définition (pas d'un autre Protocol par transitivité) : l'exemption du
gate no-stub pour les corps `...` est syntaxique sur `node.bases`
(vérifié dans le hook `no_stub_ast.py` par la revue d'architecture), pas
sémantique — un Protocol qui hériterait d'un autre Protocol perdrait
l'exemption.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DomainPort(Protocol):
    """Port consommé PAR le domaine (opsys_core.authority, opsys_core.status,
    ...) pour accéder à une capacité externe sans connaître son
    implémentation concrète — l'essence du pattern ports & adapters."""

    @property
    def port_id(self) -> str: ...


@runtime_checkable
class ProviderPort(Protocol):
    """Port REPRÉSENTANT un fournisseur externe concret (ex. un provider
    LLM, cloud, paiement) — provider-neutral : le domaine/kernel ne
    connaît que ce contrat, jamais le SDK du fournisseur lui-même."""

    @property
    def provider_id(self) -> str: ...


@runtime_checkable
class ModulePort(Protocol):
    """Port de communication INTER-MODULES (M1-M10) — interdit l'accès
    privé direct entre modules : deux modules ne communiquent qu'à
    travers ce contrat, jamais par import de l'état interne l'un de
    l'autre."""

    @property
    def module_id(self) -> str: ...
