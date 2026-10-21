from m9_strategic_intelligence import etat_consolide, registre


def _ajouter(registre_snapshots, module_source, horodatage, valeurs):
    return registre_snapshots.ajouter(
        {
            "module_source": module_source,
            "horodatage": horodatage,
            "valeurs": valeurs,
        }
    )


def test_registre_vide_produit_un_etat_consolide_vide_avec_un_id_hexadecimal():
    registre_snapshots = registre.RegistreSnapshots()

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert set(resultat) == {"type", "faits_par_module", "contradictions", "etat_id"}
    assert resultat["type"] == "ETAT_CONSOLIDE"
    assert resultat["faits_par_module"] == {}
    assert resultat["contradictions"] == []
    assert isinstance(resultat["etat_id"], str)
    assert len(resultat["etat_id"]) == 64
    assert all(caractere in "0123456789abcdef" for caractere in resultat["etat_id"])


def test_un_snapshot_est_conserve_comme_maillon_complet_du_module():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m1_collecte",
        "2025-01-01T10:00:00Z",
        {"marche": "stable"},
    )
    maillon = registre_snapshots.lire()[0]

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert set(resultat["faits_par_module"]) == {"m1_collecte"}
    assert resultat["faits_par_module"]["m1_collecte"] == maillon
    assert set(resultat["faits_par_module"]["m1_collecte"]) == {
        "index",
        "module_source",
        "horodatage",
        "valeurs",
        "hash_precedent",
        "hash_maillon",
    }


def test_deux_snapshots_dun_meme_module_ne_conservent_que_le_dernier():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m2_analyse",
        "2025-01-01T10:00:00Z",
        {"score": 10},
    )
    _ajouter(
        registre_snapshots,
        "m2_analyse",
        "2025-01-01T11:00:00Z",
        {"score": 20},
    )
    premier, dernier = registre_snapshots.lire()

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert set(resultat["faits_par_module"]) == {"m2_analyse"}
    assert resultat["faits_par_module"]["m2_analyse"] == dernier
    assert resultat["faits_par_module"]["m2_analyse"] != premier
    assert resultat["faits_par_module"]["m2_analyse"]["index"] > premier["index"]


def test_chaque_module_conserve_son_propre_dernier_snapshot():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m3_risque",
        "2025-01-01T10:00:00Z",
        {"niveau": "faible"},
    )
    _ajouter(
        registre_snapshots,
        "m4_finance",
        "2025-01-01T10:00:00Z",
        {"budget": 100},
    )
    _ajouter(
        registre_snapshots,
        "m3_risque",
        "2025-01-01T11:00:00Z",
        {"niveau": "eleve"},
    )
    premier_risque, finance, dernier_risque = registre_snapshots.lire()

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert set(resultat["faits_par_module"]) == {"m3_risque", "m4_finance"}
    assert resultat["faits_par_module"]["m3_risque"] == dernier_risque
    assert resultat["faits_par_module"]["m3_risque"] != premier_risque
    assert resultat["faits_par_module"]["m4_finance"] == finance


