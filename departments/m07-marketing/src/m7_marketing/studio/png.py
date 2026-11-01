"""PNG minimal, en Python pur (zlib, struct) : encodage déterministe, décodage borné, métadonnées texte.

Le studio n'a ni Pillow ni numpy (M7 : aucune dépendance lourde). Ce module ne couvre que ce dont il a besoin :
écrire un PNG RVB 8 bits avec des métadonnées (marquage « généré par IA », provenance) et relire un fond fourni par
un générateur (RVB, RVBA ou gris 8 bits, non entrelacé). Tout le reste (palette, 16 bits, entrelacement) est refusé
avec un code typé : jamais une image mal lue en silence.

Reproductibilité : `encoder` est une fonction pure. Deux versions de zlib peuvent compresser différemment le même
flux ; les comparaisons de rendus se font donc sur les PIXELS décodés (`decoder`), pas sur les octets compressés.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import struct
import zlib
from collections.abc import Mapping

SIGNATURE = b"\x89PNG\r\n\x1a\n"
DIMENSION_MAX = 12_000
PIXELS_MAX = 60_000_000
CHARGE_DECOMPRESSEE_MAX = PIXELS_MAX * 4 + 12_000
REJ_PNG = "REJ-STUDIO-PNG-INVALIDE"
REJ_PNG_NON_PRIS_EN_CHARGE = "REJ-STUDIO-PNG-NON-PRIS-EN-CHARGE"
_CLE_TEXTE_MAX = 79


class PngInvalide(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


@dataclasses.dataclass(frozen=True)
class ImageRVB:
    """Image RVB 8 bits, rangée par rangée (`pixels` : `3 * largeur * hauteur` octets)."""

    largeur: int
    hauteur: int
    pixels: bytes

    def __post_init__(self) -> None:
        if not (1 <= self.largeur <= DIMENSION_MAX and 1 <= self.hauteur <= DIMENSION_MAX):
            raise PngInvalide(REJ_PNG, f"dimensions hors bornes : {self.largeur}x{self.hauteur}")
        if self.largeur * self.hauteur > PIXELS_MAX:
            raise PngInvalide(REJ_PNG, "trop de pixels")
        if len(self.pixels) != 3 * self.largeur * self.hauteur:
            raise PngInvalide(REJ_PNG, "taille du tampon de pixels incohérente")


def _bloc(type_bloc: bytes, donnees: bytes) -> bytes:
    return (
        struct.pack(">I", len(donnees))
        + type_bloc
        + donnees
        + struct.pack(">I", zlib.crc32(type_bloc + donnees) & 0xFFFFFFFF)
    )


def encoder(image: ImageRVB, metadonnees: Mapping[str, str] | None = None) -> bytes:
    """PNG RVB 8 bits, sans filtre, métadonnées `tEXt` triées par clé (latin-1)."""
    entete = struct.pack(">IIBBBBB", image.largeur, image.hauteur, 8, 2, 0, 0, 0)
    ligne = 3 * image.largeur
    brut = bytearray()
    for y in range(image.hauteur):
        brut.append(0)
        brut += image.pixels[y * ligne : (y + 1) * ligne]
    sortie = [SIGNATURE, _bloc(b"IHDR", entete)]
    for cle in sorted(metadonnees or {}):
        valeur = (metadonnees or {})[cle]
        if not cle or len(cle) > _CLE_TEXTE_MAX or not cle.isascii() or not cle.isprintable():
            raise PngInvalide(REJ_PNG, "clé de métadonnée invalide")
        try:
            donnees = cle.encode("latin-1") + b"\x00" + valeur.encode("latin-1")
        except UnicodeEncodeError:
            raise PngInvalide(REJ_PNG, "métadonnée non encodable en latin-1 (ASCII exigé)") from None
        sortie.append(_bloc(b"tEXt", donnees))
    sortie.append(_bloc(b"IDAT", zlib.compress(bytes(brut), 9)))
    sortie.append(_bloc(b"IEND", b""))
    return b"".join(sortie)


def _blocs(octets: bytes):
    if not isinstance(octets, (bytes, bytearray)) or not octets.startswith(SIGNATURE):
        raise PngInvalide(REJ_PNG, "signature PNG absente")
    position = len(SIGNATURE)
    vu_iend = False
    while position < len(octets):
        if position + 12 > len(octets):
            raise PngInvalide(REJ_PNG, "bloc tronqué")
        (taille,) = struct.unpack(">I", octets[position : position + 4])
        type_bloc = bytes(octets[position + 4 : position + 8])
        fin = position + 8 + taille
        if taille > CHARGE_DECOMPRESSEE_MAX or fin + 4 > len(octets):
            raise PngInvalide(REJ_PNG, "bloc hors bornes")
        donnees = bytes(octets[position + 8 : fin])
        (crc,) = struct.unpack(">I", octets[fin : fin + 4])
        if crc != zlib.crc32(type_bloc + donnees) & 0xFFFFFFFF:
            raise PngInvalide(REJ_PNG, f"CRC invalide ({type_bloc.decode('latin-1')})")
        yield type_bloc, donnees
        position = fin + 4
        if type_bloc == b"IEND":
            vu_iend = True
            break
    if not vu_iend:
        raise PngInvalide(REJ_PNG, "IEND absent")


def dimensions(octets: bytes) -> tuple[int, int]:
    for type_bloc, donnees in _blocs(octets):
        if type_bloc == b"IHDR" and len(donnees) == 13:
            largeur, hauteur = struct.unpack(">II", donnees[:8])
            return largeur, hauteur
        break
    raise PngInvalide(REJ_PNG, "IHDR absent")


def metadonnees(octets: bytes) -> dict[str, str]:
    """Les blocs `tEXt` (latin-1). Un bloc `iTXt`/`zTXt` est ignoré : le studio n'écrit que `tEXt`."""
    trouvees: dict[str, str] = {}
    for type_bloc, donnees in _blocs(octets):
        if type_bloc == b"tEXt" and b"\x00" in donnees:
            cle, _, valeur = donnees.partition(b"\x00")
            trouvees[cle.decode("latin-1")] = valeur.decode("latin-1")
    return trouvees


