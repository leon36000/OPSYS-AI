"""Analytique et prévisions commerciales (DEFINITION-PRODUIT §7 M2.15) : pipeline, conversion, délai de cycle, valeur
pondérée et prévision PAR INTERVALLE, par la bibliothèque standard seulement.

Ce que ce module garantit :

- **Déterministe et rejouable.** Aucun flottant, aucune horloge : des entiers et des fractions exactes ; le bootstrap
  utilise `random.Random(graine)` (la même graine donne les mêmes tirages sur toute machine). Chaque calcul reçoit des
  ENTRÉES normalisées et des PARAMÈTRES déclarés, et rend un résultat en texte décimal : `moteurs_commerciaux.py` en
  fait un reçu `recu-calcul.v1` (le format du moteur de calcul de M5) que l'on peut rejouer à l'identique.
- **Honnête sur la taille d'échantillon.** Chaque mesure a un SEUIL D'ÉCHANTILLON déclaré (`SEUILS`) ; en dessous, le
  calcul REFUSE (`REJ-PREV-ECHANTILLON-INSUFFISANT`) et dit combien il en faut, ou rend la mesure comme « non
  calculable » avec l'effectif observé. Il ne devine pas, ne comble pas avec une moyenne d'ailleurs, n'arrondit pas un
  petit nombre en « tendance ». L'appelant peut RELEVER un seuil, jamais l'abaisser.
- **Des intervalles, pas un point.** Une prévision rend un intervalle (niveau 80 %, 90 % ou 95 %) obtenu par bootstrap
  des résidus à un pas (graine déclarée), avec le « centre » donné comme repère, jamais comme promesse. Une série
  constante (aucune variation observée) est refusée : un intervalle y serait un mensonge.
- **Pas de décision.** Ces chiffres informent ; ils ne changent aucun statut, n'écartent aucun lead, ne promettent
  rien à un client. La valeur pondérée porte une valeur DÉCLARÉE par le vendeur (`valeurs.py`), pas un prix de M3.

Méthodes de prévision : moyenne mobile (fenêtre w) ; lissage exponentiel simple (alpha déclaré) ; intervalle par
bootstrap des résidus à un pas (B tirages, avec remise, des écarts observés entre l'historique et sa prévision à un
pas), valeurs simulées bornées à zéro (un compte ne peut être négatif). Limite : un modèle de niveau sans tendance ni
saison ; les résidus sont supposés échangeables.

Module PUR : aucune entrée-sortie.
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

from . import horodatage as _horodatage
from . import segments
from .statuts import STATUTS
from .verdicts_commercial import construire_verdict

__all__ = [
    "METHODES",
    "NIVEAUX",
    "SEUILS",
    "analyser",
    "enregistrements",
    "prevoir",
    "serie_hebdomadaire",
    "valider_parametres",
]

SECONDES_SEMAINE = 7 * 86400
SECONDES_JOUR = 86400
# Seuils d'échantillon DÉCLARÉS (versionnés avec le moteur, dits dans chaque reçu). Relevables, jamais abaissables.
SEUILS: Mapping[str, int] = {
    "resolus_conversion": 20,  # leads résolus (convertis ou perdus) pour un taux de conversion
    "ingeres_qualification": 20,  # leads ingérés pour un taux de qualification
    "convertis_cycle": 10,  # leads convertis pour un délai de cycle
    "resolus_par_etape": 20,  # leads résolus passés par l'étape pour la probabilité qui pondère la valeur
    "periodes_serie": 12,  # semaines complètes d'historique pour une prévision
    "evenements_serie": 20,  # événements cumulés dans l'historique pour une prévision
}
METHODES = ("moyenne_mobile", "lissage_exponentiel")
NIVEAUX = (80, 90, 95)
HORIZON_MAX = 8
_RE_ALPHA = re.compile(r"^(?:[01]|0?\.[0-9]{1,3}|[01]\.[0-9]{1,3})$")
SERIE_MAX = 104
REPETITIONS = (200, 5000)
SERIES = ("leads_ingeres", "leads_qualifies", "leads_convertis", "leads_perdus")
_APRES_CONVERSION = ("converti", "cedule", "chantier", "facture", "paiement", "avis")
PRECISION = {
    "arithmetique": "entiers et fractions exactes (aucun flottant)",
    "affichage": "texte décimal, ROUND_HALF_EVEN",
    "bootstrap": "random.Random(graine), tirages avec remise",
}
AVERTISSEMENT_INFO = (
    "Information commerciale : elle ne change aucun statut, n'écarte aucun lead et ne promet rien à un client. À "
    "valider "
    "auprès d'un comptable (CPA) / professionnel qualifié avant tout usage comptable ou budgétaire."
)


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, construire_verdict(code, detail=detail)


def _texte(valeur: Fraction, chiffres: int = 4) -> str:
    decimal = Decimal(valeur.numerator) / Decimal(valeur.denominator)
    return format(decimal.quantize(Decimal(1).scaleb(-chiffres), rounding=ROUND_HALF_EVEN), "f")


def _cents_texte(valeur: Fraction) -> str:
    return _texte(valeur / 100, 2)


def _rang(taille: int, numerateur: int, denominateur: int) -> int:
    """Rang (1-indexé) du quantile `numerateur/denominateur` par la règle du rang le plus proche (plafond)."""
    return max(1, min(taille, -((-taille * numerateur) // denominateur)))


def _percentile(trie: Sequence[Fraction], numerateur: int, denominateur: int) -> Fraction:
    return trie[_rang(len(trie), numerateur, denominateur) - 1]


# ---------------------------------------------------------------------------------------------- enregistrements
def enregistrements(fiches: Mapping[str, Any], valeurs_declarees: Mapping[str, int]) -> list[dict[str, Any]]:
    """Un enregistrement ANONYME par lead : statut courant, instants (secondes UTC) d'ingestion, de première
    qualification, de première conversion et de perte, valeur déclarée. Aucun identifiant ni contact : c'est aussi
    l'entrée d'un reçu. L'ordre est celui de l'ingestion puis de l'identifiant (déterministe)."""
    sortie = []
    for lead_id, fiche in fiches.items():
        instants: dict[str, int | None] = {"qualifie": None, "converti": None, "perdu": None}
        for maillon in fiche.vue.lire():
            if maillon.get("type_entree") != "transition_statut":
                continue
            try:
                instant = int(segments.instant_utc(maillon["horodatage"]).timestamp())
            except (ValueError, TypeError, KeyError):
                continue
            statut = maillon.get("statut")
            cle = "converti" if statut in _APRES_CONVERSION else statut
            if cle in instants and (instants[cle] is None or instant < instants[cle]):
                instants[cle] = instant
        try:
            ingere = int(segments.instant_utc(fiche.ingere_le).timestamp())
        except (ValueError, TypeError):
            continue
        sortie.append(
            {
                "statut": fiche.statut,
                "ingere_s": ingere,
                "qualifie_s": instants["qualifie"],
                "converti_s": instants["converti"],
                "perdu_s": instants["perdu"],
                "valeur_cents": valeurs_declarees.get(lead_id),
                "_cle": (ingere, lead_id),
            }
        )
    sortie.sort(key=lambda r: r["_cle"])
    for r in sortie:
        del r["_cle"]
    return sortie


