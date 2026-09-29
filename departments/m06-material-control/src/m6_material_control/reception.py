"""Verdict de réception (M6.7) : chaque livraison contre la commande, puis le CUMUL des livraisons d'un PO.

`traiter_reception` juge UNE livraison contre la commande entière (contrat gelé, inchangé) : c'est l'accusé de
cette livraison. `evaluer_cumul` (PLAN T4.15-b) juge ce qu'un PO PERSISTÉ a reçu en tout, livraisons
additionnées : c'est elle qui décide si le PO est `received`. Sans elle, une livraison qui complète un PO déjà
partiel resterait `RECEPTION_INFERIEURE` (elle n'apporte que le reste) et le PO ne serait jamais reçu.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge, aucun aléa, aucun réseau. Les quantités
du cumul sont additionnées en DÉCIMAL EXACT (`Decimal(str(x))`, jamais en flottant) : 0,1 + 0,2 doit valoir 0,3,
sinon un PO de 0,3 ne serait jamais complet.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from . import catalogue


def _verdict_depuis_ecarts(ecarts) -> str:
    """CONFORME, RECEPTION_INFERIEURE, RECEPTION_SUPERIEURE ou RECEPTION_MIXTE, selon le signe des écarts
    (reçu - commandé) : une seule règle, pour la livraison seule comme pour le cumul."""
    contient_ecart_inferieur = any(ecart < 0 for ecart in ecarts)
    contient_ecart_superieur = any(ecart > 0 for ecart in ecarts)
    if contient_ecart_inferieur and contient_ecart_superieur:
        return "RECEPTION_MIXTE"
    if contient_ecart_inferieur:
        return "RECEPTION_INFERIEURE"
    if contient_ecart_superieur:
        return "RECEPTION_SUPERIEURE"
    return "CONFORME"


def traiter_reception(bon_demande, reception_po, catalogue_fourni, registre):
    bareme_version = (
        catalogue_fourni["version"] if catalogue_fourni is not None else None
    )

    resultat_indetermine = {
        "po_id": bon_demande["po_id"],
        "chantier_id": bon_demande["chantier_id"],
        "verdict_reception": "INDETERMINE",
        "lignes": [],
        "montant_total_estime": None,
        "bareme_version": bareme_version,
    }

    if (
        reception_po["po_id"] != bon_demande["po_id"]
        or reception_po["chantier_id"] != bon_demande["chantier_id"]
    ):
        return resultat_indetermine

    recues_par_materiau = {
        ligne["materiau_id"]: ligne["quantite_recue"]
        for ligne in reception_po["lignes_recues"]
    }

    lignes = []
    for ligne_demandee in bon_demande["lignes_demandees"]:
        materiau_id = ligne_demandee["materiau_id"]

        if materiau_id not in recues_par_materiau:
            return resultat_indetermine

        quantite_demandee = ligne_demandee["quantite_demandee"]
        quantite_recue = recues_par_materiau[materiau_id]
        ecart = quantite_recue - quantite_demandee
        resolution_prix = catalogue.resoudre_prix(
            materiau_id, catalogue_fourni, registre
        )
        cout_unitaire_resolu = resolution_prix["cout_unitaire_resolu"]
        montant_ligne = (
            cout_unitaire_resolu * quantite_recue
            if cout_unitaire_resolu is not None
            else None
        )

        lignes.append(
            {
                "materiau_id": materiau_id,
                "quantite_demandee": quantite_demandee,
                "quantite_recue": quantite_recue,
                "ecart": ecart,
                "verdict_resolution_prix": resolution_prix[
                    "verdict_resolution_prix"
                ],
                "cout_unitaire_resolu": cout_unitaire_resolu,
                "montant_ligne": montant_ligne,
            }
        )

    verdict_reception = _verdict_depuis_ecarts([ligne["ecart"] for ligne in lignes])

    montant_total_estime = (
        sum(ligne["montant_ligne"] for ligne in lignes)
        if all(ligne["montant_ligne"] is not None for ligne in lignes)
        else None
    )

    return {
        "po_id": bon_demande["po_id"],
        "chantier_id": bon_demande["chantier_id"],
        "verdict_reception": verdict_reception,
        "lignes": lignes,
        "montant_total_estime": montant_total_estime,
        "bareme_version": bareme_version,
    }


def _decimal(valeur: Any) -> Decimal | None:
    """Le nombre (ou le texte décimal) en décimal exact ; `None` si ce n'est ni l'un ni l'autre, ou si ce n'est
    pas fini. Jamais `Decimal(float)` : l'imprécision binaire du flottant entrerait dans la somme."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, str)):
        return None
    try:
        decimal = Decimal(str(valeur))
    except InvalidOperation:
        return None
    return decimal if decimal.is_finite() else None


def _texte(valeur: Decimal) -> str:
    if valeur.is_zero():
        valeur = abs(valeur)  # un zéro n'a pas de signe
    return format(valeur, "f")


def evaluer_cumul(lignes_commandees, livraisons) -> dict[str, Any] | None:
    """Ce qu'un PO a reçu EN TOUT, livraisons additionnées (PLAN T4.15-b), et le verdict qui en découle.

    `lignes_commandees` : les lignes du PO (`materiau_id`, `quantite_demandee`). `livraisons` : une suite de
    livraisons, chacune une suite de lignes (`materiau_id`, `quantite_recue`, nombre ou texte décimal) —
    les livraisons ANTÉRIEURES puis la courante ; une ligne dont le matériau n'est pas au PO est ignorée, comme
    `traiter_reception` l'ignore.

    Rend `{"verdict_reception", "lignes": [{"materiau_id", "quantite_demandee", "quantite_recue_cumulee",
    "ecart_cumule"}]}` (quantités et écarts en texte décimal, ordre du PO), ou `None` quand une quantité n'est
    pas un nombre fini : fail-closed, jamais un cumul deviné. Le verdict est celui de `traiter_reception`
    (CONFORME, RECEPTION_INFERIEURE, RECEPTION_SUPERIEURE, RECEPTION_MIXTE) appliqué au cumul : un PO n'est
    complet que lorsque CHAQUE ligne a atteint sa commande, et il reste partiel tant qu'une ligne manque, même si
    une autre est en excédent (RECEPTION_MIXTE)."""
    commandees: list[tuple[Any, Decimal]] = []
    for ligne in lignes_commandees:
        quantite = _decimal(ligne["quantite_demandee"])
        if quantite is None:
            return None
        commandees.append((ligne["materiau_id"], quantite))
    identifiants = {materiau_id for materiau_id, _ in commandees}
    recues: dict[Any, Decimal] = {materiau_id: Decimal(0) for materiau_id in identifiants}
    for livraison in livraisons:
        for ligne in livraison:
            if ligne["materiau_id"] not in identifiants:
                continue
            quantite = _decimal(ligne["quantite_recue"])
            if quantite is None:
                return None
            recues[ligne["materiau_id"]] += quantite
    lignes = [
        {
            "materiau_id": materiau_id,
            "quantite_demandee": _texte(quantite),
            "quantite_recue_cumulee": _texte(recues[materiau_id]),
            "ecart_cumule": _texte(recues[materiau_id] - quantite),
        }
        for materiau_id, quantite in commandees
    ]
    verdict = _verdict_depuis_ecarts([recues[materiau_id] - quantite for materiau_id, quantite in commandees])
    return {"verdict_reception": verdict, "lignes": lignes}
