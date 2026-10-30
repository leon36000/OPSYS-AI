"""Outil de la couche sémantique M9.3 : rapprocher les mesures des producteurs des définitions du registre M8.

Lecture seule. Les définitions viennent d'une capture complète de ``m8.definitions_metriques`` ; les observations, des
lignes ``resultat.mesures[*]`` des captures complètes de ``m8.mesures_chantier`` (une mesure non calculable n'est jamais
une observation : elle est rendue avec ce qui manque). M9 ne recalcule rien et n'additionne jamais deux groupes. Sans
capture complète du registre, le rapprochement est REFUSÉ : aucune définition n'est supposée. Aucun historique
versionné de définitions n'est encore consommé (``historique_definitions = NON_CONSOMME``) : une mesure portant une
empreinte reste non comparable ; aucune projection de liaisons globales n'est appliquée (contrat successeur dans
``preuves_definition``, à raccorder quand M8 publiera son historique).
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import semantique_metriques
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_CAPTURES = "captures_strategiques"
LECTURE_DEFINITIONS = "m8.definitions_metriques"
LECTURE_MESURES = "m8.mesures_chantier"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _dernieres(connues: list[dict], lecture_id: str) -> list[dict]:
    """Dernière capture connue de chaque jeu d'arguments de la lecture, rang croissant."""
    derniere: dict[str, dict] = {}
    for capture in connues:
        if capture["lecture_id"] == lecture_id:
            derniere[capture["arguments_sha256"]] = capture
    return sorted(derniere.values(), key=lambda capture: capture["index"])


def construire_outils(*, budget_sortie: int, captures_cible: Any = None) -> tuple[Outil, ...]:
    def rapprocher(connaissance: str, depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        chaine = list(source)
        ok, raison = cs.valider_chaine(chaine)
        if not ok:
            raise _refus("REJ-CAPTURE-CHAINE-INVALIDE", f"registre des captures invalide ({raison})")
        connues = cs.connues_a(chaine, connaissance)
        en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
        registres = [
            c
            for c in _dernieres(connues, LECTURE_DEFINITIONS)
            if c["verdict"] == "ACCEPTEE"
            and c["complete"]
            and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
        ]
        if not registres:
            raise _refus(
                "REJ-SEMANTIQUE-REGISTRE-ABSENT",
                "aucune capture complète et non contradictoire du registre M8 ; aucune définition supposée",
            )
        definitions = [
            ligne
            for capture in registres
            for page in capture["pages"]
            for ligne in cs.extraire(page, "resultat.definitions[*]")
        ]
        catalogue = semantique_metriques.cataloguer(definitions)
        observations: list[dict] = []
        non_calculables: list[dict] = []
        lectures_ecartees: list[dict] = []
        for capture in _dernieres(connues, LECTURE_MESURES):
            if (
                capture["verdict"] != "ACCEPTEE"
                or not capture["complete"]
                or (capture["lecture_id"], capture["arguments_sha256"]) in en_conflit
            ):
                lectures_ecartees.append(
                    {"capture": capture["index"], "verdict": capture["verdict"], "complete": capture["complete"]}
                )
                continue
            for numero_page, page in enumerate(capture["pages"]):
                for mesure in cs.extraire(page, "resultat.mesures[*]"):
                    source_mesure = f"{LECTURE_MESURES}#{capture['index']}:p{numero_page}.resultat.mesures"
                    if (
                        isinstance(mesure, dict)
                        and mesure.get("valeur") is not None
                        and type(mesure.get("valeur")) is str
                    ):
                        observations.append(
                            {
                                "metric_id": mesure.get("metric_id"),
                                "valeur": mesure["valeur"],
                                "unite": mesure.get("unite"),
                                "version_definition": mesure.get("version_definition"),
                                "preuve_definition": mesure.get("preuve_definition"),
                                "source": source_mesure,
                            }
                        )
                    elif isinstance(mesure, dict):
                        non_calculables.append(
                            {
                                "metric_id": mesure.get("metric_id"),
                                "manque": mesure.get("manque"),
                                "source": source_mesure,
                            }
                        )
        # Aucun historique versionné de définitions n'est consommé (contrat successeur non raccordé) : une mesure à
        # empreinte reste non comparable, jamais rapprochée par une liaison globale.
        resultat = semantique_metriques.rapprocher(observations, catalogue, None)
        statuts: dict[str, int] = {}
        for observation in resultat["observations"]:
            statuts[observation["statut"]] = statuts.get(observation["statut"], 0) + 1
        entete = {
            "accepte": True,
            "connaissance": connaissance,
            "definitions_connues": len(catalogue),
            "historique_definitions": "NON_CONSOMME",
            "registre_capture": [c["index"] for c in registres],
            "type": resultat["type"],
            "statuts": statuts,
            "total_observations": len(resultat["observations"]),
            "comparables_ensemble": len(resultat["comparables_ensemble"]),
            "agregable": False,
            "non_calculables": non_calculables[:20],
            "non_calculables_total": len(non_calculables),
            "captures_mesures_ecartees": lectures_ecartees,
            "limites": resultat["limites"],
        }
        classees = resultat["observations"]
        if type(depart) is not int or not 0 <= depart <= len(classees):
            raise _refus("REJ-SEMANTIQUE-DEPART", "départ entre 0 et le nombre d'observations requis ; reprendre à 0")
        marge = budget_sortie - len(cs.canonique(entete)) - 400
        page: list[dict] = []
        for observation in classees[depart:]:
            if len(cs.canonique(page + [observation])) > marge:
                break
            page.append(observation)
        if classees[depart:] and not page:
            raise _refus("REJ-TISSU-BORNE", "une observation dépasse la borne de sortie")
        suivant = depart + len(page)
        return borner(
            {
                **entete,
                "observations": page,
                "depart": depart,
                "prochain_depart": suivant if suivant < len(classees) else None,
            },
            budget_sortie,
        )

    return (
        Outil(
            nom="m9_rapprocher_metriques",
            description=(
                "Classe les mesures capturées de M8 face aux définitions du registre M8 (compatible, sans définition, "
                "unité divergente, version périmée, non déclarée ou non comparable) sans rien recalculer ni agréger ; "
                "refuse sans capture complète du registre."
            ),
            parametres={
                "type": "object",
                "properties": {"connaissance": _INSTANT, "depart": {"type": "integer", "minimum": 0}},
                "required": ["connaissance"],
                "additionalProperties": False,
            },
            fonction=rapprocher,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
    )
