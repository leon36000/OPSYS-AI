import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import conformite, digest, encodage, registre as registre_module


def _ajouter(registre, mouvement):
    maillon, erreur = registre.ajouter(mouvement)
    assert erreur is None
    assert maillon is not None


def test_produire_digest_quotidien_retourne_la_forme_exacte_du_contrat_simple():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": -2.0,
            "cout_unitaire": None,
        },
    )

    variances_significatives = [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE",
            "ecart": -2.0,
        }
    ]
    hash_digest = encodage.empreinte(
        "DIGEST_MATERIEL",
        1,
        0,
        variances_significatives,
        [],
    )

    assert digest.produire_digest_quotidien(registre, []) == {
        "type": "DIGEST_MATERIEL",
        "nb_variances_stock": 1,
        "nb_reorders_suggeres": 0,
        "variances_significatives": variances_significatives,
        "reorders": [],
        "hash_digest": hash_digest,
    }


def test_produire_digest_quotidien_derive_les_verdicts_pour_les_trois_signes():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C0",
            "materiau_id": "MAT-0",
            "quantite": 0.0,
            "cout_unitaire": None,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": -1.0,
            "cout_unitaire": None,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C2",
            "materiau_id": "MAT-2",
            "quantite": 3.0,
            "cout_unitaire": None,
        },
    )

    resultat = digest.produire_digest_quotidien(registre, [])

    assert resultat["variances_significatives"][0] == {
        "chantier_id": "C0",
        "materiau_id": "MAT-0",
        "verdict_variance": "AUCUN_ECART",
        "ecart": 0.0,
    }
    assert resultat["variances_significatives"][1] == {
        "chantier_id": "C1",
        "materiau_id": "MAT-1",
        "verdict_variance": "STOCK_INFERIEUR_AU_THEORIQUE",
        "ecart": -1.0,
    }
    assert resultat["variances_significatives"][2] == {
        "chantier_id": "C2",
        "materiau_id": "MAT-2",
        "verdict_variance": "STOCK_SUPERIEUR_AU_THEORIQUE",
        "ecart": 3.0,
    }


def test_produire_digest_quotidien_recalcule_les_reorders_independamment_des_variances():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "C1",
            "materiau_id": "MAT-2",
            "quantite": 5.0,
            "cout_unitaire": 10.0,
        },
    )
    seuils = [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-2",
            "seuil_quantite": 8.0,
        }
    ]

    resultat = digest.produire_digest_quotidien(registre, seuils)

    assert resultat["nb_variances_stock"] == 0
    assert resultat["nb_reorders_suggeres"] == 1
    assert resultat["reorders"] == [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-2",
            "quantite_suggeree": 3.0,
        }
    ]


def test_produire_digest_quotidien_est_silencieux_si_stock_au_dessus_du_seuil():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "C1",
            "materiau_id": "MAT-2",
            "quantite": 5.0,
            "cout_unitaire": 10.0,
        },
    )
    seuils = [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-2",
            "seuil_quantite": 2.0,
        }
    ]

    resultat = digest.produire_digest_quotidien(registre, seuils)

    assert resultat["reorders"] == []
    assert resultat["nb_reorders_suggeres"] == 0


def test_produire_digest_quotidien_utilise_deux_sources_independantes():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": 2.0,
            "cout_unitaire": 10.0,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C2",
            "materiau_id": "MAT-2",
            "quantite": -1.0,
            "cout_unitaire": None,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C3",
            "materiau_id": "MAT-3",
            "quantite": 1.0,
            "cout_unitaire": None,
        },
    )
    seuils = [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "seuil_quantite": 5.0,
        }
    ]

    resultat = digest.produire_digest_quotidien(registre, seuils)

    assert resultat["nb_variances_stock"] == 2
    assert resultat["nb_reorders_suggeres"] >= 1


def test_produire_digest_quotidien_est_deterministe_bit_a_bit():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": 5.0,
            "cout_unitaire": 10.0,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "CONSOMMATION",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": 1.0,
            "cout_unitaire": None,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": -2.0,
            "cout_unitaire": None,
        },
    )
    seuils_1 = [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "seuil_quantite": 8.0,
        }
    ]
    seuils_2 = [
        {
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "seuil_quantite": 8.0,
        }
    ]

    resultat_1 = digest.produire_digest_quotidien(registre, seuils_1)
    resultat_2 = digest.produire_digest_quotidien(registre, seuils_2)

    assert resultat_1 == resultat_2


def test_produire_digest_quotidien_ne_modifie_jamais_le_registre():
    registre = registre_module.Registre()
    _ajouter(
        registre,
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": 5.0,
            "cout_unitaire": 10.0,
        },
    )
    _ajouter(
        registre,
        {
            "type_mouvement": "VARIANCE_INVENTAIRE",
            "chantier_id": "C1",
            "materiau_id": "MAT-1",
            "quantite": -1.0,
            "cout_unitaire": None,
        },
    )
    avant = registre.lire()

    digest.produire_digest_quotidien(
        registre,
        [
            {
                "chantier_id": "C1",
                "materiau_id": "MAT-1",
                "seuil_quantite": 8.0,
            }
        ],
    )

    assert registre.lire() == avant


def test_produire_digest_quotidien_accepte_registre_et_seuils_vides():
    registre = registre_module.Registre()

    resultat = digest.produire_digest_quotidien(registre, [])

    assert resultat["nb_variances_stock"] == 0
    assert resultat["nb_reorders_suggeres"] == 0
    assert resultat["variances_significatives"] == []
    assert resultat["reorders"] == []
    assert resultat["type"] == "DIGEST_MATERIEL"
    assert isinstance(resultat["hash_digest"], str)
    assert len(resultat["hash_digest"]) == 64
    assert all(caractere in "0123456789abcdef" for caractere in resultat["hash_digest"])


def test_digest_ne_introduit_ni_horloge_ni_alea_ni_reseau():
    resultat = conformite.verifier_conformite(_SRC / "m6_material_control")

    assert resultat["conforme"] is True
