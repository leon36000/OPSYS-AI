from __future__ import annotations

import re
import traceback
from typing import List, Optional

# ---------------------------------------------------------------------------
# Regex étendues (A3) – capture des patterns évidents de secrets
# ---------------------------------------------------------------------------
_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),               # OpenAI like keys
    re.compile(r"Bearer\s+[^\s,;]+"),                  # Bearer tokens
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"[A-Za-z0-9+/]{40,}"),                # Chaînes longues (tokens, clés)
]

# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def redact(
    text: Optional[str],
    secrets: Optional[List[str]] = None,
    provider=None,
) -> str:
    """Remplace tous les secrets connus et patterns suspects par ``***REDIGE***``.

    Args:
        text: Texte à assainir. ``None`` ou ``""`` sont acceptés.
        secrets: Liste optionnelle de valeurs de secrets explicites à masquer.
        provider: Optionnel. Si fourni, collecte les secrets déjà connus du
            provider via ``known_secret_values()``.

    Returns:
        Le texte expurgé (toujours une chaîne non nulle).
    """
    if text is None or text == "":
        return ""

    result = text

    # Collect all known secrets: explicit list + provider cache
    all_secrets = list(secrets) if secrets else []
    if provider is not None:
        all_secrets.extend(provider.known_secret_values())

    # 1. Exact secrets (long enough)
    for secret in all_secrets:
        if len(secret) < 6:
            continue
        escaped = re.escape(secret)
        result = re.sub(escaped, "***REDIGE***", result)

    # 2. Suspicious patterns
    for pat in _PATTERNS:
        result = pat.sub("***REDIGE***", result)

    return result


def safe_traceback(exc: Exception, secrets: Optional[List[str]] = None, provider=None) -> str:
    """Formate une traceback complète et purge toutes les valeurs sensibles.
    Accepte un provider optionnel pour enrichir la liste des secrets."""
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_text = "".join(tb_lines)
    return redact(tb_text, secrets=secrets, provider=provider)
