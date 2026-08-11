"""Scan de sécurité Core — bandit (SAST) + pip-audit (CVE dépendances).

Construit pour remplacer le placeholder BLOCKED du job CI `security`
(core-ci.yml, C02-005) — mécanisme réel, jamais inventé : les 2 outils
sont ceux littéralement nommés dans le message BLOCKED d'origine
("aucun scanner de sécurité (ex. bandit, pip-audit) n'est référencé
nulle part dans ce dépôt à ce jour"), tous deux déjà installés
localement au moment de l'écriture (mesuré : `which bandit pip-audit`).

Reproductible en LOCAL et en CI avec la MÊME commande — pas de logique
dupliquée entre les deux (le job CI invoque ce script directement).

Bandit : config dans core/pyproject.toml ([tool.bandit], skips=["B101"]
— asserts de test, jamais un défaut réel, cf. justification dans le
fichier). Périmètre : core/src/ (jamais Modules M/, hors périmètre de
cette tâche comme de tout core/*). Mesuré AVANT ce script (127 findings
bruts → 0 après config + `# nosec` scopés individuellement, chacun
vérifié par lecture directe, jamais supposé) : 0 finding attendu en
fonctionnement normal, tout NOUVEAU finding doit bloquer (jamais un
pass silencieux).

pip-audit : `--disable-pip` OBLIGATOIRE sur cette machine — `ensurepip`
indisponible (`apt install python3.12-venv` interdit par les
interdictions du projet, aucun sudo) ; `--disable-pip` scanne les
versions ÉPINGLÉES de core/requirements.lock directement contre la
base OSV, sans tenter de résoudre/installer un environnement isolé.

Aucune méthode de suppression globale de type "ignore tout" : chaque
exemption est scopée à un test_id bandit précis, sur une ligne précise,
avec une justification en clair — jamais un fichier entier exclu sans
raison nommée (cf. core/pyproject.toml, exclude_dirs = [] volontaire).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_SRC = _REPO_ROOT / "core" / "src"
_PYPROJECT = _REPO_ROOT / "core" / "pyproject.toml"
_REQUIREMENTS_LOCK = _REPO_ROOT / "core" / "requirements.lock"


class OutilSecuriteAbsent(RuntimeError):
    """bandit ou pip-audit n'est pas installé/exécutable sur cette machine —
    échec explicite, jamais un skip silencieux (même discipline que le
    placeholder BLOCKED remplacé par ce script)."""


def _executer(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise OutilSecuriteAbsent(f"outil introuvable : {argv[0]} ({exc})") from None
    except subprocess.TimeoutExpired as exc:
        raise OutilSecuriteAbsent(f"délai dépassé (300s) : {' '.join(argv)} ({exc})") from None


def executer_bandit() -> tuple[bool, str]:
    """Retourne (ok, rapport_texte). ok=False si bandit trouve un finding
    de N'IMPORTE QUELLE sévérité APRÈS la configuration de
    core/pyproject.toml (skips=B101 + nosec scopés) — un scanner qui
    laisse passer un finding non exempté explicitement ne serait pas
    un scanner réel."""
    resultat = _executer(
        ["bandit", "-c", str(_PYPROJECT), "-r", str(_CORE_SRC), "-f", "json"]
    )
    # bandit : rc=0 aucun finding, rc=1 finding(s) trouvé(s), rc>1 = erreur outil.
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
    for f in findings:
        lignes.append(
            f"  {f['filename']}:{f['line_number']} {f['test_id']} "
            f"{f['issue_severity']}/{f['issue_confidence']} — {f['issue_text']}"
        )
    return (len(findings) == 0), "\n".join(lignes)


def executer_pip_audit() -> tuple[bool, str]:
    """Retourne (ok, rapport_texte). ok=False si une CVE connue affecte
    une version ÉPINGLÉE de core/requirements.lock."""
    lignes_verrou = [
        ligne
        for ligne in _REQUIREMENTS_LOCK.read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.strip().startswith("#")
    ]
    fichier_tmp = _REPO_ROOT / ".security-scan-requirements.tmp"
    fichier_tmp.write_text("\n".join(lignes_verrou) + "\n", encoding="utf-8")
    try:
        resultat = _executer(
            [
                "pip-audit",
                "-r", str(fichier_tmp),
                "--disable-pip",
                "--desc",
                "-f", "json",
            ]
        )
    finally:
        fichier_tmp.unlink(missing_ok=True)

    # pip-audit : rc=0 aucune vulnérabilité, rc=1 vulnérabilité(s) trouvée(s).
    if resultat.returncode not in (0, 1):
        raise OutilSecuriteAbsent(
            f"pip-audit a échoué avec un code inattendu ({resultat.returncode}) : {resultat.stderr}"
        )
    try:
        rapport = json.loads(resultat.stdout)
    except json.JSONDecodeError as exc:
        raise OutilSecuriteAbsent(f"sortie pip-audit non-JSON : {exc}\n{resultat.stdout}") from None

    dependances_vulnerables = [d for d in rapport.get("dependencies", []) if d.get("vulns")]
    lignes = [f"pip-audit : {len(dependances_vulnerables)} dépendance(s) vulnérable(s) (0 attendu)"]
    for d in dependances_vulnerables:
        for v in d["vulns"]:
            lignes.append(f"  {d['name']}=={d['version']} — {v['id']} : {v.get('description', '')[:200]}")
    return (len(dependances_vulnerables) == 0), "\n".join(lignes)


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
