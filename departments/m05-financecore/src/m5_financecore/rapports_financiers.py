"""Les RAPPORTS financiers de M5, tirés du grand livre (M5-RAPPORTS-1) : état des résultats, bilan, budget contre réel,
rentabilité par service et par ville, rapport mensuel de direction. Tous en BROUILLON.

Module pur (ADR-0009, même règle que `grand_livre.py`) : aucun import d'`opsys`, aucune horloge, aucun registre, aucun
réseau, aucune écriture. L'adaptateur (`outils_rapports.py`) lit le grand livre, le budget déclaré et les rentabilités
déjà calculées, puis appelle ce module avec des ENTRÉES NORMALISÉES (types JSON : textes décimaux, entiers, listes).

Règles non négociables.

* AUCUN chiffre ne vient d'un modèle ni d'un calcul « de tête » : tout vient du grand livre en partie double (écritures
  DÉFINITIVES seulement, comme la balance de vérification), additionné en `Decimal` exact. Jamais d'arrondi caché : un
  seul arrondi existe, le pourcentage (deux décimales, ROUND_HALF_UP), et il est dit. Les montants sont des textes
  décimaux au cent.
* Un brouillon n'est jamais additionné : il est COMPTÉ à part et le rapport le dit (`completude`).
* BROUILLON PRÉPARATOIRE. Chaque rapport porte `statut: BROUILLON` et la mention « Brouillon préparatoire — à valider
  auprès d'un comptable (CPA) ». Aucune clôture de période, aucune écriture, aucun état « final ».
* Fail-closed. Un compte du grand livre que le plan courant ne connaît pas fait refuser le rapport (jamais classé au
  hasard). Une donnée absente (budget, comptes de coûts directs, service ou ville d'un chantier) donne
  « NON_CALCULABLE » avec ce qu'il faut déclarer : jamais zéro.
* SOURCES CITÉES. Chaque rapport nomme les registres qu'il a lus, avec leur taille et la tête de leur chaîne
  (`sources`, dans les
  entrées du reçu) : le reçu se rejoue sur les MÊMES registres tant que ces têtes n'ont pas changé.
* REÇU REJOUABLE. Chaque rapport rend un reçu (`recu_calcul`) dont les `entrees` sont les mouvements normalisés ;
  `rejouer`
  refait le calcul à partir d'elles et compare les empreintes. Un reçu compact (sans `entrees`) reste vérifiable par son
  empreinte ; il se rejoue en rappelant l'outil sur les mêmes registres.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import encodage, recu_calcul, verdicts_rapports

__all__ = [
    "AXES",
    "MENTION_BROUILLON",
    "MOTEURS",
    "VERSION",
    "calculer_bilan",
    "calculer_budget_contre_reel",
    "calculer_etat_des_resultats",
    "calculer_rentabilite_par_axe",
    "composer_rapport_mensuel",
    "extraire_mouvements",
    "fin_de_mois",
    "mouvements_par_mois",
    "periode_en_dates",
    "rejouer",
    "section",
]

VERSION = "1.0.0"
MENTION_BROUILLON = "Brouillon préparatoire — à valider auprès d'un comptable (CPA)"
_LES_AXES = ("service", "ville")
AXES = _LES_AXES  # alias : la liste est un catalogue du code (voir `controleur_preaudit.REGLES`)
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_PRECISION = {
    "montants": "Decimal exact au cent, aucune approximation",
    "pourcentage": "ROUND_HALF_UP à deux décimales (le seul arrondi, dit)",
}
_JOURS_PERIODE_MAX = 400
_TYPES_RESULTAT = ("produits", "charges")
_TYPES_BILAN = ("actif", "passif", "capitaux_propres")


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_rapports.construire_verdict(code, detail=detail)


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _dec(texte: Any) -> Decimal:
    return Decimal(str(texte))


def _pct(numerateur: Decimal, denominateur: Decimal) -> str | None:
    if denominateur == 0:
        return None
    return format((numerateur * 100 / denominateur).quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _jour(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or len(valeur) != 10 or not valeur.isascii():
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def fin_de_mois(mois: str) -> date | None:
    """Le dernier jour du mois `AAAA-MM`, ou `None`."""
    if not isinstance(mois, str) or len(mois) != 7 or not mois.isascii():
        return None
    try:
        premier = date.fromisoformat(mois + "-01")
    except ValueError:
        return None
    suivant = date(premier.year + (premier.month == 12), premier.month % 12 + 1, 1)
    return suivant - timedelta(days=1)


# ======================================================================================== lecture du grand livre
def extraire_mouvements(
    etat_gl: Mapping[str, Any], plan: Mapping[str, Any], debut: date | None, fin: date
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les mouvements des écritures DÉFINITIVES dont la date d'effet est dans `[debut, fin]` (`debut` absent : depuis
    le début du registre), cumulés par compte, en entrées normalisées. Un brouillon est compté (`brouillons`), jamais
    additionné. Refus : chaîne du grand livre altérée, compte absent du plan courant (classement impossible)."""
    if etat_gl["anomalies"]:
        return None, _verdict("REJ-RAPPORT-CHAINE-INVALIDE", "grand livre : " + "; ".join(etat_gl["anomalies"][:3]))
    cumuls: dict[str, list[Decimal]] = {}
    ecritures = brouillons = 0
    for identifiant in etat_gl["ordre"]:
        ecriture = etat_gl["ecritures"][identifiant]
        jour = date.fromisoformat(ecriture["date_effet"])
        if jour > fin or (debut is not None and jour < debut):
            continue
        if ecriture["statut"] != "DEFINITIVE":
            brouillons += 1
            continue
        ecritures += 1
        for ligne in ecriture["lignes"]:
            cumul = cumuls.setdefault(ligne["compte"], [_ZERO, _ZERO])
            cumul[0] += ligne["debit"]
            cumul[1] += ligne["credit"]
    inconnus = sorted(c for c in cumuls if c not in plan["comptes"])
    if inconnus:
        return None, _verdict(
            "REJ-RAPPORT-COMPTE-HORS-PLAN",
            f"des écritures touchent des comptes absents du plan courant ({', '.join(inconnus[:5])}) : les ranger dans "
            "l'état financier au hasard serait faux ; rétablir le compte au plan (configuration.grand_livre)",
        )
    comptes = [
        {
            "compte": numero,
            "nom": plan["comptes"][numero]["nom"],
            "type": plan["comptes"][numero]["type"],
            "debit": _txt(debit),
            "credit": _txt(credit),
        }
        for numero, (debit, credit) in sorted(cumuls.items())
    ]
    verrou = etat_gl["verrou"]
    return {
        "comptes": comptes,
        "ecritures_definitives": ecritures,
        "brouillons": brouillons,
        "periode_close": verrou is not None and verrou >= fin,
        "plan_comptable_version": plan["version_effective"],
    }, None


