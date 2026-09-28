"""Capacités d'agent de M10 : contrat des outils et chaînes composées (décision, préflight)."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire.outils import (
    arbitrer_revision,
    contexte_preflight,
    journaliser_decision,
    memoriser_wct,
    outils,
    signaler_revision,
    statut_decision,
    verifier_reference,
)

from opsys.departements import lire_manifeste
from opsys.outils import executer

HORODATAGE = "2026-08-04T12:00:00+00:00"


def _decision(decision_id, statut="proposee", raison="Raison suffisante et tracée."):
    return {
        "decision_id": decision_id,
        "raison": raison,
        "statut": statut,
        "options_ecartees": "Ne rien faire",
    }


def _dossier_suffisant(reference_decision):
    return {
        "evenement": "Modification du module X",
        "resume": "Ajout d'une garde",
        "preuves": "Tests verts",
        "impact": "Aucun appelant cassé",
        "prochaine_action": "Ouvrir la PR",
        "references_decisions": [reference_decision],
    }


def _wct(wct_id, consommateurs=("M6", "M5", "M10")):
    return {
        "wct_id": wct_id,
        "intervention_id": "INT-001",
        "lead_id": "LEAD-001",
        "technicien_id": "TECH-001",
        "horodatage_completion": HORODATAGE,
        "fix_gps_completion": {"lat": "45.5", "lon": "-73.6"},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": "REV-001",
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": consommateurs,
        "devis_id": "DEV-001",
    }


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m10_journaliser_decision"
    assert noms[1] == "m10_contexte_preflight"
    assert all(nom.startswith("m10_") for nom in noms)


def test_journaliser_decision_valide_ecrit_et_retourne_une_reference_verifiable():
    reponse = journaliser_decision(_decision("DEC-AGENT-001"), HORODATAGE)

    assert reponse["etape"] == "complet" and reponse["accepte"] is True
    assert reponse["decision"]["decision_id"] == "DEC-AGENT-001"
    reference = reponse["reference"]
    assert set(reference) == {"ligne_id", "registre", "hash_tete"}
    assert reference["registre"] == "business"

    verification = verifier_reference(reference)
    assert verification["accepte"] is True


def test_journaliser_decision_sans_raison_n_ecrit_rien():
    reponse = journaliser_decision(_decision("DEC-AGENT-002", raison=""), HORODATAGE)

    assert reponse["etape"] == "validation" and reponse["accepte"] is False
    assert reponse["verdict"] is not None
    assert statut_decision("DEC-AGENT-002")["statut"] is None


def test_contexte_preflight_dossier_insuffisant_trace_le_refus_sans_lever():
    dossier_incomplet = _dossier_suffisant("DEC-INEXISTANTE")
    dossier_incomplet["references_decisions"] = []

    reponse = contexte_preflight(dossier_incomplet, HORODATAGE)

    assert reponse["suffisant"] is False
    assert reponse["verdict"] is not None
    assert reponse["trace"]["type_entree"] == "revision_signalee"


def test_contexte_preflight_dossier_suffisant_n_ecrit_rien():
    reponse = contexte_preflight(_dossier_suffisant("DEC-AGENT-001"), HORODATAGE)

    assert reponse == {"suffisant": True, "verdict": None, "trace": None}


def test_memoriser_wct_puis_signaler_et_arbitrer_une_revision():
    premier = memoriser_wct(_wct("WCT-AGENT-001"))
    second = memoriser_wct(_wct("WCT-AGENT-002"))
    assert premier["accepte"] is True and second["accepte"] is True

    ligne_id_a = premier["resultat"]["ligne_id"]
    ligne_id_b = second["resultat"]["ligne_id"]

    # signaler_revision cible le registre Business, memoriser_wct écrit au Forge : deux
    # ligne_id du Forge sont donc introuvables au Business (CA-M10-06, registres distincts).
    refus_registre_croise = signaler_revision(ligne_id_a, ligne_id_b, HORODATAGE)
    assert refus_registre_croise["accepte"] is False


def test_signaler_puis_arbitrer_une_revision_sur_le_registre_business():
    depart = journaliser_decision(_decision("DEC-REV-A"), HORODATAGE)
    arrivee = journaliser_decision(_decision("DEC-REV-B"), HORODATAGE)
    ligne_id_a = depart["decision"]["ligne_id"]
    ligne_id_b = arrivee["decision"]["ligne_id"]

    signalement = signaler_revision(ligne_id_a, ligne_id_b, HORODATAGE)
    assert signalement["accepte"] is True
    revision_ligne_id = signalement["resultat"]["ligne_id"]

    arbitrage = arbitrer_revision(revision_ligne_id, "distincts_confirmes", HORODATAGE)
    assert arbitrage["accepte"] is True
    assert arbitrage["resultat"]["statut"] == "distincts_confirmes"

    refus = arbitrer_revision("ligne-jamais-signalee", "obsolete_marquee", HORODATAGE)
    assert refus["accepte"] is False


def test_verifier_reference_detecte_une_reference_forgee_via_executer():
    reponse = journaliser_decision(_decision("DEC-AGENT-003"), HORODATAGE)
    reference_forgee = dict(reponse["reference"])
    reference_forgee["hash_tete"] = "hash-invente"

    outil = next(o for o in outils() if o.nom == "m10_verifier_reference")
    resultat = executer(outil, {"reference": reference_forgee})

    assert resultat["ok"] is True
    assert resultat["resultat"]["accepte"] is False


def test_wct_sans_champ_requis_refuse_par_la_validation_metier():
    """_WCT reste volontairement générique dans le schéma (12 champs hétérogènes gelés par
    M4) : c'est wct.valider_wct (validation métier) qui refuse un WCT incomplet, pas le
    schéma JSON — la réponse reste ok=True (l'outil s'est bien exécuté), accepte=False."""
    outil = next(o for o in outils() if o.nom == "m10_memoriser_wct")
    reponse = executer(outil, {"wct_recu": {"wct_id": "WCT-INCOMPLET"}})
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False


def test_statut_hors_enumeration_refuse_par_le_schema_de_arbitrer_revision():
    outil = next(o for o in outils() if o.nom == "m10_arbitrer_revision")
    reponse = executer(
        outil,
        {"revision_ligne_id": "x", "statut": "fusionnes", "horodatage": HORODATAGE},
    )
    assert reponse["erreur"] == "arguments_invalides"
