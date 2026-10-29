"""Tendances M9.9 : une projection DÉTERMINISTE extrapolée de l'historique des captures, jamais une prévision.

Module pur (aucune horloge, aucun hasard, aucun réseau, aucun import d'``opsys``). La série est lue dans les captures
M9.1 d'UNE lecture du catalogue, à UN chemin de fait numérique (``resultat…``), avec UN jeu d'arguments (l'argument de
référence de la lecture mis à part) : une valeur par capture ACCEPTÉE, COMPLÈTE, non contradictoire et connue à
``connaissance``. L'abscisse est le jour civil UTC du ``recu_a`` (quand M9 a connu la valeur), compté en jours depuis
la première observation. Chaque point est un fait citable ``<lecture>#<rang>:p<page>.<chemin>`` en texte exact.

Trois méthodes calculées par le code, en ``Decimal`` (jamais en flottant) :

* ``moyenne_mobile`` : moyenne des 3 dernières valeurs, projetée à plat ;
* ``droite`` : moindres carrés ordinaires ;
* ``saisonnier_naif`` : valeur observée une saison plus tôt, seulement si l'historique couvre au moins deux saisons
  complètes de ``saison_jours`` (fournie par l'appelant ; M9 n'en suppose aucune).

L'intervalle est projection ± 1,96 × écart-type résiduel : une APPROXIMATION, pas une probabilité calibrée. Aucun tirage
aléatoire. Ce résultat est étiqueté ``tendance_extrapolee`` : ce n'est la prévision d'aucun propriétaire et il ne
remplace jamais la prévision de trésorerie détaillée de M5.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

from . import capture_strategique as cs
from . import catalogue_producteurs as cat

VERSION = "2026-10-29.1"
ORIGINE = "tendance_extrapolee"
LIBELLE = "tendance extrapolée, pas une prévision de propriétaire"
HORIZONS: dict[str, int] = {"7j": 7, "30j": 30, "13s": 91, "6m": 182, "12m": 365, "24m": 730}
METHODES = ("moyenne_mobile", "droite", "saisonnier_naif")
MIN_POINTS = 6
POLITIQUE_MIN_POINTS = "PROPOSEE_NON_VALIDEE_PAR_NATHAN"
FENETRE_MOYENNE = 3
FACTEUR_INTERVALLE = Decimal("1.96")
LIBELLE_INTERVALLE = "approximation, pas une probabilité calibrée"
_PRECISION = 50
_CHEMIN = re.compile(r"resultat(\.[A-Za-z_][A-Za-z0-9_]*)+")
_LIMITES = (
    "Tendance extrapolée par le code à partir des valeurs capturées : ce n'est la prévision d'aucun propriétaire.",
    "Ne remplace jamais la prévision de trésorerie détaillée de M5 (m5.prevision_tresorerie).",
    "L'intervalle (± 1,96 écart-type résiduel) est une approximation, pas une probabilité calibrée.",
    "L'intervalle ne s'élargit pas avec l'horizon : il sous-estime l'incertitude loin des données observées.",
    "L'abscisse est le jour civil UTC de réception par M9, pas l'instant métier déclaré par le producteur.",
    "Une capture refusée, partielle, contradictoire ou sans le fait demandé est écartée et nommée, jamais complétée.",
    f"Minimum de {MIN_POINTS} points : politique proposée, non validée par Nathan.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _texte(valeur: Decimal, quantum: Decimal) -> str:
    return format(valeur.quantize(quantum, rounding=ROUND_HALF_UP), "f")


def _decimal(valeur: object, adresse: str) -> Decimal:
    """Valeur numérique exacte : entier ou texte décimal fini ; tout le reste (booléen, flottant, objet) est refusé."""
    if type(valeur) is int:
        return Decimal(valeur)
    if type(valeur) is str and valeur.strip() == valeur and valeur:
        try:
            nombre = Decimal(valeur)
        except InvalidOperation:
            nombre = None
        if nombre is not None and nombre.is_finite():
            return nombre
    raise _refus(
        "REJ-TENDANCE-VALEUR-NON-NUMERIQUE",
        f"{adresse} ne porte pas un nombre exact (entier ou texte décimal) : {json.dumps(valeur, ensure_ascii=False)}",
    )


def _valider(lecture_id, chemin, horizons, saison_jours, decimales, arguments) -> tuple[cat.Lecture, dict, list]:
    lecture = cat.obtenir(lecture_id)
    if type(chemin) is not str or not _CHEMIN.fullmatch(chemin) or len(chemin) > 200:
        raise _refus("REJ-TENDANCE-CHEMIN", "chemin d'UN fait « resultat.a.b » sans joker requis")
    if not isinstance(horizons, (list, tuple)) or not horizons or len(set(map(str, horizons))) != len(horizons):
        raise _refus("REJ-TENDANCE-HORIZONS", f"liste non vide et sans doublon parmi {sorted(HORIZONS)} requise")
    inconnus = [h for h in horizons if h not in HORIZONS]
    if inconnus:
        raise _refus("REJ-TENDANCE-HORIZONS", f"horizons inconnus {inconnus} ; admis : {sorted(HORIZONS)}")
    if saison_jours is not None and (type(saison_jours) is not int or not 2 <= saison_jours <= 366):
        raise _refus("REJ-TENDANCE-SAISON", "saison en jours entière de 2 à 366, ou absente")
    if type(decimales) is not int or not 0 <= decimales <= 6:
        raise _refus("REJ-TENDANCE-DECIMALES", "entier de 0 à 6 requis")
    if arguments is None:
        arguments = {}
    if type(arguments) is not dict:
        raise _refus("REJ-TENDANCE-ARGUMENTS", "objet d'arguments requis")
    if lecture.reference is not None and lecture.reference in arguments:
        raise _refus(
            "REJ-TENDANCE-ARGUMENTS",
            f"« {lecture.reference} » est la référence de lecture : elle varie d'une capture à l'autre",
        )
    try:
        filtre = cat.arguments_admis(lecture, arguments)
    except ValueError as exc:
        raise _refus("REJ-TENDANCE-ARGUMENTS", str(exc)) from exc
    return lecture, json.loads(cs.canonique(cs.normaliser(filtre))), list(horizons)


def _serie(captures, lecture, chemin, filtre, connaissance) -> tuple[list[dict], list[dict]]:
    connues = cs.connues_a(captures, connaissance)
    contradictoires = {i for c in cs.contradictions(connues) for i in (c["index_a"], c["index_b"])}
    points: list[dict] = []
    ecartees: list[dict] = []
    for capture in connues:
        if capture["lecture_id"] != lecture.id:
            continue
        sans_reference = {k: v for k, v in capture["arguments"].items() if k != lecture.reference}
        if sans_reference != filtre:
            continue  # autre série (autres filtres) : ni point ni écart
        if capture["verdict"] != "ACCEPTEE":
            raison = "REFUSEE"
        elif not capture["complete"]:
            raison = "PARTIELLE"
        elif capture["index"] in contradictoires:
            raison = "CONTRADICTOIRE"
        else:
            raison = None
        if raison is not None:
            ecartees.append({"capture": capture["index"], "recu_a": capture["recu_a"], "raison": raison})
            continue
        trouves: list[tuple[str, object]] = []
        for numero_page, page in enumerate(capture["pages"]):
            for valeur in cs.extraire(page, chemin):
                trouves.append((f"{lecture.id}#{capture['index']}:p{numero_page}.{chemin}", valeur))
        if not trouves:
            ecartees.append({"capture": capture["index"], "recu_a": capture["recu_a"], "raison": "FAIT_ABSENT"})
            continue
        nombres = [(adresse, _decimal(valeur, adresse)) for adresse, valeur in trouves]
        if len({n for _, n in nombres}) != 1:
            raise _refus(
                "REJ-TENDANCE-VALEUR-AMBIGUE",
                f"valeurs différentes d'une page à l'autre : {[adresse for adresse, _ in nombres]}",
            )
        adresse, valeur = nombres[0]
        points.append(
            {
                "capture": capture["index"],
                "recu_a": capture["recu_a"],
                "jour": cs.instant(capture["recu_a"]).date().isoformat(),  # type: ignore[union-attr]
                "valeur": valeur,
                "adresse": adresse,
            }
        )
    if points:
        premier = cs.instant(points[0]["recu_a"]).date()  # type: ignore[union-attr]
        for point in points:
            point["x"] = (cs.instant(point["recu_a"]).date() - premier).days  # type: ignore[union-attr]
    return points, ecartees


def _ecart_type(residus: Sequence[Decimal], degres: int) -> Decimal:
    return (sum((r * r for r in residus), Decimal(0)) / Decimal(degres)).sqrt()


def _moyenne_mobile(xs, ys) -> dict:
    n = len(ys)
    residus = [
        ys[i] - sum(ys[i - FENETRE_MOYENNE : i], Decimal(0)) / FENETRE_MOYENNE for i in range(FENETRE_MOYENNE, n)
    ]
    niveau = sum(ys[-FENETRE_MOYENNE:], Decimal(0)) / FENETRE_MOYENNE
    return {
        "statut": "CALCULEE",
        "projeter": lambda _x: niveau,
        "ecart_type": _ecart_type(residus, len(residus)),
        "residus": len(residus),
        "parametres": {"fenetre": FENETRE_MOYENNE, "niveau": niveau},
    }


def _droite(xs, ys) -> dict:
    n = Decimal(len(xs))
    sx = sum((Decimal(x) for x in xs), Decimal(0))
    sy = sum(ys, Decimal(0))
    sxx = sum((Decimal(x) * x for x in xs), Decimal(0))
    sxy = sum((Decimal(x) * y for x, y in zip(xs, ys, strict=True)), Decimal(0))
    denominateur = n * sxx - sx * sx
    if denominateur == 0:  # pragma: no cover - les abscisses identiques sont refusées avant
        return {"statut": "ABSCISSES_IDENTIQUES"}
    pente = (n * sxy - sx * sy) / denominateur
    ordonnee = (sy - pente * sx) / n
    residus = [y - (ordonnee + pente * x) for x, y in zip(xs, ys, strict=True)]
    return {
        "statut": "CALCULEE",
        "projeter": lambda x: ordonnee + pente * x,
        "ecart_type": _ecart_type(residus, len(residus) - 2),
        "residus": len(residus),
        "parametres": {"pente_par_jour": pente, "ordonnee_origine": ordonnee},
    }


def _saisonnier(xs, ys, saison: int | None) -> dict:
    if saison is None:
        return {"statut": "NON_DEMANDEE", "raison": "aucune saison fournie par l'appelant ; M9 n'en suppose aucune"}
    couverture = xs[-1] - xs[0] + 1
    if couverture < 2 * saison:
        return {
            "statut": "SAISONS_INSUFFISANTES",
            "raison": f"{couverture} jours couverts ; {2 * saison} requis (deux saisons complètes de {saison} jours)",
        }
    par_jour: dict[int, Decimal] = {}
    for x, y in zip(xs, ys, strict=True):
        par_jour[x] = y  # plusieurs captures le même jour : la dernière reçue représente ce jour
    residus = [y - par_jour[x - saison] for x, y in sorted(par_jour.items()) if x - saison in par_jour]
    if not residus:
        return {"statut": "AUCUN_RESIDU_SAISONNIER", "raison": "aucun jour observé exactement une saison plus tôt"}
    dernier = xs[-1]

    def projeter(x: int) -> Decimal | None:
        source = x - saison * (-(-(x - dernier) // saison))  # premier jour ≤ dernier à un multiple de saison
        return par_jour.get(source)

    return {
        "statut": "CALCULEE",
        "projeter": projeter,
        "source_jour": lambda x: x - saison * (-(-(x - dernier) // saison)),
        "ecart_type": _ecart_type(residus, len(residus)),
        "residus": len(residus),
        "parametres": {"saison_jours": saison},
    }


def _sortie_methode(nom, calcul, horizons, dernier_x, duree, quantum, quantum_coef) -> dict:
    sortie: dict = {"methode": nom, "statut": calcul["statut"]}
    if calcul["statut"] != "CALCULEE":
        sortie["raison"] = calcul.get("raison", "")
        sortie["projections"] = []
        return sortie
    ecart = calcul["ecart_type"]
    sortie["ecart_type_residuel"] = _texte(ecart, quantum)
    sortie["residus"] = calcul["residus"]
    sortie["parametres"] = {
        cle: (_texte(v, quantum_coef) if isinstance(v, Decimal) else v) for cle, v in calcul["parametres"].items()
    }
    projections = []
    for horizon in horizons:
        jours = HORIZONS[horizon]
        x = dernier_x + jours
        entree: dict = {"horizon": horizon, "jours": jours, "abscisse": x}
        if jours > duree:
            entree |= {
                "statut": "HORIZON_AU_DELA_DE_L_HISTORIQUE",
                "raison": f"horizon de {jours} jours au-delà des {duree} jours d'historique observés : aucune valeur",
            }
            projections.append(entree)
            continue
        valeur = calcul["projeter"](x)
        if valeur is None:
            entree |= {
                "statut": "JOUR_SAISONNIER_NON_OBSERVE",
                "raison": f"aucune valeur observée au jour {calcul['source_jour'](x)} (une saison plus tôt)",
            }
            projections.append(entree)
            continue
        marge = FACTEUR_INTERVALLE * ecart
        basse, haute = valeur - marge, valeur + marge
        avertissements = []
        if valeur < 0 or basse < 0:
            avertissements.append(
                "valeur négative calculée, conservée telle quelle : si le fait est un compteur, l'extrapolation sort "
                "de son domaine"
            )
        entree |= {
            "statut": "PROJETEE",
            "valeur": _texte(valeur, quantum),
            "borne_basse": _texte(basse, quantum),
            "borne_haute": _texte(haute, quantum),
            "avertissements": avertissements,
        }
        projections.append(entree)
    sortie["projections"] = projections
    return sortie


def projeter(
    captures: Sequence[Mapping],
    *,
    lecture_id: str,
    chemin: str,
    connaissance: str,
    horizons: Sequence[str],
    saison_jours: int | None = None,
    arguments: Mapping | None = None,
    decimales: int = 2,
) -> dict:
    """Tendance extrapolée d'un fait numérique capturé, par trois méthodes déterministes, avec ses points cités."""
    lecture, filtre, liste_horizons = _valider(lecture_id, chemin, horizons, saison_jours, decimales, arguments)
    quantum = Decimal(1).scaleb(-decimales)
    quantum_coef = Decimal(1).scaleb(-(decimales + 4))
    with localcontext(Context(prec=_PRECISION, rounding=ROUND_HALF_UP)):
        points, ecartees = _serie(captures, lecture, chemin, filtre, connaissance)
        xs = [p["x"] for p in points]
        ys = [p["valeur"] for p in points]
        resultat: dict = {
            "type": "TENDANCE_EXTRAPOLEE",
            "version": VERSION,
            "origine": ORIGINE,
            "libelle": LIBELLE,
            "prevision_de_proprietaire": False,
            "ne_remplace_pas": "m5.prevision_tresorerie (trésorerie détaillée de M5)",
            "lecture_id": lecture.id,
            "chemin": chemin,
            "arguments": filtre,
            "connaissance": connaissance,
            "horizons": liste_horizons,
            "saison_jours": saison_jours,
            "decimales": decimales,
            "arrondi": "ROUND_HALF_UP",
            "politique_min_points": {"minimum": MIN_POINTS, "statut": POLITIQUE_MIN_POINTS},
            "intervalle": {"facteur": format(FACTEUR_INTERVALLE, "f"), "libelle": LIBELLE_INTERVALLE},
            "n": len(points),
            "points": [{**p, "valeur": format(p["valeur"], "f")} for p in points],
            "captures_ecartees": ecartees,
            "duree_historique_jours": (xs[-1] - xs[0]) if xs else 0,
            "methodes": [],
            "limites": list(_LIMITES),
        }
        if len(points) < MIN_POINTS:
            resultat |= {
                "statut": "HISTORIQUE_INSUFFISANT",
                "manque": f"{MIN_POINTS - len(points)} point(s) de plus : {len(points)} capture(s) utilisable(s), "
                f"{MIN_POINTS} requises (politique proposée, non validée par Nathan)",
            }
        elif len(set(xs)) == 1:
            resultat |= {
                "statut": "ABSCISSES_IDENTIQUES",
                "manque": "toutes les captures sont du même jour : aucune durée observée, des jours distincts requis",
            }
        elif len(set(ys)) == 1:
            resultat |= {
                "statut": "SERIE_CONSTANTE",
                "manque": "aucune variation observée : aucune tendance à extrapoler, la valeur observée est citée",
                "valeur_observee": format(ys[0], "f"),
            }
        else:
            duree = resultat["duree_historique_jours"]
            calculs = {
                "moyenne_mobile": _moyenne_mobile(xs, ys),
                "droite": _droite(xs, ys),
                "saisonnier_naif": _saisonnier(xs, ys, saison_jours),
            }
            resultat["statut"] = "PROJETEE"
            resultat["methodes"] = [
                _sortie_methode(nom, calculs[nom], liste_horizons, xs[-1], duree, quantum, quantum_coef)
                for nom in METHODES
            ]
    resultat["projection_id"] = hashlib.sha256(cs.canonique(resultat).encode()).hexdigest()
    return resultat
