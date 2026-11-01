"""Journaux d'accès : décomptes exacts, aucune IP, bornes, ReDoS, plages publiées (adresses RFC 5737/3849)."""

from __future__ import annotations

import json
import time

import pytest
from m7_marketing.geo import journaux_bots
from m7_marketing.geo.journaux_bots import PlagesDeclarees, analyser_journaux, lignes_visites
from m7_marketing.geo.robots_ia import ErreurGeo

UA_OAI = "Mozilla/5.0 AppleWebKit/537.36 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"
UA_GPT = "Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)"
UA_HUMAIN = "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"


def combined(ip, horodatage, requete, statut, ua, referent="-"):
    return f'{ip} - - [{horodatage}] "{requete}" {statut} 512 "{referent}" "{ua}"'


JOURNAL = "\n".join([
    combined("203.0.113.10", "31/Oct/2026:12:00:01 +0000", "GET /services/gouttieres?x=1 HTTP/1.1", 200, UA_OAI),
    combined("203.0.113.10", "31/Oct/2026:12:00:05 +0000", "GET /services/revetement HTTP/1.1", 200, UA_OAI),
    combined("203.0.113.11", "31/Oct/2026:23:30:00 -0400", "GET /a-propos HTTP/1.1", 404, UA_OAI),  # 1er nov. UTC
    combined("198.51.100.7", "31/Oct/2026:12:10:00 +0000", "GET / HTTP/1.1", 301, UA_GPT),
    combined("192.0.2.55", "31/Oct/2026:12:11:00 +0000", "GET /blogue/jean.tremblay@exemple.test HTTP/1.1", 500,
        UA_GPT),
    combined("192.0.2.99", "31/Oct/2026:12:12:00 +0000", "GET / HTTP/1.1", 200, UA_HUMAIN),
    "ceci n'est pas une ligne de journal",
    '2001:db8::1 - - [01/Nov/2026:00:00:00 +0000] "GET /faq HTTP/2.0" 200 100',  # format common : pas d'agent
])


def test_decomptes_exacts_par_robot_jour_utc_statut_et_groupe():
    r = analyser_journaux(JOURNAL)
    assert r["lignes"] == {"total": 8, "lisibles": 7, "illisibles": 1, "sans_agent": 1, "autres_agents": 1}
    oai = next(x for x in r["robots"] if x["robot"] == "OAI-SearchBot")
    assert oai["total"] == 3 and oai["categorie"] == "recherche"
    assert oai["par_jour"] == {"2026-10-31": 2, "2026-11-01": 1}  # 23 h 30 à -0400 est le lendemain en UTC
    assert oai["par_statut"] == {"2xx": 2, "4xx": 1}
    assert oai["par_groupe_chemin"] == {"/a-propos": 1, "/services": 2}
    gpt = next(x for x in r["robots"] if x["robot"] == "GPTBot")
    assert gpt["total"] == 2 and gpt["par_statut"] == {"3xx": 1, "5xx": 1}
    assert gpt["categorie"] == "entrainement"
    assert r["periode"] == {"debut": "2026-10-31", "fin": "2026-11-01"}
    assert r["jours_couverts"] == {"2026-10-31": 5, "2026-11-01": 2}


def test_aucune_adresse_ip_ni_chaine_de_requete_ni_courriel_dans_la_sortie():
    sortie = json.dumps(analyser_journaux(JOURNAL), ensure_ascii=False)
    for ip in ("203.0.113.10", "203.0.113.11", "198.51.100.7", "192.0.2.55", "192.0.2.99", "2001:db8"):
        assert ip not in sortie
    assert "x=1" not in sortie and "?" not in sortie.replace("?>", "")
    assert "jean.tremblay@exemple.test" not in sortie  # le segment de chemin est ramené au premier niveau
    assert "/blogue" in sortie


def test_sans_plages_chaque_decompte_est_agent_seulement():
    r = analyser_journaux(JOURNAL)
    assert all(x["verification"] == "agent_seulement" for x in r["robots"]) and r["plages"] is None
    assert any("se falsifie" in a for a in r["avertissements"])


