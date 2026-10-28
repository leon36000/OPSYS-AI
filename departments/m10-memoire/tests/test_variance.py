import pytest
from m10_memoire import registre, variance

HORODATAGE = "2026-09-15T14:00:00-04:00"


def _variance(evenement_id="EVT-VAR-001", wct_id="WCT-001", **overrides):
    base = {
        "evenement_id": evenement_id,
        "wct_id": wct_id,
        "intervention_id": "INT-001",
        "chantier_id": "CH-001",
        "statut_variance": "evaluee",
        "signal_critique": True,
        "seuil_pourcentage": 0.1,
        "horodatage_completion": HORODATAGE,
        "lignes": [
            {
                "materiau": "bardeau",
                "unite": "boite",
                "quantite_prevue": "10",
                "quantite_reelle": "13",
                "ecart_pourcentage": "0.3",
                "critique": True,
            }
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def registre_cible():
    return registre.Registre()


def test_memoriser_variance_ecrit_un_evenement_memorise(registre_cible):
    maillon, code = variance.memoriser_variance(_variance(), registre_cible)

    assert code is None
    assert maillon["type_entree"] == "evenement_memorise"
    assert maillon["ligne_id"]
    assert len(registre_cible.lire()) == 1


def test_memoriser_variance_conserve_la_charge_telle_quelle(registre_cible):
    charge = _variance()

    maillon, _ = variance.memoriser_variance(charge, registre_cible)

    for champ, valeur in charge.items():
        assert maillon[champ] == valeur


def test_memoriser_variance_utilise_horodatage_completion_comme_horodatage_du_maillon(registre_cible):
    maillon, _ = variance.memoriser_variance(_variance(), registre_cible)
    assert maillon["horodatage"] == HORODATAGE


def test_memoriser_variance_chaine_deux_maillons_successifs(registre_cible):
    premier, _ = variance.memoriser_variance(_variance(evenement_id="EVT-1"), registre_cible)
    second, _ = variance.memoriser_variance(_variance(evenement_id="EVT-2"), registre_cible)

    assert second["precedent_ligne_id"] == premier["ligne_id"]
    assert registre_cible.valider_chaine() == (True, "")


@pytest.mark.parametrize("statut", ["declaration_absente", "unites_indeterminees"])
def test_memoriser_variance_avec_signal_critique_null_est_conserve(registre_cible, statut):
    """statut_variance != evaluee : signal_critique doit rester null, jamais un booléen inventé
    (catalogue socle) — M10 le reproduit tel quel, sans jamais le coercer."""
    maillon, _ = variance.memoriser_variance(
        _variance(statut_variance=statut, signal_critique=None, lignes=None),
        registre_cible,
    )

    assert maillon["signal_critique"] is None
    assert maillon["lignes"] is None


def test_memoriser_variance_dans_deux_registres_distincts_ne_les_affecte_pas_mutuellement():
    registre_evenements = registre.Registre()
    registre_affaires = registre.Registre()

    maillon_evenements, _ = variance.memoriser_variance(_variance(), registre_evenements)
    maillon_affaires, _ = variance.memoriser_variance(_variance(evenement_id="EVT-002"), registre_affaires)

    assert len(registre_evenements.lire()) == 1
    assert len(registre_affaires.lire()) == 1
    assert maillon_evenements != maillon_affaires
