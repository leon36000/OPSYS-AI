"""Recommandations de contenu et de technique pour le SEO et le GEO, SOURCÉES et PRIORISÉES par des règles lisibles.

Aucun modèle, aucun jugement caché : six règles déterministes (`GEO-01` à `GEO-06`) lisent les faits du registre des
signaux (Search Console, Bing, Core Web Vitals, journaux des robots d'IA) et les audits existants du site, et disent
chacune : - CE QU'ELLE A VU (les `fait_id`, leur période, leur révision, leur fraîcheur) ;
- POURQUOI cela mérite une action, et CE QUI N'EST PAS ÉTABLI ;
- sa PRIORITÉ, par une formule unique et visible : `score = impact × facilité`, deux entiers de 1 à 3 lus dans les
tables
  ci-dessous (`IMPACT_FACILITE`). Le classement est total et stable : score décroissant, puis identifiant de règle, puis
  ampleur du constat (impressions, écart…) décroissante, puis clé du constat. Ces tables sont des choix de M7
  déclarés, pas des mesures : elles disent dans quel ordre regarder, pas ce qui rapportera.

Une règle sans données utilisables est `non évaluable` et dit quoi importer ou lire : jamais une recommandation sur
du vide, jamais sur des faits PÉRIMÉS (hors de la fenêtre de la règle). Les repères de taux de clic par position
sont un repère interne indicatif à calibrer sur le site (`a_verifier`), pas une donnée de Google.

Ce que ces recommandations ne sont pas : une promesse de visibilité. La page officielle de Google dit qu'aucune
optimisation spéciale n'est requise pour apparaître dans ses fonctions d'IA (R4 §4.1) ; le contenu de masse sans
valeur ajoutée est du spam (R4 §9). Chaque recommandation de contenu est un BROUILLON à faire relire, avec des faits
propres au client.

Module pur : les faits, l'horloge et les audits sont fournis par l'appelant.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from ..mesure import statistiques
from .robots_ia import PAR_NOM, ErreurGeo

REGLES = ("GEO-01", "GEO-02", "GEO-03", "GEO-04", "GEO-05", "GEO-06")
# (impact, facilité) de 1 à 3 : impact 3 = condition d'éligibilité ou gros effet probable ; facilité 3 = un fichier
# ou un texte à changer, sans développement.
IMPACT_FACILITE: Mapping[str, tuple[int, int]] = {
    "GEO-01": (3, 3), "GEO-01:autorise": (2, 3), "GEO-02": (2, 3), "GEO-03": (2, 2), "GEO-04:mauvais": (3, 1),
    "GEO-04:a_ameliorer": (2, 1), "GEO-05": (2, 2), "GEO-06": (1, 3),
}
FORMULE_PRIORITE = ("score = impact × facilité (entiers de 1 à 3, IMPACT_FACILITE) ; tri : score décroissant, règle, "
                    "ampleur décroissante, clé")
FENETRE_RECHERCHE_JOURS = 35
FENETRE_CWV_JOURS = 90
FENETRE_JOURNAUX_JOURS = 35
FENETRE_AUDIT_JOURS = 90
COUVERTURE_JOURNAUX_MIN_JOURS = 14
IMPRESSIONS_MIN_PAGE = 200
IMPRESSIONS_MIN_REQUETE = 100
FACTEUR_CTR_BAS = Decimal("0.5")
# Repère interne indicatif (a_verifier) : taux de clic attendu selon la position moyenne arrondie (page Web, hors IA).
CTR_REPERE: Mapping[int, Decimal] = {
    1: Decimal("0.28"), 2: Decimal("0.15"), 3: Decimal("0.11"), 4: Decimal("0.08"), 5: Decimal("0.06"),
    6: Decimal("0.045"), 7: Decimal("0.035"), 8: Decimal("0.03"), 9: Decimal("0.025"), 10: Decimal("0.02"),
}
POSITION_PROCHE = (Decimal(8), Decimal(20))
# Seuils publics des Core Web Vitals au 75e centile : (bon jusqu'à, mauvais au-delà). a_verifier (web.dev).
SEUILS_CWV: Mapping[str, tuple[Decimal, Decimal]] = {
    "lcp_p75_ms": (Decimal(2500), Decimal(4000)), "inp_p75_ms": (Decimal(200), Decimal(500)),
    "cls_p75": (Decimal("0.1"), Decimal("0.25")),
}
AVERTISSEMENTS = (
    "Aucune promesse de visibilité : Google indique qu'aucune optimisation spéciale n'est requise pour apparaître "
    "dans ses "
    "fonctions d'IA (R4 §4.1).",
    "Pas de contenu de masse : chaque contenu repose sur des faits propres au client, relu par une personne (R4 §9).",
    "Les repères de taux de clic et les seuils de Core Web Vitals sont indicatifs (a_verifier) ; la priorité dit "
    "dans quel "
    "ordre regarder, pas ce qui rapportera.",
    "Une recommandation est un brouillon : rien n'est modifié ni publié (publication = décision N3 de la direction).",
)


SOURCES_RECHERCHE = ("search_console", "bing_webmaster")


def _d(texte: str) -> Decimal:
    return Decimal(texte)


def _date(texte: str) -> date:
    return date.fromisoformat(texte)


def _ref_fait(f: Mapping[str, Any]) -> dict[str, Any]:
    return {"fait_id": f["fait_id"], "source": f["source"], "nature": f["nature"], "periode_debut": f["periode_debut"],
            "periode_fin": f["periode_fin"], "revision": f["revision"], "observe_le": f["observe_le"]}


def _fraicheur(faits: Sequence[Mapping[str, Any]], aujourd_hui: date) -> dict[str, Any]:
    fins = [_date(f["periode_fin"]) for f in faits]
    return {"plus_ancienne_periode_fin": min(fins).isoformat(), "plus_recente_periode_fin": max(fins).isoformat(),
            "age_jours_max": (aujourd_hui - min(fins)).days}


def _rec(regle: str, variante: str | None, cle: str, titre: str, pourquoi: str, non_etabli: Sequence[str],
         faits: Sequence[Mapping[str, Any]], aujourd_hui: date, ampleur: Decimal, constat: Mapping[str, Any],
         action: str, brouillon_site: str | None = None, source_audit: str | None = None) -> dict[str, Any]:
    impact, facilite = IMPACT_FACILITE[f"{regle}:{variante}" if variante else regle]
    faits = sorted(faits, key=lambda f: (f["periode_fin"], f["fait_id"]))  # l'ordre d'entrée ne change rien
    return {
        "id": f"{regle}:{hashlib.sha256(cle.encode('utf-8')).hexdigest()[:10]}", "regle": regle, "cle": cle,
        "titre": titre, "pourquoi": pourquoi, "ce_qui_n_est_pas_etabli": list(non_etabli),
        "constat": dict(constat), "action_proposee": action,
        "priorite": {"impact": impact, "facilite": facilite, "score": impact * facilite, "ampleur":
                     statistiques.texte(ampleur)},
        "faits": [_ref_fait(f) for f in faits[:5]], "faits_total": len(faits),
        "fraicheur": _fraicheur(faits, aujourd_hui) if faits else None, "source_audit": source_audit,
        "changement_site": brouillon_site,
    }


def _recents(faits: Iterable[Mapping[str, Any]], aujourd_hui: date, jours: int, natures: Iterable[str],
             sources: Iterable[str] | None = None) -> list[Mapping[str, Any]]:
    limite = (aujourd_hui - timedelta(days=jours)).isoformat()
    natures, sources = set(natures), set(sources) if sources is not None else None
    return [f for f in faits if f["nature"] in natures and f["periode_fin"] >= limite
            and (sources is None or f["source"] in sources)]


def _agreger(faits: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Par (source, portée) : clics, impressions et position moyenne PONDÉRÉE par les impressions."""
    groupes: dict[tuple[str, str], dict[str, Any]] = {}
    for f in faits:
        m = f["mesures"]
        if "impressions" not in m or "clics" not in m:
            continue
        g = groupes.setdefault((f["source"], f["portee"]["ref"]), {"impressions": Decimal(0), "clics": Decimal(0),
                                                                    "pos_x_impr": Decimal(0), "impr_pos": Decimal(0),
                                                                    "faits": []})
        impr = _d(m["impressions"])
        g["impressions"] += impr
        g["clics"] += _d(m["clics"])
        if "position" in m:
            g["pos_x_impr"] += _d(m["position"]) * impr
            g["impr_pos"] += impr
        g["faits"].append(f)
    return groupes


