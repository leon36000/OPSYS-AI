"""Les routines planifiées de M10 (mémoire) : la consolidation nocturne des affaires touchées la veille, l'audit
hebdomadaire
« non-oubli » et le calcul des KPI du manifeste. Déclarées au manifeste de M10 (bloc `routines_planifiees`),
déclenchées par le
planificateur durable (docs/architecture/PLANIFICATION.md §10).

La consolidation n'est plus un tour d'agent : l'ÉNUMÉRATEUR (`m10_lister_affaires_a_consolider`, N0) désigne les
affaires dont
le fait durable de la veille manque ou ne cite pas toutes les sources, et chacune est consolidée par l'outil existant
(`m10_consolider_affaire`, N2, idempotent) sous son propre bail : l'échec d'une affaire n'arrête pas les autres.
L'audit et les KPI
écrivent un rapport au registre `rapports_routine` (consultable par `m10_lire_rapports_routine`). Aucun contact
externe, aucune
promotion ni confirmation (décisions humaines). En ombre, seule la lecture est appelée : rien n'est écrit.

Le journal du planificateur ne porte jamais l'identifiant d'une affaire : la ressource est `<jour>|<empreinte de
l'affaire>`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .bail import Bail
from .planificateur import RESSOURCES_PAR_PASSAGE, Contexte, RefusExecuteur
from .routines import ExecuteurRoutine

LISTER = "m10_lister_affaires_a_consolider"
CONSOLIDER = "m10_consolider_affaire"
AUDIT = "m10_executer_audit_non_oubli"
KPIS = "m10_calculer_kpis"
JOURS_AUDIT = 7


class ConsolidationAffaires(ExecuteurRoutine):
    """La veille de chaque affaire touchée : un fait durable qui cite ses sources (rien de plus si déjà fait)."""

    def __init__(self, declaration: Any) -> None:
        super().__init__(declaration)
        self._cibles: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _pseudonyme(affaire: str) -> str:
        return hashlib.sha256(affaire.encode("utf-8")).hexdigest()[:16]

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, aujourd_hui = self.echeance(ctx)
        if not due:
            return []
        veille = (date.fromisoformat(aujourd_hui) - timedelta(days=1)).isoformat()
        liste = self.resultat(self._appeler(ctx, LISTER, {"jour": veille, "limite": RESSOURCES_PAR_PASSAGE}))
        self._cibles = {}
        for affaire in liste["a_consolider"]:
            ressource = f"{veille}|{self._pseudonyme(affaire)}"
            if getattr(ctx, "mode", "actif") == "ombre" and self.deja_fait(ressource, ctx):
                continue
            self._cibles[ressource] = (veille, affaire)
        return sorted(self._cibles)

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        self._journaliser_aurait(ressource, aurait=1)
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        cible = self._cibles.get(ressource)
        if cible is None:
            raise RefusExecuteur("REJ-PLAN-ROUTINE-RESSOURCE-INCONNUE")
        jour, affaire = cible
        ctx.exiger_actif(bail)
        reponse = self._appeler(
            ctx, CONSOLIDER, {"affaire_id": affaire, "jour": jour, "horodatage": self.instant_iso(ctx)}
        )
        if reponse.get("verdict"):
            raise RefusExecuteur(str(reponse["verdict"]))
        ecrit = 1 if reponse.get("ecrit") else 0
        self._clore(ressource, None, etapes=1, affaires=ecrit)
        return {"etapes": 1, "affaires": ecrit}


class AuditNonOubli(ExecuteurRoutine):
    """Une fois par semaine prévue : l'audit « non-oubli », rapport consultable."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        rapport = self.resultat(
            self._appeler(ctx, AUDIT, {"fin": self.instant_iso(ctx), "jours": JOURS_AUDIT, "ecrire": False})
        )
        self._journaliser_aurait(ressource, aurait=1, oublis=int(rapport["nb_oublis"]))
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        rapport = self.resultat(self._appeler(ctx, AUDIT, {"fin": self.instant_iso(ctx), "jours": JOURS_AUDIT}))
        self._clore(ressource, None, etapes=1, oublis=int(rapport["nb_oublis"]), rapports=1 if rapport["ecrit"] else 0)
        return {"etapes": 1, "oublis": int(rapport["nb_oublis"]), "rapports": 1 if rapport["ecrit"] else 0}


class KpisMemoire(ExecuteurRoutine):
    """Une fois par jour, après la consolidation : les KPI du manifeste, vers un résultat consultable."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    @staticmethod
    def _cycle(jour: str, fuseau: str) -> tuple[str, str]:
        """La journée locale du cycle de consolidation, en UTC : `[minuit local, minuit local suivant[`."""
        zone = ZoneInfo(fuseau)
        debut = datetime.combine(date.fromisoformat(jour), datetime.min.time(), zone)
        fin = datetime.combine(date.fromisoformat(jour) + timedelta(days=1), datetime.min.time(), zone)
        return debut.astimezone(UTC).isoformat(), fin.astimezone(UTC).isoformat()

    def _arguments(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        debut, fin = self._cycle(ressource, ctx.ports.fuseau)
        return {"jour": ressource, "debut_cycle": debut, "fin_cycle": fin, "horodatage": self.instant_iso(ctx)}

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        calcul = self.resultat(self._appeler(ctx, KPIS, {**self._arguments(ressource, ctx), "ecrire": False}))
        self._journaliser_aurait(
            ressource, aurait=1, elements=sum(1 for k in calcul["kpis"].values() if k.get("calculable"))
        )
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        calcul = self.resultat(self._appeler(ctx, KPIS, self._arguments(ressource, ctx)))
        self._clore(ressource, None, etapes=1, rapports=1 if calcul["ecrit"] else 0)
        return {"etapes": 1, "rapports": 1 if calcul["ecrit"] else 0}


ROUTINES = {
    "m10:consolidation-affaires": ConsolidationAffaires,
    "m10:audit-non-oubli": AuditNonOubli,
    "m10:kpis-memoire": KpisMemoire,
}
