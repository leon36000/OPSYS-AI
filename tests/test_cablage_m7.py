"""Publication WordPress et sociale par le planificateur, sur doubles : le site simulé (qui applique les règles du
plugin) et
les adaptateurs de réseau de test. Rien n'est transmis sans approbation de la direction, non expirée, une seule fois.

Aucun WordPress, aucun PHP, aucun réseau réel : voir docs/architecture/CABLAGE-CONNECTEURS.md (limites)."""

from __future__ import annotations

import contextlib
import importlib.util
import threading
from datetime import UTC, datetime
from pathlib import Path

import cablage_qa as cq
import pytest
from sqlalchemy import select

from opsys import service_acteur_systeme as systeme
from opsys import stockage
from opsys.connecteurs_planification import bail, planificateur
from opsys.connecteurs_planification.exec_m7 import PublicationWordPress
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
M7 = Path(__file__).resolve().parents[1] / "departments" / "m07-marketing"
SECRET = "secret-de-test-fictif-pour-le-simulateur-0123456789"
SITE_ID = "horizon-fictif.example"
PROPRIETAIRE = {"par": "nathan", "role": "nathan_owner", "source": "approbation"}


def _charger(nom: str):
    chemin = M7 / "tests" / "wordpress" / f"{nom}.py"
    spec = importlib.util.spec_from_file_location(f"cablage_{nom}", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _social(nom: str):
    import sys

    sys.path.insert(0, str(M7 / "tests" / "sas_social"))
    return importlib.import_module(nom)


def _journal(registre: str):
    return stockage.maillons("m07-marketing", registre)


def _instant(c) -> str:
    return datetime.fromtimestamp(c.horloge(), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Cinq:
    pass


@pytest.fixture
def wp(tmp_path, monkeypatch):
    """Un site WordPress simulé, un client signataire, un registre de site ; horloge du planificateur = temps réel."""
    from m7_marketing.wordpress import sites
    from m7_marketing.wordpress.client import ClientWordPress

    c = cq.monter(tmp_path, monkeypatch)
    reference = _charger("reference_verificateur")
    simule = _charger("site_simule").SiteSimule(reference, SECRET, SITE_ID, lambda: int(c.horloge()))
    compteur = iter(range(1, 10_000_000))
    ouvertures = []

    @contextlib.contextmanager
    def fournisseur():
        ouvertures.append(1)
        yield SECRET

    resultat = sites.enregistrer(_journal("sites_wordpress"), SITE_ID, "https://horizon-fictif.example",
                                 {"nom": "wordpress.horizon-fictif", "cle_id": "default"}, ["post", "page"], True,
                                 "nathan", _instant(c))
    assert resultat["accepte"], resultat
    transport = Transport(simule)
    c.ports.client_wordpress = lambda site: ClientWordPress(site, fournisseur, transport, lambda: int(c.horloge()),
                                                            lambda: f"nonce-planif-{next(compteur):012d}")
    c.simule, c.transport, c.ouvertures = simule, transport, ouvertures
    yield c
    cq.demonter()


class Transport:
    """Le site simulé, avec la possibilité de PERDRE la réponse d'une publication (le site l'a traitée)."""

    def __init__(self, simule):
        self.simule, self.perdre_publications = simule, 0
        self.publications_vues = 0

    def envoyer(self, requete):
        reponse = self.simule.envoyer(requete)
        if requete.url.endswith("/publish"):
            self.publications_vues += 1
            if self.perdre_publications:
                self.perdre_publications -= 1
                raise ConnectionError("réponse perdue (double)")
        return reponse


def _article(i=1):
    return {"type": "post", "titre": f"Entretien des gouttières {i}", "contenu": "<p>Texte sobre.</p>",
            "extrait": "", "slug": ""}


def _preparer(c, i=1):
    from m7_marketing.wordpress import flux, sites

    actifs = sites.actifs(_journal("sites_wordpress"))
    prep = flux.preparer(_journal("publications_wordpress"), actifs, SITE_ID, _article(i), "draft",
                         f"cle-planif-{i:012d}", True, "agent", _instant(c))
    assert prep["accepte"], prep
    return prep["publication_id"]


def _approuver(c, pid, empreinte, **plus):
    from m7_marketing.wordpress import flux

    maintenant = datetime.fromtimestamp(c.horloge(), UTC)
    ok = flux.approuver(_journal("publications_wordpress"), pid, empreinte, plus.get("action", "publish"),
                        plus.get("publish_at"), PROPRIETAIRE, maintenant, _instant(c))
    assert ok["accepte"], ok
    return ok


def _etat(pid):
    from m7_marketing.wordpress import flux

    return flux.plier(_journal("publications_wordpress"))[pid]


def _transmettre(wp_, pid):
    wp_.activer("m7.wordpress.brouillons")
    wp_.tour()
    etat = _etat(pid)
    assert etat.etat == "en_revue", etat.resume()
    return etat


def _types():
    with stockage.transaction() as cnx:
        return [r[0] for r in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement).order_by(
            EVENEMENTS_SORTANTS.c.cree_le))]


