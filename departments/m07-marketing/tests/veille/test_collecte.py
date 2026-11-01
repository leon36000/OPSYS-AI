"""Le collecteur de sources publiques : robots d'abord, jamais de page interdite, redirections revalidées, aucun
contournement.

Tout passe par `DoubleSitePublic`, qui journalise chaque requête (URL, agent) : l'ordre et l'absence de toute requête
interdite sont PROUVÉS par ce journal, pas supposés. Rien n'est collecté chez un vrai site.
"""

from __future__ import annotations

import inspect

import pytest
from fabriques_veille import (
    ACCUEIL,
    AUTRE_HOTE,
    COMMUNIQUE,
    HOTE,
    PLAN,
    SERVICES,
    Horloge,
    collecteur,
    declarer_horizon,
    masqueur,
    site_horizon,
)
from m7_marketing.veille import collecte, doubles, observations, registre
from m7_marketing.veille.registre import ErreurVeille

ROBOTS = f"https://{HOTE}/robots.txt"


def _code(fn, *args):
    with pytest.raises(ErreurVeille) as exc:
        fn(*args)
    return exc.value


def _conc(**options):
    journal = []
    return declarer_horizon(journal, **options)


# -- le port
# --------------------------------------------------------------------------------------------------------------
def test_le_port_ne_connait_que_l_url_et_l_agent():
    assert list(inspect.signature(collecte.TransportPublic.obtenir).parameters) == [
        "self", "url", "agent_utilisateur", "delai_s"]
    assert list(inspect.signature(collecte.TransportPublicNonBranche.obtenir).parameters) == [
        "self", "url", "agent_utilisateur", "delai_s"]
    assert {f.name for f in __import__("dataclasses").fields(collecte.ReponsePublique)} == {
        "statut", "en_tetes", "corps", "url_finale"}


def test_sans_transport_la_collecte_est_un_refus_type_et_rien_ne_part():
    c = collecte.Collecteur(concurrents=_conc(), maintenant=Horloge(), masqueur=masqueur())
    erreur = _code(c.collecter_url, ACCUEIL)
    assert erreur.code == "REJ-VEILLE-TRANSPORT-NON-BRANCHE" and erreur.reprenable is False
    assert isinstance(c._transport, collecte.TransportPublicNonBranche)
    assert c.pages_demandees == 0


def test_le_collecteur_exige_un_masqueur():
    with pytest.raises(ErreurVeille) as exc:
        collecte.Collecteur(doubles.DoubleSitePublic(), concurrents=_conc(), maintenant=Horloge(), masqueur=None)
    assert exc.value.code == "REJ-VEILLE-ARGUMENT-INVALIDE"


# -- liste blanche et ordre robots -> page
# ------------------------------------------------------------------------------
def test_robots_est_demande_avant_la_page_une_seule_fois_par_hote():
    d = site_horizon()
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    c.collecter_url(ACCUEIL)
    c.collecter_url(SERVICES)
    assert d.urls_demandees() == [ROBOTS, ACCUEIL, SERVICES]
    assert {r["agent"] for r in d.requetes} == {collecte.AGENT_UTILISATEUR}
    assert set(d.requetes[0]) == {"url", "agent"}


def test_une_url_non_declaree_est_refusee_sans_aucune_requete():
    d = site_horizon()
    c, _ = collecteur(d, _conc())
    for url in (f"https://{HOTE}/non-declaree", "https://autre.example/", ROBOTS, f"{ACCUEIL}?x=1",
        "http://www.horizon.example/"):
        assert _code(c.collecter_url, url).code == "REJ-VEILLE-SOURCE-NON-DECLAREE"
    assert d.requetes == []


def test_un_concurrent_retire_n_est_plus_collecte():
    journal = []
    declarer_horizon(journal)
    registre.retirer(journal, "horizon", "gestion", "x", "2026-10-02T00:00:00Z")
    d = site_horizon()
    c, _ = collecteur(d, registre.plier(journal))
    assert _code(c.collecter_url, ACCUEIL).code == "REJ-VEILLE-SOURCE-NON-DECLAREE"
    assert d.requetes == []


