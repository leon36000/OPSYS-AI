"""Tendances déterministes de M8 (C8) sur l'historique RÉEL des constructions.

L'historique ``m8_ent_mesures_hist`` n'est PAS un échantillonnage régulier : chaque ligne vient d'une construction
déclenchée par un changement de source. Ce module ne suppose donc ni période, ni cadence, ni saisonnalité. Il lit les
faits tels qu'ils sont, dit lesquels sont comparables, et refuse de calculer ce dont les préconditions ne sont pas
prouvées.

Règles :

* **Aucun zéro inventé.** Une ligne non calculable, une valeur non finie ou illisible, un instant illisible, un
  doublon ou une version de définition incompatible est EXCLU et compté avec sa raison. Une série vide ne produit
  aucune valeur : les calculs sont ``non_calculable`` ou ``non_evalue`` et le disent.
* **Même version, même unité.** Seules les observations dont ``version_definition`` est celle du catalogue COURANT
  sont retenues ; l'unité vient de ce catalogue et n'est jamais devinée.
* **Couverture des observations.** Seule une couverture explicitement complète est retenue. Partielle, inconnue,
  absente (notamment ancien historique SQL NULL) ou invalide : exclusion comptée séparément, jamais supposée complète.
* **Variation** : absolue = dernière − première (ou avant-dernière → dernière) ; relative en pourcentage seulement si
  la base est strictement positive. Base nulle ou négative : ``non_calculable`` (jamais une division par zéro, jamais
  un pourcentage trompeur). La variation porte sur des OBSERVATIONS, pas sur des périodes calendaires.
* **Moyenne mobile** : moyenne arithmétique des ``k`` dernières observations valides, ``k = min(fenêtre demandée, n)``,
  avec ``k >= 2``. Définition rendue dans la réponse.
* **XmR et prévision** : seulement si la cadence observée est EXACTEMENT régulière (tous les intervalles égaux) et
  si ``n >= 8``. Sinon ``non_evalue`` avec la raison. Le XmR est en ``Decimal`` (constante 2,66 reprise de ``xmr.py``,
  dont le contrat flottant historique n'est pas modifié) ; la prévision est une régression linéaire par moindres
  carrés sur l'index des observations. Les « bornes » sont l'enveloppe des résidus observés : ce n'est PAS un
  intervalle de confiance. Une prévision n'est jamais un fait observé.
* **Trous** : non évalués. Aucune cadence attendue n'est déclarée dans le contrat ; un intervalle long n'est pas
  prouvé comme un trou, et un intervalle court ne prouve pas une observation manquante.
* **Futur** : toute construction STRICTEMENT postérieure à ``maintenant`` est écartée des calculs (une construction à
  l'instant même est acceptée) et comptée distinctement dans ``couverture.futur``. Elle n'entre ni dans la série, ni
  dans la variation, la moyenne, le XmR ou la prévision. La lecture de l'historique reste bornée AVANT l'analyse :
  ``couverture.lecture`` dit si la borne est atteinte et ``couverture.futur`` dit que des observations antérieures
  peuvent exister au-delà de la fenêtre lue, sans prétendre les récupérer.
  Une construction future autrement valide est comptée comme future quelle que soit sa couverture, sans double compte.
* **Bornes de sortie** : historique lu borné (1000 lignes au plus), fenêtre 2 à 200 observations, moyenne mobile 2 à
  12, horizon 1 à 12. Le résultat est paginé par l'outil sous la limite du socle.
* **Lecture pure** : aucun import d'``opsys``, aucune horloge, aucune écriture. ``maintenant`` est injecté.

Non livré volontairement (voir ``non_livre``) : saisonnalité, intervalle de confiance, prévision périodique et fiches
de variance par matériau/durée/marge. L'historique ne conserve pas les paires prévu/réel par chantier et une série
irrégulière ne permet pas ces calculs sans les inventer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, DecimalException, localcontext
from typing import Any

from . import encodage, entonnoir, fraicheur_mesures, nombres, xmr

SCHEMA_RECU = "opsys.m8.tendances.recu/v1"

FENETRE_OBSERVATIONS_DEFAUT = 30
FENETRE_OBSERVATIONS_MIN = 2
FENETRE_OBSERVATIONS_MAX = 200
FENETRE_MOYENNE_MOBILE_DEFAUT = 3
FENETRE_MOYENNE_MOBILE_MIN = 2
FENETRE_MOYENNE_MOBILE_MAX = 12
HORIZON_PREVISION_DEFAUT = 1
HORIZON_PREVISION_MIN = 1
HORIZON_PREVISION_MAX = 12
MIN_OBSERVATIONS_XMR = 8
MIN_OBSERVATIONS_PREVISION = 8
HISTORIQUE_MAX = 1000
# Précision du contexte Decimal pour les divisions (moyenne, relative, pente, résidus). Choix explicite : 28 chiffres,
# la précision par défaut de la bibliothèque, assez pour des valeurs bornées à 1e15 et un affichage à 2 décimales.
PRECISION_DECIMALE = 28
_LONGUEUR_IDENTIFIANT = 64
_LONGUEUR_INSTANT = 40
_LONGUEUR_VALEUR = 80
_EXEMPLES_MAX = 3
_CONSTANTE_XMR = Decimal(str(xmr.CONSTANTE_XMR))

REJ_FENETRE_INVALIDE = "REJ-TENDANCES-FENETRE-INVALIDE"
REJ_MOYENNE_MOBILE_INVALIDE = "REJ-TENDANCES-MOYENNE-MOBILE-INVALIDE"
REJ_HORIZON_INVALIDE = "REJ-TENDANCES-HORIZON-INVALIDE"
REJ_HISTORIQUE_INVALIDE = "REJ-TENDANCES-HISTORIQUE-INVALIDE"
REJ_HISTORIQUE_TROP_VOLUMINEUX = "REJ-TENDANCES-HISTORIQUE-TROP-VOLUMINEUX"
REJ_LIMITE_LECTURE_INVALIDE = "REJ-TENDANCES-LIMITE-LECTURE-INVALIDE"
REJ_MAINTENANT_INVALIDE = "REJ-TENDANCES-MAINTENANT-INVALIDE"
REJ_ENTREE_INVALIDE = "REJ-TENDANCES-ENTREE-INVALIDE"

_RAISONS = (
    "metrique_incompatible",
    "construction_invalide",
    "doublon",
    "instant_construction_invalide",
    "non_calculable",
    "valeur_invalide",
    "version_incompatible",
    "instant_fait_invalide",
    "instant_ambigu",
    "couverture_partielle",
    "couverture_inconnue",
    "couverture_absente",
    "couverture_invalide",
)

_NON_LIVRE = {
    "saisonnalite": "non livrée : aucune série saisonnière régulière prouvée",
    "intervalle_confiance": "non livré : bornes = résidus observés, pas un intervalle de confiance",
    "prevision_periodique": "non livrée : aucun pas de période calendaire déclaré",
    "fiches_variance": "non livrées : l'historique ne garde pas les paires prévu/réel par chantier",
}

_LIMITES = (
    "Historique irrégulier ; couverture absente = inconnue ; seules les complètes sont retenues.",
    "Variations entre observations, pas périodes calendaires.",
    "XmR et prévision : cadence régulière et n >= 8.",
    "Futur exclu ; lecture bornée ; trous non déduits.",
    "Pas de saisonnalité ni intervalle de confiance ; prévision non observée.",
    "Décision financière : validation CPA requise.",
)


def valider_parametres(
    fenetre_observations: Any = FENETRE_OBSERVATIONS_DEFAUT,
    fenetre_moyenne_mobile: Any = FENETRE_MOYENNE_MOBILE_DEFAUT,
    horizon_prevision: Any = HORIZON_PREVISION_DEFAUT,
) -> tuple[int, int, int]:
    """Les trois tailles de fenêtre, bornées et typées. Un booléen n'est pas un entier ; rien n'est corrigé."""
    if type(fenetre_observations) is not int or not (
        FENETRE_OBSERVATIONS_MIN <= fenetre_observations <= FENETRE_OBSERVATIONS_MAX
    ):
        raise ValueError(
            f"{REJ_FENETRE_INVALIDE} : fenetre_observations est un entier de {FENETRE_OBSERVATIONS_MIN} à "
            f"{FENETRE_OBSERVATIONS_MAX}"
        )
    if type(fenetre_moyenne_mobile) is not int or not (
        FENETRE_MOYENNE_MOBILE_MIN <= fenetre_moyenne_mobile <= FENETRE_MOYENNE_MOBILE_MAX
    ):
        raise ValueError(
            f"{REJ_MOYENNE_MOBILE_INVALIDE} : fenetre_moyenne_mobile est un entier de {FENETRE_MOYENNE_MOBILE_MIN} à "
            f"{FENETRE_MOYENNE_MOBILE_MAX}"
        )
    if type(horizon_prevision) is not int or not (HORIZON_PREVISION_MIN <= horizon_prevision <= HORIZON_PREVISION_MAX):
        raise ValueError(
            f"{REJ_HORIZON_INVALIDE} : horizon_prevision est un entier de {HORIZON_PREVISION_MIN} à "
            f"{HORIZON_PREVISION_MAX}"
        )
    return fenetre_observations, fenetre_moyenne_mobile, horizon_prevision


def _maintenant_lu(maintenant: Any) -> datetime:
    if not isinstance(maintenant, datetime) or maintenant.tzinfo is None or maintenant.utcoffset() is None:
        raise ValueError(f"{REJ_MAINTENANT_INVALIDE} : un datetime avec fuseau est attendu")
    return maintenant


def _cle_utc_datetime(instant: datetime) -> str:
    """Clé UTC à longueur fixe d'un ``datetime``, à la microseconde (précision native de ``datetime``).

    La clé a exactement la forme de ``entonnoir.instant_utc`` (nanoseconde, neuf chiffres) : une observation datée
    une nanoseconde après ``maintenant`` a donc une clé strictement supérieure, même si ``datetime`` la tronque à la
    microseconde. ``maintenant`` ne peut pas porter plus que la microseconde ; la clé le dit explicitement.
    """
    try:
        utc = instant.astimezone(UTC)
    except OverflowError:
        raise ValueError(f"{REJ_MAINTENANT_INVALIDE} : la normalisation UTC sort de la plage datetime") from None
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
        f".{utc.microsecond:06d}000Z"
    )


def _entree_lue(entree: Any) -> dict[str, Any]:
    if not isinstance(entree, dict):
        raise ValueError(f"{REJ_ENTREE_INVALIDE} : une entrée de catalogue est attendue")
    for cle in ("metric_id", "nom", "unite", "proprietaire", "version_definition"):
        if not isinstance(entree.get(cle), str) or not entree[cle]:
            raise ValueError(f"{REJ_ENTREE_INVALIDE} : {cle} est un texte non vide")
    if not isinstance(entree.get("fraicheur"), dict) or not entree["fraicheur"]:
        raise ValueError(f"{REJ_ENTREE_INVALIDE} : fraicheur est un dictionnaire non vide")
    return entree


def _longueur_ok(valeur: Any, maximum: int) -> bool:
    return isinstance(valeur, str) and 0 < len(valeur) <= maximum


def _exemple(construction: Any, raison: str) -> dict[str, Any]:
    return {
        "construction_id": construction[:16] if _longueur_ok(construction, _LONGUEUR_IDENTIFIANT) else None,
        "raison": raison,
    }


def _valeur_lue(valeur: Any) -> Decimal | None:
    if isinstance(valeur, str):
        if not valeur or len(valeur) > _LONGUEUR_VALEUR:
            return None
    elif isinstance(valeur, bool) or not isinstance(valeur, (int, float, Decimal)):
        return None
    return nombres.decimal_lu(valeur)


def raison_couverture(ligne: dict[str, Any]) -> str | None:
    """Une couverture historique absente n'est pas la couverture inconnue déclarée par le producteur."""
    couverture = ligne.get("couverture")
    if couverture is None:
        return "couverture_absente"
    if not isinstance(couverture, dict):
        return "couverture_invalide"
    etat = couverture.get("etat")
    if not isinstance(etat, str):
        return "couverture_invalide"
    return {
        "complete": None,
        "partielle": "couverture_partielle",
        "inconnue": "couverture_inconnue",
    }.get(etat, "couverture_invalide")