def _publications_posts(wp_):
    return [p for p in wp_.simule.posts.values() if p["statut"] == "publish"]


# -- WordPress -------------------------------------------------------------------------------------------------------
def test_rien_ne_part_vers_wordpress_tant_qu_un_admin_n_a_pas_active(wp):
    _preparer(wp)
    resume = wp.tour()
    assert {v["statut"] for v in resume["executeurs"].values()} == {"inactif"}
    assert wp.simule.requetes == [] and wp.ouvertures == []  # pas une requête, pas un secret ouvert


def test_le_brouillon_est_transmis_en_brouillon_jamais_publie_et_l_ombre_ne_touche_pas_au_site(wp):
    pid = _preparer(wp)
    wp.activer("m7.wordpress.brouillons", "ombre")
    resume = wp.tour()["executeurs"]["m7.wordpress.brouillons"]
    assert resume["statut"] == "ombre" and resume["aurait"] == 1 and wp.simule.requetes == []
    wp.activer("m7.wordpress.brouillons")
    wp.tour()
    etat = _etat(pid)
    assert etat.etat == "en_revue" and etat.post_id is not None
    assert [p["statut"] for p in wp.simule.posts.values()] == ["draft"]
    wp.tour()
    assert len(wp.simule.posts) == 1  # rejouer ne crée pas un second brouillon


def test_publication_approuvee_une_seule_fois_puis_rien_au_rejeu(wp):
    pid = _preparer(wp)
    etat = _transmettre(wp, pid)
    wp.activer("m7.wordpress.publication")
    wp.tour()
    assert _publications_posts(wp) == [] and wp.transport.publications_vues == 0  # pas approuvé : rien ne part
    _approuver(wp, pid, etat.empreinte_serveur)
    ombre = None
    wp.activer("m7.wordpress.publication", "ombre")
    ombre = wp.tour()["executeurs"]["m7.wordpress.publication"]
    assert ombre["statut"] == "ombre" and ombre["aurait"] == 1 and _publications_posts(wp) == []
    wp.activer("m7.wordpress.publication")
    resume = wp.tour()["executeurs"]["m7.wordpress.publication"]
    assert resume["publies"] == 1 and len(_publications_posts(wp)) == 1 and wp.transport.publications_vues == 1
    assert _etat(pid).etat == "publie" and "m7.publication_faite" in _types()
    for _ in range(3):
        wp.tour()
    assert wp.transport.publications_vues == 1 and len(_publications_posts(wp)) == 1


def test_une_approbation_expiree_ne_transmet_rien_ferme_la_publication_et_avertit(wp):
    pid = _preparer(wp)
    etat = _transmettre(wp, pid)
    _approuver(wp, pid, etat.empreinte_serveur)
    wp.activer("m7.wordpress.publication")
    wp.horloge.avancer(3600 + 5)  # l'approbation de la direction vaut une heure
    avant = len(wp.simule.requetes)
    resume = wp.tour(avance=1)["executeurs"]["m7.wordpress.publication"]
    assert resume["expires"] == 1 and resume["code"] == "REJ-WP-APPROBATION-EXPIREE"
    assert len(wp.simule.requetes) == avant and wp.transport.publications_vues == 0  # AUCUN jeton, aucune requête
    assert _etat(pid).etat == "echec" and _publications_posts(wp) == []
    assert "m7.publication_echouee" in _types()
    wp.tour()
    assert wp.transport.publications_vues == 0


def test_un_contenu_retouche_sur_le_site_apres_l_approbation_ne_se_publie_pas(wp):
    pid = _preparer(wp)
    etat = _transmettre(wp, pid)
    _approuver(wp, pid, etat.empreinte_serveur)
    wp.simule.modifier_dans_wp_admin(etat.post_id, contenu="<p>Autre texte, retouché dans wp-admin.</p>")
    wp.activer("m7.wordpress.publication")
    wp.tour()
    assert _publications_posts(wp) == [] and wp.transport.publications_vues == 0
    assert _etat(pid).etat == "en_revue"  # la revue est rouverte, l'approbation est tombée


