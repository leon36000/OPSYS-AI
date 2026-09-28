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

PLAN T1.2-d (partie M6) : `m3.devis_accepte` (catalogue) est maintenant la source normale
(`outils.py::_recevoir_devis_accepte`), `m6_enregistrer_besoins_prevus` restant la voie
manuelle. Deux assouplissements, en service des deux besoins réels de ce flux :
- `chantier_id` PEUT être `None` (mais pas une chaîne vide, toujours refusée) : un devis peut
  être accepté avant que M4 planifie le chantier (M3 ne le connaît pas encore à la création du
  devis, `m3.devis_accepte.json::chantier_id` est nullable) — jamais un chantier inventé ici ;
  `outils.py::_evaluer_et_publier_variance` le résout plus tard depuis la déclaration, qui le
  connaît toujours.
- `lignes` PEUT être vide : un devis accepté sans aucune ligne reliée à un besoin matériau
  (`reference_besoin_materiau` toujours nul côté M3) est un PRÉVU VIDE CONNU, distinct d'un
  prévu ABSENT (aucun maillon enregistré pour ce devis_id — `pour_devis` rend `None`, jamais
  confondu avec un maillon dont `lignes == []`) : l'ancien refus `REJ-BESOINS-PREVUS-LIGNES-
  VIDES` masquait cette distinction pour rien — `variance_chantier.evaluer` traite déjà
  chaque matériau déclaré sans prévu comme `NON_PREVU` (`ecart_pourcentage` indéfini, jamais
  critique), donc un chantier sans aucun matériau prévu reste évaluable normalement, jamais
  bloqué en revue pour la seule raison qu'aucune ligne n'était prévue.
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
    # chantier_id : None accepté (T1.2-d, devis accepté avant que M4 planifie -- jamais deviné
    # ici), une chaîne vide ne l'est jamais (ce serait un champ fourni mais vidé, pas « inconnu
    # pour l'instant »).
    if chantier_id is not None and (not isinstance(chantier_id, str) or not chantier_id):
        return None, "REJ-BESOINS-PREVUS-CHANTIER-MANQUANT"
    if not isinstance(devis_id, str) or not devis_id:
        return None, "REJ-BESOINS-PREVUS-DEVIS-MANQUANT"

    ok, code = validation.valider_besoins_estimes_chantier(lignes)
    if not ok:
        return None, code
    # lignes VIDE est un prévu VIDE CONNU (T1.2-d, docstring du module), pas un refus : distinct
    # d'un prévu ABSENT parce que pour_devis(devis_id, ...) rend None seulement quand AUCUN
    # maillon n'existe pour ce devis_id, jamais quand un maillon existe avec lignes == [].

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
