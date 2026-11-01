"""Adaptateur Gmail (API REST `gmail.googleapis.com`), projet OAuth du CLIENT (type Internal), portées minimales.

- Lecture : `users.getProfile`, `users.labels.list`, `users.messages.list` (amorçage paginé), `users.history.list`
  (incrémental depuis un `historyId`), `users.messages.get?format=raw`. Portée : `gmail.readonly` SEULE.
- Envoi : `users.messages.send` avec le MIME approuvé (portée `gmail.send`, demandée seulement pour l'usage
  `lecture_envoi`), UNIQUEMENT via la garde d'approbation (`port.EnvoiSousGarde`).
- Curseur opaque `gmail:v1:…` : phase `l` (liste, avec jeton de page) puis phase `h` (historique). L'`historyId` de
  départ est lu AVANT la liste, donc rien n'est perdu entre l'amorçage et l'incrémental ; les doublons éventuels sont
  absorbés par l'idempotence de l'ingestion. Un `historyId` périmé (HTTP 404 sur `history.list`, périmètre documenté
  par Google : il n'est garanti que ~une semaine) donne `REJ-COURRIEL-CURSEUR-EXPIRE` : le service relance un amorçage.
- Le rattrapage de l'HISTORIQUE passe par un export mbox (quotas : docs/architecture/CONNECTEURS-COURRIEL.md) ; l'API ne
  sert qu'à l'incrémental et à l'amorçage borné.

Jamais testé contre le vrai service : seulement contre `FauxGmail` (tests/fixtures/courriel_doubles.py).
"""

from __future__ import annotations

import base64
import binascii
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
    construire_mime,
    convertir_incertain,
    decoder_curseur,
    encoder_curseur,
    limite_valide,
    raw_base64url,
)

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
HOTES = frozenset({"gmail.googleapis.com"})
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HISTORY = re.compile(r"[0-9]{1,20}")
_JETON_PAGE = re.compile(r"[A-Za-z0-9_\-+=/.~%:]{1,2048}")
_DOSSIER = re.compile(r"[A-Za-z0-9_-]{1,100}")
SERVEURS_AUTH_FIABLES = frozenset({"mx.google.com"})  # à vérifier à la qualification réelle


def _identifiant(valeur: object, nature: str) -> str:
    if not isinstance(valeur, str) or not _ID.fullmatch(valeur):
        raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", f"{nature} invalide dans la réponse de Gmail", 502)
    return valeur