def test_une_page_interdite_par_robots_n_est_jamais_demandee():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nDisallow: /services\n")
    c, _ = collecteur(d, _conc())
    erreur = _code(c.collecter_url, SERVICES)
    assert erreur.code == "REJ-VEILLE-ROBOTS-INTERDIT" and erreur.reprenable is False
    assert SERVICES not in d.urls_demandees() and d.urls_demandees() == [ROBOTS]
    assert c.collecter_url(ACCUEIL)["acces"] == "ok"  # l'interdiction est par chemin


def test_le_groupe_de_notre_agent_prime_sur_l_etoile():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nDisallow: /\nUser-agent: OpsysVeille\nAllow: /\nDisallow: /services\n")
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    assert c.collecter_url(ACCUEIL)["acces"] == "ok"
    assert _code(c.collecter_url, SERVICES).code == "REJ-VEILLE-ROBOTS-INTERDIT"


@pytest.mark.parametrize("statut", [500, 502, 503, 401, 403])
def test_robots_inaccessible_ou_protege_interdit_tout(statut):
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nAllow: /\n", statut=statut)
    c, _ = collecteur(d, _conc())
    assert _code(c.collecter_url, ACCUEIL).code == "REJ-VEILLE-ROBOTS-INTERDIT"
    assert d.urls_demandees() == [ROBOTS]


def test_robots_qui_depasse_le_delai_interdit_tout():
    d = site_horizon()
    d.ajouter(ROBOTS, delai=True)
    c, _ = collecteur(d, _conc())
    assert _code(c.collecter_url, ACCUEIL).code == "REJ-VEILLE-ROBOTS-INTERDIT"
    assert d.urls_demandees() == [ROBOTS]


def test_robots_introuvable_4xx_permet_la_collecte():
    d = site_horizon()
    d.robots(HOTE, "", statut=404)
    c, _ = collecteur(d, _conc())
    assert c.collecter_url(ACCUEIL)["acces"] == "ok"
    assert d.urls_demandees() == [ROBOTS, ACCUEIL]


def test_robots_redirige_dans_l_hote_est_suivi_mais_hors_hote_interdit_tout():
    d = site_horizon()
    d.redirection(ROBOTS, f"https://{HOTE}/politique/robots.txt")
    d.ajouter(f"https://{HOTE}/politique/robots.txt", "User-agent: *\nDisallow: /\n", type_contenu="text/plain")
    c, _ = collecteur(d, _conc())
    assert _code(c.collecter_url, ACCUEIL).code == "REJ-VEILLE-ROBOTS-INTERDIT"  # le fichier suivi interdit tout

    d2 = site_horizon()
    d2.redirection(ROBOTS, "https://serveur-tiers.example/robots.txt")
    d2.ajouter("https://serveur-tiers.example/robots.txt", "User-agent: *\nAllow: /\n", type_contenu="text/plain")
    c2, _ = collecteur(d2, _conc())
    assert _code(c2.collecter_url, ACCUEIL).code == "REJ-VEILLE-ROBOTS-INTERDIT"
    assert "https://serveur-tiers.example/robots.txt" not in d2.urls_demandees()


# -- redirections
# -------------------------------------------------------------------------------------------------------
def test_redirection_dans_le_domaine_suivie_et_robots_revalide_a_chaque_saut():
    d = site_horizon()
    d.redirection(SERVICES, f"https://{HOTE}/nos-services")
    d.ajouter(f"https://{HOTE}/nos-services", doubles.page_html(titre="Nos services"))
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    obs = c.collecter_url(SERVICES)
    assert obs["url"] == SERVICES and obs["titre"] == "Nos services" and obs["statut_http"] == 200
    assert d.urls_demandees() == [ROBOTS, SERVICES, f"https://{HOTE}/nos-services"]


def test_redirection_vers_un_chemin_interdit_par_robots_est_refusee():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nDisallow: /prive\n")
    d.redirection(SERVICES, f"https://{HOTE}/prive/espace")
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    assert _code(c.collecter_url, SERVICES).code == "REJ-VEILLE-ROBOTS-INTERDIT"
    assert f"https://{HOTE}/prive/espace" not in d.urls_demandees()


