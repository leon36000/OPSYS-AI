"""Conseiller en dette, financement et investissement de M5 (M5.13) : TRÉSORERIE ET INFORMATION GÉNÉRALE seulement.

Compare, sous des hypothèses EXPLICITES de l'appelant, l'achat comptant, l'achat financé par un prêt (amortissement
canadien) et la location d'un actif d'exploitation, par la valeur actuelle de leurs coûts (VAN des flux mensuels) ;
le taux effectif du prêt est le TRI de ses flux (frais de dossier compris). Tout chiffre vient du moteur déterministe
(`moteur_calcul` : amortissement, rentabilité VAN/TRI) et chaque comparaison rend un REÇU rejouable qui cite les
reçus des calculs qu'elle compose. La sensibilité est celle que l'appelant demande (variations nommées, aucune par
défaut) : pour chacune, le coût de chaque scénario, le scénario au coût actualisé le plus bas, et si l'ordre change.

Ce que ce module ne fait JAMAIS :
- recommander un titre, un produit de placement ou une institution (garde NC 31-103 : l'objet est une décision
  d'EXPLOITATION de la liste fermée de `moteur_calcul.OBJETS_ADMIS`) ;
- inventer un taux, un prix, une valeur résiduelle ou une pénalité : tout vient de l'appelant ;
- conclure « il faut » : le scénario « au coût actualisé le plus bas » est un FAIT de calcul sous les hypothèses,
pas une
  recommandation ; aucun effet fiscal (DPA, TPS/TVQ, déductibilité) n'est modélisé.

Module pur : aucune horloge, aucun registre, aucune écriture.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from . import encodage
from . import maths_financieres as mf
from . import moteur_calcul as mc

__all__ = ["VERSION", "comparer_financement"]

VERSION = mc.VERSION
VARIATIONS_MAX = 6
_CLES_VARIABLES = frozenset(
    {
        "taux_actualisation_annuel",
        "prix_achat",
        "valeur_residuelle",
        "horizon_mois",
        "pret.taux_annuel",
        "pret.mise_de_fonds",
        "location.paiement_mensuel",
        "location.depot_initial",
    }
)
_METHODE = (
    "Flux mensuels de chaque scénario sur l'horizon (t = 0 : sorties initiales ; t = 1..h : versements ; t = h : "
    "valeur "
    "résiduelle reçue, solde du prêt remboursé), actualisés au taux mensuel (1 + r annuel effectif)^(1/12) − 1 ; coût "
    "actualisé = −VAN (moteur de rentabilité) ; taux effectif du prêt = TRI mensuel de ses flux, annualisé "
    "(1 + i)^12 − 1. Le scénario « au coût actualisé le plus bas » est un fait de calcul, pas une recommandation."
)


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return mc._refus(code, detail)


def _lire(brut: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    cles = {
        "objet",
        "prix_achat",
        "frais_achat",
        "horizon_mois",
        "valeur_residuelle",
        "taux_actualisation_annuel",
        "pret",
        "location",
        "variations",
    }
    lu, verdict = mc._cles(
        brut,
        cles,
        {"objet", "prix_achat", "frais_achat", "horizon_mois", "valeur_residuelle", "taux_actualisation_annuel"},
    )
    if verdict:
        return None, verdict
    objet, verdict = mc._objet(lu["objet"])
    if verdict:
        return None, verdict
    prix, verdict = mc._montant(lu["prix_achat"], "prix_achat", strictement_positif=True)
    if verdict:
        return None, verdict
    frais, verdict = mc._montant(lu["frais_achat"], "frais_achat", minimum=Decimal(0))
    if verdict:
        return None, verdict
    valeur_residuelle, verdict = mc._montant(lu["valeur_residuelle"], "valeur_residuelle", minimum=Decimal(0))
    if verdict:
        return None, verdict
    horizon, verdict = mc._entier(lu["horizon_mois"], "horizon_mois", "REJ-CALC-DUREE-INVALIDE", 1, mc.MOIS_MAX)
    if verdict:
        return None, verdict
    taux, verdict = mc._taux(lu["taux_actualisation_annuel"], "taux_actualisation_annuel")
    if verdict:
        return None, verdict
    hyp: dict[str, Any] = {
        "objet": objet,
        "prix_achat": prix,
        "frais_achat": frais,
        "horizon_mois": horizon,
        "valeur_residuelle": valeur_residuelle,
        "taux_actualisation_annuel": taux,
        "pret": None,
        "location": None,
    }
    if lu.get("pret") is not None:
        cles_p = {"mise_de_fonds", "taux_annuel", "convention", "amortissement_annees", "frais_dossier"}
        pret, verdict = mc._cles(lu["pret"], cles_p, cles_p)
        if verdict:
            return None, verdict
        mise, verdict = mc._montant(pret["mise_de_fonds"], "pret.mise_de_fonds", minimum=Decimal(0))
        if verdict:
            return None, verdict
        if mise >= prix:
            return _refus("REJ-CALC-MONTANT-INVALIDE", "pret.mise_de_fonds : doit être inférieure au prix d'achat")
        taux_pret, verdict = mc._taux(pret["taux_annuel"], "pret.taux_annuel")
        if verdict:
            return None, verdict
        if type(pret["convention"]) is not str or pret["convention"] not in mf.CONVENTIONS_TAUX:
            return _refus("REJ-CALC-CONVENTION-INCONNUE", f"pret.convention : une de {sorted(mf.CONVENTIONS_TAUX)}")
        annees, verdict = mc._entier(
            pret["amortissement_annees"], "pret.amortissement_annees", "REJ-CALC-DUREE-INVALIDE", 1, mc.ANNEES_MAX
        )
        if verdict:
            return None, verdict
        frais_dossier, verdict = mc._montant(pret["frais_dossier"], "pret.frais_dossier", minimum=Decimal(0))
        if verdict:
            return None, verdict
        hyp["pret"] = {
            "mise_de_fonds": mise,
            "taux_annuel": taux_pret,
            "convention": pret["convention"],
            "amortissement_annees": annees,
            "frais_dossier": frais_dossier,
        }
    if lu.get("location") is not None:
        cles_l = {"depot_initial", "paiement_mensuel", "paiements_en_debut_de_periode", "option_achat_finale"}
        loc, verdict = mc._cles(lu["location"], cles_l, cles_l - {"option_achat_finale"})
        if verdict:
            return None, verdict
        depot, verdict = mc._montant(loc["depot_initial"], "location.depot_initial", minimum=Decimal(0))
        if verdict:
            return None, verdict
        paiement, verdict = mc._montant(loc["paiement_mensuel"], "location.paiement_mensuel", strictement_positif=True)
        if verdict:
            return None, verdict
        if type(loc["paiements_en_debut_de_periode"]) is not bool:
            return _refus(
                "REJ-CALC-FLUX-INVALIDES", "location.paiements_en_debut_de_periode : vrai ou faux, jamais supposé"
            )
        option = None
        if loc.get("option_achat_finale") is not None:
            option, verdict = mc._montant(
                loc["option_achat_finale"], "location.option_achat_finale", minimum=Decimal(0)
            )
            if verdict:
                return None, verdict
        hyp["location"] = {
            "depot_initial": depot,
            "paiement_mensuel": paiement,
            "paiements_en_debut_de_periode": loc["paiements_en_debut_de_periode"],
            "option_achat_finale": option,
        }
    variations = []
    brutes = lu.get("variations", [])
    if not isinstance(brutes, list) or len(brutes) > VARIATIONS_MAX:
        return _refus("REJ-CALC-BORNE-DEPASSEE", f"variations : au plus {VARIATIONS_MAX}")
    noms: set[str] = set()
    for index, v in enumerate(brutes):
        lue, verdict = mc._cles(v, {"nom", "modifications"}, {"nom", "modifications"}, "REJ-CALC-SCENARIO-INVALIDE")
        if verdict:
            return None, verdict
        nom = lue["nom"]
        if type(nom) is not str or mc._RE_NOM_SCENARIO.fullmatch(nom) is None or nom in noms:
            return _refus("REJ-CALC-SCENARIO-INVALIDE", f"variations[{index}].nom : minuscules, chiffres, - _ ; unique")
        noms.add(nom)
        mods = lue["modifications"]
        if not isinstance(mods, Mapping) or not mods or set(mods) - _CLES_VARIABLES:
            return _refus(
                "REJ-CALC-HYPOTHESE-INVALIDE",
                f"variations[{index}].modifications : non vide, clés parmi {sorted(_CLES_VARIABLES)}",
            )
        variations.append((nom, dict(mods)))
    hyp["variations"] = variations
    return hyp, None


def _copie_avec(hyp: Mapping[str, Any], mods: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les hypothèses de base modifiées par une variation (valeurs validées comme celles de base)."""
    h = {
        **hyp,
        "pret": None if hyp["pret"] is None else dict(hyp["pret"]),
        "location": None if hyp["location"] is None else dict(hyp["location"]),
    }
    for cle, valeur in mods.items():
        if cle == "taux_actualisation_annuel":
            h[cle], verdict = mc._taux(valeur, cle)
        elif cle in ("prix_achat",):
            h[cle], verdict = mc._montant(valeur, cle, strictement_positif=True)
        elif cle == "valeur_residuelle":
            h[cle], verdict = mc._montant(valeur, cle, minimum=Decimal(0))
        elif cle == "horizon_mois":
            h[cle], verdict = mc._entier(valeur, cle, "REJ-CALC-DUREE-INVALIDE", 1, mc.MOIS_MAX)
        elif cle == "pret.taux_annuel" and h["pret"] is not None:
            h["pret"]["taux_annuel"], verdict = mc._taux(valeur, cle)
        elif cle == "pret.mise_de_fonds" and h["pret"] is not None:
            h["pret"]["mise_de_fonds"], verdict = mc._montant(valeur, cle, minimum=Decimal(0))
        elif cle == "location.paiement_mensuel" and h["location"] is not None:
            h["location"]["paiement_mensuel"], verdict = mc._montant(valeur, cle, strictement_positif=True)
        elif cle == "location.depot_initial" and h["location"] is not None:
            h["location"]["depot_initial"], verdict = mc._montant(valeur, cle, minimum=Decimal(0))
        else:
            return _refus("REJ-CALC-HYPOTHESE-INVALIDE", f"{cle} : ce scénario n'est pas dans la comparaison")
        if verdict:
            return None, verdict
    if h["pret"] is not None and h["pret"]["mise_de_fonds"] >= h["prix_achat"]:
        return _refus("REJ-CALC-MONTANT-INVALIDE", "pret.mise_de_fonds : doit être inférieure au prix d'achat")
    return h, None


