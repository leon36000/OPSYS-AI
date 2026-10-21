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


def construire_confirmation_materiaux_utilises(
    intervention_id,
    chantier_id,
    lignes_materiaux,
) -> dict:
    """Confirmation du formulaire de fin de chantier enrichi (PLAN T1.1-d, point 1).

    Distincte de construire_confirmation_consommation_terrain (m6_consommer_materiaux,
    {materiau_id, quantite} seulement) : porte les 6 types de ligne de M6.11. Comme sa
    cousine, ne porte jamais de coût (garde _verifier_absence_cles_monetaires) ni de nom
    d'employé — seul le type de ligne déclaré par le formulaire, jamais une cause.
    """
    lignes_declarees = []
    for ligne in lignes_materiaux:
        ligne_declaree = {
            "type_ligne": ligne["type_ligne"],
            "materiau_id": ligne["materiau_id"],
            "quantite": ligne["quantite"],
            "unite": ligne["unite"],
        }
        if ligne["type_ligne"] == "prevu":
            ligne_declaree["quantite_estimee"] = ligne["quantite_estimee"]
        if ligne["type_ligne"] == "achat_terrain":
            ligne_declaree["photo_fournie"] = ligne["photo_fournie"]
            ligne_declaree["recu_fourni"] = ligne["recu_fourni"]
        lignes_declarees.append(ligne_declaree)

    confirmation = {
        "intervention_id": intervention_id,
        "chantier_id": chantier_id,
        "lignes_declarees": lignes_declarees,
    }

    _verifier_absence_cles_monetaires(confirmation)
    return confirmation


def construire_resultat_variance_chantier(verdicts_materiaux, signal_variance_critique) -> dict:
    """Résultat de variance_chantier.evaluer (PLAN T1.1-d, points 2 et 3).

    Verdict neutre par matériau + SignalVarianceChantierCritique (ou None sous le seuil).
    Ni coût (garde _verifier_absence_cles_monetaires, comme les autres contrats de
    sortie M6), ni nom d'employé : aucun des deux ne transite par variance_chantier.py.
    """
    resultat = {
        "verdicts_materiaux": verdicts_materiaux,
        "signal_variance_critique": signal_variance_critique,
    }

    _verifier_absence_cles_monetaires(resultat)
    return resultat


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

