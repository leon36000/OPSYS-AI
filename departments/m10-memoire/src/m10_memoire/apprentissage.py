"""Aperçu déterministe des faits candidats M03, sans apprentissage ni mutation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any

from . import affaire

VERSION_ANALYSE = "m10-apercu-candidats-m03/v1"
MAX_MAILLONS = 10_000
MAX_PROPOSITIONS = 20
SEUIL_AFFAIRES = 3
_CLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LIGNE_ID = re.compile(r"^[0-9a-f]{64}$")


class ApercuRefuse(ValueError):
    """La photo M10 est invalide ou dépasse le plafond d'analyse."""


def _date(valeur: Any) -> datetime:
    if not isinstance(valeur, str):
        raise ApercuRefuse("horodatage invalide")
    try:
        resultat = datetime.fromisoformat(valeur)
    except ValueError as exc:
        raise ApercuRefuse("horodatage invalide") from exc
    if resultat.tzinfo is None:
        raise ApercuRefuse("horodatage sans fuseau")
    return resultat.astimezone(UTC)


def analyser_candidats(
    maillons: list[dict[str, Any]],
    *,
    cutoff_utc: datetime,
    tete_affaires: str | None,
    tete_evenements: str | None,
    outils_m03: Collection[str],
    codes_m3: Collection[str],
) -> dict[str, Any]:
    """Regroupe les seuls appels M03 par outil/résultat/code, dédupliqués par affaire.

    Les identifiants d'affaire restent internes au calcul. La sortie ne contient que les références
    de chaîne M10, des codes fermés et des comptages; elle n'est ni une vérité ni un score.
    """
    if not isinstance(maillons, list) or len(maillons) > MAX_MAILLONS:
        raise ApercuRefuse("plafond de maillons dépassé")
    if cutoff_utc.tzinfo is None:
        raise ApercuRefuse("cutoff sans fuseau")
    cutoff = cutoff_utc.astimezone(UTC)
    debut = cutoff - timedelta(days=365)
    catalogue_outils = frozenset(outils_m03)
    catalogue_codes = frozenset(codes_m3)
    if (
        not catalogue_outils or not catalogue_codes
        or any(not isinstance(item, str) or not item for item in catalogue_outils | catalogue_codes)
    ):
        raise ApercuRefuse("catalogues M03 indisponibles ou invalides")
    par_cle: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    outils_omis = 0
    codes_omis = 0
    for maillon in maillons:
        if not isinstance(maillon, dict):
            raise ApercuRefuse("maillon M10 invalide")
        if maillon.get("type_entree") != "fait_candidat":
            continue
        if maillon.get("departement_source") != "m03-estimation":
            continue
        outil = maillon.get("outil")
        if not isinstance(outil, str) or outil not in catalogue_outils:
            outils_omis += 1
            continue
        code = maillon.get("code")
        if code is not None and (not isinstance(code, str) or code not in catalogue_codes):
            codes_omis += 1
            continue
        cle = maillon.get("cle_depot")
        affaire_id = maillon.get("affaire_id")
        resultat = maillon.get("resultat")
        ligne_id = maillon.get("ligne_id")
        if (
            not isinstance(cle, str) or _CLE.fullmatch(cle) is None
            or not affaire.valide(affaire_id)
            or not isinstance(resultat, str) or resultat not in {"ok", "refus"}
            or not isinstance(ligne_id, str) or _LIGNE_ID.fullmatch(ligne_id) is None
        ):
            raise ApercuRefuse("fait candidat M03 invalide")
        instant = _date(maillon.get("horodatage"))
        contenu = (affaire_id, outil, resultat, code)
        precedent = par_cle.get(cle)
        if precedent is not None:
            if precedent[0] != contenu:
                raise ApercuRefuse("clé de dépôt M03 réutilisée avec un autre contenu")
            continue
        par_cle[cle] = (contenu, {"affaire": affaire_id, "outil": outil, "resultat": resultat,
                                  "code": code, "ligne_id": ligne_id, "horodatage": instant})

    groupes: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for _, fait in par_cle.values():
        if fait["horodatage"] < debut or fait["horodatage"] > cutoff:
            continue
        cle_groupe = (fait["outil"], fait["resultat"], fait["code"])
        groupe = groupes.setdefault(cle_groupe, {"affaires": set(), "lignes": [], "dates": []})
        groupe["affaires"].add(fait["affaire"])
        groupe["lignes"].append(fait["ligne_id"])
        groupe["dates"].append(fait["horodatage"])

    propositions = []
    for (outil, resultat, code), groupe in groupes.items():
        if len(groupe["affaires"]) < SEUIL_AFFAIRES:
            continue
        dates = groupe["dates"]
        propositions.append({
            "outil": outil,
            "resultat": resultat,
            "code": code,
            "affaires_distinctes": len(groupe["affaires"]),
            "observations": len(groupe["lignes"]),
            "premiere_observation_utc": min(dates).isoformat(),
            "derniere_observation_utc": max(dates).isoformat(),
            "sources_ligne_id": sorted(groupe["lignes"]),
        })
    propositions.sort(key=lambda p: (-p["affaires_distinctes"], p["outil"], p["resultat"], p["code"] or ""))
    total = len(propositions)
    propositions = propositions[:MAX_PROPOSITIONS]
    payload = {
        "version": VERSION_ANALYSE,
        "cutoff_utc": cutoff.isoformat(),
        "tete_affaires": tete_affaires,
        "tete_evenements": tete_evenements,
        "fenetre_jours": 365,
        "seuil_affaires": SEUIL_AFFAIRES,
        "catalogue_outils_sha256": hashlib.sha256(
            json.dumps(sorted(catalogue_outils), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "catalogue_codes_sha256": hashlib.sha256(
            json.dumps(sorted(catalogue_codes), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "propositions": propositions,
        "propositions_omises": total - len(propositions),
        "maillons_outil_hors_catalogue_omis": outils_omis,
        "maillons_code_hors_catalogue_omis": codes_omis,
        "statut": "complet",
        "nature": "statistiques_de_triage_pas_une_conclusion_metier",
    }
    canonique = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["rapport_sha256"] = hashlib.sha256(canonique.encode("utf-8")).hexdigest()
    return payload
