"""Recommandations GEO : chaque règle aux deux côtés de ses seuils, priorité stable, données absentes ou périmées."""

from __future__ import annotations

import json
import random
from datetime import timedelta

import pytest
from fabriques_geo import MAINTENANT
from m7_marketing.geo import recommandations
from m7_marketing.geo.recommandations import recommander
from m7_marketing.geo.robots_ia import ErreurGeo, analyser_robots_ia
from m7_marketing.signaux import modele

AUJOURD_HUI = MAINTENANT.date()
POLITIQUE = {"recherche": "autoriser", "recuperation_a_la_demande": "autoriser", "entrainement": "autoriser"}


def jour(delta):
    return (AUJOURD_HUI - timedelta(days=delta)).isoformat()


def fait(source, nature, ptype, ref, debut, fin, mesures, *, revision=1):
    brut = modele.brouillon_fait(
        source=source, compte_ref="principal", nature=nature, portee_type=ptype, portee_ref=ref, debut=debut, fin=fin,
        mesures=mesures, observe_le="2026-11-01T12:00:00Z", fictif=True,
        provenance={"fournisseur": "google", "point_acces": "x", "version_api": "v1", "mode": "api_lecture",
                    "empreinte_reponse": "a" * 64, "page": 0})
    return modele.normaliser_fait({**brut, "revision": revision})


def page(ref, impressions, clics, position, *, fin=7, source="search_console"):
    return fait(source, "pages_periode", "page", ref, jour(fin + 6), jour(fin),
                {"impressions": str(impressions), "clics": str(clics), "position": str(position), "ctr": "0"})


def requete(ref, impressions, position, *, fin=7, source="search_console"):
    return fait(source, "requetes_periode", "requete", ref, jour(fin + 6), jour(fin),
                {"impressions": str(impressions), "clics": "1", "position": str(position), "ctr": "0"})


def cwv(ref, **mesures):
    return fait("pagespeed", "terrain_cwv", "page", ref, jour(34), jour(6), {k: str(v) for k, v in mesures.items()})


def regles(r):
    return [x["regle"] for x in r["recommandations"]]


def non_evaluables(r):
    return {x["regle"]: x for x in r["non_evaluables"]}


# -- GEO-02 : pages à forte impression et CTR bas --------------------------------------------------------------------
@pytest.mark.parametrize("impressions,clics,position,attendu", [
    (200, 10, 3, True),    # ctr 0.05 < 0.055 (la moitié du repère 0.11 de la position 3)
    (200, 11, 3, False),   # ctr 0.055 : pas strictement sous le seuil
    (199, 0, 3, False),    # sous le minimum d'impressions
    (200, 0, 10, True),
    (200, 3, 10.4, False),  # position arrondie à 10 : repère 0.02, seuil 0.01 ; ctr 0.015
    (200, 0, 10.6, False),  # au-delà de la dixième position : règle muette
    (200, 5, 1, True),     # repère 0.28 -> seuil 0.14 ; ctr 0.025
    (200, 30, 1, False),
])
def test_geo_02_seuils_aux_deux_cotes(impressions, clics, position, attendu):
    r = recommander([page("/services", impressions, clics, position)], maintenant=MAINTENANT)
    assert ("GEO-02" in regles(r)) is attendu


def test_geo_02_agrege_les_semaines_et_pondere_la_position_par_les_impressions():
    faits = [page("/faq", 100, 1, 2, fin=14), page("/faq", 100, 1, 4, fin=7)]
    r = recommander(faits, maintenant=MAINTENANT)
    rec = next(x for x in r["recommandations"] if x["regle"] == "GEO-02")
    assert (rec["constat"]["impressions"], rec["constat"]["clics"], rec["constat"]["position"]) == ("200", "2", "3")
    assert rec["constat"]["repere_ctr"] == "0.11" and rec["faits_total"] == 2
    assert {f["fait_id"] for f in rec["faits"]} == {f["fait_id"] for f in faits}


