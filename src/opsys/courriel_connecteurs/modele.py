"""Modèle commun des connecteurs courriel : tout fournisseur parle ces types, aucun ne fuit son format.

Rien ici n'est un secret et rien n'est exécutable. Les octets d'un courriel ou d'une pièce jointe (`repr=False`) ne
s'affichent jamais dans un `repr`, une erreur ou un journal.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Literal

ETATS_AUTH = ("pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "inconnu", "absent")


@dataclasses.dataclass(frozen=True)
class Adresse:
    courriel: str
    nom: str = ""


@dataclasses.dataclass(frozen=True)
class Boite:
    id: str
    adresse: str
    fournisseur: str


@dataclasses.dataclass(frozen=True)
class Dossier:
    id: str
    nom: str
    role: str | None = None


@dataclasses.dataclass(frozen=True)
class RefMessage:
    """Référence d'un message chez le fournisseur : opaque, jamais interprétée par le code appelant."""

    ref: str
    dossier: str


@dataclasses.dataclass(frozen=True)
class PageSync:
    """Une page de synchronisation. `curseur` est opaque et ne couvre que CETTE page : le persister avant d'avoir traité
    ses messages ferait perdre les messages en cas d'arrêt. `termine` : plus rien à lire pour l'instant (le curseur est
    alors celui de l'incrémental)."""

    ajouts: tuple[RefMessage, ...]
    suppressions: tuple[str, ...]
    curseur: str
    termine: bool


@dataclasses.dataclass(frozen=True)
class MessageBrut:
    ref: str
    dossier: str
    octets: bytes = dataclasses.field(repr=False)
    fil_fournisseur: str | None = None
    recu_le: str | None = None


@dataclasses.dataclass(frozen=True)
class PieceJointe:
    nom: str
    mime_declare: str
    mime_detecte: str
    mime_verifie: bool
    extension_coherente: bool
    dangereux: bool
    taille: int
    sha256: str
    octets: bytes = dataclasses.field(repr=False, default=b"")
    refus: Literal["trop_gros"] | None = None


@dataclasses.dataclass(frozen=True)
class Authentification:
    """Verdicts SPF / DKIM / DMARC tels que RAPPORTÉS par le serveur de réception (`Authentication-Results`). OPSYS ne
    les revérifie pas : `fiable` n'est vrai que si l'identifiant du serveur est dans la liste configurée du compte."""

    spf: str = "absent"
    dkim: str = "absent"
    dmarc: str = "absent"
    serveur: str | None = None
    fiable: bool = False


@dataclasses.dataclass(frozen=True)
class MessageNormalise:
    id: str
    dossier: str
    fil: str
    message_id: str | None
    expediteur: Adresse | None
    destinataires: tuple[Adresse, ...]
    copie: tuple[Adresse, ...]
    repondre_a: tuple[Adresse, ...]
    objet: str
    date_utc: str | None
    corps_texte: str = dataclasses.field(repr=False)
    corps_tronque: bool
    pieces_jointes: tuple[PieceJointe, ...]
    pieces_ignorees: int
    authentification: Authentification
    empreinte: str
    taille_source: int
    adresses_invalides: int = 0

    def cle_idempotence(self) -> str:
        """Clé du message pour un compte : l'identifiant `Message-ID` (sinon la référence du fournisseur)."""
        return hashlib.sha256(("mid:" + (self.message_id or "ref:" + self.id)).encode("utf-8")).hexdigest()


# -- envoi ------------------------------------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class PieceSortante:
    nom: str
    mime: str
    octets: bytes = dataclasses.field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.octets).hexdigest()


@dataclasses.dataclass(frozen=True)
class ContenuBrouillon:
    compte_id: str
    de: str
    a: tuple[str, ...]
    cc: tuple[str, ...]
    cci: tuple[str, ...]
    objet: str
    corps: str = dataclasses.field(repr=False)
    pieces: tuple[PieceSortante, ...] = ()
    en_reponse_a: str | None = None

    def canonique(self) -> bytes:
        """Forme canonique : tout ce qui part vers le destinataire et vers qui. Un seul octet de différence, une
        adresse ajoutée ou une pièce remplacée change l'empreinte."""
        return json.dumps({
            "compte": self.compte_id, "de": self.de.lower(), "a": sorted(x.lower() for x in self.a),
            "cc": sorted(x.lower() for x in self.cc), "cci": sorted(x.lower() for x in self.cci),
            "objet": self.objet, "corps": self.corps, "reponse_a": self.en_reponse_a,
            "pieces": sorted([p.nom, p.mime, p.sha256] for p in self.pieces),
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def empreinte(self) -> str:
        return hashlib.sha256(b"opsys:courriel:brouillon:v1:" + self.canonique()).hexdigest()


@dataclasses.dataclass(frozen=True)
class BrouillonSortant:
    brouillon_id: str
    revision: int
    contenu: ContenuBrouillon
    empreinte: str

    def __post_init__(self) -> None:
        if self.empreinte != self.contenu.empreinte():
            raise ValueError("empreinte du brouillon incohérente avec son contenu")


@dataclasses.dataclass(frozen=True)
class JetonApprobation:
    """Ce qu'un envoi présente : la demande du sas (`opsys.approbations`) et l'empreinte qu'elle a approuvée. Le jeton
    ne prouve rien à lui seul : il est vérifié contre la base du sas à chaque envoi et consommé une seule fois."""

    demande_id: str
    empreinte: str


@dataclasses.dataclass(frozen=True)
class RecuEnvoi:
    fournisseur: str
    brouillon_id: str
    empreinte: str
    envoye_le: str
