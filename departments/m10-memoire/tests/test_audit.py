"""audit.py : audit « non-oubli » — intégrité des deux chaînes + trace de chaque fait attendu."""


from m10_memoire import audit, decisions, registre, variance, wct

HORODATAGE = "2026-09-15T14:00:00-04:00"


def _wct(wct_id="WCT-1", **overrides):
    base = {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "lead_id": "LEAD-1",
        "technicien_id": "TECH-1",
        "horodatage_completion": HORODATAGE,
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


def _variance(evenement_id="EVT-1", wct_id="WCT-1", **overrides):
    base = {
        "evenement_id": evenement_id,
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "chantier_id": "CH-1",
        "statut_variance": "evaluee",
        "signal_critique": True,
        "seuil_pourcentage": 0.1,
        "horodatage_completion": HORODATAGE,
        "lignes": [],
    }
    base.update(overrides)
    return base


def _registres():
    return registre.Registre(), registre.Registre()


def test_audit_sans_rien_attendu_est_un_rapport_honnete_pas_un_tout_va_bien():
    registre_evenements, registre_affaires = _registres()

    rapport = audit.auditer_non_oubli([], registre_evenements, registre_affaires)

    assert rapport["total_attendus"] == 0
    assert rapport["oublis"] == []
    assert rapport["nb_oublis"] == 0
    assert rapport["chaine_evenements_intacte"] is True
    assert rapport["chaine_affaires_intacte"] is True


def test_audit_trouve_un_wct_memorise():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1"), registre_evenements)

    rapport = audit.auditer_non_oubli(
        [{"type_evenement": "m4.travaux_termines", "identifiant": "WCT-1"}], registre_evenements, registre_affaires
    )

    assert rapport["nb_oublis"] == 0
    assert rapport["total_attendus"] == 1


def test_audit_signale_un_wct_jamais_memorise():
    registre_evenements, registre_affaires = _registres()

    rapport = audit.auditer_non_oubli(
        [{"type_evenement": "m4.travaux_termines", "identifiant": "WCT-OUBLIE"}],
        registre_evenements,
        registre_affaires,
    )

    assert rapport["nb_oublis"] == 1
    assert rapport["oublis"] == [
        {"type_evenement": "m4.travaux_termines", "identifiant": "WCT-OUBLIE", "verdict": audit.REJ_AUDIT_TRACE_ABSENTE}
    ]


def test_audit_trouve_une_variance_memorisee():
    registre_evenements, registre_affaires = _registres()
    variance.memoriser_variance(_variance(evenement_id="EVT-1"), registre_evenements)

    rapport = audit.auditer_non_oubli(
        [{"type_evenement": "m6.variance_chantier", "identifiant": "EVT-1"}], registre_evenements, registre_affaires
    )

    assert rapport["nb_oublis"] == 0


def test_audit_ne_confond_jamais_le_wct_id_porte_par_une_variance_avec_un_wct_reel():
    """Régression classification.py : une variance porte un wct_id, mais ce n'est PAS la preuve
    que le WCT lui-même a été mémorisé."""
    registre_evenements, registre_affaires = _registres()
    variance.memoriser_variance(_variance(evenement_id="EVT-1", wct_id="WCT-JAMAIS-RECU"), registre_evenements)

    rapport = audit.auditer_non_oubli(
        [{"type_evenement": "m4.travaux_termines", "identifiant": "WCT-JAMAIS-RECU"}],
        registre_evenements,
        registre_affaires,
    )

    assert rapport["nb_oublis"] == 1
    assert rapport["oublis"][0]["verdict"] == audit.REJ_AUDIT_TRACE_ABSENTE


def test_audit_type_evenement_inconnu_est_un_oubli_nomme():
    registre_evenements, registre_affaires = _registres()

    rapport = audit.auditer_non_oubli(
        [{"type_evenement": "m9.decision_strategique", "identifiant": "X"}], registre_evenements, registre_affaires
    )

    assert rapport["nb_oublis"] == 1
    assert rapport["oublis"][0]["verdict"] == audit.REJ_AUDIT_TYPE_INCONNU


def test_audit_detecte_une_chaine_evenements_alteree():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-1"), registre_evenements)
    registre_evenements._chain[0]["duree_reelle_minutes"] = 999  # altération directe, hors API

    rapport = audit.auditer_non_oubli([], registre_evenements, registre_affaires)

    assert rapport["chaine_evenements_intacte"] is False
    assert rapport["chaine_affaires_intacte"] is True


def test_audit_detecte_une_chaine_affaires_alteree():
    registre_evenements, registre_affaires = _registres()
    decisions.enregistrer_decision(
        {"decision_id": "DEC-1", "raison": "Motif.", "statut": "validee", "options_ecartees": ""},
        registre_affaires,
        HORODATAGE,
    )
    registre_affaires._chain[0]["statut"] = "annulee"

    rapport = audit.auditer_non_oubli([], registre_evenements, registre_affaires)

    assert rapport["chaine_affaires_intacte"] is False
    assert rapport["chaine_evenements_intacte"] is True


def test_audit_melange_oublis_et_faits_presents_dans_une_liste_compacte():
    registre_evenements, registre_affaires = _registres()
    wct.memoriser_wct(_wct(wct_id="WCT-PRESENT"), registre_evenements)

    rapport = audit.auditer_non_oubli(
        [
            {"type_evenement": "m4.travaux_termines", "identifiant": "WCT-PRESENT"},
            {"type_evenement": "m4.travaux_termines", "identifiant": "WCT-ABSENT"},
        ],
        registre_evenements,
        registre_affaires,
    )

    assert rapport["total_attendus"] == 2
    assert rapport["nb_oublis"] == 1
    assert rapport["oublis"][0]["identifiant"] == "WCT-ABSENT"
