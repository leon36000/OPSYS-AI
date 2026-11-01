"""Le port `FournisseurCourriel` et ce que tous les adaptateurs partagent : curseurs opaques, construction MIME,
et l'ENVOI SOUS GARDE.

Un adaptateur n'expose aucune méthode d'envoi qui ne reçoive un `JetonApprobation`. `envoyer_brouillon(brouillon,
jeton)` est la seule porte : elle RÉSERVE d'abord l'envoi auprès de la garde (`GardeEnvoi`, adossée au sas
d'approbation, qui vérifie le jeton, le lie au contenu par empreinte et le consomme), et ne transmet qu'ensuite. Sans
garde raccordée, tout envoi est refusé (fail-closed). `_transmettre` est privée : aucun appelant ne peut l'atteindre
sans passer par la réservation.

Issue d'un envoi : `envoye`, `non_traite` (le fournisseur a refusé AVANT de traiter, p. ex. 429 : la réservation est
rendue et le même jeton peut resservir), `echec` (refus définitif : il faudra un NOUVEAU brouillon approuvé),
`incertain` (le message a peut-être été remis : jamais de reprise automatique, un humain vérifie la boîte « Envoyés »).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any, Literal, Protocol

from .erreurs import ErreurCourriel
from .modele import (
    Boite,
    BrouillonSortant,
    Dossier,
    JetonApprobation,
    MessageBrut,
    PageSync,
    RecuEnvoi,
    RefMessage,
)

Issue = Literal["envoye", "non_traite", "echec", "incertain"]
CURSEUR_MAX = 4096
LIMITE_PAGE_MAX = 500
_PREFIXE = re.compile(r"[a-z]{3,8}")


class Reservation(Protocol):
    """Ce que la garde remet après avoir vérifié et consommé le jeton."""

    brouillon_id: str


class GardeEnvoi(Protocol):
    def reserver(self, brouillon: BrouillonSortant, jeton: JetonApprobation, fournisseur: str) -> Reservation: ...

    def terminer(self, reservation: Reservation, issue: Issue, code: str | None = None) -> None: ...


class FournisseurCourriel(Protocol):
    identifiant: str

    def lister_boites(self) -> list[Boite]: ...

    def lister_dossiers(self) -> list[Dossier]: ...

    def synchroniser(self, dossier: str, curseur: str | None, *, limite: int = 100) -> PageSync: ...

    def lire_message(self, ref: RefMessage) -> MessageBrut: ...

    def envoyer_brouillon(self, brouillon: BrouillonSortant, jeton: JetonApprobation) -> RecuEnvoi: ...


# -- curseurs opaques -------------------------------------------------------------------------------------------
def encoder_curseur(prefixe: str, donnees: dict[str, Any]) -> str:
    charge = base64.urlsafe_b64encode(json.dumps(donnees, sort_keys=True, separators=(",", ":")).encode()).decode()
    curseur = f"{prefixe}:v1:{charge.rstrip('=')}"
    if len(curseur) > CURSEUR_MAX:
        raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur trop long", 500)
    return curseur


def decoder_curseur(prefixe: str, curseur: str) -> dict[str, Any]:
    try:
        if not isinstance(curseur, str) or len(curseur) > CURSEUR_MAX:
            raise ValueError("taille")
        pre, version, charge = curseur.split(":", 2)
        if pre != prefixe or version != "v1":
            raise ValueError("prefixe")
        donnees = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
        if not isinstance(donnees, dict):
            raise ValueError("forme")
        return donnees
    except (ValueError, binascii.Error, UnicodeError):
        raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur illisible ou d'un autre fournisseur",
                             422) from None


def limite_valide(limite: object) -> int:
    if type(limite) is not int or not 1 <= limite <= LIMITE_PAGE_MAX:
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", f"limite : entier de 1 à {LIMITE_PAGE_MAX}", 422)
    return limite


# -- MIME sortant -------------------------------------------------------------------------------------------------
def construire_mime(brouillon: BrouillonSortant, *, avec_bcc: bool) -> EmailMessage:
    """Le message à transmettre, construit UNIQUEMENT à partir du contenu approuvé. `avec_bcc` : certains
    transports (SMTP) reçoivent les cci dans l'enveloppe et non dans les en-têtes."""
    c = brouillon.contenu
    message = EmailMessage()
    message["From"] = c.de
    message["To"] = ", ".join(c.a)
    if c.cc:
        message["Cc"] = ", ".join(c.cc)
    if c.cci and avec_bcc:
        message["Bcc"] = ", ".join(c.cci)
    message["Subject"] = c.objet
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid(domain=c.de.rsplit("@", 1)[-1])
    if c.en_reponse_a:
        message["In-Reply-To"] = f"<{c.en_reponse_a}>"
        message["References"] = f"<{c.en_reponse_a}>"
    message.set_content(c.corps)
    for piece in c.pieces:
        principal, _, sous = piece.mime.partition("/")
        message.add_attachment(piece.octets, maintype=principal, subtype=sous or "octet-stream", filename=piece.nom)
    return message