def test_valeurs_identiques_au_meme_horodatage_ne_creent_pas_de_contradiction():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m5_operations",
        "2025-01-01T10:00:00Z",
        {"capacite": 80},
    )
    _ajouter(
        registre_snapshots,
        "m5_operations",
        "2025-01-01T10:00:00Z",
        {"capacite": 80},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["contradictions"] == []


def test_valeurs_differentes_au_meme_horodatage_creent_une_contradiction():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m6_ventes",
        "2025-01-01T10:00:00Z",
        {"prevision": 100},
    )
    _ajouter(
        registre_snapshots,
        "m6_ventes",
        "2025-01-01T10:00:00Z",
        {"prevision": 120},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["contradictions"] == [
        {
            "ligne_id_a": 0,
            "ligne_id_b": 1,
            "module_source": "m6_ventes",
            "horodatage": "2025-01-01T10:00:00Z",
            "horodatage_utc": "2025-01-01T10:00:00+00:00",
            "horodatages_sources": ["2025-01-01T10:00:00Z"],
        }
    ]


def test_representations_d_un_meme_instant_utc_creent_une_contradiction_et_gardent_les_sources():
    registre_snapshots = registre.RegistreSnapshots()
    source_a = "2026-09-30T08:00:00-04:00"
    source_b = "2026-09-30T12:00:00Z"
    _ajouter(registre_snapshots, "m5_finance", source_a, {"cash": 1})
    _ajouter(registre_snapshots, "m5_finance", source_b, {"cash": 100})

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert len(resultat["contradictions"]) == 1
    contradiction = resultat["contradictions"][0]
    assert contradiction["horodatage_utc"] == "2026-09-30T12:00:00+00:00"
    assert contradiction["horodatages_sources"] == [source_a, source_b]
    assert resultat["faits_par_module"]["m5_finance"]["horodatage"] == source_b


def test_trois_maillons_a_a_b_produisent_deux_contradictions_distinctes():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m7_logistique",
        "2025-01-01T10:00:00Z",
        {"stock": 50},
    )
    _ajouter(
        registre_snapshots,
        "m7_logistique",
        "2025-01-01T10:00:00Z",
        {"stock": 50},
    )
    _ajouter(
        registre_snapshots,
        "m7_logistique",
        "2025-01-01T10:00:00Z",
        {"stock": 40},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["contradictions"] == [
        {
            "ligne_id_a": 0,
            "ligne_id_b": 2,
            "module_source": "m7_logistique",
            "horodatage": "2025-01-01T10:00:00Z",
            "horodatage_utc": "2025-01-01T10:00:00+00:00",
            "horodatages_sources": ["2025-01-01T10:00:00Z"],
        },
        {
            "ligne_id_a": 1,
            "ligne_id_b": 2,
            "module_source": "m7_logistique",
            "horodatage": "2025-01-01T10:00:00Z",
            "horodatage_utc": "2025-01-01T10:00:00+00:00",
            "horodatages_sources": ["2025-01-01T10:00:00Z"],
        },
    ]


def test_modules_differents_au_meme_horodatage_ne_creent_pas_de_contradiction():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m8_production",
        "2025-01-01T10:00:00Z",
        {"volume": 10},
    )
    _ajouter(
        registre_snapshots,
        "m9_distribution",
        "2025-01-01T10:00:00Z",
        {"volume": 20},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["contradictions"] == []


def test_horodatages_differents_du_meme_module_ne_creent_pas_de_contradiction():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m10_qualite",
        "2025-01-01T10:00:00Z",
        {"conformite": True},
    )
    _ajouter(
        registre_snapshots,
        "m10_qualite",
        "2025-01-01T11:00:00Z",
        {"conformite": False},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["contradictions"] == []


def test_choisit_le_dernier_fait_par_comparaison_chronologique_et_non_alphabetique():
    """Le dernier fait doit être choisi par datetime ISO-8601 PARSÉ (fuseaux
    compris), jamais par comparaison alphabétique des chaînes brutes.

    "2026-01-01T01:00:00+09:00" (= 2025-12-31T16:00:00Z) est
    alphabétiquement PLUS GRAND que "2026-01-01T00:30:00+00:00"
    (= 2026-01-01T00:30:00Z) alors qu'il est chronologiquement PLUS ANCIEN
    (~8h30 plus tôt en heure réelle) : un fuseau positif élevé peut rendre
    l'heure locale plus grande alors que l'instant UTC réel est antérieur.
    """
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m_fuseaux",
        "2026-01-01T01:00:00+09:00",
        {"v": "alphabetiquement-plus-grand-mais-plus-ancien"},
    )
    dernier, _ = _ajouter(
        registre_snapshots,
        "m_fuseaux",
        "2026-01-01T00:30:00+00:00",
        {"v": "chronologiquement-plus-recent"},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["faits_par_module"]["m_fuseaux"] == dernier
    assert (
        resultat["faits_par_module"]["m_fuseaux"]["valeurs"]["v"]
        == "chronologiquement-plus-recent"
    )


def test_etat_id_est_deterministe_pour_deux_registres_identiques():
    premier_registre = registre.RegistreSnapshots()
    second_registre = registre.RegistreSnapshots()

    for registre_snapshots in (premier_registre, second_registre):
        _ajouter(
            registre_snapshots,
            "m11_strategie",
            "2025-01-01T10:00:00Z",
            {"priorite": "croissance"},
        )
        _ajouter(
            registre_snapshots,
            "m12_ressources",
            "2025-01-01T11:00:00Z",
            {"effectif": 42},
        )

    premier_resultat = etat_consolide.construire_etat_consolide(premier_registre)
    second_resultat = etat_consolide.construire_etat_consolide(second_registre)

    assert premier_resultat["etat_id"] == second_resultat["etat_id"]


def test_etat_id_change_lorsquune_seule_valeur_de_snapshot_change():
    premier_registre = registre.RegistreSnapshots()
    second_registre = registre.RegistreSnapshots()

    _ajouter(
        premier_registre,
        "m13_marche",
        "2025-01-01T10:00:00Z",
        {"indice": 101},
    )
    _ajouter(
        second_registre,
        "m13_marche",
        "2025-01-01T10:00:00Z",
        {"indice": 102},
    )

    premier_resultat = etat_consolide.construire_etat_consolide(premier_registre)
    second_resultat = etat_consolide.construire_etat_consolide(second_registre)

    assert premier_resultat["etat_id"] != second_resultat["etat_id"]


def test_construire_etat_consolide_ne_modifie_jamais_le_registre():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "m14_pilotage",
        "2025-01-01T10:00:00Z",
        {"statut": "actif"},
    )
    _ajouter(
        registre_snapshots,
        "m14_pilotage",
        "2025-01-01T10:00:00Z",
        {"statut": "suspendu"},
    )
    avant = registre_snapshots.lire()

    premier_resultat = etat_consolide.construire_etat_consolide(registre_snapshots)
    apres_premier_appel = registre_snapshots.lire()
    second_resultat = etat_consolide.construire_etat_consolide(registre_snapshots)
    apres_second_appel = registre_snapshots.lire()

    assert premier_resultat == second_resultat
    assert apres_premier_appel == avant
    assert apres_second_appel == avant


def test_construire_etat_consolide_conserve_le_plus_recent_meme_arrive_apres():
    registre_snapshots = registre.RegistreSnapshots()
    _ajouter(
        registre_snapshots,
        "X",
        "2025-01-02T10:00:00Z",
        {"recent": True},
    )
    maillon_ancien = _ajouter(
        registre_snapshots,
        "X",
        "2025-01-01T10:00:00Z",
        {"ancien": True},
    )

    resultat = etat_consolide.construire_etat_consolide(registre_snapshots)

    assert resultat["faits_par_module"]["X"]["horodatage"] == "2025-01-02T10:00:00Z"
    assert resultat["faits_par_module"]["X"] != maillon_ancien
