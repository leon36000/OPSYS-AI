"""M9.3 — couche sémantique : rapprochement sans calcul ni fusion de définitions incompatibles (fictif)."""

import pytest
from m9_strategic_intelligence import semantique_metriques as sm

FICTIF = True


def _definitions():
    return [
        {"metric_id": "marge_reelle", "departement_proprietaire": "m05-financecore", "unite": "CAD", "version": 1},
        {"metric_id": "marge_reelle", "departement_proprietaire": "m05-financecore", "unite": "CAD", "version": 2},
        {"metric_id": "ecart_duree", "departement_proprietaire": "m04-field-ops", "unite": "minutes", "version": 1},
    ]


def test_catalogue_garde_la_version_courante_et_refuse_la_contradiction():
    catalogue = sm.cataloguer(_definitions())
    assert catalogue["marge_reelle"]["version"] == 2 and set(catalogue) == {"marge_reelle", "ecart_duree"}
    # Ordre d'arrivée sans importance : une version plus ancienne reçue après ne remplace pas la courante.
    assert sm.cataloguer(list(reversed(_definitions())))["marge_reelle"]["version"] == 2
    contradictoire = [*_definitions(), {"metric_id": "ecart_duree", "unite": "heures", "version": 1}]
    with pytest.raises(ValueError, match="REJ-SEMANTIQUE-CONTRADICTION"):
        sm.cataloguer(contradictoire)
    with pytest.raises(ValueError, match="REJ-SEMANTIQUE-DEFINITION"):
        sm.cataloguer([{"metric_id": "x", "unite": "", "version": 1}])


def test_compatible_seulement_meme_metrique_unite_et_version_courante():
    catalogue = sm.cataloguer(_definitions())
    ok = sm.classer(
        {"metric_id": "marge_reelle", "valeur": "1200.50", "unite": "CAD", "version_definition": 2}, catalogue
    )
    assert ok["statut"] == "COMPATIBLE" and ok["proprietaire"] == "m05-financecore" and ok["valeur"] == "1200.50"
    cas = {
        "UNITE_DIVERGENTE": {"metric_id": "ecart_duree", "valeur": "2", "unite": "heures", "version_definition": 1},
        "VERSION_PERIMEE": {"metric_id": "marge_reelle", "valeur": "1", "unite": "CAD", "version_definition": 1},
        "VERSION_NON_DECLAREE": {"metric_id": "marge_reelle", "valeur": "1", "unite": "CAD"},
        "SANS_DEFINITION": {"metric_id": "inventee", "valeur": "9"},
    }
    for statut, observation in cas.items():
        assert sm.classer(observation, catalogue)["statut"] == statut, statut


def test_rapprochement_ne_fusionne_jamais_deux_groupes_et_n_agrege_rien():
    catalogue = sm.cataloguer(_definitions())
    observations = [
        {"metric_id": "marge_reelle", "valeur": "100", "unite": "CAD", "version_definition": 2, "source": "m8:42"},
        {"metric_id": "marge_reelle", "valeur": "250", "unite": "CAD", "version_definition": 2, "source": "m8:43"},
        {"metric_id": "marge_reelle", "valeur": "999", "unite": "CAD", "version_definition": 1, "source": "m8:7"},
        {"metric_id": "ecart_duree", "valeur": "5", "unite": "heures", "version_definition": 1, "source": "m8:9"},
    ]
    resultat = sm.rapprocher(observations, catalogue)
    assert all(groupe["agregable"] is False for groupe in resultat["groupes"])
    comparables = resultat["comparables_ensemble"]
    assert len(comparables) == 1 and [v["valeur"] for v in comparables[0]["valeurs"]] == ["100", "250"]
    assert {e["statut"] for e in resultat["non_comparables"]} == {"VERSION_PERIMEE", "UNITE_DIVERGENTE"}
    assert not any(isinstance(v["valeur"], (int, float)) for g in resultat["groupes"] for v in g["valeurs"])
    assert "total" not in resultat and "moyenne" not in resultat


def test_une_valeur_non_textuelle_est_refusee_pas_convertie():
    catalogue = sm.cataloguer(_definitions())
    with pytest.raises(ValueError, match="REJ-SEMANTIQUE-OBSERVATION"):
        sm.classer({"metric_id": "marge_reelle", "valeur": 100.5}, catalogue)
    with pytest.raises(ValueError, match="REJ-SEMANTIQUE-OBSERVATION"):
        sm.classer({"valeur": "1"}, catalogue)