@pytest.mark.parametrize(
    "destination",
    ["https://concurrent-tiers.example/", "https://www.facebook.com/horizon", "http://www.horizon.example/",
     "https://usager:mdp@www.horizon.example/", "https://127.0.0.1/", "https://www.horizon.example:8443/",
     "https://www.horizon.example/?token=abc", "https://horizon.example.evil.example/"],
)
def test_redirection_hors_domaine_ou_interdite_refusee_et_jamais_demandee(destination):
    d = site_horizon()
    d.redirection(SERVICES, destination)
    d.ajouter(destination, doubles.page_html())
    c, _ = collecteur(d, _conc())
    assert _code(c.collecter_url, SERVICES).code == "REJ-VEILLE-REDIRECTION-HORS-DOMAINE"
    assert destination not in d.urls_demandees()


def test_trois_sauts_passent_le_quatrieme_est_refuse():
    d = site_horizon()
    chemin = [SERVICES] + [f"https://{HOTE}/s{i}" for i in range(1, 6)]
    for a, b in zip(chemin, chemin[1:], strict=False):
        d.redirection(a, b)
    d.ajouter(chemin[3], doubles.page_html(titre="Arrivée"))  # SERVICES -> s1 -> s2 -> s3 : trois sauts
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    assert c.collecter_url(SERVICES)["titre"] == "Arrivée"
    d2 = site_horizon()
    for a, b in zip(chemin, chemin[1:], strict=False):
        d2.redirection(a, b)
    c2, _ = collecteur(d2, _conc(), delai_min_s=0)
    assert _code(c2.collecter_url, SERVICES).code == "REJ-VEILLE-REDIRECTION-TROP-LONGUE"
    assert chemin[4] not in d2.urls_demandees()


def test_boucle_de_redirections_refusee():
    d = site_horizon()
    d.redirection(SERVICES, f"https://{HOTE}/boucle")
    d.redirection(f"https://{HOTE}/boucle", SERVICES)
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    assert _code(c.collecter_url, SERVICES).code == "REJ-VEILLE-REDIRECTION-TROP-LONGUE"


def test_redirection_sans_destination_refusee():
    d = site_horizon()
    d.ajouter(SERVICES, b"", statut=302, type_contenu=None)
    c, _ = collecteur(d, _conc())
    assert _code(c.collecter_url, SERVICES).code == "REJ-VEILLE-REPONSE-INVALIDE"


def test_redirection_relative_resolue_dans_l_hote():
    d = site_horizon()
    d.redirection(SERVICES, "/ailleurs")
    d.ajouter(f"https://{HOTE}/ailleurs", doubles.page_html(titre="Ailleurs"))
    c, _ = collecteur(d, _conc(), delai_min_s=0)
    assert c.collecter_url(SERVICES)["titre"] == "Ailleurs"


def test_hote_additionnel_declare_peut_etre_collecte_avec_son_propre_robots():
    d = site_horizon()
    d.robots(AUTRE_HOTE, "User-agent: *\nAllow: /\n")
    d.ajouter(COMMUNIQUE, doubles.page_html(titre="Communiqué"))
    sources = [{"url": ACCUEIL, "nature": "site_officiel"}, {"url": COMMUNIQUE, "nature": "communique"}]
    c, _ = collecteur(d, _conc(sources=sources, additionnels=[AUTRE_HOTE]), delai_min_s=0)
    assert c.collecter_url(COMMUNIQUE)["titre"] == "Communiqué"
    assert d.urls_demandees() == [f"https://{AUTRE_HOTE}/robots.txt", COMMUNIQUE]


# -- délais
# -----------------------------------------------------------------------------------------------------------------
def test_delai_minimal_par_hote_refuse_plutot_que_dormir():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nAllow: /\n")
    c, h = collecteur(d, _conc())
    c.collecter_url(ACCUEIL)
    h.avancer(seconds=4)
    erreur = _code(c.collecter_url, SERVICES)
    assert erreur.code == "REJ-VEILLE-DELAI-NON-ECOULE" and erreur.reprenable is True and erreur.reessayer_apres_s == 6
    assert SERVICES not in d.urls_demandees()
    h.avancer(seconds=6)
    assert c.collecter_url(SERVICES)["acces"] == "ok"


def test_crawl_delay_de_robots_prime_s_il_est_plus_long():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nCrawl-delay: 45\n")
    c, h = collecteur(d, _conc())
    c.collecter_url(ACCUEIL)
    h.avancer(seconds=30)
    assert _code(c.collecter_url, SERVICES).reessayer_apres_s == 15
    h.avancer(seconds=15)
    assert c.collecter_url(SERVICES)["acces"] == "ok"


