from __future__ import annotations

import hashlib
import logging
from typing import Optional

from authz.engine import AuthzEngine
from authz.model import ObjectRef, TenantScope

logger = logging.getLogger(__name__)


class DomainAuthz:
    """Surface unique d’autorisation pour le produit."""

    def __init__(self, engine: AuthzEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _user_hash(self, user: Optional[str]) -> str:
        if not user:
            return "none"
        return hashlib.sha256(user.encode("utf-8")).hexdigest()[:12]

    def _log_decision(self, user: Optional[str], perm: str, obj: Optional[ObjectRef],
                      scope: Optional[TenantScope], allowed: bool, reason_code: str) -> None:
        user_hash = self._user_hash(user)
        object_type = obj.object_type.name if obj else "unknown"
        object_id_trunc = (obj.object_id_tronque if obj and obj.object_id_tronque
                           else (obj.object_id[:8] + "…" if obj else "unknown"))
        tenant = scope.tenant_id if scope else "unknown"
        logger.info(
            "decision=%s user_hash=%s object_type=%s object_id_trunc=%s tenant=%s perm=%s reason_code=%s",
            allowed, user_hash, object_type, object_id_trunc, tenant, perm, reason_code,
        )

    # ------------------------------------------------------------------
    # API domaine
    # ------------------------------------------------------------------
    def peut_lire(self, user: Optional[str], obj: ObjectRef, scope: TenantScope) -> bool:
        allowed = self._engine.check(user, "lire", obj, scope)
        self._log_decision(user, "lire", obj, scope, allowed,
                           "role" if allowed else "deny_default")
        return allowed

    def peut_ecrire(self, user: Optional[str], obj: ObjectRef, scope: TenantScope) -> bool:
        allowed = self._engine.check(user, "ecrire", obj, scope)
        self._log_decision(user, "ecrire", obj, scope, allowed,
                           "role" if allowed else "deny_default")
        return allowed

    def peut_administrer(self, user: Optional[str], obj: ObjectRef, scope: TenantScope) -> bool:
        allowed = self._engine.check(user, "administrer", obj, scope)
        self._log_decision(user, "administrer", obj, scope, allowed,
                           "role" if allowed else "deny_default")
        return allowed

    def peut_voir_couts(self, user: Optional[str], obj: ObjectRef, scope: TenantScope) -> bool:
        allowed = self._engine.check(user, "voir_couts", obj, scope)
        self._log_decision(user, "voir_couts", obj, scope, allowed,
                           "owner_or_admin" if allowed else "deny_default")
        return allowed
