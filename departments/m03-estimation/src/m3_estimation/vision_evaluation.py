"""Harnais d'évaluation de la détection/segmentation (M3.3, M3.5) : IoU et erreur de surface sur un jeu SYNTHÉTIQUE
FICTIF.

CE QUE CE HARNAIS PROUVE. Que la mécanique de mesure est correcte et qu'elle distingue un bon détecteur d'un mauvais :
  intersection
sur union par fusion de plages, erreur de surface calculée par le pipeline (Decimal, échelle de la photo), taux de
détection, comparaison à des seuils DÉCLARÉS. Le jeu est généré de façon déterministe (générateur congruentiel à
graine fournie, aucun aléa système) : des rectangles sur une grille, avec leur vérité terrain exacte.

CE QU'IL NE PROUVE PAS. Rien sur un modèle réel : des rectangles nets ne ressemblent pas à des photos de chantier
(ombres, occlusions, perspective, reflets). Un rapport de ce harnais est toujours ``fictif`` et ``non_qualifie`` ; il
ne peut pas faire passer un modèle de « à mesurer » à « qualifié ». La qualification d'un modèle exigera un jeu de
photos réelles consenties, annoté par des personnes, une politique photos validée et des seuils décidés par
l'entreprise : rien de cela n'existe ici.

Module pur : aucune horloge, aucun aléa système, aucun réseau, aucun import ``opsys``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import journal_site, vision_contrat
from .vision_contrat import MasqueRLE, formater

__all__ = ["SCHEMA", "evaluer", "jeu_synthetique_fictif"]

SCHEMA = "m3.vision.evaluation/v1"
_ECHELLES = ("0.0200", "0.0500", "0.1000")
_OBJET = "objet_test"
_MODULE_LCG = 2**31


class _Lcg:
    """Générateur congruentiel linéaire (paramètres classiques), déterministe, sans état global."""

    def __init__(self, graine: int) -> None:
        self._x = graine % _MODULE_LCG

    def entier(self, minimum: int, maximum: int) -> int:
        self._x = (1103515245 * self._x + 12345) % _MODULE_LCG
        return minimum + (self._x >> 8) % (maximum - minimum + 1)


def jeu_synthetique_fictif(graine: int, nombre: int, largeur: int = 64, hauteur: int = 48) -> list[dict[str, Any]]:
    """``nombre`` échantillons FICTIFS déterministes : ``{photo, objet, masque_verite, surface_verite_m2,
    boite_verite}``."""
    if type(graine) is not int or type(nombre) is not int or not 1 <= nombre <= 1000:
        raise ValueError("graine entière et nombre de 1 à 1000 attendus")
    if not 16 <= largeur <= 512 or not 16 <= hauteur <= 512:
        raise ValueError("dimensions de grille : 16 à 512")
    g = _Lcg(graine)
    echantillons = []
    for i in range(nombre):
        w = g.entier(6, largeur // 2)
        h = g.entier(4, hauteur // 2)
        x0 = g.entier(0, largeur - w)
        y0 = g.entier(0, hauteur - h)
        echelle = _ECHELLES[g.entier(0, len(_ECHELLES) - 1)]
        segments = tuple((y * largeur + x0, w) for y in range(y0, y0 + h))
        masque = MasqueRLE(largeur, hauteur, segments)
        s = Decimal(echelle)
        empreinte = journal_site.empreinte_canonique(
            "jeu-synthetique-fictif", graine, i, largeur, hauteur, x0, y0, w, h
        )
        echantillons.append(
            {
                "photo": {
                    "photo_id": f"synth-{graine}-{i}",
                    "empreinte_sha256": empreinte,
                    "largeur": largeur,
                    "hauteur": hauteur,
                    "provenance": {
                        "origine": "jeu_synthetique",
                        "saisie_le": "2026-01-01T00:00:00+00:00",
                        "fictif": True,
                    },
                    "echelle": {"metres_par_pixel": echelle, "source": "declaree"},
                },
                "objet": _OBJET,
                "masque_verite": masque,
                "boite_verite": (x0, y0, x0 + w - 1, y0 + h - 1),
                "surface_verite_m2": formater(Decimal(masque.pixels) * s * s),
            }
        )
    return echantillons


def evaluer(detecteur: Any, echantillons: list[dict[str, Any]], seuils: dict[str, str] | None = None) -> dict[str, Any]:
    """Rapport fictif d'un détecteur sur un jeu. ``seuils`` (facultatif) : ``iou_moyen_min`` et/ou
    ``erreur_surface_relative_max`` (textes décimaux) ; sans seuils déclarés, le rapport mesure et ne juge pas."""
    if not echantillons:
        raise ValueError("jeu vide")
    ious: list[Decimal] = []
    erreurs: list[Decimal] = []
    detectes = rejets = 0
    for e in echantillons:
        sortie, verdict = vision_contrat.executer(
            e["photo"], detecteur, [e["objet"]], politique_validee=False, modeles_qualifies=frozenset()
        )
        if verdict is not None or sortie is None:
            ious.append(Decimal(0))
            rejets += 1
            continue
        rejets += len(sortie["rejetes"])
        meilleur, erreur = Decimal(0), None
        for c in sortie["candidats"]:
            if c["masque"] is None or c["objet"] != e["objet"]:
                continue
            masque = MasqueRLE(
                c["masque"]["largeur"],
                c["masque"]["hauteur"],
                tuple((d, longueur) for d, longueur in c["masque"]["segments"]),
            )
            valeur = vision_contrat.iou(masque, e["masque_verite"])
            if valeur > meilleur or erreur is None:
                meilleur = valeur
                verite = Decimal(e["surface_verite_m2"])
                erreur = abs(Decimal(c["valeur"]) - verite) / verite
        if erreur is not None:
            detectes += 1
            erreurs.append(erreur)
        ious.append(meilleur)
    n = len(echantillons)
    metriques = {
        "echantillons": n,
        "taux_detection": formater(Decimal(detectes) / n),
        "iou_moyen": formater(sum(ious) / n),
        "iou_minimum": formater(min(ious)),
        "erreur_surface_relative_moyenne": None if not erreurs else formater(sum(erreurs) / len(erreurs)),
        "erreur_surface_relative_max": None if not erreurs else formater(max(erreurs)),
        "detections_rejetees_par_le_pipeline": rejets,
    }
    verdict_seuils = None
    if seuils:
        ok = True
        inconnus = sorted(set(seuils) - {"iou_moyen_min", "erreur_surface_relative_max"})
        if inconnus:
            raise ValueError(f"seuils non admis : {inconnus}")
        if "iou_moyen_min" in seuils:
            ok = ok and Decimal(metriques["iou_moyen"]) >= Decimal(seuils["iou_moyen_min"])
        if "erreur_surface_relative_max" in seuils:
            ok = (
                ok
                and metriques["erreur_surface_relative_max"] is not None
                and (
                    Decimal(metriques["erreur_surface_relative_max"]) <= Decimal(seuils["erreur_surface_relative_max"])
                )
            )
        verdict_seuils = "atteints" if ok else "non_atteints"
    modele = detecteur.modele
    rapport = {
        "schema": SCHEMA,
        "fictif": True,
        "qualification": "non_qualifie",
        "portee": "jeu synthétique de rectangles : prouve le harnais, jamais un modèle réel",
        "modele": {"identifiant": modele.identifiant, "version": modele.version},
        "jeu": {
            "empreinte": journal_site.empreinte_canonique([e["photo"]["empreinte_sha256"] for e in echantillons]),
            "echantillons": n,
        },
        "metriques": metriques,
        "seuils_declares": dict(seuils) if seuils else None,
        "seuils": verdict_seuils,
    }
    rapport["empreinte"] = journal_site.empreinte_canonique(rapport)
    return rapport
