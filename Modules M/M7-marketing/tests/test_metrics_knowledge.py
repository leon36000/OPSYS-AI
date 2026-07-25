import pathlib
import unittest

import yaml


class TestMetricsKnowledge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.here = pathlib.Path(__file__).resolve().parent
        cls.metrics_path = cls.here / ".." / "metrics" / "m7-metrics.v1.yaml"
        cls.knowledge_path = cls.here / ".." / "docs" / "seo-knowledge.v1.yaml"

        with cls.metrics_path.open("r", encoding="utf-8") as f:
            cls.metrics_doc = yaml.safe_load(f)
        with cls.knowledge_path.open("r", encoding="utf-8") as f:
            cls.knowledge_doc = yaml.safe_load(f)

    def test_metrics_parse(self):
        self.assertIsInstance(self.metrics_doc, dict)

    def test_knowledge_parse(self):
        self.assertIsInstance(self.knowledge_doc, dict)

    def test_metrics_owner_calcul_mentions_m8(self):
        owner = self.metrics_doc.get("owner_calcul", "")
        self.assertIn("M8", owner)

    def test_metrics_ids(self):
        metrics = self.metrics_doc.get("metrics", [])
        ids = [m["id"] for m in metrics]
        self.assertEqual(len(ids), len(set(ids)), "les ids de métriques doivent être uniques")
        for i in ids:
            self.assertTrue(i.startswith("m7_"), f"{i} doit être préfixé m7_")
        expected = {
            "m7_cpl",
            "m7_cout_par_soumission",
            "m7_roi_par_canal",
            "m7_part_citations_ia",
            "m7_taux_doc_none",
        }
        self.assertEqual(set(ids), expected)

    def test_metrics_fields_non_empty(self):
        required = {"id", "nom", "definition", "unite", "source_donnees", "frequence", "consommateur"}
        for m in self.metrics_doc.get("metrics", []):
            self.assertEqual(set(m.keys()), required, f"champs incorrects pour {m.get('id')}")
            for field in required:
                value = m[field]
                self.assertIsNotNone(value, f"{field} de {m['id']} ne doit pas être None")
                self.assertNotEqual(str(value).strip(), "", f"{field} de {m['id']} ne doit pas être vide")

    def test_metrics_definitions_are_text_not_numbers(self):
        for m in self.metrics_doc.get("metrics", []):
            definition = m["definition"]
            self.assertIsInstance(definition, str)
            self.assertNotIsInstance(definition, (int, float))

    def test_knowledge_surfaces_present(self):
        surfaces = self.knowledge_doc.get("surfaces", {})
        self.assertIn("google", surfaces)
        self.assertIn("assistants_ia", surfaces)

    def test_knowledge_tactics_structure(self):
        allowed_statuts = {"valide", "candidat_a_verifier"}
        for surface_name, surface in self.knowledge_doc.get("surfaces", {}).items():
            tactiques = surface.get("tactiques", [])
            self.assertIsInstance(tactiques, list, f"{surface_name} doit avoir une liste de tactiques")
            for t in tactiques:
                self.assertIn("tactique", t)
                self.assertIn("statut", t)
                self.assertIn("source", t)
                self.assertIn(t["statut"], allowed_statuts)
                self.assertNotEqual(str(t["source"]).strip(), "")


if __name__ == "__main__":
    unittest.main()
