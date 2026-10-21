"""Catalogue fermé des références de règles de paie (sans calcul de retenues)."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import validation

__all__ = ["evaluer_sources"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FREQUENCES = frozenset({"hebdomadaire", "bihebdomadaire", "bimensuelle", "mensuelle"})
_STATUTS = frozenset({"QUALIFIEE", "NON_QUALIFIEE"})
_TAILLE_CAPTURE_MAX = 16 * 1024 * 1024


def _refus(code: str, detail: str) -> dict[str, str]:
    return validation.construire_verdict(code, detail=detail)


def _date_iso(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
        return None
    try:
        resultat = date.fromisoformat(valeur)
    except ValueError:
        return None
    return resultat if resultat.isoformat() == valeur else None


def _schema_catalogue(catalogue: Any) -> dict[str, Any] | None:
    if (not isinstance(catalogue, dict) or type(catalogue.get("schema_version")) is not int
            or catalogue.get("schema_version") != 1):
        return None
    juridictions = catalogue.get("juridictions")
    sources = catalogue.get("sources")
    if not isinstance(juridictions, dict) or not isinstance(sources, list):
        return None
    for code, config in juridictions.items():
        composants = config.get("composants_requis") if isinstance(config, dict) else None
        if (not isinstance(code, str) or not code or not isinstance(composants, list) or not composants
                or any(not isinstance(item, str) or not item for item in composants)
                or len(set(composants)) != len(composants)):
            return None
    ids: set[str] = set()
    requis = {
        "id", "juridiction", "composant", "document", "edition", "applicable_du", "applicable_au", "url",
        "capture_path", "sha256", "statut", "portee_statut", "frequences",
    }
    for source in sources:
        if not isinstance(source, dict) or not requis.issubset(source):
            return None
        identifiant = source.get("id")
        if not isinstance(identifiant, str) or not identifiant or identifiant in ids:
            return None
        ids.add(identifiant)
        for champ in ("juridiction", "composant", "document", "edition", "portee_statut", "url"):
            if not isinstance(source.get(champ), str) or not source[champ].strip():
                return None
        if not source["url"].startswith("https://"):
            return None
        capture_path = source.get("capture_path")
        if capture_path is not None and (not isinstance(capture_path, str) or not capture_path.strip()):
            return None
        sha256 = source.get("sha256")
        if sha256 is not None and (not isinstance(sha256, str) or not _SHA256.fullmatch(sha256)):
            return None
        statut = source.get("statut")
        if not isinstance(statut, str) or statut not in _STATUTS or not isinstance(source.get("portee_statut"), str):
            return None
        freqs = source.get("frequences")
        if freqs is not None and (
            not isinstance(freqs, list)
            or not freqs
            or any(not isinstance(freq, str) or freq not in _FREQUENCES for freq in freqs)
        ):
            return None
    return {"juridictions": juridictions, "sources": sources}


def _capture_verifiee(source: dict[str, Any], racine: Path) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    chemin_relatif = source.get("capture_path")
    attendu = source.get("sha256")
    if not isinstance(chemin_relatif, str) or not chemin_relatif:
        return None, _refus("REJ-PAIE-CAPTURE-ABSENTE", f"capture absente pour la référence {source['id']}")
    posix = PurePosixPath(chemin_relatif)
    if posix.is_absolute() or ".." in posix.parts or "\\" in chemin_relatif:
        return None, _refus("REJ-PAIE-CHEMIN-INVALIDE", f"chemin de capture invalide pour {source['id']}")
    try:
        racine_resolue = racine.resolve(strict=True)
        cible = (racine_resolue / Path(*posix.parts)).resolve(strict=True)
        cible.relative_to(racine_resolue)
    except (OSError, ValueError):
        return None, _refus("REJ-PAIE-CHEMIN-INVALIDE", f"capture absente ou hors racine pour {source['id']}")
    if not cible.is_file() or not isinstance(attendu, str) or not _SHA256.fullmatch(attendu):
        return None, _refus("REJ-PAIE-SHA-INVALIDE", f"empreinte absente ou mal formée pour {source['id']}")
    try:
        if cible.stat().st_size > _TAILLE_CAPTURE_MAX:
            return None, _refus(
                "REJ-PAIE-CAPTURE-TROP-GROSSE", f"capture dépasse {_TAILLE_CAPTURE_MAX} octets pour {source['id']}"
            )
        empreinte = hashlib.sha256()
        with cible.open("rb") as capture:
            for bloc in iter(lambda: capture.read(64 * 1024), b""):
                empreinte.update(bloc)
        digest = empreinte.hexdigest()
    except OSError:
        return None, _refus("REJ-PAIE-CAPTURE-ILLISIBLE", f"capture illisible pour {source['id']}")
    if digest != attendu:
        return None, _refus("REJ-PAIE-SHA-DIVERGENT", f"empreinte divergente pour {source['id']}")
    return {"chemin": chemin_relatif, "sha256": digest}, None


def evaluer_sources(
    catalogue: Any,
    *,
    racine: Path,
    juridiction: str,
    date_paie: str,
    periode_debut: str,
    periode_fin: str,
    fuseau: str,
    frequence: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Résout seulement des références éditoriales/captures; aucune valeur fiscale n'est rendue."""
    valide = _schema_catalogue(catalogue)
    if valide is None:
        return None, _refus("REJ-PAIE-CATALOGUE-INVALIDE", "structure du catalogue absente ou invalide")
    debut, fin, paie = _date_iso(periode_debut), _date_iso(periode_fin), _date_iso(date_paie)
    if debut is None or fin is None or paie is None:
        return None, _refus("REJ-PAIE-DATE-INVALIDE", "dates attendues en format canonique YYYY-MM-DD")
    if debut > fin:
        return None, _refus("REJ-PAIE-PERIODE-INVALIDE", "la période doit être ordonnée, bornes inclusives")
    if (fin - debut).days >= 31:
        return None, _refus("REJ-PAIE-PERIODE-INVALIDE", "la période inclusive doit couvrir de 1 à 31 jours")
    try:
        ZoneInfo(fuseau)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        return None, _refus("REJ-PAIE-FUSEAU-INVALIDE", "fuseau IANA inconnu")
    if not isinstance(juridiction, str) or juridiction not in valide["juridictions"]:
        return None, _refus("REJ-PAIE-JURIDICTION-NON-COUVERTE", "juridiction absente du catalogue fermé")
    if not isinstance(frequence, str) or frequence not in _FREQUENCES:
        return None, _refus("REJ-PAIE-FREQUENCE-INVALIDE", "fréquence absente de la liste fermée")

    config = valide["juridictions"][juridiction]
    tous = valide["sources"]
    references_catalogue = [
        {
            "id": src["id"], "composant": src["composant"], "document": src["document"],
            "edition": src["edition"], "applicable_du": src["applicable_du"],
            "applicable_au": src["applicable_au"], "url": src["url"],
            "statut_declare": src["statut"], "sha256_declare": src["sha256"],
            "portee_statut": src["portee_statut"],
        }
        for src in tous if src["juridiction"] == juridiction
    ]
    verifies: list[dict[str, str]] = []
    manques: list[dict[str, str]] = []
    for composant in config["composants_requis"]:
        candidats = [
            src for src in tous
            if src.get("juridiction") == juridiction and src.get("composant") == composant
        ]
        qui_couvrent = []
        intervalle_absent = False
        for src in candidats:
            du, au = _date_iso(src.get("applicable_du")), _date_iso(src.get("applicable_au"))
            if du is None and au is None:
                intervalle_absent = True
                continue
            if du is None:
                if paie <= au:
                    intervalle_absent = True
                continue
            if au is None:
                if paie >= du:
                    intervalle_absent = True
                continue
            if du <= paie <= au:
                qui_couvrent.append(src)
        if len(qui_couvrent) > 1:
            return None, _refus("REJ-PAIE-SOURCE-AMBIGUE", f"plusieurs éditions couvrent {composant}")
        if intervalle_absent:
            # L'inventaire reste consultable, mais l'intervalle inconnu interdit de certifier une édition unique.
            manques.append({"code": "REJ-PAIE-INTERVALLE-ABSENT", "composant": composant})
            continue
        if not qui_couvrent:
            return None, _refus("REJ-PAIE-EDITION-ABSENTE", f"aucune édition ne couvre {paie} pour {composant}")
        src = qui_couvrent[0]
        freq = src.get("frequences")
        if freq is not None and frequence not in freq:
            return None, _refus("REJ-PAIE-FREQUENCE-NON-COUVERTE", f"fréquence non couverte par {src['id']}")
        if src["statut"] != "QUALIFIEE":
            manques.append({"code": "REJ-PAIE-SOURCE-NON-QUALIFIEE", "reference": src["id"]})
            continue
        capture, refus = _capture_verifiee(src, racine)
        if refus is not None:
            return None, refus
        verifies.append({
            "id": src["id"], "document": src["document"], "edition": src["edition"],
            "applicable_du": src["applicable_du"], "applicable_au": src["applicable_au"],
            "capture_path": capture["chemin"], "sha256": capture["sha256"],
            "portee_statut": src["portee_statut"],
        })

    # Même une liste de références capturées ne constitue pas un moteur ni une validation de paie.
    return {
        "statut": "PARTIEL" if manques or not verifies else "REFERENCES_VERIFIEES",
        "juridiction": juridiction,
        "date_paie": date_paie,
        "periode": {"debut": periode_debut, "fin": periode_fin, "fuseau": fuseau},
        "frequence": frequence,
        "references_catalogue": references_catalogue,
        "sources_verifiees": verifies,
        "manques": manques,
        "couverture_catalogue": (
            "partielle; la vérification documentaire n'est ni un calcul de paie ni une approbation officielle"
        ),
        "limite": "Références seulement; aucune règle, retenue, contribution ou somme de paie calculée.",
    }, None
