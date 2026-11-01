"""Exports mbox (Google Takeout, export Workspace, Thunderbird…) en LECTURE SEULE : le chemin du rattrapage historique.

Le fichier est déposé par le client dans `<OPSYS_HOME>/imports/courriel/` et lu par son NOM seul (comme le dépôt
d'onboarding) : pas de chemin, pas de `..`, pas de lien symbolique (`O_NOFOLLOW`), fichier ordinaire, extension `.mbox`
ou `.mbox.gz`. Aucune écriture n'est faite dans ce dossier ni ailleurs.

Protections contre un export hostile :
- taille du fichier, nombre de messages, taille de CHAQUE message (au-delà, le message est référencé mais refusé à la
  lecture sans être chargé) et taille d'une ligne bornées ; un flux sans fin de lignes n'occupe jamais plus de 64 Kio ;
- `.mbox.gz` : bombe de décompression refusée (taille décompressée totale ET ratio de compression, mesurés pendant la
  lecture) ;
- séparateur `From ` reconnu seulement après une ligne vide et avec une date (un corps qui contient « From » ne coupe
  pas un message) ; les lignes `>From ` sont désécapées (mboxrd) ;
- les noms de pièces jointes ne servent jamais de chemin (voir `normalisation.nom_sur`).

Le curseur `mbox:v1:…` (décalage en octets du prochain message + taille du fichier) rend la lecture REPRENABLE ; si la
taille du fichier change, le curseur est périmé. Le port est le même que pour les API (`FournisseurCourriel`) :
l'ingestion ne distingue pas un export d'un compte.
"""

from __future__ import annotations

import dataclasses
import gzip
import os
import re
import stat
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .. import stockage
from .erreurs import ErreurCourriel
from .modele import Boite, Dossier, MessageBrut, PageSync, RefMessage
from .normalisation import SOURCE_MAX
from .port import decoder_curseur, encoder_curseur, limite_valide

_NOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}\.mbox(\.gz)?$")
_SEPARATEUR = re.compile(rb"^From \S+\s+\S{3}\s+\S{3}\s+\d{1,2}\s+\d{2}:\d{2}")
_ECHAPPE = re.compile(rb"^>(>*From )")
_LIGNE_MAX = 65536


@dataclasses.dataclass(frozen=True)
class LimitesMbox:
    fichier_max: int = 10 * 1024**3
    compresse_max: int = 2 * 1024**3
    decompresse_max: int = 20 * 1024**3
    ratio_max: int = 100
    ratio_seuil: int = 64 * 1024 * 1024
    message_max: int = SOURCE_MAX
    messages_max: int = 1_000_000
    page_octets_max: int = 64 * 1024 * 1024


def dossier_imports() -> Path:
    return stockage.dossier_opsys() / "imports" / "courriel"


class _Flux:
    """Lecture ligne à ligne bornée d'un `.mbox` ou `.mbox.gz`, avec mesure du ratio de décompression."""

    def __init__(self, brut: BinaryIO, compresse: bool, limites: LimitesMbox, taille_fichier: int) -> None:
        self._brut, self._limites, self._compresse = brut, limites, compresse
        self._flux: BinaryIO = gzip.GzipFile(fileobj=brut) if compresse else brut  # type: ignore[assignment]
        self.lu = 0
        self._taille_fichier = taille_fichier

    def ligne(self) -> bytes:
        try:
            ligne = self._flux.readline(_LIGNE_MAX)
        except (OSError, EOFError, ValueError, zlib.error):
            raise ErreurCourriel("REJ-COURRIEL-MBOX-FORMAT", "fichier mbox illisible ou compression corrompue",
                                 422) from None
        self.lu += len(ligne)
        if self._compresse:
            if self.lu > self._limites.decompresse_max:
                raise ErreurCourriel("REJ-COURRIEL-MBOX-BOMBE", "taille décompressée excessive", 413)
            if self.lu > self._limites.ratio_seuil and self.lu > self._limites.ratio_max * max(self._brut.tell(), 1):
                raise ErreurCourriel("REJ-COURRIEL-MBOX-BOMBE", "ratio de compression excessif", 413)
        return ligne

    def sauter_jusqu_a(self, decalage: int) -> None:
        if not self._compresse:
            self._flux.seek(decalage)
            self.lu = decalage
            return
        while self.lu < decalage:
            if not self.ligne():
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "décalage au-delà de la fin du fichier", 422)


