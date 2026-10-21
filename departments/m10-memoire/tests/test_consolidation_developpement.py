"""Jobs développement sur vrai canon SQLite temporaire ; aucun cron ni Gateway simulé comme production."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from m10_memoire import developpement as dev
from sqlalchemy import update

from opsys import contexte, exportation, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

FICTIF = True
NOW = dt.datetime(2026, 9, 30, 15, tzinfo=dt.UTC)
ADMIN = contexte.IdentiteAppelante("admin.dev", "admin")
HORODATAGE = NOW.isoformat()


@pytest.fixture
def base_dev(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-fictif"))
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.dev", "Admin fictif", "mot-de-passe-fictif-job-123", ["admin"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def depot_git(tmp_path):
    depot = tmp_path / "depot-fictif"
    depot.mkdir()
    dossier = depot / "departments/m10-memoire/docs"
    dossier.mkdir(parents=True)
    (dossier / "preuve.md").write_text("Mémoire M10 fictive, preuve sourcée et sans conclusion done.\n")
    for args in [
        ["init", "-q"],
        ["config", "user.email", "fictif@example.test"],
        ["config", "user.name", "Fixture fictive"],
        ["add", "."],
        ["commit", "-qm", "fixture fictive"],
    ]:
        subprocess.run(["git", "-C", str(depot), *args], check=True)
    return depot


def _module():
    nom = "m10_memoire.consolidation_developpement"
    assert importlib.util.find_spec(nom) is not None, "le runner durable de développement est absent"
    return importlib.import_module(nom)


def _autoriser(job, base_dev, depot_git, monkeypatch, **options):
    monkeypatch.setattr(job, "_maintenant", lambda: NOW)
    credential = base_dev / "job-credential.json"
    with contexte.appele_par_appareil(ADMIN):
        grant = job.autoriser("audit-dev", depot_git, credential, **options)
    return credential, grant


def _rapports(job):
    return [m["paquet"] for m in job._journal().lire() if m["paquet"]["kind"] == "report"]


def test_grant_exige_humain_vivant_et_ne_sort_pas_la_capacite(base_dev, depot_git, monkeypatch):
    job = _module()
    with pytest.raises(dev.AccesDeveloppementRefuse):
        job.autoriser("audit-dev", depot_git, base_dev / "refuse.json")
    assert not (base_dev / "refuse.json").exists()
    credential, grant = _autoriser(job, base_dev, depot_git, monkeypatch)
    secret = json.loads(credential.read_text())["capability"]
    assert len(secret) >= 40 and credential.stat().st_mode & 0o777 == 0o600
    assert grant["principal"] == "service:m10-consolidation"
    assert secret not in json.dumps(grant)
    assert secret not in json.dumps(job._journal().lire())
    assert grant["domain"] == "development"


def test_service_produit_rapport_sans_mutation_de_prompts_et_rejoue(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        dev.enregistrer_prompt(
            "p", "token=secret-fictif-123", version=1, module="M7", objectif="SEO", horodatage=HORODATAGE
        )
        dev.scanner_depot(depot_git, horodatage=HORODATAGE)
    avant = list(stockage.maillons("m10-memoire", dev.REGISTRE_DURABLE))
    resultat = job.executer("audit-dev", credential)
    assert resultat["status"] == "available" and resultat["replayed"] is False
    (rapport,) = _rapports(job)
    assert rapport["report"]["audit"]["counts"]["prompts_sans_plan"] == 1
    assert rapport["report"]["input_head"] == avant[-1]["ligne_id"]
    assert rapport["report"]["self_model"]["completion"] == "not_evaluated"
    assert "secret-fictif-123" not in json.dumps(rapport)
    assert list(stockage.maillons("m10-memoire", dev.REGISTRE_DURABLE)) == avant
    assert job._journal().valider_chaine() == (True, "")
    rejoue = job.executer("audit-dev", credential)
    assert rejoue["replayed"] is True and rejoue["report_id"] == resultat["report_id"]
    assert len(_rapports(job)) == 1
    with pytest.raises(dev.AccesDeveloppementRefuse):
        dev.auditer_developpement(repository=depot_git)


@pytest.mark.parametrize("defaut", ["symlink", "parent_symlink", "permissions", "taille", "autre_job"])
def test_credential_irregulier_ou_mauvaise_portee_refuse(base_dev, depot_git, monkeypatch, defaut):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    cible = credential
    ident = "audit-dev"
    if defaut == "symlink":
        cible = base_dev / "lien.json"
        cible.symlink_to(credential)
    elif defaut == "parent_symlink":
        lien = base_dev / "lien-dossier"
        lien.symlink_to(base_dev, target_is_directory=True)
        cible = lien / credential.name
    elif defaut == "permissions":
        credential.chmod(0o644)
    elif defaut == "taille":
        credential.write_text("x" * 4097)
    else:
        ident = "autre-job"
    with pytest.raises(job.AccesConsolidationRefuse):
        job.executer(ident, cible)
    assert _rapports(job) == []


def test_revocation_pendant_analyse_refuse_au_commit(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    produire = job._produire_rapport

    def revoquer_pendant(*args, **kwargs):
        rapport = produire(*args, **kwargs)
        with contexte.appele_par_appareil(ADMIN):
            job.revoquer("audit-dev")
        return rapport

    monkeypatch.setattr(job, "_produire_rapport", revoquer_pendant)
    with pytest.raises(job.AccesConsolidationRefuse):
        job.executer("audit-dev", credential)
    assert _rapports(job) == []


def test_transaction_finale_annule_rapport_si_checkpoint_echoue(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    ajouter = job._ajouter

    def panne_checkpoint(paquet):
        if paquet["kind"] == "checkpoint":
            raise RuntimeError("panne fictive avant commit")
        return ajouter(paquet)

    monkeypatch.setattr(job, "_ajouter", panne_checkpoint)
    with pytest.raises(RuntimeError, match="panne fictive"):
        job.executer("audit-dev", credential)
    assert _rapports(job) == []
    monkeypatch.setattr(job, "_ajouter", ajouter)
    monkeypatch.setattr(job, "_maintenant", lambda: NOW + dt.timedelta(seconds=601))
    assert job.executer("audit-dev", credential)["report_id"]
    assert len(_rapports(job)) == 1


def test_ancien_worker_expire_ne_valide_pas_apres_reprise(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    produire = job._produire_rapport
    reprise = []

    def reprendre_pendant(*args, **kwargs):
        rapport = produire(*args, **kwargs)
        monkeypatch.setattr(job, "_produire_rapport", produire)
        monkeypatch.setattr(job, "_maintenant", lambda: NOW + dt.timedelta(seconds=601))
        reprise.append(job.executer("audit-dev", credential))
        return rapport

    monkeypatch.setattr(job, "_produire_rapport", reprendre_pendant)
    with pytest.raises(job.ConflitJob):
        job.executer("audit-dev", credential)
    assert len(_rapports(job)) == 1 and _rapports(job)[0]["report_id"] == reprise[0]["report_id"]


def test_backlog_nuits_et_arrivee_tardive_ne_doublonnent_pas(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch, premier_jour="2026-09-28")
    premiere = job.executer("audit-dev", credential)
    assert premiere["slot"].startswith("2026-09-28") and premiere["backlog"] == 2
    assert job.executer("audit-dev", credential)["backlog"] == 1
    dernier = job.executer("audit-dev", credential)
    assert dernier["slot"].startswith("2026-09-30") and dernier["backlog"] == 0
    with contexte.appele_par_appareil(ADMIN):
        dev.enregistrer_prompt(
            "tardif",
            "fictif",
            version=1,
            module="M10",
            objectif="arrivée tardive",
            horodatage="2026-09-01T12:00:00+00:00",
        )
    revision = job.executer("audit-dev", credential)
    assert revision["slot"] == dernier["slot"] and revision["report_id"] != dernier["report_id"]
    assert len(_rapports(job)) == 4
    assert job.executer("audit-dev", credential)["replayed"] is True


def test_fuseau_toronto_autour_du_changement_d_heure(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch, premier_jour="2026-11-01")
    monkeypatch.setattr(job, "_maintenant", lambda: dt.datetime(2026, 11, 1, 7, 59, tzinfo=dt.UTC))
    assert job.executer("audit-dev", credential)["status"] == "not_due"
    monkeypatch.setattr(job, "_maintenant", lambda: dt.datetime(2026, 11, 1, 8, tzinfo=dt.UTC))
    resultat = job.executer("audit-dev", credential)
    assert resultat["slot"] == "2026-11-01T03:00:00-05:00"
    assert job.executer("audit-dev", credential)["replayed"] is True


def test_caps_du_grant_donnent_rapport_partiel_et_omissions(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch, limites={"max_events": 1, "max_findings": 1})
    with contexte.appele_par_appareil(ADMIN):
        for i in range(3):
            dev.enregistrer_prompt(
                str(i), "fictif", version=1, module="M10", objectif="preuve cap", horodatage=HORODATAGE
            )
    resultat = job.executer("audit-dev", credential)
    assert resultat["status"] == "partial"
    (rapport,) = _rapports(job)
    assert rapport["report"]["audit"]["event_scan_truncated"] is True
    assert rapport["report"]["limits"]["max_events"] == 1


def test_worker_cli_interdit_identite_et_racine_en_arguments(base_dev, depot_git):
    nom = "opsys.memoire_consolidation"
    assert importlib.util.find_spec(nom) is not None, "l'entrée worker déterministe est absente"
    worker = importlib.import_module(nom)
    for argument in ["--depot", "--role", "--personne", "--acteur"]:
        with pytest.raises(SystemExit) as exc:
            worker.construire_parseur().parse_args(
                ["executer", "--job-id", "audit-dev", "--credential-file", "credential", argument, "fictif"]
            )
        assert exc.value.code == 2


def test_worker_sous_processus_sur_sqlite_et_relecture_sans_secret(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch, premier_jour="2026-09-29")
    secret = json.loads(credential.read_text())["capability"]
    commande = [
        sys.executable,
        "-m",
        "opsys.memoire_consolidation",
        "executer",
        "--job-id",
        "audit-dev",
        "--credential-file",
        str(credential),
    ]
    racine = Path(__file__).resolve().parents[3]
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(
            [
                str(racine / "src"),
                str(racine / "departments/m10-memoire/src"),
            ]
        ),
        PYTHONDONTWRITEBYTECODE="1",
    )
    for _ in range(2):
        sortie = subprocess.run(commande, env=env, capture_output=True, text=True, timeout=20, check=False)
        assert sortie.returncode == 0, sortie.stderr
        assert secret not in sortie.stdout + sortie.stderr
        assert json.loads(sortie.stdout)["report_id"]
    assert len(_rapports(job)) == 2


def test_cli_humain_jobs_garde_authentification_interactive(base_dev, depot_git, monkeypatch, capsys):
    import io

    from opsys.memoire_developpement_cli import main

    monkeypatch.setattr(sys, "stdin", io.StringIO())
    code = main(
        [
            "memoire-developpement",
            "autoriser-job",
            "--job-id",
            "audit-dev",
            "--depot",
            str(depot_git),
            "--credential-file",
            str(base_dev / "creds.json"),
        ]
    )
    assert code == 1
    assert "connexion interactive requise" in capsys.readouterr().err
    assert not (base_dev / "creds.json").exists()


def test_interfaces_humaines_liste_rapport_statut_sans_capacite(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, grant = _autoriser(job, base_dev, depot_git, monkeypatch)
    assert callable(getattr(job, "lister_jobs", None)), "la liste humaine de jobs est absente"
    assert callable(getattr(job, "lire_rapport", None)), "la lecture humaine de rapport est absente"
    with pytest.raises(dev.AccesDeveloppementRefuse):
        job.lister_jobs()
    with pytest.raises(dev.AccesDeveloppementRefuse):
        job.lire_rapport("audit-dev")
    resultat = job.executer("audit-dev", credential)
    with contexte.appele_par_appareil(ADMIN):
        statut = job.lire_statut("audit-dev")
        liste = job.lister_jobs()
        rapport = job.lire_rapport("audit-dev")
        par_ident = job.lire_rapport("audit-dev", resultat["report_id"])
    assert statut["credential_file"] == str(credential)
    assert statut["next_slot"] == "2026-10-01T03:00:00-04:00"
    assert statut["version"] == grant["version"]
    assert liste == [statut] and rapport == par_ident
    assert rapport["report_id"] == resultat["report_id"]
    secret = json.loads(credential.read_text())["capability"]
    assert secret not in json.dumps([statut, liste, rapport])
    assert "capability_hash" not in json.dumps([statut, liste, rapport])


@pytest.mark.parametrize(
    "url_refusee",
    [
        "postgresql+psycopg://fictif.invalid/base_fictive",
        "sqlite://",
        "sqlite:///:memory:",
        "sqlite:///file:fictif?mode=memory&uri=true",
    ],
)
def test_backend_pg_refuse_avant_credential_et_mutation(base_dev, depot_git, monkeypatch, url_refusee):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    avant = job._journal().lire()
    sqlite_url = stockage.url_base()
    monkeypatch.setenv(stockage.ENV_URL, url_refusee)
    refuse = base_dev / "credential-pg-refuse.json"
    for action in [
        lambda: job.autoriser("pg-refuse", depot_git, refuse),
        lambda: job.revoquer("audit-dev"),
        lambda: job.executer("audit-dev", credential),
    ]:
        with pytest.raises(PermissionError, match="backend_non_pris_en_charge"):
            action()
    assert not refuse.exists()
    monkeypatch.setenv(stockage.ENV_URL, sqlite_url)
    assert job._journal().lire() == avant


def test_sources_hors_grant_ne_sont_pas_presentees_absentes(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        dev.scanner_depot(depot_git, horodatage=HORODATAGE)
    autre = base_dev / "autre-depot-fictif"
    autre.mkdir()
    subprocess.run(["git", "-C", str(autre), "init", "-q"], check=True)
    with contexte.appele_par_appareil(ADMIN):
        credential2 = base_dev / "grant-renouvele.json"
        job.autoriser("audit-dev", autre, credential2)
    resultat = job.executer("audit-dev", credential2)
    assert resultat["status"] == "partial"
    rapport = _rapports(job)[0]["report"]
    assert rapport["audit"]["counts"]["sources_perimees"] == 0
    assert rapport["audit"]["freshness"]["sources_out_of_scope"] == 1
    assert rapport["audit"]["freshness"]["sources_unchecked_by_cap"] == 0
    assert rapport["self_model"]["modules"][0]["proofs"][0]["scope"] == "outside_grant"
    assert rapport["self_model"]["modules"][0]["proofs"][0]["observed_sha256"] is None


def test_rapport_conserve_empreinte_observee_distincte_de_la_source_indexee(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        dev.scanner_depot(depot_git, horodatage=HORODATAGE)
    fichier = depot_git / "departments/m10-memoire/docs/preuve.md"
    fichier.write_text("Source fictive modifiée après indexation.\n")
    observe = hashlib.sha256(fichier.read_bytes()).hexdigest()
    job.executer("audit-dev", credential)
    preuve = _rapports(job)[0]["report"]["self_model"]["modules"][0]["proofs"][0]
    assert preuve["freshness"] == "stale" and preuve["scope"] == "inside_grant"
    assert preuve["observed_sha256"] == observe and preuve["indexed_sha256"] != observe


def test_rapport_compte_constats_omis_par_plafond_octets(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch, limites={"max_report_bytes": 4096})
    with contexte.appele_par_appareil(ADMIN):
        for indice in range(30):
            dev.enregistrer_prompt(
                str(indice), "fictif", version=1, module="M10", objectif="cap rapport", horodatage=HORODATAGE
            )
    assert job.executer("audit-dev", credential)["status"] == "partial"
    rapport = _rapports(job)[0]["report"]
    audit = rapport["audit"]
    assert len(dev._json(rapport).encode()) <= 4096 and audit["truncated"] is True
    assert audit["findings_omitted_by_report_cap"] == 30 - len(audit["findings"]) > 0


def test_budget_octets_laisses_non_verifies_est_explicitement_partiel(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch, limites={"max_total_bytes": 1})
    with contexte.appele_par_appareil(ADMIN):
        dev.scanner_depot(depot_git, horodatage=HORODATAGE)
    assert job.executer("audit-dev", credential)["status"] == "partial"
    fraicheur = _rapports(job)[0]["report"]["audit"]["freshness"]
    assert fraicheur["sources_checked"] == 0 and fraicheur["sources_unknown"] == 1
    assert fraicheur["sources_unchecked_by_cap"] == 1


def test_chaine_dev_alteree_refuse_meme_un_rejeu(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        dev.enregistrer_prompt("p", "source fictive", version=1, module="M10", objectif="chaîne", horodatage=HORODATAGE)
    job.executer("audit-dev", credential)
    maillon = list(stockage.maillons("m10-memoire", dev.REGISTRE_DURABLE))[0]
    maillon["paquet"]["events"][0]["payload_json"] = '{"fictif":true,"altération":true}'
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m10-memoire", REGISTRES.c.registre == dev.REGISTRE_DURABLE)
            .values(maillon=codec.encoder(maillon))
        )
    with pytest.raises(job.ConflitJob, match="chaîne"):
        job.executer("audit-dev", credential)
    assert len(_rapports(job)) == 1


def test_cli_humain_configurer_cron_est_une_action_authentifiee():
    from opsys.memoire_developpement_cli import construire_parseur

    args = construire_parseur().parse_args(["memoire-developpement", "configurer-cron", "--job-id", "audit-dev"])
    assert args.action == "configurer-cron" and args.job_id == "audit-dev" and callable(args.fn)


def test_credential_a_liens_multiples_refuse(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    os.link(credential, base_dev / "copie-liee.json")
    with pytest.raises(job.AccesConsolidationRefuse):
        job.executer("audit-dev", credential)
    assert _rapports(job) == []


@pytest.mark.parametrize(
    "limites", [[], {"max_events": True}, {"max_events": "1"}, {"max_sources": 501}, {"inconnu": 1}]
)
def test_caps_invalides_refusent_le_grant_avant_fichier(base_dev, depot_git, limites):
    job = _module()
    credential = base_dev / "caps-invalides.json"
    with contexte.appele_par_appareil(ADMIN), pytest.raises(ValueError):
        job.autoriser("audit-dev", depot_git, credential, limites=limites)
    assert not credential.exists() and job._journal().lire() == []


def test_humain_cli_authentifie_revoque_et_ne_divulgue_pas_credential(base_dev, depot_git, monkeypatch, capsys):
    import getpass

    from opsys.memoire_developpement_cli import main

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _invite: "admin.dev")
    monkeypatch.setattr(getpass, "getpass", lambda _invite: "mot-de-passe-fictif-job-123")
    credential = base_dev / "cli-credential.json"
    prefixe = ["memoire-developpement"]
    assert (
        main(
            prefixe
            + [
                "autoriser-job",
                "--job-id",
                "audit-dev",
                "--depot",
                str(depot_git),
                "--credential-file",
                str(credential),
            ]
        )
        == 0
    )
    assert main(prefixe + ["statut-job", "--job-id", "audit-dev"]) == 0
    assert main(prefixe + ["revoquer-job", "--job-id", "audit-dev"]) == 0
    sortie = capsys.readouterr()
    assert json.loads(credential.read_text())["capability"] not in sortie.out + sortie.err
    assert "mot-de-passe-fictif-job-123" not in sortie.out + sortie.err
    job = _module()
    with pytest.raises(job.AccesConsolidationRefuse):
        job.executer("audit-dev", credential)


def test_export_restauration_canonique_retrouve_grant_rapport_et_rejeu(base_dev, depot_git, monkeypatch):
    job = _module()
    credential, _ = _autoriser(job, base_dev, depot_git, monkeypatch)
    resultat = job.executer("audit-dev", credential)
    home = base_dev / "opsys-fictif"
    home.mkdir(exist_ok=True)
    archive = exportation.exporter(home, base_dev / "fictif-export.tar.gz", par="admin.dev")
    with tarfile.open(archive.archive, "r:gz") as tar:
        assert not any("credential" in member.name for member in tar.getmembers())
    stockage.liberer()
    nouveau = base_dev / "instance-restauree-fictive"
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{nouveau / 'opsys.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(nouveau))
    exportation.restaurer(archive.archive, nouveau, par="admin.dev")
    with contexte.appele_par_appareil(ADMIN):
        relu = job.lire_rapport("audit-dev")
    assert relu["report_id"] == resultat["report_id"]
    assert job._journal().valider_chaine() == (True, "")
    assert job.executer("audit-dev", credential)["replayed"] is True
    assert len(_rapports(job)) == 1
