"""Capacités d'agent de M10 : contrat des outils et chaînes composées (décision, préflight).

Ce module exerce les singletons de PRODUCTION de `outils.py`, câblés sur le stockage durable de
l'instance (ADR-0009/0010) — contrairement aux autres fichiers de tests du département, qui
gardent leur propre `registre.Registre()` en mémoire. La fixture `_base_durable_m10` ci-dessous
isole donc chaque test derrière sa propre base SQLite temporaire (jamais `~/.opsys` par défaut).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire.outils import (
    arbitrer_revision,
    auditer_non_oubli,
    consolider_affaire,
    contexte_preflight,
    journaliser_decision,
    memoriser_wct,
    outils,
    paquet_contexte_affaire,
    signaler_revision,
    statut_decision,
    verifier_reference,
)

from opsys import stockage
from opsys.departements import lire_manifeste
from opsys.outils import executer

HORODATAGE = "2026-08-04T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _base_durable_m10(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée pour chaque test (ADR-0009) : les singletons de production
    `_REGISTRE_EVENEMENTS`/`_REGISTRE_AFFAIRES` de `outils.py` y écrivent réellement — sans elle,
    ils viseraient la base par défaut de l'hôte (`~/.opsys`), un effet de bord inacceptable en
    test. Libérée après chaque test : aucun état ne fuit d'un test à l'autre.
    """
    url = f"sqlite:///{tmp_path / 'm10-outils.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield
    stockage.liberer()


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
    assert {"m10_paquet_contexte_affaire", "m10_consolider_affaire", "m10_auditer_non_oubli"} <= set(noms)


def test_journaliser_decision_valide_ecrit_et_retourne_une_reference_verifiable():
    reponse = journaliser_decision(_decision("DEC-AGENT-001"), HORODATAGE)

    assert reponse["etape"] == "complet" and reponse["accepte"] is True
    assert reponse["decision"]["decision_id"] == "DEC-AGENT-001"
    reference = reponse["reference"]
    assert set(reference) == {"ligne_id", "registre", "hash_tete"}
    assert reference["registre"] == "affaires"

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

    # signaler_revision cible le registre Affaires, memoriser_wct écrit au registre Événements :
    # deux ligne_id d'Événements sont donc introuvables aux Affaires (CA-M10-06, registres
    # distincts).
    refus_registre_croise = signaler_revision(ligne_id_a, ligne_id_b, HORODATAGE)
    assert refus_registre_croise["accepte"] is False


def test_signaler_puis_arbitrer_une_revision_sur_le_registre_affaires():
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


def test_paquet_contexte_affaire_declare_les_couches_vides_pour_une_affaire_inconnue():
    paquet = paquet_contexte_affaire("LEAD-AGENT-INCONNUE", HORODATAGE)

    assert paquet["affaire_id"] == "LEAD-AGENT-INCONNUE"
    assert all(couche["vide"] is True for couche in paquet["couches"])


def test_paquet_contexte_affaire_reflete_un_wct_memorise():
    memoriser_wct(_wct("WCT-PAQUET-1"))

    paquet = paquet_contexte_affaire("LEAD-001", HORODATAGE)

    couche_evenements = next(c for c in paquet["couches"] if c["nom"] == "evenements_recents")
    assert couche_evenements["vide"] is False
    assert couche_evenements["faits"][0]["identifiant"] == "WCT-PAQUET-1"


def test_paquet_contexte_affaire_via_executer_refuse_un_budget_hors_schema():
    outil = next(o for o in outils() if o.nom == "m10_paquet_contexte_affaire")
    reponse = executer(outil, {"affaire_id": "LEAD-001", "horodatage": HORODATAGE, "budget_caracteres": 1})
    assert reponse["erreur"] == "arguments_invalides"  # non exposé à l'appelant (P11)


def test_consolider_affaire_est_idempotente_par_jour():
    memoriser_wct(_wct("WCT-CONSO-1"))

    premier = consolider_affaire("LEAD-001", "2026-08-04", HORODATAGE)
    second = consolider_affaire("LEAD-001", "2026-08-04", "2026-08-05T03:00:00+00:00")

    assert premier["ecrit"] is True
    assert second["ecrit"] is False
    assert second["deja_consolide"] is True
    assert second["fait"]["ligne_id"] == premier["fait"]["ligne_id"]


def test_consolider_affaire_sans_evenement_ce_jour_refuse_nommement():
    reponse = consolider_affaire("LEAD-SANS-EVENEMENT", "2026-08-04", HORODATAGE)
    assert reponse["ecrit"] is False
    assert reponse["verdict"] is not None


def test_auditer_non_oubli_detecte_un_wct_jamais_memorise():
    rapport = auditer_non_oubli([{"type_evenement": "m4.travaux_termines", "identifiant": "WCT-JAMAIS-VU"}])

    assert rapport["nb_oublis"] == 1
    assert rapport["chaine_evenements_intacte"] is True
    assert rapport["chaine_affaires_intacte"] is True


def test_auditer_non_oubli_trouve_un_wct_memorise_par_un_autre_outil():
    memoriser_wct(_wct("WCT-AUDIT-1"))

    rapport = auditer_non_oubli([{"type_evenement": "m4.travaux_termines", "identifiant": "WCT-AUDIT-1"}])

    assert rapport["nb_oublis"] == 0


def test_auditer_non_oubli_via_executer_refuse_une_liste_mal_typee():
    outil = next(o for o in outils() if o.nom == "m10_auditer_non_oubli")
    reponse = executer(outil, {"identifiants_attendus": "pas-une-liste"})
    assert reponse["erreur"] == "arguments_invalides"


def test_auditer_non_oubli_via_executer_un_element_sans_identifiant_devient_un_oubli():
    """La validation JSON Schema d'OPSYS ne vérifie pas la structure des ÉLÉMENTS d'un tableau
    (opsys/outils.py::valider_arguments, volontairement réduite — voir sa docstring) : un élément
    incomplet n'est pas un refus_metier, il se traduit en oubli explicite (identifiant=None),
    jamais une exception ni une valeur par défaut optimiste."""
    outil = next(o for o in outils() if o.nom == "m10_auditer_non_oubli")
    reponse = executer(outil, {"identifiants_attendus": [{"type_evenement": "m4.travaux_termines"}]})
    assert reponse["ok"] is True
    assert reponse["resultat"]["nb_oublis"] == 1
