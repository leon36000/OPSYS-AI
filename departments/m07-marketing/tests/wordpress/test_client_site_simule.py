"""Le client signataire contre un site simulé qui applique les règles du plugin.

Valide le CLIENT (signature, refus typés, validation des réponses) et, par le simulateur, les règles que le plugin doit
tenir : statut forcé, rejeu refusé, publication par jeton seulement. Le plugin PHP lui-même n'est PAS exercé ici.
"""

from __future__ import annotations

import base64
import json

import pytest
from m7_marketing.wordpress import client as client_module
from m7_marketing.wordpress import flux
from m7_marketing.wordpress.client import ReponseHTTP

FICTIF = True
CLE = "cle-idempotence-0123456789"


def _creer(env, **plus):
    return env.client.creer_brouillon(
        "post",
        plus.get("titre", "Toiture à Laval"),
        plus.get("contenu", "<p>Bonjour</p>"),
        "",
        "",
        "draft",
        plus.get("cle", CLE),
    )


def test_la_sante_se_lit_signee(env):
    resultat = env.client.sante()
    assert resultat["accepte"] and resultat["donnees"]["site_id"] == "horizon-fictif.example"
    requete = env.site.requetes[-1]
    assert requete.url == "https://horizon-fictif.example/wp-json/opsys-connect/v1/health" and requete.corps == b""
    assert set(requete.en_tetes) >= {"X-OPSYS-Key-Id", "X-OPSYS-Timestamp", "X-OPSYS-Nonce", "X-OPSYS-Signature"}
    assert env.secret not in json.dumps(dict(requete.en_tetes))


def test_creer_un_brouillon_rend_l_empreinte_du_contenu_stocke(env, reference):
    resultat = _creer(env)
    assert resultat["accepte"], resultat
    donnees = resultat["donnees"]
    assert donnees["statut"] == "draft" and donnees["deja_cree"] is False
    assert donnees["empreinte"] == reference.empreinte_contenu(
        {
            "type": "post",
            "titre": "Toiture à Laval",
            "contenu": "<p>Bonjour</p>",
            "extrait": "",
            "slug": "",
            "image_a_la_une_sha256": "",
        }
    )


def test_le_rejeu_de_la_meme_creation_ne_cree_pas_un_second_article(env):
    premier = _creer(env)
    second = _creer(env)
    assert second["accepte"] and second["donnees"]["deja_cree"] is True
    assert second["donnees"]["post_id"] == premier["donnees"]["post_id"]
    assert len(env.site.posts) == 1


def test_la_meme_cle_avec_un_autre_contenu_est_refusee(env):
    _creer(env)
    refus = _creer(env, contenu="<p>Autre</p>")
    assert not refus["accepte"] and refus["refus"][0]["code"] == "REJ-WP-CLE-IDEMPOTENCE-REUTILISEE"
    assert len(env.site.posts) == 1


@pytest.mark.parametrize("statut", ["publish", "future", "private", "trash", "inherit", "auto-draft", "", None])
def test_le_client_ne_demande_jamais_un_statut_autre_que_brouillon(env, statut):
    envoyees = len(env.site.requetes)
    resultat = env.client.creer_brouillon("post", "t", "<p>x</p>", "", "", statut, CLE)
    assert resultat["refus"][0]["code"] == "REJ-WP-STATUT-INTERDIT"
    assert len(env.site.requetes) == envoyees, "la requête ne part pas"
    resultat = env.client.maj_brouillon(101, {"statut": statut})
    assert resultat["refus"][0]["code"] == "REJ-WP-STATUT-INTERDIT" or statut is None
    assert len(env.site.requetes) == envoyees or statut is None


