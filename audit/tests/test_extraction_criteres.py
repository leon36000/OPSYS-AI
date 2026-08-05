import unittest

from audit.docs.bmad.verif_coherence import _extraire_criteres_cellule


class TestExtractionCriteresCellule(unittest.TestCase):
    def test_identifiants_complets_prd_deux_criteres(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-01, CA-AUD-02"),
            {"CA-AUD-01", "CA-AUD-02"},
        )

    def test_identifiants_complets_prd_trois_criteres(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-09, CA-AUD-10, CA-AUD-12"),
            {"CA-AUD-09", "CA-AUD-10", "CA-AUD-12"},
        )

    def test_abreviation_architecture_deux_criteres(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-01, 02"),
            {"CA-AUD-01", "CA-AUD-02"},
        )

    def test_abreviations_architecture_trois_criteres(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-09, 10, 12"),
            {"CA-AUD-09", "CA-AUD-10", "CA-AUD-12"},
        )

    def test_identifiant_complet_seul(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-13"),
            {"CA-AUD-13"},
        )

    def test_formes_completes_et_abregees_melees(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-01, CA-AUD-02, 03"),
            {"CA-AUD-01", "CA-AUD-02", "CA-AUD-03"},
        )

    def test_prose_dans_une_enumeration_invalide_toute_la_cellule(self):
        self.assertEqual(
            _extraire_criteres_cellule("CA-AUD-01, 02, audit de 2023, 45"),
            set(),
        )

    def test_phrase_contenant_un_critere_n_affecte_rien(self):
        self.assertEqual(
            _extraire_criteres_cellule("Description, voir CA-AUD-01 pour le contexte"),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