def test_crawl_delay_plus_court_que_le_minimum_ne_l_abaisse_pas():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nCrawl-delay: 1\n")
    c, h = collecteur(d, _conc())
    c.collecter_url(ACCUEIL)
    h.avancer(seconds=2)
    assert _code(c.collecter_url, SERVICES).code == "REJ-VEILLE-DELAI-NON-ECOULE"


def test_le_delai_ne_se_compte_pas_entre_deux_hotes_differents():
    d = site_horizon()
    d.robots(AUTRE_HOTE, "User-agent: *\nAllow: /\n")
    d.ajouter(COMMUNIQUE, doubles.page_html(titre="Communiqué"))
    sources = [{"url": ACCUEIL, "nature": "site_officiel"}, {"url": COMMUNIQUE, "nature": "communique"}]
    c, _ = collecteur(d, _conc(sources=sources, additionnels=[AUTRE_HOTE]))
    c.collecter_url(ACCUEIL)
    assert c.collecter_url(COMMUNIQUE)["titre"] == "Communiqué"


# -- réponses
# --------------------------------------------------------------------------------------------------------------
def test_401_et_403_donnent_un_fait_acces_refuse_sans_contournement_ni_second_essai():
    for statut in (401, 403):
        d = site_horizon()
        d.ajouter(SERVICES, "Accès réservé", statut=statut, type_contenu="text/html")
        c, _ = collecteur(d, _conc())
        obs = c.collecter_url(SERVICES)
        assert obs["acces"] == "acces_refuse" and obs["statut_http"] == statut and obs["empreinte_contenu"] is None
        assert obs["titre"] is None and obs["h1"] == [] and obs["nb_mots"] is None
        assert d.urls_demandees().count(SERVICES) == 1 and d.urls_demandees() == [ROBOTS, SERVICES]
        assert {r["agent"] for r in d.requetes} == {collecte.AGENT_UTILISATEUR}


@pytest.mark.parametrize("statut", [404, 410])
def test_page_absente_est_un_fait(statut):
    d = site_horizon()
    d.ajouter(SERVICES, b"", statut=statut)
    c, _ = collecteur(d, _conc())
    obs = c.collecter_url(SERVICES)
    assert obs["acces"] == "absent" and obs["statut_http"] == statut


def test_429_et_5xx_sont_des_echecs_reprenables_avec_delai():
    d = site_horizon()
    d.ajouter(SERVICES, b"", statut=429, en_tetes={"Retry-After": "17"})
    c, _ = collecteur(d, _conc())
    e = _code(c.collecter_url, SERVICES)
    assert (e.code, e.reprenable, e.reessayer_apres_s) == ("REJ-VEILLE-FOURNISSEUR-INDISPONIBLE", True, 17)
    d.ajouter(ACCUEIL, b"", statut=429)
    assert _code(collecteur(d, _conc())[0].collecter_url, ACCUEIL).reessayer_apres_s == 300
    d.ajouter(PLAN, b"", statut=503)
    assert _code(collecteur(d, _conc())[0].collecter_url, PLAN).reessayer_apres_s == 600
    d.ajouter(PLAN + "x", b"")
    d3 = site_horizon()
    d3.ajouter(SERVICES, b"", statut=500, en_tetes={"Retry-After": "999999"})
    assert _code(collecteur(d3, _conc())[0].collecter_url, SERVICES).reessayer_apres_s == 86400
    d4 = site_horizon()
    d4.ajouter(SERVICES, b"", statut=500, en_tetes={"Retry-After": "bientot"})
    assert _code(collecteur(d4, _conc())[0].collecter_url, SERVICES).reessayer_apres_s == 600


def test_statut_inattendu_refuse():
    d = site_horizon()
    d.ajouter(SERVICES, b"", statut=418)
    assert _code(collecteur(d, _conc())[0].collecter_url, SERVICES).code == "REJ-VEILLE-REPONSE-INVALIDE"


def test_delai_http_depasse_est_un_echec_reprenable_sans_le_texte_de_l_exception():
    d = site_horizon()
    d.ajouter(SERVICES, delai=True)
    e = _code(collecteur(d, _conc())[0].collecter_url, SERVICES)
    assert (e.code, e.reprenable) == ("REJ-VEILLE-RESEAU", True)
    d2 = site_horizon()
    d2.ajouter(SERVICES, exception=RuntimeError("secret-interne-xyz 10.0.0.5"))
    e2 = _code(collecteur(d2, _conc())[0].collecter_url, SERVICES)
    assert e2.code == "REJ-VEILLE-RESEAU" and "secret-interne" not in str(e2) and "10.0.0.5" not in str(e2)


