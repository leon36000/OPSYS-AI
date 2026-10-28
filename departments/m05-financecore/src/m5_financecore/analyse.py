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

__all__ = ["MENTION_ANALYSE_PREPARATOIRE", "SORTIES_D_ANALYSE", "SORTIES_HORS_ANALYSE", "avec_mention"]

MENTION_ANALYSE_PREPARATOIRE = (
    "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle "
    "ou action réelle."
)

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
})

# Les autres outils de M5, chacun avec la raison pour laquelle sa sortie n'est pas une analyse.
SORTIES_HORS_ANALYSE = {
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
