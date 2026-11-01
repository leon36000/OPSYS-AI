"""Jeton d'approbation de publication (`opsys-approval/v1`) : ce qui autorise le plugin à publier.

OPSYS ne peut en émettre un qu'à partir d'une approbation humaine consignée (`flux.approbation_verifiee`) ; le plugin le
vérifie au point de sortie : signature, site, article, action, EMPREINTE DU CONTENU ACTUEL, expiration, usage unique.
Un jeton ne dit jamais « publie ce que tu veux » : il dit « publie CET article, dans CET état exact, avant CETTE
heure ».

Format : `v1.<charge utile JSON en base64url sans bourrage>.<MAC hexadécimal minuscule>`.
MAC = HMAC-SHA256(clé d'approbation, `OPSYS-APPROVAL-V1\\n` + <charge utile base64url, telle quelle>). La clé
d'approbation
est dérivée du secret partagé par HKDF-Expand à un bloc (RFC 5869) : HMAC-SHA256(secret, `opsys-connect/approval/v1` +
0x01), pour qu'une signature de requête ne soit jamais un jeton valide (séparation des domaines). La charge utile est
signée telle quelle : aucun format JSON canonique n'est requis des deux côtés.

Charge utile (tous les champs, aucun autre) : `v`=1, `approval_id`, `site_id`, `action` (`publish` | `schedule`),
`post_id`, `content_sha256`, `iat`, `exp` (durée de vie : 24 h au plus), `publish_at` (`AAAA-MM-JJTHH:MM:SSZ` pour
`schedule`, `null` sinon), `approved_by`.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any

from .signature import SECRET_LONGUEUR_MIN, SecretInvalide

PREFIXE_JETON = "v1"
PREFIXE_MAC = b"OPSYS-APPROVAL-V1\n"
INFO_CLE = b"opsys-connect/approval/v1\x01"
DUREE_MAX_S = 86400
ACTIONS = ("publish", "schedule")
CHAMPS = (
    "v",
    "approval_id",
    "site_id",
    "action",
    "post_id",
    "content_sha256",
    "iat",
    "exp",
    "publish_at",
    "approved_by",
)

MOTIF_APPROBATION = re.compile(r"[A-Za-z0-9_-]{8,64}")
MOTIF_SITE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
MOTIF_EMPREINTE = re.compile(r"[0-9a-f]{64}")
MOTIF_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def cle_approbation(secret: str) -> bytes:
    octets = secret.encode("utf-8") if isinstance(secret, str) else b""
    if len(octets) < SECRET_LONGUEUR_MIN:
        raise SecretInvalide(f"secret partagé de {SECRET_LONGUEUR_MIN} octets au moins exigé")
    return hmac.new(octets, INFO_CLE, hashlib.sha256).digest()


def b64url(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).decode("ascii").rstrip("=")


def mac(secret: str, charge_b64: str) -> str:
    return hmac.new(cle_approbation(secret), PREFIXE_MAC + charge_b64.encode("ascii"), hashlib.sha256).hexdigest()


def valider_charge(charge: dict[str, Any]) -> None:
    """Refuse d'avance ce que le plugin refuserait : on n'émet jamais un jeton mal formé."""
    if set(charge) != set(CHAMPS):
        raise ValueError(f"charge du jeton : champs exacts {CHAMPS} attendus")
    if charge["v"] != 1 or type(charge["v"]) is not int:
        raise ValueError("charge du jeton : v=1")
    for nom, motif in (
        ("approval_id", MOTIF_APPROBATION),
        ("site_id", MOTIF_SITE),
        ("content_sha256", MOTIF_EMPREINTE),
    ):
        if not isinstance(charge[nom], str) or not motif.fullmatch(charge[nom]):
            raise ValueError(f"charge du jeton : {nom} invalide")
    if charge["action"] not in ACTIONS:
        raise ValueError("charge du jeton : action inconnue")
    for nom in ("post_id", "iat", "exp"):
        if type(charge[nom]) is not int or charge[nom] <= 0:
            raise ValueError(f"charge du jeton : {nom} entier positif attendu")
    if not 0 < charge["exp"] - charge["iat"] <= DUREE_MAX_S:
        raise ValueError(f"charge du jeton : durée de vie de 1 à {DUREE_MAX_S} s")
    planifie = charge["action"] == "schedule"
    instant = charge["publish_at"]
    if planifie != (isinstance(instant, str) and MOTIF_INSTANT.fullmatch(instant) is not None):
        raise ValueError("charge du jeton : publish_at exigé (AAAA-MM-JJTHH:MM:SSZ) pour schedule, et seulement lui")
    if not planifie and instant is not None:
        raise ValueError("charge du jeton : publish_at interdit hors schedule")
    approbateur = charge["approved_by"]
    if not isinstance(approbateur, str) or not 1 <= len(approbateur) <= 64:
        raise ValueError("charge du jeton : approved_by de 1 à 64 caractères")


def emettre(secret: str, charge: dict[str, Any]) -> str:
    """Le jeton signé pour `charge` (dictionnaire aux champs exacts de `CHAMPS`)."""
    valider_charge(charge)
    texte = json.dumps(charge, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    charge_b64 = b64url(texte.encode("utf-8"))
    return f"{PREFIXE_JETON}.{charge_b64}.{mac(secret, charge_b64)}"