def mouvements_par_mois(
    etat_gl: Mapping[str, Any], plan: Mapping[str, Any], mois: Sequence[str]
) -> tuple[list[dict[str, str]] | None, dict[str, str] | None]:
    """Le réel PAR COMPTE ET PAR MOIS (produits : crédit moins débit ; charges : débit moins crédit) des écritures
    définitives, pour les mois demandés, en entrées normalisées. Mêmes refus que `extraire_mouvements`."""
    resultat: list[dict[str, str]] = []
    for un_mois in mois:
        fin = fin_de_mois(un_mois)
        if fin is None:
            return None, _verdict("REJ-RAPPORT-PERIODE-INVALIDE", f"mois {un_mois!r} : AAAA-MM exigé")
        mouvements, refus = extraire_mouvements(etat_gl, plan, date.fromisoformat(un_mois + "-01"), fin)
        if refus is not None:
            return None, refus
        for ligne in mouvements["comptes"]:
            if ligne["type"] in _TYPES_RESULTAT:
                resultat.append(
                    {
                        "compte": ligne["compte"],
                        "mois": un_mois,
                        "type": ligne["type"],
                        "nom": ligne["nom"],
                        "montant": _txt(_net(ligne)),
                    }
                )
    return resultat, None


def _net(ligne: Mapping[str, Any]) -> Decimal:
    """Le montant d'un compte du côté de son sens normal : débit moins crédit pour l'actif et les charges, crédit moins
    débit pour le passif, les capitaux propres et les produits. Négatif : le compte est du mauvais côté."""
    debit, credit = _dec(ligne["debit"]), _dec(ligne["credit"])
    return debit - credit if ligne["type"] in ("actif", "charges") else credit - debit


