import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import registre_metriques  # noqa: E402


def _definition(**remplacements):
    base = {
        "metric_id": "m4_duree_reelle_minutes",
        "departement_proprietaire": "m04-field-ops",
        "unite": "min",
        "source": "Module M4 — WCT",
        "fraicheur_attendue_jours": 2,
        "regles_qualite": {"plage_min": 0, "plage_max": None},
    }
    base.update(remplacements)
    return base


def test_enregistrer_definition_valide_est_acceptee_et_resoluble():
    registre = []

    reponse = registre_metriques.enregistrer_definition(_definition(), registre)

    assert reponse == {"enregistree": True, "deja_a_jour": False, "verdict": None}
    assert len(registre) == 1
    assert registre_metriques.resoudre("m4_duree_reelle_minutes", registre) == _definition()


def test_enregistrer_definition_est_idempotent_ne_fait_pas_grossir_le_registre():
    registre = []
    registre_metriques.enregistrer_definition(_definition(), registre)

    reponse = registre_metriques.enregistrer_definition(_definition(), registre)

    assert reponse == {"enregistree": True, "deja_a_jour": True, "verdict": None}
    assert len(registre) == 1


def test_enregistrer_definition_idempotent_entrelace_avec_une_autre_metrique():
    """L'idempotence ne compare que la DERNIÈRE version du MÊME metric_id — une autre métrique
    enregistrée entre les deux appels ne casse pas la déduplication."""
    registre = []
    registre_metriques.enregistrer_definition(_definition(), registre)
    registre_metriques.enregistrer_definition(_definition(metric_id="autre_metrique"), registre)

    reponse = registre_metriques.enregistrer_definition(_definition(), registre)

    assert reponse["deja_a_jour"] is True
    assert len(registre) == 2


def test_enregistrer_definition_modifiee_ajoute_une_nouvelle_version_jamais_un_ecrasement():
    registre = []
    registre_metriques.enregistrer_definition(_definition(fraicheur_attendue_jours=2), registre)

    reponse = registre_metriques.enregistrer_definition(_definition(fraicheur_attendue_jours=5), registre)

    assert reponse == {"enregistree": True, "deja_a_jour": False, "verdict": None}
    # Append-only : les DEUX versions restent lisibles dans l'historique...
    assert len(registre) == 2
    assert registre[0]["fraicheur_attendue_jours"] == 2
    # ... mais resoudre() renvoie toujours la DERNIÈRE.
    assert registre_metriques.resoudre("m4_duree_reelle_minutes", registre)["fraicheur_attendue_jours"] == 5


def test_resoudre_metric_id_jamais_enregistre_est_none_fail_closed():
    assert registre_metriques.resoudre("inconnu", []) is None


def test_resoudre_renvoie_une_copie_independante_du_registre():
    registre = []
    registre_metriques.enregistrer_definition(_definition(), registre)

    resolue = registre_metriques.resoudre("m4_duree_reelle_minutes", registre)
    resolue["regles_qualite"]["plage_min"] = -999

    assert registre[0]["regles_qualite"]["plage_min"] == 0


@pytest.mark.parametrize(
    "definition_invalide",
    [
        {},
        "pas un dict",
        None,
        _definition(**{"champ_en_trop": "x"}),
        {cle: v for cle, v in _definition().items() if cle != "source"},
    ],
    ids=["dict_vide", "texte", "none", "champ_en_trop", "champ_manquant"],
)
def test_enregistrer_definition_structure_invalide_est_refusee(definition_invalide):
    registre = []

    reponse = registre_metriques.enregistrer_definition(definition_invalide, registre)

    assert reponse["enregistree"] is False
    assert reponse["verdict"] == "REJ-DEFINITION-STRUCTURE-INVALIDE"
    assert registre == []


def test_enregistrer_definition_departement_inconnu_est_refusee_nommement():
    registre = []

    reponse = registre_metriques.enregistrer_definition(
        _definition(departement_proprietaire="m99-invente"), registre
    )

    assert reponse["enregistree"] is False
    assert reponse["verdict"] == "REJ-DEFINITION-DEPARTEMENT-INCONNU:'m99-invente'"
    assert registre == []


@pytest.mark.parametrize("unite", ["USD", "usd", "EUR/lead"])
def test_enregistrer_definition_devise_non_cad_est_refusee_par_le_meme_dictionnaire_que_t3_4(unite):
    """« unité validée par le dictionnaire » (T3.1) : registre_metriques réutilise
    dictionnaire.devise_non_autorisee, la même règle que T3.4 — pas une seconde implémentation
    qui pourrait diverger."""
    registre = []

    reponse = registre_metriques.enregistrer_definition(_definition(unite=unite), registre)

    assert reponse["enregistree"] is False
    assert reponse["verdict"].startswith("REJ-DEFINITION-DEVISE-NON-AUTORISEE:")
    assert registre == []


@pytest.mark.parametrize("unite", ["CAD", "CAD/lead", "min", "%", "ratio"])
def test_enregistrer_definition_unite_valide_est_acceptee(unite):
    registre = []

    reponse = registre_metriques.enregistrer_definition(_definition(unite=unite), registre)

    assert reponse["enregistree"] is True


@pytest.mark.parametrize("fraicheur", [0, -1, -0.5, "2", True, None])
def test_enregistrer_definition_fraicheur_attendue_invalide_est_refusee(fraicheur):
    registre = []

    reponse = registre_metriques.enregistrer_definition(
        _definition(fraicheur_attendue_jours=fraicheur), registre
    )

    assert reponse["enregistree"] is False
    assert reponse["verdict"] == "REJ-DEFINITION-FRAICHEUR-ATTENDUE-INVALIDE"


@pytest.mark.parametrize(
    "regles_qualite",
    [
        {"plage_min": 0},  # clé manquante
        {"plage_min": 0, "plage_max": 10, "extra": 1},  # clé en trop
        {"plage_min": "zero", "plage_max": None},  # type invalide
        {"plage_min": 10, "plage_max": 0},  # min > max
        {"plage_min": True, "plage_max": None},  # bool n'est pas un nombre valide ici
        "pas un dict",
    ],
)
def test_enregistrer_definition_regles_qualite_invalides_sont_refusees(regles_qualite):
    registre = []

    reponse = registre_metriques.enregistrer_definition(
        _definition(regles_qualite=regles_qualite), registre
    )

    assert reponse["enregistree"] is False
    assert reponse["verdict"] == "REJ-DEFINITION-REGLES-QUALITE-INVALIDES"


def test_enregistrer_definition_regles_qualite_sans_aucune_borne_est_valide():
    registre = []

    reponse = registre_metriques.enregistrer_definition(
        _definition(regles_qualite={"plage_min": None, "plage_max": None}), registre
    )

    assert reponse["enregistree"] is True


def test_enregistrer_definition_regles_qualite_bornes_egales_est_valide():
    registre = []

    reponse = registre_metriques.enregistrer_definition(
        _definition(regles_qualite={"plage_min": 5, "plage_max": 5}), registre
    )

    assert reponse["enregistree"] is True