def _geo_02(faits, aujourd_hui, recs, non_eval):
    pages = _recents(faits, aujourd_hui, FENETRE_RECHERCHE_JOURS, ["pages_periode"],
                     SOURCES_RECHERCHE)
    if not pages:
        non_eval.append({"regle": "GEO-02", "raison": f"aucun fait de pages de recherche des {FENETRE_RECHERCHE_JOURS} "
                         "derniers jours", "a_importer": "lire Search Console ou Bing Webmaster (flux `pages`) ou "
                         "importer "
                         "leur export"})
        return
    for (source, ref), g in sorted(_agreger(pages).items()):
        if g["impressions"] < IMPRESSIONS_MIN_PAGE or g["impr_pos"] == 0:
            continue
        position = g["pos_x_impr"] / g["impr_pos"]
        arrondie = min(max(int(position.quantize(Decimal(1), rounding="ROUND_HALF_UP")), 1), 10)
        if position > Decimal("10.5"):
            continue
        ctr = g["clics"] / g["impressions"]
        repere = CTR_REPERE[arrondie]
        if ctr < repere * FACTEUR_CTR_BAS:
            recs.append(_rec(
                "GEO-02", None, f"{source}|{ref}", f"Titre et description à retravailler : {ref}",
                f"La page a {statistiques.texte(g['impressions'])} impressions sur la période pour un taux de clic de "
                f"{statistiques.texte(ctr, Decimal('0.0001'))}, moins de la moitié du repère "
                f"({statistiques.texte(repere)}) à la position {arrondie}.",
                ["la cause du faible taux de clic (titre, extrait, intention, fonctions de la page de résultats)",
                 "l'effet d'un nouveau titre", "le repère de taux de clic est interne et indicatif"],
                g["faits"], aujourd_hui, g["impressions"],
                {"impressions": statistiques.texte(g["impressions"]), "clics": statistiques.texte(g["clics"]),
                 "ctr": statistiques.texte(ctr), "position": statistiques.texte(position),
                 "repere_ctr": statistiques.texte(repere), "facteur": statistiques.texte(FACTEUR_CTR_BAS)},
                "Reformuler le titre et la description de la page autour de ce que la requête cherche, avec des faits "
                "du client ; tester un seul changement à la fois.", brouillon_site="remplacer_texte page.titre / "
                "page.description"))