# ============================================================================================= le reçu commun
def _recu(
    moteur: str,
    methode: str,
    parametres: Mapping[str, Any],
    entrees: Mapping[str, Any],
    complet: Mapping[str, Any],
    resume: Mapping[str, Any],
    avertissements: list[str],
) -> dict[str, Any]:
    empreinte_etat = encodage.empreinte(f"m5.{moteur}.etat.v1", dict(complet))
    return recu_calcul.construire(
        moteur=moteur,
        version_moteur=VERSION,
        methode=methode,
        precision=_PRECISION,
        parametres=dict(parametres),
        entrees=entrees,
        resultat={**resume, "empreinte_etat": empreinte_etat},
        avertissements=avertissements,
    )


def _entete(statut_rapport: str = "BROUILLON") -> dict[str, str]:
    return {"statut": statut_rapport, "mention_brouillon": MENTION_BROUILLON}


# ========================================================================================= état des résultats
def calculer_etat_des_resultats(entrees: Mapping[str, Any], parametres: Mapping[str, Any]) -> dict[str, Any]:
    """L'état des résultats (BROUILLON) d'une période, depuis les mouvements normalisés. Produits : crédit moins débit ;
    charges : débit moins crédit ; résultat avant impôts = produits − charges (le plan ne porte aucun compte d'impôt
    sur le résultat). Marge brute : seulement si les comptes de coûts directs sont DÉCLARÉS
    (`configuration.rapports.comptes_couts_directs`) ; sinon « non calculable, manque X »."""
    lignes: list[dict[str, str]] = []
    produits = charges = _ZERO
    directs = set(entrees["couts_directs"] or ())
    couts_directs = _ZERO
    for compte in entrees["comptes"]:
        if compte["type"] not in _TYPES_RESULTAT:
            continue
        net = _net(compte)
        lignes.append(
            {"section": compte["type"], "compte": compte["compte"], "nom": compte["nom"], "montant": _txt(net)}
        )
        if compte["type"] == "produits":
            produits += net
        else:
            charges += net
            if compte["compte"] in directs:
                couts_directs += net
    hors_etat = sum(1 for compte in entrees["comptes"] if compte["type"] not in _TYPES_RESULTAT)
    if entrees["couts_directs"] is None:
        marge = {
            "statut": "NON_CALCULABLE",
            "manque": "configuration.rapports.comptes_couts_directs : la liste des comptes de charges que le "
            "propriétaire "
            "range dans les coûts directs (le plan comptable ne le dit pas ; aucun compte n'est supposé)",
        }
    elif produits == 0:
        marge = {
            "statut": "NON_CALCULABLE",
            "manque": "aucun produit comptabilisé dans la période : pas de marge à établir",
        }
    else:
        brute = produits - couts_directs
        marge = {
            "statut": "CALCULEE",
            "montant": _txt(brute),
            "pourcentage_des_produits": _pct(brute, produits),
            "comptes_couts_directs": sorted(directs),
        }
    net_periode = produits - charges
    complet = {
        "type": "ETAT_DES_RESULTATS",
        **_entete(),
        "sources": [dict(source) for source in entrees.get("sources", ())],
        "periode": {"debut": entrees["debut"], "fin": entrees["fin"]},
        "devise": "CAD",
        "total_produits": _txt(produits),
        "total_charges": _txt(charges),
        "resultat_avant_impots": _txt(net_periode),
        "marge_brute": marge,
        "lignes": lignes,
        "comptes_de_bilan_mouvementes": hors_etat,
        "completude": {
            "ecritures_definitives": entrees["ecritures_definitives"],
            "brouillons_non_comptabilises": entrees["brouillons"],
            "periode_close": entrees["periode_close"],
        },
        "plan_comptable_version": entrees["plan_comptable_version"],
    }
    resume = {
        "total_produits": complet["total_produits"],
        "total_charges": complet["total_charges"],
        "resultat_avant_impots": complet["resultat_avant_impots"],
        "marge_brute_statut": marge["statut"],
        "brouillons_non_comptabilises": entrees["brouillons"],
        "lignes": len(lignes),
    }
    avertissements = [
        "Écritures DÉFINITIVES seulement ; les brouillons sont comptés à part, jamais additionnés.",
        "Résultat AVANT impôts : le plan comptable ne porte aucun compte d'impôt sur le résultat.",
        "Aucun ajustement de fin de période (amortissement, provisions, régularisations) n'est passé par ce rapport.",
        MENTION_BROUILLON + ".",
    ]
    if entrees["brouillons"]:
        avertissements.append(
            f"{entrees['brouillons']} écriture(s) en brouillon dans la période ne sont pas comptées : l'état est "
            f"incomplet "
            "tant qu'une personne ne les a pas validées (N4)."
        )
    recu = _recu(
        "etat_des_resultats",
        "Somme exacte, par compte de produits et de charges du plan, des écritures définitives datées dans la période "
        "(produits : crédits − débits ; charges : débits − crédits) ; résultat = produits − charges.",
        parametres,
        entrees,
        complet,
        resume,
        avertissements,
    )
    return {"etat": complet, "recu": recu}


