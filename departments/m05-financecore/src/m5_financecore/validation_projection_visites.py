"""Contrôle défensif de la projection privée M4 V2, sans recalcul des temps.

L'empreinte n'authentifie pas son producteur. L'appelant doit obtenir instance,
WCT, snapshots et CAS auprès de propriétaires autorisés, dans leur transaction,
les revalider avant toute imputation et comparer le WCT à son reçu M5.
Une fixture ne constitue jamais cette preuve de provenance.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from . import encodage

_HEX = re.compile(r"^[0-9a-f]{64}$")
_VERSION = "opsys.m4.temps_certifies.v2"
_CHAMPS = {
    "version",
    "instance_id",
    "chantier_id",
    "intervention_id",
    "lead_id",
    "wct",
    "sources",
    "visites",
    "totaux",
    "revue_chantier",
    "inconnus",
    "empreinte",
}
_VISITE = {
    "visite_id",
    "ancre",
    "equipe_planifiee_id",
    "equipe_pointee",
    "identifiant_pointe",
    "ouverture",
    "evenements",
    "fermeture",
    "composition_declaree",
    "presence_individuelle",
    "minutes",
}


class _Invalide(ValueError):
    pass


def _exiger(condition: bool, raison: str) -> None:
    if not condition:
        raise _Invalide(raison)


def _objet(valeur: Any, cles: set[str], nom: str) -> dict:
    _exiger(isinstance(valeur, dict) and set(valeur) == cles, f"{nom} : champs invalides")
    return valeur


def _texte(valeur: Any) -> bool:
    return isinstance(valeur, str) and bool(valeur.strip())


def _hash(valeur: Any) -> bool:
    return isinstance(valeur, str) and _HEX.fullmatch(valeur) is not None


def _minute(valeur: Any) -> bool:
    return type(valeur) is int and 0 <= valeur <= 10**9


def _instant(valeur: Any) -> datetime:
    _exiger(isinstance(valeur, str), "horodatage absent")
    try:
        d = datetime.fromisoformat(valeur)
        _exiger(d.utcoffset() is not None, "horodatage sans zone")
        return d.astimezone(UTC)
    except (ValueError, OverflowError):
        raise _Invalide("horodatage invalide") from None


def _json_strict(valeur: Any, profondeur: int = 0) -> None:
    _exiger(profondeur <= 20, "projection trop profonde")
    if valeur is None or type(valeur) in (str, int, bool):
        return
    if type(valeur) is list:
        _exiger(len(valeur) <= 10000, "liste trop longue")
        for enfant in valeur:
            _json_strict(enfant, profondeur + 1)
        return
    if type(valeur) is dict:
        _exiger(all(type(k) is str for k in valeur), "clé non textuelle")
        for enfant in valeur.values():
            _json_strict(enfant, profondeur + 1)
        return
    raise _Invalide("type JSON non admis")


def _maillon(valeur: Any, nom: str) -> datetime:
    o = _objet(valeur, {"source_ligne_id", "horodatage"}, nom)
    _exiger(_hash(o["source_ligne_id"]), f"{nom} : référence invalide")
    return _instant(o["horodatage"])


def _controle_visite(visite: Any, intervention: str) -> tuple[tuple, dict, list, bool]:
    v = _objet(visite, _VISITE, "visite")
    ident = v["visite_id"]
    _exiger(_hash(ident), "visite : identifiant invalide")
    ancre = _objet(v["ancre"], {"intervention_id", "plan_id", "source_application_id", "source_ligne_id"}, "ancre")
    _exiger(ancre["intervention_id"] == intervention, "ancre : intervention différente")
    _exiger(
        all(_hash(ancre[k]) for k in ("plan_id", "source_application_id", "source_ligne_id")),
        "ancre : référence invalide",
    )
    _exiger(_texte(v["equipe_planifiee_id"]) and _texte(v["identifiant_pointe"]), "équipe ou pointage absent")
    equipe = _objet(v["equipe_pointee"], {"statut", "identifiant", "justification"}, "équipe pointée")
    _exiger(
        equipe == {"statut": "inconnue", "identifiant": None, "justification": "indeterminee"},
        "V2 ne prouve pas le type de l'identifiant pointé ; équipe inconnue requise",
    )
    equipe_connue = False
    debut = _maillon(v["ouverture"], "ouverture")
    fin = _maillon(v["fermeture"], "fermeture")
    evenements = v["evenements"]
    _exiger(isinstance(evenements, list) and 3 <= len(evenements) <= 10000, "événements absents ou hors limites")
    ordre, instants = [], []
    for evenement in evenements:
        e = _objet(evenement, {"type", "source_ligne_id", "horodatage", "revue_gps"}, "événement")
        _exiger(_hash(e["source_ligne_id"]), "événement : référence invalide")
        typ = e["type"]
        _exiger(typ in {"en_route", "arrivee", "pause_debut", "pause_fin", "depart"}, "événement : type invalide")
        ordre.append(typ)
        instants.append(_instant(e["horodatage"]))
        gps = e["revue_gps"]
        if typ in {"arrivee", "depart"}:
            gps = _objet(gps, {"statut", "demande_ligne_id", "resolution_ligne_id"}, "revue GPS")
            _exiger(
                (gps["statut"] == "coherent" and gps["demande_ligne_id"] is None and gps["resolution_ligne_id"] is None)
                or (
                    gps["statut"] == "validee" and _hash(gps["demande_ligne_id"]) and _hash(gps["resolution_ligne_id"])
                ),
                "revue GPS non validée",
            )
        else:
            _exiger(gps is None, "revue GPS inattendue")
    _exiger(ordre[:2] == ["en_route", "arrivee"] and ordre[-1] == "depart", "séquence route-arrivée-départ invalide")
    phase = "presence"
    nombre_pauses = 0
    for i, action in enumerate(ordre[2:], 2):
        if action == "pause_debut" and phase == "presence":
            phase = "pause"
            nombre_pauses += 1
        elif action == "pause_fin" and phase == "pause":
            _exiger(instants[i - 1] < instants[i], "pause vide")
            phase = "presence"
        elif action == "depart" and phase == "presence":
            phase = "fermee"
        elif action == "depart" and phase == "fermee":
            _exiger(evenements[i]["revue_gps"]["statut"] == "validee", "départ supplémentaire non arbitré")
        else:
            raise _Invalide("séquence de pause ou départ invalide")
    _exiger(phase == "fermee" and nombre_pauses <= 100, "pauses invalides ou visite non fermée")
    _exiger(
        debut <= instants[0]
        and all(a <= b for a, b in zip(instants, instants[1:], strict=False))
        and instants[-1] <= fin,
        "chronologie invalide",
    )
    comp = _objet(
        v["composition_declaree"],
        {"statut", "jour", "equipe_id", "source_ligne_id", "revision", "horodatage", "membres"},
        "composition",
    )
    try:
        _exiger(
            type(comp["jour"]) is str and date.fromisoformat(comp["jour"]).isoformat() == comp["jour"],
            "jour de composition invalide",
        )
    except ValueError:
        raise _Invalide("jour de composition invalide") from None
    _exiger(comp["equipe_id"] == v["equipe_planifiee_id"], "composition : équipe différente")
    statut = comp["statut"]
    if statut == "inconnue":
        _exiger(
            all(comp[k] is None for k in ("source_ligne_id", "revision", "horodatage", "membres")),
            "composition inconnue incohérente",
        )
    elif statut in {"declaree", "retiree"}:
        _exiger(
            _hash(comp["source_ligne_id"]) and type(comp["revision"]) is int and comp["revision"] > 0,
            "composition : source invalide",
        )
        _instant(comp["horodatage"])
        _exiger(
            (statut == "retiree" and comp["membres"] is None)
            or (
                statut == "declaree"
                and isinstance(comp["membres"], list)
                and len(comp["membres"]) <= 50
                and all(_texte(m) for m in comp["membres"])
            ),
            "composition : membres invalides",
        )
    else:
        raise _Invalide("composition : statut invalide")
    _exiger(v["presence_individuelle"] == {"statut": "inconnue"}, "présence individuelle non établie")
    minutes = _objet(v["minutes"], {"travail", "pause", "deplacement"}, "minutes")
    _exiger(all(_minute(n) for n in minutes.values()), "minutes invalides")
    _exiger(
        (minutes["travail"] + minutes["pause"]) * 60 <= (instants[-1] - instants[1]).total_seconds()
        and minutes["deplacement"] * 60 <= (instants[1] - instants[0]).total_seconds(),
        "minutes hors des bornes temporelles des faits",
    )
    inconnus = [{"code": "presence_individuelle_non_observee", "visite_id": ident}]
    if statut != "declaree":
        inconnus.append({"code": "composition_indisponible", "visite_id": ident})
    if not equipe_connue:
        inconnus.append({"code": "equipe_pointee_indeterminee", "visite_id": ident})
    return (instants[0], ident, instants[-1]), minutes, inconnus, equipe_connue


def valider_projection(
    projection: Any,
    *,
    instance_id: Any,
    wct_id: Any,
    source_attendue: Any,
    sources_actuelles: Any,
) -> dict[str, Any]:
    """Valide le contrat et son CAS ; l'autorité des arguments relève de l'appelant.

    ``valide`` concerne la structure, références, empreinte et fraîcheur comparée.
    ``exploitable`` exige en plus une revue finale et des équipes identifiées ;
    il ne dispense pas de vérifier les taux ni la provenance de l'appel au port M4.
    """
    try:
        _json_strict(projection)
        _exiger(
            len(json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 65536,
            "projection supérieure à 65536 octets",
        )
        p = _objet(projection, _CHAMPS, "projection")
        _exiger(p["version"] == _VERSION, "version non prise en charge")
        _exiger(_texte(instance_id) and p["instance_id"] == instance_id, "instance différente")
        _exiger(_texte(p["intervention_id"]) and _texte(p["lead_id"]), "identités absentes")
        _exiger(p["chantier_id"] is None or _texte(p["chantier_id"]), "chantier invalide")
        w = _objet(
            p["wct"],
            {
                "wct_id",
                "source_ligne_id",
                "hash_maillon",
                "horodatage_transition",
                "horodatage_completion",
                "statut",
                "duree_reelle_minutes",
            },
            "WCT",
        )
        _exiger(_texte(wct_id) and w["wct_id"] == wct_id, "WCT différent")
        _exiger(_hash(w["source_ligne_id"]) and _hash(w["hash_maillon"]), "WCT : références invalides")
        _instant(w["horodatage_transition"])
        completion = _instant(w["horodatage_completion"])
        _exiger(
            w["statut"] in {"completed_pending_review", "completed_verified"} and _minute(w["duree_reelle_minutes"]),
            "WCT non terminé ou durée invalide",
        )
        sources = _objet(p["sources"], {"principal", "visites", "compositions"}, "sources")
        for nom, s in sources.items():
            s = _objet(s, {"tete", "empreinte_snapshot"}, nom)
            _exiger(
                (s["tete"] is None or _hash(s["tete"])) and _hash(s["empreinte_snapshot"]), f"source {nom} invalide"
            )
        _exiger(sources == sources_actuelles, "sources périmées ou absentes")
        cas = encodage.empreinte(
            "m4.temps_certifies.cas.v2",
            instance_id,
            wct_id,
            *(sources[k]["empreinte_snapshot"] for k in ("principal", "visites", "compositions")),
        )
        _exiger(_hash(source_attendue) and source_attendue == cas, "source CAS périmée ou absente")
        empreinte = encodage.empreinte("m4.temps_certifies.v2", {k: v for k, v in p.items() if k != "empreinte"})
        _exiger(_hash(p["empreinte"]) and p["empreinte"] == empreinte, "empreinte incorrecte")
        visites = p["visites"]
        _exiger(type(visites) is list and 0 < len(visites) <= 1000, "visites absentes ou hors limites")
        controle = [_controle_visite(v, p["intervention_id"]) for v in visites]
        cles = [c[0] for c in controle]
        _exiger(cles == sorted(cles) and len({c[1] for c in cles}) == len(cles), "ordre ou doublon de visite")
        _exiger(all(a[2] <= b[0] for a, b in zip(cles, cles[1:], strict=False)), "visites chevauchées")
        _exiger(cles[-1][2] == completion, "complétion différente du dernier départ")
        totaux = _objet(p["totaux"], {"travail", "pause", "deplacement"}, "totaux")
        _exiger(
            all(_minute(n) for n in totaux.values())
            and all(totaux[k] == sum(c[1][k] for c in controle) for k in totaux)
            and totaux["travail"] == w["duree_reelle_minutes"],
            "totaux incompatibles",
        )
        revue = _objet(p["revue_chantier"], {"statut", "source_ligne_id"}, "revue chantier")
        _exiger(
            revue["statut"] in {"en_attente", "verifiee"} and _hash(revue["source_ligne_id"]), "revue chantier invalide"
        )
        inconnus = [{"code": "chantier_id_indisponible", "visite_id": None}] if p["chantier_id"] is None else []
        for c in controle:
            inconnus.extend(c[2])
        _exiger(p["inconnus"] == inconnus, "inconnus incomplets, invalides ou désordonnés")
        raisons = []
        if revue["statut"] != "verifiee":
            raisons.append("revue du chantier en attente")
        if not all(c[3] for c in controle):
            raisons.append("équipe pointée indéterminée")
        return {"valide": True, "exploitable": not raisons, "raisons": raisons}
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        return {"valide": False, "exploitable": False, "raisons": [str(exc)]}
