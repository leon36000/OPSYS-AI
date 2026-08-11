"""Scan CodeQL réel (SAST approfondi, local) sur core/src — chantier
CI-hardening, réponse à la demande explicite « ajoute CodeQL en local si
possible ».

PORTÉE ASSUMÉE — LOCAL, PAS CI : le CLI CodeQL est un outil installé
manuellement (bundle ~578 Mo, `github/codeql-action` releases, jamais un
paquet pip), absent de tout runner GitHub Actions nu et non caché dans ce
dépôt. Le câbler en job CI bloquant ajouterait un coût de téléchargement/
extraction à CHAQUE run de CHAQUE PR sans que cela ait été demandé — la
demande était explicitement « en local si possible », pas « en CI ». Ce
script est donc un outil de PRÉ-MERGE LOCAL, au même titre que
`structure_lint.py` invoqué manuellement avant commit — PAS encore câblé
dans core-ci.yml. Le câblage CI reste une question ouverte, signalée à
Nathan plutôt que décidée unilatéralement ici (cf. discipline "surface it,
never resolve it silently").

MÉCANISME DE SUPPRESSION DES FAUX POSITIFS — vérifié, PAS supposé : le
commentaire inline `# lgtm[rule-id]` (suppression CodeQL/LGTM historique)
a été testé empiriquement sur ce CLI (codeql 2.26.2) via une base de
données jetable à 2 lignes, l'une commentée `# lgtm[...]`, l'autre non —
LES DEUX apparaissent identiquement comme `results` actifs dans le SARIF
produit par `codeql database analyze`, sans clé `suppressions`. Ce
mécanisme de suppression est en réalité appliqué CÔTÉ SERVEUR par GitHub
Code Scanning APRÈS upload du SARIF (appariement par ligne), jamais par le
CLI local lui-même — inutile ici puisqu'aucun upload GitHub Code Scanning
n'est en jeu (portée = local uniquement, voir ci-dessus). Mécanisme retenu
à la place : allowlist explicite ci-dessous, clé (règle, chemin, ligne),
CHAQUE entrée porte sa justification individuelle et sa preuve — même
discipline que les 2 suppressions inline nommées de bandit (ex. B107,
run_security_scan.py), adaptée ici en table externe car l'inline ne
fonctionne pas pour CodeQL.

DÉRIVE DE L'ALLOWLIST — assumée et rendue visible, jamais silencieuse :
l'allowlist est indexée par NUMÉRO DE LIGNE (le SARIF de CodeQL ne fournit
rien de plus stable pour ces cas). Toute entrée qui ne matche plus AUCUN
finding du run courant est signalée en avertissement NON BLOQUANT (la
ligne a pu se déplacer — à re-trianger consciemment — ou le finding a pu
disparaître, ce qui est sans risque). Tout finding qui ne matche AUCUNE
entrée de l'allowlist est un ROUGE bloquant, qu'il soit nouveau ou déplacé
— jamais un pass silencieux sur un déplacement supposé anodin.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPO_ROOT / "core" / "src"
_SUITE = "python-security-and-quality.qls"

# (rule_id, chemin RELATIF à --source-root, ligne) -> justification individuelle.
# Chemins/lignes vérifiés le 2026-08-11 sur le SARIF produit par ce script
# lui-même contre le commit fc48cee (branche opsys-core/chore/ci-hardening-gates-reels).
_FAUX_POSITIFS_CONNUS: dict[tuple[str, str, int], str] = {
    (
        "py/ineffectual-statement", "opsys_core/persistence/connection.py", 98,
    ): "corps `...` de méthode Protocol (fermer(), C05-001) — idiome PEP 544 "
       "pour un contrat sans implémentation. Même motif syntaxique déjà exempté "
       "par no_stub_ast.py (vérifié sur node.bases lors de la revue d'architecture).",
    (
        "py/ineffectual-statement", "opsys_core/ports/contracts.py", 42,
    ): "idem — DomainPort.port_id, @property sur Protocol (C04-001).",
    (
        "py/ineffectual-statement", "opsys_core/ports/contracts.py", 52,
    ): "idem — ProviderPort.provider_id.",
    (
        "py/ineffectual-statement", "opsys_core/ports/contracts.py", 63,
    ): "idem — ModulePort.module_id.",
    (
        "py/ineffectual-statement", "authz/engine.py", 12,
    ): "corps `...` de méthode @abstractmethod sur ABC (AuthzEngine.add_tuple) — "
       "même idiome que Protocol, classe jamais instanciée directement.",
    (
        "py/ineffectual-statement", "authz/engine.py", 16,
    ): "idem — AuthzEngine.remove_tuple.",
    (
        "py/ineffectual-statement", "authz/engine.py", 20,
    ): "idem — AuthzEngine.check.",
    (
        "py/ineffectual-statement", "authz/engine.py", 24,
    ): "idem — AuthzEngine.list_objects.",
    (
        "py/ineffectual-statement", "opsys_core/objects/port.py", 113,
    ): "idem — ObjectStorePort.put, Protocol @runtime_checkable (C04-004+).",
    (
        "py/ineffectual-statement", "opsys_core/objects/port.py", 117,
    ): "idem — ObjectStorePort.get.",
    (
        "py/ineffectual-statement", "config/vault.py", 69,
    ): "idem — SecretProvider.get_secret, @abstractmethod sur ABC fail-closed.",
    (
        "py/unsafe-cyclic-import", "opsys_core/persistence/repository.py", 22,
    ): "import sous `if TYPE_CHECKING:` — jamais exécuté au runtime (C05-003). "
       "Vérifié empiriquement le 2026-08-11 : les 2 ordres d'import possibles "
       "(uow puis repository, et l'inverse) réussissent sans ImportError. CodeQL "
       "ne semble pas spécialiser cet idiome comme le fait mypy.",
    (
        "py/unsafe-cyclic-import", "opsys_core/persistence/uow.py", 62,
    ): "idem, sens inverse — même paire d'imports différés.",
}


class OutilCodeQLAbsent(RuntimeError):
    """Le CLI CodeQL n'est pas installé/atteignable sur cette machine."""


