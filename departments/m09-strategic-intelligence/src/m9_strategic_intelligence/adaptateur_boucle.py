"""Adaptateur de la boucle « décision → résultat mesuré → leçon » d'Athéna (``boucle_decisions``, module pur).

Les règles vivent dans ``boucle_decisions`` ; ce fichier lit et écrit les registres, vérifie l'identité et publie.

Niveaux (ADR-0009 §4) :

* ``m9_consigner_decision_direction`` et ``m9_valider_lecon_decision`` : T1 / **N3**. Ce sont des gestes de la direction
:
  ils n'écrivent QUE pendant l'exécution de LEUR PROPRE demande approuvée par un propriétaire encore actif en base
  (``approbateur_en_cours``), comme ``m9_ouvrir_suivi_decision``. Un appel direct, une ancienne approbation ou le texte
  d'un
  modèle ne donnent aucun mandat ;
* ``m9_mesurer_resultat_decision`` et ``m9_publier_faits_strategiques`` : T1 / N2 (tâche interne, append-only, événement
  interne réversible) ; l'admin authentifié est exigé ;
* ``m9_lire_boucle_decisions`` : T0 / N0.

Aucun rôle d'appareil n'est déclaré (``roles_appareil`` vide) : ces outils n'élargissent aucun droit de téléphone. Rien
n'est
APPLIQUÉ : une leçon validée est préparée pour M10 (arguments exacts) ; l'ingestion appartient à M10.
"""

from __future__ import annotations

from typing import Any

from opsys import approbations, contexte, evenements, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import boucle_decisions as boucle
from . import capture_strategique as cs
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_BOUCLE = "decisions_direction"
REGISTRE_CAPTURES = "captures_strategiques"
REGISTRE_SUIVIS = "suivi_decisions"
TYPE_EVENEMENT = "m9.fait_strategique"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}
_ATTENDU = {
    "type": "object",
    "properties": {
        "metric_id": {"type": "string", "maxLength": 80},
        "sens": {"type": "string", "enum": list(boucle.SENS)},
        "hypothese": {"type": "string", "maxLength": 300},
    },
    "required": ["metric_id", "sens", "hypothese"],
    "additionalProperties": False,
}


def _refus_verdict(exc: ValueError) -> dict[str, Any]:
    code, _, detail = str(exc).partition(" : ")
    return {"accepte": False, "verdict": {"code": code, "detail": detail}}


