"""Le RÉSUMÉ agrégé du filet anti-perte, publié pour M8 (`m2.filet_anti_perte_constate`, M2-C1).

Module pur : aucune entrée-sortie, aucune horloge. Même patron que `constat_pipeline.py` : M8 ne lit aucun outil de M2,
M2
publie sur le bus les COMPTES que le scan SLA (`sla.py`) et l'audit d'intégrité (`integrite.py`) établissent sur TOUS
les
leads, sans rien de ce qui identifie un lead, un client, un contact, un vendeur ou un devis.

Ce qui part : le nombre de leads examinés, le nombre de violations par règle SLA (`null` pour une règle NON ÉVALUÉE
faute de
seuil déclaré : jamais un zéro), leur total (la somme des règles évaluées, en entier ou en partie ; `null` quand AUCUNE
règle n'est évaluée), les règles non évaluées et celles
évaluées en partie (leur partie sans délai seulement) par leur nom, le nombre d'anomalies par contrôle d'intégrité
(`null` pour un contrôle non évalué), leur total et les contrôles
non évalués par leur nom.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import encodage, integrite, sla

__all__ = ["charge_filet", "version_filet"]


def version_filet(contenu: Mapping[str, Any]) -> str:
    """La version des DONNÉES (16 hexadécimaux) : tout sauf l'identifiant et les instants. Les mêmes données redonnent
    la
    même version."""
    sans_id = {
        cle: valeur for cle, valeur in contenu.items() if cle not in ("evenement_id", "date_reference", "constate_le")
    }
    return encodage.empreinte(["m2.filet_anti_perte_constate.v1", sans_id])[:16]


def charge_filet(rapport: Mapping[str, Any], date_reference: str, constate_le: str) -> dict[str, Any]:
    """La charge de `m2.filet_anti_perte_constate` à partir de `filet.produire` (clés `sla` et `integrite`).
    `constate_le` entre dans l'identifiant (jamais dans la version des données) : un retour à une version antérieure
    (A, puis B, puis A) ne se confond pas avec la première publication."""
    regles = {r["regle"]: r for r in rapport["sla"]["regles"]}
    controles = {c["controle"]: c for c in rapport["integrite"]["controles"]}
    violations_par_regle = {regle: regles[regle]["violations"] for regle in sla.ORDRE_REGLES}
    anomalies_par_controle = {controle: controles[controle]["anomalies"] for controle in integrite.CONTROLES}
    evaluees = [n for n in violations_par_regle.values() if n is not None]
    contenu: dict[str, Any] = {
        "date_reference": date_reference,
        "leads_examines": rapport["integrite"]["leads_examines"],
        "violations_par_regle": violations_par_regle,
        "violations_total": sum(evaluees) if evaluees else None,
        "regles_non_evaluees": [r for r in sla.ORDRE_REGLES if violations_par_regle[r] is None],
        "regles_partielles": [r for r in sla.ORDRE_REGLES if regles[r]["etat"] == sla.ETAT_PARTIELLE],
        "anomalies_par_controle": anomalies_par_controle,
        "anomalies_total": sum(n for n in anomalies_par_controle.values() if n is not None),
        "controles_non_evalues": [c for c in integrite.CONTROLES if anomalies_par_controle[c] is None],
    }
    version = version_filet(contenu)
    marque = encodage.empreinte(["m2.filet_anti_perte_constate.constate_le", constate_le])[:8]
    return {
        "evenement_id": f"m2-filet-{date_reference}-{version}-{marque}",
        "constate_le": constate_le,
        "version_donnees": version,
        **contenu,
    }
