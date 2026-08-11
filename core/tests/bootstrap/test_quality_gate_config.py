"""Tests pour core/scripts/run_static_checks.py (C02-004).

Couvre les 3 cas RED obligatoires de tasks/C02-004.md :
  1. mypy/pyright absent ne peut pas devenir pass
  2. les erreurs historiques (baseline) restent enregistrées
  3. un check required non exécuté bloque

ÉCART SOURCÉ AU SPEC, DOCUMENTÉ EN CLAIR (jamais résolu en silence) : le
spec de tâche nomme « les 374 erreurs historiques » dans son cas RED 2.
Recherche exhaustive (agent dédié + mesure directe) : ce chiffre n'a AUCUNE
provenance traçable dans le pack (absent de sources/audit/ANALYSE-
FORENSIQUE-COMPLETE.md, des 2 autres sources citées, des issues d'audit
liées ISS-CAND-CA08-0001/0003, et de tout autre fichier du pack) ; ce n'est
ni un compte mypy, ni pyright, ni ruff (425 réel), ni radon (211 réel).
Une mesure RÉELLE de mypy sur core/ donne 2 erreurs (core/src/auth/
totp.py:22, core/src/auth/admin_gate.py:109) ; mypy sur l'arbre complet
(Modules M/ inclus) ne peut même pas ACHEVER un passage (collisions de
noms de modules dupliqués entre M-modules, structurel, hors périmètre de
cette tâche — aucune modification M1-M10). Le MÉCANISME testé ici (baseline
enregistrée, jamais masquée, nouveaux écarts détectés au-delà) est fidèle
à l'intention du spec (« introduire baseline de dette sans masquer les
nouveaux écarts ») — mais les tests ci-dessous utilisent des baselines et
sorties d'outils SYNTHÉTIQUES et contrôlées (jamais 374, jamais le 2 réel
mesuré non plus) pour rester déterministes et indépendants de l'état du
dépôt. Le compte RÉEL (2, sourcé) alimente séparément core/quality-
gates.toml, l'artefact produit — jamais un nombre inventé.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_static_checks import GateOutcome, QualityGate, evaluer_gate, evaluer_matrice  # noqa: E402


def _ecrire_faux_outil(chemin: Path, nb_erreurs: int) -> None:
    """Écrit un faux outil de type mypy : produit exactement nb_erreurs
    lignes au format ``fichier.py:N: error: message`` sur stdout, jamais
    un vrai outil réel — déterministe, indépendant de l'environnement."""
    lignes = "\n".join(f"faux_module.py:{i}: error: erreur synthétique {i}" for i in range(nb_erreurs))
    chemin.write_text(
        "import sys\n"
        f"print({lignes!r})\n"
        "sys.exit(1 if " + str(nb_erreurs) + " else 0)\n",
        encoding="utf-8",
    )
    chemin.chmod(0o755)


# ---------------------------------------------------------------------------
# Cas RED 1 — mypy/pyright absent ne peut pas devenir pass
# ---------------------------------------------------------------------------


def test_d_finir_la_matrice_qualit_statique_et_typage_1(monkeypatch):
    """Un outil de type-checking introuvable dans PATH ne doit JAMAIS
    produire un résultat « pass » silencieux — la gate devient bloquée
    (si required=True), executed=False, jamais un succès inventé.
    subprocess.run est AUSSI mocké en SUCCÈS (jamais laissé s'exécuter
    réellement) : sans cela, un vrai binaire absent échouerait de toute
    façon par FileNotFoundError — capturé par le except générique — et le
    test passerait par COÏNCIDENCE même si la garde which() était retirée
    (mesuré : c'est exactement ce qui se produit, cf. mutation_proof.py M1)."""
    import shutil as shutil_module

    import run_static_checks

    monkeypatch.setattr(shutil_module, "which", lambda nom: None)

    appels = []

    def _run_qui_ne_doit_jamais_etre_appele(*a, **k):
        appels.append((a, k))

        class _FauxCompletedProcess:
            stdout = ""
            stderr = ""

        return _FauxCompletedProcess()

    monkeypatch.setattr(run_static_checks.subprocess, "run", _run_qui_ne_doit_jamais_etre_appele)

    gate = QualityGate(name="mypy-absent", argv=["mypy-introuvable-xyz"], required=True, scope=["core/"])
    resultat = evaluer_gate(gate, baseline={})

    assert appels == [], "subprocess.run ne doit JAMAIS être invoqué pour un outil non résolu par which()"
    assert isinstance(resultat, GateOutcome)
    assert resultat.executed is False
    assert resultat.blocked is True, "GARDE RETIRÉE : outil absent + required=True doit bloquer, jamais passer"


