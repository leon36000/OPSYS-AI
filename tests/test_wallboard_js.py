"""Le script des wallboards exercé sous Node avec un faux DOM (aucun navigateur : le niveau « B » n'est PAS atteint).

Prouve la logique du script servi : mise à jour par `textContent` seulement (le faux DOM jette si `innerHTML` est
touché),
flux SSE avec reconnexion, repli sur interrogation sans EventSource, perte de connexion DITE (tuiles marquées,
bannière), pause
qui coupe flux et minuteries, reprise. Ce que cela ne prouve pas : le rendu réel, le focus, les lecteurs d'écran, le
cadencement
des minuteries d'un vrai navigateur.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from opsys.console import wallboards_ressources

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")

HARNAIS = Path(__file__).parent / "fixtures" / "wallboard_harnais.cjs"


@pytest.fixture(scope="module")
def resultats(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("js")
    (dossier / "wb.js").write_text(wallboards_ressources.JS, encoding="utf-8")
    sortie = subprocess.run(["node", str(HARNAIS), str(dossier / "wb.js")], capture_output=True, text=True, timeout=60)
    assert sortie.returncode == 0, sortie.stdout + sortie.stderr
    return json.loads(sortie.stdout)


def test_la_syntaxe_du_script_est_valide(tmp_path):
    chemin = tmp_path / "wb.js"
    chemin.write_text(wallboards_ressources.JS, encoding="utf-8")
    assert subprocess.run(["node", "--check", str(chemin)], capture_output=True).returncode == 0


def test_le_script_n_utilise_jamais_de_balisage_ni_d_evaluation():
    source = wallboards_ressources.JS
    for interdit in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        'setTimeout("',
    ):
        assert interdit not in source, interdit


def test_une_valeur_hostile_reste_du_texte(resultats):
    assert resultats["texte_hostile"] == "<img src=x onerror=alert(1)>"
    assert resultats["banniere_enfants"] == [["p", "<script>x</script>"]]
    assert resultats["detail"] == "Dernier fait il y a 2 h 05 min" and resultats["maj"].startswith(
        "Mis à jour : 2026-10-30"
    )
    assert resultats["classes_t2"] == [
        "etat-indetermine",
        "fraicheur-perime",
        "tuile",
    ]  # l'état périmé se lit à la classe
    assert resultats["id_hostile_ok"] is True


def test_le_flux_met_a_jour_se_ferme_a_la_fin_et_se_reconnecte(resultats):
    assert resultats["flux_url"] == "/api/wb/flux" and resultats["flux_credentials"] is True
    assert resultats["apres_instantane"] == "20 leads" and resultats["connexion"] == "Connecté (flux)"
    assert resultats["flux_ferme_apres_fin"] is True and resultats["reconnexion_planifiee"] is True


def test_sans_eventsource_le_script_interroge_a_l_intervalle(resultats):
    assert resultats["repli_planifie"] is True and resultats["repli_valeur"] == "20 leads"


def test_la_perte_de_connexion_est_dite_et_les_valeurs_ne_se_donnent_pas_pour_fraiches(resultats):
    assert resultats["avant_perte"] is False and resultats["apres_perte"] is True
    assert resultats["banniere_perte"] == [
        "Connexion perdue : les valeurs affichées ne sont plus rafraîchies. Ne vous y fiez pas."
    ]
    assert resultats["statut_connexion"] == "Connexion perdue" and resultats["retablie"] is True


def test_la_pause_coupe_le_flux_et_n_alarme_pas_puis_la_reprise_rouvre(resultats):
    assert resultats["pause_flux_ferme"] is True and resultats["pause_aria"] == "true"
    assert resultats["pause_texte"] == "Reprendre le rafraîchissement" and resultats["pause_sans_alarme"] is True
    assert resultats["reprise_aria"] == "false" and resultats["reprise_nouveau_flux"] is True