def _ouvrir(nom: object, dossier: Path | None, limites: LimitesMbox) -> tuple[BinaryIO, bool, int]:
    if not isinstance(nom, str) or _NOM.fullmatch(nom) is None or ".." in nom:
        raise ErreurCourriel("REJ-COURRIEL-MBOX-NOM-INVALIDE",
                             "nom de fichier seul attendu (.mbox ou .mbox.gz), déposé "
                             "dans <OPSYS_HOME>/imports/courriel/ ; jamais un chemin", 422)
    racine = dossier if dossier is not None else dossier_imports()
    try:
        etat_dossier = os.lstat(racine)
    except OSError:
        raise ErreurCourriel("REJ-COURRIEL-MBOX-ABSENT", "dossier d'imports courriel absent", 404) from None
    if not stat.S_ISDIR(etat_dossier.st_mode):
        raise ErreurCourriel("REJ-COURRIEL-MBOX-ABSENT",
                             "le dossier d'imports courriel est un lien ou n'est pas un dossier",
                             422)
    try:
        descripteur = os.open(racine / nom, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise ErreurCourriel("REJ-COURRIEL-MBOX-ABSENT", "fichier absent du dossier d'imports, ou lien symbolique",
                             404) from None
    try:
        etat = os.fstat(descripteur)
        if not stat.S_ISREG(etat.st_mode):
            raise ErreurCourriel("REJ-COURRIEL-MBOX-ABSENT", "ce n'est pas un fichier ordinaire", 422)
        compresse = nom.endswith(".gz")
        maximum = limites.compresse_max if compresse else limites.fichier_max
        if etat.st_size > maximum:
            raise ErreurCourriel("REJ-COURRIEL-MBOX-TROP-GROS", f"fichier de plus de {maximum} octets", 413)
        return os.fdopen(os.dup(descripteur), "rb"), compresse, etat.st_size
    finally:
        os.close(descripteur)


class FournisseurMbox:
    """Lecture seule : pas d'envoi (`envoyer_brouillon` refuse toujours)."""

    identifiant = "mbox"

    def __init__(self, nom: str, *, dossier: Path | None = None, limites: LimitesMbox | None = None) -> None:
        self._nom, self._dossier, self._limites = nom, dossier, limites or LimitesMbox()
        _ouvrir(nom, dossier, self._limites)[0].close()  # valide le nom et l'existence dès la construction
        self._cache: dict[int, bytes | None] = {}
        self._suivant: int | None = None
        self._fin = 0
        self._taille = 0

    # -- balayage -------------------------------------------------------------------------------------------------
    def _balayer(self, depart: int, maximum: int, taille_attendue: int | None) -> Iterator[tuple[int, int,
                                                                                                 bytes | None, bool]]:
        """Rend `(décalage, longueur, octets|None, fin_du_fichier)` ; `octets` est None si le message dépasse la
        borne."""
        brut, compresse, taille = _ouvrir(self._nom, self._dossier, self._limites)
        self._taille = taille
        with brut:
            if taille_attendue is not None and taille != taille_attendue:
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-EXPIRE", "le fichier mbox a changé depuis le curseur", 409)
            flux = _Flux(brut, compresse, self._limites, taille)
            if depart:
                flux.sauter_jusqu_a(depart)
            position = depart
            courant: list[bytes] | None = None
            debut, taille_msg, depasse, avant_vide = depart, 0, False, True
            en_milieu = False
            premier = True
            livres = 0
            while True:
                ligne = flux.ligne()
                if not ligne:
                    self._fin = position
                    if courant is not None:
                        yield debut, taille_msg, (None if depasse else self._clore(courant)), True
                    return
                debut_de_ligne = not en_milieu
                en_milieu = not ligne.endswith(b"\n")
                if debut_de_ligne and avant_vide and ligne.startswith(b"From ") and _SEPARATEUR.match(ligne):
                    if courant is not None:
                        yield debut, taille_msg, (None if depasse else self._clore(courant)), False
                        livres += 1
                        if livres >= maximum:
                            self._suivant = position
                            return
                    courant, debut, taille_msg, depasse = [], position, 0, False
                    premier = False
                elif courant is None:
                    if premier and depart == 0 and ligne.strip():
                        raise ErreurCourriel("REJ-COURRIEL-MBOX-FORMAT", "le fichier ne commence pas par un séparateur "
                                             "« From »", 422)
                    if depart:
                        raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE",
                                             "le décalage ne tombe pas sur un message", 422)
                else:
                    taille_msg += len(ligne)
                    if taille_msg > self._limites.message_max:
                        depasse, courant = True, []
                    if not depasse:
                        courant.append(_ECHAPPE.sub(rb"\1", ligne))
                if debut_de_ligne:
                    avant_vide = ligne in (b"\n", b"\r\n")
                position += len(ligne)

    @staticmethod
    def _clore(lignes: list[bytes]) -> bytes:
        octets = b"".join(lignes)
        return octets[:-1] if octets.endswith(b"\n\n") or octets.endswith(b"\r\n\r\n") else octets

    # -- port -----------------------------------------------------------------------------------------------------
    def lister_boites(self) -> list[Boite]:
        return [Boite(id=self._nom, adresse=self._nom, fournisseur=self.identifiant)]

    def lister_dossiers(self) -> list[Dossier]:
        return [Dossier(self._nom, self._nom)]

    def synchroniser(self, dossier: str, curseur: str | None, *, limite: int = 100) -> PageSync:
        limite = limite_valide(limite)
        if dossier != self._nom:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "dossier inconnu pour cet export", 422)
        depart, taille, total = 0, None, 0
        if curseur is not None:
            etat = decoder_curseur("mbox", curseur)
            if (type(etat.get("o")) is not int or etat["o"] < 0 or type(etat.get("s")) is not int
                    or type(etat.get("n")) is not int or etat["n"] < 0):
                raise ErreurCourriel("REJ-COURRIEL-CURSEUR-INVALIDE", "curseur mbox mal formé", 422)
            depart, taille, total = etat["o"], etat["s"], etat["n"]
        self._cache.clear()
        self._suivant, self._fin, self._taille = None, depart, taille or 0
        refs: list[RefMessage] = []
        budget, termine = 0, True
        for decalage, longueur, octets, fin_fichier in self._balayer(depart, limite, taille):
            total += 1
            if total > self._limites.messages_max:
                raise ErreurCourriel("REJ-COURRIEL-MBOX-TROP-GROS", "trop de messages dans l'export", 413)
            refs.append(RefMessage(f"{decalage}:{longueur}", dossier))
            if octets is not None and budget + len(octets) <= self._limites.page_octets_max:
                self._cache[decalage] = octets
                budget += len(octets)
            termine = fin_fichier
        if self._suivant is not None:
            termine = False
        decalage_suivant = self._suivant if self._suivant is not None else self._fin
        return PageSync(tuple(refs), (), encoder_curseur("mbox", {"o": decalage_suivant, "s": self._taille,
                                                                  "n": total}),
                        termine)

    def lire_message(self, ref: RefMessage) -> MessageBrut:
        trouve = re.fullmatch(r"(\d{1,15}):(\d{1,15})", ref.ref)
        if trouve is None:
            raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "référence mbox invalide", 422)
        decalage, longueur = int(trouve.group(1)), int(trouve.group(2))
        if longueur > self._limites.message_max:
            raise ErreurCourriel("REJ-COURRIEL-MESSAGE-TROP-GROS", "message de l'export au-delà de la borne", 413)
        octets = self._cache.get(decalage)
        if octets is None:
            for _, _, lu, _ in self._balayer(decalage, 1, None):
                octets = lu
                break
        if octets is None:
            raise ErreurCourriel("REJ-COURRIEL-INTROUVABLE", "message absent de l'export", 404)
        return MessageBrut(ref.ref, ref.dossier, octets)

    def envoyer_brouillon(self, *_: object, **__: object) -> None:
        raise ErreurCourriel("REJ-COURRIEL-ENVOI-NON-SUPPORTE", "un export mbox est en lecture seule", 403)

