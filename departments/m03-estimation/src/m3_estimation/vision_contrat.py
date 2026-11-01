"""Contrat du pipeline de vision (M3.3 et M3.5) : entrées photo avec provenance, sorties = CANDIDATS de mesures.

ÉTAT HONNÊTE. Aucun modèle de vision n'est installé ni qualifié ici : ni poids, ni GPU, ni réseau. Ce module fixe le
CONTRAT (ce qui entre, ce qui sort, ce qui est refusé) et le port ``DetecteurVision``, que seul un double déterministe
remplit aujourd'hui (``vision_doubles.py``). Un futur détecteur (Grounding DINO, SAM 2 ou équivalent, voir
``opsys.fournisseurs.catalogue``) se branche derrière ce port sans changer une ligne de la gouvernance.

CE QUE LE CONTRAT IMPOSE.

* Entrée : une photo décrite par son empreinte SHA-256, ses dimensions et sa PROVENANCE (origine, saisie,
  consentement). Aucun octet d'image ne traverse ce module. Une photo réelle exige une politique « photos non
  contractuelles » VALIDÉE (``politique_photos``) et une référence de consentement ; à ce jour la politique est une
  proposition : seules les photos de jeu synthétique fictif passent.
* Le détecteur ne rend que de la GÉOMÉTRIE : une boîte, un masque facultatif, un code d'objet demandé et une
  confiance. Il ne rend jamais un nombre de mesure. Les valeurs (surface, longueur) sont CALCULÉES ici, en Decimal,
  depuis la géométrie et l'échelle déclarée de la photo : « le code calcule, le LLM orchestre ». Sans échelle, la
  mesure n'existe pas (pixels seulement) : une photo sans échelle donne une plage ou une hypothèse, jamais une
  dimension.
* Sortie : des candidats (``statut`` ``candidate_non_validee``) avec incertitude MÉCANIQUE (quantification des pixels
  et échelle déclarée, jamais calibrée sur le terrain), masque, version du modèle et reçu de calcul. Toute sortie du
  détecteur est une donnée non fiable : un code d'objet hors de la demande, une boîte hors image, un masque hors
  image, une confiance hors [0, 1] ou une boîte qui ne contient pas le masque est REJETÉ avec son motif, jamais
  corrigé.

Ce qu'un candidat n'est PAS : une mesure. La règle de gouvernance est dans ``vision_gouvernance.py``.

Module pur : aucune horloge, aucun aléa, aucun réseau, aucun import ``opsys``.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Protocol

from . import journal_site, verdicts

__all__ = [
    "Detection",
    "DetecteurVision",
    "MasqueRLE",
    "ModeleVision",
    "PhotoEntree",
    "SCHEMA_SORTIE",
    "VERSION_PIPELINE",
    "empreinte_candidat",
    "executer",
    "formater",
    "iou",
    "valider_photo",
]

SCHEMA_SORTIE = "m3.vision.sortie/v1"
VERSION_PIPELINE = "m3-vision-pipeline/1"
_ORIGINES = frozenset({"jeu_synthetique", "client", "employe", "estimateur"})
_SOURCES_ECHELLE = frozenset({"reference_certifiee", "plan", "declaree"})
_CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,119}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^\d{1,12}(\.\d{1,12})?$")
_DIMENSION_MAX = 20000
_PIXELS_MAX = 200_000_000
_SEGMENTS_MAX = 200_000
_DETECTIONS_MAX = 50
_OBJETS_MAX = 10
_QUANTUM = Decimal("0.0001")


def formater(valeur: Decimal) -> str:
    """Texte décimal canonique à 4 décimales (arrondi demi-pair), jamais un flottant."""
    return format(valeur.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _decimal(texte: Any) -> Decimal | None:
    if not isinstance(texte, str) or not _DECIMAL.fullmatch(texte):
        return None
    try:
        return Decimal(texte)
    except InvalidOperation:  # pragma: no cover - la forme est déjà contrôlée
        return None


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail)


# --------------------------------------------------------------------------------------------- entrées
@dataclasses.dataclass(frozen=True)
class Echelle:
    metres_par_pixel: Decimal
    source: str
    incertitude_relative: Decimal | None


@dataclasses.dataclass(frozen=True)
class Provenance:
    origine: str
    saisie_le: str
    fictif: bool
    consentement_ref: str | None


@dataclasses.dataclass(frozen=True)
class PhotoEntree:
    photo_id: str
    empreinte_sha256: str
    largeur: int
    hauteur: int
    provenance: Provenance
    echelle: Echelle | None


def valider_photo(brut: Any, *, politique_validee: bool) -> tuple[PhotoEntree | None, dict[str, Any] | None]:
    """``(photo, None)`` ou ``(None, verdict)``. Une photo RÉELLE n'entre que si la politique photos est validée ET
    qu'une
    référence de consentement l'accompagne ; une photo de jeu synthétique doit se déclarer fictive."""
    if not isinstance(brut, Mapping):
        return None, _refus("REJ-VISION-PHOTO-INVALIDE", "photo : objet attendu")
    permises = {"photo_id", "empreinte_sha256", "largeur", "hauteur", "provenance", "echelle"}
    if set(brut) - permises or not {"photo_id", "empreinte_sha256", "largeur", "hauteur", "provenance"} <= set(brut):
        return None, _refus("REJ-VISION-PHOTO-INVALIDE", "photo : champs absents ou non admis")
    if not isinstance(brut["photo_id"], str) or not _IDENTIFIANT.fullmatch(brut["photo_id"]):
        return None, _refus("REJ-VISION-PHOTO-INVALIDE", "photo_id : identifiant sans espace attendu")
    if not isinstance(brut["empreinte_sha256"], str) or not _SHA256.fullmatch(brut["empreinte_sha256"]):
        return None, _refus("REJ-VISION-PHOTO-INVALIDE", "empreinte_sha256 : 64 hexadécimaux minuscules attendus")
    largeur, hauteur = brut["largeur"], brut["hauteur"]
    if (
        type(largeur) is not int
        or type(hauteur) is not int
        or not 1 <= largeur <= _DIMENSION_MAX
        or not 1 <= hauteur <= _DIMENSION_MAX
        or largeur * hauteur > _PIXELS_MAX
    ):
        return None, _refus("REJ-VISION-PHOTO-INVALIDE", "dimensions : entiers positifs bornés attendus")
    p = brut["provenance"]
    if (
        not isinstance(p, Mapping)
        or set(p) - {"origine", "saisie_le", "fictif", "consentement_ref"}
        or not {"origine", "saisie_le", "fictif"} <= set(p)
    ):
        return None, _refus("REJ-VISION-PROVENANCE-REFUSEE", "provenance : origine, saisie_le et fictif sont requis")
    if p["origine"] not in _ORIGINES or type(p["fictif"]) is not bool:
        return None, _refus("REJ-VISION-PROVENANCE-REFUSEE", "provenance : origine inconnue ou fictif non booléen")
    try:
        if not isinstance(p["saisie_le"], str) or datetime.fromisoformat(p["saisie_le"]).tzinfo is None:
            raise ValueError
    except ValueError:
        return None, _refus("REJ-VISION-PROVENANCE-REFUSEE", "provenance.saisie_le : horodatage avec fuseau attendu")
    consentement = p.get("consentement_ref")
    if consentement is not None and (not isinstance(consentement, str) or not _IDENTIFIANT.fullmatch(consentement)):
        return None, _refus("REJ-VISION-PROVENANCE-REFUSEE", "consentement_ref : identifiant sans espace attendu")
    if p["origine"] == "jeu_synthetique":
        if p["fictif"] is not True:
            return None, _refus("REJ-VISION-PROVENANCE-REFUSEE", "un jeu synthétique se déclare fictif")
    else:
        if p["fictif"] is True:
            return None, _refus(
                "REJ-VISION-PROVENANCE-REFUSEE", "une photo d'origine réelle ne peut pas se déclarer fictive"
            )
        if politique_validee is not True:
            return None, _refus(
                "REJ-VISION-PROVENANCE-REFUSEE",
                "photo réelle refusée : la politique « photos non contractuelles » n'est pas validée (Loi 25, "
                "fail-closed)",
            )
        if consentement is None:
            return None, _refus("REJ-VISION-PROVENANCE-REFUSEE", "photo réelle sans référence de consentement")
    echelle = None
    if brut.get("echelle") is not None:
        e = brut["echelle"]
        if (
            not isinstance(e, Mapping)
            or set(e) - {"metres_par_pixel", "source", "incertitude_relative"}
            or not {"metres_par_pixel", "source"} <= set(e)
        ):
            return None, _refus("REJ-VISION-PHOTO-INVALIDE", "echelle : metres_par_pixel et source requis")
        mpp = _decimal(e["metres_par_pixel"])
        rel = _decimal(e["incertitude_relative"]) if e.get("incertitude_relative") is not None else None
        if (
            mpp is None
            or mpp <= 0
            or e["source"] not in _SOURCES_ECHELLE
            or (e.get("incertitude_relative") is not None and (rel is None or rel > 1))
        ):
            return None, _refus(
                "REJ-VISION-PHOTO-INVALIDE", "echelle : texte décimal positif et source connue attendus"
            )
        echelle = Echelle(mpp, e["source"], rel)
    return PhotoEntree(
        brut["photo_id"],
        brut["empreinte_sha256"],
        largeur,
        hauteur,
        Provenance(p["origine"], p["saisie_le"], p["fictif"], consentement),
        echelle,
    ), None


