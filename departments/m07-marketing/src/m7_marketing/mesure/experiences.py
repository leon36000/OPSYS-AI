"""Conception et lecture de tests marketing (marche-arrêt, géographiques) avec REÇU DE CALCUL rejouable.

Les chiffres d'un plan de test (taille d'échantillon, puissance, durée) ne se calculent jamais « de tête » : ce sont
des moteurs déterministes, en `Decimal`, sans flottant, dont chaque appel rend un reçu `recu-calcul.v1` — le format
du moteur de calcul de M5, construit par le pont du socle (`opsys.recu_calcul_pont`) : le reçu d'un test se vérifie
avec l'outil de M5 (`m5_verifier_recu_calcul`) et se REJOUE ici (`rejouer`). Même patron que les moteurs commerciaux
de M2 : `moteur(entrees, parametres) -> (sortie, None) | (None, verdict)`.

Moteurs (version 1.0.0) :
- `taille_echantillon_deux_proportions` : n par groupe pour comparer deux proportions, n = (z_{1-α/2}·√(2·p̄·q̄) +
z_{1-β}·√(p1q1+p2q2))²
  / (p1-p2)², arrondi à l'entier SUPÉRIEUR ;
- `puissance_deux_proportions` : la puissance d'un test de taille donnée ;
- `duree_test_marche_arret` : semaines par bras d'un test marche/arrêt, à partir de la moyenne et de l'écart-type
HEBDOMADAIRES
  d'un historique de huit semaines au moins ; au-delà du plafond de faisabilité : « irréalisable », jamais un plan
  trompeur ;
- `plan_test_geographique` : paires de régions appariées par mesure de base, test/témoin tiré de la graine ; moins
de six paires :
  « INSUFFISANT » avec ce qu'il manque ;
- `analyse_resultat_test` : différence de deux proportions observées et son intervalle de Newcombe-Wilson.
Le hasard est une graine passée à un générateur déterministe écrit ici (SplitMix64) : jamais `random`.

PRÉENREGISTREMENT. Un plan (`enregistrer_plan`) fige le reçu de conception, l'hypothèse, la métrique primaire et les
dates AVANT le test. `analyser_resultat` n'affirme la lecture d'un effet du test QUE si un plan existe avec ce reçu,
enregistré avant le début, et que les données couvrent la période du plan ; sinon le résultat est `exploratoire` («
aucun design préenregistré : aucune causalité »). La langue de sortie dit « associé à » et « observé pendant le test
», jamais « causé par ».

Limites déclarées dans chaque reçu : approximation normale, indépendance des observations, taille d'effet supposée (pas
mesurée). Une série hebdomadaire autocorrélée ou saisonnière rend la durée marche-arrêt OPTIMISTE.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Context, Decimal, localcontext
from typing import Any

from opsys import recu_calcul_pont

from .. import journal_chaine
from . import statistiques as st
from .verdicts import construire_verdict, refus_outil

VERSION = "1.0.0"
DEPARTEMENT = "m07-marketing"
REGISTRE_PLANS = (DEPARTEMENT, "plans_tests_marketing")
TYPE_PLAN = "plan_test"
M64 = (1 << 64) - 1
N_MAX = 10_000_000
PAIRES_MIN = 6
SEMAINES_MIN = 8
SEMAINES_MAX = 156
PLAFOND_SEMAINES_MAX = 26
REGIONS_MAX = 100
METRIQUES = ("conversions", "appels", "rendez_vous", "soumissions_signees", "ventes", "leads_qualifies")
MOTEURS_DE_CONCEPTION = ("taille_echantillon_deux_proportions", "duree_test_marche_arret", "plan_test_geographique")
MENTION_PRECISION = {
    "arithmetique": "Decimal, 90 chiffres significatifs, aucun flottant",
    "arrondi": "ROUND_HALF_UP à 6 décimales en sortie ; effectifs et durées arrondis au SUPÉRIEUR",
}
AVERTISSEMENTS = [
    "Approximation normale : peu fiable pour de très petits effectifs ou des taux extrêmes.",
    "Observations supposées indépendantes : une série autocorrélée, saisonnière ou contaminée entre groupes rend "
    "le plan optimiste.",
    "La taille d'effet est une SUPPOSITION de l'appelant, pas une mesure : un effet réel plus petit exige un "
    "échantillon plus grand.",
    "Un test non préenregistré est exploratoire : aucune causalité n'est affirmée.",
]
_DEC = re.compile(r"^-?[0-9]{1,12}(?:\.[0-9]{1,6})?$")
_DEC_POS = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,6})?$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_PLAN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

Verdict = dict[str, str]
Sortie = tuple[dict[str, Any] | None, Verdict | None]


# --------------------------------------------------------------------------------------------- générateur déterministe
class SplitMix64:
    """Générateur SplitMix64 (Steele, Lea, Flood) : état de 64 bits, sortie de 64 bits, entièrement déterministe."""

    def __init__(self, graine: int) -> None:
        if type(graine) is not int or not 0 <= graine <= M64:
            raise ValueError("graine : entier de 0 à 2^64 - 1")
        self._etat = graine

    def suivant(self) -> int:
        self._etat = (self._etat + 0x9E3779B97F4A7C15) & M64
        z = self._etat
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)

    def bit(self) -> int:
        return self.suivant() & 1


# ------------------------------------------------------------------------------------------------------- validation
def _refus(code: str, detail: str) -> tuple[None, Verdict]:
    return None, construire_verdict(code, detail=detail)


def _decimal(brut: Any, motif: re.Pattern[str] = _DEC) -> Decimal | None:
    if type(brut) is not str or not motif.fullmatch(brut):
        return None
    return Decimal(brut)


def _txt(valeur: Decimal) -> str:
    return st.texte(valeur)


def _cles(obj: Any, permises: set[str], requises: set[str], nom: str):
    if not isinstance(obj, Mapping):
        return _refus("REJ-MESURE-ARGUMENT-INVALIDE", f"{nom} : objet attendu")
    if set(obj) - permises or requises - set(obj):
        return _refus(
            "REJ-MESURE-ARGUMENT-INVALIDE", f"{nom} : clés requises {sorted(requises)}, permises {sorted(permises)}"
        )
    return dict(obj), None


def _proportion(brut: Any, nom: str):
    d = _decimal(brut, _DEC_POS)
    if d is None or not Decimal(0) < d < Decimal(1) or d.as_tuple().exponent < -6:
        return _refus(
            "REJ-MESURE-TAUX-INVALIDE", f"{nom} : texte décimal strictement entre 0 et 1, 6 décimales au plus"
        )
    return d, None


def _alpha(brut: Any):
    d = _decimal(brut, _DEC_POS)
    if d is None or not Decimal("0.001") <= d <= Decimal("0.2") or d.as_tuple().exponent < -3:
        return _refus("REJ-MESURE-ALPHA-INVALIDE", "alpha : texte décimal de 0.001 à 0.2, 3 décimales au plus")
    return d, None


def _puissance(brut: Any):
    d = _decimal(brut, _DEC_POS)
    if d is None or not Decimal("0.5") <= d <= Decimal("0.99") or d.as_tuple().exponent < -3:
        return _refus("REJ-MESURE-PUISSANCE-INVALIDE", "puissance : texte décimal de 0.5 à 0.99, 3 décimales au plus")
    return d, None


def _graine(brut: Any):
    if type(brut) is not int or not 0 <= brut <= M64:
        return _refus("REJ-MESURE-GRAINE-INVALIDE", "graine : entier de 0 à 2^64 - 1")
    return brut, None


def _entier(brut: Any, nom: str, minimum: int, maximum: int, code: str = "REJ-MESURE-ARGUMENT-INVALIDE"):
    if type(brut) is not int or not minimum <= brut <= maximum:
        return _refus(code, f"{nom} : entier de {minimum} à {maximum}")
    return brut, None


def _plafond(brut: Any):
    return _entier(brut, "plafond_semaines", 2, PLAFOND_SEMAINES_MAX)


def _contexte() -> Context:
    return Context(prec=st.PRECISION)


def _plafonner(valeur: Decimal) -> int:
    return int(valeur.to_integral_value(rounding=ROUND_CEILING))


def _moyenne_ecart_type(valeurs: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    """Moyenne et écart-type d'ÉCHANTILLON (n - 1), exacts en Decimal."""
    with localcontext(_contexte()):
        n = Decimal(len(valeurs))
        moyenne = sum(valeurs, Decimal(0)) / n
        variance = sum(((v - moyenne) ** 2 for v in valeurs), Decimal(0)) / (n - 1)
        return moyenne, variance.sqrt()


