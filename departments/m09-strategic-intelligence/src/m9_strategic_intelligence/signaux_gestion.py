"""Les signaux de gestion que M7 et M8 disent à M9 par le bus (interconnexion M7 -> M9 et M8 -> M9).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (``maintenant`` vient de l'appelant). ``outils.py``,
seul point de contact avec le socle, reçoit les événements, range les faits au registre ``signaux_gestion_recus`` et
ajoute la section ``signaux_de_gestion`` au briefing du matin, APRÈS l'assemblage du briefing de base.

Deux sources, deux sens :

- ``m7.anomalie_depense_detectee`` : une règle TRANSPARENTE de dépense publicitaire s'est déclenchée (plafond quotidien,
  dépense sans conversion, saut, dépense hors plan, trou de données). M7 ne propose ni n'exécute aucune action ; M9 ne
  décide rien non plus : il LIT et met l'anomalie devant le propriétaire, la plus grave d'abord ;
- ``m8.fait_consolide`` : la consolidation des mesures d'entreprise de M8 (valeur exacte en texte, statut de fraîcheur,
  changements de définition, anomalies). M9 en garde le RÉSUMÉ (combien de mesures calculées, lesquelles ne le sont pas
  ou sont périmées, quelles définitions ont changé) et pas les valeurs : les chiffres se relisent chez M8, leur
  propriétaire, par ``m8_lire_vue_executive`` ; M9 ne les recopie ni ne les recalcule.

Idempotence : une clé de CONTENU par fait (``anomalie_id``, ou l'empreinte des registres de M8 avec la version du
catalogue). Le même constat rejoué sous un autre ``evenement_id`` n'écrit rien.

Section du briefing : les anomalies dont le dernier jour tombe dans la fenêtre des alertes (comme les alertes de M8),
les
plus graves d'abord, au plus ``ANOMALIES_AFFICHEES`` ; le DERNIER fait consolidé reçu. Sans rien, la section est absente
du briefing (jamais une section vide qui laisserait croire à « tout va bien » : le briefing dit déjà ce qu'il n'a pas
reçu).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

REGISTRE = "signaux_gestion_recus"
TYPE_ANOMALIE = "anomalie_depense_m7"
TYPE_CONSOLIDATION = "consolidation_m8"
ANOMALIES_AFFICHEES = 5
IDS_AFFICHES = 8
_ORDRE_SEVERITE = {"critique": 0, "attention": 1, "info": 2}


def fait_anomalie(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {"type_entree": TYPE_ANOMALIE, **charge}


def fait_consolidation(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Le RÉSUMÉ d'une consolidation de M8 : des comptes et des identifiants de mesure, aucune valeur."""
    mesures = charge["mesures"]
    return {
        "type_entree": TYPE_CONSOLIDATION,
        "evenement_source": charge["evenement_id"],
        "consolide_le": charge["consolide_le"],
        "empreinte_registres": charge["empreinte_registres"],
        "version_catalogue": charge["version_catalogue"],
        "premiere_consolidation": charge["premiere_consolidation"],
        "mesures": len(mesures),
        "calculees": sum(1 for m in mesures if m["statut"] == "calculee"),
        "non_calculables": sorted(m["metric_id"] for m in mesures if m["statut"] == "non_calculable"),
        "perimees": sorted(m["metric_id"] for m in mesures if m["fraicheur"] == "perime"),
        "changements_definition": sorted(c["metric_id"] for c in charge["changements_definition"]),
        "anomalies": sorted((a["metric_id"], a["type"]) for a in charge["anomalies"]),
        "mention": charge["mention"],
    }


CLES_UNICITE = {
    TYPE_ANOMALIE: ("anomalie_id",),
    TYPE_CONSOLIDATION: ("empreinte_registres", "version_catalogue"),
}


def _jour(texte: str) -> date | None:
    try:
        return datetime.fromisoformat(texte).date()
    except (TypeError, ValueError):
        return None


_PLUS_ANCIEN = datetime.min.replace(tzinfo=UTC)


def _instant(texte: Any) -> datetime:
    """L'instant d'un texte ISO AVEC fuseau (comparé comme un instant, jamais comme du texte : `01:30-04:00` précède
    `01:10-05:00` au changement d'heure d'automne) ; un texte illisible ou sans fuseau passe avant tous les autres."""
    try:
        instant = datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return _PLUS_ANCIEN
    return instant if instant.tzinfo is not None else _PLUS_ANCIEN


def section(signaux: Iterable[Mapping[str, Any]], maintenant: str, fenetre_jours: int) -> dict[str, Any] | None:
    """La section ``signaux_de_gestion`` du briefing, ou ``None`` s'il n'y a rien à dire."""
    jour = _jour(maintenant)
    if jour is None:
        return None
    debut = jour - timedelta(days=fenetre_jours)
    anomalies = []
    consolidations = []
    for s in signaux:
        if s.get("type_entree") == TYPE_ANOMALIE and not s.get("fictif"):
            fin = _jour(s["jour_fin"])
            if fin is not None and debut <= fin <= jour:
                anomalies.append(s)
        elif s.get("type_entree") == TYPE_CONSOLIDATION:
            consolidations.append(s)
    anomalies.sort(key=lambda s: (_ORDRE_SEVERITE.get(s["severite"], 9), s["jour_fin"], s["anomalie_id"]))
    if not anomalies and not consolidations:
        return None
    resultat: dict[str, Any] = {
        "source": "M7 (m7.anomalie_depense_detectee) et M8 (m8.fait_consolide), par le bus ; M9 lit, ne décide pas",
        "anomalies_depense": {
            "total": len(anomalies),
            "affichees": [
                {
                    "anomalie_id": s["anomalie_id"],
                    "canal": s["canal"],
                    "regle": s["regle"],
                    "severite": s["severite"],
                    "valeur": s["valeur"],
                    "seuil": s["seuil"],
                    "unite": s["unite"],
                    "jour_fin": s["jour_fin"],
                }
                for s in anomalies[:ANOMALIES_AFFICHEES]
            ],
            "reste": max(0, len(anomalies) - ANOMALIES_AFFICHEES),
            "action": "aucune : M7 ne propose ni n'exécute rien, une pause éventuelle est une décision humaine",
        },
    }
    if consolidations:
        d = max(range(len(consolidations)), key=lambda i: (_instant(consolidations[i]["consolide_le"]), i))
        dernier = consolidations[d]
        resultat["derniere_consolidation_m8"] = {
            "consolide_le": dernier["consolide_le"],
            "mesures": dernier["mesures"],
            "calculees": dernier["calculees"],
            "non_calculables": dernier["non_calculables"][:IDS_AFFICHES],
            "perimees": dernier["perimees"][:IDS_AFFICHES],
            "changements_definition": dernier["changements_definition"][:IDS_AFFICHES],
            "anomalies": len(dernier["anomalies"]),
            "valeurs": "à relire chez M8 (m8_lire_vue_executive) : M9 ne les recopie pas",
            "mention": dernier["mention"],
        }
    return resultat
