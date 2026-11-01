"""Lecture de la SORTIE : le port `LecteurOCR`, deux doubles déterministes et l'adaptateur du profil OCR existant.

Le contrôle qualité ne croit jamais le plan : il relit l'artefact livré et compare ce qu'il y lit au brief. Trois
lecteurs existent ; AUCUN n'est un OCR réel qui a tourné ici :

  - `LecteurGabaritsPixels` (double, PNG) : lit les PIXELS. Il connaît, pour chaque ligne posée, la zone, la police,
    la taille et la couleur (des indices du plan, jamais le texte), isole l'encre, découpe par colonnes et reconnaît
    chaque glyphe par appariement avec le glyphe rendu par la même police. Un chiffre faux dans le PNG est lu faux.
    Limite : il ne lit que les zones indiquées (un texte halluciné ailleurs dans le fond ne le concerne pas) et ne
    sait lire que les polices du registre ; un vrai OCR (Tesseract, PaddleOCR) est requis pour une pièce réelle.
  - `LecteurTexteVectoriel` (double, SVG et PDF) : extrait le texte vivant d'un SVG ou le texte de remplacement
    (`/ActualText`) d'un PDF. Ce n'est pas une lecture des pixels : il atteste ce que l'artefact DÉCLARE.
  - `LecteurOCRProfil` (adaptateur, PDF et PNG emballé en PDF) : appelle `opsys.ocr_runtime.extraire_candidat`
    (Tesseract 5.5 + pdfium dans bubblewrap, bundle validé par `ocr_profil`). Il ne tourne pas sur la machine de
    construction (aucun bundle, isolation absente) ; il est testé avec un `extraire_candidat` simulé seulement.

Chaque lecteur déclare sa `nature` (`reel` ou `double`) ; le contrôle la consigne dans le rapport et l'approbation
d'un visuel NON fictif exige une lecture par un lecteur réel (`actifs.py`).

Module sans entrée-sortie propre.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from . import plan as p
from . import png, rendus
from .polices import Police, RegistrePolices
from .toile import Toile

NATURE_REEL = "reel"
NATURE_DOUBLE = "double"
REJ_OCR = "REJ-STUDIO-OCR-INDISPONIBLE"
SEUIL_BRUIT = 0.1  # sous ce taux de couverture, un pixel est du bruit de fond (fond généré non uni)
CARACTERE_ILLISIBLE = "�"


@dataclasses.dataclass(frozen=True)
class Jeton:
    """Un mot lu. `ref` (`"<id>#<n>"`) est posé par les lecteurs qui connaissent la zone ; sinon `None` et le
    contrôle attribue le jeton par sa position."""

    texte: str
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    ref: str | None = None
    confiance: float | None = None


@dataclasses.dataclass(frozen=True)
class LectureOCR:
    lecteur: str
    version: str
    nature: str
    format: str
    entree_sha256: str
    jetons: tuple[Jeton, ...]

    def vers_resume(self) -> dict[str, Any]:
        return {
            "lecteur": self.lecteur,
            "version": self.version,
            "nature": self.nature,
            "format": self.format,
            "entree_sha256": self.entree_sha256,
            "jetons": len(self.jetons),
        }


class LecteurOCR(Protocol):
    nom: str
    version: str
    nature: str
    formats: tuple[str, ...]

    def lire(self, octets: bytes, format: str, plan: p.Plan) -> LectureOCR:
        """Relit `octets` (artefact livré). `plan` ne fournit que des INDICES de zone (jamais le texte attendu)."""


def _sha(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


# -- double : texte vectoriel ---------------------------------------------------------------------------------
class LecteurTexteVectoriel:
    nom = "texte-vectoriel-double"
    version = "1"
    nature = NATURE_DOUBLE
    formats = ("svg", "pdf")

    def lire(self, octets: bytes, format: str, plan: p.Plan) -> LectureOCR:
        if format == "svg":
            lu = rendus.lire_svg(octets)
            jetons = tuple(
                Jeton(ligne, ref=f"{identifiant}#{n}")
                for identifiant, lignes in sorted(lu["textes"].items())
                for n, ligne in enumerate(lignes)
            )
        elif format == "pdf":
            lu = rendus.lire_pdf(octets)
            ordre = [(ligne.id, ligne.n) for ligne in plan.lignes]  # indices d'ordre seulement, pas de texte
            if len(ordre) != len(lu["textes"]):
                jetons = tuple(Jeton(t) for t in lu["textes"])
            else:
                jetons = tuple(Jeton(t, ref=f"{i}#{n}") for (i, n), t in zip(ordre, lu["textes"], strict=True))
        else:
            raise ValueError(f"format non lu : {format}")
        return LectureOCR(self.nom, self.version, self.nature, format, _sha(octets), jetons)


def separer(
    image: png.ImageRVB, zone: tuple[int, int, int, int], couleur: p.Couleur
) -> tuple[list[list[bool]], list[p.Couleur]]:
    """Sépare l'encre du fond dans `zone` : un pixel est de l'encre s'il est plus proche de la couleur du texte que de
    la
    couleur dominante de la zone. Rend la matrice d'encre et les pixels de fond (pour mesurer le contraste réel)."""
    x0, y0, x1, y1 = zone
    largeur = x1 - x0
    pixels = image.pixels
    compte: dict[tuple[int, int, int], int] = {}
    for y in range(y0, y1):
        base = 3 * (y * image.largeur + x0)
        for x in range(largeur):
            c = (pixels[base + 3 * x] >> 3, pixels[base + 3 * x + 1] >> 3, pixels[base + 3 * x + 2] >> 3)
            compte[c] = compte.get(c, 0) + 1
    fond_q = max(compte, key=lambda c: (compte[c], c))
    fond = (fond_q[0] * 8 + 4, fond_q[1] * 8 + 4, fond_q[2] * 8 + 4)
    sortie = []
    pixels_fond: list[p.Couleur] = []
    for y in range(y0, y1):
        base = 3 * (y * image.largeur + x0)
        ligne = []
        for x in range(largeur):
            r, g, b = pixels[base + 3 * x], pixels[base + 3 * x + 1], pixels[base + 3 * x + 2]
            d_texte = abs(r - couleur[0]) + abs(g - couleur[1]) + abs(b - couleur[2])
            d_fond = abs(r - fond[0]) + abs(g - fond[1]) + abs(b - fond[2])
            est_encre = d_texte < d_fond
            ligne.append(est_encre)
            if not est_encre:
                pixels_fond.append((r, g, b))
        sortie.append(ligne)
    return sortie, pixels_fond


