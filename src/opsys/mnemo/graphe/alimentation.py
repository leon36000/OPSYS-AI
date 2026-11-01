"""Alimentation du graphe par les événements du bus que M10 consomme déjà : BROUILLON d'arête, confirmation si sensible.

| Événement | Nœuds | Arêtes proposées |
|---|---|---|
| `m2.client_associe` | client (pseudonyme) | — |
| `m2.profil_propriete_confirme` | client, propriété (pseudonymes) | `possede` client → propriété (SENSIBLE) |
| `m4.travaux_termines` | intervention | `demande` client → intervention (SENSIBLE), si le client du lead est connu |
| `m6.variance_chantier` | intervention, matériau | `utilise` intervention → matériau (matériau réellement utilisé) |

Règle de confirmation : une arête NON sensible issue du bus est confirmée par le système (écriture interne réversible
: elle se ferme) ; une arête SENSIBLE (une extrémité personnelle, Loi 25) reste en BROUILLON jusqu'à la confirmation
d'une personne. Le plan est une fonction pure de la charge ; `appliquer` l'écrit par le port.

Minimisation : seuls les identifiants sont retenus (pseudonymes, identifiants d'intervention et de matériau). Ni nom, ni
adresse, ni ville, ni texte libre, ni technicien (une personne) ne passe de la charge au graphe. Un identifiant qui ne
respecte pas le schéma est un refus nommé dans le décompte, jamais une écriture partielle silencieuse.

La source de chaque arête est la ligne du registre de M10 qui a mémorisé l'événement
(`registre:evenements:<ligne_id>`) : elle est vérifiable et liée à la chaîne de hash. Seule exception,
`m2.profil_propriete_confirme`, que M10 ne mémorise pas ailleurs : sa source est l'identifiant du fait publié
(`bus:m2.profil_propriete_confirme:<fait_id>`), moins forte (elle ne se vérifie pas dans la chaîne de M10).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from .. import codes, vie_privee
from ..codes import ErreurMnemo
from .port import DemandeArete, MoteurGraphe
from .schema import NoeudRef

EVENEMENTS = ("m2.client_associe", "m2.profil_propriete_confirme", "m4.travaux_termines", "m6.variance_chantier")
AGENT_ALIMENTATION = "systeme:alimentation-graphe"
MATERIAUX_MAX = 40


@dataclasses.dataclass(frozen=True)
class Plan:
    noeuds: tuple[NoeudRef, ...]
    aretes: tuple[DemandeArete, ...]
    ignores: tuple[str, ...] = ()


def _date(charge: Mapping[str, Any], champ: str) -> str:
    valeur = charge.get(champ)
    if not isinstance(valeur, str) or len(valeur) < 10:
        raise ErreurMnemo(codes.ENTREE_INVALIDE, f"{champ} : instant ISO 8601 attendu")
    return valeur[:10]


def source_de(type_evenement: str, charge: Mapping[str, Any], ligne_id: str | None) -> str:
    """La provenance d'une arête issue du bus : la ligne du registre de M10 qui a mémorisé l'événement quand il y en a
    une
    (vérifiable, liée à la chaîne de hash) ; sinon l'identifiant du fait publié (`fait_id`)."""
    if ligne_id is not None:
        return f"registre:evenements:{ligne_id}"
    return f"bus:{type_evenement}:{str(charge.get('fait_id'))[:64]}"


