from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "outils_preuve"))
from _environnement_mutation import EnvironnementMutation
from adaptateur_campagne import executer_preuve, specification_outil
from campagne_m3 import (
    CampagneM3,
    EmpreinteEntrees,
    SpecificationExecution,
    racines_fermeture_m3,
)


def _installer_fixture_commune_m2(racine):
    """Dépendance réelle du harnais, copiée dans chaque dépôt fictif minimal."""
    source = Path(__file__).resolve().parents[3] / "tests/fixtures/m2_preparation_estimation.py"
    cible = racine / "tests/fixtures/m2_preparation_estimation.py"
    cible.parent.mkdir(parents=True)
    cible.write_bytes(source.read_bytes())


def _spec(*, scenario: str = "nominal", argv: tuple[str, ...] = ("muter_x.py",)):
    return SpecificationExecution(
        outil="muter_x.py",
        scenario=scenario,
        commande=("python", "muter_x.py", *argv[1:]),
        argv=argv,
        cwd="{RACINE}",
        python="python 3.13 / pytest 9.1",
        environnement_sha256=hashlib.sha256(b"PYTHONPATH=src").hexdigest(),
        options_pytest=("-q", "--junitxml={ARTEFACT}"),
        collecte="departments/m03-estimation/tests",
    )


def _capturer(racine: Path):
    return lambda: EmpreinteEntrees.capturer(
        {"departments/m03-estimation": racine / "departments/m03-estimation"}
    )


def _hash_environnement_actuel() -> str:
    contenu = json.dumps(sorted(os.environ.items()), separators=(",", ":"))
    return hashlib.sha256(contenu.encode()).hexdigest()


