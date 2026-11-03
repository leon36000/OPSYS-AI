"""Dossiers de décision C1 (camion/équipement) et C2 (bâtiment commercial) de M5 (ANALYSE-M5 §2.6).

Outils de LECTURE qui produisent un DOSSIER DE DÉCISION chiffré déterministe, jamais une décision ni un conseil
d'investissement personnalisé :

- C1 : mensualité du prêt (amortissement du moteur, convention canadienne), coût total du crédit, DSCR
  (revenus additionnels / service de la dette avec assurance et entretien), seuil de rentabilité (revenus qui
  couvrent le service), stress nommé (revenus −20 %, taux +2 points, combiné), liquidités après mise de fonds,
  impact sur la trésorerie à partir de la prévision M5 existante quand l'appelant la joint (optionnel).
- C2 : mensualité hypothécaire, coût d'occupation (mensualité + charges), écart contre le loyer évité, DSCR
  (revenus locatifs + loyer évité / coût d'occupation), stress nommé (mêmes combinaisons), liquidités après mise
  de fonds et frais, dossier pour le prêteur (questions à poser, jamais un dépôt).

CHIFFRES : `Decimal` exact, montants au cent, taux en fractions. Chaque dossier rend un REÇU rejouable
(`recu_calcul`) et s'inscrit au registre des moteurs (`moteur_calcul.MOTEURS`) pour `rejouer`.

FAIL-CLOSED : aucune valeur par défaut inventée. Entrée manquante = refus `REJ-CONSEIL-DONNEE-MANQUANTE` qui dit
quoi fournir. La DPA/CCA dépend de taux fiscaux : ce module lit les identifiants de la base fiscale versionnée
de M5 (`fed.impot.dpa.*`, jamais en dur) ; s'ils sont absents, le dossier le dit (`NON_RENSEIGNEE`), jamais un
taux supposé. Les liquidités sont déclarées par l'appelant (jamais lues d'un registre ici : module pur) ;
absentes, la rubrique trésorerie est non calculable, pas zéro.

GARDES : objet de la liste fermée d'exploitation (garde NC 31-103 du moteur : `vehicule`, `equipement`,
`outillage`, `immeuble_exploitation` ; un titre est refusé `REJ-CALC-OBJET-HORS-PERIMETRE`) ; aucune
recommandation (le dossier dit « pas une recommandation », jamais « vous devriez »).

Module pur : aucune horloge, aucun registre, aucun réseau, aucune écriture.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from . import analyse
from . import maths_financieres as mf
from . import moteur_calcul as mc

__all__ = ["VERSION", "preparer_dossier_camion", "preparer_dossier_batiment"]

VERSION = mc.VERSION

_OBJETS_C1 = frozenset({"vehicule", "equipement", "outillage"})
_OBJET_C2 = "immeuble_exploitation"
_PRECISION_TAUX_STRESS = Decimal("0.0001")

_METHODE_C1 = (
    "Mensualité = versement constant du moteur (convention canadienne semestrielle : i = (1 + j/2)^(2/12) − 1) ; "
    "service de la dette = mensualité + assurance + entretien saisis ; DSCR = revenus additionnels / service ; "
    "seuil de rentabilité = service (revenus qui le couvrent) ; stress nommé par l'appelant (revenus −20 %, "
    "taux +2 points, combiné) ; liquidités après mise de fonds = liquidités − mise de fonds ; "
    "total décaissé = mise de fonds + mensualités + assurance + entretien sur la durée."
)
_METHODE_C2 = (
    "Mensualité hypothécaire = versement constant du moteur (convention canadienne semestrielle) ; "
    "coût d'occupation = mensualité + charges saisies ; écart contre loyer = loyer évité − coût d'occupation ; "
    "DSCR = (loyer évité + revenus locatifs) / coût d'occupation ; stress nommé (revenus −20 %, taux +2 points, "
    "combiné) ; liquidités après achat = liquidités − mise de fonds − frais ; dossier prêteur = questions à poser."
)

_REGLES_DPA = (
    "fed.impot.dpa.taux_par_categorie",
    "qc.impot.dpa.taux_par_categorie",
    "fed.impot.dpa.regle_demi_annee",
)
_TAUX_STRESS_POINTS = Decimal("0.02")
_FACTEUR_REVENUS_STRESS = Decimal("0.80")
_CENT = Decimal("0.01")
_DSCR_PRECISION = Decimal("0.0001")


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, mc.verdicts_calcul.construire_verdict(code, detail)


def _refus_conseil(code: str, detail: str) -> tuple[None, dict[str, str]]:
    from . import verdicts_operations

    return None, verdicts_operations.construire_verdict(code, detail)


def _lire_objet(brut: Any, admis: frozenset[str]) -> tuple[str | None, dict[str, str] | None]:
    if type(brut) is not str or brut not in admis:
        return mc._objet(brut)
    return brut, None


def _montant(brut: Any, nom: str, *, minimum: Decimal = Decimal(0)) -> tuple[Decimal | None, dict | None]:
    return mc._montant(brut, nom, minimum=minimum)


def _montant_strict(brut: Any, nom: str) -> tuple[Decimal | None, dict | None]:
    return mc._montant(brut, nom, strictement_positif=True)


def _taux(brut: Any, nom: str) -> tuple[Decimal | None, dict | None]:
    return mc._taux(brut, nom)


def _date_iso(brut: Any, nom: str) -> tuple[str | None, dict[str, str] | None]:
    from datetime import date

    if type(brut) is not str:
        return _refus("REJ-CALC-FLUX-INVALIDES", f"{nom} : date AAAA-MM-JJ exigée (reçu {brut!r})")
    try:
        jour = date.fromisoformat(brut)
    except ValueError:
        return _refus("REJ-CALC-FLUX-INVALIDES", f"{nom} : date AAAA-MM-JJ réelle exigée (reçu {brut!r})")
    if jour.isoformat() != brut:
        return _refus("REJ-CALC-FLUX-INVALIDES", f"{nom} : date AAAA-MM-JJ réelle exigée (reçu {brut!r})")
    return brut, None


def _convention(brut: Any) -> tuple[str | None, dict[str, str] | None]:
    if type(brut) is not str or brut not in mf.CONVENTIONS_TAUX:
        return _refus("REJ-CALC-CONVENTION-INCONNUE",
                      f"convention : une de {sorted(mf.CONVENTIONS_TAUX)} (reçu {brut!r})")
    return brut, None


def _cles(brut: Any, permises: set[str], requises: set[str]) -> tuple[dict | None, dict | None]:
    return mc._cles(brut, permises, requises)


def _duree_mois(brut: Any, nom: str) -> tuple[int | None, dict | None]:
    return mc._entier(brut, nom, "REJ-CALC-DUREE-INVALIDE", 1, mc.MOIS_MAX)


def _duree_annees(brut: Any, nom: str) -> tuple[int | None, dict | None]:
    return mc._entier(brut, nom, "REJ-CALC-DUREE-INVALIDE", 1, mc.ANNEES_MAX)


def _txt_cent(valeur: Decimal) -> str:
    with localcontext(mf.CONTEXTE):
        return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), ".2f")


def _txt_dscr(valeur: Decimal) -> str:
    with localcontext(mf.CONTEXTE):
        return format(valeur.quantize(_DSCR_PRECISION, rounding=ROUND_HALF_UP), ".4f")


def _mensualite(principal: Decimal, taux_annuel: Decimal, convention: str,
                mois: int) -> tuple[Decimal, dict[str, str] | None]:
    try:
        tableau = mf.amortir(principal, mf.taux_periodique(taux_annuel, "mensuelle", convention), mois)
    except ArithmeticError as exc:
        return Decimal(0), mc.verdicts_calcul.construire_verdict("REJ-CALC-AMORTISSEMENT-IMPOSSIBLE", str(exc))
    return tableau["versement"], None


def _fiscalite_dpa(aujourd_hui: str | None) -> dict[str, Any]:
    """L'état des taux de DPA/CCA dans la base fiscale versionnée : jamais un taux en dur.

    La base de M5 ne porte aujourd'hui aucun `fed.impot.dpa.*` : le statut est `NON_RENSEIGNEE` et le détail dit
    la source officielle à fournir (au CPA). Si un jour la base les porte, le dossier citera leurs empreintes.
    """
    from . import base_fiscale

    if aujourd_hui is None:
        return {
            "statut": "NON_RENSEIGNEE",
            "regles_cherchees": list(_REGLES_DPA),
            "regles_resolues": [],
            "detail": (
                "Aucun taux de DPA/CCA n'est modélisé : taux fiscaux à lire dans la base fiscale versionnée "
                "de M5 (fed.impot.dpa.taux_par_categorie, qc.impot.dpa.taux_par_categorie, "
                "fed.impot.dpa.regle_demi_annee) ; absents ou sans deux réviseurs, source officielle requise "
                "(CPA). Aucune déduction n'est chiffrée."
            ),
        }
    try:
        base, erreur = base_fiscale.charger_base_par_defaut()
    except (OSError, ValueError):
        base, erreur = None, {"detail": "base fiscale illisible"}
    if erreur is not None or base is None:
        return {
            "statut": "NON_RENSEIGNEE",
            "regles_cherchees": list(_REGLES_DPA),
            "regles_resolues": [],
            "detail": (
                "Base fiscale illisible : taux fiscaux à fournir par source officielle (CPA). "
                "Aucune déduction n'est chiffrée."
            ),
        }
    resolues = []
    for identifiant in _REGLES_DPA:
        regle, _refus_regle = base_fiscale.resoudre(base, identifiant, aujourd_hui, mode="officiel")
        if regle is not None:
            resolues.append({"identifiant": identifiant, "empreinte": regle["empreinte"],
                             "statut_revue": regle["statut_revue"]})
    if not resolues:
        return {
            "statut": "NON_RENSEIGNEE",
            "regles_cherchees": list(_REGLES_DPA),
            "regles_resolues": [],
            "detail": (
                "Taux de DPA/CCA non renseignés ou non approuvés dans la base fiscale versionnée de M5 : "
                "source officielle requise (CPA). Aucune déduction n'est chiffrée."
            ),
        }
    return {
        "statut": "PARTIELLE" if len(resolues) < len(_REGLES_DPA) else "RENSEIGNEE",
        "regles_cherchees": list(_REGLES_DPA),
        "regles_resolues": resolues,
        "detail": (
            "Règles lues dans la base fiscale versionnée de M5 (empreintes citées) : à valider avec le CPA ; "
            "aucune déduction n'est chiffrée par ce dossier."
        ),
    }


def _garde_c1() -> str:
    return (
        "Information générale calculée sur les hypothèses fournies par l'appelant : ni conseil en placement "
        "personnalisé, ni recommandation d'achat (NC 31-103) ; ce dossier n'est pas une recommandation : "
        "il chiffre la mensualité, le coût, le DSCR, le seuil, le stress et les liquidités, à valider avec "
        "le prêteur et le CPA avant toute décision."
    )


def _preparer(
    *,
    moteur: str,
    methode: str,
    objet: str,
    principal: Decimal,
    taux_annuel: Decimal,
    convention: str,
    mois: int,
    normalisees: dict[str, Any],
    warn: list[str],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    mensualite, refus = _mensualite(principal, taux_annuel, convention, mois)
    if refus is not None:
        return None, refus
    taux_stress = (taux_annuel + _TAUX_STRESS_POINTS).quantize(_PRECISION_TAUX_STRESS,
                                                                rounding=ROUND_HALF_UP)
    if not Decimal(0) <= taux_stress <= mc.TAUX_MAX:
        return _refus("REJ-CALC-TAUX-HORS-BORNES",
                      "taux_annuel : le stress (+2 points) sort des bornes ; saisir un taux plus bas")
    mensualite_stress, refus = _mensualite(principal, taux_stress, convention, mois)
    if refus is not None:
        return None, refus
    interets = mensualite * mois - principal
    resultat = {
        "objet": objet,
        "mensualite": _txt_cent(mensualite),
        "mensualite_stress_taux_plus_2_points": _txt_cent(mensualite_stress),
        "nombre_versements": mois,
        "montant_emprunte": _txt_cent(principal),
        "total_interets": _txt_cent(interets),
        "cout_total_credit": _txt_cent(mensualite * mois),
    }
    avertissements = [mc.AVERTISSEMENT_NC_31_103, mc.AVERTISSEMENT_FISCAL, *warn]
    return {"recu": mc._recu(moteur, methode, {"conventions": "taux mensuel effectif"},
                             normalisees, resultat, avertissements)}, None


def preparer_dossier_camion(entrees: Any, parametres: Any = None) -> tuple[dict | None, dict | None]:
    """C1 : dossier de décision chiffré pour un achat de camion/équipement (lecture seule)."""
    cles = {"objet", "prix_achat", "mise_de_fonds", "taux_annuel", "convention", "duree_mois",
            "assurance_mensuelle", "entretien_mensuel", "revenus_mensuels_additionnels", "liquidites_actuelles",
            "date_reference"}
    requises = cles - {"liquidites_actuelles", "date_reference"}
    if isinstance(entrees, Mapping) and "revenus_mensuels_additionnels" not in entrees:
        return _refus_conseil("REJ-CONSEIL-DONNEE-MANQUANTE",
                              "revenus_mensuels_additionnels : montant mensuel attendu de l'actif (texte décimal) ; "
                              "sans lui, ni DSCR ni seuil ne sont calculables")
    lu, verdict = _cles(entrees, cles, requises) if isinstance(entrees, Mapping) else _refus(
        "REJ-CALC-FLUX-INVALIDES", "entrées : objet attendu")
    if verdict:
        return None, verdict
    objet, verdict = _lire_objet(lu["objet"], _OBJETS_C1)
    if verdict:
        return None, verdict
    prix, verdict = _montant_strict(lu["prix_achat"], "prix_achat")
    if verdict:
        return None, verdict
    mise, verdict = _montant(lu["mise_de_fonds"], "mise_de_fonds")
    if verdict:
        return None, verdict
    if mise >= prix:
        return _refus("REJ-CALC-MONTANT-INVALIDE", "mise_de_fonds : doit être inférieure au prix d'achat")
    taux, verdict = _taux(lu["taux_annuel"], "taux_annuel")
    if verdict:
        return None, verdict
    convention, verdict = _convention(lu["convention"])
    if verdict:
        return None, verdict
    duree, verdict = _duree_mois(lu["duree_mois"], "duree_mois")
    if verdict:
        return None, verdict
    assurance, verdict = _montant(lu["assurance_mensuelle"], "assurance_mensuelle")
    if verdict:
        return None, verdict
    entretien, verdict = _montant(lu["entretien_mensuel"], "entretien_mensuel")
    if verdict:
        return None, verdict
    if "revenus_mensuels_additionnels" not in lu:
        return _refus_conseil("REJ-CONSEIL-DONNEE-MANQUANTE",
                              "revenus_mensuels_additionnels : montant mensuel attendu de l'actif (texte décimal) ; "
                              "sans lui, ni DSCR ni seuil ne sont calculables")
    revenus, verdict = _montant(lu["revenus_mensuels_additionnels"], "revenus_mensuels_additionnels")
    if verdict:
        return None, verdict
    liquidites = None
    if lu.get("liquidites_actuelles") is not None:
        liquidites, verdict = _montant(lu["liquidites_actuelles"], "liquidites_actuelles")
        if verdict:
            return None, verdict
    date_reference = None
    if lu.get("date_reference") is not None:
        date_reference, verdict = _date_iso(lu["date_reference"], "date_reference")
        if verdict:
            return None, verdict
    principal = prix - mise
    normalisees = {
        "objet": objet, "prix_achat": format(prix, ".2f"), "mise_de_fonds": format(mise, ".2f"),
        "taux_annuel": mc._txt_norme(taux), "convention": convention, "duree_mois": duree,
        "assurance_mensuelle": format(assurance, ".2f"), "entretien_mensuel": format(entretien, ".2f"),
        "revenus_mensuels_additionnels": format(revenus, ".2f"),
        "liquidites_actuelles": None if liquidites is None else format(liquidites, ".2f"),
        "date_reference": date_reference,
    }
    with localcontext(mf.CONTEXTE):
        service = None
        base, verdict = _preparer(
            moteur="dossier_camion_equipement", methode=_METHODE_C1, objet=objet, principal=principal,
            taux_annuel=taux, convention=convention, mois=duree, normalisees=normalisees,
            warn=["L'assurance et l'entretien sont ceux saisis par l'appelant, jamais des barèmes supposés.",
                  "Le prêt est remboursé à la fin de la durée saisie ; pénalités du prêteur non modélisées."])
        if verdict:
            return None, verdict
        resultat = base["recu"]["resultat"]
        mensualite = Decimal(resultat["mensualite"])
        mensualite_stress = Decimal(resultat["mensualite_stress_taux_plus_2_points"])
        frais_mensuels = assurance + entretien
        service = mensualite + frais_mensuels
        service_stress = mensualite_stress + frais_mensuels
        if service <= 0:
            return _refus("REJ-CALC-MONTANT-INVALIDE", "service de la dette nul : mensualité et frais à vérifier")
        dscr = revenus / service
        dscr_stress_taux = revenus / service_stress
        revenus_stress = revenus * _FACTEUR_REVENUS_STRESS
        dscr_stress_revenus = revenus_stress / service
        dscr_combine = revenus_stress / service_stress
        total = mise + mensualite * duree + frais_mensuels * duree
        resultat.update({
            "assurance_mensuelle": format(assurance, ".2f"),
            "entretien_mensuel": format(entretien, ".2f"),
            "service_dette_mensuel": _txt_cent(service),
            "revenus_mensuels_additionnels": format(revenus, ".2f"),
            "dscr": _txt_dscr(dscr),
            "seuil_rentabilite_mensuel": _txt_cent(service),
            "total_decaisse": _txt_cent(total),
            "stress": {
                "revenus_moins_20": {
                    "revenus_mensuels": format(revenus_stress.quantize(_CENT, rounding=ROUND_HALF_UP), ".2f"),
                    "mensualite": resultat["mensualite"], "taux_annuel": mc._txt_norme(taux),
                    "service_dette_mensuel": _txt_cent(service), "dscr": _txt_dscr(dscr_stress_revenus),
                },
                "taux_plus_2_points": {
                    "revenus_mensuels": format(revenus, ".2f"),
                    "mensualite": _txt_cent(mensualite_stress),
                    "taux_annuel": format(taux + _TAUX_STRESS_POINTS, ".4f"),
                    "service_dette_mensuel": _txt_cent(service_stress), "dscr": _txt_dscr(dscr_stress_taux),
                },
                "combine": {
                    "revenus_mensuels": format(revenus_stress.quantize(_CENT, rounding=ROUND_HALF_UP), ".2f"),
                    "mensualite": _txt_cent(mensualite_stress),
                    "taux_annuel": format(taux + _TAUX_STRESS_POINTS, ".4f"),
                    "service_dette_mensuel": _txt_cent(service_stress), "dscr": _txt_dscr(dscr_combine),
                },
            },
            "liquidites_apres_mise_de_fonds": (
                None if liquidites is None else _txt_cent(liquidites - mise)),
            "tresorerie_manque": (
                [] if liquidites is not None
                else ["liquidites_actuelles : solde disponible déclaré (texte décimal) ; sans lui, "
                      "les liquidités après l'achat ne sont pas calculables"]),
            "fiscalite": _fiscalite_dpa(date_reference),
            "garde": _garde_c1(),
            "mention_comptable": analyse.MENTION_COMPTABLE,
        })
        avertissements = list(base["recu"]["avertissements"])
    return {"recu": mc._recu("dossier_camion_equipement", _METHODE_C1,
                            {"conventions": "taux mensuel effectif"}, normalisees, resultat,
                            avertissements)}, None


def preparer_dossier_batiment(entrees: Any, parametres: Any = None) -> tuple[dict | None, dict | None]:
    """C2 : dossier de décision chiffré pour un bâtiment commercial (lecture seule)."""
    cles = {"objet", "prix_achat", "mise_de_fonds", "taux_annuel", "convention", "amortissement_annees",
            "frais_achat", "loyer_mensuel_evite", "revenus_locatifs_mensuels", "charges_mensuelles",
            "liquidites_actuelles", "date_reference"}
    requises = cles - {"liquidites_actuelles", "revenus_locatifs_mensuels", "date_reference"}
    if isinstance(entrees, Mapping) and "loyer_mensuel_evite" not in entrees:
        return _refus_conseil("REJ-CONSEIL-DONNEE-MANQUANTE",
                              "loyer_mensuel_evite : loyer mensuel qu'acheter éviterait (texte décimal) ; "
                              "sans lui, ni écart ni DSCR ne sont calculables")
    lu, verdict = _cles(entrees, cles, requises) if isinstance(entrees, Mapping) else _refus(
        "REJ-CALC-FLUX-INVALIDES", "entrées : objet attendu")
    if verdict:
        return None, verdict
    if lu.get("objet") != _OBJET_C2:
        _objet, verdict = mc._objet(lu.get("objet"))
        if verdict:
            return None, verdict
        return _refus("REJ-CALC-FLUX-INVALIDES",
                      f"objet : ce dossier est celui d'un {_OBJET_C2} (reçu {lu.get('objet')!r})")
    prix, verdict = _montant_strict(lu["prix_achat"], "prix_achat")
    if verdict:
        return None, verdict
    mise, verdict = _montant(lu["mise_de_fonds"], "mise_de_fonds")
    if verdict:
        return None, verdict
    if mise >= prix:
        return _refus("REJ-CALC-MONTANT-INVALIDE", "mise_de_fonds : doit être inférieure au prix d'achat")
    taux, verdict = _taux(lu["taux_annuel"], "taux_annuel")
    if verdict:
        return None, verdict
    convention, verdict = _convention(lu["convention"])
    if verdict:
        return None, verdict
    annees, verdict = _duree_annees(lu["amortissement_annees"], "amortissement_annees")
    if verdict:
        return None, verdict
    frais, verdict = _montant(lu["frais_achat"], "frais_achat")
    if verdict:
        return None, verdict
    if "loyer_mensuel_evite" not in lu:
        return _refus_conseil("REJ-CONSEIL-DONNEE-MANQUANTE",
                              "loyer_mensuel_evite : loyer mensuel qu'acheter éviterait (texte décimal) ; "
                              "sans lui, ni écart ni DSCR ne sont calculables")
    loyer, verdict = _montant(lu["loyer_mensuel_evite"], "loyer_mensuel_evite")
    if verdict:
        return None, verdict
    loyers_locatifs = Decimal(0)
    if lu.get("revenus_locatifs_mensuels") is not None:
        loyers_locatifs, verdict = _montant(lu["revenus_locatifs_mensuels"], "revenus_locatifs_mensuels")
        if verdict:
            return None, verdict
    charges, verdict = _montant(lu["charges_mensuelles"], "charges_mensuelles")
    if verdict:
        return None, verdict
    liquidites = None
    if lu.get("liquidites_actuelles") is not None:
        liquidites, verdict = _montant(lu["liquidites_actuelles"], "liquidites_actuelles")
        if verdict:
            return None, verdict
    date_reference = None
    if lu.get("date_reference") is not None:
        date_reference, verdict = _date_iso(lu["date_reference"], "date_reference")
        if verdict:
            return None, verdict
    principal = prix - mise
    mois = annees * 12
    normalisees = {
        "objet": _OBJET_C2, "prix_achat": format(prix, ".2f"), "mise_de_fonds": format(mise, ".2f"),
        "taux_annuel": mc._txt_norme(taux), "convention": convention, "amortissement_annees": annees,
        "frais_achat": format(frais, ".2f"), "loyer_mensuel_evite": format(loyer, ".2f"),
        "revenus_locatifs_mensuels": format(loyers_locatifs, ".2f"),
        "charges_mensuelles": format(charges, ".2f"),
        "liquidites_actuelles": None if liquidites is None else format(liquidites, ".2f"),
        "date_reference": date_reference,
    }
    with localcontext(mf.CONTEXTE):
        base, verdict = _preparer(
            moteur="dossier_batiment_commercial", methode=_METHODE_C2, objet=_OBJET_C2, principal=principal,
            taux_annuel=taux, convention=convention, mois=mois, normalisees=normalisees,
            warn=["Les charges sont celles saisies par l'appelant (taxes foncières, assurances, entretien) : "
                  "jamais des barèmes supposés.",
                  "Le loyer évité est celui déclaré par l'appelant : aucune valeur de marché n'est estimée."])
        if verdict:
            return None, verdict
        resultat = base["recu"]["resultat"]
        mensualite = Decimal(resultat["mensualite"])
        mensualite_stress = Decimal(resultat["mensualite_stress_taux_plus_2_points"])
        occupation = mensualite + charges
        occupation_stress = mensualite_stress + charges
        if occupation <= 0 or occupation_stress <= 0:
            return _refus("REJ-CALC-MONTANT-INVALIDE", "coût d'occupation nul : mensualité et charges à vérifier")
        revenus_totaux = loyer + loyers_locatifs
        revenus_stress = revenus_totaux * _FACTEUR_REVENUS_STRESS
        dscr = revenus_totaux / occupation
        dscr_taux = revenus_totaux / occupation_stress
        dscr_revenus = revenus_stress / occupation
        dscr_combine = revenus_stress / occupation_stress
        resultat.update({
            "mensualite": resultat["mensualite"],
            "cout_occupation_mensuel": _txt_cent(occupation),
            "loyer_mensuel_evite": format(loyer, ".2f"),
            "revenus_locatifs_mensuels": format(loyers_locatifs, ".2f"),
            "ecart_mensuel_contre_loyer": _txt_cent(loyer - occupation),
            "dscr": _txt_dscr(dscr),
            "stress": {
                "revenus_moins_20": {
                    "revenus_mensuels": format(revenus_stress.quantize(_CENT, rounding=ROUND_HALF_UP), ".2f"),
                    "mensualite": resultat["mensualite"], "taux_annuel": mc._txt_norme(taux),
                    "cout_occupation_mensuel": _txt_cent(occupation), "dscr": _txt_dscr(dscr_revenus),
                },
                "taux_plus_2_points": {
                    "revenus_mensuels": format(revenus_totaux, ".2f"),
                    "mensualite": _txt_cent(mensualite_stress),
                    "taux_annuel": format(taux + _TAUX_STRESS_POINTS, ".4f"),
                    "cout_occupation_mensuel": _txt_cent(occupation_stress), "dscr": _txt_dscr(dscr_taux),
                },
                "combine": {
                    "revenus_mensuels": format(revenus_stress.quantize(_CENT, rounding=ROUND_HALF_UP), ".2f"),
                    "mensualite": _txt_cent(mensualite_stress),
                    "taux_annuel": format(taux + _TAUX_STRESS_POINTS, ".4f"),
                    "cout_occupation_mensuel": _txt_cent(occupation_stress), "dscr": _txt_dscr(dscr_combine),
                },
            },
            "liquidites_apres_achat": (
                None if liquidites is None else _txt_cent(liquidites - mise - frais)),
            "tresorerie_manque": (
                [] if liquidites is not None
                else ["liquidites_actuelles : solde disponible déclaré (texte décimal) ; sans lui, "
                      "les liquidités après l'achat ne sont pas calculables"]),
            "fiscalite": _fiscalite_dpa(date_reference),
            "questions_banque_preteur": [
                "Quel taux fixe ou variable le prêteur propose-t-il, et quels frais (dossier, notaire, "
                "expertise) s'ajoutent à la mise de fonds ?",
                "Quelles garanties et quels covenants (dont un DSCR minimal) le prêt exigerait-il ?",
                "Quel est le coût total de sortie d'un bail actuel (pénalités, remise en état) avant d'acheter ?",
                "Quel traitement fiscal (DPA/CCA, TPS/TVQ) le CPA retient-il pour ce bâtiment ?",
            ],
            "garde": (
                "Information générale calculée sur les hypothèses fournies par l'appelant : ni conseil en "
                "placement personnalisé, ni recommandation d'achat (NC 31-103) ; ce dossier n'est pas une "
                "recommandation : il chiffre la mensualité, le coût d'occupation, l'écart contre le loyer, "
                "le DSCR, le stress et les liquidités, à valider avec la banque ou le prêteur, le notaire, "
                "l'avocat et le CPA avant toute décision."
            ),
            "mention_comptable": analyse.MENTION_COMPTABLE,
        })
        avertissements = list(base["recu"]["avertissements"])
    return {"recu": mc._recu("dossier_batiment_commercial", _METHODE_C2,
                            {"conventions": "taux mensuel effectif"}, normalisees, resultat,
                            avertissements)}, None


# Les dossiers composés sont rejouables comme les autres : l'inscription au registre des moteurs se fait à
# l'import (les outils de M5 importent ce module au chargement).
mc.MOTEURS[("dossier_camion_equipement", mc.VERSION)] = (preparer_dossier_camion, ())
mc.MOTEURS[("dossier_batiment_commercial", mc.VERSION)] = (preparer_dossier_batiment, ())