def _liste_decimaux(brut: Any, nom: str, minimum: int, maximum: int, code: str, *, positifs: bool = True):
    if not isinstance(brut, list) or not minimum <= len(brut) <= maximum:
        return _refus(code, f"{nom} : liste de {minimum} à {maximum} valeurs")
    valeurs = []
    for v in brut:
        d = _decimal(v, _DEC_POS if positifs else _DEC)
        if d is None:
            return _refus(
                "REJ-MESURE-ARGUMENT-INVALIDE", f"{nom} : textes décimaux {'>= 0' if positifs else ''} attendus"
            )
        valeurs.append(d)
    return valeurs, None


# --------------------------------------------------------------------------------------------------------- moteurs
def _z(alpha: Decimal, puissance: Decimal) -> tuple[Decimal, Decimal]:
    with localcontext(_contexte()):
        return st.quantile(1 - alpha / 2), st.quantile(puissance)


def _lire_effet(effet: Any, p1: Decimal):
    cadre, erreur = _cles(effet, {"mode", "valeur"}, {"mode", "valeur"}, "effet")
    if erreur:
        return None, erreur
    valeur = _decimal(cadre["valeur"])
    if cadre["mode"] not in ("absolu", "relatif") or valeur is None or valeur == 0:
        return _refus("REJ-MESURE-EFFET-INVALIDE", "effet : {mode: absolu|relatif, valeur: texte décimal non nul}")
    with localcontext(_contexte()):
        p2 = p1 + valeur if cadre["mode"] == "absolu" else p1 * (1 + valeur)
    if not Decimal(0) < p2 < Decimal(1):
        return _refus("REJ-MESURE-EFFET-INVALIDE", "l'effet mène le second taux hors de ]0 ; 1[")
    return (cadre["mode"], valeur, p2), None


