"""Le RÉSUMÉ agrégé du pré-audit, publié pour M8 (`m5.preaudit_constate`, M5-PRE-AUDIT).

Module pur : aucune entrée-sortie, aucune horloge. Même patron que `m2_revenue_crm/constat_filet.py` : M8 n'appelle
aucun
outil de M5, M5 publie sur le bus les COMPTES que le contrôleur (`controleur_preaudit.py`) établit, sans rien de ce qui
identifie une facture, un fournisseur, un client, une écriture ou un montant.

Ce qui part : le nombre de constats par règle (`null` pour une règle NON ÉVALUÉE faute de seuil déclaré ou de grand
livre
lisible : jamais un zéro), leur total (la somme des règles évaluées ; `null` quand AUCUNE règle n'est évaluée), le
nombre
de constats par gravité, les règles non évaluées et celles évaluées en partie, par leur nom.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import controleur_preaudit, encodage

__all__ = ["charge_preaudit", "version_preaudit"]


def version_preaudit(contenu: Mapping[str, Any]) -> str:
    """La version des DONNÉES (16 hexadécimaux) : tout sauf l'identifiant et les instants. Les mêmes constats
    redonnent la
    même version."""
    sans_id = {
        cle: valeur for cle, valeur in contenu.items() if cle not in ("evenement_id", "date_reference", "constate_le")
    }
    return encodage.empreinte(["m5.preaudit_constate.v1", sans_id])[:16]


def charge_preaudit(rapport: Mapping[str, Any], date_reference: str, constate_le: str) -> dict[str, Any]:
    """La charge de `m5.preaudit_constate` à partir de `controleur_preaudit.controler`. `constate_le` entre dans
    l'identifiant (jamais dans la version des données) : un retour à une version antérieure (A, puis B, puis A)
    publie un
    événement DISTINCT ; rejouer le même constat (même instant) n'en publie aucun de plus."""
    par_regle = {regle: rapport["par_regle"][regle] for regle in controleur_preaudit.REGLES}
    evaluees = [n for n in par_regle.values() if n is not None]
    contenu: dict[str, Any] = {
        "date_reference": date_reference,
        "constats_par_regle": par_regle,
        "constats_total": sum(evaluees) if evaluees else None,
        "constats_par_gravite": {g: rapport["par_gravite"][g] for g in controleur_preaudit.GRAVITES},
        "regles_non_evaluees": [r["regle"] for r in rapport["regles"] if r["etat"] == "NON_EVALUEE"],
        "regles_partielles": [r["regle"] for r in rapport["regles"] if r["etat"] == "PARTIELLE"],
    }
    version = version_preaudit(contenu)
    marque = encodage.empreinte(["m5.preaudit_constate.constate_le", constate_le])[:8]
    return {
        "evenement_id": f"m5-preaudit-{date_reference}-{version}-{marque}",
        "constate_le": constate_le,
        "version_donnees": version,
        **contenu,
    }
