"""Raccord PDF natif : fichiers privés/clés fictives, CLI et installateur avec worker/outils doubles."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

from opsys import fusion_csv, fusion_pdf, stockage

RACINE = Path(__file__).resolve().parents[1]
CLE_V1 = base64.b64encode(b"a" * 32).decode()
CLE_V2 = base64.b64encode(b"b" * 32).decode()
REF_V1 = "OPSYS_CLE_INGESTION_FICTIVE_V1"
REF_V2 = "OPSYS_CLE_INGESTION_FICTIVE_V2"
ENV_FILE = "OPSYS_INGESTION_ENV_FILE"
ENV_HISTORY = "OPSYS_INGESTION_CLES_HISTORIQUES"


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    for nom in [ENV_FILE, ENV_HISTORY, fusion_csv.ENV_CLE, fusion_csv.ENV_REFERENCE_CLE, REF_V1, REF_V2]:
        monkeypatch.delenv(nom, raising=False)


@pytest.fixture
def fichier(tmp_path, monkeypatch):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    path = parent / "ingestion.env"
    path.write_text(f"{fusion_csv.ENV_REFERENCE_CLE}={REF_V2}\n{ENV_HISTORY}={REF_V1}\n"
                    f"{REF_V1}={CLE_V1}\n{REF_V2}={CLE_V2}\n")
    path.chmod(0o600)
    monkeypatch.setenv(ENV_FILE, str(path))
    return path


def test_reference_actuelle_et_historique_sans_export_env(fichier):
    avant = dict(os.environ)
    assert fusion_csv._reference_cle() == REF_V2
    assert fusion_csv._cle(REF_V2) == b"b" * 32
    assert fusion_csv._cle(REF_V1) == b"a" * 32
    assert dict(os.environ) == avant


@pytest.mark.parametrize("modification", ["mode", "parent", "symlink", "directory", "relative", "owner", "huge"])
def test_fichier_non_prive_refuse_sans_secret(fichier, monkeypatch, modification):
    if modification == "mode":
        fichier.chmod(0o644)
    elif modification == "parent":
        fichier.parent.chmod(0o755)
    elif modification == "symlink":
        lien = fichier.with_name("lien.env")
        lien.symlink_to(fichier)
        monkeypatch.setenv(ENV_FILE, str(lien))
    elif modification == "directory":
        monkeypatch.setenv(ENV_FILE, str(fichier.parent))
    elif modification == "relative":
        monkeypatch.setenv(ENV_FILE, "private/ingestion.env")
    elif modification == "owner":
        monkeypatch.setattr(fusion_csv.os, "geteuid", lambda: os.getuid() + 1)
    else:
        fichier.write_bytes(b"#" * 8193)
    with pytest.raises(fusion_csv.FusionErreur) as error:
        fusion_csv._reference_cle()
    assert CLE_V1 not in str(error.value) and CLE_V2 not in str(error.value)


@pytest.mark.parametrize("texte", [
    "OPENAI_API_KEY=SECRET_FICTIF\n",
    f"{fusion_csv.ENV_REFERENCE_CLE}=OPENCLAW_GATEWAY_TOKEN\nOPENCLAW_GATEWAY_TOKEN={CLE_V1}\n",
    f"{fusion_csv.ENV_REFERENCE_CLE}={REF_V1}\n{REF_V1}={CLE_V1}\n{REF_V2}={CLE_V2}\n",
    f"{fusion_csv.ENV_CLE}={CLE_V1}\n{fusion_csv.ENV_CLE}={CLE_V2}\n",
    f"{fusion_csv.ENV_CLE}=CLE_INVALIDE_FICTIVE\n",
    f"{fusion_csv.ENV_CLE}={base64.b64encode(b'x' * 31).decode()}\n",
    f"{ENV_HISTORY}={REF_V1},{REF_V1}\n",
    f"{ENV_HISTORY}={REF_V1}\n",
    "ligne_sans_affectation\n",
])
def test_format_refs_et_cles_etrangeres_refuses(fichier, texte):
    fichier.write_text(texte)
    with pytest.raises(fusion_csv.FusionErreur) as error:
        fusion_csv._reference_cle()
    assert "SECRET_FICTIF" not in str(error.value) and CLE_V1 not in str(error.value)


def test_reference_non_declaree_ne_lit_pas_env_etranger(fichier, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", CLE_V1)
    with pytest.raises(fusion_csv.FusionErreur):
        fusion_csv._cle("OPENAI_API_KEY")


def test_conflit_env_fichier_refuse_sans_rotation(fichier, monkeypatch):
    initial = fichier.read_bytes()
    monkeypatch.setenv(REF_V2, CLE_V1)
    with pytest.raises(fusion_csv.FusionErreur):
        fusion_csv._cle(REF_V2)
    assert fichier.read_bytes() == initial


def test_remplacement_pendant_lecture_refuse(fichier, monkeypatch):
    original = os.read
    cible_inode = fichier.stat().st_ino
    change = False

    def lire(fd, taille):
        nonlocal change
        resultat = original(fd, taille)
        if not change and os.fstat(fd).st_ino == cible_inode:
            change = True
            autre = fichier.with_name("replacement.env")
            autre.write_bytes(fichier.read_bytes())
            autre.chmod(0o600)
            autre.replace(fichier)
        return resultat

    monkeypatch.setattr(fusion_csv.os, "read", lire)
    with pytest.raises(fusion_csv.FusionErreur):
        fusion_csv._reference_cle()
    assert change


def test_cle_env_historique_sans_optin_inchange(monkeypatch):
    monkeypatch.setenv(fusion_csv.ENV_REFERENCE_CLE, "ANCIENNE_REFERENCE_FICTIVE")
    monkeypatch.setenv("ANCIENNE_REFERENCE_FICTIVE", CLE_V1)
    assert fusion_csv._reference_cle() == "ANCIENNE_REFERENCE_FICTIVE"
    assert fusion_csv._cle("ANCIENNE_REFERENCE_FICTIVE") == b"a" * 32


@pytest.fixture
def gate(monkeypatch):
    base = types.SimpleNamespace(main=lambda: 0)
    monkeypatch.setitem(sys.modules, "readiness", base)
    spec = importlib.util.spec_from_file_location("readiness_pdf_natif_fictif", RACINE / "deploy/readiness_pdf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv(stockage.ENV_URL, "sqlite:///:memory:")
    appels = []

    def worker(source):
        appels.append(source)
        return {"ok": False, "code": "PDF_PAGES_BORNEES"}

    monkeypatch.setattr(module.fusion_pdf, "_extraire_isole", worker)
    return module, base, appels


def test_pdf_seul_n_appelle_pas_readiness_compose(gate, fichier):
    module, base, appels = gate
    base.main = lambda: pytest.fail("gate Compose interdit au mode natif")
    assert module.main(["--pdf-only"]) == 0
    assert len(appels) == 1 and len(appels[0]) == 233


def test_cli_inconnue_refuse_avant_worker(gate, capsys):
    module, _, appels = gate
    with pytest.raises(SystemExit) as error:
        module.main(["--pdf-only", "--secret=CANARY_FICTIF"])
    assert error.value.code == 2 and appels == []
    assert "CANARY_FICTIF" not in capsys.readouterr().err


def test_fichier_absent_pending_uniquement_apres_worker(gate, fichier):
    module, _, appels = gate
    fichier.unlink()
    assert module.main(["--pdf-only"]) == 3 and len(appels) == 1


def test_refus_worker_prime_sur_fichier_absent(gate, fichier, monkeypatch, capsys):
    module, _, _ = gate
    fichier.unlink()

    def refuse(_):
        raise fusion_pdf.FusionPDFErreur("PDF_ISOLATION_INDISPONIBLE", "SECRET_FICTIF", 503)

    monkeypatch.setattr(module.fusion_pdf, "_extraire_isole", refuse)
    assert module.main(["--pdf-only"]) == 1
    assert "SECRET_FICTIF" not in capsys.readouterr().err


def test_melange_file_absent_cle_env_ne_devient_pas_pending(gate, fichier, monkeypatch):
    module, _, _ = gate
    fichier.unlink()
    monkeypatch.setenv(fusion_csv.ENV_CLE, "INVALIDE_FICTIF")
    assert module.main(["--pdf-only"]) == 1


@pytest.fixture
def bac_pdf(tmp_path):
    spec = importlib.util.spec_from_file_location("faux_install_pdf", RACINE / "tests/test_installateur_scripts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bac = module.Bac(tmp_path)
    # Dépôt sans git : aucune mutation git ; seules les surfaces attendues sont fictives.
    (bac.depot / "core").mkdir(parents=True)
    (bac.depot / "core/openclaw.mjs").write_text("// faux\n")
    (bac.depot / "core/node-version.mjs").write_text("// faux\n")
    (bac.depot / "core/package.json").write_text(json.dumps({"packageManager": f"pnpm@{module.PNPM}"}))
    (bac.depot / "pyproject.toml").write_text("[project]\nname='faux-opsys'\n")
    (bac.depot / "departments").mkdir()
    (bac.depot / "deploy").mkdir()
    for nom in ("readiness.py", "readiness_pdf.py"):
        (bac.depot / "deploy" / nom).write_bytes((RACINE / "deploy" / nom).read_bytes())
    for nom, texte in [("id", "#!/bin/sh\necho ${FAUX_UID:-1000}\n"),
                       ("uname", "#!/bin/sh\necho ${FAUX_SYSTEME:-Linux}\n"),
                       ("bwrap", "#!/bin/sh\nexit 99\n")]:
        path = bac.faux / nom
        path.write_text(texte)
        path.chmod(0o755)
    wrapper = tmp_path / "python-double"
    wrapper.write_text(f"#!{sys.executable}\n" + r'''
import os,sys,runpy,json
from pathlib import Path
if len(sys.argv)>2 and sys.argv[1]=='-c' and 'opsys_pdf_metadata' in sys.argv[2]:
    phase,path=sys.argv[3:5]
    cible=Path(path)
    injection=os.environ.get('FAUX_JSON','')
    if phase=='check' and injection=='structure':
        cible.parent.mkdir(parents=True,exist_ok=True)
        cible.write_text('{"env":["CANARY_FICTIF"]}')
        Path(os.environ['FAUX_JSON_SNAPSHOT']).write_bytes(cible.read_bytes())
    elif phase=='write' and injection:
        original_replace=os.replace
        original_fsync=os.fsync
        Path(os.environ['FAUX_JSON_SNAPSHOT']).write_bytes(cible.read_bytes())
        def remplacer(src,dst):
            if Path(src).name.startswith('.metier.json.pdf-') and injection=='replace':
                raise OSError('CANARY_FICTIF')
            return original_replace(src,dst)
        def fsync(fd):
            if injection=='fsync' and Path('/proc/self/fd/'+str(fd)).resolve().name.startswith('.metier.json.pdf-'):
                raise OSError('CANARY_FICTIF')
            original_fsync(fd)
            if injection=='writer' and Path('/proc/self/fd/'+str(fd)).resolve().name.startswith('.metier.json.pdf-'):
                contenu=cible.read_text()+'\n'
                cible.write_text(contenu)
                Path(os.environ['FAUX_JSON_SNAPSHOT']).write_bytes(cible.read_bytes())
        os.replace=remplacer
        os.fsync=fsync
    sys.argv=sys.argv[2:]
    exec(compile(sys.argv[0],'<configuration PDF fictive>','exec'))
    raise SystemExit(0)
if len(sys.argv)>1 and sys.argv[1].endswith('/readiness_pdf.py'):
    if os.environ.get('FAUX_PDF_RC'):
        print('diagnostic PDF fictif',file=sys.stderr)
        raise SystemExit(int(os.environ['FAUX_PDF_RC']))
    sys.path.insert(0,os.path.dirname(sys.argv[1]))
    from opsys import fusion_pdf
    fusion_pdf._extraire_isole=lambda _: {'ok':False,'code':'PDF_PAGES_BORNEES'}
    sys.argv=sys.argv[1:]
    runpy.run_path(sys.argv[0],run_name='__main__')
else:
    os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
''')
    wrapper.chmod(0o755)
    bac.env_supplementaire.update(FAUX_PYTHON=str(wrapper), PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(tmp_path))
    bac.preparer_decisions()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    fichier = private / "ingestion.env"
    fichier.write_text(f"{fusion_csv.ENV_CLE}={CLE_V1}\n")
    fichier.chmod(0o600)
    return bac, fichier


def test_install_pdf_optin_persistant_desactivation_et_path_seul(bac_pdf):
    bac, fichier = bac_pdf
    first = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier)})
    assert first.returncode == 0, first.stdout + first.stderr
    for resultat in [bac.installer(), bac.installer("--sans-ingestion-pdf")]:
        assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    syncs = [x for x in bac.appels() if x.startswith("uv sync")]
    assert len(syncs) == 6
    assert all("--extra ingestion-pdf" in x for x in syncs[:4])
    assert all("ingestion-pdf" not in x for x in syncs[4:])
    config = json.loads((bac.etat_core / "opsys/metier.json").read_text())
    assert ENV_FILE not in config["env"]
    assert fichier.read_text() == f"{fusion_csv.ENV_CLE}={CLE_V1}\n"
    for p in [bac.etat_core / ".env", bac.logiciel / "installation.env", bac.logiciel / "journaux/installation.log",
              bac.etat_core / "opsys/metier.json"]:
        assert CLE_V1 not in p.read_text()
    assert not list((bac.etat_core / "opsys").glob(".metier.json.pdf-*"))


@pytest.mark.parametrize("rc", [1, 3])
def test_install_pdf_propage_gate_rc_sans_faux_succes(bac_pdf, rc):
    bac, fichier = bac_pdf
    result = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier)}, FAUX_PDF_RC=str(rc))
    assert result.returncode == rc, result.stdout + result.stderr
    assert not any("gateway install" in x for x in bac.appels())
    assert CLE_V1 not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["root", "macos", "bwrap", "path_without_optin", "flags_conflict"])
def test_install_pdf_refuse_prerequis_avant_sync(bac_pdf, failure):
    bac, fichier = bac_pdf
    args = ["--avec-ingestion-pdf"]
    env = {ENV_FILE: str(fichier)}
    if failure == "root":
        env["FAUX_UID"] = "0"
    elif failure == "macos":
        env["FAUX_SYSTEME"] = "Darwin"
    elif failure == "bwrap":
        (bac.faux / "bwrap").unlink()
        (bac.faux / "bash").symlink_to("/usr/bin/bash")
        env["chemin_path"] = str(bac.faux)
    elif failure == "path_without_optin":
        args = []
    else:
        args.append("--sans-ingestion-pdf")
    result = bac.installer(*args, **env)
    assert result.returncode == 1
    assert not any(x.startswith("uv sync") for x in bac.appels())


def test_install_json_atomic_preserve_et_refuse_structure(bac_pdf):
    bac, fichier = bac_pdf
    first = bac.installer()
    assert first.returncode == 0, first.stdout + first.stderr
    path = bac.etat_core / "opsys/metier.json"
    data = json.loads(path.read_text())
    data["env"]["OPSYS_NON_SECRET_FICTIF"] = "conserver"
    path.write_text(json.dumps(data))
    result = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier)})
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(path.read_text())
    assert data["env"][ENV_FILE] == str(fichier)
    assert data["env"]["OPSYS_NON_SECRET_FICTIF"] == "conserver"
    assert CLE_V1 not in path.read_text()
    assert not list(path.parent.glob(".metier.json.pdf-*"))


@pytest.mark.parametrize("injection", ["structure", "replace", "fsync", "writer"])
def test_install_json_atomic_refuse_et_preserve_writer_independant(bac_pdf, injection):
    bac, fichier = bac_pdf
    snapshot = bac.racine / "metadata-before-failure.json"
    result = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier)},
                           FAUX_JSON=injection, FAUX_JSON_SNAPSHOT=str(snapshot))
    assert result.returncode == 1, result.stdout + result.stderr
    path = bac.etat_core / "opsys/metier.json"
    assert path.read_bytes() == snapshot.read_bytes()
    assert not list(path.parent.glob(".metier.json.pdf-*"))
    assert "CANARY_FICTIF" not in result.stdout + result.stderr
    assert not any("gateway install" in x for x in bac.appels())


def test_fichier_supprime_pendant_lecture_ne_devient_pas_absent(fichier, monkeypatch):
    original = os.read
    cible_inode = fichier.stat().st_ino

    def lire(fd, taille):
        resultat = original(fd, taille)
        if fichier.exists() and os.fstat(fd).st_ino == cible_inode:
            fichier.unlink()
        return resultat

    monkeypatch.setattr(fusion_csv.os, "read", lire)
    with pytest.raises(fusion_csv.FusionErreur):
        fusion_csv._reference_cle()


def test_fichier_optin_hors_linux_refuse(fichier, monkeypatch):
    monkeypatch.setattr(fusion_csv.sys, "platform", "darwin")
    with pytest.raises(fusion_csv.FusionErreur):
        fusion_csv._reference_cle()


def test_install_refuse_cle_globale_avant_core(bac_pdf):
    bac, fichier = bac_pdf
    result = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier), fusion_csv.ENV_CLE: CLE_V1})
    assert result.returncode == 1
    assert CLE_V1 not in result.stdout + result.stderr
    assert not any(x.startswith("uv sync") or x.startswith("openclaw ") for x in bac.appels())


def test_install_pending_absence_cle_persistante(bac_pdf):
    bac, fichier = bac_pdf
    fichier.unlink()
    result = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier)})
    assert result.returncode == 3, result.stdout + result.stderr
    config = json.loads((bac.etat_core / "opsys/metier.json").read_text())
    assert config["env"][ENV_FILE] == str(fichier)
    assert not fichier.exists()
    assert "INGESTION_PDF=1" in (bac.logiciel / "installation.env").read_text()


def test_cli_reelle_pdf_seul_sans_docker_et_sans_worker_reel(bac_pdf):
    bac, fichier = bac_pdf
    env = {**bac.env(), ENV_FILE: str(fichier), stockage.ENV_URL: "sqlite:///:memory:"}
    result = subprocess.run([env["FAUX_PYTHON"], str(RACINE / "deploy/readiness_pdf.py"), "--pdf-only"],
                            env=env, capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert bac.appels() == []
    assert CLE_V1 not in result.stdout + result.stderr


def test_cipher_ancien_conserve_avec_reference_historique(fichier, monkeypatch):
    source = b"fixture historique fictive"
    lot = {"lot_id": "lot-fictif", "source_sha256": "0" * 64, "version_format": fusion_csv.VERSION_FORMAT}
    with monkeypatch.context() as ancien:
        ancien.delenv(ENV_FILE)
        ancien.setenv(REF_V1, CLE_V1)
        nonce, chiffre, _ = fusion_csv._chiffrer(fusion_csv._cle(REF_V1), lot["lot_id"],
                                               lot["source_sha256"], "source", source)
    fichier_avant = fichier.read_bytes()
    assert fusion_csv._dechiffrer(fusion_csv._cle(REF_V1), lot, "source", nonce, chiffre) == source
    assert fichier.read_bytes() == fichier_avant


@pytest.mark.parametrize("rc_worker", [0, 3])
def test_install_echec_journal_prime_sur_succes_ou_attente(bac_pdf, rc_worker):
    bac, fichier = bac_pdf
    tee = bac.faux / "tee"
    tee.write_text("#!/bin/sh\n/bin/cat >/dev/null\nexit 1\n")
    tee.chmod(0o755)
    result = bac.installer("--avec-ingestion-pdf", **{ENV_FILE: str(fichier)}, FAUX_PDF_RC=str(rc_worker))
    assert result.returncode == 1, result.stdout + result.stderr
    assert not any("gateway install" in x for x in bac.appels())
    assert CLE_V1 not in result.stdout + result.stderr


def test_cle_privee_dans_venv_refuse_avant_os_open(monkeypatch):
    # Fuite discriminante : fichier valide appartenant au compte courant, dans le vrai venv monté RO.
    with tempfile.TemporaryDirectory(prefix=".opsys-native-key-qa-", dir=sys.prefix) as dossier:
        path = Path(dossier) / "ingestion.env"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as sortie:
            sortie.write(f"{fusion_csv.ENV_CLE}={CLE_V1}\n")
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert path.stat().st_mode & 0o777 == 0o600 and path.stat().st_uid == os.geteuid()
        monkeypatch.setenv(ENV_FILE, str(path))
        original = os.open
        appels = []

        def observer(nom, *args, **kwargs):
            if Path(nom) == path:
                appels.append(True)
            return original(nom, *args, **kwargs)

        monkeypatch.setattr(fusion_csv.os, "open", observer)
        with pytest.raises(fusion_csv.FusionErreur):
            fusion_csv._cle(fusion_csv._reference_cle())
        assert appels == []


@pytest.mark.parametrize("zone", ["prefix", "usr", "lib", "worker"])
def test_cle_refuse_geometrie_partagee_usr_lib_worker_sans_lecture(fichier, monkeypatch, zone):
    usr, prefixes, worker, bibliotheques = fusion_pdf._geometrie_lecture_isolee()
    if zone == "prefix":
        prefixes = prefixes | {fichier.parent}
    elif zone == "usr":
        usr = fichier.parent
    elif zone == "lib":
        bibliotheques = (*bibliotheques, (fichier.parent, fichier.parent, False))
    else:
        worker = fichier
    monkeypatch.setattr(fusion_pdf, "_geometrie_lecture_isolee", lambda: (usr, prefixes, worker, bibliotheques))

    def interdit(*args, **kwargs):
        pytest.fail("le fichier exposé ne doit jamais être ouvert")

    monkeypatch.setattr(fusion_csv.os, "open", interdit)
    with pytest.raises(fusion_csv.FusionErreur):
        fusion_csv._reference_cle()


def test_commande_reutilise_geometrie_sans_spawn(monkeypatch):
    geometrie = fusion_pdf._geometrie_lecture_isolee()
    appels = []

    def observer():
        appels.append(True)
        return geometrie

    monkeypatch.setattr(fusion_pdf, "_geometrie_lecture_isolee", observer)
    monkeypatch.setattr(fusion_pdf.shutil, "which", lambda _: "/bwrap-fictif-jamais-execute")
    monkeypatch.setattr(fusion_pdf.subprocess, "Popen", lambda *a, **kw: pytest.fail("spawn interdit"))
    commande = fusion_pdf._commande_isolee()
    assert appels == [True] and "--unshare-all" in commande and "--clearenv" in commande
    usr, prefixes, worker, bibliotheques = geometrie
    assert commande[commande.index(str(worker)) - 1:commande.index(str(worker)) + 2] == [
        "--ro-bind", str(worker), "/worker.py"]
    for prefixe in prefixes | {usr} | {d for d, c, lien in bibliotheques if not lien and d == c}:
        if prefixe != usr and prefixe.is_relative_to(usr):
            continue
        assert ["--ro-bind", str(prefixe), str(prefixe)] in [commande[i:i + 3] for i in range(len(commande) - 2)]
