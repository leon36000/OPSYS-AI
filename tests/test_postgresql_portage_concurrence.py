"""Écritures concurrentes de console et verrous consultatifs, en VRAIS processus, sur SQLite et sur PostgreSQL.

Défaut latent L1 du rapport de qualification PostgreSQL (écrivains concurrents de console : la collision de rang d'un
registre remontait en `EcritureConcurrente` au lieu du verdict typé) et L10 (audit dupliqué sous publication
simultanée). Sous SQLite, `BEGIN IMMEDIATE` sérialise les écrivains ; sous PostgreSQL (READ COMMITTED), c'est
`stockage.concurrence` : verrou d'écriture de console, relecture après conflit, verrou consultatif nommé.

Chaque test lance N processus `spawn` qui se disputent la même ressource au même instant (`pg_concurrence`). Données
fictives, aucun réseau.
"""

from __future__ import annotations

from collections import Counter

import pytest
from pg_concurrence import (
    ajouter_si_vide,
    auditer_une_fois,
    corriger_fournisseur_console,
    ecrire_materiau_console,
    lancer,
)
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import func, select

from opsys import identite, stockage
from opsys.stockage.schema import JOURNAL

FICTIF = True
N = 4


@pytest.fixture
def instance(url_base, monkeypatch):  # noqa: F811
    """La base du test (SQLite ou PostgreSQL) devient celle de l'instance, pour ce processus et ses fils."""
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    yield url_base
    stockage.liberer()


def _admin():
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin FICTIF", "mot-de-passe-fictif-1234", ["admin"])


def test_n_ecrivains_de_console_de_la_meme_revision_un_seul_est_accepte_les_autres_ont_le_verdict_de_sqlite(instance):
    _admin()
    premiere = lancer(ecrire_materiau_console, [("creation-fictive", 0, "Gouttière FICTIVE")])
    assert premiere == [("accepte",)], premiere
    issues = lancer(ecrire_materiau_console, [(f"concurrent-{i}", 1, f"Nom FICTIF {i}") for i in range(N)])
    assert [i for i in issues if i[0] == "PANNE"] == [], issues  # jamais une exception brute (EcritureConcurrente)
    assert Counter(i[0] for i in issues) == {"accepte": 1, "refus": N - 1}, issues
    assert {i[1] for i in issues if i[0] == "refus"} == {"REVISION-PERIMEE"}  # le verdict que rend SQLite
    from m6_material_control import catalogue_materiaux as domaine

    with stockage.transaction():
        journal = stockage.maillons("m06-material-control", domaine.REGISTRE)
        assert len(journal) == 2  # création + UNE correction : aucune mise à jour perdue
        assert domaine.lire(journal, "mat-fictif")["revision"] == 2


def test_n_corrections_de_console_d_un_fournisseur_depuis_la_meme_source_une_seule_est_acceptee(instance):
    """Mise à jour perdue sans le verrou d'écriture de console : la fiche fournisseur n'a pas de clé unique qui protège
    sa relecture, deux corrections lues sur la même source s'ajouteraient toutes deux."""
    _admin()
    creation = lancer(corriger_fournisseur_console, [("creation-fournisseur", "", "Fournisseur FICTIF")])
    assert creation[0][0] == "accepte", creation
    source = creation[0][1]
    issues = lancer(corriger_fournisseur_console, [(f"correction-{i}", source, f"Nom FICTIF {i}") for i in range(N)])
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"accepte": 1, "refus": N - 1}, issues
    with stockage.transaction():
        assert len(stockage.maillons("m06-material-control", "fournisseurs")) == 2  # création + UNE correction


def test_la_meme_saisie_rejouee_par_n_processus_n_ecrit_qu_une_fois(instance):
    """Même clé de mutation, même contenu : un seul accepté fraîchement, les autres reçoivent le rejeu identique."""
    _admin()
    issues = lancer(ecrire_materiau_console, [("meme-saisie-fictive", 0, "Gouttière FICTIVE")] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert issues == [("accepte",)] * N, issues  # rejeu = même réponse « acceptée »
    from m6_material_control import catalogue_materiaux as domaine

    with stockage.transaction():
        assert len(stockage.maillons("m06-material-control", domaine.REGISTRE)) == 1


def test_relire_si_conflit_rejoue_la_perdante_qui_relit_l_etat_du_gagnant(instance):
    issues = lancer(ajouter_si_vide, [("registre-essai", i) for i in range(N)])
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"ecrit": 1, "relu": N - 1}, issues
    with stockage.transaction():
        assert len(stockage.maillons("m09-demo", "registre-essai")) == 1


def test_le_verrou_consultatif_nomme_fait_auditer_une_seule_fois(instance):
    issues = lancer(auditer_une_fois, [("publication-fictive",)] * N)
    assert [i for i in issues if i[0] == "PANNE"] == [], issues
    assert Counter(i[0] for i in issues) == {"ecrit": 1, "relu": N - 1}, issues
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(JOURNAL).where(
            JOURNAL.c.action == "essai.verrou")).scalar_one() == 1
