"""Registre de polices du studio : OFL seulement, empreinte épinglée, lecture TrueType en Python pur.

R5 §3, §9 n°14 : « n'utiliser que des polices OFL ou sous licence du client ; stocker le fichier OFL avec chaque
police ; vérifier la couverture latin-1 et les accents français ». Le registre est un dossier d'instance
(`$OPSYS_HOME/studio/polices/`) qui contient les fichiers `.ttf` et un manifeste `polices.json` écrit par un
administrateur :

    {"schema": "opsys.polices/v1", "polices": [
      {"id": "lato-regular", "famille": "Lato", "style": "Regular", "fichier": "Lato-Regular.ttf",
       "sha256": "<64 hex>", "licence": "OFL-1.1", "source_url": "https://…", "fictif": false}]}

Aucune police n'est livrée avec OPSYS et aucune empreinte n'est inventée ici : sans manifeste, le studio refuse de
composer (`REJ-STUDIO-POLICE-ABSENTE`). Garde-fous, tous fail-closed :
  - licence déclarée = `OFL-1.1` (autre licence : refus) ET la table `name` du fichier (ID 13) mentionne la
    SIL Open Font License (le fichier ne contredit pas le manifeste) ;
  - empreinte SHA-256 du fichier = celle du manifeste (fichier remplacé : refus) ;
  - nom de fichier simple (aucun chemin, aucun lien symbolique), taille bornée ;
  - une police `fictif` (police de test) est refusée en mode production ;
  - un caractère sans glyphe n'est jamais remplacé par le glyphe `.notdef` : le texte est refusé.

Le lecteur TrueType couvre ce que les polices OFL usuelles utilisent : `cmap` formats 4 et 12, `glyf` simple et
composite, `hmtx`. Pas de crénage ni de ligatures (le rendu les ignore comme la mesure : cohérence interne). Les
polices CFF/OpenType (`OTTO`) sont refusées. Une police variable est lue à sa valeur par défaut.

Module sans entrée-sortie propre, sauf `charger_dossier` (lecture seule).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import stat
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_MANIFESTE = "opsys.polices/v1"
NOM_MANIFESTE = "polices.json"
LICENCE_PERMISE = "OFL-1.1"
TAILLE_FICHIER_MAX = 8 * 1024 * 1024
POLICES_MAX = 64
REJ_ABSENTE = "REJ-STUDIO-POLICE-ABSENTE"
REJ_MANIFESTE = "REJ-STUDIO-POLICE-MANIFESTE"
REJ_LICENCE = "REJ-STUDIO-POLICE-LICENCE"
REJ_EMPREINTE = "REJ-STUDIO-POLICE-EMPREINTE"
REJ_FICHIER = "REJ-STUDIO-POLICE-FICHIER"
REJ_FICTIVE = "REJ-STUDIO-POLICE-FICTIVE-EN-PRODUCTION"
REJ_GLYPHE = "REJ-STUDIO-POLICE-GLYPHE-ABSENT"

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
_FICHIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.ttf$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NOTICE_OFL = re.compile(r"(sil\s+)?open\s+font\s+license", re.IGNORECASE)
PROFONDEUR_COMPOSITE_MAX = 4
POINTS_GLYPHE_MAX = 4000

# Un contour : point de depart puis segments `("L", x, y)` ou `("Q", cx, cy, x, y)` (unités de la police).
Contour = tuple[tuple[float, float], tuple[tuple, ...]]


class PoliceErreur(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


def _u16(donnees: bytes, position: int) -> int:
    return struct.unpack_from(">H", donnees, position)[0]


def _i16(donnees: bytes, position: int) -> int:
    return struct.unpack_from(">h", donnees, position)[0]


def _u32(donnees: bytes, position: int) -> int:
    return struct.unpack_from(">I", donnees, position)[0]


class TTF:
    """Une police TrueType lue en mémoire (tables `head`, `hhea`, `maxp`, `hmtx`, `cmap`, `loca`, `glyf`, `name`)."""

    def __init__(self, octets: bytes) -> None:
        self._d = octets
        try:
            self._lire()
        except (struct.error, IndexError, KeyError):
            raise PoliceErreur(REJ_FICHIER, "fichier TrueType illisible ou tronqué") from None
        self._cache_contours: dict[int, tuple[Contour, ...]] = {}

    def _lire(self) -> None:
        d = self._d
        if len(d) < 12 or d[:4] not in (b"\x00\x01\x00\x00", b"true"):
            raise PoliceErreur(REJ_FICHIER, "seules les polices TrueType (glyf) sont prises en charge")
        n = _u16(d, 4)
        if not 1 <= n <= 64:
            raise PoliceErreur(REJ_FICHIER, "nombre de tables invalide")
        self._tables: dict[bytes, tuple[int, int]] = {}
        for i in range(n):
            tag, _crc, decalage, longueur = struct.unpack_from(">4sIII", d, 12 + 16 * i)
            if decalage + longueur > len(d):
                raise PoliceErreur(REJ_FICHIER, "table hors du fichier")
            self._tables[tag] = (decalage, longueur)
        for requis in (b"head", b"hhea", b"maxp", b"hmtx", b"cmap", b"loca", b"glyf"):
            if requis not in self._tables:
                raise PoliceErreur(REJ_FICHIER, f"table {requis.decode()} absente")
        t = self._tables
        tete = t[b"head"][0]
        self.unites_par_em = _u16(d, tete + 18)
        if not 16 <= self.unites_par_em <= 16384:
            raise PoliceErreur(REJ_FICHIER, "unitsPerEm hors bornes")
        self._loca_long = _i16(d, tete + 50) == 1
        hhea = t[b"hhea"][0]
        self.ascendante = _i16(d, hhea + 4)
        self.descendante = _i16(d, hhea + 6)
        self._nb_hmetrics = _u16(d, hhea + 34)
        self.nb_glyphes = _u16(d, t[b"maxp"][0] + 4)
        if self._nb_hmetrics < 1 or self._nb_hmetrics > self.nb_glyphes:
            raise PoliceErreur(REJ_FICHIER, "hmtx incohérent")
        self._cmap = self._lire_cmap()
        self.licence_fichier = self._nom(13) or ""
        self.famille_fichier = self._nom(1) or ""

    # -- noms ----------------------------------------------------------------------------------------
    def _nom(self, identifiant: int) -> str | None:
        if b"name" not in self._tables:
            return None
        base, longueur = self._tables[b"name"]
        d = self._d
        nombre, stockage = _u16(d, base + 2), _u16(d, base + 4)
        meilleur = None
        for i in range(nombre):
            plateforme, encodage, _langue, nom_id, taille, decalage = struct.unpack_from(">6H", d, base + 6 + 12 * i)
            if nom_id != identifiant or base + stockage + decalage + taille > base + longueur:
                continue
            brut = d[base + stockage + decalage : base + stockage + decalage + taille]
            if plateforme in (0, 3):
                return brut.decode("utf-16-be", "replace")
            if plateforme == 1 and meilleur is None:
                meilleur = brut.decode("latin-1")
        return meilleur

    # -- cmap ----------------------------------------------------------------------------------------
    def _lire_cmap(self) -> dict[int, int]:
        d = self._d
        base, longueur = self._tables[b"cmap"]
        nombre = _u16(d, base + 2)
        choix: tuple[int, int] | None = None
        for i in range(nombre):
            plateforme, encodage, decalage = struct.unpack_from(">HHI", d, base + 4 + 8 * i)
            if (plateforme, encodage) in ((3, 10), (0, 4), (0, 6)):
                choix = (3, base + decalage)
                break
            if (plateforme, encodage) in ((3, 1), (0, 3), (0, 0), (0, 1), (0, 2)) and choix is None:
                choix = (1, base + decalage)
        if choix is None:
            raise PoliceErreur(REJ_FICHIER, "aucune table cmap Unicode")
        position = choix[1]
        if position + 4 > base + longueur:
            raise PoliceErreur(REJ_FICHIER, "cmap hors table")
        format_ = _u16(d, position)
        if format_ == 4:
            return self._cmap4(position)
        if format_ == 12:
            return self._cmap12(position)
        raise PoliceErreur(REJ_FICHIER, f"cmap de format {format_} non pris en charge")

    def _cmap4(self, p: int) -> dict[int, int]:
        d = self._d
        segments = _u16(d, p + 6) // 2
        fins = p + 14
        debuts = fins + 2 * segments + 2
        deltas = debuts + 2 * segments
        decalages = deltas + 2 * segments
        table: dict[int, int] = {}
        for i in range(segments):
            fin, debut = _u16(d, fins + 2 * i), _u16(d, debuts + 2 * i)
            delta, decalage = _i16(d, deltas + 2 * i), _u16(d, decalages + 2 * i)
            if debut > fin or fin == 0xFFFF and debut == 0xFFFF:
                continue
            for code in range(debut, fin + 1):
                if decalage == 0:
                    glyphe = (code + delta) & 0xFFFF
                else:
                    position = decalages + 2 * i + decalage + 2 * (code - debut)
                    glyphe = _u16(d, position)
                    if glyphe:
                        glyphe = (glyphe + delta) & 0xFFFF
                if glyphe:
                    table[code] = glyphe
        return table

    def _cmap12(self, p: int) -> dict[int, int]:
        d = self._d
        groupes = _u32(d, p + 12)
        if groupes > 100_000:
            raise PoliceErreur(REJ_FICHIER, "cmap trop grand")
        table: dict[int, int] = {}
        for i in range(groupes):
            debut, fin, glyphe = struct.unpack_from(">III", d, p + 16 + 12 * i)
            if fin < debut or fin - debut > 0x10FFFF:
                continue
            for code in range(debut, fin + 1):
                table[code] = glyphe + (code - debut)
        return table

    # -- métriques -----------------------------------------------------------------------------------
    def caracteres(self) -> tuple[str, ...]:
        """Les caractères que la police sait dessiner (triés par point de code)."""
        return tuple(chr(c) for c in sorted(self._cmap) if c <= 0x10FFFF)

    def couvre(self, texte: str) -> set[str]:
        """Les caractères de `texte` qui n'ont pas de glyphe (l'espace sans glyphe est toléré par `avance`)."""
        return {c for c in texte if ord(c) not in self._cmap}

    def avance_glyphe(self, glyphe: int) -> int:
        d = self._d
        base = self._tables[b"hmtx"][0]
        indice = min(glyphe, self._nb_hmetrics - 1)
        return _u16(d, base + 4 * indice)

    def avance(self, caractere: str) -> int:
        glyphe = self._cmap.get(ord(caractere))
        if glyphe is None:
            raise PoliceErreur(REJ_GLYPHE, f"aucun glyphe pour U+{ord(caractere):04X}")
        return self.avance_glyphe(glyphe)

    def largeur(self, texte: str, taille_px: float) -> float:
        """Largeur exacte du texte (somme des avances, sans crénage) en pixels."""
        return sum(self.avance(c) for c in texte) * taille_px / self.unites_par_em

    # -- contours ------------------------------------------------------------------------------------
    def contours(self, caractere: str) -> tuple[Contour, ...]:
        glyphe = self._cmap.get(ord(caractere))
        if glyphe is None:
            raise PoliceErreur(REJ_GLYPHE, f"aucun glyphe pour U+{ord(caractere):04X}")
        return self._contours_glyphe(glyphe, 0)

    def _decalage_glyphe(self, glyphe: int) -> tuple[int, int]:
        d = self._d
        base = self._tables[b"loca"][0]
        if self._loca_long:
            debut, fin = _u32(d, base + 4 * glyphe), _u32(d, base + 4 * (glyphe + 1))
        else:
            debut, fin = 2 * _u16(d, base + 2 * glyphe), 2 * _u16(d, base + 2 * (glyphe + 1))
        return debut, fin

    def _contours_glyphe(self, glyphe: int, profondeur: int) -> tuple[Contour, ...]:
        if glyphe in self._cache_contours:
            return self._cache_contours[glyphe]
        if profondeur > PROFONDEUR_COMPOSITE_MAX or glyphe >= self.nb_glyphes:
            raise PoliceErreur(REJ_FICHIER, "glyphe composite trop profond ou hors bornes")
        try:
            resultat = self._decoder_glyphe(glyphe, profondeur)
        except (struct.error, IndexError):
            raise PoliceErreur(REJ_FICHIER, "glyphe illisible") from None
        self._cache_contours[glyphe] = resultat
        return resultat

    def _decoder_glyphe(self, glyphe: int, profondeur: int) -> tuple[Contour, ...]:
        d = self._d
        debut, fin = self._decalage_glyphe(glyphe)
        base_glyf = self._tables[b"glyf"][0]
        if fin == debut:
            return ()
        if fin < debut or base_glyf + fin > self._tables[b"glyf"][0] + self._tables[b"glyf"][1]:
            raise PoliceErreur(REJ_FICHIER, "glyphe hors table glyf")
        p = base_glyf + debut
        nb_contours = _i16(d, p)
        p += 10
        if nb_contours >= 0:
            return self._glyphe_simple(p, nb_contours)
        return self._glyphe_composite(p, profondeur)

    def _glyphe_simple(self, p: int, nb_contours: int) -> tuple[Contour, ...]:
        d = self._d
        fins = [_u16(d, p + 2 * i) for i in range(nb_contours)]
        p += 2 * nb_contours
        p += 2 + _u16(d, p)
        nb_points = fins[-1] + 1 if fins else 0
        if nb_points > POINTS_GLYPHE_MAX:
            raise PoliceErreur(REJ_FICHIER, "glyphe trop complexe")
        drapeaux: list[int] = []
        while len(drapeaux) < nb_points:
            drapeau = d[p]
            p += 1
            drapeaux.append(drapeau)
            if drapeau & 8:
                repetitions = d[p]
                p += 1
                drapeaux.extend([drapeau] * repetitions)
        drapeaux = drapeaux[:nb_points]
        xs: list[int] = []
        courant = 0
        for drapeau in drapeaux:
            if drapeau & 2:
                delta = d[p]
                p += 1
                courant += delta if drapeau & 16 else -delta
            elif not drapeau & 16:
                courant += _i16(d, p)
                p += 2
            xs.append(courant)
        ys: list[int] = []
        courant = 0
        for drapeau in drapeaux:
            if drapeau & 4:
                delta = d[p]
                p += 1
                courant += delta if drapeau & 32 else -delta
            elif not drapeau & 32:
                courant += _i16(d, p)
                p += 2
            ys.append(courant)
        contours = []
        debut = 0
        for fin in fins:
            points = [(float(xs[i]), float(ys[i]), bool(drapeaux[i] & 1)) for i in range(debut, fin + 1)]
            contour = _contour(points)
            if contour is not None:
                contours.append(contour)
            debut = fin + 1
        return tuple(contours)

    def _glyphe_composite(self, p: int, profondeur: int) -> tuple[Contour, ...]:
        d = self._d
        contours: list[Contour] = []
        while True:
            drapeaux, glyphe = _u16(d, p), _u16(d, p + 2)
            p += 4
            if drapeaux & 1:
                dx, dy = _i16(d, p), _i16(d, p + 2)
                p += 4
            else:
                dx, dy = struct.unpack_from(">bb", d, p)
                p += 2
            if not drapeaux & 2:
                raise PoliceErreur(REJ_FICHIER, "glyphe composite par points d'ancrage non pris en charge")
            a = dd = 1.0
            b = c = 0.0
            if drapeaux & 8:
                a = dd = _i16(d, p) / 16384
                p += 2
            elif drapeaux & 0x40:
                a, dd = _i16(d, p) / 16384, _i16(d, p + 2) / 16384
                p += 4
            elif drapeaux & 0x80:
                a, b, c, dd = (_i16(d, p + 2 * i) / 16384 for i in range(4))
                p += 8
            for contour in self._contours_glyphe(glyphe, profondeur + 1):
                contours.append(_transformer(contour, a, b, c, dd, float(dx), float(dy)))
            if not drapeaux & 0x20:
                break
        return tuple(contours)


def _milieu(p: tuple[float, float, bool], q: tuple[float, float, bool]) -> tuple[float, float, bool]:
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, True)


def _contour(points: list[tuple[float, float, bool]]) -> Contour | None:
    """Points TrueType (courbe quadratique, points hors courbe implicites) -> depart + segments."""
    if len(points) < 2:
        return None
    if not points[0][2]:
        points = [points[-1], *points[:-1]] if points[-1][2] else [_milieu(points[-1], points[0]), *points]
    depart = (points[0][0], points[0][1])
    segments: list[tuple] = []
    controle: tuple[float, float, bool] | None = None
    for point in [*points[1:], points[0]]:
        if point[2]:
            if controle is None:
                segments.append(("L", point[0], point[1]))
            else:
                segments.append(("Q", controle[0], controle[1], point[0], point[1]))
                controle = None
        elif controle is None:
            controle = point
        else:
            milieu = _milieu(controle, point)
            segments.append(("Q", controle[0], controle[1], milieu[0], milieu[1]))
            controle = point
    if controle is not None:
        segments.append(("Q", controle[0], controle[1], depart[0], depart[1]))
    return depart, tuple(segments)


def _transformer(contour: Contour, a: float, b: float, c: float, d: float, dx: float, dy: float) -> Contour:
    def pt(x: float, y: float) -> tuple[float, float]:
        return a * x + c * y + dx, b * x + d * y + dy

    depart, segments = contour
    sortie = []
    for segment in segments:
        if segment[0] == "L":
            sortie.append(("L", *pt(segment[1], segment[2])))
        else:
            sortie.append(("Q", *pt(segment[1], segment[2]), *pt(segment[3], segment[4])))
    return pt(*depart), tuple(sortie)


@dataclasses.dataclass(frozen=True)
class Police:
    id: str
    famille: str
    style: str
    licence: str
    source_url: str
    sha256: str
    fictif: bool
    ttf: TTF = dataclasses.field(repr=False, compare=False)

    def resume(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "famille": self.famille,
            "style": self.style,
            "licence": self.licence,
            "source_url": self.source_url,
            "sha256": self.sha256,
            "fictif": self.fictif,
        }


class RegistrePolices:
    def __init__(self, polices: Sequence[Police]) -> None:
        self._polices = {p.id: p for p in polices}

    def obtenir(self, identifiant: str) -> Police:
        police = self._polices.get(identifiant)
        if police is None:
            raise PoliceErreur(REJ_ABSENTE, f"police {identifiant!r} absente du registre")
        return police

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._polices))

    def __len__(self) -> int:
        return len(self._polices)

    def resumes(self) -> list[dict[str, Any]]:
        return [self._polices[i].resume() for i in self.ids()]


def _lire_fichier_borne(chemin: Path) -> bytes:
    try:
        meta = chemin.lstat()
    except OSError:
        raise PoliceErreur(REJ_FICHIER, "fichier de police introuvable") from None
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= TAILLE_FICHIER_MAX:
        raise PoliceErreur(REJ_FICHIER, "fichier de police : fichier ordinaire non vide de 8 Mio au plus exigé")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descripteur = os.open(chemin, flags)
        with os.fdopen(descripteur, "rb") as flux:
            donnees = flux.read(TAILLE_FICHIER_MAX + 1)
    except OSError:
        raise PoliceErreur(REJ_FICHIER, "fichier de police illisible") from None
    if len(donnees) > TAILLE_FICHIER_MAX:
        raise PoliceErreur(REJ_FICHIER, "fichier de police trop volumineux")
    return donnees


def valider_entree(entree: Any, dossier: Path, *, production: bool) -> Police:
    champs = {"id", "famille", "style", "fichier", "sha256", "licence", "source_url", "fictif"}
    if not isinstance(entree, Mapping) or set(entree) != champs:
        raise PoliceErreur(REJ_MANIFESTE, f"entrée de police : champs exacts {sorted(champs)}")
    identifiant, fichier = entree["id"], entree["fichier"]
    if not isinstance(identifiant, str) or not _ID.fullmatch(identifiant):
        raise PoliceErreur(REJ_MANIFESTE, "identifiant de police invalide")
    if not isinstance(fichier, str) or not _FICHIER.fullmatch(fichier):
        raise PoliceErreur(REJ_MANIFESTE, f"{identifiant} : nom de fichier simple « nom.ttf » exigé (aucun chemin)")
    for cle in ("famille", "style", "source_url"):
        if not isinstance(entree[cle], str) or not entree[cle].strip() or len(entree[cle]) > 300:
            raise PoliceErreur(REJ_MANIFESTE, f"{identifiant} : {cle} invalide")
    if not entree["source_url"].startswith("https://"):
        raise PoliceErreur(REJ_MANIFESTE, f"{identifiant} : source_url https:// exigée (traçabilité de la licence)")
    if type(entree["fictif"]) is not bool:
        raise PoliceErreur(REJ_MANIFESTE, f"{identifiant} : fictif est un booléen")
    if entree["licence"] != LICENCE_PERMISE:
        raise PoliceErreur(
            REJ_LICENCE,
            f"{identifiant} : licence {entree['licence']!r} refusée, seule {LICENCE_PERMISE} est permise (R5 §9 n°14)",
        )
    if not isinstance(entree["sha256"], str) or not _SHA256.fullmatch(entree["sha256"]):
        raise PoliceErreur(
            REJ_EMPREINTE, f"{identifiant} : empreinte SHA-256 en minuscules exigée (police non épinglée)"
        )
    if entree["fictif"] and production:
        raise PoliceErreur(REJ_FICTIVE, f"{identifiant} : police de test refusée en production")
    donnees = _lire_fichier_borne(dossier / fichier)
    if hashlib.sha256(donnees).hexdigest() != entree["sha256"]:
        raise PoliceErreur(REJ_EMPREINTE, f"{identifiant} : le fichier ne correspond pas à l'empreinte épinglée")
    ttf = TTF(donnees)
    if not _NOTICE_OFL.search(ttf.licence_fichier):
        raise PoliceErreur(
            REJ_LICENCE,
            f"{identifiant} : la table name du fichier ne mentionne pas la SIL Open Font License",
        )
    return Police(
        identifiant,
        entree["famille"],
        entree["style"],
        entree["licence"],
        entree["source_url"],
        entree["sha256"],
        entree["fictif"],
        ttf,
    )


def charger_dossier(dossier: Path, *, production: bool = True) -> RegistrePolices:
    """Lit `polices.json` et chaque police : tout ou rien (une police invalide refuse tout le dossier)."""
    chemin = dossier / NOM_MANIFESTE
    try:
        manifeste = json.loads(_lire_fichier_borne(chemin).decode("utf-8"))
    except PoliceErreur:
        raise PoliceErreur(
            REJ_ABSENTE, "aucun manifeste de polices (polices.json) : épingler les polices OFL"
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PoliceErreur(REJ_MANIFESTE, "manifeste de polices illisible") from None
    if (
        not isinstance(manifeste, Mapping)
        or manifeste.get("schema") != SCHEMA_MANIFESTE
        or set(manifeste)
        != {
            "schema",
            "polices",
        }
    ):
        raise PoliceErreur(REJ_MANIFESTE, f"schéma {SCHEMA_MANIFESTE!r} et clé « polices » exigés")
    entrees = manifeste["polices"]
    if not isinstance(entrees, list) or not 1 <= len(entrees) <= POLICES_MAX:
        raise PoliceErreur(REJ_MANIFESTE, f"1 à {POLICES_MAX} polices attendues")
    polices = [valider_entree(e, dossier, production=production) for e in entrees]
    if len({p.id for p in polices}) != len(polices):
        raise PoliceErreur(REJ_MANIFESTE, "identifiant de police en double")
    return RegistrePolices(polices)