class FournisseurGmail(EnvoiSousGarde):
    identifiant = "gmail"

    def __init__(self, client: ClientApi, *, garde_envoi: GardeEnvoi | None = None) -> None:
        self._client, self._garde = client, garde_envoi

    # -- lecture -------------------------------------------------------------------------------------------------
    def _profil(self) -> dict:
        profil = self._client.json("GET", f"{BASE}/profile")
        adresse, historique = profil.get("emailAddress"), str(profil.get("historyId", ""))
        if not isinstance(adresse, str) or not _HISTORY.fullmatch(historique):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "profil Gmail incomplet", 502)
        return {"adresse": adresse, "historique": historique}

    def lister_boites(self) -> list[Boite]:
        profil = self._profil()
        return [Boite(id=profil["adresse"], adresse=profil["adresse"], fournisseur=self.identifiant)]

    def lister_dossiers(self) -> list[Dossier]:
        donnees = self._client.json("GET", f"{BASE}/labels")
        dossiers = []
        for etiquette in donnees.get("labels", []):
            identifiant = _identifiant(etiquette.get("id"), "identifiant d'étiquette")
            nom = str(etiquette.get("name", identifiant))[:200]
            dossiers.append(Dossier(identifiant, nom, identifiant if etiquette.get("type") == "system" else None))
        return dossiers

    def _dossier(self, dossier: str) -> str:
        if not isinstance(dossier, str) or not _DOSSIER.fullmatch(dossier):
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "identifiant d'étiquette invalide", 422)
        return dossier

    def synchroniser(self, dossier: str, curseur: str | None, *, limite: int = 100) -> PageSync:
        limite = limite_valide(limite)
        dossier = self._dossier(dossier)
        if curseur is None:
            etat = {"p": "l", "h": self._profil()["historique"], "t": None}
        else:
            etat = decoder_curseur("gmail", curseur)
            self._valider_etat(etat)
        return self._lister(dossier, etat, limite) if etat["p"] == "l" else self._historique(dossier, etat, limite)

    @staticmethod
    def _valider_etat(etat: dict) -> None:
        jeton = etat.get("t")
        if (etat.get("p") not in {"l", "h"} or not isinstance(etat.get("h"), str) or not _HISTORY.fullmatch(etat["h"])
                or (jeton is not None and (not isinstance(jeton, str) or not _JETON_PAGE.fullmatch(jeton)))
                or (etat.get("nh") is not None and not _HISTORY.fullmatch(str(etat.get("nh"))))):
            raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur Gmail mal formé", 422)

    def _lister(self, dossier: str, etat: dict, limite: int) -> PageSync:
        params: dict = {"labelIds": dossier, "maxResults": limite}
        if etat.get("t"):
            params["pageToken"] = etat["t"]
        donnees = self._client.json("GET", f"{BASE}/messages", params=params)
        ajouts = tuple(RefMessage(_identifiant(m.get("id"), "identifiant de message"), dossier)
                       for m in donnees.get("messages", []))
        suite = donnees.get("nextPageToken")
        if suite:
            return PageSync(ajouts, (), encoder_curseur("gmail", {"p": "l", "h": etat["h"], "t": str(suite)}), False)
        return PageSync(ajouts, (), encoder_curseur("gmail", {"p": "h", "h": etat["h"]}), True)

    def _historique(self, dossier: str, etat: dict, limite: int) -> PageSync:
        params: dict = {"startHistoryId": etat["h"], "labelId": dossier, "maxResults": limite,
                        "historyTypes": ["messageAdded", "messageDeleted"]}
        if etat.get("t"):
            params["pageToken"] = etat["t"]
        reponse = self._client.appeler("GET", f"{BASE}/history", params=params, rendre=frozenset({404}))
        if reponse.statut == 404:
            raise ErreurCourriel("REJ-COURRIEL-CURSEUR-EXPIRE",
                                 "historyId périmé chez Gmail : relancer un amorçage complet", 409, reprenable=True)
        donnees = self._client.lire_json(reponse)
        ajoutes: dict[str, RefMessage] = {}
        supprimes: list[str] = []
        for evenement in donnees.get("history", []):
            for entree in evenement.get("messagesAdded", []):
                identifiant = _identifiant(entree.get("message", {}).get("id"), "identifiant de message")
                ajoutes[identifiant] = RefMessage(identifiant, dossier)
            for entree in evenement.get("messagesDeleted", []):
                identifiant = _identifiant(entree.get("message", {}).get("id"), "identifiant de message")
                ajoutes.pop(identifiant, None)  # ajouté puis supprimé dans la fenêtre : rien à lire
                supprimes.append(identifiant)
        nouvel = str(donnees.get("historyId", etat["h"]))
        if not _HISTORY.fullmatch(nouvel):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "historyId illisible", 502)
        suite = donnees.get("nextPageToken")
        if suite:
            curseur = encoder_curseur("gmail", {"p": "h", "h": etat["h"], "t": str(suite), "nh": nouvel})
            return PageSync(tuple(ajoutes.values()), tuple(supprimes), curseur, False)
        # Dernière page : le nouveau point de départ est le plus récent connu (jamais en arrière d'un nh déjà vu).
        final = max(int(nouvel), int(etat["h"]), int(etat.get("nh") or 0))
        return PageSync(tuple(ajoutes.values()), tuple(supprimes), encoder_curseur("gmail", {"p": "h",
                                                                                             "h": str(final)}),
                        True)

    def lire_message(self, ref: RefMessage) -> MessageBrut:
        identifiant = _identifiant(ref.ref, "identifiant de message")
        donnees = self._client.json("GET", f"{BASE}/messages/{urllib.parse.quote(identifiant, safe='')}",
                                    params={"format": "raw"})
        brut = donnees.get("raw")
        if not isinstance(brut, str) or len(brut) > SOURCE_MAX * 4 // 3 + 16:
            raise ErreurCourriel("REJ-COURRIEL-MESSAGE-TROP-GROS" if isinstance(brut, str) else
                                 "REJ-COURRIEL-REPONSE-INVALIDE", "message brut absent ou démesuré", 502)
        try:
            octets = base64.b64decode(brut + "=" * (-len(brut) % 4), altchars=b"-_", validate=True)
        except (binascii.Error, ValueError):
            raise ErreurCourriel("REJ-COURRIEL-REPONSE-INVALIDE", "message brut mal encodé", 502) from None
        fil = donnees.get("threadId")
        recu = None
        interne = donnees.get("internalDate")
        if isinstance(interne, str) and interne.isdigit() and len(interne) <= 14:
            from datetime import UTC, datetime
            recu = datetime.fromtimestamp(int(interne) / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return MessageBrut(identifiant, ref.dossier, octets, _identifiant(fil, "fil") if fil else None, recu)

    # -- envoi (jamais direct : voir port.EnvoiSousGarde) ------------------------------------------------------------
    def _transmettre(self, brouillon: BrouillonSortant) -> Issue:
        mime = construire_mime(brouillon, avec_bcc=True)
        convertir_incertain(lambda: self._client.json(
            "POST", f"{BASE}/messages/send", json_corps={"raw": raw_base64url(mime)}, idempotente=False))
        return "envoye"
