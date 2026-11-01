"""Sensibilité (tornade) et scénarios d'un projet d'investissement de l'entreprise (moteur de calcul, tranche 1).

Le MODÈLE est fixe et dit (aucune hypothèse n'est ajoutée en silence) : un projet coûte `investissement_initial` au
temps 0, rapporte `flux_annuel` l'année 1, croissant de `croissance_annuelle` par an (flux de l'année t :
F × (1 + g)^(t−1), arrondi au cent ROUND_HALF_UP), pendant `duree_annees` ans, plus `valeur_residuelle` l'année n ;
il est actualisé au `taux_actualisation` annuel. Mesures : VAN (au cent), TRI (avec son statut :
`maths_financieres.tri`), délai de récupération simple.

TORNADE : chaque hypothèse déclarée varie seule, à sa valeur basse puis haute, les autres restant à leur valeur de
base ; l'impact est la VAN obtenue, et l'amplitude |VAN(haut) − VAN(bas)|. Les barres sont triées par amplitude
décroissante (puis par nom : ordre total). SCÉNARIOS : des jeux nommés de valeurs qui remplacent celles de base.
Les valeurs basses, hautes et de scénario sont celles de l'appelant : aucune n'est choisie ici (pas de « ±10 % » par
défaut). Module pur, il reçoit des valeurs déjà validées par `moteur_calcul.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import Any

from . import maths_financieres as mf

__all__ = ["HYPOTHESES", "analyser", "flux_du_projet", "mesurer"]

# Les six hypothèses du modèle, fixes : une hypothèse inconnue est refusée (liste fermée, pas une classification).
HYPOTHESES = frozenset({
    "investissement_initial", "flux_annuel", "croissance_annuelle", "duree_annees", "taux_actualisation",
    "valeur_residuelle",
})


def flux_du_projet(h: Mapping[str, Any]) -> list[Decimal]:
    with localcontext(mf.CONTEXTE):
        flux = [-h["investissement_initial"]]
        for t in range(1, h["duree_annees"] + 1):
            flux.append(mf.au_cent(h["flux_annuel"] * (1 + h["croissance_annuelle"]) ** (t - 1)))
        flux[-1] += h["valeur_residuelle"]
        return flux


def mesurer(h: Mapping[str, Any]) -> dict[str, Any]:
    flux = flux_du_projet(h)
    resultat_tri = mf.tri(flux)
    return {
        "van": mf.au_cent(mf.van(h["taux_actualisation"], flux)),
        "tri_statut": resultat_tri["statut"],
        "tri": resultat_tri["tri"],
        "delai_recuperation": mf.delai_recuperation(flux),
    }


def analyser(base: Mapping[str, Any], variations: Mapping[str, Mapping[str, Any]],
             scenarios: list[Mapping[str, Any]]) -> dict[str, Any]:
    """`base` : les six hypothèses ; `variations` : hypothèse → {"bas", "haut"} ; `scenarios` : [{"nom",
    "hypotheses"}]. Rend la mesure de base, la tornade triée et les scénarios."""
    mesure_base = mesurer(base)
    tornade = []
    for nom in sorted(variations):
        bas = mesurer({**base, nom: variations[nom]["bas"]})["van"]
        haut = mesurer({**base, nom: variations[nom]["haut"]})["van"]
        tornade.append({
            "hypothese": nom, "valeur_basse": variations[nom]["bas"], "valeur_haute": variations[nom]["haut"],
            "van_basse": bas, "van_haute": haut, "amplitude": abs(haut - bas),
        })
    tornade.sort(key=lambda barre: (-barre["amplitude"], barre["hypothese"]))
    sorties = [{"nom": s["nom"], **mesurer({**base, **s["hypotheses"]})} for s in scenarios]
    return {"base": mesure_base, "tornade": tornade, "scenarios": sorties}
