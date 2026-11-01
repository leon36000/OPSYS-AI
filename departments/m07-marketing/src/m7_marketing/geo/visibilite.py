"""Visibilité dans les réponses d'IA : taux de mention et part de citations, avec leur incertitude. Rien de plus.

À partir des résultats d'un panel (`panel.executer_panel`) : par moteur, la proportion de réponses qui MENTIONNENT
la marque et celle qui CITENT son domaine, avec l'effectif `n` et l'intervalle de Wilson à 95 %
(`mesure.statistiques`) ; les mêmes mesures pour les concurrents déclarés, sur le même panel.

Honnêteté exigée (R4 §4.4) :
- les réponses d'API diffèrent de l'interface grand public (personnalisation, modèles) : l'avertissement est dans
chaque rapport ; - l'échantillon est petit et choisi : sous 20 réponses par moteur, le taux est rendu mais marqué
`insuffisant` ; - aucune causalité (rien ne dit POURQUOI une marque est mentionnée) ;
- aucun classement quand les intervalles se chevauchent : `indistinguable`, jamais « devant » ;
- une panne d'appel n'est pas une absence de mention : elle sort de l'effectif et est comptée à part.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from ..mesure import statistiques
from .robots_ia import ErreurGeo

N_MIN = 20
NIVEAU = Decimal("0.95")
AVERTISSEMENTS = (
    "Réponse d'API ≠ interface grand public : personnalisation et modèles diffèrent ; ce taux ne dit pas ce qu'un "
    "visiteur "
    "voit.",
    "Échantillon de questions choisies par le client : un taux observé, pas la visibilité réelle de la marque.",
    "Aucune causalité : le panel ne dit pas pourquoi une marque est mentionnée ou citée, ni ce qui la ferait "
    "apparaître.",
    "Aucun classement entre deux mesures dont les intervalles de Wilson (95 %) se chevauchent.",
)


def _taux(k: int, n: int) -> dict[str, Any]:
    if n == 0:
        return {"k": 0, "n": 0, "taux": None, "wilson_bas": None, "wilson_haut": None}
    bas, haut = statistiques.wilson(k, n, NIVEAU)
    return {"k": k, "n": n, "taux": statistiques.texte(Decimal(k) / Decimal(n)), "wilson_bas": statistiques.texte(bas),
            "wilson_haut": statistiques.texte(haut)}


def _chevauchent(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool | None:
    if a["taux"] is None or b["taux"] is None:
        return None
    return (Decimal(a["wilson_bas"]) <= Decimal(b["wilson_haut"])
            and Decimal(b["wilson_bas"]) <= Decimal(a["wilson_haut"]))


def calculer_visibilite(resultats: Sequence[Mapping[str, Any]], *, plan: Mapping[str, Any] | None = None
                        ) -> dict[str, Any]:
    """Le rapport de visibilité. `resultats` : lignes de `executer_panel` ; `plan` (facultatif) : pour afficher le "
    "coût."""
    if not isinstance(resultats, Sequence) or isinstance(resultats, str):
        raise ErreurGeo("REJ-GEO-RESULTATS-INVALIDES", "liste de résultats attendue")
    moteurs: dict[str, dict[str, Any]] = {}
    for ligne in resultats:
        if not isinstance(ligne, Mapping) or not isinstance(ligne.get("moteur"), str):
            raise ErreurGeo("REJ-GEO-RESULTATS-INVALIDES", "chaque résultat porte un moteur")
        m = moteurs.setdefault(ligne["moteur"], {"n": 0, "mention": 0, "cite": 0, "pannes": 0, "concurrents": {}})
        if "erreur" in ligne:
            m["pannes"] += 1
            continue
        if type(ligne.get("mentionne")) is not bool or type(ligne.get("cite")) is not bool:
            raise ErreurGeo("REJ-GEO-RESULTATS-INVALIDES", "mentionne et cite : booléens attendus")
        m["n"] += 1
        m["mention"] += ligne["mentionne"]
        m["cite"] += ligne["cite"]
        for nom, c in (ligne.get("concurrents") or {}).items():
            cc = m["concurrents"].setdefault(nom, {"mention": 0, "cite": 0})
            cc["mention"] += bool(c["mentionne"])
            cc["cite"] += bool(c["cite"])
    rapport = []
    for moteur in sorted(moteurs):
        m = moteurs[moteur]
        marque = {"mention": _taux(m["mention"], m["n"]), "citation": _taux(m["cite"], m["n"])}
        concurrents = []
        for nom in sorted(m["concurrents"]):
            c = {"mention": _taux(m["concurrents"][nom]["mention"], m["n"]),
                 "citation": _taux(m["concurrents"][nom]["cite"], m["n"])}
            comparaisons = {}
            for mesure in ("mention", "citation"):
                chev = _chevauchent(marque[mesure], c[mesure])
                comparaisons[mesure] = ("non_evaluable" if chev is None else "indistinguable" if chev else
                                        "marque_au_dessus" if Decimal(marque[mesure]["wilson_bas"]) >
                                        Decimal(c[mesure]["wilson_haut"]) else "marque_en_dessous")
            concurrents.append({"concurrent": nom, **c, "comparaison": comparaisons})
        rapport.append({"moteur": moteur, "effectif": m["n"], "appels_en_panne": m["pannes"],
                        "statut": "suffisant" if m["n"] >= N_MIN else "insuffisant", **marque,
                        "concurrents": concurrents})
    cout = None
    if plan is not None:
        cout = {"cout_mensuel_cents": plan.get("cout_mensuel_cents"), "cout": plan.get("cout")}
    return {"type": "VISIBILITE_IA", "niveau_confiance": "0.95", "n_minimal": N_MIN, "moteurs": rapport, "cout": cout,
            "avertissements": list(AVERTISSEMENTS)}


__all__ = ["AVERTISSEMENTS", "N_MIN", "calculer_visibilite"]
