"""Score de lead par règles explicables (PLAN T4.4, `docs/departements/M1-canaux.md` §9).

Le code calcule, le modèle ne note jamais : trois critères, chacun une valeur entre 0 et 1 tirée de ce que la
conversation établit, pondérés par des POIDS que le propriétaire écrit dans son profil d'entreprise
(`poids_score_lead`, lu par `opsys.taxonomie`). Aucun poids n'est dans ce code.

| Critère      | Valeur                                                                                         |
|--------------|------------------------------------------------------------------------------------------------|
| `urgence`    | 1 si un message de la conversation déclare une urgence explicite (jamais inférée du ton), sinon 0 |
| `completude` | éléments établis ÷ éléments attendus : service, ville, contact, et les questions du service    |
| `zone`       | 1 si une ville de la zone desservie est reconnue, sinon 0                                      |

`score = 100 × Σ (poids × valeur) ÷ Σ poids`, en arithmétique EXACTE (fractions), arrondi à l'entier, demi vers le
haut. Chaque critère rend ses points (sur 100) et une phrase qui dit ce qui a été constaté : le score est toujours
explicable. Sans poids, il n'y a PAS de score : le verdict dit « poids à configurer », jamais un score par défaut.

Le score reste au registre de M1 (`suivi_conversation`) : le passer à M2 exige un `LeadQualifie` v3 (P5), hors tâche.

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from opsys import taxonomie

STATUT_CALCULE = "calcule"
STATUT_POIDS_A_CONFIGURER = "poids_a_configurer"
REGLE = (
    "score = 100 × Σ (poids × valeur) ÷ Σ poids, calculé exactement puis arrondi à l'entier (demi vers le haut) ; "
    "les points de chaque critère sont arrondis au centième"
)


def _demi_vers_le_haut(valeur: Fraction) -> int:
    """La partie entière de `valeur + 1/2` : l'arrondi demi vers le haut d'une valeur positive, sans nombre flottant."""
    return (2 * valeur.numerator + valeur.denominator) // (2 * valeur.denominator)


def _points(valeur: Fraction) -> str:
    """Des points au centième, demi vers le haut, en texte (`"37.50"`)."""
    centiemes = _demi_vers_le_haut(valeur * 100)
    return f"{centiemes // 100}.{centiemes % 100:02d}"


def sans_poids(verdict: dict[str, str]) -> dict[str, Any]:
    """Le score d'une conversation dont le profil n'a pas (ou pas de valides) poids : aucun score, et pourquoi."""
    statut = (
        STATUT_POIDS_A_CONFIGURER
        if verdict["code"] == taxonomie.VERDICT_POIDS_SCORE_NON_CONFIGURES
        else "profil_invalide"
    )
    return {"statut": statut, "verdict": verdict}


def calculer(
    *, urgence: bool, zone: bool, elements_etablis: int, elements_attendus: int, poids: Mapping[str, int]
) -> dict[str, Any]:
    """Le score, critère par critère.

    `elements_etablis` sur `elements_attendus` : les champs du lead (service, ville, contact) et les questions de texte
    du service que la conversation établit, sur tous ceux que le lead et le service demandent.
    `poids` : `taxonomie.charger_poids_score_lead()`, un entier par critère de `taxonomie.CRITERES_SCORE_LEAD`.
    """
    if not 0 <= elements_etablis <= elements_attendus or elements_attendus < 1:
        raise ValueError(f"éléments incohérents : {elements_etablis} établis sur {elements_attendus} attendus")
    total_poids = sum(poids[critere] for critere in taxonomie.CRITERES_SCORE_LEAD)
    if total_poids < 1:
        raise ValueError("au moins un poids doit être positif")
    valeurs = {
        "urgence": Fraction(int(urgence)),
        "completude": Fraction(elements_etablis, elements_attendus),
        "zone": Fraction(int(zone)),
    }
    constats = {
        "urgence": (
            "urgence explicite déclarée dans la conversation" if urgence
            else "aucune urgence explicite déclarée (jamais inférée du ton)"
        ),
        "completude": (
            f"{elements_etablis} éléments établis sur {elements_attendus} (champs du lead et questions du service)"
        ),
        "zone": (
            "une ville de la zone desservie est reconnue" if zone
            else "aucune ville de la zone desservie n'est reconnue"
        ),
    }
    criteres = []
    total = Fraction(0)
    for critere in taxonomie.CRITERES_SCORE_LEAD:
        points = Fraction(100 * poids[critere], total_poids) * valeurs[critere]
        total += points
        criteres.append({
            "critere": critere, "poids": poids[critere], "valeur": str(valeurs[critere]),
            "points": _points(points), "constat": constats[critere],
        })
    return {
        "statut": STATUT_CALCULE, "score": _demi_vers_le_haut(total), "sur": 100, "criteres": criteres, "regle": REGLE,
    }
