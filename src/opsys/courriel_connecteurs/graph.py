"""Adaptateur Microsoft Graph (courrier Outlook / Microsoft 365) : requête delta par dossier, jamais EWS.

- Lecture : `GET /me/mailFolders`, `GET /me/mailFolders/{id}/messages/delta` (suivi de `@odata.nextLink` puis
  `@odata.deltaLink`), `GET /me/messages/{id}/$value` (MIME). Portées déléguées : `Mail.Read` (+ `offline_access`).
- Envoi : `POST /me/sendMail` (portée `Mail.Send`, seulement pour l'usage `lecture_envoi`), UNIQUEMENT sous garde.
- `Prefer: IdType="ImmutableId"` : les identifiants de message restent stables quand un message change de dossier
  (sinon l'idempotence serait fausse après un déplacement).
- Curseur opaque `graph:v1:…` : l'URL `nextLink` ou `deltaLink` rendue par le serveur. Elle est revalidée à CHAQUE
  usage : HTTPS, hôte `graph.microsoft.com`, chemin sous `/v1.0/me/mailFolders/` — une URL hostile (ou un curseur
  falsifié en base) ne reçoit jamais le jeton. Un `deltaLink` périmé (HTTP 410) donne `REJ-COURRIEL-CURSEUR-EXPIRE`.
- Le delta est PAR DOSSIER : l'appelant synchronise chaque dossier voulu. Les sous-dossiers ne sont pas parcourus ici.

Jamais testé contre le vrai service : seulement contre `FauxGraph` (tests/fixtures/courriel_doubles.py).
"""

from __future__ import annotations

import base64
import re
import urllib.parse

from .client_oauth import ClientApi
from .erreurs import ErreurCourriel
from .modele import (
    Boite,
    BrouillonSortant,
    Dossier,
    MessageBrut,
    PageSync,
    RefMessage,
)
from .normalisation import SOURCE_MAX
from .port import (
    EnvoiSousGarde,
    GardeEnvoi,
    Issue,
    convertir_incertain,
    decoder_curseur,
    encoder_curseur,
    limite_valide,
)

BASE = "https://graph.microsoft.com/v1.0/me"
HOTES = frozenset({"graph.microsoft.com"})
PREFIXE_CHEMIN = "/v1.0/me/mailFolders/"
_ID = re.compile(r"[A-Za-z0-9=_+-]{1,300}")
_PRESTATION = {"Prefer": 'IdType="ImmutableId"'}
PAGES_DOSSIERS_MAX = 20


def _identifiant(valeur: object, nature: str) -> str:
    if not isinstance(valeur, str) or not _ID.fullmatch(valeur):
        raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", f"{nature} invalide dans la réponse de Graph", 502)
    return valeur