def _valider_ligne(ligne: dict[str, Any], entree: dict[str, Any]) -> str | None:
    """La PREMIÈRE raison de rejet d'une ligne, ou ``None`` si elle est calculable et comparable."""
    metric_id = ligne.get("metric_id")
    if metric_id is not None and metric_id != entree["metric_id"]:
        return "metrique_incompatible"
    construit_le = ligne.get("construit_le")
    cle_attendue = entonnoir.instant_utc(construit_le)
    if (
        not _longueur_ok(construit_le, _LONGUEUR_INSTANT)
        or entonnoir.instant_lu(construit_le) is None
        or cle_attendue is None
    ):
        return "instant_construction_invalide"
    cle_utc = ligne.get("construit_le_utc")
    if cle_utc is not None and cle_utc != cle_attendue:
        # La clé stockée doit correspondre EXACTEMENT au texte d'origine : une clé incohérente ferait trier la
        # lecture sur un ordre qui n'est pas celui de la ligne.
        return "instant_construction_invalide"
    if ligne.get("statut") != entonnoir.STATUT_CALCULEE:
        return "non_calculable"
    if _valeur_lue(ligne.get("valeur")) is None:
        return "valeur_invalide"
    if ligne.get("version_definition") != entree["version_definition"]:
        return "version_incompatible"
    derniere = ligne.get("dernier_fait_le")
    if derniere is not None and (
        not _longueur_ok(derniere, _LONGUEUR_INSTANT) or entonnoir.instant_lu(derniere) is None
    ):
        return "instant_fait_invalide"
    return None


