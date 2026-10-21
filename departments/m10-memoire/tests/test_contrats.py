from m10_memoire import contrats


def test_champs_evenement_memoire_est_un_frozenset_exact():
    attendu = frozenset({"evenement", "resume", "preuves", "impact", "prochaine_action"})

    assert isinstance(contrats.CHAMPS_EVENEMENT_MEMOIRE, frozenset)
    assert attendu == contrats.CHAMPS_EVENEMENT_MEMOIRE


def test_champs_decision_est_un_frozenset_exact():
    attendu = frozenset({"decision_id", "raison", "statut", "options_ecartees"})

    assert isinstance(contrats.CHAMPS_DECISION, frozenset)
    assert attendu == contrats.CHAMPS_DECISION


def test_champs_wct_est_un_frozenset_exact_de_douze_elements():
    attendu = frozenset(
        {
            "wct_id",
            "intervention_id",
            "lead_id",
            "technicien_id",
            "horodatage_completion",
            "fix_gps_completion",
            "duree_reelle_minutes",
            "ecart_signale",
            "revue_id",
            "hash_maillon",
            "consommateurs_cibles",
            "devis_id",
        }
    )

    assert isinstance(contrats.CHAMPS_WCT, frozenset)
    assert attendu == contrats.CHAMPS_WCT
    assert len(contrats.CHAMPS_WCT) == 12


def test_champs_reference_memoire_est_un_frozenset_exact():
    attendu = frozenset({"ligne_id", "registre", "hash_tete"})

    assert isinstance(contrats.CHAMPS_REFERENCE_MEMOIRE, frozenset)
    assert attendu == contrats.CHAMPS_REFERENCE_MEMOIRE


def test_consommateur_attendu_est_m10():
    assert contrats.CONSOMMATEUR_ATTENDU == "M10"


def test_statut_decision_est_un_tuple_ordonne_exact():
    assert isinstance(contrats.STATUT_DECISION, tuple)
    assert contrats.STATUT_DECISION == (
        "proposee",
        "validee",
        "remplacee",
        "annulee",
        "indetermine",
    )


def test_statut_revision_est_un_tuple_ordonne_exact():
    assert isinstance(contrats.STATUT_REVISION, tuple)
    assert contrats.STATUT_REVISION == (
        "en_attente",
        "distincts_confirmes",
        "obsolete_marquee",
        "indetermine",
    )


def test_statut_decision_contient_echappatoire_indetermine():
    assert contrats.ECHAPPATOIRE_INDETERMINE == "indetermine"
    assert contrats.ECHAPPATOIRE_INDETERMINE in contrats.STATUT_DECISION


def test_statut_revision_contient_echappatoire_indetermine():
    assert contrats.ECHAPPATOIRE_INDETERMINE == "indetermine"
    assert contrats.ECHAPPATOIRE_INDETERMINE in contrats.STATUT_REVISION


def test_statut_revision_ne_contient_aucune_valeur_de_fusion():
    assert all("fusion" not in statut for statut in contrats.STATUT_REVISION)
