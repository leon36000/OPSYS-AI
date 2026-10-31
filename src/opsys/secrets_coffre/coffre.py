"""Coffre de secrets chiffré (DECISIONS-ARCHITECTE r1 §6) : clés API des connecteurs et des fournisseurs.

Garanties :
- **chiffrement au repos** : AES-256-GCM en enveloppe. Chaque version d'un secret a sa clé de donnée aléatoire
  (32 octets), elle-même chiffrée par une KEK dérivée de la clé maîtresse (`cle_maitresse`, hors base). Les
  données associées (AAD) lient chaque chiffré à son nom, sa version et l'algorithme : un chiffré déplacé ne se
  déchiffre pas ;
- **jamais en clair hors du serveur** : aucune fonction ne rend une valeur à un appelant distant. Les agents
  reçoivent un **jeton opaque** (`emettre_jeton`), lié à un porteur et à un usage ; seul `utiliser`, côté serveur
  et au moment de l'appel, le résout en valeur, enregistrée pour masquage le temps de l'appel ;
- **rotation** : nouvelle version active ; les octets chiffrés de l'ancienne sont détruits dans la même
  transaction ; les jetons suivent le nom, donc la nouvelle valeur ;
- **révocation immédiate** : état `revoque`, octets chiffrés détruits (SQLite `secure_delete`), jetons révoqués ;
  toute résolution ultérieure est refusée. Un nom révoqué n'est jamais réutilisé ;
- **journal d'accès** append-only (`coffre_acces`) : chaque définition, rotation, révocation, émission de jeton,
  résolution (acceptée ou refusée) et tentative d'export ; ni valeur, ni jeton, ni empreinte de valeur ;
- **export impossible en clair** : `exporter` refuse toujours (et le journalise).

Les opérations d'administration exigent une personne active `nathan_owner` ou `admin` (relue en base).
Limite : les copies antérieures de la base (WAL déjà sauvegardé, sauvegardes, instantanés) ne sont pas
nettoyées par la révocation ; la clé maîtresse doit alors être tournée (`rechiffrer`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from .. import identite
from ..stockage.schema import COFFRE_ACCES, COFFRE_JETONS, COFFRE_SECRETS, COFFRE_VERSIONS
from . import cle_maitresse, masquage
from .cle_maitresse import CleMaitresse
from .erreurs import CoffreErreur

ALGORITHME = "aes-256-gcm/enveloppe/v1"
PREFIXE_JETON = "opsys-jeton:v1:"
SERVICES: tuple[str, ...] = (
    "google", "search_console", "google_ads", "google_analytics", "google_business", "meta", "linkedin", "tiktok",
    "pinterest", "youtube", "quickbooks", "microsoft", "fournisseur_modele", "livekit", "twilio", "autre",
)
ROLES_ADMIN = frozenset({"nathan_owner", "admin"})
VALEUR_MAX = 16384
DUREE_JETON_MIN, DUREE_JETON_MAX = 60, 30 * 24 * 3600
_NOM = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_PORTEUR = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,79}$")
_USAGE = re.compile(r"^[a-z_]{2,24}:[a-z0-9._-]{2,80}$")
_JETON = re.compile(r"^opsys-jeton:v1:[A-Za-z0-9_-]{43}$")

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]


def _instant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _aes():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise CoffreErreur("COFFRE_CHIFFREMENT_INDISPONIBLE",
                           "primitive AES-GCM absente : installer l'extra ingestion (cryptography)", 503) from None
    return AESGCM, InvalidTag


def _aad(nom: str, version: int, partie: str) -> bytes:
    return f"opsys-coffre:{ALGORITHME}:{nom}:{version}:{partie}".encode("ascii")


def _journal(cnx: Connection, nom: str, action: str, acteur: str, resultat: str = "ok", *,
             usage: str | None = None, code: str | None = None) -> None:
    cnx.execute(insert(COFFRE_ACCES).values(quand=_instant(), nom=nom[:80], action=action, acteur=acteur[:80],
                                            usage=usage, resultat=resultat, code=code))


def _admin(cnx: Connection, acteur: str) -> None:
    personne = identite.personne_active(cnx, acteur) if isinstance(acteur, str) else None
    if personne is None or not personne.roles.intersection(ROLES_ADMIN):
        raise CoffreErreur("COFFRE_ADMIN_REQUIS", "administrateur actif requis", 403)


def _nom(nom: Any) -> str:
    if not isinstance(nom, str) or not _NOM.fullmatch(nom):
        raise CoffreErreur("COFFRE_NOM_INVALIDE", "nom de secret invalide (minuscules, chiffres, . _ -)", 422)
    return nom


def _valeur(valeur: Any) -> bytes:
    if (not isinstance(valeur, str) or not valeur.strip() or len(valeur) > VALEUR_MAX
            or any(c in valeur for c in "\x00\r\n")):
        raise CoffreErreur("COFFRE_VALEUR_INVALIDE",
                           f"valeur vide, multiligne ou trop longue ({VALEUR_MAX} caractères maximum)", 422)
    return valeur.encode("utf-8")


def _ligne(cnx: Connection, nom: str) -> Mapping[str, Any] | None:
    return cnx.execute(select(COFFRE_SECRETS).where(COFFRE_SECRETS.c.nom == nom)).mappings().first()


def _chiffrer(cle: CleMaitresse, nom: str, version: int, clair: bytes) -> dict[str, Any]:
    aesgcm, _ = _aes()
    donnee = secrets.token_bytes(32)
    nonce_valeur, nonce_cle = secrets.token_bytes(12), secrets.token_bytes(12)
    return {
        "algorithme": ALGORITHME, "empreinte_cle_maitresse": cle.empreinte,
        "nonce_valeur": nonce_valeur, "valeur_chiffree": aesgcm(donnee).encrypt(nonce_valeur, clair,
                                                                               _aad(nom, version, "valeur")),
        "nonce_cle": nonce_cle, "cle_enveloppee": aesgcm(cle.kek).encrypt(nonce_cle, donnee, _aad(nom, version, "cle")),
    }


def _ouvrir_cle(cle: CleMaitresse, ligne: Mapping[str, Any]) -> bytes:
    aesgcm, invalide = _aes()
    if ligne["empreinte_cle_maitresse"] != cle.empreinte:
        raise CoffreErreur("COFFRE_CLE_MAITRESSE_DIFFERENTE",
                           "secret enveloppé par une autre clé maîtresse : rechiffrer avant usage", 503)
    try:
        return aesgcm(cle.kek).decrypt(ligne["nonce_cle"], ligne["cle_enveloppee"],
                                       _aad(ligne["nom"], ligne["version"], "cle"))
    except invalide:
        raise CoffreErreur("COFFRE_CHIFFRE_CORROMPU", "secret chiffré illisible ; aucune valeur rendue", 503) from None


def _dechiffrer(cle: CleMaitresse, ligne: Mapping[str, Any]) -> str:
    aesgcm, invalide = _aes()
    donnee = _ouvrir_cle(cle, ligne)
    try:
        clair = aesgcm(donnee).decrypt(ligne["nonce_valeur"], ligne["valeur_chiffree"],
                                       _aad(ligne["nom"], ligne["version"], "valeur"))
    except invalide:
        raise CoffreErreur("COFFRE_CHIFFRE_CORROMPU", "secret chiffré illisible ; aucune valeur rendue", 503) from None
    return clair.decode("utf-8")


def _purger(cnx: Connection, nom: str, etat: str, *, version: int | None = None) -> None:
    if cnx.dialect.name == "sqlite":
        cnx.exec_driver_sql("PRAGMA secure_delete=ON")
    condition = (COFFRE_VERSIONS.c.nom == nom) & (COFFRE_VERSIONS.c.etat == "active")
    if version is not None:
        condition &= COFFRE_VERSIONS.c.version == version
    cnx.execute(update(COFFRE_VERSIONS).where(condition).values(
        etat=etat, valeur_chiffree=None, cle_enveloppee=None, nonce_cle=None, nonce_valeur=None, purge_le=_instant(),
    ))


def avec_journal(fabrique: FabriqueConnexion, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Exécute une opération du coffre dans sa propre transaction ; un refus y est journalisé ET conservé
    (la transaction est validée avant de relancer l'erreur). Chaque opération vérifie tout avant d'écrire."""
    erreur: CoffreErreur | None = None
    with fabrique() as cnx:
        try:
            resultat = operation(cnx, *args, **kwargs)
        except CoffreErreur as exc:
            nom = kwargs.get("nom") if isinstance(kwargs.get("nom"), str) else "<inconnu>"
            _journal(cnx, nom, getattr(operation, "__name__", "operation"), str(kwargs.get("acteur", "?")),
                     "refus", code=exc.code)
            erreur = exc
    if erreur is not None:
        raise erreur
    return resultat