def _preparer(
    historique: Any, entree: dict[str, Any], maintenant_cle: str
) -> tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Filtre l'historique en points comparables, et sépare les constructions futures.

    Rend ``(comptes, exemples, points_retenables, points_futurs)``. Les points futures sont VALIDES mais écartés des
    calculs : ils ne participent ni à l'ambiguïté d'instant, ni à la fenêtre. Les doublons et les lignes invalides
    gardent leur raison existante et sont comptés avant cette séparation.
    """
    if not isinstance(historique, (list, tuple)):
        raise ValueError(f"{REJ_HISTORIQUE_INVALIDE} : une liste de lignes d'historique est attendue")
    if len(historique) > HISTORIQUE_MAX:
        raise ValueError(
            f"{REJ_HISTORIQUE_TROP_VOLUMINEUX} : {len(historique)} lignes (maximum {HISTORIQUE_MAX})"
        )
    comptes = {raison: 0 for raison in _RAISONS}
    exemples: list[dict[str, Any]] = []
    bruts: list[tuple[str, dict[str, Any]]] = []
    identifiants: dict[str, int] = {}
    for ligne in historique:
        if not isinstance(ligne, dict):
            comptes["construction_invalide"] += 1
            if len(exemples) < _EXEMPLES_MAX:
                exemples.append(_exemple(None, "construction_invalide"))
            continue
        construction = ligne.get("construction_id")
        if not _longueur_ok(construction, _LONGUEUR_IDENTIFIANT):
            comptes["construction_invalide"] += 1
            if len(exemples) < _EXEMPLES_MAX:
                exemples.append(_exemple(construction, "construction_invalide"))
            continue
        identifiants[construction] = identifiants.get(construction, 0) + 1
        bruts.append((construction, ligne))

    doublons = {construction for construction, nombre in identifiants.items() if nombre > 1}
    candidats: list[dict[str, Any]] = []
    futurs: list[dict[str, Any]] = []
    for construction, ligne in bruts:
        if construction in doublons:
            comptes["doublon"] += 1
            if len(exemples) < _EXEMPLES_MAX:
                exemples.append(_exemple(construction, "doublon"))
            continue
        raison = _valider_ligne(ligne, entree)
        if raison is not None:
            comptes[raison] += 1
            if len(exemples) < _EXEMPLES_MAX:
                exemples.append(_exemple(construction, raison))
            continue
        instant = entonnoir.instant_lu(ligne["construit_le"])
        valeur = _valeur_lue(ligne["valeur"])
        cle_utc = entonnoir.instant_utc(ligne["construit_le"])
        if instant is None or valeur is None or cle_utc is None or _afficher(valeur) is None:  # défense en profondeur
            comptes["valeur_invalide"] += 1
            if len(exemples) < _EXEMPLES_MAX:
                exemples.append(_exemple(construction, "valeur_invalide"))
            continue
        point = {
            "construction_id": construction,
            "construit_le": ligne["construit_le"],
            "cle_utc": cle_utc,
            "instant": instant,
            "valeur": valeur,
            "version_definition": ligne["version_definition"],
            "dernier_fait_le": ligne.get("dernier_fait_le"),
            "raison_couverture": raison_couverture(ligne),
        }
        if cle_utc > maintenant_cle:
            futurs.append(point)
        else:
            candidats.append(point)

    par_instant: dict[str, list[dict[str, Any]]] = {}
    for point in candidats:
        par_instant.setdefault(point["cle_utc"], []).append(point)
    uniques: list[dict[str, Any]] = []
    for groupe in par_instant.values():
        if len(groupe) > 1:
            comptes["instant_ambigu"] += len(groupe)
            if len(exemples) < _EXEMPLES_MAX:
                for point in groupe[: _EXEMPLES_MAX - len(exemples)]:
                    exemples.append(_exemple(point["construction_id"], "instant_ambigu"))
            continue
        point = groupe[0]
        raison = point["raison_couverture"]
        if raison is not None:
            comptes[raison] += 1
            continue
        uniques.append(point)
    uniques.sort(key=lambda point: (point["cle_utc"], point["construction_id"]))
    futurs.sort(key=lambda point: (point["cle_utc"], point["construction_id"]))
    return comptes, exemples, uniques, futurs


def _nanosecondes_depuis_cle(cle: str) -> int:
    """Convertit une clé UTC fixe en nanosecondes ordinales sans perdre sa fraction sub-microseconde."""
    jour = datetime.fromisoformat(cle[:19]).date()
    heure = int(cle[11:13])
    minute = int(cle[14:16])
    seconde = int(cle[17:19])
    fraction = int(cle[20:29])
    secondes = ((jour.toordinal() * 24 + heure) * 60 + minute) * 60 + seconde
    return secondes * 1_000_000_000 + fraction


def _secondes_entre(debut_cle: str, fin_cle: str) -> Decimal:
    """La durée UTC exacte à la nanoseconde, sans flottant ni troncature par datetime."""
    ecart_ns = _nanosecondes_depuis_cle(fin_cle) - _nanosecondes_depuis_cle(debut_cle)
    return Decimal(ecart_ns) / Decimal(1_000_000_000)


def _duree_texte(secondes: Decimal) -> str:
    texte = format(secondes, "f")
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return "0" if texte in ("", "-0") else texte


def _afficher(valeur: Decimal | None) -> str | None:
    if valeur is None:
        return None
    try:
        if not valeur.is_finite():
            return None
        return nombres.texte_decimal(valeur)
    except (DecimalException, ValueError):
        return None


def _point_sortie(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "construction_id": point["construction_id"],
        "construit_le": point["construit_le"],
        "valeur": _afficher(point["valeur"]),
        "dernier_fait_le": point["dernier_fait_le"],
    }


def _reference(point: dict[str, Any] | None) -> dict[str, Any] | None:
    if point is None:
        return None
    return {
        "construction_id": point["construction_id"],
        "construit_le": point["construit_le"],
        "valeur": _afficher(point["valeur"]),
    }


def _variation(debut: dict[str, Any] | None, fin: dict[str, Any] | None, unite: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "de": _reference(debut),
        "a": _reference(fin),
    }
    if debut is None or fin is None:
        base["absolue"] = {"statut": "non_calculable", "valeur": None, "raison": "moins_de_2_observations"}
        base["relative_pct"] = {"statut": "non_calculable", "valeur": None, "raison": "moins_de_2_observations"}
        return base
    with localcontext() as contexte_decimal:
        contexte_decimal.prec = PRECISION_DECIMALE
        difference = fin["valeur"] - debut["valeur"]
        absolue = {
            "statut": "calculee" if _afficher(difference) is not None else "non_calculable",
            "valeur": _afficher(difference),
            "unite": unite,
        }
        if absolue["statut"] == "non_calculable":
            absolue["raison"] = "valeur_non_affichable"
        if debut["valeur"].is_zero():
            relative = {"statut": "non_calculable", "valeur": None, "raison": "base_nulle"}
        elif debut["valeur"] < 0:
            relative = {"statut": "non_calculable", "valeur": None, "raison": "base_negative"}
        else:
            taux = difference / debut["valeur"] * Decimal(100)
            relative = {
                "statut": "calculee" if _afficher(taux) is not None else "non_calculable",
                "valeur": _afficher(taux),
                "unite": "pourcent",
            }
            if relative["statut"] == "non_calculable":
                relative["raison"] = "valeur_non_affichable"
    base["absolue"] = absolue
    base["relative_pct"] = relative
    return base


def _moyenne_mobile(points: list[dict[str, Any]], fenetre: int) -> dict[str, Any]:
    if len(points) < 2:
        return {
            "statut": "non_evaluee",
            "raison": "moins_de_2_observations",
            "fenetre": 0,
            "n": len(points),
            "valeur": None,
            "definition": "moyenne arithmétique des k dernières observations valides (k = min(fenêtre demandée, n))",
        }
    k = min(fenetre, len(points))
    with localcontext() as contexte_decimal:
        contexte_decimal.prec = PRECISION_DECIMALE
        moyenne = sum((point["valeur"] for point in points[-k:]), Decimal(0)) / Decimal(k)
    valeur = _afficher(moyenne)
    return {
        "statut": "calculee" if valeur is not None else "non_evaluee",
        "raison": None if valeur is not None else "valeur_non_affichable",
        "fenetre": k,
        "n": k,
        "valeur": valeur,
        "definition": "moyenne arithmétique des k dernières observations valides (k = min(fenêtre demandée, n))",
    }


def _cadence(points: list[dict[str, Any]]) -> dict[str, Any]:
    intervalles = [_secondes_entre(points[i - 1]["cle_utc"], points[i]["cle_utc"]) for i in range(1, len(points))]
    if not intervalles:
        return {
            "cadence": "non_evaluee",
            "raison": "moins_de_2_observations",
            "intervalles": {"n": 0, "min_s": None, "max_s": None, "tous_egaux": None},
        }
    tous_egaux = all(intervalle == intervalles[0] for intervalle in intervalles)
    return {
        "cadence": "reguliere" if tous_egaux else "irreguliere",
        "raison": "tous les intervalles sont égaux" if tous_egaux else "au moins un intervalle diffère",
        "intervalles": {
            "n": len(intervalles),
            "min_s": _duree_texte(min(intervalles)),
            "max_s": _duree_texte(max(intervalles)),
            "tous_egaux": tous_egaux,
        },
    }


def _fraicheur(
    entree: dict[str, Any],
    points: list[dict[str, Any]],
    maintenant: datetime,
    fenetres_proprietaire: dict[str, int] | None,
    cadences_proprietaire: dict[str, int] | None,
    futures_ecartees: int,
    maintenant_cle: str,
) -> dict[str, Any]:
    fenetre = fraicheur_mesures.fenetre_effective(
        entree, fenetres_proprietaire or {}, None, None, cadences_proprietaire or {}
    )
    if not points:
        motif = "aucune observation valide dans l'historique : rien à dater"
        if futures_ecartees:
            motif = (
                f"{futures_ecartees} observation(s) postérieure(s) à maintenant écartée(s) et aucune observation "
                "antérieure ou égale retenue dans la fenêtre lue : la fraîcheur est inconnue"
            )
        return {
            "statut": "inconnu",
            "age_s": None,
            "fenetre_s": fenetre["secondes"],
            "origine_fenetre": fenetre["origine"],
            "peut_etre_montree_comme_a_jour": False,
            "motif": motif,
            "construit_le": None,
            "age_construction_s": None,
            "dernier_fait_le": None,
            "construction_dans_le_futur": False,
        }
    dernier = points[-1]
    age_construction = _secondes_entre(dernier["cle_utc"], maintenant_cle)
    futur = age_construction < 0
    pseudo = {
        "statut": entonnoir.STATUT_CALCULEE,
        "dernier_fait_le": dernier["dernier_fait_le"],
        "qualite": {"statut": "ok"},
    }
    evaluee = fraicheur_mesures.evaluer(pseudo, maintenant, fenetre)
    if futur:
        evaluee = {
            **evaluee,
            "statut": "inconnu",
            "peut_etre_montree_comme_a_jour": False,
            "motif": "construction datée après l'instant de l'appelant : la fraîcheur est inconnue",
        }
    return {
        **evaluee,
        "construit_le": dernier["construit_le"],
        "age_construction_s": None if futur else int(age_construction),
        "dernier_fait_le": dernier["dernier_fait_le"],
        "construction_dans_le_futur": futur,
    }


def _xmr(points: list[dict[str, Any]], cadence: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "statut": "non_evalue",
        "raison": None,
        "n": len(points),
        "methode": "XmR (moyenne, amplitude moyenne des écarts successifs, constante 2.66)",
        "preconditions": "8 observations valides, cadence exactement régulière, même version et unité",
        "constante": str(_CONSTANTE_XMR),
        "centre": None,
        "amplitude_moyenne": None,
        "limite_haute": None,
        "limite_basse": None,
        "signal": None,
        "valeur_observee": None,
    }
    if len(points) < 2:
        base["raison"] = "moins_de_2_observations"
        return base
    if cadence["cadence"] != "reguliere":
        base["raison"] = "cadence_irreguliere"
        return base
    if len(points) < MIN_OBSERVATIONS_XMR:
        base["raison"] = "moins_de_8_observations"
        return base
    try:
        with localcontext() as contexte_decimal:
            contexte_decimal.prec = PRECISION_DECIMALE
            valeurs = [point["valeur"] for point in points]
            centre = sum(valeurs, Decimal(0)) / Decimal(len(valeurs))
            amplitudes = [abs(valeurs[i] - valeurs[i - 1]) for i in range(1, len(valeurs))]
            amplitude_moyenne = sum(amplitudes, Decimal(0)) / Decimal(len(amplitudes))
            limite_haute = centre + _CONSTANTE_XMR * amplitude_moyenne
            limite_basse = centre - _CONSTANTE_XMR * amplitude_moyenne
            derniere = valeurs[-1]
            if derniere > limite_haute:
                signal = "HORS_LIMITE_SUPERIEURE"
            elif derniere < limite_basse:
                signal = "HORS_LIMITE_INFERIEURE"
            else:
                signal = "DANS_LES_LIMITES"
    except (DecimalException, ValueError):
        base["raison"] = "calcul_impossible"
        return base
    return {
        **base,
        "statut": "evalue",
        "centre": _afficher(centre),
        "amplitude_moyenne": _afficher(amplitude_moyenne),
        "limite_haute": _afficher(limite_haute),
        "limite_basse": _afficher(limite_basse),
        "signal": signal,
        "valeur_observee": _afficher(derniere),
    }


def _prevision(points: list[dict[str, Any]], cadence: dict[str, Any], horizon: int) -> dict[str, Any]:
    base: dict[str, Any] = {
        "statut": "non_evaluee",
        "raison": None,
        "methode": "moindres_carres_lineaire",
        "n": len(points),
        "horizon": horizon,
        "preconditions": "8 observations valides, cadence exactement régulière, même version et unité",
        "pente": None,
        "ordonnee": None,
        "valeur_prevue": None,
        "bornes_observees": {"min_residu": None, "max_residu": None, "intervalle": [None, None]},
        "avertissement": "Prévision déterministe, jamais un fait observé ; bornes = enveloppe des résidus, pas un "
        "intervalle de confiance.",
    }
    if cadence["cadence"] != "reguliere":
        base["raison"] = "cadence_irreguliere"
        return base
    if len(points) < MIN_OBSERVATIONS_PREVISION:
        base["raison"] = "moins_de_8_observations"
        return base
    try:
        with localcontext() as contexte_decimal:
            contexte_decimal.prec = PRECISION_DECIMALE
            valeurs = [point["valeur"] for point in points]
            n = len(valeurs)
            xs = [Decimal(i) for i in range(n)]
            x_barre = sum(xs, Decimal(0)) / Decimal(n)
            y_barre = sum(valeurs, Decimal(0)) / Decimal(n)
            sxx = sum(((x - x_barre) ** 2 for x in xs), Decimal(0))
            if sxx == 0:
                base["raison"] = "calcul_impossible"
                return base
            sxy = sum(((x - x_barre) * (y - y_barre) for x, y in zip(xs, valeurs, strict=True)), Decimal(0))
            pente = sxy / sxx
            ordonnee = y_barre - pente * x_barre
            x_prevu = Decimal(n - 1 + horizon)
            prevue = ordonnee + pente * x_prevu
            residus = [y - (ordonnee + pente * x) for x, y in zip(xs, valeurs, strict=True)]
            min_residu, max_residu = min(residus), max(residus)
            intervalle = [prevue + min_residu, prevue + max_residu]
    except (DecimalException, ValueError):
        base["raison"] = "calcul_impossible"
        return base
    return {
        **base,
        "statut": "evaluee",
        "pente": _afficher(pente),
        "ordonnee": _afficher(ordonnee),
        "valeur_prevue": _afficher(prevue),
        "bornes_observees": {
            "min_residu": _afficher(min_residu),
            "max_residu": _afficher(max_residu),
            "intervalle": [_afficher(intervalle[0]), _afficher(intervalle[1])],
        },
    }


def _recu(
    *,
    entree: dict[str, Any],
    version_catalogue: str | None,
    maintenant: datetime,
    fenetre_observations: int,
    fenetre_moyenne_mobile: int,
    horizon_prevision: int,
    serie: list[dict[str, Any]],
    variation: dict[str, Any],
    moyenne: dict[str, Any],
    xmr_resultat: dict[str, Any],
    prevision: dict[str, Any],
    futures_ecartees: int,
    exclusions: dict[str, int],
    maintenant_cle: str,
) -> dict[str, Any]:
    corps = {
        "schema": SCHEMA_RECU,
        "metric_id": entree["metric_id"],
        "version_definition": entree["version_definition"],
        "version_catalogue": version_catalogue,
        "maintenant": maintenant.isoformat(),
        "fenetre_observations": fenetre_observations,
        "fenetre_moyenne_mobile": fenetre_moyenne_mobile,
        "horizon_prevision": horizon_prevision,
        "n_points": len(serie),
        "empreinte_serie": encodage.empreinte(serie),
        "futures_ecartees": futures_ecartees,
        "empreinte_exclusions": encodage.empreinte(exclusions),
        "variation_absolue": variation["absolue"]["valeur"],
        "variation_relative_pct": variation["relative_pct"]["valeur"],
        "moyenne_mobile": moyenne["valeur"],
        "xmr_statut": xmr_resultat["statut"],
        "prevision_statut": prevision["statut"],
    }
    if maintenant_cle != _cle_utc_datetime(maintenant):
        # Une borne à la nanoseconde ne tient pas dans ``datetime`` : le reçu porte alors la clé exacte utilisée,
        # sinon sa représentation suffirait et le champ resterait absent (réponses courantes inchangées).
        corps["maintenant_cle"] = maintenant_cle
    return {**corps, "empreinte": encodage.empreinte(corps)}


def verifier_recu(recu: Any) -> bool:
    """Vrai si l'empreinte correspond au contenu : ce hachage non signé ne prouve pas son authenticité."""
    if not isinstance(recu, dict) or recu.get("schema") != SCHEMA_RECU or not isinstance(recu.get("empreinte"), str):
        return False
    corps = {cle: valeur for cle, valeur in recu.items() if cle != "empreinte"}
    try:
        return encodage.empreinte(corps) == recu["empreinte"]
    except TypeError:
        return False