# --------------------------------------------------------------------------------------------- géométrie
@dataclasses.dataclass(frozen=True)
class MasqueRLE:
    """Masque binaire en plages (début, longueur) sur l'index linéaire ligne par ligne (``y * largeur + x``)."""

    largeur: int
    hauteur: int
    segments: tuple[tuple[int, int], ...]

    def valide(self) -> str | None:
        """Le motif de refus, ou ``None``."""
        if type(self.largeur) is not int or type(self.hauteur) is not int or self.largeur < 1 or self.hauteur < 1:
            return "dimensions du masque invalides"
        if not isinstance(self.segments, tuple) or not 1 <= len(self.segments) <= _SEGMENTS_MAX:
            return "masque vide ou trop fragmenté"
        fin_precedente = -1
        total = self.largeur * self.hauteur
        for segment in self.segments:
            if (
                not isinstance(segment, tuple)
                or len(segment) != 2
                or type(segment[0]) is not int
                or type(segment[1]) is not int
            ):
                return "segment de masque mal formé"
            debut, longueur = segment
            if longueur < 1 or debut < 0 or debut + longueur > total:
                return "segment de masque hors image"
            if debut <= fin_precedente:
                return "segments de masque non triés ou qui se chevauchent"
            fin_precedente = debut + longueur - 1
        return None

    @property
    def pixels(self) -> int:
        return sum(longueur for _, longueur in self.segments)

    def boite(self) -> tuple[int, int, int, int]:
        """Rectangle englobant ``(x0, y0, x1, y1)``, bornes incluses."""
        premier, dernier = self.segments[0][0], self.segments[-1][0] + self.segments[-1][1] - 1
        y0, y1 = premier // self.largeur, dernier // self.largeur
        if y0 == y1:
            return premier % self.largeur, y0, dernier % self.largeur, y1
        # une plage qui traverse une ligne touche les bords ; sinon on cherche les colonnes extrêmes ligne par ligne
        x0, x1 = self.largeur, -1
        for debut, longueur in self.segments:
            fin = debut + longueur - 1
            ya, yb = debut // self.largeur, fin // self.largeur
            if ya == yb:
                x0, x1 = min(x0, debut % self.largeur), max(x1, fin % self.largeur)
            else:
                x0, x1 = 0, self.largeur - 1
        return x0, y0, x1, y1


