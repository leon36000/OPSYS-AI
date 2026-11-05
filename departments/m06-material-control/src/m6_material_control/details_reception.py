"""Détails d'une réception par ligne (C5, M6.7) : statut, substitution, dommage, preuve, lieu, prix BL.

`reception.py` ne juge qu'une quantité contre la commande ; ce module AJOUTE ce que le brief C5
exige sans toucher au contrat gelé (`traiter_reception`, `CHAMPS_RECEPTION_PO`) : par ligne un
`statut_ligne` (conforme, manquant, substitué, endommagé), le matériau substitué quand il y a lieu,
la référence CAS de la photo quand la ligne est endommagée (même contrat `fichier:sha256:` que
`preuves_pertes_bris.py`, jamais authentifiée ici), le lieu de livraison (liste fermée des lieux
`emplacements`, jamais un texte libre) et le prix du bon de livraison lu par l'admin (donnée saisie,
marquée `BON_LIVRAISON`, jamais un prix du catalogue).

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge, aucun aléa, aucun réseau.
Fail-closed partout : statut inconnu, substitution sans matériau, dommage sans photo CAS, lieu hors
liste, prix illisible -> refus nommé, jamais une valeur inventée.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

__all__ = [
    "STATUTS_LIGNE",
    "detecter_ecarts_prix_bl",
    "qualifier_livraison",
    "valider_coherence_statuts_quantites",
    "valider_couverture_details",
    "valider_details",
    "valider_lieu",
]

# Les 4 statuts dits par le brief C5, mot pour mot : ce que la ligne reçue EST, pas un jugement.
STATUTS_LIGNE = frozenset({"conforme", "manquant", "substitue", "endommage"})

# Même contrat que `preuves_pertes_bris.REFERENCE_CAS` : une référence déclarée, jamais authentifiée ici.
_REFERENCE_CAS = re.compile(r"fichier:sha256:[0-9a-f]{64}\Z")

# Lieux de livraison dits par M6.7 (dépôt/chantier/ramassage) projetés sur la liste fermée des
# lieux `emplacements.py` : le stock initial va à l'emplacement nommé. `camion`/`remorque`/`employe`
# exigent une référence (lequel ?) ; `retour`/`rebut` ne sont pas une livraison ; `inconnu` et
# `fournisseur` ne sont pas un lieu d'arrivée.
_LIEUX_LIVRAISON = frozenset({"depot", "chantier", "camion", "remorque", "employe"})


def _refus(code: str, detail: str) -> tuple[None, str]:
    return None, code


def valider_details(details: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Les détails ligne par ligne, validés fail-closed, recopiés sans réparer.

    - `statut_ligne` dans les 4 dits (sinon `REJ-RECEPTION-STATUT-INCONNU`, injection comprise) ;
    - `substitue` exige `materiau_substitue` non vide (sinon `REJ-RECEPTION-SUBSTITUE-INCOMPLET`) ;
    - `endommage` exige au moins une photo CAS `fichier:sha256:` (sinon `REJ-RECEPTION-PREUVE-MANQUANTE`).
    """
    if not isinstance(details, list) or not details:
        return None, "REJ-RECEPTION-DETAILS-INVALIDES"
    valides: list[dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, Mapping):
            return None, "REJ-RECEPTION-DETAILS-INVALIDES"
        materiau_id = detail.get("materiau_id")
        statut = detail.get("statut_ligne")
        if not isinstance(materiau_id, str) or not materiau_id:
            return None, "REJ-RECEPTION-DETAILS-INVALIDES"
        if statut not in STATUTS_LIGNE:
            return None, "REJ-RECEPTION-STATUT-INCONNU"
        if statut == "substitue":
            substitue = detail.get("materiau_substitue")
            if not isinstance(substitue, str) or not substitue.strip():
                return None, "REJ-RECEPTION-SUBSTITUE-INCOMPLET"
        if statut == "endommage":
            photos = detail.get("photos")
            if (
                not isinstance(photos, list)
                or not photos
                or any(not isinstance(p, str) or _REFERENCE_CAS.fullmatch(p) is None for p in photos)
            ):
                return None, "REJ-RECEPTION-PREUVE-MANQUANTE"
        # Ne pas recopier de champs libres (octets photo, secrets, prompt, etc.) dans la réponse ou
        # dans une référence durable ultérieure. Seuls les champs C5 effectivement validés sortent.
        projection = {"materiau_id": materiau_id, "statut_ligne": statut}
        if statut == "substitue":
            projection["materiau_substitue"] = detail["materiau_substitue"]
        if statut == "endommage":
            projection["photos"] = list(detail["photos"])
        valides.append(projection)
    return valides, None