def analyser(
    historique: Any,
    entree: dict[str, Any],
    maintenant: datetime,
    *,
    fenetre_observations: int = FENETRE_OBSERVATIONS_DEFAUT,
    fenetre_moyenne_mobile: int = FENETRE_MOYENNE_MOBILE_DEFAUT,
    horizon_prevision: int = HORIZON_PREVISION_DEFAUT,
    fenetres_proprietaire: dict[str, int] | None = None,
    cadences_proprietaire: dict[str, int] | None = None,
    version_catalogue: str | None = None,
    limite_lecture: int | None = None,
    maintenant_cle: str | None = None,
) -> dict[str, Any]:
    """Analyse une série d'historique et rend la réponse complète, reçu compris.

    ``historique`` est la liste des lignes lues de ``m8_ent_mesures_hist`` (l'ordre d'entrée n'importe pas : les
    observations sont triées par instant puis par identifiant de construction). La fenêtre retient les
    ``fenetre_observations`` observations VALIDES les plus récentes ; les plus anciennes sont comptées
    ``hors_fenetre``. Une ligne rejetée n'est jamais remplacée par une valeur inventée.

    Les constructions STRICTEMENT postérieures à ``maintenant`` sont écartées des calculs, comptées dans
    ``couverture.futurs_ecartes`` et absentes de la série et du reçu. ``limite_lecture`` est la borne déjà appliquée
    par ``lire_historique`` : elle sert seulement à dire si la borne a été atteinte, jamais à lire au-delà.
    """
    fenetre_observations, fenetre_moyenne_mobile, horizon_prevision = valider_parametres(
        fenetre_observations, fenetre_moyenne_mobile, horizon_prevision
    )
    if limite_lecture is not None and (
        type(limite_lecture) is not int or not 1 <= limite_lecture <= HISTORIQUE_MAX
    ):
        raise ValueError(
            f"{REJ_LIMITE_LECTURE_INVALIDE} : limite_lecture est un entier de 1 à {HISTORIQUE_MAX}"
        )
    instant = _maintenant_lu(maintenant)
    entree = _entree_lue(entree)
    if maintenant_cle is None:
        maintenant_cle = _cle_utc_datetime(instant)
    elif not isinstance(maintenant_cle, str) or entonnoir.instant_utc(maintenant_cle) != maintenant_cle:
        raise ValueError(
            f"{REJ_MAINTENANT_INVALIDE} : maintenant_cle doit être une clé UTC normalisée à la nanoseconde"
        )
    elif maintenant_cle[:26] != _cle_utc_datetime(instant)[:26]:
        raise ValueError(f"{REJ_MAINTENANT_INVALIDE} : maintenant et maintenant_cle sont incohérents")
    comptes, exemples, uniques, futurs = _preparer(historique, entree, maintenant_cle)
    borne_atteinte = None if limite_lecture is None else len(historique) >= limite_lecture
    # Même un point futur exclu pour une autre raison peut occuper la borne et masquer des points plus anciens.
    futur_lu = any(
        isinstance(ligne, dict)
        and (cle := entonnoir.instant_utc(ligne.get("construit_le"))) is not None
        and cle > maintenant_cle
        for ligne in historique
    )
    if len(uniques) > fenetre_observations:
        hors_fenetre = len(uniques) - fenetre_observations
        points = uniques[-fenetre_observations:]
    else:
        hors_fenetre = 0
        points = uniques
    serie = [_point_sortie(point) for point in points]
    cadence = _cadence(points)
    if len(points) >= 2:
        variation = _variation(points[0], points[-1], entree["unite"])
        variation_derniere = _variation(points[-2], points[-1], entree["unite"])
        variation_derniere.pop("de", None)
        variation_derniere.pop("a", None)
        fraicheur = _fraicheur(
            entree, points, instant, fenetres_proprietaire, cadences_proprietaire, len(futurs), maintenant_cle
        )
        etendue = _duree_texte(_secondes_entre(points[0]["cle_utc"], points[-1]["cle_utc"]))
    else:
        variation = _variation(None, None, entree["unite"])
        variation_derniere = _variation(None, None, entree["unite"])
        fraicheur = _fraicheur(
            entree, points, instant, fenetres_proprietaire, cadences_proprietaire, len(futurs), maintenant_cle
        )
        etendue = None
    moyenne = _moyenne_mobile(points, fenetre_moyenne_mobile)
    resultat_xmr = _xmr(points, cadence)
    prevision = _prevision(points, cadence, horizon_prevision)
    couverture = {
        "lues": len(historique),
        "retenues": len(points),
        "hors_fenetre": hors_fenetre,
        "exclues_total": sum(comptes.values()),
        "futurs_ecartes": len(futurs),
        "limite_lecture": limite_lecture,
        "lecture_bornee": borne_atteinte,
        "anterieures_non_lues_possibles": futur_lu and borne_atteinte is True,
        "fenetre_pleine": len(points) == fenetre_observations,
        "premier_construit_le": points[0]["construit_le"] if points else None,
        "dernier_construit_le": points[-1]["construit_le"] if points else None,
        "etendue_s": etendue,
        "intervalles": cadence["intervalles"],
        "cadence": cadence["cadence"],
        "raison_cadence": cadence["raison"],
        "trous": "non_evaluable",
        "raison_trous": "aucune cadence attendue déclarée ; trou non prouvé",
        "fraicheur": fraicheur,
    }
    resultat = {
        "metric_id": entree["metric_id"],
        "nom": entree["nom"],
        "unite": entree["unite"],
        "proprietaire": entree["proprietaire"],
        "version_definition": entree["version_definition"],
        "version_catalogue": version_catalogue,
        "maintenant": instant.isoformat(),
        "fenetre": {
            "observations_demandees": fenetre_observations,
            "moyenne_mobile_demandee": fenetre_moyenne_mobile,
            "horizon_prevision": horizon_prevision,
        },
        "serie": serie,
        "exclusions": {**comptes, "exemples": exemples},
        "couverture": couverture,
        "variation": variation,
        "variation_derniere": variation_derniere,
        "moyenne_mobile": moyenne,
        "xmr": resultat_xmr,
        "prevision": prevision,
        "non_livre": dict(_NON_LIVRE),
        "limites": list(_LIMITES),
    }
    resultat["recu"] = _recu(
        entree=entree,
        version_catalogue=version_catalogue,
        maintenant=instant,
        fenetre_observations=fenetre_observations,
        fenetre_moyenne_mobile=fenetre_moyenne_mobile,
        horizon_prevision=horizon_prevision,
        serie=serie,
        variation=variation,
        moyenne=moyenne,
        xmr_resultat=resultat_xmr,
        prevision=prevision,
        futures_ecartees=len(futurs),
        exclusions=comptes,
        maintenant_cle=maintenant_cle,
    )
    return resultat