def test_geo_02_sources_distinctes_ne_se_melangent_pas():
    faits = [page("/faq", 100, 0, 3, source="search_console"), page("/faq", 100, 0, 3, source="bing_webmaster")]
    assert "GEO-02" not in regles(recommander(faits, maintenant=MAINTENANT))  # 100 + 100 jamais additionnés


def test_geo_02_faits_perimes_ou_absents_rendent_la_regle_non_evaluable():
    r = recommander([page("/services", 500, 0, 3, fin=40)], maintenant=MAINTENANT)  # fin il y a 40 jours : hors fenêtre
    assert "GEO-02" not in regles(r) and "GEO-02" in non_evaluables(r)
    assert "Search Console" in non_evaluables(r)["GEO-02"]["a_importer"]
    assert "GEO-02" in non_evaluables(recommander([], maintenant=MAINTENANT))
    dans_la_fenetre = recommander([page("/services", 500, 0, 3, fin=35)], maintenant=MAINTENANT)
    assert "GEO-02" in regles(dans_la_fenetre) and "GEO-02" not in non_evaluables(dans_la_fenetre)


# -- GEO-03 : requêtes proches de la première page -------------------------------------------------------------------
@pytest.mark.parametrize("position,attendu", [("7.99", False), ("8", True), ("14", True), ("20", True), ("20.01",
    False)])
def test_geo_03_bornes_de_position(position, attendu):
    r = recommander([requete("gouttière laval", 150, position)], maintenant=MAINTENANT)
    assert ("GEO-03" in regles(r)) is attendu


@pytest.mark.parametrize("impressions,attendu", [(99, False), (100, True)])
def test_geo_03_minimum_d_impressions(impressions, attendu):
    assert ("GEO-03" in regles(recommander([requete("q", impressions, 12)], maintenant=MAINTENANT))) is attendu


def test_geo_03_sans_donnees_non_evaluable_et_perimees_aussi():
    assert "GEO-03" in non_evaluables(recommander([], maintenant=MAINTENANT))
    assert "GEO-03" in non_evaluables(recommander([requete("q", 500, 12, fin=60)], maintenant=MAINTENANT))


# -- GEO-04 : Core Web Vitals -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("mesure,valeur,niveau", [
    ("lcp_p75_ms", 2500, None), ("lcp_p75_ms", 2501, "a_ameliorer"), ("lcp_p75_ms", 4000, "a_ameliorer"),
    ("lcp_p75_ms", 4001, "mauvais"), ("inp_p75_ms", 200, None), ("inp_p75_ms", 201, "a_ameliorer"),
    ("inp_p75_ms", 500, "a_ameliorer"), ("inp_p75_ms", 501, "mauvais"), ("cls_p75", "0.1", None),
    ("cls_p75", "0.101", "a_ameliorer"), ("cls_p75", "0.25", "a_ameliorer"), ("cls_p75", "0.251", "mauvais"),
])
def test_geo_04_seuils_publics_aux_deux_cotes(mesure, valeur, niveau):
    r = recommander([cwv("/", **{mesure: valeur})], maintenant=MAINTENANT)
    recs = [x for x in r["recommandations"] if x["regle"] == "GEO-04"]
    assert [x["constat"]["niveau"] for x in recs] == ([niveau] if niveau else [])


def test_geo_04_le_fait_le_plus_recent_gagne_et_les_trop_vieux_sont_ignores():
    ancien = fait("pagespeed", "terrain_cwv", "page", "/", jour(80), jour(60), {"lcp_p75_ms": "9000"})
    recent = fait("pagespeed", "terrain_cwv", "page", "/", jour(30), jour(10), {"lcp_p75_ms": "2000"})
    assert "GEO-04" not in regles(recommander([ancien, recent], maintenant=MAINTENANT))
    tres_vieux = fait("pagespeed", "terrain_cwv", "page", "/", jour(130), jour(100), {"lcp_p75_ms": "9000"})
    r = recommander([tres_vieux], maintenant=MAINTENANT)
    assert "GEO-04" in non_evaluables(r) and "GEO-04" not in regles(r)
    assert "peu visité" in non_evaluables(r)["GEO-04"]["a_importer"]


