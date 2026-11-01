"""Concurrence MULTI-PROCESSUS réelle, sur SQLite et sur PostgreSQL (READ COMMITTED) : approbation, bail, créneau du
planificateur, réservation d'envoi.

Chaque test lance de vrais processus (`spawn`) qui se disputent la MÊME ressource au même instant (`pg_concurrence`) et
vérifie qu'un seul gagne, que les autres reçoivent un refus typé, et que l'effet (fichier-marqueur, ligne, journal) n'a
lieu qu'une fois. Données fictives, aucun réseau.

Différence d'isolation à connaître (docs/qualification/QUALIFICATION-POSTGRESQL.md) : SQLite sérialise tous les
écrivains (`BEGIN IMMEDIATE`) ; PostgreSQL en READ COMMITTED ne le fait PAS. Les comparaisons-échanges par `UPDATE …
WHERE état = ?` restent atomiques (le second `UPDATE` attend le verrou de ligne, puis réévalue sa condition) ; un
`SELECT` suivi d'un `INSERT` ne l'est pas sans verrou de ligne (voir `test_postgresql_parite_cas.py`).
"""

from __future__ import annotations

import time
from collections import Counter

import pytest
from cablage_qa import session_admin
from pg_concurrence import (
    ENV_MARQUEUR,
    acquerir_bail,
    decider,
    lancer,
    reclamer_cle,
    reserver_creneau,
    reserver_envoi,
)
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import func, select

from opsys import approbations, identite, stockage
from opsys.connecteurs_planification import bail, etat
from opsys.outils import Niveau
from opsys.stockage.schema import JOURNAL

FICTIF = True
N = 4


@pytest.fixture
def instance(url_base, monkeypatch):  # noqa: F811
    """La base du test (SQLite ou PostgreSQL) devient celle de l'instance, pour ce processus et ses fils."""
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    yield url_base
    stockage.liberer()


