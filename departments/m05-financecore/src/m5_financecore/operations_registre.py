"""Le registre des opérations comptables de M5 : relances préparées, notes de crédit, dépenses d'employés, pièces
justificatives, paiements fournisseurs PRÉPARÉS, rapprochements bancaires, périodes, jugements, mesures, flux
fournisseur et dossiers CPA scellés.

Module pur (même règle que `grand_livre.py`) : aucun import d'`opsys`, aucune horloge, aucun accès réseau. Il reçoit un
`registre_cible` déjà construit (duck-typé : `ajouter`, `lire`) que l'adaptateur adosse au registre durable DÉDIÉ
`operations_comptables` (append-only, hash-chaîné) : aucune migration. Il ne nomme jamais le registre des mouvements :
une opération comptable ne fait bouger aucun argent (`conformite.verifier_aucun_decaissement`, strict).

Chaque opération porte une CLÉ d'idempotence (`cle`) ; son identifiant est l'empreinte de (type, clé), donc le même
geste rejoué rend la même opération sans rien écrire. La même clé avec un autre contenu est un conflit
(`REJ-OPS-DOUBLON`), jamais un écrasement. Une opération n'est jamais modifiée : sa suite (par exemple la confirmation
humaine d'un rapprochement) est un maillon de plus.

Concurrence : deux appels qui auraient lu le même état et écrit la même opération laissent un doublon ; le premier
maillon fait foi, le suivant est ignoré et compté (`doublons`), la lecture continue. Une ANOMALIE (identifiant
incohérent avec la clé, contenu altéré, maillon étranger ou illisible) fait refuser toute lecture : jamais un chiffre
faux.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import encodage, verdicts_operations

__all__ = ["ajouter_operation", "etat_operations", "identifiant", "TYPES_OPERATION"]

# type de maillon -> (champ identifiant, préfixe lisible de l'identifiant)
TYPES_OPERATION: dict[str, tuple[str, str]] = {
    "op_relance_preparee": ("relance_id", "rel"),
    "op_note_credit_proposee": ("note_id", "ncr"),
    "op_depense_employe_proposee": ("depense_id", "dep"),
    "op_piece_liee": ("piece_id", "pie"),
    "op_paiement_prepare": ("paiement_id", "pai"),
    "op_rapprochement_prepare": ("rapprochement_id", "rap"),
    "op_rapprochement_confirme": ("confirmation_id", "cnf"),
    "op_periode_ouverte": ("ouverture_id", "ouv"),
    "op_precloture_constatee": ("precloture_id", "pre"),
    "op_jugement_enregistre": ("jugement_id", "jug"),
    "op_mesures_constatees": ("mesure_id", "mes"),
    "op_flux_fournisseur_constate": ("flux_id", "flx"),
    "op_dossier_cpa_scelle": ("dossier_id", "dos"),
}
_CHAMPS_RESERVES = ("type_entree", "ligne_id", "precedent_ligne_id")


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def identifiant(type_entree: str, cle: str) -> str:
    """L'identifiant déterministe d'une opération : même type et même clé, même identifiant, sur toute machine."""
    champ, prefixe = TYPES_OPERATION[type_entree]
    del champ
    return f"{prefixe}-" + encodage.empreinte("m5.operations.cle", type_entree, cle)[:20]


def _corps(maillon: Mapping[str, Any]) -> dict[str, Any]:
    return {
        cle: valeur for cle, valeur in maillon.items() if cle not in _CHAMPS_RESERVES and cle != "empreinte_contenu"
    }


def _empreinte_contenu(type_entree: str, corps: Mapping[str, Any]) -> str:
    return encodage.empreinte("m5.operations.contenu.v1", type_entree, dict(corps))


def etat_operations(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """L'état relu des maillons, dans l'ordre : `parType[type][identifiant]` (le premier maillon fait foi), `ordre`
    (les identifiants dans l'ordre d'écriture, par type), `doublons` et `anomalies`."""
    par_type: dict[str, dict[str, dict[str, Any]]] = {type_entree: {} for type_entree in TYPES_OPERATION}
    ordre: dict[str, list[str]] = {type_entree: [] for type_entree in TYPES_OPERATION}
    anomalies: list[str] = []
    doublons: list[str] = []
    for maillon in maillons:
        type_entree = maillon.get("type_entree") if isinstance(maillon, Mapping) else None
        if type_entree not in TYPES_OPERATION:
            anomalies.append(f"maillon de type {type_entree!r} étranger aux opérations comptables")
            continue
        champ = TYPES_OPERATION[type_entree][0]
        try:
            ident = maillon[champ]
            cle = maillon["cle"]
            if ident != identifiant(type_entree, cle):
                anomalies.append(f"{type_entree} {ident!r} d'identifiant incohérent avec sa clé")
            elif maillon["empreinte_contenu"] != _empreinte_contenu(type_entree, _corps(maillon)):
                anomalies.append(f"{type_entree} {ident} : contenu altéré")
            elif ident in par_type[type_entree]:
                doublons.append(f"{type_entree} {ident} écrit de nouveau (le premier maillon fait foi)")
            else:
                par_type[type_entree][ident] = dict(maillon)
                ordre[type_entree].append(ident)
        except (KeyError, TypeError):
            anomalies.append(f"maillon {type_entree!r} illisible")
    return {"par_type": par_type, "ordre": ordre, "doublons": doublons, "anomalies": anomalies}


def refus_anomalies(etat: Mapping[str, Any]) -> dict[str, str] | None:
    if etat["anomalies"]:
        return _verdict("REJ-OPS-CHAINE-INVALIDE", "; ".join(etat["anomalies"][:3]))
    return None


def ajouter_operation(
    registre_cible: Any,
    etat: Mapping[str, Any],
    type_entree: str,
    cle: str,
    corps: Mapping[str, Any],
    horodatage: str,
    hors_identite: Sequence[str] = (),
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Écrit l'opération `(type_entree, cle)` ou la reconnaît. `({"statut": "ecrite"|"deja", "operation": maillon},
    None)` ; `(None, verdict)` si la même clé porte déjà un AUTRE contenu (`REJ-OPS-DOUBLON`). `etat` est l'état lu
    AVANT l'appel (l'appelant l'a déjà contrôlé : `refus_anomalies`). Le corps ne contient ni `type_entree`, ni
    `cle`, ni identifiant : ils sont posés ici. `hors_identite` : les champs du corps qui sont ÉCRITS mais ne font
    pas l'identité de
    l'opération (par exemple les têtes de registres qu'un rapprochement a lues : elles changent à chaque écriture)."""
    if type_entree not in TYPES_OPERATION:
        raise ValueError(f"type d'opération inconnu : {type_entree!r}")
    if not isinstance(cle, str) or not cle.strip() or len(cle) > 300:
        return None, _verdict("REJ-OPS-ENTREE-INVALIDE", "clé d'opération vide ou démesurée")
    champ = TYPES_OPERATION[type_entree][0]
    if any(nom in corps for nom in (*_CHAMPS_RESERVES, "cle", champ, "empreinte_contenu", "horodatage")):
        raise ValueError("le corps d'une opération ne porte pas les champs que ce module pose")
    ident = identifiant(type_entree, cle)
    complet = {champ: ident, "cle": cle, **dict(corps), "horodatage": horodatage}
    empreinte = _empreinte_contenu(type_entree, complet)
    existant = etat["par_type"][type_entree].get(ident)
    if existant is not None:
        # L'horodatage fait partie du corps, mais deux appels qui rejouent le MÊME geste n'ont pas le même instant :
        # l'identité d'une opération est sa clé et son contenu SANS l'instant.
        exclus = {"horodatage", *hors_identite}
        sans_instant = {k: v for k, v in complet.items() if k not in exclus}
        existant_sans_instant = {k: v for k, v in _corps(existant).items() if k not in exclus}
        if encodage.empreinte(sans_instant) == encodage.empreinte(existant_sans_instant):
            return {"statut": "deja", "operation": existant}, None
        return None, _verdict("REJ-OPS-DOUBLON", f"la clé {cle!r} porte déjà l'opération {ident}, d'un autre contenu")
    ligne_id = registre_cible.ajouter({"type_entree": type_entree, **complet, "empreinte_contenu": empreinte})
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return {"statut": "ecrite", "operation": maillon}, None
    raise RuntimeError("maillon des opérations ajouté introuvable")
