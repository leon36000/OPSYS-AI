"""Le RÉSUMÉ agrégé de la disponibilité du matériel, publié pour M8 (`m6.disponibilite_constatee`, D2 de
`docs/architecture/M8-ENTREPOT-SOURCES.md`).

Module pur : aucune entrée-sortie, aucune horloge. M8 ne lit aucun outil de M6 : M6 publie, sur le bus, CINQ comptes,
sans
article, sans quantité, sans prix, sans fournisseur et sans chantier.

- `articles_suivis` : les articles connus des registres (mouvements, transferts d'emplacement, lignes de réservation
active) ;
- `articles_en_rupture` : ceux dont le disponible (en main moins réservé, `stock.deriver_disponibilite`) est nul ou
négatif ;
- `articles_sur_reserves` : ceux réservés au-delà de ce qui est en main ;
- `reservations_actives` : les réservations de chantier actives ;
- `reservations_incompletes` : celles qui ne sont pas prêtes (`partiel` ou `a_commander`).
Un registre vide donne des zéros VÉRIDIQUES (rien n'est suivi) : le compte `articles_suivis` le dit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from . import emplacements, encodage, reservations, stock

__all__ = ["charge_disponibilite", "version_disponibilite"]

_ZERO = Decimal(0)


def version_disponibilite(contenu: Mapping[str, Any]) -> str:
    """La version des DONNÉES (16 hexadécimaux) : tout sauf l'identifiant et le jour."""
    sans_id = {
        cle: valeur for cle, valeur in contenu.items() if cle not in ("evenement_id", "date_reference", "constate_le")
    }
    return encodage.empreinte(["m6.disponibilite_constatee.v1", sans_id])[:16]


def charge_disponibilite(
    mouvements: Iterable[Mapping[str, Any]],
    transferts: Iterable[Mapping[str, Any]],
    faits_reservation: Iterable[Mapping[str, Any]],
    date_reference: str,
    constate_le: str,
) -> dict[str, Any]:
    """La charge de `m6.disponibilite_constatee` à partir des trois registres durables de M6. `constate_le` : l'instant
    du
    constat ; il entre dans l'identifiant (jamais dans la version des données) pour qu'un retour à une version
    antérieure
    (A, puis B, puis A) ne se confonde pas avec la première publication."""
    mouvements, transferts, faits = list(mouvements), list(transferts), list(faits_reservation)
    en_cours = reservations.actives(faits)
    connus = {m["materiau_id"] for m in mouvements if isinstance(m.get("materiau_id"), str)}
    connus |= {t["materiau_id"] for t in transferts if t.get("type_entree") == emplacements.TYPE_TRANSFERT}
    connus |= {ligne["materiau_id"] for e in en_cours for ligne in e["lignes"]}
    chiffres = stock.deriver_disponibilite(
        sorted(connus),
        mouvements,
        emplacements.hors_main_par_article(transferts),
        reservations.reserve_par_article(faits),
    )
    contenu: dict[str, Any] = {
        "date_reference": date_reference,
        "articles_suivis": len(connus),
        "articles_en_rupture": sum(1 for c in chiffres.values() if c["disponible"] <= _ZERO),
        "articles_sur_reserves": sum(1 for c in chiffres.values() if c["reserve"] > c["en_main"]),
        "reservations_actives": len(en_cours),
        "reservations_incompletes": sum(
            1 for e in en_cours if reservations.statut_pret(e["lignes"]) != reservations.STATUT_PRET
        ),
    }
    version = version_disponibilite(contenu)
    marque = encodage.empreinte(["m6.disponibilite_constatee.constate_le", constate_le])[:8]
    return {
        "evenement_id": f"m6-disponibilite-{date_reference}-{version}-{marque}",
        "constate_le": constate_le,
        "version_donnees": version,
        **contenu,
    }
