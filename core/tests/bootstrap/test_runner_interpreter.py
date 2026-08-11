"""Tests pour core/scripts/run_tests.py (C02-003).

Couvre les 4 cas RED obligatoires de tasks/C02-003.md :
  1. refuser /usr/bin/python3 différent de l'environnement
  2. propager le code retour réel
  3. timeout = échec
  4. préserver signaux et warnings de threads

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core — le runner de tests est HERMÉTIQUE : il
n'utilise JAMAIS un interpréteur ambiant/système qui pourrait différer de
celui qui orchestre réellement (sys.executable), et il ne masque JAMAIS
un échec réel (code retour altéré, timeout avalé, avertissement de thread
ignoré) derrière un succès apparent.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_tests import resolve_test_interpreter, run_test_slice  # noqa: E402


# ---------------------------------------------------------------------------
# Cas RED 1 — refuser /usr/bin/python3 différent de l'environnement
# ---------------------------------------------------------------------------


def test_rendre_le_runner_de_tests_herm_tique_1(monkeypatch):
    """Si sys.executable est indisponible (chaîne vide — cas documenté de
    la stdlib pour certains contextes embarqués), le runner doit REFUSER
    explicitement plutôt que de retomber silencieusement sur un chemin
    système en dur (/usr/bin/python3) qui pourrait être un interpréteur
    différent de celui qui orchestre réellement — jamais un repli
    implicite non hermétique."""
    monkeypatch.setattr(sys, "executable", "")
    with pytest_raises_hermetique():
        resolve_test_interpreter()


def test_resolve_retourne_reellement_sys_executable(monkeypatch):
    """Preuve directe (pas un mock du résultat) : resolve_test_interpreter()
    retourne l'interpréteur RÉEL du processus courant, jamais un chemin
    système en dur — vérifié en comparant au sys.executable RÉEL de ce
    processus (garanti présent, contrairement au cas RED 1)."""
    interpreter = resolve_test_interpreter()
    assert interpreter == Path(sys.executable).resolve()
    assert interpreter.is_file()


def pytest_raises_hermetique():
    import pytest

    return pytest.raises(Exception)


# ---------------------------------------------------------------------------
# Cas RED 2 — propager le code retour réel
# ---------------------------------------------------------------------------


def test_rendre_le_runner_de_tests_herm_tique_2(tmp_path):
    """Le code retour d'un test qui ÉCHOUE réellement doit être propagé
    tel quel — jamais normalisé à 1, jamais avalé en 0."""
    fichier_echec = tmp_path / "test_echec_reel.py"
    fichier_echec.write_text("def test_qui_echoue():\n    assert False\n", encoding="utf-8")

    rc = run_test_slice([str(fichier_echec)])
    assert rc != 0
    # pytest retourne précisément 1 pour « au moins un test a échoué » —
    # preuve que le code n'est pas ré-inventé par le runner.
    assert rc == 1


def test_code_retour_zero_propage_sur_succes_reel(tmp_path):
    """Symétrique : un test qui RÉUSSIT réellement doit produire rc=0,
    jamais un code non nul inventé par erreur de propagation."""
    fichier_succes = tmp_path / "test_succes_reel.py"
    fichier_succes.write_text("def test_qui_reussit():\n    assert True\n", encoding="utf-8")

    rc = run_test_slice([str(fichier_succes)])
    assert rc == 0


# ---------------------------------------------------------------------------
# Cas RED 3 — timeout = échec
# ---------------------------------------------------------------------------


def test_rendre_le_runner_de_tests_herm_tique_3(tmp_path):
    """Un test qui dépasse le timeau alloué doit produire un ÉCHEC
    explicite (code retour non nul) — jamais un succès silencieux, jamais
    un hang indéfini du processus appelant."""
    fichier_lent = tmp_path / "test_trop_lent.py"
    fichier_lent.write_text(
        "import time\n\n\ndef test_qui_depasse_le_timeout():\n    time.sleep(30)\n",
        encoding="utf-8",
    )

    rc = run_test_slice([str(fichier_lent)], timeout=1)
    assert rc != 0


# ---------------------------------------------------------------------------
# Cas RED 4 — préserver signaux et warnings de threads
# ---------------------------------------------------------------------------


def test_rendre_le_runner_de_tests_herm_tique_4(tmp_path):
    """Un avertissement PytestUnhandledThreadExceptionWarning (exception
    levée dans un thread, jamais remontée au thread principal — invisible
    par défaut) doit faire ÉCHOUER la suite, jamais rester un simple
    avertissement imprimé et ignoré. Preuve DIRECTE (pas mockée) : un vrai
    thread qui lève une exception non gérée pendant l'exécution pytest."""
    fichier_thread = tmp_path / "test_thread_leve_une_exception.py"
    fichier_thread.write_text(
        "import threading\n"
        "import time\n"
        "\n"
        "\n"
        "def test_thread_non_gere():\n"
        "    def casse():\n"
        "        raise RuntimeError('exception non gérée dans un thread')\n"
        "\n"
        "    t = threading.Thread(target=casse)\n"
        "    t.start()\n"
        "    t.join()\n"
        "    time.sleep(0.2)\n",
        encoding="utf-8",
    )

    rc = run_test_slice([str(fichier_thread)])
    assert rc != 0


def test_run_test_slice_propage_argv_sans_les_alterer(tmp_path):
    """Les arguments passés à run_test_slice (chemins de test, options
    pytest) doivent atteindre pytest inchangés — preuve directe en passant
    -k pour ne sélectionner qu'UN SEUL des deux tests d'un fichier."""
    fichier = tmp_path / "test_selection.py"
    fichier.write_text(
        "def test_a_selectionner():\n    assert True\n\n\ndef test_a_ignorer():\n    assert False\n",
        encoding="utf-8",
    )

    rc = run_test_slice([str(fichier), "-k", "test_a_selectionner"])
    assert rc == 0


def test_resolve_test_interpreter_est_appele_par_run_test_slice(monkeypatch, tmp_path):
    """Garde structurelle : run_test_slice DOIT passer par
    resolve_test_interpreter() pour obtenir son interpréteur — jamais un
    `sys.executable` ou un chemin en dur invoqué directement en parallèle,
    ce qui rendrait le cas RED 1 sans effet sur le chemin réellement
    emprunté par run_test_slice."""
    import run_tests

    appels = []
    original = run_tests.resolve_test_interpreter

    def espion():
        appels.append(True)
        return original()

    monkeypatch.setattr(run_tests, "resolve_test_interpreter", espion)

    fichier = tmp_path / "test_trivial.py"
    fichier.write_text("def test_trivial():\n    assert True\n", encoding="utf-8")
    run_test_slice([str(fichier)])

    assert appels, "run_test_slice n'a jamais appelé resolve_test_interpreter()"
