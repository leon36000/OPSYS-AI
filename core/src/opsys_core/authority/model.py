"""Modèle du registre d'autorité (C03-002) — `AuthorityRecord`, résultat
de la jointure entre la carte des chemins ratifiée (C00-004, audit/core-
baseline/AUTHORITY-MAP.csv) et la carte d'autorité métier ratifiée (chore
PR #501, audit/core-baseline/BUSINESS-AUTHORITY-MAP-M1-M10.csv).

Revue d'architecture AVANT code (subagent `architecte`, Claude Opus 5
natif, 4 questions fermées, 2026-08-11) a tranché :

- 5e champ `status` (au-delà des 4 de la spec `AuthorityRecord(aggregate,
  owner, read_port, write_port)`) : `RESOLVED` ou `AMENDMENT_REQUIRED` —
  c'est LUI que tout consommateur doit tester, jamais le préfixe de
  `read_port`/`write_port` (cf. `registry.py` pour le pourquoi : la garde
  C00-004 existante — `WriterCoreSurModulesRefuse` — ne se déclenche que
  sur la FORME d'un `write_port` pointant une racine de module ; une
  sentinelle textuelle la contournerait en silence, un `status` explicite
  ne peut pas être contourné de la même façon).
- Défaut `status="RESOLVED"` : la signature déclarée par la spec reste
  constructible telle quelle (`AuthorityRecord("ledger","M5-financecore",
  "Modules M/M5-financecore/src","Modules M/M5-financecore/src")` reste
  valide sans argument supplémentaire).
"""
from __future__ import annotations

from dataclasses import dataclass

STATUTS_VALIDES = frozenset({"RESOLVED", "AMENDMENT_REQUIRED"})

# Préfixe sentinelle pour un port non résolu — jamais un chemin réel ne
# peut commencer ainsi (tous les chemins réels du dépôt commencent par
# `Modules M/` ou `core/`), donc aucune collision possible avec une
# donnée légitime.
PREFIXE_NON_RESOLU = "UNRESOLVED"


class StatutIncoherentAvecPort(Exception):
    """`status="AMENDMENT_REQUIRED"` doit TOUJOURS porter des ports
    préfixés `UNRESOLVED` (et réciproquement, `status="RESOLVED"` ne doit
    JAMAIS porter un tel préfixe) — sinon un consommateur qui lit l'un des
    deux signaux verrait une réponse différente selon lequel il choisit,
    ce qui romprait la garantie « status est la seule source de vérité »
    documentée ci-dessus."""


@dataclass(frozen=True)
class AuthorityRecord:
    """Un agrégat métier, son propriétaire (nom LONG de module — seul
    identifiant de module réellement enregistré dans ce dépôt, cf.
    `registries/modules.yaml` — jamais le nom court `M5` de la carte
    métier source) et ses ports de chemin réels, ou une sentinelle
    explicite si aucun chemin ratifié ne peut être résolu sans deviner
    (cas CORE — cf. `registry.py`)."""

    aggregate: str
    owner: str
    read_port: str
    write_port: str
    status: str = "RESOLVED"

    def __post_init__(self) -> None:
        for champ in ("aggregate", "owner", "read_port", "write_port"):
            valeur = getattr(self, champ)
            if not isinstance(valeur, str) or not valeur.strip():
                raise ValueError(f"{champ} doit être une str non vide : {valeur!r}")
        if self.status not in STATUTS_VALIDES:
            raise ValueError(f"status {self.status!r} hors liste blanche {sorted(STATUTS_VALIDES)}")

        port_non_resolu = self.read_port.startswith(PREFIXE_NON_RESOLU) or self.write_port.startswith(PREFIXE_NON_RESOLU)
        if self.status == "AMENDMENT_REQUIRED" and not port_non_resolu:
            raise StatutIncoherentAvecPort(
                f"status=AMENDMENT_REQUIRED mais aucun port ne porte le préfixe "
                f"{PREFIXE_NON_RESOLU!r} : read_port={self.read_port!r} write_port={self.write_port!r}"
            )
        if self.status == "RESOLVED" and port_non_resolu:
            raise StatutIncoherentAvecPort(
                f"status=RESOLVED mais un port porte le préfixe {PREFIXE_NON_RESOLU!r} : "
                f"read_port={self.read_port!r} write_port={self.write_port!r}"
            )