# ==================================================================================================== bilan
def calculer_bilan(entrees: Mapping[str, Any], parametres: Mapping[str, Any]) -> dict[str, Any]:
    """Le bilan (BROUILLON) à une date, depuis les mouvements CUMULÉS depuis le début du registre jusqu'à `au`. Actif ;
    passif ; capitaux propres ; et le résultat cumulé non clos (produits − charges depuis le début du registre : le
    grand
    livre ne porte aucune écriture de clôture d'exercice). Preuve : actif = passif + capitaux propres + résultat cumulé,
    sinon `equilibre` est faux et le rapport le dit."""
    sections: dict[str, list[dict[str, Any]]] = {t: [] for t in _TYPES_BILAN}
    totaux = {t: _ZERO for t in _TYPES_BILAN}
    produits = charges = _ZERO
    anormaux = 0
    for compte in entrees["comptes"]:
        net = _net(compte)
        if compte["type"] in _TYPES_BILAN:
            anormal = net < 0
            anormaux += anormal
            sections[compte["type"]].append(
                {"compte": compte["compte"], "nom": compte["nom"], "montant": _txt(net), "solde_anormal": anormal}
            )
            totaux[compte["type"]] += net
        elif compte["type"] == "produits":
            produits += net
        else:
            charges += net
    cumule = produits - charges
    passif_et_capitaux = totaux["passif"] + totaux["capitaux_propres"] + cumule
    equilibre = totaux["actif"] == passif_et_capitaux
    lignes = [{"section": t, **ligne} for t in _TYPES_BILAN for ligne in sections[t]]
    complet = {
        "type": "BILAN",
        **_entete(),
        "sources": [dict(source) for source in entrees.get("sources", ())],
        "au": entrees["au"],
        "devise": "CAD",
        "total_actif": _txt(totaux["actif"]),
        "total_passif": _txt(totaux["passif"]),
        "total_capitaux_propres": _txt(totaux["capitaux_propres"]),
        "resultat_cumule_non_clos": _txt(cumule),
        "total_passif_et_capitaux": _txt(passif_et_capitaux),
        "equilibre": equilibre,
        "ecart_equilibre": _txt(totaux["actif"] - passif_et_capitaux),
        "comptes_a_solde_anormal": anormaux,
        "lignes": lignes,
        "completude": {
            "ecritures_definitives": entrees["ecritures_definitives"],
            "brouillons_non_comptabilises": entrees["brouillons"],
        },
        "plan_comptable_version": entrees["plan_comptable_version"],
    }
    resume = {
        "total_actif": complet["total_actif"],
        "total_passif": complet["total_passif"],
        "total_capitaux_propres": complet["total_capitaux_propres"],
        "resultat_cumule_non_clos": complet["resultat_cumule_non_clos"],
        "equilibre": equilibre,
        "brouillons_non_comptabilises": entrees["brouillons"],
        "lignes": len(lignes),
    }
    avertissements = [
        "Écritures DÉFINITIVES seulement, depuis le début du registre jusqu'à la date demandée.",
        "Le grand livre ne porte aucune écriture de clôture d'exercice : les produits et charges cumulés sont "
        "montrés en "
        "« résultat cumulé non clos » (aucun report aux bénéfices non répartis n'est fait ici).",
        "Aucun ajustement de fin de période (amortissement, provisions, régularisations) n'est passé par ce rapport.",
        MENTION_BROUILLON + ".",
    ]
    if not equilibre:
        avertissements.append(
            "LE BILAN NE S'ÉQUILIBRE PAS : l'écart est nommé, jamais absorbé ; à expliquer avant tout usage."
        )
    if entrees["brouillons"]:
        avertissements.append(f"{entrees['brouillons']} écriture(s) en brouillon ne sont pas comptées.")
    recu = _recu(
        "bilan_brouillon",
        "Soldes cumulés des écritures définitives par compte d'actif, de passif et de capitaux propres, dans le "
        "sens normal "
        "du compte ; résultat cumulé non clos = produits − charges ; preuve actif = passif + capitaux + résultat.",
        parametres,
        entrees,
        complet,
        resume,
        avertissements,
    )
    return {"etat": complet, "recu": recu}


