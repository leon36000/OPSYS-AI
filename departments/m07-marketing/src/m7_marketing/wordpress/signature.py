"""Signature des requêtes OPSYS -> plugin WordPress « OPSYS Connect » (protocole `opsys-connect-sig/v1`).

Le plugin (PHP, GPLv2+, `integrations/wordpress/opsys-connect/`) et ce module ne partagent aucun code : ils partagent
une SPÉCIFICATION et des VECTEURS DE TEST fixes (`contracts/opsys-connect-vecteurs.v1.json`) que les deux doivent
respecter octet pour octet. Rien ici n'importe le plugin, et le plugin n'importe rien d'ici.

Chaîne canonique (UTF-8, séparateurs LF, aucun LF final) :

    OPSYS-CONNECT-V1
    <MÉTHODE en majuscules>
    <route REST, ex. /opsys-connect/v1/drafts : sans « /wp-json », sans paramètre de requête>
    <horodatage : secondes UNIX, 10 chiffres>
    <nonce : 16 à 64 caractères [A-Za-z0-9_-]>
    <SHA-256 hexadécimal minuscule des octets exacts du corps (corps vide : SHA-256 de la chaîne vide)>

Signature : `v1=` + HMAC-SHA256(secret partagé en UTF-8, chaîne canonique) en hexadécimal minuscule. En-têtes :
`X-OPSYS-Key-Id`, `X-OPSYS-Timestamp`, `X-OPSYS-Nonce`, `X-OPSYS-Signature`. Fenêtre de ±300 s ; le nonce n'est
valable qu'une fois (mémoire d'état côté plugin). Les requêtes n'ont aucun paramètre de
requête : le plugin en refuse un.

Ce module ne fait que SIGNER. Le vérificateur de référence vit dans les tests
(`tests/wordpress/reference_verificateur.py`),
écrit à part pour que les deux ne partagent pas leurs erreurs.

Module pur : aucune entrée-sortie, aucune horloge (le moment est un argument).
"""

from __future__ import annotations

import hashlib
import hmac
import re

PREFIXE_CANONIQUE = "OPSYS-CONNECT-V1"
VERSION_SIGNATURE = "v1"
FENETRE_S = 300
SECRET_LONGUEUR_MIN = 32

EN_TETE_CLE = "X-OPSYS-Key-Id"
EN_TETE_HORODATAGE = "X-OPSYS-Timestamp"
EN_TETE_NONCE = "X-OPSYS-Nonce"
EN_TETE_SIGNATURE = "X-OPSYS-Signature"

# `fullmatch` partout : `$` accepterait un LF final (le plugin PHP utilise le modificateur /D pour la même raison).
MOTIF_HORODATAGE = re.compile(r"[0-9]{10}")
MOTIF_NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")
MOTIF_SIGNATURE = re.compile(r"v1=[0-9a-f]{64}")
MOTIF_CLE = re.compile(r"[A-Za-z0-9._-]{1,64}")

REJ_SECRET_COURT = "REJ-WP-SECRET-TROP-COURT"


class SecretInvalide(ValueError):
    """Le secret partagé est trop court : refusé avant toute signature (message sans la valeur)."""


def empreinte_corps(corps: bytes) -> str:
    return hashlib.sha256(corps).hexdigest()


def chaine_canonique(methode: str, route: str, horodatage: str, nonce: str, corps: bytes) -> str:
    return "\n".join((PREFIXE_CANONIQUE, methode.upper(), route, horodatage, nonce, empreinte_corps(corps)))


def _cle(secret: str) -> bytes:
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < SECRET_LONGUEUR_MIN:
        raise SecretInvalide(f"secret partagé de {SECRET_LONGUEUR_MIN} octets au moins exigé")
    return secret.encode("utf-8")


def signature(secret: str, methode: str, route: str, horodatage: str, nonce: str, corps: bytes) -> str:
    """`v1=<hex>` pour ces éléments exacts."""
    canonique = chaine_canonique(methode, route, horodatage, nonce, corps).encode("utf-8")
    return f"{VERSION_SIGNATURE}=" + hmac.new(_cle(secret), canonique, hashlib.sha256).hexdigest()


def en_tetes_signes(
    secret: str,
    cle_id: str,
    methode: str,
    route: str,
    horodatage: int,
    nonce: str,
    corps: bytes,
) -> dict[str, str]:
    """Les quatre en-têtes d'une requête signée. Refuse d'avance ce que le plugin refuserait (format du nonce, de la
    clé, de l'horodatage) : une requête mal formée ne part jamais."""
    stamp = str(horodatage)
    if not MOTIF_HORODATAGE.fullmatch(stamp):
        raise ValueError("horodatage : 10 chiffres (secondes UNIX) attendus")
    if not MOTIF_NONCE.fullmatch(nonce):
        raise ValueError("nonce : 16 à 64 caractères [A-Za-z0-9_-] attendus")
    if not MOTIF_CLE.fullmatch(cle_id):
        raise ValueError("identifiant de clé invalide")
    return {
        EN_TETE_CLE: cle_id,
        EN_TETE_HORODATAGE: stamp,
        EN_TETE_NONCE: nonce,
        EN_TETE_SIGNATURE: signature(secret, methode, route, stamp, nonce, corps),
    }
