"""Police TrueType de TEST, fabriquée par le code (aucun fichier binaire dans le dépôt) : chaque pixel d'une matrice
5×7 est un carré de 100 unités. Elle sert au rendu, à la lecture par gabarits et au registre de polices. Elle porte
la mention OFL dans sa table `name` pour traverser le contrôle du registre, mais le manifeste la déclare `fictif` :
le mode production la refuse. Ce n'est PAS une police OFL réelle."""

from __future__ import annotations

import struct

UNITES = 1000
CELLULE = 100
LIGNES_ACCENT, LIGNES_CORPS, LIGNES_DESC = 2, 7, 2


def _g(*lignes: str) -> list[str]:
    return list(lignes)


# Corps des glyphes : 7 lignes (rangées 2..8 de la boîte), plus éventuellement des lignes de jambage.
MAJUSCULES = {
    "A": _g(".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": _g("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": _g(".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": _g("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": _g("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": _g("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": _g(".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": _g("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": _g("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": _g("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": _g("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": _g("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": _g("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": _g("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": _g(".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": _g("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": _g(".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": _g("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": _g(".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": _g("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": _g("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": _g("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": _g("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": _g("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": _g("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": _g("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
}
CHIFFRES = {
    "0": _g(".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": _g("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": _g(".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": _g("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": _g("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": _g("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": _g("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": _g("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": _g(".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": _g(".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
}
_V = "....."
MINUSCULES = {
    "a": _g(_V, _V, ".###.", "....#", ".####", "#...#", ".####"),
    "b": _g("#....", "#....", "####.", "#...#", "#...#", "#...#", "####."),
    "c": _g(_V, _V, ".###.", "#...#", "#....", "#...#", ".###."),
    "d": _g("....#", "....#", ".####", "#...#", "#...#", "#...#", ".####"),
    "e": _g(_V, _V, ".###.", "#...#", "#####", "#....", ".####"),
    "f": _g("..##.", ".#..#", ".#...", "###..", ".#...", ".#...", ".#..."),
    "g": _g(_V, _V, ".####", "#...#", "#...#", ".####", "....#") + ["....#", ".###."],
    "h": _g("#....", "#....", "####.", "#...#", "#...#", "#...#", "#...#"),
    "i": _g("..#..", _V, ".##..", "..#..", "..#..", "..#..", ".###."),
    "j": _g("...#.", _V, "..##.", "...#.", "...#.", "...#.", "...#.") + ["#..#.", ".##.."],
    "k": _g("#....", "#....", "#..#.", "#.#..", "##...", "#.#..", "#..#."),
    "l": _g(".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "m": _g(_V, _V, "##.#.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"),
    "n": _g(_V, _V, "####.", "#...#", "#...#", "#...#", "#...#"),
    "o": _g(_V, _V, ".###.", "#...#", "#...#", "#...#", ".###."),
    "p": _g(_V, _V, "####.", "#...#", "#...#", "####.", "#....") + ["#....", "#...."],
    "q": _g(_V, _V, ".####", "#...#", "#...#", ".####", "....#") + ["....#", "....#"],
    "r": _g(_V, _V, "#.##.", "##..#", "#....", "#....", "#...."),
    "s": _g(_V, _V, ".####", "#....", ".###.", "....#", "####."),
    "t": _g(".#...", ".#...", "###..", ".#...", ".#...", ".#..#", "..##."),
    "u": _g(_V, _V, "#...#", "#...#", "#...#", "#..##", ".##.#"),
    "v": _g(_V, _V, "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "w": _g(_V, _V, "#...#", "#...#", "#.#.#", "#.#.#", ".#.#."),
    "x": _g(_V, _V, "#...#", ".#.#.", "..#..", ".#.#.", "#...#"),
    "y": _g(_V, _V, "#...#", "#...#", "#...#", ".####", "....#") + ["....#", ".###."],
    "z": _g(_V, _V, "#####", "...#.", "..#..", ".#...", "#####"),
}
PONCTUATION = {
    ".": _g(_V, _V, _V, _V, _V, ".##..", ".##.."),
    ",": _g(_V, _V, _V, _V, _V, "..#..", "..#..") + [".#...", _V],
    ":": _g(_V, ".##..", ".##..", _V, ".##..", ".##..", _V),
    ";": _g(_V, ".##..", ".##..", _V, ".##..", "..#..", "..#..") + [".#...", _V],
    "-": _g(_V, _V, _V, "#####", _V, _V, _V),
    "'": _g("..#..", "..#..", _V, _V, _V, _V, _V),
    '"': _g(".#.#.", ".#.#.", _V, _V, _V, _V, _V),
    "(": _g("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": _g(".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "/": _g("....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."),
    "+": _g(_V, "..#..", "..#..", "#####", "..#..", "..#..", _V),
    "&": _g(".##..", "#..#.", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"),
    "@": _g(".###.", "#...#", "#.###", "#.#.#", "#.###", "#....", ".####"),
    "$": _g("..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."),
    "%": _g("##..#", "##..#", "...#.", "..#..", ".#...", "#..##", "#..##"),
    "!": _g("..#..", "..#..", "..#..", "..#..", "..#..", _V, "..#.."),
    "?": _g(".###.", "#...#", "....#", "...#.", "..#..", _V, "..#.."),
    "«": _g(_V, "..#.#", ".#.#.", "#.#..", ".#.#.", "..#.#", _V),
    "»": _g(_V, "#.#..", ".#.#.", "..#.#", ".#.#.", "#.#..", _V),
    "#": _g(".#.#.", "#####", ".#.#.", ".#.#.", ".#.#.", "#####", ".#.#."),
    "_": _g(_V, _V, _V, _V, _V, _V, _V) + ["#####", _V],
    "=": _g(_V, _V, "#####", _V, "#####", _V, _V),
    "<": _g("...#.", "..#..", ".#...", "#....", ".#...", "..#..", "...#."),
    ">": _g(".#...", "..#..", "...#.", "....#", "...#.", "..#..", ".#..."),
    "*": _g(_V, ".#.#.", "..#..", "#####", "..#..", ".#.#.", _V),
}
ACCENTS = {
    "aigu": ("...#.", "..#.."),
    "grave": (".#...", "..#.."),
    "circonflexe": ("..#..", ".#.#."),
    "trema": (".#.#.", _V),
}
# (caractère, base, accent) : l'accent des majuscules est posé dans les 2 lignes au-dessus ; celui des minuscules à
# x-hauteur remplace les 2 premières lignes (vides) du corps.
ACCENTUES = [
    ("é", "e", "aigu"),
    ("è", "e", "grave"),
    ("ê", "e", "circonflexe"),
    ("ë", "e", "trema"),
    ("à", "a", "grave"),
    ("â", "a", "circonflexe"),
    ("ô", "o", "circonflexe"),
    ("û", "u", "circonflexe"),
    ("ù", "u", "grave"),
    ("ü", "u", "trema"),
    ("î", "i", "circonflexe"),
    ("ï", "i", "trema"),
    ("É", "E", "aigu"),
    ("È", "E", "grave"),
    ("À", "A", "grave"),
    ("Ê", "E", "circonflexe"),
    ("Ç", "C", None),
    ("ç", "c", None),
]
OEUF = ["", ".##.##.", "#..#..#", "#..####", "#..#...", ".##.###"]

ESPACES = {" ": 4, " ": 4, " ": 2}  # avance en cellules


def _boite(corps: list[str], accent: tuple[str, str] | None, majuscule: bool) -> list[str]:
    """11 rangées : 2 d'accent, 7 de corps, 2 de jambage."""
    largeur = len(corps[0])
    vide = "." * largeur
    haut = [vide, vide]
    lignes = list(corps[:LIGNES_CORPS])
    desc = list(corps[LIGNES_CORPS : LIGNES_CORPS + LIGNES_DESC])
    desc += [vide] * (LIGNES_DESC - len(desc))
    if accent is not None:
        a = [accent[0].ljust(largeur, "."), accent[1].ljust(largeur, ".")]
        if majuscule:
            haut = a
        else:
            lignes[0], lignes[1] = a[0], a[1]
    return haut + lignes + desc


def definitions() -> dict[str, tuple[list[str], int]]:
    """caractère -> (rangées de 11 lignes, avance en unités de police)."""
    sortie: dict[str, tuple[list[str], int]] = {}
    base: dict[str, list[str]] = {**MAJUSCULES, **CHIFFRES, **MINUSCULES, **PONCTUATION}
    for caractere, corps in base.items():
        largeur = len(corps[0])
        sortie[caractere] = (_boite(corps, None, caractere.isupper()), (largeur + 1) * CELLULE)
    for caractere, lettre, accent in ACCENTUES:
        corps = list(base[lettre])
        if caractere in "çÇ":
            corps = corps[:LIGNES_CORPS] + ["..#..", ".##.."]
            sortie[caractere] = (_boite(corps, None, caractere.isupper()), 6 * CELLULE)
            continue
        if lettre == "i":
            corps = ["....." if i < 2 else r for i, r in enumerate(corps)]
        sortie[caractere] = (_boite(corps, ACCENTS[accent], caractere.isupper()), 6 * CELLULE)
    oeuf = ["......."] * 2 + OEUF[1:]
    sortie["œ"] = (_boite(oeuf, None, False), 8 * CELLULE)
    for espace, cellules in ESPACES.items():
        sortie[espace] = (["....."] * (LIGNES_ACCENT + LIGNES_CORPS + LIGNES_DESC), cellules * CELLULE)
    return sortie


def _contours(rangees: list[str]) -> list[list[tuple[int, int]]]:
    """Un carré par pixel allumé, sens horaire (TrueType : contour extérieur horaire)."""
    carres = []
    hauteur = len(rangees)
    for j, rangee in enumerate(rangees):
        y = (hauteur - 1 - j) * CELLULE - LIGNES_DESC * CELLULE  # y = 0 : ligne de base (bas des majuscules)
        for i, c in enumerate(rangee):
            if c == "#":
                x = i * CELLULE
                carres.append([(x, y), (x, y + CELLULE), (x + CELLULE, y + CELLULE), (x + CELLULE, y)])
    return carres


def _glyphe(contours: list[list[tuple[int, int]]]) -> bytes:
    if not contours:
        return b""
    points = [p for c in contours for p in c]
    fins, total = [], -1
    for c in contours:
        total += len(c)
        fins.append(total)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    entete = struct.pack(">hhhhh", len(contours), min(xs), min(ys), max(xs), max(ys))
    corps = struct.pack(f">{len(fins)}H", *fins) + struct.pack(">H", 0) + bytes([1]) * len(points)
    precedent = 0
    for x in xs:
        corps += struct.pack(">h", x - precedent)
        precedent = x
    precedent = 0
    for y in ys:
        corps += struct.pack(">h", y - precedent)
        precedent = y
    donnees = entete + corps
    return donnees + b"\x00" * (-len(donnees) % 4)


def _table_cmap(codes: list[int], format12: bool = False) -> bytes:
    """Chaque caractère est son propre segment ; le glyphe n°(i+1) correspond au i-ème code trié."""
    codes = sorted(codes)
    if format12:
        groupes = b"".join(struct.pack(">III", c, c, i + 1) for i, c in enumerate(codes))
        sous = struct.pack(">HHIII", 12, 0, 16 + len(groupes), 0, len(codes)) + groupes
        return struct.pack(">HH", 0, 1) + struct.pack(">HHI", 3, 10, 12) + sous
    segments = [(c, c, ((i + 1) - c) & 0xFFFF) for i, c in enumerate(codes)] + [(0xFFFF, 0xFFFF, 1)]
    nb = len(segments)
    corps = (
        b"".join(struct.pack(">H", s[1]) for s in segments)
        + b"\x00\x00"
        + b"".join(struct.pack(">H", s[0]) for s in segments)
        + b"".join(struct.pack(">H", s[2]) for s in segments)
        + b"\x00\x00" * nb
    )
    sous = struct.pack(">HHHHHHH", 4, 14 + len(corps), 0, nb * 2, 0, 0, 0) + corps
    return struct.pack(">HH", 0, 1) + struct.pack(">HHI", 3, 1, 12) + sous


CERCLE = 0x25CB
DEUX_CERCLES = 0x25CE
CERCLE_REDUIT = 0x25CF
AIRE_CERCLE_UNITES2 = 300_000  # 4 × (triangle 45 000 + segment parabolique 30 000)


def _glyphe_cercle() -> bytes:
    """Un contour à courbes quadratiques : 4 points sur la courbe, 4 points de contrôle (hors courbe)."""
    points = [
        (800, 500, 1),
        (800, 800, 0),
        (500, 800, 1),
        (200, 800, 0),
        (200, 500, 1),
        (200, 200, 0),
        (500, 200, 1),
        (800, 200, 0),
    ]
    entete = struct.pack(">hhhhh", 1, 200, 200, 800, 800)
    corps = struct.pack(">HH", len(points) - 1, 0) + bytes(p[2] for p in points)
    precedent = 0
    for x, _y, _f in points:
        corps += struct.pack(">h", x - precedent)
        precedent = x
    precedent = 0
    for _x, y, _f in points:
        corps += struct.pack(">h", y - precedent)
        precedent = y
    donnees = entete + corps
    return donnees + b"\x00" * (-len(donnees) % 4)


def _glyphe_composite(composants: list[tuple[int, int, int, float | None]]) -> bytes:
    """Composants (glyphe, dx, dy, échelle) : drapeaux mots + valeurs XY, échelle F2Dot14 optionnelle."""
    corps = struct.pack(">hhhhh", -1, 0, 0, 2000, 1000)
    for rang, (glyphe, dx, dy, echelle) in enumerate(composants):
        drapeaux = 0x0001 | 0x0002 | (0x0020 if rang < len(composants) - 1 else 0) | (0x0008 if echelle else 0)
        corps += struct.pack(">HHhh", drapeaux, glyphe, dx, dy)
        if echelle:
            corps += struct.pack(">h", round(echelle * 16384))
    return corps + b"\x00" * (-len(corps) % 4)


def _nom(chaines: dict[int, str]) -> bytes:
    enregistrements, stockage = b"", b""
    for identifiant in sorted(chaines):
        brut = chaines[identifiant].encode("utf-16-be")
        enregistrements += struct.pack(">6H", 3, 1, 0x409, identifiant, len(brut), len(stockage))
        stockage += brut
    entete = struct.pack(">HHH", 0, len(chaines), 6 + 12 * len(chaines))
    return entete + enregistrements + stockage


def ttf_octets(
    famille: str = "OPSYS Test Pixel", notice_ofl: bool = True, loca_courte: bool = False, cmap12: bool = False
) -> bytes:
    defs = definitions()
    ordre = sorted(defs, key=ord)
    glyphes = [b""]  # .notdef vide (aucun caractère n'y mène : un caractère absent doit être refusé)
    avances = [600]
    for caractere in ordre:
        rangees, avance = defs[caractere]
        glyphes.append(_glyphe(_contours(rangees)))
        avances.append(avance)
    codes = [ord(c) for c in ordre]
    # Glyphes à courbes et composites, ajoutés après les carrés : codes plus grands, donc cmap trié inchangé.
    rang_cercle = len(glyphes)
    glyphes += [
        _glyphe_cercle(),
        _glyphe_composite([(rang_cercle, 0, 0, None), (rang_cercle, 700, 0, None)]),
        _glyphe_composite([(rang_cercle, 0, 0, 0.5)]),
    ]
    avances += [1000, 1500, 1000]
    codes += [CERCLE, DEUX_CERCLES, CERCLE_REDUIT]
    n = len(glyphes)
    glyf, loca, position = b"", [], 0
    for g in glyphes:
        loca.append(position)
        glyf += g
        position += len(g)
    loca.append(position)
    hmtx = b"".join(struct.pack(">Hh", a, 0) for a in avances)
    hauteur_boite = (LIGNES_ACCENT + LIGNES_CORPS + LIGNES_DESC) * CELLULE
    tete = struct.pack(
        ">IIIIHHqqhhhhHHhhh",
        0x00010000,
        0x00010000,
        0,
        0x5F0F3CF5,
        0,
        UNITES,
        0,
        0,
        0,
        0,
        1000,
        hauteur_boite,
        0,
        8,
        2,
        0 if loca_courte else 1,
        0,
    )
    hhea = struct.pack(">IhhhHhhhhhhhhhhhH", 0x00010000, 900, -200, 0, 1000, 0, 0, 1000, 1, 0, 0, 0, 0, 0, 0, 0, n)
    maxp = struct.pack(">IH", 0x00010000, n) + b"\x00" * 26
    mention = (
        "This Font Software is licensed under the SIL Open Font License, Version 1.1."
        if notice_ofl
        else "Aucune licence déclarée."
    )
    nom = _nom(
        {
            1: famille,
            2: "Regular",
            4: famille,
            6: famille.replace(" ", "-"),
            13: mention,
            14: "https://openfontlicense.org",
        }
    )
    cmap = _table_cmap(codes, cmap12)
    loca_octets = (
        b"".join(struct.pack(">H", o // 2) for o in loca)
        if loca_courte
        else b"".join(struct.pack(">I", o) for o in loca)
    )
    tables = {
        b"cmap": cmap,
        b"glyf": glyf,
        b"head": tete,
        b"hhea": hhea,
        b"hmtx": hmtx,
        b"loca": loca_octets,
        b"maxp": maxp,
        b"name": nom,
    }
    nb_tables = len(tables)
    decalage = 12 + 16 * nb_tables
    repertoire, corps = b"", b""
    for tag in sorted(tables):
        donnees = tables[tag]
        repertoire += struct.pack(">4sIII", tag, 0, decalage + len(corps), len(donnees))
        corps += donnees + b"\x00" * (-len(donnees) % 4)
    entete = struct.pack(">IHHHH", 0x00010000, nb_tables, 0, 0, 0)
    return entete + repertoire + corps