def test_avec_plages_publiees_l_appartenance_est_calculee_puis_l_ip_est_jetee():
    plages = PlagesDeclarees({"OAI-SearchBot": ["203.0.113.0/28"], "GPTBot": ["198.51.100.0/24"]},
                             source="page publiée de l'éditeur (copie fictive)", date="2026-10-30")
    r = analyser_journaux(JOURNAL, plages)
    oai = next(x for x in r["robots"] if x["robot"] == "OAI-SearchBot")
    assert oai["verification"] == {"mode": "ip_verifiee", "ip_verifiees": 3, "ip_non_verifiees": 0, "ip_illisibles": 0}
    gpt = next(x for x in r["robots"] if x["robot"] == "GPTBot")
    assert gpt["verification"]["ip_verifiees"] == 1 and gpt["verification"]["ip_non_verifiees"] == 1
    assert r["plages"] == {"source": "page publiée de l'éditeur (copie fictive)", "date": "2026-10-30"}
    sortie = json.dumps(r)
    assert "203.0.113" not in sortie and "198.51.100" not in sortie


def test_un_robot_sans_plage_connue_n_est_jamais_verifie():
    plages = PlagesDeclarees({"GPTBot": ["198.51.100.0/24"]}, source="s", date="2026-10-30")
    oai = next(x for x in analyser_journaux(JOURNAL, plages)["robots"] if x["robot"] == "OAI-SearchBot")
    assert oai["verification"]["ip_verifiees"] == 0 and oai["verification"]["ip_non_verifiees"] == 3


def test_ip_illisible_comptee_a_part():
    ligne = combined("pas-une-ip", "31/Oct/2026:12:00:01 +0000", "GET / HTTP/1.1", 200, UA_GPT)
    plages = PlagesDeclarees({"GPTBot": ["198.51.100.0/24"]}, source="s", date="2026-10-30")
    gpt = analyser_journaux(ligne, plages)["robots"][0]
    assert gpt["verification"]["ip_illisibles"] == 1 and gpt["verification"]["ip_verifiees"] == 0


@pytest.mark.parametrize("plages,source,date,code", [
    ({"GPTBot": ["198.51.100.0/24"]}, "", "2026-10-30", "REJ-GEO-PLAGES-SANS-SOURCE"),
    ({"GPTBot": ["198.51.100.0/24"]}, "s", " ", "REJ-GEO-PLAGES-SANS-SOURCE"),
    ({"RobotInconnu": ["198.51.100.0/24"]}, "s", "d", "REJ-GEO-PLAGES-ROBOT-INCONNU"),
    ({"GPTBot": ["pas-un-cidr"]}, "s", "d", "REJ-GEO-PLAGES-INVALIDES"),
])
def test_des_plages_sans_source_ou_invalides_sont_refusees(plages, source, date, code):
    with pytest.raises(ErreurGeo) as exc:
        PlagesDeclarees(plages, source=source, date=date)
    assert exc.value.code == code


def test_lignes_illisibles_sont_comptees_jamais_devinees():
    mauvaises = [
        "", "   ", "1.2.3.4", "1.2.3.4 - - [pas une date] \"GET / HTTP/1.1\" 200 1",
        '1.2.3.4 - - [31/Oct/2026:12:00:01 +0000] "GET / HTTP/1.1" abc 1 "-" "GPTBot"',
        '1.2.3.4 - - [31/Oct/2026:12:00:01 +0000] "GET sans-barre HTTP/1.1" 200 1 "-" "GPTBot"',
        '1.2.3.4 - - [31/Oct/2026:12:00:01 +0000] "GET / HTTP/1.1',
        '1.2.3.4 - - [31/Xyz/2026:12:00:01 +0000] "GET / HTTP/1.1" 200 1 "-" "GPTBot"',
        '1.2.3.4 - - [31/Oct/2026:12:00:01 0000] "GET / HTTP/1.1" 200 1 "-" "GPTBot"',
    ]
    r = analyser_journaux("\n".join(mauvaises))
    assert r["lignes"]["lisibles"] == 0 and r["lignes"]["illisibles"] == 7 and r["robots"] == []


def test_agent_avec_guillemet_echappe_est_lu():
    ligne = '1.2.3.4 - - [31/Oct/2026:12:00:01 +0000] "GET / HTTP/1.1" 200 1 "-" "x \\" GPTBot/1.1"'
    assert analyser_journaux(ligne)["robots"][0]["robot"] == "GPTBot"


