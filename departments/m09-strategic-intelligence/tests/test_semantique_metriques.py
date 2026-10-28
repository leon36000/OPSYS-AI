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