def valider_couverture_details(
    details: list[dict[str, Any]],
    lignes_demandees: Any,
    lignes_recues: Any,
) -> str | None:
    """Vérifie l'association univoque des détails aux lignes de CETTE réception.

    Le champ entier `details_reception` reste optionnel pour les appels historiques. Si l'appelant
    choisit de le fournir, chaque matériau effectivement reçu doit avoir exactement un détail, et
    ce matériau doit appartenir à la demande. Les lignes de réception répétées ne peuvent pas être
    associées sans ambiguïté à un détail indexé seulement par `materiau_id`.

    La fonction est pure ; elle ne complète jamais une ligne absente par « conforme ».
    """
    if not isinstance(lignes_demandees, list) or not isinstance(lignes_recues, list):
        return "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"

    details_ids = [detail.get("materiau_id") for detail in details]
    demandes_ids = [ligne.get("materiau_id") for ligne in lignes_demandees]
    recus_ids = [ligne.get("materiau_id") for ligne in lignes_recues]
    if any(not isinstance(materiau_id, str) or not materiau_id for materiau_id in details_ids + demandes_ids + recus_ids):
        return "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"
    if len(details_ids) != len(set(details_ids)):
        return "REJ-RECEPTION-DETAILS-DUPLIQUES"

    if len(recus_ids) != len(set(recus_ids)):
        return "REJ-RECEPTION-DETAILS-LIGNES-AMBIGUES"

    if len(demandes_ids) != len(set(demandes_ids)):
        return "REJ-RECEPTION-DETAILS-LIGNES-AMBIGUES"

    ensemble_demandes = set(demandes_ids)
    ensemble_recus = set(recus_ids)
    ensemble_details = set(details_ids)
    if not ensemble_recus <= ensemble_demandes:
        return "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"
    if ensemble_details - ensemble_recus:
        return "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"
    if ensemble_recus - ensemble_details:
        return "REJ-RECEPTION-DETAILS-INCOMPLETS"
    return None


def valider_coherence_statuts_quantites(
    details: list[dict[str, Any]],
    lignes_recues: Any,
) -> str | None:
    """Refuse un statut C5 qui contredit la quantité effectivement reçue.

    Une ligne `manquant` signifie zéro reçu (et doit être représentée par une ligne de quantité
    zéro dans `lignes_recues`). Les trois autres statuts décrivent un matériau reçu et exigent
    donc une quantité strictement positive. Les écarts positif/négatif à la quantité commandée
    restent jugés séparément par `reception.py` ; ils ne changent pas le statut matériel.
    """
    if not isinstance(lignes_recues, list):
        return "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"

    par_materiau = {detail.get("materiau_id"): detail for detail in details}
    for ligne in lignes_recues:
        if not isinstance(ligne, Mapping):
            return "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"
        materiau_id = ligne.get("materiau_id")
        detail = par_materiau.get(materiau_id)
        if not isinstance(detail, Mapping):
            return "REJ-RECEPTION-DETAILS-INCOHERENTES"
        try:
            quantite = Decimal(str(ligne.get("quantite_recue")))
        except (InvalidOperation, TypeError, ValueError):
            return "REJ-RECEPTION-QUANTITE-INVALIDE"
        if not quantite.is_finite() or quantite < 0:
            return "REJ-RECEPTION-QUANTITE-INVALIDE"
        statut = detail.get("statut_ligne")
        if (statut == "manquant") != (quantite == 0):
            return "REJ-RECEPTION-STATUT-QUANTITE-INCOHERENT"
    return None


