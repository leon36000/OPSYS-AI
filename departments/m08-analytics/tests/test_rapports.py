import pytest
from m8_analytics import encodage, rapports


def _metrique(metric_id, valeur=42.5, fraicheur=3.0, n=1):
    return {
        "metric_id": metric_id,
        "valeur": valeur,
        "version_definition": "a" * 64,
        "fraicheur": fraicheur,
        "n": n,
    }


def _signal(metric_id, valeur_observee=50.0, n=5):
    return {
        "metric_id": metric_id,
        "type_signal": "HORS_LIMITE_SUPERIEURE",
        "valeur_observee": valeur_observee,
        "limite_naturelle_haute": 33.5,
        "limite_naturelle_basse": 10.0,
        "n": n,
    }


def test_vue_complete_sans_filtre_conserve_toutes_les_donnees():
    metriques = [_metrique("a", 42.5), _metrique("b", 43.5)]
    signaux = [_signal("a")]

    resultat = rapports.construire_rapport(metriques, signaux)

    assert set(resultat) == {
        "type",
        "role",
        "metriques",
        "signaux",
        "snapshot_id",
    }
    assert resultat["type"] == "RAPPORT_ANALYTIQUE"
    assert resultat["role"] is None
    assert resultat["metriques"] == metriques
    assert resultat["signaux"] == signaux
    assert resultat["snapshot_id"] == encodage.empreinte(
        "RAPPORT_ANALYTIQUE", None, metriques, signaux
    )


def test_filtre_non_vide_exclut_metrique_et_signal_non_autorises():
    metriques = [
        _metrique("a", 42.5),
        _metrique("b", 43.5),
        _metrique("c", 44.5),
    ]
    signaux = [_signal("b")]

    resultat = rapports.construire_rapport(
        metriques,
        signaux,
        role="terrain",
        metric_ids_autorises=["a", "c"],
    )

    assert resultat["metriques"] == [metriques[0], metriques[2]]
    assert resultat["signaux"] == []
    assert resultat["role"] == "terrain"


def test_filtre_vide_exclut_tout():
    metriques = [
        _metrique("a", 42.5),
        _metrique("b", 43.5),
        _metrique("c", 44.5),
    ]
    signaux = [_signal("b")]

    resultat = rapports.construire_rapport(
        metriques,
        signaux,
        role="terrain",
        metric_ids_autorises=[],
    )

    assert resultat["metriques"] == []
    assert resultat["signaux"] == []


def test_snapshot_id_est_deterministe_pour_des_objets_distincts_mais_egaux():
    metriques_1 = [_metrique("a", 42.5)]
    signaux_1 = [_signal("a")]
    metriques_2 = [_metrique("a", 42.5)]
    signaux_2 = [_signal("a")]

    resultat_1 = rapports.construire_rapport(
        metriques_1,
        signaux_1,
        role="terrain",
        metric_ids_autorises=["a"],
    )
    resultat_2 = rapports.construire_rapport(
        metriques_2,
        signaux_2,
        role="terrain",
        metric_ids_autorises=["a"],
    )

    assert metriques_1[0] is not metriques_2[0]
    assert signaux_1[0] is not signaux_2[0]
    assert resultat_1["snapshot_id"] == resultat_2["snapshot_id"]


def test_snapshot_id_differe_entre_vue_complete_et_vue_filtree():
    metriques = [_metrique("a", 42.5), _metrique("b", 43.5)]
    signaux = [_signal("b")]

    vue_complete = rapports.construire_rapport(metriques, signaux)
    vue_filtree = rapports.construire_rapport(
        metriques,
        signaux,
        metric_ids_autorises=["a"],
    )

    assert vue_complete["snapshot_id"] != vue_filtree["snapshot_id"]


def test_metrique_non_autorisee_sans_valeur_est_exclue():
    metriques = [
        {
            "metric_id": "b",
            "valeur": None,
            "version_definition": "a" * 64,
            "fraicheur": None,
            "n": 0,
        }
    ]
    signaux = []

    resultat = rapports.construire_rapport(
        metriques,
        signaux,
        metric_ids_autorises=["a"],
    )

    assert resultat["metriques"] == []