def test_une_reponse_perdue_est_reconciliee_en_relisant_le_site_jamais_en_renvoyant_un_jeton(wp):
    pid = _preparer(wp)
    etat = _transmettre(wp, pid)
    _approuver(wp, pid, etat.empreinte_serveur)
    wp.activer("m7.wordpress.publication")
    wp.transport.perdre_publications = 1
    resume = wp.tour()["executeurs"]["m7.wordpress.publication"]
    assert resume["erreurs"] == 1 and wp.transport.publications_vues == 1
    assert _etat(pid).etat == "approuve" and _etat(pid).jeton_emis  # le site a publié, OPSYS ne le sait pas encore
    resume = wp.tour()["executeurs"]["m7.wordpress.publication"]
    assert resume["reconcilies"] == 1 and _etat(pid).etat == "publie"
    assert wp.transport.publications_vues == 1 and len(_publications_posts(wp)) == 1  # jamais un second jeton


def test_un_brouillon_sans_site_raccorde_n_est_pas_transmis(wp):
    _preparer(wp)
    wp.ports.client_wordpress = None
    wp.activer("m7.wordpress.brouillons")
    resume = wp.tour()["executeurs"]["m7.wordpress.brouillons"]
    assert resume["code"] == "REJ-PLAN-WORDPRESS-NON-RACCORDE" and wp.simule.requetes == []