def test_reponse_de_transport_illisible_refusee():
    class Faux:
        def obtenir(self, url, agent_utilisateur, delai_s):
            return "pas une réponse"

    c = collecte.Collecteur(Faux(), concurrents=_conc(), maintenant=Horloge(), masqueur=masqueur())
    assert _code(c.collecter_url, ACCUEIL).code == "REJ-VEILLE-ROBOTS-INTERDIT"  # robots illisible : tout interdit

    class FauxPage(Faux):
        def obtenir(self, url, agent_utilisateur, delai_s):
            if url.endswith("robots.txt"):
                return collecte.ReponsePublique(404)
            return collecte.ReponsePublique("200", {}, "texte")  # type: ignore[arg-type]

    c2 = collecte.Collecteur(FauxPage(), concurrents=_conc(), maintenant=Horloge(), masqueur=masqueur())
    assert _code(c2.collecter_url, ACCUEIL).code == "REJ-VEILLE-REPONSE-INVALIDE"


@pytest.mark.parametrize("type_contenu", ["image/png", "application/pdf", "application/json",
    "application/octet-stream",
                                          "text/css", "application/javascript", "", None])
def test_types_de_contenu_non_permis_refuses(type_contenu):
    d = site_horizon()
    d.ajouter(SERVICES, b"contenu", type_contenu=type_contenu)
    assert _code(collecteur(d, _conc())[0].collecter_url, SERVICES).code == "REJ-VEILLE-TYPE-CONTENU"


@pytest.mark.parametrize("type_contenu", ["text/html", "TEXT/HTML; charset=ISO-8859-1", "application/xhtml+xml",
                                          "application/xml", "text/xml", "text/plain"])
def test_types_de_contenu_permis(type_contenu):
    d = site_horizon()
    d.ajouter(SERVICES, doubles.page_html(titre="Ok"), type_contenu=type_contenu)
    assert collecteur(d, _conc())[0].collecter_url(SERVICES)["acces"] == "ok"


def test_taille_limite_a_un_mio_pile_passe_un_octet_de_plus_est_refuse():
    d = site_horizon()
    pile = doubles.page_html(corps="x") + b" " * (collecte.OCTETS_MAX - len(doubles.page_html(corps="x")))
    assert len(pile) == collecte.OCTETS_MAX
    d.ajouter(SERVICES, pile)
    assert collecteur(d, _conc())[0].collecter_url(SERVICES)["acces"] == "ok"
    d2 = site_horizon()
    d2.ajouter(SERVICES, pile + b" ")
    assert _code(collecteur(d2, _conc())[0].collecter_url, SERVICES).code == "REJ-VEILLE-REPONSE-TROP-GROSSE"


def test_content_length_annonce_trop_grand_refuse_meme_si_le_corps_est_petit():
    d = site_horizon()
    d.ajouter(SERVICES, b"<html></html>", en_tetes={"Content-Length": str(collecte.OCTETS_MAX + 1)})
    assert _code(collecteur(d, _conc())[0].collecter_url, SERVICES).code == "REJ-VEILLE-REPONSE-TROP-GROSSE"


def test_octets_invalides_sont_remplaces_jamais_une_panne():
    d = site_horizon()
    d.ajouter(SERVICES, b"<html><head><title>Caf\xe9 \xff</title></head><body><h1>Bonjour</h1></body></html>")
    obs = collecteur(d, _conc())[0].collecter_url(SERVICES)
    assert obs["titre"].startswith("Caf") and "�" in obs["titre"] and obs["h1"] == ["Bonjour"]


def test_le_contenu_n_est_jamais_execute_ni_compte_comme_texte():
    d = site_horizon()
    d.ajouter(SERVICES, b"<html><head><title>T</title><script>import os; "
                        b"os.system('x')</script><style>p{}</style></head>"
              b"<body><p>un deux trois</p><script>ignore ceci tout</script><noscript>et cela</noscript></body></html>")
    obs = collecteur(d, _conc())[0].collecter_url(SERVICES)
    assert obs["nb_mots"] == 3


