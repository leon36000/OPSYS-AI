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

    def test_base_ref_hors_liste_blanche_est_rejete_avant_git(self) -> None:
        with TemporaryDirectory() as repertoire:
            repo = Path(repertoire)
            fichier = repo / "module.py"
            contenu = "def fonction():\n    return 1\n"
            fichier.write_text(contenu, encoding="utf-8")

            def subprocess_interdit(*_args, **_kwargs):
                self.fail("une --base-ref hors liste blanche a atteint subprocess")

            with patch.object(gate.subprocess, "run", side_effect=subprocess_interdit):
                with self.assertRaisesRegex(ValueError, "base-ref"):
                    gate._lignes_du_diff(repo, fichier, "main;echo", contenu)

    def test_base_ref_non_contractuelle_est_rejete_avant_git(self) -> None:
        with TemporaryDirectory() as repertoire:
            repo = Path(repertoire)
            fichier = repo / "module.py"
            contenu = "def fonction():\n    return 1\n"
            fichier.write_text(contenu, encoding="utf-8")

            def subprocess_interdit(*_args, **_kwargs):
                self.fail("une --base-ref hors contrat a atteint subprocess")

            with patch.object(gate.subprocess, "run", side_effect=subprocess_interdit):
                with self.assertRaisesRegex(ValueError, "base-ref"):
                    gate._lignes_du_diff(repo, fichier, "main", contenu)

    def test_cli_rejects_invalid_base_ref_during_argument_parsing(self) -> None:
        def contrat_interdit(*_args, **_kwargs):
            self.fail("un --base-ref invalide a depasse argparse")

        with patch.object(gate, "_lire_contrat", side_effect=contrat_interdit):
            with self.assertRaises(SystemExit) as erreur:
                gate.main(["--base-ref=--stat"])
        self.assertEqual(erreur.exception.code, 2)

    def test_pathspec_git_hors_liste_blanche_est_rejete_avant_git(self) -> None:
        """Un nom de fichier non sûr ne doit jamais atteindre git comme argument."""
        with TemporaryDirectory() as repertoire:
            repo = Path(repertoire)
            fichier = repo / "module;$(touch pwned).py"
            contenu = "def fonction():\n    return 1\n"
            fichier.write_text(contenu, encoding="utf-8")

            def subprocess_interdit(*_args, **_kwargs):
                self.fail("un pathspec non fiable a atteint subprocess")

            with patch.object(gate.subprocess, "run", side_effect=subprocess_interdit):
                with self.assertRaisesRegex(ValueError, "chemin"):
                    gate._lignes_du_diff(repo, fichier, "origin/main", contenu)

    def test_nom_de_fichier_filtre_en_memoire_et_absent_des_argv_git(self) -> None:
        """Le chemin cible ne doit pas être transmis comme argument à Git."""
        with TemporaryDirectory() as repertoire:
            repo = Path(repertoire)
            fichier = repo / "module.py"
            contenu = "def fonction():\n    return 1\n"
            fichier.write_text(contenu, encoding="utf-8")
            appels: list[tuple[list[str], dict[str, object]]] = []

            def git_sans_pathspec(argv: list[str], **kwargs: object):
                appels.append((argv, kwargs))
                if argv[1] == "ls-files":
                    return gate.subprocess.CompletedProcess(
                        argv, 0, stdout="module.py\0", stderr=""
                    )
                return gate.subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=(
                        "diff --git a/module.py b/module.py\n"
                        "--- a/module.py\n"
                        "+++ b/module.py\n"
                        "@@ -1 +1 @@\n"
                        "+def fonction():\n"
                    ),
                    stderr="",
                )

            with patch.object(gate.subprocess, "run", side_effect=git_sans_pathspec):
                assert gate._lignes_du_diff(repo, fichier, "origin/main", contenu) == {1}

            assert len(appels) == 2
            assert all("module.py" not in argv for argv, _ in appels)
            assert appels[1][0][-1] == "origin/main...HEAD"


if __name__ == "__main__":
    unittest.main()
