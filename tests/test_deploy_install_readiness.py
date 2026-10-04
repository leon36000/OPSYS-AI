"""R45 : vraie génération/SQLite et Bash ; HTTP/Docker simulés, aucun VPS ni modèle lancé."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import urllib.error
from pathlib import Path

import pytest
from sqlalchemy import text

from opsys import departements, modeles, openclaw, serveur_bootstrap, stockage

RACINE = Path(__file__).resolve().parents[1]
JETON_FICTIF = "bearer-fictif-R45-1234567890ABCDEFGHIJK"
SECRET_FICTIF = "secret-fictif-R45-ne-jamais-afficher"


@pytest.fixture
def configuration(opsys_home, tmp_path, monkeypatch):
    """Les dix départements, leurs vrais outils et les migrations de SQLite sont utilisés."""
    stockage.liberer()
    for nom in list(os.environ):
        if nom.endswith("_API_KEY") or nom.startswith("OPSYS_EMBEDDINGS_"):
            monkeypatch.delenv(nom)
    monkeypatch.delenv("OPSYS_DATABASE_URL", raising=False)
    monkeypatch.delenv("OPSYS_PASSERELLE_URL", raising=False)
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(RACINE / "departments"))
    monkeypatch.setenv("OPSYS_MODE_FOURNISSEUR", "natif")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", JETON_FICTIF)
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "embeddings-fictif")
    monkeypatch.setenv("OPSYS_EMBEDDINGS_LOCAL", "1")
    dossier = tmp_path / "config"
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(dossier))
    stockage.migrer()
    deps = departements.charger_departements()
    serveur_bootstrap.preparer(dossier, "r45.example.test")
    spec = importlib.util.spec_from_file_location("readiness_r45", RACINE / "deploy/readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    appels = []

    class Console200:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def http_double(url, *, timeout):
        assert url in {
            "http://127.0.0.1:8700/connexion", "http://127.0.0.1:9/health/liveliness",
        } and timeout <= 3
        appels.append(url)
        return Console200()

    monkeypatch.setattr(module.urllib.request, "urlopen", http_double)

    def generer(provider="ollama", *, cle=False, mode="natif"):
        conf = {"provider": provider, "model": "modele-fictif", "base_url": "http://127.0.0.1:9/v1"}
        if cle:
            monkeypatch.setenv("R45_MODEL_API_KEY", SECRET_FICTIF)
            conf["api_key_env"] = "R45_MODEL_API_KEY"
        paliers = {palier: dict(conf) for palier in ("local", "rapide", "standard", "fort")}
        modeles.enregistrer_paliers(paliers)
        monkeypatch.setenv("OPSYS_MODE_FOURNISSEUR", mode)
        url_passerelle = None
        if mode == "litellm":
            url_passerelle = "http://127.0.0.1:9"
            monkeypatch.setenv("OPSYS_PASSERELLE_URL", url_passerelle)
            monkeypatch.setenv("LITELLM_MASTER_KEY", SECRET_FICTIF)
            for dep in deps.values():
                monkeypatch.setenv(f"OPSYS_CLE_{dep.code}", SECRET_FICTIF)
        openclaw.generer(deps, dossier, paliers, mode_fournisseur=mode, url_passerelle=url_passerelle)
        return paliers

    yield module, dossier, generer, deps, appels
    stockage.liberer()


@pytest.mark.parametrize("provider", ["ollama", "custom"])
def test_projection_reelle_valide_est_ready(configuration, provider):
    module, _, generer, _, appels = configuration
    generer(provider)
    assert module.main() == 0
    assert appels == ["http://127.0.0.1:8700/connexion"]


def test_projection_litellm_reelle_preservee(configuration):
    module, _, generer, _, appels = configuration
    generer(mode="litellm")
    assert module.main() == 0
    assert appels == ["http://127.0.0.1:9/health/liveliness", "http://127.0.0.1:8700/connexion"]


def test_paliers_absents_avec_schema_et_console_valides_est_attente(configuration):
    module, _, _, _, _ = configuration
    assert module.main() == 3


def test_embeddings_retires_refusent_anciens_fragments(configuration, monkeypatch, capsys):
    module, dossier, generer, deps, _ = configuration
    paliers = generer()
    assert module.main() == 0
    avant = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in dossier.rglob("*.json")}
    monkeypatch.delenv("OPSYS_EMBEDDINGS_URL")
    with pytest.raises(ValueError, match="OPSYS_EMBEDDINGS_URL"):
        openclaw.generer(deps, dossier, paliers)
    assert avant == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in dossier.rglob("*.json")}
    assert module.main() == 3
    assert "OPSYS_EMBEDDINGS_URL" in capsys.readouterr().err


def test_modele_embeddings_absent_est_configuration_en_attente(configuration, monkeypatch):
    module, _, generer, _, _ = configuration
    generer()
    monkeypatch.delenv("OPSYS_EMBEDDINGS_MODELE")
    assert module.main() == 3


@pytest.mark.parametrize("url", ["file:///URL-privee-R45", "http://[hote-invalide-R45"])
def test_url_invalide_prime_sur_modele_absent(configuration, monkeypatch, capsys, url):
    module, _, generer, _, _ = configuration
    generer()
    monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", url)
    monkeypatch.delenv("OPSYS_EMBEDDINGS_MODELE")
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert url not in sorties.out + sorties.err


@pytest.mark.parametrize("exception", [RuntimeError, ValueError])
def test_exception_memoire_inattendue_prime_sur_variables_absentes(configuration, monkeypatch, capsys, exception):
    module, _, generer, _, _ = configuration
    generer()
    monkeypatch.delenv("OPSYS_EMBEDDINGS_URL")

    def panne(environ):
        raise exception(SECRET_FICTIF)

    monkeypatch.setattr(module.openclaw, "_configuration_memoire", panne)
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert SECRET_FICTIF not in sorties.out + sorties.err


def test_yaml_paliers_malforme_prime_sur_embeddings_absents(configuration, monkeypatch):
    module, _, generer, _, _ = configuration
    generer()
    modeles.fichier_paliers().write_text("paliers: [yaml-malforme")
    monkeypatch.delenv("OPSYS_EMBEDDINGS_URL")
    assert module.main() == 1


@pytest.mark.parametrize("nom,valeur", [
    ("OPSYS_EMBEDDINGS_URL", "file:///config-fictive"),
    ("OPSYS_EMBEDDINGS_TAILLE_LOT", "0"),
])
def test_embeddings_invalides_sont_erreur_et_pas_attente(configuration, monkeypatch, nom, valeur):
    module, _, generer, _, _ = configuration
    generer()
    monkeypatch.setenv(nom, valeur)
    assert module.main() == 1


@pytest.mark.parametrize("champ,valeur", [
    ("baseUrl", "http://endpoint-obsolete.example.test/v1"),
    ("models", [{"id": "modele-obsolete", "name": "modele-obsolete"}]),
    ("apiKey", SECRET_FICTIF),
])
def test_catalogue_obsolete_ou_cle_litterale_refuse(configuration, capsys, champ, valeur):
    module, dossier, generer, _, _ = configuration
    generer("ollama")
    fichier = dossier / "opsys/models.json"
    contenu = json.loads(fichier.read_text())
    contenu["providers"]["ollama"][champ] = valeur
    fichier.write_text(json.dumps(contenu))
    assert module.main() == 1
    sorties = capsys.readouterr()
    assert SECRET_FICTIF not in sorties.out + sorties.err


def test_reference_secrete_custom_preservee_et_absence_diagnostiquee(configuration, monkeypatch, capsys):
    module, dossier, generer, _, _ = configuration
    generer("custom", cle=True)
    assert module.main() == 0
    assert SECRET_FICTIF not in (dossier / "opsys/models.json").read_text()
    monkeypatch.delenv("R45_MODEL_API_KEY")
    assert module.main() == 3
    sorties = capsys.readouterr()
    assert "R45_MODEL_API_KEY" in sorties.err
    assert SECRET_FICTIF not in sorties.out + sorties.err


@pytest.mark.parametrize("operation", ["url-changee", "fichier-absent", "json-invalide"])
def test_memoire_perimee_refusee(configuration, monkeypatch, operation):
    module, dossier, generer, _, _ = configuration
    generer()
    fichier = dossier / "opsys/memory.json"
    if operation == "url-changee":
        monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", "http://127.0.0.1:10/v1")
    elif operation == "fichier-absent":
        fichier.unlink()
    else:
        fichier.write_text("{invalide")
    assert module.main() == 1


@pytest.mark.parametrize("erreur", ["console", "revision"])
def test_erreur_runtime_ne_devient_pas_attente(configuration, monkeypatch, erreur):
    module, _, generer, _, _ = configuration
    generer()
    monkeypatch.delenv("OPSYS_EMBEDDINGS_URL")
    if erreur == "console":
        def indisponible(*args, **kwargs):
            raise urllib.error.URLError("console QA indisponible")
        monkeypatch.setattr(module.urllib.request, "urlopen", indisponible)
    else:
        with stockage.transaction() as cnx:
            cnx.execute(text("UPDATE alembic_version SET version_num='revision-inconnue-r45'"))
    assert module.main() == 1


DOCKER_FICTIF = r'''#!/usr/bin/env bash
set -eu
if [ "$1" = inspect ]; then
    cid="${@: -1}"
    case "$cid" in
        cid-opsys) printf '%s\n' "$QA_HEALTH_OPSYS" ;;
        cid-openclaw-gateway) printf '%s\n' "$QA_HEALTH_GATEWAY" ;;
        cid-caddy) printf '%s\n' "$QA_HEALTH_EDGE" ;;
        *) exit 98 ;;
    esac
    exit 0
fi
[ "$1" = compose ] || exit 98
shift
while [ "$#" -gt 0 ]; do
    case "$1" in --env-file|-f|--profile) shift 2 ;; *) break ;; esac
done
printf '%s\n' "$*" >>"$QA_COMMANDES"
case "$1" in
    build) exit "${QA_BUILD_RC:-0}" ;;
    up) exit 0 ;;
    ps) printf 'cid-%s\n' "${@: -1}" ;;
    exec)
        if [ "${@: -1}" = /opt/opsys/deploy/readiness.py ]; then
            exit "$QA_READINESS_RC"
        fi
        exit "${QA_BOOTSTRAP_RC:-0}"
        ;;
    *) exit 98 ;;
esac
'''


def installer_fictif(tmp_path, *, opsys="healthy", gateway="healthy", edge="healthy", readiness=0,
                     bootstrap=0, build=0):
    """Fonctions Compose/wait/main réelles ; seul CLI Docker factice, sleep sans attente."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for nom, corps in {
        "docker": DOCKER_FICTIF,
        "curl": "#!/bin/sh\nexit 98\n",
        "litellm": '#!/bin/sh\nprintf appele >"$QA_LITELLM"\nexit 98\n',
    }.items():
        p = bin_dir / nom
        p.write_text(corps)
        p.chmod(0o755)
    (tmp_path / ".env").write_text("OPSYS_DOMAINE=r45.example.test\n")
    source = (RACINE / "deploy/install.sh").read_text()
    compose = source[source.index("compose() {"):source.index("# -- Vérifications préalables")]
    fonctions = source[source.index("wait_healthy() {"):source.rindex('\nmain "$@"')]
    script = tmp_path / "installer.sh"
    script.write_text('''set -euo pipefail
CORE_READY=0
INSTALL_EN_ATTENTE=0
CODE_EN_ATTENTE=3
COMPOSE_PROFILE=""
log() { printf '[install] %s\\n' "$*"; }
warn() { printf '[install] %s\\n' "$*" >&2; }
die() { printf '[install] ERREUR %s\\n' "$*" >&2; exit 1; }
sleep() { :; }
# Étapes privilégiées volontairement exclues du banc : aucune commande apt/ufw/useradd.
require_root() { :; }
check_os() { :; }
check_resources() { :; }
install_docker() { :; }
create_deploy_user() { :; }
ensure_env() { :; }
setup_firewall() { :; }
setup_fail2ban() { :; }
''' + compose + fonctions + '\nmain\n')
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "SCRIPT_DIR": str(tmp_path), "QA_COMMANDES": str(tmp_path / "commandes.log"),
           "QA_LITELLM": str(tmp_path / "commande-litellm"), "QA_HEALTH_OPSYS": opsys,
           "QA_HEALTH_GATEWAY": gateway, "QA_HEALTH_EDGE": edge, "QA_READINESS_RC": str(readiness),
           "QA_BOOTSTRAP_RC": str(bootstrap), "QA_BUILD_RC": str(build)}
    retour = subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True, timeout=10)
    commandes = (tmp_path / "commandes.log").read_text()
    return retour, commandes


