"""C6 — tests tueurs de mutants de `achats_terrain.py` (aucune ligne de code source changée).

Les trois survivants mesurés remplacent un zéro par un un : montant, quantité et plafond
strictement positifs mais inférieurs à 1 $. Chaque test fixe la borne exacte (0,50 $, 1,00 $)
avec le texte décimal, sans flottant pour l'argent.
"""
from m6_material_control import achats_terrain


def _achat(**champs):
    base = {
        "materiau_id": "scellant-fictif",
        "quantite": 3.0,
        "montant": "25.50",
        "devise": "CAD",
        "fournisseur": "Quincaillerie Fictive",
        "raison": "urgence chantier",
        "chantier_id": "CH-FICT-1",
        "recu": "fichier:sha256:" + "ab" * 32,
    }
    base.update(champs)
    return base


def test_montant_positif_sous_un_dollar_accepte_exactement():
    """Tuer `montant <= 0` -> `montant <= 1` (ligne 44) : 0,50 $ est un montant valide."""
    achat, code = achats_terrain.valider_achat(_achat(montant="0.50"))
    assert code is None
    assert achat is not None and achat["montant"] == "0.50"
    # 0 et négatif restent refusés : la borne basse ne bouge pas.
    for montant in ("0", "0.00", "-0.50"):
        assert achats_terrain.valider_achat(_achat(montant=montant))[1] == \
            "REJ-ACHAT-TERRAIN-MONTANT-INVALIDE"


def test_quantite_positive_jusqua_un_acceptee_borne_incluse():
    """Tuer `quantite <= 0` -> `quantite <= 1` (ligne 64) : 0,5 et 1,0 sont des quantités."""
    for quantite in (0.5, 1, 1.0):
        achat, code = achats_terrain.valider_achat(_achat(quantite=quantite))
        assert code is None, repr(quantite)
        assert achat is not None and achat["quantite"] == quantite
    # Juste sous zéro et zéro restent refusés.
    for quantite in (0, 0.0, -0.5):
        assert achats_terrain.valider_achat(_achat(quantite=quantite))[1] == \
            "REJ-ACHAT-TERRAIN-QUANTITE-INVALIDE", repr(quantite)


def test_plafond_positif_sous_un_dollar_reste_un_plafond_valide():
    """Tuer `candidat > 0` -> `candidat > 1` (ligne 97) : un plafond de 0,50 $ décide.

    À 0,25 $ accepté, à 0,50 $ (borne incluse) accepté, à 0,51 $ attente N3 : un plafond
    sous 1 $ n'est ni absent ni illisible.
    """
    for montant, statut in (("0.25", "accepte"), ("0.50", "accepte"), ("0.51", "en_attente_approbation")):
        achat, code = achats_terrain.valider_achat(_achat(montant=montant))
        assert code is None, montant
        decision = achats_terrain.decider(achat, plafond="0.50")
        assert decision["statut"] == statut, montant


def test_plafond_un_dollar_exact_accepte_la_borne():
    """Borne haute exacte de `<=` : 1,00 $ sous un plafond de 1 $ est accepté."""
    achat, code = achats_terrain.valider_achat(_achat(montant="1.00"))
    assert code is None
    assert achats_terrain.decider(achat, plafond="1")["statut"] == "accepte"
    achat, code = achats_terrain.valider_achat(_achat(montant="1.01"))
    assert code is None
    decision = achats_terrain.decider(achat, plafond="1")
    assert decision["statut"] == "en_attente_approbation"
    assert decision["motif"] == "plafond_depasse"


def test_plafond_zero_negatif_reste_absent_fail_closed():
    """Un plafond nul ou négatif n'est pas un plafond : attente, aucune valeur de repli."""
    achat, _ = achats_terrain.valider_achat(_achat(montant="0.25"))
    for plafond in ("0", "0.00", "-0.50"):
        decision = achats_terrain.decider(achat, plafond=plafond)
        assert decision["statut"] == "en_attente_approbation", plafond
        assert decision["motif"] == "plafond_absent", plafond
