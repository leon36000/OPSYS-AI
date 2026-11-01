"""Revue adverse (num) : la variance de chantier se calcule en décimal EXACT (`variance_chantier.py`).

Défauts trouvés : les quantités (nombres JSON, donc float) étaient additionnées et soustraites en flottant :
- un écart d'exactement 10 % (3,0 prévu, 3,3 réel) donnait un ratio de 0,09999999999999994 : « atteint ou dépasse le
  seuil de 10 % » n'était pas déclenché, donc AUCUN signal de variance critique (le chantier restait sans alerte) ;
- 0,1 + 0,2 déclarés contre 0,3 estimé donnaient un écart de 5,5e-17 : un faux verdict « ECART_REEL_SUPERIEUR » qui
  EXIGE une classification humaine, pour une quantité pourtant égale à l'estimée.
Les sommes et différences se font maintenant en `Decimal(str(x))` (comme `stock.py`) ; le contrat de sortie (float) est
inchangé. Données fictives.
"""

from __future__ import annotations

import pytest
from m6_material_control import variance_chantier as vc
from m6_material_control.registre import Registre

FICTIF = True


def _evaluer(estimee, declarees, seuil):
    besoins = [{"materiau_id": "M1", "quantite_estimee": estimee, "unite": "pi"}]
    lignes = [{"type_ligne": "prevu", "materiau_id": "M1", "quantite": q, "unite": "pi", "quantite_estimee": estimee}
              for q in declarees]
    resultat, code = vc.evaluer("C1", besoins, lignes, seuil)
    assert code is None, code
    return resultat["verdicts_materiaux"][0], resultat["signal_variance_critique"]


@pytest.mark.parametrize("estimee, declarees, seuil", [
    (3.0, [3.3], 0.1),   # +10 % exactement
    (3.0, [2.7], 0.1),   # -10 % exactement
    (0.7, [0.77], 0.1),
    (10.0, [11.0], 0.1),
    (5.0, [5.5], 0.1),
    (1.5, [1.65], 0.1),
    (0.3, [0.33], 0.1),
    (6.0, [7.2], 0.2),
])
def test_un_ecart_exactement_au_seuil_declenche_le_signal(estimee, declarees, seuil):
    verdict, signal = _evaluer(estimee, declarees, seuil)
    assert verdict["ecart_pourcentage"] == seuil
    assert signal is not None and signal["materiaux_en_ecart_critique"] == ["M1"]


@pytest.mark.parametrize("estimee, declarees, seuil", [(3.0, [3.29], 0.1), (3.0, [2.71], 0.1), (10.0, [10.9], 0.1)])
def test_un_ecart_sous_le_seuil_ne_declenche_rien(estimee, declarees, seuil):
    verdict, signal = _evaluer(estimee, declarees, seuil)
    assert verdict["ecart_pourcentage"] < seuil and signal is None


def test_des_quantites_decimales_egales_a_l_estimee_ne_sont_pas_un_ecart():
    verdict, signal = _evaluer(0.3, [0.1, 0.2], 0.1)
    assert verdict["verdict_variance"] == "AUCUN_ECART"
    assert verdict["ecart"] == 0.0 and verdict["ecart_pourcentage"] == 0.0
    assert verdict["classification_requise"] is False and signal is None


def test_les_retours_se_soustraient_en_decimal_exact():
    besoins = [{"materiau_id": "M1", "quantite_estimee": 0.3, "unite": "pi"}]
    lignes = [
        {"type_ligne": "prevu", "materiau_id": "M1", "quantite": 0.7, "unite": "pi", "quantite_estimee": 0.3},
        {"type_ligne": "retour", "materiau_id": "M1", "quantite": 0.4, "unite": "pi"},
    ]
    resultat, code = vc.evaluer("C1", besoins, lignes, 0.1)
    assert code is None and resultat["verdicts_materiaux"][0]["verdict_variance"] == "AUCUN_ECART"


def test_le_reel_relu_du_registre_se_somme_en_decimal_exact():
    registre = Registre()
    for quantite in (-0.1, -0.2):
        registre.ajouter({"type_mouvement": "CONSOMMATION", "chantier_id": "C1", "materiau_id": "M1",
                          "quantite": quantite, "cout_unitaire": 1.0, "unite": "pi", "wct_id": "W1"})
    besoins = [{"materiau_id": "M1", "quantite_estimee": 0.3, "unite": "pi"}]
    verdicts = vc.comparer_depuis_registre(besoins, "C1", registre, "W1")
    assert verdicts[0]["verdict_variance"] == "AUCUN_ECART" and verdicts[0]["quantite_reelle"] == 0.3
    resultat, code = vc.evaluer("C1", [{"materiau_id": "M1", "quantite_estimee": 3.0, "unite": "pi"}], None, 0.1,
                                registre=_registre_de(3.3), wct_id="W2")
    assert code is None and resultat["signal_variance_critique"] is not None


def _registre_de(quantite):
    registre = Registre()
    registre.ajouter({"type_mouvement": "CONSOMMATION", "chantier_id": "C1", "materiau_id": "M1",
                      "quantite": -quantite, "cout_unitaire": 1.0, "unite": "pi", "wct_id": "W2"})
    return registre


@pytest.mark.parametrize("estimee, declarees, attendu", [
    (10.0, [4.0, 7.0], ("ECART_REEL_SUPERIEUR", 1.0, 0.1)),
    (10.0, [9.0], ("ECART_REEL_INFERIEUR", -1.0, 0.1)),
    (5.0, [], ("NON_UTILISE", -5.0, 1.0)),
    (4.0, [4.0], ("AUCUN_ECART", 0.0, 0.0)),
    (2.5, [3.0], ("ECART_REEL_SUPERIEUR", 0.5, 0.2)),
])
def test_les_cas_ordinaires_gardent_leurs_valeurs(estimee, declarees, attendu):
    verdict, _ = _evaluer(estimee, declarees, 0.5)
    assert (verdict["verdict_variance"], verdict["ecart"], verdict["ecart_pourcentage"]) == attendu