@pytest.mark.parametrize("gateway,edge", [("unhealthy", "healthy"), ("healthy", "unhealthy")])
def test_health_obligatoire_ne_termine_pas_avec_succes(tmp_path, gateway, edge):
    retour, _ = installer_fictif(tmp_path, gateway=gateway, edge=edge)
    assert retour.returncode == 1
    assert "Installation OPSYS terminée." not in retour.stdout


def test_configuration_absente_est_attente_explicite_sans_gateway(tmp_path):
    retour, commandes = installer_fictif(tmp_path, opsys="unhealthy", readiness=3)
    assert retour.returncode == 3
    assert "en attente de configuration" in retour.stdout
    assert "Installation OPSYS terminée." not in retour.stdout
    assert "up -d openclaw-gateway" not in commandes
    assert "exec -T opsys python3 /opt/opsys/deploy/readiness.py" in commandes


@pytest.mark.parametrize("readiness", [0, 1, 125])
def test_opsys_non_sain_hors_absence_configuration_est_erreur(tmp_path, readiness):
    retour, commandes = installer_fictif(tmp_path, opsys="unhealthy", readiness=readiness)
    assert retour.returncode == 1
    assert "up -d openclaw-gateway" not in commandes
    assert "Installation OPSYS terminée." not in retour.stdout


def test_edge_indisponible_ne_devient_pas_attente(tmp_path):
    retour, _ = installer_fictif(tmp_path, opsys="unhealthy", readiness=3, edge="unhealthy")
    assert retour.returncode == 1


@pytest.mark.parametrize("bootstrap,build", [(1, 0), (0, 1)])
def test_echec_bootstrap_ou_build_reste_refuse(tmp_path, bootstrap, build):
    retour, _ = installer_fictif(tmp_path, bootstrap=bootstrap, build=build)
    assert retour.returncode == 1


def test_bilan_reussi_et_texte_ne_lancent_pas_commande(tmp_path):
    retour, commandes = installer_fictif(tmp_path)
    assert retour.returncode == 0
    assert "Installation OPSYS terminée." in retour.stdout
    assert "up -d openclaw-gateway" in commandes
    assert not (tmp_path / "commande-litellm").exists()
