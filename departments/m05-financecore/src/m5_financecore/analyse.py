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
    "MENTION_ANALYSE_PREPARATOIRE", "MENTION_COMPTABLE", "SORTIES_CALCUL", "SORTIES_COMPTABLES", "SORTIES_D_ANALYSE",
    "SORTIES_FISCALES", "SORTIES_ONBOARDING", "SORTIES_HORS_ANALYSE", "SORTIES_OPERATIONS", "SORTIES_CONSEIL",
    "avec_mention", "avec_mention_comptable",
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

# Moteur de calcul (tranche 1, `docs/moteur-calcul.md`) : chaque sortie est un REÇU de calcul sous les deux mentions
# (analyse préparatoire et comptable) ; elles sont prouvées sur chaque sortie acceptée par
# `tests/test_moteur_calcul_outils.py`.
SORTIES_CALCUL = frozenset({
    "m5_calculer_rentabilite_investissement",  # VAN, TRI (et son statut), TRI modifié, délais : sous hypothèses
    "m5_calculer_amortissement_pret",  # tableau d'amortissement : une convention de taux déclarée
    "m5_comparer_credit_bail_achat",  # coûts actualisés sous hypothèses : jamais une recommandation
    "m5_calculer_point_mort",  # modèle linéaire déclaré
    "m5_analyser_sensibilite_projet",  # tornade et scénarios sur les valeurs de l'appelant
    "m5_simuler_tresorerie_monte_carlo",  # distributions déclarées sur la prévision existante
    "m5_verifier_recu_calcul",  # vérification et rejeu d'un reçu : le même calcul refait
})

# Base fiscale versionnée, validation de la paie, catalogue de subventions et garde investissement
# (`docs/architecture/BASE-FISCALE.md`) : lectures et brouillons sous les deux mentions, prouvés par
# `tests/test_outils_base_fiscale.py` sur chaque sortie acceptée.
SORTIES_FISCALES = frozenset({
    "m5_lire_etat_base_fiscale",  # combien de valeurs, combien approuvées, ce qui n'a pas de source
    "m5_lire_regle_fiscale",  # un paramètre en vigueur à une date, avec son mode (officiel ou essai marqué)
    "m5_lire_statut_campagne_paie",  # « campagne officielle : N/300 » et le rejeu des cas fictifs
    "m5_apparier_subventions",  # critères satisfaits/non satisfaits/inconnus et brouillon de dossier : à valider
    "m5_verifier_demande_investissement",  # verdict de la garde NC 31-103 : refus générique ou contenu permis
})

# Opérations comptables, rapprochement bancaire et dossier CPA (`docs/architecture/M5-SOPHIE.md`) : brouillons,
# constats et lectures sous les deux mentions, prouvés sur chaque sortie acceptée par
# `tests/test_m5_operations_outils.py`.
SORTIES_OPERATIONS = frozenset({
    "m5_preparer_relances_clients",  # brouillons de relance de créances en retard : rien n'est envoyé
    "m5_proposer_note_credit",  # note de crédit et brouillon d'écriture : une proposition
    "m5_proposer_depense_employe",  # dépense d'employé et brouillon d'écriture : une proposition
    "m5_lier_piece_justificative",  # empreinte d'une pièce liée à une opération
    "m5_lire_flux_fournisseur",  # où en est une facture fournisseur, prochaine action
    "m5_avancer_flux_fournisseur",  # brouillon d'écriture et constat de rapprochement PO
    "m5_preparer_paiement_fournisseur",  # paiement PRÉPARÉ (fiche), jamais exécuté
    "m5_consigner_jugement_comptable",  # jugement ou estimation consigné par une personne
    "m5_ouvrir_periode_comptable",  # soldes d'ouverture consignés
    "m5_precloturer_periode_comptable",  # liste de contrôle de préclôture
    "m5_constater_mesures_comptables",  # mesures publiées pour M8
    "m5_executer_cycle_comptable",  # cycle jusqu'aux brouillons
    "m5_preparer_rapprochement_bancaire",  # état de rapprochement PRÉPARÉ avec reçu
    "m5_lire_rapprochement_bancaire",  # liste, détail et rejeu des rapprochements
    "m5_confirmer_rapprochement_bancaire",  # confirmation humaine (N4)
    "m5_preparer_dossier_cpa",  # dossier scellé pour le CPA
    "m5_verifier_dossier_cpa",  # vérification d'un dossier scellé
})

# Conseillers (dette, financement, investissement de trésorerie ; fiscal et comptable ; base de connaissances fiscale) :
# reçus de calcul, analyses sourcées et citations, mêmes deux mentions, prouvés par
# `tests/test_m5_conseillers_outils.py`.
SORTIES_CONSEIL = frozenset({
    "m5_comparer_financement_achat",  # coûts actualisés comptant, prêt, location : jamais une recommandation
    "m5_simuler_remboursement_anticipe",  # intérêts épargnés sous hypothèses
    "m5_echelonner_placements_terme_fixe",  # échelonnement de trésorerie aux taux saisis, aucun titre
    "m5_lister_sujets_conseil_fiscal",  # les sujets, leurs règles et données exigées
    "m5_analyser_situation_fiscale",  # affirmations sourcées, ESSAI/non approuvé, refus si règle non renseignée
    "m5_rechercher_connaissance_fiscale",  # citations de la base fiscale et comptable, ou « inconnu »
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
}) | (
    SORTIES_COMPTABLES | SORTIES_ONBOARDING | SORTIES_CALCUL | SORTIES_FISCALES | SORTIES_OPERATIONS | SORTIES_CONSEIL)

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
