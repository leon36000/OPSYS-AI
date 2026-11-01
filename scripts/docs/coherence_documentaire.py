"""Contrôles de cohérence documentaire (stdlib, hors ligne) : liens relatifs, chiffres clés, commandes citées.

Fonctions pures paramétrées par `racine` : `tests/test_coherence_documentaire.py` les applique au vrai dépôt ET à des
arbres fictifs (cas négatifs). Aucune ne modifie un fichier.
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import re
from pathlib import Path

# Dossiers dont les .md sont contrôlés (le reste du dépôt, dont core/ et mobile/, a ses propres documents).
RACINES_MD = ("docs", "packs", "integrations", "install", "deploy")
FICHIERS_RACINE_MD = ("README.md", "AGENTS.md", "CLAUDE.md", "00-DIGEST.md")
EXCLUS = ("node_modules",)
_LIEN = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE = re.compile(r"```.*?```", re.S)
_CODE_EN_LIGNE = re.compile(r"`[^`\n]*`")
_COMMANDE = re.compile(r"(?:opsys-metier|opsys\s+metier)\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?")
BLOC_DEBUT, BLOC_FIN = "<!-- chiffres:debut -->", "<!-- chiffres:fin -->"


def fichiers_markdown(racine: Path) -> list[Path]:
    trouves = [racine / f for f in FICHIERS_RACINE_MD if (racine / f).is_file()]
    for dossier in RACINES_MD:
        base = racine / dossier
        if base.is_dir():
            trouves += [p for p in base.rglob("*.md") if not any(x in p.parts for x in EXCLUS)]
    for readme in racine.glob("departments/*/README.md"):
        trouves.append(readme)
    return sorted(set(trouves))


def liens_relatifs(texte: str) -> list[str]:
    """Cibles des liens Markdown relatifs (hors blocs de code, URL, ancres, courriels, chevrons)."""
    sans_code = _FENCE.sub("", texte)
    sortie = []
    for m in _LIEN.finditer(sans_code):
        cible = m.group(1)
        if re.match(r"^(https?:|mailto:|tel:|#)", cible) or "<" in cible or ">" in cible:
            continue
        sortie.append(cible)
    return sortie


def liens_casses(racine: Path, fichiers: list[Path]) -> dict[str, list[str]]:
    """`{fichier relatif à racine: [cibles introuvables]}` ; une cible absolue (`/workspace/...`) est introuvable par définition."""
    casses: dict[str, list[str]] = {}
    for f in fichiers:
        for cible in liens_relatifs(f.read_text(encoding="utf-8", errors="replace")):
            chemin = cible.split("#")[0]
            if not chemin:
                continue
            existe = (f.parent / chemin).exists() if not chemin.startswith("/") else False
            if not existe:
                casses.setdefault(f.relative_to(racine).as_posix(), []).append(cible)
    return {k: sorted(set(v)) for k, v in sorted(casses.items())}


def commandes_citees(texte: str) -> set[tuple[str, ...]]:
    """Commandes `opsys-metier …` ou `opsys metier …` citées (première et, si présente, deuxième parole)."""
    return {tuple(x for x in m.groups() if x) for m in _COMMANDE.finditer(texte)}


def commandes_invalides(citees: set[tuple[str, ...]], valides: set[str]) -> list[str]:
    """Commandes citées qui n'existent pas dans le parseur. `valides` : « verifier », « pack choisir »…

    Le deuxième mot n'est jugé que si le premier a des sous-commandes (sinon c'est un argument, ex. `mode m05 supervise`).
    """
    premiers = {v.split()[0] for v in valides}
    avec_sous = {v.split()[0] for v in valides if " " in v}
    mauvaises = []
    for c in sorted(citees):
        if c[0] not in premiers:
            mauvaises.append(" ".join(c[:1]))
        elif len(c) > 1 and c[0] in avec_sous and " ".join(c[:2]) not in valides:
            mauvaises.append(" ".join(c[:2]))
    return sorted(set(mauvaises))


def migrations(racine: Path) -> tuple[int, str]:
    """`(nombre de fichiers de migration, tête alembic)` ; échoue s'il y a plusieurs têtes ou une chaîne rompue."""
    dossier = racine / "src" / "opsys" / "stockage" / "migrations" / "versions"
    revs: dict[str, str | None] = {}
    for f in sorted(dossier.glob("[0-9]*.py")):
        texte = f.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", texte, re.M).group(1)
        down = re.search(r"^down_revision\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", texte, re.M).group(1)
        revs[rev] = down
    parents = {d for d in revs.values() if d}
    tetes = sorted(set(revs) - parents)
    if len(tetes) != 1:
        raise AssertionError(f"plusieurs têtes alembic : {tetes}")
    return len(revs), tetes[0]


def chiffres_du_bloc(texte: str) -> dict[str, str]:
    """Lit le tableau `| Libellé | valeur |` entre les repères du bloc des chiffres clés."""
    debut, fin = texte.index(BLOC_DEBUT), texte.index(BLOC_FIN)
    chiffres = {}
    for ligne in texte[debut:fin].splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", ligne)
        if m and set(m.group(1)) - set("-: ") and m.group(1) != "Chiffre":
            chiffres[m.group(1)] = m.group(2)
    return chiffres
