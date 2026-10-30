"""Contrats attendus des propriétaires : forme exigée, absence nommée, aucune valeur fabriquée (fictif)."""

import pytest
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import contrats_attendus as ca
from m9_strategic_intelligence import tendances

FICTIF = True


def _capacite():
    return {
        "semaine_debut": "2026-11-02",
        "calculable": True,
        "manque": [],
        "equipes": [{"equipe_id": "equipe-a", "heures_disponibles": "120.5", "heures_planifiees": "98"}],
    }


def _depenses():
    return {
        "debut": "2026-10-01",
        "fin": "2026-10-31",
        "couverture": "PARTIELLE",
        "manque": ["CANAL_NON_RAPPORTE"],
        "lignes": [{"canal": "recherche", "montant_cad": "450.00", "constate_le": "2026-10-15", "source_ref": "ref:7"}],
    }


def _plaintes():
    return {
        "debut": "2026-10-01",
        "fin": "2026-10-31",
        "ouvertes_total": 3,
        "manque": [],
        "categories": [{"categorie": "garantie", "ouvertes": 2}, {"categorie": "degat", "ouvertes": 1}],
    }


def _liaisons():
    return {"liaisons_versions": [{"metric_id": "m8_marge_reelle_cad", "revision": 2, "empreinte": "a" * 64}]}


EXEMPLES = {
    "capacite_equipe": _capacite,
    "depenses_marketing": _depenses,
    "plaintes_structurees": _plaintes,
    "liaisons_versions": _liaisons,
}


def test_chaque_contrat_a_un_exemple_conforme_et_un_proprietaire_connu():
    assert set(EXEMPLES) == set(ca.CONTRATS)
    for domaine, fabrique in EXEMPLES.items():
        verdict = ca.valider_charge(domaine, fabrique())
        assert verdict["conforme"] is True and verdict["manques"] == [] and verdict["erreurs"] == [], domaine
        proprietaires = {"m01-front-office", "m04-field-ops", "m07-marketing", "m08-analytics"}
        assert ca.CONTRATS[domaine]["proprietaire"] in proprietaires


def test_un_champ_absent_est_nomme_jamais_complete():
    for domaine, fabrique in EXEMPLES.items():
        charge = fabrique()
        champ = next(iter(charge))
        del charge[champ]
        verdict = ca.valider_charge(domaine, charge)
        assert verdict["conforme"] is False and champ in verdict["manques"], domaine
        assert champ not in charge  # le validateur ne complète rien
    ligne = _depenses()
    del ligne["lignes"][0]["montant_cad"]
    assert ca.valider_charge("depenses_marketing", ligne)["manques"] == ["lignes[0].montant_cad"]


def test_un_flottant_un_enum_hors_liste_une_charge_non_objet_sont_refuses():
    flottant = _depenses()
    flottant["lignes"][0]["montant_cad"] = 450.0
    assert "lignes[0].montant_cad : decimal attendu" in ca.valider_charge("depenses_marketing", flottant)["erreurs"]
    categorie = _plaintes()
    categorie["categories"][0]["categorie"] = "inventee"
    assert ca.valider_charge("plaintes_structurees", categorie)["conforme"] is False
    booleen = _capacite()
    booleen["equipes"][0]["heures_disponibles"] = True
    assert ca.valider_charge("capacite_equipe", booleen)["conforme"] is False
    entier_bool = _plaintes()
    entier_bool["ouvertes_total"] = True
    assert ca.valider_charge("plaintes_structurees", entier_bool)["conforme"] is False
    couverture = _depenses()
    couverture["couverture"] = "TOTALE"
    assert ca.valider_charge("depenses_marketing", couverture)["conforme"] is False
    for pas_objet in (None, [], "texte", 3):
        assert ca.valider_charge("capacite_equipe", pas_objet)["conforme"] is False
    empreinte = _liaisons()
    empreinte["liaisons_versions"][0]["empreinte"] = "A" * 64
    assert ca.valider_charge("liaisons_versions", empreinte)["conforme"] is False
    revision = _liaisons()
    revision["liaisons_versions"][0]["revision"] = 0
    assert ca.valider_charge("liaisons_versions", revision)["conforme"] is False


