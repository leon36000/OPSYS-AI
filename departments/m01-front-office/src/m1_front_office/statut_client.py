"""Statut client borné (M1.10, chantier M1-G) : ce que M1 est autorisé à DIRE après vérification d'identité.

`identite_client.py` décide SI M1 peut répondre sur un dossier ; ce module décide CE QU'IL DIT. Il ne lit rien : il
reçoit l'état brut d'un département (M2, M3, M4 ou M5) et le traduit en une phrase d'un GABARIT FIXE, ou rend le repli
exact « Je vais vérifier avec l'équipe. ».

Règles :

- **Ensemble fermé.** Un sujet (`dossier`, `soumission`, `visite`, `facture`) et un statut brut sont traduits par une
  table écrite ici. Un statut inconnu ne fuit jamais : il produit le repli, jamais le code brut du département.
- **Aucun texte libre.** La réponse est rendue par `gabarits.rendre` (`statut_client`, variables `sujet` et `statut`
  contrôlées) ; l'agent ne fournit ni phrase, ni prix, ni date, ni complément.
- **Aucune donnée financière.** Le module ne connaît aucun montant ; l'adaptateur ne lit que le statut. Le niveau
  « probable » (un seul moyen d'identité) ne suffit jamais : la finalité `facturation` exige le niveau `sensible`, et
  les autres sujets le niveau `general` (`identite_client.exiger_niveau`).
- **Fail-closed.** Une référence absente, mal formée, inconnue ou ambiguë produit le repli ; elle ne fait jamais
  deviner un dossier.

Module pur : aucune horloge, aucune base, aucun réseau.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import gabarits
from . import identite_client as ic

SUJETS = ("dossier", "soumission", "visite", "facture")
SUJET_DOSSIER, SUJET_SOUMISSION, SUJET_VISITE, SUJET_FACTURE = SUJETS
SOURCES = {
    SUJET_DOSSIER: "m02-revenue-crm",
    SUJET_SOUMISSION: "m03-estimation",
    SUJET_VISITE: "m04-field-ops",
    SUJET_FACTURE: "m05-financecore",
}
FINALITES = {
    SUJET_DOSSIER: "statut_dossier",
    SUJET_SOUMISSION: "statut_dossier",
    SUJET_VISITE: "statut_dossier",
    SUJET_FACTURE: "facturation",
}
LIBELLES_SUJET = {
    SUJET_DOSSIER: "dossier",
    SUJET_SOUMISSION: "soumission",
    SUJET_VISITE: "visite",
    SUJET_FACTURE: "facture",
}

# Les statuts bruts que les départements emploient AUJOURD'HUI. Toute autre valeur : repli. Ces tables ne sont pas
# des données d'affaires : ce sont des libellés de lecture, sans prix, sans date, sans engagement.
STATUTS: Mapping[str, Mapping[str, str]] = {
    SUJET_DOSSIER: {
        "nouveau": "en cours de prise en charge",
        "qualifie": "en qualification",
        "converti": "accepté, en préparation",
        "perdu": "fermé",
        "cedule": "planifié",
        "chantier": "travaux en cours",
        "facture": "en facturation",
        "paiement": "en attente de paiement",
        "avis": "suivi après les travaux",
    },
    SUJET_SOUMISSION: {
        "brouillon": "en préparation",
        "envoye": "envoyée, en attente de réponse",
        "accepte": "acceptée",
    },
    SUJET_VISITE: {
        "a_planifier": "à planifier",
        "planifiee": "planifiée",
        "en_route": "équipe en route",
        "sur_site": "en cours",
        "en_revue": "en revue",
        "reportee": "reportée",
        "completed_pending_review": "terminée, en vérification",
        "completed_verified": "terminée et vérifiée",
        "annulee": "annulée",
    },
    SUJET_FACTURE: {
        "BROUILLON": "en préparation",
        "ENVOYEE": "envoyée",
        "PAYEE": "payée",
        "ANNULEE": "annulée",
    },
}

TEXTE_REPLI = ic.TEXTE_SI_NON

# Motifs de repli : codes fermés, jamais un message du département ni une valeur du registre.
MOTIF_IDENTITE_NON_VERIFIEE = "identite_non_verifiee"
MOTIF_NIVEAU_INSUFFISANT = "niveau_insuffisant"
MOTIF_LECTEUR_INDISPONIBLE = "lecteur_indisponible"
MOTIF_LEAD_INTROUVABLE = "lead_introuvable"
MOTIF_LEAD_AMBIGU = "lead_ambigu"
MOTIF_REFERENCE_INVALIDE = "reference_invalide"
MOTIF_REFERENCE_INCONNUE = "reference_inconnue"
MOTIF_STATUT_INCONNU = "statut_inconnu"
MOTIF_STATUT_ETABLI = "statut_etabli"
MOTIFS = (
    MOTIF_IDENTITE_NON_VERIFIEE,
    MOTIF_NIVEAU_INSUFFISANT,
    MOTIF_LECTEUR_INDISPONIBLE,
    MOTIF_LEAD_INTROUVABLE,
    MOTIF_LEAD_AMBIGU,
    MOTIF_REFERENCE_INVALIDE,
    MOTIF_REFERENCE_INCONNUE,
    MOTIF_STATUT_INCONNU,
    MOTIF_STATUT_ETABLI,
)

# Une référence interne : lettres, chiffres et séparateurs usuels, bornée. Un texte libre, un chemin, un espace ou
# une accolade n'en est pas une.
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def finalite(sujet: str) -> str:
    return FINALITES[sujet]


def reference_valide(sujet: str, reference: Any) -> bool:
    """`dossier` : aucune référence. Les autres : une référence interne bornée. `facture_id` est une seconde
    référence facultative, du même domaine."""
    if sujet == SUJET_DOSSIER:
        return reference is None
    return isinstance(reference, str) and _REFERENCE.fullmatch(reference) is not None


def facture_id_valide(facture_id: Any) -> bool:
    return facture_id is None or (isinstance(facture_id, str) and _REFERENCE.fullmatch(facture_id) is not None)


def statut_lisible(sujet: str, brut: Any) -> str | None:
    """Le libellé client d'un statut brut, ou `None` : aucune valeur brute, aucun texte du département ne sort."""
    if not isinstance(brut, str):
        return None
    return STATUTS.get(sujet, {}).get(brut)


def repondre(sujet: str, brut: Any) -> dict[str, Any]:
    """La réponse d'un statut établi, ou le repli exact. `statut` de sortie : `repondu` ou `repli`."""
    libelle = statut_lisible(sujet, brut)
    if libelle is None:
        return repli(MOTIF_STATUT_INCONNU, sujet=sujet)
    try:
        _, corps = gabarits.rendre("statut_client", {"sujet": LIBELLES_SUJET[sujet], "statut": libelle})
    except gabarits.RefusGabarit:
        return repli(MOTIF_STATUT_INCONNU, sujet=sujet)
    return {
        "statut": "repondu",
        "sujet": sujet,
        "reponse": corps,
        "motif": MOTIF_STATUT_ETABLI,
    }


def repli(motif: str, *, sujet: str | None = None) -> dict[str, Any]:
    """Le repli EXACT, avec un motif d'ensemble fermé. Aucun détail brut, aucune existence révélée."""
    if motif not in MOTIFS:
        motif = MOTIF_IDENTITE_NON_VERIFIEE
    resultat: dict[str, Any] = {
        "statut": "repli",
        "sujet": sujet,
        "reponse": TEXTE_REPLI,
        "motif": motif,
    }
    return resultat
