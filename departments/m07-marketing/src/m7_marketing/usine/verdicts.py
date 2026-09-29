"""Codes de refus de l'usine à contenu (PLAN T4.17) : un verdict `{code, detail}` dit quoi corriger ou demander.

Un refus métier n'est pas une panne : il est rendu à l'agent tel quel (`{accepte: False, verdict}`), jamais
masqué. Même forme que M10 (`validation.construire_verdict`), sans importer M10.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

from typing import Any

REJ_CONTENU_INCONNU = "REJ-CONTENU-INCONNU"
REJ_CONTENU_DEJA_TRANCHE = "REJ-CONTENU-DEJA-TRANCHE"
REJ_CONTENU_PERIME = "REJ-CONTENU-PERIME"
REJ_CONTENU_NON_APPROUVE = "REJ-CONTENU-NON-APPROUVE"
REJ_CONTENU_MODIFIE = "REJ-CONTENU-MODIFIE-APRES-APPROBATION"
REJ_CONSENTEMENT_RETIRE = "REJ-CONSENTEMENT-RETIRE"
REJ_TEXTE_NON_CONFORME = "REJ-TEXTE-NON-CONFORME"
REJ_PROFIL_MARQUE = "REJ-PROFIL-MARQUE-NON-CONFIGURE"
REJ_DECISION_INVALIDE = "REJ-DECISION-INVALIDE"
REJ_MOTIF_REQUIS = "REJ-MOTIF-REQUIS"
REJ_HORODATAGE_INVALIDE = "REJ-HORODATAGE-INVALIDE"
REJ_RETRAIT_INVALIDE = "REJ-RETRAIT-INVALIDE"
REJ_HUMAIN_REQUIS = "REJ-HUMAIN-REQUIS"
REJ_HUMAIN_IDENTITE_INVALIDE = "REJ-HUMAIN-IDENTITE-INVALIDE"
REJ_HUMAIN_ROLE_INSUFFISANT = "REJ-HUMAIN-ROLE-INSUFFISANT"
REJ_HUMAIN_ACTEUR_INVALIDE = "REJ-HUMAIN-ACTEUR-INVALIDE"


def verdict(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}