def _termes(p1: Decimal, p2: Decimal) -> tuple[Decimal, Decimal]:
    """(√(2·p̄·q̄), √(p1·q1 + p2·q2))"""
    with localcontext(_contexte()):
        pbar = (p1 + p2) / 2
        return (2 * pbar * (1 - pbar)).sqrt(), (p1 * (1 - p1) + p2 * (1 - p2)).sqrt()


def moteur_taille_echantillon(entrees: Any, parametres: Any) -> Sortie:
    e, erreur = _cles(entrees, {"p1", "effet"}, {"p1", "effet"}, "entrées")
    if erreur:
        return None, erreur
    p, erreur = _cles(parametres, {"alpha", "puissance"}, {"alpha", "puissance"}, "paramètres")
    if erreur:
        return None, erreur
    p1, erreur = _proportion(e["p1"], "p1")
    if erreur:
        return None, erreur
    alpha, erreur = _alpha(p["alpha"])
    if erreur:
        return None, erreur
    puiss, erreur = _puissance(p["puissance"])
    if erreur:
        return None, erreur
    lu, erreur = _lire_effet(e["effet"], p1)
    if erreur:
        return None, erreur
    mode, valeur, p2 = lu
    za, zb = _z(alpha, puiss)
    with localcontext(_contexte()):
        a, b = _termes(p1, p2)
        n_exact = (za * a + zb * b) ** 2 / (p1 - p2) ** 2
        n = _plafonner(n_exact)
        pbar = (p1 + p2) / 2
    if n > N_MAX:
        return _refus(
            "REJ-MESURE-EFFET-INVALIDE",
            f"taille requise irréaliste (plus de {N_MAX} par groupe) : effet trop petit pour être détecté",
        )
    return {
        "methode": "Comparaison bilatérale de deux proportions indépendantes par approximation normale : "
        "n = (z_{1-α/2}·√(2·p̄·q̄) + z_{1-β}·√(p1·q1 + p2·q2))² / (p1 - p2)², arrondi à l'entier supérieur.",
        "precision": dict(MENTION_PRECISION),
        "parametres": {"alpha": _txt(alpha), "puissance": _txt(puiss)},
        "entrees": {"p1": _txt(p1), "effet": {"mode": mode, "valeur": _txt(valeur)}},
        "resultat": {
            "p1": _txt(p1),
            "p2": _txt(p2),
            "p_moyen": _txt(pbar),
            "z_alpha": _txt(za),
            "z_puissance": _txt(zb),
            "n_exact": _txt(n_exact),
            "n_par_groupe": n,
            "n_total": 2 * n,
            "lecture": "Taille requise AVANT de lancer le test : en dessous, la puissance visée n'est pas "
            "atteinte et un effet réel de cette taille risque de passer inaperçu.",
        },
        "avertissements": list(AVERTISSEMENTS),
    }, None


def moteur_puissance(entrees: Any, parametres: Any) -> Sortie:
    e, erreur = _cles(entrees, {"n_par_groupe", "p1", "p2"}, {"n_par_groupe", "p1", "p2"}, "entrées")
    if erreur:
        return None, erreur
    p, erreur = _cles(parametres, {"alpha"}, {"alpha"}, "paramètres")
    if erreur:
        return None, erreur
    n, erreur = _entier(e["n_par_groupe"], "n_par_groupe", 2, 1_000_000_000)
    if erreur:
        return None, erreur
    p1, erreur = _proportion(e["p1"], "p1")
    if erreur:
        return None, erreur
    p2, erreur = _proportion(e["p2"], "p2")
    if erreur:
        return None, erreur
    if p1 == p2:
        return _refus("REJ-MESURE-EFFET-INVALIDE", "p1 et p2 identiques : aucune différence à détecter")
    alpha, erreur = _alpha(p["alpha"])
    if erreur:
        return None, erreur
    with localcontext(_contexte()):
        za = st.quantile(1 - alpha / 2)
        a, b = _termes(p1, p2)
        z = (abs(p1 - p2) * Decimal(n).sqrt() - za * a) / b
        puissance = st.phi(z)
    return {
        "methode": "Puissance d'un test bilatéral de deux proportions (approximation normale, queue opposée "
        "négligée) : "
        "Φ((|p1 - p2|·√n - z_{1-α/2}·√(2·p̄·q̄)) / √(p1·q1 + p2·q2)).",
        "precision": dict(MENTION_PRECISION),
        "parametres": {"alpha": _txt(alpha)},
        "entrees": {"n_par_groupe": n, "p1": _txt(p1), "p2": _txt(p2)},
        "resultat": {"puissance": _txt(puissance), "z_alpha": _txt(za), "n_par_groupe": n},
        "avertissements": list(AVERTISSEMENTS),
    }, None


def _lundi(brut: Any):
    if not isinstance(brut, str) or not _DATE.fullmatch(brut):
        return _refus("REJ-MESURE-PERIODE-INVALIDE", "debut : date AAAA-MM-JJ attendue")
    try:
        jour = date.fromisoformat(brut)
    except ValueError:
        return _refus("REJ-MESURE-PERIODE-INVALIDE", "debut : date civile attendue")
    if jour.weekday() != 0:
        return _refus(
            "REJ-MESURE-PERIODE-INVALIDE", "debut doit être un lundi (les semaines du test sont des lundis à dimanches)"
        )
    return jour, None


