"""Adapter GATED pour Postiz (mode ombre strict).

Doctrine : read-only -> dry-run -> write gated.
ADR-0003 Q3a : le feature-flag est OFF par défaut.
D-010 : l'écriture réelle est interdite tant que l'Approval Engine n'est pas branché.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Canal(Enum):
    """Canaux supportés par l'adapter."""

    GBP = "gbp"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class AdapterDisabled(Exception):
    """Le feature-flag est désactivé (ADR-0003 Q3a)."""


class NotAutorise(Exception):
    """Écriture réelle interdite en mode ombre sans Approval Engine."""


@dataclass(frozen=True)
class SocialPost:
    """Publication sociale à destination de Postiz.

    Attributs :
        canal: canal de publication (gbp, facebook, instagram).
        texte: contenu textuel du post (non vide).
        media: liste optionnelle de chemins vers les médias.
        niveau_validation: niveau d'approbation requis, de 0 à 6.
    """

    canal: str
    texte: str
    media: list[str] | None = None
    niveau_validation: int = 0

    def __post_init__(self) -> None:
        if self.canal not in {c.value for c in Canal}:
            raise ValueError(
                f"canal invalide : {self.canal!r} (attendu : gbp, facebook, instagram)"
            )
        if not isinstance(self.texte, str) or not self.texte.strip():
            raise ValueError("texte doit être une chaîne non vide")
        if (
            not isinstance(self.niveau_validation, int)
            or not 0 <= self.niveau_validation <= 6
        ):
            raise ValueError(
                f"niveau_validation doit être un entier entre 0 et 6, reçu {self.niveau_validation!r}"
            )
        if self.media is not None and (
            not isinstance(self.media, list) or not all(isinstance(m, str) for m in self.media)
        ):
            raise ValueError("media doit être une liste de chemins (str)")


class PostizAdapter:
    """Adapter Postiz en mode ombre.

    Config attendue :
        {
            "enabled": bool,   # défaut False
            "dry_run": bool,   # défaut True
            "base_url": str,   # défaut ""
        }
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.dry_run = bool(cfg.get("dry_run", True))
        self.base_url = str(cfg.get("base_url", ""))

    def preparer(self, post: SocialPost) -> dict[str, Any]:
        """Construit le payload Postiz sans aucun appel réseau.

        Format du payload retourné :
        {
            "platform": str,          # "gbp" | "facebook" | "instagram"
            "content": str,           # texte du post
            "media": list[str],       # chemins des médias (vide si aucun)
            "approval_level": int,    # 0-6
            "dry_run": bool           # état actuel de l'adapter
        }
        """
        if not isinstance(post, SocialPost):
            raise ValueError("post doit être une instance de SocialPost")

        return {
            "platform": post.canal,
            "content": post.texte,
            "media": list(post.media) if post.media else [],
            "approval_level": post.niveau_validation,
            "dry_run": self.dry_run,
        }

    def publier(self, post: SocialPost) -> dict[str, Any]:
        """Publie un post selon la doctrine GATED.

        - enabled=False  -> lève AdapterDisabled.
        - enabled=True & dry_run=True  -> retourne un résultat dry-run sans réseau.
        - enabled=True & dry_run=False -> lève NotAutorise (écriture réelle non implémentée).
        """
        if not self.enabled:
            raise AdapterDisabled("feature-flag OFF (ADR-0003 Q3a)")

        payload = self.preparer(post)

        if self.dry_run:
            return {
                "statut": "dry-run",
                "payload": payload,
                "approbation_requise": post.niveau_validation >= 1,
            }

        raise NotAutorise(
            "écriture réelle interdite en mode ombre — Approval Engine requis (D-010)"
        )

    def file_approbation(self, posts: list[SocialPost]) -> list[SocialPost]:
        """Simule localement la file d'approbation 0-6.

        Retourne les posts triés par niveau_validation décroissant.
        Aucun effet de bord.
        """
        return sorted(posts, key=lambda p: p.niveau_validation, reverse=True)
