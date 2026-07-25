import os
import unittest

import yaml


class TestMetricsKnowledge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = os.path.dirname(os.path.abspath(__file__))
        cls.metrics_path = os.path.join(
            cls.base_dir, "..", "metrics", "m7-metrics.v1.yaml"
        )
        cls.knowledge_path = os.path.join(
            cls.base_dir, "..", "docs", "seo-knowledge.v1.yaml"
        )

        with open(cls.metrics_path, "r", encoding="utf-8") as f:
            cls.metrics = yaml.safe_load(f)
        with open(cls.knowledge_path, "r", encoding="utf-8") as f:
            cls.knowledge = yaml.safe_load(f)

    def test_metrics_parse(self):
        self.assertIsInstance(self.metrics, dict)

    def test_metrics_header(self):
        self.assertEqual(self.metrics.get("schema_version"), 1)
        self.assertEqual(self.metrics.get("module"), "M7-marketing")
        owner = self.metrics.get("owner_calcul", "")
        self.assertIn("M8", owner)

    def test_metrics_fields(self):
        metrics = self.metrics.get("metrics", [])
        self.assertIsInstance(metrics, list)

        expected_ids = {
            "m7_cpl",
            "m7_cout_par_soumission",
            "m7_roi_par_canal",
            "m7_part_citations_ia",
            "m7_taux_doc_none",
            # M7-S009 — Reputation Engine
            "m7_rep_total_avis",
            "m7_rep_repartition_notes",
            "m7_rep_note_moyenne",
            "m7_rep_taux_reponse",
            "m7_rep_repartition_cats",
            "m7_rep_delai_moyen_jours",
        }
        required_fields = {
            "id",
            "nom",
            "definition",
            "unite",
            "source_donnees",
            "frequence",
            "consommateur",
        }
        seen = set()

        for metric in metrics:
            self.assertIsInstance(metric, dict)
            self.assertTrue(
                required_fields.issubset(metric.keys()),
                f"Champs manquants pour {metric.get('id')}",
            )
            for field in required_fields:
                value = metric[field]
                self.assertIsInstance(
                    value,
                    str,
                    f"{metric.get('id')}.{field} doit être une chaîne",
                )
                self.assertTrue(
                    value.strip(),
                    f"{metric.get('id')}.{field} est vide",
                )
            self.assertTrue(
                metric["id"].startswith("m7_"),
                f"{metric['id']} ne préfixe pas m7_",
            )
            seen.add(metric["id"])

        self.assertEqual(seen, expected_ids)
        self.assertEqual(len(metrics), len(seen), "ids métriques en double")

    def test_metrics_no_calculated_numbers(self):
        for metric in self.metrics.get("metrics", []):
            for key, value in metric.items():
                self.assertIsInstance(
                    value,
                    str,
                    f"{metric.get('id')}.{key} contient une valeur non texte",
                )

    def test_knowledge_parse(self):
        self.assertIsInstance(self.knowledge, dict)

    def test_knowledge_header(self):
        self.assertEqual(self.knowledge.get("schema_version"), 1)
        self.assertIn("surfaces", self.knowledge)

    def test_knowledge_surfaces(self):
        surfaces = self.knowledge.get("surfaces", {})
        required = {"google_aio", "perplexity", "assistants_ia"}
        self.assertTrue(
            required.issubset(set(surfaces.keys())),
            f"Surfaces manquantes : {required - set(surfaces.keys())}",
        )

        for name, surface in surfaces.items():
            self.assertIsInstance(surface, dict)
            self.assertIn("position", surface)
            self.assertIn("tactiques", surface)
            for tactic in surface["tactiques"]:
                self.assertIsInstance(tactic, dict)
                self.assertIn("tactique", tactic)
                self.assertIn("statut", tactic)
                self.assertIn("source", tactic)
                self.assertTrue(str(tactic["tactique"]).strip())
                self.assertIn(
                    tactic["statut"],
                    {"valide", "candidat_a_verifier"},
                )
                self.assertTrue(str(tactic["source"]).strip())

    def test_knowledge_regles(self):
        regles = self.knowledge.get("regles", [])
        self.assertIsInstance(regles, list)
        self.assertTrue(
            all(isinstance(r, str) and r.strip() for r in regles),
            "Règles vides ou non textuelles",
        )


if __name__ == "__main__":
    unittest.main()