def definir(cnx: Connection, *, acteur: str, nom: str, service: str, valeur: str,
            cle: CleMaitresse | None = None) -> dict[str, Any]:
    """Saisie unique d'un nouveau secret. Rend ses métadonnées, jamais la valeur."""
    _admin(cnx, acteur)
    nom = _nom(nom)
    if service not in SERVICES:
        raise CoffreErreur("COFFRE_SERVICE_INVALIDE", f"service parmi : {', '.join(SERVICES)}", 422)
    clair = _valeur(valeur)
    existant = _ligne(cnx, nom)
    if existant is not None:
        code = "COFFRE_SECRET_REVOQUE" if existant["etat"] == "revoque" else "COFFRE_SECRET_EXISTE"
        raise CoffreErreur(code, "nom déjà utilisé : rotation pour changer la valeur ; un nom révoqué est clos")
    cle = cle or cle_maitresse.charger()
    chiffre = _chiffrer(cle, nom, 1, clair)
    instant = _instant()
    cnx.execute(insert(COFFRE_SECRETS).values(nom=nom, service=service, etat="actif", version_active=1,
                                              cree_le=instant, cree_par=acteur, modifie_le=instant, modifie_par=acteur))
    cnx.execute(insert(COFFRE_VERSIONS).values(nom=nom, version=1, etat="active", cree_le=instant, **chiffre))
    _journal(cnx, nom, "definir", acteur)
    return metadonnees(cnx, nom)