def iou(a: MasqueRLE, b: MasqueRLE) -> Decimal:
    """Intersection sur union de deux masques de mêmes dimensions, par fusion de plages (jamais d'expansion en
    pixels)."""
    if (a.largeur, a.hauteur) != (b.largeur, b.hauteur):
        raise ValueError("masques de dimensions différentes")
    i = j = inter = 0
    while i < len(a.segments) and j < len(b.segments):
        da, la = a.segments[i]
        db, lb = b.segments[j]
        debut, fin = max(da, db), min(da + la, db + lb)
        if fin > debut:
            inter += fin - debut
        if da + la <= db + lb:
            i += 1
        else:
            j += 1
    union = a.pixels + b.pixels - inter
    return Decimal(inter) / Decimal(union) if union else Decimal(0)


@dataclasses.dataclass(frozen=True)
class Detection:
    objet: str
    boite: tuple[int, int, int, int]
    masque: MasqueRLE | None
    confiance: Decimal


@dataclasses.dataclass(frozen=True)
class ModeleVision:
    identifiant: str
    version: str
    empreinte_poids: str | None


class DetecteurVision(Protocol):
    """Port d'un détecteur/segmenteur. Rend de la géométrie, jamais une mesure ; ne lit que l'image que l'adaptateur
    lui donne (l'image ne passe pas par ce contrat). Branché derrière ce port : un double (``vision_doubles``) ou,
    plus tard,
    un service local (Grounding DINO + SAM 2). Aucune connexion réseau n'est ouverte par le contrat."""

    @property
    def modele(self) -> ModeleVision: ...

    def detecter(self, photo: PhotoEntree, objets: tuple[str, ...]) -> Sequence[Detection]: ...


