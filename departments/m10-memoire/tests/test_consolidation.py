"""consolidation.py : consolidation nocturne, idempotente par (affaire_id, jour), maintenant fourni.

Chaque test injecte son propre `horodatage`/`jour` explicite — aucun appel à une horloge n'est
possible dans le module (conformite.py::HORLOGE_INTERNE le détecterait de toute façon), ce que
`test_conformite.py` vérifie déjà pour tout le paquet ; ici on vérifie le COMPORTEMENT : rejouer la
même nuit ne crée rien de plus, même avec un `horodatage` d'appel différent.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import consolidation, registre, variance, wct


JOUR = "2026-09-15"
HORODATAGE_EVENEMENT = "2026-09-15T14:00:00-04:00"
HORODATAGE_CONSOLIDATION = "2026-09-16T03:00:00-04:00"


def _wct(wct_id="WCT-1", lead_id="LEAD-1", horodatage=HORODATAGE_EVENEMENT, **overrides):
    base = {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "lead_id": lead_id,
        "technicien_id": "TECH-1",
        "horodatage_completion": horodatage,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": f"devis-{wct_id}",
    }
    base.update(overrides)
    return base


def _variance(evenement_id="EVT-1", wct_id="WCT-1", horodatage=HORODATAGE_EVENEMENT, **overrides):
    base = {
        "evenement_id": evenement_id,
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "chantier_id": "CH-1",
        "statut_variance": "evaluee",
        "signal_critique": True,
        "seuil_pourcentage": 0.1,
        "horodatage_completion": horodatage,
        "lignes": [],
    }
    base.update(overrides)
    return base


def _registres():
    return registre.Registre(), registre.Registre()


def test_consolider_affaire_refuse_un_affaire_id_absent():
    registre_evenements, registre_affaires = _registres()

    resultat = consolidation.consolider_affaire(
        "", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    assert resultat["ecrit"] is False
    assert resultat["verdict"] == consolidation.REJ_CONSOLIDATION_AFFAIRE_ABSENTE
    assert registre_affaires.lire() == []


def test_consolider_affaire_refuse_un_jour_absent():
    registre_evenements, registre_affaires = _registres()

    resultat = consolidation.consolider_affaire(
        "LEAD-1", "", HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    assert resultat["ecrit"] is False
    assert resultat["verdict"] == consolidation.REJ_CONSOLIDATION_JOUR_ABSENT


def test_consolider_affaire_sans_evenement_n_ecrit_rien():
    registre_evenements, registre_affaires = _registres()

    resultat = consolidation.consolider_affaire(
        "LEAD-INCONNUE", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    assert resultat["ecrit"] is False
    assert resultat["deja_consolide"] is False
    assert resultat["verdict"] == consolidation.REJ_CONSOLIDATION_AUCUN_EVENEMENT
    assert registre_affaires.lire() == []


def test_consolider_affaire_condense_wct_et_variance_en_un_seul_fait():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    variance.memoriser_variance(_variance(evenement_id="EVT-1", wct_id="WCT-1"), registre_evenements)

    resultat = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    assert resultat["ecrit"] is True
    assert resultat["verdict"] is None
    fait = resultat["fait"]
    assert fait["type_entree"] == "fait_consolide"
    assert fait["affaire_id"] == "LEAD-1"
    assert fait["jour"] == JOUR
    assert fait["horodatage"] == HORODATAGE_CONSOLIDATION
    assert len(registre_affaires.lire()) == 1


def test_consolider_affaire_cite_ses_sources_sans_les_perdre():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    maillon_evenements = registre_evenements.lire()

    resultat = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    sources = resultat["fait"]["sources"]
    assert len(sources) == 1
    assert sources[0]["registre"] == "evenements"
    assert sources[0]["ligne_id"] == maillon_evenements[0]["ligne_id"]
    assert sources[0]["type_evenement"] == "m4.travaux_termines"
    assert sources[0]["identifiant"] == "WCT-1"


def test_consolider_affaire_rejouee_la_meme_nuit_ne_cree_rien_de_plus():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)

    premier = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )
    # `horodatage` d'appel DIFFÉRENT du premier : l'idempotence ne dépend jamais de l'instant
    # d'appel, seulement de (affaire_id, jour) déjà consolidé.
    second = consolidation.consolider_affaire(
        "LEAD-1", JOUR, "2026-09-16T04:30:00-04:00", registre_evenements, registre_affaires
    )

    assert premier["ecrit"] is True
    assert second["ecrit"] is False
    assert second["deja_consolide"] is True
    assert second["fait"]["ligne_id"] == premier["fait"]["ligne_id"]
    assert len(registre_affaires.lire()) == 1


def test_consolider_affaire_un_nouveau_jour_cree_un_nouveau_fait():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(
        _wct(wct_id="WCT-1", lead_id="LEAD-1", horodatage="2026-09-15T14:00:00-04:00"), registre_evenements
    )
    wct.memoriser_wct(
        _wct(wct_id="WCT-2", lead_id="LEAD-1", horodatage="2026-09-16T14:00:00-04:00"), registre_evenements
    )

    resultat_jour_1 = consolidation.consolider_affaire(
        "LEAD-1", "2026-09-15", HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )
    resultat_jour_2 = consolidation.consolider_affaire(
        "LEAD-1", "2026-09-16", "2026-09-17T03:00:00-04:00", registre_evenements, registre_affaires
    )

    assert resultat_jour_1["ecrit"] is True
    assert resultat_jour_2["ecrit"] is True
    assert resultat_jour_1["fait"]["ligne_id"] != resultat_jour_2["fait"]["ligne_id"]
    assert len(registre_affaires.lire()) == 2


def test_consolider_affaire_ignore_les_evenements_d_une_autre_affaire():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-A"), registre_evenements)
    wct.memoriser_wct(_wct(wct_id="WCT-2", lead_id="LEAD-B"), registre_evenements)

    resultat = consolidation.consolider_affaire(
        "LEAD-A", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    assert len(resultat["fait"]["sources"]) == 1
    assert resultat["fait"]["sources"][0]["identifiant"] == "WCT-1"


def test_consolider_affaire_ignore_les_evenements_d_un_autre_jour():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(
        _wct(wct_id="WCT-1", lead_id="LEAD-1", horodatage="2026-09-14T23:59:00-04:00"), registre_evenements
    )
    wct.memoriser_wct(
        _wct(wct_id="WCT-2", lead_id="LEAD-1", horodatage="2026-09-15T00:01:00-04:00"), registre_evenements
    )

    resultat = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    assert len(resultat["fait"]["sources"]) == 1
    assert resultat["fait"]["sources"][0]["identifiant"] == "WCT-2"


def test_consolider_affaire_resume_compte_les_variances_critiques():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    variance.memoriser_variance(
        _variance(evenement_id="EVT-1", wct_id="WCT-1", signal_critique=True), registre_evenements
    )

    resultat = consolidation.consolider_affaire(
        "LEAD-1", JOUR, HORODATAGE_CONSOLIDATION, registre_evenements, registre_affaires
    )

    resume = resultat["fait"]["resume"]
    assert "1 travaux terminés" in resume
    assert "1 variance" in resume
    assert "1 critique" in resume