def planifier(
    type_evenement: str, charge: Mapping[str, Any], *, source_ref: str, client_de_lead: Callable[[str], str | None]
) -> Plan:
    """Ce que cet événement apprend au graphe. Pur : ne lit ni n'écrit rien."""
    source = source_ref

    def arete(
        type_arete: str, de: NoeudRef, vers: NoeudRef, valide_de: str, libelle_vers: str | None = None
    ) -> DemandeArete:
        return DemandeArete(
            type=type_arete,
            de=de,
            vers=vers,
            valide_de=valide_de,
            origine="bus",
            source_type=f"bus:{type_evenement}",
            source_ref=source,
            confiance="haute",
            vers_libelle=libelle_vers,
        )

    if type_evenement == "m2.client_associe":
        return Plan((NoeudRef("client", str(charge.get("client_id"))),), ())
    if type_evenement == "m2.profil_propriete_confirme":
        client, propriete = (
            NoeudRef("client", str(charge.get("client_id"))),
            NoeudRef("propriete", str(charge.get("propriete_id"))),
        )
        return Plan((client, propriete), (arete("possede", client, propriete, _date(charge, "horodatage")),))
    if type_evenement == "m4.travaux_termines":
        intervention = NoeudRef("intervention", str(charge.get("intervention_id")))
        jour = _date(charge, "horodatage_completion")
        client_id = client_de_lead(str(charge.get("lead_id")))
        if client_id is None:
            return Plan((intervention,), (), ("client_inconnu",))
        client = NoeudRef("client", client_id)
        return Plan((intervention, client), (arete("demande", client, intervention, jour),))
    if type_evenement == "m6.variance_chantier":
        intervention = NoeudRef("intervention", str(charge.get("intervention_id")))
        jour = _date(charge, "horodatage_completion")
        lignes = charge.get("lignes") or []
        if not isinstance(lignes, list):
            raise ErreurMnemo(codes.ENTREE_INVALIDE, "lignes : liste attendue")
        noeuds, aretes, ignores = [intervention], [], []
        for ligne in lignes[:MATERIAUX_MAX]:
            try:
                utilise = Decimal(str(ligne["quantite_reelle"])) > 0
            except (InvalidOperation, KeyError, TypeError):
                ignores.append("quantite_illisible")
                continue
            if not utilise:
                continue  # prévu mais pas utilisé : aucune relation « utilise »
            materiau = NoeudRef("materiau", str(ligne.get("materiau")))
            noeuds.append(materiau)
            aretes.append(arete("utilise", intervention, materiau, jour, str(ligne.get("materiau"))[:80]))
        if len(lignes) > MATERIAUX_MAX:
            ignores.append("lignes_au_dela_du_plafond")
        return Plan(tuple(noeuds), tuple(aretes), tuple(ignores))
    raise ErreurMnemo(
        codes.ENTREE_INVALIDE,
        f"événement {vie_privee.court(type_evenement)} non alimenté (permis : {list(EVENEMENTS)})",
    )


def appliquer(moteur: MoteurGraphe, plan: Plan, *, type_evenement: str, source_ref: str, quand: str) -> dict[str, Any]:
    """Écrit le plan. Un élément refusé par le schéma est compté avec son code ; les autres sont écrits."""
    resume: dict[str, Any] = {
        "noeuds": 0,
        "aretes_proposees": 0,
        "aretes_confirmees_systeme": 0,
        "en_attente_confirmation": 0,
        "deja_connues": 0,
        "refus": [],
        "ignores": list(plan.ignores),
    }
    source = source_ref
    for ref in plan.noeuds:
        try:
            moteur.poser_noeud(
                ref.type,
                ref.cle,
                None if ref.type in ("client", "propriete") else ref.cle[:80],
                source_ref=source,
                par=AGENT_ALIMENTATION,
                quand=quand,
            )
            resume["noeuds"] += 1
        except ErreurMnemo as exc:
            resume["refus"].append({"element": f"noeud:{ref.type}", "code": exc.code})
    for demande in plan.aretes:
        try:
            proposition = moteur.proposer_arete(demande, par=AGENT_ALIMENTATION, quand=quand)
        except ErreurMnemo as exc:
            resume["refus"].append({"element": f"arete:{demande.type}", "code": exc.code})
            continue
        if not proposition.creee:
            resume["deja_connues"] += 1
            continue
        resume["aretes_proposees"] += 1
        if proposition.arete.sensible:
            resume["en_attente_confirmation"] += 1
        else:
            moteur.confirmer_arete(
                proposition.arete.arete_id,
                par=AGENT_ALIMENTATION,
                mode="systeme",
                role=None,
                raison=f"alimentation par le bus ({type_evenement}), arête non sensible",
                quand=quand,
            )
            resume["aretes_confirmees_systeme"] += 1
    return resume
