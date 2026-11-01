"""Minimisation des renseignements personnels (Loi 25) à l'entrée des signaux : le masqueur d'observabilité d'OPSYS.

Tout texte tiré d'un fournisseur (requête de recherche, URL de page avec paramètres, libellé de campagne, extrait
d'avis)
passe par le masqueur `opsys.observabilite.pii` AVANT d'entrer dans un fait : courriels, téléphones, NAS, cartes,
adresses,
codes postaux, NEQ, secrets sont remplacés par des jetons stables `[[ETIQUETTE:hmac12]]` qui permettent de corréler sans
exposer. Les paramètres d'URL sont retirés (une page de signal est identifiée par son chemin, jamais par sa chaîne de
requête). Le nom d'un auteur d'avis n'entre jamais : il n'est pas lu.

Limites dites sans euphémisme (celles du masqueur à motifs) : un nom propre SANS civilité n'est pas détecté, une adresse
écrite en mots non plus. C'est pourquoi aucun texte libre d'un tiers n'est conservé par défaut et que tout texte
conservé
est marqué `non_fiable`.

Fail-closed : sans masqueur, aucun tour d'ingestion ne démarre.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any

from opsys.observabilite import cle_locale
from opsys.observabilite.pii import MasqueurMotifs, MasqueurPII

from .erreurs import refus

_CONTROLES = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁦-⁩]")


def masqueur_local() -> MasqueurPII:
    """Le masqueur de motifs de l'instance (clé locale `pii/v1`, créée au besoin). Hors transaction métier."""
    return MasqueurMotifs(cle_locale.deriver(cle_locale.charger(creer=True), "pii/v1"))


def exiger_masqueur(masqueur: Any) -> MasqueurPII:
    if masqueur is None or not isinstance(masqueur, MasqueurPII):
        raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "masqueur de renseignements personnels obligatoire", 500)
    return masqueur


def texte_minimise(masqueur: MasqueurPII, texte: Any, maximum: int) -> str:
    """Texte NFC, sans caractère de contrôle ni de direction cachée, masqué, coupé à `maximum` caractères. Un jeton de
    masquage n'est jamais coupé en deux."""
    if not isinstance(texte, str):
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "texte attendu dans la réponse du fournisseur", 502)
    propre = _CONTROLES.sub(" ", unicodedata.normalize("NFC", texte)).strip()
    masque = masqueur.masquer(propre[:2000]).texte
    if len(masque) <= maximum:
        return masque
    coupe = masque[:maximum]
    dernier = coupe.rfind("[[")
    if dernier != -1 and "]]" not in coupe[dernier:]:
        coupe = coupe[:dernier]
    return coupe.rstrip()


def chemin_de_page(masqueur: MasqueurPII, url: Any, maximum: int = 200) -> str:
    """Le chemin d'une URL de page, sans schéma d'autorité, sans paramètres ni fragment, masqué. Une valeur qui
    n'est pas
    une URL http(s) est rendue minimisée telle quelle (certaines sources donnent déjà un chemin)."""
    if not isinstance(url, str):
        raise refus("REJ-SIGNAUX-REPONSE-INVALIDE", "URL attendue dans la réponse du fournisseur", 502)
    morceaux = urllib.parse.urlsplit(url.strip())
    chemin = morceaux.path or "/"
    base = (
        f"{morceaux.scheme}://{morceaux.hostname}{chemin}"
        if morceaux.scheme in ("http", "https") and morceaux.hostname
        else chemin
    )
    return texte_minimise(masqueur, base, maximum)


__all__ = ["chemin_de_page", "exiger_masqueur", "masqueur_local", "texte_minimise"]
