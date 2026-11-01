"""Vérificateur de RÉFÉRENCE du protocole `opsys-connect-sig/v1` et du jeton `opsys-approval/v1`.

Écrit pour les tests, à partir de la spécification seulement (docstrings de `m7_marketing.wordpress.signature` et
`jeton`), SANS importer aucun de ces modules : un défaut de lecture de la spécification n'est pas partagé entre le
signataire
et son vérificateur. Il joue le rôle du plugin PHP dans les tests (le plugin, lui, n'a jamais été exécuté) et se
mesure aux
mêmes vecteurs fixes que lui (`contracts/opsys-connect-vecteurs.v1.json`).

Il garde aussi l'ÉTAT que le plugin garde en base : la mémoire des nonces et des identifiants d'approbation, à usage
unique,
avec expiration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

FENETRE = 300
DUREE_MAX = 86400
TOLERANCE_EMISSION = 60


class MemoireUsageUnique:
    """Le magasin à usage unique : `consommer` est vrai la première fois seulement, tant que l'entrée n'a pas expiré."""

    def __init__(self) -> None:
        self.lignes: dict[tuple[str, str], int] = {}

    def purger(self, maintenant: int) -> None:
        self.lignes = {cle: exp for cle, exp in self.lignes.items() if exp >= maintenant}

    def consommer(self, genre: str, valeur: str, expire_a: int, maintenant: int) -> bool:
        self.purger(maintenant)
        cle = (genre, hashlib.sha256(valeur.encode()).hexdigest())
        if cle in self.lignes:
            return False
        self.lignes[cle] = expire_a
        return True


def verifier_requete(
    secret: str,
    methode: str,
    route: str,
    corps: bytes,
    en_tetes: dict[str, str],
    maintenant: int,
) -> str:
    plis = {k.lower(): v for k, v in en_tetes.items()}
    horodatage = plis.get("x-opsys-timestamp")
    nonce = plis.get("x-opsys-nonce")
    recue = plis.get("x-opsys-signature")
    if horodatage is None or nonce is None or recue is None:
        return "EN_TETE_MANQUANT"
    if re.fullmatch(r"[0-9]{10}", horodatage) is None:
        return "HORODATAGE_INVALIDE"
    if re.fullmatch(r"[A-Za-z0-9_-]{16,64}", nonce) is None:
        return "NONCE_INVALIDE"
    if re.fullmatch(r"v1=[0-9a-f]{64}", recue) is None:
        return "SIGNATURE_MALFORMEE"
    if abs(maintenant - int(horodatage)) > FENETRE:
        return "HORS_FENETRE"
    canonique = "\n".join(
        [
            "OPSYS-CONNECT-V1",
            methode.upper(),
            route,
            horodatage,
            nonce,
            hashlib.sha256(corps).hexdigest(),
        ]
    )
    calculee = "v1=" + hmac.new(secret.encode("utf-8"), canonique.encode("utf-8"), hashlib.sha256).hexdigest()
    return "OK" if hmac.compare_digest(calculee, recue) else "SIGNATURE_INVALIDE"


def cle_approbation(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), b"opsys-connect/approval/v1" + bytes([1]), hashlib.sha256).digest()


def _b64url_decode(texte: str) -> bytes | None:
    if re.fullmatch(r"[A-Za-z0-9_-]+", texte) is None:
        return None
    try:
        octets = base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))
    except ValueError:
        return None
    return octets if base64.urlsafe_b64encode(octets).decode().rstrip("=") == texte else None


def _est_entier(valeur: object) -> bool:
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def verifier_jeton(
    secret: str,
    jeton: str,
    *,
    site_id_attendu: str,
    post_id_attendu: int,
    empreinte_courante: str,
    maintenant: int,
    actions_permises: tuple[str, ...] = ("publish", "schedule"),
) -> tuple[str, dict | None]:
    parties = jeton.split(".")
    if len(parties) != 3 or parties[0] != "v1":
        return "JETON_MALFORME", None
    charge_b64, mac = parties[1], parties[2]
    if re.fullmatch(r"[0-9a-f]{64}", mac) is None or not charge_b64:
        return "JETON_MALFORME", None
    attendu = hmac.new(
        cle_approbation(secret), b"OPSYS-APPROVAL-V1\n" + charge_b64.encode("ascii", "replace"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(attendu, mac):
        return "JETON_SIGNATURE_INVALIDE", None
    octets = _b64url_decode(charge_b64)
    if octets is None:
        return "JETON_MALFORME", None
    try:
        charge = json.loads(octets.decode("utf-8"))
    except ValueError:
        return "JETON_MALFORME", None
    if not isinstance(charge, dict):
        return "JETON_MALFORME", None
    champs = {
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
    }
    if set(charge) != champs:
        return "JETON_CHAMP_INVALIDE", None
    if not _est_entier(charge["v"]) or charge["v"] != 1:
        return "JETON_CHAMP_INVALIDE", None
    textes = (
        ("approval_id", r"[A-Za-z0-9_-]{8,64}"),
        ("site_id", r"[a-z0-9][a-z0-9._-]{2,63}"),
        ("content_sha256", r"[0-9a-f]{64}"),
    )
    for nom, motif in textes:
        if not isinstance(charge[nom], str) or re.fullmatch(motif, charge[nom]) is None:
            return "JETON_CHAMP_INVALIDE", None
    if charge["action"] not in ("publish", "schedule"):
        return "JETON_CHAMP_INVALIDE", None
    for nom in ("post_id", "iat", "exp"):
        if not _est_entier(charge[nom]) or charge[nom] <= 0:
            return "JETON_CHAMP_INVALIDE", None
    instant = charge["publish_at"]
    instant_valide = (
        isinstance(instant, str)
        and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", instant) is not None
    )
    if charge["action"] == "schedule" and not instant_valide:
        return "JETON_CHAMP_INVALIDE", None
    if charge["action"] == "publish" and instant is not None:
        return "JETON_CHAMP_INVALIDE", None
    if not isinstance(charge["approved_by"], str) or not 1 <= len(charge["approved_by"]) <= 64:
        return "JETON_CHAMP_INVALIDE", None
    vie = charge["exp"] - charge["iat"]
    if vie <= 0 or vie > DUREE_MAX:
        return "JETON_DUREE_EXCESSIVE", None
    if charge["exp"] <= maintenant:
        return "JETON_EXPIRE", None
    if charge["iat"] > maintenant + TOLERANCE_EMISSION:
        return "JETON_EMIS_DANS_LE_FUTUR", None
    if charge["site_id"] != site_id_attendu:
        return "JETON_SITE_DIFFERENT", None
    if charge["post_id"] != post_id_attendu:
        return "JETON_ARTICLE_DIFFERENT", None
    if not hmac.compare_digest(charge["content_sha256"], empreinte_courante):
        return "JETON_EMPREINTE_DIFFERENTE", None
    if charge["action"] not in actions_permises:
        return "JETON_ACTION_NON_PERMISE", None
    if charge["action"] == "schedule":
        from datetime import UTC, datetime

        try:
            prevu = int(datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())
        except ValueError:
            prevu = 0
        if prevu <= maintenant:
            return "JETON_PLANIFICATION_INVALIDE", None
    return "OK", charge


def empreinte_contenu(champs: dict[str, str]) -> str:
    corps = "opsys-content/v1\n"
    for nom in ("type", "titre", "contenu", "extrait", "slug", "image_a_la_une_sha256"):
        corps += f"{nom}:{len(champs[nom].encode('utf-8'))}:{champs[nom]}\n"
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()
