"""Scan de sécurité Core — bandit (SAST) + pip-audit (CVE dépendances).

Construit pour remplacer le placeholder BLOCKED du job CI `security`
(core-ci.yml, C02-005) — mécanisme réel, jamais inventé : les 2 outils
sont ceux littéralement nommés dans le message BLOCKED d'origine
("aucun scanner de sécurité (ex. bandit, pip-audit) n'est référencé
nulle part dans ce dépôt à ce jour"), tous deux déjà installés
localement au moment de l'écriture (mesuré : `which bandit pip-audit`).

Reproductible en LOCAL et en CI avec la MÊME commande — pas de logique
dupliquée entre les deux (le job CI invoque ce script directement).

Bandit : config dans core/pyproject.toml ([tool.bandit]). Le périmètre
vient désormais du contrat unique core/quality-scopes.toml ; les racines
absentes sont ignorées, les racines présentes sont toutes réellement
transmises à bandit. Les exclusions bandit B101/B404/B603/B607 documentées
dans pyproject.toml restent applicables à ce périmètre contractuel.

pip-audit : `--disable-pip` OBLIGATOIRE sur cette machine — `ensurepip`
indisponible (`apt install python3.12-venv` interdit par les
interdictions du projet, aucun sudo) ; `--disable-pip` scanne les
versions ÉPINGLÉES de core/requirements.lock directement contre la
base OSV, sans tenter de résoudre/installer un environnement isolé.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUALITY_SCOPES = _REPO_ROOT / "core" / "quality-scopes.toml"
_PYPROJECT = _REPO_ROOT / "core" / "pyproject.toml"
_REQUIREMENTS_LOCK = _REPO_ROOT / "core" / "requirements.lock"


class OutilSecuriteAbsent(RuntimeError):
    """bandit ou pip-audit n'est pas installé/exécutable sur cette machine."""


def charger_racines_qualite() -> tuple[Path, ...]:
    """Charge les racines Python existantes définies par le contrat unique."""
    with _QUALITY_SCOPES.open("rb") as flux:
        contrat = tomllib.load(flux)
    racines = contrat.get("python_roots")
    if not isinstance(racines, list) or not all(isinstance(racine, str) for racine in racines):
        raise OutilSecuriteAbsent("contrat quality-scopes.toml invalide : python_roots attendu")
    return tuple(
        chemin
        for racine in racines
        if (chemin := _REPO_ROOT / racine).exists()
    )


def _executer(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise OutilSecuriteAbsent(f"outil introuvable : {argv[0]} ({exc})") from None
    except subprocess.TimeoutExpired as exc:
        raise OutilSecuriteAbsent(f"délai dépassé (300s) : {' '.join(argv)} ({exc})") from None


def executer_bandit() -> tuple[bool, str]:
    """Exécute bandit sur toutes les racines contractuelles présentes."""
    racines = charger_racines_qualite()
    if not racines:
        raise OutilSecuriteAbsent("aucune racine Python existante dans quality-scopes.toml")

    resultat = _executer(
        [
            "bandit",
            "-q",
            "-c",
            str(_PYPROJECT),
            "-r",
            *(str(racine) for racine in racines),
            "-f",
            "json",
        ]
    )
    if resultat.returncode not in (0, 1):
        raise OutilSecuriteAbsent(
            f"bandit a échoué avec un code inattendu ({resultat.returncode}) : {resultat.stderr}"
        )
    try:
        rapport = json.loads(resultat.stdout)
    except json.JSONDecodeError as exc:
        raise OutilSecuriteAbsent(f"sortie bandit non-JSON : {exc}\n{resultat.stdout}") from None

    findings = rapport.get("results", [])
    lignes = [f"bandit : {len(findings)} finding(s) (0 attendu)"]
    for finding in findings:
        lignes.append(
            f"  {finding['filename']}:{finding['line_number']} {finding['test_id']} "
            f"{finding['issue_severity']}/{finding['issue_confidence']} — "
            f"{finding['issue_text']}"
        )
    return not findings, "\n".join(lignes)


def executer_pip_audit() -> tuple[bool, str]:
    """Exécute pip-audit contre les dépendances épinglées du verrou."""
    lignes_verrou = [
        ligne
        for ligne in _REQUIREMENTS_LOCK.read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.strip().startswith("#")
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as flux:
        flux.write("\n".join(lignes_verrou) + "\n")
        chemin_tmp = Path(flux.name)
    try:
        resultat = _executer(
            ["pip-audit", "-r", str(chemin_tmp), "--disable-pip", "--desc", "-f", "json"]
        )
    finally:
        chemin_tmp.unlink(missing_ok=True)

    if resultat.returncode not in (0, 1):
        raise OutilSecuriteAbsent(
            f"pip-audit a échoué avec un code inattendu ({resultat.returncode}) : {resultat.stderr}"
        )
    try:
        rapport = json.loads(resultat.stdout)
    except json.JSONDecodeError as exc:
        raise OutilSecuriteAbsent(f"sortie pip-audit non-JSON : {exc}\n{resultat.stdout}") from None

    dependances = [dependance for dependance in rapport.get("dependencies", []) if dependance.get("vulns")]
    lignes = [f"pip-audit : {len(dependances)} dépendance(s) vulnérable(s) (0 attendu)"]
    for dependance in dependances:
        for vulnerabilite in dependance["vulns"]:
            lignes.append(
                f"  {dependance['name']}=={dependance['version']} — "
                f"{vulnerabilite['id']} : {vulnerabilite.get('description', '')[:200]}"
            )
    return not dependances, "\n".join(lignes)


def main() -> int:
    ok_bandit, rapport_bandit = executer_bandit()
    ok_pip_audit, rapport_pip_audit = executer_pip_audit()

    print(rapport_bandit)
    print(rapport_pip_audit)

    if ok_bandit and ok_pip_audit:
        print("SECURITY_SCAN: VERT (bandit 0 finding, pip-audit 0 CVE)")
        return 0
    print("SECURITY_SCAN: ROUGE — voir détail ci-dessus.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