def test_meme_forge_a_la_main_le_site_refuse_de_publier_sans_jeton(env):
    """Le client est contourné : une requête signée VALIDE qui demande « publish » reste refusée par le site."""

    class Forge(client_module.ClientWordPress):
        def forger(self, charge):
            return self._appeler("POST", "/opsys-connect/v1/drafts", "brouillon_cree", charge)

    forge = Forge(
        env.client._site, env.client._fournisseur, env.site, env.horloge, lambda: "n" * 24 + str(env.horloge.t)
    )
    resultat = forge.forger(
        {
            "type": "post",
            "titre": "t",
            "contenu": "",
            "extrait": "",
            "slug": "",
            "statut": "publish",
            "cle_idempotence": CLE,
        }
    )
    assert resultat["refus"][0]["code"] == "REJ-WP-PUBLICATION-SANS-JETON" and resultat["http"] == 403
    assert not env.site.posts


def test_un_corps_rejoue_tel_quel_est_refuse_comme_rejeu(env):
    _creer(env)
    original = env.site.requetes[-1]
    rejeu = env.site.envoyer(original)
    assert rejeu.statut == 401 and json.loads(rejeu.corps)["code"] == "opsys_rejeu"


def test_une_requete_hors_fenetre_est_refusee(env):
    env.client.sante()
    ancienne = env.site.requetes[-1]
    env.horloge.avancer(301)
    reponse = env.site.envoyer(ancienne)
    assert json.loads(reponse.corps)["code"] == "opsys_horodatage_hors_fenetre"


def test_un_corps_modifie_en_route_est_refuse(env):
    _creer(env)
    original = env.site.requetes[-1]
    falsifiee = client_module.RequeteHTTP(
        original.methode,
        original.url,
        original.en_tetes,
        original.corps.replace(b"Bonjour", b"Piratee"),
        original.delai_s,
    )
    assert json.loads(env.site.envoyer(falsifiee).corps)["code"] == "opsys_signature_invalide"


def test_une_autre_route_avec_la_meme_signature_est_refusee(env):
    env.client.sante()
    original = env.site.requetes[-1]
    detournee = client_module.RequeteHTTP(
        original.methode, original.url.replace("/health", "/types"), original.en_tetes, original.corps, original.delai_s
    )
    assert json.loads(env.site.envoyer(detournee).corps)["code"] == "opsys_signature_invalide"


def test_un_autre_secret_signe_mais_n_est_pas_cru(env):
    import contextlib

    from m7_marketing.wordpress.client import ClientWordPress

    @contextlib.contextmanager
    def autre():
        yield "un-autre-secret-fictif-0123456789abcdef-xx"

    intrus = ClientWordPress(
        env.site_wp, autre, env.site, env.horloge, lambda: "intrus-" + str(env.horloge.t) + "-0000000"
    )
    assert intrus.sante()["refus"][0]["code"] == "REJ-WP-SIGNATURE-INVALIDE"


def test_un_secret_trop_court_n_envoie_rien(env):
    import contextlib

    @contextlib.contextmanager
    def court():
        yield "trop-court"

    c = client_module.ClientWordPress(env.site_wp, court, env.site, env.horloge, lambda: "n" * 24)
    avant = len(env.site.requetes)
    assert c.sante()["refus"][0]["code"] == "REJ-WP-SECRET-TROP-COURT"
    assert len(env.site.requetes) == avant


def test_un_site_sans_https_est_refuse(env):
    env.site.https = False
    assert env.client.sante()["refus"][0]["code"] == "REJ-WP-HTTPS-REQUIS"


def test_un_utilisateur_de_service_dangereux_bloque_tout(env):
    env.site.agent_sur = False
    assert env.client.sante()["refus"][0]["code"] == "REJ-WP-AGENT-DANGEREUX"


def test_la_mise_a_jour_ne_touche_que_les_brouillons(env):
    cree = _creer(env)["donnees"]
    maj = env.client.maj_brouillon(cree["post_id"], {"titre": "Nouveau titre"}, empreinte_attendue=cree["empreinte"])
    assert maj["accepte"] and maj["donnees"]["empreinte"] != cree["empreinte"]
    obsolete = env.client.maj_brouillon(cree["post_id"], {"titre": "x"}, empreinte_attendue=cree["empreinte"])
    assert obsolete["refus"][0]["code"] == "REJ-WP-EMPREINTE-OBSOLETE"
    env.site.posts[cree["post_id"]]["statut"] = "publish"
    fige = env.client.maj_brouillon(cree["post_id"], {"titre": "y"})
    assert fige["refus"][0]["code"] == "REJ-WP-ETAT-NON-MODIFIABLE"


