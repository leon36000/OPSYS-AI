import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import digest, xmr


def _signal_superieur():
    return xmr.detecter_signal("haut", [10.0, 10.0, 10.0, 10.0, 50.0], 3)


def _signal_inferieur():
    return xmr.detecter_signal("bas", [10.0, 10.0, 10.0, 10.0, -30.0], 3)


def _signal_insuffisant():
    return xmr.detecter_signal("court", [10.0, 20.0], 5)


def test_produire_digest_quotidien_retourne_un_contrat_complet_avec_un_signal_actif():
    signal = _signal_superieur()

    resultat = digest.produire_digest_quotidien([signal])

    assert set(resultat) == {
        "type",
        "nb_signaux_actifs",
        "signaux_actifs",
        "hash_digest",
    }
    assert resultat["type"] == "DIGEST_ANALYTICS"
    assert resultat["nb_signaux_actifs"] == 1
    assert resultat["signaux_actifs"] == [signal]
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
