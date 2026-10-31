"""Dossier stratégique M9 : la matière citable d'une question, bâtie des seules captures connues.

Module pur. Il transforme les captures (M9.1) connues à un instant en un dossier borné : couverture explicite,
contradictions
conservées, manques nommés et FAITS CITABLES — chaque valeur scalaire d'une capture acceptée et complète, adressée par
``<lecture_id>#<rang>:<chemin>`` et conservée en texte exact. Cette adresse est ce qu'un spécialiste cite et ce que
``conseil.admettre_proposition`` compare mot pour mot : aucune valeur n'est reformulée, arrondie ni calculée ici.

Le dossier ne dit rien de la vérité ni de la fraîcheur métier de ses faits ; il dit ce qui est connu, de qui, quand M9
l'a
reçu, et ce qui manque. Une capture refusée, partielle ou contradictoire ne produit AUCUN fait citable : son état figure
dans
les manques. Les faits sont ordonnés de façon stable (lecture, rang, chemin) et bornés ; le dépassement est compté,
jamais
tronqué en silence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import catalogue_producteurs as cat

MAX_FAITS = 400
MAX_PROFONDEUR = 12
MAX_QUESTION = 2048
_LIMITES = (
    "Faits reçus de producteurs, cités tels quels : ni vérité, ni fraîcheur métier, ni couverture complète démontrée.",
    "Un fait n'existe que d'une capture acceptée, complète et non contradictoire ; le reste figure dans les manques.",
)


def _scalaire(valeur: object) -> str | None:
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    if isinstance(valeur, (int, float)):
        return json.dumps(valeur)
    if isinstance(valeur, str):
        return valeur
    return None


def _aplatir(document: object, chemin: str, sortie: list[tuple[str, str]], profondeur: int = 0) -> None:
    if profondeur > MAX_PROFONDEUR:
        return
    if isinstance(document, Mapping):
        for cle in sorted(document):
            _aplatir(document[cle], f"{chemin}.{cle}" if chemin else str(cle), sortie, profondeur + 1)
    elif isinstance(document, list):
        for rang, element in enumerate(document):
            _aplatir(element, f"{chemin}[{rang}]", sortie, profondeur + 1)
    else:
        texte = _scalaire(document)
        if texte is not None:
            sortie.append((chemin, texte))


def _est_zero(texte: str) -> bool:
    try:
        return Decimal(texte) == 0
    except InvalidOperation:
        return False


def faits_citables(captures: Sequence[Mapping], *, max_faits: int = MAX_FAITS) -> tuple[dict[str, str], int]:
    """(faits ``adresse → texte``, nombre de faits non retenus). Captures déjà filtrées (acceptées, complètes)."""
    faits: dict[str, str] = {}
    exces = 0
    for capture in sorted(captures, key=lambda c: (c["lecture_id"], c["index"])):
        lecture = cat.PAR_ID[capture["lecture_id"]]
        for numero_page, page in enumerate(capture["pages"]):
            paires: list[tuple[str, str]] = []
            _aplatir(page, "", paires)
            for chemin, texte in paires:
                if not cat.est_citable(lecture, chemin):
                    continue  # champ hors de la liste sûre du catalogue : ni fait, ni « fait non retenu »
                if lecture.zero_non_citable and _est_zero(texte):
                    continue  # un compte nul dit « aucune déclarée par la source », jamais « zéro »
                adresse = f"{capture['lecture_id']}#{capture['index']}:p{numero_page}.{chemin}"
                if len(faits) >= max_faits:
                    exces += 1
                else:
                    faits[adresse] = texte
    return faits, exces


def construire(
    captures: Sequence[Mapping],
    *,
    question: str,
    domaines: Sequence[str],
    reference: str,
    connaissance: str,
    attendues: Sequence[str] | None = None,
    max_faits: int = MAX_FAITS,
) -> dict:
    """Dossier d'une question à une référence, avec ce que M9 connaissait à ``connaissance``."""
    if type(question) is not str or not question.strip() or len(question) > MAX_QUESTION:
        raise ValueError(f"REJ-DOSSIER-QUESTION : question non vide de {MAX_QUESTION} caractères au plus requise")
    liste = list(attendues) if attendues is not None else [lecture.id for lecture in cat.LECTURES]
    couverture = cs.evaluer_couverture(captures, reference=reference, connaissance=connaissance, attendues=liste)
    connues = cs.connues_a(captures, connaissance)
    # Citable : capture ACCEPTÉE dont le temps métier est présent ou non déclaré (une réserve, pas une exclusion), y
    # compris
    # PARTIELLE : les faits reçus sont réels, la lecture reste nommée aux manques et à ``lectures_partielles``.
    # Hors dossier, nommés dans les manques : absente, refusée, contradictoire, ou postérieure à la référence.
    presentes = {
        e["lecture_id"]
        for e in couverture["lectures"]
        if e["statut"] in ("PRESENTE", "TEMPS_METIER_NON_DECLARE", "PARTIELLE")
    }
    utiles = []
    for lecture_id in sorted(presentes):
        siennes = [c for c in connues if c["lecture_id"] == lecture_id and c["verdict"] == "ACCEPTEE"]
        derniers: dict[str, Mapping] = {}
        for capture in siennes:
            derniers[capture["arguments_sha256"]] = capture
        utiles.extend(derniers.values())
    faits, exces = faits_citables(utiles, max_faits=max_faits)
    manques = [
        {"lecture_id": e["lecture_id"], "statut": e["statut"], "manque": e.get("manque")}
        for e in couverture["lectures"]
        if e["statut"] != "PRESENTE"
    ]
    dossier = {
        "type": "DOSSIER_STRATEGIQUE",
        "question": question,
        "domaines": sorted(domaines),
        "reference": couverture["reference"],
        "connaissance": couverture["connaissance"],
        "couverture": {
            "complete": couverture["complete"],
            "lectures_non_presentes": couverture["lectures_non_presentes"],
            "lectures": couverture["lectures"],
        },
        "contradictions": couverture["contradictions"],
        "manques": manques,
        "faits": faits,
        "faits_non_retenus": exces,
        "lectures_partielles": sorted(e["lecture_id"] for e in couverture["lectures"] if e["statut"] == "PARTIELLE"),
        "temps_metier_non_declare": sorted(
            e["lecture_id"] for e in couverture["lectures"] if e["statut"] == "TEMPS_METIER_NON_DECLARE"
        ),
        "captures_utilisees": sorted({(c["index"], c["hash_maillon"]) for c in utiles}),
        "limites": list(_LIMITES),
    }
    dossier["captures_utilisees"] = [{"index": i, "hash_maillon": h} for i, h in dossier["captures_utilisees"]]
    dossier["dossier_id"] = hashlib.sha256(
        json.dumps(dossier, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return dossier
