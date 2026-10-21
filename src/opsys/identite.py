"""Identité (ADR-0009 §5) : personnes, rôles fermés, mots de passe individuels.

Remplace le mot de passe partagé : toute décision (approbation, connexion à la console) est
signée par une personne active, jamais par un secret commun. Un rôle est un des huit noms fermés
de l'ADR (`ROLES`) ; un département déclare, dans son manifeste, quels rôles peuvent décider quel
niveau N (voir `opsys.departements.PolitiqueApprobation`).

Mots de passe : `hashlib.scrypt` (bibliothèque standard, aucune nouvelle dépendance), sel aléatoire
par personne, comparaison à temps constant. Jamais de mot de passe en clair stocké ni journalisé —
seule l'empreinte (`mot_de_passe_hash`) traverse la base et les journaux ; `_maintenant`/l'audit
n'écrivent jamais le mot de passe fourni.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from .stockage.moteur import inserer
from .stockage.schema import PERSONNES, ROLES_PERSONNES

_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
LONGUEUR_MIN_MOT_DE_PASSE = 12
_PREFIXE_HACHAGE = "scrypt"
# Paramètres interactifs recommandés (RFC 7914 §2) : coût mémoire ~16 Mio, largement sous les
# limites par défaut d'OpenSSL (`hashlib.scrypt(maxmem=0)`), rapide pour une connexion humaine.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_DKLEN = 2**14, 8, 1, 32


class Role(enum.StrEnum):
    """Rôles fermés (ADR-0009 §5, DEFINITION-PRODUIT §8/P8) : aucun autre nom n'est accepté."""

    NATHAN_OWNER = "nathan_owner"
    ADMIN = "admin"
    FINANCE = "finance"
    MANAGER = "manager"
    SELLER = "seller"
    EMPLOYEE = "employee"
    CLIENT = "client"
    SYSTEM_AGENT = "system_agent"


ROLES: frozenset[str] = frozenset(role.value for role in Role)


@dataclasses.dataclass(frozen=True)
class Personne:
    identifiant: str
    nom: str
    actif: bool
    roles: frozenset[str]


def _maintenant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def identifiant_valide(identifiant: object) -> bool:
    """Vrai si `identifiant` a la forme d'un identifiant de personne OPSYS (la base n'est pas consultée).

    Le profil des équipes (`opsys.equipes`) s'en sert pour ne pas recopier la règle."""
    return isinstance(identifiant, str) and _IDENTIFIANT.match(identifiant) is not None


def _valider_identifiant(identifiant: str) -> str:
    if not isinstance(identifiant, str) or not _IDENTIFIANT.match(identifiant):
        raise ValueError(
            f"identifiant invalide {identifiant!r} : minuscules, chiffres, '.', '_', '-', "
            "commence par une lettre, 2 à 64 caractères"
        )
    return identifiant


def _valider_roles(roles: Sequence[str]) -> frozenset[str]:
    ensemble = frozenset(roles)
    inconnus = sorted(ensemble - ROLES)
    if inconnus:
        raise ValueError(f"rôle(s) inconnu(s) {inconnus} (ADR-0009 §5 : {sorted(ROLES)})")
    return ensemble


# -- mots de passe --------------------------------------------------------------------------------


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    """Empreinte scrypt versionnée (`algo$n$r$p$sel$hachage`, tout en hexadécimal)."""
    if not isinstance(mot_de_passe, str) or len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        raise ValueError(f"mot de passe trop court ({LONGUEUR_MIN_MOT_DE_PASSE} caractères minimum)")
    sel = secrets.token_bytes(16)
    empreinte = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel, n=_SCRYPT_N, r=_SCRYPT_R,
                               p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return f"{_PREFIXE_HACHAGE}${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sel.hex()}${empreinte.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, empreinte: str) -> bool:
    """Compare à temps constant ; toute empreinte mal formée est un refus, jamais une exception."""
    try:
        algo, n, r, p, sel_hex, hachage_hex = empreinte.split("$")
        if algo != _PREFIXE_HACHAGE:
            return False
        recalcule = hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=bytes.fromhex(sel_hex),
                                   n=int(n), r=int(r), p=int(p), dklen=len(hachage_hex) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(recalcule, bytes.fromhex(hachage_hex))


# Empreinte factice, calculée une fois : `authentifier` l'utilise pour un identifiant inconnu, afin
# que la vérification prenne le même temps qu'avec un identifiant réel (pas d'énumération de comptes
# par mesure de latence).
_EMPREINTE_FACTICE = hacher_mot_de_passe("mot-de-passe-factice-a-temps-constant-xx")


# -- personnes -------------------------------------------------------------------------------------


