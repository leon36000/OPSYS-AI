from m8_analytics import alertes, digest, qualite, xmr


def _signal_superieur():
    return xmr.detecter_signal("haut", [10.0, 10.0, 10.0, 10.0, 50.0], 3)


def _signal_inferieur():
    return xmr.detecter_signal("bas", [10.0, 10.0, 10.0, 10.0, -30.0], 3)


def _signal_insuffisant():
    return xmr.detecter_signal("court", [10.0, 20.0], 5)


_DEFINITION_M4 = {
    "metric_id": "m4_duree_reelle_minutes",
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": 0, "plage_max": None},
}


def _alerte_perimee():
    evaluation = qualite.evaluer_fraicheur(_DEFINITION_M4["metric_id"], 5.0, 2)
    return alertes.proposer_action(evaluation, _DEFINITION_M4)


def _alerte_hors_plage():
    evaluation = qualite.evaluer_plage(_DEFINITION_M4["metric_id"], 999.0, 0, 30)
    return alertes.proposer_action(evaluation, _DEFINITION_M4)


def test_produire_digest_quotidien_retourne_un_contrat_complet_avec_un_signal_actif():
    signal = _signal_superieur()

    resultat = digest.produire_digest_quotidien([signal])

    assert set(resultat) == {
        "type",
        "nb_signaux_actifs",
        "signaux_actifs",
        "nb_alertes_proposees",
        "alertes_proposees",
        "resume_alertes",
        "hash_digest",
    }
    assert resultat["type"] == "DIGEST_ANALYTICS"
    assert resultat["nb_signaux_actifs"] == 1
    assert resultat["signaux_actifs"] == [signal]
    assert resultat["nb_alertes_proposees"] == 0
    assert resultat["alertes_proposees"] == []
    assert resultat["resume_alertes"] == "Aucune alerte proposée aujourd'hui."
    assert isinstance(resultat["hash_digest"], str)
    assert resultat["hash_digest"]


def test_produire_digest_quotidien_exclut_les_donnees_insuffisantes():
    signal_actif = _signal_superieur()
    signal_insuffisant = _signal_insuffisant()

    resultat = digest.produire_digest_quotidien(
        [signal_actif, signal_insuffisant]
    )

    assert resultat["signaux_actifs"] == [signal_actif]
    assert resultat["nb_signaux_actifs"] == 1
    assert resultat["nb_signaux_actifs"] == len(resultat["signaux_actifs"])


def test_produire_digest_quotidien_retourne_zero_pour_une_liste_vide():
    resultat = digest.produire_digest_quotidien([])

    assert resultat["type"] == "DIGEST_ANALYTICS"
    assert resultat["nb_signaux_actifs"] == 0
    assert resultat["signaux_actifs"] == []
    assert isinstance(resultat["hash_digest"], str)
    assert resultat["hash_digest"]


def test_produire_digest_quotidien_retourne_zero_si_tous_les_signaux_sont_insuffisants():
    signaux = [_signal_insuffisant()]

    resultat = digest.produire_digest_quotidien(signaux)

    assert resultat["nb_signaux_actifs"] == 0
    assert resultat["signaux_actifs"] == []


def test_produire_digest_quotidien_produit_un_hash_deterministe():
    signaux = [_signal_superieur(), _signal_inferieur()]

    resultat_1 = digest.produire_digest_quotidien(signaux)
    resultat_2 = digest.produire_digest_quotidien(signaux)

    assert resultat_1["hash_digest"] == resultat_2["hash_digest"]


def test_produire_digest_quotidien_conserve_l_ordre_des_signaux_actifs():
    signal_superieur = _signal_superieur()
    signal_inferieur = _signal_inferieur()
    signal_insuffisant = _signal_insuffisant()

    resultat = digest.produire_digest_quotidien(
        [signal_inferieur, signal_insuffisant, signal_superieur]
    )

    assert resultat["signaux_actifs"] == [
        signal_inferieur,
        signal_superieur,
    ]


