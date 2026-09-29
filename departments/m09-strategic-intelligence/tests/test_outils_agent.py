"""Capacités d'agent de M9 : contrat des outils et chaîne d'état consolidé composée."""

from __future__ import annotations

from pathlib import Path

from m9_strategic_intelligence.outils import consommateurs, outils
from m9_strategic_intelligence.registre import RegistreSnapshots

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer


def _snapshot(module_source, horodatage, valeurs):
    return {"module_source": module_source, "horodatage": horodatage, "valeurs": valeurs}


def _rapport_complet(champs):
    return {cle: "valeur" for cle in champs}


def _outils_par_nom(alertes=None):
    """Registre ET registre d'alertes EN MÉMOIRE, explicites : `outils()` sans argument adosse le
    registre de production au stockage durable de l'instance (ADR-0009), qu'aucun test unitaire
    de ce fichier ne monte — voir `departments/m09-strategic-intelligence/tests/
    test_registre_durable.py` pour la preuve du branchement durable lui-même, et
    `test_evenements_alerte_proposee_m8.py` pour `m9_produire_briefing_matin` (qui exige une base
    réelle via `opsys.approbations.file_proprietaire`, donc hors de ce fichier)."""
    return {o.nom: o for o in outils(RegistreSnapshots(), alertes_cible=alertes if alertes is not None else [])}


def _appeler(par_nom, nom, **kwargs):
    return executer(par_nom[nom], kwargs)


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m9_etat_consolide"
    assert all(nom.startswith("m9_") for nom in noms)


def test_etat_consolide_snapshot_valide_ecrit_et_retourne_l_etat():
    par_nom = _outils_par_nom()
    reponse = _appeler(
        par_nom, "m9_etat_consolide",
        snapshot=_snapshot("M-nominal", "2026-01-04T00:00:00Z", {"a": "1"}),
    )

    resultat = reponse["resultat"]
    assert resultat["etape"] == "complet" and resultat["accepte"] is True
    etat = resultat["etat_consolide"]
    assert etat["type"] == "ETAT_CONSOLIDE"
    assert etat["faits_par_module"]["M-nominal"]["valeurs"] == {"a": "1"}
    assert etat["contradictions"] == []


def test_etat_consolide_snapshot_invalide_est_bloque_avant_ecriture():
    par_nom = _outils_par_nom()
    reponse = _appeler(
        par_nom, "m9_etat_consolide",
        snapshot=_snapshot("M-invalide", "2026-01-04T00:00:00Z", {"a": 1}),  # valeur NUMÉRIQUE
    )

    resultat = reponse["resultat"]
    assert resultat["etape"] == "validation" and resultat["accepte"] is False
    assert resultat["verdict"] == "REJ-SNAPSHOT-VALEUR-NON-TEXTE"


def test_etat_consolide_detecte_une_contradiction_meme_source_meme_horodatage():
    par_nom = _outils_par_nom()
    module_source = "M-contradiction"
    horodatage = "2026-01-04T00:00:00Z"
    _appeler(
        par_nom, "m9_etat_consolide", snapshot=_snapshot(module_source, horodatage, {"prevision": "100"}),
    )
    reponse = _appeler(
        par_nom, "m9_etat_consolide", snapshot=_snapshot(module_source, horodatage, {"prevision": "120"}),
    )

    contradictions = reponse["resultat"]["etat_consolide"]["contradictions"]
    assert len(contradictions) == 1
    assert contradictions[0]["module_source"] == module_source
    assert contradictions[0]["horodatage"] == horodatage


def test_etat_consolide_choisit_le_dernier_fait_chronologiquement_pas_alphabetiquement():
    """Même cas limite que le correctif de etat_consolide.py, exercé de bout en bout via
    l'outil composé plutôt que la fonction métier nue."""
    par_nom = _outils_par_nom()
    module_source = "M-fuseaux-outil"
    _appeler(
        par_nom, "m9_etat_consolide",
        snapshot=_snapshot(module_source, "2026-01-01T01:00:00+09:00", {"v": "plus-vieux"}),
    )
    reponse = _appeler(
        par_nom, "m9_etat_consolide",
        snapshot=_snapshot(module_source, "2026-01-01T00:30:00+00:00", {"v": "plus-recent"}),
    )

    etat = reponse["resultat"]["etat_consolide"]
    assert etat["faits_par_module"][module_source]["valeurs"]["v"] == "plus-recent"


def test_lire_etat_consolide_n_ingere_rien_de_nouveau():
    par_nom = _outils_par_nom()
    module_source = "M-lecture-seule"
    avant = _appeler(
        par_nom, "m9_etat_consolide",
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", {"a": "1"}),
    )["resultat"]["etat_consolide"]

    relu = _appeler(par_nom, "m9_lire_etat_consolide")["resultat"]

    assert relu["faits_par_module"][module_source] == avant["faits_par_module"][module_source]
    assert relu["etat_id"] == avant["etat_id"]


