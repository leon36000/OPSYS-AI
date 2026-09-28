"""Politiques d'autonomie : quand une action exige une approbation humaine.

Trois modes par département :
- ``ombre``     : le département propose, un humain approuve toute écriture (T1/N3 et plus) ;
- ``supervise`` : les écritures internes passent, toute action externe (T2/N4) est approuvée ;
- ``autonome``  : seules les frontières humaines (T3/N5) sont approuvées.
T3/N5 exige TOUJOURS une approbation : paiements, écritures financières, publication,
engagements externes et suppressions ne sont jamais autonomes.

La règle s'exprime en N (ADR-0009 §4) : `approbation_requise_niveau` est la version de référence,
`approbation_requise` (en T) est conservée pour compatibilité et délègue à la première via la
correspondance par défaut (`niveau_par_defaut`) — mêmes seuils qu'avant, aucune régression.

Ces seuils décident quand un AGENT doit attendre un humain. Ils ne disent rien de l'humain qui agit
lui-même : `validation_au_depart_possible` (ADR-0009 §4, addendum T1.4-h) fixe jusqu'où sa propre
action tient lieu de validation (N3 au plus) ; l'application (identité, portée du rôle, trace) est
dans `opsys.capacites`.
"""

from __future__ import annotations

from .outils import Autonomie, Niveau, niveau_par_defaut

MODES = ("ombre", "supervise", "autonome")

# Seuils exprimés en N : mêmes seuils que l'ancienne échelle T (ombre -> T1, supervise -> T2,
# autonome -> T3), traduits par la correspondance par défaut documentée dans l'ADR.
_SEUIL_APPROBATION_NIVEAU = {
    "ombre": Niveau.N3,
    "supervise": Niveau.N4,
    "autonome": Niveau.N5,
}
_RANG_NIVEAU = {niveau: rang for rang, niveau in enumerate(Niveau)}


# Plafond de la « validation humaine au départ » (ADR-0009 §4, addendum T1.4-h) : ADR-0009 §4 définit
# N3 comme « validation humaine au départ » ; quand la personne authentifiée lance elle-même l'action
# depuis son appareil, cette validation est faite. Elle ne s'étend jamais au-delà : N4 (engagement)
# est décidé par le propriétaire, N5 par le propriétaire ET l'attestation du professionnel.
PLAFOND_VALIDATION_AU_DEPART = Niveau.N3


def valider_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode de département inconnu {mode!r} (attendu : {', '.join(MODES)})")
    return mode


def approbation_requise_niveau(niveau: Niveau, mode: str) -> bool:
    """Vrai si une demande de ce niveau N doit passer par la file d'approbation dans ce mode
    (ADR-0009 §4) : au niveau du seuil du mode, ou au-dessus."""
    seuil = _SEUIL_APPROBATION_NIVEAU[valider_mode(mode)]
    return _RANG_NIVEAU[niveau] >= _RANG_NIVEAU[seuil]


def validation_au_depart_possible(niveau: Niveau) -> bool:
    """Vrai si l'action d'un outil de ce niveau N PEUT être validée au départ par la personne
    authentifiée qui la lance elle-même (N3 au plus, `PLAFOND_VALIDATION_AU_DEPART`).

    Condition NÉCESSAIRE, jamais suffisante : `opsys.capacites` exige en plus une identité de jeton
    d'appareil valide (personne active portant ce rôle) et un outil dans la portée de ce rôle. Ne
    dépend pas du mode du département : le mode décide si une approbation est requise, cette
    fonction décide seulement si l'humain qui agit peut en tenir lieu.
    """
    return _RANG_NIVEAU[niveau] <= _RANG_NIVEAU[PLAFOND_VALIDATION_AU_DEPART]


def approbation_requise(autonomie: Autonomie, mode: str) -> bool:
    """Vrai si l'outil de ce palier T doit passer par la file d'approbation dans ce mode.

    Conservée pour compatibilité, aucune régression : délègue à `approbation_requise_niveau` via la
    correspondance par défaut T -> N (`niveau_par_defaut`, ADR-0009 §4). Un outil qui fixe un
    `Outil.niveau` explicite doit être vérifié avec `approbation_requise_niveau(outil.niveau_effectif,
    mode)` pour que ce choix soit respecté (c'est ce que fait `opsys.capacites`).
    """
    return approbation_requise_niveau(niveau_par_defaut(autonomie), mode)
