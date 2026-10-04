"""Parcours locaux de mémoire de développement : autorité, sources, liens et restauration d'instance."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from m10_memoire import developpement as memoire_dev

from opsys import contexte, identite, stockage
from opsys.console.memoire_ui import audit_contenu
from opsys.memoire_developpement_cli import construire_parseur
from opsys.memoire_developpement_cli import main as cli_main

ADMIN = contexte.IdentiteAppelante("admin.dev", "admin")
PROPRIETAIRE = contexte.IdentiteAppelante("proprietaire.dev", "nathan_owner")
M1 = contexte.IdentiteAppelante("vendeur.dev", "m01-front-office")
M3 = contexte.IdentiteAppelante("estimation.dev", "employee")
HORODATAGE = "2026-09-30T15:00:00+00:00"


@pytest.fixture
def base_dev(tmp_path, monkeypatch):
    opsys_home = tmp_path / "opsys-home"
    opsys_home.mkdir()
    db_opsys = tmp_path / "opsys.db"
    url = f"sqlite:///{db_opsys}"
    monkeypatch.setenv("OPSYS_HOME", str(opsys_home))
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.dev", "Admin développement", "mot-de-passe-admin-dev-123", ["admin"])
        identite.creer_personne(
            cnx, "proprietaire.dev", "Propriétaire développement", "mot-de-passe-owner-dev-123", ["nathan_owner"]
        )
        identite.creer_personne(cnx, "vendeur.dev", "Vendeur fictif", "mot-de-passe-vendeur-1234", ["seller"])
        identite.creer_personne(
            cnx, "estimation.dev", "Estimation fictive", "mot-de-passe-estimation-123", ["employee"]
        )
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def depot_git(tmp_path):
    depot = tmp_path / "repo"
    depot.mkdir()
    (depot / "departments/m07-marketing/docs").mkdir(parents=True)
    (depot / "core/src").mkdir(parents=True)
    (depot / "backups").mkdir()
    (depot / "data").mkdir()
    (depot / "departments/m07-marketing/docs/seo.md").write_text(
        "M7 SEO local : garder les sources et les tests de rendu des pages de service.\n", encoding="utf-8"
    )
    (depot / "core/src/config.ts").write_text("export const retries = 3;\n", encoding="utf-8")
    (depot / "core/.env.example").write_text("OPSYS_TOKEN=example-secret-value\n", encoding="utf-8")
    (depot / "backups/old.md").write_text("must not be scanned\n", encoding="utf-8")
    (depot / "data/client_leads.csv").write_text("email,phone\nclient@example.test,418-555-0137\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(depot)], check=True)
    subprocess.run(["git", "-C", str(depot), "config", "user.email", "dev@example.test"], check=True)
    subprocess.run(["git", "-C", str(depot), "config", "user.name", "Dev Fixture"], check=True)
    subprocess.run(["git", "-C", str(depot), "add", "."], check=True)
    subprocess.run(["git", "-C", str(depot), "commit", "-qm", "fixtures développement fictives"], check=True)
    return depot


def test_lecture_et_ecriture_exigent_le_principal_authentifie_admin_ou_owner(base_dev):
    with pytest.raises(memoire_dev.AccesDeveloppementRefuse):
        memoire_dev.preflight("M7", "SEO", files=[])

    for principal in (M1, M3):
        with contexte.appele_par_appareil(principal):
            with pytest.raises(memoire_dev.AccesDeveloppementRefuse):
                memoire_dev.enregistrer_prompt(
                    "p", "prompt exact", version=1, module="M7", objectif="SEO", horodatage=HORODATAGE
                )
            with pytest.raises(memoire_dev.AccesDeveloppementRefuse):
                memoire_dev.preflight("M7", "SEO", files=[])

    with contexte.appele_par_appareil(ADMIN):
        resultat = memoire_dev.enregistrer_prompt(
            "p", "prompt exact", version=1, module="M7", objectif="SEO", horodatage=HORODATAGE
        )
    assert resultat["status"] == "active"


def test_scan_repo_git_est_borne_read_only_et_exclut_secrets_backups_et_donnees(base_dev, depot_git):
    statut_avant = subprocess.check_output(["git", "-C", str(depot_git), "status", "--porcelain"], text=True)

    with contexte.appele_par_appareil(ADMIN):
        resultat = memoire_dev.scanner_depot(
            depot_git,
            max_files=20,
            max_bytes=100_000,
            max_total_bytes=200_000,
            horodatage=HORODATAGE,
        )
        paquet = memoire_dev.preflight("M7", "SEO pages locales", files=[], repository=depot_git)

    chemins = {source["path"] for source in resultat["sources"]}
    assert "departments/m07-marketing/docs/seo.md" in chemins
    assert "core/src/config.ts" in chemins
    assert not any(".env" in chemin or "backup" in chemin or "client_leads" in chemin for chemin in chemins)
    assert "client@example.test" not in json.dumps(paquet)
    assert "418-555-0137" not in json.dumps(paquet)
    assert subprocess.check_output(["git", "-C", str(depot_git), "status", "--porcelain"], text=True) == statut_avant


def test_scan_sous_repertoire_conserve_chemin_git_complet_module_et_fraicheur(base_dev, depot_git):
    sous_arbre = depot_git / "departments/m10-memoire/src/m10_memoire"
    sous_arbre.mkdir(parents=True)
    source_relative = "departments/m10-memoire/src/m10_memoire/sous-arbre.md"
    (sous_arbre / "sous-arbre.md").write_text("M10 bounded source truth for persistent recall.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(depot_git), "add", source_relative], check=True)
    subprocess.run(["git", "-C", str(depot_git), "commit", "-qm", "source M10 fictive"], check=True)

    with contexte.appele_par_appareil(ADMIN):
        scan = memoire_dev.scanner_depot(sous_arbre, horodatage=HORODATAGE)
        paquet = memoire_dev.preflight(
            "M10", "bounded source truth persistent recall", files=[], repository=depot_git
        )

    assert any(source["path"] == source_relative and source["module"] == "M10" for source in scan["sources"])
    assert any(
        preuve["path"] == source_relative and preuve["freshness"] == "current" for preuve in paquet["evidence"]
    )


def test_scanner_normalise_m01_et_conserve_m10():
    assert memoire_dev._module_de("departments/m01-front-office/src/outils.py") == "M1"
    assert memoire_dev._module_de("departments/m10-memoire/src/outils.py") == "M10"


def test_scanner_borne_un_fichier_qui_grossit_apres_indexation(base_dev, depot_git, monkeypatch):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        fichier = depot_git / "departments/m07-marketing/docs/seo.md"
        with fichier.open("wb") as stream:
            stream.truncate(memoire_dev.MAX_FILE_BYTES + 100)
        inode = fichier.stat().st_ino
        original_fstat = os.fstat
        original_read = os.read
        lectures = []

        def taille_avant_croissance(fd):
            resultat = original_fstat(fd)
            if resultat.st_ino == inode:
                champs = list(resultat)
                champs[6] = 1  # Simule la croissance après le stat utilisé par le lecteur.
                return os.stat_result(champs)
            return resultat

        def lecture_quota(fd, limite):
            if original_fstat(fd).st_ino == inode:
                lectures.append(limite)
                assert limite <= memoire_dev.MAX_FILE_BYTES + 1
            return original_read(fd, limite)

        class LectureSansBorne(BaseException):
            pass

        monkeypatch.setattr(os, "fstat", taille_avant_croissance)
        monkeypatch.setattr(os, "read", lecture_quota)
        monkeypatch.setattr(Path, "read_bytes", lambda _path: (_ for _ in ()).throw(LectureSansBorne()))
        resultat = memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)

    assert sum(lectures) <= memoire_dev.MAX_FILE_BYTES + 1
    assert any(
        item["path"].endswith("seo.md") and "taille" in item["reason"] for item in resultat["skipped"]
    )
    assert not any(item["path"].endswith("seo.md") for item in resultat["sources"])


def test_scanner_refuse_symlink_leaf_vers_fichier_exclu(base_dev, depot_git):
    alias = depot_git / "core/src/alias.txt"
    alias.symlink_to("../.env.example")
    subprocess.run(["git", "-C", str(depot_git), "add", "core/src/alias.txt"], check=True)
    statut_avant = subprocess.check_output(["git", "-C", str(depot_git), "status", "--porcelain"], text=True)

    with contexte.appele_par_appareil(ADMIN):
        resultat = memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)

    assert "core/src/alias.txt" not in {item["path"] for item in resultat["sources"]}
    assert any(item["path"] == "core/src/alias.txt" for item in resultat["skipped"])
    journal = json.dumps(list(stockage.maillons("m10-memoire", "developpement")))
    assert "example-secret-value" not in journal
    assert subprocess.check_output(["git", "-C", str(depot_git), "status", "--porcelain"], text=True) == statut_avant


def test_scanner_refuse_composant_symlink_vers_repertoire_prive(base_dev, depot_git):
    source_dir = depot_git / "core/src"
    cible = depot_git / "private"
    cible.mkdir()
    (cible / "config.ts").write_text("PRIVATE_SENTINEL_NOT_FOR_INDEX", encoding="utf-8")
    shutil.rmtree(source_dir)
    source_dir.symlink_to(cible)
    statut_avant = subprocess.check_output(["git", "-C", str(depot_git), "status", "--porcelain"], text=True)

    with contexte.appele_par_appareil(ADMIN):
        resultat = memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)

    assert "core/src/config.ts" not in {item["path"] for item in resultat["sources"]}
    assert any(item["path"] == "core/src/config.ts" for item in resultat["skipped"])
    journal = json.dumps(list(stockage.maillons("m10-memoire", "developpement")))
    assert "PRIVATE_SENTINEL_NOT_FOR_INDEX" not in journal
    assert subprocess.check_output(["git", "-C", str(depot_git), "status", "--porcelain"], text=True) == statut_avant


def test_prompt_plan_preflight_postflight_sont_sourcables_apres_restauration(base_dev, depot_git, monkeypatch):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        prompt = memoire_dev.enregistrer_prompt(
            "m7-seo-audit",
            "Pourquoi la page locale oubliait ses sources ? Conserver la preuve du test M7.",
            version=1,
            module="M7",
            objectif="corriger le rappel des sources SEO",
            source_refs=["departments/m07-marketing/docs/seo.md"],
            horodatage=HORODATAGE,
        )
        plan = memoire_dev.enregistrer_plan(
            "m7-seo-audit",
            version=1,
            module="M7",
            prompt_id="m7-seo-audit",
            prompt_version=1,
            objectif="Rétablir les sources de la page locale",
            etapes=[
                {"id": "inspecter", "description": "Lire la page et les tests existants", "statut": "done"},
                {"id": "corriger", "description": "Ajouter les liens locaux manquants", "statut": "active"},
            ],
            fichiers=["departments/m07-marketing/docs/seo.md"],
            risques=["Ne pas exposer de données client"],
            horodatage=HORODATAGE,
        )
        plan_v2 = memoire_dev.enregistrer_plan(
            "m7-seo-audit",
            version=2,
            module="M7",
            prompt_id="m7-seo-audit",
            prompt_version=1,
            objectif="Rétablir les sources et vérifier le rendu mobile",
            etapes=[{"id": "mobile", "description": "Vérifier le rendu mobile", "statut": "active"}],
            fichiers=["departments/m07-marketing/docs/seo.md"],
            horodatage=HORODATAGE,
        )
        decision = memoire_dev.enregistrer_decision(
            "m7-seo-citations",
            version=1,
            module="M7",
            contexte_decision="Les sources doivent rester vérifiables.",
            options=["garder les liens", "retirer les citations"],
            raisons=["Le test de source doit être reproductible."],
            consequences=["La page expose des preuves consultables."],
            autorite="Décision de développement sourcée",
            source_refs=["departments/m07-marketing/docs/seo.md"],
            horodatage=HORODATAGE,
        )
        postflight = memoire_dev.enregistrer_postflight(
            "run-m7-seo-1",
            module="M7",
            plan_id="m7-seo-audit",
            statut="partial",
            resume="Le rappel est corrigé; les tests de liens passent, l'analyse mobile reste à faire.",
            changements=[{"fichier": "departments/m07-marketing/docs/seo.md", "resume": "Ajout des citations"}],
            tests=[{"source": "departments/m07-marketing/tests/test_seo.py", "resultat": "passed"}],
            rapport_refs=["reports/m7-seo-run-1"],
            claim_key="seo-sources-local",
            horodatage=HORODATAGE,
        )
        preflight = memoire_dev.preflight(
            "M7",
            "Rappelle le prompt et le plan du correctif SEO avec ses preuves",
            files=["departments/m07-marketing/docs/seo.md"],
            repository=depot_git,
        )

    # Copie de la base après fermeture et restauration sous une autre URL : le registre suit l'instance.
    stockage.liberer()
    url_restauree = f"sqlite:///{base_dev / 'opsys-restauree.db'}"
    shutil.copy2(base_dev / "opsys.db", base_dev / "opsys-restauree.db")
    monkeypatch.setenv(stockage.ENV_URL, url_restauree)
    stockage.migrer(url_restauree)
    with contexte.appele_par_appareil(PROPRIETAIRE):
        relu = memoire_dev.preflight("M7", "correctif SEO sources", files=[], repository=depot_git)
        audit_restaure = memoire_dev.auditer_developpement(repository=depot_git)

    assert prompt["content_hash"] == hashlib.sha256(prompt["content"].encode()).hexdigest()
    assert plan["version"] == decision["version"] == 1
    assert plan_v2["version"] == 2
    assert postflight["status"] == "partial"
    assert preflight["status"] == "available"
    assert any(item["kind"] == "prompt" and item["entity_id"] == "m7-seo-audit" for item in preflight["must_know"])
    assert any(item["kind"] == "plan" and item["entity_id"] == "m7-seo-audit" for item in preflight["must_know"])
    plan_states = {item["version"]: item["status"] for item in preflight["must_know"] if item["kind"] == "plan"}
    assert plan_states == {1: "superseded", 2: "active"}
    assert any(
        item["kind"] == "decision" and item["entity_id"] == "m7-seo-citations" for item in preflight["must_know"]
    )
    assert any(item["path"].endswith("seo.md") and item["sha256"] for item in preflight["evidence"])
    assert any(link["type"] == "prompt_for" for link in preflight["links"])
    assert any(link["type"] == "changes" for link in preflight["links"])
    assert any(link["type"] == "tests" for link in preflight["links"])
    assert any(link["type"] == "report" for link in preflight["links"])
    assert relu["status"] == "available"
    assert {item["event_id"] for item in relu["must_know"]} == {item["event_id"] for item in preflight["must_know"]}
    assert audit_restaure["counts"]["prompts_sans_plan"] == 0
    assert audit_restaure["counts"]["plans_sans_postflight"] == 0


def test_postflight_idempotent_et_faits_done_vs_partial_restent_en_contradiction(base_dev, depot_git):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        (depot_git / "core/src/config.ts").write_text("export const retries = 7;\n", encoding="utf-8")
        memoire_dev.enregistrer_postflight(
            "config-run-1",
            module="CORE",
            plan_id="config-plan",
            statut="done",
            resume="La nouvelle configuration de petit volume fonctionne.",
            changements=[{"fichier": "core/config.toml"}],
            tests=[{"source": "core/test/config.test.ts", "resultat": "passed"}],
            rapport_refs=["reports/config-run-1"],
            claim_key="small-config-change",
            horodatage=HORODATAGE,
        )
        replay = memoire_dev.enregistrer_postflight(
            "config-run-1",
            module="CORE",
            plan_id="config-plan",
            statut="done",
            resume="La nouvelle configuration de petit volume fonctionne.",
            changements=[{"fichier": "core/config.toml"}],
            tests=[{"source": "core/test/config.test.ts", "resultat": "passed"}],
            rapport_refs=["reports/config-run-1"],
            claim_key="small-config-change",
            horodatage=HORODATAGE,
        )
        with pytest.raises(memoire_dev.ConflitIdempotence):
            memoire_dev.enregistrer_postflight(
                "config-run-1",
                module="CORE",
                plan_id="config-plan",
                statut="partial",
                resume="Autre résultat sous la même clé.",
                changements=[],
                tests=[],
                rapport_refs=[],
                claim_key="small-config-change",
                horodatage=HORODATAGE,
            )
        memoire_dev.enregistrer_postflight(
            "config-run-2",
            module="CORE",
            plan_id="config-plan",
            statut="partial",
            resume="La variante grand volume échoue encore.",
            changements=[{"fichier": "core/config.toml"}],
            tests=[{"source": "core/test/config.test.ts", "resultat": "failed"}],
            rapport_refs=["reports/config-run-2"],
            claim_key="small-config-change",
            horodatage=HORODATAGE,
        )
        contexte_reprise = memoire_dev.preflight(
            "CORE", "revoir small config change core config", files=["core/src/config.ts"], repository=depot_git
        )

    assert replay["replayed"] is True
    assert len(contexte_reprise["contradictions"]) == 1
    assert {item["status"] for item in contexte_reprise["contradictions"][0]["evidence"]} == {"done", "partial"}
    assert any(item["freshness"] == "stale" for item in contexte_reprise["evidence"])
    assert any("résultat" in item for item in contexte_reprise["limitations"])


def test_preflight_borne_lecture_fraicheur_apres_gonflement_du_fichier(base_dev, depot_git, monkeypatch):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        fichier = depot_git / "departments/m07-marketing/docs/seo.md"
        with fichier.open("wb") as stream:
            stream.truncate(memoire_dev.MAX_FILE_BYTES + 1)
        original = Path.open
        ouvert = []

        def ouverture_gardee(path, *args, **kwargs):
            if path == fichier:
                ouvert.append(True)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", ouverture_gardee)
        paquet = memoire_dev.preflight("M7", "SEO sources locales", files=[], repository=depot_git)

    source = next(item for item in paquet["evidence"] if item["path"].endswith("seo.md"))
    assert source["freshness"] == "too_large"
    assert not ouvert


def test_preflight_ne_suit_pas_une_source_devenue_symlink_vers_fichier_exclu(base_dev, depot_git):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        source = depot_git / "departments/m07-marketing/docs/seo.md"
        source.unlink()
        source.symlink_to(depot_git / "core/.env.example")
        paquet = memoire_dev.preflight("M7", "SEO local sources", files=[], repository=depot_git)

    preuve = next(item for item in paquet["evidence"] if item["path"].endswith("seo.md"))
    assert preuve["freshness"] == "missing"
    assert "example-secret-value" not in json.dumps(paquet)


def test_audit_developpement_borne_authentifie_et_sourcable(base_dev, depot_git):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "prompt-sans-plan",
            "Garder les tests existants.",
            version=1,
            module="M7",
            objectif="audit",
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "prompt-avec-plan",
            "Corriger la config locale.",
            version=1,
            module="CORE",
            objectif="audit",
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_plan(
            "plan-sans-postflight",
            version=1,
            module="CORE",
            prompt_id="prompt-avec-plan",
            prompt_version=1,
            objectif="Inspecter la config",
            etapes=[{"id": "inspecter", "description": "Inspecter", "statut": "done"}],
            fichiers=["core/src/config.ts"],
            horodatage=HORODATAGE,
        )
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        (depot_git / "core/src/config.ts").write_text("export const retries = 99;\n", encoding="utf-8")
        rapport = memoire_dev.auditer_developpement(repository=depot_git, limite=1)

    assert rapport["status"] == "partial"
    assert rapport["truncated"] is True
    assert rapport["counts"]["prompts_sans_plan"] == 1
    assert rapport["counts"]["plans_sans_postflight"] == 1
    assert rapport["counts"]["sources_perimees"] == 1
    assert all(item["event_ids"] and item["preuves"] for item in rapport["findings"])
    with contexte.appele_par_appareil(M3), pytest.raises(memoire_dev.AccesDeveloppementRefuse):
        memoire_dev.auditer_developpement(repository=depot_git)


def test_audit_ne_classe_pas_absente_une_cible_valide_hors_fenetre(base_dev, monkeypatch):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "prompt-ancien",
            "Conserver la preuve du changement.",
            version=1,
            module="M7",
            objectif="test fenêtre",
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_plan(
            "plan-recent",
            version=1,
            module="M7",
            prompt_id="prompt-ancien",
            prompt_version=1,
            objectif="Vérifier le lien",
            etapes=[{"id": "inspecter", "description": "Inspecter", "statut": "active"}],
            fichiers=[],
            horodatage=HORODATAGE,
        )
        monkeypatch.setattr(memoire_dev, "MAX_AUDIT_EVENTS", 1)
        rapport = memoire_dev.auditer_developpement()

    assert rapport["event_scan_truncated"] is True
    assert rapport["counts"]["relations_cibles_absentes"] == 0
    assert rapport["counts"]["relations_hors_fenetre"] == 1
    assert rapport["freshness"]["status"] == "unknown"


def test_audit_namespace_claim_par_module(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        for operation, module, status in (
            ("run-m1", "M1", "done"),
            ("run-m7", "M7", "partial"),
        ):
            memoire_dev.enregistrer_postflight(
                operation,
                module=module,
                plan_id=f"plan-{module}",
                statut=status,
                resume=f"Verdict {status} de {module}.",
                changements=[],
                tests=[],
                rapport_refs=[],
                claim_key="même-claim-littéral",
                horodatage=HORODATAGE,
            )
        rapport = memoire_dev.auditer_developpement()

    assert rapport["counts"]["claims_contradictoires"] == 0
    assert rapport["freshness"]["status"] == "unknown"


def test_audit_signale_postflight_dont_le_plan_est_absent_du_registre(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        postflight = memoire_dev.enregistrer_postflight(
            "run-sans-plan",
            module="M7",
            plan_id="plan-jamais-enregistre",
            statut="partial",
            resume="État conservé sans plan source.",
            changements=[],
            tests=[],
            rapport_refs=[],
            horodatage=HORODATAGE,
        )
        rapport = memoire_dev.auditer_developpement()

    assert rapport["counts"]["postflights_sans_plan"] == 1
    finding = next(item for item in rapport["findings"] if item["type"] == "postflights_sans_plan")
    assert finding["event_ids"] == [postflight["event_id"]]
    assert finding["preuves"] == [{"event_id": postflight["event_id"], "plan_id": "plan-jamais-enregistre"}]


def test_redaction_par_cle_json_masque_secrets_factices_sans_masquer_compteurs(base_dev):
    faux_api_key = "fixture-api-value-not-a-secret"
    faux_password = "fixture-password-value"
    faux_authorization = "fixture-authorization-value"
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "prompt-redaction-cle", "Protéger les champs de configuration.", version=1, module="M7",
            objectif="test redaction structurée", horodatage=HORODATAGE,
        )
        plan = memoire_dev.enregistrer_plan(
            "plan-redaction-cle", version=1, module="M7", prompt_id="prompt-redaction-cle", prompt_version=1,
            objectif="Vérifier la préservation des métriques légitimes",
            etapes=[
                {
                    "id": "configurer",
                    "description": "Entrées de configuration factices",
                    "statut": "active",
                    "api_key": faux_api_key,
                    "password": faux_password,
                    "token_count": 17,
                    "source_refs": ["docs/configuration.md#safe-reference"],
                }
            ],
            fichiers=["src/configuration.py"], horodatage=HORODATAGE,
        )
        postflight = memoire_dev.enregistrer_postflight(
            "run-redaction-cle", module="M7", plan_id="plan-redaction-cle", statut="partial",
            resume="Les clés de configuration sont masquées.",
            changements=[{"fichier": "src/configuration.py", "authorization": faux_authorization, "retry_count": 4}],
            tests=[{"source": "tests/test_configuration.py", "client_secret": "fixture-client-secret-value"}],
            rapport_refs=[], horodatage=HORODATAGE,
        )

    journal_relu = json.dumps(list(stockage.maillons("m10-memoire", "developpement")), ensure_ascii=False)
    plan_relu = json.dumps(plan, ensure_ascii=False)
    postflight_relu = json.dumps(postflight, ensure_ascii=False)
    for valeur in (faux_api_key, faux_password, faux_authorization, "fixture-client-secret-value"):
        assert valeur not in journal_relu and valeur not in plan_relu and valeur not in postflight_relu
    assert journal_relu.count("[REDACTED]") >= 4
    assert '\\"token_count\\":17' in journal_relu
    assert '\\"retry_count\\":4' in journal_relu
    assert "docs/configuration.md#safe-reference" in journal_relu


def test_prompts_expurgent_secrets_et_contexte_vide_est_explicitement_indisponible(base_dev, depot_git):
    secret = "sk-opsys-12345678901234567890"
    with contexte.appele_par_appareil(ADMIN):
        prompt = memoire_dev.enregistrer_prompt(
            "prompt-avec-cle",
            f"Corriger le rappel; API_KEY={secret}",
            version=1,
            module="M7",
            objectif="test redaction",
            horodatage=HORODATAGE,
        )
        vide = memoire_dev.preflight("M9", "scénario inexistant", files=[], repository=depot_git)

    journal = json.dumps(list(stockage.maillons("m10-memoire", "developpement")))
    assert secret not in journal
    assert "[REDACTED]" in prompt["content"]
    assert prompt["redacted"] is True
    assert vide["status"] == "unavailable"
    assert vide["reason"] and vide["must_know"] == []
    assert vide["limits"]["must_know"] == 30
    assert vide["counts"]["candidates"] == 0
    assert vide["counts"]["candidates_omitted"] == 0
    assert vide["truncated"] is False


def test_cli_standalone_n_expose_aucun_argument_identite():
    args = construire_parseur().parse_args(
        ["memoire-developpement", "preflight", "--module", "M7", "--tache", "rappel bugfix"]
    )
    assert args.module == "M7"
    assert not hasattr(args, "agent") and not hasattr(args, "principal")


def test_cli_authentifie_interactivement_sans_env_et_ne_journalise_pas_le_secret(base_dev, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    mot_de_passe = "mot-de-passe-admin-dev-123"
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _prompt: "admin.dev")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: mot_de_passe)
    monkeypatch.setenv("OPSYS_MEMOIRE_DEVELOPPEMENT_UTILISATEUR", "vendeur.dev")

    code = cli_main(["memoire-developpement", "preflight", "--module", "M7", "--tache", "rappel inexistant"])

    sortie = capsys.readouterr()
    assert code == 0
    assert '"status": "unavailable"' in sortie.out
    assert mot_de_passe not in sortie.out and mot_de_passe not in sortie.err


def test_cli_non_interactif_refuse_memes_avec_env_d_identite(base_dev, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setenv("OPSYS_MEMOIRE_DEVELOPPEMENT_UTILISATEUR", "admin.dev")

    code = cli_main(["memoire-developpement", "preflight", "--module", "M7", "--tache", "test"])

    assert code == 1
    assert "connexion interactive" in capsys.readouterr().err


def test_cli_audit_requiert_auth_interactive_et_retourne_echec_si_partiel(base_dev, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _prompt: "admin.dev")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "mot-de-passe-admin-dev-123")
    reports = []

    def audit(*, repository=None, limite=100):
        reports.append((repository, limite))
        return {"status": "partial", "findings": [], "limit": limite}

    monkeypatch.setattr(memoire_dev, "auditer_developpement", audit)
    assert cli_main(["memoire-developpement", "auditer", "--limite", "25"]) == 1
    assert reports == [(None, 25)]
    assert '"status": "partial"' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["memoire-developpement", "auditer", "--limite", "501"])


def test_rendu_audit_console_ne_divulgue_pas_le_texte_des_prompts():
    html = audit_contenu(
        {
            "status": "partial",
            "domain": "development",
            "repository": "/tmp/repo<script>",
            "limit": 1,
            "truncated": True,
            "counts": {"prompts_sans_plan": 1},
            "findings": [
                {
                    "type": "prompts_sans_plan",
                    "detail": "prompt courant sans relation",
                    "event_ids": ["evt-1"],
                    "preuves": [{"event_id": "evt-1", "hash": "abc123"}],
                    "content": "TEXTE SECRET DU PROMPT",
                }
            ],
        },
        "/console",
    )
    assert "evt-1" in html and "abc123" in html
    assert "TEXTE SECRET DU PROMPT" not in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_preflight_annonce_troncature_et_compte_candidats_omis(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "cible-ancienne",
            "rappel fenêtre ambré",
            version=1,
            module="M10",
            objectif="ambré",
            horodatage=HORODATAGE,
        )
        for index in range(30):
            memoire_dev.enregistrer_prompt(
                f"candidat-{index:02}",
                f"rappel fenêtre ambré candidat {index}",
                version=1,
                module="M10",
                objectif="ambré",
                horodatage=HORODATAGE,
            )
        paquet = memoire_dev.preflight("M10", "rappel fenêtre ambré", files=[])

    assert paquet["status"] == "available"
    assert len(paquet["must_know"]) == 30
    assert not any(item["entity_id"] == "cible-ancienne" for item in paquet["must_know"])
    assert paquet["truncated"] is True
    assert paquet["limits"]["must_know"] == 30
    assert paquet["counts"]["candidates"] == 31
    assert paquet["counts"]["must_know"] == 30
    assert paquet["counts"]["candidates_omitted"] == 1


def test_preflight_signale_contradiction_dont_un_postflight_hors_fenetre(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_postflight(
            "claim-partial-old",
            module="M10",
            plan_id="plan-claim",
            statut="partial",
            resume="cobaltplume citadel needle preuve partielle",
            changements=[],
            tests=[],
            rapport_refs=[],
            claim_key="cobaltplume",
            horodatage="2026-09-30T14:00:00+00:00",
        )
        memoire_dev.enregistrer_postflight(
            "claim-done-new",
            module="M10",
            plan_id="plan-claim",
            statut="done",
            resume="cobaltplume résultat terminé",
            changements=[],
            tests=[],
            rapport_refs=[],
            claim_key="cobaltplume",
            horodatage="2026-09-30T14:30:00+00:00",
        )
        for index in range(29):
            memoire_dev.enregistrer_prompt(
                f"concurrent-{index:02}",
                f"cobaltplume citadel needle contexte concurrent {index}",
                version=1,
                module="M10",
                objectif="cobaltplume citadel needle",
                horodatage=HORODATAGE,
            )
        paquet = memoire_dev.preflight("M10", "cobaltplume citadel needle", files=[])

    assert len(paquet["must_know"]) == 30
    assert not any(item["entity_id"] == "claim-done-new" for item in paquet["must_know"])
    assert paquet["counts"]["candidates_omitted"] == 1
    assert len(paquet["contradictions"]) == 1
    assert paquet["contradictions"][0]["claim_key"] == "cobaltplume"
    assert paquet["truncated"] is True
    assert len(paquet["must_know"]) <= paquet["limits"]["must_know"]
    assert len(paquet["contradictions"]) <= paquet["limits"]["contradictions"]
    assert (
        len(paquet["contradictions"][0]["evidence"])
        <= paquet["limits"]["contradiction_evidence_per_claim"]
    )
    assert paquet["counts"]["contradictions_returned"] == 1
    assert {item["status"] for item in paquet["contradictions"][0]["evidence"]} == {
        "done",
        "partial",
    }


def test_preflight_borne_contradictions_et_preuves_par_claim(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        for claim_index in range(31):
            claim_key = f"fenix-{claim_index:02}"
            for status_index, status in enumerate(("done", "partial", "blocked")):
                memoire_dev.enregistrer_postflight(
                    f"fenix-{claim_index:02}-{status_index}",
                    module="M10",
                    plan_id="plan-fenix",
                    statut=status,
                    resume="preuve synthétique bornée",
                    changements=[],
                    tests=[],
                    rapport_refs=[],
                    claim_key=claim_key,
                    horodatage=HORODATAGE,
                )
        paquet = memoire_dev.preflight("M10", "fenix", files=[])

    assert paquet["status"] == "available"
    assert len(paquet["must_know"]) == 30
    assert paquet["counts"]["candidates"] == 93
    assert paquet["counts"]["candidates_omitted"] == 63
    assert paquet["counts"]["contradictions"] == 31
    assert paquet["counts"]["contradictions_returned"] == 30
    assert paquet["counts"]["contradictions_omitted"] == 1
    fixture_evidence_total = 31 * 3
    evidence_returned_from_output = sum(
        len(contradiction["evidence"]) for contradiction in paquet["contradictions"]
    )
    evidence_omitted_from_fixture = fixture_evidence_total - evidence_returned_from_output
    assert fixture_evidence_total == 93
    assert evidence_returned_from_output == 60
    assert evidence_omitted_from_fixture == 33
    assert paquet["counts"]["evidence_total"] == fixture_evidence_total
    assert paquet["counts"]["evidence_returned"] == evidence_returned_from_output
    assert paquet["counts"]["evidence_omitted"] == evidence_omitted_from_fixture
    assert paquet["counts"]["contradiction_evidence_per_claim_omitted"] == 31
    assert paquet["limits"] == {
        "must_know": 30,
        "contradictions": 30,
        "contradiction_evidence_per_claim": 2,
    }
    assert paquet["truncated"] is True
    assert len(paquet["contradictions"]) == 30
    for contradiction in paquet["contradictions"]:
        assert contradiction["evidence_count"] == 3
        assert contradiction["statuses"] == ["blocked", "done", "partial"]
        evidence_statuses = {item["status"] for item in contradiction["evidence"]}
        assert len(contradiction["evidence"]) == 2
        assert len(evidence_statuses) == 2


def test_preflight_ancre_fichier_exact_et_ignore_chemin_proche_ou_texte_libre(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "exact-file-anchor",
            "rappel bruit lexical src target",
            version=1,
            module="M10",
            objectif="rappel bruit lexical src target",
            source_refs=["src/target.py"],
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "near-file-anchor",
            "rappel bruit lexical src target src/target.py.old",
            version=1,
            module="M10",
            objectif="rappel bruit lexical src target",
            source_refs=["src/target.py.old"],
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "free-text-anchor",
            "rappel bruit lexical src target src/target.py",
            version=1,
            module="M10",
            objectif="rappel bruit lexical src target",
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "other-module-anchor",
            "rappel bruit lexical src target",
            version=1,
            module="M7",
            objectif="rappel bruit lexical src target",
            source_refs=["src/target.py"],
            horodatage=HORODATAGE,
        )
        for index in range(31):
            memoire_dev.enregistrer_prompt(
                f"lexical-noise-{index:02}",
                "rappel bruit lexical src target",
                version=1,
                module="M10",
                objectif="rappel bruit lexical src target",
                horodatage=HORODATAGE,
            )
        result = memoire_dev.preflight("M10", "rappel bruit lexical src target", files=["src/target.py"])

    returned = {item["entity_id"] for item in result["must_know"]}
    assert "exact-file-anchor" in returned
    assert "near-file-anchor" not in returned
    assert "free-text-anchor" not in returned
    assert "other-module-anchor" not in returned
    assert result["counts"]["must_know"] == 30
    assert result["counts"]["candidates_omitted"] == 4
    assert result["truncated"] is True


def test_preflight_ancre_identifiant_tape_exact_sans_matcher_son_extension(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "target-blue",
            "rappel bruit lexical",
            version=1,
            module="M10",
            objectif="rappel bruit lexical",
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "target-blueish",
            "rappel bruit lexical",
            version=1,
            module="M10",
            objectif="rappel bruit lexical",
            horodatage=HORODATAGE,
        )
        for index in range(31):
            memoire_dev.enregistrer_prompt(
                f"id-noise-{index:02}",
                "rappel bruit lexical",
                version=1,
                module="M10",
                objectif="rappel bruit lexical",
                horodatage=HORODATAGE,
            )
        exact = memoire_dev.preflight("M10", "rappel bruit lexical target-blue", files=[])
        extended = memoire_dev.preflight("M10", "rappel bruit lexical target-blueish-extra", files=[])

    exact_ids = {item["entity_id"] for item in exact["must_know"]}
    extended_ids = {item["entity_id"] for item in extended["must_know"]}
    assert "target-blue" in exact_ids
    assert "target-blueish" not in extended_ids
    assert exact["counts"]["candidates"] == extended["counts"]["candidates"] == 33
    assert exact["counts"]["must_know"] == extended["counts"]["must_know"] == 30


def test_preflight_remplacement_cycle_est_visite_une_seule_fois(base_dev, monkeypatch):
    from contextlib import contextmanager

    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "cycle-anchor",
            "directive quartz",
            version=1,
            module="M10",
            objectif="directive quartz",
            source_refs=["docs/quartz.md"],
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "cycle-anchor",
            "directive quartz remplacée",
            version=2,
            module="M10",
            objectif="directive quartz",
            source_refs=["docs/quartz-v2.md"],
            horodatage=HORODATAGE,
        )

    original_connexion = memoire_dev._connexion

    @contextmanager
    def connexion_avec_cycle():
        with original_connexion() as cnx:
            event_ids = [
                row[0]
                for row in cnx.execute(
                    "SELECT event_id FROM events WHERE entity_id = ? ORDER BY version",
                    ("prompt:cycle-anchor",),
                )
            ]
            source, replacement = event_ids
            relation = [replacement, source, "superseded_by"]
            cnx.execute(
                "INSERT OR IGNORE INTO relations(relation_id,from_event,to_ref,relation_type,created_at) "
                "VALUES(?,?,?,?,?)",
                (
                    memoire_dev._hash(memoire_dev._json(relation)),
                    replacement,
                    source,
                    "superseded_by",
                    HORODATAGE,
                ),
            )
            yield cnx
            relation_hash = memoire_dev._hash(memoire_dev._json(relation))
            cnx.execute("DELETE FROM relations WHERE relation_id = ?", (relation_hash,))

    monkeypatch.setattr(memoire_dev, "_connexion", connexion_avec_cycle)
    with contexte.appele_par_appareil(ADMIN):
        result = memoire_dev.preflight("M10", "directive quartz", files=["docs/quartz.md"])

    returned = [item for item in result["must_know"] if item["entity_id"] == "cycle-anchor"]
    assert len(returned) == 2
    assert result["counts"]["candidates"] == 2
    assert result["counts"]["lineage_unresolved"] == 1
    assert len([link for link in result["links"] if link["type"] == "superseded_by"]) == 2


def test_preflight_annonce_frontiere_d_une_lignee_supersedee_bornee(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        for version in range(1, 32):
            memoire_dev.enregistrer_prompt(
                "long-replacement-chain",
                f"directive quartz version {version}",
                version=version,
                module="M10",
                objectif="directive quartz",
                source_refs=["docs/quartz.md"] if version == 1 else [f"docs/quartz-v{version}.md"],
                horodatage=HORODATAGE,
            )
        result = memoire_dev.preflight("M10", "directive quartz", files=["docs/quartz.md"])

    assert result["limits"]["must_know"] == 30
    assert result["counts"]["must_know"] == 30
    assert result["counts"]["candidates"] == 31
    assert result["counts"]["candidates_omitted"] == 1
    assert result["counts"]["lineage_traversal_truncated"] is False
    assert result["counts"]["lineage_frontier_omitted"] == 0
    assert result["counts"]["lineage_node_limit"] == 1000
    assert result["truncated"] is True


def test_r3_red_cible_actuelle_apres_chaine_supersedee_de_31(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        for version in range(1, 32):
            memoire_dev.enregistrer_prompt(
                "long-chain-r3",
                f"rappel quartz marker version {version}" if version > 1 else "consigne ancienne",
                version=version,
                module="M10",
                objectif="rappel quartz marker" if version > 1 else "ancienne consigne",
                source_refs=["docs/only-v1.md"] if version == 1 else [f"docs/version-{version}.md"],
                horodatage=f"2026-09-30T15:{version:02}:00+00:00",
            )
        result = memoire_dev.preflight("M10", "rappel quartz marker", files=["docs/only-v1.md"])
    versions = {item["version"]: item["status"] for item in result["must_know"] if item["entity_id"] == "long-chain-r3"}
    assert versions.get(31) == "active", "latest eligible replacement omitted behind older lineage nodes"
    assert versions.get(1) == "superseded", "explicitly anchored old prompt lost its replacement lineage"
    assert result["counts"]["candidates_omitted"] == 1


def test_r3_red_trente_ancres_directes_laissent_les_endpoints_hors_selection(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        files = []
        for index in range(30):
            prompt_id = f"many-anchor-{index:02}"
            old_path = f"docs/old-{index:02}.md"
            files.append(old_path)
            memoire_dev.enregistrer_prompt(
                prompt_id,
                "rappel quartz",
                version=1,
                module="M10",
                objectif="rappel quartz",
                source_refs=[old_path],
                horodatage=HORODATAGE,
            )
            memoire_dev.enregistrer_prompt(
                prompt_id,
                "rappel quartz actuel",
                version=2,
                module="M10",
                objectif="rappel quartz actuel",
                source_refs=[f"docs/current-{index:02}.md"],
                horodatage=HORODATAGE,
            )
        result = memoire_dev.preflight("M10", "rappel quartz", files=files)
    returned = {(item["entity_id"], item["version"]) for item in result["must_know"]}
    expected_current = {(f"many-anchor-{index:02}", 2) for index in range(30)}
    assert returned == expected_current, "all 30 current endpoints must fit before older anchors"
    assert result["counts"]["lineage_endpoints"] == 30
    assert result["counts"]["candidates"] == 60
    assert result["counts"]["candidates_omitted"] == 30
    assert result["truncated"] is True


def test_r3_red_evenements_hors_module_ne_confèrent_pas_une_lignee(base_dev, monkeypatch):
    from contextlib import contextmanager

    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "filter-anchor",
            "ancienne directive",
            version=1,
            module="M10",
            objectif="ancienne directive",
            source_refs=["docs/filter-anchor.md"],
            horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "filter-current-target",
            "résumé faible",
            version=1,
            module="M10",
            objectif="résumé court",
            horodatage=HORODATAGE,
        )
        for index in range(30):
            memoire_dev.enregistrer_prompt(
                f"foreign-node-{index:02}",
                "foreign module record",
                version=1,
                module="M7",
                objectif="foreign module record",
                horodatage=HORODATAGE,
            )
        for index in range(31):
            memoire_dev.enregistrer_prompt(
                f"valid-noise-{index:02}",
                "needle quartz unrelated lexical noise",
                version=1,
                module="M10",
                objectif="needle quartz unrelated lexical noise",
                horodatage=HORODATAGE,
            )

    original_connexion = memoire_dev._connexion

    @contextmanager
    def connexion_avec_lignee_hors_module():
        with original_connexion() as cnx:
            event_ids = {
                row["entity_id"]: row["event_id"]
                for row in cnx.execute("SELECT entity_id,event_id FROM events")
            }
            source = event_ids["prompt:filter-anchor"]
            target = event_ids["prompt:filter-current-target"]
            foreign = [event_ids[f"prompt:foreign-node-{index:02}"] for index in range(30)]
            injected = []
            chain = [source, *foreign, target]
            for index, (from_event, to_event) in enumerate(zip(chain, chain[1:], strict=False)):
                relation = [from_event, to_event, "superseded_by"]
                relation_id = memoire_dev._hash(memoire_dev._json(relation))
                injected.append(relation_id)
                cnx.execute(
                    "INSERT OR IGNORE INTO relations("
                    "relation_id,from_event,to_ref,relation_type,created_at) VALUES(?,?,?,?,?)",
                    (relation_id, from_event, to_event, "superseded_by", f"2026-09-30T14:{index:02}:00+00:00"),
                )
            yield cnx
            placeholders = ",".join("?" for _ in injected)
            cnx.execute(f"DELETE FROM relations WHERE relation_id IN ({placeholders})", injected)

    monkeypatch.setattr(memoire_dev, "_connexion", connexion_avec_lignee_hors_module)
    with contexte.appele_par_appareil(ADMIN):
        result = memoire_dev.preflight("M10", "needle quartz", files=["docs/filter-anchor.md"])
    returned = {(item["entity_id"], item["version"]) for item in result["must_know"]}
    assert ("filter-current-target", 1) not in returned, (
        "foreign-module intermediary incorrectly conferred targeted lineage"
    )
    assert result["counts"]["lineage_unresolved"] == 1



def test_r3_lignee_stockee_peut_renommer_l_identite(base_dev, monkeypatch):
    from contextlib import contextmanager

    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "legacy-name", "directive quartz ancienne", version=1, module="M10",
            objectif="directive quartz ancienne", source_refs=["docs/legacy.md"], horodatage=HORODATAGE,
        )
        memoire_dev.enregistrer_prompt(
            "new-name", "directive quartz actuelle", version=1, module="M10",
            objectif="directive quartz actuelle", source_refs=["docs/current.md"], horodatage=HORODATAGE,
        )

    original_connexion = memoire_dev._connexion

    @contextmanager
    def connexion_avec_remplacement_renomme():
        with original_connexion() as cnx:
            event_ids = {
                row["entity_id"]: row["event_id"]
                for row in cnx.execute("SELECT entity_id,event_id FROM events")
            }
            old_event = event_ids["prompt:legacy-name"]
            new_event = event_ids["prompt:new-name"]
            relation = [old_event, new_event, "superseded_by"]
            relation_id = memoire_dev._hash(memoire_dev._json(relation))
            cnx.execute(
                "INSERT OR IGNORE INTO relations("
                "relation_id,from_event,to_ref,relation_type,created_at) VALUES(?,?,?,?,?)",
                (relation_id, old_event, new_event, "superseded_by", HORODATAGE),
            )
            yield cnx
            cnx.execute("DELETE FROM relations WHERE relation_id = ?", (relation_id,))

    monkeypatch.setattr(memoire_dev, "_connexion", connexion_avec_remplacement_renomme)
    with contexte.appele_par_appareil(ADMIN):
        result = memoire_dev.preflight("M10", "directive quartz", files=["docs/legacy.md"])

    returned = {(item["entity_id"], item["status"]) for item in result["must_know"]}
    assert ("new-name", "active") in returned
    assert result["counts"]["lineage_endpoints"] == 1
    assert any(link["type"] == "superseded_by" for link in result["links"])



def test_r4_diamond_convergent_est_lignee_valide_pas_un_cycle(base_dev, monkeypatch):
    from contextlib import contextmanager

    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "diamond-anchor", "directive quartz convergence", version=1, module="M10",
            objectif="directive quartz", source_refs=["docs/diamond.md"], horodatage=HORODATAGE,
        )
        for name in ("branch-left", "branch-right", "diamond-current"):
            memoire_dev.enregistrer_prompt(
                name, "résumé court", version=1, module="M10", objectif="résumé court",
                horodatage=HORODATAGE,
            )

    original_connexion = memoire_dev._connexion

    @contextmanager
    def connexion_avec_diamond():
        with original_connexion() as cnx:
            event_ids = {
                row["entity_id"]: row["event_id"]
                for row in cnx.execute("SELECT entity_id,event_id FROM events")
            }
            a, b, c, d = [event_ids[f"prompt:{name}"] for name in (
                "diamond-anchor", "branch-left", "branch-right", "diamond-current"
            )]
            inserted = []
            for source, target in ((a, b), (a, c), (b, d), (c, d)):
                relation = [source, target, "superseded_by"]
                relation_id = memoire_dev._hash(memoire_dev._json(relation))
                cnx.execute(
                    "INSERT OR IGNORE INTO relations("
                    "relation_id,from_event,to_ref,relation_type,created_at) VALUES(?,?,?,?,?)",
                    (relation_id, source, target, "superseded_by", HORODATAGE),
                )
                inserted.append(relation_id)
            yield cnx
            cnx.executemany("DELETE FROM relations WHERE relation_id = ?", [(item,) for item in inserted])

    monkeypatch.setattr(memoire_dev, "_connexion", connexion_avec_diamond)
    with contexte.appele_par_appareil(ADMIN):
        result = memoire_dev.preflight("M10", "directive quartz", files=["docs/diamond.md"])

    assert ("diamond-current", 1) in {
        (item["entity_id"], item["version"]) for item in result["must_know"]
    }
    assert result["counts"]["lineage_unresolved"] == 0, "DAG convergence is not a cycle"
    assert result["counts"]["lineage_endpoints"] == 1
    assert result["truncated"] is False


def test_r3_red_fraicheur_preuve_est_par_hash_et_non_par_chemin(base_dev, depot_git):
    source = depot_git / "departments/m07-marketing/docs/seo.md"
    source.write_text("SEO keyword amber initial snapshot\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(depot_git), "add", "."], check=True)
    subprocess.run(["git", "-C", str(depot_git), "commit", "-qm", "source v1"], check=True)
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage="2026-09-30T15:00:00+00:00")
    source.write_text("SEO keyword amber updated snapshot\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(depot_git), "add", "."], check=True)
    subprocess.run(["git", "-C", str(depot_git), "commit", "-qm", "source v2"], check=True)
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage="2026-09-30T15:01:00+00:00")
        result = memoire_dev.preflight("M7", "SEO keyword amber updated initial", files=[], repository=depot_git)
    evidence = [item for item in result["evidence"] if item["path"] == "departments/m07-marketing/docs/seo.md"]
    by_hash = {item["sha256"]: item["freshness"] for item in evidence}
    assert len(by_hash) == 2
    assert sorted(by_hash.values()) == ["current", "stale"], "old file hash incorrectly inherited newest path freshness"


def test_r3_red_relevance_lexicale_precede_statut_ordinaire_recence_departage(base_dev):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "lexical-vs-status",
            "quartz rare marker",
            version=1,
            module="M10",
            objectif="quartz rare marker",
            horodatage="2026-09-30T14:00:00+00:00",
        )
        memoire_dev.enregistrer_prompt(
            "lexical-vs-status",
            "note faible",
            version=2,
            module="M10",
            objectif="résumé court",
            horodatage="2026-09-30T15:00:00+00:00",
        )
        result = memoire_dev.preflight("M10", "quartz rare marker", files=[])
    assert result["must_know"][0]["version"] == 1, (
        "active status outranked stronger lexical match for ordinary candidates"
    )


def test_diagnostic_de_postflight_est_une_assertion_sourcable_et_redigee(base_dev, depot_git, monkeypatch):
    incident = {
        "incident_id": "M10-DEV-123",
        "symptom": "La cible ne ressort pas après trop de bruit lexical.",
        "cause": "L'index reste borné avant la cible.",
        "cause_status": "confirmed",
        "prevention": "Citer le chemin exact de la source attendue.",
        "source_refs": ["core/src/bug.py"],
        "observed_at": HORODATAGE,
    }
    with contexte.appele_par_appareil(ADMIN):
        event = memoire_dev.enregistrer_postflight(
            "incident-run-1",
            module="CORE",
            plan_id="incident-plan",
            statut="done",
            resume="Correctif du rappel",
            changements=[{"fichier": "core/src/bug.py", "resume": "Ajuste la sélection"}],
            tests=[{"source": "core/test/bug.test.ts", "resultat": "passed"}],
            rapport_refs=[],
            claim_key=None,
            diagnostic=incident,
            horodatage=HORODATAGE,
        )
        reprise = memoire_dev.preflight(
            "CORE", "Comment éviter M10-DEV-123 ?", files=["core/src/bug.py"], repository=depot_git
        )

    assert event["diagnostic"] == incident
    assert reprise["status"] == "available"
    matched = next(item for item in reprise["must_know"] if item["payload"].get("diagnostic"))
    assert matched["payload"]["diagnostic"]["cause_status"] == "confirmed"
    assert matched["diagnostic_assurance"] == "author_assertion_unverified"
    assert any(link["type"] == "changes" and link["to_ref"] == "file:core/src/bug.py" for link in reprise["links"])
    assert any(link["type"] == "tests" and link["to_ref"] == "core/test/bug.test.ts" for link in reprise["links"])
    assert any("déclarations d'auteur" in text for text in reprise["limitations"])
    with contexte.appele_par_appareil(ADMIN):
        mauvais_module = memoire_dev.preflight("M7", "M10-DEV-123", files=[], repository=depot_git)
    assert not any(item["payload"].get("diagnostic") for item in mauvais_module["must_know"])
    event_id = matched["event_id"]
    stockage.liberer()
    url_restauree = f"sqlite:///{base_dev / 'opsys-restauree.db'}"
    shutil.copy2(base_dev / "opsys.db", base_dev / "opsys-restauree.db")
    monkeypatch.setenv(stockage.ENV_URL, url_restauree)
    stockage.migrer(url_restauree)
    with contexte.appele_par_appareil(PROPRIETAIRE):
        restauree = memoire_dev.preflight("CORE", "M10-DEV-123", files=[], repository=depot_git)
    assert any(item["event_id"] == event_id for item in restauree["must_know"])


def test_diagnostic_refuse_statut_non_unknown_sans_source_sans_ecriture(base_dev):
    avant = list(stockage.maillons("m10-memoire", "developpement"))
    diagnostic = {
        "incident_id": "M10-DEV-EMPTY",
        "symptom": "symptôme fictif",
        "cause": "cause déclarée",
        "cause_status": "confirmed",
        "prevention": "prévention déclarée",
        "source_refs": [],
        "observed_at": HORODATAGE,
    }
    with contexte.appele_par_appareil(ADMIN), pytest.raises(ValueError, match="source"):
        memoire_dev.enregistrer_postflight(
            "empty-incident",
            module="CORE",
            plan_id="empty-plan",
            statut="done",
            resume="aucun",
            changements=[],
            tests=[],
            rapport_refs=[],
            diagnostic=diagnostic,
            horodatage=HORODATAGE,
        )
    assert list(stockage.maillons("m10-memoire", "developpement")) == avant


def test_revision_diagnostic_cree_lignee_uniquement_entre_versions_du_meme_postflight(base_dev, depot_git):
    common = {
        "incident_id": "M10-DEV-REV",
        "symptom": "symptôme",
        "cause_status": "supported",
        "prevention": "prévention",
        "source_refs": ["core/src/revision.py"],
        "observed_at": HORODATAGE,
    }
    with contexte.appele_par_appareil(ADMIN):
        for version, cause in ((1, "cause initiale"), (2, "cause révisée")):
            memoire_dev.enregistrer_postflight(
                "revision-same-operation",
                module="CORE",
                plan_id="revision-plan",
                statut="done",
                resume="diagnostic révisable",
                changements=[{"fichier": "core/src/revision.py", "resume": "fix"}],
                tests=[{"source": "core/test/revision_test.py", "resultat": "passed"}],
                rapport_refs=[],
                diagnostic=common | {"cause": cause},
                version=version,
                horodatage=HORODATAGE,
            )
        courant = memoire_dev.preflight("CORE", "M10-DEV-REV", files=[], repository=depot_git)
        unlinked = memoire_dev.enregistrer_postflight(
            "revision-other-operation",
            module="CORE",
            plan_id="revision-plan",
            statut="done",
            resume="assertion indépendante même incident",
            changements=[],
            tests=[],
            rapport_refs=[],
            diagnostic=common | {"cause": "cause sans lien explicite"},
            horodatage=HORODATAGE,
        )
        ambigu = memoire_dev.preflight("CORE", "M10-DEV-REV", files=[], repository=depot_git)

    versions = [item for item in courant["must_know"] if item["payload"].get("diagnostic")]
    assert {(item["version"], item["status"]) for item in versions} == {(1, "superseded"), (2, "done")}
    assert any(link["type"] == "superseded_by" for link in courant["links"])
    same_incident = [
        item for item in ambigu["must_know"]
        if item["payload"].get("diagnostic", {}).get("incident_id") == "M10-DEV-REV"
    ]
    assert len(same_incident) == 3
    assert not any(
        link["type"] == "superseded_by" and link["from_event"] == unlinked["event_id"]
        for link in ambigu["links"]
    )


def test_diagnostic_source_changee_est_perimee_et_secret_expurge(base_dev, depot_git):
    source = depot_git / "core/src/diagnostic.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# cause initiale\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(depot_git), "add", "core/src/diagnostic.py"], check=True)
    subprocess.run(["git", "-C", str(depot_git), "commit", "-qm", "source diagnostic fictive"], check=True)
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.scanner_depot(depot_git, horodatage=HORODATAGE)
        memoire_dev.enregistrer_postflight(
            "stale-diagnostic",
            module="CORE",
            plan_id="stale-plan",
            statut="partial",
            resume="API_KEY=fixture-diagnostic-secret",
            changements=[{"fichier": "core/src/diagnostic.py", "resume": "fix"}],
            tests=[],
            rapport_refs=[],
            diagnostic={
                "incident_id": "M10-DEV-STALE",
                "symptom": "symptôme fictif",
                "cause": "cause avec API_KEY=fixture-cause-secret",
                "cause_status": "supported",
                "prevention": "prévention",
                "source_refs": ["core/src/diagnostic.py"],
                "observed_at": HORODATAGE,
            },
            horodatage=HORODATAGE,
        )
        source.write_text("# cause corrigée\n", encoding="utf-8")
        reprise = memoire_dev.preflight(
            "CORE", "M10-DEV-STALE", files=["core/src/diagnostic.py"], repository=depot_git
        )

    encoded = json.dumps(reprise, ensure_ascii=False)
    assert "fixture-diagnostic-secret" not in encoded
    assert "fixture-cause-secret" not in encoded
    assert any(
        item["path"] == "core/src/diagnostic.py" and item["freshness"] == "stale"
        for item in reprise["evidence"]
    )


def test_postflight_diagnostic_qualifie_retour_immediat_et_rejeu(base_dev):
    diagnostic = {
        "incident_id": "M10.DEV:123_case", "symptom": "symptôme fictif",
        "cause": "cause déclarée", "cause_status": "confirmed",
        "prevention": "prévention déclarée", "source_refs": ["core/src/diagnostic.py"],
        "observed_at": HORODATAGE,
    }
    args = {
        "module": "CORE", "plan_id": "diagnostic-plan", "statut": "done",
        "resume": "diagnostic", "changements": [], "tests": [], "rapport_refs": [],
        "diagnostic": diagnostic, "horodatage": HORODATAGE,
    }
    with contexte.appele_par_appareil(ADMIN):
        first = memoire_dev.enregistrer_postflight("diagnostic-return", **args)
        replay = memoire_dev.enregistrer_postflight("diagnostic-return", **args)
        legacy = memoire_dev.enregistrer_postflight("legacy-return", **(args | {"diagnostic": None}))
    assert first["diagnostic"]["cause_status"] == "confirmed"
    assert first["diagnostic_assurance"] == "author_assertion_unverified"
    assert first["replayed"] is False
    assert replay["diagnostic_assurance"] == "author_assertion_unverified"
    assert replay["replayed"] is True
    assert "diagnostic_assurance" not in legacy


def test_incident_id_est_ancre_exacte_et_un_suffixe_ne_lest_pas(base_dev, depot_git):
    diagnostic = {
        "incident_id": "M10.DEV:123_case",
        "symptom": "symptôme fictif",
        "cause": "cause déclarée",
        "cause_status": "supported",
        "prevention": "prévention déclarée",
        "source_refs": ["core/src/token.py"],
        "observed_at": HORODATAGE,
    }
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_postflight(
            "token-incident",
            module="CORE",
            plan_id="token-plan",
            statut="done",
            resume="diagnostic fictif",
            changements=[],
            tests=[],
            rapport_refs=[],
            diagnostic=diagnostic,
            horodatage=HORODATAGE,
        )
        for index in range(35):
            memoire_dev.enregistrer_postflight(
                f"lexical-noise-{index}", module="CORE", plan_id=f"noise-plan-{index}",
                statut="done", resume="diagnostic token sélection lexicale bruit", changements=[],
                tests=[], rapport_refs=[], horodatage=HORODATAGE,
            )
        exact = memoire_dev.preflight("CORE", "M10.DEV:123_case", files=[], repository=depot_git)
        prefixed = memoire_dev.preflight("CORE", "xM10.DEV:123_case", files=[], repository=depot_git)
        suffixed = memoire_dev.preflight("CORE", "M10.DEV:123_case-extra", files=[], repository=depot_git)

    assert exact["counts"]["lineage_anchors"] == 1
    assert prefixed["counts"]["lineage_anchors"] == 0
    assert suffixed["counts"]["lineage_anchors"] == 0
    assert len(exact["must_know"]) <= 30
    assert any(
        item["payload"].get("diagnostic", {}).get("incident_id") == "M10.DEV:123_case"
        for item in exact["must_know"]
    )
    assert exact["counts"]["candidates_omitted"] > 0


def test_prompt_id_existant_garde_point_terminal_avec_bruit_au_dela_du_cap(base_dev, depot_git):
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_prompt(
            "PROMPT-ABC", "instruction distincte", version=1, module="CORE",
            objectif="objectif distinct", horodatage=HORODATAGE,
        )
        for index in range(35):
            memoire_dev.enregistrer_prompt(
                f"noise-prompt-{index}", "Find PROMPT ABC parmi le bruit", version=1,
                module="CORE", objectif="Find PROMPT ABC parmi le bruit", horodatage=HORODATAGE,
            )
        result = memoire_dev.preflight("CORE", "Find PROMPT-ABC.", files=[], repository=depot_git)

    assert result["counts"]["lineage_anchors"] == 1
    assert len(result["must_know"]) <= 30
    assert any(item["entity_id"] == "PROMPT-ABC" for item in result["must_know"])
    assert result["counts"]["candidates_omitted"] > 0


def test_incident_hyphene_suffixe_point_n_est_pas_ancre(base_dev, depot_git):
    diagnostic = {
        "incident_id": "INC-ABC", "symptom": "symptôme fictif", "cause": "cause déclarée",
        "cause_status": "supported", "prevention": "prévention déclarée",
        "source_refs": ["core/src/incident.py"], "observed_at": HORODATAGE,
    }
    with contexte.appele_par_appareil(ADMIN):
        memoire_dev.enregistrer_postflight(
            "incident-hyphen", module="CORE", plan_id="incident-plan", statut="done",
            resume="incident fictif", changements=[], tests=[], rapport_refs=[],
            diagnostic=diagnostic, horodatage=HORODATAGE,
        )
        exact = memoire_dev.preflight("CORE", "INC-ABC", files=[], repository=depot_git)
        suffixed = memoire_dev.preflight("CORE", "INC-ABC.extra", files=[], repository=depot_git)

    assert exact["counts"]["lineage_anchors"] == 1
    assert suffixed["counts"]["lineage_anchors"] == 0
