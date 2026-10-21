"""paquets.py : paquet de contexte en 4 couches ordonnées pour une affaire."""


import pytest
from m10_memoire import consolidation, decisions, paquets, registre, signaux, variance, wct

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


def test_resume_du_wct_ne_dit_ecart_signale_que_si_m4_l_a_signale(registres):
    """PLAN T1.5-c : M4 ne signale plus d'écart « par précaution » à chaque complétion d'appareil
    (`ecart_signale` faux tant qu'aucune demande d'écart n'est ouverte) ; M10 ne grave donc « écart
    signalé » que pour un écart réel, sans que son code change."""
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-SANS", lead_id="LEAD-1", ecart_signale=False), registre_evenements)
    wct.memoriser_wct(_wct(wct_id="WCT-AVEC", lead_id="LEAD-1", ecart_signale=True), registre_evenements)

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    resumes = {f["identifiant"]: f["resume"] for f in _couche(paquet, paquets.COUCHE_EVENEMENTS_RECENTS)["faits"]}
    assert resumes["WCT-SANS"] == "WCT WCT-SANS : durée réelle 90 min"
    assert resumes["WCT-AVEC"] == "WCT WCT-AVEC : durée réelle 90 min, écart signalé"


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
    assert set(fait) == {"identifiant", "horodatage", "source", "resume", "confidentialite"}
    assert fait["confidentialite"] == "INTERNAL"
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


# -- PLAN T3.3-suite-b : signaux avec cycle de vie, blocs de synthèse, agent --------------------------------
def _humain(par="amina.admin", role="admin", source="appareil"):
    return {"par": par, "role": role, "source_decision": source}


def _signal_pris_en_compte_puis_clos(registre_evenements, registre_affaires, signal_id, jour):
    for action, moment, motif in (
        (signaux.ACTION_PRISE_EN_COMPTE, "2026-09-16T08:00:00-04:00", "Lu par l'admin, on vérifie sur place."),
        (signaux.ACTION_CLOTURE, jour, "Écart expliqué, facture corrigée avec le client."),
    ):
        _, verdict = signaux.traiter_signal(
            action, signal_id, "amina.admin", "admin", "appareil", motif, moment, registre_evenements, registre_affaires
        )
        assert verdict is None


def test_couche_signaux_montre_les_ouverts_d_abord_puis_les_derniers_clos_avec_qui_et_pourquoi(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    for i in (1, 2, 3):
        variance.memoriser_variance(_variance(evenement_id=f"EVT-{i}", wct_id="WCT-1"), registre_evenements)
    _signal_pris_en_compte_puis_clos(registre_evenements, registre_affaires, "EVT-1", "2026-09-17T08:00:00-04:00")
    signaux.traiter_signal(
        signaux.ACTION_PRISE_EN_COMPTE, "EVT-2", "amina.admin", "admin", "appareil",
        "Lu par l'admin, on vérifie sur place.", "2026-09-16T08:00:00-04:00", registre_evenements, registre_affaires,
    )

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    couche = _couche(paquet, paquets.COUCHE_SIGNAUX_NON_RESOLUS)
    assert [(f["identifiant"], f["etat"]) for f in couche["faits"]] == [
        ("EVT-3", "ouvert"),
        ("EVT-2", "pris_en_compte"),
        ("EVT-1", "clos"),
    ]
    clos = couche["faits"][2]
    assert clos["traite_par"] == "amina.admin" and clos["traite_le"] == "2026-09-17T08:00:00-04:00"
    assert "Écart expliqué" in clos["resume"] and "amina.admin" in clos["resume"]
    assert paquet["signaux"] == {"nb_ouverts": 1, "nb_pris_en_compte": 1, "nb_clos": 1}


def test_le_decompte_des_signaux_ne_depend_pas_de_la_troncature_de_la_couche(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    for i in range(4):
        variance.memoriser_variance(_variance(evenement_id=f"EVT-{i}", wct_id="WCT-1"), registre_evenements)

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires, n_faits_max_par_couche=1
    )

    couche = _couche(paquet, paquets.COUCHE_SIGNAUX_NON_RESOLUS)
    assert couche["nb_inclus"] == 1 and couche["nb_omis"] == 3 and couche["tronque"] is True
    assert paquet["signaux"]["nb_ouverts"] == 4  # le core bloque sur ce nombre, pas sur ce qui reste affiché


def test_un_signal_d_une_autre_affaire_ne_compte_pas(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-A", lead_id="LEAD-A"), registre_evenements)
    wct.memoriser_wct(_wct(wct_id="WCT-B", lead_id="LEAD-B"), registre_evenements)
    variance.memoriser_variance(_variance(evenement_id="EVT-B", wct_id="WCT-B"), registre_evenements)

    paquet = paquets.assembler_paquet_contexte("LEAD-A", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert paquet["signaux"] == {"nb_ouverts": 0, "nb_pris_en_compte": 0, "nb_clos": 0}
    assert _couche(paquet, paquets.COUCHE_SIGNAUX_NON_RESOLUS)["vide"] is True


def test_un_signal_clos_par_la_regle_de_reevaluation_apparait_clos_dans_le_paquet(registres):
    registre_evenements, registre_affaires = registres
    wct.memoriser_wct(_wct(wct_id="WCT-1", lead_id="LEAD-1"), registre_evenements)
    variance.memoriser_variance(_variance(evenement_id="EVT-1", wct_id="WCT-1"), registre_evenements)
    variance.memoriser_variance(
        _variance(evenement_id="EVT-2", wct_id="WCT-1", signal_critique=False), registre_evenements
    )

    paquet = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    [fait] = _couche(paquet, paquets.COUCHE_SIGNAUX_NON_RESOLUS)["faits"]
    assert fait["etat"] == "clos" and fait["traite_par"] == signaux.REGLE_VARIANCE_REEVALUEE
    assert paquet["signaux"]["nb_ouverts"] == 0


def test_le_paquet_porte_le_bloc_de_confidentialite_de_l_agent_demande(registres):
    registre_evenements, registre_affaires = registres

    paquet = paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent="m03-estimation"
    )
    sans_agent = paquets.assembler_paquet_contexte("LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires)

    assert paquet["confidentialite"] == {"agent": "m03-estimation", "regle": "v1", "nb_retenus": 0}
    assert sans_agent["confidentialite"] == {"agent": None, "regle": "v1", "nb_retenus": 0}


@pytest.mark.parametrize(
    "agent", ["", "M03-ESTIMATION", "m11-inconnu", "m03_estimation", "m3-estimation", 3, ["m03-estimation"]]
)
def test_un_agent_qui_n_est_pas_un_departement_est_refuse(registres, agent):
    registre_evenements, registre_affaires = registres

    with pytest.raises(ValueError, match="agent invalide"):
        paquets.assembler_paquet_contexte(
            "LEAD-1", HORODATAGE_PAQUET, registre_evenements, registre_affaires, agent=agent
        )