def _geo_03(faits, aujourd_hui, recs, non_eval):
    req = _recents(faits, aujourd_hui, FENETRE_RECHERCHE_JOURS, ["requetes_periode"],
                   SOURCES_RECHERCHE)
    if not req:
        non_eval.append({"regle": "GEO-03",
                         "raison": f"aucun fait de requêtes des {FENETRE_RECHERCHE_JOURS} derniers jours",
                         "a_importer": "lire Search Console ou Bing Webmaster (flux `requetes`) ou importer "
                                       "leur export"})
        return
    for (source, ref), g in sorted(_agreger(req).items()):
        if g["impressions"] < IMPRESSIONS_MIN_REQUETE or g["impr_pos"] == 0:
            continue
        position = g["pos_x_impr"] / g["impr_pos"]
        if not POSITION_PROCHE[0] <= position <= POSITION_PROCHE[1]:
            continue
        recs.append(_rec(
            "GEO-03", None, f"{source}|{ref}", f"Requête proche de la première page : {ref}",
            f"La requête affiche {statistiques.texte(g['impressions'])} impressions à la position moyenne "
            f"{statistiques.texte(position)}, entre {POSITION_PROCHE[0]} et {POSITION_PROCHE[1]} : un contenu qui y "
            f"répond "
            "mieux pourrait la rapprocher de la première page.",
            ["qu'un nouveau contenu fera monter la position", "l'intention réelle de la requête",
             "les requêtes rares sont anonymisées par le fournisseur"],
            g["faits"], aujourd_hui, g["impressions"],
            {"impressions": statistiques.texte(g["impressions"]), "position": statistiques.texte(position)},
            "Créer ou enrichir UNE page qui répond précisément à la requête, avec des faits propres au client "
            "(zones, services, exemples réels) ; pas de pages en série.", brouillon_site="ajouter_faq ou "
            "remplacer_texte service.description"))


