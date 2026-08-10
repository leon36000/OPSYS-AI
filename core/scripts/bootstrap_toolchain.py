"""Bootstrap de la toolchain — verrou (lock) reproductible (C02-001).

Rendre l'environnement, les dépendances et les checks bloquants
reproductibles avant le Core. Ce module produit un ``ToolchainLock`` —
contrat qui garantit qu'un outil inventorié aujourd'hui (Python, uv/pip,
clients PostgreSQL, Docker/Podman, Helm, outils de preuve) est LE MÊME
BINAIRE demain, jamais une version approximative ni un binaire substitué
silencieusement.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass

_EXACT_VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ToolSpec:
    version: str
    digest: str


@dataclass(frozen=True)
class ToolchainLock:
    tools: dict[str, ToolSpec]

    def __post_init__(self) -> None:
        # frozen=True bloque la RÉAFFECTATION de l'attribut (lock.tools = ...)
        # mais pas la mutation du dict qu'il référence (lock.tools["x"] = ...).
        # On fige donc aussi le contenu : vue en lecture seule sur une copie
        # défensive, via le type mappingproxy natif (aucun import requis —
        # object.__dict__ est toujours de ce type). object.__setattr__ est
        # l'idiome documenté pour muter un champ dérivé sur une dataclass gelée.
        object.__setattr__(self, "tools", type(object.__dict__)(dict(self.tools)))


def validate_toolchain_lock(lock: ToolchainLock) -> list[str]:
    """Retourne les erreurs de validation du lock (liste vide = valide).

    Fonction de mesure : ne lève jamais d'exception pour un contenu
    invalide, elle le signale dans la liste retournée.
    """
    erreurs: list[str] = []
    for nom, spec in lock.tools.items():
        if not _EXACT_VERSION_RE.match(spec.version):
            erreurs.append(f"{nom}: version non exacte ({spec.version!r})")
        if not spec.digest or not _SHA256_HEX_RE.match(spec.digest):
            erreurs.append(f"{nom}: digest absent ou invalide")
    return erreurs


def detect_drift(lock: ToolchainLock, mesures: dict[str, ToolSpec]) -> list[str]:
    """Compare le lock aux mesures réellement observées sur le système.

    Retourne les noms des outils en dérive (absents des mesures, ou dont
    la version et/ou le digest mesuré diffère du lock), dans l'ordre
    d'itération de ``lock.tools``.
    """
    derives: list[str] = []
    for nom, spec_verrou in lock.tools.items():
        if nom not in mesures:
            derives.append(nom)
            continue
        mesure = mesures[nom]
        if mesure.version != spec_verrou.version or mesure.digest != spec_verrou.digest:
            derives.append(nom)
    return derives


def inventorier_toolchain(outils: dict[str, list[str]]) -> tuple[ToolchainLock, list[str]]:
    """Mesure réellement chaque outil (version + digest du binaire résolu).

    ``outils`` associe un nom d'outil à l'argv permettant d'obtenir sa
    version (ex. ``{"python": [sys.executable, "--version"]}``). Ne tente
    jamais d'installer ou de télécharger quoi que ce soit : un outil
    absent ou dont la mesure échoue devient toujours un blocker explicite
    dans la liste retournée, jamais une exception non gérée, jamais une
    entrée fantôme dans le lock produit.
    """
    trouves: dict[str, ToolSpec] = {}
    blockers: list[str] = []

    for nom, argv in outils.items():
        chemin = shutil.which(argv[0])
        if chemin is None:
            blockers.append(f"{nom}: introuvable dans PATH")
            continue

        try:
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            blockers.append(f"{nom}: {exc}")
            continue

        sortie = (cp.stdout + cp.stderr).strip()
        match = re.search(r"\d+(\.\d+){1,3}", sortie)
        if match is None:
            blockers.append(f"{nom}: version illisible dans la sortie")
            continue

        try:
            with open(chemin, "rb") as fh:
                contenu = fh.read()
        except OSError:
            blockers.append(f"{nom}: digest illisible")
            continue

        digest = hashlib.sha256(contenu).hexdigest()
        trouves[nom] = ToolSpec(version=match.group(0), digest=digest)

    return ToolchainLock(tools=trouves), blockers