# ============================================================================================ budget contre réel
def calculer_budget_contre_reel(entrees: Mapping[str, Any], parametres: Mapping[str, Any]) -> dict[str, Any]:
    """Le budget DÉCLARÉ contre le réel du grand livre, mois par mois et compte par compte. Seuls les mois que le budget
    couvre sont comparés ; un mois sans aucune ligne de budget est NOMMÉ (`mois_sans_budget`), jamais comparé à zéro. Un
    compte qui a du réel sans ligne de budget ce mois-là est « non budgété » (montré, jamais absorbé). Écart = réel −
    budget ; favorable si les produits dépassent le budget ou si les charges restent sous le budget."""
    budget: dict[tuple[str, str], Decimal] = {
        (ligne["compte"], ligne["mois"]): _dec(ligne["montant"]) for ligne in entrees["budget"]["lignes"]
    }
    reel: dict[tuple[str, str], Decimal] = {
        (ligne["compte"], ligne["mois"]): _dec(ligne["montant"]) for ligne in entrees["reel"]
    }
    types = {ligne["compte"]: (ligne["type"], ligne["nom"]) for ligne in entrees["reel"]}
    for fiche in entrees["comptes_budget"]:
        types[fiche["compte"]] = (fiche["type"], fiche["nom"])
    mois_demandes = list(entrees["mois"])
    mois_couverts = sorted({mois for (_c, mois) in budget} & set(mois_demandes))
    mois_sans_budget = [m for m in mois_demandes if m not in mois_couverts]
    base = {
        "type": "BUDGET_CONTRE_REEL",
        **_entete(),
        "sources": [dict(source) for source in entrees.get("sources", ())],
        "devise": "CAD",
        "budget": {"budget_id": entrees["budget"]["budget_id"], "version": entrees["budget"]["version"]},
        "mois_demandes": mois_demandes,
        "mois_compares": mois_couverts,
        "mois_sans_budget": mois_sans_budget,
    }
    if not mois_couverts:
        complet = {
            **base,
            "statut": "NON_CALCULABLE",
            "lignes": [],
            "non_budgetes": [],
            "manque": "le budget déclaré ne couvre aucun des mois demandés : déclarer le budget de "
            + ", ".join(mois_demandes)
            + " (m5_etablir_budget)",
        }
        resume = {"statut": "NON_CALCULABLE", "mois_compares": 0}
        recu = _recu(
            "budget_contre_reel",
            "Budget déclaré contre réel du grand livre, mois par mois.",
            parametres,
            entrees,
            complet,
            resume,
            ["Aucun mois de la période n'est budgété : rien n'est comparé (jamais un budget à zéro)."],
        )
        return {"etat": complet, "recu": recu}
    par_compte: dict[str, dict[str, Decimal]] = {}
    non_budgetes: dict[str, Decimal] = {}
    for (compte, mois), montant in sorted(budget.items()):
        if mois not in mois_couverts:
            continue
        ligne = par_compte.setdefault(compte, {"budget": _ZERO, "reel": _ZERO})
        ligne["budget"] += montant
        ligne["reel"] += reel.get((compte, mois), _ZERO)
    for (compte, mois), montant in sorted(reel.items()):
        if mois in mois_couverts and (compte, mois) not in budget and montant != 0:
            non_budgetes[compte] = non_budgetes.get(compte, _ZERO) + montant
    lignes = []
    totaux = {"produits": [_ZERO, _ZERO], "charges": [_ZERO, _ZERO]}
    for compte in sorted(par_compte):
        genre, nom = types[compte]
        valeurs = par_compte[compte]
        ecart = valeurs["reel"] - valeurs["budget"]
        if ecart == 0:
            sens = "NUL"
        elif (genre == "produits") == (ecart > 0):
            sens = "FAVORABLE"
        else:
            sens = "DEFAVORABLE"
        totaux[genre][0] += valeurs["budget"]
        totaux[genre][1] += valeurs["reel"]
        lignes.append(
            {
                "compte": compte,
                "nom": nom,
                "type": genre,
                "budget": _txt(valeurs["budget"]),
                "reel": _txt(valeurs["reel"]),
                "ecart": _txt(ecart),
                "ecart_pct_du_budget": _pct(ecart, valeurs["budget"]),
                "sens": sens,
            }
        )
    lignes_nb = [
        {"compte": c, "nom": types[c][1], "type": types[c][0], "reel": _txt(m)} for c, m in sorted(non_budgetes.items())
    ]
    resultat_budget = totaux["produits"][0] - totaux["charges"][0]
    resultat_reel = totaux["produits"][1] - totaux["charges"][1]
    complet = {
        **base,
        "statut": "CALCULEE",
        "totaux": {
            "produits": {"budget": _txt(totaux["produits"][0]), "reel": _txt(totaux["produits"][1])},
            "charges": {"budget": _txt(totaux["charges"][0]), "reel": _txt(totaux["charges"][1])},
            "resultat_budgete": _txt(resultat_budget),
            "resultat_reel_des_comptes_budgetes": _txt(resultat_reel),
            "ecart_resultat": _txt(resultat_reel - resultat_budget),
        },
        "lignes": lignes,
        "non_budgetes": lignes_nb,
        "completude": {
            "ecritures_definitives": entrees["ecritures_definitives"],
            "brouillons_non_comptabilises": entrees["brouillons"],
        },
    }
    resume = {
        "statut": "CALCULEE",
        "mois_compares": len(mois_couverts),
        "mois_sans_budget": len(mois_sans_budget),
        "ecart_resultat": complet["totaux"]["ecart_resultat"],
        "comptes_non_budgetes": len(lignes_nb),
        "brouillons_non_comptabilises": entrees["brouillons"],
    }
    avertissements = [
        "Le budget est celui que la direction a DÉCLARÉ (m5_etablir_budget), version "
        f"{entrees['budget']['version']} ; M5 n'en invente aucun.",
        "Réel : écritures DÉFINITIVES seulement.",
        MENTION_BROUILLON + ".",
    ]
    if mois_sans_budget:
        avertissements.append("Mois sans budget, non comparés : " + ", ".join(mois_sans_budget) + ".")
    if lignes_nb:
        avertissements.append(f"{len(lignes_nb)} compte(s) ont du réel sans ligne de budget : montrés à part.")
    if entrees["brouillons"]:
        avertissements.append(f"{entrees['brouillons']} écriture(s) en brouillon ne sont pas comptées dans le réel.")
    recu = _recu(
        "budget_contre_reel",
        "Budget déclaré (par compte et par mois) contre le réel du grand livre ; écart = réel − budget ; "
        "pourcentage de l'écart sur le budget (ROUND_HALF_UP, deux décimales).",
        parametres,
        entrees,
        complet,
        resume,
        avertissements,
    )
    return {"etat": complet, "recu": recu}


