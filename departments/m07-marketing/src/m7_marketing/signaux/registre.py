"""Le registre durable des faits de signaux (`m07-marketing/signaux_marketing`, schéma `opsys.m7.signal_marketing/v1`).

Append-only à chaîne de hachage. Un fait a une IDENTITÉ (`fait_id`) et des révisions : si le fournisseur révise une
valeur
(Search Console et les plateformes publicitaires le font), la nouvelle valeur est une RÉVISION suivante, jamais une
modification ; relire la même valeur ne change rien (idempotence). Les faits d'une même page sont écrits ensemble ou
pas du
tout : un conflit (le même fait, deux valeurs, dans une même page) refuse la page entière.

Bornes : le registre refuse au-delà de `MAX_FAITS` maillons (`REJ-SIGNAUX-REGISTRE-PLEIN`) au lieu de tronquer en
silence ;
la lecture est bornée et dit ce qui reste (`reste`).

Module pur : aucune entrée-sortie propre (le journal est injecté), aucune horloge.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from .. import journal_chaine
from . import modele
from .erreurs import refus

DEPARTEMENT = "m07-marketing"
REGISTRE = (DEPARTEMENT, "signaux_marketing")
REGISTRE_COMPTES = (DEPARTEMENT, "sources_signaux")
REGISTRE_CURSEURS = (DEPARTEMENT, "curseurs_signaux")
TYPE_MAILLON = "signal"
MAX_FAITS = 50_000
LIMITE_LECTURE_DEFAUT = 200
LIMITE_LECTURE_MAX = 1000


def charger(journal: Sequence[Any]) -> list[dict[str, Any]]:
    """Les faits du registre, chaîne vérifiée et chaque fait renormalisé. Une altération ou une forme inattendue est une
    ERREUR, jamais une lecture partielle."""
    if journal_chaine.verifier(journal):
        raise refus(
            "REJ-SIGNAUX-JOURNAL-ALTERE", "la chaîne de hachage du registre des signaux ne correspond plus", 500
        )
    faits = []
    for m in journal:
        if m["type"] != TYPE_MAILLON:
            raise refus("REJ-SIGNAUX-REGISTRE-INVALIDE", "maillon inattendu dans le registre des signaux", 500)
        corps = {k: v for k, v in m.items() if k not in journal_chaine.CLES_RESERVEES}
        try:
            faits.append(modele.normaliser_fait(corps))
        except Exception:  # noqa: BLE001
            raise refus(
                "REJ-SIGNAUX-REGISTRE-INVALIDE", "un fait du registre n'est plus conforme au schéma", 500
            ) from None
    return faits


def courants(faits: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Dernière révision de chaque fait. Une chaîne de révisions incohérente (saut, retour) est une erreur."""
    derniers: dict[str, dict[str, Any]] = {}
    for fait in faits:
        precedent = derniers.get(fait["fait_id"])
        attendu = 1 if precedent is None else precedent["revision"] + 1
        if fait["revision"] != attendu:
            raise refus("REJ-SIGNAUX-REGISTRE-INVALIDE", "révisions d'un fait incohérentes (saut ou retour)", 500)
        derniers[fait["fait_id"]] = dict(fait)
    return derniers


def enregistrer(journal: Any, faits: Iterable[Mapping[str, Any]], horodatage: str) -> dict[str, int]:
    """Écrit les faits (révision 1 en entrée) : nouveau fait, révision d'un fait existant dont la valeur a changé, ou
    rien si la valeur est identique. Tout ou rien."""
    normalises = [modele.normaliser_fait(f) for f in faits]
    page: dict[str, dict[str, Any]] = {}
    for fait in normalises:
        deja = page.get(fait["fait_id"])
        if deja is not None:
            if modele.sans_provenance_variable(deja) != modele.sans_provenance_variable(fait):
                raise refus(
                    "REJ-SIGNAUX-FAIT-CONFLIT",
                    "le même fait porte deux valeurs dans une même page : la page est refusée en entier",
                    422,
                )
            continue
        page[fait["fait_id"]] = fait
    existants = courants(charger(journal))
    a_ecrire, inchanges, revisions = [], 0, 0
    for fait_id, fait in page.items():
        courant = existants.get(fait_id)
        if courant is None:
            a_ecrire.append(fait)
        elif modele.sans_provenance_variable(courant) == modele.sans_provenance_variable(fait):
            inchanges += 1
        else:
            revisions += 1
            a_ecrire.append(modele.normaliser_fait({**fait, "revision": courant["revision"] + 1}))
    if len(journal) + len(a_ecrire) > MAX_FAITS:
        raise refus(
            "REJ-SIGNAUX-REGISTRE-PLEIN",
            f"le registre des signaux est borné à {MAX_FAITS} maillons : archiver "
            "avant de continuer (rien n'est tronqué en silence)",
            507,
        )
    for fait in a_ecrire:
        journal_chaine.ajouter(journal, TYPE_MAILLON, fait, horodatage)
    return {"nouveaux": len(a_ecrire) - revisions, "revisions": revisions, "inchanges": inchanges}


def lire(
    journal: Sequence[Any],
    *,
    source: str | None = None,
    nature: str | None = None,
    compte_ref: str | None = None,
    debut: date | None = None,
    fin: date | None = None,
    limite: int = LIMITE_LECTURE_DEFAUT,
    decalage: int = 0,
) -> dict[str, Any]:
    """Les faits COURANTS qui chevauchent [debut, fin], triés (source, nature, période, portée), avec `reste`."""
    if type(limite) is not int or not 1 <= limite <= LIMITE_LECTURE_MAX or type(decalage) is not int or decalage < 0:
        raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"limite 1 à {LIMITE_LECTURE_MAX}, décalage >= 0", 422)
    if source is not None and source not in modele.SOURCES:
        raise refus("REJ-SIGNAUX-SOURCE-INCONNUE", f"source attendue parmi {list(modele.SOURCES)}", 422)
    if nature is not None and nature not in modele.NATURES:
        raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", f"nature attendue parmi {list(modele.NATURES)}", 422)
    if debut is not None and fin is not None and debut > fin:
        raise refus("REJ-SIGNAUX-FENETRE-INVALIDE", "période inversée", 422)
    tous = courants(charger(journal))
    choisis = []
    for fait in tous.values():
        if source is not None and fait["source"] != source:
            continue
        if nature is not None and fait["nature"] != nature:
            continue
        if compte_ref is not None and fait["compte_ref"] != compte_ref:
            continue
        if debut is not None and fait["periode_fin"] < debut.isoformat():
            continue
        if fin is not None and fait["periode_debut"] > fin.isoformat():
            continue
        choisis.append(fait)
    choisis.sort(
        key=lambda f: (
            f["source"],
            f["nature"],
            f["periode_debut"],
            f["periode_fin"],
            f["portee"]["type"],
            f["portee"]["ref"],
            f["compte_ref"],
        )
    )
    page = choisis[decalage : decalage + limite]
    return {
        "faits": page,
        "total": len(choisis),
        "reste": max(0, len(choisis) - decalage - len(page)),
        "revises": sum(1 for f in choisis if f["revision"] > 1),
        "integrite": {"chaine_intacte": True},
    }


__all__ = [
    "DEPARTEMENT",
    "LIMITE_LECTURE_DEFAUT",
    "LIMITE_LECTURE_MAX",
    "MAX_FAITS",
    "REGISTRE",
    "REGISTRE_COMPTES",
    "REGISTRE_CURSEURS",
    "TYPE_MAILLON",
    "charger",
    "courants",
    "enregistrer",
    "lire",
]