def serie_hebdomadaire(records: Sequence[Mapping[str, Any]], nom: str, maintenant_s: int) -> list[int]:
    """Les comptes par SEMAINE COMPLÈTE (blocs de 7 jours qui se terminent à `maintenant_s`, du plus ancien au plus
    récent) de l'événement `nom`. L'historique commence à la première ingestion : jamais de semaines d'avant
    l'existence du CRM, jamais la semaine en cours, au plus `SERIE_MAX` semaines."""
    cle = {
        "leads_ingeres": "ingere_s",
        "leads_qualifies": "qualifie_s",
        "leads_convertis": "converti_s",
        "leads_perdus": "perdu_s",
    }[nom]
    ingestions = [r["ingere_s"] for r in records]
    if not ingestions:
        return []
    blocs = min(SERIE_MAX, (maintenant_s - min(ingestions)) // SECONDES_SEMAINE)
    if blocs <= 0:
        return []
    comptes = [0] * blocs
    for r in records:
        instant = r[cle]
        if instant is None or instant > maintenant_s:
            continue
        age = (maintenant_s - instant) // SECONDES_SEMAINE
        if 0 <= age < blocs:
            comptes[blocs - 1 - age] += 1
    return comptes


# ---------------------------------------------------------------------------------------------- analytique
def _mesure_taux(numerateur: int, effectif: int, seuil: int, libelle: str) -> dict[str, Any]:
    if effectif < seuil:
        return {
            "valeur": None,
            "n": effectif,
            "seuil": seuil,
            "refus": f"échantillon insuffisant pour {libelle} : {effectif} observé(s), {seuil} exigés",
        }
    return {"valeur": _texte(Fraction(numerateur, effectif)), "n": effectif, "seuil": seuil, "succes": numerateur}


def _quantiles(valeurs_f: list[Fraction]) -> dict[str, str]:
    trie = sorted(valeurs_f)
    return {
        "p25": _texte(_percentile(trie, 25, 100), 2),
        "mediane": _texte(_percentile(trie, 50, 100), 2),
        "p75": _texte(_percentile(trie, 75, 100), 2),
        "moyenne": _texte(sum(trie, Fraction(0)) / len(trie), 2),
    }


def _probabilites_par_etape(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """P(conversion | étape) d'après les leads RÉSOLUS passés par l'étape : « nouveau » = tout lead résolu ; «
    qualifié »
    = ceux qui ont été qualifiés. Un effectif sous le seuil : probabilité absente (le motif est dit)."""
    sortie = {}
    for etape, filtre in (("nouveau", lambda r: True), ("qualifie", lambda r: r["qualifie_s"] is not None)):
        resolus = [r for r in records if filtre(r) and (r["converti_s"] is not None or r["perdu_s"] is not None)]
        convertis = sum(1 for r in resolus if r["converti_s"] is not None)
        sortie[etape] = _mesure_taux(
            convertis, len(resolus), SEUILS["resolus_par_etape"], f"la probabilité de conversion depuis l'étape {etape}"
        )
    return sortie


def _valeur_ponderee(
    records: Sequence[Mapping[str, Any]],
    probas: Mapping[str, Mapping[str, Any]],
    graine: int,
    repetitions: int,
    niveau: int,
) -> dict[str, Any]:
    ouverts = [r for r in records if r["statut"] in ("nouveau", "qualifie")]
    avec_valeur = [r for r in ouverts if r["valeur_cents"] is not None]
    sans_valeur = len(ouverts) - len(avec_valeur)
    resultat: dict[str, Any] = {
        "ouverts": len(ouverts),
        "sans_valeur_declaree": sans_valeur,
        "valeur_declaree_totale": _cents_texte(Fraction(sum(r["valeur_cents"] for r in avec_valeur))),
    }
    if not avec_valeur:
        resultat.update(valeur_ponderee=None, refus="non calculable : aucune valeur déclarée sur les leads ouverts")
        return resultat
    manquantes = sorted({r["statut"] for r in avec_valeur if probas[r["statut"]]["valeur"] is None})
    if manquantes:
        resultat.update(
            valeur_ponderee=None,
            refus=(
                f"non calculable : probabilité de conversion indisponible pour l'étape {manquantes} (échantillon "
                f"insuffisant : {', '.join(e + ' n=' + str(probas[e]['n']) for e in manquantes)})"
            ),
        )
        return resultat

    # Le point : Σ valeur × P(étape). L'incertitude : bootstrap des leads RÉSOLUS (probabilités ré-estimées à chaque
    # tirage).
    def ponderee(p_nouveau: Fraction, p_qualifie: Fraction) -> Fraction:
        return sum(
            (
                Fraction(r["valeur_cents"]) * (p_qualifie if r["statut"] == "qualifie" else p_nouveau)
                for r in avec_valeur
            ),
            Fraction(0),
        )

    p_n = Fraction(probas["nouveau"]["succes"], probas["nouveau"]["n"])
    p_q = (
        Fraction(probas["qualifie"]["succes"], probas["qualifie"]["n"]) if probas["qualifie"]["valeur"] else Fraction(0)
    )
    resolus = [r for r in records if r["converti_s"] is not None or r["perdu_s"] is not None]
    rng = random.Random(graine)
    tirages = []
    for _ in range(repetitions):
        echantillon = [resolus[rng.randrange(len(resolus))] for _ in range(len(resolus))]
        conv_n = sum(1 for r in echantillon if r["converti_s"] is not None)
        qualifies = [r for r in echantillon if r["qualifie_s"] is not None]
        conv_q = sum(1 for r in qualifies if r["converti_s"] is not None)
        pq = Fraction(conv_q, len(qualifies)) if qualifies else Fraction(0)
        tirages.append(ponderee(Fraction(conv_n, len(echantillon)), pq))
    tirages.sort()
    resultat.update(
        valeur_ponderee={
            "centre": _cents_texte(ponderee(p_n, p_q)),
            "intervalle": {
                "niveau": niveau,
                "bas": _cents_texte(_percentile(tirages, 100 - niveau, 200)),
                "haut": _cents_texte(_percentile(tirages, 100 + niveau, 200)),
            },
            "methode": f"Σ valeur déclarée × P(conversion | étape) ; intervalle par bootstrap des leads "
            f"résolus ({repetitions} tirages, graine {graine})",
        },
        unite="CAD",
    )
    return resultat


def valider_parametres_analyse(parametres: Any) -> tuple[dict[str, int] | None, dict[str, str] | None]:
    if not isinstance(parametres, Mapping) or set(parametres) != {"graine", "repetitions", "niveau"}:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", "paramètres : graine, repetitions, niveau")
    graine, repetitions, niveau = parametres["graine"], parametres["repetitions"], parametres["niveau"]
    if type(graine) is not int or not 0 <= graine <= 2**63 - 1:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", "graine : entier de 0 à 2^63-1")
    if type(repetitions) is not int or not REPETITIONS[0] <= repetitions <= REPETITIONS[1]:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"repetitions : entier de {REPETITIONS[0]} à {REPETITIONS[1]}")
    if type(niveau) is not int or niveau not in NIVEAUX:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"niveau : l'un de {list(NIVEAUX)}")
    return {"graine": graine, "repetitions": repetitions, "niveau": niveau}, None


