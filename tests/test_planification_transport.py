"""Planification autonome : les tours qui dépendent d'un TRANSPORT (signaux, veille, studio, embeddings, sauvegardes).

Aucun transport réel n'existe pour eux. Sans transport : « en attente de transport », visible, jamais un échec
silencieux
ni un succès simulé, et zéro appel. Avec un double : le tour agit, se rejoue sans doublon, respecte son plafond
d'appels.
Les modèles payants ne sont jamais exécutés. Données fictives."""

from __future__ import annotations

import dataclasses
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import planif_qa as pq
import pytest
from sqlalchemy import func, select

from opsys import stockage
from opsys.connecteurs_planification import etat, hote, journal
from opsys.stockage.schema import PLANIFICATEUR_JOURNAL

RACINE = Path(__file__).resolve().parents[1]
for sous in ("signaux", "studio", "veille"):
    sys.path.insert(0, str(RACINE / "departments" / "m07-marketing" / "tests" / sous))

import fabriques_signaux as fs  # noqa: E402
import fabriques_studio as fst  # noqa: E402
import fabriques_veille as fv  # noqa: E402
from m7_marketing.signaux import comptes, search_console  # noqa: E402
from m7_marketing.signaux import registre as reg_signaux  # noqa: E402
from m7_marketing.signaux.doubles_search_console import DoubleSearchConsole  # noqa: E402
from m7_marketing.studio import brief as b  # noqa: E402
from m7_marketing.studio import executeur as exec_studio  # noqa: E402
from m7_marketing.studio import generation, modeles  # noqa: E402
from m7_marketing.veille import collecte  # noqa: E402
from m7_marketing.veille import registre as reg_veille  # noqa: E402

FICTIF = True
SITE = "https://www.horizon.example/"


@pytest.fixture
def p(tmp_path, monkeypatch):
    mon = pq.monter(tmp_path, monkeypatch, ())
    yield mon
    pq.demonter()


def _jours():
    from datetime import date, timedelta

    sortie, d = {}, date(2026, 9, 25)
    while d <= date(2026, 10, 29):
        sortie[d.isoformat()] = (d.isoformat(), 10, 200, 0.05, 8.5)
        d += timedelta(days=1)
    return sortie


def _declarer_source() -> None:
    journal_comptes = stockage.maillons(*reg_signaux.REGISTRE_COMPTES)
    ack = comptes.enregistrer(journal_comptes, "search_console", "principal", SITE, {"nom": "secret.principal"}, None,
                              None, None, True, "nathan", "2026-10-01T00:00:00Z")
    assert ack["accepte"], ack


def _journal(executeur: str) -> list[dict]:
    with stockage.transaction() as cnx:
        return journal.lire(cnx, executeur)


# -- sans transport : visible, jamais silencieux ni simulé -------------------------------------------------------------
def test_signaux_sans_transport_est_en_attente_de_transport_et_visible(p):
    _declarer_source()
    p.activer("m7.signaux")
    resume = p.tour()["executeurs"]["m7.signaux"]
    assert resume["statut"] == "attente_transport" and resume["code"] == "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE"
    assert p.ligne("m7.signaux")["dernier_statut"] == "attente_transport"
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx, p.horloge(), ports=p.ports)}
    assert vue["m7.signaux"]["en_attente_transport"] is True and vue["m7.signaux"]["transport_branche"] is False
    assert vue["m7.signaux"]["transport_libelle"]
    # le curseur n'a pas bougé : rien n'a été lu
    assert stockage.maillons(*reg_signaux.REGISTRE_CURSEURS).__len__() == 0


def test_la_vue_dit_en_attente_de_transport_meme_pour_un_executeur_inactif(p):
    with stockage.transaction() as cnx:
        vue = {v["executeur"]: v for v in etat.vue(cnx, p.horloge(), ports=p.ports)}
    for nom in ("m7.signaux", "m7.veille", "m7.studio.fonds", "m10.connaissances.reindexation",
                "m7.wordpress.publication", "m7.social.publication", "courriel.synchro"):
        assert vue[nom]["mode"] == "inactif" and vue[nom]["en_attente_transport"] is True, nom
    assert vue["m8.entrepot"]["transport_branche"] is None and vue["m8.entrepot"]["en_attente_transport"] is False


def test_sans_aucune_source_declaree_rien_n_est_en_attente(p):
    p.activer("m7.signaux")
    assert p.tour()["executeurs"]["m7.signaux"]["statut"] == "ok"  # aucun travail : pas d'attente inventée


