"""Minimisation Loi 25 de Mnémo : ce qui a le droit d'entrer dans le modèle de soi et dans le graphe.

Règles (écrites une fois, appliquées partout) :

1. **Un client et une propriété ne sont connus que par leur pseudonyme stable** (l'empreinte que M2 publie déjà :
   `client_id`, `propriete_id`), jamais par un nom, une adresse, un courriel ou un téléphone. Le libellé d'un tel
   nœud est calculé par le code à partir du pseudonyme ; l'appelant ne le choisit pas.
2. **Un texte libre** (libellé d'un nœud non personnel, texte d'une règle de la direction, description) passe le
   garde-fou de texte du socle : aucun lien, aucune adresse, aucun courriel ni téléphone, aucun nom de client.
3. **Une consigne glissée dans un texte** est refusée, pas neutralisée : un énoncé du modèle de soi est relu par les
   agents de tous les départements, c'est un vecteur d'injection (filtre de provenance de M1, comme la base de
   connaissances).
4. Aucune donnée n'est conservée « au cas où » : le schéma du graphe n'a pas de champ libre, seulement un libellé borné.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import re
import unicodedata

from .. import garde_fou_texte as gft
from . import codes
from .codes import ErreurMnemo

PROFIL_TEXTE = gft.profil(
    "mnemo_texte", (gft.LONGUEUR, gft.LIEN, gft.ADRESSE, gft.COORDONNEES, gft.NOM_CLIENT), texte_max=400
)
_PSEUDONYME = re.compile(r"^[0-9a-f]{16,64}$")
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


def court(valeur: object, maximum: int = 40) -> str:
    """Une valeur de l'appelant, bornée pour un message de refus (ni texte démesuré, ni donnée entière)."""
    texte = repr(valeur)
    return texte if len(texte) <= maximum else texte[: maximum - 1] + "…"


def pseudonyme_valide(cle: object) -> bool:
    """Un pseudonyme stable est une empreinte hexadécimale en minuscules (16 à 64 caractères)."""
    return isinstance(cle, str) and _PSEUDONYME.fullmatch(cle) is not None


def libelle_pseudonyme(type_noeud: str, cle: str) -> str:
    """Libellé d'un nœud personnel : calculé, jamais fourni (« client·a1b2c3d4 »)."""
    return f"{type_noeud}·{cle[:8]}"


def refuser_secret(valeur: object, champ: str) -> None:
    """Refuse (sans jamais citer la valeur) un texte qui ressemble à une clé, un jeton ou un en-tête d'autorisation : un
    secret qui entrerait ici serait relu par les agents de tous les départements et resterait dans le journal."""
    from ..secrets_coffre import masquage

    if isinstance(valeur, str) and masquage.contient_secret(valeur):
        raise ErreurMnemo(
            codes.SECRET, f"{champ} : ressemble à un secret (clé, jeton, en-tête) ; il n'a rien à faire ici"
        )


def texte_libre(valeur: object, champ: str, *, maximum: int = 300, minimum: int = 1) -> str:
    """Texte libre propre : borné, imprimable, sans donnée personnelle ni consigne. Lève `ErreurMnemo`."""
    if not isinstance(valeur, str):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, f"{champ} : texte attendu")
    texte = unicodedata.normalize("NFKC", valeur).strip()
    if not minimum <= len(texte) <= maximum or _CONTROLE.search(texte):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, f"{champ} : {minimum} à {maximum} caractères imprimables")
    refuser_secret(texte, champ)
    violations = gft.controler(texte, PROFIL_TEXTE)
    if violations:
        # Les règles seulement, jamais l'extrait fautif : le détail d'une violation cite la donnée personnelle trouvée.
        regles = ", ".join(v.regle for v in violations)
        raise ErreurMnemo(
            codes.DONNEE_PERSONNELLE,
            f"{champ} : règle(s) {regles} (Loi 25 : ni lieu, ni coordonnées, ni nom de client, ni lien)",
        )
    return texte


def texte_sans_consigne(texte: str, champ: str) -> str:
    """Refuse (jamais ne corrige) un texte où le filtre anti-injection de provenance a trouvé une consigne."""
    from ..connaissances import isolation

    try:
        resultat = isolation.isoler(texte)
    except ValueError as exc:  # filtre de M1 introuvable : fail-closed
        raise ErreurMnemo(codes.TEXTE_SUSPECT, f"{champ} : filtre anti-injection indisponible, texte refusé") from exc
    if resultat.neutralise:
        raise ErreurMnemo(codes.TEXTE_SUSPECT, f"{champ} : le texte contient une consigne ; reformule-le en fait")
    return texte


def texte_propre(valeur: object, champ: str, *, maximum: int = 300, minimum: int = 1) -> str:
    """`texte_libre` puis `texte_sans_consigne` : la porte unique du texte destiné à être relu par un agent."""
    return texte_sans_consigne(texte_libre(valeur, champ, maximum=maximum, minimum=minimum), champ)