def _enregistrements_valides(brut: Any) -> tuple[list[dict[str, Any]] | None, dict[str, str] | None]:
    if not isinstance(brut, list):
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", "leads : liste d'enregistrements attendue")
    cles = {"statut", "ingere_s", "qualifie_s", "converti_s", "perdu_s", "valeur_cents"}
    for i, r in enumerate(brut):
        if (
            not isinstance(r, Mapping)
            or set(r) != cles
            or r["statut"] not in STATUTS
            or type(r["ingere_s"]) is not int
            or any(r[c] is not None and type(r[c]) is not int for c in ("qualifie_s", "converti_s", "perdu_s"))
            or (r["valeur_cents"] is not None and (type(r["valeur_cents"]) is not int or r["valeur_cents"] <= 0))
        ):
            return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"leads[{i}] : enregistrement mal formé")
    return [dict(r) for r in brut], None


def analyser(entrees: Any, parametres: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """L'analytique du pipeline : `({methode, precision, parametres, entrees, resultat, avertissements}, None)`.

    `entrees` : `{"leads": [enregistrements anonymes de `enregistrements`]}` ; `parametres` : `{graine, repetitions,
    niveau}` (bootstrap de la valeur pondérée). Résultat : le pipeline par statut, l'entonnoir, les taux (avec leur
    effectif et leur seuil), le délai de cycle en jours, les probabilités par étape et la valeur pondérée avec son
    intervalle."""
    if not isinstance(entrees, Mapping) or set(entrees) != {"leads"}:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", "entrées : {leads}")
    leads, verdict = _enregistrements_valides(entrees["leads"])
    if verdict is not None:
        return None, verdict
    params, verdict = valider_parametres_analyse(parametres)
    if verdict is not None:
        return None, verdict
    par_statut = {s: sum(1 for r in leads if r["statut"] == s) for s in STATUTS}
    convertis = [r for r in leads if r["converti_s"] is not None]
    perdus = [r for r in leads if r["perdu_s"] is not None and r["converti_s"] is None]
    qualifies = [r for r in leads if r["qualifie_s"] is not None]
    resolus = len(convertis) + len(perdus)
    cycles = [
        Fraction(r["converti_s"] - r["ingere_s"], SECONDES_JOUR) for r in convertis if r["converti_s"] >= r["ingere_s"]
    ]
    probas = _probabilites_par_etape(leads)
    delai: dict[str, Any] = {"n": len(cycles), "seuil": SEUILS["convertis_cycle"], "unite": "jours"}
    if len(cycles) < SEUILS["convertis_cycle"]:
        delai.update(
            valeurs=None,
            refus=(
                f"échantillon insuffisant pour le délai de cycle : {len(cycles)} converti(s), "
                f"{SEUILS['convertis_cycle']} exigés"
            ),
        )
    else:
        delai["valeurs"] = _quantiles(cycles)
    resultat = {
        "pipeline": {
            "par_statut": par_statut,
            "ouverts": par_statut["nouveau"] + par_statut["qualifie"],
            "total": len(leads),
        },
        "entonnoir": {
            "ingeres": len(leads),
            "qualifies_un_jour": len(qualifies),
            "convertis_un_jour": len(convertis),
            "perdus": len(perdus),
            "resolus": resolus,
        },
        "taux_conversion_des_resolus": _mesure_taux(
            len(convertis), resolus, SEUILS["resolus_conversion"], "le taux de conversion"
        ),
        "taux_qualification": _mesure_taux(
            len(qualifies), len(leads), SEUILS["ingeres_qualification"], "le taux de qualification"
        ),
        "delai_de_cycle": delai,
        "probabilite_de_conversion_par_etape": probas,
        "valeur_ponderee": _valeur_ponderee(leads, probas, params["graine"], params["repetitions"], params["niveau"]),
        "seuils_declares": dict(SEUILS),
    }
    avertissements = [
        AVERTISSEMENT_INFO,
        "Les taux ne portent que sur les leads RÉSOLUS : un lead encore ouvert n'est ni gagné ni perdu, il n'est pas "
        "compté.",
        "La valeur pondérée utilise la valeur DÉCLARÉE par le vendeur (estimation commerciale), pas un prix de M3.",
    ]
    return {
        "methode": (
            "Comptages et rapports exacts sur des enregistrements anonymes ; délai de cycle = première conversion "
            "moins ingestion ; quantiles au rang le plus proche ; valeur pondérée = Σ valeur déclarée × P(conversion "
            "| étape) avec intervalle par bootstrap des leads résolus."
        ),
        "precision": dict(PRECISION),
        "parametres": params,
        "entrees": {"leads": leads},
        "resultat": resultat,
        "avertissements": avertissements,
    }, None


# ---------------------------------------------------------------------------------------------- prévision
def valider_parametres(parametres: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """Les paramètres d'une prévision, normalisés : `methode`, `fenetre` (moyenne mobile) ou `alpha` (lissage, texte
    décimal dans ]0 ; 1], 3 décimales au plus), `horizon`, `niveau`, `graine`, `repetitions`, et les minimums
    d'échantillon (`periodes_minimum`, `evenements_minimum`) qui ne peuvent QUE relever les seuils déclarés."""
    attendus = {
        "methode",
        "fenetre",
        "alpha",
        "horizon",
        "niveau",
        "graine",
        "repetitions",
        "periodes_minimum",
        "evenements_minimum",
    }
    if not isinstance(parametres, Mapping) or set(parametres) != attendus:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"paramètres exigés : {sorted(attendus)}")
    methode = parametres["methode"]
    if methode not in METHODES:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"methode : l'une de {list(METHODES)}")
    fenetre, alpha = parametres["fenetre"], parametres["alpha"]
    if methode == "moyenne_mobile":
        if type(fenetre) is not int or not 2 <= fenetre <= 12 or alpha is not None:
            return _refus("REJ-PREV-PARAMETRE-INVALIDE", "moyenne_mobile : fenetre entière de 2 à 12, alpha nul")
    else:
        if fenetre is not None or type(alpha) is not str:
            return _refus("REJ-PREV-PARAMETRE-INVALIDE", "lissage_exponentiel : alpha en texte décimal, fenetre nulle")
        if _RE_ALPHA.fullmatch(alpha) is None or not 0 < Fraction(Decimal(alpha)) <= 1:
            return _refus(
                "REJ-PREV-PARAMETRE-INVALIDE",
                "alpha : texte décimal simple (« 0.3 ») dans ]0 ; 1], trois décimales au plus",
            )
    horizon, niveau, graine, repetitions = (parametres[c] for c in ("horizon", "niveau", "graine", "repetitions"))
    if type(horizon) is not int or not 1 <= horizon <= HORIZON_MAX:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"horizon : entier de 1 à {HORIZON_MAX} périodes")
    if type(niveau) is not int or niveau not in NIVEAUX:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"niveau : l'un de {list(NIVEAUX)}")
    if type(graine) is not int or not 0 <= graine <= 2**63 - 1:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", "graine : entier de 0 à 2^63-1")
    if type(repetitions) is not int or not REPETITIONS[0] <= repetitions <= REPETITIONS[1]:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"repetitions : entier de {REPETITIONS[0]} à {REPETITIONS[1]}")
    for cle, plancher in (
        ("periodes_minimum", SEUILS["periodes_serie"]),
        ("evenements_minimum", SEUILS["evenements_serie"]),
    ):
        if type(parametres[cle]) is not int or parametres[cle] < plancher:
            return _refus(
                "REJ-PREV-PARAMETRE-INVALIDE",
                (f"{cle} : au moins {plancher} (le seuil déclaré se relève, il ne s'abaisse pas)"),
            )
    return dict(parametres), None


