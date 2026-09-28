import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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
