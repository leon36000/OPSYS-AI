"""Détection d'anomalies de dépense publicitaire par des règles TRANSPARENTES.

Sept règles, chacune lisible en une phrase, sans apprentissage ni seuil caché :

| Code   | Ce qu'elle constate | Source de son seuil |
|---|---|---|
| DEP-01 | un jour dépasse le plafond quotidien du plan (plus une tolérance de 20 %) | le budget du plan |
| DEP-02 | dépense sans aucune conversion sur N jours consécutifs | règle déclarée dans le plan |
| DEP-03 | un jour dépasse k fois la médiane des 7 jours précédents (et d'au moins un minimum) | règle du plan, sinon
300 % et 25 $ |
| DEP-04 | de la dépense hors de la période du plan (avant son début, après sa fin) | le plan |
| DEP-05 | jours sans donnée dans la période : la dépense est INCONNUE, pas nulle | la période lue |
| DEP-06 | coût par conversion au-dessus du maximum, avec assez de conversions | règle déclarée dans le plan |
| DEP-07 | la dépense lue dépasse déjà le budget total du plan | le budget du plan |

Une règle qui ne peut pas être jugée (jours manquants, conversions inconnues, échantillon mince, aucun plan) est rendue
`non_evaluable` avec sa raison : ce n'est jamais un « tout va bien ». Une anomalie ne propose qu'une chose, une PAUSE à
décider par la direction (`regles.ACTION`) ; elle n'exécute rien. Les identifiants sont déterministes (rejouer une même
détection donne les mêmes), les valeurs sont des textes décimaux.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from . import regles as r

SEUIL_SAUT_DEFAUT = {
    "regle_id": "saut-depense",
    "type": "saut_depense",
    "ratio_pct": 300,
    "minimum_cents": 2500,
    "action": r.ACTION,
    "statut": r.STATUT_PREPAREE,
    "executee_par_opsys": False,
    "obligatoire": False,
}
SEVERITES = ("info", "attention", "critique")


def identifiant(canal: str, campagne_ref: str | None, code: str, debut: str, fin: str) -> str:
    corps = f"{canal}\x1f{campagne_ref or ''}\x1f{code}\x1f{debut}\x1f{fin}"
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()[:32]


def _severite(constat: Mapping[str, Any]) -> str:
    if constat["code_dep"] == "DEP-07":
        return "critique"
    if (
        constat["code_dep"] == "DEP-01"
        and constat["valeur"] is not None
        and constat["seuil"] is not None
        and Decimal(constat["valeur"]) > 2 * Decimal(constat["seuil"])
    ):
        return "critique"
    return "attention"


def _anomalie(canal, campagne_ref, code, severite, valeur, seuil, unite, jours, raison, fictif) -> dict[str, Any]:
    debut, fin = (min(jours), max(jours)) if jours else ("", "")
    return {
        "anomalie_id": identifiant(canal, campagne_ref, code, debut, fin),
        "canal": canal,
        "campagne_ref": campagne_ref,
        "regle": code,
        "severite": severite,
        "valeur": valeur,
        "seuil": seuil,
        "unite": unite,
        "jour_debut": debut,
        "jour_fin": fin,
        "raison": raison,
        "fictif": fictif,
        "action_preparee": r.ACTION,
        "executee": False,
    }


def detecter(
    *,
    canal: str,
    campagne_ref: str | None,
    serie: Sequence[r.Jour],
    debut: date,
    fin: date,
    plan: Mapping[str, Any] | None,
    fictif: bool,
) -> dict[str, Any]:
    """Évalue les règles du plan (ou, sans plan, la seule règle DEP-03 et le contrôle des trous) sur [debut, fin]."""
    regles = list(plan["regles"]) if plan else [dict(SEUIL_SAUT_DEFAUT)]
    if plan and not any(x["type"] == "saut_depense" for x in regles):
        regles.append(dict(SEUIL_SAUT_DEFAUT))
    constats = r.evaluer(regles, serie, debut=debut, fin=fin)
    anomalies, non_evaluables = [], []
    for c in constats:
        if c["declenchee"]:
            anomalies.append(
                _anomalie(
                    canal,
                    campagne_ref,
                    c["code_dep"],
                    _severite(c),
                    c["valeur"],
                    c["seuil"],
                    c["unite"],
                    c["jours"],
                    c["raison"],
                    fictif,
                )
            )
        elif c["declenchee"] is None:
            non_evaluables.append({"regle": c["code_dep"], "regle_id": c["regle_id"], "raison": c["raison"]})
    if plan is None:
        non_evaluables.append(
            {
                "regle": "DEP-01/04/06/07",
                "regle_id": "plafonds",
                "raison": "aucun plan de campagne indiqué : plafonds, période et coût maximal inconnus",
            }
        )
    dans = [j for j in serie if debut <= j.jour <= fin]
    manquants = r.trous(dans, debut, fin)
    if manquants:
        anomalies.append(
            _anomalie(
                canal,
                campagne_ref,
                "DEP-05",
                "info",
                str(len(manquants)),
                None,
                "jours",
                [m.isoformat() for m in manquants],
                "jours sans donnée dans la période : la dépense de ces jours est INCONNUE, pas nulle",
                fictif,
            )
        )
    if plan is not None:
        d0 = date.fromisoformat(plan["budget"]["date_debut"])
        d1 = d0 + timedelta(days=plan["budget"]["duree_jours"] - 1)
        hors = [j for j in dans if j.cout_cents > 0 and not d0 <= j.jour <= d1]
        if hors:
            total = sum(j.cout_cents for j in hors)
            anomalies.append(
                _anomalie(
                    canal,
                    campagne_ref,
                    "DEP-04",
                    "attention",
                    format(Decimal(total) / 100, "f"),
                    None,
                    "CAD",
                    [j.jour.isoformat() for j in hors],
                    f"dépense hors de la période du plan ({d0.isoformat()} au {d1.isoformat()})",
                    fictif,
                )
            )
    anomalies.sort(key=lambda a: (a["regle"], a["jour_debut"]))
    return {
        "constats": constats,
        "anomalies": anomalies,
        "non_evaluables": non_evaluables,
        "jours_lus": len(dans),
        "jours_manquants": [m.isoformat() for m in manquants],
        "periode": {"debut": debut.isoformat(), "fin": fin.isoformat()},
    }


__all__ = ["SEUIL_SAUT_DEFAUT", "SEVERITES", "detecter", "identifiant"]