def test_limite_de_pages_par_tour():
    d = site_horizon()
    c, _ = collecteur(d, _conc(), delai_min_s=0, pages_max=2)
    c.collecter_url(ACCUEIL)
    c.collecter_url(SERVICES)
    e = _code(c.collecter_url, PLAN)
    assert e.code == "REJ-VEILLE-LIMITE-PAGES" and e.reprenable is True
    assert PLAN not in d.urls_demandees() and c.pages_demandees == 2


def test_l_observation_porte_les_robots_d_ia_de_l_hote():
    d = site_horizon()
    d.robots(HOTE, "User-agent: GPTBot\nDisallow: /\nUser-agent: ClaudeBot\nDisallow: /\nUser-agent: *\nAllow: /\n")
    obs = collecteur(d, _conc())[0].collecter_url(ACCUEIL)
    assert obs["robots_ia"]["gptbot"] is False and obs["robots_ia"]["claudebot"] is False
    assert obs["robots_ia"]["oai-searchbot"] is True and set(obs["robots_ia"]) == set(observations.BOTS_IA)


# -- le tour
# -------------------------------------------------------------------------------------------------------------------
def test_tour_inscrit_les_observations_et_rejouer_ne_double_pas():
    d = site_horizon()
    conc = _conc()
    c, h = collecteur(d, conc)

    def attendre(secondes):
        h.avancer(seconds=secondes)

    journal = []
    bilan = collecte.tour_veille(c, journal, concurrents=conc, maintenant=h, attendre=attendre)
    assert bilan == {"nouvelles": 3, "deja_presentes": 0, "acces_refuse": 0, "echecs": []}
    assert len(journal) == 3 and observations.charger(journal)
    c2, _ = collecteur(d, conc, h)
    bilan2 = collecte.tour_veille(c2, journal, concurrents=conc, maintenant=h, attendre=attendre)
    assert bilan2["nouvelles"] == 0 and bilan2["deja_presentes"] == 3 and len(journal) == 3


def test_tour_sans_attendre_rend_le_delai_dans_un_echec_reprenable():
    d = site_horizon()
    conc = _conc()
    c, h = collecteur(d, conc)
    journal = []
    bilan = collecte.tour_veille(c, journal, concurrents=conc, maintenant=h)
    assert bilan["nouvelles"] == 1 and len(bilan["echecs"]) == 2
    assert {e["code"] for e in bilan["echecs"]} == {"REJ-VEILLE-DELAI-NON-ECOULE"}
    assert all(e["reprenable"] and e["reessayer_apres_s"] >= 1 for e in bilan["echecs"])


def test_tour_un_echec_n_arrete_pas_les_autres_sources_et_un_refus_est_compte():
    d = site_horizon()
    d.ajouter(SERVICES, b"", statut=403)
    d.ajouter(PLAN, b"", statut=503)
    conc = _conc()
    c, h = collecteur(d, conc, delai_min_s=0)
    journal = []
    bilan = collecte.tour_veille(c, journal, concurrents=conc, maintenant=h)
    assert bilan["nouvelles"] == 2 and bilan["acces_refuse"] == 1
    assert [e["code"] for e in bilan["echecs"]] == ["REJ-VEILLE-FOURNISSEUR-INDISPONIBLE"]
    assert [o["acces"] for o in observations.charger(journal)] == ["ok", "acces_refuse"]


def test_tour_sans_transport_s_arrete_au_premier_refus():
    conc = _conc()
    c = collecte.Collecteur(concurrents=conc, maintenant=Horloge(), masqueur=masqueur())
    bilan = collecte.tour_veille(c, [], concurrents=conc, maintenant=Horloge())
    assert [e["code"] for e in bilan["echecs"]] == ["REJ-VEILLE-TRANSPORT-NON-BRANCHE"] and bilan["nouvelles"] == 0


def test_tour_n_attend_pas_plus_de_soixante_secondes():
    d = site_horizon()
    d.robots(HOTE, "User-agent: *\nCrawl-delay: 600\n")
    conc = _conc()
    c, h = collecteur(d, conc)
    attentes = []
    bilan = collecte.tour_veille(c, [], concurrents=conc, maintenant=h, attendre=attentes.append)
    assert attentes == [] and len(bilan["echecs"]) == 2