def test_valider_rapport_strategique_via_executer_accepte_les_15_cles_exactes():
    from m9_strategic_intelligence import contrats

    par_nom = _outils_par_nom()
    reponse = _appeler(
        par_nom, "m9_valider_rapport_strategique",
        rapport=_rapport_complet(contrats.CHAMPS_RAPPORT_STRATEGIQUE),
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True


def test_valider_rapport_strategique_via_executer_rejette_une_cle_manquante():
    from m9_strategic_intelligence import contrats

    rapport = _rapport_complet(contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    rapport.pop(next(iter(contrats.CHAMPS_RAPPORT_STRATEGIQUE)))
    par_nom = _outils_par_nom()

    reponse = _appeler(par_nom, "m9_valider_rapport_strategique", rapport=rapport)

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"] == "REJ-RAPPORT-CLE-MANQUANTE"


def test_snapshot_sans_champ_requis_refuse_par_le_schema():
    par_nom = _outils_par_nom()
    reponse = executer(par_nom["m9_etat_consolide"], {})
    assert reponse["erreur"] == "arguments_invalides"


def test_outils_partagent_le_meme_registre_entre_deux_appels():
    """Preuve de la fermeture (closure) sur registre_cible : m9_etat_consolide et
    m9_lire_etat_consolide de la même instance voient le même registre, comme avant le passage
    à l'injection."""
    registre_memoire = RegistreSnapshots()
    par_nom = {o.nom: o for o in outils(registre_memoire)}
    module_source = "M-partage"

    _appeler(par_nom, "m9_etat_consolide", snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", {"a": "1"}))

    assert len(registre_memoire.lire()) == 1
    relu = _appeler(par_nom, "m9_lire_etat_consolide")["resultat"]
    assert relu["faits_par_module"][module_source]["valeurs"] == {"a": "1"}


# ---------------------------------------------------------------------------
# PLAN T3.2 — briefing du matin : m9_lire_alertes_m8 (en mémoire) et cohérence du câblage bus.
# m9_produire_briefing_matin exige une base réelle (file du propriétaire) : couvert par
# test_evenements_alerte_proposee_m8.py, pas ici.
# ---------------------------------------------------------------------------
def _alerte_m8(**overrides):
    base = {
        "evenement_id": "m8-alerte-x-REJ-QUALITE-DONNEE-PERIMEE-2026-09-28T00:00:00Z",
        "metric_id": "x", "type_alerte": "REJ-QUALITE-DONNEE-PERIMEE",
        "quoi": "Valeur périmée pour x.", "a_qui": "m04-field-ops", "pourquoi": "…",
        "preuve": {"metric_id": "x", "fraicheur_jours": 10.0, "fraicheur_attendue_jours": 2},
        "source": "src", "horodatage_reference": "2026-09-28T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_lire_alertes_m8_relecture_pure_sans_filtre():
    alertes_memoire = [_alerte_m8()]
    par_nom = _outils_par_nom(alertes=alertes_memoire)

    reponse = _appeler(par_nom, "m9_lire_alertes_m8")

    assert reponse["ok"] is True
    page = reponse["resultat"]
    # Depuis la borne (T1.5-d) : un objet, la liste est sous `alertes`. Ici une seule page, tout y tient.
    assert page["alertes"] == alertes_memoire
    assert page["total"] == 1 and page["reste"] == 0 and page["prochain_depart"] is None
    # Relecture pure : n'a rien ingéré, la liste source n'a pas grossi.
    assert len(alertes_memoire) == 1


def test_lire_alertes_m8_vide_par_defaut():
    par_nom = _outils_par_nom()
    page = _appeler(par_nom, "m9_lire_alertes_m8")["resultat"]
    assert page["alertes"] == [] and page["total"] == 0 and page["prochain_depart"] is None


def test_manifeste_et_outils_incluent_le_briefing_du_matin():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert {"m9_lire_alertes_m8", "m9_produire_briefing_matin"}.issubset(noms)


def test_briefing_matin_et_lire_alertes_sont_t0_lecture_seule():
    """Point 4 du PLAN T3.2 : les outils du briefing sont T0 (lecture), jamais une écriture —
    seul m9_etat_consolide (ingestion) reste T1."""
    par_nom = _outils_par_nom()
    assert par_nom["m9_lire_alertes_m8"].autonomie == Autonomie.T0
    assert par_nom["m9_produire_briefing_matin"].autonomie == Autonomie.T0


def test_produire_briefing_matin_sans_argument_refuse_par_le_schema():
    par_nom = _outils_par_nom()
    reponse = executer(par_nom["m9_produire_briefing_matin"], {})
    assert reponse["erreur"] == "arguments_invalides"


def test_consommateurs_expose_m8_alerte_proposee():
    """Cohérence avec `department.yaml:evenements.consomme` (vérifiée par `opsys-metier verifier`) :
    exactement un consommateur, pour m8.alerte_proposee."""
    assert set(consommateurs()) == {"m8.alerte_proposee"}
    assert callable(consommateurs()["m8.alerte_proposee"])