def _geo_04(faits, aujourd_hui, recs, non_eval):
    terrain = _recents(faits, aujourd_hui, FENETRE_CWV_JOURS, ["terrain_cwv"])
    derniers: dict[tuple[str, str], Mapping[str, Any]] = {}
    for f in sorted(terrain, key=lambda x: (x["periode_fin"], x["revision"], x["fait_id"])):
        derniers[(f["source"], f["portee"]["ref"])] = f
    if not derniers:
        non_eval.append({"regle": "GEO-04", "raison": f"aucun fait de terrain Core Web Vitals des {FENETRE_CWV_JOURS} "
                         "derniers jours", "a_importer": "lire PageSpeed Insights ou CrUX (un site peu visité peut "
                         "ne pas "
                         "avoir de données de terrain : ce n'est pas un bon résultat)"})
        return
    for (source, ref), f in sorted(derniers.items()):
        for metrique, (bon, mauvais) in SEUILS_CWV.items():
            if metrique not in f["mesures"]:
                continue
            valeur = _d(f["mesures"][metrique])
            if valeur <= bon:
                continue
            variante = "mauvais" if valeur > mauvais else "a_ameliorer"
            recs.append(_rec(
                "GEO-04", variante, f"{source}|{ref}|{metrique}", "Performance de terrain à améliorer : "
                "{metrique} sur {ref}",
                f"{metrique} vaut {statistiques.texte(valeur)} au 75e centile ; seuil « bon » {bon}, seuil « mauvais » "
                f"{mauvais}.", ["l'effet d'une correction sur le classement ou sur les réponses d'IA",
                                "la cause (images, scripts, hébergement, serveur)",
                                "les seuils sont ceux publiés par Google (a_verifier)"],
                [f], aujourd_hui, valeur - bon,
                {"metrique": metrique, "p75": statistiques.texte(valeur), "bon": str(bon), "mauvais": str(mauvais),
                 "niveau": variante}, "Auditer le rendu de la page (Lighthouse en CI) et corriger la cause la plus "
                "coûteuse d'abord (poids des images, scripts bloquants, temps de réponse du serveur)."))


def _geo_05(faits, aujourd_hui, recs, non_eval, analyse_robots):
    journaux = _recents(faits, aujourd_hui, FENETRE_JOURNAUX_JOURS, ["visites_robots_ia"])
    couverture = {f["periode_debut"] for f in journaux if f["portee"]["ref"] == "journal_couverture"}
    if analyse_robots is None:
        non_eval.append({"regle": "GEO-05", "raison": "analyse de robots.txt absente",
                         "a_importer": "fournir l'analyse "
                         "robots_ia (m7_analyser_robots_ia) : on ne peut dire qu'un robot est attendu que s'il est "
                         "autorisé"})
        return
    if len(couverture) < COUVERTURE_JOURNAUX_MIN_JOURS:
        non_eval.append({"regle": "GEO-05", "raison": f"journaux couvrant {len(couverture)} jours sur "
                         f"{COUVERTURE_JOURNAUX_MIN_JOURS} requis", "a_importer": "importer les journaux d'accès du "
                         "serveur "
                         "(m7_analyser_journaux_robots_ia puis m7_importer_signaux_manuel)"})
        return
    attendus = [r["robot"] for r in analyse_robots["robots"] if r["categorie"] == "recherche" and r["autorise"]
                and r["voulu"]]
    if not attendus:
        return
    visites = sum(_d(f["mesures"].get("visites", "0")) for f in journaux
                  if f["portee"]["ref"] in attendus)
    if visites == 0:
        couverts = [f for f in journaux if f["portee"]["ref"] == "journal_couverture"]
        noms = ", ".join(sorted(attendus))
        recs.append(_rec(
            "GEO-05", None, "robots-recherche", "Aucune visite d'un robot d'IA de recherche autorisé",
            f"Les journaux importés couvrent {len(couverture)} jours sans aucune visite de {noms}, "
            "alors que robots.txt les autorise et que la politique du client le veut.",
            ["la cause (pare-feu ou CDN qui bloque, site jamais découvert, robot qui ne passe pas)",
             "qu'une visite entraînerait une citation dans une réponse"], couverts, aujourd_hui,
            Decimal(len(couverture)),
            {"robots_attendus": sorted(attendus), "jours_couverts": len(couverture), "visites": "0"},
            "Vérifier que le pare-feu et le CDN ne bloquent pas ces agents, que le plan de site est à jour et que "
            "les pages "
            "se rendent en HTML sans script."))


