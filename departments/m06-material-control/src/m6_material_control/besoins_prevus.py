"""Besoins matériaux PRÉVUS d'un chantier — PLAN T1.2-b (M6), « M6 garde le prévu ».

C'est le « prévu » que `variance_chantier.py` compare au réel déclaré (T1.1-d2). Source
produit : le devis M3 (M6.4, T2.3-a — en préparation ailleurs, par événement plus tard) ;
en attendant cet événement, `chantier_id`/`devis_id`/`lignes` sont fournis DIRECTEMENT par
l'appelant de `m6_enregistrer_besoins_prevus` (outils.py).

DISTINCT du registre de mouvements de stock (`registre.py`, `TYPES_MOUVEMENT_VALIDES`) : un
besoin prévu ne fait bouger AUCUNE quantité de stock, donc il ne partage ni sa forme
(`_CHAMPS_MOUVEMENT_REQUIS` exige `quantite`/`cout_unitaire`/`type_mouvement`) ni ses gardes
(`conformite.DESIGNATION_TYPE_MOUVEMENT`). Il vit dans son propre registre durable append-only
(`opsys.stockage.maillons(dept, "besoins_prevus")`, branché côté `outils.py` — module pur ici,
comme `variance_chantier.py` : aucun import `opsys`).

Module pur (AGENTS.md, docs/decisions/ADR-0009-socle-metier.md) : `maillons_existants` est
n'importe quel itérable de dicts déjà enregistrés (protocole liste, comme partout ailleurs dans
ce paquet) — une liste Python en mémoire (tests) ou `opsys.stockage.MaillonsDurables`
(production), au choix de l'appelant.

Idempotent par `devis_id` (même discipline que `materiel.soumettre_materiaux_utilises` par
`wct_id`, REJ-DECLARATION-DEJA-SOUMISE) : une seconde tentative pour le même devis_id est
refusée nommément, JAMAIS réécrite ni fusionnée avec la première — fusionner inventerait un
jeu de besoins que personne n'a affirmé tel quel (P2, AGENTS.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import validation

__all__ = ["enregistrer", "pour_devis"]


def enregistrer(
    chantier_id: Any, devis_id: Any, lignes: Any, maillons_existants: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, str | None]:
    """Valide puis construit le maillon des besoins prévus d'un chantier (sans l'écrire :
    l'appelant — `outils.py` — fait l'ajout, seul point où `opsys.stockage` est touché).

    Returns:
        (maillon, None) si accepté, (None, code) sinon — aucune écriture dans les deux cas,
        cette fonction ne mute jamais `maillons_existants`.
    """
    if not isinstance(chantier_id, str) or not chantier_id:
        return None, "REJ-BESOINS-PREVUS-CHANTIER-MANQUANT"
    if not isinstance(devis_id, str) or not devis_id:
        return None, "REJ-BESOINS-PREVUS-DEVIS-MANQUANT"

    ok, code = validation.valider_besoins_estimes_chantier(lignes)
    if not ok:
        return None, code
    # Une liste VALIDE mais vide n'est pas un « prévu » : ce serait indistinguable, plus loin
    # dans la chaîne, d'un devis qui n'a simplement jamais été enregistré (prevu_absent) —
    # fail-closed nommé plutôt qu'un prévu silencieusement vide.
    if not lignes:
        return None, "REJ-BESOINS-PREVUS-LIGNES-VIDES"

    for maillon in maillons_existants:
        if maillon.get("devis_id") == devis_id:
            return None, "REJ-BESOINS-PREVUS-DEJA-ENREGISTRES"

    return {"chantier_id": chantier_id, "devis_id": devis_id, "lignes": lignes}, None


def pour_devis(devis_id: Any, maillons_existants: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Besoins prévus enregistrés pour ce `devis_id`, ou `None` si aucun (PLAN T1.2, M6 point 3 :
    « prevu_absent »). Il n'en existe jamais plus d'un par devis_id (idempotence de
    `enregistrer` ci-dessus) : le premier trouvé EST le seul."""
    if not isinstance(devis_id, str) or not devis_id:
        return None
    for maillon in maillons_existants:
        if maillon.get("devis_id") == devis_id:
            return maillon
    return None