class FournisseurGraph(EnvoiSousGarde):
    identifiant = "graph"

    def __init__(self, client: ClientApi, *, adresse: str, garde_envoi: GardeEnvoi | None = None) -> None:
        self._client, self._adresse, self._garde = client, adresse, garde_envoi

    # -- lecture -------------------------------------------------------------------------------------------------
    def lister_boites(self) -> list[Boite]:
        return [Boite(id=self._adresse, adresse=self._adresse, fournisseur=self.identifiant)]

    def lister_dossiers(self) -> list[Dossier]:
        dossiers: list[Dossier] = []
        url: str | None = f"{BASE}/mailFolders"
        params: dict | None = {"$top": 100, "$select": "id,displayName"}
        for _ in range(PAGES_DOSSIERS_MAX):
            donnees = self._client.json("GET", url, params=params, entetes=_PRESTATION)
            for entree in donnees.get("value", []):
                dossiers.append(Dossier(_identifiant(entree.get("id"), "identifiant de dossier"),
                                        str(entree.get("displayName", ""))[:200]))
            url, params = donnees.get("@odata.nextLink"), None
            if not url:
                break
        return dossiers

    def _url_depart(self, dossier: str, limite: int) -> str:
        if not isinstance(dossier, str) or not _ID.fullmatch(dossier):
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "identifiant de dossier invalide", 422)
        return (f"{BASE}/mailFolders/{urllib.parse.quote(dossier, safe='')}/messages/delta?"
                + urllib.parse.urlencode({"$select": "id,conversationId,receivedDateTime"}))

    def _verifier_lien(self, url: str) -> str:
        self._client.verifier_url(url)
        if not urllib.parse.urlsplit(url).path.startswith(PREFIXE_CHEMIN):
            raise ErreurCourriel("REJ-COURRIEL-LIEN-NON-AUTORISE", "lien hors de la zone des dossiers de courrier", 502)
        return url

    def synchroniser(self, dossier: str, curseur: str | None, *, limite: int = 100) -> PageSync:
        limite = limite_valide(limite)
        if curseur is None:
            url = self._url_depart(dossier, limite)
        else:
            etat = decoder_curseur("graph", curseur)
            url = etat.get("u")
            if not isinstance(url, str) or etat.get("k") not in {"n", "d"}:
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur Graph mal formé", 422)
        self._verifier_lien(url)
        if self._dossier_du_lien(url, "") != dossier:
            raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur Graph d'un autre dossier", 422)
        reponse = self._client.appeler("GET", url,
                                       entetes={"Prefer": f'IdType="ImmutableId", odata.maxpagesize={limite}'},
                                       rendre=frozenset({410}))
        if reponse.statut == 410:
            raise ErreurCourriel("REJ-COURRIEL-CURSEUR-EXPIRE", "deltaLink périmé chez Graph : relancer un amorçage "
                                 "complet", 409, reprenable=True)
        donnees = self._client.lire_json(reponse)
        ajouts, suppressions = [], []
        for entree in donnees.get("value", []):
            identifiant = _identifiant(entree.get("id"), "identifiant de message")
            if "@removed" in entree:
                suppressions.append(identifiant)
            else:
                ajouts.append(RefMessage(identifiant, dossier))
        suite, final = donnees.get("@odata.nextLink"), donnees.get("@odata.deltaLink")
        if isinstance(suite, str):
            self._verifier_lien(suite)
            return PageSync(tuple(ajouts), tuple(suppressions), encoder_curseur("graph", {"k": "n", "u": suite}), False)
        if isinstance(final, str):
            self._verifier_lien(final)
            return PageSync(tuple(ajouts), tuple(suppressions), encoder_curseur("graph", {"k": "d", "u": final}), True)
        raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "réponse delta sans lien de suite", 502)

    @staticmethod
    def _dossier_du_lien(url: str, repli: str) -> str:
        morceaux = urllib.parse.urlsplit(url).path[len(PREFIXE_CHEMIN):].split("/")
        return urllib.parse.unquote(morceaux[0]) if morceaux and morceaux[0] else repli

    def lire_message(self, ref: RefMessage) -> MessageBrut:
        identifiant = _identifiant(ref.ref, "identifiant de message")
        chemin = f"{BASE}/messages/{urllib.parse.quote(identifiant, safe='')}"
        meta = self._client.json("GET", chemin, params={"$select": "id,conversationId,receivedDateTime"},
                                 entetes=_PRESTATION)
        reponse = self._client.appeler("GET", chemin + "/$value", entetes={**_PRESTATION, "Accept": "*/*"})
        if len(reponse.corps) > SOURCE_MAX:
            raise ErreurCourriel("REJ-COURRIEL-MESSAGE-TROP-GROS", "message de plus de 32 Mio", 413)
        fil, recu = meta.get("conversationId"), meta.get("receivedDateTime")
        return MessageBrut(identifiant, ref.dossier, reponse.corps,
                           _identifiant(fil, "fil") if fil else None, recu if isinstance(recu, str) else None)

    # -- envoi (jamais direct : voir port.EnvoiSousGarde) ------------------------------------------------------------
    def _transmettre(self, brouillon: BrouillonSortant) -> Issue:
        c = brouillon.contenu

        def destinataires(adresses: tuple[str, ...]) -> list[dict]:
            return [{"emailAddress": {"address": a}} for a in adresses]

        message = {
            "subject": c.objet, "body": {"contentType": "Text", "content": c.corps},
            "toRecipients": destinataires(c.a), "ccRecipients": destinataires(c.cc),
            "bccRecipients": destinataires(c.cci),
            "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": p.nom, "contentType": p.mime,
                             "contentBytes": base64.b64encode(p.octets).decode("ascii")} for p in c.pieces],
        }
        convertir_incertain(lambda: self._client.appeler(
            "POST", f"{BASE}/sendMail", json_corps={"message": message, "saveToSentItems": True}, idempotente=False))
        return "envoye"