def test_empreinte_de_definition_face_a_une_version_entiere_n_est_ni_perimee_ni_compatible():
    catalogue = sm.cataloguer(_definitions())
    empreinte = "a" * 64
    res = sm.classer(
        {"metric_id": "marge_reelle", "valeur": "1", "unite": "CAD", "version_definition": empreinte}, catalogue
    )
    assert res["statut"] == "VERSION_NON_COMPARABLE" and res["version_courante"] == 2
    groupes = sm.rapprocher(
        [{"metric_id": "marge_reelle", "valeur": "1", "unite": "CAD", "version_definition": empreinte}], catalogue
    )
    assert groupes["comparables_ensemble"] == [] and "VERSION_NON_COMPARABLE" in sm.STATUTS
    # Une chaîne hexadécimale de longueur différente n'est pas une empreinte : elle reste une version périmée.
    court = sm.classer(
        {"metric_id": "marge_reelle", "valeur": "1", "unite": "CAD", "version_definition": "abc"}, catalogue
    )
    assert court["statut"] == "VERSION_PERIMEE"


def _liaison(metric_id="marge_reelle", revision=2, empreinte="b" * 64):
    return {"metric_id": metric_id, "revision": revision, "empreinte": empreinte}


def _observation(empreinte, metric_id="marge_reelle", unite="CAD"):
    return {"metric_id": metric_id, "valeur": "1", "unite": unite, "version_definition": empreinte}


def test_liaison_fiable_distingue_courante_perimee_et_revision_inconnue():
    catalogue = sm.cataloguer(_definitions())
    liaisons = sm.cataloguer_liaisons(
        [_liaison(revision=2, empreinte="b" * 64), _liaison(revision=1, empreinte="c" * 64),
         _liaison(revision=9, empreinte="d" * 64)],
        catalogue,
    )  # fmt: skip
    courante = sm.classer(_observation("b" * 64), catalogue, liaisons)
    assert courante["statut"] == "COMPATIBLE" and courante["revision_liee"] == 2
    perimee = sm.classer(_observation("c" * 64), catalogue, liaisons)
    assert perimee["statut"] == "VERSION_PERIMEE" and perimee["revision_liee"] == 1 and perimee["version_courante"] == 2
    inconnue = sm.classer(_observation("d" * 64), catalogue, liaisons)
    assert inconnue["statut"] == "VERSION_NON_COMPARABLE" and inconnue["raison"] == "REVISION_INCONNUE_DU_REGISTRE"
    sans = sm.classer(_observation("e" * 64), catalogue, liaisons)
    assert sans["statut"] == "VERSION_NON_COMPARABLE" and sans["raison"] == "AUCUNE_LIAISON"
    assert {inconnue["raison"], sans["raison"]} == sm.RAISONS_NON_COMPARABLE


def test_l_historique_sans_liaison_reste_non_comparable_meme_si_d_autres_metriques_sont_liees():
    catalogue = sm.cataloguer(_definitions())
    liaisons = sm.cataloguer_liaisons([_liaison("marge_reelle", 2, "b" * 64)], catalogue)
    # Même empreinte, autre métrique : la liaison est propre à (métrique, empreinte), elle ne se transpose pas.
    autre = sm.classer(_observation("b" * 64, "ecart_duree", "minutes"), catalogue, liaisons)
    assert autre["statut"] == "VERSION_NON_COMPARABLE" and autre["raison"] == "AUCUNE_LIAISON"
    resultat = sm.rapprocher([_observation("b" * 64), _observation("f" * 64)], catalogue, liaisons)
    assert [e["statut"] for e in resultat["observations"]] == ["COMPATIBLE", "VERSION_NON_COMPARABLE"]
    assert len(resultat["comparables_ensemble"]) == 1 and resultat["comparables_ensemble"][0]["agregable"] is False


def test_liaisons_contradictoires_ou_mal_formees_sont_refusees_jamais_choisies():
    catalogue = sm.cataloguer(_definitions())
    with pytest.raises(ValueError, match="REJ-SEMANTIQUE-LIAISON-CONTRADICTION"):
        sm.cataloguer_liaisons([_liaison(revision=1), _liaison(revision=2)], catalogue)  # même empreinte, 2 révisions
    with pytest.raises(ValueError, match="REJ-SEMANTIQUE-LIAISON-CONTRADICTION"):
        sm.cataloguer_liaisons([_liaison(empreinte="b" * 64), _liaison(empreinte="c" * 64)], catalogue)
    for mauvaise in (
        _liaison(revision=True), _liaison(revision=0), _liaison(revision="2"), _liaison(empreinte="B" * 64),
        _liaison(empreinte="b" * 63), _liaison(metric_id=""), "texte",
    ):  # fmt: skip
        with pytest.raises(ValueError, match="REJ-SEMANTIQUE-LIAISON"):
            sm.cataloguer_liaisons([mauvaise], catalogue)
    # Une liaison identique répétée est idempotente ; celle d'une métrique inconnue du registre est ignorée.
    assert sm.cataloguer_liaisons([_liaison(), _liaison(), _liaison("inconnue")], catalogue) == {
        ("marge_reelle", "b" * 64): 2
    }
