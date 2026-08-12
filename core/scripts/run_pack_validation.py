"""Validation de cohérence globale du pack bootstrap Core (C02-001..004
réunis) — remplace le placeholder BLOCKED du job CI `pack-validation`
(core-ci.yml, C02-005).

N'INVENTE aucun nouveau mécanisme : rejoue RÉELLEMENT, sur l'environnement
qui exécute ce script (jamais une comparaison cross-machine invalide —
cf. limitation nommée ci-dessous), les 4 interfaces déjà livrées et déjà
unitairement testées, mais dont certaines n'étaient JAMAIS réellement
INVOQUÉES par un job CI avant ce script (mesuré, pas supposé).

Le périmètre Python de la validation est lu depuis le contrat unique
core/quality-scopes.toml. Les racines absentes sur le checkout courant sont
ignorées ; les racines présentes sont passées au contrôle de structure.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUALITY_SCOPES = _REPO_ROOT / "core" / "quality-scopes.toml"
sys.path.insert(0, str(_REPO_ROOT / "core" / "scripts"))

from bootstrap_toolchain import inventorier_toolchain, validate_toolchain_lock  # noqa: E402
from run_tests import run_test_slice  # noqa: E402
from verify_dependencies import verify_lock  # noqa: E402

_OUTILS_GARANTIS = {
    "python": [sys.executable, "--version"],
    "git": ["git", "--version"],
}

_SCOPE_TESTS = [
    "-q",
    str(_REPO_ROOT / "core" / "tests" / "bootstrap"),
    str(_REPO_ROOT / "core" / "tests" / "architecture"),
    str(_REPO_ROOT / "core" / "tests" / "persistence"),
]


def charger_racines_qualite() -> tuple[Path, ...]:
    """Charge les racines Python présentes déclarées par le contrat qualité."""
    with _QUALITY_SCOPES.open("rb") as flux:
        contrat = tomllib.load(flux)
    racines = contrat.get("python_roots")
    if not isinstance(racines, list) or not all(isinstance(racine, str) for racine in racines):
        raise RuntimeError("contrat quality-scopes.toml invalide : python_roots attendu")
    return tuple(
        chemin
        for racine in racines
        if (chemin := _REPO_ROOT / racine).exists()
    )


def verifier_toolchain() -> tuple[bool, str]:
    """Vérifie le format d'une mesure fraîche de la toolchain."""
    lock, blockers = inventorier_toolchain(_OUTILS_GARANTIS)
    erreurs_format = validate_toolchain_lock(lock)
    ok = not blockers and not erreurs_format
    lignes = [f"toolchain (C02-001, mesure fraîche sur ce runner) : {'OK' if ok else 'ROUGE'}"]
    for blocker in blockers:
        lignes.append(f"  blocker : {blocker}")
    for erreur in erreurs_format:
        lignes.append(f"  format invalide : {erreur}")
    if ok:
        for nom, spec in lock.tools.items():
            lignes.append(f"  {nom} : version={spec.version} digest={spec.digest[:12]}…")
    return ok, "\n".join(lignes)


def verifier_dependances() -> tuple[bool, str]:
    """Vérifie le verrou de dépendances Core."""
    rapport = verify_lock(_REPO_ROOT / "core" / "pyproject.toml", _REPO_ROOT / "core" / "requirements.lock")
    lignes = [f"dépendances (C02-002) : {'OK' if rapport.ok else 'ROUGE'}"]
    for valeur in rapport.declared_but_undeclared_imports:
        lignes.append(f"  import non déclaré : {valeur}")
    for valeur in rapport.floating_dependencies:
        lignes.append(f"  version flottante : {valeur}")
    for valeur in rapport.missing_hash_packages:
        lignes.append(f"  hash manquant : {valeur}")
    return rapport.ok, "\n".join(lignes)


def verifier_runner_hermetique() -> tuple[bool, str]:
    """Rejoue le runner hermétique sur les slices bootstrap existantes."""
    rc = run_test_slice(_SCOPE_TESTS)
    ok = rc == 0
    return ok, f"runner hermétique (C02-003, run_test_slice réel) : rc={rc} ({'OK' if ok else 'ROUGE'})"


def verifier_structure() -> tuple[bool, str]:
    """Exécute le contrôle de structure sur les racines du contrat."""
    racines = charger_racines_qualite()
    resultat = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "structure_lint.py"),
            *(str(racine) for racine in racines),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=60,
    )
    ok = resultat.returncode == 0
    sortie = (resultat.stdout + resultat.stderr).strip()
    return ok, f"structure_lint.py : rc={resultat.returncode} — {sortie}"


def main() -> int:
    """Exécute toutes les vérifications du pack."""
    verifications = [
        verifier_toolchain(),
        verifier_dependances(),
        verifier_runner_hermetique(),
        verifier_structure(),
    ]
    tout_ok = True
    for ok, rapport in verifications:
        print(rapport)
        tout_ok = tout_ok and ok

    if tout_ok:
        print("PACK_VALIDATION: VERT (toolchain + dépendances + runner hermétique + structure, C02-001..004 réunis)")
        return 0
    print("PACK_VALIDATION: ROUGE — voir détail ci-dessus.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
