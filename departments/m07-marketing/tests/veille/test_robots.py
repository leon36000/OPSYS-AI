"""Sémantique de `robots.txt` selon la RFC 9309 : ce que le robot déclaré a le droit de demander."""

from __future__ import annotations

import pytest
from m7_marketing.veille import robots

AGENT = "OpsysVeille/1.0"


def _ok(texte, chemin, agent=AGENT, statut=200):
    return robots.autorise(robots.analyser(texte, statut), agent, chemin)


def test_fichier_vide_ou_sans_groupe_permet_tout():
    assert _ok("", "/n-importe-quoi")
    assert _ok("# seulement un commentaire\n", "/x")
    assert _ok("Sitemap: https://www.horizon.example/sitemap.xml\n", "/x")


def test_disallow_simple_par_prefixe():
    texte = "User-agent: *\nDisallow: /prive\n"
    assert not _ok(texte, "/prive")
    assert not _ok(texte, "/prive/dossier/x.html")
    assert not _ok(texte, "/prive-aussi")  # préfixe, pas répertoire
    assert _ok(texte, "/public")
    assert _ok(texte, "/")


def test_disallow_vide_permet_tout():
    assert _ok("User-agent: *\nDisallow:\n", "/x")


def test_disallow_racine_interdit_tout():
    assert not _ok("User-agent: *\nDisallow: /\n", "/")
    assert not _ok("User-agent: *\nDisallow: /\n", "/a/b")


def test_le_chemin_le_plus_long_l_emporte():
    texte = "User-agent: *\nDisallow: /a/\nAllow: /a/b\n"
    assert _ok(texte, "/a/b/c")
    assert not _ok(texte, "/a/x")
    texte_inverse = "User-agent: *\nAllow: /a/\nDisallow: /a/b\n"
    assert not _ok(texte_inverse, "/a/b/c")
    assert _ok(texte_inverse, "/a/x")


def test_a_longueur_egale_allow_l_emporte():
    assert _ok("User-agent: *\nDisallow: /page\nAllow: /page\n", "/page")
    assert _ok("User-agent: *\nAllow: /page\nDisallow: /page\n", "/page")


@pytest.mark.parametrize(
    ("motif", "chemin", "attendu"),
    [
        ("/*.pdf$", "/docs/a.pdf", False),
        ("/*.pdf$", "/docs/a.pdf?v=1", True),  # `$` ancre la fin : la requête échappe à la règle
        ("/*.pdf$", "/docs/a.pdf.html", True),
        ("/*/tmp", "/a/b/tmp/x", False),
        ("/*/tmp", "/tmp/x", True),
        ("/fichier$", "/fichier", False),
        ("/fichier$", "/fichier2", True),
        ("/a*c", "/abbbc", False),
        ("/a*c", "/abbb", True),
        ("/*", "/quoi/que/ce/soit", False),
    ],
)
def test_jokers_etoile_et_dollar(motif, chemin, attendu):
    assert _ok(f"User-agent: *\nDisallow: {motif}\n", chemin) is attendu


def test_la_requete_fait_partie_du_chemin():
    texte = "User-agent: *\nDisallow: /recherche?q=\n"
    assert not _ok(texte, "/recherche?q=abc")
    assert _ok(texte, "/recherche")


def test_la_casse_du_chemin_compte():
    texte = "User-agent: *\nDisallow: /Prive\n"
    assert not _ok(texte, "/Prive")
    assert _ok(texte, "/prive")


def test_la_casse_de_l_agent_et_des_directives_ne_compte_pas():
    texte = "USER-AGENT: opsysveille\nDISALLOW: /x\n"
    assert not _ok(texte, "/x")
    assert _ok(texte, "/y")


def test_le_groupe_le_plus_specifique_l_emporte_sur_l_etoile():
    texte = "User-agent: *\nDisallow: /\n\nUser-agent: OpsysVeille\nAllow: /\n"
    assert _ok(texte, "/page")
    assert not _ok(texte, "/page", agent="AutreRobot/2.0")


def test_le_jeton_le_plus_long_contenu_dans_le_nom_gagne():
    texte = "User-agent: opsys\nDisallow: /\n\nUser-agent: opsysveille\nDisallow: /seulement-ici\n"
    assert _ok(texte, "/page")
    assert not _ok(texte, "/seulement-ici")


def test_sans_groupe_pour_l_agent_ni_etoile_tout_est_permis():
    assert _ok("User-agent: gptbot\nDisallow: /\n", "/page")


def test_plusieurs_lignes_user_agent_partagent_le_groupe():
    texte = "User-agent: a\nUser-agent: opsysveille\nDisallow: /x\n"
    assert not _ok(texte, "/x")


def test_un_nouveau_user_agent_apres_des_regles_ouvre_un_autre_groupe():
    texte = "User-agent: opsysveille\nDisallow: /x\nUser-agent: autre\nDisallow: /y\n"
    assert not _ok(texte, "/x")
    assert _ok(texte, "/y")