def _roles_de(cnx: Connection, identifiant: str) -> frozenset[str]:
    requete = select(ROLES_PERSONNES.c.role).where(ROLES_PERSONNES.c.identifiant == identifiant)
    return frozenset(ligne[0] for ligne in cnx.execute(requete))


def personne(cnx: Connection, identifiant: str) -> Personne | None:
    ligne = cnx.execute(select(PERSONNES).where(PERSONNES.c.identifiant == identifiant)).mappings().fetchone()
    if ligne is None:
        return None
    return Personne(ligne["identifiant"], ligne["nom"], bool(ligne["actif"]), _roles_de(cnx, identifiant))


def personne_active(cnx: Connection, identifiant: str) -> Personne | None:
    """`personne`, mais None si l'identifiant est inconnu OU inactif (fail-closed pour les décisions)."""
    trouvee = personne(cnx, identifiant)
    return trouvee if (trouvee is not None and trouvee.actif) else None


def authentifier(cnx: Connection, identifiant: str, mot_de_passe: str) -> Personne | None:
    """Personne active dont le mot de passe correspond ; None sinon (identifiant, mot de passe ou
    compte inactif : un seul message générique côté appelant, pour ne rien révéler)."""
    ligne = cnx.execute(select(PERSONNES).where(PERSONNES.c.identifiant == identifiant)).mappings().fetchone()
    empreinte = ligne["mot_de_passe_hash"] if ligne is not None else _EMPREINTE_FACTICE
    valide = verifier_mot_de_passe(mot_de_passe, empreinte)  # toujours calculé : temps constant
    if ligne is None or not ligne["actif"] or not valide:
        return None
    return Personne(ligne["identifiant"], ligne["nom"], True, _roles_de(cnx, identifiant))


def lister(cnx: Connection) -> list[Personne]:
    identifiants = [ligne[0] for ligne in
                    cnx.execute(select(PERSONNES.c.identifiant).order_by(PERSONNES.c.identifiant))]
    return [trouvee for i in identifiants if (trouvee := personne(cnx, i)) is not None]


def creer_personne(cnx: Connection, identifiant: str, nom: str, mot_de_passe: str,
                   roles: Sequence[str] = (), *, actif: bool = True) -> Personne:
    identifiant = _valider_identifiant(identifiant)
    if personne(cnx, identifiant) is not None:
        raise ValueError(f"identifiant déjà utilisé : {identifiant}")
    if not isinstance(nom, str) or not nom.strip():
        raise ValueError("nom requis")
    ensemble_roles = _valider_roles(roles)
    hachage = hacher_mot_de_passe(mot_de_passe)
    cnx.execute(insert(PERSONNES).values(identifiant=identifiant, nom=nom.strip(), actif=actif,
                                         mot_de_passe_hash=hachage, cree_le=_maintenant()))
    if ensemble_roles:
        cnx.execute(insert(ROLES_PERSONNES),
                   [{"identifiant": identifiant, "role": role} for role in sorted(ensemble_roles)])
    return Personne(identifiant, nom.strip(), actif, ensemble_roles)


def _exiger(cnx: Connection, identifiant: str) -> None:
    if personne(cnx, identifiant) is None:
        raise KeyError(f"personne inconnue : {identifiant}")


def ajouter_role(cnx: Connection, identifiant: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"rôle inconnu {role!r} (ADR-0009 §5 : {sorted(ROLES)})")
    _exiger(cnx, identifiant)
    insertion = inserer(cnx)(ROLES_PERSONNES).values(identifiant=identifiant, role=role)
    cnx.execute(insertion.on_conflict_do_nothing())


def retirer_role(cnx: Connection, identifiant: str, role: str) -> None:
    _exiger(cnx, identifiant)
    cnx.execute(delete(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == identifiant,
                                              ROLES_PERSONNES.c.role == role))


def activer(cnx: Connection, identifiant: str, actif: bool) -> None:
    resultat = cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == identifiant).values(actif=actif))
    if resultat.rowcount == 0:
        raise KeyError(f"personne inconnue : {identifiant}")


def changer_mot_de_passe(cnx: Connection, identifiant: str, mot_de_passe: str) -> None:
    hachage = hacher_mot_de_passe(mot_de_passe)  # lève ValueError si trop court, avant toute écriture
    resultat = cnx.execute(
        update(PERSONNES).where(PERSONNES.c.identifiant == identifiant).values(mot_de_passe_hash=hachage)
    )
    if resultat.rowcount == 0:
        raise KeyError(f"personne inconnue : {identifiant}")


def vers_json(p: Personne) -> dict[str, Any]:
    """Représentation JSON sûre : jamais l'empreinte du mot de passe (elle n'est même pas portée
    par `Personne`)."""
    return {"identifiant": p.identifiant, "nom": p.nom, "actif": p.actif, "roles": sorted(p.roles)}
