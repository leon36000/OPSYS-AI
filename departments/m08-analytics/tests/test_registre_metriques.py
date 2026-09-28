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


# ---------------------------------------------------------------------------
# T3.1-suite : listage compact et paginé (jamais l'historique complet).
# ---------------------------------------------------------------------------


def test_lister_registre_vide_retourne_une_page_vide():
    resultat = registre_metriques.lister([], limite=10)

    assert resultat == {"definitions": [], "total": 0, "curseur": 0, "curseur_suivant": None}


def test_lister_une_ligne_par_metric_id_jamais_par_version():
    registre = []
    registre_metriques.enregistrer_definition(_definition(), registre)
    registre_metriques.enregistrer_definition(_definition(fraicheur_attendue_jours=5), registre)

    resultat = registre_metriques.lister(registre, limite=10)

    assert resultat["total"] == 1
    assert len(resultat["definitions"]) == 1


def test_lister_projette_les_champs_compacts_et_la_derniere_version():
    registre = []
    registre_metriques.enregistrer_definition(_definition(), registre)
    registre_metriques.enregistrer_definition(_definition(fraicheur_attendue_jours=5), registre)

    resultat = registre_metriques.lister(registre, limite=10)

    assert resultat["definitions"] == [
        {
            "metric_id": "m4_duree_reelle_minutes",
            "departement_proprietaire": "m04-field-ops",
            "unite": "min",
            "fraicheur_attendue_jours": 5,  # la DERNIÈRE version, jamais la première
            "version": 2,
        }
    ]


def test_lister_trie_par_metric_id_ordre_deterministe():
    registre = []
    registre_metriques.enregistrer_definition(_definition(metric_id="zzz"), registre)
    registre_metriques.enregistrer_definition(_definition(metric_id="aaa"), registre)

    resultat = registre_metriques.lister(registre, limite=10)

    assert [d["metric_id"] for d in resultat["definitions"]] == ["aaa", "zzz"]


def test_lister_pagine_avec_curseur_suivant():
    registre = []
    for i in range(3):
        registre_metriques.enregistrer_definition(_definition(metric_id=f"m_{i}"), registre)

    page_1 = registre_metriques.lister(registre, limite=2)
    assert [d["metric_id"] for d in page_1["definitions"]] == ["m_0", "m_1"]
    assert page_1["total"] == 3
    assert page_1["curseur_suivant"] == 2

    page_2 = registre_metriques.lister(registre, limite=2, curseur=page_1["curseur_suivant"])
    assert [d["metric_id"] for d in page_2["definitions"]] == ["m_2"]
    assert page_2["curseur_suivant"] is None


def test_lister_curseur_au_dela_du_total_retourne_une_page_vide_sans_erreur():
    registre = []
    registre_metriques.enregistrer_definition(_definition(), registre)

    resultat = registre_metriques.lister(registre, limite=10, curseur=999)

    assert resultat["definitions"] == []
    assert resultat["curseur_suivant"] is None


@pytest.mark.parametrize("limite", [0, -1])
def test_lister_limite_non_positive_est_refusee(limite):
    with pytest.raises(ValueError, match="limite"):
        registre_metriques.lister([], limite=limite)


def test_lister_curseur_negatif_est_refuse():
    with pytest.raises(ValueError, match="curseur"):
        registre_metriques.lister([], limite=10, curseur=-1)


def test_lister_ne_renvoie_jamais_l_historique_complet():
    """Preuve directe de la contrainte « jamais l'historique complet » : quel que soit le nombre
    de versions enregistrées pour UNE métrique, une seule ligne apparaît dans le listage — même
    quand la limite dépasse largement le nombre de versions."""
    registre = []
    for i in range(5):
        registre_metriques.enregistrer_definition(_definition(fraicheur_attendue_jours=i + 1), registre)

    resultat = registre_metriques.lister(registre, limite=1000)

    assert len(registre) == 5  # l'historique complet existe bien, append-only...
    assert resultat["total"] == 1  # ...mais le listage n'en montre jamais qu'une ligne par métrique
    assert resultat["definitions"][0]["version"] == 5
