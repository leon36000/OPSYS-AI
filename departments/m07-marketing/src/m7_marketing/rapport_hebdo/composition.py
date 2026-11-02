"""Composition du rapport marketing hebdomadaire (boucle B) : des entrées déjà calculées par leurs propriétaires →
des sections.

Doctrine :

  - **Le code calcule, rien d'autre.** Ce module ne lit rien (aucun registre, aucun outil, aucune horloge) : il
  COMPOSE des
    entrées fournies par l'appelant (les mesures de l'entrepôt de M8, la performance des campagnes de M7, la
    réputation, la
    croissance déclarée, le calendrier). Il ne recalcule JAMAIS la finance : la marge constatée vient de M5 (telle que
    M7 l'a
    reçue), la dépense comptabilisée et le coût par lead viennent des mesures de M8. Le seul calcul est un rapport de
    comptes
    entiers (conversion), jamais un montant.
  - **Jamais un zéro inventé.** Une source absente, illisible ou périmée donne une section `source_absente` ou
    `donnees_insuffisantes` qui dit CE QUI MANQUE ; un classement n'est tenté qu'avec assez de données (`SEUILS`).
  - **Sourcé.** Chaque section nomme ses sources ; `references` liste les identifiants (mesures, contenus, observations)
    sur lesquels le rapport s'appuie, pour que chaque recommandation y soit rattachée (`recommandations`).
  - **Déterministe.** Mêmes entrées, même rapport, même empreinte.

Module pur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import croissance, recommandations, semaine

VERSION = "rapport-hebdo/v1"
MENTION = (
    "Rapport d'analyse interne, déterministe. Les montants viennent de M5 et de M8 tels quels ; aucun ROI n'est "
    "calculé ici. "
    "À valider auprès d'un comptable (CPA) / professionnel qualifié pour toute décision financière."
)
SEUILS = {
    "leads_conversion_min": 5,  # sous ce nombre de leads, aucun taux de conversion
    "contenus_mesurables_min": 3,  # sous ce nombre, aucun classement meilleurs/pires contenus
    "jours_avant_contenu_faible": 14,  # un contenu sans lead n'est « faible » qu'après ce délai depuis son export
    "contenus_classes": 3,
    "series_croissance_max": 12,
}
MESURES_M8 = (
    "m8_leads_recus",
    "m8_devis_envoyes",
    "m8_devis_acceptes",
    "m8_taux_acceptation_pct",
    "m8_leads_publicitaires",
    "m8_cout_par_lead_pub_cad",
    "m8_depense_pub_comptabilisee_cad",
    "m8_clics_recherche",
    "m8_impressions_recherche",
    "m8_visites_site",
    "m8_conversions_hors_ligne",
    "m8_anomalies_depense_critiques",
)
STATUT_CALCULE = "calcule"
STATUT_INSUFFISANT = "donnees_insuffisantes"
STATUT_ABSENT = "source_absente"
SOURCES = ("m8_mesures", "m8_contenus", "performance", "reputation", "croissance", "calendrier")
_MAX_LIGNES = 2000


def _decimal(valeur: Any) -> Decimal | None:
    if isinstance(valeur, bool) or valeur is None:
        return None
    try:
        d = Decimal(str(valeur))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _entier(valeur: Any) -> int | None:
    return valeur if type(valeur) is int and valeur >= 0 else None


def _pct(numerateur: int, denominateur: int) -> str:
    return str((Decimal(numerateur) * 100 / Decimal(denominateur)).quantize(Decimal("1"), ROUND_HALF_UP))


def _instant(valeur: Any) -> dt.datetime | None:
    if not isinstance(valeur, str):
        return None
    try:
        i = dt.datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        return None
    return i if i.tzinfo is not None else None


def _liste_bornee(valeur: Any) -> list[dict[str, Any]] | None:
    if not isinstance(valeur, list) or len(valeur) > _MAX_LIGNES or not all(isinstance(x, dict) for x in valeur):
        return None
    return valeur


# -- sections --------------------------------------------------------------------------------------------------------
def _mesures_m8(mesures: list[dict[str, Any]] | None) -> dict[str, Any]:
    if mesures is None:
        return {"statut": STATUT_ABSENT, "manque": "mesures de l'entrepôt de M8 (m8_lire_mesures)", "mesures": {}}
    par_id = {m.get("metric_id"): m for m in mesures if isinstance(m.get("metric_id"), str)}
    lignes: dict[str, Any] = {}
    for metric_id in MESURES_M8:
        m = par_id.get(metric_id)
        if m is None:
            continue
        lignes[metric_id] = {
            "valeur": m.get("valeur") if isinstance(m.get("valeur"), str) else None,
            "unite": m.get("unite") if isinstance(m.get("unite"), str) else None,
            "statut": m.get("statut"),
            "fraicheur": m.get("fraicheur"),
            "couverture": m.get("couverture"),
            "a_jour": bool(m.get("a_jour")),
        }
    if not lignes:
        return {
            "statut": STATUT_INSUFFISANT,
            "manque": "aucune des mesures marketing attendues n'a été lue",
            "mesures": {},
        }
    return {"statut": STATUT_CALCULE, "mesures": lignes}


def _leads_par_canal(performance: dict[str, Any] | None) -> dict[str, Any]:
    if performance is None:
        return {"statut": STATUT_ABSENT, "manque": "performance des campagnes (leads de M2, devis de M3, marge de M5)"}
    campagnes = performance.get("campagnes")
    if not isinstance(campagnes, list) or not campagnes:
        return {
            "statut": STATUT_INSUFFISANT,
            "manque": "aucun lead attribué observé dans la semaine (ce n'est pas un zéro : le bus n'a rien livré ou "
            "rien n'a été attribué)",
        }
    canaux: dict[str, dict[str, Any]] = {}
    for ligne in campagnes:
        if not isinstance(ligne, dict):
            continue
        canal = ligne["source"] if isinstance(ligne.get("source"), str) and ligne["source"] else "inconnu"
        c = canaux.setdefault(
            canal,
            {
                "canal": canal,
                "leads": 0,
                "devis_acceptes": 0,
                "marge": Decimal(0),
                "marge_connue": False,
                "marge_manquante": False,
                "couvertures": set(),
                "manque": set(),
            },
        )
        c["leads"] += _entier(ligne.get("leads_associes_observes")) or 0
        c["devis_acceptes"] += _entier(ligne.get("devis_acceptes")) or 0
        marge = _decimal(ligne.get("marge_constatee_M5_cad"))
        if marge is not None:
            c["marge"] += marge
            c["marge_connue"] = True
        elif (_entier(ligne.get("devis_acceptes")) or 0) > 0:
            c["marge_manquante"] = True
        c["couvertures"].add(str(ligne.get("couverture")))
        c["manque"].update(x for x in ligne.get("manque", []) if isinstance(x, str))
    lignes = []
    for canal, c in canaux.items():
        lignes.append(
            {
                "canal": canal,
                "leads": c["leads"],
                "devis_acceptes": c["devis_acceptes"],
                "marge_constatee_m5_cad": format(c["marge"], "f") if c["marge_connue"] else None,
                "marge_somme_partielle": c["marge_connue"]
                and (c["marge_manquante"] or "SOMME_MARGES_CONNUES_SEULEMENT" in c["manque"]),
                "couverture": "complete" if c["couvertures"] == {"COMPLETE"} else "partielle",
                "manque": sorted(c["manque"])[:6],
            }
        )
    lignes.sort(key=lambda x: (-x["leads"], x["canal"]))
    return {"statut": STATUT_CALCULE, "canaux": lignes, "total_leads": sum(x["leads"] for x in lignes)}


def _cout_par_lead(mesures: dict[str, Any]) -> dict[str, Any]:
    if mesures["statut"] == STATUT_ABSENT:
        return {"statut": STATUT_ABSENT, "manque": mesures["manque"]}
    cout = mesures["mesures"].get("m8_cout_par_lead_pub_cad")
    leads = mesures["mesures"].get("m8_leads_publicitaires")
    base = {
        "cout_par_lead_pub_cad": cout,
        "leads_publicitaires": leads,
        "source": "M8 (relevés de dépense de M7 divisés par les leads de M2) ; jamais recalculé ici",
    }
    if cout is None or cout["statut"] != "calculee" or cout["valeur"] is None:
        return {
            "statut": STATUT_INSUFFISANT,
            **base,
            "manque": "coût par lead non calculable chez M8 (déclaration des canaux, relevés de dépense et leads "
            "rattachés requis)",
        }
    return {"statut": STATUT_CALCULE, **base}


def _conversion(contenus: list[dict[str, Any]] | None) -> dict[str, Any]:
    if contenus is None:
        return {"statut": STATUT_ABSENT, "manque": "mesure par contenu de M8 (leads et devis par utm_content)"}
    mesurables = [c for c in contenus if c.get("suivi") == "lien"]
    comptes = [(c.get("leads"), c.get("devis_envoyes"), c.get("devis_acceptes")) for c in mesurables]
    if (
        not mesurables
        or any(x is None for t in comptes for x in t)
        or any(_entier(x) is None for t in comptes for x in t)
    ):
        return {
            "statut": STATUT_INSUFFISANT,
            "manque": "aucun contenu mesurable avec ses comptes de leads et de devis (lien de suivi, leads de M1, "
            "devis de M3)",
        }
    leads = sum(t[0] for t in comptes)
    envoyes = sum(t[1] for t in comptes)
    acceptes = sum(t[2] for t in comptes)
    base = {
        "leads_attribues_aux_contenus": leads,
        "devis_envoyes": envoyes,
        "devis_acceptes": acceptes,
        "cumul": "depuis l'export de chaque contenu (M8 n'a pas de fenêtre de période)",
    }
    if leads < SEUILS["leads_conversion_min"]:
        return {
            "statut": STATUT_INSUFFISANT,
            **base,
            "manque": f"au moins {SEUILS['leads_conversion_min']} leads attribués pour un taux de conversion "
            f"({leads} actuellement)",
        }
    return {
        "statut": STATUT_CALCULE,
        **base,
        "lead_vers_devis_envoye_pct": _pct(envoyes, leads),
        "lead_vers_devis_accepte_pct": _pct(acceptes, leads),
    }


def _roi(performance: dict[str, Any] | None, leads_canal: dict[str, Any], mesures: dict[str, Any]) -> dict[str, Any]:
    marge = None
    if leads_canal.get("statut") == STATUT_CALCULE:
        marges = [Decimal(x["marge_constatee_m5_cad"]) for x in leads_canal["canaux"] if x["marge_constatee_m5_cad"]]
        marge = format(sum(marges, Decimal(0)), "f") if marges else None
    depense = mesures.get("mesures", {}).get("m8_depense_pub_comptabilisee_cad")
    return {
        "statut": STATUT_INSUFFISANT,
        "marge_constatee_m5_cad": marge,
        "depense_comptabilisee_m5_cad": depense["valeur"] if depense else None,
        "roi": None,
        "raison": "M7 ne recalcule pas la finance : la marge (chantiers à marge constatée par M5) et la dépense "
        "comptabilisée "
        "(M5, via M8) ne couvrent pas forcément les mêmes canaux ni la même période. Aucun ratio n'est publié "
        "sans alignement déclaré. À valider auprès d'un comptable (CPA) / professionnel qualifié.",
    }


def _croissance_engagement(observations: list[dict[str, Any]] | None) -> dict[str, Any]:
    if observations is None:
        return {"statut": STATUT_ABSENT, "manque": "observations de croissance et d'engagement déclarées"}
    series: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for obs in observations:
        periode = obs.get("periode")
        valeur = _decimal(obs.get("valeur"))
        if not isinstance(periode, dict) or valeur is None or not isinstance(obs.get("observation_id"), str):
            continue
        series.setdefault((str(obs.get("plateforme")), str(obs.get("metrique")), str(obs.get("campagne"))), []).append(
            {"id": obs["observation_id"], "fin": str(periode.get("fin")), "valeur": valeur, "unite": obs.get("unite")}
        )
    if not series:
        return {"statut": STATUT_INSUFFISANT, "manque": "aucune observation de croissance ou d'engagement saisie"}
    lignes = []
    for (plateforme, metrique, campagne), obs in series.items():
        obs.sort(key=lambda o: (o["fin"], o["id"]))
        dernier = obs[-1]
        ligne = {
            "plateforme": plateforme,
            "metrique": metrique,
            "campagne": campagne,
            "unite": dernier["unite"],
            "derniere_valeur": str(dernier["valeur"]),
            "observation_ids": [dernier["id"]],
            "variation": None,
        }
        if len(obs) >= 2:
            precedent = obs[-2]
            ligne["observation_ids"].insert(0, precedent["id"])
            difference = dernier["valeur"] - precedent["valeur"]
            ligne["variation"] = {
                "difference": str(difference),
                "pct": None
                if precedent["valeur"] == 0
                else str((difference * 100 / precedent["valeur"]).quantize(Decimal("1"), ROUND_HALF_UP)),
            }
        lignes.append((dernier["fin"], plateforme, metrique, campagne, ligne))
    lignes.sort(key=lambda t: (t[0], t[1], t[2], t[3]), reverse=True)
    return {"statut": STATUT_CALCULE, "series": [t[4] for t in lignes[: SEUILS["series_croissance_max"]]]}


def _contenus(contenus: list[dict[str, Any]] | None, fin: dt.date) -> dict[str, Any]:
    if contenus is None:
        return {"statut": STATUT_ABSENT, "manque": "mesure par contenu de M8"}
    suivis = {"lien": 0, "sans_lien": 0, "ambigu": 0}
    for c in contenus:
        suivis[c.get("suivi") if c.get("suivi") in suivis else "sans_lien"] += 1
    base = {
        "exportes": len(contenus),
        "mesurables": suivis["lien"],
        "sans_lien_de_suivi": suivis["sans_lien"],
        "cle_ambigue": suivis["ambigu"],
        "sans_lien_ids": sorted(
            str(c.get("utm_content"))
            for c in contenus
            if c.get("suivi") != "lien" and isinstance(c.get("utm_content"), str)
        )[:5],
    }
    mesurables = [c for c in contenus if c.get("suivi") == "lien" and _entier(c.get("leads")) is not None]
    if len(mesurables) < SEUILS["contenus_mesurables_min"]:
        return {
            "statut": STATUT_INSUFFISANT,
            **base,
            "manque": f"au moins {SEUILS['contenus_mesurables_min']} contenus mesurables pour un classement "
            f"({len(mesurables)} actuellement)",
        }

    def ligne(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "utm_content": c.get("utm_content"),
            "canal": c.get("canal"),
            "leads": c.get("leads"),
            "devis_envoyes": c.get("devis_envoyes"),
            "devis_acceptes": c.get("devis_acceptes"),
            "exporte_le": c.get("exporte_le"),
        }

    meilleurs = sorted(
        (c for c in mesurables if c["leads"] >= 1),
        key=lambda c: (
            -c["leads"],
            -(c.get("devis_acceptes") or 0),
            -(c.get("devis_envoyes") or 0),
            str(c.get("utm_content")),
        ),
    )[: SEUILS["contenus_classes"]]
    limite = dt.datetime.combine(fin, dt.time(23, 59, 59), tzinfo=dt.UTC) - dt.timedelta(
        days=SEUILS["jours_avant_contenu_faible"]
    )
    faibles = []
    for c in mesurables:
        exporte = _instant(c.get("exporte_le"))
        if c["leads"] == 0 and exporte is not None and exporte <= limite:
            faibles.append((exporte, str(c.get("utm_content")), c))
    faibles.sort(key=lambda t: (t[0], t[1]))
    return {
        "statut": STATUT_CALCULE,
        **base,
        "meilleurs": [ligne(c) for c in meilleurs],
        "faibles": [ligne(t[2]) for t in faibles[: SEUILS["contenus_classes"]]],
        "regle_faible": f"aucun lead attribué {SEUILS['jours_avant_contenu_faible']} jours après l'export",
    }


def _calendrier(calendrier: dict[str, Any] | None) -> dict[str, Any]:
    if calendrier is None:
        return {"statut": STATUT_ABSENT, "manque": "file de contenus et calendrier éditorial de M7"}
    cles = ("en_attente_de_decision", "approuves_non_exportes", "exportes_semaine", "creneaux_semaine")
    if not all(_entier(calendrier.get(c)) is not None for c in cles):
        return {"statut": STATUT_INSUFFISANT, "manque": "comptes du calendrier illisibles"}
    return {"statut": STATUT_CALCULE, **{c: calendrier[c] for c in cles}}


def _reputation(reputation: dict[str, Any] | None) -> dict[str, Any]:
    if reputation is None:
        return {"statut": STATUT_ABSENT, "manque": "avis importés (inbox de réputation de M7)"}
    total = _entier(reputation.get("avis_semaine"))
    if total is None:
        return {"statut": STATUT_INSUFFISANT, "manque": "comptes d'avis illisibles"}
    note = _decimal(reputation.get("note_moyenne_semaine"))
    return {
        "statut": STATUT_CALCULE,
        "avis_semaine": total,
        "note_moyenne_semaine": None if note is None else str(note.quantize(Decimal("0.01"), ROUND_HALF_UP)),
        "categories": {
            k: _entier(v) or 0
            for k, v in (reputation.get("categories") or {}).items()
            if k in ("litige", "urgence", "eloge", "neutre")
        },
        "sans_reponse": _entier(reputation.get("sans_reponse")) or 0,
        "negatifs_sans_reponse": _entier(reputation.get("negatifs_sans_reponse")) or 0,
        "note": "Les réponses publiques restent des décisions humaines ; la demande d'avis est envoyée à tous les "
        "clients "
        "consentants, jamais filtrée par la satisfaction.",
    }


def valider_entrees(entrees: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Les entrées normalisées et l'état de chaque source : `disponible`, `absente` ou `illisible`. Une source mal
    formée est
    traitée comme ABSENTE (le rapport le dit), jamais comme vide."""
    sortie: dict[str, Any] = {}
    etat: dict[str, str] = {}
    for nom in SOURCES:
        brut = entrees.get(nom)
        if brut is None:
            sortie[nom], etat[nom] = None, "absente"
        elif nom in ("performance", "calendrier", "reputation"):
            ok = isinstance(brut, dict)
            sortie[nom], etat[nom] = (brut if ok else None), ("disponible" if ok else "illisible")
        else:
            liste = _liste_bornee(brut)
            sortie[nom], etat[nom] = liste, ("disponible" if liste is not None else "illisible")
    return sortie, etat