# --------------------------------------------------------------------------------------------- pipeline
def _valider_detection(d: Any, photo: PhotoEntree, objets: tuple[str, ...]) -> tuple[Detection | None, str | None]:
    """``(detection, None)`` ou ``(None, motif)`` : la sortie d'un modèle est une donnée non fiable."""
    if not isinstance(d, Detection):
        return None, "SORTIE-TYPE"
    if not isinstance(d.objet, str) or d.objet not in objets:
        return None, "OBJET-NON-DEMANDE"
    if (
        not isinstance(d.confiance, Decimal)
        or not d.confiance.is_finite()
        or not Decimal(0) <= d.confiance <= Decimal(1)
    ):
        return None, "CONFIANCE-HORS-BORNES"
    b = d.boite
    if (
        not isinstance(b, tuple)
        or len(b) != 4
        or any(type(v) is not int for v in b)
        or not (0 <= b[0] <= b[2] < photo.largeur and 0 <= b[1] <= b[3] < photo.hauteur)
    ):
        return None, "BOITE-HORS-IMAGE"
    if d.masque is not None:
        if not isinstance(d.masque, MasqueRLE):
            return None, "MASQUE-TYPE"
        if (d.masque.largeur, d.masque.hauteur) != (photo.largeur, photo.hauteur):
            return None, "MASQUE-DIMENSIONS"
        if d.masque.valide() is not None:
            return None, "MASQUE-INVALIDE"
        x0, y0, x1, y1 = d.masque.boite()
        if not (b[0] <= x0 and b[1] <= y0 and x1 <= b[2] and y1 <= b[3]):
            return None, "MASQUE-HORS-BOITE"
    return d, None