def test_outil_absent_mais_non_required_ne_bloque_pas(monkeypatch):
    """Contrôle : un outil absent sur une gate NON required (advisory) ne
    doit pas faire échouer toute la matrice — seul le champ `required`
    décide du blocage, jamais une confusion entre les deux."""
    import shutil as shutil_module

    monkeypatch.setattr(shutil_module, "which", lambda nom: None)

    gate = QualityGate(name="advisory-absent", argv=["outil-optionnel-xyz"], required=False, scope=["core/"])
    resultat = evaluer_gate(gate, baseline={})
    assert resultat.executed is False
    assert resultat.blocked is False


# ---------------------------------------------------------------------------
# Cas RED 2 — les erreurs historiques (baseline) restent enregistrées
# ---------------------------------------------------------------------------


def test_d_finir_la_matrice_qualit_statique_et_typage_2(tmp_path):
    """Une baseline de dette CONNUE (ex. 5 erreurs historiques) ne doit
    JAMAIS être masquée — le compte de baseline est TOUJOURS reflété dans
    le résultat, que la gate bloque ou non. Un run qui retrouve EXACTEMENT
    le compte de baseline (aucune régression) ne bloque pas une gate
    required, mais la baseline reste ENREGISTRÉE dans le résultat, jamais
    silencieusement remise à zéro."""
    faux_outil = tmp_path / "faux_mypy.py"
    _ecrire_faux_outil(faux_outil, nb_erreurs=5)

    gate = QualityGate(name="type-check-synthetique", argv=[sys.executable, str(faux_outil)], required=True, scope=["core/"])
    resultat = evaluer_gate(gate, baseline={"type-check-synthetique": 5})

    assert resultat.executed is True
    assert resultat.baseline_count == 5, "GARDE RETIRÉE : la baseline historique doit être enregistrée dans le résultat"
    assert resultat.error_count == 5
    assert resultat.new_error_count == 0
    assert resultat.blocked is False, "aucune RÉGRESSION (5 erreurs = baseline exacte) ne doit bloquer"


def test_nouvelle_erreur_au_dela_de_la_baseline_bloque(tmp_path):
    """Symétrique et central : si le run ACTUEL trouve PLUS d'erreurs que
    la baseline enregistrée, les erreurs au-delà de la baseline sont des
    RÉGRESSIONS NOUVELLES — jamais masquées par le fait qu'une partie du
    total était déjà connue. La baseline ne doit jamais devenir un permis
    d'empirer silencieusement."""
    faux_outil = tmp_path / "faux_mypy.py"
    _ecrire_faux_outil(faux_outil, nb_erreurs=7)

    gate = QualityGate(name="type-check-synthetique", argv=[sys.executable, str(faux_outil)], required=True, scope=["core/"])
    resultat = evaluer_gate(gate, baseline={"type-check-synthetique": 5})

    assert resultat.baseline_count == 5
    assert resultat.error_count == 7
    assert resultat.new_error_count == 2, "GARDE RETIRÉE : 2 erreurs au-delà de la baseline doivent être détectées nommément"
    assert resultat.blocked is True, "GARDE RETIRÉE : une régression au-delà de la baseline doit bloquer une gate required"