def test_geo_04_priorite_mauvais_plus_haute_que_a_ameliorer():
    r = recommander([cwv("/a", lcp_p75_ms=5000), cwv("/b", lcp_p75_ms=3000)], maintenant=MAINTENANT)
    scores = {x["constat"]["niveau"]: x["priorite"]["score"] for x in r["recommandations"]}
    assert scores == {"mauvais": 3, "a_ameliorer": 2}  # impact x facilité : 3x1 et 2x1


# -- GEO-01 et GEO-05 : robots et journaux ---------------------------------------------------------------------------
def analyse(texte="", statut=200, politique=POLITIQUE):
    return analyser_robots_ia(texte, statut, politique)


def visite(robot, j, n):
    return fait("journaux_serveur", "visites_robots_ia", "robot_ia", robot, jour(j), jour(j), {"visites": str(n)})


def couverture(jours):
    return [visite("journal_couverture", j, 0) for j in range(1, jours + 1)]


def test_geo_01_robot_bloque_contre_la_politique_et_la_variante_autorise():
    a = analyse("User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: GPTBot\nAllow: /\n")
    r = recommander([], maintenant=MAINTENANT, analyse_robots=a)
    cles = {x["cle"]: x for x in r["recommandations"] if x["regle"] == "GEO-01"}
    assert set(cles) == {"bloque|OAI-SearchBot"}  # GPTBot est autorisé ET la politique veut autoriser : conforme
    assert cles["bloque|OAI-SearchBot"]["priorite"] == {"impact": 3, "facilite": 3, "score": 9, "ampleur": "2",
        "rang": 1}
    contre = recommander([], maintenant=MAINTENANT, analyse_robots=analyse("", 200, {**POLITIQUE,
        "entrainement": "bloquer"}))
    autorises = [x for x in contre["recommandations"] if x["cle"].startswith("autorise|")]
    assert len(autorises) == 5 and {x["priorite"]["score"] for x in autorises} == {6}
    assert "Allow: /" in cles["bloque|OAI-SearchBot"]["action_proposee"]
    assert "exclut le site de ce moteur" in cles["bloque|OAI-SearchBot"]["pourquoi"]


def test_geo_01_robots_inaccessible_et_conforme():
    r = recommander([], maintenant=MAINTENANT, analyse_robots=analyse(None, 503))
    assert [x["cle"] for x in r["recommandations"]] == ["robots-inaccessible"]
    conforme = analyse("User-agent: GPTBot\nDisallow: /\n", 200, {**POLITIQUE, "entrainement": "bloquer"})
    # GPTBot est bloqué et c'est voulu ; les quatre autres robots d'entraînement restent autorisés contre la politique
    assert {x["cle"] for x in recommander([], maintenant=MAINTENANT, analyse_robots=conforme)["recommandations"]} == {
        "autorise|ClaudeBot", "autorise|Google-Extended", "autorise|Applebot-Extended", "autorise|CCBot"}
    parfait = analyse("User-agent: *\nAllow: /\n")
    assert "GEO-01" not in regles(recommander([], maintenant=MAINTENANT, analyse_robots=parfait))


def test_geo_01_et_05_non_evaluables_sans_analyse_robots():
    ne = non_evaluables(recommander([], maintenant=MAINTENANT))
    assert "GEO-01" in ne and "GEO-05" in ne and "m7_analyser_robots_ia" in ne["GEO-01"]["a_importer"]


def test_geo_05_aucune_visite_d_un_robot_de_recherche_autorise():
    r = recommander(couverture(14) + [visite("GPTBot", 3, 40)], maintenant=MAINTENANT, analyse_robots=analyse())
    rec = next(x for x in r["recommandations"] if x["regle"] == "GEO-05")
    assert rec["constat"]["visites"] == "0" and rec["constat"]["jours_couverts"] == 14
    assert rec["constat"]["robots_attendus"] == sorted(rec["constat"]["robots_attendus"])
    assert "OAI-SearchBot" in rec["constat"]["robots_attendus"] and "GPTBot" not in rec["constat"]["robots_attendus"]
    assert rec["priorite"]["score"] == 4