def test_un_article_non_gere_est_introuvable(env):
    assert env.client.etat(9999)["refus"][0]["code"] == "REJ-WP-NON-GERE"


# -- médias ----------------------------------------------------------------------------------------------------------
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_un_media_est_verifie_par_ses_octets_pas_par_son_nom(env):
    ok = env.client.televerser_media("photo.png", PNG, "Toiture neuve")
    assert ok["accepte"] and ok["donnees"]["mime"] == "image/png"
    rejeu = env.client.televerser_media("photo.png", PNG, "Toiture neuve")
    assert rejeu["donnees"]["deja_cree"] is True and rejeu["donnees"]["media_id"] == ok["donnees"]["media_id"]
    deguise = env.client.televerser_media("belle-image.png", b"<?php system($_GET['c']); ?>" + b"A" * 40, "x")
    assert deguise["refus"][0]["code"] in ("REJ-WP-MEDIA-CONTENU-ACTIF", "REJ-WP-MEDIA-TYPE-REFUSE")
    script = env.client.televerser_media("logo.png", b"<svg onload=alert(1)></svg>", "Logo")
    assert script["refus"][0]["code"] == "REJ-WP-MEDIA-TYPE-REFUSE"
    polyglotte = env.client.televerser_media("x.png", PNG + b"<?php eval($_POST[1]);", "x")
    assert polyglotte["refus"][0]["code"] == "REJ-WP-MEDIA-CONTENU-ACTIF"


def test_le_client_refuse_un_media_vide_trop_gros_ou_sans_texte_alternatif(env):
    avant = len(env.site.requetes)
    assert env.client.televerser_media("a.png", b"", "alt")["refus"][0]["code"] == "REJ-WP-MEDIA-INVALIDE"
    assert env.client.televerser_media("a.png", PNG, "  ")["refus"][0]["code"] == "REJ-WP-MEDIA-INVALIDE"
    assert (
        env.client.televerser_media("a.png", b"\x89PNG" + b"0" * (8 * 1024 * 1024), "alt")["refus"][0]["code"]
        == "REJ-WP-MEDIA-INVALIDE"
    )
    assert len(env.site.requetes) == avant


def test_une_empreinte_de_media_declaree_fausse_est_refusee(env):
    class Menteur(client_module.ClientWordPress):
        def fausse(self):
            return self._appeler(
                "POST",
                "/opsys-connect/v1/media",
                "media",
                {
                    "nom_fichier": "a.png",
                    "contenu_base64": base64.b64encode(PNG).decode(),
                    "sha256": "0" * 64,
                    "alt": "x",
                },
            )

    m = Menteur(env.client._site, env.client._fournisseur, env.site, env.horloge, lambda: "m" * 24)
    assert m.fausse()["refus"][0]["code"] == "REJ-WP-MEDIA-EMPREINTE-DIFFERENTE"


# -- réponses -------------------------------------------------------------------------------------------------------
class TransportScripte:
    def __init__(self, reponse):
        self.reponse, self.vues = reponse, []

    def envoyer(self, requete):
        self.vues.append(requete)
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse


def _client_avec(env, reponse):
    return client_module.ClientWordPress(
        env.site_wp, env.client._fournisseur, TransportScripte(reponse), env.horloge, lambda: "x" * 24
    )


@pytest.mark.parametrize("corps", [b"", b"pas du json", b"[1]", b'{"post_id":1}', b'{"schema":"autre"}'])
def test_une_reponse_mal_formee_est_rejetee_jamais_crue(env, corps):
    c = _client_avec(env, ReponseHTTP(200, corps))
    assert c.sante()["refus"][0]["code"] == "REJ-WP-REPONSE-INATTENDUE"