def test_baseline_absente_du_dictionnaire_vaut_zero_jamais_une_exception(tmp_path):
    """Une gate SANS entrée de baseline (jamais mesurée avant) doit être
    traitée comme baseline=0 — TOUTE erreur trouvée devient alors
    « nouvelle », jamais une KeyError qui ferait planter l'évaluation."""
    faux_outil = tmp_path / "faux_mypy.py"
    _ecrire_faux_outil(faux_outil, nb_erreurs=3)

    gate = QualityGate(name="jamais-mesuree-avant", argv=[sys.executable, str(faux_outil)], required=True, scope=["core/"])
    resultat = evaluer_gate(gate, baseline={})

    assert resultat.baseline_count == 0
    assert resultat.new_error_count == 3
    assert resultat.blocked is True


# ---------------------------------------------------------------------------
# Cas RED 3 — un check required non exécuté bloque
# ---------------------------------------------------------------------------


def test_d_finir_la_matrice_qualit_statique_et_typage_3(tmp_path):
    """Une gate required dont l'exécution ÉCHOUE (timeout, crash du
    sous-processus) doit bloquer TOUTE la matrice — jamais un résultat
    partiel traité comme un succès."""
    script_qui_plante = tmp_path / "outil_qui_plante.py"
    script_qui_plante.write_text("import sys\nsys.exit(127)\n", encoding="utf-8")

    # argv pointant vers un exécutable qui n'existe PAS du tout (jamais
    # résolu par shutil.which) simule une exécution qui ne peut pas avoir
    # lieu — le cas le plus direct d'un « required non exécuté ».
    gate_absente = QualityGate(name="required-introuvable", argv=["outil-totalement-absent-xyz"], required=True, scope=["core/"])
    gate_ok = QualityGate(name="ok", argv=[sys.executable, "-c", "pass"], required=True, scope=["core/"])

    ok, resultats = evaluer_matrice([gate_ok, gate_absente], baseline={})

    assert ok is False, "GARDE RETIRÉE : une SEULE gate required non exécutée doit bloquer TOUTE la matrice"
    par_nom = {r.name: r for r in resultats}
    assert par_nom["required-introuvable"].blocked is True
    assert par_nom["required-introuvable"].executed is False


def test_matrice_ok_quand_toutes_les_gates_required_passent(tmp_path):
    """Contrôle symétrique : si toutes les gates required s'exécutent et
    ne dépassent pas leur baseline, la matrice entière est OK — jamais un
    faux blocage sur un état par ailleurs sain."""
    gate_ok1 = QualityGate(name="ok1", argv=[sys.executable, "-c", "pass"], required=True, scope=["core/"])
    gate_ok2 = QualityGate(name="ok2", argv=[sys.executable, "-c", "pass"], required=False, scope=["core/"])

    ok, resultats = evaluer_matrice([gate_ok1, gate_ok2], baseline={})
    assert ok is True
    assert all(not r.blocked for r in resultats)


def test_gate_qui_timeout_est_bloquee_jamais_une_exception_brute(tmp_path):
    """Un sous-processus qui dépasse le timeout imparti ne doit jamais
    faire s'échapper subprocess.TimeoutExpired — converti en blocker
    explicite, comme une exécution qui échoue."""
    script_lent = tmp_path / "outil_lent.py"
    script_lent.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    gate = QualityGate(name="lent", argv=[sys.executable, str(script_lent)], required=True, scope=["core/"])
    resultat = evaluer_gate(gate, baseline={}, timeout=1)

    assert resultat.executed is False
    assert resultat.blocked is True


# ---------------------------------------------------------------------------
# Robustesse structurelle
# ---------------------------------------------------------------------------


def test_quality_gate_et_gate_outcome_sont_geles():
    """QualityGate et GateOutcome sont immuables — une configuration de
    gate ou un résultat ne doivent jamais pouvoir être réécrits après
    coup pour fabriquer une conformité."""
    import pytest

    gate = QualityGate(name="x", argv=["y"], required=True, scope=["core/"])
    with pytest.raises(Exception):
        gate.required = False

    resultat = GateOutcome(
        name="x", executed=True, error_count=0, baseline_count=0,
        new_error_count=0, blocked=False, detail="",
    )
    with pytest.raises(Exception):
        resultat.blocked = True