def moteur_marche_arret(entrees: Any, parametres: Any) -> Sortie:
    e, erreur = _cles(
        entrees,
        {"historique_hebdo", "effet_relatif", "debut"},
        {"historique_hebdo", "effet_relatif", "debut"},
        "entrées",
    )
    if erreur:
        return None, erreur
    p, erreur = _cles(
        parametres,
        {"alpha", "puissance", "graine", "plafond_semaines"},
        {"alpha", "puissance", "graine", "plafond_semaines"},
        "paramètres",
    )
    if erreur:
        return None, erreur
    historique, erreur = _liste_decimaux(
        e["historique_hebdo"], "historique_hebdo", SEMAINES_MIN, SEMAINES_MAX, "REJ-MESURE-HISTORIQUE-INSUFFISANT"
    )
    if erreur:
        return None, erreur
    delta = _decimal(e["effet_relatif"], _DEC_POS)
    if delta is None or not Decimal("0.001") <= delta <= Decimal(5):
        return _refus("REJ-MESURE-EFFET-INVALIDE", "effet_relatif : texte décimal de 0.001 à 5 (0.2 = 20 %)")
    debut, erreur = _lundi(e["debut"])
    if erreur:
        return None, erreur
    alpha, erreur = _alpha(p["alpha"])
    if erreur:
        return None, erreur
    puiss, erreur = _puissance(p["puissance"])
    if erreur:
        return None, erreur
    graine, erreur = _graine(p["graine"])
    if erreur:
        return None, erreur
    plafond, erreur = _plafond(p["plafond_semaines"])
    if erreur:
        return None, erreur
    mu, sigma = _moyenne_ecart_type(historique)
    if mu == 0 or sigma == 0:
        return _refus(
            "REJ-MESURE-SERIE-DEGENEREE",
            "historique constant ou de moyenne nulle : l'écart-type ne dit rien de la variabilité réelle",
        )
    za, zb = _z(alpha, puiss)
    with localcontext(_contexte()):
        n_formule = _plafonner(2 * (za + zb) ** 2 * sigma**2 / (delta * mu) ** 2)
    n = max(n_formule, 2)  # au moins deux paires : sans quoi l'ordre aléatoire ne rime à rien
    total = 2 * n
    resultat: dict[str, Any] = {
        "moyenne_hebdo": _txt(mu),
        "ecart_type_hebdo": _txt(sigma),
        "z_alpha": _txt(za),
        "z_puissance": _txt(zb),
        "n_formule": n_formule,
        "semaines_par_bras": n,
        "duree_totale_semaines": total,
        "plafond_semaines": plafond,
        "debut": debut.isoformat(),
    }
    if total > plafond:
        resultat.update(
            {
                "faisabilite": "irrealisable",
                "calendrier": [],
                "raison": f"{total} semaines nécessaires pour détecter cet effet, plafond de faisabilité {plafond} : "
                "viser un effet plus grand, un historique moins variable ou un autre type de test (géographique)",
            }
        )
    else:
        generateur = SplitMix64(graine)
        calendrier = []
        for paire in range(n):
            ordre = ("marche", "arret") if generateur.bit() == 0 else ("arret", "marche")
            for rang, bras in enumerate(ordre):
                semaine = 2 * paire + rang
                lundi = debut + timedelta(days=7 * semaine)
                calendrier.append(
                    {
                        "semaine": semaine + 1,
                        "debut": lundi.isoformat(),
                        "fin": (lundi + timedelta(days=6)).isoformat(),
                        "bras": bras,
                    }
                )
        resultat.update({"faisabilite": "realisable", "calendrier": calendrier, "raison": None})
    return {
        "methode": "Comparaison de deux moyennes hebdomadaires (marche contre arrêt) : n = 2·(z_{1-α/2} + "
        "z_{1-β})²·σ² / "
        "(δ·μ)² semaines par bras, μ et σ tirés de l'historique ; chaque paire de semaines consécutives "
        "contient "
        "une semaine « marche » et une « arrêt », l'ordre venant de la graine (SplitMix64).",
        "precision": dict(MENTION_PRECISION),
        "parametres": {"alpha": _txt(alpha), "puissance": _txt(puiss), "graine": graine, "plafond_semaines": plafond},
        "entrees": {
            "historique_hebdo": [_txt(v) for v in historique],
            "effet_relatif": _txt(delta),
            "debut": debut.isoformat(),
        },
        "resultat": resultat,
        "avertissements": [
            *AVERTISSEMENTS,
            "Un effet qui se prolonge après l'arrêt (mémoire de marque) fausse la comparaison marche/arrêt.",
        ],
    }, None


