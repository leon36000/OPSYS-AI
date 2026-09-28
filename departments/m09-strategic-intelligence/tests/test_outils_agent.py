"""Capacités d'agent de M9 : contrat des outils et chaîne d'état consolidé composée."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m9_strategic_intelligence.outils import etat_consolide, lire_etat_consolide, outils

from opsys.departements import lire_manifeste
from opsys.outils import executer


def _snapshot(module_source, horodatage, valeurs):
    return {"module_source": module_source, "horodatage": horodatage, "valeurs": valeurs}


def _rapport_complet(champs):
    return {cle: "valeur" for cle in champs}


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m9_etat_consolide"
    assert all(nom.startswith("m9_") for nom in noms)


def test_etat_consolide_snapshot_valide_ecrit_et_retourne_l_etat():
    reponse = etat_consolide(_snapshot("M-nominal", "2026-01-04T00:00:00Z", {"a": "1"}))

    assert reponse["etape"] == "complet" and reponse["accepte"] is True
    etat = reponse["etat_consolide"]
    assert etat["type"] == "ETAT_CONSOLIDE"
    assert etat["faits_par_module"]["M-nominal"]["valeurs"] == {"a": "1"}
    assert etat["contradictions"] == []


def test_etat_consolide_snapshot_invalide_est_bloque_avant_ecriture():
    reponse = etat_consolide(_snapshot("M-invalide", "2026-01-04T00:00:00Z", {"a": 1}))  # valeur NUMÉRIQUE

    assert reponse["etape"] == "validation" and reponse["accepte"] is False
    assert reponse["verdict"] == "REJ-SNAPSHOT-VALEUR-NON-TEXTE"


def test_etat_consolide_detecte_une_contradiction_meme_source_meme_horodatage():
    module_source = "M-contradiction"
    horodatage = "2026-01-04T00:00:00Z"
    etat_consolide(_snapshot(module_source, horodatage, {"prevision": "100"}))
    reponse = etat_consolide(_snapshot(module_source, horodatage, {"prevision": "120"}))

    contradictions = reponse["etat_consolide"]["contradictions"]
    assert len(contradictions) == 1
    assert contradictions[0]["module_source"] == module_source
    assert contradictions[0]["horodatage"] == horodatage


def test_etat_consolide_choisit_le_dernier_fait_chronologiquement_pas_alphabetiquement():
    """Même cas limite que le correctif de etat_consolide.py, exercé de bout en bout via
    l'outil composé plutôt que la fonction métier nue."""
    module_source = "M-fuseaux-outil"
    etat_consolide(_snapshot(module_source, "2026-01-01T01:00:00+09:00", {"v": "plus-vieux"}))
    reponse = etat_consolide(_snapshot(module_source, "2026-01-01T00:30:00+00:00", {"v": "plus-recent"}))

    assert reponse["etat_consolide"]["faits_par_module"][module_source]["valeurs"]["v"] == "plus-recent"


def test_lire_etat_consolide_n_ingere_rien_de_nouveau():
    module_source = "M-lecture-seule"
    avant = etat_consolide(_snapshot(module_source, "2026-01-04T00:00:00Z", {"a": "1"}))["etat_consolide"]

    relu = lire_etat_consolide()

    assert relu["faits_par_module"][module_source] == avant["faits_par_module"][module_source]
    assert relu["etat_id"] == avant["etat_id"]


def test_valider_rapport_strategique_via_executer_accepte_les_15_cles_exactes():
    from m9_strategic_intelligence import contrats

    outil = next(o for o in outils() if o.nom == "m9_valider_rapport_strategique")
    reponse = executer(outil, {"rapport": _rapport_complet(contrats.CHAMPS_RAPPORT_STRATEGIQUE)})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True


def test_valider_rapport_strategique_via_executer_rejette_une_cle_manquante():
    from m9_strategic_intelligence import contrats

    rapport = _rapport_complet(contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    rapport.pop(next(iter(contrats.CHAMPS_RAPPORT_STRATEGIQUE)))
    outil = next(o for o in outils() if o.nom == "m9_valider_rapport_strategique")

    reponse = executer(outil, {"rapport": rapport})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"] == "REJ-RAPPORT-CLE-MANQUANTE"


def test_snapshot_sans_champ_requis_refuse_par_le_schema():
    outil = next(o for o in outils() if o.nom == "m9_etat_consolide")
    reponse = executer(outil, {})
    assert reponse["erreur"] == "arguments_invalides"