def test_produire_digest_quotidien_conserve_integralement_les_signaux_actifs():
    signal_superieur = _signal_superieur()
    signal_inferieur = _signal_inferieur()

    resultat = digest.produire_digest_quotidien(
        [signal_superieur, signal_inferieur]
    )

    assert resultat["signaux_actifs"][0] == signal_superieur
    assert resultat["signaux_actifs"][1] == signal_inferieur
    assert set(resultat["signaux_actifs"][0]) == {
        "metric_id",
        "type_signal",
        "valeur_observee",
        "limite_naturelle_haute",
        "limite_naturelle_basse",
        "n",
    }
    assert set(resultat["signaux_actifs"][1]) == {
        "metric_id",
        "type_signal",
        "valeur_observee",
        "limite_naturelle_haute",
        "limite_naturelle_basse",
        "n",
    }


def test_produire_digest_quotidien_compte_apres_filtrage_des_signaux_actifs():
    signaux = [
        _signal_insuffisant(),
        _signal_superieur(),
        _signal_insuffisant(),
        _signal_inferieur(),
    ]

    resultat = digest.produire_digest_quotidien(signaux)

    assert resultat["nb_signaux_actifs"] == 2
    assert resultat["nb_signaux_actifs"] == len(resultat["signaux_actifs"])
    assert all(
        signal["type_signal"]
        in {"HORS_LIMITE_SUPERIEURE", "HORS_LIMITE_INFERIEURE"}
        for signal in resultat["signaux_actifs"]
    )


# ---------------------------------------------------------------------------
# T3.1-suite : alertes de qualité proposées dans le digest — sourcées, sans doublon, et une
# journée sans alerte le dit explicitement.
# ---------------------------------------------------------------------------


def test_produire_digest_quotidien_sans_alerte_le_dit_explicitement():
    """alertes_proposees omis (défaut) : équivalent à une liste vide, jamais un champ absent."""
    resultat = digest.produire_digest_quotidien([])

    assert resultat["nb_alertes_proposees"] == 0
    assert resultat["alertes_proposees"] == []
    assert resultat["resume_alertes"] == "Aucune alerte proposée aujourd'hui."


def test_produire_digest_quotidien_inclut_une_alerte_proposee_sourcee():
    alerte = _alerte_perimee()

    resultat = digest.produire_digest_quotidien([], alertes_proposees=[alerte])

    assert resultat["nb_alertes_proposees"] == 1
    assert resultat["alertes_proposees"] == [alerte]
    assert resultat["alertes_proposees"][0]["source"] == "Module M4 — WCT"
    assert resultat["resume_alertes"] == "1 alerte(s) proposée(s) aujourd'hui, sourcée(s) ci-dessous."


def test_produire_digest_quotidien_deduplique_une_alerte_identique_repetee():
    alerte = _alerte_perimee()

    resultat = digest.produire_digest_quotidien([], alertes_proposees=[alerte, alerte, alerte])

    assert resultat["nb_alertes_proposees"] == 1
    assert resultat["alertes_proposees"] == [alerte]


def test_produire_digest_quotidien_conserve_deux_alertes_distinctes_dans_l_ordre():
    perimee = _alerte_perimee()
    hors_plage = _alerte_hors_plage()

    resultat = digest.produire_digest_quotidien([], alertes_proposees=[hors_plage, perimee])

    assert resultat["nb_alertes_proposees"] == 2
    assert resultat["alertes_proposees"] == [hors_plage, perimee]


def test_produire_digest_quotidien_hash_depend_des_alertes_proposees():
    alerte = _alerte_perimee()

    sans_alerte = digest.produire_digest_quotidien([])
    avec_alerte = digest.produire_digest_quotidien([], alertes_proposees=[alerte])

    assert sans_alerte["hash_digest"] != avec_alerte["hash_digest"]


def test_produire_digest_quotidien_signaux_et_alertes_sont_independants():
    """Aucun signal actif, une alerte proposée : les deux sections restent honnêtes chacune pour
    soi, jamais l'une masquée par l'absence de l'autre."""
    resultat = digest.produire_digest_quotidien(
        [_signal_insuffisant()], alertes_proposees=[_alerte_perimee()]
    )

    assert resultat["nb_signaux_actifs"] == 0
    assert resultat["signaux_actifs"] == []
    assert resultat["nb_alertes_proposees"] == 1
