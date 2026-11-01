"""Revue adverse (num) : `entrepot._entier` lit un entier ou refuse (`None`), sans jamais lever.

Défaut trouvé : le texte « --5 » passait le contrôle `lstrip("-").isdigit()` (qui retire TOUS les signes) puis
`int("--5")`
levait `ValueError` : une durée mal écrite d'un fait de chantier faisait échouer la construction de l'entrepôt entière.
Les chiffres non ASCII (« ٣ ») étaient lus comme des nombres. Données fictives.
"""

from __future__ import annotations

import pytest
from m8_analytics import entrepot

FICTIF = True


@pytest.mark.parametrize("valeur", ["--5", "-", "", " ", "5-", "+-5", "٣", "１２", "1_000", "5.0", "1e3", "abc", True,
                                    None,
                                    5.0, [], {}])
def test_une_valeur_qui_n_est_pas_un_entier_decimal_est_refusee(valeur):
    assert entrepot._entier(valeur) is None


@pytest.mark.parametrize("valeur, attendu", [(5, 5), (0, 0), (-5, -5), ("5", 5), (" 42 ", 42), ("-7", -7), ("007", 7)])
def test_les_entiers_legitimes_restent_lus(valeur, attendu):
    assert entrepot._entier(valeur) == attendu
