"""Élagage reproductible du fork OPSYS-CORE à partir de la release OpenClaw (ADR-0008, R11).

Usage :
    python outils/fork/elaguer_core.py <clone de la release v2026.9.6> <destination vide>

Copie la release en retirant ce qu'OPSYS n'utilise pas (voir docs/research/R11-fork-openclaw.md §3),
ajuste `pnpm-workspace.yaml`, puis vérifie qu'aucun paquet conservé ne dépend d'un paquet retiré.
N'exécute aucun code de la release. Le lockfile se régénère ensuite, sans script de paquet :

    pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Premier niveau retiré. `git-hooks/` : sans lui, `scripts/prepare-git-hooks.mjs` (lancé par
# `pnpm install`) ne reconfigure pas `core.hooksPath` du dépôt OPSYS-AI qui contient core/.
RETIRER_RACINE = frozenset({
    ".git", ".github", ".agents", ".claude", ".vscode", "apps", "crates", "docs", "CHANGELOG",
    "CHANGELOG.md", "qa", "examples", "appcast.xml", "fly.toml", "render.yaml", "git-hooks",
})

# 40 extensions retenues par R11 §3.2, plus deux dépendances d'appui (tests et génération d'images
# des fournisseurs conservés).
EXTENSIONS_GARDEES = frozenset({
    # canaux
    "sms", "whatsapp", "telegram", "signal", "msteams", "slack", "googlechat", "imessage", "imap",
    # fournisseurs de modèles
    "anthropic", "openai", "google", "openrouter", "mistral", "ollama", "lmstudio", "llama-cpp", "litellm",
    # web
    "browser", "firecrawl",
    # mémoire
    "memory-core", "memory-lancedb", "memory-wiki", "active-memory",
    # voix
    "voice-call", "talk-voice", "elevenlabs", "deepgram", "tts-local-cli",
    # infrastructure et sécurité
    "diagnostics-otel", "diagnostics-prometheus", "geolocation", "code-mode-quickjs", "crabbox",
    "policy", "device-pair", "vault",
    # documents, orchestration, contexte
    "document-extract", "llm-task", "tokenjuice",
    # appui
    "test-support", "image-generation-core",
})

# Patches pnpm dont la dépendance disparaît avec l'élagage.
PATCHS_RETIRES = {"matrix-js-sdk@42.3.0": "patches/matrix-js-sdk@42.3.0.patch"}

_CHAMPS_DEPENDANCES = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _ignorer(racine: Path):
    def ignorer(dossier: str, noms: list[str]) -> set[str]:
        courant = Path(dossier)
        if courant == racine:
            return {n for n in noms if n in RETIRER_RACINE}
        if courant == racine / "extensions":
            return {n for n in noms if (courant / n).is_dir() and n not in EXTENSIONS_GARDEES}
        if courant == racine / "patches":
            return {Path(chemin).name for chemin in PATCHS_RETIRES.values()} & set(noms)
        return set()
    return ignorer


def _ajuster_workspace(fichier: Path) -> None:
    lignes = fichier.read_text(encoding="utf-8").splitlines(keepends=True)
    retirees = [ligne for ligne in lignes if ligne.strip() == "- examples/*" or any(
        ligne.strip().startswith((f'"{cle}"', f"{cle}:")) for cle in PATCHS_RETIRES)]
    if len(retirees) != 1 + len(PATCHS_RETIRES):
        raise SystemExit(f"pnpm-workspace.yaml inattendu : lignes à retirer trouvées {retirees!r}")
    fichier.write_text("".join(ligne for ligne in lignes if ligne not in retirees), encoding="utf-8")


def _paquets(racine: Path) -> dict[str, Path]:
    manifestes = [racine / "package.json", racine / "ui" / "package.json"]
    manifestes += sorted((racine / "packages").glob("*/package.json"))
    manifestes += sorted((racine / "extensions").glob("*/package.json"))
    return {json.loads(m.read_text(encoding="utf-8"))["name"]: m for m in manifestes if m.exists()}


def verifier_fermeture(source: Path, destination: Path) -> list[str]:
    """Dépendances de workspace rompues : un paquet conservé qui dépend d'un paquet retiré."""
    avant, apres = _paquets(source), _paquets(destination)
    retires = set(avant) - set(apres)
    ruptures = []
    for nom, manifeste in apres.items():
        contenu = json.loads(manifeste.read_text(encoding="utf-8"))
        for champ in _CHAMPS_DEPENDANCES:
            for dependance in contenu.get(champ, {}):
                if dependance in retires:
                    ruptures.append(f"{nom} ({champ}) → {dependance}")
    return ruptures


def elaguer(source: Path, destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"destination non vide : {destination}")
    manquantes = sorted(n for n in EXTENSIONS_GARDEES if not (source / "extensions" / n).is_dir())
    if manquantes:
        raise SystemExit(f"extensions retenues absentes de la release : {manquantes}")
    shutil.copytree(source, destination, ignore=_ignorer(source), symlinks=True, dirs_exist_ok=True)
    _ajuster_workspace(destination / "pnpm-workspace.yaml")
    ruptures = verifier_fermeture(source, destination)
    if ruptures:
        raise SystemExit("dépendances de workspace rompues :\n" + "\n".join(ruptures))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    elaguer(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    print("élagage terminé")