def test_six_fils_en_meme_temps_une_seule_publication(wp):
    pid = _preparer(wp)
    etat = _transmettre(wp, pid)
    _approuver(wp, pid, etat.empreinte_serveur)
    wp.activer("m7.wordpress.publication")
    barriere, erreurs, refus = threading.Barrier(6), [], []

    def fil(i):
        try:
            with systeme.contexte_planificateur() as acteur:
                ctx = planificateur.Contexte(wp.ports, acteur, f"fil-{i}", None, wp.horloge())
                executeur = PublicationWordPress()
                ressources = executeur.ressources(ctx)
                barriere.wait()
                for ressource in ressources:
                    b = bail.acquerir(executeur.cle_bail(ressource), ctx.porteur, 60, horloge=wp.horloge)
                    if b is None:
                        refus.append(i)
                        continue
                    try:
                        executeur.traiter(ressource, ctx, b)
                    finally:
                        bail.liberer(b)
        except BaseException as exc:  # noqa: BLE001
            erreurs.append(exc)

    fils = [threading.Thread(target=fil, args=(i,)) for i in range(6)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert erreurs == [] and wp.transport.publications_vues == 1 and len(_publications_posts(wp)) == 1
    assert len(refus) >= 1  # au moins un fil a trouvé le bail pris


# -- réseaux sociaux -------------------------------------------------------------------------------------------------
@pytest.fixture
def so(tmp_path, monkeypatch):
    fab = _social("fabriques_sociales")
    from m7_marketing.sas_social import comptes, doubles, politique, reseaux

    prevu = datetime(2026, 1, 6, 15, 0, 0, tzinfo=UTC)
    c = cq.monter(tmp_path, monkeypatch, debut=prevu.timestamp() - 7200)
    resultat = comptes.enregistrer(_journal("comptes_sociaux"), "facebook", fab.COMPTE,
                                   {"nom": "jeton.facebook.fictif"}, True, "nathan", fab.HORODATAGE)
    assert resultat["accepte"], resultat
    double = doubles.DoubleFacebook(jeton_attendu=fab.JETON)
    ouvertures = []

    @contextlib.contextmanager
    def secret():
        ouvertures.append(1)
        yield fab.JETON

    c.ports.adaptateurs_sociaux = lambda: {"facebook": double}
    c.ports.secret_social = lambda nom: secret
    c.fab, c.double, c.ouvertures, c.prevu = fab, double, ouvertures, prevu
    c.declarations, c.politique = reseaux.declarations_par_defaut(), politique.PolitiqueSas()
    yield c
    cq.demonter()


def _composer_et_approuver(so_, i=1, approuver=True):
    from m7_marketing.sas_social import service

    journal = _journal("publications_sociales")
    fab = so_.fab
    cree = service.composer(journal, fab.publication("facebook"), f"cle-sociale-{i:012d}",
                            {("facebook", fab.COMPTE)}, "agent", fab.HORODATAGE)
    assert cree["accepte"], cree
    pid = cree["publication_id"]
    assert service.soumettre(journal, pid, so_.declarations, so_.politique, fab.MAINTENANT, fab.HORODATAGE)["accepte"]
    if approuver:
        ok = service.approuver(journal, pid, cree["empreinte"], 3, PROPRIETAIRE, so_.declarations, so_.politique,
                               fab.MAINTENANT, fab.HORODATAGE)
        assert ok["accepte"], ok
    return pid


def _etat_social(pid):
    from m7_marketing.sas_social import service

    return service.charger(_journal("publications_sociales"))[0][pid]


def test_publication_sociale_approuvee_sort_a_l_heure_une_seule_fois(so):
    pid = _composer_et_approuver(so)
    so.activer("m7.social.publication")
    so.tour(avance=60)  # trop tôt : 1 h 58 avant l'heure approuvée
    assert so.double.appels == 0 and so.ouvertures == [] and _etat_social(pid).etat == "planifie"
    so.horloge.t = so.prevu.timestamp() + 30
    resume = so.tour(avance=60)["executeurs"]["m7.social.publication"]
    assert resume["publies"] == 1 and so.double.appels == 1 and _etat_social(pid).etat == "publie"
    assert "m7.publication_faite" in _types()
    for _ in range(3):
        so.tour()
    assert so.double.appels == 1 and len(so.double.publiees) == 1


def test_publication_sociale_non_approuvee_ne_part_jamais(so):
    pid = _composer_et_approuver(so, approuver=False)
    so.activer("m7.social.publication")
    so.horloge.t = so.prevu.timestamp() + 30
    so.tour()
    assert so.double.appels == 0 and _etat_social(pid).etat == "en_attente_approbation"


def test_publication_sociale_en_mode_ombre_dit_ce_qui_partirait_sans_appeler_le_reseau(so):
    _composer_et_approuver(so)
    so.activer("m7.social.publication", "ombre")
    so.horloge.t = so.prevu.timestamp() + 30
    resume = so.tour()["executeurs"]["m7.social.publication"]
    assert resume["statut"] == "ombre" and resume["aurait"] == 1 and so.double.appels == 0 and so.ouvertures == []


def test_heure_approuvee_trop_depassee_aucune_publication_et_echec_consigne(so):
    pid = _composer_et_approuver(so)
    so.activer("m7.social.publication")
    so.horloge.t = so.prevu.timestamp() + so.politique.tolerance_retard_s + 600
    so.tour()
    assert so.double.appels == 0 and so.ouvertures == []
    etat = _etat_social(pid)
    assert etat.etat == "echec" and etat.derniere_erreur["code"] == "REJ-SOCIAL-ECHEANCE-DEPASSEE"
    assert "m7.publication_echouee" in _types()
    so.tour()
    assert so.double.appels == 0


def test_panne_apres_l_envoi_le_planificateur_retrouve_au_lieu_de_republier(so):
    from m7_marketing.sas_social import doubles

    pid = _composer_et_approuver(so)
    so.double._scenario = iter([doubles.PANNE_APRES_ENVOI])
    so.activer("m7.social.publication")
    so.horloge.t = so.prevu.timestamp() + 30
    so.tour()
    assert len(so.double.publiees) == 1 and _etat_social(pid).incertain  # publié chez le réseau, réponse perdue
    for _ in range(3):
        so.tour()
    assert len(so.double.publiees) == 1, "aucun doublon"
    assert _etat_social(pid).etat == "publie"


def test_sans_adaptateur_raccorde_rien_ne_part(so):
    pid = _composer_et_approuver(so)
    so.ports.adaptateurs_sociaux = None
    so.activer("m7.social.publication")
    so.horloge.t = so.prevu.timestamp() + 30
    resume = so.tour()["executeurs"]["m7.social.publication"]
    assert resume["code"] == "REJ-PLAN-SOCIAL-NON-RACCORDE" and _etat_social(pid).etat == "planifie"


def test_le_jeton_du_reseau_n_entre_ni_au_journal_du_sas_ni_a_celui_du_planificateur(so):
    _composer_et_approuver(so)
    so.activer("m7.social.publication")
    so.horloge.t = so.prevu.timestamp() + 30
    so.tour()
    from opsys.connecteurs_planification import journal

    with stockage.transaction() as cnx:
        texte = repr(journal.lire(cnx)) + repr(cnx.execute(select(EVENEMENTS_SORTANTS.c.charge)).all())
    texte += repr(list(_journal("publications_sociales")))
    assert so.fab.JETON not in texte