def rotation(cnx: Connection, *, acteur: str, nom: str, valeur: str, cle: CleMaitresse | None = None) -> dict[str, Any]:
    _admin(cnx, acteur)
    nom = _nom(nom)
    clair = _valeur(valeur)
    ligne = _ligne(cnx, nom)
    if ligne is None:
        raise CoffreErreur("COFFRE_SECRET_INCONNU", "secret inconnu", 404)
    if ligne["etat"] != "actif":
        raise CoffreErreur("COFFRE_SECRET_REVOQUE", "secret révoqué : aucune rotation")
    cle = cle or cle_maitresse.charger()
    version = ligne["version_active"] + 1
    chiffre = _chiffrer(cle, nom, version, clair)
    _purger(cnx, nom, "remplacee")
    instant = _instant()
    cnx.execute(insert(COFFRE_VERSIONS).values(nom=nom, version=version, etat="active", cree_le=instant, **chiffre))
    cnx.execute(update(COFFRE_SECRETS).where(COFFRE_SECRETS.c.nom == nom).values(
        version_active=version, modifie_le=instant, modifie_par=acteur))
    _journal(cnx, nom, "rotation", acteur)
    return metadonnees(cnx, nom)


def revoquer(cnx: Connection, *, acteur: str, nom: str) -> dict[str, Any]:
    _admin(cnx, acteur)
    nom = _nom(nom)
    ligne = _ligne(cnx, nom)
    if ligne is None:
        raise CoffreErreur("COFFRE_SECRET_INCONNU", "secret inconnu", 404)
    if ligne["etat"] == "revoque":
        return metadonnees(cnx, nom)
    _purger(cnx, nom, "revoquee")
    instant = _instant()
    cnx.execute(update(COFFRE_SECRETS).where(COFFRE_SECRETS.c.nom == nom).values(
        etat="revoque", version_active=None, revoque_le=instant, revoque_par=acteur, modifie_le=instant,
        modifie_par=acteur))
    cnx.execute(update(COFFRE_JETONS).where(COFFRE_JETONS.c.nom == nom).values(revoque=True))
    _journal(cnx, nom, "revocation", acteur)
    return metadonnees(cnx, nom)


def metadonnees(cnx: Connection, nom: str) -> dict[str, Any]:
    ligne = _ligne(cnx, nom)
    if ligne is None:
        raise CoffreErreur("COFFRE_SECRET_INCONNU", "secret inconnu", 404)
    jetons = cnx.execute(select(func.count()).select_from(COFFRE_JETONS).where(
        (COFFRE_JETONS.c.nom == nom) & COFFRE_JETONS.c.revoque.is_(False)
        & (COFFRE_JETONS.c.expire_epoch > int(time.time())))).scalar_one()
    return {
        "nom": ligne["nom"], "service": ligne["service"], "etat": ligne["etat"], "version": ligne["version_active"],
        "algorithme": ALGORITHME, "cree_le": ligne["cree_le"], "cree_par": ligne["cree_par"],
        "modifie_le": ligne["modifie_le"], "modifie_par": ligne["modifie_par"], "revoque_le": ligne["revoque_le"],
        "revoque_par": ligne["revoque_par"], "jetons_actifs": jetons, "valeur": "non affichable",
    }


