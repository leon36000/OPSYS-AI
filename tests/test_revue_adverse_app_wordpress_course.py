"""Revue adverse (app-01) : le jeton d'approbation WordPress ne s'émet qu'UNE fois, même quand deux exécuteurs se
croisent (bail expiré pendant `client.etat`, deux processus, redémarrage).

`publier` vérifie l'approbation, relit le site (appel réseau), PUIS consigne `jeton_emis` avant d'envoyer le jeton.
Sans précondition sur cette écriture, un second exécuteur qui a vérifié avant la consignation du premier écrit son
propre `jeton_emis` (le rang est recalculé à l'écriture) et envoie un second jeton pour la même approbation. Le plugin
finit par refuser le rejeu, mais « une approbation sert une fois » n'est plus tenu par OPSYS lui-même. Vrai socle
(SQLite migré), site simulé : AUCUN réseau, aucun WordPress.
"""

from __future__ import annotations

import contextlib
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import cablage_qa as cq
import pytest

from opsys import stockage

FICTIF = True
M7 = Path(__file__).resolve().parents[1] / "departments" / "m07-marketing"
SECRET = "secret-de-test-fictif-pour-le-simulateur-0123456789"
SITE_ID = "horizon-fictif.example"
PROPRIETAIRE = {"par": "nathan", "role": "nathan_owner", "source": "approbation"}