def valider_lieu(lieu: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Le lieu de livraison : un lieu fermé d'arrivée du stock, jamais un texte libre.

    `depot` seul ; `chantier`/`camion`/`remorque`/`employe` avec `reference` non vide (lequel ?).
    Délègue à `emplacements.normaliser` après le filtre d'arrivée (un retour n'est pas une livraison).
    """
    from . import emplacements

    if not isinstance(lieu, Mapping):
        return None, "REJ-RECEPTION-LIEU-INVALIDE"
    if lieu.get("type") not in _LIEUX_LIVRAISON:
        return None, "REJ-RECEPTION-LIEU-INVALIDE"
    normalise, verdict = emplacements.normaliser(dict(lieu))
    if verdict is not None:
        return None, "REJ-RECEPTION-LIEU-INVALIDE"
    return normalise, None


def qualifier_livraison(
    lignes_commandees: list[Mapping[str, Any]],
    lignes_recues: list[Mapping[str, Any]],
    details: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verdict de CETTE livraison enrichi du statut de chaque ligne.

    La quantité reste jugée comme `reception.py` (écart reçu − commandé, décimal exact) ; le statut
    précis (manquant : 0 reçu et dit ; endommagé : reçu mais à mettre au rebut, pas au stock
    disponible) et le matériau substitué accompagnent chaque ligne. Une substitution ne change pas
    la quantité due du matériau commandé : elle la signale, sans inventer de stock.
    """
    recues = {ligne["materiau_id"]: ligne["quantite_recue"] for ligne in lignes_recues if isinstance(ligne, Mapping)}
    par_detail = {d["materiau_id"]: d for d in details if isinstance(d, Mapping)}
    lignes = []
    for ligne in lignes_commandees:
        materiau_id = ligne["materiau_id"]
        demandee = Decimal(str(ligne["quantite_demandee"]))
        recue = Decimal(str(recues.get(materiau_id, 0)))
        detail = par_detail.get(materiau_id, {})
        statut = detail.get("statut_ligne", "conforme")
        lignes.append(
            {
                "materiau_id": materiau_id,
                "quantite_demandee": float(demandee),
                "quantite_recue": float(recue),
                "ecart": float(recue - demandee),
                "statut_ligne": statut,
                **(
                    {"materiau_substitue": detail["materiau_substitue"]}
                    if statut == "substitue"
                    else {}
                ),
                **({"photos": list(detail.get("photos", []))} if statut == "endommage" else {}),
            }
        )
    ecarts = [ligne["ecart"] for ligne in lignes]
    if any(e < 0 for e in ecarts) and any(e > 0 for e in ecarts):
        verdict = "RECEPTION_MIXTE"
    elif any(e < 0 for e in ecarts):
        verdict = "RECEPTION_INFERIEURE"
    elif any(e > 0 for e in ecarts):
        verdict = "RECEPTION_SUPERIEURE"
    else:
        verdict = "CONFORME"
    return {"verdict_reception": verdict, "lignes": lignes}


def detecter_ecarts_prix_bl(
    lignes_po: list[Mapping[str, Any]],
    prix_bl: Mapping[str, Any],
    seuil_pourcentage: float | None,
) -> list[dict[str, Any]]:
    """Écart entre le prix du bon de livraison (donné saisie, marquée `BON_LIVRAISON`) et le prix prévu du PO.

    Même discipline que `bons_commande.detecter_ecarts_prix` (valeur absolue, seuil, silence si un
    prix manque) ; le seuil vient du manifeste DÉCLARÉ (`seuil_ecart_prix_reception_pourcentage`),
    jamais d'un nombre codé en dur ici : absent, aucun écart n'est signalé. Comparaison en
    `Fraction` sur le texte décimal (1.20/1.00 atteint exactement 20 %).
    """
    if seuil_pourcentage is None or not isinstance(prix_bl, Mapping):
        return []
    try:
        seuil = Fraction(str(seuil_pourcentage))
    except (ValueError, ZeroDivisionError, ArithmeticError):
        return []
    prevu_par_materiau = {ligne["materiau_id"]: ligne.get("prix_unitaire_prevu") for ligne in lignes_po}
    signaux: list[dict[str, Any]] = []
    for materiau_id, prix_prevu in prevu_par_materiau.items():
        prix_lu = prix_bl.get(materiau_id)
        if prix_prevu is None or prix_lu is None:
            continue
        try:
            ecart = abs(Fraction(str(prix_lu)) - Fraction(str(prix_prevu))) / Fraction(str(prix_prevu))
        except (ValueError, ZeroDivisionError, ArithmeticError):
            continue
        if ecart >= seuil:
            signaux.append(
                {
                    "materiau_id": materiau_id,
                    "prix_prevu": prix_prevu,
                    "prix_bl": prix_lu,
                    "ecart_pourcentage": float(ecart),
                    "source_prix": "BON_LIVRAISON",
                }
            )
    return signaux
