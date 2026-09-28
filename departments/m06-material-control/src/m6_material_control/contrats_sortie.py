import math
from decimal import Decimal

CLES_MONETAIRES_INTERDITES = frozenset({
    "cout_unitaire",
    "cout",
    "prix",
    "montant",
    "devise",
    "unite_monetaire",
    "montant_total_estime",
})


def _verifier_absence_cles_monetaires(valeur) -> None:
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if cle in CLES_MONETAIRES_INTERDITES:
                raise ValueError(f"Clé monétaire interdite détectée : {cle}")
            _verifier_absence_cles_monetaires(sous_valeur)
    elif isinstance(valeur, list):
        for element in valeur:
            _verifier_absence_cles_monetaires(element)


def construire_confirmation_consommation_terrain(
    intervention_id,
    chantier_id,
    lignes_consommees,
    stock_restant,
) -> dict:
    confirmation = {
        "intervention_id": intervention_id,
        "chantier_id": chantier_id,
        "materiaux_confirmes": [
            {
                "materiau_id": ligne["materiau_id"],
                "quantite_declaree": ligne["quantite"],
            }
            for ligne in lignes_consommees
        ],
        "stock_restant": stock_restant,
    }

    _verifier_absence_cles_monetaires(confirmation)
    return confirmation


def montant_decimal_a_la_frontiere(montant_m6):
    """Convertit un montant M6 (float, contrat gelé §2.6/§2.8) en Decimal EXACT
    pour toute frontière qui l'exige (ex. M5-FinanceCore, CA-M5-01 : Decimal
    fini, jamais un float). Bug NEW-PROD corrigé ici : SignalPoAPayer et
    AccuseReceptionPO restent des float en interne (contrat M6 gelé, PRD §5.6/
    §5.8 — on ne les modifie pas), mais quiconque transmet ce montant à un
    domaine qui exige Decimal DOIT passer par `Decimal(str(x))`, jamais
    `Decimal(x)` qui importerait l'imprécision binaire du float source.

    #109 : cette fonction ne connaît rien de m5_financecore (aucun import), elle
    ne fait que produire un Decimal exact ; c'est à l'appelant (outil agent,
    orchestrateur) de construire le mouvement financier attendu par M5 avec.
    """
    if isinstance(montant_m6, bool) or not isinstance(montant_m6, (int, float)):
        raise TypeError(f"montant M6 invalide pour conversion Decimal : {montant_m6!r}")
    if isinstance(montant_m6, float) and not math.isfinite(montant_m6):
        raise ValueError(f"montant M6 non fini, conversion Decimal refusée : {montant_m6!r}")
    return Decimal(str(montant_m6))

