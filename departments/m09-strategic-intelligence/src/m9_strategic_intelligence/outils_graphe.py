"""Outils du graphe d'impacts M9.2 : résumé du graphe connu et propagation d'un changement, en lecture seule.

Le graphe est reconstruit à chaque appel depuis le registre chaîné des captures, à l'instant de connaissance demandé :
aucune
copie persistante, donc aucune dérive. Sans règle prouvée ou sans objet connu, la réponse dit « inconnu » et n'affirme
jamais
« aucun impact ». Aucune quantité n'est propagée.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import graphe_impacts, relations_catalogue
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}
RELATIONS = frozenset(regle.relation for regle in relations_catalogue.REGLES)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def graphe(connaissance: str) -> dict:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        cs.instant(connaissance)
        return graphe_impacts.construire(chaine, relations_catalogue.REGLES, connaissance=connaissance)

    def apercu_graphe(connaissance: str) -> dict[str, Any]:
        exiger_admin_strict()
        construit = graphe(connaissance)
        kinds: dict[str, int] = {}
        for noeud in construit["noeuds"]:
            kinds[noeud["kind"]] = kinds.get(noeud["kind"], 0) + 1
        return borner(
            {
                "accepte": True,
                "type": construit["type"],
                "graphe_id": construit["graphe_id"],
                "version_relations": construit["version_relations"],
                "catalogue_relations": relations_catalogue.CATALOGUE_RELATIONS_VERSION,
                "connaissance": connaissance,
                "noeuds_par_type": kinds,
                "total_aretes": len(construit["aretes"]),
                "regles_actives": construit["regles_actives"],
                "regles_inconnues": construit["regles_inconnues"],
                "manques_connus": list(relations_catalogue.MANQUES),
                "limites": construit["limites"],
            },
            budget_sortie,
        )

    def propager_impacts(
        connaissance: str, kind: str, identifiant: str, relations: list[str] | None = None, profondeur_max: int = 4
    ) -> dict[str, Any]:
        exiger_admin_strict()
        if relations is not None:
            inconnues = sorted(set(relations) - RELATIONS)
            if inconnues:
                raise _refus("REJ-GRAPHE-RELATION", f"relations hors catalogue {inconnues}")
        construit = graphe(connaissance)
        propagation = graphe_impacts.propager(
            construit, kind, identifiant, relations=relations, profondeur_max=profondeur_max
        )
        par_id = {arete["id"]: arete for arete in construit["aretes"]}
        preuves = {
            arete_id: {
                "relation": par_id[arete_id]["relation"],
                "regle": par_id[arete_id]["regle"],
                "de": par_id[arete_id]["de"],
                "vers": par_id[arete_id]["vers"],
                "preuve": par_id[arete_id]["preuve"],
            }
            for impact in propagation["impacts"]
            for arete_id in impact["chemin"]
        }
        return borner(
            {"accepte": True, **propagation, "connaissance": connaissance, "aretes_citees": preuves}, budget_sortie
        )

    def outil(nom, description, proprietes, requis, fonction):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        )

    return (
        outil(
            "m9_apercu_graphe_impacts",
            "Résume le graphe d'impacts connu à un instant : objets par type, arêtes, règles actives et règles "
            "INCONNUES (lecture absente, refusée, partielle ou contradictoire), manques connus du catalogue.",
            {"connaissance": _INSTANT},
            ["connaissance"],
            apercu_graphe,
        ),
        outil(
            "m9_propager_impacts",
            "Propage un changement depuis un objet (devis, chantier, intervention, lead…) selon les relations "
            "prouvées par des lignes capturées : rend les objets liés, leur distance, le chemin cité (capture, "
            "empreinte, ligne) et les règles inconnues pertinentes. Aucune quantité ; un objet absent est refusé, "
            "jamais « sans impact ».",
            {
                "connaissance": _INSTANT,
                "kind": _ID,
                "identifiant": _ID,
                "relations": {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 32},
                "profondeur_max": {"type": "integer", "minimum": 1, "maximum": graphe_impacts.MAX_PROFONDEUR},
            },
            ["connaissance", "kind", "identifiant"],
            propager_impacts,
        ),
    )
