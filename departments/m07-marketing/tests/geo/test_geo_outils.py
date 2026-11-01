"""Outils GEO : niveaux, schémas fermés, parcours de bout en bout sur base fictive, paquet sans réseau (AST)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from m7_marketing import geo_outils
from m7_marketing.geo import proposition_site
from m7_marketing.signaux import registre as reg_signaux
from m7_marketing.veille import registre as reg_veille

from opsys import stockage
from opsys.outils import Autonomie, Niveau

RACINE_SRC = Path(geo_outils.__file__).parent
HORO = "2026-11-01T12:00:00+00:00"
LIGNE_GPT = ('203.0.113.9 - - [31/Oct/2026:12:00:00 +0000] "GET /faq HTTP/1.1" 200 5 "-" '
             '"Mozilla (compatible; GPTBot/1.1)"')
POLITIQUE = {"recherche": "autoriser", "recuperation_a_la_demande": "autoriser", "entrainement": "bloquer"}
ATTENDUS = {
    "m7_analyser_robots_ia": (Autonomie.T0, None),
    "m7_analyser_journaux_robots_ia": (Autonomie.T0, None),
    "m7_importer_signaux_manuel": (Autonomie.T1, Niveau.N2),
    "m7_planifier_panel_visibilite_ia": (Autonomie.T0, None),
    "m7_calculer_visibilite_ia": (Autonomie.T0, None),
    "m7_recommander_contenu_geo": (Autonomie.T0, None),
    "m7_proposer_changement_site": (Autonomie.T1, Niveau.N2),
    "m7_retirer_proposition_site": (Autonomie.T1, Niveau.N2),
    "m7_lire_propositions_site": (Autonomie.T0, None),
}


def par_nom():
    return {o.nom: o for o in geo_outils.outils()}


def test_niveaux_schemas_fermes_aucun_role_d_appareil_et_fonctions_distinctes():
    outils = par_nom()
    assert {n: (o.autonomie, o.niveau) for n, o in outils.items()} == ATTENDUS
    for o in outils.values():
        assert o.parametres["additionalProperties"] is False and o.roles_appareil == frozenset()
        assert set(o.parametres.get("required", ())) <= set(o.parametres["properties"])
    assert len({o.fonction for o in outils.values()}) == len(outils)
    # aucun outil n'interroge un moteur, ne publie ni ne modifie robots.txt
    assert not [n for n in outils if "publier" in n or "interroger" in n or "executer" in n]
    # N3+ : aucun (publier reste une décision de la direction)
    assert all(o.niveau in (None, Niveau.N2) for o in outils.values())


def test_les_sources_d_import_de_l_outil_sont_celles_du_modele():
    from m7_marketing.signaux import modele

    source = par_nom()["m7_importer_signaux_manuel"].parametres["properties"]["source"]
    assert source["enum"] == list(modele.SOURCES_IMPORT)


def test_robots_ia_sans_politique_est_un_refus_typé_pas_une_exception():
    r = geo_outils.analyser_robots_ia("", 200, {})
    assert r["accepte"] is False and r["refus"][0]["code"] == "REJ-GEO-POLITIQUE-ABSENTE"
    ok = geo_outils.analyser_robots_ia("User-agent: GPTBot\nDisallow: /\n", 200, POLITIQUE)
    assert ok["type"] == "ROBOTS_IA" and json.dumps(ok)


def test_journaux_outil_refuse_les_plages_mal_formees_et_rend_les_lignes_a_importer():
    ligne = LIGNE_GPT
    r = geo_outils.analyser_journaux_robots_ia(ligne)
    assert r["robots"][0]["robot"] == "GPTBot" and r["lignes_a_importer"] and "203.0.113.9" not in json.dumps(r)
    assert geo_outils.analyser_journaux_robots_ia(ligne, {"x": 1})["refus"][0]["code"] == "REJ-GEO-PLAGES-INVALIDES"
    r = geo_outils.analyser_journaux_robots_ia(ligne, {"plages": {"GPTBot": ["203.0.113.0/24"]}, "source": "s",
        "date": "d"})
    assert r["robots"][0]["verification"]["ip_verifiees"] == 1
    trop = geo_outils.analyser_journaux_robots_ia("x" * (3 * 1024 * 1024))
    assert trop["refus"][0]["code"] == "REJ-GEO-JOURNAL-TROP-GROS"


def test_panel_et_visibilite_par_les_outils():
    prompts = [{"id": f"q{i}", "texte": f"Question numéro {i} sur les gouttières", "langue": "fr"} for i in range(20)]
    plan = geo_outils.planifier_panel_visibilite_ia(prompts, ["perplexity_sonar"], 2, {"perplexity_sonar": 3}, 1000)
    assert plan["cout_mensuel_cents"] == 120
    refus = geo_outils.planifier_panel_visibilite_ia(prompts, ["chatgpt_ui"], 1, {}, None)
    assert refus["refus"][0]["code"] == "REJ-GEO-MOTEUR-INTERFACE"
    resultats = [{"prompt_id": f"q{i}", "moteur": "perplexity_sonar", "repetition": 1, "mentionne": i < 5,
        "cite": i < 2}
                 for i in range(20)]
    v = geo_outils.calculer_visibilite_ia(resultats, plan)
    assert v["moteurs"][0]["mention"]["taux"] == "0.25" and v["cout"]["cout_mensuel_cents"] == 120
    assert geo_outils.calculer_visibilite_ia(["x"])["refus"][0]["code"] == "REJ-GEO-RESULTATS-INVALIDES"


MAPPING_PAGES = {"portee": {"type": "page", "colonne": "Page"}, "periode": {"debut": "Debut", "fin": "Fin"},
                 "mesures": {"impressions": "Impr", "clics": "Clics", "position": "Pos"},
                     "echantillon": "echantillonne"}


def test_parcours_import_puis_recommandation_sourcee_de_bout_en_bout(base):
    csv_texte = ("Page,Debut,Fin,Impr,Clics,Pos\n"
                 "https://horizon.example/services/,2026-10-19,2026-10-25,600,3,3\n"
                 "https://horizon.example/faq,2026-10-19,2026-10-25,50,0,3\n")
    r = geo_outils.importer_signaux_manuel("search_console", "principal", "pages_periode", MAPPING_PAGES, True, HORO,
                                           csv_texte=csv_texte)
    assert r["accepte"] and r["faits_nouveaux"] == 2 and r["par"] == "agent"
    rec = geo_outils.recommander_contenu_geo(HORO)
    assert rec["type"] == "RECOMMANDATIONS_GEO"
    assert [x["cle"] for x in rec["recommandations"]] == ["search_console|https://horizon.example/services/"]
    sourcee = rec["recommandations"][0]
    fait_id = reg_signaux.charger(stockage.maillons(*reg_signaux.REGISTRE))[0]["fait_id"]
    assert sourcee["faits"][0]["periode_fin"] == "2026-10-25" and sourcee["faits"][0]["fait_id"] in {
        f["fait_id"] for f in reg_signaux.charger(stockage.maillons(*reg_signaux.REGISTRE))} and fait_id
    assert {x["regle"] for x in rec["non_evaluables"]} == {"GEO-01", "GEO-03", "GEO-04", "GEO-05", "GEO-06"}
    # avec la politique et le fichier robots : GEO-01 devient évaluable
    rec2 = geo_outils.recommander_contenu_geo(HORO, "User-agent: OAI-SearchBot\nDisallow: /\n", 200, POLITIQUE)
    assert "bloque|OAI-SearchBot" in {x["cle"] for x in rec2["recommandations"]}
    assert geo_outils.recommander_contenu_geo(HORO, "", None,
        POLITIQUE)["refus"][0]["code"] == "REJ-GEO-POLITIQUE-ABSENTE"
    # horodatage sans fuseau : refus
    assert geo_outils.recommander_contenu_geo("2026-11-01T12:00:00")["accepte"] is False


def test_importer_par_l_outil_refuse_une_source_hors_liste_et_un_horodatage_sans_fuseau(base):
    r = geo_outils.importer_signaux_manuel("inconnue", "principal", "pages_periode", MAPPING_PAGES, True, HORO,
                                           csv_texte="a\n1\n")
    assert r["accepte"] is False and r["refus"][0]["code"] == "REJ-SIGNAUX-SOURCE-INCONNUE"
    r = geo_outils.importer_signaux_manuel("search_console", "principal", "pages_periode", MAPPING_PAGES, True,
                                           "2026-11-01T12:00:00", csv_texte="a\n1\n")
    assert r["accepte"] is False


def test_proposition_par_l_outil_avec_le_controle_de_marques_reel_de_la_veille(base):
    journal = stockage.maillons(*reg_veille.REGISTRE)
    ack = reg_veille.declarer(journal, "toitures-rivales", "Toitures Rivales", "toitures-rivales.example",
                              [{"url": "https://toitures-rivales.example/", "nature": "site_officiel"}], [], "nathan",
                              "2026-10-31T00:00:00Z")
    assert ack["accepte"], ack
    op_ok = {"op": "remplacer_texte", "cible": "page.titre", "id": "services",
             "valeur": {"fr-CA": "Services de revêtement et de gouttières à Laval", "en-CA": "Siding and gutter "
                                                                                             "services"}}
    ok = geo_outils.proposer_changement_site([op_ok], "2026-11-02", HORO, schema_demo="revetements-horizon-fictif")
    assert ok["accepte"] and ok["avertissements"] == [] and ok["etat"] == "BROUILLON"
    op_marque = {**op_ok, "valeur": {"fr-CA": "Mieux que Toitures Rivales à Laval", "en-CA": "Better than Toitures "
                                                                                             "Rivales"}}
    refus = geo_outils.proposer_changement_site([op_marque], "2026-11-02", HORO,
        schema_demo="revetements-horizon-fictif")
    assert refus["accepte"] is False and {x["code"] for x in refus["refus"]} == {"REJ-VEILLE-MARQUE-CONCURRENT"}
    lu = geo_outils.lire_propositions_site()
    assert lu["total"] == 1 and lu["propositions"][0]["proposition_id"] == ok["proposition_id"]
    detail = geo_outils.lire_propositions_site(ok["proposition_id"])
    assert detail["proposition"]["operations"] == [op_ok]
    assert geo_outils.retirer_proposition_site(ok["proposition_id"], "obsolète", HORO)["deja_retiree"] is False
    assert geo_outils.lire_propositions_site(etat="RETIREE")["total"] == 1
    # une source de schéma exactement : ni les deux, ni aucune
    assert geo_outils.proposer_changement_site([op_ok], "2026-11-02", HORO)["accepte"] is False
    assert geo_outils.proposer_changement_site([op_ok], "2026-11-02", HORO, schema={"a": 1},
                                               schema_demo="revetements-horizon-fictif")["accepte"] is False
    assert proposition_site.REGISTRE == geo_outils.REGISTRE_PROPOSITIONS


def test_aucune_sortie_d_outil_ne_porte_de_secret_ni_d_ip(base):
    ligne = LIGNE_GPT
    sortie = json.dumps(geo_outils.analyser_journaux_robots_ia(ligne))
    assert "203.0.113.9" not in sortie


INTERDITS = {"socket", "http", "urllib3", "requests", "httpx", "aiohttp", "smtplib", "ftplib", "subprocess", "ssl",
             "telnetlib", "openai", "litellm", "anthropic", "playwright", "selenium", "googleapiclient", "tweepy",
             "facebook"}


@pytest.mark.parametrize("source", sorted([*(RACINE_SRC / "geo").glob("*.py"), RACINE_SRC / "geo_outils.py",
                                            RACINE_SRC / "signaux" / "import_manuel.py"]), ids=lambda p: p.name)
def test_aucun_import_reseau_ni_acces_dynamique_dans_le_volet_geo(source):
    arbre = ast.parse(source.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            noms = [a.name for a in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level:
            noms = [noeud.module]
        else:
            noms = []
        for nom in noms:
            assert nom.split(".")[0] not in INTERDITS and nom != "urllib.request", (source.name, nom)
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"open", "eval", "exec", "__import__", "compile"}, (source.name, noeud.id)
    texte = source.read_text(encoding="utf-8")
    assert "os.environ" not in texte and "getenv" not in texte


def test_les_moteurs_d_interface_n_apparaissent_dans_aucun_module_comme_moteur_permis():
    texte = (RACINE_SRC / "geo" / "panel.py").read_text(encoding="utf-8")
    bloc = texte[texte.index("MOTEURS: Mapping"):texte.index("SOURCE_MOTEURS")]
    for interdit in ("chatgpt.com", "gemini.google.com", "perplexity.ai", "_ui", "_web\"", "aio"):
        assert interdit not in bloc