# -- double : appariement de glyphes sur les pixels -------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class _Masque:
    caractere: str
    decalage: int  # colonne de la 1re encre, relative à l'origine du glyphe (la plume)
    largeur: int
    couverture: Mapping[tuple[int, int], float]  # (x rel. à la 1re colonne d'encre, y rel. à la base) -> [0, 1]
    masse: float


# Masques des glyphes candidats, partagés entre lecteurs : clé (empreinte de la police, taille, caractère). Une police
# est identifiée par son empreinte SHA-256 épinglée ; le cache est borné.
_MASQUES: dict[tuple[str, float, str], _Masque | None] = {}
_MASQUES_MAX = 60_000


def _masque(police: Police, taille: float, caractere: str) -> _Masque | None:
    cle = (police.sha256, round(taille, 3), caractere)
    if cle in _MASQUES:
        return _MASQUES[cle]
    if len(_MASQUES) > _MASQUES_MAX:
        _MASQUES.clear()
    marge = math.ceil(taille)  # place pour les accents et jambages
    toile = Toile(marge * 4, marge * 4, (255, 255, 255))
    base_y = marge * 2
    toile.texte(police, caractere, marge, base_y, taille, (0, 0, 0))
    couverture = {
        (i % toile.largeur, i // toile.largeur): 1 - toile.pixels[3 * i] / 255
        for i in range(toile.largeur * toile.hauteur)
        if toile.pixels[3 * i] < 250
    }
    encre = [c for c, v in couverture.items() if v > 0.5]
    if not encre:
        _MASQUES[cle] = None
        return None
    x0 = min(x for x, _ in encre)
    utile = {(x - x0, y - base_y): v for (x, y), v in couverture.items() if v >= SEUIL_BRUIT}
    masque = _Masque(caractere, x0 - marge, max(x for x, _ in encre) - x0 + 1, utile, sum(utile.values()))
    _MASQUES[cle] = masque
    return masque


class LecteurGabaritsPixels:
    nom = "gabarits-pixels-double"
    version = "1"
    nature = NATURE_DOUBLE
    formats = ("png",)
    SEUIL_APPARIEMENT = 0.80

    def __init__(self, polices: RegistrePolices) -> None:
        self._polices = polices

    def _alphabet(self, police: Police) -> list[str]:
        return [c for c in police.ttf.caracteres() if 0x21 <= ord(c) < 0x250 and police.ttf.contours(c)]

    def _candidats(self, police: Police, taille: float, alphabet: Sequence[str]) -> dict[int, list[_Masque]]:
        par_largeur: dict[int, list[_Masque]] = {}
        for caractere in alphabet:
            masque = _masque(police, taille, caractere)
            if masque is not None:
                par_largeur.setdefault(masque.largeur, []).append(masque)
        return par_largeur

    # lecture --------------------------------------------------------------------------------------------------
    def lire(self, octets: bytes, format: str, plan: p.Plan) -> LectureOCR:
        if format != "png":
            raise ValueError(f"format non lu : {format}")
        image = png.decoder(octets)
        jetons: list[Jeton] = []
        for ligne in plan.lignes:
            police = self._polices.obtenir(ligne.police_id)
            jetons += self._lire_ligne(image, ligne, police)
        return LectureOCR(self.nom, self.version, self.nature, "png", _sha(octets), tuple(jetons))

    def _lire_ligne(self, image: png.ImageRVB, ligne: p.Ligne, police: Police) -> list[Jeton]:
        taille = ligne.taille_px
        asc = police.ttf.ascendante / police.ttf.unites_par_em
        desc = -police.ttf.descendante / police.ttf.unites_par_em
        x0 = max(0, int(ligne.boite[0]) - 3)
        x1 = min(image.largeur, int(ligne.boite[2]) + 4)
        base = round(ligne.baseline)
        y0 = max(0, base - int(asc * ligne.taille_px) - 3)
        y1 = min(image.hauteur, base + int(desc * ligne.taille_px) + 4)
        if x1 <= x0 or y1 <= y0:
            return [Jeton(CARACTERE_ILLISIBLE, ref=f"{ligne.id}#{ligne.n}")]
        encre, pixels_fond = separer(image, (x0, y0, x1, y1), ligne.couleur)
        fond_moyen = tuple(sum(c[i] for c in pixels_fond) / max(1, len(pixels_fond)) for i in range(3))
        grille = self._grille(image, (x0, y0, x1, y1), ligne.couleur, fond_moyen)
        colonnes = [any(encre[y][x - x0] for y in range(y1 - y0)) for x in range(x0, x1)]
        segments: list[tuple[int, int]] = []
        debut = None
        for i, a in enumerate(colonnes + [False]):
            if a and debut is None:
                debut = i
            elif not a and debut is not None:
                segments.append((debut, i))
                debut = None
        cellule = ligne.taille_px / 10
        espace = (
            police.ttf.avance(" ") * ligne.taille_px / police.ttf.unites_par_em
            if " " in police.ttf.caracteres()
            else 4 * cellule
        )
        mots: list[list[str]] = []
        boites: list[list[int]] = []
        fin_plume: float | None = None
        precedent_fin = None
        candidats = self._candidats(police, taille, self._alphabet(police))
        i = 0
        while i < len(segments):
            # Un glyphe peut se découper en plusieurs plages d'encre (rangées sans recouvrement de colonnes) : on essaie
            # de fusionner 1 à 4 plages proches (écart ≤ 1,5 cellule) et on garde la fusion qui s'apparie le mieux.
            meilleur = None
            for k in range(1, min(4, len(segments) - i) + 1):
                if k > 1 and (segments[i + k - 1][0] - segments[i + k - 2][1]) > 1.5 * cellule:
                    break
                debut, fin = segments[i][0], segments[i + k - 1][1]
                lu, masque, score = self._glyphe(grille, debut, fin, base - y0, candidats)
                if meilleur is None or score >= meilleur[0]:
                    meilleur = (score, k, debut, fin, lu, masque)
            _score, k, debut, fin, lu, masque = meilleur
            i += k
            if masque is not None:
                origine = x0 + debut - masque.decalage
            if not mots:
                nouveau_mot = True
            elif masque is not None and fin_plume is not None:
                nouveau_mot = (origine - fin_plume) > 0.5 * espace
            else:
                nouveau_mot = (debut - precedent_fin) > 3.5 * cellule
            if nouveau_mot:
                mots.append([])
                boites.append([x0 + debut, y0, x0 + fin, y1])
            mots[-1].append(lu)
            boites[-1][2] = x0 + fin
            precedent_fin = fin
            fin_plume = (
                origine + police.ttf.avance(lu) * ligne.taille_px / police.ttf.unites_par_em
                if masque is not None
                else None
            )
        texte_mots = ["".join(m) for m in mots]
        if not texte_mots:
            return []
        ref = f"{ligne.id}#{ligne.n}"
        # Un jeton par mot : le contrôle les réassemble par `ref` dans l'ordre.
        return [
            Jeton(m, float(b[0]), float(b[1]), float(b[2]), float(b[3]), ref=ref)
            for m, b in zip(texte_mots, boites, strict=True)
        ]

    @staticmethod
    def _grille(
        image: png.ImageRVB, zone: tuple[int, int, int, int], couleur: p.Couleur, fond: Sequence[float]
    ) -> list[list[float]]:
        """Couverture observée de chaque pixel de la zone : projection du pixel sur l'axe fond -> couleur du texte."""
        x0, y0, x1, y1 = zone
        axe = [couleur[i] - fond[i] for i in range(3)]
        norme = sum(a * a for a in axe) or 1.0
        grille = []
        for y in range(y0, y1):
            q = 3 * (y * image.largeur + x0)
            ligne = []
            for x in range(x1 - x0):
                r, g, b = image.pixels[q + 3 * x], image.pixels[q + 3 * x + 1], image.pixels[q + 3 * x + 2]
                c = ((r - fond[0]) * axe[0] + (g - fond[1]) * axe[1] + (b - fond[2]) * axe[2]) / norme
                ligne.append(min(1.0, c) if c >= SEUIL_BRUIT else 0.0)
            grille.append(ligne)
        return grille

    def _glyphe(
        self, grille: list[list[float]], debut: int, fin: int, base_rel: int, candidats: Mapping[int, list[_Masque]]
    ) -> tuple[str, _Masque | None, float]:
        """Apparie la plage de colonnes `[debut, fin)` aux glyphes de même largeur (à 1 px près) par recouvrement
        pondéré (Jaccard) des couvertures ; la ligne de base du plan est connue."""
        largeur = fin - debut
        a_tester = [m for w in (largeur - 1, largeur, largeur + 1) for m in candidats.get(w, ())]
        if not a_tester:
            return CARACTERE_ILLISIBLE, None, 0.0
        observe: dict[tuple[int, int], float] = {}
        for y, rangee in enumerate(grille):
            # +1 px de chaque côté : la frange d'anticrénelage (couverture proche de 0,5) fait partie du glyphe.
            for x in range(max(0, debut - 1), min(len(rangee), fin + 1)):
                c = rangee[x]
                if c:
                    observe[(x - debut, y - base_rel)] = c
        masse = sum(observe.values())
        meilleur, score_max, retenu = CARACTERE_ILLISIBLE, 0.0, None
        for masque in a_tester:
            if abs(masse - masque.masse) > 0.5 * max(masse, masque.masse):
                continue
            inter = union = 0.0
            for cle in observe.keys() | masque.couverture.keys():
                a, b = observe.get(cle, 0.0), masque.couverture.get(cle, 0.0)
                inter += a if a < b else b
                union += a if a > b else b
            score = inter / union if union else 0.0
            if score > score_max or (score == score_max and score > 0 and masque.caractere < meilleur):
                meilleur, score_max, retenu = masque.caractere, score, masque
        if score_max >= self.SEUIL_APPARIEMENT:
            return meilleur, retenu, score_max
        return CARACTERE_ILLISIBLE, None, score_max


# -- adaptateur du profil OCR existant ---------------------------------------------------------------------------
class LecteurOCRProfil:
    """Adaptateur de `opsys.ocr_runtime.extraire_candidat` (PDF seulement : un PNG est emballé dans un PDF d'une page).

    `extraire` est injectable : par défaut `opsys.ocr_runtime.extraire_candidat` (Tesseract + pdfium isolés, bundle
    local). Aucun appel réseau. NON exécuté sur la machine de construction."""

    nom = "ocr-profil-tesseract"
    version = "tesseract-5.5.0"
    nature = NATURE_REEL
    formats = ("pdf", "png")

    def __init__(
        self,
        bundle: Any,
        extraire: Callable[..., dict[str, Any]] | None = None,
        emballer_png: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._bundle = bundle
        self._extraire = extraire
        self._emballer = emballer_png or emballer_png_dans_pdf

    def lire(self, octets: bytes, format: str, plan: p.Plan) -> LectureOCR:
        from opsys import ocr_runtime  # import différé : le profil exige l'extra d'ingestion et le bundle

        source = self._emballer(octets) if format == "png" else octets
        extraire = self._extraire or ocr_runtime.extraire_candidat
        try:
            candidat = extraire(source, lot_id="studio-controle", revision_source=1, bundle=self._bundle)
        except ocr_runtime.OCRRuntimeErreur as exc:
            raise LectureImpossible(f"{REJ_OCR} : {exc.code}") from None
        page = candidat["page"]
        echelle_x = plan.largeur_px / page["largeur_px"] if page["largeur_px"] else 1.0
        echelle_y = plan.hauteur_px / page["hauteur_px"] if page["hauteur_px"] else 1.0
        jetons = tuple(
            Jeton(
                t["texte"],
                t["x0"] * echelle_x,
                t["y0"] * echelle_y,
                t["x1"] * echelle_x,
                t["y1"] * echelle_y,
                None,
                t["confiance_brute"],
            )
            for t in page["tokens"]
        )
        return LectureOCR(self.nom, self.version, self.nature, format, _sha(octets), jetons)


class LectureImpossible(RuntimeError):
    """Le lecteur n'a pas pu lire (profil absent, isolation indisponible) : le contrôle échoue, rien n'est supposé."""


def emballer_png_dans_pdf(octets: bytes) -> bytes:
    """Un PDF d'une page qui n'affiche que ce PNG (pour la lecture par le profil OCR, qui ne lit que des PDF)."""
    image = png.decoder(octets)
    import zlib

    brut = zlib.compress(image.pixels, 9)
    contenu = f"q {image.largeur} 0 0 {image.hauteur} 0 0 cm /Im Do Q".encode("latin-1")
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {image.largeur} {image.hauteur}] /Contents 4 0 R "
        f"/Resources << /XObject << /Im 5 0 R >> >> >>".encode("latin-1"),
        f"<< /Length {len(contenu)} >>\nstream\n".encode("latin-1") + contenu + b"\nendstream",
        f"<< /Type /XObject /Subtype /Image /Width {image.largeur} /Height {image.hauteur} /ColorSpace /DeviceRGB "
        f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(brut)} >>\nstream\n".encode("latin-1")
        + brut
        + b"\nendstream",
    ]
    sortie = bytearray(b"%PDF-1.4\n")
    positions = []
    for numero, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode("latin-1") + corps + b"\nendobj\n"
    debut = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n".encode("latin-1") + b"0000000000 65535 f \n"
    for position in positions:
        sortie += f"{position:010d} 00000 n \n".encode("latin-1")
    sortie += (f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{debut}\n%%EOF\n").encode("latin-1")
    return bytes(sortie)


def lecteurs_par_defaut(polices: RegistrePolices) -> Mapping[str, LecteurOCR]:
    """Les doubles, un par format : ce qui tourne ici. Un déploiement avec le profil OCR remplace le lecteur PNG/PDF."""
    vectoriel = LecteurTexteVectoriel()
    return {"png": LecteurGabaritsPixels(polices), "svg": vectoriel, "pdf": vectoriel}