def _geo_01(analyse_robots, aujourd_hui, recs, non_eval):
    if analyse_robots is None:
        non_eval.append({"regle": "GEO-01", "raison": "analyse de robots.txt absente",
                         "a_importer": "fournir le texte de "
                         "robots.txt, son statut HTTP et la politique du client (m7_analyser_robots_ia)"})
        return
    for c in analyse_robots["constats"]:
        if analyse_robots["etat_robots"] == "inaccessible" and c["code"] != "GEO-ROBOTS-INACCESSIBLE":
            continue  # tout est « bloqué » par défaut d'accès : une seule recommandation, la disponibilité du fichier
        if c["code"] == "GEO-ROBOTS-INACCESSIBLE":
            recs.append(_rec("GEO-01", None, "robots-inaccessible", "robots.txt inaccessible",
                             c["detail"], ["si le blocage est intentionnel ou accidentel"], [], aujourd_hui, Decimal(1),
                             {"etat_robots": "inaccessible"}, "Rétablir la disponibilité de robots.txt."))
        elif c["code"] == "GEO-ROBOT-BLOQUE-CONTRE-POLITIQUE":
            recherche = c["categorie"] == "recherche"
            recs.append(_rec(
                "GEO-01", None, f"bloque|{c['robot']}", f"{c['robot']} est bloqué contre la politique du client",
                c["detail"] + (" ; bloquer un robot de recherche exclut le site de ce moteur de réponses." if recherche
                               else "."),
                ["que l'autoriser fasse apparaître le site dans les réponses", "la décision actuelle du client si la "
                 "politique a changé"], [], aujourd_hui, Decimal(2 if recherche else 1),
                {"robot": c["robot"], "categorie": c["categorie"], "constat": c["code"]},
                f"Ajouter à robots.txt (après relecture) :\nUser-agent: {c['robot']}\nAllow: /"))
        elif c["code"] == "GEO-ROBOT-AUTORISE-CONTRE-POLITIQUE":
            recs.append(_rec(
                "GEO-01", "autorise", f"autorise|{c['robot']}", f"{c['robot']} est autorisé contre la politique du "
                "client",
                c["detail"] + ".", ["si le robot respecte la directive"], [], aujourd_hui, Decimal(1),
                {"robot": c["robot"], "categorie": c["categorie"], "constat": c["code"]},
                f"Ajouter à robots.txt (après relecture) :\nUser-agent: {c['robot']}\nDisallow: /"))


