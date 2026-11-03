"""C5 — tests tueurs de mutants de `details_reception.py` (aucune ligne de code source changée).

Chaque test vise une borne exacte que la suite C5 ne touchait pas : quantité reçue absente
(zéro, pas un), écart exactement nul d'un côté et non nul de l'autre, écart positif sous un.
Données fictives, décimales exactes ; aucun service externe.
"""
from m6_material_control import details_reception

PHOTO = "fichier:sha256:" + "ab" * 32


def _verdict(commandees, recues, details=None):
    return details_reception.qualifier_livraison(commandees, recues, details or [])


def test_ligne_commandee_absente_des_receptions_compte_zero_exact():
    """Tuer `recues.get(materiau_id, 0)` -> `1` (ligne 120) : le défaut est zéro, pas un.

    Le matériau commandé n'apparaît pas du tout dans les lignes reçues : la réception vaut
    zéro exactement (écart -10), jamais une unité inventée qui réduirait le manquant.
    """
    verdict = _verdict(
        [{"materiau_id": "gouttiere-5po-fictive", "quantite_demandee": 10.0}],
        [],
        [{"materiau_id": "gouttiere-5po-fictive", "statut_ligne": "manquant"}],
    )
    ligne = verdict["lignes"][0]
    assert ligne["quantite_recue"] == 0.0
    assert ligne["ecart"] == -10.0
    assert verdict["verdict_reception"] == "RECEPTION_INFERIEURE"


def test_ecart_zero_et_positif_donne_superieure_pas_mixte():
    """Tuer `e < 0` -> `e <= 0`, `e > 0` -> `e > 1` et `0` -> `1` (ligne 139/143).

    Écarts exactement [0, +1] : aucun manquant, donc SUPERIEURE. Un `<=` transformerait le zéro
    en manquant et fabriquerait un MIXTE ; un seuil `> 1` perdrait le +1 et dirait CONFORME.
    """
    verdict = _verdict(
        [
            {"materiau_id": "a-fictif", "quantite_demandee": 10.0},
            {"materiau_id": "b-fictif", "quantite_demandee": 10.0},
        ],
        [
            {"materiau_id": "a-fictif", "quantite_recue": 10.0},
            {"materiau_id": "b-fictif", "quantite_recue": 11.0},
        ],
    )
    assert [ligne["ecart"] for ligne in verdict["lignes"]] == [0.0, 1.0]
    assert verdict["verdict_reception"] == "RECEPTION_SUPERIEURE"


def test_ecart_zero_et_negatif_donne_inferieure_pas_mixte():
    """Tuer `e > 0` -> `e >= 0` (ligne 139) : le zéro n'est pas un surplus.

    Écarts exactement [0, -1] : un `>=` compterait le zéro comme surplus et fabriquerait un
    MIXTE au lieu de la réception inférieure.
    """
    verdict = _verdict(
        [
            {"materiau_id": "a-fictif", "quantite_demandee": 10.0},
            {"materiau_id": "b-fictif", "quantite_demandee": 10.0},
        ],
        [
            {"materiau_id": "a-fictif", "quantite_recue": 10.0},
            {"materiau_id": "b-fictif", "quantite_recue": 9.0},
        ],
    )
    assert [ligne["ecart"] for ligne in verdict["lignes"]] == [0.0, -1.0]
    assert verdict["verdict_reception"] == "RECEPTION_INFERIEURE"


def test_ecart_positif_inferieur_a_un_reste_un_mixte():
    """Tuer `e > 0` -> `e > 1` (ligne 139) : un surplus de 0,5 est un surplus.

    Écarts exactement [-1, +0,5] : un seuil à 1 perdrait le demi-surplus et conclurait à tort
    INFERIEURE au lieu de MIXTE.
    """
    verdict = _verdict(
        [
            {"materiau_id": "a-fictif", "quantite_demandee": 10.0},
            {"materiau_id": "b-fictif", "quantite_demandee": 10.0},
        ],
        [
            {"materiau_id": "a-fictif", "quantite_recue": 9.0},
            {"materiau_id": "b-fictif", "quantite_recue": 10.5},
        ],
    )
    assert [ligne["ecart"] for ligne in verdict["lignes"]] == [-1.0, 0.5]
    assert verdict["verdict_reception"] == "RECEPTION_MIXTE"


def test_prix_prevu_ou_prix_bl_absent_reste_silencieux_des_deux_cotes():
    """Documente l'équivalence de `or` -> `and` (ligne 172) : les deux `None` se taisent.

    `str(None)` vaut « None », que `Fraction` refuse (ValueError rattrapée) : le mutant `and`
    entre dans le `try` puis sort par la même porte. Comportement observable identique, aucun
    signal inventé, rien à tuer.
    """
    lignes = [
        {"materiau_id": "a-fictif", "prix_unitaire_prevu": None},
        {"materiau_id": "b-fictif", "prix_unitaire_prevu": "10.00"},
    ]
    assert details_reception.detecter_ecarts_prix_bl(
        lignes, {"a-fictif": "12.00"}, seuil_pourcentage=0.15) == []
    assert details_reception.detecter_ecarts_prix_bl(
        lignes, {"b-fictif": None}, seuil_pourcentage=0.15) == []


def test_endommage_photo_cas_exacte_acceptee():
    """Borne de format : 64 hexadécimaux exactement, pas 63 ni 65."""
    ok, code = details_reception.valider_details(
        [{"materiau_id": "a-fictif", "statut_ligne": "endommage", "photos": [PHOTO]}]
    )
    assert code is None and ok is not None
    for photo in ("fichier:sha256:" + "ab" * 31, "fichier:sha256:" + "ab" * 32 + "c"):
        _, code = details_reception.valider_details(
            [{"materiau_id": "a-fictif", "statut_ligne": "endommage", "photos": [photo]}]
        )
        assert code == "REJ-RECEPTION-PREUVE-MANQUANTE"
