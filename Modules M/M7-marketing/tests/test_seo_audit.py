"""Tests pour l'audit SEO local du module M7."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "src/seo/seo_audit.py"

spec = importlib.util.spec_from_file_location("seo_audit", MODULE_PATH)
seo_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seo_audit)
audit_dir = seo_audit.audit_dir


class TestSEOAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.real_site = ROOT / "src/site/static"

    def _assert_no_score(self, obj: object) -> None:
        if isinstance(obj, dict):
            self.assertNotIn("score", obj)
            for value in obj.values():
                self._assert_no_score(value)
        elif isinstance(obj, list):
            for item in obj:
                self._assert_no_score(item)

    def _find_rule(self, rapport: dict, regle: str, fichier: str | None = None) -> dict:
        if regle == "robots_crawlable":
            verdicts = rapport["robots"]["verdicts"]
        else:
            pages = [
                p for p in rapport["pages"] if fichier is None or p["fichier"] == fichier
            ]
            self.assertTrue(pages, f"page {fichier!r} non trouvée")
            verdicts = pages[0]["verdicts"]

        for verdict in verdicts:
            if verdict["regle"] == regle:
                return verdict
        self.fail(f"règle {regle!r} non trouvée")

    def _write_page(
        self,
        directory: Path,
        filename: str = "page.html",
        *,
        title: str = "<title>Titre</title>",
        description: str = '<meta name="description" content="Description">',
        lang: str = 'lang="fr"',
        h1: str = "<h1>Titre principal</h1>",
        extra: str = "",
    ) -> None:
        html = f"""<!DOCTYPE html>
<html {lang}>
<head>
  <meta charset="UTF-8">
  {title}
  {description}
</head>
<body>
  {h1}
  {extra}
</body>
</html>"""
        (directory / filename).write_text(html, encoding="utf-8")

    def _write_robots(self, directory: Path, content: str) -> None:
        (directory / "robots.txt").write_text(content, encoding="utf-8")

    def test_real_site_no_score_field(self) -> None:
        rapport = audit_dir(self.real_site)
        self._assert_no_score(rapport)

    def test_real_site_all_green(self) -> None:
        rapport = audit_dir(self.real_site)
        self.assertEqual(rapport["resume"]["regles_ko"], 0)

        for page in rapport["pages"]:
            for verdict in page["verdicts"]:
                self.assertTrue(
                    verdict["ok"],
                    f"{page['fichier']} / {verdict['regle']} : {verdict['detail']}",
                )

        for verdict in rapport["robots"]["verdicts"]:
            self.assertTrue(verdict["ok"], f"robots : {verdict['detail']}")

    def test_page_sans_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            self._write_page(site, title="")
            self._write_robots(site, "User-agent: *\nAllow: /\n")
            rapport = audit_dir(site)

            self.assertEqual(rapport["resume"]["regles_ko"], 1)
            verdict = self._find_rule(rapport, "title")
            self.assertFalse(verdict["ok"])

    def test_page_sans_h1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            self._write_page(site, h1="")
            self._write_robots(site, "User-agent: *\nAllow: /\n")
            rapport = audit_dir(site)

            verdict = self._find_rule(rapport, "h1_unique")
            self.assertFalse(verdict["ok"])

    def test_page_deux_h1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            self._write_page(site, h1="<h1>A</h1><h1>B</h1>")
            self._write_robots(site, "User-agent: *\nAllow: /\n")
            rapport = audit_dir(site)

            verdict = self._find_rule(rapport, "h1_unique")
            self.assertFalse(verdict["ok"])

    def test_json_ld_casse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            extra = '<script type="application/ld+json">{ pas du json </script>'
            self._write_page(site, extra=extra)
            self._write_robots(site, "User-agent: *\nAllow: /\n")
            rapport = audit_dir(site)

            verdict = self._find_rule(rapport, "json_ld_valide")
            self.assertFalse(verdict["ok"])

    def test_robots_sans_allow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            self._write_page(site)
            self._write_robots(site, "User-agent: *\n")
            rapport = audit_dir(site)

            verdict = self._find_rule(rapport, "robots_crawlable")
            self.assertFalse(verdict["ok"])

    def test_robots_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            self._write_page(site)
            rapport = audit_dir(site)

            verdict = self._find_rule(rapport, "robots_crawlable")
            self.assertFalse(verdict["ok"])
            self.assertIn("absent", verdict["detail"])


if __name__ == "__main__":
    unittest.main()
