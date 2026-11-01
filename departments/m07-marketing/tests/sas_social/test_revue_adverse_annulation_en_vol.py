"""Revue adverse (app-02) : une annulation (outil d'agent N2) posée pendant qu'une publication sort ne doit pas
EMPOISONNER le registre.

Le registre social est le pliage de ses maillons ; un maillon impossible depuis l'état courant rend le journal
incohérent POUR TOUJOURS (`REJ-SOCIAL-JOURNAL-INCOHERENT` : l'exécuteur, la lecture de la file, toute composition
échouent, et le journal est append-only : rien ne s'enlève). Or `executer` écrit `publiee` / `echec` APRÈS l'appel
réseau, et `annuler` est permise sur une publication planifiée dont une tentative est ouverte. Un agent (ou un humain)
qui annule pendant l'appel réseau fait donc écrire `publiee` depuis `annule` : le message est sorti, le registre est
mort. Doubles de test, journaux en liste : aucun réseau.
"""

from __future__ import annotations

import contextlib
import dataclasses
from datetime import UTC, datetime

import pytest
from fabriques_sociales import HORODATAGE, JETON, MAINTENANT, publication
from m7_marketing import journal_chaine
from m7_marketing.sas_social import doubles, etats, executeur, garde_fous, service

FICTIF = True
HEURE_PREVUE = datetime(2026, 1, 6, 15, 0, 0, tzinfo=UTC)


@contextlib.contextmanager
def _jeton():
    yield JETON


def _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire):
    cree = service.composer(journal, publication("facebook"), "cle-annul-0123456789ab", comptes_actifs, "agent",
                            HORODATAGE)
    assert service.soumettre(journal, cree["publication_id"], declarations, politique_sas, MAINTENANT, HORODATAGE)[
        "accepte"]
    ok = service.approuver(journal, cree["publication_id"], cree["empreinte"], 3, proprietaire, declarations,
                           politique_sas, MAINTENANT, HORODATAGE)
    assert ok["accepte"], ok
    return cree["publication_id"]


class DoubleQuiAnnule(doubles.DoubleFacebook):
    """Pendant l'appel réseau (le message sort), un agent annule la publication."""

    def __init__(self, journal, pid, **options):
        super().__init__(**options)
        self._journal, self._pid = journal, pid

    def publier(self, requete, jeton_acces):
        resultat = super().publier(requete, jeton_acces)
        annulation = service.annuler(self._journal, self._pid, "agent", "je change d'avis", HORODATAGE)
        assert annulation["accepte"], annulation  # l'annulation d'une planifiée en vol EST permise
        return resultat


def _registre_sain(journal):
    tous, refus = service.charger(journal)
    assert refus is None, refus
    assert journal_chaine.integre(journal)
    return tous


def test_une_annulation_pendant_l_appel_reseau_n_empoisonne_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = DoubleQuiAnnule(journal, pid)
    executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)

    assert len(double.publiees) == 1
    tous = _registre_sain(journal)  # avant le correctif : REJ-SOCIAL-JOURNAL-INCOHERENT, pour toujours
    # La vérité est consignée : le message est SORTI malgré l'annulation tardive (rien ne se retire d'un réseau).
    assert tous[pid].etat == etats.PUBLIE and tous[pid].id_externe == "facebook-000001"


def test_une_annulation_pendant_un_echec_reseau_n_empoisonne_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)

    class EchecApresAnnulation(doubles.DoubleFacebook):
        def publier(self, requete, jeton_acces):
            service.annuler(journal, pid, "agent", "stop", HORODATAGE)
            return super().publier(requete, jeton_acces)

    double = EchecApresAnnulation(scenario=[doubles.PANNE_AVANT_ENVOI])
    executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)

    tous = _registre_sain(journal)
    assert tous[pid].etat == etats.ANNULE  # l'annulation tient : l'échec tardif ne la défait pas


def test_une_annulation_entre_la_lecture_et_la_tentative_n_empoisonne_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire, monkeypatch
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()
    reel = garde_fous.quota_respecte
    fait = {"oui": False}

    def annule_puis_continue(*args, **kwargs):
        if not fait["oui"]:
            fait["oui"] = True
            assert service.annuler(journal, pid, "agent", "stop", HORODATAGE)["accepte"]
        return reel(*args, **kwargs)

    monkeypatch.setattr(garde_fous, "quota_respecte", annule_puis_continue)
    resultat = executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)

    assert double.publiees == [] and resultat["publie"] is False  # rien ne part après une annulation
    assert _registre_sain(journal)[pid].etat == etats.ANNULE