def construire_outils(
    *, budget_sortie: int, captures_cible: Any = None, boucle_cible: Any = None, suivis_cible: Any = None
) -> tuple[Outil, ...]:
    def registre_boucle() -> Any:
        return boucle_cible if boucle_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_BOUCLE)

    def chaine() -> list[dict]:
        liste = list(registre_boucle())
        ok, raison = boucle.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-BOUCLE-CHAINE-INVALIDE : registre de la boucle invalide ({raison})")
        return liste

    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        liste = list(source)
        ok, raison = cs.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-CAPTURE-CHAINE-INVALIDE : registre des captures invalide ({raison})")
        return liste

    def suivis_connus() -> list[str]:
        source = suivis_cible if suivis_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_SUIVIS)
        return [s["suivi_id"] for s in source if isinstance(s, dict) and "suivi_id" in s]

    def approbateur_et_demande(nom_outil: str) -> tuple[Any, str, dict] | dict:
        """Le mandat : CETTE demande, approuvée par un propriétaire SQL encore actif. Sinon un verdict de refus."""
        cnx = stockage.connexion_courante()
        approbateur = approbations.approbateur_en_cours(cnx, nom_outil, DEPARTEMENT, roles=frozenset({"nathan_owner"}))
        if approbateur is None:
            return {
                "accepte": False,
                "verdict": {
                    "code": "REJ-BOUCLE-APPROBATION",
                    "detail": "Demande dédiée approuvée par le propriétaire encore actif requise",
                },
            }
        demande_id = contexte.demande_approuvee_en_cours()
        return approbateur, demande_id, approbations.lire(cnx, demande_id)

    def ajouter(maillons: list[dict]) -> None:
        cible = registre_boucle()
        base = len(cible)
        for rang, maillon in enumerate(maillons):
            cible.append(maillon, rang_attendu=base + rang)

    # -------------------------------------------------------------------------------- décision (geste de la direction)
    def consigner_decision(enonce: str, attendus: list, suivi_id: str | None = None) -> dict[str, Any]:
        mandat = approbateur_et_demande("m9_consigner_decision_direction")
        if isinstance(mandat, dict):
            return mandat
        approbateur, demande_id, demande = mandat
        try:
            maillon = boucle.declarer(
                chaine(), decision_id=demande_id, enonce=enonce, attendus=attendus, captures=captures(),
                decide_par=approbateur.personne, decide_role=approbateur.role, decide_le=demande["decide_le"],
                suivi_id=suivi_id, suivis_connus=suivis_connus(),
            )  # fmt: skip
            resultat = borner({"accepte": True, "decision_id": demande_id, "decision": maillon}, budget_sortie)
        except ValueError as exc:
            return _refus_verdict(exc)
        ajouter([maillon])
        return resultat

    def valider_lecon(lecon_id: str, statut: str, motif: str | None = None) -> dict[str, Any]:
        mandat = approbateur_et_demande("m9_valider_lecon_decision")
        if isinstance(mandat, dict):
            return mandat
        approbateur, _, demande = mandat
        try:
            maillon = boucle.valider_lecon(
                chaine(), lecon_id, statut, decide_par=approbateur.personne, decide_role=approbateur.role,
                decide_le=demande["decide_le"], motif=motif,
            )  # fmt: skip
            resultat = borner({"accepte": True, "validation": maillon}, budget_sortie)
        except ValueError as exc:
            return _refus_verdict(exc)
        ajouter([maillon])
        return resultat

    # -------------------------------------------------------------------------------- mesure (tâche interne)
    def mesurer(decision_id: str, maintenant: str) -> dict[str, Any]:
        exiger_admin_strict()
        courante = chaine()
        ajouts = boucle.mesurer(courante, decision_id, captures=captures(), maintenant=maintenant)
        ajouter(ajouts)
        etat = boucle.etat([*courante, *ajouts], decision_id)
        return borner(
            {
                "accepte": True,
                "ajoute": bool(ajouts),
                "rejeu": not ajouts,
                "entrees_ajoutees": [a["type"] for a in ajouts],
                "etat": etat,
                "regle": "Une leçon proposée n'est ni une cause ni une décision ; la direction la valide ou la "
                         "rejette.",
            },
            budget_sortie,
        )

    # -------------------------------------------------------------------------------- lecture
    def lire(decision_id: str | None = None, depart: int = 0) -> dict[str, Any]:
        exiger_admin_strict()
        courante = chaine()
        if decision_id is not None:
            return borner(
                {"accepte": True, "type": "DECISION_DE_LA_DIRECTION", **boucle.etat(courante, decision_id)},
                budget_sortie,
            )
        ids = list(reversed(boucle.decisions(courante)))
        if type(depart) is not int or not 0 <= depart <= len(ids):
            raise ValueError("REJ-TISSU-DEPART : départ entre 0 et le total requis ; reprendre à 0")
        page: list[dict] = []
        for ident in ids[depart:]:
            e = boucle.etat(courante, ident)
            ligne = {"decision_id": ident, "etat": e["etat"], "decide_le": e["decide_le"], "enonce": e["enonce"][:160],
                     "lecon": None if e["lecon"] is None else {"lecon_id": e["lecon"]["lecon_id"],
                         "statut": e["lecon"]["statut"]}}  # fmt: skip
            if len(str([*page, ligne])) > budget_sortie - 800:
                break
            page.append(ligne)
        suivant = depart + len(page)
        return {
            "accepte": True, "type": "BOUCLE_DECISIONS", "decisions": page, "total": len(ids), "depart": depart,
            "prochain_depart": suivant if suivant < len(ids) else None, "ordre": "la plus récente d'abord",
        }  # fmt: skip

    # -------------------------------------------------------------------------------- publication vers M10
    def publier(decision_id: str) -> dict[str, Any]:
        exiger_admin_strict()
        courante = chaine()
        boucle.etat(courante, decision_id)  # refuse une décision inconnue
        concernees = [e for e in courante if e["decision_id"] == decision_id]
        nouvelles = 0
        for entree in concernees:
            charge = boucle.evenement_fait(entree, courante)
            premiere = evenements.charge_publiee(TYPE_EVENEMENT, charge["evenement_id"])
            evenements.publier(
                TYPE_EVENEMENT, DEPARTEMENT, premiere if premiere is not None else charge,
                evenement_id=charge["evenement_id"],
            )  # fmt: skip
            nouvelles += premiere is None
        a_proposer = []
        for entree in concernees:
            if entree["type"] == "VALIDATION_LECON" and entree["statut"] == "validee":
                a_proposer.append(
                    {
                        "departement": "m10-memoire",
                        "outil": "m10_ingerer_source_connaissance",
                        "arguments": boucle.source_connaissance(courante, entree["lecon_id"]),
                        "sources": [f"boucle:{entree['hash_maillon']}"],
                    }
                )
        return borner(
            {
                "accepte": True,
                "decision_id": decision_id,
                "evenements": len(concernees),
                "nouveaux": nouvelles,
                "memoire_a_proposer": a_proposer,
                "ecrit_dans_la_memoire_de_connaissances": False,
                "prochaine_etape": "l'agent de M10 ingère la source (brouillon, N2) ; sa publication suit le cycle "
                                   "de revue de M10"
                if a_proposer
                else None,
            },
            budget_sortie,
        )

    def outil(nom, description, proprietes, requis, fonction, *, autonomie=Autonomie.T0, niveau=Niveau.N0):
        return Outil(
            nom=nom,
            description=description,
            parametres={"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False},
            fonction=fonction,
            autonomie=autonomie,
            niveau=niveau,
            roles_appareil=frozenset(),
        )

    return (
        outil(
            "m9_consigner_decision_direction",
            "Consigne UNE décision de la direction et ce qu'elle en attend, en SENS seulement (hausse, baisse, "
            "stable) sur "
            "des mesures de M8. N3 : s'exécute seulement sous SA demande approuvée par le propriétaire ; l'identifiant "
            "de la décision est celui de la demande. La base de comparaison est la dernière lecture établie connue à "
            "l'instant de l'approbation ; sans elle, la base est dite inconnue. M9 ne décide rien.",
            {
                "enonce": {"type": "string", "minLength": 1, "maxLength": boucle.MAX_ENONCE},
                "attendus": {"type": "array", "items": _ATTENDU, "minItems": 1, "maxItems": boucle.MAX_ATTENDUS},
                "suivi_id": _ID,
            },
            ["enonce", "attendus"],
            consigner_decision,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        outil(
            "m9_mesurer_resultat_decision",
            "Compare, par le code, la base de la décision à la dernière lecture établie : sens observé de chaque "
            "mesure et "
            "concordance avec l'attendu (CONCORDE, NE_CONCORDE_PAS, NON_MESURABLE avec sa raison). Propose une leçon "
            "(PROPOSEE_NON_VALIDEE) seulement si une mesure est mesurable ; elle n'établit aucune cause. Rejeu sans "
            "effet.",
            {"decision_id": _ID, "maintenant": _INSTANT},
            ["decision_id", "maintenant"],
            mesurer,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        outil(
            "m9_valider_lecon_decision",
            "La direction valide ou rejette (motif obligatoire) une leçon proposée. N3 : sous SA demande approuvée "
            "par le "
            "propriétaire. Rien n'est appliqué ni écrit dans la mémoire de connaissances.",
            {
                "lecon_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "statut": {"type": "string", "enum": ["validee", "rejetee"]},
                "motif": {"type": "string", "maxLength": 300},
            },
            ["lecon_id", "statut"],
            valider_lecon,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        outil(
            "m9_lire_boucle_decisions",
            "Lit la boucle décision → résultat mesuré → leçon : la liste des décisions de la direction (état de "
            "chacune) ou "
            "le détail d'une décision. Lecture seule.",
            {"decision_id": _ID, "depart": {"type": "integer", "minimum": 0}},
            [],
            lire,
        ),
        outil(
            "m9_publier_faits_strategiques",
            "Publie vers la mémoire de M10 les entrées de la boucle d'une décision (un événement "
            "m9.fait_strategique par "
            "entrée, idempotent) et PRÉPARE, pour chaque leçon validée par la direction, les arguments exacts d'une "
            "source de connaissance interne (rien n'est écrit dans la base de connaissances).",
            {"decision_id": _ID},
            ["decision_id"],
            publier,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
    )
