"""Registre append-only des briefs créatifs : créer, réviser (idempotent), relire.

Même patron que le sas social : une clé d'idempotence = un brief ; même clé et même contenu = le même brief (rien
d'écrit) ; même clé et autre contenu = refus (`REJ-STUDIO-BRIEF-CLE-CONFLIT`) ; une révision passe par l'identifiant. Un
brief déjà COMPOSÉ (un visuel en dérive) se révise quand même : le visuel dérivé garde l'empreinte de l'ancien contenu
et
la nouvelle révision donne un autre visuel (l'ancien n'est pas modifié).

Module pur : le journal est n'importe quelle séquence `append`/`len`/itération.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .. import journal_chaine
from . import brief as b

REGISTRE = ("m07-marketing", "briefs_studio")
M_CREE = "brief_cree"
M_REVISE = "brief_revise"
REJ_JOURNAL_ALTERE = "REJ-STUDIO-BRIEFS-JOURNAL-ALTERE"
REJ_CLE = "REJ-STUDIO-BRIEF-CLE-INVALIDE"
REJ_CLE_CONFLIT = "REJ-STUDIO-BRIEF-CLE-CONFLIT"
REJ_INCONNU = "REJ-STUDIO-BRIEF-INCONNU"
_CLE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@dataclasses.dataclass(frozen=True)
class EtatBrief:
    brief_id: str
    brief: b.Brief
    empreinte: str
    revision: int


def identifiant(cle: str) -> str:
    return "brief-" + hashlib.sha256(("opsys-studio-brief-id\n" + cle).encode()).hexdigest()[:20]


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def charger(journal: Any) -> tuple[dict[str, EtatBrief], dict[str, Any] | None]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, _refus(REJ_JOURNAL_ALTERE, "$", "; ".join(problemes[:3]))
    etats: dict[str, EtatBrief] = {}
    for m in journal_chaine.maillons(journal):
        brief, refus = b.depuis_dict(m["brief"])
        if brief is None or brief.empreinte() != m["empreinte"]:
            return {}, _refus(REJ_JOURNAL_ALTERE, "$", f"maillon {m['rang']} : brief illisible ou empreinte différente")
        revision = etats[m["brief_id"]].revision + 1 if m["type"] == M_REVISE and m["brief_id"] in etats else 1
        etats[m["brief_id"]] = EtatBrief(m["brief_id"], brief, m["empreinte"], revision)
    return etats, None


def composer(
    journal: Any, donnees: Any, cle_idempotence: str, par: str, horodatage: str, brief_id: str | None = None
) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    brief, problemes = b.depuis_dict(donnees)
    if brief is None:
        return {"accepte": False, "refus": problemes}
    if not isinstance(cle_idempotence, str) or not _CLE.fullmatch(cle_idempotence):
        return _refus(REJ_CLE, "$.cle_idempotence", "16 à 64 caractères [A-Za-z0-9_-]")
    empreinte = brief.empreinte()
    if brief_id is not None:
        courant = etats.get(brief_id)
        if courant is None:
            return _refus(REJ_INCONNU, "$.brief_id", f"brief inconnu : {brief_id!r}")
        if courant.empreinte == empreinte:
            return {
                "accepte": True,
                "brief_id": brief_id,
                "empreinte": empreinte,
                "revision": courant.revision,
                "deja_cree": True,
            }
        journal_chaine.ajouter(
            journal,
            M_REVISE,
            {"brief_id": brief_id, "brief": brief.vers_dict(), "empreinte": empreinte, "par": par},
            horodatage,
        )
        return {
            "accepte": True,
            "brief_id": brief_id,
            "empreinte": empreinte,
            "revision": courant.revision + 1,
            "deja_cree": False,
        }
    identifiant_brief = identifiant(cle_idempotence)
    existant = etats.get(identifiant_brief)
    if existant is not None:
        if existant.empreinte != empreinte:
            return _refus(
                REJ_CLE_CONFLIT,
                "$.cle_idempotence",
                f"cette clé désigne déjà un brief au contenu différent ({identifiant_brief}) : le réviser par "
                "son identifiant",
            )
        return {
            "accepte": True,
            "brief_id": identifiant_brief,
            "empreinte": empreinte,
            "revision": existant.revision,
            "deja_cree": True,
        }
    journal_chaine.ajouter(
        journal,
        M_CREE,
        {
            "brief_id": identifiant_brief,
            "brief": brief.vers_dict(),
            "empreinte": empreinte,
            "cle_idempotence": cle_idempotence,
            "par": par,
        },
        horodatage,
    )
    return {"accepte": True, "brief_id": identifiant_brief, "empreinte": empreinte, "revision": 1, "deja_cree": False}


def obtenir(journal: Any, brief_id: str) -> EtatBrief | dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    courant = etats.get(brief_id)
    if courant is None:
        return _refus(REJ_INCONNU, "$.brief_id", f"brief inconnu : {brief_id!r}")
    return courant


def par_empreinte(journal: Any, empreinte: str) -> b.Brief | None:
    """Le contenu d'une révision précise (un visuel dérive d'UNE empreinte de brief, pas du brief courant)."""
    if journal_chaine.verifier(journal):
        return None
    for m in journal_chaine.maillons(journal):
        if m["empreinte"] == empreinte:
            brief, _ = b.depuis_dict(m["brief"])
            return brief
    return None


def lire(journal: Any, brief_id: str | None = None, limite: int = 20) -> dict[str, Any]:
    etats, refus = charger(journal)
    if refus is not None:
        return refus
    if brief_id is not None:
        courant = etats.get(brief_id)
        if courant is None:
            return _refus(REJ_INCONNU, "$.brief_id", f"brief inconnu : {brief_id!r}")
        return {
            "accepte": True,
            "brief_id": brief_id,
            "revision": courant.revision,
            "empreinte": courant.empreinte,
            "brief": courant.brief.vers_dict(),
        }
    recents = list(etats.values())[-max(1, min(limite, 50)) :]
    return {
        "accepte": True,
        "total": len(etats),
        "briefs": [
            {
                "brief_id": e.brief_id,
                "revision": e.revision,
                "empreinte": e.empreinte,
                "gabarit": e.brief.gabarit,
                "format": e.brief.format,
                "fictif": e.brief.fictif,
                "genere": e.brief.genere,
            }
            for e in reversed(recents)
        ],
    }


def sans_marque(donnees: Mapping[str, Any]) -> dict[str, Any]:
    """Le brief que l'agent fournit : tout sauf la marque, posée par l'outil depuis le profil de marque existant."""
    return {k: v for k, v in donnees.items() if k != "marque"}
