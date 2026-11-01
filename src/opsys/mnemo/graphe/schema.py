"""Schéma FERMÉ du graphe de connaissances : les seuls types de nœuds et d'arêtes, et les seules arêtes permises.

Une arête dont (type, source, cible) ne figure pas dans `ARETES` est refusée (`REJ-MNEMO-GRAPHE-ARETE-NON-AUTORISEE`) :
un graphe ouvert devient un fourre-tout où tout « se rapporte » à tout. Ajouter un type est une décision d'architecture
(ce fichier, sa migration `CHECK`, ses tests), jamais un paramètre d'appel.

**Sensibilité (Loi 25).** Une arête est sensible dès que l'une de ses extrémités est un nœud personnel (client,
propriété) : relier un client à sa propriété ou à ses interventions, c'est une information personnelle. Une arête
sensible naît en BROUILLON et ne devient une relation de confiance que par la confirmation d'une personne (N3). Une
arête non sensible, issue du bus, est confirmée par le système (écriture interne réversible : elle se ferme).

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re

from .. import codes, vie_privee
from ..codes import ErreurMnemo

TYPES_NOEUD = ("client", "propriete", "intervention", "materiau", "fournisseur", "equipe", "document", "decision")
NOEUDS_PERSONNELS = frozenset({"client", "propriete"})

# type d'arête -> couples (type du nœud source, type du nœud cible) permis. Le sens est fixe.
ARETES: dict[str, frozenset[tuple[str, str]]] = {
    "possede": frozenset({("client", "propriete")}),
    "demande": frozenset({("client", "intervention")}),
    "realisee_sur": frozenset({("intervention", "propriete")}),
    "realisee_par": frozenset({("intervention", "equipe")}),
    "utilise": frozenset({("intervention", "materiau")}),
    "fourni_par": frozenset({("materiau", "fournisseur")}),
    "documente": frozenset({("document", "intervention"), ("document", "client"), ("document", "propriete")}),
    "justifie": frozenset({("document", "decision")}),
    "concerne": frozenset({("decision", t) for t in TYPES_NOEUD if t not in ("decision", "document")}),
    "precede": frozenset({("intervention", "intervention")}),
}
TYPES_ARETE = tuple(ARETES)
ORIGINES = ("bus", "agent", "humain", "systeme")
ETATS = ("brouillon", "confirmee", "fermee", "rejetee")
CONFIANCES = ("faible", "moyenne", "haute")

_CLE_COMMUNE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$")
_SOURCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#~-]{2,199}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIBELLE_MAX = 80


def noeud_id(type_noeud: str, cle: str) -> str:
    return hashlib.sha256(f"noeud|{type_noeud}|{cle}".encode()).hexdigest()[:32]


def arete_id(type_arete: str, de: str, vers: str, valide_de: str) -> str:
    return hashlib.sha256(f"arete|{type_arete}|{de}|{vers}|{valide_de}".encode()).hexdigest()[:32]


def sensible(type_source: str, type_cible: str) -> bool:
    return type_source in NOEUDS_PERSONNELS or type_cible in NOEUDS_PERSONNELS


def date_valide(valeur: object) -> bool:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        return False
    import datetime as dt

    try:
        dt.date.fromisoformat(valeur)
    except ValueError:
        return False
    return True


def exiger_date(valeur: object, champ: str) -> str:
    if not date_valide(valeur):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, f"{champ} : date AAAA-MM-JJ valide attendue")
    return str(valeur)


def exiger_source_ref(valeur: object, champ: str = "source_ref") -> str:
    vie_privee.refuser_secret(valeur, champ)
    if not isinstance(valeur, str) or not _SOURCE_REF.fullmatch(valeur):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, f"{champ} : référence de source attendue (3 à 200 caractères sûrs)")
    return valeur


@dataclasses.dataclass(frozen=True)
class NoeudRef:
    type: str
    cle: str


def valider_noeud(type_noeud: object, cle: object, libelle: object = None) -> tuple[str, str, str]:
    """`(type, cle, libellé)` conformes, ou `ErreurMnemo`. Un nœud personnel n'a qu'un libellé calculé du pseudonyme ;
    un
    libellé fourni pour lui est refusé (jamais ignoré en silence : l'appelant croirait l'avoir posé)."""
    if type_noeud not in TYPES_NOEUD:
        raise ErreurMnemo(
            codes.NOEUD_TYPE_INCONNU,
            f"type de nœud {vie_privee.court(type_noeud)} hors du schéma : {list(TYPES_NOEUD)}",
        )
    if type_noeud in NOEUDS_PERSONNELS:
        if not vie_privee.pseudonyme_valide(cle):
            raise ErreurMnemo(
                codes.NOEUD_CLE_INVALIDE,
                f"{type_noeud} : seule l'empreinte stable (hexadécimal, 16 à 64 caractères) est admise, jamais un "
                "nom, une adresse ni des coordonnées (Loi 25)",
            )
        if libelle not in (None, ""):
            raise ErreurMnemo(
                codes.DONNEE_PERSONNELLE, f"{type_noeud} : le libellé est calculé du pseudonyme, il ne se fournit pas"
            )
        return type_noeud, str(cle), vie_privee.libelle_pseudonyme(type_noeud, str(cle))
    if not isinstance(cle, str) or not _CLE_COMMUNE.fullmatch(cle):
        raise ErreurMnemo(
            codes.NOEUD_CLE_INVALIDE, f"{type_noeud} : clé 1 à 128 caractères (lettres, chiffres, . _ : ~ -)"
        )
    texte = cle if libelle in (None, "") else libelle
    return type_noeud, cle, vie_privee.texte_libre(texte, "libelle", maximum=LIBELLE_MAX)


def verifier_arete(type_arete: object, type_source: str, type_cible: str) -> bool:
    """Vrai si l'arête est dans le schéma et renvoie sa sensibilité ; `ErreurMnemo` sinon."""
    if type_arete not in ARETES:
        raise ErreurMnemo(
            codes.ARETE_NON_AUTORISEE,
            f"type d'arête {vie_privee.court(type_arete)} hors du schéma : {list(TYPES_ARETE)}",
        )
    if (type_source, type_cible) not in ARETES[str(type_arete)]:
        raise ErreurMnemo(
            codes.ARETE_NON_AUTORISEE,
            f"« {type_arete} » ne relie pas {type_source} à {type_cible} (permis : "
            f"{sorted(f'{a}→{b}' for a, b in ARETES[str(type_arete)])})",
        )
    return sensible(type_source, type_cible)
