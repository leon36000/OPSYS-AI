"""Doubles de test des connecteurs courriel (tests seulement, jamais une capacité livrée).

AUCUN réseau, AUCUN vrai service : ce sont des IMITATIONS écrites d'après la documentation publique des API. Un test qui
passe contre elles prouve la logique d'adaptateur, PAS la compatibilité avec Gmail, Microsoft Graph ou un serveur IMAP
réel (voir docs/architecture/CONNECTEURS-COURRIEL.md, « Plan de qualification réelle »).

- `FauxGmail`, `FauxGraph` : serveurs REST en mémoire (pagination par jeton de page, historique / delta, 401 sur jeton
  inconnu, réponses scriptées 429 + Retry-After / 5xx / 403 / 410, envois enregistrés) derrière l'interface
  `Transport` ;
- `FauxOAuth` : points de jeton et de révocation (échange de code PKCE vérifié, rafraîchissement, rotation du refresh
  token, portées configurables, `invalid_grant`) ;
- `Aiguilleur` : route une requête vers le double de l'hôte visé et REFUSE tout hôte inconnu (aucune fuite de jeton) ;
- `FauxServeurImap` / `FauxImap4SSL` / `FauxSmtpSSL` : un serveur IMAP et SMTP en mémoire derrière les fabriques de
  `imaplib` / `smtplib`, avec journal des commandes ;
- `StockageJetonsMemoire` : un `StockageJetons` en mémoire pour les tests d'adaptateur hors coffre ;
- `courriel_brut`, `Horloge` : construction de courriels fictifs (`@example.test`) et horloge / sommeil contrôlés.
"""

from __future__ import annotations

import base64
import hashlib
import imaplib
import json
import re
import smtplib
import urllib.parse
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from opsys.courriel_connecteurs.jetons import JeuJetons
from opsys.courriel_connecteurs.transport import ReponseHttp, RequeteHttp

FICTIF = True


class Horloge:
    """Horloge et sommeil contrôlés : `dormir` n'attend pas, il avance l'horloge et se souvient."""

    def __init__(self, depart: float = 1_800_000_000.0) -> None:
        self.t = depart
        self.sommeils: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, secondes: float) -> None:
        self.sommeils.append(secondes)
        self.t += secondes