# ============================================================================== rentabilité par service / ville
def calculer_rentabilite_par_axe(entrees: Mapping[str, Any], parametres: Mapping[str, Any]) -> dict[str, Any]:
    """La marge réelle par SERVICE ou par VILLE, à partir des rentabilités de chantier DÉJÀ calculées par M5 (coût
    complet seulement : un coût partiel est exclu et compté, jamais mis dans une moyenne) et de la dimension que M4
    publie à la fin des travaux. Une dimension absente d'un chantier le place dans « sans dimension » (compté, dit) ;
    absente de TOUS les chantiers, la rentabilité est « non calculable, manque X » : jamais zéro, jamais une ville
    devinée."""
    axe = parametres["axe"]
    complets = []
    exclus_partiels = 0
    exclus_provisoires = 0
    sans_dimension = 0
    for chantier in entrees["chantiers"]:
        if chantier["marge_reelle"] is None or chantier["cout_reel"] is None or chantier["prix_facture"] is None:
            exclus_partiels += 1
            continue
        if chantier.get("prix_definitif") is not True:
            exclus_provisoires += 1
            continue
        if not chantier.get(axe):
            sans_dimension += 1
            continue
        complets.append(chantier)
    base = {
        "type": "RENTABILITE_PAR_AXE",
        **_entete(),
        "sources": [dict(source) for source in entrees.get("sources", ())],
        "axe": axe,
        "devise": "CAD",
        "chantiers_examines": len(entrees["chantiers"]),
        "exclus_cout_partiel": exclus_partiels,
        "exclus_prix_provisoire": exclus_provisoires,
        "sans_dimension": sans_dimension,
    }
    if not entrees["chantiers"]:
        manque = "aucune rentabilité de chantier calculée (m5.rentabilite_chantier) : rien à regrouper"
    elif not complets and sans_dimension == 0:
        manque = (
            "aucun chantier à coût complet ET à prix définitif : la marge d'un coût partiel ou d'un prix encore "
            "provisoire (jalons non tous émis) n'est jamais regroupée"
        )
    elif not complets:
        manque = (
            f"la dimension « {axe} » est absente de tous les chantiers à coût complet : M4 la publie à la fin des "
            "travaux (m4.travaux_termines) mais M5 n'en a reçu aucune ; elle ne se devine pas"
        )
    else:
        manque = None
    if manque is not None:
        complet = {**base, "statut": "NON_CALCULABLE", "manque": manque, "groupes": []}
        resume = {
            "statut": "NON_CALCULABLE",
            "groupes": 0,
            "exclus_cout_partiel": exclus_partiels,
            "exclus_prix_provisoire": exclus_provisoires,
            "sans_dimension": sans_dimension,
        }
    else:
        groupes: dict[str, list[Decimal]] = {}
        compte: dict[str, int] = {}
        for chantier in complets:
            cumul = groupes.setdefault(chantier[axe], [_ZERO, _ZERO, _ZERO])
            cumul[0] += _dec(chantier["prix_facture"])
            cumul[1] += _dec(chantier["cout_reel"])
            cumul[2] += _dec(chantier["marge_reelle"])
            compte[chantier[axe]] = compte.get(chantier[axe], 0) + 1
        lignes = [
            {
                axe: valeur,
                "chantiers": compte[valeur],
                "ventes": _txt(c[0]),
                "cout_reel": _txt(c[1]),
                "marge_reelle": _txt(c[2]),
                "marge_pct_des_ventes": _pct(c[2], c[0]),
            }
            for valeur, c in sorted(groupes.items())
        ]
        total = [sum((g[i] for g in groupes.values()), _ZERO) for i in range(3)]
        complet = {
            **base,
            "statut": "CALCULEE",
            "groupes": lignes,
            "total": {
                "chantiers": len(complets),
                "ventes": _txt(total[0]),
                "cout_reel": _txt(total[1]),
                "marge_reelle": _txt(total[2]),
                "marge_pct_des_ventes": _pct(total[2], total[0]),
            },
        }
        resume = {
            "statut": "CALCULEE",
            "groupes": len(lignes),
            "chantiers": len(complets),
            "marge_reelle": complet["total"]["marge_reelle"],
            "exclus_cout_partiel": exclus_partiels,
            "exclus_prix_provisoire": exclus_provisoires,
            "sans_dimension": sans_dimension,
        }
    avertissements = [
        "Marge réelle des chantiers à coût COMPLET et à prix DÉFINITIF seulement ; un coût partiel ou un prix encore "
        "provisoire est exclu et compté.",
        f"La dimension « {axe} » vient de M4 (m4.travaux_termines), reçue par M5 à la fin des travaux ; elle ne se "
        f"déduit pas.",
        "Ce n'est pas la marge comptable du grand livre : c'est la rentabilité par chantier de M5 (matériaux, "
        "main-d'œuvre).",
        MENTION_BROUILLON + ".",
    ]
    recu = _recu(
        "rentabilite_par_axe",
        "Regroupement, par valeur de la dimension, de la marge réelle des chantiers à coût complet "
        "(ventes, coût, marge additionnés exactement ; pourcentage ROUND_HALF_UP, deux décimales).",
        parametres,
        entrees,
        complet,
        resume,
        avertissements,
    )
    return {"etat": complet, "recu": recu}


