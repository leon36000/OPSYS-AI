"""Comparaison préparatoire d'une acquisition à partir d'offres documentées et du cash libre réel.

Ce module ne choisit pas de taux, ne calcule pas un financement et n'engage aucune dépense : il compare uniquement
les chiffres présents dans les offres datées. Toute donnée manquante bloque la décision chiffrée.
"""

from __future__ import annotations

from datetime import date
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import analyse, validation

_CONTEXTE = Context(prec=64)


def _refus(code: str, detail: str = "", manque: list[str] | None = None) -> dict[str, Any]:
    verdict = validation.construire_verdict(code, detail=detail)
    if manque:
        verdict["manque"] = manque
    return {"accepte": False, "verdict": verdict}


def _montant(valeur: Any, *, negatif_permis: bool = False) -> Decimal | None:
    if not isinstance(valeur, (str, Decimal)) or isinstance(valeur, bool):
        return None
    try:
        resultat = valeur if isinstance(valeur, Decimal) else Decimal(valeur)
    except (InvalidOperation, ValueError):
        return None
    if (
        not resultat.is_finite()
        or (resultat < 0 and not negatif_permis)
        or resultat.as_tuple().exponent < -2
        or resultat.copy_abs().adjusted() > 11
    ):
        return None
    return resultat