def test_l_ombre_des_signaux_constate_sans_toucher_au_transport(p):
    _declarer_source()
    appels = []
    p.ports.fabrique_signaux = lambda compte, horloge: appels.append(1)
    p.activer("m7.signaux", "ombre")
    r = p.tour()["executeurs"]["m7.signaux"]
    assert r["statut"] == "ombre" and r["aurait"] == 1 and appels == []


# -- signaux avec un double -----------------------------------------------------------------------------------------
def _brancher_signaux(p):
    serveur = DoubleSearchConsole(propriete=SITE, jeton=fs.JETON, jours=_jours())
    coffre = fs.coffre_pour("search_console")

    def fabrique(compte, horloge):
        return search_console.ConnecteurSearchConsole(serveur, compte, coffre.fournisseurs(), maintenant=horloge,
                                                      masqueur=fs.masqueur())

    p.ports.fabrique_signaux = fabrique
    return serveur


def test_signaux_avec_double_lit_ecrit_et_se_rejoue_sans_doublon(p):
    _declarer_source()
    serveur = _brancher_signaux(p)
    p.activer("m7.signaux")
    r = p.tour()["executeurs"]["m7.signaux"]
    assert r["statut"] == "ok" and r["appels"] >= 1 and r["traites"] > 0
    faits = len(reg_signaux.charger(stockage.maillons(*reg_signaux.REGISTRE)))
    assert faits > 0
    # curseur persisté : un second passage (plus tard) ne duplique rien
    p.tour()
    assert len(reg_signaux.charger(stockage.maillons(*reg_signaux.REGISTRE))) == faits
    texte = repr(_journal("m7.signaux"))
    assert fs.JETON not in texte and "secret.principal" not in texte and serveur is not None


def test_le_plafond_d_appels_arrete_l_executeur_et_le_dit(p, monkeypatch):
    _declarer_source()
    _brancher_signaux(p)
    petit = dataclasses.replace(etat.definition("m7.signaux"), plafond_appels_jour=1)
    monkeypatch.setitem(etat._PAR_NOM, "m7.signaux", petit)
    p.activer("m7.signaux")
    assert p.tour()["executeurs"]["m7.signaux"]["statut"] == "ok"
    r = p.tour()["executeurs"]["m7.signaux"]  # le budget des 24 h est consommé : plus aucun appel
    assert (r["statut"], r["code"]) == ("plafond", "REJ-PLAN-PLAFOND-ATTEINT")
    assert p.ligne("m7.signaux")["dernier_statut"] == "plafond"
    p.tour()  # un épisode = une seule ligne de journal de plafond
    plafonds = [j for j in _journal("m7.signaux") if j["statut"] == "plafond"]
    assert len(plafonds) == 1
    p.horloge.avancer(25 * 3600)  # fenêtre glissante : le budget revient
    assert p.tour(avance=1)["executeurs"]["m7.signaux"]["statut"] == "ok"


# -- veille ---------------------------------------------------------------------------------------------------------
def test_veille_sans_transport_puis_avec_un_double(p):
    journal_conc = stockage.maillons(*reg_veille.REGISTRE)
    fv.declarer_horizon(journal_conc)
    p.activer("m7.veille")
    assert p.tour()["executeurs"]["m7.veille"]["code"] == "REJ-VEILLE-TRANSPORT-NON-BRANCHE"
    assert len(stockage.maillons("m07-marketing", "observations_concurrents")) == 0
    double = fv.site_horizon()

    def fabrique(concurrents, horloge):
        return collecte.Collecteur(double, concurrents=concurrents, maintenant=horloge, masqueur=fv.masqueur(),
                                   delai_min_s=0)

    p.ports.fabrique_veille = fabrique
    r = p.tour()["executeurs"]["m7.veille"]
    assert r["statut"] == "ok" and r["traites"] == 3 and r["appels"] >= 3
    avant = len(stockage.maillons("m07-marketing", "observations_concurrents"))
    p.tour()
    assert len(stockage.maillons("m07-marketing", "observations_concurrents")) == avant  # même jour : pas de doublon


# -- studio ---------------------------------------------------------------------------------------------------------
def _demander_fond():
    donnees = fst.brief("banniere_social", fictif=True, fond=fst.GENERE)
    brief, refus = b.depuis_dict(donnees)
    assert brief is not None, refus
    ack = exec_studio.demander_generation(stockage.maillons("m07-marketing", "jobs_studio"), "brief-1", brief,
                                          fst.selection_double(), par="agent", horodatage=fst.HORODATAGE,
                                          maintenant=fst.MAINTENANT)
    assert ack["accepte"], ack
    return ack["job_id"]


class _Generateur(generation.GenerateurImageDouble):
    def __init__(self):
        super().__init__()
        self.appels = 0

    def generer(self, demande):
        self.appels += 1
        return super().generer(demande)


