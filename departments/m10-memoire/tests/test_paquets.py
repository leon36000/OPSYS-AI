"""paquets.py : paquet de contexte en 4 couches ordonnées pour une affaire."""


import pytest
from m10_memoire import consolidation, decisions, paquets, registre, variance, wct

HORODATAGE = "2026-09-15T14:00:00-04:00"
HORODATAGE_PAQUET = "2026-09-16T08:00:00-04:00"


def _wct(wct_id="WCT-1", lead_id="LEAD-1", horodatage=HORODATAGE, **overrides):
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


def _variance(evenement_id="EVT-1", wct_id="WCT-1", horodatage=HORODATAGE, **overrides):
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


def _decision(decision_id, statut, raison="Raison suffisante et tracée."):
    return {"decision_id": decision_id, "raison": raison, "statut": statut, "options_ecartees": ""}


@pytest.fixture
def registres():
    return registre.Registre(), registre.Registre()


def _couche(paquet, nom):
    return next(c for c in paquet["couches"] if c["nom"] == nom)


def test_paquet_sans_aucune_donnee_declare_les_quatre_couches_vides(registres):
    registre_evenements, registre_affaires = registres

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert [c["nom"] for c in paquet["couches"]] == [
        paquets.COUCHE_REGLES_ENTREPRISE,
        paquets.COUCHE_FAITS_AFFAIRE,
        paquets.COUCHE_EVENEMENTS_RECENTS,
        paquets.COUCHE_SIGNAUX_NON_RESOLUS,
    ]
    for couche in paquet["couches"]:
        assert couche["vide"] is True
        assert couche["tronque"] is False
        assert couche["nb_total"] == 0
        assert couche["faits"] == []
    assert paquet["affaire_id"] == "LEAD-1"
    assert paquet["horodatage"] == HORODATAGE_PAQUET


def test_couche_regles_entreprise_ne_garde_que_le_statut_validee_courant(registres):
    _, registre_affaires = registres
    decisions.enregistrer_decision(_decision("DEC-VALIDEE", "validee"), registre_affaires, HORODATAGE)
    decisions.enregistrer_decision(_decision("DEC-PROPOSEE", "proposee"), registre_affaires, HORODATAGE)
    # validée puis remplacée : le statut COURANT n'est plus validee, ne doit plus apparaître.
    decisions.enregistrer_decision(_decision("DEC-REMPLACEE", "validee"), registre_affaires, HORODATAGE)
    decisions.enregistrer_decision(_decision("DEC-REMPLACEE", "remplacee"), registre_affaires, HORODATAGE)

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, registre.Registre(), registre_affaires
    )

    couche = _couche(paquet, paquets.COUCHE_REGLES_ENTREPRISE)
    identifiants = {f["identifiant"] for f in couche["faits"]}
    decisions_validees = [m for m in registre_affaires.lire() if m.get("decision_id") == "DEC-VALIDEE"]
    assert identifiants == {decisions_validees[0]["ligne_id"]}
    assert couche["vide"] is False


