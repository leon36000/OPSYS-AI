from __future__ import annotations

import copy

from . import encodage, soldes

_TYPE_ETAT_FINANCIER = "ETAT_FINANCIER"


def construire_etat_financier(
    registre_mouvements, taux_utilises, role=None, autorise_couts=False
):
    """Fail-closed par construction (bug NEW-PROD : autorise_couts=True par défaut
    exposait le solde à un rôle non autorisé, ex. « employe »). L'appelant doit
    fournir explicitement autorise_couts=True pour voir solde/argent_disponible ;
    aucune valeur par défaut ne doit jamais exposer une donnée financière."""
    if autorise_couts:
        solde = soldes.calculer_solde(registre_mouvements)
        argent_disponible = soldes.calculer_argent_disponible(registre_mouvements)
        taux_visibles = copy.deepcopy(list(taux_utilises))
    else:
        solde = None
        argent_disponible = None
        taux_visibles = []

    contenu = {
        "type": _TYPE_ETAT_FINANCIER,
        "role": role,
        "solde": solde,
        "argent_disponible": argent_disponible,
        "taux_utilises": taux_visibles,
    }
    etat_id = encodage.empreinte(contenu)

    return {**contenu, "etat_id": etat_id}
