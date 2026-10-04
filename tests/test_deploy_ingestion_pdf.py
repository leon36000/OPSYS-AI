"""Installation PDF opt-in : shell réel, outils factices et clés entièrement fictives."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from opsys import fusion_csv, fusion_pdf, stockage

RACINE = Path(__file__).resolve().parents[1]
SONDE = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"xref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
    b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n110\n%%EOF\n"
)
REPONSE_SONDE = {"ok": False, "code": "PDF_PAGES_BORNEES"}


def _runs_dockerfile():
    lignes = iter((RACINE / "deploy/Dockerfile").read_text().splitlines())
    blocs = []
    for ligne in lignes:
        if not ligne.startswith("RUN "):
            continue
        morceaux = [ligne[4:]]
        while morceaux[-1].rstrip().endswith("\\"):
            morceaux[-1] = morceaux[-1].rstrip()[:-1]
            morceaux.append(next(lignes))
        blocs.append(re.sub(r"^(?:--mount=\S+\s+)+", "", " ".join(morceaux)))
    return blocs


@pytest.fixture
def shell_build(tmp_path):
    """Exécute seulement les RUN apt/pip avec des remplaçants, jamais Docker/apt/pip réels."""
    outils = tmp_path / "outils"
    outils.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    for nom in ("requirements-runtime.lock.txt", "requirements-ingestion-pdf.lock.txt"):
        (source / nom).write_bytes((RACINE / nom).read_bytes())
    journal = tmp_path / "commandes.jsonl"
    script_factice = (
        f"#!{sys.executable}\n"
        "import json,os,sys\nfrom pathlib import Path\n"
        "nom=Path(sys.argv[0]).name\n"
        "with open(os.environ['QA_COMMANDES'],'a') as f: "
        "f.write(json.dumps([nom,*sys.argv[1:]])+'\\n')\n"
        "if nom=='python3' and sys.argv[1:3]==['-m','venv']:\n"
        " p=Path(sys.argv[3])/'bin'/'python';p.parent.mkdir(parents=True)\n"
        " p.write_text(Path(sys.argv[0]).read_text());p.chmod(0o700)\n"
    )
    for nom in ("apt-get", "rm", "python3"):
        cible = outils / nom
        cible.write_text(script_factice)
        cible.chmod(0o700)

    def executer(stage, mode, proxy=False):
        blocs = _runs_dockerfile()
        marqueur = "apt-get install" if stage == "apt" else "requirements-runtime.lock.txt"
        bloc = next(b for b in blocs if marqueur in b)
        venv = tmp_path / "venv"
        ca = tmp_path / "proxy-ca-fictif"
        if proxy:
            ca.write_text("certificat de fixture, jamais utilisé par un client réel")
        bloc = bloc.replace("/opt/opsys-venv", str(venv)).replace("/opt/opsys", str(source))
        bloc = bloc.replace("/run/secrets/proxy_ca", str(ca))
        bloc = bloc.replace("/var/lib/apt/lists", str(tmp_path / "apt-lists"))
        env = {
            "PATH": str(outils) + os.pathsep + os.defpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "QA_COMMANDES": str(journal), "OPSYS_INGESTION_PDF": mode,
        }
        retour = subprocess.run(["/bin/sh", "-ec", bloc], env=env, capture_output=True, text=True, timeout=5)
        commandes = [json.loads(ligne) for ligne in journal.read_text().splitlines()] if journal.exists() else []
        return retour, commandes, source

    return executer


@pytest.mark.parametrize("mode,paquets", [("0", ["libpq5"]), ("1", ["libpq5", "bubblewrap"])])
def test_paquets_systeme_opt_in(shell_build, mode, paquets):
    retour, commandes, _ = shell_build("apt", mode)
    assert retour.returncode == 0, retour.stderr
    installation = next(c for c in commandes if c[:2] == ["apt-get", "install"])
    assert installation[4:] == paquets


@pytest.mark.parametrize("mode", ["", "2", "true"])
def test_mode_build_invalide_refuse_avant_apt(shell_build, mode):
    retour, commandes, _ = shell_build("apt", mode)
    assert retour.returncode != 0
    assert commandes == []


@pytest.mark.parametrize("mode,lock", [("0", "requirements-runtime.lock.txt"),
                                        ("1", "requirements-ingestion-pdf.lock.txt")])
@pytest.mark.parametrize("proxy", [False, True])
def test_lock_selection_et_hashes_dans_les_deux_branches(shell_build, mode, lock, proxy):
    retour, commandes, source = shell_build("pip", mode, proxy)
    assert retour.returncode == 0, retour.stderr
    pip = [c for c in commandes if c[1:4] == ["-m", "pip", "install"]]
    assert len(pip) == 2
    assert "--require-hashes" in pip[0]
    assert pip[0][pip[0].index("-r") + 1] == str(source / lock)
    assert "--no-deps" in pip[1] and "--no-build-isolation" in pip[1]
    assert pip[1][pip[1].index("-e") + 1] == str(source)


def test_mode_build_invalide_refuse_avant_pip(shell_build):
    retour, commandes, _ = shell_build("pip", "2")
    assert retour.returncode != 0
    assert commandes == []


def test_overlay_opsys_seul_et_secret_exterieur():
    fichier = RACINE / "deploy/docker-compose.ingestion-pdf.yml"
    assert fichier.is_file(), "overlay PDF absent"
    profil = yaml.safe_load(fichier.read_text())
    assert set(profil) == {"services"}
    assert set(profil["services"]) == {"opsys"}
    service = profil["services"]["opsys"]
    assert service["image"] != "opsys:local"
    assert service["build"]["args"] == {"OPSYS_INGESTION_PDF": "1"}
    assert service["env_file"] == [
        "${OPSYS_INGESTION_ENV_FILE:?OPSYS_INGESTION_ENV_FILE doit pointer vers un fichier privé externe}"
    ]
    assert "environment" not in service and "volumes" not in service and "ports" not in service
    assert "privileged" not in service and "cap_add" not in service and "security_opt" not in service
    assert service["healthcheck"]["test"] == ["CMD", "python3", "/opt/opsys/deploy/readiness_pdf.py"]
    assert service["healthcheck"]["timeout"] == "30s"


@pytest.fixture
def preflight(monkeypatch):
    chemin = RACINE / "deploy/readiness_pdf.py"
    assert chemin.is_file(), "préflight PDF absent"
    base = types.SimpleNamespace(main=lambda: 0)
    monkeypatch.setitem(sys.modules, "readiness", base)
    spec = importlib.util.spec_from_file_location("readiness_pdf_fictive", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv(stockage.ENV_URL, "sqlite:///:memory:")
    monkeypatch.delenv(fusion_csv.ENV_REFERENCE_CLE, raising=False)
    monkeypatch.setenv(fusion_csv.ENV_CLE, base64.b64encode(b"f" * 32).decode())
    appels = []

    def worker(source):
        appels.append(source)
        return dict(REPONSE_SONDE)

    monkeypatch.setattr(module.fusion_pdf, "_extraire_isole", worker)
    return module, base, appels


def test_sonde_reutilise_worker_exact_et_ne_mutile_pas_env(preflight, monkeypatch):
    module, _, appels = preflight
    monkeypatch.setenv(fusion_csv.ENV_REFERENCE_CLE, "OPSYS_CLE_FICTIVE_V2")
    monkeypatch.setenv("OPSYS_CLE_FICTIVE_V2", base64.b64encode(b"v" * 32).decode())
    avant = dict(os.environ)
    assert module.main() == 0
    assert appels == [SONDE]
    assert dict(os.environ) == avant


def test_cle_absente_est_attente_uniquement_apres_sonde_valide(preflight, monkeypatch, capsys):
    module, _, appels = preflight
    monkeypatch.delenv(fusion_csv.ENV_CLE)
    assert module.main() == 3
    assert appels == [SONDE]
    assert "clé externe absente" in capsys.readouterr().err


@pytest.mark.parametrize("valeur", ["PAS_BASE64_CLE_FICTIVE", base64.b64encode(b"x" * 31).decode(), " "])
def test_cle_invalide_erreur_sans_valeur(preflight, monkeypatch, capsys, valeur):
    module, _, _ = preflight
    monkeypatch.setenv(fusion_csv.ENV_CLE, valeur)
    assert module.main() == 1
    sorties = capsys.readouterr()
    if valeur.strip():
        assert valeur not in sorties.out + sorties.err


def test_reference_invalide_refuse_sans_valeur(preflight, monkeypatch, capsys):
    module, _, _ = preflight
    valeur = "reference-secrete-fictive"
    monkeypatch.setenv(fusion_csv.ENV_REFERENCE_CLE, valeur)
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert valeur not in sorties.out + sorties.err


def test_chiffrement_absent_prime_sur_cle_absente(preflight, monkeypatch, capsys):
    module, _, _ = preflight
    monkeypatch.delenv(fusion_csv.ENV_CLE)

    def refus():
        raise fusion_csv.FusionErreur("CHIFFREMENT_INDISPONIBLE", "DETAIL_SECRET_FICTIF", 503)

    monkeypatch.setattr(module.fusion_csv, "_aesgcm", refus)
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert "DETAIL_SECRET_FICTIF" not in sorties.out + sorties.err


def test_plateforme_non_linux_refuse_avant_worker(preflight, monkeypatch):
    module, _, appels = preflight
    monkeypatch.setattr(module.sys, "platform", "darwin")
    assert module.main() == 1
    assert appels == []


def test_sqlite_par_defaut_sans_creation_de_base(preflight, monkeypatch):
    module, _, appels = preflight
    monkeypatch.delenv(stockage.ENV_URL)
    assert module.main() == 0
    assert appels == [SONDE]


@pytest.mark.parametrize("url", ["postgresql://fictif:SECRET_FICTIF@127.0.0.1:9/qa", "URL_INVALIDE_SECRET_FICTIF"])
def test_backend_non_qualifie_prime_sur_cle_absente(preflight, monkeypatch, capsys, url):
    module, _, appels = preflight
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.delenv(fusion_csv.ENV_CLE)
    assert module.main() == 1
    assert appels == []
    sorties = capsys.readouterr()
    assert url not in sorties.out + sorties.err and "SECRET_FICTIF" not in sorties.out + sorties.err


@pytest.mark.parametrize("code", ["PDF_ISOLATION_INDISPONIBLE", "PDF_TIMEOUT", "PDF_LIMITES_INDISPONIBLES"])
def test_echec_worker_prime_sur_configuration_absente(preflight, monkeypatch, capsys, code):
    module, base, _ = preflight
    base.main = lambda: 3
    monkeypatch.delenv(fusion_csv.ENV_CLE)

    def refus(_):
        raise fusion_pdf.FusionPDFErreur(code, "DETAIL_SECRET_FICTIF", 503)

    monkeypatch.setattr(module.fusion_pdf, "_extraire_isole", refus)
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert code in sorties.err and "DETAIL_SECRET_FICTIF" not in sorties.out + sorties.err


@pytest.mark.parametrize("reponse", [
    {"ok": False, "code": "PDF_DEPENDANCE_INDISPONIBLE"},
    {"ok": False, "code": "PDF_MALFORME"},
    {"ok": True, "resultat": {"contenu": "SECRET_FICTIF"}},
    {"ok": 0, "code": "PDF_PAGES_BORNEES"},
])
def test_reponse_worker_inattendue_refuse_sans_faux_vert(preflight, monkeypatch, capsys, reponse):
    module, _, _ = preflight
    monkeypatch.setattr(module.fusion_pdf, "_extraire_isole", lambda _: reponse)
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert "SECRET_FICTIF" not in sorties.out + sorties.err


@pytest.mark.parametrize("rc_base,rc_pdf,attendu", [(0, 0, 0), (3, 0, 3), (0, 3, 3),
                                                    (1, 3, 1), (3, 1, 1), (125, 0, 1)])
def test_combinaison_readiness_erreur_prioritaire(preflight, monkeypatch, rc_base, rc_pdf, attendu):
    module, base, _ = preflight
    base.main = lambda: rc_base
    monkeypatch.setattr(module, "verifier_pdf", lambda: rc_pdf)
    assert module.main() == attendu


def test_exception_runtime_readiness_sans_detail_secret(preflight, capsys):
    module, base, _ = preflight

    def echec():
        raise RuntimeError("SECRET_FICTIF")

    base.main = echec
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert "SECRET_FICTIF" not in sorties.out + sorties.err


def test_fixture_sonde_worker_reel_local_sans_qualification_namespace():
    """Contrôle négatif autonome du worker sur 233 octets fixes ; aucun conteneur ni bwrap."""
    retour = subprocess.run(
        [sys.executable, str(RACINE / "src/opsys/fusion_pdf_worker.py")], input=SONDE,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=5,
    )
    assert retour.returncode == 0
    assert retour.stderr == b""
    assert json.loads(retour.stdout) == REPONSE_SONDE
