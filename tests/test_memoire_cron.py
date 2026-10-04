"""Déclaration native à partir d'un véritable grant de service SQLite fictif."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from m10_memoire import consolidation_developpement as jobs
from m10_memoire import developpement

from opsys import contexte, identite, openclaw, stockage

ADMIN = contexte.IdentiteAppelante("cron.fictif", "admin", source="console")


@pytest.fixture
def grant_fictif(tmp_path, monkeypatch):
    # Retirer l'autorité humaine, ignorer le grant ou changer le scope du worker doit faire échouer ces tests.
    home = tmp_path / "instance avec espaces ; $(interdit)"
    home.mkdir()
    depot = tmp_path / "depot-fictif"
    depot.mkdir()
    (depot / "README.md").write_text("Dépôt fictif du job M10.\n")
    for arguments in (
        ["init", "-q"], ["add", "."],
        ["-c", "user.name=Fixture fictive", "-c", "user.email=fictif@example.test", "commit", "-qm", "fictif"],
    ):
        subprocess.run(["git", "-C", str(depot), *arguments], check=True)
    monkeypatch.setenv("OPSYS_HOME", str(home))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{home / 'fictif.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN.personne, "Admin fictif", "mot-de-passe-cron-fictif-1234", ["admin"])
    credential = home / "credential.json"
    with contexte.appele_par_appareil(ADMIN):
        jobs.autoriser("audit-fictif", depot, credential, fuseau="America/Toronto", premier_jour="2026-09-29")
    yield home, credential
    stockage.liberer()


def _generer():
    assert hasattr(openclaw, "configuration_cron_memoire_developpement"), "projection cron M10 absente"
    return openclaw.configuration_cron_memoire_developpement("audit-fictif")


def test_declaration_native_sans_modele_secret_ni_expansion_shell(grant_fictif):
    home, credential = grant_fictif
    secret = json.loads(credential.read_text())["capability"]
    avant = list(stockage.maillons("m10-memoire", jobs.REGISTRE))
    with contexte.appele_par_appareil(ADMIN):
        declaration = _generer()
        assert _generer() == declaration
    argv = declaration["argv"]
    assert argv[:3] == ["opsys", "automations", "add"]
    assert argv[argv.index("--cron") + 1] == "0 3 * * *"
    assert argv[argv.index("--tz") + 1] == "America/Toronto"
    assert "--declaration-key" in argv and "--no-deliver" in argv
    assert not {"--agent", "--message", "--model", "--command"}.intersection(argv)
    worker = json.loads(argv[argv.index("--command-argv") + 1])
    assert worker[1:4] == ["-m", "opsys.memoire_consolidation", "executer"]
    assert worker[worker.index("--job-id") + 1] == "audit-fictif"
    assert worker[worker.index("--credential-file") + 1] == str(credential)
    assert not {"--depot", "--role", "--personne"}.intersection(worker)
    env = [argv[i + 1] for i, valeur in enumerate(argv) if valeur == "--command-env"]
    assert f"OPSYS_HOME={home}" in env
    assert f"{stockage.ENV_URL}=sqlite:///{home / 'fictif.db'}" in env
    assert secret not in json.dumps(declaration)
    assert declaration["transport"] == "core-command-same-host"
    assert list(stockage.maillons("m10-memoire", jobs.REGISTRE)) == avant


def test_declaration_refuse_sans_principal_et_role_retire(grant_fictif):
    with pytest.raises(developpement.AccesDeveloppementRefuse):
        _generer()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    with contexte.appele_par_appareil(ADMIN), pytest.raises(developpement.AccesDeveloppementRefuse):
        _generer()


def test_grant_revoque_ne_produit_plus_de_declaration(grant_fictif):
    with contexte.appele_par_appareil(ADMIN):
        jobs.revoquer("audit-fictif")
        with pytest.raises(PermissionError, match="révoqu"):
            _generer()


def test_worker_genere_relit_la_meme_base_avec_chemins_speciaux(grant_fictif):
    _, credential = grant_fictif
    with contexte.appele_par_appareil(ADMIN):
        argv = _generer()["argv"]
    worker = json.loads(argv[argv.index("--command-argv") + 1])
    env = dict(os.environ)
    for indice, argument in enumerate(argv):
        if argument == "--command-env":
            cle, valeur = argv[indice + 1].split("=", 1)
            env[cle] = valeur
    sortie = subprocess.run(
        worker, cwd=argv[argv.index("--command-cwd") + 1], env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert sortie.returncode == 0, sortie.stderr
    resultat = json.loads(sortie.stdout)
    assert resultat["status"] == "available" and resultat["report_id"]
    with contexte.appele_par_appareil(ADMIN):
        rapport = jobs.lire_rapport("audit-fictif")
    assert rapport["report_id"] == resultat["report_id"]
    assert json.loads(credential.read_text())["capability"] not in sortie.stdout + sortie.stderr
