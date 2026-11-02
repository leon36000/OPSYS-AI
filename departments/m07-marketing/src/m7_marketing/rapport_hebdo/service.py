"""Persistance du rapport marketing hebdomadaire : un rapport par semaine, ses tâches internes et ses observations de
mémoire.

Tout se fait dans UNE transaction (celle de l'appelant) : le rapport, ses tâches et les observations annoncées au bus
(`m7.apprentissage_marketing_constate`) sont écrits ensemble ou pas du tout.

  - **Idempotent par semaine.** Un rapport existe par lundi : le redire (même semaine, mêmes entrées ou non) ne
  réécrit rien,
    ne recrée aucune tâche et n'annonce rien de plus. Le premier rapport d'une semaine fait foi.
  - **Aucun effet externe.** Ni publication, ni dépense, ni courriel, ni SMS. Les tâches sont des lignes internes de
  niveau bas
    (N1) montrées dans « À voir » ; elles ne s'exécutent pas seules.
  - **Minimal.** Le rapport garde des comptes, des clés de mesure et des identifiants de mesure ; aucun texte de client.

Registres (append-only, M7) : `rapports_hebdomadaires`, `taches_marketing`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from opsys import evenements, stockage

from . import composition, memoire, recommandations, semaine

DEPARTEMENT = "m07-marketing"
REGISTRE_RAPPORTS = (DEPARTEMENT, "rapports_hebdomadaires")
REGISTRE_TACHES = (DEPARTEMENT, "taches_marketing")
RAPPORT_MAX_OCTETS = 60_000
RAPPORTS_MAX_LUS = 600
STATUT_ENREGISTRE = "enregistre"
STATUT_DEJA = "deja_present"
STATUT_REFUSE = "refuse"
NIVEAU_TACHE = "N1"


def _lire(registre: tuple[str, str]) -> list[dict[str, Any]]:
    maillons = list(stockage.maillons(*registre))
    if len(maillons) > RAPPORTS_MAX_LUS * 20:
        raise ValueError("REJ-RAPPORT-REGISTRE-HORS-BORNE")
    return maillons


def rapport_de(debut: str) -> dict[str, Any] | None:
    return next(
        (m for m in _lire(REGISTRE_RAPPORTS) if m.get("type") == "rapport_hebdo" and m.get("semaine") == debut), None
    )


def tache_id(debut: str, recommandation_id: str) -> str:
    return "tm-" + hashlib.sha256(f"{debut}|{recommandation_id}".encode()).hexdigest()[:20]


def constater(entrees: dict[str, Any], debut: str, horodatage: str) -> dict[str, Any]:
    """Compose, enregistre (une fois par semaine), crée les tâches et annonce les observations. Idempotent.

    `debut` est le lundi de la semaine. `horodatage` est l'instant du serveur (ISO 8601 avec fuseau) fourni par
    l'appelant
    (l'horloge du planificateur) : jamais lu ici."""
    try:
        lundi, _ = semaine.semaine_de(debut)
    except ValueError as exc:
        return {"statut": STATUT_REFUSE, "code": "REJ-RAPPORT-SEMAINE-INVALIDE", "detail": str(exc)}
    existant = rapport_de(lundi.isoformat())
    if existant is not None:
        return {"statut": STATUT_DEJA, "semaine": lundi.isoformat(), "empreinte": existant["empreinte"]}
    rapport = composition.composer(entrees, lundi.isoformat())
    liaison = recommandations.verifier_liaison(rapport)
    if liaison:  # ne devrait jamais arriver : le code construit des recommandations liées
        return {"statut": STATUT_REFUSE, "code": "REJ-RAPPORT-RECOMMANDATION-NON-LIEE", "detail": liaison[0]}
    if len(json.dumps(rapport, ensure_ascii=False).encode("utf-8")) > RAPPORT_MAX_OCTETS:
        return {
            "statut": STATUT_REFUSE,
            "code": "REJ-RAPPORT-TROP-GROS",
            "detail": f"plus de {RAPPORT_MAX_OCTETS} octets",
        }
    taches = [
        {
            "type": "tache_marketing",
            "tache_id": tache_id(rapport["semaine"]["debut"], r["id"]),
            "semaine": rapport["semaine"]["debut"],
            "recommandation_id": r["id"],
            "regle": r["regle"],
            "resume": r["action"][:300],
            "priorite": r["priorite"],
            "hypothese": r["hypothese"],
            "niveau": NIVEAU_TACHE,
            "cree_le": horodatage,
        }
        for r in rapport["recommandations"]
        if r["tache"]
    ]
    rapports = stockage.maillons(*REGISTRE_RAPPORTS)
    rapports.append(
        {
            "type": "rapport_hebdo",
            "semaine": rapport["semaine"]["debut"],
            "empreinte": rapport["empreinte"],
            "cree_le": horodatage,
            "rapport": rapport,
        }
    )
    registre_taches = stockage.maillons(*REGISTRE_TACHES)
    for tache in taches:
        registre_taches.append(tache)
    publiees = 0
    for observation in memoire.observations(rapport):
        evenements.publier(memoire.TYPE_EVENEMENT, DEPARTEMENT, observation, evenement_id=observation["observation_id"])
        publiees += 1
    return {
        "statut": STATUT_ENREGISTRE,
        "semaine": rapport["semaine"]["debut"],
        "empreinte": rapport["empreinte"],
        "recommandations": len(rapport["recommandations"]),
        "taches": len(taches),
        "observations_annoncees": publiees,
    }


def lire(debut: str | None = None) -> dict[str, Any]:
    """Le rapport de la semaine `debut`, ou le plus récent ; `statut: aucun_rapport` sinon (jamais un rapport
    inventé)."""
    maillons = [m for m in _lire(REGISTRE_RAPPORTS) if m.get("type") == "rapport_hebdo"]
    if debut is not None:
        maillons = [m for m in maillons if m.get("semaine") == debut]
    if not maillons:
        return {"statut": "aucun_rapport", "semaine": debut}
    dernier = max(maillons, key=lambda m: m["semaine"])
    return {
        "statut": "rapport",
        "semaine": dernier["semaine"],
        "cree_le": dernier["cree_le"],
        "rapport": dernier["rapport"],
    }


def taches_courantes() -> list[dict[str, Any]]:
    """Les tâches du rapport le plus récent seulement : une tâche ne survit pas au rapport de la semaine suivante."""
    taches = [t for t in _lire(REGISTRE_TACHES) if t.get("type") == "tache_marketing"]
    if not taches:
        return []
    derniere = max(t["semaine"] for t in taches)
    return sorted((t for t in taches if t["semaine"] == derniere), key=lambda t: (-t["priorite"], t["tache_id"]))
