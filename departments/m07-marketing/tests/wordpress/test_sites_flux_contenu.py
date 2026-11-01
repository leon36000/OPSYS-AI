"""Registre des sites, garde-fou du contenu d'article et machine d'états du flux WordPress (modules purs)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from m7_marketing import journal_chaine
from m7_marketing.wordpress import contenu, flux, sites

FICTIF = True
H = "2026-01-05T15:00:00Z"
MAINTENANT = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
SECRET_REF = {"nom": "wordpress.horizon-fictif", "cle_id": "default"}
SITE = "horizon-fictif.example"
ARTICLE = {
    "type": "post",
    "titre": "Rénovation de toiture",
    "contenu": "<p>Texte sobre.</p>",
    "extrait": "",
    "slug": "",
}
CLE = "cle-flux-0123456789abcd"


def _enregistrer(journal, **plus):
    args = {
        "site_id": SITE,
        "base_url": "https://horizon-fictif.example",
        "secret_ref": SECRET_REF,
        "types_autorises": ["post", "page"],
        "fictif": True,
        **plus,
    }
    return sites.enregistrer(
        journal,
        args["site_id"],
        args["base_url"],
        args["secret_ref"],
        args["types_autorises"],
        args["fictif"],
        "nathan",
        H,
    )


# -- sites
# ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "fictif", "valide"),
    [
        ("https://horizon-fictif.example", True, True),
        ("https://horizon-fictif.example/blogue", True, True),
        ("https://horizon-fictif.example:443", True, True),
        ("https://horizon-fictif.test/", True, True),
        ("https://mon-entreprise.com", False, True),
        ("https://www.mon-entreprise.ca/sous/dossier/", False, True),
        ("http://horizon-fictif.example", True, False),
        ("ftp://horizon-fictif.example", True, False),
        ("https://horizon-fictif.example:8443", True, False),
        ("https://user@horizon-fictif.example", True, False),
        ("https://u:p@horizon-fictif.example", True, False),
        ("https://horizon-fictif.example?x=1", True, False),
        ("https://horizon-fictif.example#frag", True, False),
        ("https://127.0.0.1", False, False),
        ("https://10.0.0.5/", False, False),
        ("https://[::1]/", False, False),
        ("https://localhost", True, False),
        ("https://HORIZON.example", True, False),
        ("https://horizon_fictif.example", True, False),
        ("https://-bad.example", True, False),
        ("https://horizon-fictif.example/a b", True, False),
        ("https://horizon-fictif.example/../x", True, False),
        ("https://mon-entreprise.com", True, False),
        ("https://horizon-fictif.example", False, False),
        (" https://horizon-fictif.example", True, False),
        ("https://horizon-fictif.example/" + "a" * 200, True, False),
        ("", True, False),
        (None, True, False),
        (12, True, False),
        ("https://horizon-fictif.example/a/b/c/d/e/f", True, False),
    ],
)
def test_validation_de_l_adresse_d_un_site(url, fictif, valide):
    normalisee, detail = sites.valider_url(url, fictif)
    assert (normalisee is not None) is valide, detail


def test_l_adresse_est_normalisee_sans_barre_finale():
    assert (
        sites.valider_url("https://horizon-fictif.example/blogue/", True)[0] == "https://horizon-fictif.example/blogue"
    )


def test_enregistrer_un_site_est_idempotent_et_immuable():
    journal: list = []
    assert _enregistrer(journal) == {"accepte": True, "site_id": SITE, "deja_enregistre": False}
    assert _enregistrer(journal)["deja_enregistre"] is True and len(journal) == 1
    for modification in (
        {"base_url": "https://autre.example"},
        {"secret_ref": {**SECRET_REF, "nom": "autre.secret"}},
        {"types_autorises": ["post"]},
    ):
        refus = _enregistrer(journal, **modification)
        assert refus["refus"][0]["code"] == "REJ-WP-SITE-EXISTANT", modification
    assert len(journal) == 1


@pytest.mark.parametrize(
    ("modification", "code"),
    [
        ({"site_id": "ab"}, "REJ-WP-SITE-INVALIDE"),
        ({"site_id": "Majuscule.example"}, "REJ-WP-SITE-INVALIDE"),
        ({"site_id": 5}, "REJ-WP-SITE-INVALIDE"),
        ({"fictif": "oui"}, "REJ-WP-SITE-INVALIDE"),
        ({"secret_ref": "secret-en-clair-0123456789abcdef"}, "REJ-WP-SECRET-REF-INVALIDE"),
        ({"secret_ref": {"nom": "x"}}, "REJ-WP-SECRET-REF-INVALIDE"),
        ({"secret_ref": {"nom": "valeur", "cle_id": "a b"}}, "REJ-WP-SECRET-REF-INVALIDE"),
        ({"secret_ref": {"nom": "valeur-1234", "cle_id": "d", "secret": "oups"}}, "REJ-WP-SECRET-REF-INVALIDE"),
        ({"types_autorises": []}, "REJ-WP-TYPES-INVALIDES"),
        ({"types_autorises": ["attachment"]}, "REJ-WP-TYPES-INVALIDES"),
        ({"types_autorises": ["post", "post"]}, "REJ-WP-TYPES-INVALIDES"),
        ({"types_autorises": "post"}, "REJ-WP-TYPES-INVALIDES"),
        ({"base_url": "https://mon-entreprise.com"}, "REJ-WP-FICTIF-DOMAINE"),
        ({"base_url": "http://horizon-fictif.example"}, "REJ-WP-URL-INVALIDE"),
    ],
)
def test_un_enregistrement_invalide_est_refuse_sans_rien_ecrire(modification, code):
    journal: list = []
    assert _enregistrer(journal, **modification)["refus"][0]["code"] == code
    assert journal == []


def test_un_site_desactive_ne_sert_plus_et_ne_se_reenregistre_pas():
    journal: list = []
    _enregistrer(journal)
    assert sites.actifs(journal)[SITE].base_url == "https://horizon-fictif.example"
    assert sites.desactiver(journal, SITE, "nathan", "client parti", H) == {
        "accepte": True,
        "site_id": SITE,
        "deja_desactive": False,
    }
    assert sites.actifs(journal) == {} and sites.desactiver(journal, SITE, "nathan", "x", H)["deja_desactive"] is True
    assert _enregistrer(journal)["refus"][0]["code"] == "REJ-WP-SITE-DESACTIVE"
    assert sites.desactiver(journal, "inconnu.example", "n", "x", H)["refus"][0]["code"] == "REJ-WP-SITE-INCONNU"


def test_le_registre_des_sites_ne_contient_aucune_valeur_de_secret():
    journal: list = []
    _enregistrer(journal)
    assert "secret_ref" in journal[0]["site"] and set(journal[0]["site"]["secret_ref"]) == {"nom", "cle_id"}
    assert journal_chaine.verifier(journal) == []
    journal[0]["site"]["base_url"] = "https://pirate.example"
    assert (
        sites.enregistrer(
            journal, "autre-site.example", "https://autre-site.example", SECRET_REF, ["post"], True, "n", H
        )["refus"][0]["code"]
        == "REJ-WP-JOURNAL-ALTERE"
    )


# -- contenu d'article
# --------------------------------------------------------------------------------------------------------------
def _controle(**champs):
    return [r["code"] for r in contenu.controler({**ARTICLE, **champs})]


def test_un_article_sobre_passe():
    assert _controle() == []
    assert (
        _controle(
            contenu="<h2>Titre</h2><p>Un <strong>texte</strong> avec un <a href='https://exemple.example/a'>lien</a>.</p>"
        )
        == []
    )


@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script>",
        "<SCRIPT SRC=x></SCRIPT>",
        "<iframe src='https://x.example'></iframe>",
        "<object data=x></object>",
        "<embed src=x>",
        "<form action=x><input></form>",
        "<style>body{}</style>",
        "<link rel=stylesheet href=x>",
        "<meta http-equiv=refresh>",
        "<base href='https://pirate.example/'>",
        "<svg onload=alert(1)></svg>",
        "<math><mi>x</mi></math>",
        "<video src=x></video>",
        "<img src=x onerror=alert(1)>",
        "<p onclick='x()'>t</p>",
        "<a href='javascript:alert(1)'>x</a>",
        "<a href=' JavaScript:alert(1)'>x</a>",
        "<a href='vbscript:x'>x</a>",
        "<img src='data:image/svg+xml;base64,PHN2Zz4='>",
        '<a href="data:text/html,<script>">x</a>',
        "<button>x</button>",
        "<textarea>x</textarea>",
        "<noscript>x</noscript>",
        "<template>x</template>",
    ],
)
def test_le_contenu_actif_est_refuse(html):
    assert "REJ-WP-CONTENU-ACTIF" in _controle(contenu=f"<p>Texte.</p>{html}"), html


@pytest.mark.parametrize(
    ("champ", "valeur", "regle"),
    [
        ("contenu", "<p>Appelez le 450 555 0142.</p>", "REJ-COORDONNEES"),
        ("contenu", "<p>Écrivez à info@horizon.example.</p>", "REJ-COORDONNEES"),
        ("contenu", "<p>Chantier au 12 rue des Érables.</p>", "REJ-ADRESSE"),
        ("contenu", "<p>Soumission gratuite, rabais de saison.</p>", "REJ-PRIX"),
        ("contenu", "<p>Une toiture de 1200 pieds carrés.</p>", "REJ-CHIFFRE-NON-SOURCE"),
        ("contenu", "<p>Garantie à vie sur tous nos travaux.</p>", "REJ-GARANTIE-NON-VALIDEE"),
        ("contenu", "<p>Nous livrons demain, d'ici deux semaines.</p>", "REJ-PROMESSE-DE-DATE"),
        ("contenu", "<p>Le meilleur couvreur, numéro 1.</p>", "REJ-EXAGERATION"),
        ("titre", "Le meilleur toit du Québec", "REJ-EXAGERATION"),
        ("extrait", "Rabais de 20 % cette semaine", "REJ-PRIX"),
    ],
)
def test_le_texte_visible_passe_par_le_garde_fou_du_socle(champ, valeur, regle):
    assert regle in _controle(**{champ: valeur})


def test_le_texte_cache_dans_une_balise_est_aussi_lu():
    assert "REJ-COORDONNEES" in _controle(contenu="<p><span title='x'>Écrivez à info@horizon.example</span></p>")
    assert _controle(contenu="<p>Appelez au 450 555 0142</p>") != []


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("titre", "t" * 201),
        ("contenu", "c" * 100_001),
        ("extrait", "e" * 1001),
        ("slug", "s" * 101),
        ("titre", 5),
        ("contenu", None),
        ("titre", "   "),
        ("slug", "Pas Propre"),
        ("slug", "a--b"),
        ("slug", "-a"),
        ("slug", "é"),
    ],
)
def test_les_bornes_et_les_formes_des_champs(champ, valeur):
    assert "REJ-WP-CHAMP" in _controle(**{champ: valeur})


# -- flux : états, approbation, expiration, usage unique
# ---------------------------------------------------------------------------
@pytest.fixture
def prepare():
    journal: list = []
    _enregistrer(journal)
    actifs = sites.actifs(journal)
    resultat = flux.preparer([], actifs, SITE, ARTICLE, "draft", CLE, True, "agent", H)
    assert resultat["accepte"], resultat
    flux_journal: list = []
    r = flux.preparer(flux_journal, actifs, SITE, ARTICLE, "draft", CLE, True, "agent", H)
    return flux_journal, actifs, r["publication_id"], r


OWNER = {"par": "nathan", "role": "nathan_owner", "source": "approbation"}


def _revu(flux_journal, pid, empreinte="d" * 64, post_id=42):
    assert flux.consigner_transmission(flux_journal, pid, post_id, empreinte, H)["accepte"]


def test_une_publication_naît_brouillon_avec_l_ia_marquee_et_ne_peut_etre_approuvee_avant_la_revue(prepare):
    flux_journal, _, pid, r = prepare
    assert r["etat"] == "brouillon" and flux_journal[0]["ia_generee"] is True
    refus = flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    assert refus["refus"][0]["code"] == "REJ-WP-ETAT"


def test_l_approbation_exige_le_proprietaire_l_empreinte_du_site_et_une_action_valide(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    n = len(flux_journal)
    for approbateur in (
        None,
        {},
        {"par": "a", "role": "admin", "source": "appareil"},
        {"par": "", "role": "nathan_owner", "source": "x"},
    ):
        assert (
            flux.approuver(flux_journal, pid, "d" * 64, "publish", None, approbateur, MAINTENANT, H)["refus"][0]["code"]
            == "REJ-WP-HUMAIN-REQUIS"
        )
    assert (
        flux.approuver(flux_journal, pid, "e" * 64, "publish", None, OWNER, MAINTENANT, H)["refus"][0]["code"]
        == "REJ-WP-EMPREINTE-DIFFERENTE"
    )
    assert (
        flux.approuver(flux_journal, pid, "d" * 64, "delete", None, OWNER, MAINTENANT, H)["refus"][0]["code"]
        == "REJ-WP-ACTION-INVALIDE"
    )
    assert (
        flux.approuver(flux_journal, pid, "d" * 64, "publish", "2026-01-06T15:00:00Z", OWNER, MAINTENANT, H)["refus"][
            0
        ]["code"]
        == "REJ-WP-PLANIFICATION-INVALIDE"
    )
    assert len(flux_journal) == n


@pytest.mark.parametrize(
    ("publier_le", "ok"),
    [
        ("2026-01-05T15:05:00Z", True),
        ("2026-01-05T15:04:59Z", False),
        ("2026-01-05T14:00:00Z", False),
        (None, False),
        ("demain", False),
        ("2026-01-06 15:00:00", False),
        ("2026-01-06T15:00:00+00:00", False),
    ],
)
def test_la_planification_exige_un_instant_utc_futur_d_au_moins_cinq_minutes(prepare, publier_le, ok):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    resultat = flux.approuver(flux_journal, pid, "d" * 64, "schedule", publier_le, OWNER, MAINTENANT, H)
    assert resultat["accepte"] is ok, resultat


def test_une_approbation_est_bornee_a_une_heure_et_porte_un_identifiant_aleatoire(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    a = flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    approbation = flux.approbation_verifiee(flux_journal, pid, MAINTENANT)
    assert approbation.expire_le - approbation.emis_le == flux.VALIDITE_APPROBATION_S == 3600
    assert approbation.approval_id == a["approval_id"] and len(a["approval_id"]) >= 20
    assert approbation.empreinte == "d" * 64 and approbation.post_id == 42 and approbation.site_id == SITE


def test_une_approbation_expiree_ou_pas_encore_emise_est_refusee(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    juste = MAINTENANT + timedelta(seconds=flux.VALIDITE_APPROBATION_S - 1)
    assert isinstance(flux.approbation_verifiee(flux_journal, pid, juste), flux.ApprobationVerifiee)
    for instant in (MAINTENANT + timedelta(seconds=flux.VALIDITE_APPROBATION_S), MAINTENANT + timedelta(days=1)):
        assert flux.approbation_verifiee(flux_journal, pid, instant)["refus"][0]["code"] == "REJ-WP-APPROBATION-EXPIREE"


def test_une_approbation_ne_sert_qu_une_fois(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    approbation = flux.approbation_verifiee(flux_journal, pid, MAINTENANT)
    flux.consigner_jeton_emis(flux_journal, approbation, H)
    assert (
        flux.approbation_verifiee(flux_journal, pid, MAINTENANT)["refus"][0]["code"]
        == "REJ-WP-APPROBATION-DEJA-UTILISEE"
    )


def test_une_revision_apres_l_approbation_est_refusee_et_apres_la_revue_elle_ramene_au_brouillon(prepare):
    flux_journal, actifs, pid, _ = prepare
    _revu(flux_journal, pid)
    nouvelle = {**ARTICLE, "titre": "Un autre titre"}
    revision = flux.preparer(flux_journal, actifs, SITE, nouvelle, "draft", CLE, True, "agent", H, publication_id=pid)
    assert revision["accepte"] and revision["etat"] == "brouillon"
    assert flux.plier(flux_journal)[pid].empreinte_serveur is None, (
        "l'empreinte du site est périmée : il faut retransmettre"
    )
    _revu(flux_journal, pid, "f" * 64)
    flux.approuver(flux_journal, pid, "f" * 64, "publish", None, OWNER, MAINTENANT, H)
    refus = flux.preparer(
        flux_journal,
        actifs,
        SITE,
        {**ARTICLE, "titre": "Encore un autre"},
        "draft",
        CLE,
        True,
        "agent",
        H,
        publication_id=pid,
    )
    assert refus["refus"][0]["code"] == "REJ-WP-ETAT", "approuvée : annuler d'abord"


def test_la_retransmission_rouvre_la_revue_et_efface_l_approbation(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    _revu(flux_journal, pid, "9" * 64)
    etat = flux.plier(flux_journal)[pid]
    assert etat.etat == "en_revue" and etat.approbation is None and etat.empreinte_serveur == "9" * 64


def test_apres_l_emission_du_jeton_on_ne_peut_plus_retransmettre_sans_reconcilier(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    flux.consigner_jeton_emis(flux_journal, flux.approbation_verifiee(flux_journal, pid, MAINTENANT), H)
    assert flux.consigner_transmission(flux_journal, pid, 42, "9" * 64, H)["refus"][0]["code"] == "REJ-WP-ETAT"


@pytest.mark.parametrize(
    ("statut", "code"),
    [
        ("publish", "REJ-WP-STATUT-INTERDIT"),
        ("future", "REJ-WP-STATUT-INTERDIT"),
        ("private", "REJ-WP-STATUT-INTERDIT"),
        ("", "REJ-WP-STATUT-INTERDIT"),
        (None, "REJ-WP-STATUT-INTERDIT"),
    ],
)
def test_un_brouillon_n_est_jamais_prepare_publie(prepare, statut, code):
    flux_journal, actifs, _, _ = prepare
    n = len(flux_journal)
    assert (
        flux.preparer(flux_journal, actifs, SITE, ARTICLE, statut, "autre-cle-0123456789ab", True, "agent", H)["refus"][
            0
        ]["code"]
        == code
    )
    assert len(flux_journal) == n


def test_le_type_doit_etre_permis_pour_le_site_et_le_site_doit_etre_actif(prepare):
    flux_journal, _, _, _ = prepare
    journal: list = []
    sites.enregistrer(
        journal, "blog-seulement.example", "https://blog-seulement.example", SECRET_REF, ["post"], True, "n", H
    )
    actifs = sites.actifs(journal)
    refus = flux.preparer(
        flux_journal,
        actifs,
        "blog-seulement.example",
        {**ARTICLE, "type": "page"},
        "draft",
        "cle-page-0123456789abc",
        True,
        "a",
        H,
    )
    assert refus["refus"][0]["code"] == "REJ-WP-TYPE-NON-PERMIS"
    assert (
        flux.preparer(flux_journal, {}, SITE, ARTICLE, "draft", "cle-page-0123456789abc", True, "a", H)["refus"][0][
            "code"
        ]
        == "REJ-WP-SITE-INACTIF"
    )


def test_la_publication_sans_jeton_emis_est_incoherente_au_journal(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)
    flux.consigner_publication(flux_journal, pid, "publish", None, H)
    assert flux.lire(flux_journal)["refus"][0]["code"] == "REJ-WP-JOURNAL-INCOHERENT"


def test_lire_borne_la_liste_et_ne_rend_pas_le_secret(prepare):
    flux_journal, _, pid, _ = prepare
    assert flux.lire(flux_journal, limite=0)["total"] == 1
    detail = flux.lire(flux_journal, pid)["publication"]
    assert detail["article"]["titre"] == ARTICLE["titre"] and "secret" not in str(detail).lower()
    assert flux.lire(flux_journal, "wp-inconnue")["refus"][0]["code"] == "REJ-WP-PUBLICATION-INCONNUE"


def test_annuler_garde_une_trace_et_signale_le_brouillon_du_site(prepare):
    flux_journal, _, pid, _ = prepare
    _revu(flux_journal, pid)
    resultat = flux.annuler(flux_journal, pid, "agent", "plus d'actualité", H)
    assert resultat["etat"] == "annule" and "supprimer à la main" in resultat["attention"]
    assert flux.annuler(flux_journal, pid, "agent", "x", H)["refus"][0]["code"] == "REJ-WP-ETAT"
    assert (
        flux.approuver(flux_journal, pid, "d" * 64, "publish", None, OWNER, MAINTENANT, H)["refus"][0]["code"]
        == "REJ-WP-ETAT"
    )