def test_role_sans_liste_d_autorisations_est_refuse_fail_closed():
    """Un rôle nommé sans metric_ids_autorises ne doit jamais tout voir.

    Avant ce correctif, seule l'absence de ``metric_ids_autorises`` était testée
    (jamais le rôle) : un rôle réel (ex. "terrain") sans liste explicite tombait
    dans la branche "vue complète" et voyait des métriques qui auraient dû être
    filtrées (ex. coûts/marges). Fail-closed : un rôle SANS liste est un refus
    métier, jamais une vue complète.
    """
    metriques = [_metrique("cout_secret", 999.0)]
    signaux = [_signal("cout_secret")]

    with pytest.raises(ValueError):
        rapports.construire_rapport(
            metriques, signaux, role="terrain", metric_ids_autorises=None
        )


def test_role_none_sans_liste_reste_une_vue_complete_non_filtree():
    """L'absence de RÔLE (pas de rôle du tout) reste la vue complète existante."""
    metriques = [_metrique("a", 42.5)]
    signaux = [_signal("a")]

    resultat = rapports.construire_rapport(metriques, signaux, role=None, metric_ids_autorises=None)

    assert resultat["metriques"] == metriques
    assert resultat["signaux"] == signaux


def test_role_est_conserve_avec_filtre_actif_et_vide():
    metriques = [_metrique("a")]
    signaux = [_signal("a")]

    resultat = rapports.construire_rapport(
        metriques,
        signaux,
        role="admin",
        metric_ids_autorises=[],
    )

    assert resultat["role"] == "admin"


def test_rendu_markdown_est_stable_et_reproduit_les_champs_du_rapport():
    metriques = [_metrique("m8_cash_libre_cad", 1234.5, fraicheur=0.5, n=4)]
    signaux = [_signal("m8_cash_libre_cad", valeur_observee=1234.5, n=8)]
    rapport = rapports.construire_rapport(
        metriques, signaux, role="admin", metric_ids_autorises=["m8_cash_libre_cad"]
    )

    rendu = rapports.rendre_markdown(rapport)

    assert rendu == rapports.rendre_markdown(rapport)
    assert "m8\\_cash\\_libre\\_cad" in rendu
    assert "1234.5" in rendu
    assert "0.5" in rendu
    assert "a" * 64 in rendu
    assert rapport["snapshot_id"] in rendu
    assert "n'authentifie pas les sources" in rendu


def test_rendu_markdown_refuse_empreinte_alteree_et_n_expose_pas_champs_ajoutes():
    rapport = rapports.construire_rapport(
        [_metrique("visible", 12.0), {**_metrique("masquee", 99), "contact": "fictif@example.test"}],
        [],
        role="terrain",
        metric_ids_autorises=["visible"],
    )
    rendu = rapports.rendre_markdown(rapport)
    assert "visible" in rendu
    assert "masquee" not in rendu
    assert "fictif@example.test" not in rendu

    falsifie = dict(rapport, role="admin")
    with pytest.raises(ValueError, match="EMPREINTE-INVALIDE"):
        rapports.rendre_markdown(falsifie)


def test_rendu_markdown_refuse_nombres_non_finis_et_echappe_identifiants():
    non_fini = rapports.construire_rapport([_metrique("metric", float("inf"))], [])
    with pytest.raises(ValueError, match="VALEUR-INVALIDE"):
        rapports.rendre_markdown(non_fini)

    rapport = rapports.construire_rapport([_metrique("[lien](javascript:alerte)\n# titre")], [])
    rendu = rapports.rendre_markdown(rapport)
    assert "\\[lien\\]\\(javascript:alerte\\) \\# titre" in rendu
    assert "\n# titre" not in rendu


def test_rendu_markdown_preserve_extensions_json_autorisees_sans_les_interpreter_ou_tronquer():
    extension = {"note_fictive": "extension-metric", "preuve_fictive": ["a", {"rang": 2}]}
    extension_signal = {"annotation_fictive": "extension-signal"}
    metrique = {**_metrique("mesure"), **extension}
    signal = {**_signal("mesure"), **extension_signal}
    rapport = rapports.construire_rapport([metrique], [signal])

    rendu = rapports.rendre_markdown(rapport)

    assert "note\\_fictive" in rendu and "extension-metric" in rendu
    assert "preuve\\_fictive" in rendu and '"rang":2' in rendu
    assert "annotation\\_fictive" in rendu and "extension-signal" in rendu

    grande_extension = "x" * 12_000 + "FIN-FICTIF"
    rapport_long = rapports.construire_rapport([_metrique("mesure") | {"extension": grande_extension}], [])
    rendu_long = rapports.rendre_markdown(rapport_long)
    assert grande_extension in rendu_long
