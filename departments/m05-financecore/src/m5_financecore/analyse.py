"""La mention obligatoire de M5 sur toute sortie d'analyse (DEFINITION-PRODUIT §7 M5, §13.3 ; audit M5 §5).

M5 n'est PAS un conseiller financier réglementé : ses sorties sont des analyses préparatoires, jamais un avis fiscal
ou comptable officiel. La définition produit impose donc une mention sur toute réponse stratégique, et retient la
formulation de l'extension « CFO IA » (§13.3). Jusqu'ici, elle n'était codée nulle part (audit M5 §5) : ce module la
code, et `SORTIES_D_ANALYSE` dit quels outils la portent. Un test ferme le monde : chaque outil de M5 est classé ici
(analyse, ou hors analyse avec sa raison), donc un nouvel outil ne peut pas naître sans que la question soit posée, et
chaque sortie acceptée d'un outil d'analyse porte la mention, telle quelle.

Module pur : aucune horloge, aucun accès à un registre.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "MENTION_ANALYSE_PREPARATOIRE", "MENTION_COMPTABLE", "SORTIES_COMPTABLES", "SORTIES_D_ANALYSE",
    "SORTIES_ONBOARDING", "SORTIES_HORS_ANALYSE", "avec_mention", "avec_mention_comptable",
]

MENTION_ANALYSE_PREPARATOIRE = (
    "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle "
    "ou action réelle."
)

# Grand livre (tranche 1) : toute sortie comptable porte EN PLUS cette mention (clé `mention_comptable`). Une balance,
# un grand livre, un rapprochement ou une écriture préparés par OPSYS ne sont pas des états financiers vérifiés.
MENTION_COMPTABLE = "À valider auprès d'un comptable (CPA) / professionnel qualifié."

# Les outils du grand livre : des sorties d'analyse (mention obligatoire) ET comptables (mention comptable). Leurs deux
# mentions sont testées dans `tests/test_grand_livre_outils.py`.
SORTIES_COMPTABLES = frozenset({
    "m5_lire_balance_verification",  # balance de vérification à une date : un état préparé, non vérifié
    "m5_lire_grand_livre_compte",  # grand livre d'un compte : soldes courants des écritures définitives
    "m5_rapprocher_grand_livre",  # équilibre débits/crédits et TPS/TVQ contre taxes.py : un contrôle à interpréter
    "m5_proposer_ecriture_comptable",  # un brouillon d'écriture saisi : une proposition, jamais définitive
    "m5_generer_brouillons_comptables",  # brouillons tirés des faits M5 : des propositions
    "m5_proposer_contre_passation",  # le brouillon qui corrigerait une définitive : une proposition
    "m5_valider_ecriture_comptable",  # l'écriture rendue définitive par un humain (N4) : reste à valider par le CPA
    "m5_clore_periode_comptable",  # la clôture décidée par un humain (N4) et ses totaux : à valider par le CPA
    # Import QuickBooks (repli « exports ») : lectures et propositions de reprise d'historique, à valider par le CPA.
    "m5_analyser_exports_quickbooks",  # lecture des exports et correspondance PROPOSÉE : un brouillon à interpréter
    "m5_valider_correspondance_quickbooks",  # la correspondance validée par un humain (N4) : reste à valider par le CPA
    "m5_importer_quickbooks",  # des brouillons d'écritures repris d'un autre logiciel : des propositions
    "m5_lire_import_quickbooks",  # un import, sa vérification et ses soldes attendus : un contrôle à interpréter
    "m5_valider_import_quickbooks",  # les écritures reprises rendues définitives (N4) : reste à valider par le CPA
})

# Ingestion d'onboarding : la lecture d'un lot et de ses brouillons (champs lus, taxes recalculées, raisons) et la
# validation d'une facture proposée (la facture sans PO saisie : un calcul, comme la saisie). Leur mention est prouvée
# sur chaque sortie acceptée par `tests/test_ingestion_onboarding_bout_en_bout.py` (un lot réel est requis).
SORTIES_ONBOARDING = frozenset({"m5_lire_lot_onboarding", "m5_valider_brouillon_onboarding_ap"})

# Les outils dont la réponse acceptée est une analyse, un calcul interprété ou une proposition : elle porte la mention
# (clé `mention`, au niveau de ce que l'outil rend dans `resultat`).
SORTIES_D_ANALYSE = frozenset({
    "m5_etat_tresorerie",  # le cash libre réel : un calcul qui retranche des obligations, sous hypothèses
    "m5_lire_echeances_fiscales",  # échéances TPS/TVQ : un calendrier à valider par le CPA
    "m5_lire_calendrier_obligations",  # paies, DAS, dettes et fiscalité sous sources déclarées
    "m5_prevoir_tresorerie",  # prévision des flux connus et datés : un calcul sous hypothèses, seuil et délais déclarés
    "m5_preparer_decision_capital",  # comparaison préparatoire de scénarios d'acquisition
    "m5_preparer_dossier_decision_cfo",  # dossier stratégique composé à partir des vues canoniques M5
    "m5_constater_cash_libre",  # le cash libre constaté et publié au bus (T4.19-b) : le même calcul, sous hypothèses
    "m5_lire_rentabilite_chantier",  # coût réel et marge : une lecture de rentabilité
    "m5_lister_comptes_a_payer",  # « à payer attendu » et rapprochement PROPOSÉ
    "m5_saisir_facture_fournisseur",  # rend le rapprochement PROPOSÉ du PO
    "m5_saisir_facture_sans_po",  # rend la facture recalculée et ce que valent les factures sans PO : un calcul
    "m5_corriger_facture_fournisseur",  # rend le rapprochement PROPOSÉ du PO (ou le total sans PO) au nouvel état
    "m5_annuler_facture_fournisseur",  # idem : ce que le PO doit après l'annulation, PROPOSÉ, jamais appliqué
    "m5_preparer_brut_regulier",  # estimation préparatoire humaine du brut, sans retenues ni action officielle
    "m5_preparer_dossier_webras",  # dossier préparatoire pour calcul humain dans les services officiels
    "m5_prevoir_tresorerie_contrats",  # prévision préparatoire de flux contractuels rapprochés aux sources M3/M5
}) | SORTIES_COMPTABLES | SORTIES_ONBOARDING

# Les autres outils de M5, chacun avec la raison pour laquelle sa sortie n'est pas une analyse.
SORTIES_HORS_ANALYSE = {
    "m5_deposer_lot_onboarding": (
        "crée un lot de documents déposés (types, empreintes, doublons, compteurs), sans aucun montant ni calcul"
    ),
    "m5_avancer_lot_onboarding": (
        "rend l'état des tâches d'un lot (compteurs et issues par étape), sans aucun montant ni calcul financier"
    ),
    "m5_verifier_admission_paie_preparatoire": (
        "diagnostic documentaire et génération Source, sans calcul monétaire ni qualification fiscale"
    ),
    "m5_lire_obligations_preparees_appareil": (
        "inventorie les déclarations humaines non attestées et les lacunes de leurs sources, "
        "sans projection de flux, calcul de paie ou décision financière"
    ),
    "m5_enregistrer_obligation_preparee_appareil": (
        "accuse la saisie ou le retrait brut dans le registre préparatoire séparé, "
        "sans mouvement ni activation du calendrier financier"
    ),
    "m5_calculer_taxes_tps_tvq": "calcul déterministe avec taux versionnés et sourcés, sans interprétation",
    "m5_enregistrer_mouvement": "écriture d'un mouvement (T3) : la sortie est le maillon écrit",
    "m5_creer_facture_brouillon": "écriture d'un brouillon (T1) : la sortie est la facture recalculée",
    "m5_lister_attentes_facturation": "liste de ce qui attend, avec l'étape manquante : un fait du registre",
    "m5_lire_comptes_a_recevoir": "liste des factures envoyées et de leur âge : un fait du registre",
    "m5_envoyer_facture": "action de N4, déjà tenue par une approbation humaine du socle",
    "m5_enregistrer_paiement_facture": "action de N5, déjà tenue par Nathan et le professionnel (socle)",
    "m5_enregistrer_contrat_horaire": "enregistre une source de rémunération après approbation humaine N4",
    "m5_revoquer_contrat_horaire": "révoque append-only une source salariale après approbation humaine N4",
    "m5_lire_contrat_horaire": "lit la version actuelle d'un contrat salarié sans calculer de montant",
    "m5_lire_sources_regles_paie": (
        "inventorie l'état des références déclarées et leurs lacunes, sans calculer ni valider une paie"
    ),
    "m5_enregistrer_echeancier_contrat": (
        "enregistre un échéancier contractuel après validation humaine N4; la sortie est une écriture sourcée"
    ),
    "m5_revoquer_echeancier_contrat": (
        "révoque append-only un échéancier après validation humaine N4, sans calculer une projection"
    ),
}


def avec_mention(sortie: Mapping[str, Any]) -> dict[str, Any]:
    """`sortie` avec la mention obligatoire. Un dictionnaire seulement : la mention est une clé, jamais un texte collé
    sur autre chose."""
    if not isinstance(sortie, Mapping):
        raise TypeError("la mention s'ajoute à un dictionnaire de sortie")
    return {**sortie, "mention": MENTION_ANALYSE_PREPARATOIRE}


def avec_mention_comptable(sortie: Mapping[str, Any]) -> dict[str, Any]:
    """`sortie` avec la mention obligatoire ET la mention comptable (grand livre) ; aucune ne se remplace."""
    return {**avec_mention(sortie), "mention_comptable": MENTION_COMPTABLE}
