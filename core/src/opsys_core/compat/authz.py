"""Shim de compatibilité pour authz/ existant (C04-003).

Encapsule `authz.domain_api.DomainAuthz` — la « surface unique
d'autorisation pour le produit » déjà déclarée par son propre docstring
— SANS déplacer ni copier son code. Revue d'architecture AVANT code
(subagent `architecte`) : envelopper `DomainAuthz` plutôt que
`AuthzEngine` directement, pour préserver sa piste d'audit (hash
tronqué de l'utilisateur, reason_code distinct par permission) que
l'Engine seul n'a pas.

Deux surfaces, deux contrats, jamais confondus :
  - Le moteur encapsulé (`AuthzEngine.check`) garde son deny-by-default
    HISTORIQUE et TESTÉ : utilisateur sans rôle, tenant différent,
    objet absent -> False, sans exception. C'est un VERDICT
    d'autorisation, produit par le code hérité — ce shim le laisse
    passer verbatim (jamais de coercition bool(), qui masquerait un
    moteur non conforme).
  - Une permission HORS du vocabulaire des 4 méthodes exposées par
    DomainAuthz (lire/ecrire/administrer/voir_couts) n'est PAS un
    verdict d'autorisation : c'est l'incapacité du shim à traduire
    l'appel. La masquer en False la rendrait indistinguable d'un refus
    légitime — interdit explicitement par le cas RED « le shim signale
    les limitations au lieu de les masquer » (tasks/C04-003.md).
    `authorize()` lève alors `PermissionLegacyNonSupportee`.
"""
from __future__ import annotations

from typing import Callable, Final, Mapping

from authz.domain_api import DomainAuthz
from authz.model import ObjectRef, TenantScope


class PermissionLegacyNonSupportee(LookupError):
    """Levée par `LegacyAuthzAdapter.authorize` sur une permission hors
    du vocabulaire de `DomainAuthz` — signale une limitation du SHIM,
    jamais un verdict d'autorisation (cf. docstring du module)."""

    def __init__(self, permission: str) -> None:
        supportees = ", ".join(sorted(_DISPATCH))
        super().__init__(
            f"permission legacy non supportee par LegacyAuthzAdapter: {permission!r} "
            f"(permissions supportees: {supportees})"
        )
        self.permission = permission


# Table de dispatch EXPLICITE vers les 4 fonctions non liées de
# DomainAuthz — jamais `getattr(domain, "peut_" + permission)` (une
# faute de frappe deviendrait un AttributeError au runtime au lieu
# d'une erreur mypy/à l'import) et jamais un import de la table privée
# `authz.engine._PERMISSION_RELATIONS` (nom privé d'un autre paquet :
# violerait la mission même de la phase C04, « interdiction des accès
# privés intermodules »). La non-duplication avec le vocabulaire réel
# du moteur est prouvée par un test comportemental dédié (garde de
# dérive, cas RED 3(d)), pas par cette table elle-même.
_DISPATCH: Final[Mapping[str, Callable[[DomainAuthz, "str | None", ObjectRef, TenantScope], bool]]] = {
    "lire": DomainAuthz.peut_lire,
    "ecrire": DomainAuthz.peut_ecrire,
    "administrer": DomainAuthz.peut_administrer,
    "voir_couts": DomainAuthz.peut_voir_couts,
}


class LegacyAuthzAdapter:
    """Encapsule un `DomainAuthz` existant derrière une surface unique
    `authorize(user, permission, obj, scope)`. Ne journalise pas les
    décisions : `DomainAuthz._log_decision` le fait déjà (avec hachage
    de l'utilisateur) — un log supplémentaire ici doublerait la piste
    d'audit et risquerait de journaliser l'utilisateur en clair."""

    def __init__(self, domain: DomainAuthz) -> None:
        self._domain = domain

    def authorize(
        self,
        user: "str | None",
        permission: str,
        obj: ObjectRef,
        scope: TenantScope,
    ) -> bool:
        methode = _DISPATCH.get(permission)
        if methode is None:
            raise PermissionLegacyNonSupportee(permission)
        return methode(self._domain, user, obj, scope)
