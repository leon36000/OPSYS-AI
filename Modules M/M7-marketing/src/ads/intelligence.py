from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

import sys

_CURR = Path(__file__).resolve().parent
if str(_CURR) not in sys.path:
    sys.path.insert(0, str(_CURR))

from ads_loader import load_fixtures


RULES = ("AD-01", "AD-02", "AD-03", "AD-04", "AD-05", "AD-06")


def _safe_ratio(numerator: float, denominator: float) -> float | str:
    if denominator == 0:
        return "n_insuffisant"
    return round(numerator / denominator, 6)


def _charger_calendrier(chemin: str) -> dict:
    with open(chemin, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "fenetres_marketing" not in data:
        raise ValueError("calendrier invalide : clé 'fenetres_marketing' manquante")
    return data


def _fenetres_actives(calendrier: dict, mois_ref: int) -> list[dict]:
    actives = []
    for fw in calendrier["fenetres_marketing"]:
        debut = fw["mois_debut"]
        fin = fw["mois_fin"]
        if debut <= fin:
            if debut <= mois_ref <= fin:
                actives.append(fw)
        else:
            if mois_ref >= debut or mois_ref <= fin:
                actives.append(fw)
    actives.sort(key=lambda f: f["id"])
    return actives


def _mk_verdict(regle: str, verdict: str, fait: str, action: str = "") -> dict:
    return {
        "regle": regle,
        "verdict": verdict,
        "fait_mesure": fait,
        "action": action,
    }


def _analyser_campagne(plateforme: str, campagne: dict, active_ids: set[str]) -> tuple[list[dict], dict]:
    budget = campagne["budget"]
    cout = campagne["cout"]
    impressions = campagne["impressions"]
    clics = campagne["clics"]
    conversions = campagne["conversions"]

    ctr = _safe_ratio(clics, impressions)
    cpc = _safe_ratio(cout, clics)
    cpa = _safe_ratio(cout, conversions)
    faits = {"ctr": ctr, "cpc": cpc, "cpa": cpa}

    verdicts = []
    metrics_fact = f"ctr={ctr}, cpc={cpc}, cpa={cpa}"
    if "n_insuffisant" in (ctr, cpc, cpa):
        verdicts.append(_mk_verdict("AD-01", "attention", metrics_fact))
    else:
        verdicts.append(_mk_verdict("AD-01", "conforme", metrics_fact))

    verdicts.append(_mk_verdict("AD-02", "conforme", f"plateforme={plateforme}"))

    if campagne["fenetre_id"] not in active_ids:
        verdicts.append(_mk_verdict("AD-03", "action_proposee", f"fenetre_active=false ({campagne['fenetre_id']})", "réallocation"))
    else:
        verdicts.append(_mk_verdict("AD-03", "conforme", f"fenetre_active=true ({campagne['fenetre_id']})"))

    if conversions == 0:
        verdicts.append(_mk_verdict("AD-04", "action_proposee", "conversions=0", "pause candidate"))
    else:
        verdicts.append(_mk_verdict("AD-04", "conforme", f"conversions={conversions}"))

    if budget > 0 and cout > budget:
        verdicts.append(_mk_verdict("AD-05", "action_proposee", f"depassement_budget={round(cout - budget, 2)}", "alerte dépassement budget"))
    else:
        verdicts.append(_mk_verdict("AD-05", "conforme", f"depassement_budget={round(max(0, cout - budget), 2)}"))

    if budget <= 0:
        verdicts.append(_mk_verdict("AD-06", "attention", f"budget={budget}"))
    elif cout >= budget * 0.8:
        verdicts.append(_mk_verdict("AD-06", "attention", f"consommation_budget={round(cout / budget, 6)}"))
    else:
        verdicts.append(_mk_verdict("AD-06", "conforme", f"consommation_budget={round(cout / budget, 6)}"))

    verdicts.sort(key=lambda v: v["regle"])
    return verdicts, faits


def generate_report(fixtures_dir: str, calendrier_path: str, date_reference: str) -> dict:
    d = date.fromisoformat(date_reference.split("T")[0])
    calendrier = _charger_calendrier(calendrier_path)

    toutes_fenetres = {f["id"] for f in calendrier["fenetres_marketing"]}
    actives = _fenetres_actives(calendrier, d.month)
    active_ids = {f["id"] for f in actives}

    campagnes_analyses = []
    recommandations = []

    for fixture in load_fixtures(fixtures_dir):
        plateforme = fixture["plateforme"]
        for campagne in fixture["campagnes"]:
            fenetre_id = campagne["fenetre_id"]
            if fenetre_id not in toutes_fenetres:
                raise ValueError(f"fenetre_id inconnu: {fenetre_id}")

            verdicts, faits = _analyser_campagne(plateforme, campagne, active_ids)
            campagnes_analyses.append(
                {
                    "plateforme": plateforme,
                    "campagne": campagne["campagne"],
                    "periode": campagne["periode"],
                    "fenetre_id": fenetre_id,
                    "budget": campagne["budget"],
                    "cout": campagne["cout"],
                    "impressions": campagne["impressions"],
                    "clics": campagne["clics"],
                    "conversions": campagne["conversions"],
                    "faits_mesures": faits,
                    "verdicts": verdicts,
                }
            )

            for verdict in verdicts:
                if verdict["verdict"] == "conforme":
                    continue
                action = verdict["action"] if verdict["action"] else "surveillance"
                recommandations.append(
                    {
                        "statut": "PROPOSE",
                        "plateforme": plateforme,
                        "campagne": campagne["campagne"],
                        "regle": verdict["regle"],
                        "verdict": verdict["verdict"],
                        "action": action,
                        "fait_mesure": verdict["fait_mesure"],
                    }
                )

    campagnes_analyses.sort(key=lambda c: (c["plateforme"], c["campagne"], c["fenetre_id"]))
    recommandations.sort(key=lambda r: (r["plateforme"], r["campagne"], r["regle"]))

    return {
        "date_reference": date_reference,
        "fenetres_actives": [f["id"] for f in actives],
        "campagnes": campagnes_analyses,
        "recommandations": recommandations,
    }