def test_une_preuve_nominale_identique_est_reutilisee_explicitement(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    campagne = CampagneM3()
    appels = []

    def lancer():
        appels.append(1)
        return SimpleNamespace(returncode=0, stdout="10/10 mutations", stderr="")

    spec = _spec()
    capture = _capturer(racine)
    premier = campagne.obtenir_ou_executer(
        spec, capture, lancer, commande=("python", "muter_x.py")
    )
    second = campagne.obtenir_ou_executer(
        spec,
        capture,
        lambda: (_ for _ in ()).throw(AssertionError("ne doit pas relancer")),
        commande=("python", "muter_x.py"),
    )

    assert premier.processus_lance_ici is True
    assert second.processus_lance_ici is False
    assert second.preuve is premier.preuve
    assert second.preuve.stdout == "10/10 mutations"
    assert second.preuve.nettoyage_prouve is True
    assert len(appels) == 1
    assert campagne.nombre_executions == 1
    artefacts = tmp_path / "preuves"
    repertoire_campagne = campagne.ecrire_artefacts(artefacts)
    recu, = repertoire_campagne.glob("*.json")
    contenu = json.loads(recu.read_text())
    assert contenu["commande"] == ["python", "muter_x.py"]
    assert contenu["retour"] == 0
    assert contenu["avant"]["sha256"] == contenu["apres"]["sha256"]
    assert contenu["stdout"] == "10/10 mutations"
    relu = CampagneM3.lire_artefact(recu, spec, capture())
    assert relu["commande"] == ["python", "muter_x.py"]
    contenu["stdout"] = "résultat altéré"
    recu.write_text(json.dumps(contenu))
    try:
        CampagneM3.lire_artefact(recu, spec, capture())
    except AssertionError as erreur:
        assert "intégrité" in str(erreur)
    else:
        raise AssertionError("un reçu altéré a été accepté")


def test_hash_scenario_et_commande_differents_ne_reutilisent_pas_la_preuve(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    source = m3 / "src/outil.py"
    test = m3 / "tests/test_x.py"
    outil = m3 / "tests/muter_x.py"
    source.write_text("valeur = 1\n")
    test.write_text("assert True\n")
    outil.write_text("mutant = 1\n")
    campagne = CampagneM3()
    appels = []

    def lancer():
        appels.append(len(appels) + 1)
        return SimpleNamespace(returncode=0, stdout=str(appels[-1]), stderr="")

    capture = _capturer(racine)
    commande = ("python", "muter_x.py")
    nom = _spec()
    campagne.obtenir_ou_executer(nom, capture, lancer, commande=commande)

    # Un test rouge ne peut jamais être satisfait par l'entrée nominale.
    rouge = _spec(scenario="suite-rouge")
    preuve_rouge = campagne.obtenir_ou_executer(
        rouge, capture, lancer, commande=commande
    ).preuve
    assert preuve_rouge.specification.scenario == "suite-rouge"
    assert preuve_rouge.stdout == "2"
    acces_rouge = campagne.obtenir_ou_executer(
        rouge,
        capture,
        lambda: (_ for _ in ()).throw(AssertionError("preuve rouge déjà capturée")),
        commande=commande,
    )
    assert acces_rouge.processus_lance_ici is False
    assert acces_rouge.preuve is preuve_rouge

    sans_garde = _spec(scenario="module-sans-garde")
    preuve_sans_garde = campagne.obtenir_ou_executer(
        sans_garde, capture, lancer, commande=commande
    ).preuve
    assert preuve_sans_garde.stdout == "3"
    non_compilable = _spec(scenario="mutant-non-compilable")
    preuve_non_compilable = campagne.obtenir_ou_executer(
        non_compilable, capture, lancer, commande=commande
    ).preuve
    assert preuve_non_compilable.stdout == "4"
    assert len({
        nom.cle(capture()),
        rouge.cle(capture()),
        sans_garde.cle(capture()),
        non_compilable.cle(capture()),
    }) == 4

    # Même scénario et mêmes options, mais un octet source différent: cache invalidé.
    source.write_text("valeur = 2\n")
    preuve_source = campagne.obtenir_ou_executer(
        nom, capture, lancer, commande=commande
    ).preuve
    assert preuve_source.stdout == "5"

    # Un mode modifié est une différence d'entrée même si le contenu est identique.
    os.chmod(test, 0o640)
    preuve_mode = campagne.obtenir_ou_executer(
        nom, capture, lancer, commande=commande
    ).preuve
    assert preuve_mode.stdout == "6"

    # Un mutant modifié invalide l'entrée; la sortie de la version précédente est rejetée.
    outil.write_text("mutant = 2\n")
    preuve_mutant = campagne.obtenir_ou_executer(
        nom, capture, lancer, commande=commande
    ).preuve
    assert preuve_mutant.stdout == "7"

    # Les options et argv font partie de la clé, indépendamment des empreintes de fichiers.
    autre_argv = _spec(argv=("muter_x.py", "--mutation=2"))
    preuve_argv = campagne.obtenir_ou_executer(
        autre_argv, capture, lancer, commande=("python", "muter_x.py", "--mutation=2")
    ).preuve
    assert preuve_argv.stdout == "8"

    autre_commande = replace(nom, commande=("python3", "muter_x.py"))
    preuve_commande = campagne.obtenir_ou_executer(
        autre_commande,
        capture,
        lancer,
        commande=("python3", "muter_x.py"),
    ).preuve
    assert preuve_commande.stdout == "9"

    for autre_spec in (
        replace(nom, cwd="{AUTRE_CWD}"),
        replace(nom, python="python 3.13 / pytest 9.2"),
        replace(
            nom,
            environnement_sha256=hashlib.sha256(b"PYTHONPATH=autre").hexdigest(),
        ),
        replace(nom, options_pytest=("-q", "-k", "autre")),
        replace(nom, collecte="tests/test_autre.py"),
    ):
        campagne.obtenir_ou_executer(
            autre_spec, capture, lancer, commande=commande
        )

    assert campagne.nombre_executions == 14
    assert len(appels) == 14


def test_la_commande_reelle_doit_correspondre_a_la_specification(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    campagne = CampagneM3()

    try:
        campagne.obtenir_ou_executer(
            _spec(),
            _capturer(racine),
            lambda: SimpleNamespace(returncode=0, stdout="", stderr=""),
            commande=("python3", "muter_x.py"),
        )
    except AssertionError as erreur:
        assert "diffère" in str(erreur)
    else:
        raise AssertionError("une commande différente a pu réutiliser la preuve")

    assert campagne.nombre_executions == 0


def test_les_captures_entourent_le_launcher_et_un_nettoyage_absent_n_est_pas_reutilise(
    tmp_path,
):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    source = m3 / "src/outil.py"
    source.write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    campagne = CampagneM3()
    appels = []

    def lancer():
        appels.append(True)
        source.write_text(f"valeur = {len(appels) + 1}\n")
        return SimpleNamespace(returncode=1, stdout="trace", stderr="")

    spec = _spec()
    capture = _capturer(racine)
    premiere = campagne.obtenir_ou_executer(
        spec, capture, lancer, commande=spec.commande
    ).preuve
    seconde = campagne.obtenir_ou_executer(
        spec, capture, lancer, commande=spec.commande
    ).preuve

    assert premiere.avant.sha256 != premiere.apres.sha256
    assert premiere.nettoyage_prouve is False
    assert seconde is not premiere
    assert seconde.avant.sha256 != seconde.apres.sha256
    assert campagne.nombre_executions == 2
    assert len(appels) == 2
    assert not campagne._preuves
    artefacts = tmp_path / "preuves-echec-nettoyage"
    repertoire_campagne = campagne.ecrire_artefacts(artefacts)
    recus = sorted(repertoire_campagne.glob("*.json"))
    assert len(recus) == 2
    captures = [json.loads(recu.read_text()) for recu in recus]
    assert all(preuve["nettoyage_prouve"] is False for preuve in captures)
    assert all(preuve["avant"] != preuve["apres"] for preuve in captures)


def test_l_identite_de_cible_d_un_lien_symbolique_est_dans_la_fermeture(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    premiere = racine / "dependance-a.py"
    seconde = racine / "dependance-b.py"
    premiere.write_text("valeur = 1\n")
    seconde.write_text("valeur = 1\n")
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    lien = m3 / "src/dependance.py"
    lien.symlink_to(premiere)
    capture = _capturer(racine)
    sha_avant = capture().sha256
    lien.unlink()
    lien.symlink_to(seconde)

    assert capture().sha256 != sha_avant


def test_la_fermeture_couvre_src_docs_pyproject_conftest_et_voisins(tmp_path):
    racine = tmp_path / "repo"
    departments = racine / "departments"
    m3 = departments / "m03-estimation"
    voisin = departments / "m02-revenue-crm"
    for chemin in (m3 / "src", m3 / "tests", voisin / "src"):
        chemin.mkdir(parents=True)
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    (voisin / "src/contrat.py").write_text("contrat = 1\n")
    for nom in ("src", "docs"):
        dossier = racine / nom
        dossier.mkdir()
        (dossier / "fichier.txt").write_text(nom)
    (racine / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (racine / "conftest.py").write_text("# fixtures\n")
    _installer_fixture_commune_m2(racine)
    def capture():
        return EmpreinteEntrees.capturer(racines_fermeture_m3(racine))

    noms = set(racines_fermeture_m3(racine))
    assert {
        "department:m03-estimation",
        "department:m02-revenue-crm",
        "src",
        "docs",
        "pyproject.toml",
        "conftest.py",
        "fixture:m2_preparation_estimation",
    } <= noms
    sha_avant = capture().sha256
    (voisin / "src/contrat.py").write_text("contrat = 2\n")

    assert capture().sha256 != sha_avant
    sha_apres_voisin = capture().sha256
    fixture = racine / "tests/fixtures/m2_preparation_estimation.py"
    fixture.write_bytes(fixture.read_bytes() + b"\n# drift de fixture fictive\n")
    assert capture().sha256 != sha_apres_voisin, "la dépendance M2 doit invalider la preuve"


def test_un_recu_durable_est_produit_par_un_sous_processus_reel(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    lanceur = m3 / "tests/lanceur_reel.py"
    lanceur.write_text("print('preuve subprocess réelle')\n")
    commande = (sys.executable, "-B", str(lanceur))
    spec = replace(
        _spec(),
        commande=commande,
        argv=commande,
        cwd=str(racine),
        python=sys.version,
        environnement_sha256=_hash_environnement_actuel(),
        options_pytest=(),
        collecte=str(lanceur),
    )
    campagne = CampagneM3()
    capturer = _capturer(racine)
    acces = campagne.obtenir_ou_lancer_commande(spec, capturer)
    assert acces.processus_lance_ici is True
    assert acces.preuve.retour == 0
    assert acces.preuve.stdout.strip() == "preuve subprocess réelle"
    assert acces.preuve.nettoyage_prouve is True
    repertoire_campagne = campagne.ecrire_artefacts(tmp_path / "artefacts")
    recu, = repertoire_campagne.glob("*.json")
    relu = CampagneM3.lire_artefact(recu, spec, capturer())
    assert relu["retour"] == 0
    rejoue = campagne.obtenir_ou_lancer_commande(spec, capturer)
    assert rejoue.processus_lance_ici is False
    assert rejoue.preuve is acces.preuve


def test_un_recu_existant_est_immutable_et_un_conflit_est_refuse(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    campagne = CampagneM3()
    capture = _capturer(racine)

    def lancer_ok():
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    nominal = _spec()
    preuve_nominale = campagne.obtenir_ou_executer(
        nominal, capture, lancer_ok, commande=nominal.commande
    ).preuve
    chemin = tmp_path / "artefacts" / "recu.json"
    preuve_nominale.ecrire(chemin)
    bytes_initiaux = chemin.read_bytes()
    mtime_initial = chemin.stat().st_mtime_ns
    preuve_nominale.ecrire(chemin)
    assert chemin.read_bytes() == bytes_initiaux
    assert chemin.stat().st_mtime_ns == mtime_initial

    rouge = _spec(scenario="suite-rouge")
    preuve_rouge = campagne.obtenir_ou_executer(
        rouge,
        capture,
        lambda: SimpleNamespace(returncode=1, stdout="rouge", stderr=""),
        commande=rouge.commande,
    ).preuve
    with pytest.raises(FileExistsError, match="reçu existant différent"):
        preuve_rouge.ecrire(chemin)
    assert chemin.read_bytes() == bytes_initiaux

    racine_artefacts = tmp_path / "campagnes"
    repertoire_1 = campagne.ecrire_artefacts(racine_artefacts)
    recus_1 = sorted(repertoire_1.glob("*.json"))
    assert len(recus_1) == 2
    bytes_campagne_1 = {recu.name: recu.read_bytes() for recu in recus_1}
    mtimes_campagne_1 = {recu.name: recu.stat().st_mtime_ns for recu in recus_1}
    assert campagne.ecrire_artefacts(racine_artefacts) == repertoire_1
    assert bytes_campagne_1 == {
        recu.name: recu.read_bytes() for recu in sorted(repertoire_1.glob("*.json"))
    }
    assert mtimes_campagne_1 == {
        recu.name: recu.stat().st_mtime_ns
        for recu in sorted(repertoire_1.glob("*.json"))
    }
    campagne_2 = CampagneM3()
    acces_campagne_2 = campagne_2.obtenir_ou_executer(
        nominal, capture, lancer_ok, commande=nominal.commande
    )
    assert acces_campagne_2.processus_lance_ici is True
    repertoire_2 = campagne_2.ecrire_artefacts(racine_artefacts)
    assert repertoire_2 != repertoire_1
    assert len(list(repertoire_2.glob("*.json"))) == 1
    assert bytes_campagne_1 == {
        recu.name: recu.read_bytes() for recu in sorted(repertoire_1.glob("*.json"))
    }


def test_adaptateur_reutilise_une_copie_env_sans_pytest_current_test(
    tmp_path, monkeypatch, request
):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    outils = m3 / "tests/outils_preuve"
    (m3 / "src/m3_estimation").mkdir(parents=True)
    outils.mkdir(parents=True)
    (racine / "src").mkdir()
    (racine / "docs").mkdir()
    (racine / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (racine / "conftest.py").write_text("", encoding="utf-8")
    _installer_fixture_commune_m2(racine)
    outil = outils / "probe_environnement.py"
    outil.write_text(
        "import json, os, pathlib, sys\n"
        "with pathlib.Path(sys.argv[2]).open('a', encoding='utf-8') as f:\n"
        "    f.write('ran\\n')\n"
        "print(json.dumps({'pytest_current_test': os.environ.get('PYTEST_CURRENT_TEST')}))\n",
        encoding="utf-8",
    )
    compteur = tmp_path / "appels.txt"
    campagne = CampagneM3()
    request.addfinalizer(
        lambda: campagne.ecrire_artefacts(tmp_path / "artefacts")
    )

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "consommateur-un::test-a")
    spec_un = specification_outil(
        outil, racine, "nominal", arguments=(str(compteur),)
    )
    premier = executer_preuve(campagne, spec_un, racine)

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "consommateur-deux::test-b")
    spec_deux = specification_outil(
        outil, racine, "nominal", arguments=(str(compteur),)
    )
    second = executer_preuve(campagne, spec_deux, racine)

    assert spec_un.environnement_sha256 == spec_deux.environnement_sha256, (
        "PYTEST_CURRENT_TEST ne doit pas changer la clé de la même invocation"
    )
    assert premier.processus_lance_ici is True
    assert second.processus_lance_ici is False
    assert second.preuve is premier.preuve
    assert json.loads(premier.preuve.stdout)["pytest_current_test"] is None
    assert compteur.read_text(encoding="utf-8").splitlines() == ["ran"]
    assert os.environ["PYTEST_CURRENT_TEST"] == "consommateur-deux::test-b"
    artefacts = campagne.ecrire_artefacts(tmp_path / "artefacts")
    assert len(list(artefacts.glob("*.json"))) == 1


def test_un_recu_durable_est_rejoue_exactement_apres_reprise_du_processus(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    outil = m3 / "tests/outil_recu.py"
    compteur = tmp_path / "compteur.txt"
    outil.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "with Path(sys.argv[1]).open('a') as f: f.write('run\\n')\n"
        "print('sortie originale')\n"
        "print('erreur originale', file=sys.stderr)\n"
        "raise SystemExit(1)\n"
    )
    commande = (sys.executable, str(outil), str(compteur))
    spec = replace(
        _spec(),
        commande=commande,
        argv=commande,
        cwd=str(racine),
        python=sys.version,
        environnement_sha256=_hash_environnement_actuel(),
        options_pytest=(),
        collecte=str(outil),
    )
    dossier = tmp_path / "preuves"
    run_id = "reprise-fixture-01"
    capturer = _capturer(racine)

    premiere_campagne = CampagneM3(
        dossier_artefacts=dossier, identifiant=run_id
    )
    premier = premiere_campagne.obtenir_ou_lancer_commande(spec, capturer)
    assert premier.processus_lance_ici is True
    assert premier.preuve.retour == 1
    assert premier.preuve.stdout.strip() == "sortie originale"
    assert premier.preuve.stderr.strip() == "erreur originale"
    chemin = dossier / run_id / f"{premier.preuve.cle}.json"
    bytes_recu = chemin.read_bytes()

    seconde_campagne = CampagneM3(
        dossier_artefacts=dossier, identifiant=run_id
    )
    second = seconde_campagne.obtenir_ou_lancer_commande(spec, capturer)
    assert second.processus_lance_ici is False
    assert second.preuve.retour == 1
    assert second.preuve.stdout == premier.preuve.stdout
    assert second.preuve.stderr == premier.preuve.stderr
    assert second.preuve.commande == commande
    assert compteur.read_text().splitlines() == ["run"]
    assert chemin.read_bytes() == bytes_recu


def test_un_recu_durable_corrompu_refuse_le_cache_et_ne_lance_pas(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    outil = m3 / "tests/outil_recu.py"
    outil.write_text("print('ok')\n")
    commande = (sys.executable, "-c", "print('ok')")
    spec = replace(
        _spec(),
        commande=commande,
        argv=commande,
        cwd=str(racine),
        python=sys.version,
        environnement_sha256=_hash_environnement_actuel(),
        options_pytest=(),
        collecte=str(outil),
    )
    dossier = tmp_path / "preuves"
    run_id = "reprise-corrompue-01"
    capturer = _capturer(racine)
    premiere_campagne = CampagneM3(dossier_artefacts=dossier, identifiant=run_id)
    premier = premiere_campagne.obtenir_ou_lancer_commande(spec, capturer)
    chemin = dossier / run_id / f"{premier.preuve.cle}.json"
    recu = json.loads(chemin.read_text())
    recu["stdout"] = "falsifie"
    chemin.write_text(json.dumps(recu) + "\n")

    seconde_campagne = CampagneM3(dossier_artefacts=dossier, identifiant=run_id)
    with pytest.raises(AssertionError, match="intégrité"):
        seconde_campagne.obtenir_ou_executer(
            spec,
            capturer,
            lambda: (_ for _ in ()).throw(AssertionError("ne doit pas lancer")),
            commande=commande,
        )


def test_un_environnement_different_ne_reutilise_pas_le_recu(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (m3 / "src/outil.py").write_text("valeur = 1\n")
    (m3 / "tests/test_x.py").write_text("assert True\n")
    outil = m3 / "tests/outil_recu.py"
    outil.write_text("import os\nprint(os.environ['R9_MODE'])\n")
    commande = (sys.executable, str(outil))
    environnement_1 = dict(os.environ, R9_MODE="premier")
    environnement_2 = dict(os.environ, R9_MODE="second")

    def specification(environnement):
        canon = json.dumps(sorted(environnement.items()), separators=(",", ":"))
        return replace(
            _spec(),
            commande=commande,
            argv=commande,
            cwd=str(racine),
            python=sys.version,
            environnement_sha256=hashlib.sha256(canon.encode()).hexdigest(),
            options_pytest=(),
            collecte=str(outil),
        )

    dossier = tmp_path / "preuves"
    run_id = "reprise-environnement-01"
    capturer = _capturer(racine)
    premiere = CampagneM3(dossier_artefacts=dossier, identifiant=run_id)
    acces_1 = premiere.obtenir_ou_lancer_commande(
        specification(environnement_1), capturer, environnement=environnement_1
    )
    seconde = CampagneM3(dossier_artefacts=dossier, identifiant=run_id)
    acces_2 = seconde.obtenir_ou_lancer_commande(
        specification(environnement_2), capturer, environnement=environnement_2
    )
    assert acces_1.processus_lance_ici is True
    assert acces_1.preuve.stdout.strip() == "premier"
    assert acces_2.processus_lance_ici is True
    assert acces_2.preuve.stdout.strip() == "second"
    assert acces_1.preuve.cle != acces_2.preuve.cle
    assert len(list((dossier / run_id).glob("*.json"))) == 2


def test_une_copie_persistante_de_scenario_est_stable_et_son_drift_refuse(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src/m3_estimation").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (racine / "src").mkdir()
    (racine / "docs").mkdir()
    (racine / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (racine / "conftest.py").write_text("")
    _installer_fixture_commune_m2(racine)
    (m3 / "src/m3_estimation/source.py").write_text("valeur = 1\n")
    destination = tmp_path / "run" / "scenario-rouge"

    premiere = EnvironnementMutation(racine, dossier=destination)
    ajout = premiere.dossier_tests / "epreuve.py"
    ajout.write_text("def test_rouge(): assert False\n")
    premiere.sceller()
    chemin_stable = premiere.dossier

    reprise = EnvironnementMutation(racine, dossier=destination)
    assert reprise.dossier == chemin_stable
    assert reprise.dossier_tests.joinpath("epreuve.py").is_file()
    reprise.nettoyer()
    assert destination.is_dir(), "le scénario stable ne doit pas être supprimé au teardown"

    (reprise.dossier_source / "source.py").write_text("valeur = 2\n")
    with pytest.raises(AssertionError, match="copie de scénario persistante modifiée"):
        EnvironnementMutation(racine, dossier=destination)


def test_une_copie_temporaire_n_est_pas_confondue_avec_une_reprise(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src/m3_estimation").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (racine / "src").mkdir()
    (racine / "docs").mkdir()
    (racine / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (racine / "conftest.py").write_text("")
    _installer_fixture_commune_m2(racine)
    source = m3 / "src/m3_estimation/source.py"
    source.write_text("valeur = 1\n")

    environnement = EnvironnementMutation(racine)
    try:
        copie = environnement.cible(source)
        assert copie.read_text() == "valeur = 1\n"
        assert not (environnement.dossier / ".m3-scenario.sha256").exists()
    finally:
        environnement.nettoyer()
    assert not environnement.dossier.exists()


def test_une_reprise_persistante_sans_sceau_est_refusee(tmp_path):
    racine = tmp_path / "repo"
    m3 = racine / "departments/m03-estimation"
    (m3 / "src/m3_estimation").mkdir(parents=True)
    (m3 / "tests").mkdir()
    (racine / "src").mkdir()
    (racine / "docs").mkdir()
    (racine / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (racine / "conftest.py").write_text("")
    _installer_fixture_commune_m2(racine)
    (m3 / "src/m3_estimation/source.py").write_text("valeur = 1\n")
    destination = tmp_path / "run" / "sans-sceau"

    premiere = EnvironnementMutation(racine, dossier=destination)
    assert (destination / ".m3-source.sha256").is_file()
    assert not (destination / ".m3-scenario.sha256").exists()
    with pytest.raises(AssertionError, match="copie de scénario persistante incomplète"):
        EnvironnementMutation(racine, dossier=destination)
    premiere.nettoyer()