def test_un_site_qui_repond_publie_a_une_creation_de_brouillon_est_signale(env):
    corps = json.dumps(
        {
            "post_id": 5,
            "type": "post",
            "statut": "publish",
            "empreinte": "a" * 64,
            "modifie_gmt": "2026-01-01T00:00:00Z",
            "deja_cree": False,
            "lien_modification": "x",
        }
    ).encode()
    c = _client_avec(env, ReponseHTTP(201, corps))
    assert (
        c.creer_brouillon("post", "t", "<p>x</p>", "", "", "draft", CLE)["refus"][0]["code"]
        == "REJ-WP-REPONSE-INATTENDUE"
    )


def test_un_code_d_erreur_inconnu_n_est_jamais_repris_tel_quel(env):
    corps = json.dumps({"code": "opsys_inventé_<script>", "message": "m", "data": {"status": 400}}).encode()
    resultat = _client_avec(env, ReponseHTTP(400, corps)).sante()
    assert resultat["refus"][0]["code"] == "REJ-WP-REPONSE-INATTENDUE"


def test_une_panne_de_transport_ne_cite_pas_le_message_de_l_exception(env):
    c = _client_avec(env, ConnectionError("secret-dans-le-message " + env.secret))
    refus = c.sante()["refus"][0]
    assert (
        refus["code"] == "REJ-WP-TRANSPORT"
        and env.secret not in json.dumps(refus)
        and "ConnectionError" in refus["detail"]
    )


def test_une_reponse_geante_est_rejetee(env):
    c = _client_avec(env, ReponseHTTP(200, b"{" + b" " * (client_module.REPONSE_MAX + 1) + b"}"))
    assert c.sante()["refus"][0]["code"] == "REJ-WP-REPONSE-INATTENDUE"


def test_le_client_n_envoie_rien_hors_de_l_espace_opsys_connect(env):
    avant = len(env.site.requetes)
    for route in ("/wp/v2/users", "/opsys-connect/v1/../../wp/v2/users", "/opsys-connect/v1/drafts?x=1"):
        assert env.client._appeler("GET", route, "sante")["refus"][0]["code"] == "REJ-WP-ROUTE-INVALIDE"
    assert len(env.site.requetes) == avant


def test_le_secret_n_apparait_dans_aucune_requete_ni_reponse_ni_refus(env):
    _creer(env)
    env.client.sante()
    env.client.etat(101)
    for requete in env.site.requetes:
        assert env.secret.encode() not in requete.corps and env.secret not in json.dumps(dict(requete.en_tetes))
        assert env.secret not in requete.url
    assert env.ouvertures_secret, "le secret est demandé au fournisseur à chaque appel"


# -- publication par jeton --------------------------------------------------------------------------------------------
def _article():
    return {
        "type": "post",
        "titre": "Rénovation de toiture à Laval",
        "contenu": "<p>Texte sobre.</p>",
        "extrait": "",
        "slug": "",
    }


def _preparer_et_transmettre(env, journal=None):
    journal = env.journal if journal is None else journal
    sites_actifs = {env.site_wp.site_id: env.site_wp}
    prep = flux.preparer(
        journal, sites_actifs, env.site_wp.site_id, _article(), "draft", CLE, True, "agent", "2026-01-01T00:00:00Z"
    )
    assert prep["accepte"], prep
    from m7_marketing.wordpress import executeur

    transmis = executeur.transmettre_brouillon(journal, prep["publication_id"], env.client, env.horloge.maintenant())
    assert transmis["accepte"], transmis
    return prep["publication_id"], transmis


def _approuver(env, publication_id, empreinte, **plus):
    return flux.approuver(
        env.journal,
        publication_id,
        empreinte,
        plus.get("action", "publish"),
        plus.get("publish_at"),
        {"par": "nathan", "role": "nathan_owner", "source": "approbation"},
        env.horloge.maintenant(),
        "2026-01-01T00:00:10Z",
    )