def test_n_processus_decident_la_meme_approbation_l_outil_ne_s_execute_qu_une_fois(instance, tmp_path, monkeypatch):
    marqueur = tmp_path / "executions.txt"
    monkeypatch.setenv(ENV_MARQUEUR, str(marqueur))
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-fictif-1234", ["nathan_owner"])
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_compte", {"x": 7}, niveau=Niveau.N4)
    issues = lancer(decider, [(ident,)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"ok": 1, "refus": N - 1}, issues
    assert [i for i in issues if i[0] == "ok"] == [("ok", "executee")]
    # « déjà traitée » (SQLite : l'écrivain attend) ou « déjà prise en charge » (PostgreSQL : verrou de ligne)
    assert all("déjà" in i[1] for i in issues if i[0] == "refus")
    assert len(marqueur.read_text(encoding="utf-8").splitlines()) == 1  # l'effet n'a eu lieu qu'une fois
    with stockage.transaction() as cnx:
        assert approbations.lire(cnx, ident)["statut"] == "executee"
        decisions = cnx.execute(select(func.count()).select_from(JOURNAL).where(
            JOURNAL.c.action == "approbation.approuver", JOURNAL.c.cible == ident)).scalar_one()
        assert decisions == 1  # une seule décision journalisée


def test_n_processus_rejouent_la_meme_cle_d_idempotence_une_seule_execution_fraiche(instance, tmp_path, monkeypatch):
    marqueur = tmp_path / "executions.txt"
    monkeypatch.setenv(ENV_MARQUEUR, str(marqueur))
    issues = lancer(reclamer_cle, [("cle-concurrente-fictive",)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"frais": 1, "rejoue": N - 1}, issues
    assert all(i[1] == {"ok": True, "resultat": {"x": 1}} for i in issues if i[0] == "rejoue")  # la réponse du gagnant
    assert len(marqueur.read_text(encoding="utf-8").splitlines()) == 1  # jamais deux exécutions


def test_n_executeurs_se_disputent_une_ressource_un_seul_obtient_le_bail_puis_la_reprise_est_unique(instance):
    ressource = "courriel:compte-fictif"
    premiere = lancer(acquerir_bail, [(ressource, f"porteur-{i}", 0) for i in range(N)])
    assert [p for p in premiere if p[0] == "PANNE"] == [], premiere
    gagnants = [p for p in premiere if p[0] == "bail"]
    assert len(gagnants) == 1 and gagnants[0][1] == 1 and sum(p == ("occupe",) for p in premiere) == N - 1
    porteur_initial = gagnants[0][2]
    # Le processus du détenteur est « mort » : 1000 s plus tard, le bail est expiré ; UN SEUL repreneur, jeton plus
    # grand.
    reprise = lancer(acquerir_bail, [(ressource, f"repreneur-{i}", 1000) for i in range(N)])
    repreneurs = [p for p in reprise if p[0] == "bail"]
    assert [p for p in reprise if p[0] == "PANNE"] == [] and len(repreneurs) == 1, reprise
    assert repreneurs[0][1] == 2 and repreneurs[0][2] != porteur_initial  # jeton de fencing croissant
    # L'ancien détenteur le voit au renouvellement suivant et s'arrête.
    ancien = bail.Bail(ressource, porteur_initial, 1, int(time.time()) + 30)
    assert bail.renouveler(ancien) is None


def test_n_processus_reservent_le_meme_creneau_de_planificateur_un_seul_passe(instance):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-fictif-1234", ["admin", "nathan_owner"])
        etat.appliquer(cnx, session_admin(), "courriel.synchro", "actif", motif="essai fictif", intervalle_s=30,
                       maintenant=time.time())
    maintenant = time.time() + 5  # le créneau est échu pour tous
    issues = lancer(reserver_creneau, [("courriel.synchro", maintenant)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    modes = Counter(i[0] for i in issues)
    assert modes["actif"] == 1 and modes["actif"] + modes["deja_pris"] + modes["pas_echu"] == N, issues
    with stockage.transaction() as cnx:
        assert etat.ligne(cnx, "courriel.synchro")["prochain_passage"] == int(maintenant) + 30


def test_n_processus_reservent_l_envoi_du_meme_brouillon_approuve_un_seul_part(url_base, tmp_path, monkeypatch):  # noqa: F811
    import base64
    import os

    import courriel_doubles as dbl  # noqa: F401  (le monde de QA le charge)
    import courriel_qa as qa

    from opsys.courriel_connecteurs import envoi
    from opsys.courriel_connecteurs.envoi import NOM_OUTIL, OUTIL_APPROBATION

    monde = qa.preparer(tmp_path, monkeypatch, scope_google=f"{qa.SCOPE_GMAIL_LECTURE} {qa.SCOPE_GMAIL_ENVOI}")
    stockage.liberer()
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(os.urandom(32)).decode("ascii"))
    try:
        stockage.migrer(url_base)
        with stockage.transaction() as cnx:
            identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-nathan-1234",
                                    ["nathan_owner", "admin"])
        qa.creer_compte(monde, usage="lecture_envoi")
        qa.connecter_oauth(monde)
        with stockage.transaction() as cnx:
            brouillon = envoi.creer_brouillon(cnx, "agent-m1", "gmail-paul", a=["cliente.fictive@example.test"],
                                              objet="Suite", corps="Bonjour, merci pour votre message.")
            demande = envoi.demander_approbation(cnx, "agent-m1", brouillon.brouillon_id, contexte="Réponse.",
                                                 sources=["gmail:conc1"])
        with stockage.transaction() as cnx:
            assert approbations.decider(cnx, demande, True, "nathan", {NOM_OUTIL: OUTIL_APPROBATION},
                                        {})["statut"] == "executee"
        issues = lancer(reserver_envoi, [(brouillon.brouillon_id, "gmail")] * N)
        assert [i for i in issues if i[0] == "PANNE"] == [], issues
        assert Counter(i[0] for i in issues) == {"reserve": 1, "refus": N - 1}, issues
        assert {i[1] for i in issues if i[0] == "refus"} <= {"REJ-COURRIEL-BROUILLON-ETAT",
                                                              "REJ-COURRIEL-APPROBATION-REJOUEE"}
        with stockage.transaction() as cnx:
            assert envoi.statut_brouillon(cnx, brouillon.brouillon_id)["statut"] == "ENVOI_RESERVE"
    finally:
        stockage.liberer()
