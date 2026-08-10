import hashlib as _hashlib
import json as _json


def hash_ratification(ratification: dict) -> str:
    """Retourne le SHA-256 hexadécimal du JSON canonique du dict ratification."""
    canonical = _json.dumps(
        ratification,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _hashlib.sha256(canonical.encode("utf-8")).hexdigest()