def moteur_geographique(entrees: Any, parametres: Any) -> Sortie:
    e, erreur = _cles(
        entrees, {"regions", "effet_relatif", "ecarts_relatifs_apparies"}, {"regions", "effet_relatif"}, "entrées"
    )
    if erreur:
        return None, erreur
    p, erreur = _cles(parametres, {"alpha", "puissance", "graine"}, {"alpha", "puissance", "graine"}, "paramètres")
    if erreur:
        return None, erreur
    brutes = e["regions"]
    if not isinstance(brutes, list) or not 2 <= len(brutes) <= REGIONS_MAX:
        return _refus("REJ-MESURE-REGIONS-INVALIDES", f"regions : liste de 2 à {REGIONS_MAX} régions")
    regions, vus = [], set()
    for r in brutes:
        c, erreur = _cles(r, {"id", "mesure_base"}, {"id", "mesure_base"}, "région")
        if erreur:
            return _refus("REJ-MESURE-REGIONS-INVALIDES", erreur["detail"])
        mesure = _decimal(c["mesure_base"], _DEC_POS)
        if (
            not isinstance(c["id"], str)
            or not _SLUG.fullmatch(c["id"])
            or c["id"] in vus
            or mesure is None
            or mesure <= 0
        ):
            return _refus(
                "REJ-MESURE-REGIONS-INVALIDES",
                "région : id en minuscules unique et mesure_base (texte décimal > 0) obligatoires",
            )
        vus.add(c["id"])
        regions.append((c["id"], mesure))
    delta = _decimal(e["effet_relatif"], _DEC_POS)
    if delta is None or not Decimal("0.001") <= delta <= Decimal(5):
        return _refus("REJ-MESURE-EFFET-INVALIDE", "effet_relatif : texte décimal de 0.001 à 5")
    ecarts = None
    if e.get("ecarts_relatifs_apparies") is not None:
        ecarts, erreur = _liste_decimaux(
            e["ecarts_relatifs_apparies"],
            "ecarts_relatifs_apparies",
            4,
            200,
            "REJ-MESURE-HISTORIQUE-INSUFFISANT",
            positifs=False,
        )
        if erreur:
            return None, erreur
    alpha, erreur = _alpha(p["alpha"])
    if erreur:
        return None, erreur
    puiss, erreur = _puissance(p["puissance"])
    if erreur:
        return None, erreur
    graine, erreur = _graine(p["graine"])
    if erreur:
        return None, erreur
    ordonnees = sorted(regions, key=lambda r: (-r[1], r[0]))
    nb_paires = len(ordonnees) // 2
    base = {
        "regions": [{"id": i, "mesure_base": _txt(m)} for i, m in sorted(regions)],
        "effet_relatif": _txt(delta),
    }
    if ecarts is not None:
        base["ecarts_relatifs_apparies"] = [_txt(v) for v in ecarts]
    entrees_norm = base
    params = {"alpha": _txt(alpha), "puissance": _txt(puiss), "graine": graine}
    methode = (
        "Appariement des régions par mesure de base voisine (tri décroissant, deux à deux), affectation "
        "test/témoin "
        "dans chaque paire par la graine (SplitMix64) ; puissance approchée : Φ(δ·√paires / σ_d - "
        "z_{1-α/2}) sur "
        "l'écart-type σ_d des écarts relatifs appariés fournis."
    )
    if nb_paires < PAIRES_MIN:
        return {
            "methode": methode,
            "precision": dict(MENTION_PRECISION),
            "parametres": params,
            "entrees": entrees_norm,
            "resultat": {
                "statut": "INSUFFISANT",
                "paires_disponibles": nb_paires,
                "paires_minimales": PAIRES_MIN,
                "regions_minimales": 2 * PAIRES_MIN,
                "regions_a_ajouter": 2 * PAIRES_MIN - len(regions),
                "paires": [],
                "regions_exclues": [],
                "puissance_approx": None,
                "raison": f"{nb_paires} paire(s) de régions : il en faut au moins {PAIRES_MIN} "
                f"({2 * PAIRES_MIN} régions) "
                "pour qu'un test géographique puisse conclure. Aucune affectation n'est proposée.",
            },
            "avertissements": list(AVERTISSEMENTS),
        }, None
    generateur = SplitMix64(graine)
    paires = []
    for rang in range(nb_paires):
        (id_a, m_a), (id_b, m_b) = ordonnees[2 * rang], ordonnees[2 * rang + 1]
        test, temoin = ((id_a, m_a), (id_b, m_b)) if generateur.bit() == 0 else ((id_b, m_b), (id_a, m_a))
        with localcontext(_contexte()):
            ecart = abs(m_a - m_b) / max(m_a, m_b)
        paires.append(
            {
                "rang": rang + 1,
                "test": test[0],
                "temoin": temoin[0],
                "mesure_base_test": _txt(test[1]),
                "mesure_base_temoin": _txt(temoin[1]),
                "ecart_base_relatif": _txt(ecart),
            }
        )
    exclues = [i for i, _ in ordonnees[2 * nb_paires :]]
    resultat: dict[str, Any] = {
        "statut": "PLAN",
        "paires_disponibles": nb_paires,
        "paires_minimales": PAIRES_MIN,
        "paires": paires,
        "regions_exclues": exclues,
        "raison": None,
    }
    if ecarts is None:
        resultat.update(
            {
                "puissance_approx": None,
                "paires_requises": None,
                "suffisant": None,
                "lecture_puissance": "inconnue : aucun écart relatif apparié fourni, aucune variabilité inventée",
            }
        )
    else:
        _, sigma_d = _moyenne_ecart_type(ecarts)
        if sigma_d == 0:
            return _refus("REJ-MESURE-SERIE-DEGENEREE", "écarts relatifs appariés constants : variabilité nulle")
        za, zb = _z(alpha, puiss)
        with localcontext(_contexte()):
            requises = _plafonner((za + zb) ** 2 * sigma_d**2 / delta**2)
            puissance = st.phi(delta * Decimal(nb_paires).sqrt() / sigma_d - za)
        resultat.update(
            {
                "ecart_type_apparie": _txt(sigma_d),
                "puissance_approx": _txt(puissance),
                "paires_requises": requises,
                "suffisant": nb_paires >= requises,
                "lecture_puissance": "approchée par la loi normale : optimiste avec peu de paires",
            }
        )
    return {
        "methode": methode,
        "precision": dict(MENTION_PRECISION),
        "parametres": params,
        "entrees": entrees_norm,
        "resultat": resultat,
        "avertissements": [
            *AVERTISSEMENTS,
            "Des régions voisines peuvent se contaminer (déplacements, médias communs).",
        ],
    }, None