def test_une_annulation_entre_la_lecture_et_l_echec_de_controle_n_empoisonne_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire, monkeypatch
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()

    def annule_et_refuse(*args, **kwargs):
        assert service.annuler(journal, pid, "agent", "stop", HORODATAGE)["accepte"]
        return [{"code": "REJ-CONTENU-FICTIF", "chemin": "$", "detail": "contrôle de sortie refusé"}]

    monkeypatch.setattr(garde_fous, "controler_contenu", annule_et_refuse)
    executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)

    assert double.publiees == []
    assert _registre_sain(journal)[pid].etat == etats.ANNULE


def test_une_annulation_entre_la_lecture_et_la_reprise_n_empoisonne_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire, monkeypatch
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook(scenario=[doubles.PANNE_AVANT_ENVOI])
    executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)
    assert service.charger(journal)[0][pid].etat == etats.ECHEC
    reel = service.charger
    fait = {"oui": False}

    def lit_puis_annule(j):
        lu = reel(j)
        if not fait["oui"]:
            fait["oui"] = True
            assert service.annuler(j, pid, "agent", "stop", HORODATAGE)["accepte"]
        return lu

    monkeypatch.setattr(service, "charger", lit_puis_annule)
    executeur.reprendre(journal, pid, politique_sas, HORODATAGE)
    monkeypatch.setattr(service, "charger", reel)
    assert _registre_sain(journal)[pid].etat == etats.ANNULE


def test_sans_annulation_la_sortie_normale_et_l_annulation_normale_restent_acceptees(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()
    assert executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)["publie"]
    assert _registre_sain(journal)[pid].etat == etats.PUBLIE
    # `publie` reste terminal pour une annulation POSÉE APRÈS la sortie : rien ne se retire d'un réseau.
    assert service.annuler(journal, pid, "agent", "trop tard", HORODATAGE)["accepte"] is False

    autre = service.composer(journal, publication("facebook"), "cle-annul-autre-0123456", comptes_actifs, "agent",
                             HORODATAGE)
    assert service.annuler(journal, autre["publication_id"], "agent", "stop", HORODATAGE)["accepte"]
    assert _registre_sain(journal)[autre["publication_id"]].etat == etats.ANNULE


def test_une_annulation_ne_ressuscite_pas_apres_coup(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    """Un `publiee` forgé ou rejoué depuis une annulation SANS tentative ouverte reste un journal incohérent."""
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    assert service.annuler(journal, pid, "agent", "stop", HORODATAGE)["accepte"]
    journal_chaine.ajouter(journal, etats.MAILLON_PUBLIEE, {
        "publication_id": pid, "id_externe": "x", "url": None, "publie_le": HORODATAGE, "publie_le_externe": None,
        "tentative": 1, "retrouvee": False}, HORODATAGE)
    tous, refus = service.charger(journal)
    assert refus is not None and refus["refus"][0]["code"] == etats.REJ_JOURNAL_INCOHERENT
    del tous


@pytest.mark.parametrize("variante", ["echeance_depassee", "tentatives_epuisees"])
def test_une_annulation_entre_la_lecture_et_les_autres_echecs_de_controle_n_empoisonne_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire, monkeypatch, variante
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    double = doubles.DoubleFacebook()
    instant = HEURE_PREVUE
    if variante == "echeance_depassee":
        politique_sas = dataclasses.replace(politique_sas, tolerance_retard_s=0)
        instant = HEURE_PREVUE.replace(second=30)  # 30 s après l'heure approuvée, tolérance nulle
    else:
        politique_sas = dataclasses.replace(politique_sas, tentatives_max=0)
    reel = service._adaptateur_de

    def annule_puis_continue(*args, **kwargs):
        assert service.annuler(journal, pid, "agent", "stop", HORODATAGE)["accepte"]
        return reel(*args, **kwargs)

    monkeypatch.setattr(service, "_adaptateur_de", annule_puis_continue)
    executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, instant)

    assert double.publiees == []
    assert _registre_sain(journal)[pid].etat == etats.ANNULE