# =========================================================================================== rapport de direction
def section(
    ident: str,
    titre: str,
    statut: str,
    *,
    faits: Sequence[Mapping[str, Any]] = (),
    hypotheses: Sequence[str] = (),
    manquantes: Sequence[Mapping[str, str]] = (),
    recu: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Une section du rapport de direction : les FAITS (chiffres tirés d'un rapport, avec leur source), les HYPOTHÈSES
    et les DONNÉES MANQUANTES (ce qu'il faut déclarer) sont séparés, jamais mêlés."""
    return {
        "id": ident,
        "titre": titre,
        "statut": statut,
        "faits": [dict(f) for f in faits],
        "hypotheses": list(hypotheses),
        "donnees_manquantes": [dict(m) for m in manquantes],
        "recu_empreinte": recu["empreinte"] if recu is not None else None,
    }


def composer_rapport_mensuel(
    periode: str, sections: Sequence[Mapping[str, Any]], parametres: Mapping[str, Any]
) -> dict[str, Any]:
    """Le rapport mensuel de direction (BROUILLON) : les sections, et un reçu dont les entrées sont l'empreinte de
    chaque section et de son reçu. Rien n'est recalculé ici : chaque chiffre vient du rapport de sa section."""
    entrees = {
        "periode": periode,
        "sections": [
            {
                "id": s["id"],
                "statut": s["statut"],
                "recu_empreinte": s["recu_empreinte"],
                "empreinte_section": encodage.empreinte("m5.rapport_direction.section.v1", dict(s)),
            }
            for s in sections
        ],
    }
    complet = {
        "type": "RAPPORT_DIRECTION_MENSUEL",
        **_entete(),
        "periode": periode,
        "devise": "CAD",
        "sections": [dict(s) for s in sections],
    }
    manquantes = sum(len(s["donnees_manquantes"]) for s in sections)
    resume = {
        "sections": len(sections),
        "sections_non_calculables": sum(1 for s in sections if s["statut"] == "NON_CALCULABLE"),
        "donnees_manquantes": manquantes,
    }
    recu = _recu(
        "rapport_direction_mensuel",
        "Composition de sections dont chaque chiffre vient du rapport de sa section (état des résultats, bilan, "
        "budget, rentabilité, pré-audit) ; aucun calcul propre.",
        parametres,
        entrees,
        complet,
        resume,
        ["Chaque section distingue faits, hypothèses et données manquantes.", MENTION_BROUILLON + "."],
    )
    return {"etat": complet, "recu": recu}


# ======================================================================================================= rejeu
MOTEURS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]] = {
    "etat_des_resultats": calculer_etat_des_resultats,
    "bilan_brouillon": calculer_bilan,
    "budget_contre_reel": calculer_budget_contre_reel,
    "rentabilite_par_axe": calculer_rentabilite_par_axe,
}


def rejouer(recu: Any, moteurs: Mapping[str, Callable[..., Any]] | None = None) -> tuple[bool, str]:
    """Refait le calcul d'un reçu de rapport à partir de ses `entrees` et compare les empreintes. `(True, "")` si le
    rejeu redonne EXACTEMENT le reçu ; sinon `(False, raison)` (reçu retouché, compact — sans entrées —, moteur inconnu
    ou chiffres différents). Un reçu compact se vérifie (`recu_calcul.verifier`) mais ne se rejoue pas hors ligne."""
    valide, raison = recu_calcul.verifier(recu)
    if not valide:
        return False, raison
    if "entrees" not in recu:
        return (
            False,
            "reçu compact (sans entrées) : le rejeu hors ligne est impossible ; rappeler l'outil sur les mêmes "
            "registres",
        )
    table = dict(MOTEURS if moteurs is None else moteurs)
    moteur = table.get(recu["moteur"])
    if moteur is None:
        return False, f"moteur {recu['moteur']!r} inconnu des rapports"
    try:
        refait = moteur(recu["entrees"], recu["parametres"])
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return False, f"entrées inexploitables : {type(exc).__name__}"
    recu_refait = refait["recu"]
    if recu_refait["empreinte"] != recu["empreinte"]:
        return False, "le rejeu ne redonne pas la même empreinte : les chiffres du reçu ne sont pas ceux des entrées"
    return True, ""


def periode_en_dates(debut: Any, fin: Any) -> tuple[tuple[date, date] | None, dict[str, str] | None]:
    """`debut` et `fin` (AAAA-MM-JJ, inclus) lus et contrôlés : début au plus tard à fin, 400 jours au plus."""
    d, f = _jour(debut), _jour(fin)
    if d is None or f is None:
        return None, _verdict("REJ-RAPPORT-DATE-INVALIDE", f"debut {debut!r} et fin {fin!r} : AAAA-MM-JJ exigé")
    if f < d or (f - d).days >= _JOURS_PERIODE_MAX:
        return None, _verdict(
            "REJ-RAPPORT-PERIODE-INVALIDE",
            f"période inversée ou de plus de {_JOURS_PERIODE_MAX} jours : {debut} -> {fin}",
        )
    return (d, f), None