def _geo_06(audit_seo, audit_aeo, audit_le, aujourd_hui, recs, non_eval):
    if audit_seo is None and audit_aeo is None:
        non_eval.append({"regle": "GEO-06", "raison": "aucun audit SEO ou AEO fourni",
                         "a_importer": "fournir le rapport "
                         "de m7_auditer_seo_site ou m7_evaluer_aeo"})
        return
    try:
        jour = date.fromisoformat(audit_le) if isinstance(audit_le, str) else None
    except ValueError:
        jour = None
    if jour is None or (aujourd_hui - jour).days > FENETRE_AUDIT_JOURS or jour > aujourd_hui:
        non_eval.append({"regle": "GEO-06", "raison": "date de l'audit absente, future ou de plus de "
                         f"{FENETRE_AUDIT_JOURS} jours", "a_importer": "relancer l'audit et fournir sa date "
                         "(audit_le)"})
        return
    echecs: dict[str, dict[str, Any]] = {}
    for page in (audit_seo or {}).get("pages", []):
        for v in page.get("verdicts", []):
            if v.get("ok") is False:
                e = echecs.setdefault(f"seo:{v['regle']}", {"pages": set(), "detail": v.get("detail", "")})
                e["pages"].add(page.get("fichier") or page.get("page") or "?")
    for v in (audit_seo or {}).get("robots", {}).get("verdicts", []):
        if v.get("ok") is False:
            echecs.setdefault(f"seo:robots:{v['regle']}", {"pages": {"robots.txt"}, "detail": v.get("detail", "")})
    for surface, verdicts in (audit_aeo or {}).get("surface_reports", {}).items():
        for v in verdicts:
            if v.get("verdict") == "non_conforme":
                e = echecs.setdefault(f"aeo:{surface}:{v['rule_id']}", {"pages": {surface}, "detail":
                                                                       v.get("measured_fact", "")})
    for cle, e in sorted(echecs.items()):
        recs.append(_rec(
            "GEO-06", None, cle, f"Écart d'audit : {cle}", f"L'audit du {audit_le} relève : {e['detail']} "
            f"({len(e['pages'])} élément(s)).", ["l'effet de la correction sur le classement ou les réponses d'IA"], [],
            aujourd_hui, Decimal(len(e["pages"])), {"regle_audit": cle, "elements": sorted(e["pages"])[:20],
                                                    "nombre": len(e["pages"])},
            "Corriger l'écart sur le contenu du site (brouillon relu), puis relancer l'audit.",
            source_audit=f"audit du {audit_le}",
            brouillon_site=("remplacer_texte page.titre / page.description"
                            if "title" in cle or "meta" in cle else None)))


def recommander(faits: Sequence[Mapping[str, Any]], *, maintenant: datetime,
                analyse_robots: Mapping[str, Any] | None = None, audit_seo: Mapping[str, Any] | None = None,
                audit_aeo: Mapping[str, Any] | None = None,
                audit_le: str | None = None) -> dict[str, Any]:
    """Les recommandations, classées, et les règles non évaluables. `faits` : faits COURANTS du registre des signaux."""
    if maintenant.tzinfo is None:
        raise ErreurGeo("REJ-GEO-HORLOGE", "horloge sans fuseau")
    if analyse_robots is not None and analyse_robots.get("type") != "ROBOTS_IA":
        raise ErreurGeo("REJ-GEO-ANALYSE-INVALIDE", "analyse robots_ia attendue")
    aujourd_hui = maintenant.date()
    recs: list[dict[str, Any]] = []
    non_eval: list[dict[str, Any]] = []
    _geo_01(analyse_robots, aujourd_hui, recs, non_eval)
    _geo_02(faits, aujourd_hui, recs, non_eval)
    _geo_03(faits, aujourd_hui, recs, non_eval)
    _geo_04(faits, aujourd_hui, recs, non_eval)
    _geo_05(faits, aujourd_hui, recs, non_eval, analyse_robots)
    _geo_06(audit_seo, audit_aeo, audit_le, aujourd_hui, recs, non_eval)
    recs.sort(key=lambda r: (-r["priorite"]["score"], r["regle"], -Decimal(r["priorite"]["ampleur"]), r["cle"]))
    for rang, r in enumerate(recs, start=1):
        r["priorite"]["rang"] = rang
    return {"type": "RECOMMANDATIONS_GEO", "evalue_le": aujourd_hui.isoformat(), "recommandations": recs,
            "non_evaluables": non_eval, "formule_priorite": FORMULE_PRIORITE,
            "tables": {"impact_facilite": {k: list(v) for k, v in IMPACT_FACILITE.items()}},
            "robots_connus": sorted(PAR_NOM), "avertissements": list(AVERTISSEMENTS)}


__all__ = ["AVERTISSEMENTS", "CTR_REPERE", "FORMULE_PRIORITE", "IMPACT_FACILITE", "REGLES", "SEUILS_CWV", "recommander"]