def _candidat(photo: PhotoEntree, modele: ModeleVision, d: Detection) -> dict[str, Any]:
    """Un candidat : la mesure est CALCULÉE ici (Decimal) depuis la géométrie et l'échelle, jamais lue du modèle."""
    largeur_px = d.boite[2] - d.boite[0] + 1
    hauteur_px = d.boite[3] - d.boite[1] + 1
    grandeur = "surface" if d.masque is not None else "longueur"
    pixels = d.masque.pixels if d.masque is not None else None
    hypotheses = [
        "plan frontal supposé, sans correction de perspective ni de distorsion",
        "incertitude mécanique non calibrée sur le terrain",
    ]
    valeur = None
    unite = "m2" if grandeur == "surface" else "m"
    incertitude: dict[str, Any] = {"absolue": None, "calibree": False, "composantes": []}
    if photo.echelle is None:
        unite = "px2" if grandeur == "surface" else "px"
        valeur_px = Decimal(pixels) if grandeur == "surface" else Decimal(max(largeur_px, hauteur_px))
        incertitude["composantes"].append(
            {"nom": "echelle", "absolue": None, "motif": "aucune échelle : pas de mesure"}
        )
        hypotheses.append("photo sans échelle : plage ou hypothèse seulement, aucune dimension")
        pixels_seulement = formater(valeur_px)
    else:
        s = photo.echelle.metres_par_pixel
        if grandeur == "surface":
            valeur = Decimal(pixels) * s * s
            quant = Decimal(largeur_px + hauteur_px) * s * s
            facteur_echelle = 2
        else:
            valeur = Decimal(max(largeur_px, hauteur_px)) * s
            quant = Decimal(2) * s
            facteur_echelle = 1
        incertitude["composantes"].append({"nom": "quantification_pixels", "absolue": formater(quant), "motif": None})
        total = quant
        if photo.echelle.incertitude_relative is None:
            incertitude["composantes"].append(
                {"nom": "echelle", "absolue": None, "motif": "incertitude d'échelle non déclarée"}
            )
        else:
            terme = valeur * photo.echelle.incertitude_relative * facteur_echelle
            incertitude["composantes"].append({"nom": "echelle", "absolue": formater(terme), "motif": None})
            total += terme
        incertitude["absolue"] = formater(total)
        incertitude["complete"] = photo.echelle.incertitude_relative is not None
        pixels_seulement = None
    corps = {
        "photo_id": photo.photo_id,
        "photo_empreinte": photo.empreinte_sha256,
        "objet": d.objet,
        "grandeur": grandeur,
        "unite": unite,
        "valeur": None if valeur is None else formater(valeur),
        "pixels": pixels,
        "valeur_pixels": pixels_seulement,
        "incertitude": incertitude,
        "confiance": formater(d.confiance),
        "boite": list(d.boite),
        "masque": None
        if d.masque is None
        else {
            "largeur": d.masque.largeur,
            "hauteur": d.masque.hauteur,
            "segments": [list(s) for s in d.masque.segments],
        },
        "echelle": None
        if photo.echelle is None
        else {
            "metres_par_pixel": formater(photo.echelle.metres_par_pixel),
            "source": photo.echelle.source,
            "incertitude_relative": None
            if photo.echelle.incertitude_relative is None
            else formater(photo.echelle.incertitude_relative),
        },
        "sans_echelle": photo.echelle is None,
        "modele": {
            "identifiant": modele.identifiant,
            "version": modele.version,
            "empreinte_poids": modele.empreinte_poids,
        },
        "hypotheses": hypotheses,
        "statut": "candidate_non_validee",
    }
    empreinte = journal_site.empreinte_canonique(SCHEMA_SORTIE, corps)
    return {"candidat_id": "cand-" + empreinte[:24], **corps, "empreinte": empreinte}


def empreinte_candidat(candidat: Mapping[str, Any]) -> str:
    """Recalcule l'empreinte d'un candidat (tout sauf ``candidat_id`` et ``empreinte``) : détecte un candidat
    retouché."""
    corps = {k: v for k, v in candidat.items() if k not in ("candidat_id", "empreinte")}
    return journal_site.empreinte_canonique(SCHEMA_SORTIE, corps)


