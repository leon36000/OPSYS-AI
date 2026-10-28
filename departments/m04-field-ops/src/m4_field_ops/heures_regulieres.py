"""Aperçu déterministe d'heures régulières à partir des pointages canoniques.

Cette couche ne décide jamais si une catégorie est payable. Elle expose une proposition
individuelle bornée et ses références; une approbation humaine distincte doit en choisir
explicitement le traitement avant qu'un maillon validé soit écrit.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _refus(code: str, detail: str) -> dict:
    return {"accepte": False, "verdict": {"code": code, "detail": detail}}


def _minutes(debut: datetime, fin: datetime) -> int | None:
    secondes = (fin.astimezone(UTC) - debut.astimezone(UTC)).total_seconds()
    if secondes < 0 or secondes % 60:
        return None
    return int(secondes // 60)


def validation_coherente(maillon: dict, apercu: dict, revision_attendue: int, remplace_attendu: str | None) -> bool:
    """Vérifie les données métier N4 indépendamment de l'intégrité hash du registre."""
    categories = apercu.get("categories_minutes")
    if not isinstance(categories, dict) or set(categories) != {"travail", "deplacement", "pause"}:
        return False
    dispositions = maillon.get("dispositions")
    if not isinstance(dispositions, dict) or set(dispositions) != set(categories):
        return False
    if any(not isinstance(v, dict) or type(v.get("inclure")) is not bool
           or not isinstance(v.get("source"), str) or not v["source"].strip() for v in dispositions.values()):
        return False
    total = sum(categories[key] for key, valeur in dispositions.items() if valeur["inclure"])
    sources = maillon.get("sources")
    if (maillon.get("type_entree") != "heures_regulieres_validees" or maillon.get("version_schema") != 1
            or maillon.get("revision") != revision_attendue
            or maillon.get("remplace_ligne_id") != remplace_attendu
            or maillon.get("periode") != apercu.get("periode")
            or maillon.get("technicien_id") != apercu.get("technicien_id")
            or maillon.get("categories_minutes") != categories
            or maillon.get("details_intervalles") != apercu.get("details_intervalles")
            or sources != apercu.get("sources")
            or maillon.get("empreinte_sources") != apercu.get("empreinte_sources")
            or type(maillon.get("minutes_regulieres")) is not int or maillon["minutes_regulieres"] != total
            or maillon.get("couverture_complete") is not True
            or maillon.get("classification_reguliere_confirmee") is not True
            or maillon.get("role_approbateur") not in {"admin", "manager", "nathan_owner"}
            or not isinstance(maillon.get("approuve_par"), str) or not maillon["approuve_par"].strip()
            or not isinstance(maillon.get("demande_approbation_id"), str)
            or not isinstance(maillon.get("motif_correction"), str) or not maillon["motif_correction"].strip()):
        return False
    try:
        horodatage = datetime.fromisoformat(maillon["horodatage"])
    except (ValueError, TypeError, KeyError):
        return False
    return horodatage.tzinfo is not None