def test_geo_05_une_visite_d_un_robot_attendu_suffit_pour_ne_rien_recommander():
    r = recommander(couverture(14) + [visite("PerplexityBot", 2, 1)], maintenant=MAINTENANT, analyse_robots=analyse())
    assert "GEO-05" not in regles(r) and "GEO-05" not in non_evaluables(r)


@pytest.mark.parametrize("jours,evaluable", [(13, False), (14, True)])
def test_geo_05_couverture_minimale_des_journaux(jours, evaluable):
    r = recommander(couverture(jours), maintenant=MAINTENANT, analyse_robots=analyse())
    assert ("GEO-05" not in non_evaluables(r)) is evaluable


def test_geo_05_robots_de_recherche_bloques_par_le_client_ne_sont_pas_attendus():
    tous_bloques = analyse("User-agent: *\nDisallow: /\n")
    r = recommander(couverture(20), maintenant=MAINTENANT, analyse_robots=tous_bloques)
    assert "GEO-05" not in regles(r)
    politique_bloquer = analyse("", 200, {**POLITIQUE, "recherche": "bloquer"})
    assert "GEO-05" not in regles(recommander(couverture(20), maintenant=MAINTENANT, analyse_robots=politique_bloquer))


def test_geo_05_journaux_hors_fenetre_ne_comptent_pas():
    vieux = [visite("journal_couverture", j, 0) for j in range(40, 60)]
    r = recommander(vieux, maintenant=MAINTENANT, analyse_robots=analyse())
    assert "GEO-05" in non_evaluables(r)


# -- GEO-06 : audits ---------------------------------------------------------------------------------------------------
AUDIT_SEO = {"pages": [{"fichier": "index.html", "verdicts": [{"regle": "title", "ok": False, "detail": "title absent"},
                                                           {"regle": "h1", "ok": True, "detail": "ok"}]},
                       {"fichier": "faq.html", "verdicts": [{"regle": "title", "ok": False,
                           "detail": "title absent"}]}],
             "robots": {"verdicts": [{"regle": "sitemap", "ok": False, "detail": "plan de site absent"}]},
             "resume": {"pages_auditees": 2, "regles_ko": 3}}
AUDIT_AEO = {"surface_reports": {"google_aio": [{"rule_id": "A-01", "verdict": "non_conforme",
    "measured_fact": "title_len=80"},
                                                {"rule_id": "A-02", "verdict": "conforme", "measured_fact": "ok"}]}}


def test_geo_06_regroupe_les_ecarts_d_audit_par_regle():
    r = recommander([], maintenant=MAINTENANT, audit_seo=AUDIT_SEO, audit_aeo=AUDIT_AEO, audit_le=jour(10))
    cles = {x["cle"]: x for x in r["recommandations"] if x["regle"] == "GEO-06"}
    assert set(cles) == {"seo:title", "seo:robots:sitemap", "aeo:google_aio:A-01"}
    assert cles["seo:title"]["constat"]["nombre"] == 2 and cles["seo:title"]["changement_site"] is not None
    assert cles["seo:robots:sitemap"]["changement_site"] is None
    assert cles["seo:title"]["source_audit"] == f"audit du {jour(10)}"


@pytest.mark.parametrize("audit_le,evaluable", [(None, False), ("pas-une-date", False), ("2026-12-01", False),
                                                  (jour(91), False), (jour(90), True), (jour(0), True)])
def test_geo_06_date_de_l_audit_obligatoire_et_recente(audit_le, evaluable):
    r = recommander([], maintenant=MAINTENANT, audit_seo=AUDIT_SEO, audit_le=audit_le)
    assert ("GEO-06" not in non_evaluables(r)) is evaluable and (("GEO-06" in regles(r)) is evaluable)


def test_geo_06_sans_audit_non_evaluable():
    assert "GEO-06" in non_evaluables(recommander([], maintenant=MAINTENANT))


# -- priorité explicite et stable --------------------------------------------------------------------------------------
def jeu_complet():
    return ([page("/services", 400, 2, 3), page("/faq", 1000, 5, 3), requete("gouttière laval", 300, 12),
             requete("revêtement terrebonne", 800, 9), cwv("/", lcp_p75_ms=5000), cwv("/b", cls_p75="0.2")]
            + couverture(14))