def composer(entrees: dict[str, Any], debut: str) -> dict[str, Any]:
    """Le rapport de la semaine commençant le lundi `debut` (AAAA-MM-JJ). `ValueError` si `debut` n'est pas un lundi."""
    lundi, dimanche = semaine.semaine_de(debut)
    sources, etat = valider_entrees(entrees)
    mesures = _mesures_m8(sources["m8_mesures"])
    leads = _leads_par_canal(sources["performance"])
    conversion = _conversion(sources["m8_contenus"])
    contenus = _contenus(sources["m8_contenus"], dimanche)
    croissance_obs = _croissance_engagement(sources["croissance"])
    plan = croissance.analyser(sources["croissance"] or [])
    rapport: dict[str, Any] = {
        "type": "RAPPORT_HEBDOMADAIRE",
        "version": VERSION,
        "semaine": {"debut": lundi.isoformat(), "fin": dimanche.isoformat()},
        "sources": etat,
        "mesures_m8": mesures,
        "leads_par_canal": leads,
        "cout_par_lead": _cout_par_lead(mesures),
        "conversion": conversion,
        "roi": _roi(sources["performance"], leads, mesures),
        "croissance_engagement": croissance_obs,
        "contenus": contenus,
        "calendrier": _calendrier(sources["calendrier"]),
        "reputation": _reputation(sources["reputation"]),
        "plan_croissance": plan,
        "references": _references(sources),
        "mention": MENTION,
    }
    rapport["recommandations"] = recommandations.deriver(rapport)
    rapport["opportunites"] = [
        r["id"] for r in rapport["recommandations"] if r["regle"] in recommandations.REGLES_OPPORTUNITE
    ]
    rapport["donnees_manquantes"] = _manques(rapport)
    rapport["empreinte"] = empreinte(rapport)
    return rapport