def test_studio_modele_local_s_execute_et_se_rejoue_sans_second_appel(p, monkeypatch):
    job = _demander_fond()
    gen = _Generateur()
    monkeypatch.setattr(modeles, "selectionner", lambda cnx, genre, departement="m07-marketing": fst.selection_double())
    p.activer("m7.studio.fonds")
    assert p.tour()["executeurs"]["m7.studio.fonds"]["code"] == "REJ-STUDIO-ADAPTATEUR-ABSENT"  # pas d'adaptateur
    assert gen.appels == 0
    p.ports.fabrique_studio = lambda: {fst.selection_double().fournisseur.identifiant: gen}
    assert p.tour()["executeurs"]["m7.studio.fonds"]["statut"] == "ok" and gen.appels == 1
    jobs, _ = exec_studio.charger(stockage.maillons("m07-marketing", "jobs_studio"))
    assert jobs[job].etat == "terminee"
    p.tour()
    assert gen.appels == 1  # terminée : plus rien à faire


def test_studio_un_modele_payant_n_est_jamais_execute(p, monkeypatch):
    _demander_fond()
    gen = _Generateur()
    payant = types.SimpleNamespace(fournisseur=types.SimpleNamespace(mode="api", identifiant="image.recraft-v4.1.api"))
    monkeypatch.setattr(modeles, "selectionner", lambda cnx, genre, departement="m07-marketing": payant)
    p.ports.fabrique_studio = lambda: {"image.recraft-v4.1.api": gen,
    fst.selection_double().fournisseur.identifiant: gen}
    p.activer("m7.studio.fonds")
    r = p.tour()["executeurs"]["m7.studio.fonds"]
    assert r["refuses"] == 1 and r["code"] == "REJ-PLAN-GENERATION-PAYANTE-APPROBATION-REQUISE"
    assert gen.appels == 0  # aucun appel, aucune dépense
    jobs, _ = exec_studio.charger(stockage.maillons("m07-marketing", "jobs_studio"))
    assert {j.etat for j in jobs.values()} == {"en_attente"}


def test_studio_l_ombre_distingue_local_et_payant_sans_rien_executer(p, monkeypatch):
    _demander_fond()
    gen = _Generateur()
    p.ports.fabrique_studio = lambda: {fst.selection_double().fournisseur.identifiant: gen}
    monkeypatch.setattr(modeles, "selectionner", lambda cnx, genre, departement="m07-marketing": fst.selection_double())
    p.activer("m7.studio.fonds", "ombre")
    assert p.tour()["executeurs"]["m7.studio.fonds"]["aurait"] == 1 and gen.appels == 0


# -- embeddings -----------------------------------------------------------------------------------------------------
def _base_a_reindexer(monkeypatch):
    from connaissances_aide import changer_modele, declarer_embeddings, ingerer_et_publier, raccorder_embeddings

    from opsys.connaissances import ports as ports_connaissances

    declarer_embeddings(stockage.transaction)
    raccorder_embeddings(monkeypatch)
    with stockage.transaction() as cnx:
        ingerer_et_publier(cnx, embeddeur=ports_connaissances.resoudre_embeddeur(cnx, "m05-financecore"))
    changer_modele(stockage.transaction, "embeddings.fictif-a", "Modèle fictif B")


def test_reindexation_sans_adaptateur_est_en_attente_de_transport(p, monkeypatch):
    _base_a_reindexer(monkeypatch)
    p.activer("m10.connaissances.reindexation")
    p.ports.embeddings_raccordes = lambda: False
    r = p.tour()["executeurs"]["m10.connaissances.reindexation"]
    assert r["statut"] == "attente_transport" and r["code"] == "REJ-CONN-EMBEDDINGS-NON-RACCORDE"


def test_reindexation_avec_adaptateur_bascule_une_fois(p, monkeypatch):
    _base_a_reindexer(monkeypatch)
    p.ports.embeddings_raccordes = lambda: True
    p.activer("m10.connaissances.reindexation")
    r = p.tour()["executeurs"]["m10.connaissances.reindexation"]
    assert r["statut"] == "ok" and r["appels"] >= 1 and r["traites"] >= 1
    assert p.tour()["executeurs"]["m10.connaissances.reindexation"]["statut"] == "ok"
    with stockage.transaction() as cnx:
        n = cnx.exec_driver_sql("SELECT COUNT(*) FROM connaissances_indexations WHERE genre='bascule'").scalar_one()
    assert n == 1  # la base n'a plus besoin d'être réindexée : pas de seconde bascule