def test_le_flux_complet_brouillon_revue_approbation_publication(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    assert transmis["etat"] == "en_revue"
    assert _approuver(env, pid, transmis["empreinte_serveur"])["accepte"]
    publie = executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    assert publie["accepte"] and publie["etat"] == "publie" and publie["statut_site"] == "publish"
    assert env.site.posts[transmis["post_id"]]["statut"] == "publish"
    etat = flux.plier(env.journal)[pid]
    assert etat.etat == "publie" and etat.jeton_emis


def test_aucun_jeton_ni_secret_n_entre_au_journal(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    texte = json.dumps(env.journal)
    assert env.secret not in texte
    token = json.loads(env.site.requetes[-1].corps)["approval_token"]
    assert token not in texte and token.split(".")[1] not in texte


def test_un_contenu_modifie_apres_l_approbation_ne_se_publie_pas(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    env.site.modifier_dans_wp_admin(transmis["post_id"], titre="Titre modifié par quelqu'un d'autre")
    resultat = executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    assert resultat["refus"][0]["code"] == "REJ-WP-CONTENU-DIVERGENT"
    assert env.site.posts[transmis["post_id"]]["statut"] == "draft"
    etat = flux.plier(env.journal)[pid]
    assert etat.etat == "en_revue" and etat.approbation is None, "la revue est rouverte, l'approbation tombe"


def test_le_plugin_refuse_aussi_si_le_client_est_contourne(env):
    """Défense en profondeur : même sans la relecture préalable du client, le site compare l'empreinte au point de
    sortie.
    """
    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    env.site.modifier_dans_wp_admin(transmis["post_id"], contenu="<p>Autre texte</p>")
    approbation = flux.approbation_verifiee(env.journal, pid, env.horloge.maintenant())
    resultat = env.client.publier(approbation)
    assert resultat["refus"][0]["code"] == "REJ-WP-JETON-EMPREINTE-DIFFERENTE"
    assert env.site.posts[transmis["post_id"]]["statut"] == "draft"


def test_un_jeton_ne_sert_qu_une_fois(env):
    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    approbation = flux.approbation_verifiee(env.journal, pid, env.horloge.maintenant())
    assert env.client.publier(approbation)["accepte"]
    env.site.posts[transmis["post_id"]]["statut"] = "draft"  # on remet l'article en brouillon : le jeton resservirait
    env.site.posts[transmis["post_id"]]["slug"] = ""
    rejeu = env.client.publier(approbation)
    assert rejeu["refus"][0]["code"] == "REJ-WP-JETON-DEJA-UTILISE"


def test_un_jeton_expire_est_refuse_par_le_site(env):
    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    approbation = flux.approbation_verifiee(env.journal, pid, env.horloge.maintenant())
    env.horloge.avancer(flux.VALIDITE_APPROBATION_S + 1)
    assert env.client.publier(approbation)["refus"][0]["code"] == "REJ-WP-JETON-EXPIRE"


def test_le_jeton_d_un_autre_site_est_refuse(env):
    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    approbation = flux.approbation_verifiee(env.journal, pid, env.horloge.maintenant())
    env.site.site_id = "autre-site.example"
    assert env.client.publier(approbation)["refus"][0]["code"] == "REJ-WP-JETON-SITE-DIFFERENT"


def test_une_publication_planifiee_passe_par_future(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    assert _approuver(env, pid, transmis["empreinte_serveur"], action="schedule", publish_at="2026-01-01T14:00:00Z")[
        "accepte"
    ]
    publie = executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    assert publie["statut_site"] == "future"


def test_la_publication_est_desactivee_sans_identifiant_de_site(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    env.site.publication_activee = False
    resultat = executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    assert resultat["refus"][0]["code"] == "REJ-WP-PUBLICATION-DESACTIVEE"
    assert flux.plier(env.journal)[pid].etat == "echec"


def test_une_reponse_perdue_se_reconcilie_sans_renvoyer_de_jeton(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])

    class PerdLaReponse:
        def __init__(self, vrai):
            self.vrai, self.appels = vrai, 0

        def envoyer(self, requete):
            reponse = self.vrai.envoyer(requete)
            if requete.url.endswith("/publish"):
                self.appels += 1
                raise TimeoutError("réponse perdue")
            return reponse

    perdant = PerdLaReponse(env.site)
    env.client._transport = perdant
    resultat = executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    assert resultat["refus"][0]["code"] == "REJ-WP-TRANSPORT"
    assert env.site.posts[transmis["post_id"]]["statut"] == "publish", "le site a bien publié"
    assert flux.plier(env.journal)[pid].etat == "approuve", "mais OPSYS ne le sait pas encore"
    assert (
        flux.approbation_verifiee(env.journal, pid, env.horloge.maintenant())["refus"][0]["code"]
        == "REJ-WP-APPROBATION-DEJA-UTILISEE"
    ), "l'approbation est brûlée : aucun second jeton"
    env.client._transport = env.site
    rec = executeur.reconcilier(env.journal, pid, env.client, env.horloge.maintenant())
    assert rec["accepte"] and rec["reconcilie"] and flux.plier(env.journal)[pid].etat == "publie"
    assert perdant.appels == 1


def test_apres_un_echec_la_revue_peut_etre_rouverte_et_une_autre_approbation_donnee(env):
    from m7_marketing.wordpress import executeur

    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    env.site.publication_activee = False
    executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())
    env.site.publication_activee = True
    again = executeur.transmettre_brouillon(env.journal, pid, env.client, env.horloge.maintenant())
    assert again["accepte"] and again["etat"] == "en_revue"
    assert _approuver(env, pid, again["empreinte_serveur"])["accepte"]
    assert executeur.publier(env.journal, pid, env.client, env.horloge.maintenant())["accepte"]


def test_la_divergence_d_assainissement_est_dite_et_c_est_l_empreinte_du_site_qui_s_approuve(env):
    from m7_marketing.wordpress import executeur

    sites_actifs = {env.site_wp.site_id: env.site_wp}
    article = {**_article(), "contenu": "<p>Texte</p><script>alert(1)</script>"}
    refus = flux.preparer(
        env.journal, sites_actifs, env.site_wp.site_id, article, "draft", CLE, True, "agent", "2026-01-01T00:00:00Z"
    )
    assert refus["refus"][0]["code"] == "REJ-WP-CONTENU-ACTIF", "OPSYS refuse d'avance le contenu actif"
    article = {**_article(), "contenu": "<p>Texte</p><center>centré</center>"}
    prep = flux.preparer(
        env.journal, sites_actifs, env.site_wp.site_id, article, "draft", CLE, False, "agent", "2026-01-01T00:00:00Z"
    )
    assert prep["accepte"]
    transmis = executeur.transmettre_brouillon(
        env.journal, prep["publication_id"], env.client, env.horloge.maintenant()
    )
    assert transmis["divergence"] is True, (
        "le site a retiré <center> : l'empreinte du site n'est plus l'empreinte locale"
    )
    faux = _approuver(env, prep["publication_id"], prep["empreinte_locale"])
    assert faux["refus"][0]["code"] == "REJ-WP-EMPREINTE-DIFFERENTE", "approuver l'empreinte locale est refusé"
    assert _approuver(env, prep["publication_id"], transmis["empreinte_serveur"])["accepte"]


def test_un_site_qui_publie_un_autre_contenu_que_celui_approuve_est_signale(env):
    """Réponse hostile : le site dit « publié » mais avec une autre empreinte que l'approbation. Jamais cru."""
    pid, transmis = _preparer_et_transmettre(env)
    _approuver(env, pid, transmis["empreinte_serveur"])
    approbation = flux.approbation_verifiee(env.journal, pid, env.horloge.maintenant())
    corps = json.dumps(
        {
            "post_id": transmis["post_id"],
            "statut": "publish",
            "empreinte": "e" * 64,
            "publie_le_gmt": "2026-01-01T00:00:00Z",
            "lien_public": None,
        }
    ).encode()
    hostile = _client_avec(env, ReponseHTTP(200, corps))
    resultat = hostile.publier(approbation)
    assert resultat["accepte"] is False
    assert resultat["refus"][0]["code"] == "REJ-WP-EMPREINTE-REPONSE"