def test_les_trois_lectures_manquantes_sont_absentes_du_catalogue_et_dites_telles():
    """Le jour où un propriétaire publie la lecture, ce test échoue : c'est le signal de brancher le consommateur."""
    etats = {r["domaine"]: r["etat"] for r in ca.resume()}
    assert etats["capacite_equipe"] == etats["depenses_marketing"] == etats["plaintes_structurees"]
    assert etats["capacite_equipe"] == "ABSENT_CHEZ_LE_PROPRIETAIRE"
    assert etats["liaisons_versions"] == "CHAMP_NON_VERIFIE_CHEZ_LE_PROPRIETAIRE"
    for domaine in ("capacite_equipe", "depenses_marketing", "plaintes_structurees"):
        assert ca.CONTRATS[domaine]["lecture_id"] not in cat.PAR_ID, domaine
    assert all(r["limite"] and r["outil_attendu"] for r in ca.resume())


def test_une_extrapolation_de_m9_n_est_jamais_une_prevision_de_proprietaire():
    assert tendances.ORIGINE == ca.ORIGINE_EXTRAPOLATION
    extrapolation = {"origine": tendances.ORIGINE, "methodes": []}
    with pytest.raises(ValueError, match="REJ-CONTRAT-EXTRAPOLATION"):
        ca.refuser_extrapolation(extrapolation, presentee_comme_prevision_de_proprietaire=True)
    # Dite pour ce qu'elle est, elle passe ; une vraie prévision de propriétaire n'est pas visée.
    ca.refuser_extrapolation(extrapolation, presentee_comme_prevision_de_proprietaire=False)
    ca.refuser_extrapolation({"prevision_id": "a" * 64}, presentee_comme_prevision_de_proprietaire=True)


def _erreurs(domaine, charge):
    verdict = ca.valider_charge(domaine, charge)
    assert verdict["conforme"] is False, (domaine, charge)
    return " | ".join(verdict["erreurs"])


def test_types_non_hachables_dates_impossibles_et_negatifs_sont_des_erreurs_nommees():
    """Défauts trouvés en relecture : TypeError non nommée, dates impossibles et montants négatifs acceptés."""
    couverture = _depenses()
    couverture["couverture"] = []
    assert "couverture" in _erreurs("depenses_marketing", couverture)
    categorie = _plaintes()
    categorie["categories"][0]["categorie"] = {"x": 1}
    assert "categorie" in _erreurs("plaintes_structurees", categorie)
    for date in ("2026-99-99", "0000-00-00", "2026-02-30"):
        impossible = _depenses()
        impossible["debut"] = date
        assert "debut" in _erreurs("depenses_marketing", impossible), date
    negatif = _depenses()
    negatif["lignes"][0]["montant_cad"] = "-450"
    assert "montant_cad" in _erreurs("depenses_marketing", negatif)
    heures = _capacite()
    heures["equipes"][0]["heures_disponibles"] = "-5"
    assert "heures_disponibles" in _erreurs("capacite_equipe", heures)
    octets = _capacite()
    octets["manque"] = b""
    assert "manque" in _erreurs("capacite_equipe", octets)


def test_incoherences_entre_champs_sont_des_erreurs_nommees():
    inverse = _depenses()
    inverse["debut"], inverse["fin"] = "2026-10-31", "2026-10-01"
    assert "fin antérieure au début" in _erreurs("depenses_marketing", inverse)
    hors_periode = _depenses()
    hors_periode["lignes"][0]["constate_le"] = "2026-11-02"
    assert "hors de la période" in _erreurs("depenses_marketing", hors_periode)
    partielle = _depenses()
    partielle["manque"] = []
    assert "sans manque nommé" in _erreurs("depenses_marketing", partielle)
    doublon = _plaintes()
    doublon["categories"][1]["categorie"] = "garantie"
    assert "catégorie en double" in _erreurs("plaintes_structurees", doublon)
    total = _plaintes()
    total["ouvertes_total"] = 99
    assert "somme des catégories" in _erreurs("plaintes_structurees", total)
    calcul = _capacite()
    calcul["calculable"] = False
    assert "sans manque nommé" in _erreurs("capacite_equipe", calcul)
    equipes = _capacite()
    equipes["equipes"].append(dict(equipes["equipes"][0]))
    assert "equipe_id en double" in _erreurs("capacite_equipe", equipes)
    contradiction = _liaisons()
    contradiction["liaisons_versions"].append(
        {"metric_id": "m8_marge_reelle_cad", "revision": 3, "empreinte": "a" * 64}
    )
    assert "deux révisions" in _erreurs("liaisons_versions", contradiction)
    revision = _liaisons()
    revision["liaisons_versions"].append({"metric_id": "m8_marge_reelle_cad", "revision": 2, "empreinte": "b" * 64})
    assert "deux empreintes" in _erreurs("liaisons_versions", revision)
