"""Ce qui exige la direction : hiérarchisation DÉTERMINISTE et explicable des demandes en attente (Athéna).

Module pur : aucune horloge (``maintenant`` fourni), aucun import d'``opsys``. La règle est écrite en clair, rendue avec
le résultat et se refait à la main :

1. le niveau d'approbation le plus ÉLEVÉ d'abord (N5, N4, N3, N2, N1, N0) ;
2. à niveau égal, la demande en attente DEPUIS LE PLUS LONGTEMPS d'abord ;
3. à âge égal, l'identifiant (ordre stable, indépendant de l'ordre d'arrivée).

Aucun score caché, aucune pondération apprise, aucune lecture du contenu : le texte d'une demande (``resume``) est une
donnée affichée, bornée, jamais interprétée. Une demande dont le niveau n'est pas déclaré n'est PAS classée parmi les
niveaux connus ni supposée basse : elle forme un groupe « niveau non déclaré » placé après les niveaux connus, compté et
dit. Une demande dont l'âge est illisible (ou postérieur à ``maintenant``) passe après les demandes d'âge connu de son
niveau, avec le motif. M9 ne décide, n'approuve ni ne refuse rien : il ordonne ce qui attend un humain.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

VERSION = "2026-11-01.1"
NIVEAUX = ("N5", "N4", "N3", "N2", "N1", "N0")
_CHAMPS = ("type", "id", "resume", "niveau", "depuis", "action_proposee", "departement")
MAX_RESUME = 160
MAX_ELEMENTS = 5000
REGLE = (
    "niveau le plus élevé d'abord (N5 à N0), puis l'attente la plus ancienne, puis l'identifiant ; une demande sans "
    "niveau déclaré passe après les niveaux connus et est comptée à part"
)
_NIVEAU = re.compile(r"[Nn]?([0-5])")


def parse_niveau(valeur: object) -> str | None:
    """``N3``, ``n3``, ``3`` ou l'entier 3 → ``N3`` ; tout le reste (absent, hors 0–5, booléen) → ``None``."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        texte = str(valeur)
    elif isinstance(valeur, str):
        texte = valeur.strip()
    else:
        return None
    trouve = _NIVEAU.fullmatch(texte)
    return f"N{trouve.group(1)}" if trouve else None


def _instant(valeur: object) -> datetime | None:
    if type(valeur) is not str or not valeur or len(valeur) > 64:
        return None
    try:
        analyse = datetime.fromisoformat(valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur)
    except ValueError:
        return None
    return analyse.astimezone(UTC) if analyse.utcoffset() is not None else None


def duree_texte(secondes: int) -> str:
    """« 3 j 4 h » : mise en forme d'une durée connue, sans arrondi caché (les minutes ne sont pas écrites)."""
    jours, reste = divmod(max(0, secondes), 86400)
    heures = reste // 3600
    if jours:
        return f"{jours} j {heures} h"
    return f"{heures} h" if heures else f"{reste // 60} min"


def hierarchiser(decisions: Sequence[Mapping], *, maintenant: str) -> dict:
    """Classement complet (non borné ; la pagination est l'affaire de l'adaptateur), groupes par niveau et règle."""
    instant_ref = _instant(maintenant)
    if instant_ref is None:
        raise ValueError("REJ-PRIORITE-TEMPS : instant avec fuseau explicite requis")
    if len(decisions) > MAX_ELEMENTS:
        raise ValueError("REJ-PRIORITE-BORNE : trop de demandes pour un classement en une lecture")
    elements = []
    identifiants: set[str] = set()
    for rang_entree, item in enumerate(decisions):
        if not isinstance(item, Mapping) or any(champ not in item for champ in _CHAMPS):
            raise ValueError(f"REJ-PRIORITE-ENTREE : demande {rang_entree} sans les champs {list(_CHAMPS)}")
        identifiant = item["id"]
        if type(identifiant) is not str or not identifiant or identifiant in identifiants:
            raise ValueError("REJ-PRIORITE-ENTREE : identifiant de demande distinct requis")
        identifiants.add(identifiant)
        niveau = parse_niveau(item["niveau"])
        depuis = _instant(item["depuis"])
        age = int((instant_ref - depuis).total_seconds()) if depuis is not None else None
        age_connu = age is not None and age >= 0
        elements.append(
            {
                "id": identifiant,
                "type": str(item["type"])[:40],
                "departement": str(item["departement"])[:64],
                "resume": str(item["resume"])[:MAX_RESUME],
                "action_proposee": str(item["action_proposee"])[:80],
                "niveau": niveau,
                "depuis": item["depuis"] if isinstance(item["depuis"], str) else None,
                "age_s": age if age_connu else None,
                "age_texte": duree_texte(age) if age_connu else None,
                "motifs": [
                    m
                    for m, ok in (("niveau_non_declare", niveau is None), ("age_illisible_ou_futur", not age_connu))
                    if ok
                ],
            }
        )
    elements.sort(
        key=lambda e: (
            NIVEAUX.index(e["niveau"]) if e["niveau"] is not None else len(NIVEAUX),
            0 if e["age_s"] is not None else 1,
            -(e["age_s"] or 0),
            e["id"],
        )
    )
    for rang, element in enumerate(elements, start=1):
        niveau = element["niveau"] or "niveau non déclaré"
        ancien = f"en attente depuis {element['age_texte']}" if element["age_texte"] else "âge illisible"
        element["rang"] = rang
        element["raison"] = f"{niveau} ; {ancien}"
    par_niveau = {}
    for niveau in (*NIVEAUX, None):
        membres = [e for e in elements if e["niveau"] == niveau]
        if not membres:
            continue
        ages = [e["age_s"] for e in membres if e["age_s"] is not None]
        par_niveau[niveau or "non_declare"] = {
            "nombre": len(membres),
            "plus_ancien_s": max(ages) if ages else None,
            "plus_ancien_texte": duree_texte(max(ages)) if ages else None,
        }
    return {
        "type": "EXIGE_LA_DIRECTION",
        "version": VERSION,
        "maintenant": maintenant,
        "regle": REGLE,
        "total": len(elements),
        "par_niveau": par_niveau,
        "elements": elements,
        "limites": [
            "M9 ordonne ce qui attend un humain ; il n'approuve, ne refuse et n'exécute rien.",
            "Le texte d'une demande est une donnée affichée (bornée), jamais une instruction.",
        ],
    }