def test_couche_faits_affaire_filtre_par_affaire(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-A", lead_id="LEAD-A"), registre_evenements)
    wct.memoriser_wct(_wct(wct_id="WCT-B", lead_id="LEAD-B"), registre_evenements)
    consolidation.consolider_affaire("LEAD-A", "2026-09-15", HORODATAGE_PAQUET, registre_evenements, registre_affaires)
    consolidation.consolider_affaire("LEAD-B", "2026-09-15", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    paquet = paquets.assembler_paquet_contexte("LEAD-A", HORODATAGE_PAQUET, registre_evenements, registre_affaires)
    fait_consolide_a = next(
        m
        for m in registre_affaires.lire()
        if m.get("type_entree") == "fait_consolide" and m.get("affaire_id") == "LEAD-A"
    )

    couche = _couche(paquet, paquets.COUCHE_FAITS_AFFAIRE)
    assert couche["nb_total"] == 1
    assert couche["faits"][0]["identifiant"] == fait_consolide_a["ligne_id"]
    assert couche["faits"][0]["source"] == "m10:consolidation"
    assert couche["faits"][0]["resume"].startswith("2026-09-15")


def test_couche_evenements_recents_contient_wct_et_variance_triees_recent_dabord(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(
        _wct(wct_id="WCT-1", lead_id="LEAD-1", horodatage="2026-09-15T08:00:00-04:00"), registre_evenements
    )
    variance.memoriser_variance(
        _variance(evenement_id="EVT-1", wct_id="WCT-1", horodatage="2026-09-15T09:00:00-04:00"), registre_evenements
    )

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    couche = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)
    assert couche["nb_total"] == 2
    # la variance (09h) est plus récente que le WCT (08h) : elle vient en premier.
    assert couche["faits"][0]["source"] == "m6.variance_chantier"
    assert couche["faits"][1]["source"] == "m4.travaux_termines"


def test_couche_signaux_non_resolus_ne_garde_que_les_variances_critiques(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    variance.memoriser_variance(
        _variance(evenement_id="EVT-CRITIQUE", wct_id="WCT-1", signal_critique=True), registre_evenements
    )
    variance.memoriser_variance(
        _variance(evenement_id="EVT-OK", wct_id="WCT-1", signal_critique=False), registre_evenements
    )

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    couche = _couche(paquet, paquets.COUCHE_SIGNAUX_NON_RESOLUS)
    assert couche["nb_total"] == 1
    assert couche["faits"][0]["identifiant"] == "EVT-CRITIQUE"


def test_chaque_fait_porte_sa_provenance(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    couche = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)
    fait = couche["faits"][0]
    assert set(fait) == {"identifiant", "horodatage", "source", "resume"}
    assert fait["identifiant"] == "WCT-1"
    assert fait["horodatage"] == HORODATAGE
    assert fait["source"] == "m4.travaux_termines"


def test_budget_caracteres_tronque_et_le_dit(registres):
    registre_evenements, registre_affaires = registres
    for i in range(10):
        wct.memoriser_wct(
            _wct(wct_id=f"WCT-{i}", lead_id="LEAD-1", horodatage=f"2026-09-15T{8 + i:02d}:00:00-04:00"),
            registre_evenements,
        )

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1",
        HORODATAGE_PAQUET,
        registre_evenements,
        registre_affaires,
        budget_caracteres=400,
        n_faits_max_par_couche=10,
    )

    couche = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)
    assert couche["nb_total"] == 10
    assert couche["tronque"] is True
    assert couche["nb_omis"] == couche["nb_total"] - couche["nb_inclus"]
    assert couche["nb_omis"] > 0
    assert couche["nb_inclus"] < couche["nb_total"]


def test_n_faits_max_par_couche_borne_le_nombre_de_faits(registres):
    registre_evenements, registre_affaires = registres
    for i in range(5):
        wct.memoriser_wct(
            _wct(wct_id=f"WCT-{i}", lead_id="LEAD-1", horodatage=f"2026-09-15T{8 + i:02d}:00:00-04:00"),
            registre_evenements,
        )

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1",
        HORODATAGE_PAQUET,
        registre_evenements,
        registre_affaires,
        budget_caracteres=paquets.BUDGET_CARACTERES_DEFAUT,
        n_faits_max_par_couche=2,
    )

    couche = _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)
    assert couche["nb_total"] == 5
    assert couche["nb_inclus"] == 2
    assert couche["tronque"] is True


def test_caracteres_utilises_est_la_somme_des_couches(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert paquet["caracteres_utilises"] == sum(c["caracteres"] for c in paquet["couches"])
    assert paquet["caracteres_utilises"] > 0


@pytest.mark.parametrize(
    "affaire_id,horodatage,budget,n_max",
    [
        ("", HORODATAGE_PAQUET, paquets.BUDGET_CARACTERES_DEFAUT, paquets.NB_FAITS_MAX_PAR_COUCHE_DEFAUT),
        ("LEAD-1", "", paquets.BUDGET_CARACTERES_DEFAUT, paquets.NB_FAITS_MAX_PAR_COUCHE_DEFAUT),
        ("LEAD-1", HORODATAGE_PAQUET, 0, paquets.NB_FAITS_MAX_PAR_COUCHE_DEFAUT),
        ("LEAD-1", HORODATAGE_PAQUET, -1, paquets.NB_FAITS_MAX_PAR_COUCHE_DEFAUT),
        ("LEAD-1", HORODATAGE_PAQUET, paquets.BUDGET_CARACTERES_DEFAUT, 0),
    ],
)
def test_assembler_paquet_contexte_refuse_une_entree_invalide(registres, affaire_id, horodatage, budget, n_max):
    registre_evenements, registre_affaires = registres

    with pytest.raises(ValueError):
        paquets.assembler_paquet_contexte(
            affaire_id,
            horodatage,
            registre_evenements,
            registre_affaires,
            budget_caracteres=budget,
            n_faits_max_par_couche=n_max,
        )


def test_resume_dune_decision_tres_longue_est_borne(registres):
    _, registre_affaires = registres
    decisions.enregistrer_decision(
        _decision("DEC-LONGUE", "validee", raison="x" * 500), registre_affaires, HORODATAGE
    )

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, registre.Registre(), registre_affaires
    )

    resume = _couche(paquet, paquets.COUCHE_REGLES_ENTREPRISE)["faits"][0]["resume"]
    assert len(resume) == paquets.RESUME_MAX_CARACTERES
    assert resume.endswith("…")