def test_deux_executeurs_qui_finalisent_la_meme_publication_n_empoisonnent_pas_le_registre(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    """A est dans l'appel réseau ; B, qui voit une tentative ouverte, RETROUVE le message et consigne `publiee`
    AVANT A. La seconde écriture de `publiee` (publie -> publie) rendait le registre incohérent pour toujours."""
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)

    class DoubleOuLAutreRetrouve(doubles.DoubleFacebook):
        def publier(self, requete, jeton_acces):
            resultat = super().publier(requete, jeton_acces)  # le message est sorti
            executeur.executer(journal, pid, {"facebook": self}, _jeton, politique_sas, HEURE_PREVUE)  # B passe avant
            return resultat

    double = DoubleOuLAutreRetrouve()
    resultat = executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)

    assert len(double.publiees) == 1 and resultat["publie"] is True
    tous = _registre_sain(journal)
    assert tous[pid].etat == etats.PUBLIE
    assert len(journal_chaine.de_type(journal, etats.MAILLON_PUBLIEE)) == 1


def test_un_echec_reseau_tardif_ne_defait_pas_une_publication_deja_consignee(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    """A échoue (« délai dépassé après l'envoi ») pendant que B a déjà retrouvé et consigné la publication."""
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)

    class DoubleOuLAutreRetrouve(doubles.DoubleFacebook):
        def publier(self, requete, jeton_acces):
            try:
                super().publier(requete, jeton_acces)  # PANNE_APRES_ENVOI : sorti, réponse perdue
            finally:
                executeur.executer(journal, pid, {"facebook": self}, _jeton, politique_sas, HEURE_PREVUE)
            raise AssertionError("inatteignable")

    double = DoubleOuLAutreRetrouve(scenario=[doubles.PANNE_APRES_ENVOI])
    executeur.executer(journal, pid, {"facebook": double}, _jeton, politique_sas, HEURE_PREVUE)

    tous = _registre_sain(journal)
    assert tous[pid].etat == etats.PUBLIE and len(double.publiees) == 1


class JournalQuiBouge(list):
    """Un journal en liste où un AUTRE exécuteur écrit juste après la fin de la lecture visée (la deuxième : `charger`
    vérifie la chaîne puis plie)."""

    def __init__(self, contenu, apres_lecture):
        super().__init__(contenu)
        self._apres, self._lectures = apres_lecture, 0

    def __iter__(self):
        self._lectures += 1
        derniere = self._lectures == 2
        yield from list.__iter__(self)
        if derniere and self._apres is not None:
            declencher, self._apres = self._apres, None
            declencher()


def _donnees_publiee(pid):
    return {"publication_id": pid, "id_externe": "x", "url": None, "publie_le": HORODATAGE,
            "publie_le_externe": None, "tentative": 1, "retrouvee": False}


def test_une_issue_ecrite_pendant_qu_un_autre_ecrit_est_refusee_par_la_comparaison_echange(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)

    def autre_ecrit():
        service.composer(proxy, publication("facebook"), "cle-autre-publication-01", comptes_actifs, "agent",
                         HORODATAGE)

    proxy = JournalQuiBouge(journal, autre_ecrit)
    assert executeur._consigner_issue(proxy, pid, etats.MAILLON_PUBLIEE, _donnees_publiee(pid), HORODATAGE) is False
    assert not journal_chaine.de_type(proxy, etats.MAILLON_PUBLIEE)
    _registre_sain(proxy)


def test_une_issue_se_consigne_une_seule_fois_et_jamais_hors_sortie(
    journal, comptes_actifs, declarations, politique_sas, proprietaire
):
    pid = _planifiee(journal, comptes_actifs, declarations, politique_sas, proprietaire)
    assert executeur._consigner_issue(journal, pid, etats.MAILLON_PUBLIEE, _donnees_publiee(pid), HORODATAGE) is True
    assert executeur._consigner_issue(journal, pid, etats.MAILLON_PUBLIEE, _donnees_publiee(pid), HORODATAGE) is False
    assert _registre_sain(journal)[pid].etat == etats.PUBLIE
    # Une publication annulée SANS tentative ouverte ne reçoit aucune issue (rien n'est parti).
    autre = service.composer(journal, publication("facebook"), "cle-autre-publication-02", comptes_actifs, "agent",
                             HORODATAGE)["publication_id"]
    assert service.annuler(journal, autre, "agent", "stop", HORODATAGE)["accepte"]
    assert executeur._consigner_issue(journal, autre, etats.MAILLON_PUBLIEE, _donnees_publiee(autre), HORODATAGE) \
        is False
    assert _registre_sain(journal)[autre].etat == etats.ANNULE
