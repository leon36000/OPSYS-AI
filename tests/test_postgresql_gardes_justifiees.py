"""Les trois gardes « SQLite seulement » qui RESTENT, sur un VRAI PostgreSQL 17 : chacune est correcte par construction.

Une garde n'est pas toujours un défaut de portage : elle est juste quand le code qu'elle protège agit sur un FICHIER
SQLite, ou quand le lever exposerait un secret. Pour chacune : (1) ce que PostgreSQL reçoit à la place, dit et typé ;
(2) la preuve, sur le vrai serveur, que rien n'est écrit à moitié et qu'aucun identifiant de connexion ne fuit.

- `cles_chiffrement._nettoyer_fichiers_courants` : réécrit les pages d'un fichier SQLite (VACUUM, WAL). Sur PostgreSQL,
  la clé est détruite LOGIQUEMENT (DELETE) et l'effacement est inscrit `non_qualifie` / `backend_non_qualifie` dès
  la demande :
  jamais « terminé », jamais « en attente » à perpétuité ; le nettoyage physique d'un serveur (WAL archivé, répliques,
  sauvegardes) n'est pas une opération de l'application.
- `exportation._base_sqlite` : l'export est un instantané du FICHIER SQLite de l'instance ; PostgreSQL se sauvegarde par
  `deploy/backup.sh` (pg_dump), qui est éprouvé sur PostgreSQL réel (`test_postgresql_sauvegarde_restauration`).
- `openclaw.configuration_cron_memoire_developpement` : la déclaration du cron place l'URL de la base dans
l'environnement
  d'une commande de la Gateway ; pour PostgreSQL, ce serait un mot de passe en clair dans la configuration d'un autre
  produit. Refus tant qu'il n'existe pas de coffre pour cette frontière.
Données fictives.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pg_parite import base_pg, serveur_pg  # noqa: F401  (fixtures pytest)
from sqlalchemy.engine import make_url

from opsys import cles_chiffrement, contexte, exportation, identite, openclaw, stockage

FICTIF = True
ADMIN = contexte.IdentiteAppelante("admin.dev", "admin")


@pytest.fixture
def instance_pg(base_pg, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-fictif"))
    yield base_pg
    stockage.liberer()


def _mot_de_passe(url: str) -> str:
    mdp = make_url(url).password
    assert mdp and len(mdp) >= 12
    return mdp


# -- cles_chiffrement ------------------------------------------------------------------------------------------------
def test_effacement_de_cle_sur_postgresql_detruit_logiquement_et_dit_non_qualifie(instance_pg):
    with stockage.transaction() as cnx:
        cles_chiffrement.obtenir_ou_creer(cnx, "m4.geoloc", "tech-1", "2026-11-02T10:00:00+00:00")
        etat = cles_chiffrement.demander_effacement(cnx, "m4.geoloc", "tech-1", "2026-11-02T10:05:00+00:00")
    assert (etat["cle_detruite"], etat["etat_fichiers"], etat["motif"]) == (
        True, "non_qualifie", "backend_non_qualifie")
    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, "m4.geoloc", "tech-1") is None  # la clé n'existe plus
        courant = cles_chiffrement.lire_effacement(cnx, etat["purge_id"])
    assert courant["etat_fichiers"] == "non_qualifie"  # jamais « terminé » : rien de physique n'est affirmé


def test_le_nettoyage_de_fichiers_refuse_un_moteur_postgresql_sans_rien_toucher(instance_pg):
    moteur = stockage.moteur(instance_pg)
    assert cles_chiffrement._nettoyer_fichiers_courants(moteur) == (False, "backend_non_qualifie")


def test_la_reprise_ne_boucle_pas_sur_postgresql_aucun_effacement_n_attend(instance_pg):
    with stockage.transaction() as cnx:
        cles_chiffrement.obtenir_ou_creer(cnx, "m4.geoloc", "tech-2", "2026-11-02T10:00:00+00:00")
        cles_chiffrement.demander_effacement(cnx, "m4.geoloc", "tech-2", "2026-11-02T10:05:00+00:00")
    assert cles_chiffrement.reprendre_effacements() == []  # aucun « en_attente » à reprendre
    from opsys.connecteurs_planification.exec_retention import EffacementsReprise

    assert EffacementsReprise().ressources(None) == []  # l'exécuteur de reprise n'a rien à faire


# -- exportation -----------------------------------------------------------------------------------------------------
def test_l_export_du_fichier_sqlite_est_refuse_sur_postgresql_avec_la_voie_pg_dump(instance_pg, tmp_path):
    home = tmp_path / "opsys-fictif"
    home.mkdir()
    sortie = tmp_path / "sortie" / "export.tar.gz"
    with pytest.raises(exportation.ErreurExportation) as refus:
        exportation.exporter(home, sortie, par="test")
    message = str(refus.value)
    assert "deploy/backup.sh" in message and _mot_de_passe(instance_pg) not in message
    assert not sortie.exists() and not sortie.parent.exists()  # rien n'est créé, pas même le dossier
    with pytest.raises(exportation.ErreurExportation, match="deploy/backup.sh"):
        exportation.restaurer(tmp_path / "inexistante.tar.gz", home, par="test")


def test_la_voie_proposee_existe_et_est_un_vrai_pg_dump():
    script = Path(exportation.__file__).resolve().parents[2] / "deploy" / "backup.sh"
    texte = script.read_text(encoding="utf-8")
    assert "pg_dump" in texte and subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0


# -- openclaw : la déclaration du cron M10
# ---------------------------------------------------------------------------------
def test_la_declaration_du_cron_m10_refuse_postgresql_sans_divulguer_l_url_ni_le_mot_de_passe(instance_pg, tmp_path):
    from m10_memoire import consolidation_developpement as job

    depot = tmp_path / "depot-fictif"
    depot.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "fictif@example.test"], ["config", "user.name", "Fictif"]):
        subprocess.run(["git", "-C", str(depot), *args], check=True)
    (depot / "a.md").write_text("fictif\n")
    for args in (["add", "."], ["commit", "-qm", "fictif"]):
        subprocess.run(["git", "-C", str(depot), *args], check=True)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.dev", "Admin fictif", "mot-de-passe-fictif-job-123", ["admin"])
    with contexte.appele_par_appareil(ADMIN):
        job.autoriser("audit-dev", depot, tmp_path / "cred.json")  # le job existe bien SUR PostgreSQL (garde levée)
    with contexte.appele_par_appareil(ADMIN), pytest.raises(
            ValueError, match="SQLite fichier sans identifiants") as refus:
        openclaw.configuration_cron_memoire_developpement("audit-dev")
    assert _mot_de_passe(instance_pg) not in str(refus.value) and instance_pg not in str(refus.value)
