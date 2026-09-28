"""Calcul des taxes (TPS/TVQ) en Decimal, à partir des taux fiscaux versionnés.

Bug NEW-PROD corrigé ici : les taux fiscaux déclarés dans
`contracts/taux_fiscaux.v1.yaml` (CA-M5-07) n'étaient utilisés par aucun calcul.
Ce module est le seul endroit du paquet qui multiplie un montant par un taux — le
taux est TOUJOURS lu via `taux_fiscaux.rechercher_taux` (jamais codé en dur ici ni
ailleurs, CA-M5-14) et converti en Decimal depuis sa représentation textuelle
(`Decimal(str(taux["taux"]))`, jamais `Decimal(taux["taux"])` qui importerait
l'imprécision binaire du float source).
"""

from __future__ import annotations

from decimal import Decimal

from . import taux_fiscaux, validation

_DEUX_DECIMALES = Decimal("0.01")
_IDS_TAXES_QUEBEC_DEFAUT = ("tps_federale", "tvq_quebec")


def calculer_taxes(montant_avant_taxes, dictionnaire_taux, ids_taux=_IDS_TAXES_QUEBEC_DEFAUT):
    """Calcule chaque taxe listée dans `ids_taux` sur `montant_avant_taxes`.

    `dictionnaire_taux` est le dictionnaire chargé par
    `taux_fiscaux.charger_taux_fiscaux` depuis le fichier versionné courant.
    Bloque par verdict nommé (REJ-TAUX-INCONNU) si un identifiant demandé est
    absent de la déclaration versionnée — jamais une approximation ou un dernier
    taux connu réutilisé silencieusement (CA-M5-07).
    """
    if not isinstance(montant_avant_taxes, Decimal) or not montant_avant_taxes.is_finite():
        return None, validation.construire_verdict(
            "REJ-MOUVEMENT-MONTANT-INVALIDE",
            detail="montant_avant_taxes doit être un Decimal fini",
        )

    detail_taxes = []
    total_taxes = Decimal("0")
    for taux_id in ids_taux:
        taux, verdict = taux_fiscaux.rechercher_taux(dictionnaire_taux, taux_id)
        if verdict is not None:
            return None, verdict
        taux_decimal = Decimal(str(taux["taux"]))
        montant_taxe = (montant_avant_taxes * taux_decimal).quantize(_DEUX_DECIMALES)
        detail_taxes.append(
            {
                "id": taux_id,
                "nom": taux["nom"],
                "version": taux["version"],
                "taux": str(taux_decimal),
                "montant": montant_taxe,
            }
        )
        total_taxes += montant_taxe

    return {
        "montant_avant_taxes": montant_avant_taxes,
        "taxes": detail_taxes,
        "total_taxes": total_taxes,
        "montant_apres_taxes": montant_avant_taxes + total_taxes,
    }, None