def test_fichier_introuvable_4xx_permet_tout():
    for statut in (400, 401, 403, 404, 410, 451):
        assert robots.analyser("Disallow: /", statut).etat == "absent"
        assert robots.autorise(robots.analyser("User-agent: *\nDisallow: /", statut), AGENT, "/page")


def test_fichier_inaccessible_5xx_interdit_tout():
    for statut in (500, 502, 503, 599):
        regle = robots.analyser("User-agent: *\nAllow: /", statut)
        assert regle.etat == "inaccessible"
        assert not robots.autorise(regle, AGENT, "/page")


def test_statut_incoherent_ou_corps_absent_interdit_tout():
    assert robots.analyser(None, 200).etat == "inaccessible"
    assert robots.analyser("", 302).etat == "inaccessible"
    assert robots.analyser("", 99).etat == "inaccessible"
    assert robots.analyser("", "200").etat == "inaccessible"  # type: ignore[arg-type]


def test_seuls_les_500_premiers_kio_sont_lus():
    remplissage = "# " + "x" * 100 + "\n"
    texte = "User-agent: *\n" + remplissage * (robots.TAILLE_MAX // len(remplissage) + 50) + "Disallow: /secret\n"
    regle = robots.analyser(texte, 200)
    assert regle.tronque is True
    assert robots.autorise(regle, AGENT, "/secret")  # la règle est au-delà de la limite : ignorée (RFC 9309 §2.5)
    court = robots.analyser("User-agent: *\nDisallow: /secret\n", 200)
    assert court.tronque is False and not robots.autorise(court, AGENT, "/secret")


def test_crawl_delay_est_lu_borne_et_ignore_s_il_est_invalide():
    assert robots.delai_exige_s(robots.analyser("User-agent: *\nCrawl-delay: 5\n", 200), AGENT) == 5
    assert robots.delai_exige_s(robots.analyser("User-agent: *\nCrawl-delay: 99999\n", 200), AGENT) == 3600
    assert robots.delai_exige_s(robots.analyser("User-agent: *\nCrawl-delay: abc\n", 200), AGENT) is None
    assert robots.delai_exige_s(robots.analyser("User-agent: *\nCrawl-delay: -4\n", 200), AGENT) is None
    assert robots.delai_exige_s(robots.analyser("User-agent: *\nDisallow: /x\n", 200), AGENT) is None
    assert robots.delai_exige_s(robots.analyser("", 404), AGENT) is None


def test_crawl_delay_suit_le_groupe_de_l_agent():
    texte = "User-agent: *\nCrawl-delay: 30\n\nUser-agent: opsysveille\nCrawl-delay: 2\n"
    assert robots.delai_exige_s(robots.analyser(texte, 200), AGENT) == 2
    assert robots.delai_exige_s(robots.analyser(texte, 200), "Autre") == 30


def test_lignes_mal_formees_commentaires_et_fins_de_ligne_mixtes():
    texte = "User-agent: *\r\nceci n'est pas une directive\r\n# Disallow: /commente\r\nDisallow: /reel # fin\r\n:vide\r"
    regle = robots.analyser(texte, 200)
    assert not robots.autorise(regle, AGENT, "/reel")
    assert robots.autorise(regle, AGENT, "/commente")


def test_les_plans_de_site_declares_sont_rendus_tels_quels_et_bornes():
    texte = "Sitemap: https://www.horizon.example/a.xml\n" + "".join(f"Sitemap: https://x.example/{i}.xml\n"
                                                                       for i in range(40))
    regle = robots.analyser(texte, 200)
    assert regle.plans_de_site[0] == "https://www.horizon.example/a.xml" and len(regle.plans_de_site) == 20


def test_chemin_sans_barre_initiale_est_normalise():
    assert not _ok("User-agent: *\nDisallow: /x\n", "x")


def test_agents_declares():
    regle = robots.analyser("User-agent: GPTBot\nDisallow: /\nUser-agent: *\nAllow: /\n", 200)
    assert list(robots.agents_declares(regle)) == ["*", "gptbot"]


def test_un_motif_hostile_ne_bloque_pas_l_analyse():
    """Deux cents jokers : une expression régulière naïve exploserait ; la correspondance est en temps polynomial."""
    import time

    motif = "/" + "*a" * 200 + "$"
    regle = robots.analyser(f"User-agent: *\nDisallow: {motif}\n", 200)
    debut = time.monotonic()
    assert not robots.autorise(regle, AGENT, "/" + "a" * 5000)  # 5000 « a » : le motif en demande 200 au moins
    assert robots.autorise(regle, AGENT, "/" + "a" * 100)  # 100 « a » : pas assez
    assert robots.autorise(regle, AGENT, "/" + "a" * 4000 + "b")  # `$` : se termine par autre chose
    assert time.monotonic() - debut < 5


def test_un_motif_demesure_est_ignore():
    regle = robots.analyser("User-agent: *\nDisallow: /" + "x" * 3000 + "\n", 200)
    assert robots.autorise(regle, AGENT, "/" + "x" * 3000)
