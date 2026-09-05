"""AUD-QUAL-003 (#618) : hygiene du snapshot -- config d'hote et backups suivis par git.

Trois regressions scellees, mesurees sur main @ c243af6 (2026-09-05) :
(1) aucun endpoint prive RFC1918 ni chemin /home/<user>/ dans un fichier de config suivi
    -- mesure : .forge/config.ini:26, `litellm_base_url = http://192.168.1.149:4000/v1` ;
(2) aucun artefact de sauvegarde (*.bak/*.orig/*~/*.old) suivi a la racine
    -- mesure : AGENTS.md.pre-proof.bak, CLAUDE.md.pre-proof.bak (introduits par d3c76ac) ;
(3) .forge/config.ini est la config LOCALE (copie de config.ini.example, START_HERE.md:32
    prescrit `cp config.ini.example .forge/config.ini`) : elle ne doit pas etre suivie, et
    .gitignore doit l'ignorer explicitement.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Final

RACINE: Final[Path] = Path(__file__).resolve().parents[2]

_EXTENSIONS_CONFIG: Final[tuple[str, ...]] = (".ini", ".toml", ".yaml", ".yml", ".env", ".cfg")

_RE_IP_PRIVEE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)
_RE_CHEMIN_HOME: Final[re.Pattern[str]] = re.compile(r"/home/[^/\s]+/")


def _fichiers_suivis() -> list[str]:
    """Chemins suivis par git (git ls-files -z, decoupe sur NUL, tel quel)."""
    resultat = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=RACINE,
        check=True,
        capture_output=True,
        text=True,
    )
    return [chemin for chemin in resultat.stdout.split("\0") if chemin]


def _hors_perimetre(chemin: str) -> bool:
    """Modules M/ est interdit a modifier ; les repertoires de tests peuvent contenir des
    fixtures synthetiques qui ressemblent a des IP sans en etre une fuite reelle."""
    segments = chemin.split("/")
    return "Modules M" in segments or "tests" in segments


def test_aucun_endpoint_prive_dans_les_configs_suivies() -> None:
    violations: list[str] = []
    for chemin in _fichiers_suivis():
        if not chemin.endswith(_EXTENSIONS_CONFIG) or _hors_perimetre(chemin):
            continue
        cible = RACINE / chemin
        if not cible.is_file():
            continue
        texte = cible.read_text(encoding="utf-8", errors="replace")
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            nue = ligne.strip()
            if not nue or nue.startswith("#") or nue.startswith(";"):
                continue
            if _RE_IP_PRIVEE.search(ligne) or _RE_CHEMIN_HOME.search(ligne):
                violations.append(f"{chemin}:{numero}: {ligne.strip()}")
    assert violations == [], (
        "endpoint(s) prive(s) ou chemin(s) /home/<user>/ dans une config suivie : "
        + "; ".join(violations)
    )


def test_aucun_artefact_de_sauvegarde_a_la_racine() -> None:
    motifs = ("*.bak", "*.orig", "*~", "*.old")
    violations = [
        chemin
        for chemin in _fichiers_suivis()
        if "/" not in chemin and any(fnmatch.fnmatch(chemin, motif) for motif in motifs)
    ]
    assert violations == [], f"artefact(s) de sauvegarde suivi(s) a la racine : {violations}"


def test_config_locale_forge_non_suivie() -> None:
    suivis = _fichiers_suivis()
    assert ".forge/config.ini" not in suivis, (
        ".forge/config.ini (config locale, cf. config.ini.example) est encore suivi par git"
    )
    lignes = (RACINE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".forge/config.ini" in [ligne.strip() for ligne in lignes], (
        ".gitignore ne contient pas la ligne exacte '.forge/config.ini'"
    )
