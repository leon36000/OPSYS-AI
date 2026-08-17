"""Régression sécurité CLR-001 pour la validation de --base-ref."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.quality import no_stub_gate as gate


class BaseRefValidationTest(unittest.TestCase):
    """Verrouille le rejet d'une pseudo-référence Git avant tout subprocess."""

    def test_option_like_base_ref_is_rejected_before_git(self) -> None:
        with TemporaryDirectory() as repertoire:
            repo = Path(repertoire)
            fichier = repo / "module.py"
            contenu = "def fonction():\n    return 1\n"
            fichier.write_text(contenu, encoding="utf-8")

            def subprocess_interdit(*_args, **_kwargs):
                self.fail("un --base-ref non fiable a atteint subprocess")

            with patch.object(gate.subprocess, "run", side_effect=subprocess_interdit):
                with self.assertRaisesRegex(ValueError, "base-ref"):
                    gate._lignes_du_diff(repo, fichier, "--stat", contenu)


if __name__ == "__main__":
    unittest.main()