def previsualiser(maillons: list[dict], technicien_id: str, debut: str, fin: str, fuseau: str) -> dict:
    """Dérive des durées explicites; refuse toute séquence ambiguë/incomplète.

    Les dates de période sont des dates civiles du fuseau fourni. Toute l'intervalle de
    chaque catégorie doit être dans la période. Aucun champ GPS n'est copié en sortie.
    """
    if (not isinstance(debut, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", debut)
            or not isinstance(fin, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fin)):
        return _refus("REJ-PERIODE-INVALIDE", "dates ISO AAAA-MM-JJ requises")
    try:
        d0, d1, zone = date.fromisoformat(debut), date.fromisoformat(fin), ZoneInfo(fuseau)
        date_suivante = d1 + timedelta(days=1)
    except (ValueError, TypeError, ZoneInfoNotFoundError, OverflowError):
        return _refus("REJ-PERIODE-INVALIDE", "dates ISO ou fuseau IANA invalides")
    if d1 < d0 or (d1 - d0).days + 1 > 31 or not isinstance(technicien_id, str) or not technicien_id.strip():
        return _refus("REJ-PERIODE-INVALIDE", "technicien requis; période doit couvrir de 1 à 31 jours")
    try:
        periode_debut_utc = datetime.combine(d0, time.min, zone).astimezone(UTC)
        periode_fin_utc = datetime.combine(date_suivante, time.min, zone).astimezone(UTC)
    except OverflowError:
        return _refus("REJ-PERIODE-INVALIDE", "bornes civiles non représentables en UTC")

    points = [dict(m) for m in maillons if m.get("type_entree") == "pointage"
              and m.get("technicien_id") == technicien_id]
    if not points:
        return _refus("REJ-SOURCES-ABSENTES", "aucun pointage canonique pour cette personne")
    if any(not m.get("intervention_id") for m in points):
        return _refus("REJ-INTERVENTION-AMBIGUE", "chaque pointage doit référencer une intervention")
    if any(m.get("action") not in {"arrivee", "depart", "pause_debut", "pause_fin"} for m in points):
        return _refus("REJ-POINTAGE-INCONNU", "action de pointage non classifiable")
    try:
        for m in points:
            if not isinstance(m.get("ligne_id"), str) or not re.fullmatch(r"[0-9a-f]{64}", m["ligne_id"]):
                raise ValueError
            dt = datetime.fromisoformat(m["horodatage"])
            if dt.tzinfo is None:
                raise ValueError
            m["_dt_local"] = dt.astimezone(zone)
            m["_dt_utc"] = dt.astimezone(UTC)
    except (ValueError, TypeError, KeyError):
        return _refus("REJ-SOURCE-INVALIDE", "pointage sans horodatage zoné ou référence valide")
    points.sort(key=lambda m: m["_dt_utc"])

    interventions = {m["intervention_id"] for m in points if m.get("intervention_id")}
    if any(m.get("type_entree") == "pointage" and m.get("intervention_id") in interventions
           and m.get("technicien_id") != technicien_id for m in maillons):
        return _refus("REJ-TECHNICIEN-AMBIGU", "une intervention relie des pointages de plusieurs techniciens")
    travail = deplacement = pause = 0
    details = []
    refs: set[str] = set()
    intervalles_occupes: list[tuple[datetime, datetime]] = []
    for iid in sorted(interventions):
        ps = [m for m in points if m.get("intervention_id") == iid]
        actions = [m for m in ps if m.get("action") in {"arrivee", "depart", "pause_debut", "pause_fin"}]
        arrivees = [m for m in actions if m.get("action") == "arrivee"]
        departs = [m for m in actions if m.get("action") == "depart"]
        transitions = [m for m in maillons if m.get("type_entree") == "transition_statut"
                       and m.get("intervention_id") == iid and m.get("statut") == "en_route"]
        if len(arrivees) != 1 or len(departs) != 1 or len(transitions) != 1:
            if ps and min(m["_dt_utc"] for m in ps) >= periode_fin_utc:
                continue
            return _refus("REJ-POINTAGES-AMBIGUS", "une intervention doit avoir une arrivée et un départ uniques")
        arrivee, depart = arrivees[0], departs[0]
        start, stop = arrivee["_dt_local"], depart["_dt_local"]
        start_utc, stop_utc = arrivee["_dt_utc"], depart["_dt_utc"]
        try:
            route_source = datetime.fromisoformat(transitions[0]["horodatage"])
            if (route_source.tzinfo is None or not isinstance(transitions[0].get("ligne_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", transitions[0]["ligne_id"])):
                raise ValueError
            route = route_source.astimezone(zone)
            route_utc = route_source.astimezone(UTC)
        except (ValueError, TypeError, KeyError):
            return _refus("REJ-SOURCE-INVALIDE", "transition en_route invalide ou sans fuseau")
        if route_utc > start_utc or stop_utc <= start_utc:
            return _refus("REJ-INTERVALLE-HORS-PERIODE", "ordre temporel route/arrivée/départ incohérent")
        if stop_utc <= periode_debut_utc or route_utc >= periode_fin_utc:
            continue
        if (route_utc < periode_debut_utc or stop_utc > periode_fin_utc
                or route.date() != start.date() or start.date() != stop.date()
                or not d0 <= start.date() <= d1):
            return _refus("REJ-INTERVALLE-HORS-PERIODE", "intervalle incomplet ou traversant une date civile")
        if any(m["_dt_utc"] < periode_debut_utc or m["_dt_utc"] >= periode_fin_utc for m in ps):
            return _refus("REJ-INTERVALLE-HORS-PERIODE", "un pointage de l'intervention traverse la période")
        minutes_travail = _minutes(start, stop)
        if minutes_travail is None:
            return _refus("REJ-PRECISION-MINUTE", "durée non représentable en minutes entières; aucun arrondi appliqué")
        refs.update((arrivee["ligne_id"], depart["ligne_id"]))
        detail = {"intervention_id": iid, "travail": {
            "debut": start.isoformat(), "fin": stop.isoformat(),
            "sources": [arrivee["ligne_id"], depart["ligne_id"]]}, "pauses": []}

        pause_intervention = 0
        pauses = sorted((m for m in actions if m.get("action") in {"pause_debut", "pause_fin"}),
                        key=lambda m: m["_dt_utc"])
        if len(pauses) % 2:
            return _refus("REJ-PAUSE-INCOMPLETE", "la séquence de pauses est incomplète")
        for a, b in zip(pauses[::2], pauses[1::2], strict=True):
            if (a["action"] != "pause_debut" or b["action"] != "pause_fin"
                    or not start_utc <= a["_dt_utc"] < b["_dt_utc"] <= stop_utc):
                return _refus("REJ-PAUSE-AMBIGUE", "séquence de pauses incohérente")
            minutes_pause = _minutes(a["_dt_local"], b["_dt_local"])
            if minutes_pause is None:
                return _refus("REJ-PRECISION-MINUTE", "pause non représentable en minutes entières")
            pause += minutes_pause
            pause_intervention += minutes_pause
            refs.update((a["ligne_id"], b["ligne_id"]))
            detail["pauses"].append({"debut": a["_dt_local"].isoformat(), "fin": b["_dt_local"].isoformat(),
                                     "sources": [a["ligne_id"], b["ligne_id"]]})
        if pause_intervention > minutes_travail:
            return _refus("REJ-PAUSE-AMBIGUE", "la pause dépasse la durée sur site")
        travail += minutes_travail - pause_intervention
        detail["travail"]["minutes_net_apres_pauses"] = minutes_travail - pause_intervention

        minutes_deplacement = _minutes(route, start)
        if minutes_deplacement is None:
            return _refus("REJ-PRECISION-MINUTE", "déplacement non représentable en minutes entières")
        deplacement += minutes_deplacement
        refs.update((transitions[0]["ligne_id"],))
        detail["deplacement"] = {"debut": route.isoformat(), "fin": start.isoformat(),
                                  "sources": [transitions[0]["ligne_id"], arrivee["ligne_id"]]}
        details.append(detail)
        intervalles_occupes.append((route_utc, stop_utc))

    intervalles_occupes.sort(key=lambda intervalle: intervalle[0])
    if any(courant[0] < precedent[1] for precedent, courant in
           zip(intervalles_occupes, intervalles_occupes[1:], strict=False)):
        return _refus("REJ-INTERVENTIONS-CHEVAUCHEES", "interventions ou déplacements se chevauchent")
    if not details:
        return _refus("REJ-SOURCES-ABSENTES", "aucune séquence de pointage dans cette période")

    references = sorted(refs)
    canonical = json.dumps({"sources": references, "technicien_id": technicien_id, "debut": debut,
                            "fin": fin, "fuseau": fuseau}, sort_keys=True, separators=(",", ":"))
    empreinte = sha256(canonical.encode()).hexdigest()
    validations = [m for m in maillons if m.get("type_entree") == "heures_regulieres_validees"
                   and m.get("technicien_id") == technicien_id
                   and m.get("periode") == {"debut": debut, "fin": fin, "fuseau": fuseau}]
    if any(type(m.get("revision")) is not int or m["revision"] < 1
           or not isinstance(m.get("ligne_id"), str) or not re.fullmatch(r"[0-9a-f]{64}", m["ligne_id"])
           for m in validations):
        return _refus("REJ-VALIDATION-INCOHERENTE", "métadonnées de validation précédente invalides")
    precedente = None if not validations else {
        "revision": validations[-1]["revision"], "ligne_id": validations[-1]["ligne_id"]}
    return {"accepte": True, "resultat": {
        "technicien_id": technicien_id, "periode": {"debut": debut, "fin": fin, "fuseau": fuseau},
        "categories_minutes": {"travail": travail, "deplacement": deplacement, "pause": pause},
        "details_intervalles": details, "sources": references, "empreinte_sources": empreinte,
        "validation_precedente": precedente,
    }}