def test_la_priorite_est_la_formule_impact_fois_facilite_et_le_classement_est_total():
    a = analyse("User-agent: OAI-SearchBot\nDisallow: /\n")
    r = recommander(jeu_complet(), maintenant=MAINTENANT, analyse_robots=a, audit_seo=AUDIT_SEO, audit_le=jour(5))
    recs = r["recommandations"]
    assert [x["priorite"]["rang"] for x in recs] == list(range(1, len(recs) + 1))
    for x in recs:
        assert x["priorite"]["score"] == x["priorite"]["impact"] * x["priorite"]["facilite"]
    cles = [(-x["priorite"]["score"], x["regle"]) for x in recs]
    assert cles == sorted(cles)
    assert recs[0]["regle"] == "GEO-01" and recs[0]["priorite"]["score"] == 9
    assert "impact × facilité" in r["formule_priorite"] and r["tables"]["impact_facilite"]["GEO-01"] == [3, 3]
    # à score égal, l'ampleur décroissante départage : /faq (1000 impressions) avant /services (400)
    geo02 = [x for x in recs if x["regle"] == "GEO-02"]
    assert [x["cle"] for x in geo02] == ["search_console|/faq", "search_console|/services"]
    geo03 = [x for x in recs if x["regle"] == "GEO-03"]
    assert [x["cle"] for x in geo03] == ["search_console|revêtement terrebonne", "search_console|gouttière laval"]


def test_l_ordre_des_faits_en_entree_ne_change_rien():
    faits = jeu_complet()
    a = analyse("User-agent: OAI-SearchBot\nDisallow: /\n")
    reference = recommander(faits, maintenant=MAINTENANT, analyse_robots=a)
    for graine in range(5):
        melange = faits[:]
        random.Random(graine).shuffle(melange)
        assert recommander(melange, maintenant=MAINTENANT, analyse_robots=a) == reference


def test_chaque_recommandation_est_sourcee_et_dit_ce_qui_n_est_pas_etabli():
    r = recommander(jeu_complet(), maintenant=MAINTENANT, analyse_robots=analyse())
    for x in r["recommandations"]:
        assert x["pourquoi"] and x["ce_qui_n_est_pas_etabli"] and x["action_proposee"]
        assert x["id"].startswith(x["regle"])
        if x["regle"] in ("GEO-02", "GEO-03", "GEO-04"):
            assert x["faits"] and all(f["fait_id"] and f["periode_fin"] and f["observe_le"] for f in x["faits"])
            assert x["fraicheur"]["age_jours_max"] >= 0 and x["fraicheur"]["plus_ancienne_periode_fin"]


def test_aucune_promesse_de_visibilite_et_le_rappel_de_google_est_present():
    r = recommander(jeu_complet(), maintenant=MAINTENANT, analyse_robots=analyse())
    texte = json.dumps(r, ensure_ascii=False).lower()
    for promesse in ("garanti", "vous serez", "première position assurée", "doublera", "augmentera votre"):
        assert promesse not in texte
    assert "aucune optimisation spéciale" in " ".join(r["avertissements"])
    assert "contenu de masse" in " ".join(r["avertissements"]).lower()
    assert "brouillon" in " ".join(r["avertissements"])


def test_entrees_invalides_refusees():
    with pytest.raises(ErreurGeo):
        recommander([], maintenant=MAINTENANT.replace(tzinfo=None))
    with pytest.raises(ErreurGeo):
        recommander([], maintenant=MAINTENANT, analyse_robots={"type": "autre"})


def test_les_tables_declarees_sont_celles_documentees():
    assert recommandations.IMPACT_FACILITE["GEO-01"] == (3, 3)
    assert recommandations.SEUILS_CWV["lcp_p75_ms"][0] == 2500 and recommandations.SEUILS_CWV["inp_p75_ms"][1] == 500
    assert recommandations.CTR_REPERE[1] > recommandations.CTR_REPERE[10]
    assert len(recommandations.REGLES) == 6
