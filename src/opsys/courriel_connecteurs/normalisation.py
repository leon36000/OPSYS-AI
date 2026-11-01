"""Normalisation : un courriel brut (RFC 5322 / MIME) devient un `MessageNormalise`, le même pour tous les fournisseurs.

Le courriel est une DONNÉE NON FIABLE, y compris son objet, le nom de l'expéditeur, les noms de pièces jointes et les
en-têtes. Ce module ne l'interprète jamais : il le DÉCODE, le BORNE et le NETTOIE (caractères de contrôle, bidi,
largeur nulle ; HTML réduit à son texte VISIBLE : scripts, styles, commentaires et contenu masqué sont écartés). Il ne
le rend pas pour autant sûr : tout usage par un agent passe par `isolation.vue_pour_agent`.

Bornes (courriel hostile) : source 32 Mio, 100 pièces, 8 Mio par pièce (au-delà : métadonnées et empreinte seulement),
profondeur MIME bornée par l'analyseur (RecursionError attrapée), corps 200 000 caractères.
Les pièces jointes ne sont jamais ouvertes, décodées ni exécutées : empreinte SHA-256, signature (octets magiques) pour
vérifier le type MIME déclaré, et c'est tout.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import html.parser
import re
import unicodedata
import zipfile
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from io import BytesIO

from .erreurs import ErreurCourriel
from .modele import Adresse, Authentification, MessageBrut, MessageNormalise, PieceJointe

SOURCE_MAX = 32 * 1024 * 1024
PIECE_MAX = 8 * 1024 * 1024
PIECES_MAX = 100
CORPS_MAX = 200_000
OBJET_MAX = 500
NOM_MAX = 255
_ADRESSE = re.compile(r"^[A-Za-z0-9._%+'=!#$&*/?^`{|}~-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
# Caractères de contrôle (sauf \t \n), invisibles et marques bidirectionnelles : détournent un nom de fichier ou cachent
# du texte à l'œil humain.
_INVISIBLES = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f­؜᠎​-‏‪-‮⁠-⁤"
                         "⁦-⁯﻿￹-￻]")
_MASQUE_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|%)?\s*(?:;|$)"
                           r"|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)|(?:^|;)\s*height\s*:\s*0(?:px)?\s*;?[^;]*overflow\s*:\s*hidden"
                           r"|text-indent\s*:\s*-\d{3,}|mso-hide\s*:\s*all", re.IGNORECASE)
_EXTENSIONS_DANGEREUSES = frozenset({
    "exe", "scr", "bat", "cmd", "com", "pif", "js", "jse", "vbs", "vbe", "wsf", "wsh", "ps1", "psm1", "msi", "msp",
    "jar", "lnk", "reg", "hta", "cpl", "dll", "sh", "apk", "iso", "img", "docm", "xlsm", "pptm", "html", "htm", "svg",
})
_MIME_PAR_EXTENSION = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "txt": "text/plain", "csv": "text/plain", "zip": "application/zip",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_EQUIVALENTS = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "text/csv": "text/plain",
                "application/x-pdf": "application/pdf", "application/x-zip-compressed": "application/zip",
                "text/html": "text/html"}
_ETATS = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror"}


# ============================================================================================ texte
def nettoyer_texte(texte: str, *, maximum: int = CORPS_MAX) -> tuple[str, bool]:
    """Texte sans contrôle ni invisibles, fins de ligne `\\n`, lignes vides consécutives réduites à une ; `(texte,
    tronque)`."""
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    texte = _INVISIBLES.sub("", texte)
    texte = re.sub(r"[ \t\f\v]+\n", "\n", texte)
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    if len(texte) > maximum:
        return texte[:maximum], True
    return texte, False


def nettoyer_ligne(texte: str, maximum: int) -> str:
    """Une seule ligne : espaces normalisés, invisibles retirés, bornée."""
    texte = _INVISIBLES.sub("", texte)
    return re.sub(r"\s+", " ", texte).strip()[:maximum]


class _ExtracteurHtml(html.parser.HTMLParser):
    """Texte VISIBLE d'un HTML : ni script, ni style, ni commentaire, ni élément masqué (display:none, taille 0,
    attribut `hidden`…). Le contenu masqué est le véhicule classique d'une injection de consigne invisible à
    l'humain."""

    _IGNORES = frozenset({"script", "style", "head", "title", "template", "noscript", "iframe", "object", "embed",
                          "svg", "math", "meta", "link", "base"})
    _VIDES = frozenset({"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "wbr"})
    _BLOCS = frozenset({"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
                        "blockquote", "pre", "section", "article", "header", "footer", "hr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._morceaux: list[str] = []
        self._pile: list[bool] = []  # un booléen par balise ouverte : l'élément est-il masqué ?
        self._masque = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCS:
            self._morceaux.append("\n")
        if tag in self._VIDES:
            return
        dictionnaire = {k.lower(): (v or "") for k, v in attrs}
        masque = (tag in self._IGNORES or "hidden" in dictionnaire or dictionnaire.get("aria-hidden") == "true"
                  or bool(_MASQUE_STYLE.search(dictionnaire.get("style", "")))
                  or dictionnaire.get("type", "").lower() == "hidden")
        self._pile.append(masque)
        self._masque += masque

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VIDES:
            return
        if self._pile:
            self._masque -= self._pile.pop()
        if tag in self._BLOCS:
            self._morceaux.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._masque:
            self._morceaux.append(data)

    def handle_comment(self, data: str) -> None:  # les commentaires ne sont jamais du texte visible
        return

    def texte(self) -> str:
        return "".join(self._morceaux)


def html_vers_texte(source: str) -> str:
    extracteur = _ExtracteurHtml()
    try:
        extracteur.feed(source[: 4 * CORPS_MAX])
        extracteur.close()
    except (ValueError, RecursionError, AssertionError):
        raise ErreurCourriel("REJ-COURRIEL-MESSAGE-INVALIDE", "HTML illisible", 422) from None
    return extracteur.texte()


# ============================================================================================ pièces jointes
def _texte_probable(octets: bytes) -> bool:
    if not octets or b"\x00" in octets[:8192]:
        return False
    try:
        echantillon = octets[:8192].decode("utf-8")
    except UnicodeDecodeError:
        try:
            echantillon = octets[:8192].decode("cp1252")
        except UnicodeDecodeError:
            return False
    imprimables = sum(1 for c in echantillon if c.isprintable() or c in "\r\n\t")
    return imprimables >= 0.95 * len(echantillon)


def detecter_mime(octets: bytes) -> str:
    """Type d'après les octets magiques seulement (jamais le nom ni le type déclaré)."""
    debut = octets[:16]
    if debut.startswith(b"%PDF-"):
        return "application/pdf"
    if debut.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if debut.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if debut.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if debut.startswith(b"MZ"):
        return "application/x-msdownload"
    if debut.startswith(b"\x7fELF"):
        return "application/x-elf"
    if debut.startswith((b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")):
        return "application/x-mach-binary"
    if debut.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if debut.startswith(b"{\\rtf"):
        return "application/rtf"
    if debut.startswith(b"PK\x03\x04") or debut.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(BytesIO(octets)) as archive:
                noms = archive.namelist()[:2000]
        except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
            return "application/zip"
        if any(n.startswith("xl/") for n in noms):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if any(n.startswith("word/") for n in noms):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if any(n.startswith("ppt/") for n in noms):
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return "application/zip"
    if octets.lstrip()[:2] == b"#!":
        return "text/x-script"
    if octets.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html", b"<script", b"<svg")):
        return "text/html"
    if _texte_probable(octets):
        return "text/plain"
    return "application/octet-stream"


def nom_sur(nom: str | None, repli: str = "sans-nom") -> str:
    """Nom d'affichage assaini : jamais un chemin, jamais de contrôle ni de marque bidi (`facture‮fdp.exe`)."""
    nom = nettoyer_ligne(nom or "", NOM_MAX * 2)
    nom = nom.replace("\\", "/").rsplit("/", 1)[-1].strip(" .")
    nom = re.sub(r"[<>:\"|?*]", "_", nom)[:NOM_MAX]
    return nom or repli


def _piece(partie: EmailMessage) -> PieceJointe | None:
    try:
        octets = partie.get_payload(decode=True)
        if octets is None and partie.get_content_type() == "message/rfc822":
            octets = b"".join(sous.as_bytes() for sous in partie.get_payload())  # type: ignore[union-attr]
        if not isinstance(octets, bytes):
            return None
        nom = nom_sur(partie.get_filename())
        declare = partie.get_content_type().lower()
    except (LookupError, ValueError, UnicodeError, TypeError, AttributeError, IndexError):
        return None
    declare = _EQUIVALENTS.get(declare, declare)
    detecte = detecter_mime(octets)
    extension = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    attendu_extension = _MIME_PAR_EXTENSION.get(extension)
    coherent_extension = attendu_extension is None or attendu_extension == detecte
    # Vérifié : le type déclaré est le type détecté (équivalents admis). « octet-stream » ne vérifie rien.
    verifie = declare == detecte or (declare == "application/zip" and detecte.startswith("application/vnd.openxml"))
    dangereux = (detecte in {"application/x-msdownload", "application/x-elf", "application/x-mach-binary",
                             "text/x-script", "text/html"} or extension in _EXTENSIONS_DANGEREUSES)
    trop_gros = len(octets) > PIECE_MAX
    return PieceJointe(nom=nom, mime_declare=declare[:100], mime_detecte=detecte, mime_verifie=verifie,
                       extension_coherente=coherent_extension, dangereux=dangereux, taille=len(octets),
                       sha256=hashlib.sha256(octets).hexdigest(), octets=b"" if trop_gros else octets,
                       refus="trop_gros" if trop_gros else None)


# ============================================================================================ en-têtes
def _adresses(valeurs: list[str]) -> tuple[tuple[Adresse, ...], int]:
    adresses, invalides = [], 0
    for nom, courriel in getaddresses(valeurs)[:200]:
        courriel = courriel.strip().lower()
        if _ADRESSE.fullmatch(courriel):
            adresses.append(Adresse(courriel, nettoyer_ligne(nom, 120)))
        elif courriel or nom:
            invalides += 1
    return tuple(adresses), invalides


def _entetes(message: EmailMessage, nom: str) -> list[str]:
    valeurs = []
    for valeur in message.get_all(nom, []) or []:
        try:
            valeurs.append(str(valeur))
        except (ValueError, UnicodeError, LookupError):
            continue
    return valeurs


def _date_utc(message: EmailMessage, secours: str | None) -> str | None:
    for brut in _entetes(message, "date")[:1] + ([secours] if secours else []):
        try:
            date = parsedate_to_datetime(brut) if brut is not secours else datetime.fromisoformat(brut)
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        try:
            return date.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OverflowError):
            continue
    return None


def authentification(message: EmailMessage, serveurs_fiables: frozenset[str] | None) -> Authentification:
    """Lit l'en-tête `Authentication-Results` LE PLUS HAUT (celui que le serveur de réception a ajouté en dernier ; les
    suivants peuvent avoir été écrits par l'expéditeur). N'est `fiable` que si l'identifiant du serveur est connu."""
    entetes = _entetes(message, "authentication-results")
    if not entetes:
        return Authentification()
    haut = " ".join(entetes[0].split())
    serveur = haut.split(";", 1)[0].strip().split(" ")[0].lower()[:100] or None
    resultats = {"spf": "absent", "dkim": "absent", "dmarc": "absent"}
    for methode, verdict in re.findall(r"\b(spf|dkim|dmarc)\s*=\s*([a-z]+)", haut, re.IGNORECASE):
        methode, verdict = methode.lower(), verdict.lower()
        verdict = verdict if verdict in _ETATS else "inconnu"
        if resultats[methode] in {"absent", "inconnu"} or (methode == "dkim" and verdict == "pass"):
            resultats[methode] = verdict
    fiable = bool(serveurs_fiables) and serveur in {s.lower() for s in serveurs_fiables}
    return Authentification(resultats["spf"], resultats["dkim"], resultats["dmarc"], serveur, fiable)


def _corps(message: EmailMessage) -> tuple[str, EmailMessage | None]:
    try:
        corps = message.get_body(preferencelist=("plain", "html"))
    except (LookupError, ValueError, TypeError, AttributeError, IndexError):
        corps = None
    if corps is None:
        return "", None
    try:
        contenu = corps.get_content()
    except (LookupError, ValueError, UnicodeError, AssertionError):
        brut = corps.get_payload(decode=True) or b""
        contenu = brut.decode("utf-8", "replace") if isinstance(brut, bytes) else ""
    if not isinstance(contenu, str):
        return "", corps
    return (html_vers_texte(contenu) if corps.get_content_type() == "text/html" else contenu), corps


def _fil(message_id: str | None, references: str, en_reponse_a: str, fournisseur: str | None) -> str:
    if fournisseur:
        return fournisseur[:128]
    liens = references.split()
    racine = (liens[0] if liens else en_reponse_a.strip() or message_id or "").strip("<>")
    return "msgid:" + hashlib.sha256(racine.encode("utf-8")).hexdigest()[:32]


def empreinte_message(expediteur: Adresse | None, destinataires: tuple[Adresse, ...], objet: str, date_utc: str | None,
                      corps: str, pieces: tuple[PieceJointe, ...]) -> str:
    """Empreinte du CONTENU (pas des octets de transport) : un même courriel vu dans deux dossiers, avec des en-têtes
    `Received` différents, donne la même empreinte ; un contenu modifié en donne une autre."""
    canon = "\x1f".join([
        expediteur.courriel if expediteur else "", ",".join(sorted(a.courriel for a in destinataires)), objet,
        date_utc or "", corps, ",".join(sorted(p.sha256 for p in pieces)),
    ])
    return hashlib.sha256(b"opsys:courriel:message:v1:" + canon.encode("utf-8")).hexdigest()


# ============================================================================================ point d'entrée
def normaliser(brut: MessageBrut, *, serveurs_fiables: frozenset[str] | None = None) -> MessageNormalise:
    if len(brut.octets) > SOURCE_MAX:
        raise ErreurCourriel("REJ-COURRIEL-MESSAGE-TROP-GROS", f"message de plus de {SOURCE_MAX} octets", 413)
    if not brut.octets.strip():
        raise ErreurCourriel("REJ-COURRIEL-MESSAGE-INVALIDE", "message vide", 422)
    try:
        message = email.message_from_bytes(brut.octets, policy=email.policy.default)
        if not isinstance(message, EmailMessage):
            raise ValueError("forme")
        mids = _entetes(message, "message-id")
        message_id = nettoyer_ligne(mids[0], 998).strip("<> ") if mids else None
        if message_id is not None and (not message_id or " " in message_id):
            message_id = None
        expediteurs, inv1 = _adresses(_entetes(message, "from"))
        destinataires, inv2 = _adresses(_entetes(message, "to"))
        copie, inv3 = _adresses(_entetes(message, "cc"))
        repondre, inv4 = _adresses(_entetes(message, "reply-to"))
        objets = _entetes(message, "subject")
        objet = nettoyer_ligne(objets[0], OBJET_MAX) if objets else ""
        date_utc = _date_utc(message, brut.recu_le)
        texte_brut, partie_corps = _corps(message)
        corps, tronque = nettoyer_texte(texte_brut)
        pieces: list[PieceJointe] = []
        ignorees = 0
        for partie in message.walk():
            if partie is partie_corps or (partie.is_multipart() and partie.get_content_type() != "message/rfc822"):
                continue
            if partie is message and message.get_content_maintype() == "text":
                continue
            piece = _piece(partie)  # type: ignore[arg-type]
            if piece is None:
                continue
            if len(pieces) >= PIECES_MAX:
                ignorees += 1
                continue
            pieces.append(piece)
        references = " ".join(nettoyer_ligne(r, 1000) for r in _entetes(message, "references"))
        reponse_a = " ".join(nettoyer_ligne(r, 1000) for r in _entetes(message, "in-reply-to"))
        auth = authentification(message, serveurs_fiables)
    except RecursionError:
        raise ErreurCourriel("REJ-COURRIEL-MESSAGE-INVALIDE", "imbrication MIME excessive", 422) from None
    except (ValueError, LookupError, UnicodeError, TypeError, AttributeError, IndexError) as exc:
        if isinstance(exc, ErreurCourriel):
            raise
        raise ErreurCourriel("REJ-COURRIEL-MESSAGE-INVALIDE", "message illisible", 422) from None
    pieces_t = tuple(pieces)
    expediteur = expediteurs[0] if expediteurs else None
    return MessageNormalise(
        id=brut.ref, dossier=brut.dossier, fil=_fil(message_id, references, reponse_a, brut.fil_fournisseur),
        message_id=message_id, expediteur=expediteur, destinataires=destinataires, copie=copie, repondre_a=repondre,
        objet=objet, date_utc=date_utc, corps_texte=corps, corps_tronque=tronque, pieces_jointes=pieces_t,
        pieces_ignorees=ignorees, authentification=auth,
        empreinte=empreinte_message(expediteur, destinataires, objet, date_utc, corps, pieces_t),
        taille_source=len(brut.octets), adresses_invalides=inv1 + inv2 + inv3 + inv4,
    )


def sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