def prevoir(entrees: Any, parametres: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La prévision par intervalle d'une série hebdomadaire de comptes : `({methode, precision, parametres, entrees,
    resultat, avertissements}, None)` ou un refus (échantillon insuffisant, série constante, paramètres invalides).

    `entrees` : `{"serie": [comptes entiers ≥ 0], "unite": "semaine", "nom": <série>}`."""
    if (
        not isinstance(entrees, Mapping)
        or set(entrees) != {"serie", "unite", "nom"}
        or entrees["unite"] != "semaine"
        or entrees["nom"] not in SERIES
        or not isinstance(entrees["serie"], list)
        or not all(type(v) is int and 0 <= v <= 10**9 for v in entrees["serie"])
    ):
        return _refus(
            "REJ-PREV-PARAMETRE-INVALIDE", f"entrées : {{serie: comptes entiers, unite: semaine, nom: {list(SERIES)}}}"
        )
    serie: list[int] = list(entrees["serie"])
    params, verdict = valider_parametres(parametres)
    if verdict is not None:
        return None, verdict
    n, total = len(serie), sum(serie)
    if n < params["periodes_minimum"] or total < params["evenements_minimum"]:
        return _refus(
            "REJ-PREV-ECHANTILLON-INSUFFISANT",
            (
                f"{n} semaine(s) complète(s) et {total} événement(s) observés ; il en faut au moins "
                f"{params['periodes_minimum']} et {params['evenements_minimum']} pour prévoir (seuils déclarés). "
                f"Aucune "
                "prévision n'est donnée : attendre plus d'historique, ne rien estimer à la place."
            ),
        )
    if len(set(serie)) == 1:
        return _refus(
            "REJ-PREV-SERIE-DEGENEREE",
            "l'historique est constant : aucune variation à partir de laquelle bâtir un intervalle",
        )
    horizon = params["horizon"]
    if horizon > n // 3:
        return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"horizon : au plus le tiers de l'historique ({n // 3} périodes)")
    if params["methode"] == "moyenne_mobile":
        w = params["fenetre"]
        if w > n // 2:
            return _refus("REJ-PREV-PARAMETRE-INVALIDE", f"fenetre : au plus la moitié de l'historique ({n // 2})")
        ajustees = [(t, Fraction(sum(serie[t - w : t]), w)) for t in range(w, n)]
        niveau_final = Fraction(sum(serie[n - w :]), w)
    else:
        alpha = Fraction(Decimal(params["alpha"]))
        lisse = Fraction(serie[0])
        ajustees = []
        for t in range(1, n):
            ajustees.append((t, lisse))
            lisse = alpha * serie[t] + (1 - alpha) * lisse
        niveau_final = lisse
    residus = [serie[t] - prevu for t, prevu in ajustees]
    if len(residus) < 8:
        return _refus(
            "REJ-PREV-ECHANTILLON-INSUFFISANT",
            (f"{len(residus)} résidu(s) à un pas : au moins 8 exigés pour un intervalle par bootstrap"),
        )
    mae = sum((abs(r) for r in residus), Fraction(0)) / len(residus)
    rng = random.Random(params["graine"])
    totaux: list[Fraction] = []
    par_pas: list[list[Fraction]] = [[] for _ in range(horizon)]
    for _ in range(params["repetitions"]):
        somme = Fraction(0)
        for k in range(horizon):
            simule = max(Fraction(0), niveau_final + residus[rng.randrange(len(residus))])
            par_pas[k].append(simule)
            somme += simule
        totaux.append(somme)
    totaux.sort()
    niveau = params["niveau"]
    bas_num, haut_num = 100 - niveau, 100 + niveau
    resultat = {
        "serie": {"nom": entrees["nom"], "unite": "semaine", "periodes": n, "evenements": total},
        "prevision_totale": {
            "horizon_periodes": horizon,
            "centre": _texte(niveau_final * horizon, 2),
            "intervalle": {
                "niveau": niveau,
                "bas": _texte(_percentile(totaux, bas_num, 200), 2),
                "haut": _texte(_percentile(totaux, haut_num, 200), 2),
            },
        },
        "par_periode": [
            {
                "periode": k + 1,
                "centre": _texte(niveau_final, 2),
                "intervalle": {
                    "niveau": niveau,
                    "bas": _texte(_percentile(sorted(par_pas[k]), bas_num, 200), 2),
                    "haut": _texte(_percentile(sorted(par_pas[k]), haut_num, 200), 2),
                },
            }
            for k in range(horizon)
        ],
        "erreur_absolue_moyenne_un_pas": _texte(mae, 4),
        "niveau_courant": _texte(niveau_final, 4),
        "seuils_declares": {
            "periodes_minimum": params["periodes_minimum"],
            "evenements_minimum": params["evenements_minimum"],
        },
    }
    avertissements = [
        AVERTISSEMENT_INFO,
        "Le « centre » est un repère, pas une promesse : c'est l'intervalle qui porte l'incertitude.",
        *(
            [
                "Intervalle de largeur nulle : l'historique récent est entièrement nul ou sans variation ; ne pas le "
                "lire comme "
                "une certitude."
            ]
            if resultat["prevision_totale"]["intervalle"]["bas"] == resultat["prevision_totale"]["intervalle"]["haut"]
            else []
        ),
        "Modèle de niveau, sans tendance ni saison ; résidus supposés échangeables ; valeurs simulées bornées à zéro.",
        f"Historique de {n} semaine(s) complète(s) : un petit historique donne un intervalle trop étroit ou trop large "
        "sans qu'on puisse le savoir ; ne pas l'utiliser comme engagement.",
    ]
    return {
        "methode": (
            f"{params['methode']} "
            f"({'fenêtre ' + str(params['fenetre']) if params['fenetre'] else 'alpha ' + str(params['alpha'])}) ; "
            f"intervalle par bootstrap des résidus à un pas ({params['repetitions']} tirages, graine "
            f"{params['graine']})"
        ),
        "precision": dict(PRECISION),
        "parametres": params,
        "entrees": {"serie": serie, "unite": "semaine", "nom": entrees["nom"]},
        "resultat": resultat,
        "avertissements": avertissements,
    }, None


def instant_s(horodatage: str) -> int:
    """Les secondes UTC d'un horodatage ISO-8601 avec fuseau."""
    _horodatage.valider_horodatage(horodatage)
    return int(datetime.fromisoformat(horodatage).astimezone(UTC).timestamp())


__all__.append("instant_s")
__all__.append("valider_parametres_analyse")