def _localiser_codeql() -> str:
    exe = shutil.which("codeql")
    if exe:
        return exe
    candidat = Path.home() / ".local" / "bin" / "codeql"
    if candidat.exists():
        return str(candidat)
    raise OutilCodeQLAbsent(
        "codeql introuvable (ni sur PATH, ni ~/.local/bin/codeql). "
        "Installation manuelle requise (bundle github/codeql-action releases) "
        "— hors périmètre de ce script, cf. docstring module (outil local, "
        "pas encore packagé/caché pour CI)."
    )


def _executer(codeql: str, argv: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [codeql, *argv], capture_output=True, text=True, timeout=timeout, cwd=_REPO_ROOT,
    )


def construire_base(codeql: str, db_path: Path) -> tuple[bool, str]:
    resultat = _executer(
        codeql,
        [
            "database", "create", str(db_path),
            "--language=python",
            f"--source-root={_SOURCE_ROOT}",
            "--overwrite",
        ],
        timeout=600,
    )
    ok = resultat.returncode == 0
    sortie = (resultat.stdout + resultat.stderr).strip()
    return ok, f"database create : rc={resultat.returncode}\n{sortie[-2000:]}"


def analyser_base(codeql: str, db_path: Path, sarif_path: Path) -> tuple[bool, str]:
    resultat = _executer(
        codeql,
        [
            "database", "analyze", str(db_path), _SUITE,
            "--format=sarif-latest", f"--output={sarif_path}",
        ],
        timeout=600,
    )
    ok = resultat.returncode == 0
    sortie = (resultat.stdout + resultat.stderr).strip()
    return ok, f"database analyze : rc={resultat.returncode}\n{sortie[-1000:]}"


def trier_resultats(sarif_path: Path) -> tuple[bool, str]:
    data = json.loads(sarif_path.read_text(encoding="utf-8"))
    resultats = data["runs"][0]["results"]

    non_alloues: list[str] = []
    connus_vus: set[tuple[str, str, int]] = set()

    for res in resultats:
        rule_id = res["ruleId"]
        loc = res["locations"][0]["physicalLocation"]
        chemin = loc["artifactLocation"]["uri"]
        ligne = loc["region"]["startLine"]
        cle = (rule_id, chemin, ligne)
        if cle in _FAUX_POSITIFS_CONNUS:
            connus_vus.add(cle)
        else:
            non_alloues.append(f"  NOUVEAU/NON-ALLOUÉ : {rule_id} | {chemin}:{ligne} | {res['message']['text']}")

    perimes = set(_FAUX_POSITIFS_CONNUS) - connus_vus

    lignes = [f"CodeQL : {len(resultats)} finding(s) brut(s), {len(connus_vus)} connu(s)/justifié(s), {len(non_alloues)} non-alloué(s)."]
    if connus_vus:
        lignes.append("Connus/justifiés (ignorés, voir _FAUX_POSITIFS_CONNUS pour la preuve) :")
        for cle in sorted(connus_vus):
            lignes.append(f"  - {cle[0]} | {cle[1]}:{cle[2]}")
    if perimes:
        lignes.append("AVERTISSEMENT (non bloquant) — entrée(s) allowlist sans correspondance dans ce run (ligne déplacée à re-trianger, ou finding disparu) :")
        for cle in sorted(perimes):
            lignes.append(f"  - {cle[0]} | {cle[1]}:{cle[2]}")
    if non_alloues:
        lignes.append("ROUGE — finding(s) non justifié(s) :")
        lignes.extend(non_alloues)

    ok = not non_alloues
    return ok, "\n".join(lignes)


def main() -> int:
    try:
        codeql = _localiser_codeql()
    except OutilCodeQLAbsent as exc:
        print(f"CODEQL: BLOCKED — {exc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="codeql-run-") as tmp:
        db_path = Path(tmp) / "db"
        sarif_path = Path(tmp) / "results.sarif"

        ok, rapport = construire_base(codeql, db_path)
        print(rapport)
        if not ok:
            print("CODEQL: ROUGE — échec database create.", file=sys.stderr)
            return 1

        ok, rapport = analyser_base(codeql, db_path, sarif_path)
        print(rapport)
        if not ok:
            print("CODEQL: ROUGE — échec database analyze.", file=sys.stderr)
            return 1

        ok, rapport = trier_resultats(sarif_path)
        print(rapport)

    if ok:
        print("CODEQL: VERT (tous les findings sont soit absents, soit connus/justifiés).")
        return 0
    print("CODEQL: ROUGE — voir détail ci-dessus.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
