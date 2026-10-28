"""Tests de calculs fictifs, sans producteur M4 ni contrat réseau publié."""

import unittest
from datetime import date
from decimal import Decimal


class TestCalculContractuel(unittest.TestCase):
    def test_oracle_deux_equipes(self):
        from m5_financecore.ventilation_couts_visites import calculer_ligne_equipe

        commun = dict(unite="heure-equipe", devise="CAD", source="fictif", version="1",
                      date_effet=date(2026, 1, 1), date_fin=date(2026, 12, 31),
                      date_travail=date(2026, 10, 28))
        a = calculer_ligne_equipe(150, "100", **commun)
        b = calculer_ligne_equipe(240, "120", **commun)
        self.assertEqual(a["cout"], Decimal("250.00"))
        self.assertEqual(b["cout"], Decimal("480.00"))
        self.assertEqual(a["cout"] + b["cout"], Decimal("730.00"))


    def test_arrondi_par_ligne_et_provenance(self):
        from m5_financecore.ventilation_couts_visites import calculer_ligne_equipe

        result = calculer_ligne_equipe(
            1, "1.50", unite="heure-equipe", devise="CAD", source="fictif",
            version="v2", date_effet=date(2026, 1, 1), date_fin=date(2026, 12, 31),
            date_travail=date(2026, 10, 28),
        )
        self.assertEqual(result["cout"], Decimal("0.03"))
        self.assertEqual(result["version"], "v2")
        self.assertIn("déplacements exclus", result["politique"])

    def test_manques_interdisent_imputation(self):
        from m5_financecore.ventilation_couts_visites import calculer_ligne_equipe

        base = dict(minutes=150, taux="100", unite="heure-equipe", devise="CAD",
                    source="fictif", version="1", date_effet=date(2026, 1, 1),
                    date_fin=date(2026, 12, 31), date_travail=date(2026, 10, 28))
        cas = [
            {"unite": "heure-personne"}, {"unite": None}, {"devise": None},
            {"source": ""}, {"version": ""}, {"date_effet": None},
            {"date_fin": date(2026, 10, 27)}, {"minutes": True},
            {"minutes": -1}, {"taux": float("nan")}, {"taux": "NaN"},
            {"taux": "1e100000"}, {"taux": "0"},
        ]
        for modification in cas:
            with self.subTest(modification=modification):
                result = calculer_ligne_equipe(**(base | modification))
                self.assertIsNone(result["cout"])
                self.assertEqual(result["statut"], "non_disponible")
                self.assertTrue(result["raisons"])

if __name__ == "__main__":
    unittest.main()