def _groupe(brut: Any, nom: str):
    c, erreur = _cles(brut, {"k", "n"}, {"k", "n"}, nom)
    if erreur:
        return None, erreur
    entiers = type(c["n"]) is int and type(c["k"]) is int
    if not entiers or not 1 <= c["n"] <= 1_000_000_000 or not 0 <= c["k"] <= c["n"]:
        return _refus("REJ-MESURE-ECHANTILLON-INVALIDE", f"{nom} : entiers 1 <= n <= 10^9 et 0 <= k <= n")
    return (c["k"], c["n"]), None


def moteur_analyse(entrees: Any, parametres: Any) -> Sortie:
    e, erreur = _cles(entrees, {"test", "temoin"}, {"test", "temoin"}, "entrées")
    if erreur:
        return None, erreur
    p, erreur = _cles(parametres, {"niveau"}, {"niveau"}, "paramètres")
    if erreur:
        return None, erreur
    test, erreur = _groupe(e["test"], "test")
    if erreur:
        return None, erreur
    temoin, erreur = _groupe(e["temoin"], "temoin")
    if erreur:
        return None, erreur
    niveau = _decimal(p["niveau"], _DEC_POS)
    if niveau not in st.NIVEAUX_PERMIS:
        return _refus("REJ-MESURE-ARGUMENT-INVALIDE", f"niveau : un de {[str(n) for n in st.NIVEAUX_PERMIS]}")
    difference, bas, haut = st.ecart_proportions(test[0], test[1], temoin[0], temoin[1], niveau)
    with localcontext(_contexte()):
        taux_test, taux_temoin = Decimal(test[0]) / test[1], Decimal(temoin[0]) / temoin[1]
    inclut_zero = bas <= 0 <= haut
    conclusion = (
        "aucune_difference_detectee"
        if inclut_zero
        else ("difference_observee_test_superieur" if difference > 0 else "difference_observee_test_inferieur")
    )
    return {
        "methode": "Différence de deux proportions observées (test - témoin) et intervalle hybride de Newcombe-Wilson.",
        "precision": dict(MENTION_PRECISION),
        "parametres": {"niveau": _txt(niveau)},
        "entrees": {"test": {"k": test[0], "n": test[1]}, "temoin": {"k": temoin[0], "n": temoin[1]}},
        "resultat": {
            "taux_test": _txt(taux_test),
            "taux_temoin": _txt(taux_temoin),
            "difference": _txt(difference),
            "borne_basse": _txt(bas),
            "borne_haute": _txt(haut),
            "niveau": _txt(niveau),
            "conclusion": conclusion,
            "lecture": "compatible avec aucune différence" if inclut_zero else "différence observée dans ce test",
        },
        "avertissements": list(AVERTISSEMENTS),
    }, None


MOTEURS: dict[tuple[str, str], Callable[[Any, Any], Sortie]] = {
    ("taille_echantillon_deux_proportions", VERSION): moteur_taille_echantillon,
    ("puissance_deux_proportions", VERSION): moteur_puissance,
    ("duree_test_marche_arret", VERSION): moteur_marche_arret,
    ("plan_test_geographique", VERSION): moteur_geographique,
    ("analyse_resultat_test", VERSION): moteur_analyse,
}


def produire(moteur: str, version: str, entrees: Any, parametres: Any) -> Sortie:
    """`(reçu complet, None)` ou `(None, verdict)` : le moteur calcule, le pont construit le reçu `recu-calcul.v1`."""
    fonction = MOTEURS.get((moteur, version))
    if fonction is None:
        return _refus("REJ-MESURE-MOTEUR-INCONNU", f"moteur {moteur!r} version {version!r} inconnu")
    sortie, verdict = fonction(entrees, parametres)
    if verdict is not None:
        return None, verdict
    return recu_calcul_pont.construire(
        moteur=moteur,
        version_moteur=version,
        methode=sortie["methode"],
        precision=sortie["precision"],
        parametres=sortie["parametres"],
        entrees=sortie["entrees"],
        resultat=sortie["resultat"],
        avertissements=sortie["avertissements"],
    ), None


