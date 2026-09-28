"""Bus d'événements du socle OPSYS (ADR-0009 §3) : outbox durcie, catalogue, répartiteur.

API fixée (§3, T1.2-a) — d'autres départements la consomment, sa signification ne change pas :

    publier(type_evenement, producteur, charge, *, evenement_id=None) -> str
    repartir(departements, *, limite=100, maintenant=None) -> dict
    etat() -> dict

`publier` écrit dans `evenements_sortants` DANS la transaction métier courante (`stockage.transaction`,
point de sauvegarde si imbriquée) : l'écriture qui déclenche l'événement et l'événement lui-même sont
atomiques. La charge est validée contre le schéma JSON du catalogue (`catalogue/*.json`, un fichier par
type, `$id: opsys.evenement/v1/<type>`), avec `outils.valider_arguments` — aucune nouvelle dépendance.

Un département déclare ce qu'il publie et consomme dans `department.yaml` (`evenements: {publie,
consomme}`, optionnel) et fournit les fonctions de ses types consommés dans `consommateurs() -> dict[str,
Callable[[dict], dict]]`, au même endroit que ses outils (`module_outils` du manifeste — voir
`docs/architecture/DEPARTEMENTS.md`). `repartir` les appelle ; `verifier_coherence` (utilisée par `opsys
verifier`) détecte une déclaration incohérente : type absent du catalogue, type consommé sans fonction,
fonction orpheline.
"""

from __future__ import annotations

from .bus import ChargeInvalide, publier
from .repartiteur import etat, repartir, verifier_coherence
from .schemas import TypeEvenementInconnu, schema, types_connus

__all__ = [
    "ChargeInvalide",
    "TypeEvenementInconnu",
    "etat",
    "publier",
    "repartir",
    "schema",
    "types_connus",
    "verifier_coherence",
]