def test_url_absolue_dans_la_requete_est_reduite_a_son_chemin():
    ligne = combined("1.2.3.4", "31/Oct/2026:12:00:01 +0000", "GET https://exemple.test/services/x?a=b HTTP/1.1", 200,
        UA_GPT)
    assert analyser_journaux(ligne)["robots"][0]["par_groupe_chemin"] == {"/services": 1}


def test_le_robot_le_plus_specifique_gagne():
    ligne = combined("1.2.3.4", "31/Oct/2026:12:00:01 +0000", "GET / HTTP/1.1", 200,
                     "Mozilla/5.0 (compatible; Perplexity-User/1.0; PerplexityBot/1.0)")
    robots = [x["robot"] for x in analyser_journaux(ligne)["robots"]]
    assert robots == ["Perplexity-User"]


def test_bornes_octets_et_lignes_jamais_tronquees_en_silence():
    with pytest.raises(ErreurGeo) as exc:
        analyser_journaux("a" * (journaux_bots.OCTETS_MAX + 1))
    assert exc.value.code == "REJ-GEO-JOURNAL-TROP-GROS"
    with pytest.raises(ErreurGeo) as exc:
        analyser_journaux("\n" * (journaux_bots.LIGNES_MAX + 1))
    assert exc.value.code == "REJ-GEO-JOURNAL-TROP-GROS"
    juste = "\n".join([combined("1.2.3.4", "31/Oct/2026:12:00:01 +0000", "GET / HTTP/1.1", 200, UA_GPT)] * 1000)
    assert analyser_journaux(juste)["robots"][0]["total"] == 1000
    with pytest.raises(ErreurGeo):
        analyser_journaux(None)


def test_ligne_geante_d_un_mega_octet_est_rejetee_sans_regex_en_moins_d_une_seconde():
    geante = '1.2.3.4 - - [31/Oct/2026:12:00:01 +0000] "GET /' + "a" * 1_000_000 + ' HTTP/1.1" 200 1 "-" "GPTBot"'
    pathologique = '1.2.3.4 - - [' + "[" * 400_000 + '" ' + '\\' * 100_000
    debut = time.perf_counter()
    r = analyser_journaux(geante + "\n" + pathologique + "\n" + JOURNAL)
    assert time.perf_counter() - debut < 1.0
    assert r["lignes"]["illisibles"] == 3  # les deux géantes + la ligne absurde du jeu
    assert next(x for x in r["robots"] if x["robot"] == "GPTBot")["total"] == 2


def test_groupes_de_chemins_bornes_et_assainis():
    lignes = [combined("1.2.3.4", "31/Oct/2026:12:00:01 +0000", f"GET /dossier{i}/x HTTP/1.1", 200, UA_GPT)
              for i in range(60)]
    lignes.append(combined("1.2.3.4", "31/Oct/2026:12:00:01 +0000", "GET /a b%20c<script>/x HTTP/1.1", 200, UA_GPT))
    gpt = analyser_journaux("\n".join(lignes))["robots"][0]
    assert len(gpt["par_groupe_chemin"]) <= journaux_bots.GROUPES_MAX_PAR_ROBOT + 1
    assert gpt["par_groupe_chemin"]["(autres)"] >= 10


def test_lignes_visites_couverture_par_jour_et_ligne_par_robot_et_jour():
    plages = PlagesDeclarees({"OAI-SearchBot": ["203.0.113.0/28"]}, source="s", date="d")
    lignes = lignes_visites(analyser_journaux(JOURNAL, plages))
    couverture = [x for x in lignes if x["robot"] == "journal_couverture"]
    assert {x["jour"]: x["lignes_lues"] for x in couverture} == {"2026-10-31": 5, "2026-11-01": 2}
    oai = [x for x in lignes if x["robot"] == "OAI-SearchBot"]
    assert {x["jour"]: (x["visites"], x["ip_verifiees"], x["ok_2xx"], x["erreurs_4xx"]) for x in oai} == {
        "2026-10-31": (2, 2, 2, 0), "2026-11-01": (1, 1, 0, 1)}
