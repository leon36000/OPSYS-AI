import os
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run-e2e.sh"
# bash résolu en ABSOLU : les tests manipulent PATH pour contrôler la
# découverte de k6 ; un PATH vidé masquerait aussi bash et le test
# échouerait sur FileNotFoundError au lieu de tester le script.
_BASH = shutil.which("bash") or "/usr/bin/bash"


def _env_with_path(path: str) -> dict[str, str]:
    return {**os.environ, "PATH": path, "PYTHON_BIN": sys.executable}


def _make_fake_k6(dirpath: str) -> str:
    """Crée un faux exécutable k6 dans le répertoire donné, retourne son chemin."""
    fake_k6 = os.path.join(dirpath, "k6")
    with open(fake_k6, "w") as f:
        f.write("#!/bin/sh\n")
        f.write('echo "k6 factice : travail utile"\n')
        f.write("exit 0\n")
    os.chmod(fake_k6, 0o755)
    return fake_k6


def test_mode_load_reussit_avec_k6_factice():
    """Prouve que le mode load termine avec succès quand k6 factice est présent.

    Sans le correctif de portée des variables, le trap EXIT échoue avec
    « SERVER_PID: unbound variable » même quand le test de charge a réussi.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_fake_k6(tmpdir)
        new_path = f"{tmpdir}:/usr/bin:/bin"
        env = _env_with_path(new_path)
        completed = subprocess.run(
            [_BASH, str(SCRIPT), "load"],
            capture_output=True, text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        assert completed.returncode == 0, (
            f"Le script aurait dû réussir (rc=0).\n"
            f"stdout: {completed.stdout}\n"
            f"stderr: {completed.stderr}"
        )
        assert "unbound variable" not in completed.stdout
        assert "unbound variable" not in completed.stderr


def _pids_brand_server():
    """PID des processus PYTHON exécutant réellement brand_server.py.

    Deux filtres nécessaires. D'abord ``pgrep -f`` matche l'argv de tout
    processus mentionnant la chaîne, y compris pgrep lui-même et le shell qui
    l'invoque — mesuré : deux faux positifs sans filtrage. On relit donc
    /proc/<pid>/cmdline et on exige à la fois « python » et « brand_server.py ».
    Retourne None si pgrep est absent.
    """
    if not shutil.which("pgrep"):
        return None
    r = subprocess.run(["pgrep", "-f", "brand_server.py"], capture_output=True, text=True)
    reels = set()
    for brut in r.stdout.split():
        if not brut.strip().isdigit():
            continue
        try:
            with open(f"/proc/{brut.strip()}/cmdline", "rb") as f:
                cmdline = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        if "python" in cmdline and "brand_server.py" in cmdline:
            reels.add(brut.strip())
    return reels


def test_aucun_processus_serveur_ne_survit_au_run():
    """Prouve qu'un run n'AJOUTE aucun processus serveur survivant.

    Comparaison DIFFÉRENTIELLE et non absolue : asserter « aucun brand_server.py
    sur la machine » est pollué par tout orphelin préexistant — une exécution
    antérieure du script buggé en laissait justement plusieurs, le trap échouant
    avant de tuer le serveur. On compare donc l'ensemble des PID avant et après :
    le run ne doit en ajouter aucun.
    """
    avant = _pids_brand_server()
    if avant is None:
        pytest.skip("pgrep absent : impossible d'observer les processus")
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_fake_k6(tmpdir)
        env = _env_with_path(f"{tmpdir}:/usr/bin:/bin")
        completed = subprocess.run(
            [_BASH, str(SCRIPT), "load"],
            capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        )
        assert completed.returncode == 0, (
            f"le run doit réussir.\nstdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    survivants = _pids_brand_server() - avant
    assert not survivants, (
        f"le run a laissé {len(survivants)} processus serveur vivant(s) : "
        f"{sorted(survivants)} — le nettoyage n'est pas systématique"
    )


def test_skip_propre_si_k6_absent():
    """Prouve qu'en l'absence de k6, le mode load sort 0 et affiche le SKIP."""
    env_no_k6 = {**os.environ, "PYTHON_BIN": sys.executable}
    # On retire k6 du PATH en utilisant un répertoire vide comme seul chemin.
    with tempfile.TemporaryDirectory() as tmpdir:
        # PATH volontairement dépourvu de k6 mais contenant python3 :
        # le script a besoin de python3 pour choisir un port libre.
        env_no_k6["PATH"] = f"{tmpdir}:/usr/bin:/bin"
        completed = subprocess.run(
            [_BASH, str(SCRIPT), "load"],
            capture_output=True, text=True,
            cwd=REPO_ROOT,
            env=env_no_k6,
        )
        assert completed.returncode == 0, (
            f"Le script doit sortir en 0 en cas d'absence de k6.\n"
            f"stdout: {completed.stdout}\n"
            f"stderr: {completed.stderr}"
        )
        assert "SKIP: k6 absent" in completed.stdout, (
            f"Le message de skip attendu n'a pas été trouvé dans stdout:\n{completed.stdout}"
        )


def test_syntaxe_bash_valide():
    """Prouve que le script passe la vérification syntaxique de bash."""
    completed = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == 0, (
        f"Le script contient une erreur de syntaxe bash.\n"
        f"stderr: {completed.stderr}"
    )

def _ecrire_k6_factice(dirpath, corps):
    """Écrit un k6 factice avec le corps shell donné et le rend exécutable."""
    chemin = os.path.join(dirpath, "k6")
    with open(chemin, "w") as f:
        f.write("#!/bin/sh\n" + corps)
    os.chmod(chemin, 0o755)
    return chemin


def test_echec_k6_rend_20_et_nettoie():
    """Prouve que l'ÉCHEC de k6 rend le code 20 ET ne laisse aucun serveur.

    Chemin d'erreur non couvert par les autres tests, qui utilisent tous un k6
    qui réussit : sans appel de arreter_serveur sur ce chemin, un échec de charge
    laisserait un serveur vivant.
    """
    avant = _pids_brand_server()
    with tempfile.TemporaryDirectory() as tmpdir:
        _ecrire_k6_factice(tmpdir, 'echo "k6 factice : echec simule" >&2\nexit 1\n')
        env = _env_with_path(f"{tmpdir}:/usr/bin:/bin")
        completed = subprocess.run(
            [_BASH, str(SCRIPT), "load"],
            capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        )
        assert completed.returncode == 20, (
            "un échec de k6 doit rendre 20 (et non 1 par un trap cassé).\n"
            f"rc={completed.returncode}\nstdout: {completed.stdout}\n"
            f"stderr: {completed.stderr}"
        )
        assert "unbound variable" not in completed.stderr, (
            f"le trap ne doit pas échouer sur une variable non liée : {completed.stderr}"
        )
    if avant is not None:
        survivants = _pids_brand_server() - avant
        assert not survivants, (
            f"un échec de k6 a laissé {len(survivants)} serveur(s) vivant(s) : "
            f"{sorted(survivants)}"
        )


def test_trap_nettoie_sur_signal_term():
    """Prouve que le TRAP nettoie quand le script est INTERROMPU par SIGTERM.

    C'est le seul chemin où le trap est indispensable : sur les chemins nominal
    et d'erreur, arreter_serveur est appelée explicitement.

    DÉTERMINISME — le point délicat. bash n'exécute un trap qu'APRÈS la fin de la
    commande de premier plan en cours. Avec un k6 factice qui dort longtemps, le
    trap différé et l'expiration du timeout côté Python arrivent au même instant :
    c'est une COURSE, et une première version de ce test la gagnait par chance
    (mesuré : 30,1 s d'attente, SIGKILL, puis zéro survivant — le trap avait
    gagné de justesse). On donne donc au k6 factice une durée COURTE et au
    communicate une marge LARGE : SIGTERM arrive pendant le sommeil, k6 rend la
    main vite, bash exécute alors le trap, et tout se termine bien avant le
    timeout. Le test assert d'ailleurs que la durée reste petite, pour qu'un
    retour au comportement de course soit détecté.
    """
    avant = _pids_brand_server()
    if avant is None:
        pytest.skip("pgrep absent : impossible d'observer les processus")
    _SOMMEIL_K6 = 2
    _MARGE_COMMUNICATE = 60
    with tempfile.TemporaryDirectory() as tmpdir:
        _ecrire_k6_factice(tmpdir, f"sleep {_SOMMEIL_K6}\n")
        env = _env_with_path(f"{tmpdir}:/usr/bin:/bin")
        proc = subprocess.Popen(
            [_BASH, str(SCRIPT), "load"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=REPO_ROOT, env=env, text=True,
        )
        # Attendre que le serveur soit effectivement lancé avant d'interrompre,
        # sinon le trap n'aurait rien à nettoyer et le test ne prouverait rien.
        lance = False
        for _ in range(100):
            time.sleep(0.1)
            courant = _pids_brand_server()
            if courant is not None and courant - avant:
                lance = True
                break
        assert lance, (
            "pré-condition : le serveur doit avoir démarré avant l'interruption, "
            "sinon le trap n'a rien à nettoyer et le test ne prouve rien"
        )
        debut = time.monotonic()
        proc.terminate()
        try:
            proc.communicate(timeout=_MARGE_COMMUNICATE)
            tue_de_force = False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            tue_de_force = True
        duree = time.monotonic() - debut
        assert not tue_de_force, (
            f"le script n'a pas rendu la main en {_MARGE_COMMUNICATE}s après SIGTERM : "
            "il a fallu un SIGKILL, donc le trap n'a PAS pu s'exécuter et ce test "
            "ne prouverait rien"
        )
        assert proc.returncode == 143, (
            f"SIGTERM doit être HONORÉ (sortie 143 = 128+15), reçu {proc.returncode} : "
            "un handler qui nettoie sans sortir laisse le script reprendre son cours"
        )
        assert duree < _SOMMEIL_K6 + 5, (
            f"le script a mis {duree:.1f}s à sortir après SIGTERM alors que le k6 "
            f"factice ne dort que {_SOMMEIL_K6}s : le signal n'est pas honoré "
            "immédiatement (comportement de course mesuré à 30 s)"
        )
    for _ in range(50):
        if not (_pids_brand_server() - avant):
            break
        time.sleep(0.1)
    survivants = _pids_brand_server() - avant
    assert not survivants, (
        f"après SIGTERM, {len(survivants)} serveur(s) survivent : {sorted(survivants)} "
        "— le trap ne nettoie pas"
    )