def _offre(offre: Any, nom: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if (not isinstance(offre, dict) or set(offre) != {"source", "mise_de_fonds", "paiement_mensuel", "mois"}
            or not isinstance(offre.get("source"), str) or not offre["source"].strip()):
        return None, _refus("REJ-CAPITAL-OFFRE-SOURCE-ABSENTE", nom)
    mise = _montant(offre.get("mise_de_fonds"))
    paiement = _montant(offre.get("paiement_mensuel"))
    mois = offre.get("mois")
    if mise is None or paiement is None or type(mois) is not int or not 1 <= mois <= 600:
        return None, _refus("REJ-CAPITAL-OFFRE-INVALIDE", nom)
    return {"source": offre["source"].strip(), "mise": mise, "paiement": paiement, "mois": mois}, None


def normaliser_echeanciers(
    echeanciers: Any,
    prix: Any,
    offre_financement: Any,
    offre_location: Any,
) -> tuple[dict[str, list[dict[str, Any]] | None] | None, dict[str, Any] | None]:
    """Valide les flux datés saisis et les rapproche des montants cités, sans créer d'échéance."""
    if echeanciers is None:
        return None, None
    noms = ("achat_comptant", "financement", "location")
    if not isinstance(echeanciers, dict) or set(echeanciers) - set(noms):
        return None, _refus("REJ-CAPITAL-ECHEANCIER-INVALIDE")["verdict"]
    prix_decimal = _montant(prix)
    financement, refus = _offre(offre_financement, "financement")
    if prix_decimal is None or refus is not None:
        return None, refus["verdict"] if refus is not None else _refus("REJ-CAPITAL-ECHEANCIER-INVALIDE")["verdict"]
    location, refus = _offre(offre_location, "location")
    if refus is not None:
        return None, refus["verdict"]
    devis = {"achat_comptant": ("prix", prix_decimal, None),
             "financement": ("mise_de_fonds", financement["mise"], financement["paiement"]),
             "location": ("mise_de_fonds", location["mise"], location["paiement"])}
    resultat: dict[str, list[dict[str, Any]] | None] = {}
    champs = {"type_sortie", "montant", "date", "source", "hypothese"}
    types_sortie = {"prix", "mise_de_fonds", "paiement_mensuel", "autre"}
    for nom in noms:
        objet = echeanciers.get(nom)
        if objet is None:
            resultat[nom] = None
            continue
        if (not isinstance(objet, dict) or set(objet) != {"couvre_jusquau", "flux_sorties"}
                or not isinstance(objet.get("flux_sorties"), list) or len(objet["flux_sorties"]) > 8):
            return None, _refus("REJ-CAPITAL-ECHEANCIER-INVALIDE", nom)["verdict"]
        couverture_brute = objet["couvre_jusquau"]
        try:
            couverture = date.fromisoformat(couverture_brute) if isinstance(couverture_brute, str) else None
        except ValueError:
            couverture = None
        lignes = objet["flux_sorties"]
        if couverture is None or couverture.isoformat() != couverture_brute or not lignes:
            resultat[nom] = None
            continue
        normalisees: list[dict[str, Any]] = []
        incomplete = False
        for index, ligne in enumerate(lignes):
            if not isinstance(ligne, dict) or set(ligne) - champs:
                return None, _refus("REJ-CAPITAL-ECHEANCIER-INVALIDE", f"{nom}[{index}]")["verdict"]
            if champs - set(ligne):
                incomplete = True
                break
            montant = _montant(ligne["montant"])
            jour_brut = ligne["date"]
            try:
                jour = date.fromisoformat(jour_brut) if isinstance(jour_brut, str) else None
            except ValueError:
                jour = None
            source, hypothese = ligne["source"], ligne["hypothese"]
            if (
                not isinstance(ligne["type_sortie"], str)
                or ligne["type_sortie"] not in types_sortie
                or
                montant is None
                or jour is None
                or jour.isoformat() != jour_brut
                or not isinstance(source, str)
                or not 1 <= len(source.strip()) <= 80
                or not isinstance(hypothese, str)
                or not 1 <= len(hypothese.strip()) <= 80
            ):
                return None, _refus("REJ-CAPITAL-ECHEANCIER-INVALIDE", f"{nom}[{index}]")["verdict"]
            normalisees.append(
                {
                    "id": f"capital:{nom}:{index + 1}",
                    "sens": "SORTIE",
                    "nature": "scenario_capital",
                    "type_sortie": ligne["type_sortie"],
                    "couvre_jusquau": couverture,
                    "montant": montant,
                    "date": jour,
                    "regle_de_date": f"hypothèse saisie : {hypothese.strip()}",
                    "source": source.strip(),
                    "hypothese": hypothese.strip(),
                    "manque": [],
                    "reserves": [],
                }
            )
        if incomplete or not normalisees:
            resultat[nom] = None
            continue
        type_attendu, montant_attendu, paiement_attendu = devis[nom]
        sommes: dict[str, Decimal] = {}
        with localcontext(_CONTEXTE):
            for flux in normalisees:
                type_sortie = flux["type_sortie"]
                sommes[type_sortie] = sommes.get(type_sortie, Decimal("0")) + flux["montant"]
                if type_sortie == "paiement_mensuel" and flux["montant"] != paiement_attendu:
                    resultat[nom] = None
                    break
                if type_sortie in {"prix", "mise_de_fonds"} and type_sortie != type_attendu:
                    resultat[nom] = None
                    break
                if type_sortie == "paiement_mensuel" and nom == "achat_comptant":
                    resultat[nom] = None
                    break
            else:
                # Les montants cités sont rapprochés sans fabriquer de date ni de fréquence.
                if (
                    sommes.get(type_attendu, Decimal("0")) != montant_attendu
                    or (nom != "achat_comptant" and paiement_attendu and not sommes.get("paiement_mensuel"))
                ):
                    resultat[nom] = None
                else:
                    resultat[nom] = normalisees
    return resultat, None


def preparer(
    actif: str,
    prix: Any,
    source_prix: str,
    prix_valide_jusqua: str,
    aujourd_hui: str,
    cash_libre: Any,
    financement: Any,
    location: Any,
) -> dict[str, Any]:
    """Construit les trois scénarios depuis une soumission fournisseur et des offres complètes, sans avis d'achat."""
    if not isinstance(actif, str) or not actif.strip() or len(actif) > 120:
        return _refus("REJ-CAPITAL-ACTIF-INVALIDE")
    montant = _montant(prix)
    if montant is None or montant <= 0 or not isinstance(source_prix, str) or not source_prix.strip():
        return _refus("REJ-CAPITAL-SOUMISSION-INVALIDE")
    try:
        validite = date.fromisoformat(prix_valide_jusqua) if isinstance(prix_valide_jusqua, str) else None
    except ValueError:
        validite = None
    try:
        jour = date.fromisoformat(aujourd_hui) if isinstance(aujourd_hui, str) else None
    except ValueError:
        jour = None
    if (
        validite is None or validite.isoformat() != prix_valide_jusqua or jour is None
        or jour.isoformat() != aujourd_hui
    ):
        return _refus("REJ-CAPITAL-VALIDITE-SOUMISSION-ABSENTE")
    if validite < jour:
        return _refus("REJ-CAPITAL-SOUMISSION-EXPIREE")
    if not isinstance(cash_libre, dict) or cash_libre.get("calculable") is not True:
        manque = cash_libre.get("manque", []) if isinstance(cash_libre, dict) else []
        return _refus("REJ-CAPITAL-CASH-LIBRE-NON-CALCULABLE", manque=manque)
    # Un cash libre négatif est une donnée valide qui doit bloquer l'optimisme, pas la lecture.
    disponible = _montant(cash_libre.get("cash_libre"), negatif_permis=True)
    if disponible is None:
        return _refus("REJ-CAPITAL-CASH-LIBRE-NON-CALCULABLE", manque=["cash libre valide"])
    emprunt, refus = _offre(financement, "financement")
    if refus:
        return refus
    bail, refus = _offre(location, "location")
    if refus:
        return refus

    with localcontext(_CONTEXTE):
        apres_comptant = disponible - montant
        total_emprunt = emprunt["mise"] + emprunt["paiement"] * emprunt["mois"]
        total_bail = bail["mise"] + bail["paiement"] * bail["mois"]
        resultat = {
            "actif": actif.strip(), "devise": "CAD", "prix_cite": format(montant, ".2f"),
            "source_prix": source_prix.strip(), "soumission_valide_jusqua": prix_valide_jusqua,
            "date_reference": aujourd_hui,
            "cash_libre_source": list(cash_libre.get("sources", [])),
            "cash_libre_composantes": list(cash_libre.get("composantes", [])),
            "cash_libre_actuel": format(disponible, ".2f"),
            "scenarios": {
                "achat_comptant": {
                    "sortie_initiale": format(montant, ".2f"),
                    "cash_libre_apres": format(apres_comptant, ".2f"),
                },
                "financement": {"source_offre": emprunt["source"], "mise_de_fonds": format(emprunt["mise"], ".2f"),
                                "paiement_mensuel_cite": format(emprunt["paiement"], ".2f"), "mois": emprunt["mois"],
                "total_paiements_cites": format(total_emprunt, ".2f"),
                                "cash_libre_apres_mise_de_fonds": format(disponible - emprunt["mise"], ".2f")},
                "location": {"source_offre": bail["source"], "mise_de_fonds": format(bail["mise"], ".2f"),
                             "paiement_mensuel_cite": format(bail["paiement"], ".2f"), "mois": bail["mois"],
                             "total_paiements_cites": format(total_bail, ".2f"),
                             "cash_libre_apres_mise_de_fonds": format(disponible - bail["mise"], ".2f")},
            },
            "sources_a_valider": [
                source_prix.strip(), emprunt["source"], bail["source"], *cash_libre.get("sources", [])
            ],
            "questions_cpa": [
                "Traitement TPS/TVQ et récupérabilité selon l'usage",
                "Déductibilité et amortissement fiscal",
                "Engagement de trésorerie et covenants à confirmer sur les contrats signés",
            ],
            "action_proposee": "DEMANDER_APPROBATION_HUMAINE",
            "limites": ["Montants de financement/location recopiés de l'offre, aucun taux ni frais calculé ou supposé",
                        "Le cash libre est un instantané, pas une prévision de trésorerie après acquisition",
                        "Aucune commande, signature, déclaration ou paiement n'est effectué"],
        }
    return {"accepte": True, "resultat": analyse.avec_mention(resultat)}