def _references(sources: dict[str, Any]) -> dict[str, list[str]]:
    """Les identifiants sur lesquels le rapport peut s'appuyer, par type : ce que chaque recommandation cite doit y
    figurer."""
    mesures = sorted(
        {m["metric_id"] for m in sources["m8_mesures"] or [] if isinstance(m.get("metric_id"), str)} & set(MESURES_M8)
    )
    contenus = sorted({c["utm_content"] for c in sources["m8_contenus"] or [] if isinstance(c.get("utm_content"), str)})
    observations = sorted(
        {o["observation_id"] for o in sources["croissance"] or [] if isinstance(o.get("observation_id"), str)}
    )
    sections = sorted(n for n in ("performance", "calendrier", "reputation") if sources[n] is not None)
    return {"mesure_m8": mesures, "contenu_m8": contenus, "observation_growth": observations, "section_m7": sections}


def _manques(rapport: dict[str, Any]) -> list[str]:
    manques = []
    for nom in (
        "leads_par_canal",
        "conversion",
        "roi",
        "croissance_engagement",
        "contenus",
        "calendrier",
        "reputation",
    ):
        section = rapport[nom]
        if section.get("statut") in (STATUT_ABSENT, STATUT_INSUFFISANT):
            manques.append(f"{nom} : {section.get('manque') or section.get('raison')}")
    manques.extend(f"plan_croissance : {m}" for m in rapport["plan_croissance"]["manques"])
    return manques


def empreinte(rapport: dict[str, Any]) -> str:
    """SHA-256 du rapport canonique sans son empreinte : deux rapports égaux ont la même."""
    corps = {k: v for k, v in rapport.items() if k != "empreinte"}
    return hashlib.sha256(
        json.dumps(corps, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