__all__ = [
    "FENETRE_MOYENNE_MOBILE_DEFAUT",
    "FENETRE_MOYENNE_MOBILE_MAX",
    "FENETRE_MOYENNE_MOBILE_MIN",
    "FENETRE_OBSERVATIONS_DEFAUT",
    "FENETRE_OBSERVATIONS_MAX",
    "FENETRE_OBSERVATIONS_MIN",
    "HISTORIQUE_MAX",
    "HORIZON_PREVISION_DEFAUT",
    "HORIZON_PREVISION_MAX",
    "HORIZON_PREVISION_MIN",
    "MIN_OBSERVATIONS_PREVISION",
    "MIN_OBSERVATIONS_XMR",
    "PRECISION_DECIMALE",
    "REJ_ENTREE_INVALIDE",
    "REJ_FENETRE_INVALIDE",
    "REJ_HISTORIQUE_INVALIDE",
    "REJ_HISTORIQUE_TROP_VOLUMINEUX",
    "REJ_HORIZON_INVALIDE",
    "REJ_LIMITE_LECTURE_INVALIDE",
    "REJ_MAINTENANT_INVALIDE",
    "REJ_MOYENNE_MOBILE_INVALIDE",
    "SCHEMA_RECU",
    "analyser",
    "valider_parametres",
    "verifier_recu",
]