def test_reindexation_n_a_rien_a_faire_sans_changement_de_modele(p, monkeypatch):
    from connaissances_aide import declarer_embeddings, ingerer_et_publier, raccorder_embeddings

    from opsys.connaissances import ports as ports_connaissances

    declarer_embeddings(stockage.transaction)
    raccorder_embeddings(monkeypatch)
    with stockage.transaction() as cnx:
        ingerer_et_publier(cnx, embeddeur=ports_connaissances.resoudre_embeddeur(cnx, "m05-financecore"))
    p.activer("m10.connaissances.reindexation")
    assert p.tour()["executeurs"]["m10.connaissances.reindexation"]["statut"] == "ok"


# -- sauvegardes ----------------------------------------------------------------------------------------------------
def test_verification_des_sauvegardes_non_configuree_est_en_attente(p):
    p.activer("sauvegarde.verification")
    r = p.tour()["executeurs"]["sauvegarde.verification"]
    assert r["statut"] == "attente_transport" and r["code"] == "REJ-PLAN-SAUVEGARDE-NON-CONFIGUREE"


@pytest.mark.parametrize("rapport,code", [
    ({"trouvee": False}, "REJ-PLAN-SAUVEGARDE-ABSENTE"),
    ({"trouvee": True, "authentique": False, "code": "REJ-SAUVEGARDE-ALTEREE", "age_s": 10},
     "REJ-SAUVEGARDE-ALTEREE"),
    ({"trouvee": True, "authentique": True, "age_s": 10 * 86400}, "REJ-PLAN-SAUVEGARDE-TROP-ANCIENNE"),
])
def test_une_sauvegarde_absente_alteree_ou_trop_ancienne_est_une_erreur_visible(p, rapport, code):
    p.ports.verifier_sauvegarde = lambda: rapport
    p.activer("sauvegarde.verification")
    r = p.tour()["executeurs"]["sauvegarde.verification"]
    assert r["statut"] == "erreur" and r["code"] == code


def test_une_sauvegarde_recente_et_authentique_passe(p):
    p.ports.verifier_sauvegarde = lambda: {"trouvee": True, "authentique": True, "age_s": 3600}
    p.activer("sauvegarde.verification")
    assert p.tour()["executeurs"]["sauvegarde.verification"]["statut"] == "ok"


def test_le_verificateur_de_production_exige_dossier_et_cle_et_authentifie_vraiment(tmp_path, monkeypatch):
    assert hote.verifier_sauvegarde_depuis_env({}) is None
    assert hote.verifier_sauvegarde_depuis_env({"OPSYS_PLANIF_SAUVEGARDES_DOSSIER": str(tmp_path)}) is None
    from opsys import sauvegarde_chiffree as sc

    dossier, cle = tmp_path / "sauvegardes", tmp_path / "cles" / "cle"
    dossier.mkdir()
    cle.parent.mkdir(mode=0o700)
    environ = {"OPSYS_PLANIF_SAUVEGARDES_DOSSIER": str(dossier), sc.ENV_CLE_FICHIER: str(cle)}
    verifier = hote.verifier_sauvegarde_depuis_env(environ)
    assert verifier is not None and verifier() == {"trouvee": False}
    sc.generer_cle(cle)
    # une archive au bon nom mais qui n'est PAS une sauvegarde : refusée, jamais « authentique »
    faux = dossier / "opsys-sauvegarde-20261101T020000Z-abcd.tar.gz.enc"
    faux.write_bytes(b"pas une sauvegarde")
    r = verifier(datetime(2026, 11, 1, 3, 0, tzinfo=UTC).timestamp())
    assert r["trouvee"] is True and r["authentique"] is False and r["code"].startswith("REJ-SAUVEGARDE-")
    assert r["age_s"] == 3600


# -- péremptions ----------------------------------------------------------------------------------------------------
def test_le_balayage_constate_les_sources_perimees_et_ne_corrige_rien(p, monkeypatch):
    from connaissances_aide import declarer_embeddings, ingerer_et_publier

    declarer_embeddings(stockage.transaction)
    with stockage.transaction() as cnx:
        ingerer_et_publier(cnx, expire_le="2026-11-02")
    p.activer("peremptions.balayage")
    p.horloge.avancer(3 * 86400)  # la source (valable jusqu'au 2 novembre) est maintenant périmée
    r = p.tour()["executeurs"]["peremptions.balayage"]
    assert r["statut"] == "ok" and r["code"] == "REJ-PLAN-PEREMPTION-DETECTEE"
    constat = [j for j in _journal("peremptions.balayage") if j["evenement"] == "constat"]
    assert len(constat) == 1 and constat[0]["details"]["expires"] == 1
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(PLANIFICATEUR_JOURNAL)).scalar_one() >= 2