def _charger(nom: str):
    chemin = M7 / "tests" / "wordpress" / f"{nom}.py"
    spec = importlib.util.spec_from_file_location(f"revue_adverse_{nom}", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _journal(registre: str):
    return stockage.maillons("m07-marketing", registre)


def _instant(c) -> str:
    return datetime.fromtimestamp(c.horloge(), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Transport:
    def __init__(self, simule):
        self.simule, self.publications_vues = simule, 0

    def envoyer(self, requete):
        reponse = self.simule.envoyer(requete)
        if requete.url.endswith("/publish"):
            self.publications_vues += 1
        return reponse


@pytest.fixture
def wp(tmp_path, monkeypatch):
    from m7_marketing.wordpress import flux, sites
    from m7_marketing.wordpress.client import ClientWordPress

    c = cq.monter(tmp_path, monkeypatch)
    reference = _charger("reference_verificateur")
    simule = _charger("site_simule").SiteSimule(reference, SECRET, SITE_ID, lambda: int(c.horloge()))
    compteur = iter(range(1, 10_000_000))

    @contextlib.contextmanager
    def fournisseur():
        yield SECRET

    assert sites.enregistrer(_journal("sites_wordpress"), SITE_ID, "https://horizon-fictif.example",
                             {"nom": "wordpress.horizon-fictif", "cle_id": "default"}, ["post", "page"], True,
                             "nathan", _instant(c))["accepte"]
    transport = Transport(simule)
    site = sites.actifs(_journal("sites_wordpress"))[SITE_ID]
    c.client = ClientWordPress(site, fournisseur, transport, lambda: int(c.horloge()),
                               lambda: f"nonce-revue-{next(compteur):012d}")
    c.simule, c.transport = simule, transport
    article = {"type": "post", "titre": "Entretien des gouttières", "contenu": "<p>Texte sobre.</p>",
               "extrait": "", "slug": ""}
    prep = flux.preparer(_journal("publications_wordpress"), sites.actifs(_journal("sites_wordpress")), SITE_ID,
                         article, "draft", "cle-revue-000000000001", True, "agent", _instant(c))
    assert prep["accepte"], prep
    c.pid = prep["publication_id"]
    yield c
    cq.demonter()


def _maintenant(c):
    return datetime.fromtimestamp(c.horloge(), UTC)


def _approuver(c):
    from m7_marketing.wordpress import executeur, flux

    journal = _journal("publications_wordpress")
    assert executeur.transmettre_brouillon(journal, c.pid, c.client, _maintenant(c))["accepte"]
    empreinte = flux.plier(journal)[c.pid].empreinte_serveur
    ok = flux.approuver(journal, c.pid, empreinte, "publish", None, PROPRIETAIRE, _maintenant(c), _instant(c))
    assert ok["accepte"], ok


class ClientLent:
    """Le client du premier exécuteur : pendant sa relecture du site (réseau lent), un second exécuteur passe."""

    def __init__(self, reel, autre):
        self._reel, self._autre, self.deja = reel, autre, False

    def etat(self, post_id):
        lu = self._reel.etat(post_id)  # l'état du site tel qu'avant toute publication : il correspond à l'approbation
        if not self.deja:
            self.deja = True
            self._autre()
        return lu

    def publier(self, approbation):
        return self._reel.publier(approbation)


def test_deux_executeurs_qui_se_croisent_n_emettent_qu_un_jeton(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import executeur, flux

    _approuver(wp)
    journal = _journal("publications_wordpress")
    autre = lambda: executeur.publier(journal, wp.pid, wp.client, _maintenant(wp))  # noqa: E731
    resultat = executeur.publier(journal, wp.pid, ClientLent(wp.client, autre), _maintenant(wp))

    jetons = [m for m in journal_chaine.de_type(journal, flux.M_JETON) if m["publication_id"] == wp.pid]
    assert len(jetons) == 1, "la même approbation a servi à émettre deux jetons"
    assert wp.transport.publications_vues == 1, "le site a reçu deux demandes de publication pour une approbation"
    assert resultat["accepte"] is False and resultat["refus"][0]["code"] == flux.REJ_APPROBATION_UTILISEE
    # L'exécuteur perdant ne doit RIEN écrire : la publication sortie par l'autre reste « publiée », jamais « échec ».
    assert flux.plier(journal)[wp.pid].etat == "publie"
    assert journal_chaine.integre(journal)


def test_sans_croisement_la_publication_normale_reste_acceptee_et_ne_se_rejoue_pas(wp):
    from m7_marketing.wordpress import executeur, flux

    _approuver(wp)
    journal = _journal("publications_wordpress")
    premier = executeur.publier(journal, wp.pid, wp.client, _maintenant(wp))
    assert premier["accepte"] is True and flux.plier(journal)[wp.pid].etat == "publie"
    second = executeur.publier(journal, wp.pid, wp.client, _maintenant(wp))
    assert second["accepte"] is False and wp.transport.publications_vues == 1


class JournalQuiBouge:
    """Le journal durable vu par un exécuteur lent : après la fin de la première lecture complète, un AUTRE exécuteur
    écrit (`apres_lecture`) ; `longueur_perimee` fait mentir le premier `len` (la fenêtre entre le contrôle du rang et
    l'écriture elle-même)."""

    def __init__(self, reel, apres_lecture=None, longueur_perimee=None, lecture_visee=2):
        self._reel, self._apres, self._perimee = reel, apres_lecture, longueur_perimee
        # `charger` lit deux fois : vérification de la chaîne, puis pliage.
        self._lectures, self._visee = 0, lecture_visee

    def __len__(self):
        if self._perimee is not None:
            valeur, self._perimee = self._perimee, None
            return valeur
        return len(self._reel)

    def __iter__(self):
        liste = list(self._reel)
        self._lectures += 1
        derniere = self._lectures == self._visee
        yield from liste
        if derniere and self._apres is not None:
            declencher, self._apres = self._apres, None
            declencher()  # la lecture visée est finie : l'état rendu à l'exécuteur lent est déjà périmé

    def __getitem__(self, index):
        return self._reel[index]

    def append(self, maillon, **options):
        self._reel.append(maillon, **options)


def _verifiee(wp):
    from m7_marketing.wordpress import flux

    approbation = flux.approbation_verifiee(_journal("publications_wordpress"), wp.pid, _maintenant(wp))
    assert isinstance(approbation, flux.ApprobationVerifiee), approbation
    return approbation


def test_un_executeur_qui_ecrit_pendant_la_relecture_de_l_etat_fait_refuser_la_consignation(wp):
    """Le rang est lu AVANT l'état : si un autre exécuteur écrit juste après cette lecture, la consignation échoue."""
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")
    approbation = _verifiee(wp)

    def autre_ecrit():
        flux.annuler(reel, wp.pid, "autre exécuteur", "écrit entre la lecture et l'écriture", _instant(wp))

    proxy = JournalQuiBouge(reel, apres_lecture=autre_ecrit)
    refus = flux.consigner_jeton_emis(proxy, approbation, _instant(wp))
    assert refus is not None and refus["refus"][0]["code"] == flux.REJ_APPROBATION_UTILISEE
    assert not [m for m in journal_chaine.de_type(reel, flux.M_JETON) if m["publication_id"] == wp.pid]


def test_la_precondition_de_rang_est_refaite_en_base_a_l_ecriture(wp):
    """Même si le contrôle du rang passe (longueur périmée), la base refuse l'écriture au mauvais rang."""
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")
    taille = len(reel)
    flux.annuler(reel, wp.pid, "autre exécuteur", "écrit entre la lecture et l'écriture", _instant(wp))
    proxy = JournalQuiBouge(reel, longueur_perimee=taille)  # l'exécuteur lent croit encore à l'ancien rang
    with pytest.raises(journal_chaine.ConcurrenceJournal):
        journal_chaine.ajouter(proxy, "jeton_emis", {"publication_id": wp.pid}, _instant(wp), rang_attendu=taille)
    assert len(reel) == taille + 1


def test_la_consignation_est_acceptee_quand_rien_n_a_bouge(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")
    assert flux.consigner_jeton_emis(reel, _verifiee(wp), _instant(wp)) is None
    assert len([m for m in journal_chaine.de_type(reel, flux.M_JETON) if m["publication_id"] == wp.pid]) == 1
    assert flux.consigner_jeton_emis(reel, _verifiee_apres(wp), _instant(wp)) is not None  # sert une fois


def _verifiee_apres(wp):
    from m7_marketing.wordpress import flux

    courant = flux.plier(_journal("publications_wordpress"))[wp.pid]
    return flux.ApprobationVerifiee(
        publication_id=wp.pid, approval_id=courant.approbation["approval_id"], site_id=courant.site_id,
        post_id=courant.post_id, empreinte=courant.approbation["empreinte"], action="publish", publish_at=None,
        approuve_par="nathan", emis_le=courant.approbation["emis_le"], expire_le=courant.approbation["expire_le"])


# -- app-02 : une annulation (outil d'agent N2) ou un instantané périmé n'empoisonnent pas le registre ---------------


def _registre_sain(journal):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    tous, refus = flux.charger(journal)
    assert refus is None, refus  # avant le correctif : REJ-WP-JOURNAL-INCOHERENT, pour toujours
    assert journal_chaine.integre(journal)
    return tous


class ClientAnnuleEnVol:
    """Pendant l'appel au site (jeton parti), un agent annule la publication (`m7_annuler_publication_wordpress`)."""

    def __init__(self, reel, journal, pid):
        self._reel, self._journal, self._pid = reel, journal, pid

    def etat(self, post_id):
        return self._reel.etat(post_id)

    def publier(self, approbation):
        from m7_marketing.wordpress import flux

        annulation = flux.annuler(self._journal, self._pid, "agent", "stop", "2026-01-01T00:00:00Z")
        assert annulation["accepte"], annulation
        return self._reel.publier(approbation)


def test_une_annulation_pendant_l_appel_au_site_n_empoisonne_pas_le_registre(wp):
    from m7_marketing.wordpress import executeur

    _approuver(wp)
    journal = _journal("publications_wordpress")
    executeur.publier(journal, wp.pid, ClientAnnuleEnVol(wp.client, journal, wp.pid), _maintenant(wp))

    assert wp.transport.publications_vues == 1  # le site a publié
    tous = _registre_sain(journal)
    assert tous[wp.pid].etat == "publie"  # la vérité : l'article est sorti malgré l'annulation tardive


def test_un_echec_du_site_apres_une_annulation_en_vol_n_empoisonne_pas_le_registre(wp):
    from m7_marketing.wordpress import executeur, flux

    _approuver(wp)
    journal = _journal("publications_wordpress")

    class ClientQuiRefuse(ClientAnnuleEnVol):
        def publier(self, approbation):
            assert flux.annuler(self._journal, self._pid, "agent", "stop", "2026-01-01T00:00:00Z")["accepte"]
            return {"accepte": False, "refus": [{"code": "REJ-WP-PLUGIN-REFUSE", "chemin": "$", "detail": "refusé"}]}

    executeur.publier(journal, wp.pid, ClientQuiRefuse(wp.client, journal, wp.pid), _maintenant(wp))

    assert _registre_sain(journal)[wp.pid].etat == "annule"  # l'annulation tient : l'échec tardif ne la défait pas


def test_un_instantane_perime_ne_fait_pas_ecrire_un_echec_sur_une_publication_annulee(wp, monkeypatch):
    """`PublicationWordPress.traiter` boucle sur un instantané pris en début de tour : une publication annulée
    entre-temps n'est plus « approuvée » ; l'écriture de l'échec d'approbation ne doit pas la suivre."""
    from m7_marketing.wordpress import flux

    from opsys.connecteurs_planification import exec_m7
    from opsys.connecteurs_planification.planificateur import Contexte

    _approuver(wp)
    journal = _journal("publications_wordpress")
    executeur = exec_m7.PublicationWordPress()
    instantane = executeur._par_site(None, "approuve")
    assert instantane  # la publication est « approuvée » dans l'instantané
    assert flux.annuler(journal, wp.pid, "agent", "annulée entre-temps", _instant(wp))["accepte"]
    monkeypatch.setattr(exec_m7.PublicationWordPress, "_par_site", lambda self, ctx, etat, filtre=None: instantane)
    monkeypatch.setattr(exec_m7.PublicationWordPress, "_client", lambda self, ctx, site_id: (exec_m7._m7(), wp.client))

    class Ctx(Contexte):
        def exiger_actif(self, bail):
            return bail

    resume = executeur.traiter(SITE_ID, Ctx(wp.ports, None, "essai", None, wp.horloge()), None)

    assert _registre_sain(journal)[wp.pid].etat == "annule"
    assert wp.transport.publications_vues == 0
    assert resume["expires"] == 0 and resume["code"] is None  # rien d'écrit, rien de compté


def test_une_publication_normale_et_une_annulation_normale_restent_acceptees(wp):
    from m7_marketing.wordpress import flux

    journal = _journal("publications_wordpress")
    assert flux.annuler(journal, wp.pid, "agent", "avant approbation", _instant(wp))["accepte"]
    assert _registre_sain(journal)[wp.pid].etat == "annule"


def test_un_echec_consigne_pendant_qu_un_autre_annule_est_refuse_par_la_comparaison_echange(wp):
    """Le rang est lu AVANT l'état : une annulation écrite juste après la lecture fait refuser l'échec."""
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")

    def annule():
        assert flux.annuler(reel, wp.pid, "agent", "stop", _instant(wp))["accepte"]

    proxy = JournalQuiBouge(reel, apres_lecture=annule)
    assert flux.consigner_echec(proxy, wp.pid, "REJ-X", "détail", _instant(wp)) is False
    assert _registre_sain(reel)[wp.pid].etat == "annule"


def test_un_echec_d_approbation_expiree_se_consigne_quand_la_publication_est_toujours_approuvee(wp):
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")
    assert flux.consigner_echec(reel, wp.pid, "REJ-WP-APPROBATION-EXPIREE", "expirée", _instant(wp)) is True
    assert _registre_sain(reel)[wp.pid].etat == "echec"


def test_un_publie_forge_apres_une_annulation_sans_jeton_reste_un_journal_incoherent(wp):
    """La tolérance de `publie` après annulation ne vaut QUE si le jeton est parti (le site a pu publier)."""
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")
    assert flux.annuler(reel, wp.pid, "agent", "stop", _instant(wp))["accepte"]  # approuvée mais AUCUN jeton émis
    journal_chaine.ajouter(reel, flux.M_PUBLIE, {"publication_id": wp.pid, "statut_site": "publish",
                                                 "lien_public": None}, _instant(wp))
    tous, refus = flux.charger(reel)
    assert refus is not None and refus["refus"][0]["code"] == flux.REJ_INCOHERENT


def test_une_annulation_pendant_la_transmission_du_brouillon_n_empoisonne_pas_le_registre(wp):
    """`transmettre_brouillon` appelle le site (réseau) puis consigne le résultat ; un agent annule entre les deux."""
    from m7_marketing.wordpress import executeur, flux

    journal = _journal("publications_wordpress")

    class ClientQuiEchoue:
        def creer_brouillon(self, *args):
            assert flux.annuler(journal, wp.pid, "agent", "stop", _instant(wp))["accepte"]
            return {"accepte": False, "refus": [{"code": "REJ-WP-TRANSPORT", "chemin": "$", "detail": "délai dépassé"}]}

    executeur.transmettre_brouillon(journal, wp.pid, ClientQuiEchoue(), _maintenant(wp))
    assert _registre_sain(journal)[wp.pid].etat == "annule"


def test_une_transmission_reussie_pendant_qu_un_autre_ecrit_est_refusee_par_la_comparaison_echange(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    reel = _journal("publications_wordpress")

    def autre_annule():
        assert flux.annuler(reel, wp.pid, "agent", "stop", _instant(wp))["accepte"]

    proxy = JournalQuiBouge(reel, apres_lecture=autre_annule)
    refus = flux.consigner_transmission(proxy, wp.pid, 42, "a" * 64, _instant(wp))
    assert refus["accepte"] is False and refus["refus"][0]["code"] == flux.REJ_ETAT
    assert not journal_chaine.de_type(reel, flux.M_TRANSMIS)
    assert _registre_sain(reel)[wp.pid].etat == "annule"


def test_un_echec_de_transmission_se_consigne_pour_un_brouillon_toujours_a_transmettre(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    reel = _journal("publications_wordpress")
    assert flux.consigner_echec_transmission(reel, wp.pid, "REJ-WP-TRANSPORT", "délai dépassé", _instant(wp)) is True
    assert len(journal_chaine.de_type(reel, flux.M_TRANSMISSION_ECHEC)) == 1
    assert _registre_sain(reel)[wp.pid].etat == "brouillon"


def test_un_echec_de_transmission_pendant_qu_un_autre_annule_est_refuse_par_la_comparaison_echange(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    reel = _journal("publications_wordpress")

    def autre_annule():
        assert flux.annuler(reel, wp.pid, "agent", "stop", _instant(wp))["accepte"]

    proxy = JournalQuiBouge(reel, apres_lecture=autre_annule)
    assert flux.consigner_echec_transmission(proxy, wp.pid, "REJ-X", "détail", _instant(wp)) is False
    assert not journal_chaine.de_type(reel, flux.M_TRANSMISSION_ECHEC)
    assert _registre_sain(reel)[wp.pid].etat == "annule"


def test_deux_executeurs_qui_consignent_la_meme_publication_n_empoisonnent_pas_le_registre(wp):
    """A publie (appel au site en cours) ; B, qui voit « jeton émis, ni publiée ni échec », réconcilie en relisant le
    site et consigne `publie` AVANT A. La seconde écriture de `publie` rendait le registre incohérent pour toujours."""
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import executeur, flux

    _approuver(wp)
    journal = _journal("publications_wordpress")

    class ClientOuLAutreReconcilie(ClientAnnuleEnVol):
        def publier(self, approbation):
            resultat = self._reel.publier(approbation)  # le site a publié
            executeur.reconcilier(self._journal, self._pid, self._reel, _maintenant(wp))  # B passe avant la fin de A
            return resultat

    resultat = executeur.publier(journal, wp.pid, ClientOuLAutreReconcilie(wp.client, journal, wp.pid), _maintenant(wp))

    assert resultat["accepte"] is True
    tous = _registre_sain(journal)
    assert tous[wp.pid].etat == "publie"
    assert len([m for m in journal_chaine.de_type(journal, flux.M_PUBLIE) if m["publication_id"] == wp.pid]) == 1


def test_consigner_publication_est_idempotente_et_refuse_hors_etat(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    reel = _journal("publications_wordpress")
    # Pas d'approbation ni de jeton : rien à consigner, rien d'écrit.
    assert flux.consigner_publication(reel, wp.pid, "publish", None, _instant(wp)) is False
    assert not journal_chaine.de_type(reel, flux.M_PUBLIE)
    _approuver(wp)
    assert flux.consigner_jeton_emis(reel, _verifiee(wp), _instant(wp)) is None
    assert flux.consigner_publication(reel, wp.pid, "publish", None, _instant(wp)) is True
    assert flux.consigner_publication(reel, wp.pid, "publish", None, _instant(wp)) is False  # une fois
    assert _registre_sain(reel)[wp.pid].etat == "publie"


def test_une_publication_consignee_pendant_qu_un_autre_ecrit_est_refusee_par_la_comparaison_echange(wp):
    from m7_marketing import journal_chaine
    from m7_marketing.wordpress import flux

    _approuver(wp)
    reel = _journal("publications_wordpress")
    assert flux.consigner_jeton_emis(reel, _verifiee(wp), _instant(wp)) is None

    def autre_consigne():
        assert flux.consigner_publication(reel, wp.pid, "publish", None, _instant(wp)) is True

    proxy = JournalQuiBouge(reel, apres_lecture=autre_consigne)
    assert flux.consigner_publication(proxy, wp.pid, "publish", None, _instant(wp)) is False
    assert len(journal_chaine.de_type(reel, flux.M_PUBLIE)) == 1
    _registre_sain(reel)


# -- app-04 : l'heure d'une approbation WordPress est celle du SERVEUR à la décision, pas l'argument d'un agent ----


def _decider_via_la_file(wp, arguments):
    """Un agent dépose la demande N3 (arguments à lui) ; le propriétaire l'approuve par le chemin de la console."""
    from opsys import approbations
    from opsys.capacites import outils_executables
    from opsys.departements import lire_manifeste
    from opsys.outils import Niveau

    dep7 = lire_manifeste(M7)
    departements = {dep7.id: dep7}
    outils = outils_executables(departements, stockage.transaction)
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, dep7.id, "m7_demander_publication_wordpress", arguments,
                                           niveau=Niveau.N3)
        return approbations.decider(cnx, ident, True, "nathan", outils, departements)


def _preparer_en_revue(wp):
    from m7_marketing.wordpress import executeur, flux

    journal = _journal("publications_wordpress")
    assert executeur.transmettre_brouillon(journal, wp.pid, wp.client, _maintenant(wp))["accepte"]
    return flux.plier(journal)[wp.pid].empreinte_serveur


def test_un_agent_ne_peut_pas_fixer_l_heure_d_une_approbation_wordpress(wp):
    """L'agent dépose `horodatage` = 2099 : l'approbation « valable une heure » le serait jusqu'en 2099, et une
    approbation donnée aujourd'hui servirait n'importe quand (exécuteur activé des mois plus tard)."""
    from m7_marketing.wordpress import flux

    empreinte = _preparer_en_revue(wp)
    decision = _decider_via_la_file(wp, {
        "publication_id": wp.pid, "empreinte": empreinte, "action": "publish", "horodatage": "2099-01-01T00:00:00Z"})
    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"] is True, decision

    approbation = flux.plier(_journal("publications_wordpress"))[wp.pid].approbation
    maintenant = wp.horloge()
    assert approbation["emis_le"] <= int(maintenant) + 5, "l'approbation porte l'heure fixée par l'agent"
    assert approbation["expire_le"] == approbation["emis_le"] + flux.VALIDITE_APPROBATION_S
    # Le lendemain, elle est expirée : l'exécuteur ne publie plus rien.
    apres = datetime.fromtimestamp(maintenant + 2 * 86400, UTC)
    refus = flux.approbation_verifiee(_journal("publications_wordpress"), wp.pid, apres)
    assert isinstance(refus, dict) and refus["refus"][0]["code"] == flux.REJ_APPROBATION_EXPIREE


def test_une_heure_passee_par_un_agent_ne_contourne_pas_le_delai_minimal_d_une_planification(wp):
    """`schedule` exige 5 minutes d'avance sur l'heure de l'approbation : cette heure n'est pas celle de l'agent."""
    empreinte = _preparer_en_revue(wp)
    trop_proche = datetime.fromtimestamp(wp.horloge() + 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    decision = _decider_via_la_file(wp, {
        "publication_id": wp.pid, "empreinte": empreinte, "action": "schedule", "publier_le": trop_proche,
        "horodatage": "2020-01-01T00:00:00Z"})  # l'agent recule l'horloge : 60 s deviennent « des années d'avance »
    assert decision["reponse"]["resultat"]["accepte"] is False, decision


def test_l_approbation_par_la_file_garde_l_heure_du_serveur_et_reste_acceptee(wp):
    from m7_marketing.wordpress import flux

    empreinte = _preparer_en_revue(wp)
    decision = _decider_via_la_file(wp, {
        "publication_id": wp.pid, "empreinte": empreinte, "action": "publish", "horodatage": _instant(wp)})
    assert decision["reponse"]["resultat"]["accepte"] is True, decision
    approbation = flux.plier(_journal("publications_wordpress"))[wp.pid].approbation
    assert abs(approbation["emis_le"] - int(wp.horloge())) <= 5


def test_l_heure_d_une_approbation_sociale_par_la_file_est_celle_du_serveur(tmp_path, monkeypatch):
    """Même défaut côté réseaux sociaux : l'agent recule l'horloge de la demande pour faire accepter une publication
    dont l'heure approuvée est DÉJÀ passée (délai minimal et horizon calculés sur son `horodatage`)."""
    import sys

    from opsys import approbations
    from opsys.capacites import outils_executables
    from opsys.departements import lire_manifeste
    from opsys.outils import Niveau

    sys.path.insert(0, str(M7 / "tests" / "sas_social"))
    import fabriques_sociales as fab
    from m7_marketing.sas_social import comptes, reseaux, service
    from m7_marketing.sas_social.politique import PolitiqueSas

    cq.monter(tmp_path, monkeypatch)
    try:
        secret = {"nom": "jeton.facebook.fictif"}
        assert comptes.enregistrer(_journal("comptes_sociaux"), "facebook", fab.COMPTE, secret, True, "nathan",
                                   fab.HORODATAGE)["accepte"]
        journal = _journal("publications_sociales")
        cree = service.composer(journal, fab.publication("facebook"), "cle-revue-sociale-0001",
                                {("facebook", fab.COMPTE)}, "agent", fab.HORODATAGE)
        declarations = reseaux.declarations_par_defaut()
        assert service.soumettre(journal, cree["publication_id"], declarations, PolitiqueSas(), fab.MAINTENANT,
                                 fab.HORODATAGE)["accepte"]
        dep7 = lire_manifeste(M7)
        departements = {dep7.id: dep7}
        outils = outils_executables(departements, stockage.transaction)
        with stockage.transaction() as cnx:
            ident = approbations.creer_demande(
                cnx, dep7.id, "m7_demander_publication_sociale",
                {"publication_id": cree["publication_id"], "empreinte": cree["empreinte"],
                 "horodatage": fab.HORODATAGE},  # janvier 2026 : l'heure approuvée (6 janvier) paraît « demain »
                niveau=Niveau.N3)
            decision = approbations.decider(cnx, ident, True, "nathan", outils, departements)
        assert decision["reponse"]["resultat"]["accepte"] is False, decision  # l'heure approuvée est passée
        assert service.charger(journal)[0][cree["publication_id"]].etat == "en_attente_approbation"
    finally:
        sys.path.remove(str(M7 / "tests" / "sas_social"))
        cq.demonter()


def _demande_en_cours(statut="en_cours", decide_le="2026-11-01T12:00:00+00:00"):
    from sqlalchemy import update

    from opsys import approbations
    from opsys.outils import Niveau
    from opsys.stockage.schema import APPROBATIONS

    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, "m07-marketing", "m7_demander_publication_wordpress", {"x": 1},
                                           niveau=Niveau.N3)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(statut=statut, decide_le=decide_le))
    return ident


def test_instant_de_la_decision_en_cours_ne_vaut_que_pour_la_demande_en_cours_d_execution(wp):
    from opsys import approbations, contexte

    ident = _demande_en_cours()
    with stockage.transaction() as cnx:
        assert approbations.instant_de_la_decision_en_cours(cnx) is None  # aucune décision en cours
        with contexte.executer_demande_approuvee(ident):
            instant = approbations.instant_de_la_decision_en_cours(cnx)
            assert instant == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
            assert approbations.instant_de_la_decision_en_cours(None) is None  # hors transaction : fermé
    for statut in ("en_attente", "executee", "refusee", "echec"):
        autre = _demande_en_cours(statut=statut)
        with stockage.transaction() as cnx, contexte.executer_demande_approuvee(autre):
            assert approbations.instant_de_la_decision_en_cours(cnx) is None, statut  # seule `en_cours` compte
    illisible = _demande_en_cours(decide_le="pas une date")
    with stockage.transaction() as cnx, contexte.executer_demande_approuvee(illisible):
        assert approbations.instant_de_la_decision_en_cours(cnx) is None
    with stockage.transaction() as cnx, contexte.executer_demande_approuvee("inconnue00000"):
        assert approbations.instant_de_la_decision_en_cours(cnx) is None


def test_pendant_un_appel_d_appareil_l_heure_de_reception_reste_celle_qui_fait_foi(wp):
    from m7_marketing import publication_outils

    from opsys import contexte

    ident = _demande_en_cours()
    recu = datetime(2026, 12, 25, 8, 30, tzinfo=UTC)
    with stockage.transaction(), contexte.executer_demande_approuvee(ident), contexte.receptionne_de(
        contexte.HorodatageAppareil("tel-fictif-1", recu, recu)
    ):
        assert publication_outils._horodatage("2020-01-01T00:00:00Z")[1] == recu
    with stockage.transaction(), contexte.executer_demande_approuvee(ident):
        assert publication_outils._horodatage("2020-01-01T00:00:00Z")[1] == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    with stockage.transaction():  # appel d'agent direct (N2) : l'argument reste la règle, comme avant
        assert publication_outils._horodatage("2020-01-01T00:00:00Z")[1] == datetime(2020, 1, 1, tzinfo=UTC)
        assert isinstance(publication_outils._horodatage("pas une date"), dict)
