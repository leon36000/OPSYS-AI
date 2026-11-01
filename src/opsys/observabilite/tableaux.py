"""Tableaux de coût et de latence par département, calculés sur le journal de traces (lecture seule).

Déterministe : percentiles par rang le plus proche, montants en `Decimal` (jamais un flottant), un coût inconnu n'est
jamais compté comme zéro (`spans_sans_cout`). Sert la CLI (`traces tableau`) et la console (`/observabilite`).
"""

from __future__ import annotations

import dataclasses
import math
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from .traces import Span


@dataclasses.dataclass(frozen=True)
class LigneDepartement:
    departement: str
    appels_outils: int
    tours_agent: int
    refus: int
    attentes_approbation: int
    erreurs: int
    latence_p50_ms: int | None
    latence_p95_ms: int | None
    latence_max_ms: int | None
    jetons_entree: int
    jetons_sortie: int
    cout_estime_usd: str
    spans_sans_cout: int

    @property
    def taux_refus(self) -> str:
        total = self.appels_outils
        return f"{self.refus * 100 / total:.1f} %" if total else "—"


def percentile(valeurs: Sequence[int], p: int) -> int | None:
    """Percentile par rang le plus proche (méthode « nearest rank ») ; None sur une liste vide."""
    if not valeurs:
        return None
    ordonnees = sorted(valeurs)
    return ordonnees[max(0, math.ceil(p / 100 * len(ordonnees)) - 1)]


def agreger(spans: Sequence[Span]) -> list[LigneDepartement]:
    par_dep: dict[str, list[Span]] = {}
    for s in spans:
        par_dep.setdefault(s.departement, []).append(s)
    lignes = []
    for dep in sorted(par_dep):
        groupe = par_dep[dep]
        outils = [s for s in groupe if s.type == "appel_outil"]
        tours = [s for s in groupe if s.type == "tour_agent"]
        latences = [s.duree_ms for s in outils + tours]
        couts = [Decimal(s.cout_estime_usd) for s in groupe if s.cout_estime_usd is not None]
        lignes.append(LigneDepartement(
            departement=dep, appels_outils=len(outils), tours_agent=len(tours),
            refus=sum(1 for s in groupe if s.issue == "refus"),
            attentes_approbation=sum(1 for s in groupe if s.issue == "attente_approbation"),
            erreurs=sum(1 for s in groupe if s.issue == "erreur"),
            latence_p50_ms=percentile(latences, 50), latence_p95_ms=percentile(latences, 95),
            latence_max_ms=max(latences) if latences else None,
            jetons_entree=sum(s.jetons_entree or 0 for s in groupe),
            jetons_sortie=sum(s.jetons_sortie or 0 for s in groupe),
            cout_estime_usd=str(sum(couts, Decimal("0")).quantize(Decimal("0.000001"))),
            spans_sans_cout=sum(1 for s in tours if s.cout_estime_usd is None)))
    return lignes


def refus_par_code(spans: Sequence[Span], limite: int = 10) -> list[tuple[str, int]]:
    compte = Counter(s.code_refus for s in spans if s.issue == "refus" and s.code_refus)
    return sorted(compte.items(), key=lambda kv: (-kv[1], kv[0]))[:limite]


def rendre_texte(lignes: Sequence[LigneDepartement], refus: Sequence[tuple[str, int]] = ()) -> str:
    """Tableau en texte fixe, lisible dans un terminal. Coûts ESTIMÉS (tarifs configurés), pas la facture."""
    if not lignes:
        return "Aucune trace enregistrée sur la période."
    entetes = ("Département", "Outils", "Tours", "Refus", "Attente", "Err.", "p50 ms", "p95 ms", "max ms", "Jetons e/s",
               "Coût est. USD", "Sans coût")
    rangees: list[tuple[str, ...]] = [entetes]
    for ln in lignes:
        rangees.append((ln.departement, str(ln.appels_outils), str(ln.tours_agent), f"{ln.refus} ({ln.taux_refus})",
                        str(ln.attentes_approbation), str(ln.erreurs),
                        *(str(v) if v is not None else "—" for v in (ln.latence_p50_ms, ln.latence_p95_ms,
                                                                     ln.latence_max_ms)),
                        f"{ln.jetons_entree}/{ln.jetons_sortie}", ln.cout_estime_usd, str(ln.spans_sans_cout)))
    largeurs = [max(len(r[i]) for r in rangees) for i in range(len(entetes))]
    sortie = ["  ".join(c.ljust(largeurs[i]) for i, c in enumerate(r)).rstrip() for r in rangees]
    sortie.insert(1, "  ".join("-" * w for w in largeurs))
    if refus:
        sortie += ["", "Refus les plus fréquents :"] + [f"  {code}  ×{n}" for code, n in refus]
    sortie += ["", "Coûts estimés d'après les tarifs configurés ; ce n'est pas la facture du fournisseur."]
    return "\n".join(sortie)


def vers_json(lignes: Sequence[LigneDepartement], refus: Sequence[tuple[str, int]] = ()) -> dict[str, Any]:
    return {"departements": [dataclasses.asdict(ln) | {"taux_refus": ln.taux_refus} for ln in lignes],
            "refus_par_code": [{"code": c, "n": n} for c, n in refus]}