def decoder(octets: bytes) -> ImageRVB:
    entete: tuple[int, int, int, int, int, int, int] | None = None
    idat = bytearray()
    for type_bloc, donnees in _blocs(octets):
        if type_bloc == b"IHDR":
            if len(donnees) != 13:
                raise PngInvalide(REJ_PNG, "IHDR invalide")
            entete = struct.unpack(">IIBBBBB", donnees)
        elif type_bloc == b"IDAT":
            idat += donnees
            if len(idat) > CHARGE_DECOMPRESSEE_MAX:
                raise PngInvalide(REJ_PNG, "données trop volumineuses")
        elif type_bloc == b"PLTE":
            raise PngInvalide(REJ_PNG_NON_PRIS_EN_CHARGE, "PNG à palette : convertir en RVB 8 bits")
    if entete is None or not idat:
        raise PngInvalide(REJ_PNG, "IHDR ou IDAT absent")
    largeur, hauteur, profondeur, couleur, compression, filtre, entrelace = entete
    if (profondeur, compression, filtre) != (8, 0, 0) or couleur not in (0, 2, 4, 6):
        raise PngInvalide(REJ_PNG_NON_PRIS_EN_CHARGE, "seuls les PNG 8 bits gris, RVB, gris+alpha, RVBA sont lus")
    if entrelace != 0:
        raise PngInvalide(REJ_PNG_NON_PRIS_EN_CHARGE, "PNG entrelacé non pris en charge")
    if not (1 <= largeur <= DIMENSION_MAX and 1 <= hauteur <= DIMENSION_MAX) or largeur * hauteur > PIXELS_MAX:
        raise PngInvalide(REJ_PNG, "dimensions hors bornes")
    canaux = {0: 1, 2: 3, 4: 2, 6: 4}[couleur]
    ligne = canaux * largeur
    attendu = (ligne + 1) * hauteur
    decompresseur = zlib.decompressobj()
    try:
        brut = decompresseur.decompress(bytes(idat), attendu + 1)
    except zlib.error:
        raise PngInvalide(REJ_PNG, "flux zlib invalide") from None
    if len(brut) != attendu or decompresseur.unconsumed_tail:
        raise PngInvalide(REJ_PNG, "taille décompressée incohérente")
    precedente = bytearray(ligne)
    sortie = bytearray()
    for y in range(hauteur):
        type_filtre = brut[y * (ligne + 1)]
        courante = bytearray(brut[y * (ligne + 1) + 1 : (y + 1) * (ligne + 1)])
        _defiltrer(type_filtre, courante, precedente, canaux)
        precedente = courante
        sortie += _vers_rvb(courante, canaux, couleur)
    return ImageRVB(largeur, hauteur, bytes(sortie))


def _defiltrer(type_filtre: int, ligne: bytearray, precedente: bytearray, canaux: int) -> None:
    if type_filtre == 0:
        return
    taille = len(ligne)
    if type_filtre == 1:
        for i in range(canaux, taille):
            ligne[i] = (ligne[i] + ligne[i - canaux]) & 0xFF
    elif type_filtre == 2:
        for i in range(taille):
            ligne[i] = (ligne[i] + precedente[i]) & 0xFF
    elif type_filtre == 3:
        for i in range(taille):
            gauche = ligne[i - canaux] if i >= canaux else 0
            ligne[i] = (ligne[i] + ((gauche + precedente[i]) >> 1)) & 0xFF
    elif type_filtre == 4:
        for i in range(taille):
            a = ligne[i - canaux] if i >= canaux else 0
            b = precedente[i]
            c = precedente[i - canaux] if i >= canaux else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            predicteur = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            ligne[i] = (ligne[i] + predicteur) & 0xFF
    else:
        raise PngInvalide(REJ_PNG, f"filtre {type_filtre} inconnu")


def _vers_rvb(ligne: bytearray, canaux: int, couleur: int) -> bytes:
    if couleur == 2:
        return bytes(ligne)
    sortie = bytearray()
    if couleur == 0:
        for v in ligne:
            sortie += bytes((v, v, v))
    elif couleur == 4:
        for i in range(0, len(ligne), 2):
            sortie += _sur_blanc(ligne[i], ligne[i], ligne[i], ligne[i + 1])
    else:
        for i in range(0, len(ligne), 4):
            sortie += _sur_blanc(ligne[i], ligne[i + 1], ligne[i + 2], ligne[i + 3])
    return bytes(sortie)


def _sur_blanc(r: int, g: int, b: int, alpha: int) -> bytes:
    """Alpha composité sur blanc, arrondi entier : un fond avec transparence n'a pas de rendu ambigu."""
    return bytes((255 - ((255 - c) * alpha + 127) // 255) for c in (r, g, b))
