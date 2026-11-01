"""Inventaire exécutable des tours et de leur état de branchement : le script, ses contrôles, sa cohérence avec le
planificateur. Aucune exécution de code de département (lecture de l'arbre syntaxique)."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from opsys.connecteurs_planification import etat, inventaire, planificateur

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "planification" / "inventaire_tours.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("inventaire_tours", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_l_inventaire_est_coherent_avec_le_code_et_les_executeurs(script):
    assert script.verifier() == []


def test_le_script_s_execute_et_dit_ok():
    sortie = subprocess.run([sys.executable, str(SCRIPT), "--verifier"], capture_output=True, text=True, timeout=60)
    assert sortie.returncode == 0 and sortie.stdout.strip() == "OK", sortie.stderr[-500:]
    tableau = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert tableau.returncode == 0
    for decision in ("deja_branche", "brancher_maintenant", "brancher_quand_transport", "ne_jamais_automatiser"):
        assert f"== {decision}" in tableau.stdout
    donnees = json.loads(subprocess.run([sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True,
                                        timeout=60).stdout)
    assert {t["identifiant"] for t in donnees} == {t.identifiant for t in inventaire.TOURS}


def test_chaque_tour_nomme_dans_la_tache_est_inventorie():
    ids = inventaire.par_identifiant()
    attendus = ("m7.tour_ingestion", "m7.tour_veille", "m7.executer_panel", "m7.studio.executer_fond",
                "m10.reindexer_connaissances", "m10.ingerer_source", "m8.construire_entrepot", "m9.rafraichir_lectures",
                "m5.cycle_comptable", "m10.synchroniser_graphe", "retention.courriel", "retention.traces",
                "retention.cles", "sauvegarde.verifier", "peremptions.connaissances", "courriel.synchro",
                "m10.construire_soi")
    assert not [a for a in attendus if a not in ids]


def test_chaque_decision_est_justifiee_et_les_n3_plus_ne_sont_jamais_libres():
    for t in inventaire.TOURS:
        assert len(t.justification) > 30 and len(t.idempotent) > 5, t.identifiant
        if t.n3_ou_plus and t.decision in ("deja_branche", "brancher_maintenant"):
            assert "approbation" in t.niveau or "humain" in t.niveau, t.identifiant
    jamais = {t.identifiant for t in inventaire.TOURS if t.decision == "ne_jamais_automatiser"}
    assert {"m7.executer_panel", "m9.rafraichir_lectures", "m4.purger_retention_gps"} <= jamais
    assert all(t.executeur is None for t in inventaire.TOURS if t.decision not in ("deja_branche",
    "brancher_maintenant"))


def test_la_verification_detecte_un_ecart(script, tmp_path, monkeypatch):
    # une fonction renommée, une décision sans exécuteur, un exécuteur inconnu, un N3 libre : tous signalés
    faux_tour = dataclasses.replace(inventaire.TOURS[0], fonction="fonction_qui_n_existe_pas")
    sans_executeur = dataclasses.replace(inventaire.TOURS[6], executeur=None)
    inconnu = dataclasses.replace(inventaire.TOURS[6], identifiant="x.inconnu", executeur="exec.inconnu")
    n3_libre = dataclasses.replace(inventaire.TOURS[6], identifiant="x.n3", niveau="N3", executeur="m8.entrepot")
    monkeypatch.setattr(inventaire, "TOURS", (faux_tour, sans_executeur, inconnu, n3_libre))
    problemes = "\n".join(script.verifier())
    assert "fonction_qui_n_existe_pas" in problemes and "sans exécuteur" in problemes
    assert "exec.inconnu" in problemes and "sans approbation humaine" in problemes
    assert "aucun tour de l'inventaire ne le justifie" in problemes  # les exécuteurs non cités sont signalés


def test_chaque_executeur_declare_a_une_implementation_et_chaque_irreversible_un_apercu():
    implementations = {e.nom: e for e in planificateur.executeurs_par_defaut()}
    assert set(implementations) == set(etat.NOMS)
    for d in etat.DEFINITIONS:
        e = implementations[d.nom]
        for methode in ("ressources", "cle_bail", "constater", "traiter"):
            assert callable(getattr(e, methode)), (d.nom, methode)
        if d.irreversible:
            assert callable(getattr(e, "apercu", None)), d.nom
        assert d.transport is None or d.transport in etat.TRANSPORTS
        assert 15 <= d.intervalle_defaut_s <= 86400 and len(d.nom) <= 40


def test_un_executeur_irreversible_est_toujours_declare_n3_humain_a_la_premiere_activation():
    for d in etat.DEFINITIONS:
        assert d.irreversible == (d.famille == "retention" and "N3 humain" in d.niveau), d.nom


def test_tout_executeur_qui_appelle_un_fournisseur_a_un_plafond_d_appels_ou_son_propre_quota():
    # les exécuteurs de lecture/génération qui comptent leurs appels portent un plafond par 24 h
    for nom in ("m7.signaux", "m7.veille", "m7.studio.fonds", "m10.connaissances.reindexation"):
        assert etat.definition(nom).plafond_appels_jour
