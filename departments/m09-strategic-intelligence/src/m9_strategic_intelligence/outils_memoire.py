"""Outils de mémoire M10 pour M9 : préparer l'écriture exacte d'une décision, vérifier la mémoire. Lecture seule.

``m9_preparer_memoire_decision`` ne consigne rien : il rend les arguments exacts à proposer à la file d'approbation
native
(``m9_proposer_action`` vers ``m10_journaliser_decision``). ``m9_verifier_memoire_decision`` compare ce que M9 croit
avoir
consigné à ce que M10 dit, sur la lecture capturée ``m10.statut_decision``.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import capture_strategique as cs
from . import memoire_m10, orchestrateur, sessions_conseil
from .outils_tissu import DEPARTEMENT, borner, exiger_admin_strict

REGISTRE_SESSIONS = "sessions_conseil"
REGISTRE_CAPTURES = "captures_strategiques"
REGISTRE_ACTIONS = "actions"
_INSTANT = {"type": "string", "description": "Instant RFC 3339 à fuseau explicite (M9 n'a pas d'horloge)."}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}


def construire_outils(
    *, budget_sortie: int, sessions_cible: Any = None, captures_cible: Any = None, actions_cible: Any = None
) -> tuple[Outil, ...]:
    def sessions() -> list[dict]:
        source = sessions_cible if sessions_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_SESSIONS)
        liste = list(source)
        ok, raison = sessions_conseil.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-SESSION-CHAINE-INVALIDE : registre des sessions invalide ({raison})")
        return liste

    def captures() -> list[dict]:
        source = captures_cible if captures_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_CAPTURES)
        liste = list(source)
        ok, raison = cs.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-CAPTURE-CHAINE-INVALIDE : registre des captures invalide ({raison})")
        return liste

    def actions() -> list[dict]:
        source = actions_cible if actions_cible is not None else stockage.maillons(DEPARTEMENT, REGISTRE_ACTIONS)
        liste = list(source)
        ok, raison = orchestrateur.valider_chaine(liste)
        if not ok:
            raise ValueError(f"REJ-ACTION-CHAINE-INVALIDE : registre des actions invalide ({raison})")
        return liste

    def preparer(
        session_id: str,
        statut: str,
        horodatage: str,
        options_ecartees: str = "",
        motif: str | None = None,
        validation_humaine_declaree: bool = False,
        correction: bool = False,
    ) -> dict[str, Any]:
        exiger_admin_strict()
        projection = sessions_conseil.etat(sessions(), session_id)
        arguments = memoire_m10.preparer(
            projection,
            statut,
            horodatage,
            options_ecartees=options_ecartees,
            motif=motif,
            validation_humaine_declaree=validation_humaine_declaree,
            correction=correction,
        )
        return {
            "accepte": True,
            "decision_id": arguments["decision"]["decision_id"],
            "rapport_id": projection["cloture"]["rapport_id"],
            "a_proposer": {
                "departement": "m10-memoire",
                "outil": memoire_m10.OUTIL_M10,
                "arguments": arguments,
                "sources": [f"conseil:{projection['cloture']['rapport_id']}"],
            },
            "ecrit": False,
            "prochaine_etape": "m9_proposer_action puis approbation humaine dans la file native",
        }

    def verifier(
        decision_id: str, connaissance: str, attendu: str | None = None, action_id: str | None = None
    ) -> dict[str, Any]:
        exiger_admin_strict()
        etat_action = None
        if action_id is not None:
            courante = orchestrateur.etat(actions()).get(action_id)
            if courante is None:
                raise ValueError("REJ-ACTION-INCONNUE : action jamais proposée")
            etat_action = courante["etat"]
        resultat = memoire_m10.verifier(
            captures(), decision_id, connaissance=connaissance, attendu=attendu, action_etat=etat_action
        )
        return borner({"accepte": True, **resultat}, budget_sortie)

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
            "m9_preparer_memoire_decision",
            "Prépare, sans rien écrire, les arguments exacts de m10_journaliser_decision pour une session de conseil "
            "close : identifiant stable par session, version = rapport, dossier et gouvernance cités. Une correction "
            "(remplacee, annulee) exige un motif ; validee exige la validation humaine déclarée.",
            {
                "session_id": _ID,
                "statut": {"type": "string", "enum": list(memoire_m10.STATUTS_PREPARABLES)},
                "horodatage": _INSTANT,
                "options_ecartees": {"type": "string", "maxLength": 400},
                "motif": {"type": "string", "maxLength": 300},
                "validation_humaine_declaree": {"type": "boolean"},
                "correction": {"type": "boolean"},
            },
            ["session_id", "statut", "horodatage"],
            preparer,
        ),
        outil(
            "m9_verifier_memoire_decision",
            "Compare ce que M9 croit avoir consigné dans M10 à ce que M10 dit (lecture capturée m10.statut_decision) : "
            "cohérent, mémoire fantôme, divergent, non enregistrée, non attribuable ou inconnu.",
            {
                "decision_id": _ID,
                "connaissance": _INSTANT,
                "attendu": {"type": "string", "maxLength": 32},
                "action_id": _ID,
            },
            ["decision_id", "connaissance"],
            verifier,
        ),
    )