def raw_base64url(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


# -- envoi sous garde -------------------------------------------------------------------------------------------
class EnvoiSousGarde:
    """Mixin des adaptateurs capables d'envoyer. La classe fille fournit `identifiant`, `_garde` et `_transmettre`."""

    identifiant: str
    _garde: GardeEnvoi | None

    def _transmettre(self, brouillon: BrouillonSortant) -> Issue:  # pragma: no cover — surchargée
        raise NotImplementedError

    def envoyer_brouillon(self, brouillon: BrouillonSortant, jeton: JetonApprobation) -> RecuEnvoi:
        if self._garde is None:
            raise ErreurCourriel("REJ-COURRIEL-ENVOI-NON-SUPPORTE",
                                 "aucun sas d'approbation raccordé à cet adaptateur : envoi refusé", 403)
        if not isinstance(brouillon, BrouillonSortant) or not isinstance(jeton, JetonApprobation):
            raise ErreurCourriel("REJ-COURRIEL-APPROBATION-ABSENTE",
                                 "un brouillon et un jeton d'approbation sont requis",
                                 403)
        reservation = self._garde.reserver(brouillon, jeton, self.identifiant)
        try:
            issue = self._transmettre(brouillon)
        except ErreurCourriel as exc:
            self._garde.terminer(reservation, _issue_de(exc), exc.code)
            raise
        except Exception:
            self._garde.terminer(reservation, "incertain", "REJ-COURRIEL-ENVOI-INCERTAIN")
            raise ErreurCourriel("REJ-COURRIEL-ENVOI-INCERTAIN",
                                 "issue de l'envoi inconnue : vérifier la boîte « Envoyés » avant tout nouvel essai",
                                 502) from None
        self._garde.terminer(reservation, issue)
        return RecuEnvoi(self.identifiant, brouillon.brouillon_id, brouillon.empreinte,
                         datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _issue_de(exc: ErreurCourriel) -> Issue:
    if exc.code == "REJ-COURRIEL-LIMITE-DEBIT":
        return "non_traite"
    if exc.code in {"REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE", "REJ-COURRIEL-RESEAU", "REJ-COURRIEL-ENVOI-INCERTAIN"}:
        return "incertain"
    return "echec"


def convertir_incertain(fonction: Callable[[], Any]) -> Any:
    """Exécute un appel d'envoi : une panne de transport ou un 5xx devient `ENVOI-INCERTAIN`, jamais un simple échec."""
    try:
        return fonction()
    except ErreurCourriel as exc:
        if exc.code in {"REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE", "REJ-COURRIEL-RESEAU"}:
            raise ErreurCourriel("REJ-COURRIEL-ENVOI-INCERTAIN",
                                 "issue de l'envoi inconnue : vérifier la boîte « Envoyés » avant tout nouvel essai",
                                 502) from None
        raise