def rejouer(recu: Any) -> tuple[dict[str, Any] | None, Verdict | None]:
    """Refait le calcul d'un reçu COMPLET et compare les empreintes. Un reçu retouché, compact ou d'un moteur inconnu
    est refusé ; un reçu intact rend `{"identique": ...}`."""
    valide, raison = recu_calcul_pont.verifier(recu)
    if not valide:
        return _refus("REJ-MESURE-RECU-INVALIDE", raison)
    if "entrees" not in recu:
        return _refus(
            "REJ-MESURE-RECU-INVALIDE",
            "reçu compact (sans entrées) : son empreinte est vérifiée, mais il ne se rejoue qu'avec ses entrées",
        )
    cle = (recu["moteur"], recu["version_moteur"])
    if cle not in MOTEURS:
        return _refus("REJ-MESURE-RECU-INVALIDE", f"moteur {cle[0]!r} version {cle[1]!r} : non rejouable par M7")
    refait, verdict = produire(cle[0], cle[1], recu["entrees"], recu["parametres"] or None)
    if verdict is not None:
        return None, verdict
    return {
        "identique": refait["empreinte"] == recu["empreinte"],
        "moteur": cle[0],
        "version_moteur": cle[1],
        "empreinte_recue": recu["empreinte"],
        "empreinte_recalculee": refait["empreinte"],
    }, None


