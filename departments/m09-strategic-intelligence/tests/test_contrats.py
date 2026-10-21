from m9_strategic_intelligence import contrats


def test_champs_snapshot_module_est_un_frozenset_exact():
    attendu = frozenset({"module_source", "horodatage", "valeurs"})

    assert isinstance(contrats.CHAMPS_SNAPSHOT_MODULE, frozenset)
    assert attendu == contrats.CHAMPS_SNAPSHOT_MODULE


def test_champs_rapport_strategique_est_un_frozenset_exact():
    attendu = frozenset(
        {
            "etat",
            "diagnostic",
            "preuves",
            "hypotheses",
            "incertitudes",
            "scenarios",
            "recommandations",
            "priorites",
            "impacts",
            "risques",
            "actions",
            "validation",
            "taches_par_departement",
            "suivi",
            "memoire_m10",
        }
    )

    assert isinstance(contrats.CHAMPS_RAPPORT_STRATEGIQUE, frozenset)
    assert attendu == contrats.CHAMPS_RAPPORT_STRATEGIQUE
