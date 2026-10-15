"""La CI teste chaque département : la matrice du job `departement` de `.github/workflows/ci.yml`
doit nommer exactement les dossiers de `departments/`. Un département ajouté sans entrée dans la
matrice ne serait jamais testé par la CI.

Le lint (PLAN T5.1) est activé département par département : la liste `DEPARTEMENTS_LINT` du job ne
contient que des départements déjà propres selon `ruff`. Un département absent de la liste n'est
pas linté ; un département listé mais sale ferait échouer la CI, donc ce fichier le détecte avant."""

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
CONDITION_LINT = "contains(fromJSON(env.DEPARTEMENTS_LINT), matrix.dossier)"


def _ci() -> dict:
    return yaml.safe_load((RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _dossiers_departements() -> list[str]:
    return sorted(p.name for p in (RACINE / "departments").iterdir() if (p / "department.yaml").is_file())


def _departements_lintes() -> list[str]:
    return json.loads(_ci()["jobs"]["departement"]["env"]["DEPARTEMENTS_LINT"])


def _etape_lint() -> dict:
    etapes = [e for e in _ci()["jobs"]["departement"]["steps"] if e.get("name", "").startswith("Lint du département")]
    assert len(etapes) == 1
    return etapes[0]


def _commande_ruff() -> list[str] | None:
    """`ruff` du même environnement Python que les tests, sinon celui du PATH ; None s'il manque."""
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    binaire = shutil.which("ruff")
    return [binaire] if binaire else None


def _ruff_check(*chemins: str | Path) -> subprocess.CompletedProcess:
    commande = _commande_ruff()
    if commande is None:
        pytest.skip("ruff n'est pas installé dans cet environnement (la CI l'installe via `.[dev]`)")
    return subprocess.run(
        [*commande, "check", "--no-cache", "--config", str(RACINE / "pyproject.toml"), *map(str, chemins)],
        cwd=RACINE,
        capture_output=True,
        text=True,
        check=False,
    )


def test_la_matrice_ci_couvre_exactement_les_departements():
    matrice = _ci()["jobs"]["departement"]["strategy"]["matrix"]["dossier"]
    assert sorted(matrice) == _dossiers_departements()
    assert len(matrice) == len(set(matrice))
    assert _ci()["jobs"]["socle"]["timeout-minutes"] >= 35


def test_le_controle_requis_de_pr_ne_partage_pas_le_nom_d_un_push_prive():
    # Le push compare deux points, la PR trois : leurs checks ne doivent pas se remplacer.
    assert _ci()["jobs"]["gates"].get("name") == (
        "${{ github.event_name == 'push' && github.ref != 'refs/heads/main' && 'gates-push' || 'gates' }}"
    )


def test_gates_exige_le_succes_de_chaque_job_requis():
    gates = _ci()["jobs"]["gates"]
    python = {"socle", "departement", "m03-preuves", "frontiere-postgresql"}
    appels = {"core", "e2e_core", "mobile", "installateur", "dependency_audit"}
    assert set(gates["needs"]) == {"changements", *python, *appels}
    assert len(gates["needs"]) == 10
    assert gates["if"] == "always()"
    (etape,) = [e for e in gates["steps"] if "selection_workflows.py gates" in e.get("run", "")]
    assert etape["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert etape["run"].split() == ["python", ".github/ci/selection_workflows.py", "gates"]

    def controle(needs):
        # Exécuter l'entrée réellement câblée par le YAML, avec des résultats GitHub fictifs seulement.
        return subprocess.run(
            [sys.executable, *etape["run"].split()[1:]],
            cwd=RACINE,
            env={"NEEDS_JSON": json.dumps(needs)},
            capture_output=True,
            text=True,
            check=False,
        )

    needs = {job: {"result": "success", "outputs": {}} for job in ("changements", *python)}
    needs["changements"]["outputs"] = dict.fromkeys(appels, "false")
    needs.update({job: {"result": "skipped", "outputs": {}} for job in appels})
    assert controle(needs).returncode == 0  # Aucun appel applicable n'est exigé pour un diff documentaire.
    for job in ("changements", *python):
        incomplets = json.loads(json.dumps(needs))
        incomplets[job]["result"] = "failure"
        assert controle(incomplets).returncode != 0, job
    for job in appels:
        incomplets = json.loads(json.dumps(needs))
        incomplets["changements"]["outputs"][job] = "true"
        assert controle(incomplets).returncode != 0, job  # Applicable mais skipped ne devient jamais vert.
    for job in appels:
        needs["changements"]["outputs"][job] = "true"
        needs[job]["result"] = "success"
    assert controle(needs).returncode == 0


def test_la_liste_de_lint_nomme_des_departements_existants_de_la_matrice_sans_doublon():
    lintes = _departements_lintes()
    assert lintes, "la liste de lint ne peut pas être vide : T5.1 est amorcée avec M7 à M10"
    assert len(lintes) == len(set(lintes))
    matrice = _ci()["jobs"]["departement"]["strategy"]["matrix"]["dossier"]
    assert sorted(set(lintes) - set(_dossiers_departements())) == []
    assert sorted(set(lintes) - set(matrice)) == []


def test_l_etape_de_lint_ne_vise_que_le_departement_de_la_matrice_et_seulement_s_il_est_liste():
    etape = _etape_lint()
    assert etape["if"] == CONDITION_LINT
    assert etape["run"] == 'ruff check "departments/${{ matrix.dossier }}"'
    noms = [e.get("name", "") for e in _ci()["jobs"]["departement"]["steps"]]
    # Lint avant les tests : un avertissement échoue vite, sans attendre la suite du département.
    assert noms.index(etape["name"]) < noms.index("Tests du département ${{ matrix.dossier }}")


def test_aucune_autre_etape_ne_linte_un_departement():
    """Le socle lint `src tests` ; seul le pas conditionné ci-dessus lint un département."""
    autorisees = {"ruff check src tests", 'ruff check "departments/${{ matrix.dossier }}"'}
    for nom_job, job in _ci()["jobs"].items():
        if "uses" in job:
            fichiers = {"core": "core", "e2e_core": "e2e-core", "mobile": "mobile",
                        "installateur": "installateur", "dependency_audit": "dependency-audit"}
            assert nom_job in fichiers
            assert job["uses"] == f"./.github/workflows/{fichiers[nom_job]}.yml"
            assert "steps" not in job  # Appel réutilisable, pas un job de lint omis silencieusement.
            continue
        for etape in job["steps"]:
            for ligne in etape.get("run", "").splitlines():
                if re.search(r"\bruff\b", ligne):
                    assert ligne.strip() in autorisees, (nom_job, ligne)


def test_le_job_socle_lint_toujours_le_socle():
    commandes = [e.get("run", "") for e in _ci()["jobs"]["socle"]["steps"]]
    assert "ruff check src tests" in commandes


def test_le_job_socle_installe_et_eprouve_l_isolation_pdf_avant_pytest():
    socle = _ci()["jobs"]["socle"]
    assert socle["runs-on"] == "ubuntu-latest"
    etapes = socle["steps"]
    (etape,) = [e for e in etapes if e.get("name") == "Vérification de l’isolation PDF native"]
    commande = etape["run"]
    assert etape["shell"] == "bash"
    assert "set -euo pipefail" in commande
    assert "sudo apt-get update" in commande
    assert "sudo apt-get install -y --no-install-recommends bubblewrap" in commande
    assert "bwrap --version" in commande
    assert "from opsys.fusion_pdf import _commande_isolee" in commande
    assert "commande = _commande_isolee()" in commande
    assert "subprocess.run(commande, check=True, env={}, timeout=10)" in commande
    assert "continue-on-error" not in etape
    assert "|| true" not in commande
    assert "skip" not in commande.lower()
    assert not etape.get("if")
    noms = [e.get("name", "") for e in etapes]
    assert noms.index(etape["name"]) < noms.index("Tests du socle")


def test_chaque_departement_de_la_liste_de_lint_est_propre_selon_ruff():
    for dossier in _departements_lintes():
        resultat = _ruff_check(RACINE / "departments" / dossier)
        assert resultat.returncode == 0, f"{dossier} n'est pas propre :\n{resultat.stdout}{resultat.stderr}"


def test_le_controle_ruff_detecte_un_avertissement(tmp_path):
    """Garde contre un faux vert : le même appel doit échouer sur un fichier qui viole la règle."""
    sale = tmp_path / "sale.py"
    sale.write_text("import os\n", encoding="utf-8")
    resultat = _ruff_check(sale)
    assert resultat.returncode != 0
    assert "F401" in resultat.stdout


def test_les_outils_de_preuve_de_m3_tournent_une_fois_et_une_seule():
    """Le job de M3 les écarte, `m03-preuves` les exécute : aucun des deux fichiers n'est oublié ni joué deux fois."""
    ci = _ci()
    parts = ci["jobs"]["m03-preuves"]["strategy"]["matrix"]["include"]
    fichiers = sorted({p["fichier"] for p in parts})
    assert fichiers == ["test_gardes_des_outils.py", "test_outils_de_preuve.py"]
    for fichier in fichiers:  # chaque part de 0 à parts-1 exactement une fois, un seul nombre de parts
        du_fichier = [p for p in parts if p["fichier"] == fichier and "seul" not in p]
        (total,) = {p["parts"] for p in du_fichier}
        assert sorted(p["part"] for p in du_fichier) == list(range(total))
    assert not any("seul" in p for p in parts)
    assert "CAS_SEULS" not in ci["jobs"]["m03-preuves"].get("env", {})
    etape_preuves = next(e for e in ci["jobs"]["m03-preuves"]["steps"] if "Outils de preuve de M3" in e.get("name", ""))
    assert "i % PARTS == PART" in etape_preuves["run"]
    assert 'test "${#retenus[@]}" -gt 0' in etape_preuves["run"]
    for fichier in fichiers:
        assert (RACINE / "departments" / "m03-estimation" / "tests" / fichier).is_file()
    nom = "Tests du département ${{ matrix.dossier }}"
    etape = next(e for e in ci["jobs"]["departement"]["steps"] if e.get("name") == nom)
    for fichier in fichiers:
        assert f"departments/m03-estimation/tests/{fichier}" in etape["run"]
    assert "matrix.dossier == 'm03-estimation'" in etape["run"]


@pytest.mark.parametrize(
    "nombre,etat,accepte",
    [(31, "ok", True), (0, "ok", False), (30, "ok", False), (32, "ok", False),
     (31, "skipped", False), (31, "failure", False), (31, "error", False)],
)
def test_la_preuve_postgresql_exige_des_scenarios_executes_sans_ignorance(
    tmp_path, monkeypatch, nombre, etat, accepte,
):
    """Exécute le contrôle réel du job contre un rapport : un job sans preuve ne passe pas."""
    import xml.etree.ElementTree as ET

    job = _ci()["jobs"]["frontiere-postgresql"]
    assert not job.get("if") and not job.get("continue-on-error")
    etapes = [e for e in job["steps"] if "tests/e2e/test_verticale_postgresql_refus_c02.py" in e.get("run", "")]
    assert len(etapes) == 1
    etape = etapes[0]
    commande = etape["run"]
    assert "tests/e2e/test_verticale_postgresql_refus_c02.py" in commande
    assert "tests/e2e/test_m9_snapshot_concurrent.py" in commande
    assert "tests/e2e/test_m9_ingestion_concurrent.py" in commande
    assert "tests/e2e/test_bus_publication_concurrente.py" in commande
    assert "tests/e2e/test_readiness_m2_m3_concurrente.py" in commande
    assert "tests/e2e/test_m8_ingestion_reprise_concurrente.py" in commande
    assert "tests/e2e/test_m5_mouvement_concurrent.py" in commande
    assert "tests/e2e/test_m5_facture_brouillon_concurrent.py" in commande
    assert "tests/e2e/test_m5_facture_consommateur_concurrent.py" in commande
    assert "tests/e2e/test_m5_envoi_facture_concurrent.py" in commande
    assert "tests/e2e/test_m5_paiement_facture_concurrent.py" in commande
    assert "tests/e2e/test_m5_saisie_facture_fournisseur_concurrente.py" in commande
    assert "tests/e2e/test_m5_saisie_sans_po_concurrente.py" in commande
    assert "tests/e2e/test_m5_annulation_fournisseur_concurrente.py" in commande
    assert "tests/e2e/test_m5_correction_fournisseur_concurrente.py" in commande
    assert "tests/e2e/test_m5_reception_consumer_concurrente.py" in commande
    assert "tests/e2e/test_m7_inbox_concurrente.py" in commande
    assert "tests/e2e/test_m7_decision_concurrente.py" in commande
    script = commande.split("python - <<'PYTHON'\n", 1)[1].rsplit("\nPYTHON", 1)[0]
    racine = ET.Element("testsuites")
    suite = ET.SubElement(racine, "testsuite")
    for index in range(nombre):
        cas = ET.SubElement(suite, "testcase", name=f"frontiere-fictive-{index}")
        if index == 0 and etat != "ok":
            ET.SubElement(cas, etat)
    ET.ElementTree(racine).write(tmp_path / "frontiere-postgresql.xml", encoding="utf-8")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    resultat = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert (resultat.returncode == 0) is accepte, resultat.stderr


# Le transport CI utilise l'artefact officiel déjà courant, pas une nouvelle version.
PGVECTOR_EPINGLE = (
    "pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
)
PGVECTOR_TAG_LOCAL = "pgvector/pgvector:pg17"
MIROIR_GOOGLE = "https://mirror.gcr.io"
IMAGE_ID_FICTIF = "sha256:" + "a" * 64


@pytest.fixture
def preparation_pgvector():
    chemin = RACINE / "scripts/ci/preparer_pgvector.py"
    assert chemin.is_file(), "le préparateur partagé borné de PostgreSQL est absent"
    spec = importlib.util.spec_from_file_location("preparation_pgvector_ci", chemin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DockerCiFictif:
    """Frontière Docker remplacée seulement : le préparateur réel fait tous les contrôles."""

    def __init__(self, *, panne=None, erreur=None, inspection=None, versions=None):
        self.appels = []
        self.panne = panne
        self.erreur = erreur
        self.inspection = inspection
        self.versions = versions

    def __call__(self, commande, **options):
        self.appels.append((commande, options))
        assert options["check"] is True and options["capture_output"] is True
        assert isinstance(options["timeout"], int) and options["timeout"] > 0
        if len(self.appels) == self.panne:
            if self.erreur is not None:
                raise self.erreur
            raise subprocess.CalledProcessError(1, commande, stderr=b"CANARY-ERREUR-FICTIVE")
        sortie = b""
        if commande[:3] == ["docker", "image", "inspect"]:
            objet = {"id": IMAGE_ID_FICTIF, "digests": [PGVECTOR_EPINGLE]}
            sortie = self.inspection if self.inspection is not None else (
                json.dumps(objet) + "\n" + json.dumps(objet) + "\n"
            ).encode()
        if commande[:2] == ["docker", "run"]:
            sortie = self.versions if self.versions is not None else (
                b"postgres (PostgreSQL) 17.6\ndefault_version = '0.8.7'\n"
            )
        return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr=b"")


@pytest.mark.parametrize("job", ["departement", "frontiere-postgresql", "socle"])
def test_pgvector_chaque_job_pg_prepare_la_meme_image_bornee(job):
    nom = {"departement": "Préparation PostgreSQL pour les tests M10 en RAM",
           "frontiere-postgresql": "Préparation explicite de PostgreSQL",
           "socle": "Préparation PostgreSQL pour les tests du socle"}[job]
    etapes = _ci()["jobs"][job]["steps"]
    retenues = [e for e in etapes if e.get("name") == nom]
    assert len(retenues) == 1
    etape = retenues[0]
    assert etape["run"].strip() == "python scripts/ci/preparer_pgvector.py"
    assert not etape.get("continue-on-error")
    if job == "departement":
        assert etape["if"] == "matrix.dossier == 'm10-memoire'"
    if job == "socle":
        assert not etape.get("if")
        noms = [e.get("name") for e in etapes]
        assert noms.index(nom) < noms.index("Tests du socle")


def test_miroir_installation_ubuntu_avant_docker_sans_toucher_aux_autres_profils():
    workflow = yaml.safe_load((RACINE / ".github/workflows/installateur.yml").read_text())
    nom = "Docker : cache public des images épinglées"
    etapes = workflow["jobs"]["installation"]["steps"]
    retenues = [e for e in etapes if e.get("name") == nom]
    assert len(retenues) == 1
    assert retenues[0]["run"] == "python scripts/ci/preparer_pgvector.py --miroir-seulement"
    assert not retenues[0].get("if") and not retenues[0].get("continue-on-error")
    noms = [e.get("name") for e in etapes]
    assert noms.index(nom) < noms.index("Docker : CLI et daemon Linux requis avant le vrai E2E")
    for job, description in workflow["jobs"].items():
        if job != "installation":
            assert all(e.get("name") != nom for e in description["steps"])


def test_miroir_seulement_cli_ne_tire_ni_ne_sonde_une_image(preparation_pgvector, tmp_path, monkeypatch, capsys):
    docker = DockerCiFictif()
    configurer = preparation_pgvector.configurer_miroir
    monkeypatch.setattr(preparation_pgvector, "configurer_miroir",
                        lambda: configurer(tmp_path / "daemon.json", executer=docker))
    monkeypatch.setattr(preparation_pgvector, "preparer", lambda: pytest.fail("PG interdit dans le mode miroir"))
    assert preparation_pgvector.main(["--miroir-seulement"]) == 0
    assert len(docker.appels) == 2
    assert docker.appels[1][0] == ["sudo", "systemctl", "restart", "docker"]
    assert all(c[0] != "docker" for c, _ in docker.appels)
    assert json.loads(capsys.readouterr().out) == {"miroir_configure": MIROIR_GOOGLE}


def test_pgvector_fusion_preserve_cles_et_miroirs_inconnus(preparation_pgvector, tmp_path):
    chemin = tmp_path / "daemon.json"
    original = {"log-driver": "json-file", "debug": False, "dns": ["192.0.2.1"],
                "registry-mirrors": ["https://cache-fictif.invalid", MIROIR_GOOGLE]}
    chemin.write_text(json.dumps(original))
    fusion = preparation_pgvector.lire_configuration(chemin)
    assert fusion == {**original, "registry-mirrors": [MIROIR_GOOGLE, "https://cache-fictif.invalid"]}
    assert json.loads(chemin.read_text()) == original  # la lecture/fusion ne réécrit pas le fichier


def test_pgvector_configuration_absente_est_explicitement_creee(preparation_pgvector, tmp_path):
    assert preparation_pgvector.lire_configuration(tmp_path / "absent.json") == {
        "registry-mirrors": [MIROIR_GOOGLE]
    }


@pytest.mark.parametrize("existant", [False, True])
def test_pgvector_ecriture_atomique_reelle_fictive_preserve_mode(preparation_pgvector, tmp_path, monkeypatch, existant):
    chemin = tmp_path / "docker-fictif" / "daemon.json"
    if existant:
        chemin.parent.mkdir()
        chemin.write_text('{"debug": false}')
        chemin.chmod(0o640)
    entree = b'{"debug": false, "registry-mirrors": ["https://mirror.gcr.io"]}\n'
    monkeypatch.setattr(sys, "argv", ["ecriture-fictive", str(chemin)])
    monkeypatch.setattr(sys, "stdin", type("Entree", (), {"buffer": io.BytesIO(entree)})())
    # Même code -c privilégié, sur un namespace tmp_path possédé : aucun sudo/démon/commande.
    exec(compile(preparation_pgvector.ECRITURE, "ecriture-ci-fictive", "exec"), {})
    assert chemin.read_bytes() == entree
    assert chemin.stat().st_mode & 0o777 == (0o640 if existant else 0o600)
    assert list(chemin.parent.glob(".opsys-ci-*")) == []


@pytest.mark.parametrize("brut", [
    "", "{", "[]", "null", "true", '{"registry-mirrors": null}',
    '{"registry-mirrors": "https://cache-fictif.invalid"}', '{"registry-mirrors": [true]}',
    '{"registry-mirrors": [""]}', '{"debug": NaN}', '{"debug": Infinity}',
    '{"registry-mirrors": [], "registry-mirrors": []}',
])
def test_pgvector_config_malformee_refuse_avant_toute_commande(preparation_pgvector, tmp_path, brut):
    chemin = tmp_path / "daemon.json"
    chemin.write_text(brut)
    docker = DockerCiFictif()
    with pytest.raises(preparation_pgvector.PreparationRefusee):
        preparation_pgvector.preparer(chemin, executer=docker)
    assert docker.appels == []
    assert chemin.read_text() == brut


def test_pgvector_config_et_sortie_bornees_avant_toute_commande(preparation_pgvector, tmp_path):
    chemin = tmp_path / "daemon.json"
    for brut in [b" " * 65537, json.dumps({"opaque": "x" * 65498}).encode()]:
        chemin.write_bytes(brut)
        docker = DockerCiFictif()
        with pytest.raises(preparation_pgvector.PreparationRefusee):
            preparation_pgvector.preparer(chemin, executer=docker)
        assert docker.appels == []


def test_pgvector_parcours_reel_du_helper_pin_tag_identite_et_versions(preparation_pgvector, tmp_path):
    docker = DockerCiFictif()
    resultat = preparation_pgvector.preparer(tmp_path / "daemon.json", executer=docker)
    commandes = [c for c, _ in docker.appels]
    assert len(commandes) == 6
    assert commandes[0][0] == "sudo"
    assert json.loads(docker.appels[0][1]["input"]) == {"registry-mirrors": [MIROIR_GOOGLE]}
    assert commandes[1] == ["sudo", "systemctl", "restart", "docker"]
    assert commandes[2] == ["docker", "pull", PGVECTOR_EPINGLE]
    assert docker.appels[2][1]["timeout"] == 900
    assert commandes[3] == ["docker", "tag", PGVECTOR_EPINGLE, PGVECTOR_TAG_LOCAL]
    assert commandes[4][:3] == ["docker", "image", "inspect"]
    assert commandes[4][-2:] == [PGVECTOR_EPINGLE, PGVECTOR_TAG_LOCAL]
    assert commandes[5][:2] == ["docker", "run"]
    assert "--pull=never" in commandes[5] and "--network=none" in commandes[5]
    assert "--read-only" in commandes[5] and PGVECTOR_EPINGLE in commandes[5]
    assert "postgres --version" in commandes[5][-1] and "vector.control" in commandes[5][-1]
    assert resultat == {"image": PGVECTOR_TAG_LOCAL, "digest": PGVECTOR_EPINGLE.split("@", 1)[1],
                        "postgres_major": 17, "pgvector_version_installee": "0.8.7"}


@pytest.mark.parametrize("panne", [1, 2, 3, 4, 5, 6])
def test_pgvector_chaque_panne_arrete_sans_retry_ni_detail_brut(preparation_pgvector, tmp_path, panne):
    docker = DockerCiFictif(panne=panne)
    with pytest.raises(preparation_pgvector.PreparationRefusee) as erreur:
        preparation_pgvector.preparer(tmp_path / "daemon.json", executer=docker)
    assert len(docker.appels) == panne
    assert "CANARY" not in str(erreur.value)


@pytest.mark.parametrize("exception", [
    subprocess.TimeoutExpired("commande-fictive", 900, stderr=b"CANARY-FICTIF"),
    OSError("CANARY-FICTIF"),
])
def test_pgvector_timeout_et_exec_impossible_sont_rouges_sans_retry(preparation_pgvector, tmp_path, exception):
    docker = DockerCiFictif(panne=3, erreur=exception)
    with pytest.raises(preparation_pgvector.PreparationRefusee) as erreur:
        preparation_pgvector.preparer(tmp_path / "daemon.json", executer=docker)
    assert len(docker.appels) == 3
    assert "CANARY" not in str(erreur.value)


@pytest.mark.parametrize("inspection", [
    b"pas du JSON\n", b"{}\n{}\n", b"[]\n[]\n", b"x" * 8193,
    (json.dumps({"id": IMAGE_ID_FICTIF, "digests": ["pgvector/pgvector@sha256:" + "b" * 64]})
     + "\n" + json.dumps({"id": IMAGE_ID_FICTIF, "digests": [PGVECTOR_EPINGLE]})).encode(),
    (json.dumps({"id": IMAGE_ID_FICTIF, "digests": [PGVECTOR_EPINGLE]})
     + "\n" + json.dumps({"id": "sha256:" + "b" * 64, "digests": [PGVECTOR_EPINGLE]})).encode(),
])
def test_pgvector_digest_ou_tag_divergent_ne_lance_pas_le_probe_version(preparation_pgvector, tmp_path, inspection):
    docker = DockerCiFictif(inspection=inspection)
    with pytest.raises(preparation_pgvector.PreparationRefusee):
        preparation_pgvector.preparer(tmp_path / "daemon.json", executer=docker)
    assert len(docker.appels) == 5


@pytest.mark.parametrize("versions", [
    b"postgres (PostgreSQL) 18.0\ndefault_version = '0.8.7'\n",
    b"postgres (PostgreSQL) 17.6\ndefault_version = '0.8.6'\n",
    b"postgres (PostgreSQL) 17.6\n", b"\xff", b"x" * 8193,
])
def test_pgvector_version_binaire_ou_extension_inattendue_reste_rouge(preparation_pgvector, tmp_path, versions):
    docker = DockerCiFictif(versions=versions)
    with pytest.raises(preparation_pgvector.PreparationRefusee):
        preparation_pgvector.preparer(tmp_path / "daemon.json", executer=docker)
    assert len(docker.appels) == 6