# ------------------------------------------------------------------------------------------------ préenregistrement
def _instant(maintenant: datetime) -> str:
    return maintenant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def charger_plans(journal: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Les plans enregistrés par identifiant, chaîne vérifiée (une altération est une ERREUR)."""
    if journal_chaine.verifier(journal):
        raise ValueError("REJ-MESURE-JOURNAL-ALTERE : la chaîne de hachage du registre des plans ne correspond plus")
    plans = {}
    for m in journal:
        if m["type"] != TYPE_PLAN:
            raise ValueError("REJ-MESURE-JOURNAL-ALTERE : maillon inattendu dans le registre des plans")
        plans[m["plan_id"]] = {k: v for k, v in m.items() if k not in journal_chaine.CLES_RESERVEES}
    return plans


def _n_prevu(recu: Mapping[str, Any]) -> tuple[int | None, str | None]:
    resultat = recu.get("resultat", {})
    if recu["moteur"] == "taille_echantillon_deux_proportions":
        return resultat.get("n_par_groupe"), "observations_par_groupe"
    if recu["moteur"] == "duree_test_marche_arret":
        return resultat.get("semaines_par_bras"), "semaines_par_bras"
    return resultat.get("paires_disponibles"), "paires"


def enregistrer_plan(
    journal: Any,
    plan_id: Any,
    recu: Any,
    hypothese: Any,
    metrique_primaire: Any,
    debut: Any,
    fin: Any,
    par: str,
    maintenant: datetime,
) -> dict[str, Any]:
    """Préenregistre un plan : fige le reçu de conception, l'hypothèse, la métrique primaire et les dates."""

    def refus(detail: str, code: str = "REJ-MESURE-PLAN-INVALIDE") -> dict[str, Any]:
        return refus_outil(construire_verdict(code, detail=detail))

    if not isinstance(plan_id, str) or not _PLAN_ID.fullmatch(plan_id):
        return refus("plan_id invalide (80 caractères, lettres, chiffres, . _ : -)")
    valide, raison = recu_calcul_pont.verifier(recu)
    if not valide:
        return refus(f"reçu de conception invalide : {raison}", "REJ-MESURE-RECU-INVALIDE")
    if recu["moteur"] not in MOTEURS_DE_CONCEPTION or (recu["moteur"], recu["version_moteur"]) not in MOTEURS:
        return refus(f"le reçu doit venir d'un moteur de conception parmi {list(MOTEURS_DE_CONCEPTION)}")
    resultat = recu["resultat"]
    if resultat.get("faisabilite") == "irrealisable" or resultat.get("statut") == "INSUFFISANT":
        return refus(
            "conception irréalisable ou insuffisante : aucun plan préenregistré sur un test qui ne peut pas conclure"
        )
    if (
        not isinstance(hypothese, str)
        or not 10 <= len(hypothese.strip()) <= 300
        or re.search(r"[\x00-\x1f\x7f-\x9f]", hypothese)
    ):
        return refus("hypothese : texte de 10 à 300 caractères, sans caractère de contrôle")
    if metrique_primaire not in METRIQUES:
        return refus(f"metrique_primaire : une de {list(METRIQUES)}")
    try:
        jour_debut, jour_fin = date.fromisoformat(debut), date.fromisoformat(fin)
    except (TypeError, ValueError):
        return refus("debut et fin : dates AAAA-MM-JJ", "REJ-MESURE-PERIODE-INVALIDE")
    forme = _DATE.fullmatch(debut) and _DATE.fullmatch(fin)
    if not forme or jour_debut > jour_fin or (jour_fin - jour_debut).days > 366:
        return refus("période inversée ou de plus d'un an", "REJ-MESURE-PERIODE-INVALIDE")
    if maintenant.tzinfo is None:
        raise ValueError("horloge sans fuseau")
    n_prevu, unite = _n_prevu(recu)
    enregistre_le = _instant(maintenant)
    nouveau = {
        "plan_id": plan_id,
        "moteur": recu["moteur"],
        "version_moteur": recu["version_moteur"],
        "empreinte_recu": recu["empreinte"],
        "hypothese": hypothese.strip(),
        "metrique_primaire": metrique_primaire,
        "debut": debut,
        "fin": fin,
        "n_prevu": n_prevu,
        "unite_n": unite,
    }
    try:
        existants = charger_plans(journal)
    except ValueError as exc:
        return refus(str(exc).split(" : ", 1)[1], "REJ-MESURE-JOURNAL-ALTERE")
    deja = existants.get(plan_id)
    if deja is not None:
        meme = {k: deja[k] for k in nouveau} == nouveau
        if meme:
            return {
                "accepte": True,
                "plan_id": plan_id,
                "deja_enregistre": True,
                "enregistre_le": deja["enregistre_le"],
                "tardif": deja["tardif"],
            }
        return refus(
            "ce plan_id désigne déjà un plan au contenu différent : un plan préenregistré ne se modifie pas",
            "REJ-MESURE-PLAN-EXISTANT",
        )
    tardif = maintenant.astimezone(UTC).date() >= jour_debut
    journal_chaine.ajouter(
        journal, TYPE_PLAN, {**nouveau, "enregistre_le": enregistre_le, "tardif": tardif, "par": par}, enregistre_le
    )
    avertissement = (
        "Plan enregistré le jour du début ou après : il ne comptera pas comme préenregistré." if tardif else None
    )
    return {
        "accepte": True,
        "plan_id": plan_id,
        "deja_enregistre": False,
        "enregistre_le": enregistre_le,
        "tardif": tardif,
        "avertissement": avertissement,
    }


CAUSALITE_NON_ETABLIE = (
    "Aucun design préenregistré : aucune causalité. La différence observée est associée à la "
    "période "
    "étudiée ; elle n'est pas expliquée par l'intervention."
)


def analyser_resultat(
    journal_plans: Sequence[Any], entrees: Any, niveau: Any = "0.95", plan_id: Any = None, periode_donnees: Any = None
) -> dict[str, Any]:
    """Analyse un résultat de test (k/n du test et du témoin) et dit s'il peut être LU comme un effet du test.

    `preenregistre` seulement si le plan existe avec son reçu, a été enregistré AVANT le début, et que les données
    couvrent la
    période du plan ; sinon `exploratoire` avec les raisons."""
    recu, verdict = produire("analyse_resultat_test", VERSION, entrees, {"niveau": niveau})
    if verdict is not None:
        return refus_outil(verdict)
    resultat = recu["resultat"]
    raisons: list[str] = []
    plan: dict[str, Any] | None = None
    if plan_id is None:
        raisons.append("aucun design préenregistré : aucune causalité")
    else:
        try:
            plans = charger_plans(journal_plans)
        except ValueError as exc:
            return refus_outil(construire_verdict("REJ-MESURE-JOURNAL-ALTERE", detail=str(exc).split(" : ", 1)[1]))
        plan = plans.get(plan_id) if isinstance(plan_id, str) else None
        if plan is None:
            return refus_outil(construire_verdict("REJ-MESURE-PLAN-INCONNU", detail="plan_id absent du registre"))
        debut_plan = datetime.fromisoformat(plan["debut"] + "T00:00:00+00:00")
        # l'INSTANT d'enregistrement fait foi (le drapeau `tardif` n'en est que le résumé affiché)
        if datetime.fromisoformat(plan["enregistre_le"].replace("Z", "+00:00")) >= debut_plan:
            raisons.append("plan enregistré après le début du test : il n'est pas préenregistré")
        if (
            not isinstance(periode_donnees, Mapping)
            or set(periode_donnees) != {"debut", "fin"}
            or periode_donnees["debut"] != plan["debut"]
            or periode_donnees["fin"] != plan["fin"]
        ):
            raisons.append("la période des données n'est pas celle du plan")
    n_min = min(entrees["test"]["n"], entrees["temoin"]["n"])
    conforme = None
    if plan is not None and plan["unite_n"] == "observations_par_groupe" and plan["n_prevu"] is not None:
        conforme = n_min >= plan["n_prevu"]
    statut = "preenregistre" if plan is not None and not raisons else "exploratoire"
    if statut == "exploratoire":
        lecture = f"Résultat exploratoire : {'; '.join(raisons)}. " + CAUSALITE_NON_ETABLIE
    elif resultat["conclusion"] == "aucune_difference_detectee":
        lecture = (
            "Selon le design préenregistré, la différence observée pendant le test est compatible avec aucune "
            "différence entre test et témoin."
        )
    else:
        lecture = (
            "Selon le design préenregistré, la différence observée pendant le test est associée au groupe "
            "test ; "
            "elle est compatible avec un effet du test, sous les hypothèses du plan (observations "
            "indépendantes, "
            "aucune contamination entre groupes), à valider."
        )
    if conforme is False:
        lecture += " L'échantillon est inférieur à celui du plan : le test est sous-dimensionné."
    return {
        "accepte": True,
        "statut": statut,
        "raisons": raisons,
        "lecture": lecture,
        "recu": recu,
        "plan": None
        if plan is None
        else {
            k: plan[k]
            for k in (
                "plan_id",
                "empreinte_recu",
                "metrique_primaire",
                "debut",
                "fin",
                "enregistre_le",
                "n_prevu",
                "unite_n",
            )
        },
        "echantillon_conforme_au_plan": conforme,
    }


__all__ = [
    "AVERTISSEMENTS",
    "CAUSALITE_NON_ETABLIE",
    "METRIQUES",
    "MOTEURS",
    "PAIRES_MIN",
    "REGISTRE_PLANS",
    "SplitMix64",
    "VERSION",
    "analyser_resultat",
    "charger_plans",
    "enregistrer_plan",
    "produire",
    "rejouer",
]