def lister(cnx: Connection) -> list[dict[str, Any]]:
    noms = cnx.execute(select(COFFRE_SECRETS.c.nom).order_by(COFFRE_SECRETS.c.nom)).scalars().all()
    return [metadonnees(cnx, nom) for nom in noms]


def journal(cnx: Connection, nom: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    requete = select(COFFRE_ACCES).order_by(COFFRE_ACCES.c.id.desc()).limit(max(1, min(limite, 500)))
    if nom is not None:
        requete = requete.where(COFFRE_ACCES.c.nom == nom)
    return [dict(r) for r in cnx.execute(requete).mappings()]


def exporter(cnx: Connection, *, acteur: str, nom: str | None = None) -> None:
    """Toujours refusé : aucune valeur ne sort du coffre en clair (ni par la console, ni par la CLI)."""
    _journal(cnx, nom or "*", "export", str(acteur), "refus", code="COFFRE_EXPORT_INTERDIT")
    raise CoffreErreur("COFFRE_EXPORT_INTERDIT", "export en clair interdit : redéfinir le secret à la source", 403)


def emettre_jeton(cnx: Connection, *, acteur: str, nom: str, porteur: str, usage: str, duree_s: int,
                  maintenant: float | None = None) -> str:
    """Jeton opaque pour un agent : rendu UNE fois, seule son empreinte SHA-256 est conservée."""
    _admin(cnx, acteur)
    nom = _nom(nom)
    if not isinstance(porteur, str) or not _PORTEUR.fullmatch(porteur):
        raise CoffreErreur("COFFRE_PORTEUR_INVALIDE", "porteur invalide", 422)
    if not isinstance(usage, str) or not _USAGE.fullmatch(usage):
        raise CoffreErreur("COFFRE_USAGE_INVALIDE", "usage invalide (ex. fournisseur:llm.mistral-api)", 422)
    if type(duree_s) is not int or not DUREE_JETON_MIN <= duree_s <= DUREE_JETON_MAX:
        raise CoffreErreur("COFFRE_DUREE_INVALIDE", "durée de jeton entre 60 s et 30 jours", 422)
    ligne = _ligne(cnx, nom)
    if ligne is None or ligne["etat"] != "actif":
        raise CoffreErreur("COFFRE_SECRET_INDISPONIBLE", "secret inconnu ou révoqué", 409)
    jeton = PREFIXE_JETON + secrets.token_urlsafe(32)
    instant = int(time.time() if maintenant is None else maintenant)
    cnx.execute(insert(COFFRE_JETONS).values(
        empreinte=hashlib.sha256(jeton.encode("ascii")).hexdigest(), nom=nom, porteur=porteur, usage=usage,
        cree_le=_instant(), cree_par=acteur, expire_epoch=instant + duree_s, revoque=False))
    _journal(cnx, nom, "jeton_emis", acteur, usage=usage)
    return jeton


def _version_active(cnx: Connection, nom: str) -> Mapping[str, Any]:
    ligne = _ligne(cnx, nom)
    if ligne is None:
        raise CoffreErreur("COFFRE_SECRET_INCONNU", "secret inconnu", 404)
    if ligne["etat"] != "actif":
        raise CoffreErreur("COFFRE_SECRET_REVOQUE", "secret révoqué")
    version = cnx.execute(select(COFFRE_VERSIONS).where(
        (COFFRE_VERSIONS.c.nom == nom) & (COFFRE_VERSIONS.c.version == ligne["version_active"])
        & (COFFRE_VERSIONS.c.etat == "active"))).mappings().first()
    if version is None:
        raise CoffreErreur("COFFRE_CHIFFRE_CORROMPU", "version active introuvable ; aucune valeur rendue", 503)
    return version


def _resoudre(cnx: Connection, *, usage: str, acteur: str, jeton: str | None, nom: str | None,
              cle: CleMaitresse | None, maintenant: float | None) -> tuple[str, str]:
    if not isinstance(usage, str) or not _USAGE.fullmatch(usage):
        raise CoffreErreur("COFFRE_USAGE_INVALIDE", "usage invalide", 422)
    if jeton is not None:
        if not isinstance(jeton, str) or not _JETON.fullmatch(jeton):
            raise CoffreErreur("COFFRE_JETON_INVALIDE", "jeton invalide", 403)
        ligne = cnx.execute(select(COFFRE_JETONS).where(
            COFFRE_JETONS.c.empreinte == hashlib.sha256(jeton.encode("ascii")).hexdigest())).mappings().first()
        if ligne is None:
            raise CoffreErreur("COFFRE_JETON_INVALIDE", "jeton inconnu", 403)
        nom = ligne["nom"]
        if ligne["revoque"]:
            raise CoffreErreur("COFFRE_JETON_REVOQUE", "jeton révoqué", 403)
        if ligne["expire_epoch"] <= (time.time() if maintenant is None else maintenant):
            raise CoffreErreur("COFFRE_JETON_EXPIRE", "jeton expiré", 403)
        if ligne["porteur"] != acteur:
            raise CoffreErreur("COFFRE_PORTEUR_REFUSE", "jeton présenté par un autre porteur", 403)
        if ligne["usage"] != usage:
            raise CoffreErreur("COFFRE_USAGE_REFUSE", "jeton non valable pour cet usage", 403)
    nom = _nom(nom)
    version = _version_active(cnx, nom)
    valeur = _dechiffrer(cle or cle_maitresse.charger(), version)
    return nom, valeur


@contextmanager
def utiliser(*, usage: str, acteur: str, jeton: str | None = None, nom: str | None = None,
             cle: CleMaitresse | None = None, fabrique: FabriqueConnexion | None = None,
             maintenant: float | None = None) -> Iterator[str]:
    """Résolution CÔTÉ SERVEUR au moment de l'appel : par jeton opaque (agents) ou par nom (code serveur).

    Ouvre sa propre transaction (interdit dans une transaction métier, pour que le journal d'un refus survive),
    journalise l'accès, puis rend la valeur le temps du bloc `with`, masquée dans tous les journaux."""
    from ..stockage.moteur import connexion_courante, transaction

    if connexion_courante() is not None:
        raise CoffreErreur("COFFRE_TRANSACTION_METIER", "résolution interdite dans une transaction métier", 500)
    if (jeton is None) == (nom is None):
        raise CoffreErreur("COFFRE_RESOLUTION_INVALIDE", "jeton OU nom requis", 422)
    erreur: CoffreErreur | None = None
    valeur = ""
    with (fabrique or transaction)() as cnx:
        try:
            nom_resolu, valeur = _resoudre(cnx, usage=usage, acteur=acteur, jeton=jeton, nom=nom, cle=cle,
                                           maintenant=maintenant)
            _journal(cnx, nom_resolu, "resolution", acteur, usage=usage if isinstance(usage, str) else None)
        except CoffreErreur as exc:
            cible = nom if isinstance(nom, str) and _NOM.fullmatch(nom) else "<jeton>" if jeton else "<inconnu>"
            _journal(cnx, cible, "resolution", str(acteur), "refus",
                     usage=usage if isinstance(usage, str) and _USAGE.fullmatch(usage) else None, code=exc.code)
            erreur = exc
    if erreur is not None:
        raise erreur
    masquage.installer()
    masquage.enregistrer(valeur)
    try:
        yield valeur
    finally:
        masquage.oublier(valeur)


def rechiffrer(cnx: Connection, *, acteur: str, ancienne: CleMaitresse, nouvelle: CleMaitresse) -> int:
    """Rotation de la clé maîtresse : ré-enveloppe toutes les clés de donnée actives ; les valeurs ne sont pas
    déchiffrées. Tout ou rien : une version enveloppée par une troisième clé refuse l'opération."""
    _admin(cnx, acteur)
    if ancienne.empreinte == nouvelle.empreinte:
        raise CoffreErreur("COFFRE_CLE_IDENTIQUE", "la nouvelle clé maîtresse est identique à l'actuelle", 422)
    versions = cnx.execute(select(COFFRE_VERSIONS).where(COFFRE_VERSIONS.c.etat == "active")).mappings().all()
    if any(v["empreinte_cle_maitresse"] != ancienne.empreinte for v in versions):
        raise CoffreErreur("COFFRE_CLE_MAITRESSE_DIFFERENTE", "versions enveloppées par une autre clé : refus", 409)
    aesgcm, _ = _aes()
    # Toutes les clés de donnée sont ouvertes AVANT la première écriture : un chiffré illisible refuse tout.
    ouvertes = [(v, _ouvrir_cle(ancienne, v)) for v in versions]
    for v, donnee in ouvertes:
        nonce = secrets.token_bytes(12)
        cnx.execute(update(COFFRE_VERSIONS).where(
            (COFFRE_VERSIONS.c.nom == v["nom"]) & (COFFRE_VERSIONS.c.version == v["version"])).values(
            nonce_cle=nonce, cle_enveloppee=aesgcm(nouvelle.kek).encrypt(nonce, donnee, _aad(v["nom"], v["version"],
                                                                                             "cle")),
            empreinte_cle_maitresse=nouvelle.empreinte))
    _journal(cnx, "*", "rechiffrement", acteur)
    return len(versions)