def executer(
    photo_brut: Any,
    detecteur: Any,
    objets: Any,
    *,
    politique_validee: bool,
    modeles_qualifies: frozenset[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le pipeline : photo validée → détecteur (port) → sortie validée → candidats. ``(sortie, None)`` ou ``(None,
    verdict)``.

    ``modeles_qualifies`` : identifiants de modèles que le registre a qualifiés ET activés (vide aujourd'hui). Une
    photo RÉELLE n'est traitée que par l'un d'eux ; une photo de jeu synthétique accepte n'importe quel détecteur
    (double compris),
    parce qu'elle ne prouve rien d'un modèle réel. Un détecteur qui échoue ne laisse AUCUN résultat partiel."""
    photo, verdict = valider_photo(photo_brut, politique_validee=politique_validee)
    if verdict is not None:
        return None, verdict
    assert photo is not None
    if (
        not isinstance(objets, (list, tuple))
        or not 1 <= len(objets) <= _OBJETS_MAX
        or not all(isinstance(o, str) and _CODE.fullmatch(o) for o in objets)
        or len(set(objets)) != len(objets)
    ):
        return None, _refus("REJ-VISION-PHOTO-INVALIDE", "objets : 1 à 10 codes distincts en minuscules attendus")
    objets = tuple(objets)
    modele = getattr(detecteur, "modele", None)
    if (
        not isinstance(modele, ModeleVision)
        or not callable(getattr(detecteur, "detecter", None))
        or not isinstance(modele.identifiant, str)
        or not _IDENTIFIANT.fullmatch(modele.identifiant)
        or not isinstance(modele.version, str)
        or not _IDENTIFIANT.fullmatch(modele.version)
        or (
            modele.empreinte_poids is not None
            and (not isinstance(modele.empreinte_poids, str) or not _SHA256.fullmatch(modele.empreinte_poids))
        )
    ):
        return None, _refus("REJ-VISION-MODELE-INCONNU", "le détecteur ne déclare pas d'identité de modèle valide")
    if photo.provenance.origine != "jeu_synthetique" and modele.identifiant not in modeles_qualifies:
        return None, _refus(
            "REJ-VISION-AUCUN-MODELE-QUALIFIE",
            "aucun modèle de vision n'est qualifié et activé : une photo réelle n'est pas traitée "
            "(contrat prêt, aucun modèle qualifié)",
        )
    try:
        brutes = detecteur.detecter(photo, objets)
    except Exception as exc:  # noqa: BLE001 - le détecteur est hors confiance : seule la classe d'erreur est gardée
        return None, _refus("REJ-VISION-DETECTEUR-INDISPONIBLE", f"le détecteur a échoué ({type(exc).__name__})")
    if not isinstance(brutes, (list, tuple)) or len(brutes) > _DETECTIONS_MAX:
        return None, _refus(
            "REJ-VISION-SORTIE-INVALIDE", "sortie du détecteur : liste de 50 détections au plus attendue"
        )
    candidats, rejetes = [], []
    for indice, d in enumerate(brutes):
        valide, motif = _valider_detection(d, photo, objets)
        if valide is None:
            rejetes.append({"indice": indice, "motif": motif})
        else:
            candidats.append(_candidat(photo, modele, valide))
    ids = [c["candidat_id"] for c in candidats]
    if len(set(ids)) != len(ids):  # deux détections identiques : un seul candidat, le doublon est écarté
        vus: set[str] = set()
        uniques = []
        for c in candidats:
            if c["candidat_id"] in vus:
                rejetes.append({"indice": None, "motif": "DOUBLON"})
            else:
                vus.add(c["candidat_id"])
                uniques.append(c)
        candidats = uniques
    sortie = {
        "schema": SCHEMA_SORTIE,
        "version_pipeline": VERSION_PIPELINE,
        "photo": {
            "photo_id": photo.photo_id,
            "empreinte_sha256": photo.empreinte_sha256,
            "origine": photo.provenance.origine,
            "fictif": photo.provenance.fictif,
            "sans_echelle": photo.echelle is None,
        },
        "modele": {
            "identifiant": modele.identifiant,
            "version": modele.version,
            "empreinte_poids": modele.empreinte_poids,
        },
        "objets_demandes": list(objets),
        "candidats": candidats,
        "rejetes": rejetes,
        "aucune_mesure_retenue": True,
        "mise_en_garde": "Ces candidats ne sont pas des mesures : voir la gouvernance (validation humaine ou mesure de "
        "référence).",
    }
    sortie["recu"] = {
        "moteur": "m3.vision.pipeline",
        "version": VERSION_PIPELINE,
        "empreinte_entrees": journal_site.empreinte_canonique(
            photo.empreinte_sha256, list(objets), modele.identifiant, modele.version
        ),
        "empreinte_sortie": journal_site.empreinte_canonique(sortie["candidats"], sortie["rejetes"]),
    }
    return sortie, None