def _flux_txt(flux: list[Decimal]) -> list[str]:
    return [format(c.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f") for c in flux]


def _evaluer(h: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les scénarios de `h` : flux, coût actualisé (−VAN du moteur) et reçus enfants. `(None, verdict)` au premier "
    "refus."""
    horizon = h["horizon_mois"]
    taux_mensuel = mf.taux_periodique(h["taux_actualisation_annuel"], "mensuelle", "effectif_annuel")
    taux_txt = mc._txt_taux(taux_mensuel)
    scenarios: dict[str, dict[str, Any]] = {}
    enfants: list[dict[str, str]] = []

    def cout(flux: list[Decimal]) -> tuple[Decimal | None, dict[str, str] | None]:
        sortie, verdict = mc.calculer_rentabilite(
            {"objet": h["objet"], "flux": _flux_txt(flux), "taux_actualisation": taux_txt}
        )
        if verdict:
            return None, verdict
        enfants.append({"moteur": sortie["recu"]["moteur"], "empreinte": sortie["recu"]["empreinte"]})
        return -Decimal(sortie["recu"]["resultat"]["van"]), None

    # --- comptant
    flux = [Decimal(0)] * (horizon + 1)
    flux[0] = -(h["prix_achat"] + h["frais_achat"])
    flux[horizon] += h["valeur_residuelle"]
    valeur, verdict = cout(flux)
    if verdict:
        return None, verdict
    scenarios["comptant"] = {
        "cout_actualise": valeur,
        "sorties_initiales": -flux[0],
        "mensualite": None,
        "total_decaisse": h["prix_achat"] + h["frais_achat"],
        "interets_et_frais": Decimal(0),
    }
    # --- prêt
    pret = h["pret"]
    if pret is not None:
        principal = h["prix_achat"] - pret["mise_de_fonds"]
        sortie, verdict = mc.calculer_amortissement(
            {
                "objet": "pret_entreprise",
                "montant_emprunte": format(principal, ".2f"),
                "taux_annuel": mc._txt_norme(pret["taux_annuel"]),
                "frequence": "mensuelle",
                "convention": pret["convention"],
                "amortissement_annees": pret["amortissement_annees"],
            }
        )
        if verdict:
            return None, verdict
        enfants.append({"moteur": sortie["recu"]["moteur"], "empreinte": sortie["recu"]["empreinte"]})
        tableau = sortie["tableau"]
        flux = [Decimal(0)] * (horizon + 1)
        flux[0] = -(pret["mise_de_fonds"] + h["frais_achat"] + pret["frais_dossier"])
        flux_pret = [Decimal(0)] * (horizon + 1)
        flux_pret[0] = principal - pret["frais_dossier"]
        verses = interets = Decimal(0)
        for ligne in tableau[:horizon]:
            v = Decimal(ligne["versement"])
            flux[ligne["periode"]] -= v
            flux_pret[ligne["periode"]] -= v
            verses += v
            interets += Decimal(ligne["interet"])
        if len(tableau) > horizon:
            solde = Decimal(tableau[horizon - 1]["solde"])
            flux[horizon] -= solde
            flux_pret[horizon] -= solde
            verses += solde
        flux[horizon] += h["valeur_residuelle"]
        valeur, verdict = cout(flux)
        if verdict:
            return None, verdict
        tri_sortie, verdict = mc.calculer_rentabilite(
            {"objet": "pret_entreprise", "flux": _flux_txt(flux_pret), "taux_actualisation": taux_txt}
        )
        if verdict:
            return None, verdict
        enfants.append({"moteur": tri_sortie["recu"]["moteur"], "empreinte": tri_sortie["recu"]["empreinte"]})
        tri = tri_sortie["recu"]["resultat"]["tri"]
        effectif = None
        if tri["statut"] == "UNIQUE" and tri["valeur"] is not None:
            with localcontext(mf.CONTEXTE):
                effectif = (Decimal(1) + Decimal(tri["valeur"])) ** 12 - 1
        scenarios["pret"] = {
            "cout_actualise": valeur,
            "sorties_initiales": -flux[0],
            "mensualite": Decimal(tableau[0]["versement"]),
            "total_decaisse": -flux[0] + verses,
            "interets_et_frais": interets + pret["frais_dossier"],
            "taux_effectif_annuel": effectif,
            "statut_tri": tri["statut"],
            "versements_dans_l_horizon": min(len(tableau), horizon),
            "solde_rembourse_a_l_horizon": (
                Decimal(tableau[horizon - 1]["solde"]) if len(tableau) > horizon else Decimal(0)
            ),
        }
    # --- location
    loc = h["location"]
    if loc is not None:
        flux = [Decimal(0)] * (horizon + 1)
        flux[0] = -loc["depot_initial"]
        debut = 0 if loc["paiements_en_debut_de_periode"] else 1
        for t in range(debut, debut + horizon):
            flux[t] -= loc["paiement_mensuel"]
        if loc["option_achat_finale"] is not None:
            flux[horizon] += h["valeur_residuelle"] - loc["option_achat_finale"]
        valeur, verdict = cout(flux)
        if verdict:
            return None, verdict
        sorties = loc["depot_initial"] + loc["paiement_mensuel"] * horizon + (loc["option_achat_finale"] or Decimal(0))
        scenarios["location"] = {
            "cout_actualise": valeur,
            "sorties_initiales": -flux[0],
            "mensualite": loc["paiement_mensuel"],
            "total_decaisse": sorties,
            "interets_et_frais": Decimal(0),
            "option_exercee": loc["option_achat_finale"] is not None,
        }
    return {"scenarios": scenarios, "enfants": enfants}, None


def _ordre(scenarios: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(scenarios, key=lambda nom: (scenarios[nom]["cout_actualise"], nom))


def _vue(nom: str, s: Mapping[str, Any]) -> dict[str, Any]:
    vue: dict[str, Any] = {"scenario": nom}
    for cle, valeur in s.items():
        if isinstance(valeur, Decimal):
            vue[cle] = mc._txt_pourcent(valeur) if cle == "taux_effectif_annuel" else mc._txt_cent(valeur)
        else:
            vue[cle] = valeur
    if "taux_effectif_annuel" in vue:
        vue["taux_effectif_annuel_pourcentage"] = vue.pop("taux_effectif_annuel")
    return vue


def comparer_financement(entrees: Any, parametres: Any = None):
    """Compare comptant, prêt et location sur un même horizon ; sensibilité aux variations nommées de l'appelant."""
    hyp, verdict = (
        _lire(entrees) if isinstance(entrees, Mapping) else _refus("REJ-CALC-FLUX-INVALIDES", "entrées : objet attendu")
    )
    if verdict:
        return None, verdict
    if hyp["pret"] is None and hyp["location"] is None:
        return _refus(
            "REJ-CALC-SCENARIO-INVALIDE",
            "au moins un scénario de financement ou de location est à comparer à l'achat comptant",
        )
    base, verdict = _evaluer(hyp)
    if verdict:
        return None, verdict
    ordre_base = _ordre(base["scenarios"])
    enfants = list(base["enfants"])
    sensibilite = []
    for nom, mods in hyp["variations"]:
        h, verdict = _copie_avec(hyp, mods)
        if verdict:
            return None, verdict
        evalue, verdict = _evaluer(h)
        if verdict:
            return None, verdict
        enfants.extend(evalue["enfants"])
        ordre = _ordre(evalue["scenarios"])
        sensibilite.append(
            {
                "variation": nom,
                "modifications": {k: str(v) for k, v in sorted(mods.items())},
                "couts_actualises": {s: mc._txt_cent(evalue["scenarios"][s]["cout_actualise"]) for s in sorted(ordre)},
                "cout_actualise_le_plus_bas": ordre[0],
                "ordre_change": ordre != ordre_base,
            }
        )
    plus_bas = ordre_base[0]
    couts = base["scenarios"]
    lectures = [
        f"Sous les hypothèses saisies, le coût actualisé le plus bas est celui du scénario « {plus_bas} » "
        f"({mc._txt_cent(couts[plus_bas]['cout_actualise'])} $)."
    ]
    for autre in ordre_base[1:]:
        surcout = mc._txt_cent(couts[autre]["cout_actualise"] - couts[plus_bas]["cout_actualise"])
        lectures.append(f"Le scénario « {autre} » coûte {surcout} $ de plus en valeur actuelle que « {plus_bas} ».")
    lectures.append(
        "Ce sont des faits de calcul sous des hypothèses, pas une recommandation : liquidités, risque, "
        "fiscalité et conditions réelles de l'offre ne sont pas évalués."
    )
    if any(s["ordre_change"] for s in sensibilite):
        lectures.append(
            "Au moins une variation demandée change l'ordre des coûts : la conclusion dépend des hypothèses."
        )
    resultat = {
        "horizon_mois": hyp["horizon_mois"],
        "taux_mensuel_d_actualisation": mc._txt_taux(
            mf.taux_periodique(hyp["taux_actualisation_annuel"], "mensuelle", "effectif_annuel")
        ),
        "scenarios": [_vue(nom, couts[nom]) for nom in ordre_base],
        "ordre_par_cout_actualise": ordre_base,
        "cout_actualise_le_plus_bas": plus_bas,
        "sensibilite": sensibilite,
        "lectures": lectures,
        "recus_composes": {"nombre": len(enfants), "empreinte": encodage.empreinte("m5.financement.recus.v1", enfants)},
    }
    avertissements = [
        mc.AVERTISSEMENT_NC_31_103,
        mc.AVERTISSEMENT_FISCAL,
        "Le scénario « au coût actualisé le plus bas » n'est pas une recommandation : seuls les coûts actualisés sont "
        "comparés, sous les hypothèses de l'appelant (valeur résiduelle, taux d'actualisation, conditions de l'offre).",
        "La location couvre tout l'horizon ; les frais de fin de bail, l'entretien et l'assurance ne sont comptés que "
        "s'ils sont inclus dans les montants saisis.",
        "Le prêt est remboursé à l'horizon s'il n'est pas échu (solde dû ; pénalités du prêteur non modélisées).",
    ]
    normalisees: dict[str, Any] = {
        "objet": hyp["objet"],
        "prix_achat": format(hyp["prix_achat"], ".2f"),
        "frais_achat": format(hyp["frais_achat"], ".2f"),
        "horizon_mois": hyp["horizon_mois"],
        "valeur_residuelle": format(hyp["valeur_residuelle"], ".2f"),
        "taux_actualisation_annuel": mc._txt_norme(hyp["taux_actualisation_annuel"]),
        "pret": None
        if hyp["pret"] is None
        else {
            "mise_de_fonds": format(hyp["pret"]["mise_de_fonds"], ".2f"),
            "taux_annuel": mc._txt_norme(hyp["pret"]["taux_annuel"]),
            "convention": hyp["pret"]["convention"],
            "amortissement_annees": hyp["pret"]["amortissement_annees"],
            "frais_dossier": format(hyp["pret"]["frais_dossier"], ".2f"),
        },
        "location": None
        if hyp["location"] is None
        else {
            "depot_initial": format(hyp["location"]["depot_initial"], ".2f"),
            "paiement_mensuel": format(hyp["location"]["paiement_mensuel"], ".2f"),
            "paiements_en_debut_de_periode": hyp["location"]["paiements_en_debut_de_periode"],
            "option_achat_finale": None
            if hyp["location"]["option_achat_finale"] is None
            else format(hyp["location"]["option_achat_finale"], ".2f"),
        },
        "variations": [
            {"nom": n, "modifications": {k: str(v) for k, v in sorted(m.items())}} for n, m in hyp["variations"]
        ],
    }
    return {
        "recu": mc._recu(
            "comparaison_financement",
            _METHODE,
            {"conventions": "taux mensuel effectif"},
            normalisees,
            resultat,
            avertissements,
        )
    }, None


# Le moteur composé est rejouable comme les autres : l'inscription au registre des moteurs se fait à l'import (les
# outils de M5 importent ce module au chargement).
mc.MOTEURS[("comparaison_financement", mc.VERSION)] = (comparer_financement, ())
