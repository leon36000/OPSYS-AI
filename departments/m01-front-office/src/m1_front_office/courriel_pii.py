"""Les renseignements personnels d'un courriel reçu (adresse de l'expéditeur, objet) : scellés, effaçables, sans
casser la chaîne du registre.

Le registre de M1 est append-only et hash-chaîné : le haché d'une ligne couvre tous ses champs, donc on ne peut ni
supprimer ni réécrire une ligne sans rompre la chaîne. La rétention Loi 25 passe donc par le CHIFFREMENT : à la
réception, l'adresse et l'objet sont chiffrés (AES-256-GCM) avec une clé PROPRE à ce courriel (`cles_chiffrement`,
portée `m01-front-office/courriel`) ; la ligne du registre ne porte que l'enveloppe (nonce, chiffré, empreinte du
chiffré),
que la chaîne couvre. À l'échéance déclarée du compte, l'exécuteur `retention.cles` du planificateur détruit la clé :
la chaîne reste valide, l'adresse est irrécupérable. Les lignes écrites AVANT ce changement portent l'adresse en clair
et ne sont pas purgeables (elles sont comptées par `opsys.retention`, jamais réécrites).

Limites dites : le texte neutralisé du courriel (`contenu_filtre` du signal) et le contact du lead restent au registre ;
ils appartiennent au pipeline commun à tous les canaux et à la qualification, et leur effacement est une décision
distincte (docs/architecture/PLANIFICATION.md §6).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from opsys import cles_chiffrement, stockage
from opsys.retention import echeances

PORTEE = echeances.PORTEE_M1_COURRIEL
VERSION = 1


def _cnx() -> Any:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ValueError("REJ-M1-COURRIEL-BASE: la clé d'un courriel vit dans la base de l'instance (appel dans une "
                         "transaction)")
    return cnx


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ValueError("REJ-M1-COURRIEL-CHIFFREMENT: l'extra « ingestion » (cryptography) est requis") from None
    return AESGCM


def _aad(signal_id: str) -> bytes:
    return f"opsys-m1-courriel:v{VERSION}:{signal_id}".encode()


def _epoch(horodatage: str) -> int:
    import datetime as dt

    return int(dt.datetime.fromisoformat(horodatage.replace("Z", "+00:00")).timestamp())


def sceller(signal_id: str, expediteur: str, objet: str, *, retention_jours: int, recu_le: str) -> dict[str, Any]:
    """L'enveloppe à inscrire au registre, et l'échéance de destruction de sa clé (même transaction)."""
    cnx = _cnx()
    quand = echeances.instant(_epoch(recu_le))
    cle = cles_chiffrement.obtenir_ou_creer(cnx, PORTEE, signal_id, quand)
    nonce = os.urandom(12)
    chiffre = _aesgcm()(cle).encrypt(nonce, json.dumps({"expediteur": expediteur, "objet": objet},
                                                       ensure_ascii=False).encode(), _aad(signal_id))
    echeances.enregistrer(cnx, "m1_courriel", signal_id.replace("courriel:", "m1:", 1), signal_id,
                          _epoch(recu_le) + retention_jours * 86400, quand)
    return {"v": VERSION, "nonce": base64.b64encode(nonce).decode(), "chiffre": base64.b64encode(chiffre).decode(),
            "sha256": hashlib.sha256(chiffre).hexdigest()}


def ouvrir(ligne: dict[str, Any], *, exiger: bool = False) -> dict[str, Any]:
    """Une COPIE de la ligne de réception avec `expediteur` et `objet` en clair ; clé détruite : les deux valent
    `None` et `efface` est vrai. `exiger` : refus typé au lieu de rendre une ligne effacée. Une ligne ancienne (adresse
    en clair) est rendue telle quelle."""
    pii = ligne.get("pii")
    if pii is None:
        return dict(ligne)
    cle = cles_chiffrement.lire(_cnx(), PORTEE, ligne["signal_id"])
    if cle is None:
        if exiger:
            raise ValueError("REJ-M1-COURRIEL-EFFACE: l'adresse de ce courriel a été effacée à l'échéance de "
                             "rétention (Loi 25)")
        return {**ligne, "expediteur": None, "objet": None, "efface": True}
    try:
        clair = json.loads(_aesgcm()(cle).decrypt(base64.b64decode(pii["nonce"]), base64.b64decode(pii["chiffre"]),
                                                  _aad(ligne["signal_id"])))
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 — InvalidTag : enveloppe déplacée ou altérée
        raise ValueError("REJ-M1-COURRIEL-ALTERE: l'enveloppe de l'adresse ne s'authentifie pas") from None
    return {**ligne, "expediteur": clair["expediteur"], "objet": clair["objet"], "efface": False}
