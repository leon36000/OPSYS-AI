"""Observations Growth sourcées et plans déterministes sur 30 jours."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Any

from opsys import stockage

DEPARTEMENT = "m07-marketing"
REGISTRE = "growth"


def _empreinte(donnees: dict[str, Any]) -> str:
    canon = json.dumps(donnees, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def enregistrer_observation(
    observation_id: str,
    metrique: str,
    valeur: float,
    unite: str,
    debut: str,
    fin: str,
    plateforme: str,
    campagne: str,
    source: str,
    preuve: str,
    confiance: float,
) -> dict[str, Any]:
    if not observation_id.strip() or not source.strip() or not preuve.strip() or not metrique.strip():
        return {"statut": "donnee_invalide", "motif": "id, métrique, source et référence de preuve requis"}
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not math.isfinite(valeur):
        return {"statut": "donnee_invalide", "motif": "valeur numérique finie requise"}
    if (
        not isinstance(confiance, (int, float))
        or isinstance(confiance, bool)
        or not math.isfinite(confiance)
        or not 0 <= confiance <= 1
    ):
        return {"statut": "donnee_invalide", "motif": "confiance entre 0 et 1 requise"}
    try:
        debut_date = dt.date.fromisoformat(debut)
        fin_date = dt.date.fromisoformat(fin)
    except (TypeError, ValueError):
        return {"statut": "donnee_invalide", "motif": "périodes ISO 8601 (AAAA-MM-JJ) requises"}
    if not unite.strip() or fin_date < debut_date or not plateforme.strip() or not campagne.strip():
        return {"statut": "donnee_invalide", "motif": "période, unité, plateforme et campagne requis"}
    charge = {
        "observation_id": observation_id,
        "metrique": metrique,
        "valeur": float(valeur),
        "unite": unite,
        "periode": {"debut": debut, "fin": fin},
        "plateforme": plateforme,
        "campagne": campagne,
        "source": source,
        "preuve": preuve,
        "confiance": float(confiance),
    }
    fp = _empreinte(charge)
    registre = stockage.maillons(DEPARTEMENT, REGISTRE)
    deja = next(
        (m for m in registre if m.get("type") == "observation" and m.get("observation_id") == observation_id), None
    )
    if deja:
        if deja["empreinte"] == fp:
            return {"statut": "deja_enregistre", "observation": deja}
        return {"statut": "conflit", "motif": "observation_id déjà utilisé avec une charge différente"}
    maillon = {"type": "observation", **charge, "empreinte": fp}
    registre.append(maillon)
    return {"statut": "enregistre", "observation": maillon}


def plan_30j(horizon: str) -> dict[str, Any]:
    try:
        dt.date.fromisoformat(horizon)
    except (TypeError, ValueError):
        return {"statut": "horizon_invalide", "motif": "date ISO 8601 (AAAA-MM-JJ) requise"}
    observations = [m for m in stockage.maillons(DEPARTEMENT, REGISTRE) if m.get("type") == "observation"]
    groupes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for obs in observations:
        groupes.setdefault((obs["plateforme"], obs["campagne"]), []).append(obs)
    recommandations = []
    for (plateforme, campagne), items in sorted(groupes.items()):
        noms = sorted({x["metrique"] for x in items})
        recommandations.append(
            {
                "plateforme": plateforme,
                "campagne": campagne,
                "action": "poursuivre la mesure avec les mêmes définitions sur les 30 prochains jours",
                "observations_source": sorted(x["observation_id"] for x in items),
                "hypotheses": ["les observations fournies décrivent la période passée, sans inférence causale"],
                "donnees_manquantes": [
                    "objectif métier",
                    "coûts complets",
                    "conversion CRM vérifiée",
                    "comparaison contrôlée",
                ],
                "metriques_observees": noms,
            }
        )
    plan = {
        "type": "plan_growth_30j",
        "horizon_debut": horizon,
        "recommandations": recommandations,
        "donnees_manquantes": [] if observations else ["observations sourcées de performance"],
        "limites": ["aucune causalité, projection de volume ni ROI calculé"],
    }
    stockage.maillons(DEPARTEMENT, REGISTRE).append(plan)
    return {"statut": "plan_genere", **plan}


def enregistrer_observation_humaine(
    arguments: dict[str, Any], *, rang_attendu: int, empreinte_attendue: str, horodatage: str,
) -> dict[str, Any]:
    """Port privé de la console : aucune exposition au catalogue d'outils agent.

    La phase humaine est créée par metier, jamais déduite par le writer legacy.
    La provenance identifie la saisie, pas la vérité de la statistique ni de sa source.
    """
    from opsys import contexte, identite
    from opsys.stockage import codec

    from . import growth_lecture as lecture

    cnx = stockage.connexion_courante()
    appelant = contexte.identite_appelante()
    if (cnx is None or cnx.engine.dialect.name != "sqlite" or appelant is None
            or appelant.source != "console" or contexte.departement_origine_appelante() != "console"):
        raise PermissionError("saisie humaine Growth réservée au port console SQLite")
    personne = identite.personne_active(cnx, appelant.personne)
    if personne is None or appelant.role not in personne.roles or appelant.role not in {"admin", "nathan_owner"}:
        raise PermissionError("autorité humaine Growth retirée")
    attendus = {
        "observation_id", "metrique", "valeur", "unite", "debut", "fin", "plateforme", "campagne",
        "source", "preuve", "confiance",
    }
    if not isinstance(arguments, dict) or set(arguments) != attendus:
        raise ValueError("GROWTH-ARGUMENTS-INVALIDES")
    if (type(rang_attendu) is not int or not 0 <= rang_attendu <= lecture.LIMITE_MAILLONS
            or not isinstance(empreinte_attendue, str) or len(empreinte_attendue) != 64
            or any(c not in "0123456789abcdef" for c in empreinte_attendue)):
        raise ValueError("GROWTH-TETE-INVALIDE")
    charge = {k: v for k, v in arguments.items() if k not in {"debut", "fin"}}
    charge["periode"] = {"debut": arguments["debut"], "fin": arguments["fin"]}
    charge.update(schema_version=2, provenance={
        "mode": "saisie_humaine_console", "auteur": personne.identifiant,
        "role": appelant.role, "horodatage": horodatage,
    })
    maillon = {"type": "observation", **charge, "empreinte": _empreinte(charge)}
    lecture._valider_observation(maillon)
    debut = dt.date.fromisoformat(arguments["debut"])
    fin = dt.date.fromisoformat(arguments["fin"])
    if (fin - debut).days >= lecture.LIMITE_JOURS_PERIODE:
        raise ValueError("GROWTH-PERIODE-TROP-LONGUE")
    textes, tete = lecture.lire_prefixe(cnx)
    observations = lecture.decoder_prefixe(textes)
    if any(o["observation_id"] == arguments["observation_id"] for o in observations):
        raise ValueError("GROWTH-ID-DEJA-UTILISE")
    if tete != {"rang": rang_attendu, "empreinte": empreinte_attendue}:
        raise ValueError("GROWTH-TETE-PERIMEE")
    taille = len(codec.encoder(maillon))
    lecture._verifier_bornes_sql(len(textes) + 1, sum(map(len, textes)) + taille, taille)
    # Relecture sur la transaction canonique immédiatement avant l'effet.
    personne = identite.personne_active(cnx, appelant.personne)
    if personne is None or appelant.role not in personne.roles:
        raise PermissionError("autorité humaine Growth retirée")
    stockage.maillons(DEPARTEMENT, REGISTRE).append(maillon, rang_attendu=rang_attendu)
    return {"ok": True, "statut": "enregistre", "observation": maillon,
            "statut_source": "DECLAREE_NON_VERIFIEE", "verification_externe": None}
