"""Outils de M10 pour la mémoire d'EXPÉRIENCE des agents, jalon J1 (`opsys.mnemo.experience`, docs/architecture/
MEMOIRE-EXPERIENCE-AGENTS-J1-J2.md) : proposer un élément candidat (garde d'admission) et lire les candidats.

- `m10_proposer_experience` (T1 / **N2**, agent) : passe la garde d'admission (schéma fermé, registre MCP, aucune
  valeur,
  aucun renseignement personnel, aucun contournement). L'élément reste `candidat` : aucun département ne le lit, rien
  n'est appliqué sans promotion humaine N3 (jalon J6, non construit). Un refus est consigné (code et empreinte,
  jamais le
  contenu) puis rendu à l'appelant ;
- `m10_lire_experiences` (T0 / N0) : les candidats (et les refus comptés) d'un département et d'un domaine, avec
  leur état
  rejoué (`candidat`, ou `perime` si l'empreinte d'un outil a changé).

Aucun droit d'appareil. Aucun modèle n'est appelé.
"""

from __future__ import annotations

import os
from typing import Any

from opsys import stockage
from opsys.mnemo import experience, registres, service
from opsys.mnemo.codes import ErreurMnemo
from opsys.outils import Autonomie, Niveau, Outil
from opsys.registre_mcp import garde as garde_mcp
from opsys.registre_mcp import registre as registre_mcp
from opsys.stockage.concurrence import verrou_consultatif

from . import validation

AGENT = "agent:m10-memoire"
LIMITE_LECTURE_MAX = 20


def _verdict(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": validation.construire_verdict(code, detail)}


def vue_registre() -> experience.VueRegistre:
    """Le registre MCP scellé que la garde consulte : celui de l'environnement (`OPSYS_MCP_REGISTRE`) ou le livré.
    Illisible
    ou altéré : refus (fail-closed), jamais une admission sans registre."""
    try:
        garde = garde_mcp.garde_depuis_env(os.environ)
        return garde.registre if garde is not None else registre_mcp.charger(garde_mcp.REGISTRE_LIVRE)
    except registre_mcp.RefusMCP as exc:
        raise ErreurMnemo(
            "REJ-EXPERIENCE-REGISTRE-INDISPONIBLE", f"registre MCP illisible ou altéré ({exc.code})"
        ) from None


def proposer_experience(element: dict[str, Any]) -> dict[str, Any]:
    service.refuser_appareil()
    cnx = stockage.connexion_courante()
    if cnx is None:
        return _verdict("REJ-EXPERIENCE-STOCKAGE", "une transaction de l'instance est requise")
    try:
        vue = vue_registre()
        verrou_consultatif(cnx, "m10-experiences")
        registre = registres.experiences()
        instant = service.instant_iso(service.maintenant())
        try:
            reponse = experience.proposer(registre, element, vue, par=AGENT, horodatage=instant)
        except experience.ErreurExperience as exc:
            experience.consigner_refus(registre, element, exc, par=AGENT, horodatage=instant)
            return _verdict(exc.code, exc.detail)
    except ErreurMnemo as exc:
        return _verdict(exc.code, exc.detail)
    return {
        "accepte": True,
        "resultat": {
            **reponse,
            "mention": "Candidat seulement : ni évalué, ni promu, ni lu par un département. Rien n'est appliqué sans "
            "promotion humaine (N3).",
        },
    }


def lire_experiences(
    departement: str | None = None,
    domaine: str | None = None,
    statut: str | None = None,
    limite: int = 10,
    decalage: int = 0,
) -> dict[str, Any]:
    service.refuser_appareil()
    if domaine is not None and domaine not in experience.DOMAINES:
        return _verdict(experience.DOMAINE_INCONNU, f"domaine parmi {list(experience.DOMAINES)}")
    if statut is not None and statut not in (experience.STATUT_CANDIDAT, experience.STATUT_PERIME):
        return _verdict(experience.F, "statut : candidat ou perime")
    if type(limite) is not int or not 1 <= limite <= LIMITE_LECTURE_MAX or type(decalage) is not int or decalage < 0:
        return _verdict(experience.F, f"limite de 1 à {LIMITE_LECTURE_MAX}, décalage ≥ 0")
    try:
        vue = vue_registre()
    except ErreurMnemo as exc:
        return _verdict(exc.code, exc.detail)
    maillons = service.Lecture(stockage.maillons("m10-memoire", "experiences")).lire()
    tous = experience.vue_elements(maillons, vue, departement=departement, domaine=domaine, statut=statut)
    page = tous[decalage : decalage + limite]
    reponse = {
        "total": len(tous),
        "elements": page,
        "refus_comptes": experience.etat(maillons)["refus"],
        "suivant": decalage + limite if decalage + limite < len(tous) else None,
        "registre_mcp_revision": vue.revision,
    }
    return {"accepte": True, "resultat": service.borner(reponse, ("elements",))}


_ELEMENT = {
    "type": "object",
    "properties": {
        "genre": {"type": "string", "enum": list(experience.GENRES)},
        "departement": {"type": "string", "description": "département propriétaire, ex. m02-revenue-crm"},
        "domaine": {"type": "string", "enum": list(experience.DOMAINES)},
        "pack": {
            "type": ["string", "null"],
            "description": "pack sectoriel si l'élément suppose le secteur, sinon null",
        },
        "declencheur": {
            "type": "object",
            "description": "{outil, code_refus?} : l'outil (et le code REJ-…) qui rappelle l'élément",
        },
        "contenu": {
            "type": "object",
            "description": "selon le genre : convention_outil {outil, cle_argument, regle, correction} ; "
            "exemple_sous_tache "
            "{intention, appels:[{outil, arguments}], reponse_cles} avec marques <MONTANT>, <ID_AFFAIRE>, <DATE>… ; "
            "strategie_flux {intention, etapes:[{outil, condition}]}",
        },
        "origine": {"type": "string", "enum": list(experience.ORIGINES_DECLARABLES)},
    },
    "required": ["genre", "departement", "domaine", "pack", "declencheur", "contenu", "origine"],
    "additionalProperties": False,
}


def outils_experience() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m10_proposer_experience",
            description=(
                "Propose un élément d'EXPÉRIENCE d'agent (stratégie de flux, exemple d'appel, convention d'outil) à "
                "la garde "
                "d'admission : schéma fermé, noms d'outils et d'arguments vérifiés contre le registre MCP scellé, "
                "exemple à "
                "marques de substitution (jamais une valeur), aucun chiffre, aucun renseignement personnel, aucun "
                "conseil de "
                "contourner une approbation. Accepté, il reste CANDIDAT : rien n'est appliqué sans promotion humaine."
            ),
            parametres={
                "type": "object",
                "properties": {"element": _ELEMENT},
                "required": ["element"],
                "additionalProperties": False,
            },
            fonction=proposer_experience,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m10_lire_experiences",
            description=(
                "Lit les éléments d'expérience candidats (état rejoué : candidat, ou périmé si l'empreinte d'un "
                "outil a "
                "changé) d'un département et d'un domaine, et le nombre de refus d'admission. Lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "departement": {"type": "string"},
                    "domaine": {"type": "string", "enum": list(experience.DOMAINES)},
                    "statut": {"type": "string", "enum": [experience.STATUT_CANDIDAT, experience.STATUT_PERIME]},
                    "limite": {"type": "integer", "minimum": 1, "maximum": LIMITE_LECTURE_MAX},
                    "decalage": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            fonction=lire_experiences,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
    )
