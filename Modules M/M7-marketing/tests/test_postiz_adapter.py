"""Tests déterministes de l'adapter Postiz GATED."""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "src" / "social" / "postiz_adapter.py"
CONFIG_PATH = ROOT / "src" / "social" / "config.yaml"

# Chargement direct pour éviter les espaces dans les noms de packages.
spec = importlib.util.spec_from_file_location("postiz_adapter", ADAPTER_PATH)
postiz_adapter = importlib.util.module_from_spec(spec)
sys.modules["postiz_adapter"] = postiz_adapter
spec.loader.exec_module(postiz_adapter)

AdapterDisabled = postiz_adapter.AdapterDisabled
NotAutorise = postiz_adapter.NotAutorise
PostizAdapter = postiz_adapter.PostizAdapter
SocialPost = postiz_adapter.SocialPost


class TestPostizAdapter(unittest.TestCase):
    def _load_config(self) -> dict:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def test_aucun_import_reseau_dans_l_adapter(self):
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        "urllib", alias.name,
                        "l'adapter ne doit pas importer urllib"
                    )
                    self.assertNotIn(
                        "socket", alias.name,
                        "l'adapter ne doit pas importer socket"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn("urllib", module)
                self.assertNotIn("socket", module)

    def test_config_yaml_default_est_flag_off(self):
        config = self._load_config()
        self.assertIs(config.get("enabled"), False)
        self.assertIs(config.get("dry_run"), True)
        self.assertEqual(config.get("base_url"), "")

    def test_flag_off_leve_adapter_disabled(self):
        adapter = PostizAdapter({"enabled": False})
        post = SocialPost(canal="facebook", texte="Hello", niveau_validation=0)
        with self.assertRaises(AdapterDisabled) as ctx:
            adapter.publier(post)
        self.assertIn("feature-flag OFF", str(ctx.exception))

    def test_dry_run_retourne_statut_dry_run_avec_payload_conforme(self):
        adapter = PostizAdapter({"enabled": True, "dry_run": True})
        post = SocialPost(
            canal="instagram",
            texte="Nouvelle offre",
            media=["/tmp/photo.jpg"],
            niveau_validation=2,
        )
        result = adapter.publier(post)

        self.assertEqual(result["statut"], "dry-run")
        self.assertIs(result["approbation_requise"], True)

        payload = result["payload"]
        self.assertEqual(payload["platform"], "instagram")
        self.assertEqual(payload["content"], "Nouvelle offre")
        self.assertEqual(payload["media"], ["/tmp/photo.jpg"])
        self.assertEqual(payload["approval_level"], 2)
        self.assertIs(payload["dry_run"], True)

    def test_dry_run_avec_niveau_zero_nexige_pas_approbation(self):
        adapter = PostizAdapter({"enabled": True, "dry_run": True})
        post = SocialPost(canal="gbp", texte="Info", niveau_validation=0)
        result = adapter.publier(post)
        self.assertIs(result["approbation_requise"], False)

    def test_enabled_sans_dry_run_leve_not_autorise(self):
        adapter = PostizAdapter({"enabled": True, "dry_run": False})
        post = SocialPost(canal="facebook", texte="Hello", niveau_validation=1)
        with self.assertRaises(NotAutorise) as ctx:
            adapter.publier(post)
        self.assertIn("écriture réelle interdite", str(ctx.exception))

    def test_validation_canal_invalide(self):
        with self.assertRaises(ValueError):
            SocialPost(canal="twitter", texte="Hello", niveau_validation=0)

    def test_validation_texte_vide(self):
        with self.assertRaises(ValueError):
            SocialPost(canal="facebook", texte="", niveau_validation=0)
        with self.assertRaises(ValueError):
            SocialPost(canal="facebook", texte="   ", niveau_validation=0)

    def test_validation_niveau_hors_limites(self):
        with self.assertRaises(ValueError):
            SocialPost(canal="facebook", texte="Hello", niveau_validation=7)
        with self.assertRaises(ValueError):
            SocialPost(canal="facebook", texte="Hello", niveau_validation=-1)

    def test_file_approbation_triee_par_niveau_decroissant(self):
        posts = [
            SocialPost(canal="facebook", texte="A", niveau_validation=1),
            SocialPost(canal="instagram", texte="B", niveau_validation=6),
            SocialPost(canal="gbp", texte="C", niveau_validation=3),
        ]
        adapter = PostizAdapter({})
        result = adapter.file_approbation(posts)
        niveaux = [p.niveau_validation for p in result]
        self.assertEqual(niveaux, [6, 3, 1])


if __name__ == "__main__":
    unittest.main()