def courriel_brut(
    *,
    de: str = "client.fictif@example.test",
    a: str = "paul.fictif@example.test",
    objet: str = "Bonjour",
    corps: str = "Message fictif.",
    message_id: str | None = None,
    date: datetime | None = None,
    pieces: list[tuple[str, str, bytes]] | None = None,
    html: str | None = None,
    extra: dict[str, str] | None = None,
    nom_expediteur: str = "Client Fictif",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"{nom_expediteur} <{de}>" if nom_expediteur else de
    msg["To"] = a
    msg["Subject"] = objet
    msg["Date"] = format_datetime(date or datetime(2026, 10, 30, 14, 0, tzinfo=UTC))
    msg["Message-ID"] = message_id or f"<{hashlib.sha1((objet + corps).encode()).hexdigest()[:16]}@example.test>"
    for cle, valeur in (extra or {}).items():
        msg[cle] = valeur
    msg.set_content(corps)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    for nom, mime, octets in pieces or []:
        principal, _, sous = mime.partition("/")
        msg.add_attachment(octets, maintype=principal, subtype=sous, filename=nom)
    return msg.as_bytes()


def pdf_fictif(texte: str = "facture fictive") -> bytes:
    return b"%PDF-1.4\n% " + texte.encode() + b"\n%%EOF\n"


# ============================================================================================ transport
class Aiguilleur:
    """Transport de test : un double par hôte. Un hôte inconnu est une ERREUR de test (jamais de réseau)."""

    def __init__(self, **hotes: Any) -> None:
        self.hotes: dict[str, Any] = {h.replace("_", "."): d for h, d in hotes.items()}
        self.requetes: list[RequeteHttp] = []

    def ajouter(self, hote: str, double: Any) -> None:
        self.hotes[hote] = double

    def envoyer(self, requete: RequeteHttp) -> ReponseHttp:
        self.requetes.append(requete)
        hote = urllib.parse.urlsplit(requete.url).hostname or ""
        if hote not in self.hotes:
            raise AssertionError(f"requête vers un hôte non simulé : {hote}")
        return self.hotes[hote].traiter(requete)


def _json(statut: int, donnees: Any, entetes: dict[str, str] | None = None) -> ReponseHttp:
    return ReponseHttp(
        statut, {"content-type": "application/json", **(entetes or {})}, json.dumps(donnees).encode("utf-8")
    )


class _Base:
    """Comportements communs : réponses scriptées d'avance, jeton valide, journal de requêtes."""

    def __init__(self) -> None:
        self.tokens_valides: set[str] = set()
        self.scripts: list[ReponseHttp | Exception] = []
        self.requetes: list[RequeteHttp] = []

    def scripter(self, *reponses: ReponseHttp | Exception) -> None:
        self.scripts.extend(reponses)

    def traiter(self, requete: RequeteHttp) -> ReponseHttp:
        self.requetes.append(requete)
        if self.scripts:
            suivante = self.scripts.pop(0)
            if isinstance(suivante, Exception):
                raise suivante
            return suivante
        jeton = requete.entetes.get("Authorization", "").removeprefix("Bearer ")
        if jeton not in self.tokens_valides:
            return _json(401, {"error": {"code": 401, "message": "Invalid Credentials", "status": "UNAUTHENTICATED"}})
        return self.repondre(requete)

    def repondre(self, requete: RequeteHttp) -> ReponseHttp:  # pragma: no cover — surchargée
        raise NotImplementedError


def reponse_429(attente: str = "2") -> ReponseHttp:
    return _json(429, {"error": {"code": 429, "message": "Too Many Requests"}}, {"retry-after": attente})


def reponse_5xx(statut: int = 503, attente: str | None = None) -> ReponseHttp:
    return _json(
        statut, {"error": {"code": statut, "message": "Backend Error"}}, {"retry-after": attente} if attente else None
    )


def reponse_403_debit() -> ReponseHttp:
    return _json(403, {"error": {"code": 403, "errors": [{"reason": "userRateLimitExceeded"}]}})


# ============================================================================================ Gmail
class FauxGmail(_Base):
    HOTE = "gmail.googleapis.com"

    def __init__(self, adresse: str = "paul.fictif@example.test") -> None:
        super().__init__()
        self.adresse = adresse
        self.messages: dict[str, dict[str, Any]] = {}
        self.historique: list[dict[str, Any]] = []
        self.history_id = 5000
        self.history_min = 5000
        self.envoyes: list[bytes] = []
        self.taille_page_max = 500
        self._n = 0

    def ajouter(self, raw: bytes, labels: tuple[str, ...] = ("INBOX",)) -> str:
        self._n += 1
        identifiant = f"{self._n:016x}"
        self.history_id += 1
        self.messages[identifiant] = {
            "raw": raw,
            "thread": f"t{self._n:015x}",
            "labels": set(labels),
            "internal": 1_790_000_000_000 + self._n * 1000,
        }
        self.historique.append({"id": self.history_id, "type": "added", "message": identifiant, "labels": list(labels)})
        return identifiant

    def supprimer(self, identifiant: str) -> None:
        self.history_id += 1
        labels = list(self.messages.pop(identifiant)["labels"])
        self.historique.append({"id": self.history_id, "type": "deleted", "message": identifiant, "labels": labels})

    def purger_historique(self) -> None:
        """Simule l'expiration de l'historique : les historyId plus anciens répondent 404."""
        self.history_min = self.history_id + 1

    def repondre(self, requete: RequeteHttp) -> ReponseHttp:
        url = urllib.parse.urlsplit(requete.url)
        params = urllib.parse.parse_qs(url.query)
        chemin = url.path.removeprefix("/gmail/v1/users/me")
        if requete.methode == "GET" and chemin == "/profile":
            return _json(
                200,
                {
                    "emailAddress": self.adresse,
                    "messagesTotal": len(self.messages),
                    "threadsTotal": len(self.messages),
                    "historyId": str(self.history_id),
                },
            )
        if requete.methode == "GET" and chemin == "/labels":
            return _json(
                200,
                {
                    "labels": [
                        {"id": "INBOX", "name": "INBOX", "type": "system"},
                        {"id": "SENT", "name": "SENT", "type": "system"},
                        {"id": "Label_1", "name": "Clients", "type": "user"},
                    ]
                },
            )
        if requete.methode == "GET" and chemin == "/messages":
            return self._lister(params)
        if requete.methode == "GET" and chemin == "/history":
            return self._histoire(params)
        if requete.methode == "GET" and chemin.startswith("/messages/"):
            identifiant = chemin.removeprefix("/messages/")
            if identifiant not in self.messages:
                return _json(404, {"error": {"code": 404, "message": "Requested entity was not found."}})
            m = self.messages[identifiant]
            return _json(
                200,
                {
                    "id": identifiant,
                    "threadId": m["thread"],
                    "labelIds": sorted(m["labels"]),
                    "internalDate": str(m["internal"]),
                    "sizeEstimate": len(m["raw"]),
                    "raw": base64.urlsafe_b64encode(m["raw"]).decode().rstrip("="),
                },
            )
        if requete.methode == "POST" and chemin == "/messages/send":
            donnees = json.loads(requete.corps or b"{}")
            brut = base64.urlsafe_b64decode(donnees["raw"] + "=" * (-len(donnees["raw"]) % 4))
            self.envoyes.append(brut)
            return _json(200, {"id": "envoye" + str(len(self.envoyes)), "threadId": "tsend", "labelIds": ["SENT"]})
        return _json(404, {"error": {"code": 404, "message": "route inconnue du double"}})

    def _pager(self, elements: list[Any], params: dict[str, list[str]]) -> tuple[list[Any], str | None]:
        taille = min(int(params.get("maxResults", ["100"])[0]), self.taille_page_max)
        debut = int(params["pageToken"][0].removeprefix("tok") if "pageToken" in params else 0)
        suite = f"tok{debut + taille}" if debut + taille < len(elements) else None
        return elements[debut : debut + taille], suite

    def _lister(self, params: dict[str, list[str]]) -> ReponseHttp:
        labels = set(params.get("labelIds", []))
        ids = [i for i, m in self.messages.items() if not labels or labels & m["labels"]]
        page, suite = self._pager(ids, params)
        corps: dict[str, Any] = {"resultSizeEstimate": len(ids)}
        if page:
            corps["messages"] = [{"id": i, "threadId": self.messages[i]["thread"]} for i in page]
        if suite:
            corps["nextPageToken"] = suite
        return _json(200, corps)

    def _histoire(self, params: dict[str, list[str]]) -> ReponseHttp:
        depart = int(params["startHistoryId"][0])
        if depart < self.history_min:
            return _json(404, {"error": {"code": 404, "message": "Requested entity was not found."}})
        label = params.get("labelId", [None])[0]
        evenements = [e for e in self.historique if e["id"] > depart and (label is None or label in e["labels"])]
        page, suite = self._pager(evenements, params)
        corps: dict[str, Any] = {"historyId": str(self.history_id)}
        if page:
            corps["history"] = [
                {
                    "id": str(e["id"]),
                    ("messagesAdded" if e["type"] == "added" else "messagesDeleted"): [
                        {"message": {"id": e["message"], "threadId": "t", "labelIds": e["labels"]}}
                    ],
                }
                for e in page
            ]
        if suite:
            corps["nextPageToken"] = suite
        return _json(200, corps)


# ============================================================================================ Graph
class FauxGraph(_Base):
    HOTE = "graph.microsoft.com"

    def __init__(self) -> None:
        super().__init__()
        self.messages: dict[str, dict[str, Any]] = {}
        self.changes: list[dict[str, Any]] = []
        self.seq = 0
        self.envoyes: list[dict[str, Any]] = []
        self.delta_expire = False
        self.page = 100
        self.liens_forces: dict[str, str] = {}  # substitution hostile d'un lien (test SSRF)

    def ajouter(self, raw: bytes, dossier: str = "inbox") -> str:
        self.seq += 1
        identifiant = "AAMk" + hashlib.sha1(str(self.seq).encode()).hexdigest()[:20] + "AAA="
        self.messages[identifiant] = {
            "raw": raw,
            "dossier": dossier,
            "conv": f"AAQk{self.seq:08d}=",
            "recu": "2026-10-30T18:00:00Z",
        }
        self.changes.append({"seq": self.seq, "id": identifiant, "dossier": dossier, "supprime": False})
        return identifiant

    def supprimer(self, identifiant: str) -> None:
        self.seq += 1
        m = self.messages.pop(identifiant)
        self.changes.append({"seq": self.seq, "id": identifiant, "dossier": m["dossier"], "supprime": True})

    def repondre(self, requete: RequeteHttp) -> ReponseHttp:
        url = urllib.parse.urlsplit(requete.url)
        params = urllib.parse.parse_qs(url.query)
        chemin = urllib.parse.unquote(url.path).removeprefix("/v1.0/me")
        if requete.methode == "GET" and chemin == "/mailFolders":
            return _json(
                200,
                {
                    "value": [
                        {"id": "inbox", "displayName": "Boîte de réception"},
                        {"id": "AAMkFOLDER1=", "displayName": "Clients"},
                    ]
                },
            )
        if requete.methode == "GET" and chemin.startswith("/mailFolders/") and chemin.endswith("/messages/delta"):
            return self._delta(chemin.split("/")[2], params)
        if requete.methode == "GET" and chemin.startswith("/messages/") and chemin.endswith("/$value"):
            identifiant = chemin.split("/")[2]
            if identifiant not in self.messages:
                return _json(404, {"error": {"code": "ErrorItemNotFound"}})
            return ReponseHttp(200, {"content-type": "text/plain"}, self.messages[identifiant]["raw"])
        if requete.methode == "GET" and chemin.startswith("/messages/"):
            identifiant = chemin.split("/")[2]
            if identifiant not in self.messages:
                return _json(404, {"error": {"code": "ErrorItemNotFound"}})
            m = self.messages[identifiant]
            return _json(200, {"id": identifiant, "conversationId": m["conv"], "receivedDateTime": m["recu"]})
        if requete.methode == "POST" and chemin == "/sendMail":
            self.envoyes.append(json.loads(requete.corps or b"{}"))
            return ReponseHttp(202, {}, b"")
        return _json(404, {"error": {"code": "ErrorInvalidRequest"}})

    def _delta(self, dossier: str, params: dict[str, list[str]]) -> ReponseHttp:
        base = f"https://graph.microsoft.com/v1.0/me/mailFolders/{urllib.parse.quote(dossier, safe='')}/messages/delta"
        if "$deltatoken" in params:
            if self.delta_expire:
                return _json(410, {"error": {"code": "syncStateNotFound"}})
            depart, decalage = int(params["$deltatoken"][0].removeprefix("d")), 0
        elif "$skiptoken" in params:
            depart, decalage = (int(x) for x in params["$skiptoken"][0].removeprefix("s").split("_"))
        else:
            depart, decalage = 0, 0
        en_attente = [c for c in self.changes if c["seq"] > depart and c["dossier"] == dossier]
        # Un message ajouté puis supprimé : seul l'état final est rendu, comme le fait Graph.
        etat_final: dict[str, dict[str, Any]] = {}
        for c in en_attente:
            etat_final[c["id"]] = c
        elements = list(etat_final.values())
        morceau = elements[decalage : decalage + self.page]
        valeurs = [
            (
                {"id": c["id"], "@removed": {"reason": "deleted"}}
                if c["supprime"]
                else {"id": c["id"], "conversationId": self.messages[c["id"]]["conv"]}
            )
            for c in morceau
        ]
        corps: dict[str, Any] = {"value": valeurs}
        if decalage + self.page < len(elements):
            lien = f"{base}?$skiptoken=s{depart}_{decalage + self.page}"
            corps["@odata.nextLink"] = self.liens_forces.get("nextLink", lien)
        else:
            lien = f"{base}?$deltatoken=d{self.seq}"
            corps["@odata.deltaLink"] = self.liens_forces.get("deltaLink", lien)
        return _json(200, corps)


# ============================================================================================ OAuth
class FauxOAuth(_Base):
    """Point de jeton + révocation. Un test choisit les portées renvoyées, la rotation, `invalid_grant`."""

    def __init__(
        self,
        hote: str,
        horloge: Horloge,
        *,
        scope_accorde: str,
        refresh: bool = True,
        rotation: bool = False,
        duree: int = 3600,
    ) -> None:
        super().__init__()
        self.HOTE = hote
        self.horloge, self.scope_accorde, self.avec_refresh = horloge, scope_accorde, refresh
        self.rotation, self.duree = rotation, duree
        self.codes: dict[str, str] = {}  # code -> code_challenge attendu
        self.refresh_valides: set[str] = set()
        self.revoques: list[str] = []
        self.invalid_grant = False
        self.emis = 0
        self.dernier_acces = ""
        self.reponses_scope: bool = True
        self.clients: set[str] = set()
        self.secret_client: str | None = None
        self.cibles: list[Any] = []

    def traiter(self, requete: RequeteHttp) -> ReponseHttp:
        self.requetes.append(requete)
        if self.scripts:
            suivante = self.scripts.pop(0)
            if isinstance(suivante, Exception):
                raise suivante
            return suivante
        champs = {k: v[0] for k, v in urllib.parse.parse_qs((requete.corps or b"").decode()).items()}
        if requete.url.endswith("/revoke"):
            self.revoques.append(champs.get("token", ""))
            return ReponseHttp(200, {}, b"{}")
        if self.secret_client is not None and champs.get("client_secret") != self.secret_client:
            return _json(401, {"error": "invalid_client"})
        if champs.get("grant_type") == "authorization_code":
            attendu = self.codes.pop(champs.get("code", ""), None)
            verifier = champs.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            if attendu is None or challenge != attendu:
                return _json(400, {"error": "invalid_grant", "error_description": "Bad Request"})
            return self._jetons(nouveau_refresh=True)
        if champs.get("grant_type") == "refresh_token":
            if self.invalid_grant or champs.get("refresh_token") not in self.refresh_valides:
                return _json(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            return self._jetons(nouveau_refresh=self.rotation, ancien=champs["refresh_token"])
        return _json(400, {"error": "unsupported_grant_type"})

    def _jetons(self, *, nouveau_refresh: bool, ancien: str | None = None) -> ReponseHttp:
        self.emis += 1
        acces = f"acces-fictif-{self.emis}-{hashlib.sha1(str(self.emis).encode()).hexdigest()[:12]}"
        self.dernier_acces = acces
        corps: dict[str, Any] = {"access_token": acces, "expires_in": self.duree, "token_type": "Bearer"}
        if self.reponses_scope:
            corps["scope"] = self.scope_accorde
        if self.avec_refresh and nouveau_refresh:
            refresh = f"refresh-fictif-{self.emis}-{hashlib.sha1(('r' + str(self.emis)).encode()).hexdigest()[:12]}"
            if ancien:
                self.refresh_valides.discard(ancien)
            self.refresh_valides.add(refresh)
            corps["refresh_token"] = refresh
        for cible in self.cibles:
            cible.tokens_valides = {acces}  # un nouveau jeton remplace l'ancien chez le fournisseur d'API
        return _json(200, corps)

    def autoriser(self, code: str, verifier_challenge: str) -> None:
        self.codes[code] = verifier_challenge

    def expirer_acces(self) -> None:
        for cible in self.cibles:
            cible.tokens_valides = set()


# ============================================================================================ stockage de jetons
class StockageJetonsMemoire:
    """`StockageJetons` en mémoire (tests d'adaptateur hors coffre). Compte les lectures et les écritures."""

    def __init__(self) -> None:
        self.donnees: dict[str, JeuJetons] = {}
        self.ecritures: list[str] = []
        self.revoques: list[str] = []

    def lire(self, nom_secret: str) -> JeuJetons:
        return self.donnees[nom_secret]

    def ecrire(self, nom_secret: str, jeu: JeuJetons, *, service: str) -> None:
        self.donnees[nom_secret] = jeu
        self.ecritures.append(nom_secret)

    def revoquer(self, nom_secret: str) -> None:
        self.revoques.append(nom_secret)
        self.donnees.pop(nom_secret, None)


# ============================================================================================ IMAP / SMTP
class FauxServeurImap:
    def __init__(
        self, utilisateur: str = "paul.fictif@example.test", mot_de_passe: str = "mot-de-passe-app-fictif-0001"
    ):
        self.utilisateur, self.mot_de_passe = utilisateur, mot_de_passe
        self.dossiers: dict[str, dict[str, Any]] = {"INBOX": {"uidvalidity": 1700000001, "messages": {}, "suivant": 1}}
        self.commandes: list[tuple] = []
        self.connexions = 0
        self.fermetures = 0
        self.panne_connexion = False

    def ajouter(self, raw: bytes, dossier: str = "INBOX") -> int:
        d = self.dossiers.setdefault(dossier, {"uidvalidity": 1700000002, "messages": {}, "suivant": 1})
        uid = d["suivant"]
        d["suivant"] += 1
        d["messages"][uid] = raw
        return uid

    def changer_uidvalidity(self, dossier: str = "INBOX") -> None:
        self.dossiers[dossier]["uidvalidity"] += 1


class FauxImap4SSL:
    """Imite l'API de `imaplib.IMAP4_SSL` utilisée par l'adaptateur : le résultat de `uid()` a la forme réelle."""

    def __init__(self, serveur: FauxServeurImap):
        self.serveur = serveur
        self.dossier: str | None = None

    def __call__(self, hote: str, port: int = 993, timeout: float | None = None) -> FauxImap4SSL:
        self.serveur.connexions += 1
        if self.serveur.panne_connexion:
            raise OSError("connexion refusée (double)")
        self.serveur.commandes.append(("connect", hote, port))
        instance = FauxImap4SSL(self.serveur)
        return instance

    def login(self, utilisateur: str, mot_de_passe: str):
        self.serveur.commandes.append(("login", utilisateur))  # jamais le mot de passe dans le journal du double
        if (utilisateur, mot_de_passe) != (self.serveur.utilisateur, self.serveur.mot_de_passe):
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"Logged in"]

    def list(self):
        self.serveur.commandes.append(("list",))
        lignes = [b'(\\HasNoChildren) "/" "' + n.encode() + b'"' for n in self.serveur.dossiers]
        lignes.append(b'(\\Noselect \\HasChildren) "/" "[Gmail]"')
        lignes.append(b'(\\HasNoChildren \\Sent) "/" "Elements envoyes"')
        return "OK", lignes

    def select(self, mailbox: str = "INBOX", readonly: bool = False):
        self.serveur.commandes.append(("select", mailbox, readonly))
        assert mailbox.startswith('"') and mailbox.endswith('"'), "nom de dossier non cité"
        nom = re.sub(r"\\(.)", r"\1", mailbox[1:-1])
        if nom not in self.serveur.dossiers:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
        self.dossier = nom
        return "OK", [str(len(self.serveur.dossiers[nom]["messages"])).encode()]

    def response(self, code: str):
        assert self.dossier is not None
        if code == "UIDVALIDITY":
            return code, [str(self.serveur.dossiers[self.dossier]["uidvalidity"]).encode()]
        return code, [None]

    def uid(self, commande: str, *args: Any):
        self.serveur.commandes.append(("uid", commande, *[a for a in args if a is not None]))
        assert self.dossier is not None
        messages = self.serveur.dossiers[self.dossier]["messages"]
        if commande == "SEARCH":
            critere = args[-1]
            debut = int(critere.split(":")[0])
            uids = sorted(u for u in messages if u >= debut)
            if not uids and messages:  # la bizarrerie réelle de `UID n:*` : toujours au moins le dernier message
                uids = [max(messages)]
            return "OK", [b" ".join(str(u).encode() for u in uids)]
        if commande == "FETCH":
            uid = int(args[0])
            if uid not in messages:
                return "OK", [None]
            if "RFC822.SIZE" in args[1]:
                return "OK", [f"{uid} (UID {uid} RFC822.SIZE {len(messages[uid])})".encode()]
            return "OK", [(f"{uid} (UID {uid} BODY[] {{{len(messages[uid])}}}".encode(), messages[uid]), b")"]
        return "BAD", [b"commande inconnue"]

    def logout(self):
        self.serveur.fermetures += 1
        return "BYE", [b"Logging out"]


class FauxServeurSmtp:
    def __init__(self, utilisateur: str, mot_de_passe: str) -> None:
        self.utilisateur, self.mot_de_passe = utilisateur, mot_de_passe
        self.envoyes: list[dict[str, Any]] = []
        self.refuser_destinataires = False
        self.panne_pendant_envoi = False
        self.connexions = 0


class FauxSmtpSSL:
    def __init__(self, serveur: FauxServeurSmtp) -> None:
        self.serveur = serveur

    def __call__(self, hote: str, port: int = 465, timeout: float | None = None) -> FauxSmtpSSL:
        self.serveur.connexions += 1
        return FauxSmtpSSL(self.serveur)

    def login(self, utilisateur: str, mot_de_passe: str) -> None:
        if (utilisateur, mot_de_passe) != (self.serveur.utilisateur, self.serveur.mot_de_passe):
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")

    def send_message(self, message: EmailMessage, from_addr: str, to_addrs: list[str]) -> dict:
        if self.serveur.refuser_destinataires:
            raise smtplib.SMTPRecipientsRefused({a: (550, b"no such user") for a in to_addrs})
        if self.serveur.panne_pendant_envoi:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        self.serveur.envoyes.append({"de": from_addr, "a": list(to_addrs), "message": message.as_bytes()})
        return {}

    def quit(self) -> None:
        return None
