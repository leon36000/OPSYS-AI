"""Revue adverse (num) : les montants d'un devis sont BORNÉS au domaine monétaire de M5 (999 999 999 999,99 $).

Défauts trouvés (`devis_durable`) : ni la quantité, ni le coût unitaire, ni le taux de marge n'avaient de borne, et les
arrondis se faisaient dans le contexte `decimal` de l'appelant (28 chiffres) :
- `cout_unitaire = "1E+30"` (ou une quantité, ou un taux de marge de `1E+30`) levait `InvalidOperation` au lieu d'un
  verdict ;
- 999 999 999 999,99 $ × 999 999 999 999,99 produisait un devis de 1,5 × 10^24 $ que M5 refuse ensuite de facturer
  (ses lignes plafonnent à 999 999 999 999,99 $).
Données fictives.
"""

from __future__ import annotations

import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, verdicts  # noqa: E402

FICTIF = True
D = Decimal
_H = "2026-09-28T14:00:00-04:00"
MAXIMUM = "999999999999.99"


def _ligne(**surcharges):
    ligne = {"description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin", "cout_unitaire": "10.00",
             "reference_besoin_materiau": None}
    ligne.update(surcharges)
    return ligne


def _creer(registre, lignes=None, taux_marge="0.20"):
    return devis_durable.creer_devis("D-NUM-1", "lead-1", None, lignes or [_ligne()], taux_marge, _H, registre)


@pytest.mark.parametrize("surcharge, taux, code, extrait", [
    ({"cout_unitaire": "1E+30"}, "0.20", "REJ-DEVIS-LIGNE-INVALIDE", "quantite et cout_unitaire"),
    ({"quantite": "1E+30"}, "0.20", "REJ-DEVIS-LIGNE-INVALIDE", "quantite et cout_unitaire"),
    ({"cout_unitaire": "1E+999999"}, "0.20", "REJ-DEVIS-LIGNE-INVALIDE", "quantite et cout_unitaire"),
    ({"cout_unitaire": "1000000000000.00"}, "0.20", "REJ-DEVIS-LIGNE-INVALIDE", "quantite et cout_unitaire"),
    ({"quantite": "1000000000000.00"}, "0.20", "REJ-DEVIS-LIGNE-INVALIDE", "quantite et cout_unitaire"),
    ({}, "1E+30", "REJ-DEVIS-TAUX-MARGE-INVALIDE", "au plus"),
    ({}, "1E+999999", "REJ-DEVIS-TAUX-MARGE-INVALIDE", "au plus"),
    ({}, "1000.01", "REJ-DEVIS-TAUX-MARGE-INVALIDE", "au plus"),
    ({"cout_unitaire": "999999999999.99", "quantite": "999999999999.99"}, "0.5", "REJ-DEVIS-LIGNE-INVALIDE",
     "montant de ligne"),
    ({"cout_unitaire": "0.01", "quantite": "999999999999.99"}, "1000", "REJ-DEVIS-LIGNE-INVALIDE",
     "montant de ligne"),  # coût de ligne 1e10 $ permis ; prix de ligne 1e13 $ non
    ({"cout_unitaire": "0.01", "quantite": "1E+26"}, "0.5", "REJ-DEVIS-LIGNE-INVALIDE", "quantite et cout_unitaire"),
])
def test_un_montant_hors_domaine_est_un_verdict_jamais_une_exception(surcharge, taux, code, extrait):
    registre = []
    reponse = _creer(registre, [_ligne(**surcharge)], taux)
    assert reponse[0] is None and reponse[1]["code"] == code and reponse[1]["code"] in verdicts.CODES_M3
    assert extrait in reponse[1]["detail"]
    assert registre == []  # rien n'est écrit sur un refus


def test_un_total_de_devis_hors_domaine_est_refuse():
    # Chaque ligne tient dans le domaine ; leur somme non.
    lignes = [_ligne(description=f"poste {i}", cout_unitaire="400000000000.00", quantite="1") for i in range(3)]
    registre = []
    reponse = _creer(registre, lignes, "0")
    assert reponse[0] is None and reponse[1]["code"] == "REJ-DEVIS-LIGNE-INVALIDE"
    assert "total" in reponse[1]["detail"]
    assert registre == []


def test_les_limites_permises_et_les_cas_ordinaires_restent_acceptes():
    devis, verdict = _creer([], [_ligne(cout_unitaire=MAXIMUM, quantite="1")], "0")
    assert verdict is None and devis["prix_total"] == D(MAXIMUM)
    devis, verdict = _creer([], [_ligne(cout_unitaire="0.01", quantite="1000000000")], "0.5")
    # prix unitaire 0,015 arrondi à 0,02 d'abord, comme le fait la facture M5
    assert verdict is None and devis["cout_total"] == D("10000000.00") and devis["prix_total"] == D("20000000.00")
    devis, verdict = _creer([], [_ligne()], "0.20")
    assert verdict is None and devis["prix_total"] == D("360.00") and devis["cout_total"] == D("300.00")
    devis, verdict = _creer([], [_ligne()], "-0.5")  # un rabais reste permis
    assert verdict is None and devis["prix_total"] == D("150.00")


def test_la_quantite_infinitesimale_donne_une_ligne_a_zero_sans_exception():
    devis, verdict = _creer([], [_ligne(quantite="1E-30")])
    assert verdict is None and devis["prix_total"] == D("0.00")


def test_prix_depuis_cout_ne_depend_pas_du_contexte_de_l_appelant():
    with localcontext() as contexte:
        contexte.prec = 6
        assert devis_durable.prix_depuis_cout(D("1234567.89"), D("0.2")) == D("1481481.47")


def test_une_quantite_a_nombreuses_decimales_garde_un_produit_exact():
    # 40 chiffres de quantité : le produit exact (17 + 40 chiffres) dépasse un contexte fixe de 32 ; l'arrondi au cent
    # se fait sur le produit EXACT.
    quantite = "0." + "0" * 20 + "5" + "0" * 17 + "1"  # 5E-21 + 1E-40
    devis, verdict = _creer([], [_ligne(quantite=quantite, cout_unitaire="999999999999.99")], "1000")
    assert verdict is None and devis["prix_total"] == D("0.00")
    grand = "123456789012.34567890123456789012345678901234567890"
    devis, verdict = _creer([], [_ligne(quantite=grand, cout_unitaire="3.33")], "0")
    assert verdict is None
    exact = Fraction(grand) * Fraction("3.33") * 100  # en cents, exact
    assert devis["cout_total"] == D(int(exact + Fraction(1, 2))) / 100  # demi-cent vers le haut


def test_l_arrondi_au_cent_se_fait_sur_le_produit_exact_et_non_sur_un_produit_deja_arrondi():
    # 0,01 $ × 0,4999… (37 chiffres) = 0,004999…9 $ : sous le demi-cent, donc 0,00 $. Un contexte de 28 chiffres
    # arrondirait d'abord le produit à 0,005000…0 puis le cent supérieur : 0,01 $.
    quantite = "0.4" + "9" * 36
    devis, verdict = _creer([], [_ligne(quantite=quantite, cout_unitaire="0.01")], "0")
    assert verdict is None
    assert devis["cout_total"] == D("0.00") and devis["prix_total"] == D("0.00")
    with localcontext() as contexte:
        contexte.prec = 6
        devis, verdict = _creer([], [_ligne(quantite=quantite, cout_unitaire="0.01")], "0")
        assert verdict is None and devis["cout_total"] == D("0.00")
